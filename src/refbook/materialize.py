"""Materialize a collection: its sequences as an Arrow stream (CompoSeq Sequence 0.1).

Seqcol level 3: one row per sequence, in the collection's order: `name`,
`description` (null) and `sequence` (LargeUtf8). The collection can be any that
refbook.resolve accepts: a flavor, a target, a stored digest, a seqcol
representation or a named sequence set. Each sequence's bases are built from
its canonical derivation in the sequence store (a root and nucleotide
operations) and checked against its digests. Soft-masking is a layer, not part
of the bases, so sequences are uppercase. Formatting (line width, deflines) is
out of band.

Hosted roots come from root_blocks.parquet (their row groups; see blocks.py). External
roots (IMGT/HLA) are never hosted: their bases are read from the source release,
a local mirror if there is one, else downloaded into a cache, and checked
against the catalog's digests.
"""

import hashlib
import os
import struct
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa

from refbook.blocks import BLOCK_SIZE, row_groups_by_root
from refbook.catalog import Catalog
from refbook.resolve import collection
from refbook.seqcol import sha512t24u

SCHEMA = pa.schema([
    pa.field("name", pa.string(), nullable=False),
    pa.field("description", pa.string(), nullable=True),
    pa.field("sequence", pa.large_string(), nullable=False),
])
# Uppercase IUPAC codes other than N, to N: the recipe alphabet step iupac -> N.
IUPAC_TO_N = bytes.maketrans(b"BDHKMRSVWY", b"N" * 10)
USER_AGENT = "refbook (reference genome catalog)"


class Bases:
    """Fetches root bases: hosted from root_blocks, external from their source."""

    def __init__(self, cat: Catalog, cache: str | Path | None = None):
        self.cat = cat
        self.blocks = cat.open_blocks()
        self.http = cat.blocks_http if cat.remote else None   # this Bases' own range reader
        self.row_groups = row_groups_by_root(self.blocks)
        # A local mirror of the sources (raw/), when the catalog is a build (build/<assembly>).
        self.mirror = None if cat.remote else cat.path.parent.parent / "raw"
        self.cache = Path(cache or os.environ.get("REFBOOK_CACHE",
                                                  Path.home() / ".cache" / "refbook"))
        self._external_files: dict[str, dict] = {}
        self._spans: dict[str, list[tuple[int, int, int]]] = {}
        self._cache: dict[int, list[tuple[int, str]]] = {}

    def get(self, root_id: str) -> bytearray:
        if root_id in self.row_groups:
            self.prefetch(self.row_groups[root_id])
            t = self.blocks.read_row_groups(self.row_groups[root_id], columns=["start", "bases"])
            blocks = sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist()))
            return bytearray(b"".join(b.encode("ascii") for _, b in blocks))
        if root_id in self.cat.external:
            return bytearray(self._external(root_id))
        raise KeyError(f"{root_id}: no bases (not a hosted or external root)")

    def row_groups_for(self, root_id: str, start: int, end: int) -> list[int]:
        """Row groups of a hosted root that hold bases [start, end)."""
        if root_id not in self._spans:
            md = self.blocks.metadata
            self._spans[root_id] = [(md.row_group(i).column(1).statistics.min,
                                     md.row_group(i).column(1).statistics.max, i)
                                    for i in self.row_groups[root_id]]
        first, last = start // BLOCK_SIZE * BLOCK_SIZE, max(end - 1, start) // BLOCK_SIZE * BLOCK_SIZE
        return [i for lo, hi, i in self._spans[root_id] if not (hi < first or lo > last)]

    def prefetch(self, row_groups: list[int]) -> None:
        """Over HTTP: fetch these row groups' start and bases chunks concurrently."""
        http = self.http
        if http is None:
            return
        md, spans = self.blocks.metadata, []
        for i in row_groups:
            cols = [md.row_group(i).column(c) for c in (1, 2)]          # start, bases
            lo = min(c.dictionary_page_offset if c.has_dictionary_page else c.data_page_offset for c in cols)
            hi = max((c.dictionary_page_offset if c.has_dictionary_page else c.data_page_offset)
                     + c.total_compressed_size for c in cols)
            spans.append((lo, hi))
        http.clear()
        http.prefetch(spans)

    def slice(self, root_id: str, start: int, end: int) -> bytes:
        """Bases [start, end) of a root, reading only the row groups that cover them."""
        if root_id not in self.row_groups:
            return bytes(self.get(root_id)[start:end])  # external roots are small; read whole
        if root_id not in self._spans:
            md = self.blocks.metadata
            self._spans[root_id] = [(md.row_group(i).column(1).statistics.min,
                                     md.row_group(i).column(1).statistics.max, i)
                                    for i in self.row_groups[root_id]]
        first, last = start // BLOCK_SIZE * BLOCK_SIZE, max(end - 1, start) // BLOCK_SIZE * BLOCK_SIZE
        parts = []
        for lo, hi, i in self._spans[root_id]:
            if hi < first or lo > last:
                continue
            if i not in self._cache:
                if len(self._cache) > 64:
                    self._cache.clear()
                t = self.blocks.read_row_group(i, columns=["start", "bases"])
                self._cache[i] = sorted(zip(t["start"].to_pylist(), t["bases"].to_pylist()))
            parts += [(s, b) for s, b in self._cache[i] if first <= s <= last]
        if not parts:
            return b""
        parts.sort()
        off = parts[0][0]
        return "".join(b for _, b in parts).encode("ascii")[start - off:end - off]

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
        local = self.mirror / url.split("://", 1)[1] if self.mirror else None
        if local and local.exists():
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


