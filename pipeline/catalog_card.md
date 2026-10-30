---
license: cc-by-4.0
pretty_name: refbook
tags:
  - genomics
  - reference-genome
  - GRCh38
  - refget
  - seqcol
configs:
  - config_name: flavor_sequences
    data_files: flavor_sequences.parquet
  - config_name: recipes
    data_files: recipes.parquet
  - config_name: roots
    data_files: roots.parquet
  - config_name: aliases
    data_files: aliases.parquet
---

# refbook

**One catalog for the many published versions of the human reference genome.**

"GRCh38" names dozens of different FASTA files: UCSC, Ensembl, GENCODE, NCBI's
analysis sets, Broad/GATK, 1000 Genomes, iGenomes. They differ in which sequences
they contain, how they name and order them, and whether some bases are masked or
rewritten. refbook describes every one of them as a **recipe** applied to the same
**roots**, the original INSDC sequences, and counts a version as cataloged only
when its recipe reproduces the published file sequence by sequence.

Release {version} covers {n_flavors} published GRCh38 files, which reduce to {n_sets}
distinct sequence sets.

{flavor_table}

## What is in it

All coordinates are 0-based, half-open. Sequence digests follow GA4GH refget
(MD5 and `SQ.` sha512t24u); collection digests follow GA4GH seqcol.

| File | Contents |
| --- | --- |
| `roots.parquet` | The {n_roots:,} roots: GRCh38 p0–p14 ({n_grch38:,} sequences), the hs38d1 decoys ({n_decoys:,}) and EBV, with length and refget digests |
| `roots_external.parquet` | IMGT/HLA 3.18.0 alleles, by identifier and digest only (see below) |
| `root_blocks.parquet` | The bases of every root, uppercase with IUPAC codes kept, in 64 kb blocks, laid out for HTTP range reads |
| `assembly_members.parquet` | Every row of every GRCh38 and hs38d1 assembly report |
| `aliases.parquet` | Names of each root in the GenBank, RefSeq, UCSC, GRC, Ensembl and IMGT namespaces |
| `layer_*.parquet` | Annotations in root coordinates: AGP components and gaps, alt/patch placements, named regions (centromeres, PARs), the GRC hard-masks, IUPAC positions, N runs, NCBI soft-masking |
| `recipes.parquet` | Each published file's recipe and seqcol digest |
| `flavor_sequences.parquet` | Each published file's sequences in order: name, root, length, MD5, `SQ.` digest |
| `family_tree.json` | How the files relate: each one's nearest relative and the exact difference |
| `seqcol/*.json` | A seqcol (level 2) document per published file |
| `evidence/` | What each published file was observed to contain, and the root verification reports |
| `catalog.json` | The release manifest: every file's size, sha256 and role |

Read any table directly with DuckDB, Polars or pyarrow, for example:

```python
import polars as pl
base = "https://huggingface.co/datasets/abdenlab/refbook/resolve/v{version}/"
fs = pl.read_parquet(base + "flavor_sequences.parquet")
fs.filter(pl.col("name") == "chr21").select("flavor", "md5").unique("md5")
```

A Python library that identifies a header against this catalog and fetches bases
by region is in development.

## Sources and licensing

The catalog tables are released under CC-BY-4.0. The underlying sequences are
INSDC records (GenBank), distributed by NCBI without restrictions on use. The
published files used as reproduction targets belong to their publishers and are
not redistributed here; the `evidence/` tables record only their sequence names,
lengths and digests.

IMGT/HLA alleles are not redistributed. The IPD-IMGT/HLA Database is licensed
under CC BY-NoDerivs, and its maintainers ask not to be mirrored. This catalog
records only allele identifiers, names and digests, with links to the IMGT/HLA
release. If you use the HLA entries, please cite IPD-IMGT/HLA (Barker et al.,
*Nucleic Acids Research* 2026; Robinson et al., *Tissue Antigens* 2000).

## Versions

Each release is a tag (`v{version}`, …). Pin URLs to a tag, for example
`https://huggingface.co/datasets/abdenlab/refbook/resolve/v{version}/catalog.json`.
