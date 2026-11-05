"""Identify a reference from its sequence list.

sequences(header, cat) says what each sequence is, on its own evidence (the
Rust core's identify): with a digest the store knows, the sequence, its root,
the nucleotide operations from it, and the flavors that use it; otherwise,
from a name that names a root of that length, the root and its cognates
(the stored sequences it could be); and notes on whatever disagrees.

identify(header, cat), below, summarizes a whole header against the flavors.
It has two layers:

- Per sequence: each header sequence with an MD5 is looked up in the sequence
  store, which says what it is ("CM000663.2 with IUPAC -> N"). This needs no
  flavor at all.
- Per collection: the header (names, lengths, and MD5s where the format
  carries them) is compared with every cataloged flavor as a named sequence
  set, so order plays no part in the verdict:

  - exact        the same names, each with the same length, and the same MD5
                 if the header has them
  - consistent   the same names and lengths, but the header has no MD5s, so
                 flavors that differ only in bases cannot be told apart
  - contains     the whole flavor, unchanged, plus other sequences
                 (spike-ins, other genomes)
  - subset       every header sequence is in the flavor, unchanged, but the
                 flavor has more (e.g. chr1-22, X, Y only)
  - partial      everything else, with the differences from that flavor

  Order is reported separately: the flavor's targets whose order the header
  follows. That matters to formats that refer to sequences by position (BAM
  reference IDs, coordinate-sorted files).

Sequences are paired by name first, then (for renamed headers) by what they
are: an MD5 we know, or a name that is an alias of a root.
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from refbook import _core, seqcol
from refbook.catalog import Catalog, Seq
from refbook.parse import Entry, Header


def sequences(x: Header | list, cat: Catalog) -> list[dict]:
    """What each entry is: one identity per entry, in order (see the module
    docstring). x is a Header, or a list of Entry or of dicts with any of
    name, length, md5 and sq."""
    entries = x.entries if isinstance(x, Header) else x
    rows = []
    for e in entries:
        d = e if isinstance(e, dict) else vars(e)
        rows.append((d.get("name"), d.get("length"), d.get("md5"), d.get("sq")))
    return json.loads(_core.identify_sequences(rows, cat.identify_tables()))


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
    in_order_of: list[str] = field(default_factory=list)               # targets whose order it follows


def _root_of(e: Entry, cat: Catalog, roots_here: set[str]) -> str | None:
    sq = cat.sq_by_md5.get(e.md5) if e.md5 else None
    if sq is not None:
        return cat.sequence[sq]["root_id"]
    hits = cat.by_alias.get(e.name, set()) & roots_here
    if len(hits) == 1:
        return next(iter(hits))
    return None


def compare(header: Header, flavor: str, cat: Catalog) -> Comparison:
    seqs = cat.manifests[flavor]
    by_name = {s.name: s for s in seqs}
    by_root = {s.root_id: s for s in seqs}
    pairs, unpaired = [], []
    for e in header.entries:
        if e.name in by_name:
            pairs.append((e, by_name[e.name], False))
        else:
            unpaired.append(e)
    used = {s.name for _, s, _ in pairs}
    c = Comparison(flavor, "partial", 0.0)
    for e in unpaired:
        root = _root_of(e, cat, set(by_root))
        s = by_root.get(root) if root else None
        if s is not None and s.name not in used and s.length == e.length:
            pairs.append((e, s, True))
            used.add(s.name)
        else:
            c.extra.append(e)
    c.missing = [s for s in seqs if s.name not in used]
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
    # Which of the flavor's targets list the paired sequences in the header's order.
    header_order = [s.name for _, s, _ in sorted(pairs, key=lambda p: header.entries.index(p[0]))]
    for t, r in cat.targets.items():
        if r["flavor"] == flavor:
            shared = set(header_order)
            if [n for n in cat.target_order[t] if n in shared] == header_order:
                c.in_order_of.append(t)
    # A renamed match counts a little less, so plain name matches win ties.
    weighted = good - 0.1 * len(c.renamed)
    c.score = weighted / (len(header.entries) + len(seqs) - good) if seqs else 0.0
    unchanged = not (c.different_bases or c.different_length or c.renamed)
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
    sequences: dict[str, str]         # header name -> SQ. digest, for each known MD5
    unknown: list[str]                # header names whose MD5 the store doesn't know
    seqcol_digest: str | None         # the header's collection, if every MD5 is known
    seqcol_matches: list[str]         # stored collections (flavors, targets) with that digest
    ambiguity: list[str]              # how indistinguishable candidates differ


def _base_differences(a: str, b: str, cat: Catalog) -> str | None:
    sa = {s.root_id: s.sha512t24u for s in cat.manifests[a]}
    sb = {s.root_id: s.sha512t24u for s in cat.manifests[b]}
    diff = [r for r in sb if r in sa and sa[r] != sb[r]]
    if not diff:
        return None
    hows = Counter(f"{cat.how(sa[r])} vs {cat.how(sb[r])}" for r in diff)
    return f"{len(diff)} sequences differ in bases (" + "; ".join(f"{n}: {h}" for h, n in hows.items()) + ")"


def identify(header: Header, cat: Catalog) -> Result:
    ranked = sorted((compare(header, f, cat) for f in cat.flavors),
                    key=lambda c: (RANK[c.verdict], -c.matched if c.verdict == "contains" else 0,
                                   len(c.missing), -c.score, c.flavor))
    top = RANK[ranked[0].verdict]
    best = [c for c in ranked if RANK[c.verdict] == top and c.verdict != "partial"] or ranked[:1]
    if best[0].verdict == "contains":
        best = [c for c in best if c.matched == best[0].matched]

    known = {e.name: cat.sq_by_md5[e.md5] for e in header.entries if e.md5 in cat.sq_by_md5}
    unknown = [e.name for e in header.entries if e.md5 and e.md5 not in cat.sq_by_md5]
    digest, matches = None, []
    if header.has_md5 and len(known) == len(header.entries):
        digest, _ = seqcol.digests([e.name for e in header.entries], [e.length for e in header.entries],
                                   [known[e.name] for e in header.entries])
        matches = sorted(n for d, n in cat.named.items() if d == digest)
        matches += sorted(t for t, r in cat.targets.items()
                          if r["seqcol_digest"] == digest and t not in matches)

    ambiguity = []
    consistent = [c.flavor for c in best if c.verdict == "consistent"]
    for other in consistent[1:]:
        d = _base_differences(consistent[0], other, cat)
        if d:
            ambiguity.append(f"{other} vs {consistent[0]}: {d}")
    return Result(header, best, ranked, known, unknown, digest, matches, ambiguity)


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
            sq = cat.sq_by_md5.get(e.md5) if e.md5 else None
            root = cat.sequence[sq]["root_id"] if sq else None
            if root is None:
                hits = cat.by_alias.get(e.name, set())
                root = next(iter(hits)) if len(hits) == 1 else None
                if root and cat.root_length.get(root) != e.length:
                    known["named like cataloged sequences, but other lengths"].append(e.name)
                    continue
            known[cat.kind(root) if root else "unknown to the catalog"].append(e.name)
        out.append("only in header: " + ", ".join(
            f"{len(v)} {k} ({', '.join(v[:limit])}{', ...' if len(v) > limit else ''})" for k, v in known.items()))
    for e, s in c.different_bases[:limit]:
        sq = cat.sq_by_md5.get(e.md5)
        if sq is not None and cat.sequence[sq]["root_id"] == s.root_id:
            seen = cat.flavors_with(sq)
            where = f"; as in {', '.join(seen[:2])}" if seen else ""
            out.append(f"{e.name}: a different version of the same sequence: header has it {cat.how(sq)}, "
                       f"{c.flavor} has it {cat.how(s.sha512t24u)}{where}")
        else:
            out.append(f"{e.name}: different bases (header MD5 {e.md5} is not a version of {s.root_id} we know)")
    if len(c.different_bases) > limit:
        out.append(f"... {len(c.different_bases) - limit} more sequences with different bases")
    for e, s in c.different_length[:limit]:
        out.append(f"{e.name}: length {e.length:,}, but {c.flavor} has {s.length:,}")
    if c.verdict in ("exact", "consistent") and not c.in_order_of:
        out.append("in an order none of this flavor's targets uses")
    return out
