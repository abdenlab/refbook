"""The Rust core (refbook._core) against reference implementations and the build.

The reference implementations here are the Python code the core replaced;
they stay as test oracles only.
"""

import base64
import hashlib
import os
import random
import re
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from refbook import _core

BUILD = Path(os.environ.get("REFBOOK_CATALOG", Path(__file__).resolve().parent.parent / "build" / "grch38"))
needs_build = pytest.mark.skipif(not (BUILD / "catalog.json").exists(), reason="no build")

NOT_AZ = re.compile(rb"[^A-Z]")


def reference_canonical(seq: bytes) -> bytes | int:
    """The bases, or the position of the first character outside the policy."""
    up = seq.translate(None, b" \t\r\n\v\f").upper()
    m = NOT_AZ.search(up)
    return m.start() if m else up


def reference_digests(bases: bytes) -> tuple[str, str]:
    return (hashlib.md5(bases).hexdigest(),
            "SQ." + base64.urlsafe_b64encode(hashlib.sha512(bases).digest()[:24]).decode())


def reference_scan(seq: bytes) -> dict:
    up = seq.upper()
    return {"lower": [(m.start(), m.end()) for m in re.finditer(rb"[a-z]+", seq)],
            "n_runs": [(m.start(), m.end()) for m in re.finditer(rb"N+", up)],
            "iupac": [(m.start(), m.group().decode()) for m in re.finditer(rb"[^ACGTN]", up)]}


def random_sequences(n: int, seed: int = 11):
    rng = random.Random(seed)
    alphabet = b"ACGTNacgtnRYKMSWBDHVrykmswbdhv \n\r\t" + bytes(range(0, 256, 7))
    for _ in range(n):
        yield bytes(rng.choice(alphabet) for _ in range(rng.randrange(0, 300)))


def test_canonical_bases_and_digests_agree_with_the_reference():
    for seq in random_sequences(3000):
        want = reference_canonical(seq)
        if isinstance(want, int):
            with pytest.raises(ValueError, match=f"position {want}$"):
                _core.canonical_bases(seq)
        else:
            assert _core.canonical_bases(seq) == want
            assert _core.digests(want) == reference_digests(want)
        assert _core.remove_whitespace(seq) == seq.translate(None, b" \t\r\n\v\f")
        assert _core.sha512t24u(seq) == reference_digests(seq)[1][3:]


def test_scan_agrees_with_the_reference():
    rng = random.Random(5)
    for _ in range(2000):
        seq = bytes(rng.choice(b"ACGTNacgtnRYKMryk") for _ in range(rng.randrange(0, 200)))
        got, want = _core.scan(seq), reference_scan(seq)
        assert (got["lower"], got["n_runs"], got["iupac"]) == (want["lower"], want["n_runs"], want["iupac"])
        assert got["bases"] == seq.upper() and (got["md5"], got["sha512t24u"]) == reference_digests(seq.upper())


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
