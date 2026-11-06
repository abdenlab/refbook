"""Build the aliases tables: every root's names across naming conventions, and
every stored sequence's names as refget serves them.

Writes to build/grch38/50_aliases/:

- aliases.parquet   root_id, namespace, alias, source. GenBank, RefSeq, UCSC
                    and GRC Sequence-Name from the assembly reports (GenBank
                    also for the roots fetched from INSDC by accession, such
                    as EBV); Ensembl
                    from UCSC's p14 chromAlias.txt, checked against the names
                    in the reproduced Ensembl targets; UCSC-style names for
                    EBV and the decoys from the GRC analysis sets; IMGT allele
                    names and accessions for HLA.
- sequence_aliases.parquet   sha512t24u, naming_authority, alias: the
                    `aliases` of refget's /sequence/:id/metadata. A root as
                    submitted has all its root's aliases. A derivative (a root
                    with nucleotide operations applied) has only the names
                    editions give it that are names of its root (UCSC, GRC,
                    Ensembl, IMGT allele), never an accession: an INSDC or
                    RefSeq accession identifies the bases as submitted.
                    Namespaces become refget naming authorities (genbank ->
                    insdc; both IMGT namespaces -> imgt.hla).

(Editions, targets and seqcol documents are built by 41_editions.py.)

Usage: uv run python -I catalog/50_aliases.py [--assembly A] [--raw DIR] [--build DIR]
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I leaves this directory out
import layout

STEP = "50_aliases"
AUTHORITY = {"genbank": "insdc", "refseq": "refseq", "ucsc": "ucsc", "ensembl": "ensembl", "grc": "grc",
             "imgt": "imgt.hla", "imgt_accession": "imgt.hla"}
NAMES = {"ucsc", "grc", "ensembl", "imgt"}  # namespaces of names, not of accessions
CHROMALIAS = "hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/p14/hg38.p14.chromAlias.txt"


def main() -> None:
    ap = argparse.ArgumentParser()
    args = layout.arguments(ap)
    build = args.build
    with layout.step_output(build, STEP) as out:
        run(args.raw, build, out)
        layout.record_inputs(out, STEP, layout.targets_lock(args.assembly))  # chromAlias.txt


def run(raw: Path, build: Path, out: Path) -> None:

    targets = defaultdict(list)
    for s in pq.read_table(layout.path(build, "reproduced.parquet")).to_pylist():
        targets[s["target"]].append(s)

    # Aliases.
    aliases = set()
    for m in pq.read_table(layout.path(build, "assembly_members.parquet")).to_pylist():
        acc, src = m["genbank_accession"], f"{m['assembly_accession']} assembly report"
        aliases.add((acc, "genbank", acc, src))
        if m["refseq_accession"]:
            aliases.add((acc, "refseq", m["refseq_accession"], src))
        if m["ucsc_name"]:
            aliases.add((acc, "ucsc", m["ucsc_name"], src))
        if m["assembly_name"].startswith("GRCh38"):
            aliases.add((acc, "grc", m["sequence_name"], src))
    # Roots fetched from INSDC one by one (EBV): their accession is their GenBank name.
    for r in pq.read_table(layout.path(build, "roots.parquet"), columns=["root_id", "source"]).to_pylist():
        if "eutils.ncbi.nlm.nih.gov" in r["source"] and f"id={r['root_id']}&" in r["source"]:
            aliases.add((r["root_id"], "genbank", r["root_id"], "INSDC record"))
    ensembl = {}
    lines = (raw / CHROMALIAS).read_text().splitlines()
    header = lines[0].lstrip("# ").split("\t")
    for line in lines[1:]:
        rec = dict(zip(header, line.split("\t")))
        if rec.get("ensembl") and rec.get("genbank"):
            ensembl[rec["genbank"]] = rec["ensembl"]
            aliases.add((rec["genbank"], "ensembl", rec["ensembl"], "UCSC hg38.p14.chromAlias.txt"))
    seen = {}
    for f in ("Ensembl116_primary_assembly", "Ensembl116_toplevel"):
        for s in targets.get(f, []):
            seen[s["root_id"]] = s["name"]
    mismatch = {a: (ensembl.get(a), n) for a, n in seen.items() if ensembl.get(a) not in (None, n)}
    if mismatch:
        print(f"note: UCSC chromAlias ensembl names differ from Ensembl 116 for {len(mismatch)} roots, "
              f"e.g. {list(mismatch.items())[:3]}", file=sys.stderr)
    for a, n in seen.items():
        if a not in ensembl:
            aliases.add((a, "ensembl", n, "Ensembl 116 FASTA (reproduced)"))
    for s in targets.get("GRCh38_full_plus_hs38d1_analysis_set", []):
        if s["root_id"] == "AJ507799.2" or s["name"].endswith("_decoy"):
            aliases.add((s["root_id"], "ucsc", s["name"], "GRC analysis sets (reproduced)"))
    ext = build / "11_external_roots" / "roots_external.parquet"
    if ext.exists():
        for e in pq.read_table(ext).to_pylist():
            aliases.add((e["root_id"], "imgt", e["name"], e["collection"]))
            aliases.add((e["root_id"], "imgt_accession", e["accession"], e["collection"]))
    cols = list(zip(*sorted(aliases)))
    table = pa.table(dict(zip(("root_id", "namespace", "alias", "source"), cols)))
    pq.write_table(table, out / "aliases.parquet", compression="zstd")
    counts = defaultdict(int)
    for ns in table["namespace"].to_pylist():
        counts[ns] += 1
    print(f"aliases.parquet: {table.num_rows} rows {dict(counts)}", file=sys.stderr)

    seq_aliases = sequence_aliases(build, aliases)
    cols = list(zip(*sorted(seq_aliases)))
    pq.write_table(pa.table(dict(zip(("sha512t24u", "naming_authority", "alias"), cols))),
                   out / "sequence_aliases.parquet", compression="zstd")
    print(f"sequence_aliases.parquet: {len(seq_aliases)} rows for "
          f"{len({a[0] for a in seq_aliases})} sequences", file=sys.stderr)


def sequence_aliases(build: Path, aliases: set) -> set[tuple[str, str, str]]:
    """(sha512t24u, naming_authority, alias) for every stored sequence; see the module docstring."""
    by_root = defaultdict(set)
    for root, ns, alias, _ in aliases:
        by_root[root].add((ns, alias))
    edition_names = defaultdict(set)
    for m in pq.read_table(layout.path(build, "manifests.parquet"), columns=["name", "sha512t24u"]).to_pylist():
        edition_names[m["sha512t24u"]].add(m["name"])
    out = set()
    for s in pq.read_table(layout.path(build, "sequences.parquet"),
                           columns=["sha512t24u", "root_id", "operations"]).to_pylist():
        sq, root = s["sha512t24u"], s["root_id"]
        if not s["operations"]:
            out |= {(sq, AUTHORITY[ns], alias) for ns, alias in by_root[root]}
        else:
            names = edition_names[sq]
            out |= {(sq, AUTHORITY[ns], alias) for ns, alias in by_root[root] if ns in NAMES and alias in names}
    return out


if __name__ == "__main__":
    main()
