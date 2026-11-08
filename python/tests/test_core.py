"""The Rust core (refbook._core) against reference implementations.

The reference implementations here are the Python code the core replaced;
they stay as test oracles only. The same core against a whole build is
tests/test_core_on_build.py at the repository root.
"""

import base64
import hashlib
import random
import re

import pytest

from refbook import _core

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


# seqcol

def reference_canonical_json(item) -> str:
    import json
    return json.dumps(item, separators=(",", ":"), ensure_ascii=False, allow_nan=False, sort_keys=True)


def random_strings(n: int, seed: int = 3):
    rng = random.Random(seed)
    pool = [chr(c) for c in range(0x80)] + ["é", "ß", "中", "😀", " ", "﻿", "\\", '"']
    for _ in range(n):
        yield "".join(rng.choice(pool) for _ in range(rng.randrange(0, 20)))


def test_canonical_json_agrees_with_pythons_json():
    rng = random.Random(9)
    strings = list(random_strings(3000))
    for i in range(0, len(strings), 7):
        chunk = strings[i:i + 7]
        assert _core.canonical_json(chunk) == reference_canonical_json(chunk)
        ints = [rng.randrange(-2**63, 2**63) for _ in range(5)]
        assert _core.canonical_json(ints) == reference_canonical_json(ints)
        obj = [{"name": s, "length": n} for s, n in zip(chunk, ints)]
        assert _core.canonical_json(obj) == reference_canonical_json(obj)
    with pytest.raises(ValueError):
        _core.canonical_json([True])


# nucleotide operations

def reference_apply(bases: bytes, start: int, spans, to_n: bool) -> bytes:
    """Mask the whole root, then cut the slice: no slice arithmetic to get wrong."""
    end = start + len(bases)
    whole = bytearray(b"?" * start + bases + b"?" * max(0, max((e for _, e in spans), default=0) - end))
    for s, e in spans:
        whole[s:e] = b"N" * (e - s)
    out = bytes(whole[start:end])
    return re.sub(rb"[^ACGTN]", b"N", out) if to_n else out


def test_operations_agree_with_the_reference():
    rng = random.Random(5)
    for _ in range(3000):
        n = rng.randrange(0, 200)
        bases = bytes(rng.choice(b"ACGTNRYKMSWBDHV") for _ in range(n))
        start = rng.randrange(0, 50)
        spans = [(s, s + rng.randrange(0, 40)) for s in (rng.randrange(0, n + 100) for _ in range(rng.randrange(0, 6)))]
        to_n = rng.random() < 0.5
        assert _core.apply_operations(bases, start, spans, to_n) == reference_apply(bases, start, spans, to_n)


COMPLEMENT = bytes.maketrans(b"ACGTRYKMBVDHSWN", b"TGCAYRMKVBHDSWN")


def reference_pad(root: bytes, before: int, after: int, reverse: bool) -> bytes:
    """The whole padded sequence, built plainly."""
    return b"N" * before + (root.translate(COMPLEMENT)[::-1] if reverse else root) + b"N" * after


def test_padding_agrees_with_the_reference_on_every_slice():
    rng = random.Random(11)
    for _ in range(200):
        root = bytes(rng.choice(b"ACGTNRYKMSWBDHV") for _ in range(rng.randrange(0, 30)))
        p = (rng.randrange(0, 12), len(root), rng.randrange(0, 12), rng.random() < 0.5)
        whole = reference_pad(root, p[0], p[2], p[3])
        assert _core.pad(root, 0, len(whole), p) == whole
        for _ in range(20):
            start = rng.randrange(0, len(whole) + 1)
            end = rng.randrange(start, len(whole) + 1)
            a, z = _core.pad_root_range(start, end, p)
            assert _core.pad(root[a:z], start, end, p) == whole[start:end]
    with pytest.raises(ValueError, match="root range"):
        _core.pad(b"ACGT", 0, 11, (3, 5, 3, False))


def test_materialize_pads_after_the_masks():
    """The library's apply_operations: masks in root coordinates, then padding; slices agree with the whole."""
    from refbook.materialize import apply_operations, root_window

    class Cat:
        def spans(self, layer):
            return {"R": [(1, 3)]}

        def __init__(self):
            self.root_length = {"R": 6}

        def padding(self, root, book=None):
            assert book == "B"
            return (4, 6, 2, True)

    root = b"ACGTRA"
    for ops, want in ((["hardmask_x", "iupac_to_n", "pad"], b"NNNNTNANNTNN"),
                      (["hardmask_x", "iupac_to_n", "orient"], b"TNANNT")):  # orient: no Ns, reversed
        whole = apply_operations(Cat(), "R", ops, root, book="B")
        assert whole == want
        for start in range(len(whole) + 1):
            for end in range(start, len(whole) + 1):
                a, z = root_window(Cat(), "R", ops, start, end, "B")
                assert apply_operations(Cat(), "R", ops, root[a:z], start, end, "B") == whole[start:end]
    assert reference_pad(b"ANNTNA", 4, 2, True) == b"NNNNTNANNTNN"
