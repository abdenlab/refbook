"""Build the catalog tables that sit on top of the reproduced flavors.

Writes to REGISTRY/build/grch38:

- recipes.parquet   one row per flavor: the recipe (JSON), its source file,
                    the published URL, what it was checked against (the FASTA
                    content, or the publisher's .dict), sequence count, total
                    length, and its GA4GH seqcol digests (top level, plus the
                    level-1 digests of names, lengths and sequences)
- seqcol/<flavor>.json   the level-2 seqcol object (names, lengths, sequences)
- aliases.parquet   root_id, namespace, alias, source: GenBank, RefSeq, UCSC and
                    GRC Sequence-Name from the assembly reports; Ensembl from
                    UCSC's p14 chromAlias.txt, checked against the names in the
                    reproduced Ensembl flavors; UCSC-style names for EBV and the
                    decoys from the GRC analysis sets; IMGT allele names for HLA

Seqcol digests follow the GA4GH spec (github.com/ga4gh/refget,
docs/seqcols/README.md): RFC-8785 canonical JSON of each attribute, digested
with sha512t24u; the top level digests the inherent attributes, names and
sequences. The spec's worked example is checked first.

Usage: uv run python -I pipeline/build_catalog.py REGISTRY_DIR recipes/*.json
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from refbook import seqcol

CHROMALIAS = "hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/p14/hg38.p14.chromAlias.txt"


def check_spec_example() -> None:
    obj = {"lengths": [248956422, 242193529, 198295559], "names": ["chr1", "chr2", "chr3"],
           "sequences": ["SQ.2YnepKM7OkBoOrKmvHbGqguVfF9amCST", "SQ.lwDyBi432Py-7xnAISyQlnlhWDEaBPv2",
                         "SQ.Eqk6_SvMMDCc6C-uEfickOUWTatLMDQZ"]}
    top, level1 = seqcol.digests(obj["names"], obj["lengths"], obj["sequences"])
    want = {"lengths": "5K4odB173rjao1Cnbk5BnvLt9V7aPAa2", "names": "g04lKdxiYtG3dOGeUC5AdKEifw65G0Wp",
            "sequences": "rD29ZKmEqwwHRXjiQ36p6UMZQ5hemmsb"}
    if level1 != want or top != "sjNNwm4zov3Dl0FRWbRTcZwzqrTQKIqL":
        sys.exit(f"seqcol implementation fails the spec example: {top} {level1}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("registry", type=Path)
    ap.add_argument("recipes", type=Path, nargs="+")
    args = ap.parse_args()
    build = args.registry / "build" / "grch38"
    check_spec_example()

    flavors = defaultdict(list)
    for s in pq.read_table(build / "flavor_sequences.parquet").to_pylist():
        flavors[s["flavor"]].append(s)

    rows = []
    (build / "seqcol").mkdir(exist_ok=True)
    for path in args.recipes:
        for r in json.loads(path.read_text())["recipes"]:
            f = r["flavor"]
            seqs = sorted(flavors.get(f, []), key=lambda s: s["position"])
            if not seqs:
                sys.exit(f"{f}: not in flavor_sequences.parquet (run run_recipes.py)")
            obj = {"lengths": [s["length"] for s in seqs], "names": [s["name"] for s in seqs],
                   "sequences": [s["sha512t24u"] for s in seqs]}
            top, level1 = seqcol.digests(obj["names"], obj["lengths"], obj["sequences"])
            (build / "seqcol" / f"{f}.json").write_text(json.dumps(obj) + "\n")
            checked = r.get("observed_from", r["published"])
            rows.append({
                "flavor": f, "recipe_file": path.name, "published": r["published"],
                "checked_against": checked,
                "checked_by": ".dict M5" if checked.endswith(".dict") else "FASTA content",
                "n_sequences": len(seqs), "total_length": sum(obj["lengths"]),
                "seqcol_digest": top, "seqcol_names": level1["names"],
                "seqcol_lengths": level1["lengths"], "seqcol_sequences": level1["sequences"],
                "recipe": json.dumps(r, sort_keys=True),
            })
    pq.write_table(pa.Table.from_pylist(rows), build / "recipes.parquet", compression="zstd")
    print(f"recipes.parquet: {len(rows)} flavors; seqcol/ written", file=sys.stderr)
    by_digest = defaultdict(list)
    for row in rows:
        by_digest[row["seqcol_digest"]].append(row["flavor"])
    for d, fs in by_digest.items():
        print(f"  {d}  {', '.join(fs)}", file=sys.stderr)

    # Aliases.
    aliases = set()
    for m in pq.read_table(build / "assembly_members.parquet").to_pylist():
        acc, src = m["genbank_accession"], f"{m['assembly_accession']} assembly report"
        aliases.add((acc, "genbank", acc, src))
        if m["refseq_accession"]:
            aliases.add((acc, "refseq", m["refseq_accession"], src))
        if m["ucsc_name"]:
            aliases.add((acc, "ucsc", m["ucsc_name"], src))
        if m["assembly_name"].startswith("GRCh38"):
            aliases.add((acc, "grc", m["sequence_name"], src))
    ensembl = {}
    lines = (args.registry / "raw" / CHROMALIAS).read_text().splitlines()
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
    ext = build / "roots_external.parquet"
    if ext.exists():
        for e in pq.read_table(ext).to_pylist():
            aliases.add((e["root_id"], "imgt", e["name"], e["collection"]))
            aliases.add((e["root_id"], "imgt_accession", e["accession"], e["collection"]))
    cols = list(zip(*sorted(aliases)))
    table = pa.table(dict(zip(("root_id", "namespace", "alias", "source"), cols)))
    pq.write_table(table, build / "aliases.parquet", compression="zstd")
    counts = defaultdict(int)
    for ns in table["namespace"].to_pylist():
        counts[ns] += 1
    print(f"aliases.parquet: {table.num_rows} rows {dict(counts)}", file=sys.stderr)


if __name__ == "__main__":
    main()
