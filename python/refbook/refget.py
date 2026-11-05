"""Refget sequence digests, and the canonicalization they are computed over.

Refget digests the uppercased bases with everything outside A-Z removed.
refbook is stricter: whitespace is removed, lowercase is uppercased, and any
other character outside A-Z is an error rather than silently dropped, so the
bases stored, the length and the digests always come from the same string.

Implemented in the Rust core (refbook._core, crates/refbook-core/src/refget.rs).
"""

from refbook import _core


class NonCanonicalBase(ValueError):
    """A sequence holds a character that is neither A-Z, a-z nor whitespace."""


def remove_whitespace(seq: bytes) -> bytes:
    return _core.remove_whitespace(seq)


def canonical_bases(seq: bytes) -> bytes:
    """The bases refget digests: whitespace removed, uppercased, A-Z only."""
    try:
        return _core.canonical_bases(seq)
    except ValueError as e:
        raise NonCanonicalBase(str(e)) from None


def digests(bases: bytes) -> tuple[str, str]:
    """(MD5, SQ. digest) of canonical bases."""
    return _core.digests(bases)


def scan(seq: bytes) -> dict:
    """One sequence (whitespace removed): its canonical bases, md5, sha512t24u,
    lowercase runs (`lower`), N-runs (`n_runs`), both 0-based half-open, and
    IUPAC positions with their codes (`iupac`)."""
    try:
        return _core.scan(seq)
    except ValueError as e:
        raise NonCanonicalBase(str(e)) from None
