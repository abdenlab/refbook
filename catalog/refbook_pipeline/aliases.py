"""Aliases: every root's names across naming conventions, and every stored sequence's names as refget serves them.

- aliases.parquet   book, root_id, namespace, alias, source. GenBank, RefSeq and UCSC names, and GRC sequence names
                    (for members of the book's releases), from the assembly reports; GenBank for the roots fetched
                    from INSDC one by one (EBV); and what each book declares (book.toml [[aliases]]: Ensembl names
                    from a chromAlias file and its reproduced Ensembl targets; UCSC names for its add-ons and loose
                    roots from a reproduced target); IMGT allele names and accessions for the external roots. A name
                    that means something only within a book (UCSC, GRC, Ensembl: chrM is another sequence in hg19
                    than in hg38) carries the book; an accession or an IMGT name, which mean the same everywhere,
                    carries none.
- sequence_aliases.parquet   sha512t24u, naming_authority, alias: the `aliases` of refget's /sequence/:id/metadata.
                    A root as submitted has all its root's aliases. A derivative (a root with nucleotide operations)
                    has only the names editions give it that are names of its root (UCSC, GRC, Ensembl, IMGT
                    allele), never an accession: an accession identifies the bases as submitted. Namespaces become
                    refget naming authorities (genbank -> insdc; both IMGT namespaces -> imgt.hla).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import Refused

AUTHORITY = {"genbank": "insdc", "refseq": "refseq", "ucsc": "ucsc", "ensembl": "ensembl", "grc": "grc",
             "imgt": "imgt.hla", "imgt_accession": "imgt.hla"}
NAMES = {"ucsc", "grc", "ensembl", "imgt"}        # namespaces of names, not of accessions
BOOK_SCOPED = {"ucsc", "grc", "ensembl"}           # names whose meaning depends on the book


def read_chromalias(path: Path) -> list[dict[str, str]]:
    """A UCSC chromAlias.txt: for each row, its names by column (genbank, ensembl, refseq, ...)."""
    lines = path.read_text().splitlines()
    header = lines[0].lstrip("# ").split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def book_aliases(book: str, members: list[dict], releases: set[str], declared: list[dict],
                 reproduced: dict[str, list[dict]], chromalias: dict[str, Path],
                 roots: set[str] | None = None) -> tuple[set, list[str]]:
    """One book's aliases, (book, root_id, namespace, alias, source), and its notes. `chromalias` gives the raw path
    of each declared chromAlias file, by its source/file key. A chromAlias row counts only for an accession that is
    one of the catalog's `roots` (hg19.p13.plusMT's lists the Yoruba chrM by its RefSeq accession, NC_001807.4, in
    its GenBank column); the others are noted."""
    out, notes = set(), []
    for m in members:
        acc, src = m["genbank_accession"], f"{m['assembly_accession']} assembly report"
        out.add((None, acc, "genbank", acc, src))
        if m["refseq_accession"]:
            out.add((None, acc, "refseq", m["refseq_accession"], src))
        if m["ucsc_name"]:
            out.add((book, acc, "ucsc", m["ucsc_name"], src))
        if m["assembly_name"] in releases:
            out.add((book, acc, "grc", m["sequence_name"], src))
    in_releases = {m["genbank_accession"] for m in members if m["assembly_name"] in releases}
    have = defaultdict(dict)  # namespace -> {genbank accession: name}, from the chromAlias files
    for d in declared:
        ns = d["namespace"]
        if "chromalias" in d:
            path = chromalias[f"{d['chromalias']['source']}/{d['chromalias']['file']}"]
            strays = []
            for rec in read_chromalias(path):
                if rec.get(ns) and rec.get("genbank"):
                    if roots is not None and rec["genbank"] not in roots:
                        strays.append(f"{rec['genbank']} ({rec[ns]})")
                        continue
                    have[ns][rec["genbank"]] = rec[ns]
                    out.add((book, rec["genbank"], ns, rec[ns], d["label"]))
            if strays:
                notes.append(f"{d['label']}: names for accessions that are no root, left out: {', '.join(strays)}")
        else:
            missing = [t for t in d["targets"] if t not in reproduced]
            if missing:
                raise Refused(f"{book}: aliases from targets it doesn't reproduce: {missing}")
            seen = {}
            for t in d["targets"]:
                for s in reproduced[t]:
                    seen[s["root_id"]] = s["name"]
            if d["roots"] == "fill":
                mismatch = {a: (have[ns].get(a), n) for a, n in seen.items() if have[ns].get(a) not in (None, n)}
                if mismatch:
                    notes.append(f"{ns} names in {d['label']} differ from the chromAlias file's for {len(mismatch)} "
                                 f"roots, e.g. {list(mismatch.items())[:3]}")
                out |= {(book, a, ns, n, d["label"]) for a, n in seen.items() if a not in have[ns]}
            elif d["roots"] == "outside_releases":
                out |= {(book, a, ns, n, d["label"]) for a, n in seen.items() if a not in in_releases}
            else:
                raise Refused(f"{book}: aliases roots must be fill or outside_releases, not {d['roots']!r}")
    return out, notes


def global_aliases(roots: list[dict], external: list[dict]) -> set:
    """Aliases that mean the same in every book: the GenBank accession of a root fetched from INSDC by itself, and
    the IMGT names of the external roots."""
    out = set()
    for r in roots:
        if "eutils.ncbi.nlm.nih.gov" in r["source"] and f"id={r['root_id']}&" in r["source"]:
            out.add((None, r["root_id"], "genbank", r["root_id"], "INSDC record"))
    for e in external:
        out.add((None, e["root_id"], "imgt", e["name"], e["collection"]))
        out.add((None, e["root_id"], "imgt_accession", e["accession"], e["collection"]))
    return out


def sequence_aliases(aliases: set, manifests: list[dict], sequences: list[dict]) -> set[tuple[str, str, str]]:
    """(sha512t24u, naming_authority, alias) for every stored sequence; see the module docstring."""
    by_root = defaultdict(set)
    for _, root, ns, alias, _ in aliases:
        by_root[root].add((ns, alias))
    names = defaultdict(set)
    for m in manifests:
        names[m["sha512t24u"]].add(m["name"])
    out = set()
    for s in sequences:
        sq, root = s["sha512t24u"], s["root_id"]
        if not s["operations"]:
            out |= {(sq, AUTHORITY[ns], alias) for ns, alias in by_root[root]}
        else:
            out |= {(sq, AUTHORITY[ns], alias) for ns, alias in by_root[root] if ns in NAMES and alias in names[sq]}
    return out
