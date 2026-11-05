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

# Fill htslib's reference cache so a CRAM decodes without its FASTA.
$ uv run refbook populate-ref-cache sample.cram --root ~/refcache
$ REF_CACHE=~/refcache/%2s/%2s/%s samtools view sample.cram
```

`identify` accepts `.fai`, `chrom.sizes`, `.dict`, SAM header text, BAM, CRAM
(2.x/3.x), VCF and FASTA. It compares the header with each cataloged
**flavor**, a set of named sequences whatever their order. Its verdicts are
**exact**, **consistent**, **contains** (the whole flavor plus extra sequences,
such as spike-ins), **subset**, or the **closest** match with an itemized
difference. Order is reported separately: which published files list the
sequences in the header's order, which is what BAM reference IDs and sorted
files depend on.

## Python

```python
import pyarrow as pa
from refbook import Catalog, identify, read_header, resolve, materialize, fetch, sequence_by_md5

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.2.0/")

# Identify a header.
result = identify(read_header("sample.bam"), cat)
print(result.best[0].verdict, [c.flavor for c in result.best], result.best[0].in_order_of)

# A collection can be a flavor ("hg38-analysis-set"), a published file
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
```

Every sequence is built from the catalog's sequence store (a root and the
nucleotide operations applied to it) and checked against its MD5 and `SQ.`
digests. `fetch` honors polars-bio's coordinate-system metadata, so its
1-based frames are converted correctly; an interval outside its sequence is an
error unless `clip=True`.

## The catalog

The catalog (CC-BY-4.0) reproduces 17 published GRCh38 files, which reduce to
13 flavors:

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
it is made), each flavor's recipe and facets, GA4GH seqcol documents, and the
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
  alphabet (IUPAC→N) and rename. They are data, in `catalog/assemblies/grch38/recipes/*.json`. Order
  isn't part of a recipe: each published file's order is recorded as observed.
- **Reconstruction is the verification.** A file counts as cataloged only when
  its recipe reproduces it, sequence by sequence: names, lengths, MD5 and `SQ.`
  digests. The rebuild also turned up details that no publisher documents: the
  order UCSC uses, which patches Ensembl leaves out, and how bwakit chose its HLA
  alleles.

[`docs/SCOPE.md`](docs/SCOPE.md) is the design document, and
[`docs/GLOSSARY.md`](docs/GLOSSARY.md) defines its terms.

## Building the catalog

The pipeline in `catalog/` builds a catalog from the original downloads; it
runs on the lab server and needs about 15 GB.

```bash
mkdir -p catalog/output && ln -s /path/to/a/mirror catalog/output/raw   # optional: share the downloads between checkouts
catalog/00_fetch_inputs.sh           # INSDC assemblies, hs38d1, EBV, GRC analysis sets, IMGT/HLA; checks the inputs lock
catalog/01_fetch_targets.sh          # published files used as reproduction targets; checks the targets lock
uv run python -I catalog/10_roots.py
uv run python -I catalog/11_external_roots.py
uv run python -I catalog/20_layers.py
uv run python -I catalog/30_observe.py
uv run python -I catalog/40_recipes.py
uv run python -I catalog/41_flavors.py
uv run python -I catalog/50_aliases.py
uv run python -I catalog/60_check_gaps.py
uv run python -I catalog/61_check_roots.py
uv run python -I catalog/62_check_materialize.py
uv run python -I catalog/70_export.py catalog/output/releases/<version> <version>
```

Steps read the downloads in `catalog/output/raw/` and write
`catalog/output/build/<assembly>/` (`catalog/output/` is gitignored; override
with `--raw`/`--build` or `REFBOOK_RAW`/`REFBOOK_BUILD`).
Their declarative inputs are in `catalog/assemblies/<assembly>/`: the recipes, the
cataloged flavors, and the locks.

Each step writes its own directory, `catalog/output/build/grch38/<NN_step>/`,
assembled under
a temporary name and renamed into place when it finishes, so a rerun replaces
exactly that step's outputs. A step finds earlier steps' tables by name, and
`catalog/output/build/grch38/catalog.json` indexes them all, so
`Catalog("catalog/output/build/grch38")` opens a build directly. Every step takes `--assembly` (only `grch38` is defined so
far). `catalog/layout.py` holds the layout and the GRCh38 releases, and
`catalog/engine.py` the recipe engine.

The checks (60-62) record their results with the hashes of the tables they
read, and the export refuses unless every check passed on exactly the files it
ships.

The fetch steps pin their downloads with **locks**
(`catalog/assemblies/grch38/locks/inputs.lock` and `targets.lock`): every file's size,
sha256, Last-Modified and URL. A fetch checks each file against its publisher's
checksum list where there is one, and against the lock; anything new or
changed fails until you accept it with `--update`. On the first run there is no
lock, so the files are trusted and the lock is written. Publisher checksums
that disagree with what the publisher actually serves are listed, with the
reason, in `checksum_exceptions.tsv` next to the locks. Each observation records
the exact target file it was made from, and a release records the hash of each
lock.

Each script's docstring says what it reads, writes and checks.

## Repository layout

| Path | Contents |
| --- | --- |
| `crates/` | The Rust crates: `refbook-core` (refget digests and canonicalization, seqcol, nucleotide operations, the recipe compiler; no I/O), and its bindings, `refbook-py` (pyo3, built by maturin as `refbook._core`) and `refbook-wasm` (wasm-bindgen, for `js/`) |
| `python/` | The Python package (`pyproject.toml`, `README.md`, and `tests/`, with real ENCODE, gnomAD and GIAB headers as fixtures) |
| `python/refbook/` | The Python library: `catalog`, `resolve`, `identify`, `materialize`, `fetch`, `refcache`, `parse`, `refget`, `seqcol`, `blocks`, `remote` |
| `js/` | The npm package `@abdenlab/refbook`: the TypeScript front end (`js/src/`) over the core's wasm bindings (`crates/refbook-wasm`). Build with `cd js && npm install && npm run build` (needs the `wasm32-unknown-unknown` target and `wasm-bindgen-cli` 0.2.130); test with `npm test` |
| `catalog/` | The numbered steps that build, check and export the catalog, their shared modules (`layout`, `engine`, `observe`, `lock`), and their tests |
| `catalog/output/` | Gitignored: `raw/` (the downloads, or a symlink to a mirror) and `build/` (the steps' outputs) |
| `catalog/assemblies/grch38/` | The declarative inputs: `recipes/` (one JSON file per publisher), `flavors.json` (labels, and the targets that reproduce each flavor) and `locks/` |
| `docs/` | `SCOPE.md` (the design document) and `GLOSSARY.md` |

## Development

```bash
uv sync
uv run pytest                       # python/tests (the library) and catalog/tests (the pipeline)
(cd js && npm install && npm run build && npm test)   # the npm package
```

Tests that need a catalog read `$REFBOOK_CATALOG` (default: the build in
`catalog/output/build/grch38`) and are skipped without one. The wasm
cross-check (`catalog/tests/test_wasm.py`) is skipped until `js/` is built.

## License

The code is released under the [MIT License](LICENSE). The catalog data is
CC-BY-4.0.
