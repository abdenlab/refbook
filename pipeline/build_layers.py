"""Build the GRCh38 annotation layers from the raw NCBI downloads.

Reads REGISTRY/raw (see fetch_grch38.sh) and REGISTRY/build/grch38/roots.parquet,
and writes Parquet to REGISTRY/build/grch38:

- layer_agp.parquet   one row per AGP part of each root's component-level AGP
                      (*.comp.agp.gz, *.scaf.agp.gz); start/end are 0-based
                      half-open on the root, component_start/end likewise on
                      the component. Gap rows have null component columns and
                      vice versa.

A root's AGP is the same in every release (checked by check_gaps.py and again
here), so each root appears once.

Usage: uv run --with pyarrow python build_layers.py REGISTRY_DIR
"""

import argparse
import gzip
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

NCBI = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405"


def releases(raw: Path) -> list[Path]:
    dirs = sorted(
        (raw / NCBI).glob("GCA_000001405.*_GRCh38*"),
        key=lambda p: int(p.name.split("_")[1].split(".")[1]),
    )
    return [d for d in dirs if 15 <= int(d.name.split("_")[1].split(".")[1]) <= 29]


def agp_files(release: Path) -> list[Path]:
    return sorted(p for p in release.glob("*_assembly_structure/**/AGP/*.agp.gz")
                  if p.name.endswith((".comp.agp.gz", ".scaf.agp.gz")))


def read_agp(path: Path) -> dict[str, list[tuple]]:
    """object -> AGP rows, as tuples of the (string) columns after `object`."""
    objs = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            objs.setdefault(cols[0], []).append(tuple(cols[1:]))
    return objs


def build_agp(raw: Path, roots: set[str]) -> pa.Table:
    agp, source = {}, {}
    for d in releases(raw):
        for path in agp_files(d):
            for obj, rows in read_agp(path).items():
                if obj not in roots:
                    continue  # placed scaffolds are AGP objects but not roots
                if obj in agp and agp[obj] != rows:
                    sys.exit(f"{obj}: AGP in {path} differs from {source[obj]}")
                if obj not in agp:
                    agp[obj], source[obj] = rows, path
    if roots - set(agp):
        sys.exit(f"no AGP for: {sorted(roots - set(agp))}")

    cols = {k: [] for k in (
        "root_id", "part_number", "start", "end", "component_type",
        "component_id", "component_start", "component_end", "orientation",
        "gap_length", "gap_type", "linkage", "linkage_evidence", "source",
    )}
    raw_prefix = len(str(raw)) + 1
    for obj in sorted(agp):
        url = "https://" + str(source[obj])[raw_prefix:]
        for r in agp[obj]:
            gap = r[3] in ("N", "U")
            cols["root_id"].append(obj)
            cols["part_number"].append(int(r[2]))
            cols["start"].append(int(r[0]) - 1)
            cols["end"].append(int(r[1]))
            cols["component_type"].append(r[3])
            cols["component_id"].append(None if gap else r[4])
            cols["component_start"].append(None if gap else int(r[5]) - 1)
            cols["component_end"].append(None if gap else int(r[6]))
            cols["orientation"].append(None if gap else r[7])
            cols["gap_length"].append(int(r[4]) if gap else None)
            cols["gap_type"].append(r[5] if gap else None)
            cols["linkage"].append((r[6] == "yes") if gap else None)
            cols["linkage_evidence"].append(
                (None if r[7] == "na" else r[7]) if gap else None)
            cols["source"].append(url)
    return pa.table(cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    args = ap.parse_args()
    raw = args.registry / "raw"
    out = args.registry / "build" / "grch38"
    roots = set(pq.read_table(out / "roots.parquet", columns=["root_id"])
                ["root_id"].to_pylist())

    agp = build_agp(raw, roots)
    pq.write_table(agp, out / "layer_agp.parquet", compression="zstd")
    print(f"layer_agp: {agp.num_rows} parts on {len(roots)} roots", file=sys.stderr)


if __name__ == "__main__":
    main()
