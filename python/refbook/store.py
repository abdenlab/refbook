"""The sequence store: find a sequence by any identifier, describe it, read its bases.

The functions refget Sequences v2 needs, over a catalog:

- find(cat, identifier)     the stored sequences an identifier names: a digest
                            (MD5, `SQ.`, either with its `md5:`/`ga4gh:`
                            namespace) or a namespaced alias (`insdc:CM000663.2`,
                            `ucsc:chr1`). An alias can name several sequences
                            (`ucsc:chr1` names the root and its derivatives).
- metadata(cat, sq)         /sequence/:id/metadata: md5, ga4gh, length and
                            aliases, plus refbook's account of the sequence: its
                            root, the nucleotide operations from it, and the
                            editions that use it under which names.
- subsequence(cat, sq, ...) bases [start, end) of a stored sequence, reading
                            only the root blocks that hold them.
"""

import re

from refbook.catalog import Catalog
from refbook.materialize import Bases, apply_operations

MD5 = re.compile(r"[0-9a-fA-F]{32}")


def find(cat: Catalog, identifier: str) -> list[str]:
    """The `SQ.` digests of the stored sequences an identifier names, sorted."""
    ns, sep, rest = identifier.partition(":")
    if not sep:
        ns, rest = None, identifier
    if ns in (None, "md5") and MD5.fullmatch(rest):
        sq = cat.sq_by_md5.get(rest.lower())
        return [sq] if sq else []
    if ns in (None, "ga4gh") and rest.startswith("SQ."):
        return [rest] if rest in cat.sequence else []
    if ns is None:
        return []
    return sorted(cat.by_identifier().get((ns, rest), ()))


def metadata(cat: Catalog, sq: str) -> dict:
    """A stored sequence's refget metadata ("metadata", as the spec defines it)
    and refbook's account of it ("refbook")."""
    rec = cat.sequence[sq]
    aliases = sorted(cat.sequence_aliases().get(sq, ()))
    return {
        "metadata": {
            "md5": rec["md5"],
            "ga4gh": sq,
            "length": rec["length"],
            "aliases": [{"alias": a, "naming_authority": auth} for auth, a in aliases],
        },
        "refbook": {
            "root_id": rec["root_id"],
            "operations": list(rec["operations"]),
            "editions": [{"edition": f, "name": n} for f, n in cat.edition_names().get(sq, [])],
        },
    }


def subsequence(cat: Catalog, sq: str, start: int, end: int, bases: Bases) -> bytes:
    """Bases [start, end) (0-based, half-open) of a stored sequence: its root's
    bases there, with the sequence's nucleotide operations applied."""
    rec = cat.sequence[sq]
    if not 0 <= start <= end <= rec["length"]:
        raise ValueError(f"{start}-{end} is outside {sq} (length {rec['length']})")
    root = rec["root_id"]
    return apply_operations(cat, root, rec["operations"], bases.slice(root, start, end), start)