def apply_operations(cat: Catalog, root: str, operations: list[str], b: bytearray,
                     start: int = 0) -> bytes:
    """Bases b of a root, starting at `start`, with nucleotide operations applied:
    a mask layer's spans set to N, or iupac_to_n."""
    end = start + len(b)
    for op in operations:
        if op == "iupac_to_n":
            b = bytearray(bytes(b).translate(IUPAC_TO_N))
        else:
            for s, e in cat.spans(op).get(root, ()):
                if s < end and e > start:
                    a, z = max(s, start) - start, min(e, end) - start
                    b[a:z] = b"N" * (z - a)
    return bytes(b)


def sequence_bases(cat: Catalog, sq: str, bases: "Bases", verify: bool = True) -> bytes:
    """A known sequence's bases, from its canonical derivation."""
    rec = cat.sequence[sq]
    b = apply_operations(cat, rec["root_id"], rec["operations"], bases.get(rec["root_id"]))
    if verify and (hashlib.md5(b).hexdigest() != rec["md5"] or "SQ." + sha512t24u(b) != sq):
        raise ValueError(f"{sq}: bases built from {rec['root_id']} {rec['operations']} "
                         "do not match the digest")
    return b


def sequences(cat: Catalog, x, names: list[str] | None = None,
              bases: Bases | None = None, verify: bool = True) -> Iterator[tuple[str, bytes]]:
    """(name, bases) for each sequence of a collection, in its order."""
    c = collection(cat, x)
    bases = bases or Bases(cat)
    wanted = set(names) if names is not None else None
    if wanted is not None and wanted - set(c.names):
        raise KeyError(f"no sequence named {', '.join(sorted(wanted - set(c.names))[:5])}")
    for name, sq in zip(c.names, c.sequences):
        if wanted is None or name in wanted:
            yield name, sequence_bases(cat, sq, bases, verify)


def materialize(cat: Catalog, x, names: list[str] | None = None, *,
                max_batch_bytes: int = 1 << 30, verify: bool = True,
                bases: Bases | None = None) -> pa.RecordBatchReader:
    """A collection as a Sequence 0.1 stream. Batches end early at max_batch_bytes
    of sequence. The schema metadata names the collection; the whole collection
    also carries its seqcol digest."""
    c = collection(cat, x)
    meta = {"refbook:collection": c.label or c.digest}
    if names is None:
        meta["refbook:seqcol_digest"] = c.digest
    schema = SCHEMA.with_metadata(meta)

    def batches() -> Iterator[pa.RecordBatch]:
        rows: list[tuple[str, bytes]] = []
        size = 0
        for name, b in sequences(cat, c, names, bases, verify):
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
