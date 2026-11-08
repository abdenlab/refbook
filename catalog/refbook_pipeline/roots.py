"""Roots: every sequence the catalog builds from, each once, whichever books use it.

Reads the FASTA files the sources declare (`sequences`) and writes:

- roots.parquet             one row per root (accession.version): length, refget digests (MD5, SQ.), counts of
                            N, IUPAC codes and lowercase bases, and the URL it was read from
- root_blocks.parquet       its bases, uppercase with IUPAC codes kept, in fixed-size blocks (refbook.blocks)
- layer_softmask_ncbi.parquet   the lowercase (repeat) runs, as the source FASTA had them
- layer_n_runs.parquet          runs of N
- layer_iupac.parquet           positions of non-ACGTN codes

The roots expected are the assembly members (their reports give each one's length) and the loose roots the
sources declare (EBV, length from its GenBank record), and the minted roots (hs37d5's decoys: read under their
FASTA name, kept under the ID the catalog gives them; length from their FASTA index). Refuses a sequence that is
expected nowhere, has another
length, has a non-canonical base, or is missing. A root found in two files must have the same bases in both
(as rCRS will in GRCh37's and GRCh38's): the first is kept.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from refbook import blocks as root_blocks
from refbook import refget
from refbook.parse import open_compressed

from . import Refused

LAYERS = {"softmask_ncbi": "lower", "n_runs": "n_runs"}


def genbank_length(path: Path) -> int:
    """A sequence's length from its GenBank record's LOCUS line."""
    return int(path.read_text().split("\n", 1)[0].split()[2])


def read_fasta(path: Path):
    """(accession.version, sequence bytes) from a FASTA, gzipped or not."""
    name, chunks = None, []
    with open_compressed(path) as f:
        for line in f:
            if line.startswith(b">"):
                if name is not None:
                    yield name, b"".join(chunks)
                name, chunks = line[1:].split()[0].decode(), []
            else:
                chunks.append(line.rstrip())
    if name is not None:
        yield name, b"".join(chunks)


def build(expected: dict[str, int], fastas: list[tuple[Path, str]], out: Path,
          block_size: int = root_blocks.BLOCK_SIZE, minted: dict[Path, dict[str, str]] | None = None) -> dict:
    """Write the root tables into the directory `out` from `fastas` ((path, URL), read in order). `minted` maps,
    for a FASTA, a name in it to the root ID it is kept under."""
    minted = minted or {}
    roots = {k: [] for k in ("root_id", "length", "md5", "sha512t24u", "n_N", "n_iupac", "n_lower", "source")}
    layers = {name: {"root_id": [], "start": [], "end": []} for name in LAYERS}
    iupac = {"root_id": [], "pos": [], "code": []}
    seen, duplicates = {}, []
    blocks = root_blocks.writer(out / "root_blocks.parquet")
    try:
        for path, url in fastas:
            for acc, seq in read_fasta(path):
                acc = minted.get(path, {}).get(acc, acc)
                if acc not in expected:
                    raise Refused(f"{acc} in {path.name}: in no assembly report, and not a declared loose root")
                seq = refget.remove_whitespace(seq)
                if len(seq) != expected[acc]:
                    raise Refused(f"{acc} in {path.name}: length {len(seq)}, but {expected[acc]} expected")
                try:
                    sc = refget.scan(seq)
                except refget.NonCanonicalBase as e:
                    raise Refused(f"{acc} in {path.name}: {e}") from e
                if acc in seen:
                    if seen[acc] != sc["sha512t24u"]:
                        raise Refused(f"{acc}: other bases in {path.name} than where it was first read")
                    duplicates.append(acc)
                    continue
                seen[acc] = sc["sha512t24u"]
                for name, key in LAYERS.items():
                    for start, end in sc[key]:
                        layers[name]["root_id"].append(acc)
                        layers[name]["start"].append(start)
                        layers[name]["end"].append(end)
                for pos, code in sc["iupac"]:
                    iupac["root_id"].append(acc)
                    iupac["pos"].append(pos)
                    iupac["code"].append(code)
                up = sc["bases"]
                for k, v in (("root_id", acc), ("length", len(up)), ("md5", sc["md5"]),
                             ("sha512t24u", sc["sha512t24u"]), ("n_N", sum(e - s for s, e in sc["n_runs"])),
                             ("n_iupac", len(sc["iupac"])), ("n_lower", sum(e - s for s, e in sc["lower"])),
                             ("source", url)):
                    roots[k].append(v)
                starts = range(0, len(up), block_size)
                root_blocks.write_root(blocks, pa.table({
                    "root_id": [acc] * len(starts), "start": list(starts),
                    "bases": [up[s:s + block_size].decode() for s in starts]}, schema=root_blocks.SCHEMA))
    finally:
        blocks.close()
    missing = sorted(set(expected) - set(seen))
    if missing:
        raise Refused(f"{len(missing)} expected roots are in no declared FASTA, e.g. {missing[:5]}")
    pq.write_table(pa.table(roots), out / "roots.parquet", compression="zstd")
    for name, cols in layers.items():
        pq.write_table(pa.table(cols), out / f"layer_{name}.parquet", compression="zstd")
    pq.write_table(pa.table(iupac), out / "layer_iupac.parquet", compression="zstd")
    return {"roots": len(seen), "read_twice": duplicates}
