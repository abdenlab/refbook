---
license: cc-by-4.0
pretty_name: refbook
tags:
  - genomics
  - reference-genome
  - GRCh38
  - GRCh37
  - hg19
  - T2T-CHM13
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

"GRCh38" names dozens of different FASTA files, and "hg19" or "b37" as many
again: UCSC, Ensembl, GENCODE, the GRC's analysis sets, Broad/GATK, 1000 Genomes,
iGenomes. They differ in which sequences they contain, how they name and order
them, and whether some bases are masked or rewritten. refbook describes every one
of them as a **recipe** applied to the same **roots**, the original INSDC
sequences, and counts a version as cataloged only when its recipe reproduces the
published file sequence by sequence.

Release {version} covers {n_editions} published files, which reduce to {n_sets}
**editions**: distinct sets of named sequences, whatever their order. Each edition
has a refbook label; the publishers' names for its files are its aliases.

The catalog is organized in {n_books} **books**, one per assembly: every release
of the assembly, with the sequences its editions add from outside it, and the
editions made from them. One set of roots serves every book: a sequence GRCh37
and GRCh38 both carry (rCRS, some unplaced scaffolds, GRCh37 patches that became
GRCh38 alt loci) is one root.

{book_table}

{edition_table}

## What is in it

All coordinates are 0-based, half-open. Sequence digests follow GA4GH refget
(MD5 and `SQ.` sha512t24u); collection digests follow GA4GH seqcol.

| File | Contents |
| --- | --- |
| `roots.parquet` | The {n_roots:,} roots, with length and refget digests: every sequence of every release of each assembly (withdrawn patches included), and those editions add from outside it: the hs38d1 decoys, EBV, hg19's Yoruba mitochondrion and the hs37d5 decoy |
| `roots_external.parquet` | IMGT/HLA 3.18.0 alleles, by identifier and digest only (see below) |
| `root_blocks.parquet` | The bases of every root, uppercase with IUPAC codes kept, in 64 kb blocks, laid out for HTTP range reads |
| `assembly_members.parquet` | Every row of every assembly report each book draws on, with its book |
| `aliases.parquet` | Names of each root in the GenBank, RefSeq, UCSC, GRC, Ensembl and IMGT namespaces; a name that means something only within an assembly (`chrM` is the Yoruba sequence in hg19, rCRS in hg38) carries its book |
| `layer_*.parquet` | Annotations in root coordinates: AGP components and gaps, alt/patch placements and the padding they give (by book: a scaffold can be placed in two assemblies), named regions (centromeres, PARs), chrY's PARs, the GRC hard-masks, IUPAC positions, N runs, NCBI soft-masking, and the masks read from published masked files where no file gives them (T2T-CHM13's acrocentric and 5S rDNA masks, named by the regions T2T-Ref's README lists) |
| `sequences.parquet` | The sequence store: every distinct sequence (each root, and each derivative: masked, IUPAC→N, padded or oriented), by `SQ.` digest and MD5, with the root and nucleotide operations it is made from (and, for a padded or oriented one, the book whose placement it follows) |
| `derivations.parquet` | Every known way to make each sequence, and the editions that use it |
| `editions.parquet` | Each edition: book, label, identifier (an order-independent digest of its named sequences), seqcol digest, recipe, and facets (contents, operations, naming) |
| `manifests.parquet` | Each edition's sequences: name, root, operations, length, MD5, `SQ.` digest |
| `targets.parquet` | Each published file: its edition, publisher, name, URL and seqcol digest |
| `target_sequences.parquet` | Each published file's order of sequences |
| `collections/*.json` | Seqcol (level 2) documents for every edition and published file, named by digest |
| `evidence/` | What each published file was observed to contain, the source locks, and the root verification reports |
| `catalog.json` | The release manifest: every file's size, sha256 and role |

Four nucleotide operations make every derivative. Two write `N` and keep
coordinates: a **mask** (a layer's spans: the GRC hard-mask, chrY's PARs) and
**IUPAC→N**. Two lay an alt scaffold or patch out by its placement on its
parent: **pad** writes it in the parent's coordinates, `N` before and after, as
Ensembl's GRCh37 files do; **orient** only reverse-complements one placed on
the minus strand, as GENCODE 19 does.

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
INSDC records (GenBank), distributed by NCBI without restrictions on use; the
one root with no INSDC record, the hs37d5 decoy (`1000G:hs37d5`), is 1000
Genomes' concatenation of segments of other sequences, with its make-up as its
AGP. The published files used as reproduction targets belong to their
publishers and are not redistributed here; the `evidence/` tables record only
their sequence names, lengths and digests.

IMGT/HLA alleles are not redistributed. The IPD-IMGT/HLA Database is licensed
under CC BY-NoDerivs, and its maintainers ask not to be mirrored. This catalog
records only allele identifiers, names and digests, with links to the IMGT/HLA
release. If you use the HLA entries, please cite IPD-IMGT/HLA (Barker et al.,
*Nucleic Acids Research* 2026; Robinson et al., *Tissue Antigens* 2000).

## Versions

Each release is a tag (`v{version}`, …). Pin URLs to a tag, for example
`https://huggingface.co/datasets/abdenlab/refbook/resolve/v{version}/catalog.json`.

## Citation

Each catalog release has its own DOI, minted after it is published. A DOI
links to this repository's current state, so cite the version with it:

| Release | DOI |
| --- | --- |
| 0.2.0 | [10.57967/hf/11657](https://doi.org/10.57967/hf/11657) |

The refbook software is archived on Zenodo:
[10.5281/zenodo.24268815](https://doi.org/10.5281/zenodo.24268815) (all
versions).
