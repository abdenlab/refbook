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
"""

import json
from collections import defaultdict

import pyarrow as pa
import pyarrow.parquet as pq

from ref_registry.catalog import Catalog
from ref_registry.materialize import IUPAC_TO_N, Bases

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
          clip: bool = False, bases: Bases | None = None) -> pa.Table:
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
        layer = pq.read_table(cat.path / f"layer_{m['layer']}.parquet", columns=["root_id", "start", "end"])
        for r, s, e in zip(*(layer[c].to_pylist() for c in ("root_id", "start", "end"))):
            spans[r].append((s, e))
    to_n = recipe.get("alphabet", {}).get("iupac") == "N"
    bases = bases or Bases(cat)

    out = [None] * table.num_rows
    # Visit intervals in genome order so row groups are read once; write back in input order.
    for i in sorted(range(table.num_rows), key=lambda i: (seqs[names[i]].root_id, lo[i])):
        root = seqs[names[i]].root_id
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
    meta.update({b"ref_registry:flavor": flavor.encode(),
                 b"ref_registry:seqcol_digest": cat.recipes[flavor]["seqcol_digest"].encode(),
                 ARROW_KEY: b"true" if zb else b"false"})
    result = table.append_column(pa.field("sequence", pa.large_string(), nullable=False),
                                 pa.array(out, pa.large_string()))
    return result.replace_schema_metadata(meta)
