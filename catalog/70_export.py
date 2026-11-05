"""Export a catalog release: the published tables plus a manifest.

Copies the published files from the step directories of build/grch38
into OUT_DIR, in the flat layout a release has (copies,
not links, so a later rebuild can't change a release) and writes
OUT_DIR/catalog.json: the
version, the date, and for every file its size, sha256 and role. Also writes
OUT_DIR/README.md, the dataset card, from catalog/catalog_card.md with the
release's version and counts filled in. Pipeline
intermediates stay behind. OUT_DIR is what gets hosted; a client opens it by
URL (`Catalog("https://.../catalog/")`) or by path. A release is never
overwritten: OUT_DIR must not exist. It is assembled in OUT_DIR.partial and
renamed into place when complete.

The export is gated on the checks (60-62): each must have recorded a pass, and
the tables it read must still have the hashes it recorded, so a release ships
only files that passed every check as they are. The root check must have
consulted ENA; --development accepts a run with --skip-ena, for exports that
are not releases. Every step that read raw/ must have read it through the
current locks (catalog/assemblies/<assembly>/locks/). catalog.json records
each check's result and the hash of each lock, and the locks ship under
evidence/locks/.

Usage: uv run python -I catalog/70_export.py OUT_DIR VERSION [--development] [--assembly A] [--raw DIR] [--build DIR]
"""

import argparse
import datetime
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

# Published files and their roles; directories export every file they contain.
FILES = {
    "roots.parquet": "roots", "roots_external.parquet": "roots",
    "root_blocks.parquet": "bases",
    "assembly_members.parquet": "assemblies", "aliases.parquet": "aliases",
    "layer_agp.parquet": "layer", "layer_regions.parquet": "layer",
    "layer_placements.parquet": "layer", "layer_hardmask_grc.parquet": "layer",
    "layer_iupac.parquet": "layer", "layer_n_runs.parquet": "layer",
    "layer_softmask_ncbi.parquet": "layer",
    "sequences.parquet": "sequences", "derivations.parquet": "sequences",
    "flavors.parquet": "flavors", "manifests.parquet": "flavors",
    "targets.parquet": "targets", "target_sequences.parquet": "targets",
    "collections": "collections",
}
FORMAT = layout.CATALOG_FORMAT
EVIDENCE = ["observed", "verify_roots.tsv", "check_gaps.tsv",   # shipped under evidence/
            "check_gaps.json", "check_roots.json", "check_materialize.json"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def place(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def card(build: Path, version: str) -> str:
    import pyarrow.parquet as pq
    flavors = pq.read_table(layout.path(build, "flavors.parquet"), columns=["flavor"]).to_pylist()
    targets = pq.read_table(layout.path(build, "targets.parquet"), columns=["flavor", "publisher", "alias"]).to_pylist()
    by_flavor = defaultdict(list)
    for t in targets:
        by_flavor[t["flavor"]].append(f"{t['publisher']} `{t['alias']}`")
    rows = ["| Flavor | Published as |", "| --- | --- |"]
    rows += [f"| `{f}` | {'; '.join(sorted(ts))} |" for f, ts in sorted(by_flavor.items())]
    members = pq.read_table(layout.path(build, "assembly_members.parquet"),
                            columns=["assembly_name", "genbank_accession"]).to_pylist()
    grch38 = {m["genbank_accession"] for m in members if m["assembly_name"].startswith("GRCh38")}
    decoys = {m["genbank_accession"] for m in members if m["assembly_name"] == "hs38d1"}
    template = (Path(__file__).parent / "catalog_card.md").read_text()
    return template.format(version=version, n_flavors=len(targets), n_sets=len(flavors),
                           flavor_table="\n".join(rows),
                           n_roots=pq.read_metadata(layout.path(build, "roots.parquet")).num_rows,
                           n_grch38=len(grch38), n_decoys=len(decoys))


CHECKS = ["check_gaps", "check_roots", "check_materialize"]


def gate(build: Path, development: bool = False, assembly: str = layout.ASSEMBLY) -> tuple[dict, list[str]]:
    """Each check's recorded result, and why the build can't be exported, if it can't."""
    results, problems = {}, []
    for check in CHECKS:
        try:
            r = json.loads(layout.path(build, f"{check}.json").read_text())
        except FileNotFoundError:
            problems.append(f"{check}: has not run")
            continue
        results[check] = r
        if not r["passed"]:
            problems.append(f"{check}: failed")
        for name, digest in r["inputs"].items():
            try:
                now = layout.sha256(layout.path(build, name))
            except FileNotFoundError:
                now = None
            if now != digest:
                problems.append(f"{check}: {name} has changed since the check ran; rerun it")
        if r["details"].get("ena") == "skipped" and not development:
            problems.append(f"{check}: ran without ENA (--skip-ena); rerun it, or export --development")
    # Every step that read raw/ must have read it through the current locks.
    locks = {lock.name: layout.sha256(lock) for lock in (layout.inputs_lock(assembly), layout.targets_lock(assembly))}
    for d in layout.step_dirs(build):
        for f in d.glob("*.inputs.json"):
            for name, digest in json.loads(f.read_text()).items():
                if locks.get(name) != digest:
                    problems.append(f"{d.name}: built from another {name}; rerun it")
    return results, problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("version")
    ap.add_argument("--development", action="store_true",
                    help="accept a root check run without ENA (not for releases)")
    args = layout.arguments(ap)
    build, out, version = args.build, args.out, args.version
    if out.exists():
        sys.exit(f"{out} exists: a release is never overwritten")
    results, problems = gate(build, args.development, args.assembly)
    if problems:
        sys.exit("not exported:\n  " + "\n  ".join(problems))
    staging = out.with_name(out.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)  # left by an interrupted export
    entries = []
    for name, role in FILES.items():
        src = layout.path(build, name)
        entries += [(p, f"{name}/{p.name}" if src.is_dir() else name, role)
                    for p in ([src] if src.is_file() else sorted(src.glob("*")))]
    for name in EVIDENCE:
        src = layout.path(build, name)
        entries += [(p, f"evidence/{name}" + (f"/{p.name}" if src.is_dir() else ""), "evidence")
                    for p in ([src] if src.is_file() else sorted(src.glob("*")))]
    for lock in (layout.inputs_lock(args.assembly), layout.targets_lock(args.assembly), layout.inputs_lock(args.assembly).with_name("checksum_exceptions.tsv")):
        entries.append((lock, f"evidence/locks/{lock.name}", "evidence"))
    files = {}
    for src, rel, role in entries:
        dst = staging / rel
        place(src, dst)
        files[rel] = {"bytes": dst.stat().st_size, "sha256": sha256(dst), "role": role}
        print(f"{rel}\t{dst.stat().st_size}", file=sys.stderr)
    manifest = {
        "name": "refbook", "format": FORMAT, "version": version,
        "locks": {lock.name: layout.sha256(lock) for lock in (layout.inputs_lock(args.assembly), layout.targets_lock(args.assembly))},
        "checks": {c: {"passed": r["passed"], **({"ena": r["details"]["ena"]} if "ena" in r["details"] else {})}
                   for c, r in results.items()},
        "created": datetime.date.today().isoformat(),
        "description": "GRCh38 roots, layers and reproduced flavor recipes",
        "files": files,
    }
    (staging / "catalog.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (staging / "README.md").write_text(card(build, version))
    staging.rename(out)
    print(f"{len(files)} files, {sum(f['bytes'] for f in files.values()) / 1e6:.0f} MB -> {out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
