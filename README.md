<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/refbook-mark-dark.svg">
  <img src="docs/assets/refbook-mark.svg" alt="refbook's mark: a shelf of book spines banded like chromosomes" width="72" height="72">
</picture>

# refbook

**A catalog of human reference genome sequences, and a library to identify,
fetch and reconstruct them.**

"GRCh38" names dozens of different FASTA files. UCSC, Ensembl, GENCODE, the
GRC's own analysis sets, Broad/GATK, 1000 Genomes and iGenomes each publish a
version: different sequences included, different names and order, some bases
masked or rewritten. Two files that both say "hg38" may disagree on chr21.

refbook describes every published version as a **recipe** over the same
**roots**, the original INSDC sequences, and checks each recipe by rebuilding
the published file sequence by sequence. On top of that catalog, the library
answers practical questions:

- **Which reference is this?** Identify a BAM, CRAM, VCF, `.dict`, `.fai` or
  FASTA from its header, with an exact answer when the header carries MD5s and
  an explained ambiguity when it doesn't.
- **Give me its sequence.** Materialize any cataloged version as an Arrow
  stream, or fetch the bases at a table of intervals.
- **Decode this CRAM.** Serve sequences by MD5 to htslib's `REF_CACHE`,
  including masked or IUPAC-rewritten versions that no public MD5 server
  holds.

> Status: early. The catalog covers GRCh38; this library reads catalog format 2
> (release 0.2.0 on). It is not yet on PyPI, and its API may change.

## Install

