"""Export a catalog release: the published tables plus a manifest.

Copies (hard-links where possible) the published files from
REGISTRY/build/grch38 into OUT_DIR and writes OUT_DIR/catalog.json: the
version, the date, and for every file its size, sha256 and role. Also writes
OUT_DIR/README.md, the dataset card, from pipeline/catalog_card.md with the
release's version and counts filled in. Pipeline
intermediates stay behind. OUT_DIR is what gets hosted; a client opens it by
URL (`Catalog("https://.../catalog/")`) or by path.

Usage: uv run python -I pipeline/export_catalog.py REGISTRY_DIR OUT_DIR VERSION
"""

import datetime
import hashlib
import json
import os
import shutil
from collections import defaultdict
import sys
from pathlib import Path

# Published files and their roles; directories export every file they contain.
FILES = {
    "roots.parquet": "roots", "roots_external.parquet": "roots",
    "root_blocks.parquet": "bases",
    "assembly_members.parquet": "assemblies", "aliases.parquet": "aliases",
    "layer_agp.parquet": "layer", "layer_regions.parquet": "layer",
    "layer_placements.parquet": "layer", "layer_hardmask_grc.parquet": "layer",
    "layer_iupac.parquet": "layer", "layer_n_runs.parquet": "layer",
    "layer_softmask_ncbi.parquet": "layer",
    "recipes.parquet": "flavors", "flavor_sequences.parquet": "flavors",
    "family_tree.json": "flavors", "seqcol": "seqcol",
}
EVIDENCE = {"observed": "observed", "verify_roots.tsv": "verify_roots.tsv",
            "check_gaps.tsv": "check_gaps.tsv"}   # build path -> path under evidence/


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def place(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def publisher_and_label(flavor: str) -> tuple[str, str]:
    """For the dataset card: who published a flavor, and a short name for its file."""
    import re
    if flavor.startswith("GRCh38_"):
        return "GRC (NCBI analysis sets)", flavor[7:].replace("_analysis_set", "").replace("_plus_", " + ")
    if flavor.startswith("UCSC_"):
        return "UCSC", flavor[5:]
    if m := re.fullmatch(r"(Ensembl|GENCODE)(\d+)_(.+)", flavor):
        return f"{m[1]} {m[2]}", m[3]
    if flavor.startswith(("Broad_", "1000G_")):
        return "Broad / 1000 Genomes", flavor.split("_", 1)[1]
    if flavor.startswith("iGenomes_"):
        return "Illumina iGenomes", flavor[9:].replace("_", "/", 1)
    return "Other", flavor


def card(build: Path, version: str) -> str:
    import pyarrow.parquet as pq
    recipes = pq.read_table(build / "recipes.parquet", columns=["flavor", "published", "seqcol_digest"]).to_pylist()
    by_pub = defaultdict(list)
    for r in recipes:
        pub, label = publisher_and_label(r["flavor"])
        by_pub[pub].append(label)
    rows = ["| Publisher | Files reproduced |", "| --- | --- |"]
    rows += [f"| {pub} | {', '.join(sorted(labels))} |" for pub, labels in sorted(by_pub.items())]
    members = pq.read_table(build / "assembly_members.parquet",
                            columns=["assembly_name", "genbank_accession"]).to_pylist()
    grch38 = {m["genbank_accession"] for m in members if m["assembly_name"].startswith("GRCh38")}
    decoys = {m["genbank_accession"] for m in members if m["assembly_name"] == "hs38d1"}
    template = (Path(__file__).parent / "catalog_card.md").read_text()
    return template.format(version=version, n_flavors=len(recipes),
                           n_sets=len({r["seqcol_digest"] for r in recipes}),
                           flavor_table="\n".join(rows),
                           n_roots=pq.read_metadata(build / "roots.parquet").num_rows,
                           n_grch38=len(grch38), n_decoys=len(decoys))


def main() -> None:
    build, out, version = Path(sys.argv[1]) / "build" / "grch38", Path(sys.argv[2]), sys.argv[3]
    entries = []
    for name, role in FILES.items():
        entries += [(p, p.relative_to(build).as_posix(), role)
                    for p in ([build / name] if (build / name).is_file() else sorted((build / name).glob("*")))]
    for name, rel in EVIDENCE.items():
        src = build / name
        entries += [(p, f"evidence/{rel}" + (f"/{p.name}" if src.is_dir() else ""), "evidence")
                    for p in ([src] if src.is_file() else sorted(src.glob("*")))]
    files = {}
    for src, rel, role in entries:
        place(src, out / rel)
        files[rel] = {"bytes": src.stat().st_size, "sha256": sha256(src), "role": role}
        print(f"{rel}\t{src.stat().st_size}", file=sys.stderr)
    manifest = {
        "name": "refbook", "version": version,
        "created": datetime.date.today().isoformat(),
        "description": "GRCh38 roots, layers and reproduced flavor recipes",
        "files": files,
    }
    (out / "catalog.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "README.md").write_text(card(build, version))
    print(f"{len(files)} files, {sum(f['bytes'] for f in files.values()) / 1e6:.0f} MB -> {out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
