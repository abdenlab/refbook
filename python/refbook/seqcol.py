"""GA4GH sequence collection (seqcol) digests, representations and comparison.

From the spec (github.com/ga4gh/refget, docs/seqcols/README.md): canonicalize
each attribute with RFC-8785, digest it with sha512t24u; the top-level digest
covers the inherent attributes, names and sequences. SCHEMA is the schema
refbook serves: the spec's extended schema plus named_sequences and
sorted_named_sequences. Transient attributes (TRANSIENT) have a level-1 digest
but no level-2 value.

Implemented in the Rust core (refbook._core, crates/refbook-core/src/seqcol.rs).
"""

import json

from refbook import _core

INHERENT = ("names", "sequences")
TRANSIENT = tuple(_core.SEQCOL_TRANSIENT)
SCHEMA = json.loads(_core.SEQCOL_SCHEMA)


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


def level2(names: list[str], lengths: list[int], sequences: list[str]) -> dict:
    """The level-2 representation (/collection?level=2): every attribute but
    the transient ones."""
    return _core.seqcol_level2(names, lengths, sequences)


def level1_attributes(names: list[str], lengths: list[int], sequences: list[str]) -> dict:
    """The level-1 representation (/collection?level=1): the digest of every
    attribute, transient ones included."""
    return _core.seqcol_level1(names, lengths, sequences)


def top_level_digest(collection: dict) -> str | None:
    """The top-level digest of a collection given as its attributes (level 2,
    or level 1), or None without the inherent attributes."""
    return _core.seqcol_top_level_digest(collection)


def compare(a: dict, b: dict) -> dict:
    """seqcol's /comparison (spec 3.3) of two collections given as their
    level-2 attributes. Arrays are counted; an attribute given as a digest is
    listed only. Shared elements count with multiplicity; the order of fewer
    than 2 shared elements, or of unbalanced duplicates, is None."""
    return json.loads(_core.seqcol_compare(a, b))