From a clone of this repository, with [uv](https://docs.astral.sh/uv/) and a
Rust toolchain ([rustup](https://rustup.rs/); the core and its bindings in `crates/`
are built into the package by maturin). The root
`pyproject.toml` is a uv workspace of the library (`python/`, its own package,
with its own [README](python/README.md)) and the pipeline that builds the catalog
(`catalog/`):

```bash
uv sync    # the library (with DataFusion), the `refbook` command, the pipeline and dev tools
```

The catalog itself is downloaded on demand from Hugging Face
([abdenlab/refbook](https://huggingface.co/datasets/abdenlab/refbook)). Only
the small tables, about 1.3 MB, are downloaded and cached; the bases are read
with HTTP range requests as needed.

## Command line

```bash
# Which reference was this aligned to?
$ uv run refbook identify sample.cram
sample.cram
  cram, 3366 sequences, with MD5s
  EXACT: hs38dh
    hs38dh: in the order of Broad Institute Homo_sapiens_assembly38; 1000 Genomes GRCh38_full_analysis_set_plus_decoy_hla; ...

# A VCF without MD5s can only be narrowed down, and the output says how the candidates differ.
$ uv run refbook identify HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz
  vcf, 195 sequences, without MD5s
  CONSISTENT (names and lengths; no MD5s to check bases): grch38-no-alt, hg38-analysis-set
    hg38-analysis-set vs grch38-no-alt: 14 sequences differ in bases (12: as submitted (INSDC) vs IUPAC -> N; ...)
    grch38-no-alt: in the order of GRC GCA_000001405.15_GRCh38_no_alt_analysis_set; Illumina iGenomes NCBI/GRCh38

# What each sequence is, on its own evidence (root, operations, editions).
$ uv run refbook identify sample.dict --sequences
  sequences:
    chr1	248956422	CM000663.2 as submitted (INSDC), in 6 editions
    chr2	242193529	CM000664.2 (by name and length), one of 2 cataloged versions
    phiX	5386	unknown to the catalog

# Fill htslib's reference cache so a CRAM decodes without its FASTA.
$ uv run refbook populate-ref-cache sample.cram --root ~/refcache
$ REF_CACHE=~/refcache/%2s/%2s/%s samtools view sample.cram

# Serve the catalog over the GA4GH refget APIs (Sequences v2, Sequence Collections v1).
$ uv run refbook serve --port 8000
$ curl localhost:8000/sequence/insdc:CM000663.2?start=10000&end=10060
$ curl localhost:8000/comparison/B-rB7OjNDYYfvB8O1yO2mVQjYziwvppI/Q_Qsamo09hQ5KdbaJWyVX90qzu94147N
```

`identify` accepts `.fai`, `chrom.sizes`, `.dict`, SAM header text, BAM, CRAM
(2.x/3.x), VCF, FASTA and seqcol collections (level 2 JSON). It compares the header with each cataloged
**edition**, a set of named sequences whatever their order. Its verdicts are
**exact**, **consistent**, **contains** (the whole edition plus extra sequences,
such as spike-ins), **subset**, or the **closest** match with an itemized
difference. Order is reported separately: which published files list the
sequences in the header's order, which is what BAM reference IDs and sorted
files depend on.

`--sequences` (and `refbook.identify.sequences` in Python, `identifySequences`
in JS) says what each sequence is on its own: with a digest the catalog knows,
the sequence, its root, the nucleotide operations from it and the editions that
use it; from a name and length, the root and the cataloged versions it could
be; and notes on whatever disagrees (an unknown digest, a length, a name that
names another root). A FASTA's sequences are digested (MD5 and `SQ.`).

## Python

```python
import pyarrow as pa
from refbook import Catalog, identify, read_header, resolve, materialize, fetch, sequence_by_md5

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/")

# Identify a header.
result = identify(read_header("sample.bam"), cat)
print(result.best[0].verdict, [c.edition for c in result.best], result.best[0].in_order_of)

# A collection can be an edition ("hg38-analysis-set"), a published file
# ("UCSC_hg38.analysisSet", in its own order), a seqcol digest, a seqcol object,
# or any list of (name, digest) pairs whose sequences the catalog holds.
resolve(cat, "hg38-analysis-set", 0)     # its seqcol digest
resolve(cat, "hg38-analysis-set", 2)     # names, lengths, sequence digests, ancillary attributes

# Materialize (seqcol level 3): an Arrow stream, one row per sequence, with name,
# description and sequence, following the CompoSeq Sequence schema.
chr21 = materialize(cat, "hg38-analysis-set", names=["chr21"]).read_all()
mine = materialize(cat, [("mito", "c68f52674c9fb33aef52dcf399755519"),
                         ("chr21", "974dc7aec0b755b19f031418fdedf293")]).read_all()

# Fetch bases at intervals: 0-based half-open by default, polars-bio column names,
# "-" strands reverse-complemented. Also takes Polars or pandas frames.
intervals = pa.table({"chrom": ["chr1", "chrY"], "start": [1_000_000, 10_000],
                      "end": [1_000_100, 10_050], "strand": ["+", "-"]})
seqs = fetch(cat, "grch38-no-alt", intervals, strand="strand")

# Any cataloged sequence by its MD5.
chrM = sequence_by_md5(cat, "c68f52674c9fb33aef52dcf399755519")

# Compare two collections as seqcol's /comparison does.
from refbook import seqcol
seqcol.compare(resolve(cat, "grch38-no-alt", 2), resolve(cat, "hg38-analysis-set", 2))
```

`refbook serve` answers every endpoint of refget Sequences v2 and Sequence
Collections v1 (`refbook.service`). A sequence can be named by MD5, `SQ.`
digest or a namespaced alias (`insdc:CM000663.2`); an alias that names several
sequences, such as `ucsc:chr1` (the root and its IUPAC→N derivative), answers
300 with the list. Naming authorities are refget's recommended `insdc`,
`refseq`, `ensembl` and `ucsc`, plus `imgt.hla` and refbook's `grc` (GRC
Sequence-Names, e.g. `grc:HSCHR1_CTG1_UNLOCALIZED`); of these, `insdc`,
`refseq`, `ensembl` and `imgt.hla` are identifiers.org prefixes. Metadata adds refbook's account under `refbook`: the root,
the nucleotide operations from it, and the editions that use the sequence.
Collections are served with refbook's seqcol schema: the spec's extended
schema plus `named_sequences` and `sorted_named_sequences`. Against the seqcol
compliance suite in the `refget` package it passes 52 of 65 checks. The rest
are `named_sequences` appearing in comparisons (the suite expects exactly its
own attributes) and `/list/attributes` (not in the spec). Against the refget
Sequences compliance suite (ga4gh/refget-compliance-suite 2.0.0, from GitHub;
PyPI has only the v1 suite), on its test sequences (`--sequences`), every
check passes except range edge cases where the suite departs from the spec:
it expects a Range past the end to be truncated (the spec: 400), a start or
Range beyond the end to be 416 (the spec: 400), and `start` equal to the
length to be 416 (the spec allows it). Circular and TRUNC512 checks are
skipped (not supported). The API is described at `/openapi.json`.

Every sequence is built from the catalog's sequence store (a root and the
nucleotide operations applied to it) and checked against its MD5 and `SQ.`
digests. `fetch` honors polars-bio's coordinate-system metadata, so its
1-based frames are converted correctly; an interval outside its sequence is an
error unless `clip=True`.

## The catalog

The catalog (CC-BY-4.0) reproduces 17 published GRCh38 files, which reduce to
13 editions:

| Publisher | Files |
| --- | --- |
| GRC (NCBI analysis sets) | no_alt, no_alt + hs38d1, full, full + hs38d1 |
| UCSC | hg38 (initial), hg38.p14, hg38.analysisSet |
| Ensembl 116 | primary_assembly, toplevel |
| GENCODE 50 | primary_assembly, GRCh38.p14.genome |
| Broad / 1000 Genomes | Homo_sapiens_assembly38, GRCh38_full_analysis_set_plus_decoy_hla |
| Illumina iGenomes | NCBI/GRCh38, NCBI/GRCh38Decoy, UCSC/hg38, GATK/GRCh38 |

It holds 3,097 roots: GRCh38 p0–p14, the hs38d1 decoys and EBV. Their bases are
uppercase with IUPAC codes kept, in Parquet laid out for range reads. It also
holds annotation layers in root coordinates (AGP components and gaps, alt and
patch placements, named regions, the GRC hard-masks, soft-masking), aliases
across naming conventions, the sequence store (every distinct sequence and how
it is made), each edition's recipe and facets, GA4GH seqcol documents, and the
evidence of each reproduction. The tables are plain Parquet: read them with
DuckDB, Polars or pyarrow without this library. See the
[dataset card](https://huggingface.co/datasets/abdenlab/refbook) for the file
list.

The HLA alleles in the Broad and 1000 Genomes references are IPD-IMGT/HLA
3.18.0, which may not be redistributed. The catalog records their identifiers
and digests only, and the library reads their bases from the IMGT/HLA release.

## How it works

- **Roots** are the lossless source sequences, keyed by INSDC accession.version
  and checked against ENA's refget server.
- **Layers** annotate roots in their own coordinates.
- **Recipes** turn roots into a published file: select, mask, change the
  alphabet (IUPAC→N) and rename. They are data, in `catalog/books/<book>/recipes/*.json`. Order
  isn't part of a recipe: each published file's order is recorded as observed.
- **Reconstruction is the verification.** A file counts as cataloged only when
  its recipe reproduces it, sequence by sequence: names, lengths, MD5 and `SQ.`
  digests. The rebuild also turned up details that no publisher documents: the
  order UCSC uses, which patches Ensembl leaves out, and how bwakit chose its HLA
  alleles.

[`docs/SCOPE.md`](docs/SCOPE.md) is the design document, and
[`docs/GLOSSARY.md`](docs/GLOSSARY.md) defines its terms.

## Building the catalog

The pipeline in `catalog/` builds one catalog from every book's original
downloads; it runs on the lab server and needs about 15 GB. It is a set of
[doit](https://pydoit.org) tasks (`catalog/dodo.py`), each calling plain
functions in `catalog/refbook_pipeline/`, and doit reruns a task only when the
bytes of something it reads (the code included) have changed.

```bash
cd catalog
mkdir -p output && ln -s /path/to/a/mirror output/raw   # optional: share the downloads between checkouts
uv run doit fetch:GRCh38.p14         # download a source into output/raw/ (each is fetched only when asked)
uv run doit                          # lock every source, build the catalog, run the checks
uv run doit check_roots_ena          # the root check against ENA's refget server (3,097 requests; a release needs it)
uv run doit export --version <version> --out output/releases/<version>
uv run doit list                     # every task; `uv run doit info roots` says why one would run
```

What the catalog is built from is data:

- `catalog/sources.toml` declares every **source**: a set of files from one
  publisher (an NCBI assembly directory, files on a host, GenBank records,
  a GitHub tree), what it's used for (an input, a reproduction target, or
  both), which of its files hold sequences, and any external collection.
- `catalog/books/<book>/` is a **book**: an assembly, every release of it, and
  its add-ons (`book.toml`), the recipes that reproduce its published
  editions (`recipes/`, one file per publisher) and their labels
  (`editions.json`). `book.toml` also holds what is particular to the book:
  the report disagreements accepted, where its hard-mask is defined, where
  names come from beyond the assembly reports, and the checks' choices.
- `catalog/locks/<source>.lock` pins each source to exact bytes: every file's
  size, sha256, Last-Modified and URL. Locking checks each file against its
  publisher's checksum list, where there is one, and against the lock;
  anything new or changed refuses until you accept it with
  `uv run doit lock:<source> --update`. On the first run there is no lock,
  so the files are trusted and the lock is written. Publisher checksums that
  disagree with what the publisher serves are listed, with the reason, in
  `<source>.exceptions.tsv` beside the lock. A task reads a source only after
  its lock passes, and records the locks it read.

The build is in `catalog/output/build/` (gitignored; `REFBOOK_RAW` and
`REFBOOK_BUILD` override the paths): `books/<book>/` for what is built per
book, `catalog/` for the shared catalog, one directory per task, each written
whole or not at all, with `catalog/catalog.json` indexing it, so
`Catalog("catalog/output/build/catalog")` opens a build directly; and
`checks/` for the checks' results. The checks run on the tables the catalog
publishes and record the hash of each, and the export refuses unless every
check passed on exactly the files it ships, every task read the current
locks, and (for a release) the root check consulted ENA.

Each module's docstring says what it reads, writes and checks.

## Repository layout

| Path | Contents |
| --- | --- |
| `crates/` | The Rust crates: `refbook-core` (refget digests and canonicalization, seqcol, nucleotide operations, the recipe compiler; no I/O), and its bindings, `refbook-py` (pyo3, built by maturin as `refbook._core`) and `refbook-wasm` (wasm-bindgen, for `js/`) |
| `python/` | The Python package (`pyproject.toml`, `README.md`, and `tests/`, with real ENCODE, gnomAD and GIAB headers as fixtures) |
| `python/refbook/` | The Python library: `catalog`, `resolve`, `identify`, `materialize`, `fetch`, `refcache`, `parse`, `refget`, `seqcol`, `store`, `service`, `blocks`, `remote` |
| `js/` | The npm package `@abdenlab/refbook`: the TypeScript front end (`js/src/`) over the core's wasm bindings (`crates/refbook-wasm`). Built with `pnpm build` at the root (needs the `wasm32-unknown-unknown` target and `wasm-bindgen-cli` 0.2.130) |
| `app/` | The web app (Svelte 5, Vite, TypeScript; the data layer in `app/src/data/` is plain TypeScript): the catalog, each edition's recipe, identity, files and exports, and its sequences' bases, built in the browser from the roots with the core's operations; identify (paste a `.fai`, `.dict`, SAM header, VCF contigs or FASTA: each sequence identified by the core, in the browser); compare (two editions or published files: seqcol's comparison, and what differs sequence by sequence); and design (a recipe editor: the choices always in view, with a naming convention per sequence group; tabs for analysis goals, the JSON, details, and the catalog ranked by closeness to load an edition's recipe; compiled live in the browser by the core, with a strip saying whether it is a cataloged edition, its ID and exports, and a link that carries it). `pnpm dev` at the root serves it with the build in `catalog/output/build/catalog` at `/catalog/`; `VITE_CATALOG_URL` (or `?catalog=` on the page) points it elsewhere |
| `catalog/` | The pipeline: `dodo.py` (the doit tasks), `refbook_pipeline/` (the functions they call), `sources.toml`, `locks/`, `books/<book>/` (each book's declaration, recipes and labels), `tests/` |
| `catalog/output/` | Gitignored: `raw/` (the downloads, or a symlink to a mirror) and `build/` (the tasks' outputs) |
| `docs/` | `SCOPE.md` (the design document) and `GLOSSARY.md` |

## Development

```bash
uv sync
uv run pytest                       # python/tests (the library) and catalog/tests (the pipeline)
pnpm install && pnpm build && pnpm test   # js/ and app/: a pnpm workspace (pnpm-workspace.yaml)
```

Tests that need a catalog read `$REFBOOK_CATALOG` (default: the build in
`catalog/output/build/catalog`; a release works too) and are skipped without one. The wasm
cross-check (`catalog/tests/test_wasm.py`) is skipped until `js/` is built.

## License

The code is released under the [MIT License](LICENSE). The catalog data is
CC-BY-4.0.
