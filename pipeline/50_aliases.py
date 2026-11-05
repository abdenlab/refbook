"""Build the aliases table: every root's names across naming conventions.

Writes REGISTRY/build/grch38/50_aliases/aliases.parquet: root_id, namespace, alias,
source. GenBank, RefSeq, UCSC and GRC Sequence-Name from the assembly reports;
Ensembl from UCSC's p14 chromAlias.txt, checked against the names in the
reproduced Ensembl targets; UCSC-style names for EBV and the decoys from the
GRC analysis sets; IMGT allele names for HLA.

(Flavors, targets and seqcol documents are built by 41_flavors.py.)

Usage: uv run python -I pipeline/50_aliases.py REGISTRY_DIR [--assembly grch38]
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
CHROMALIAS = "hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/p14/hg38.p14.chromAlias.txt"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("--assembly", default=layout.ASSEMBLY)
    args = ap.parse_args()
    build = layout.build_dir(args.registry, args.assembly)
    with layout.step_output(build, STEP) as out:
        run(layout.raw_dir(args.registry), build, out)


def run(raw: Path, build: Path, out: Path) -> None:

    flavors = defaultdict(list)
    for s in pq.read_table(layout.path(build, "flavor_sequences.parquet")).to_pylist():
        flavors[s["flavor"]].append(s)

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
        for s in flavors.get(f, []):
            seen[s["root_id"]] = s["name"]
    mismatch = {a: (ensembl.get(a), n) for a, n in seen.items() if ensembl.get(a) not in (None, n)}
    if mismatch:
        print(f"note: UCSC chromAlias ensembl names differ from Ensembl 116 for {len(mismatch)} roots, "
              f"e.g. {list(mismatch.items())[:3]}", file=sys.stderr)
    for a, n in seen.items():
        if a not in ensembl:
            aliases.add((a, "ensembl", n, "Ensembl 116 FASTA (reproduced)"))
    for s in flavors.get("GRCh38_full_plus_hs38d1_analysis_set", []):
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


if __name__ == "__main__":
    main()
