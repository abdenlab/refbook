"""Materialize a flavor: its sequences as an Arrow stream (CompoSeq Sequence 0.1).

One row per sequence, in the flavor's order: `name`, `description` (null) and
`sequence` (LargeUtf8). The bases are built from the roots by the recipe's
identity operations, hard masks and alphabet; selection, names and order come
from the reproduced flavor. Soft-masking is a layer, not part of the bases, so
sequences are uppercase. Formatting (line width, deflines) is out of band.

Hosted roots come from root_blocks.parquet (their row groups; see blocks.py). External
roots (IMGT/HLA) are never hosted: their bases are read from the source release,
a local mirror if there is one, else downloaded into a cache, and checked
against the catalog's digests.
"""

import hashlib
import json
import os
import struct
import urllib.request
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ref_registry.blocks import row_groups_by_root
from ref_registry.catalog import Catalog
from ref_registry.seqcol import sha512t24u

SCHEMA = pa.schema([
    pa.field("name", pa.string(), nullable=False),
    pa.field("description", pa.string(), nullable=True),
    pa.field("sequence", pa.large_string(), nullable=False),
])
# Uppercase IUPAC codes other than N, to N: the recipe alphabet step iupac -> N.
IUPAC_TO_N = bytes.maketrans(b"BDHKMRSVWY", b"N" * 10)
USER_AGENT = "ref-registry (reference genome catalog)"


class Bases:
    """Fetches root bases: hosted from root_blocks, external from their source."""

    def __init__(self, cat: Catalog, cache: str | Path | None = None):
        self.cat = cat
        self.blocks = pq.ParquetFile(cat.path / "root_blocks.parquet")
        self.row_groups = row_groups_by_root(self.blocks)
        self.mirror = cat.path.parent.parent / "raw"  # REGISTRY/raw next to REGISTRY/build/grch38
        self.cache = Path(cache or os.environ.get("REF_REGISTRY_CACHE",
                                                  Path.home() / ".cache" / "ref-registry"))
        self._external_files: dict[str, dict] = {}

    def get(self, root_id: str) -> bytearray:
        if root_id in self.row_groups:
            t = self.blocks.read_row_groups(self.row_groups[root_id], columns=["start", "bases"])
            blocks = sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist()))
            return bytearray(b"".join(b.encode("ascii") for _, b in blocks))
        if root_id in self.cat.external:
            return bytearray(self._external(root_id))
        raise KeyError(f"{root_id}: no bases (not a hosted or external root)")

    def _external(self, root_id: str) -> bytes:
        e = self.cat.external[root_id]
        url = e["source"]
        if url not in self._external_files:
            self._external_files[url] = _read_imgt_fasta(self._fetch(url))
        records = self._external_files[url]
        seq = records.get((e["accession"], e["name"]))
        if seq is None:
            raise KeyError(f"{root_id}: {e['accession']} {e['name']} not in {url}")
        if hashlib.md5(seq).hexdigest() != e["md5"]:
            raise ValueError(f"{root_id}: bases from {url} do not match the catalog's MD5")
        return seq

    def _fetch(self, url: str) -> Path:
        local = self.mirror / url.split("://", 1)[1]
        if local.exists():
            return local
        cached = self.cache / url.split("://", 1)[1]
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                cached.write_bytes(r.read())
        return cached


def _read_imgt_fasta(path: Path) -> dict[tuple[str, str], bytes]:
    """(accession, allele name) -> uppercase bases, from an IMGT/HLA *_gen.fasta."""
    out, key, chunks = {}, None, []
    for line in path.read_bytes().splitlines():
        if line.startswith(b">"):
            if key:
                out.setdefault(key, b"".join(chunks).upper())
            acc, allele = line[1:].decode().split()[:2]
            key, chunks = (acc.split(":")[1], allele), []
        else:
            chunks.append(line.strip())
    if key:
        out.setdefault(key, b"".join(chunks).upper())
    return out


def sequences(cat: Catalog, flavor: str, names: list[str] | None = None,
              bases: Bases | None = None, verify: bool = True) -> Iterator[tuple[str, bytes]]:
    """(name, bases) for each sequence of a flavor, in order; checked against its digests."""
    if flavor not in cat.flavors:
        raise KeyError(f"{flavor}: not a reproduced flavor")
    recipe = json.loads(cat.recipes[flavor]["recipe"])
    bases = bases or Bases(cat)
    spans = defaultdict(list)
    for m in recipe.get("mask", []):
        layer = pq.read_table(cat.path / f"layer_{m['layer']}.parquet", columns=["root_id", "start", "end"])
        for r, s, e in zip(*(layer[c].to_pylist() for c in ("root_id", "start", "end"))):
            spans[r].append((s, e))
    to_n = recipe.get("alphabet", {}).get("iupac") == "N"
    wanted = set(names) if names is not None else None
    for s in cat.flavors[flavor]:
        if wanted is not None and s.name not in wanted:
            continue
        b = bases.get(s.root_id)
        for start, end in spans.get(s.root_id, ()):
            b[start:end] = b"N" * (end - start)
        if to_n:
            b = bytearray(bytes(b).translate(IUPAC_TO_N))
        b = bytes(b)
        if verify and (hashlib.md5(b).hexdigest() != s.md5 or "SQ." + sha512t24u(b) != s.sha512t24u):
            raise ValueError(f"{flavor} {s.name}: materialized bases do not match the recipe's digests")
        yield s.name, b


def materialize(cat: Catalog, flavor: str, names: list[str] | None = None, *,
                max_batch_bytes: int = 1 << 30, verify: bool = True,
                bases: Bases | None = None) -> pa.RecordBatchReader:
    """A flavor as a Sequence 0.1 stream. Batches end early at max_batch_bytes of sequence."""
    meta = {"ref_registry:flavor": flavor,
            "ref_registry:seqcol_digest": cat.recipes[flavor]["seqcol_digest"]}
    schema = SCHEMA.with_metadata(meta) if names is None else SCHEMA.with_metadata(
        {"ref_registry:flavor": flavor})

    def batches() -> Iterator[pa.RecordBatch]:
        rows: list[tuple[str, bytes]] = []
        size = 0
        for name, b in sequences(cat, flavor, names, bases, verify):
            if rows and size + len(b) > max_batch_bytes:
                yield _batch(rows, schema)
                rows, size = [], 0
            rows.append((name, b))
            size += len(b)
        if rows:
            yield _batch(rows, schema)

    return pa.RecordBatchReader.from_batches(schema, batches())


def _batch(rows: list[tuple[str, bytes]], schema: pa.Schema) -> pa.RecordBatch:
    """Build the LargeUtf8 column from one joined buffer (ASCII, so valid UTF-8)."""
    ends, total = [0], 0
    for _, b in rows:
        total += len(b)
        ends.append(total)
    offsets = pa.py_buffer(struct.pack(f"<{len(ends)}q", *ends))
    seq = pa.LargeStringArray.from_buffers(len(rows), offsets, pa.py_buffer(b"".join(b for _, b in rows)))
    return pa.RecordBatch.from_arrays(
        [pa.array([n for n, _ in rows], pa.string()), pa.nulls(len(rows), pa.string()), seq],
        schema=schema)
