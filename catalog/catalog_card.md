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
  - config_name: editions
    data_files: editions.parquet
  - config_name: manifests
    data_files: manifests.parquet
  - config_name: targets
    data_files: targets.parquet
  - config_name: sequences
    data_files: sequences.parquet
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

Release {version} covers {n_editions} published GRCh38 files, which reduce to {n_sets}
**editions**: distinct sets of named sequences, whatever their order. Each edition
has a refbook label; the publishers' names for its files are its aliases.

{edition_table}

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
| `layer_*.parquet` | Annotations in root coordinates: AGP components and gaps, alt/patch placements and the padding they give, named regions (centromeres, PARs), chrY's PARs, the GRC hard-masks, IUPAC positions, N runs, NCBI soft-masking |
| `sequences.parquet` | The sequence store: every distinct sequence (each root, and each derivative: masked, IUPAC→N, padded or oriented), by `SQ.` digest and MD5, with the root and nucleotide operations it is made from (and, for a padded or oriented one, the book whose placement it follows) |
| `derivations.parquet` | Every known way to make each sequence, and the editions that use it |
| `editions.parquet` | Each edition: label, identifier (an order-independent digest of its named sequences), seqcol digest, recipe, and facets (contents, operations, naming) |
| `manifests.parquet` | Each edition's sequences: name, root, operations, length, MD5, `SQ.` digest |
| `targets.parquet` | Each published file: its edition, publisher, name, URL and seqcol digest |
| `target_sequences.parquet` | Each published file's order of sequences |
| `collections/*.json` | Seqcol (level 2) documents for every edition and published file, named by digest |
| `evidence/` | What each published file was observed to contain, and the root verification reports |
| `catalog.json` | The release manifest: every file's size, sha256 and role |

Read any table directly with DuckDB, Polars or pyarrow, for example:

```python
import polars as pl
base = "https://huggingface.co/datasets/abdenlab/refbook/resolve/v{version}/"
m = pl.read_parquet(base + "manifests.parquet")
m.filter(pl.col("name") == "chr21").select("edition", "md5", "operations").unique("md5")
```

The `refbook` Python library (github.com/abdenlab/refbook) identifies a header
against this catalog, and resolves, materializes and fetches any collection
whose sequences it holds.

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
