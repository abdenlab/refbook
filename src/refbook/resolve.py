"""Resolve sequence collections against a catalog, at any seqcol level.

A collection can be given as a flavor label, a target, a seqcol top-level
digest (looked up in the collection store), a flavor's named-sequence-set id,
a level-1 or level-2 representation, or a named sequence set: (name, digest)
pairs, where each digest is an `SQ.` digest or an MD5. Nothing requires it to
be a cataloged flavor; every sequence just has to be in the sequence store.

    resolve(cat, collection, 0)   the top-level digest
    resolve(cat, collection, 1)   one digest per attribute
    resolve(cat, collection, 2)   the arrays (names, lengths, sequences) and
                                  the ancillary attributes
    resolve(cat, collection, 3)   the named sequences with their bases, as an
                                  Arrow stream (materialize)

A named sequence set has no order; it is listed in canonical order (by name,
code point).
"""

from collections.abc import Iterable
from dataclasses import dataclass

from refbook import seqcol
from refbook.catalog import Catalog


class UnknownSequences(KeyError):
    """A collection names sequences the sequence store doesn't hold."""


@dataclass(frozen=True)
class Collection:
    """A collection at level 2. `label` is the flavor or target it is, if any."""
    names: tuple[str, ...]
    lengths: tuple[int, ...]
    sequences: tuple[str, ...]    # SQ. digests
    label: str | None = None

    @property
    def digest(self) -> str:
        return seqcol.digests(list(self.names), list(self.lengths), list(self.sequences))[0]

    def __len__(self) -> int:
        return len(self.names)


def _from_store(cat: Catalog, names: list[str], digests: list[str], label: str | None) -> Collection:
    sqs, unknown = [], []
    for n, d in zip(names, digests):
        sq = d if d.startswith("SQ.") else cat.sq_by_md5.get(d)
        if sq not in cat.sequence:
            unknown.append(n)
        sqs.append(sq)
    if unknown:
        raise UnknownSequences(f"{len(unknown)} sequences are not in the sequence store, "
                               f"e.g. {', '.join(unknown[:5])}")
    if len(set(names)) != len(names):
        raise ValueError("a collection uses a name twice")
    return Collection(tuple(names), tuple(cat.sequence[sq]["length"] for sq in sqs), tuple(sqs), label)


def collection(cat: Catalog, x) -> Collection:
    """The level-2 collection that x names or represents (see the module docstring)."""
    if isinstance(x, Collection):
        return x
    if isinstance(x, str):
        if x in cat.flavor_by_id:
            x = cat.flavor_by_id[x]
        if x in cat.manifests:
            seqs = cat.manifests[x]
            return Collection(tuple(s.name for s in seqs), tuple(s.length for s in seqs),
                              tuple(s.sha512t24u for s in seqs), x)
        if x in cat.target_order:
            by_name = {s.name: s for s in cat.manifests[cat.targets[x]["flavor"]]}
            seqs = [by_name[n] for n in cat.target_order[x]]
            return Collection(tuple(s.name for s in seqs), tuple(s.length for s in seqs),
                              tuple(s.sha512t24u for s in seqs), x)
        stored = cat.stored_collection(x)
        if stored is None:
            raise KeyError(f"{x}: not a flavor, target or stored collection")
        return _from_store(cat, stored["names"], stored["sequences"], cat.named.get(x))
    if isinstance(x, dict):
        if all(isinstance(v, str) for v in x.values()):
            return _from_level1(cat, x)
        if "names" not in x or "sequences" not in x:
            raise ValueError("a level-2 collection needs names and sequences")
        c = _from_store(cat, list(x["names"]), list(x["sequences"]), None)
        if "lengths" in x and list(x["lengths"]) != list(c.lengths):
            raise ValueError("the collection's lengths disagree with its sequences")
        return Collection(c.names, c.lengths, c.sequences, cat.named.get(c.digest))
    if not isinstance(x, Iterable):
        raise TypeError(f"not a collection: {x!r}")
    pairs = sorted(x, key=lambda p: p[0].encode())
    c = _from_store(cat, [n for n, _ in pairs], [d for _, d in pairs], None)
    named = cat.flavor_by_id.get(seqcol.named_set_digest(list(c.names), list(c.sequences)))
    return Collection(c.names, c.lengths, c.sequences, named)


def _from_level1(cat: Catalog, level1: dict) -> Collection:
    """A level-1 representation, by its names and sequences digests, among the
    collections the catalog stores."""
    want = (level1.get("names"), level1.get("sequences"))
    for digest in cat.named:
        c = collection(cat, digest)
        _, l1 = seqcol.digests(list(c.names), list(c.lengths), list(c.sequences))
        if (l1["names"], l1["sequences"]) == want:
            return c
    raise KeyError("no stored collection has these level-1 digests")


def resolve(cat: Catalog, x, level: int = 2, **materialize_options):
    """A collection at seqcol level 0, 1, 2, or 3 (with bases)."""
    c = collection(cat, x)
    names, lengths, sqs = list(c.names), list(c.lengths), list(c.sequences)
    if level == 3:
        from refbook.materialize import materialize
        return materialize(cat, c, **materialize_options)
    top, level1 = seqcol.digests(names, lengths, sqs)
    if level == 0:
        return top
    ancillary = seqcol.ancillary(names, lengths, sqs)
    if level == 1:
        return {**level1, **{k: seqcol.level1(v) for k, v in ancillary.items()}}
    if level == 2:
        return {"names": names, "lengths": lengths, "sequences": sqs, **ancillary}
    raise ValueError(f"level must be 0, 1, 2 or 3, not {level!r}")
