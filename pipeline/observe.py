"""Observe a target: record what a file was found to contain, per sequence.

Observations are what a recipe must reproduce. One row per sequence, in file
order: position, name, length, MD5 and SQ. digests, counts of N and lowercase,
the first line's width, the defline's `AC:` and `M5:` tags (GRC analysis sets)
and the whole defline.

- From a FASTA, every digest is computed here, from the bases under
  refbook.refget's canonicalization policy (a character outside A-Z, a-z and
  whitespace is an error).
- From a SAM sequence dictionary (.dict), the weaker kind, for targets whose
  FASTA isn't fetched: only position, name, length and the publisher's M5 are
  known. md5 is the M5 as published (not computed); the fields a .dict lacks
  are null, and reproduction skips them.

A module, used by 30_observe.py.
"""

import gzip
import re
from pathlib import Path

import pyarrow as pa

from refbook import refget

LOWER = bytes(range(ord("a"), ord("z") + 1))
SCHEMA = pa.schema([("position", pa.int64()), ("name", pa.string()), ("length", pa.int64()),
                    ("md5", pa.string()), ("sha512t24u", pa.string()), ("n_N", pa.int64()),
                    ("n_lower", pa.int64()), ("line_width", pa.int64()),
                    ("defline_ac", pa.string()), ("defline_m5", pa.string()),
                    ("defline", pa.string())])


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


def observe_fasta(path: Path) -> pa.Table:
    rows = []
    for i, (defline, lines) in enumerate(records(path)):
        seq = refget.remove_whitespace(b"".join(lines))
        try:
            up = refget.canonical_bases(seq)
        except refget.NonCanonicalBase as e:
            raise ValueError(f"{path.name} {defline.split()[0]}: {e}") from None
        md5, sq = refget.digests(up)
        tags = dict(re.findall(r"\b(\w\w):(\S+)", defline))
        rows.append({"position": i, "name": defline.split()[0], "length": len(seq),
                     "md5": md5, "sha512t24u": sq, "n_N": up.count(b"N"),
                     "n_lower": len(seq) - len(seq.translate(None, LOWER)),
                     "line_width": len(lines[0]) if lines else 0,
                     "defline_ac": tags.get("AC"), "defline_m5": tags.get("M5"),
                     "defline": defline})
    return pa.Table.from_pylist(rows, schema=SCHEMA)


def parse_dict(text: str) -> list[dict]:
    """One observation row per @SQ line of a SAM sequence dictionary."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("@SQ"):
            continue
        tags = dict(f.split(":", 1) for f in line.split("\t")[1:])
        rows.append({
            "position": len(rows), "name": tags["SN"], "length": int(tags["LN"]),
            "md5": tags.get("M5"), "sha512t24u": None, "n_N": None, "n_lower": None,
            "line_width": None, "defline_ac": None, "defline_m5": tags.get("M5"),
            "defline": line,
        })
    return rows


def observe_dict(path: Path) -> pa.Table:
    return pa.Table.from_pylist(parse_dict(path.read_text()), schema=SCHEMA)


def observe(path: Path) -> pa.Table:
    """A FASTA's or a .dict's observation, by file name."""
    return observe_dict(path) if path.name.endswith(".dict") else observe_fasta(path)
