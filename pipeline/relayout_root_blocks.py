"""Rewrite root_blocks.parquet in the current storage layout (refbook.blocks).

Same rows, new row groups, statistics and page index. Writes next to the file,
checks that every root has the same blocks (count, starts and a digest of its
bases), then moves the old file to root_blocks.v1.parquet and the new one in.

Usage: uv run python -I pipeline/relayout_root_blocks.py REGISTRY_DIR
"""

import hashlib
import sys
from pathlib import Path

import pyarrow.parquet as pq

from refbook import blocks


def fingerprint(f: pq.ParquetFile, groups: list[int]) -> tuple[int, str]:
    t = f.read_row_groups(groups, columns=["start", "bases"])
    h = hashlib.md5()
    rows = sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist()))
    for s, b in rows:
        h.update(f"{s}:".encode() + b.encode())
    return len(rows), h.hexdigest()


def main() -> None:
    build = Path(sys.argv[1]) / "build" / "grch38"
    old_path, new_path = build / "root_blocks.parquet", build / "root_blocks.new.parquet"
    old = pq.ParquetFile(old_path)
    old_groups = blocks.row_groups_by_root(old)
    w = blocks.writer(new_path, old.schema_arrow)
    for root, groups in old_groups.items():
        t = old.read_row_groups(groups).sort_by("start")
        blocks.write_root(w, t)
    w.close()
    new = pq.ParquetFile(new_path)
    new_groups = blocks.row_groups_by_root(new)
    if set(new_groups) != set(old_groups):
        sys.exit("roots differ between old and new files")
    for root in old_groups:
        if fingerprint(old, old_groups[root]) != fingerprint(new, new_groups[root]):
            sys.exit(f"{root}: blocks differ after re-layout")
    old_path.rename(build / "root_blocks.v1.parquet")
    new_path.rename(old_path)
    print(f"re-laid out {len(old_groups)} roots: {old.metadata.num_row_groups} -> "
          f"{new.metadata.num_row_groups} row groups; old file kept as root_blocks.v1.parquet",
          file=sys.stderr)


if __name__ == "__main__":
    main()
