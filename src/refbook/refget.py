"""Refget sequence digests, and the canonicalization they are computed over.

Refget digests the uppercased bases with everything outside A-Z removed.
refbook is stricter: whitespace is removed, lowercase is uppercased, and any
other character outside A-Z is an error rather than silently dropped, so the
bases stored, the length and the digests always come from the same string.
"""

import hashlib
import re

from refbook.seqcol import sha512t24u

WHITESPACE = b" \t\r\n\v\f"
NOT_AZ = re.compile(rb"[^A-Z]")


class NonCanonicalBase(ValueError):
    """A sequence holds a character that is neither A-Z, a-z nor whitespace."""


def remove_whitespace(seq: bytes) -> bytes:
    return seq.translate(None, WHITESPACE)


def canonical_bases(seq: bytes) -> bytes:
    """The bases refget digests: whitespace removed, uppercased, A-Z only."""
    up = remove_whitespace(seq).upper()
    if m := NOT_AZ.search(up):
        raise NonCanonicalBase(f"character {m.group()!r} at position {m.start()}")
    return up


def digests(bases: bytes) -> tuple[str, str]:
    """(MD5, SQ. digest) of canonical bases."""
    return hashlib.md5(bases).hexdigest(), "SQ." + sha512t24u(bases)
