"""Export a catalog release: the published tables plus a manifest.

Copies the published files from the step directories of REGISTRY/build/grch38
into OUT_DIR, in the flat layout a release has (copies,
not links, so a later rebuild can't change a release) and writes
OUT_DIR/catalog.json: the
version, the date, and for every file its size, sha256 and role. Also writes
OUT_DIR/README.md, the dataset card, from pipeline/catalog_card.md with the
release's version and counts filled in. Pipeline
intermediates stay behind. OUT_DIR is what gets hosted; a client opens it by
URL (`Catalog("https://.../catalog/")`) or by path. A release is never
overwritten: OUT_DIR must not exist. It is assembled in OUT_DIR.partial and
renamed into place when complete.

Usage: uv run python -I pipeline/70_export.py REGISTRY_DIR OUT_DIR VERSION [--assembly grch38]
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("version")
    ap.add_argument("--assembly", default=layout.ASSEMBLY)
    args = ap.parse_args()
    build, out, version = layout.build_dir(args.registry, args.assembly), args.out, args.version
    if out.exists():
        sys.exit(f"{out} exists: a release is never overwritten")
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
    files = {}
    for src, rel, role in entries:
        dst = staging / rel
        place(src, dst)
        files[rel] = {"bytes": dst.stat().st_size, "sha256": sha256(dst), "role": role}
        print(f"{rel}\t{dst.stat().st_size}", file=sys.stderr)
    manifest = {
        "name": "refbook", "format": FORMAT, "version": version,
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
