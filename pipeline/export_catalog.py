"""Export a catalog release: the published tables plus a manifest.

Copies (hard-links where possible) the published files from
REGISTRY/build/grch38 into OUT_DIR and writes OUT_DIR/catalog.json: the
version, the date, and for every file its size, sha256 and role. Pipeline
intermediates stay behind. OUT_DIR is what gets hosted; a client opens it by
URL (`Catalog("https://.../catalog/")`) or by path.

Usage: uv run python -I pipeline/export_catalog.py REGISTRY_DIR OUT_DIR VERSION
"""

import datetime
import hashlib
import json
import os
import shutil
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
        "name": "ref-registry", "version": version,
        "created": datetime.date.today().isoformat(),
        "description": "GRCh38 roots, layers and reproduced flavor recipes",
        "files": files,
    }
    (out / "catalog.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(files)} files, {sum(f['bytes'] for f in files.values()) / 1e6:.0f} MB -> {out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
