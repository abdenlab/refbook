"""Build the GRCh38 root tables from the raw NCBI downloads.

The roots are every GRCh38 sequence (p0-p14) plus the roots its flavors add:
the hs38d1 decoys and EBV. Reads REGISTRY/raw (see fetch_grch38.sh) and
writes Parquet to REGISTRY/build/grch38:

- roots.parquet             one row per sequence accession.version: length,
                            refget digests (MD5, SQ.), base composition counts
- root_blocks.parquet       uppercase bases (IUPAC kept), fixed-size blocks
- assembly_members.parquet  every row of every assembly report (GRCh38 p0-p14,
                            hs38d1); EBV is in none
- layer_softmask_ncbi.parquet   NCBI's lowercase (repeat) intervals
- layer_n_runs.parquet          runs of N
- layer_iupac.parquet           positions of non-ACGTN codes

Fails if a report lists a sequence that is missing or has the wrong length
(EBV's length comes from its GenBank record).

Usage: uv run python -I pipeline/build_roots.py REGISTRY_DIR [--block-size N]
"""

import argparse
import gzip
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from refbook import blocks as root_blocks  # the root_blocks storage layout
from refbook import refget

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

P14 = f"{layout.LATEST[1]}_{layout.LATEST[2]}"
SUPERSEDED = ["KQ759759.1", "KQ759762.1"]
# Roots outside GRCh38 that GRCh38 flavors add: the hs38d1 decoys (an
# assembly of their own) and EBV (in no assembly).
EBV = "AJ507799.2"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

LOWER = re.compile(rb"[a-z]+")
N_RUN = re.compile(rb"N+")
IUPAC = re.compile(rb"[^ACGTN]")


def genbank_length(path: Path) -> int:
    """Sequence length from a GenBank record's LOCUS line."""
    return int(path.read_text().split("\n", 1)[0].split()[2])


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


def scan(seq: bytes) -> dict:
    """Everything build_roots records about one sequence (whitespace already removed):
    canonical bases, digests, lowercase runs, N-runs and IUPAC positions (0-based,
    half-open runs), and their counts. Raises refget.NonCanonicalBase."""
    lower = [(m.start(), m.end()) for m in LOWER.finditer(seq)]
    up = refget.canonical_bases(seq)
    n_runs = [(m.start(), m.end()) for m in N_RUN.finditer(up)]
    md5, sq = refget.digests(up)
    return {"bases": up, "md5": md5, "sha512t24u": sq,
            "lower": lower, "n_lower": sum(e - s for s, e in lower),
            "n_runs": n_runs, "n_N": sum(e - s for s, e in n_runs),
            "iupac": [(m.start(), m.group().decode()) for m in IUPAC.finditer(up)]}


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
    for d in layout.assembly_dirs(raw):
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
    ap.add_argument("--block-size", type=int, default=root_blocks.BLOCK_SIZE)
    args = ap.parse_args()
    raw = layout.raw_dir(args.registry)
    out = layout.build_dir(args.registry)
    out.mkdir(parents=True, exist_ok=True)

    members = build_members(raw)
    pq.write_table(members, out / "assembly_members.parquet", compression="zstd")
    expected = {}
    for acc, length in zip(members["genbank_accession"].to_pylist(),
                           members["length"].to_pylist()):
        if expected.setdefault(acc, length) != length:
            sys.exit(f"{acc}: reports disagree on length")
    print(f"{len(expected)} distinct sequences across {len(layout.assembly_dirs(raw))} reports",
          file=sys.stderr)
    efetch = raw / "eutils.ncbi.nlm.nih.gov" / "efetch"
    expected[EBV] = genbank_length(efetch / f"nuccore_{EBV}.gb")

    sources = [(raw / layout.NCBI / P14 / f"{P14}_genomic.fna.gz",
                f"https://{layout.NCBI}/{P14}/{P14}_genomic.fna.gz")]
    for acc in SUPERSEDED + [EBV]:
        sources.append((efetch / f"nuccore_{acc}.fasta",
                        f"{EFETCH}?db=nuccore&id={acc}&rettype=fasta&retmode=text"))
    hs38d1 = f"{Path(layout.HS38D1).name}_genomic.fna.gz"
    sources.append((raw / layout.HS38D1 / hs38d1, f"https://{layout.HS38D1}/{hs38d1}"))

    roots = {k: [] for k in ("root_id", "length", "md5", "sha512t24u", "n_N",
                             "n_iupac", "n_lower", "source")}
    layers = {
        "softmask_ncbi": {"root_id": [], "start": [], "end": []},
        "n_runs": {"root_id": [], "start": [], "end": []},
        "iupac": {"root_id": [], "pos": [], "code": []},
    }
    blocks = root_blocks.writer(out / "root_blocks.parquet")
    seen = set()
    for path, url in sources:
        for acc, seq in read_fasta(path):
            if acc not in expected:
                sys.exit(f"{acc} in {path.name}: in no assembly report and not a listed root")
            if acc in seen:
                sys.exit(f"{acc}: seen twice")
            seen.add(acc)
            seq = refget.remove_whitespace(seq)
            if len(seq) != expected[acc]:
                sys.exit(f"{acc}: length {len(seq)} != report {expected[acc]}")
            try:
                sc = scan(seq)
            except refget.NonCanonicalBase as e:
                sys.exit(f"{acc}: {e}")
            up = sc["bases"]
            for name, key in (("softmask_ncbi", "lower"), ("n_runs", "n_runs")):
                for start, end in sc[key]:
                    layers[name]["root_id"].append(acc)
                    layers[name]["start"].append(start)
                    layers[name]["end"].append(end)
            for pos, code in sc["iupac"]:
                layers["iupac"]["root_id"].append(acc)
                layers["iupac"]["pos"].append(pos)
                layers["iupac"]["code"].append(code)
            md5 = sc["md5"]
            for k, v in (("root_id", acc), ("length", len(up)), ("md5", md5),
                         ("sha512t24u", sc["sha512t24u"]), ("n_N", sc["n_N"]),
                         ("n_iupac", len(sc["iupac"])), ("n_lower", sc["n_lower"]),
                         ("source", url)):
                roots[k].append(v)
            starts = range(0, len(up), args.block_size)
            root_blocks.write_root(blocks, pa.table({
                "root_id": [acc] * len(starts),
                "start": list(starts),
                "bases": [up[s:s + args.block_size].decode() for s in starts],
            }, schema=root_blocks.SCHEMA))
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
