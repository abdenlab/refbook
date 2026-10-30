"""Record what a published SAM sequence dictionary (.dict) claims, per sequence.

The weaker sibling of observe_fasta.py, for flavors whose FASTA we have not
downloaded: same output schema, but only position, name, length and the
publisher's M5 are known. md5 is the M5 as published (not a digest we computed);
the fields a .dict lacks (sha512t24u, n_N, n_lower, line_width, defline_ac)
are null, and run_recipes.py skips them.

Usage: uv run python -I pipeline/observe_dict.py FILE.dict OUT.parquet
"""

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    rows = []
    for line in src.read_text().splitlines():
        if not line.startswith("@SQ"):
            continue
        tags = dict(f.split(":", 1) for f in line.split("\t")[1:])
        rows.append({
            "position": len(rows), "name": tags["SN"], "length": int(tags["LN"]),
            "md5": tags.get("M5"), "sha512t24u": None, "n_N": None, "n_lower": None,
            "line_width": None, "defline_ac": None, "defline_m5": tags.get("M5"),
            "defline": line,
        })
    schema = pa.schema([("position", pa.int64()), ("name", pa.string()),
                        ("length", pa.int64()), ("md5", pa.string()),
                        ("sha512t24u", pa.string()), ("n_N", pa.int64()),
                        ("n_lower", pa.int64()), ("line_width", pa.int64()),
                        ("defline_ac", pa.string()), ("defline_m5", pa.string()),
                        ("defline", pa.string())])
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out, compression="zstd")
    print(f"wrote {len(rows)} sequences to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
