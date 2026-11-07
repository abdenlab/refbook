"""External roots: sequences the catalog lists by identity and digest only, never hosting their bases, because
their licence doesn't allow it; the library fetches them from the source. A source declares its collection
(`external`); for now that is IPD-IMGT/HLA release 3.18.0 (CC BY-ND), the HLA alleles in bwakit's hs38DH.

roots_external.parquet:
- root_id      <prefix>:<IMGT accession>, e.g. IMGTHLA:3.18.0:HLA00001. A release can carry one accession twice
               (3.18.0: HLA00664, DRB1*01:01:01, in DRB1_gen.fasta at 10,741 bp and again at 801 bp in
               DRB5_gen.fasta); later copies get ":<group>" appended
- collection   e.g. "IMGT/HLA 3.18.0" (what recipes select by)
- group        the gene file it comes from, e.g. "A", "DQA", "DRB1" (<group>_gen.fasta; the allele's gene is in name)
- name         allele name, e.g. "A*01:01:01:01"
- accession    IMGT accession, e.g. HLA00001
- rank         position in the release: gene files in name order, then file order
- length, md5, sha512t24u, n_N, n_iupac, n_lower   as in roots.parquet
- source       URL of the gene FASTA
"""

from __future__ import annotations

import re
from pathlib import Path

import pyarrow as pa

from refbook import refget

from . import Refused

IUPAC = re.compile(rb"[^ACGTN]")
COLUMNS = ["root_id", "collection", "group", "name", "accession", "rank", "length", "md5", "sha512t24u", "n_N",
           "n_iupac", "n_lower", "source"]


def read_fasta(path: Path):
    """(header, raw sequence bytes) from an uncompressed FASTA."""
    header, chunks = None, []
    with open(path, "rb") as f:
        for line in f:
            if line.startswith(b">"):
                if header is not None:
                    yield header, b"".join(chunks)
                header, chunks = line[1:].decode().rstrip(), []
            else:
                chunks.append(line.rstrip())
    if header is not None:
        yield header, b"".join(chunks)


def parse_header(header: str) -> tuple[str, str, int]:
    """(IMGT accession, allele name, stated length) of an IMGT/HLA header, e.g. "HLA:HLA00001 A*01:01:01:01 3503 bp"."""
    acc_field, allele, n_bp, unit = header.split()
    if unit != "bp" or not acc_field.startswith("HLA:"):
        raise Refused(f"unexpected IMGT/HLA header: {header!r}")
    return acc_field.split(":")[1], allele, int(n_bp)


def imgt_hla(collection: str, prefix: str, files: list[tuple[Path, str]]) -> list[dict]:
    """One release's alleles, from its gene FASTAs ((path, URL), in name order)."""
    if not files:
        raise Refused(f"{collection}: no gene FASTAs")
    rows, seen = [], set()
    for path, url in files:
        group = path.name.removesuffix("_gen.fasta")
        for header, seq in read_fasta(path):
            acc, allele, n_bp = parse_header(header)
            root_id = f"{prefix}:{acc}"
            if root_id in seen:
                root_id += f":{group}"
            seen.add(root_id)
            seq = refget.remove_whitespace(seq)
            if n_bp != len(seq):
                raise Refused(f"{acc}: its header says {n_bp} bp, its sequence has {len(seq)}")
            try:
                up = refget.canonical_bases(seq)
            except refget.NonCanonicalBase as e:
                raise Refused(f"{acc}: {e}") from e
            md5, sq = refget.digests(up)
            rows.append({"root_id": root_id, "collection": collection, "group": group, "name": allele,
                         "accession": acc, "rank": len(rows), "length": len(up), "md5": md5, "sha512t24u": sq,
                         "n_N": up.count(b"N"), "n_iupac": len(IUPAC.findall(up)),
                         "n_lower": sum(1 for a, b in zip(seq, up) if a != b), "source": url})
    return rows


def table(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=pa.schema(
        [(c, pa.int64() if c in ("rank", "length", "n_N", "n_iupac", "n_lower") else pa.string()) for c in COLUMNS]))
