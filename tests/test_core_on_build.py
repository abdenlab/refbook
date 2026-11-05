"""The Rust core (refbook._core) against a whole build: every root, every
stored collection and every derivation. The core against its reference
implementations is python/tests/test_core.py.

Needs the build (REFBOOK_CATALOG, by default build/grch38); skipped without it.
"""

import json
import os
import random
from pathlib import Path

import layout
import pyarrow.parquet as pq
import pytest

from refbook import _core

BUILD = Path(os.environ.get("REFBOOK_CATALOG", Path(__file__).resolve().parent.parent / "build" / "grch38"))
needs_build = pytest.mark.skipif(not (BUILD / "catalog.json").exists(), reason="no build")


@needs_build
def test_every_root_digest():
    """Every hosted root's bases, read back from root_blocks, give its stored digests."""
    from refbook import Catalog
    from refbook.materialize import Bases
    cat = Catalog(BUILD)
    bases = Bases(cat)
    roots = pq.read_table(cat.file("roots.parquet"), columns=["root_id", "md5", "sha512t24u"]).to_pylist()
    assert len(roots) == 3097
    for r in roots:
        assert _core.digests(bytes(bases.get(r["root_id"]))) == (r["md5"], r["sha512t24u"]), r["root_id"]


@needs_build
def test_every_stored_collection():
    """Every collection the build stores: its name is its top-level digest, and its
    ancillary attributes are those the core computes."""
    files = sorted(layout.path(BUILD, "collections").glob("*.json"))
    assert len(files) == 26
    for f in files:
        doc = json.loads(f.read_text())
        names, lengths, sqs = doc["names"], doc["lengths"], doc["sequences"]
        top, _ = _core.seqcol_digests(names, lengths, sqs)
        assert top == f.stem
        anc = _core.seqcol_ancillary(names, lengths, sqs)
        assert anc == {k: doc[k] for k in anc}, f.name


@needs_build
def test_every_derivation():
    """Every known derivation, rebuilt by the core from its root, gives its digest,
    and slices of it agree with the whole."""
    from refbook import Catalog
    from refbook.materialize import Bases, apply_operations
    cat = Catalog(BUILD)
    bases = Bases(cat)
    by_root = {}
    for sq, ways in cat.derivations.items():
        for d in ways:
            by_root.setdefault(d["root_id"], []).append((sq, d["operations"]))
    assert sum(map(len, by_root.values())) == 3846
    rng = random.Random(7)
    for root, ways in by_root.items():
        raw = bytes(bases.get(root))
        for sq, ops in ways:
            b = apply_operations(cat, root, ops, raw)
            assert _core.digests(b) == (cat.sequence[sq]["md5"], sq), (root, ops)
            for _ in range(3):
                lo = rng.randrange(0, len(raw) + 1)
                hi = min(len(raw), lo + rng.randrange(0, 100_000))
                assert apply_operations(cat, root, ops, raw[lo:hi], lo) == b[lo:hi], (root, ops, lo)
