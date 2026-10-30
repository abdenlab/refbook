"""Record what a published FASTA actually contains, sequence by sequence.

These observations are the targets a flavor's recipe must reproduce. Per
sequence: position, name, length, refget digests (MD5, SQ.) of the uppercased
bases, counts of N and lowercase, the line width, and the defline's `AC:` and
`M5:` tags where present (GRC analysis sets).

Usage: uv run python -I pipeline/observe_fasta.py FASTA[.gz] OUT.parquet
"""

import base64
import gzip
import hashlib
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

NOT_AZ = re.compile(rb"[^A-Z]")
LOWER = bytes(range(ord("a"), ord("z") + 1))


def records(path: Path):
    """Yield (defline, [sequence lines]) from a FASTA, gzipped or not."""
    opener = gzip.open if path.suffix == ".gz" else open
    defline, lines = None, []
    with opener(path, "rb") as f:
        for line in f:
            if line.startswith(b">"):
                if defline is not None:
                    yield defline, lines
                defline, lines = line[1:].rstrip(b"\r\n").decode(), []
            else:
                lines.append(line.rstrip(b"\r\n"))
    if defline is not None:
        yield defline, lines


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    cols = {k: [] for k in ("position", "name", "length", "md5", "sha512t24u", "n_N",
                            "n_lower", "line_width", "defline_ac", "defline_m5",
                            "defline")}
    for i, (defline, lines) in enumerate(records(src)):
        seq = b"".join(lines)
        up = NOT_AZ.sub(b"", seq.upper())
        tags = dict(re.findall(r"\b(\w\w):(\S+)", defline))
        for k, v in (
            ("position", i), ("name", defline.split()[0]), ("length", len(seq)),
            ("md5", hashlib.md5(up).hexdigest()),
            ("sha512t24u", "SQ." + base64.urlsafe_b64encode(
                hashlib.sha512(up).digest()[:24]).decode()),
            ("n_N", up.count(b"N")), ("n_lower", len(seq) - len(seq.translate(None, LOWER))),
            ("line_width", len(lines[0]) if lines else 0),
            ("defline_ac", tags.get("AC")), ("defline_m5", tags.get("M5")),
            ("defline", defline),
        ):
            cols[k].append(v)
        print(f"{cols['name'][-1]}\t{len(seq)}\t{cols['md5'][-1]}", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), out, compression="zstd")
    print(f"wrote {len(cols['name'])} sequences to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
