"""GA4GH sequence collection (seqcol) digests.

From the spec (github.com/ga4gh/refget, docs/seqcols/README.md): canonicalize
each attribute with RFC-8785, digest it with sha512t24u; the top-level digest
covers the inherent attributes, names and sequences.

Implemented in the Rust core (refbook._core, crates/refbook-core/src/seqcol.rs).
"""

from refbook import _core

INHERENT = ("names", "sequences")


def canonical(item) -> bytes:
    """RFC-8785 canonical JSON of a value made of strings, integers, lists and dicts."""
    return _core.canonical_json(item).encode("utf8")


def sha512t24u(data: bytes) -> str:
    return _core.sha512t24u(data)


def level1(value) -> str:
    """The level-1 digest of an attribute's level-2 value."""
    return _core.level1(value)


def digests(names: list[str], lengths: list[int], sequences: list[str]) -> tuple[str, dict]:
    """(top-level digest, level-1 digests) of a collection; sequences are SQ. ids."""
    return _core.seqcol_digests(names, lengths, sequences)


def ancillary(names: list[str], lengths: list[int], sequences: list[str]) -> dict:
    """Level-2 values of the non-inherent attributes refbook computes.

    From the spec: name_length_pairs (5.1), sorted_name_length_pairs (5.2) and
    sorted_sequences (5.3). named_sequences is the per-element digest of
    {"name", "sequence"} that footnote F1 suggests; sorted_named_sequences is
    refbook's: those digests sorted, as 5.2 sorts name-length pairs. Its
    level-1 digest identifies the named sequence set, whatever the order.
    """
    return _core.seqcol_ancillary(names, lengths, sequences)


def named_set_digest(names: list[str], sequences: list[str]) -> str:
    """The order-independent identifier of a named sequence set: the level-1
    digest of sorted_named_sequences."""
    return _core.named_set_digest(names, sequences)
