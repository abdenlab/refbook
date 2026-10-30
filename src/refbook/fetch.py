"""Fetch the bases of a flavor at a table of intervals.

`fetch(cat, flavor, intervals)` takes an interval table and returns it as an
Arrow table with one more column, `sequence`: the flavor's bases at each
interval, with the recipe's hard masks and IUPAC -> N applied, as
`materialize` would give them. Bases are uppercase; soft-masking is a layer.

Conventions:
- Columns: `chrom`, `start`, `end` by default (polars-bio's names), renamable;
  an optional strand column. `chrom` is a name in the flavor; an unknown name
  is an error.
- Coordinates: 0-based half-open by default. An explicit `zero_based` wins;
  otherwise polars-bio's coordinate-system metadata is honored when present
  (Polars `config_meta`, pandas `attrs`, Arrow schema metadata
  `bio.coordinate_system_zero_based`); an explicit value that contradicts the
  metadata is an error. 1-based closed intervals are converted, and the output
  keeps the input's coordinates as given.
- Bounds: an interval outside its sequence (start < 0, end > length,
  start > end) is an error, unless `clip=True`, which clips to the sequence.
- Strand: `-` gives the reverse complement (IUPAC codes complemented too);
  `+`, `.` and null give the forward strand; anything else is an error.

Output schema metadata records the flavor and its seqcol digest, so a slice
identifies its reference by content.

Engines (`engine=`): "datafusion" reads only the needed blocks with
DataFusion (the `datafusion` extra, the engine under polars-bio). It issues one
semi-join with filter pushdown, or, when every sequence needs at most 20
blocks, per-sequence `IN` lists that the page index prunes to single pages.
"pyarrow" reads whole row groups (remotely, prefetched in parallel).
"auto" (the default) uses DataFusion for a local catalog if it is installed,
and pyarrow for a remote one. DataFusion's HTTP store re-follows a host's
redirect on every request and cannot send a token or keep a signed URL's
query string, so on hosts like Hugging Face it pays a redirect per request and
gets rate-limited (HTTP 429) on dense queries; plain http:// is refused.
"""

import json
from collections import defaultdict

import pyarrow as pa
import pyarrow.parquet as pq

from refbook.blocks import BLOCK_SIZE
from refbook.catalog import Catalog
from refbook.materialize import IUPAC_TO_N, Bases

COMPLEMENT = bytes.maketrans(b"ACGTRYKMBDHVSWN", b"TGCAYRMKVHDBSWN")
ARROW_KEY = b"bio.coordinate_system_zero_based"


def _to_arrow(intervals) -> tuple[pa.Table, bool | None]:
    """The table as Arrow, and its polars-bio coordinate-system flag if it has one."""
    flag = None
    meta = getattr(intervals, "config_meta", None)          # Polars, via polars-config-meta
    if meta is not None:
        flag = meta.get_metadata().get("coordinate_system_zero_based")
    elif isinstance(getattr(intervals, "attrs", None), dict):  # pandas
        flag = intervals.attrs.get("coordinate_system_zero_based")
    if hasattr(intervals, "collect") and not isinstance(intervals, pa.Table):
        intervals = intervals.collect()                        # Polars LazyFrame
    if isinstance(intervals, pa.RecordBatch):
        intervals = pa.Table.from_batches([intervals])
    if not isinstance(intervals, pa.Table):
        if hasattr(intervals, "to_arrow"):
            intervals = intervals.to_arrow()
        else:
            intervals = pa.Table.from_pandas(intervals, preserve_index=False)
    md = intervals.schema.metadata or {}
    if flag is None and ARROW_KEY in md:
        flag = md[ARROW_KEY].decode().lower() == "true"
    return intervals, flag


