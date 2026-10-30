"""Identify a reference from its sequence list.

Compare a header (names, lengths, and MD5s where the format carries them)
with every reproduced flavor in the catalog. Each flavor gets a verdict:

- exact             same names, lengths and order, and same MD5s if the
                    header has them
- consistent        same names, lengths and order, but the header has no MD5s,
                    so flavors that differ only in bases cannot be told apart
- contains          the whole flavor, unchanged and in order, plus other
                    sequences (spike-ins, other genomes)
- subset            every header sequence is in the flavor, unchanged and in
                    order, but the flavor has more (e.g. chr1-22, X, Y only)
- partial           everything else, with the differences from that flavor

Sequences are paired by name first, then (for renamed or reordered headers)
by what they are: an MD5 we know, or a name that is an alias of a root.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from refbook.catalog import Catalog, Seq
from refbook.parse import Entry, Header
from refbook import seqcol


@dataclass
class Comparison:
    flavor: str
    verdict: str                      # exact | consistent | contains | subset | partial
    score: float                      # Jaccard of matching sequences
    matched: int = 0
    renamed: list[tuple[str, str]] = field(default_factory=list)       # (header, flavor)
    different_bases: list[tuple[Entry, Seq]] = field(default_factory=list)
    different_length: list[tuple[Entry, Seq]] = field(default_factory=list)
    extra: list[Entry] = field(default_factory=list)                   # in header only
    missing: list[Seq] = field(default_factory=list)                   # in flavor only
    order_differs: bool = False


def _root_of(e: Entry, cat: Catalog, roots_here: set[str]) -> str | None:
    if e.md5 and e.md5 in cat.variant:
        return cat.variant[e.md5][0]
    hits = cat.by_alias.get(e.name, set()) & roots_here
    if len(hits) == 1:
        return next(iter(hits))
    return None


def compare(header: Header, flavor: str, cat: Catalog) -> Comparison:
    seqs = cat.flavors[flavor]
    by_name = {s.name: s for s in seqs}
    by_root = {s.root_id: s for s in seqs}
    pairs, unpaired = [], []
    for e in header.entries:
        if e.name in by_name:
            pairs.append((e, by_name[e.name], False))
        else:
            unpaired.append(e)
    used = {id(s) for _, s, _ in pairs}
    c = Comparison(flavor, "partial", 0.0)
    for e in unpaired:
        root = _root_of(e, cat, set(by_root))
        s = by_root.get(root) if root else None
        if s is not None and id(s) not in used and s.length == e.length:
            pairs.append((e, s, True))
            used.add(id(s))
        else:
            c.extra.append(e)
    c.missing = [s for s in seqs if id(s) not in used]
    good = 0
    for e, s, renamed in pairs:
        if e.length != s.length:
            c.different_length.append((e, s))
            continue
        if e.md5 and e.md5 != s.md5:
            c.different_bases.append((e, s))
            continue
        good += 1
        if renamed:
            c.renamed.append((e.name, s.name))
    c.matched = good
    order_h = [s.position for _, s, _ in sorted(pairs, key=lambda p: header.entries.index(p[0]))]
    c.order_differs = order_h != sorted(order_h)
    # A renamed match counts a little less, so plain name matches win ties.
    weighted = good - 0.1 * len(c.renamed)
    c.score = weighted / (len(header.entries) + len(seqs) - good) if seqs else 0.0
    unchanged = not (c.different_bases or c.different_length or c.order_differs or c.renamed)
    if unchanged and not c.extra and not c.missing:
        c.verdict = "exact" if header.has_md5 else "consistent"
    elif unchanged and c.extra and not c.missing:
        c.verdict = "contains"
    elif unchanged and c.missing and not c.extra:
        c.verdict = "subset"
    return c


RANK = {"exact": 0, "consistent": 1, "contains": 2, "subset": 3, "partial": 4}


@dataclass
class Result:
    header: Header
    best: list[Comparison]            # exact or consistent matches, else the closest
    ranked: list[Comparison]
    seqcol_digest: str | None
    seqcol_flavors: list[str]
    ambiguity: list[str]              # how indistinguishable candidates differ


def _base_differences(a: str, b: str, cat: Catalog) -> str | None:
    sa = {s.root_id: s.md5 for s in cat.flavors[a]}
    diff = [r for r, m in ((s.root_id, s.md5) for s in cat.flavors[b]) if r in sa and sa[r] != m]
    if not diff:
        return None
    hows = Counter()
    for r in diff:
        how_a = cat.variant.get(sa[r], (r, "?"))[1]
        how_b = cat.variant.get(next(s.md5 for s in cat.flavors[b] if s.root_id == r), (r, "?"))[1]
        hows[f"{how_a} vs {how_b}"] += 1
    return f"{len(diff)} sequences differ in bases (" + "; ".join(f"{n}: {h}" for h, n in hows.items()) + ")"


def identify(header: Header, cat: Catalog) -> Result:
    ranked = sorted((compare(header, f, cat) for f in cat.flavors),
                    key=lambda c: (RANK[c.verdict], -c.matched if c.verdict == "contains" else 0,
                                   len(c.missing), -c.score, c.flavor))
    top = RANK[ranked[0].verdict]
    best = [c for c in ranked if RANK[c.verdict] == top and c.verdict != "partial"] or ranked[:1]
    if best[0].verdict == "contains":
        best = [c for c in best if c.matched == best[0].matched]

    digest, digest_flavors = None, []
    sha = {}
    for seqs in cat.flavors.values():
        for s in seqs:
            sha[s.md5] = s.sha512t24u
    if header.has_md5 and all(e.md5 in sha for e in header.entries):
        digest, _ = seqcol.digests([e.name for e in header.entries], [e.length for e in header.entries],
                                   [sha[e.md5] for e in header.entries])
        digest_flavors = sorted(f for f, r in cat.recipes.items() if r["seqcol_digest"] == digest)

    ambiguity = []
    consistent = [c.flavor for c in best if c.verdict == "consistent"]
    for other in consistent[1:]:
        d = _base_differences(consistent[0], other, cat)
        if d:
            ambiguity.append(f"{other} vs {consistent[0]}: {d}")
    return Result(header, best, ranked, digest, digest_flavors, ambiguity)


def describe(c: Comparison, cat: Catalog, limit: int = 3) -> list[str]:
    """Plain-language differences between the header and one flavor."""
    out = []
    if c.renamed:
        ex = ", ".join(f"{h} = {f}" for h, f in c.renamed[:limit])
        out.append(f"{len(c.renamed)} sequences have other names ({ex}{', ...' if len(c.renamed) > limit else ''})")
    if c.missing:
        kinds = Counter(cat.kind(s.root_id) for s in c.missing)
        out.append("not in header: " + ", ".join(f"{n} {k}" for k, n in kinds.most_common()))
    if c.extra:
        known = defaultdict(list)
        for e in c.extra:
            root = cat.variant.get(e.md5, (None,))[0] if e.md5 else None
            if root is None:
                hits = cat.by_alias.get(e.name, set())
                root = next(iter(hits)) if len(hits) == 1 else None
                if root and cat.root_length.get(root) != e.length:
                    known["named like GRCh38 sequences, but other lengths"].append(e.name)
                    continue
            known[cat.kind(root) if root else "unknown to the catalog"].append(e.name)
        out.append("only in header: " + ", ".join(
            f"{len(v)} {k} ({', '.join(v[:limit])}{', ...' if len(v) > limit else ''})" for k, v in known.items()))
    for e, s in c.different_bases[:limit]:
        root, how = cat.variant.get(e.md5, (None, None))
        if root == s.root_id:
            seen = sorted(cat.flavors_with_md5.get(e.md5, ()))
            where = f"; as in {', '.join(seen[:2])}" if seen else ""
            out.append(f"{e.name}: a different version of the same sequence: header has it {how}, "
                       f"{c.flavor} has it {cat.variant.get(s.md5, (None, '?'))[1]}{where}")
        else:
            out.append(f"{e.name}: different bases (header MD5 {e.md5} is not a version of {s.root_id} we know)")
    if len(c.different_bases) > limit:
        out.append(f"... {len(c.different_bases) - limit} more sequences with different bases")
    for e, s in c.different_length[:limit]:
        out.append(f"{e.name}: length {e.length:,}, but {c.flavor} has {s.length:,}")
    if c.order_differs:
        out.append("order differs")
    return out
