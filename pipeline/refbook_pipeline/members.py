"""Assembly members: every row of every assembly report a book draws on.

assembly_members has one row per (book, release, sequence): the book, the release's GenBank assembly accession,
name and patch number, and the report's columns (role, assigned molecule, accessions, assembly unit, length,
UCSC-style name). A book's add-on assemblies (hs38d1 for GRCh38) are members of that book too. Lengths must agree
wherever an accession appears.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from . import Refused

COLUMNS = ["book", "assembly_accession", "assembly_name", "release", "sequence_name", "role", "assigned_molecule",
           "location_type", "genbank_accession", "relationship", "refseq_accession", "assembly_unit", "length",
           "ucsc_name"]
SCHEMA = pa.schema([(c, pa.int64() if c in ("release", "length") else pa.string()) for c in COLUMNS])


def parse_report(path: Path) -> tuple[dict, list[dict]]:
    """An NCBI assembly report: its header's `# Key: value` lines, and its rows by column name."""
    meta, rows, header = {}, [], None
    for line in path.read_text().splitlines():
        if line.startswith("# ") and ":" in line and header is None:
            k, _, v = line[2:].partition(":")
            meta[k.strip()] = v.strip()
        if line.startswith("# Sequence-Name"):
            header = line[2:].split("\t")
        elif not line.startswith("#") and header:
            rows.append(dict(zip(header, line.split("\t"))))
    return meta, rows


def release_of(name: str) -> int:
    """The patch number in an assembly name: 14 for GRCh38.p14, 0 for GRCh38 (or hs38d1)."""
    return int(name.split(".p")[1]) if ".p" in name else 0


def members(book: str, reports: list[Path]) -> pa.Table:
    """The book's assembly members, from its reports."""
    na = lambda v: None if v in ("na", "") else v
    rows = []
    for path in reports:
        meta, report = parse_report(path)
        name = meta["Assembly name"]
        for r in report:
            rows.append({"book": book, "assembly_accession": meta["GenBank assembly accession"],
                         "assembly_name": name, "release": release_of(name), "sequence_name": r["Sequence-Name"],
                         "role": r["Sequence-Role"], "assigned_molecule": na(r["Assigned-Molecule"]),
                         "location_type": na(r["Assigned-Molecule-Location/Type"]),
                         "genbank_accession": r["GenBank-Accn"], "relationship": r["Relationship"],
                         "refseq_accession": na(r["RefSeq-Accn"]), "assembly_unit": r["Assembly-Unit"],
                         "length": int(r["Sequence-Length"]), "ucsc_name": na(r["UCSC-style-name"])})
    return pa.Table.from_pylist(rows, schema=SCHEMA)


def lengths(table: pa.Table) -> dict[str, int]:
    """Each member accession's length; refuses an accession whose reports disagree."""
    out = {}
    for acc, n in zip(table["genbank_accession"].to_pylist(), table["length"].to_pylist()):
        if out.setdefault(acc, n) != n:
            raise Refused(f"{acc}: assembly reports disagree on its length ({out[acc]} and {n})")
    return out