def fetch(cat: Catalog, flavor: str, intervals, *, chrom: str = "chrom", start: str = "start",
          end: str = "end", strand: str | None = None, zero_based: bool | None = None,
          clip: bool = False, engine: str = "auto", bases: Bases | None = None,
          reader: "DataFusionBlocks | None" = None) -> pa.Table:
    if flavor not in cat.flavors:
        raise KeyError(f"{flavor}: not a reproduced flavor")
    table, flag = _to_arrow(intervals)
    if zero_based is not None and flag is not None and zero_based != flag:
        raise ValueError(f"zero_based={zero_based}, but the intervals say "
                         f"coordinate_system_zero_based={flag}")
    zb = zero_based if zero_based is not None else (flag if flag is not None else True)

    seqs = {s.name: s for s in cat.flavors[flavor]}
    names = table.column(chrom).to_pylist()
    starts = table.column(start).to_pylist()
    ends = table.column(end).to_pylist()
    strands = table.column(strand).to_pylist() if strand else [None] * table.num_rows
    unknown = sorted({n for n in names if n not in seqs})
    if unknown:
        raise KeyError(f"{flavor} has no sequence named {', '.join(unknown[:5])}"
                       f"{' ...' if len(unknown) > 5 else ''}")

    # 0-based half-open bounds, checked or clipped.
    lo = [s if zb else s - 1 for s in starts]
    hi = list(ends)
    bad = []
    for i, n in enumerate(names):
        length = seqs[n].length
        if clip:
            lo[i], hi[i] = max(0, min(lo[i], length)), max(0, min(hi[i], length))
            hi[i] = max(hi[i], lo[i])
        elif not 0 <= lo[i] <= hi[i] <= length:
            bad.append(f"{n}:{starts[i]}-{ends[i]} (length {length:,})")
    if bad:
        raise ValueError(f"{len(bad)} intervals outside their sequence, e.g. {bad[0]}; "
                         "pass clip=True to clip them")
    for x in strands:
        if x not in (None, "+", "-", "."):
            raise ValueError(f"strand must be +, -, . or null, not {x!r}")

    recipe = json.loads(cat.recipes[flavor]["recipe"])
    spans = defaultdict(list)
    for m in recipe.get("mask", []):
        layer = pq.read_table(cat.file(f"layer_{m['layer']}.parquet"), columns=["root_id", "start", "end"])
        for r, s, e in zip(*(layer[c].to_pylist() for c in ("root_id", "start", "end"))):
            spans[r].append((s, e))
    to_n = recipe.get("alphabet", {}).get("iupac") == "N"
    bases = bases or Bases(cat)
    roots = [seqs[n].root_id for n in names]
    if engine == "auto":
        engine = "datafusion" if reader is not None or (_have_datafusion() and not cat.remote) else "pyarrow"
    blocks = None
    if engine == "datafusion":
        need = {(r, k * BLOCK_SIZE) for r, a, z in zip(roots, lo, hi) if r in bases.row_groups and z > a
                for k in range(a // BLOCK_SIZE, (z - 1) // BLOCK_SIZE + 1)}
        blocks = (reader or DataFusionBlocks(cat)).get(sorted(need))
    elif engine != "pyarrow":
        raise ValueError(f"engine must be auto, datafusion or pyarrow, not {engine!r}")

    out = [None] * table.num_rows
    # Visit intervals in genome order so row groups are read once; write back in input order.
    order = sorted(range(table.num_rows), key=lambda i: (roots[i], lo[i]))
    if blocks is None and bases.http is not None:
        # Over HTTP: prefetch the row groups in visit order, 64 at a time, concurrently.
        needed = []
        for i in order:
            if roots[i] in bases.row_groups and hi[i] > lo[i]:
                needed += [g for g in bases.row_groups_for(roots[i], lo[i], hi[i]) if g not in needed[-8:]]
        needed = list(dict.fromkeys(needed))
        batches = {g: k // 64 for k, g in enumerate(needed)}
        fetched = None
    for i in order:
        root = roots[i]
        if blocks is None and bases.http is not None and root in bases.row_groups and hi[i] > lo[i]:
            batch = batches[bases.row_groups_for(root, lo[i], hi[i])[0]]
            if batch != fetched:
                bases._cache.clear()
                bases.prefetch(needed[batch * 64:(batch + 1) * 64])
                fetched = batch
        if blocks is not None and root in bases.row_groups:
            b = bytearray(_from_blocks(blocks, root, lo[i], hi[i]))
        else:
            b = bytearray(bases.slice(root, lo[i], hi[i]))
        for s, e in spans.get(root, ()):
            if s < hi[i] and e > lo[i]:
                a, z = max(s, lo[i]) - lo[i], min(e, hi[i]) - lo[i]
                b[a:z] = b"N" * (z - a)
        b = bytes(b)
        if to_n:
            b = b.translate(IUPAC_TO_N)
        if strands[i] == "-":
            b = b.translate(COMPLEMENT)[::-1]
        out[i] = b.decode("ascii")

    meta = dict(table.schema.metadata or {})
    meta.update({b"refbook:flavor": flavor.encode(),
                 b"refbook:seqcol_digest": cat.recipes[flavor]["seqcol_digest"].encode(),
                 ARROW_KEY: b"true" if zb else b"false"})
    result = table.append_column(pa.field("sequence", pa.large_string(), nullable=False),
                                 pa.array(out, pa.large_string()))
    return result.replace_schema_metadata(meta)


def _have_datafusion() -> bool:
    try:
        import datafusion  # noqa: F401
    except ImportError:
        return False
    return True


def _from_blocks(blocks: dict, root: str, start: int, end: int) -> bytes:
    if end <= start:
        return b""
    first = start // BLOCK_SIZE * BLOCK_SIZE
    joined = "".join(blocks[(root, k)] for k in range(first, end, BLOCK_SIZE))
    return joined[start - first:end - first].encode("ascii")


class DataFusionBlocks:
    """Reads chosen (root_id, start) blocks from root_blocks.parquet with DataFusion.

    Few blocks per sequence: one query per sequence with an `IN` list, which
    the page index prunes to single pages (DataFusion only prunes `IN` lists of
    up to 20 values). Otherwise: one semi-join against the needed blocks, with
    filter pushdown so `bases` pages are decoded only for matching rows (the
    join's dynamic filter alone is just min/max bounds, which prune nothing).
    """

    MAX_IN_LIST = 20

    def __init__(self, cat: Catalog):
        import datafusion
        self._df = datafusion
        cfg = datafusion.SessionConfig({"datafusion.execution.parquet.pushdown_filters": "true"})
        self.ctx = datafusion.SessionContext(cfg)
        location = cat.blocks_location()
        if cat.remote and location.startswith("http://"):
            raise ValueError("DataFusion's HTTP object store requires https:// (datafusion-python "
                             "does not expose object_store's allow_http); use engine='pyarrow'")
        if cat.remote:
            from urllib.parse import urlparse
            from datafusion.object_store import Http
            u = urlparse(location)
            self.ctx.register_object_store(f"{u.scheme}://", Http(f"{u.scheme}://{u.netloc}"), u.netloc)
        self.ctx.register_parquet("blocks", location)
        self._n = 0

    def get(self, need: list[tuple[str, int]]) -> dict[tuple[str, int], str]:
        if not need:
            return {}
        by_root = defaultdict(list)
        for r, s in need:
            by_root[r].append(s)
        tables = []
        if max(len(v) for v in by_root.values()) <= self.MAX_IN_LIST:
            for r, starts in by_root.items():
                tables.append(self.ctx.sql(
                    f"SELECT root_id, start, bases FROM blocks WHERE root_id = '{r}' "
                    f"AND start IN ({', '.join(map(str, starts))})").to_arrow_table())
        else:
            self._n += 1
            name = f"need_{self._n}"
            self.ctx.register_record_batches(name, [[pa.record_batch(
                {"root_id": [r for r, _ in need], "start": [s for _, s in need]})]])
            tables.append(self.ctx.sql(
                f"SELECT b.root_id, b.start, b.bases FROM blocks b JOIN {name} n "
                "ON b.root_id = n.root_id AND b.start = n.start").to_arrow_table())
            self.ctx.deregister_table(name)
        out = {}
        for t in tables:
            out.update(zip(zip(t["root_id"].to_pylist(), t["start"].to_pylist()), t["bases"].to_pylist()))
        missing = set(need) - set(out)
        if missing:
            raise KeyError(f"root_blocks has no block {sorted(missing)[0]}")
        return out
