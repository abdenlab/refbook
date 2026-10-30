"""Build the external roots: sequences we catalog by identity and digest only.

An external root's bases are never hosted (no root_blocks rows), because its
licence does not allow it; the library fetches them from the source. For now
that is IPD-IMGT/HLA release 3.18.0 (CC BY-ND), the HLA alleles in bwakit's
hs38DH. Reads its per-gene FASTAs from REGISTRY/raw (see fetch_grch38.sh) and
writes REGISTRY/build/grch38/roots_external.parquet:

- root_id      IMGTHLA:<release>:<IMGT accession>, e.g. IMGTHLA:3.18.0:HLA00001.
               A release can carry one accession twice (3.18.0: HLA00664,
               DRB1*01:01:01, is in DRB1_gen.fasta at 10,741 bp and again at
               801 bp in DRB5_gen.fasta); later copies get ":<group>" appended
- collection   the release, e.g. "IMGT/HLA 3.18.0" (what recipes select by)
- group        the gene file it comes from, e.g. "A", "DQA", "DRB1" (file
               <group>_gen.fasta; the allele's own gene is in `name`)
- name         allele name, e.g. "A*01:01:01:01"
- accession    IMGT accession, e.g. HLA00001
- rank         position in the release: gene files in name order, then file order
- length, md5, sha512t24u, n_N, n_iupac, n_lower   as in roots.parquet
- source       URL of the gene FASTA

Usage: uv run --with pyarrow python build_external_roots.py REGISTRY_DIR
"""

import argparse
import base64
import hashlib
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

IMGT = "raw.githubusercontent.com/ANHIG/IMGTHLA"
RELEASES = {"3180": "3.18.0"}
NOT_AZ = re.compile(rb"[^A-Z]")
IUPAC = re.compile(rb"[^ACGTN]")


def read_fasta(path: Path):
    """Yield (header, raw sequence bytes)."""
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    args = ap.parse_args()
    raw = args.registry / "raw"
    cols = {k: [] for k in ("root_id", "collection", "group", "name", "accession", "rank",
                            "length", "md5", "sha512t24u", "n_N", "n_iupac", "n_lower",
                            "source")}
    for branch, release in RELEASES.items():
        files = sorted((raw / IMGT / branch / "fasta").glob("*_gen.fasta"))
        if not files:
            sys.exit(f"no IMGT/HLA {release} FASTAs under {raw / IMGT / branch}")
        rank, seen = 0, set()
        for path in files:
            group = path.name.removesuffix("_gen.fasta")
            for header, seq in read_fasta(path):
                # >HLA:HLA00001 A*01:01:01:01 3503 bp
                acc_field, allele, n_bp, _ = header.split()
                acc = acc_field.split(":")[1]
                root_id = f"IMGTHLA:{release}:{acc}"
                if root_id in seen:
                    root_id += f":{group}"
                seen.add(root_id)
                if int(n_bp) != len(seq):
                    sys.exit(f"{acc}: header says {n_bp} bp, sequence has {len(seq)}")
                up = seq.upper()
                if NOT_AZ.search(up):
                    sys.exit(f"{acc}: characters outside A-Z")
                for k, v in (
                    ("root_id", root_id),
                    ("collection", f"IMGT/HLA {release}"), ("group", group),
                    ("name", allele), ("accession", acc), ("rank", rank),
                    ("length", len(up)), ("md5", hashlib.md5(up).hexdigest()),
                    ("sha512t24u", "SQ." + base64.urlsafe_b64encode(
                        hashlib.sha512(up).digest()[:24]).decode()),
                    ("n_N", up.count(b"N")), ("n_iupac", len(IUPAC.findall(up))),
                    ("n_lower", sum(1 for a, b in zip(seq, up) if a != b)),
                    ("source", f"https://{IMGT}/{branch}/fasta/{path.name}"),
                ):
                    cols[k].append(v)
                rank += 1
    out = args.registry / "build" / "grch38" / "roots_external.parquet"
    pq.write_table(pa.table(cols), out, compression="zstd")
    if len(set(cols["md5"])) != len(cols["md5"]):
        print("note: some external roots share an MD5", file=sys.stderr)
    print(f"wrote {len(cols['root_id'])} external roots to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
