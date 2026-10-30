"""Experiment: how the root_blocks Parquet layout affects small region fetches.

Rewrites root_blocks.parquet in four layouts (same rows, same 64 kb blocks)
into REGISTRY/build/experiments/, then runs one fixed query set against each
with pyarrow, DuckDB and Polars:

  A  current: one row group per root, no page index
  B  one row group per root, page index, ~1 block per page
  C  row groups of 128 blocks (~8 MB uncompressed), page index
  D  row groups of 128 blocks, no page index

Queries: 200 random 1 kb regions and 20 random 1 Mb regions (seeded, placed in
proportion to root length). Each reads the blocks overlapping the region. For
each layout and engine it reports wall time and the bytes and read calls the
process asked the OS for (/proc/self/io rchar and syscr), which is what an HTTP
range-reading client would fetch. Times are with a warm page cache on NFS.

Usage: uv run --with duckdb --with polars python -I experiments/root_blocks_layout.py REGISTRY_DIR

Results (2026-10-29/30; pyarrow 26, DuckDB 2.0.0, Polars 2.1, DataFusion 55):

- Layout A (one row group per root, default statistics) reads 39-58 MB per
  1 kb fetch, and its footer is 9.1 MB. Min/max statistics on the 64 kb
  `bases` strings account for about 8 MB of that.
- Small row groups help every engine. With statistics only on root_id/start,
  reading the one row group directly with the footer cached costs:
    rg 128 blocks: 2.04 MB/query, footer 0.96 MB
    rg  32 blocks: 0.52 MB/query, footer 1.27 MB
    rg  16 blocks: 0.27 MB/query, footer 1.69 MB
- The page index: layouts B and C here show no gain, but that test was
  flawed. Pages limited by bytes (data_page_size) left the small `start`
  column, the one filtered on, with a single page per chunk, so there was
  nothing to prune. With max_rows_per_page=1, DataFusion prunes to one page:
  0.54 MB per query on a one-row-group chr1 (mostly the page index itself),
  and 18 kB per query on the full genome with 32-block row groups plus the
  page index (vs 515 kB without it). The file grows ~3%. DuckDB 2.0.0 does not
  use the page index; duckdb/duckdb#27326 (merged 2026-10-29) adds it. pyarrow
  and Polars prune by row group only.
- Adopted (src/ref_registry/blocks.py): 32-block row groups that never span
  roots, statistics on root_id/start only, page index with 1 row per page.
"""

import random
import statistics
import sys
import time
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

BLOCK = 65536


def io_counters() -> tuple[int, int]:
    vals = dict(line.split(": ") for line in Path("/proc/self/io").read_text().splitlines())
    return int(vals["rchar"]), int(vals["syscr"])


def write_variants(src: Path, out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    f = pq.ParquetFile(src)
    variants = {"A": src}
    specs = {"B": dict(per_root=True, page_index=True), "C": dict(per_root=False, page_index=True),
             "D": dict(per_root=False, page_index=False)}
    for name, spec in specs.items():
        path = out / f"root_blocks_{name}.parquet"
        variants[name] = path
        if path.exists():
            continue
        w = pq.ParquetWriter(path, f.schema_arrow, compression="zstd", use_dictionary=["root_id"],
                             write_page_index=spec["page_index"], data_page_size=BLOCK)
        for i in range(f.metadata.num_row_groups):
            t = f.read_row_group(i)
            w.write_table(t, row_group_size=t.num_rows if spec["per_root"] else 128)
        w.close()
    return variants


def queries(roots: list[tuple[str, int]], n: int, width: int, rng: random.Random):
    total = sum(L for _, L in roots)
    out = []
    while len(out) < n:
        x = rng.randrange(total)
        for r, L in roots:
            if x < L:
                if L > width:
                    s = min(x, L - width)
                    out.append((r, s, s + width))
                break
            x -= L
    return out


def block_range(s: int, e: int) -> tuple[int, int]:
    return (s // BLOCK) * BLOCK, e


def run_pyarrow(path: Path, qs):
    d = ds.dataset(path)
    for r, s, e in qs:
        lo, hi = block_range(s, e)
        d.to_table(columns=["start", "bases"],
                   filter=(pc.field("root_id") == r) & (pc.field("start") >= lo) & (pc.field("start") < hi))


def run_duckdb(path: Path, qs):
    import duckdb
    con = duckdb.connect()
    for r, s, e in qs:
        lo, hi = block_range(s, e)
        con.execute(f"SELECT start, bases FROM read_parquet('{path}') "
                    "WHERE root_id = ? AND start >= ? AND start < ?", [r, lo, hi]).fetchall()


def run_polars(path: Path, qs):
    import polars as pl
    for r, s, e in qs:
        lo, hi = block_range(s, e)
        (pl.scan_parquet(path).filter((pl.col("root_id") == r) & (pl.col("start") >= lo) & (pl.col("start") < hi))
         .select("start", "bases").collect())


def measure(fn, path: Path, qs) -> dict:
    times, bytes_, calls = [], [], []
    for q in qs:
        b0, c0 = io_counters()
        t0 = time.perf_counter()
        fn(path, [q])
        times.append(time.perf_counter() - t0)
        b1, c1 = io_counters()
        bytes_.append(b1 - b0)
        calls.append(c1 - c0)
    return {"median_ms": 1000 * statistics.median(times), "p90_ms": 1000 * sorted(times)[int(0.9 * len(times))],
            "mean_MB": statistics.mean(bytes_) / 1e6, "mean_reads": statistics.mean(calls)}


def main() -> None:
    registry = Path(sys.argv[1])
    build = registry / "build" / "grch38"
    variants = write_variants(build / "root_blocks.parquet", registry / "build" / "experiments")
    roots = [(r["root_id"], r["length"]) for r in
             pq.read_table(build / "roots.parquet", columns=["root_id", "length"]).to_pylist()]
    rng = random.Random(20261029)
    workloads = {"1 kb x200": queries(roots, 200, 1_000, rng), "1 Mb x20": queries(roots, 20, 1_000_000, rng)}
    engines = {"pyarrow": run_pyarrow, "duckdb": run_duckdb, "polars": run_polars}
    print("layout  size_MB  row_groups  page_index")
    for name, path in variants.items():
        md = pq.ParquetFile(path).metadata
        print(f"{name:6}  {path.stat().st_size / 1e6:7.0f}  {md.num_row_groups:10}  "
              f"{md.row_group(0).column(2).has_offset_index}")
    print("\nworkload    engine   layout  median_ms  p90_ms  mean_MB_read  mean_read_calls")
    for wname, qs in workloads.items():
        for ename, fn in engines.items():
            for name, path in variants.items():
                fn(path, qs[:3])  # warm up: footers, page cache
                m = measure(fn, path, qs)
                print(f"{wname:10}  {ename:7}  {name:6}  {m['median_ms']:9.1f}  {m['p90_ms']:6.1f}  "
                      f"{m['mean_MB']:12.2f}  {m['mean_reads']:15.1f}", flush=True)


if __name__ == "__main__":
    main()
