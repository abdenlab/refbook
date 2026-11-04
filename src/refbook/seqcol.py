"""GA4GH sequence collection (seqcol) digests.

From the spec (github.com/ga4gh/refget, docs/seqcols/README.md): canonicalize
each attribute with RFC-8785, digest it with sha512t24u; the top-level digest
covers the inherent attributes, names and sequences.
"""

import base64
import hashlib
import json

INHERENT = ("names", "sequences")


def canonical(item) -> bytes:
    """RFC-8785 for our data: ASCII keys, no floats, integers within 64 bits."""
    return json.dumps(item, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
                      sort_keys=True).encode("utf8")


def sha512t24u(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha512(data).digest()[:24]).decode("ascii")


def level1(value) -> str:
    """The level-1 digest of an attribute's level-2 value."""
    return sha512t24u(canonical(value))


def digests(names: list[str], lengths: list[int], sequences: list[str]) -> tuple[str, dict]:
    """(top-level digest, level-1 digests) of a collection; sequences are SQ. ids."""
    obj = {"lengths": lengths, "names": names, "sequences": sequences}
    level1s = {k: level1(v) for k, v in obj.items()}
    return sha512t24u(canonical({k: level1s[k] for k in INHERENT})), level1s


def ancillary(names: list[str], lengths: list[int], sequences: list[str]) -> dict:
    """Level-2 values of the non-inherent attributes refbook computes.

    From the spec: name_length_pairs (5.1), sorted_name_length_pairs (5.2) and
    sorted_sequences (5.3). named_sequences is the per-element digest of
    {"name", "sequence"} that footnote F1 suggests; sorted_named_sequences is
    refbook's: those digests sorted, as 5.2 sorts name-length pairs. Its
    level-1 digest identifies the named sequence set, whatever the order.
    """
    pairs = [{"name": n, "length": n_bp} for n, n_bp in zip(names, lengths)]
    named = [level1({"name": n, "sequence": s}) for n, s in zip(names, sequences)]
    return {"name_length_pairs": pairs,
            "sorted_name_length_pairs": sorted(level1(p) for p in pairs),
            "sorted_sequences": sorted(sequences),
            "named_sequences": named,
            "sorted_named_sequences": sorted(named)}


def named_set_digest(names: list[str], sequences: list[str]) -> str:
    """The order-independent identifier of a named sequence set: the level-1
    digest of sorted_named_sequences."""
    return level1(sorted(level1({"name": n, "sequence": s}) for n, s in zip(names, sequences)))
