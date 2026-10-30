"""Storage layout of root_blocks.parquet: the bases of the hosted roots.

Rows are (root_id, start, bases): fixed 64 kb blocks of uppercase bases, IUPAC
codes kept, sorted by root and start. The layout is tuned for fetching small
regions, locally or over HTTP range reads (measured in
experiments/root_blocks_layout.py):

- row groups of 32 blocks (~2 MB uncompressed) that never span roots, so every
  engine can skip to the right ~0.5 MB with row-group statistics;
- a page index with one row per page, so engines that use it (DataFusion, and
  so polars-bio; DuckDB once duckdb/duckdb#27326 is released) fetch about one
  compressed block. Pages must be limited by rows, not bytes: pruning happens
  on the filter column's pages, and `start` is tiny;
- statistics only on root_id and start. Min/max of 64 kb strings made the
  footer 9 MB; without them it is ~1.5 MB.
"""

import pyarrow as pa
import pyarrow.parquet as pq

BLOCK_SIZE = 65536
ROW_GROUP_BLOCKS = 32
SCHEMA = pa.schema([("root_id", pa.string()), ("start", pa.int64()), ("bases", pa.string())])


def writer(path, schema: pa.Schema = SCHEMA) -> pq.ParquetWriter:
    return pq.ParquetWriter(path, schema, compression="zstd", use_dictionary=["root_id"],
                            write_statistics=["root_id", "start"], write_page_index=True,
                            max_rows_per_page=1)


def write_root(w: pq.ParquetWriter, table: pa.Table) -> None:
    """Write one root's blocks (sorted by start) as its own row groups."""
    w.write_table(table, row_group_size=ROW_GROUP_BLOCKS)


def row_groups_by_root(f: pq.ParquetFile) -> dict[str, list[int]]:
    """root_id -> its row group indices, in start order."""
    md = f.metadata
    out: dict[str, list[tuple[int, int]]] = {}
    for i in range(md.num_row_groups):
        rid = md.row_group(i).column(0).statistics
        if rid.min != rid.max:
            raise ValueError(f"row group {i} spans roots {rid.min}..{rid.max}")
        out.setdefault(rid.min, []).append((md.row_group(i).column(1).statistics.min, i))
    return {r: [i for _, i in sorted(v)] for r, v in out.items()}
