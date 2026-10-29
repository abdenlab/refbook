"""Build the GRCh38 root tables from the raw NCBI downloads.

Reads REGISTRY/raw (see fetch_grch38.sh) and writes Parquet to REGISTRY/build/grch38:

- roots.parquet             one row per sequence accession.version: length,
                            refget digests (MD5, SQ.), base composition counts
- root_blocks.parquet       uppercase bases (IUPAC kept), fixed-size blocks
- assembly_members.parquet  every row of every GRCh38 assembly report (p0-p14)
- layer_softmask_ncbi.parquet   NCBI's lowercase (repeat) intervals
- layer_n_runs.parquet          runs of N
- layer_iupac.parquet           positions of non-ACGTN codes

Fails if a report lists a sequence that is missing or has the wrong length.

Usage: uv run --with pyarrow python build_roots.py REGISTRY_DIR [--block-size N]
"""

import argparse
import base64
import gzip
import hashlib
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

NCBI = "ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405"
P14 = "GCA_000001405.29_GRCh38.p14"
SUPERSEDED = ["KQ759759.1", "KQ759762.1"]

LOWER = re.compile(rb"[a-z]+")
N_RUN = re.compile(rb"N+")
IUPAC = re.compile(rb"[^ACGTN]")
NOT_AZ = re.compile(rb"[^A-Z]")


def releases(raw: Path) -> list[Path]:
    dirs = sorted(
        (raw / NCBI).glob("GCA_000001405.*_GRCh38*"),
        key=lambda p: int(p.name.split("_")[1].split(".")[1]),
    )
    return [d for d in dirs if 15 <= int(d.name.split("_")[1].split(".")[1]) <= 29]


def read_fasta(path: Path):
    """Yield (accession.version, raw sequence bytes) from a FASTA, gzipped or not."""
    opener = gzip.open if path.suffix == ".gz" else open
    name, chunks = None, []
    with opener(path, "rb") as f:
        for line in f:
            if line.startswith(b">"):
                if name is not None:
                    yield name, b"".join(chunks)
                name, chunks = line[1:].split()[0].decode(), []
            else:
                chunks.append(line.rstrip())
    if name is not None:
        yield name, b"".join(chunks)


def digests(seq_upper: bytes) -> tuple[str, str]:
    """refget MD5 and ga4gh (SQ.) digests: drop non A-Z, of already uppercased bytes."""
    norm = NOT_AZ.sub(b"", seq_upper)
    md5 = hashlib.md5(norm).hexdigest()
    sq = "SQ." + base64.urlsafe_b64encode(hashlib.sha512(norm).digest()[:24]).decode()
    return md5, sq


def parse_report(path: Path) -> tuple[dict, list[dict]]:
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


