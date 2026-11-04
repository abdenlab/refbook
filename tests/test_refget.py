"""Refget digests and the canonicalization policy."""

import pytest

from refbook.refget import NonCanonicalBase, canonical_bases, digests


def test_digests_of_a_known_sequence():
    # sha512t24u("ACGT") as given in the GA4GH VRS documentation.
    assert digests(b"ACGT") == ("f1f8f4bf413b16ad135722aa4591043e",
                                "SQ.aKF498dAxcJAqme6QYQ7EZ07-fiw8Kw2")


def test_canonical_bases_uppercases_and_drops_whitespace():
    assert canonical_bases(b"acgt\nNNry \r\n") == b"ACGTNNRY"
    assert canonical_bases(b"") == b""


@pytest.mark.parametrize("seq", [b"ACGT*", b"AC-GT", b"AC.GT", b"ACG1"])
def test_canonical_bases_rejects_other_characters(seq):
    with pytest.raises(NonCanonicalBase):
        canonical_bases(seq)
