# The catalog

The catalog is a set of Parquet tables and JSON documents, published as [abdenlab/refbook](https://huggingface.co/datasets/abdenlab/refbook). Both the library and the web app read it directly from there (or a local copy).

## Releases

Each release is a tag on the dataset. Pin URLs to a tag:

```
https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/catalog.json
```

`catalog.json` is the release's manifest: every file's size, sha256 and role,
and the catalog format the library checks before reading. Release 0.2.0 is
format 2, with three books: GRCh37, GRCh38 and T2T-CHM13.

## What is in a release

All coordinates are 0-based, half-open. Sequence digests follow GA4GH refget
(MD5 and `SQ.` sha512t24u); collection digests follow GA4GH seqcol.

| File | Contents |
| --- | --- |
| `roots.parquet` | The 3,417 roots, with length and refget digests |
| `roots_external.parquet` | The IMGT/HLA 3.18.0 alleles, by identifier and digest only |
| `root_blocks.parquet` | The bases of every root, uppercase with IUPAC codes kept, in 64 kb blocks laid out for HTTP range reads |
| `assembly_members.parquet` | Every row of every assembly report each book draws on, with its book |
| `aliases.parquet` | Names of each root in the GenBank, RefSeq, UCSC, GRC, Ensembl and IMGT namespaces; a name that means something only within one assembly (`chrM` is the Yoruba sequence in hg19, rCRS in hg38) carries its book |
| `layer_*.parquet` | The [layers](model.md#layers): AGP components and gaps, placements and padding, regions, masks, IUPAC positions, runs of N, soft-masking |
| `sequences.parquet` | The sequence store: every distinct sequence, by `SQ.` digest and MD5, with the root and operations it is made from |
| `derivations.parquet` | Every known way to make each sequence, and the editions that use it |
| `editions.parquet` | Each edition: book, label, identifier, seqcol digest, recipe and facets |
| `manifests.parquet` | Each edition's sequences: name, root, operations, length, MD5, `SQ.` digest |
| `targets.parquet` | Each published file: its edition, publisher, name, URL and seqcol digest |
| `target_sequences.parquet` | Each published file's order of sequences |
| `collections/*.json` | Seqcol level-2 documents for every edition and published file, named by digest |
| `evidence/` | What each published file was observed to contain, the source locks, and the root checks |

The [dataset card](https://huggingface.co/datasets/abdenlab/refbook) lists every
edition, with its publishers and files.

## Reading it directly

```python
import polars as pl

base = "https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/"
m = pl.read_parquet(base + "manifests.parquet")

# Every distinct chr21 among the editions, and what was done to it.
m.filter(pl.col("name") == "chr21").select("edition", "md5", "operations").unique("md5")
```

## Licensing

The catalog tables are CC-BY-4.0. The sequences are INSDC records, distributed by NCBI without restrictions on use.

The one root with no INSDC record, the hs37d5 decoy, is 1000 Genomes' concatenation of segments of other sequences, recorded with its make-up. The published files used as reproduction targets belong to their publishers and are not redistributed: the catalog records only their sequence names, lengths and digests.

The IPD-IMGT/HLA alleles are licensed CC BY-NoDerivs, and their maintainers ask not to be mirrored, so the catalog records only their identifiers and digests. If you use the HLA entries, please cite IPD-IMGT/HLA.