def build_members(raw: Path) -> pa.Table:
    cols = {k: [] for k in (
        "assembly_accession", "assembly_name", "release", "sequence_name",
        "role", "assigned_molecule", "location_type", "genbank_accession",
        "relationship", "refseq_accession", "assembly_unit", "length", "ucsc_name",
    )}
    for d in releases(raw):
        meta, rows = parse_report(d / f"{d.name}_assembly_report.txt")
        name = meta["Assembly name"]
        release = int(name.split(".p")[1]) if ".p" in name else 0
        for r in rows:
            na = lambda v: None if v in ("na", "") else v
            cols["assembly_accession"].append(meta["GenBank assembly accession"])
            cols["assembly_name"].append(name)
            cols["release"].append(release)
            cols["sequence_name"].append(r["Sequence-Name"])
            cols["role"].append(r["Sequence-Role"])
            cols["assigned_molecule"].append(na(r["Assigned-Molecule"]))
            cols["location_type"].append(na(r["Assigned-Molecule-Location/Type"]))
            cols["genbank_accession"].append(r["GenBank-Accn"])
            cols["relationship"].append(r["Relationship"])
            cols["refseq_accession"].append(na(r["RefSeq-Accn"]))
            cols["assembly_unit"].append(r["Assembly-Unit"])
            cols["length"].append(int(r["Sequence-Length"]))
            cols["ucsc_name"].append(na(r["UCSC-style-name"]))
    return pa.table(cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("--block-size", type=int, default=65536)
    args = ap.parse_args()
    raw = args.registry / "raw"
    out = args.registry / "build" / "grch38"
    out.mkdir(parents=True, exist_ok=True)

    members = build_members(raw)
    pq.write_table(members, out / "assembly_members.parquet", compression="zstd")
    expected = {}
    for acc, length in zip(members["genbank_accession"].to_pylist(),
                           members["length"].to_pylist()):
        if expected.setdefault(acc, length) != length:
            sys.exit(f"{acc}: reports disagree on length")
    print(f"{len(expected)} distinct sequences across {len(releases(raw))} reports",
          file=sys.stderr)

    sources = [(raw / NCBI / P14 / f"{P14}_genomic.fna.gz",
                f"https://{NCBI}/{P14}/{P14}_genomic.fna.gz")]
    for acc in SUPERSEDED:
        sources.append((
            raw / "eutils.ncbi.nlm.nih.gov" / "efetch" / f"nuccore_{acc}.fasta",
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=nuccore&id={acc}&rettype=fasta&retmode=text",
        ))

    roots = {k: [] for k in ("root_id", "length", "md5", "sha512t24u", "n_N",
                             "n_iupac", "n_lower", "source")}
    layers = {
        "softmask_ncbi": {"root_id": [], "start": [], "end": []},
        "n_runs": {"root_id": [], "start": [], "end": []},
        "iupac": {"root_id": [], "pos": [], "code": []},
    }
    blocks_schema = pa.schema([("root_id", pa.string()), ("start", pa.int64()),
                               ("bases", pa.string())])
    blocks = pq.ParquetWriter(out / "root_blocks.parquet", blocks_schema,
                              compression="zstd")
    seen = set()
    for path, url in sources:
        for acc, seq in read_fasta(path):
            if acc not in expected:
                continue  # not a GRCh38 sequence (shouldn't happen)
            if acc in seen:
                sys.exit(f"{acc}: seen twice")
            seen.add(acc)
            if len(seq) != expected[acc]:
                sys.exit(f"{acc}: length {len(seq)} != report {expected[acc]}")
            n_lower = 0
            for m in LOWER.finditer(seq):
                layers["softmask_ncbi"]["root_id"].append(acc)
                layers["softmask_ncbi"]["start"].append(m.start())
                layers["softmask_ncbi"]["end"].append(m.end())
                n_lower += m.end() - m.start()
            up = seq.upper()
            if NOT_AZ.search(up):
                sys.exit(f"{acc}: contains characters outside A-Z")
            n_N = 0
            for m in N_RUN.finditer(up):
                layers["n_runs"]["root_id"].append(acc)
                layers["n_runs"]["start"].append(m.start())
                layers["n_runs"]["end"].append(m.end())
                n_N += m.end() - m.start()
            iupac = list(IUPAC.finditer(up))
            for m in iupac:
                layers["iupac"]["root_id"].append(acc)
                layers["iupac"]["pos"].append(m.start())
                layers["iupac"]["code"].append(m.group().decode())
            md5, sq = digests(up)
            for k, v in (("root_id", acc), ("length", len(up)), ("md5", md5),
                         ("sha512t24u", sq), ("n_N", n_N), ("n_iupac", len(iupac)),
                         ("n_lower", n_lower), ("source", url)):
                roots[k].append(v)
            starts = range(0, len(up), args.block_size)
            blocks.write_table(pa.table({
                "root_id": [acc] * len(starts),
                "start": list(starts),
                "bases": [up[s:s + args.block_size].decode() for s in starts],
            }, schema=blocks_schema))
            print(f"{acc}\t{len(up)}\t{md5}", file=sys.stderr)
    blocks.close()

    missing = set(expected) - seen
    if missing:
        sys.exit(f"missing sequences: {sorted(missing)}")
    pq.write_table(pa.table(roots), out / "roots.parquet", compression="zstd")
    for name, cols in layers.items():
        pq.write_table(pa.table(cols), out / f"layer_{name}.parquet",
                       compression="zstd")
    print(f"wrote {len(seen)} roots to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
