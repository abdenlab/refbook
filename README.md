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

> Status: early. Catalog release 0.1.0 covers GRCh38. The library is not yet
> on PyPI, and its API may change.

## Install

From a clone of this repository, with [uv](https://docs.astral.sh/uv/):

```bash
uv sync                      # the library and the `refbook` command
uv sync --extra datafusion   # also DataFusion, for faster fetches from a local catalog
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
  EXACT: 1000G_GRCh38_full_analysis_set_plus_decoy_hla, Broad_Homo_sapiens_assembly38, iGenomes_GATK_GRCh38

# A VCF without MD5s can only be narrowed down, and the output says how the candidates differ.
$ uv run refbook identify HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz
  vcf, 195 sequences, without MD5s
  CONSISTENT (names, lengths and order; no MD5s to check bases): GRCh38_no_alt_analysis_set, UCSC_hg38.analysisSet, ...
    UCSC_hg38.analysisSet vs GRCh38_no_alt_analysis_set: 14 sequences differ in bases (12: as submitted (INSDC) vs IUPAC -> N; ...)

# Fill htslib's reference cache so a CRAM decodes without its FASTA.
$ uv run refbook populate-ref-cache sample.cram --root ~/refcache
$ REF_CACHE=~/refcache/%2s/%2s/%s samtools view sample.cram
```

`identify` accepts `.fai`, `chrom.sizes`, `.dict`, SAM header text, BAM, CRAM
(2.x/3.x), VCF and FASTA. Its verdicts are **exact**, **consistent**,
**contains** (the whole reference plus extra sequences, such as spike-ins),
**subset**, or the **closest** match with an itemized difference.

## Python

```python
import pyarrow as pa
from refbook import Catalog, identify, read_header, materialize, fetch, sequence_by_md5

cat = Catalog("https://huggingface.co/datasets/abdenlab/refbook/resolve/v0.1.0/")

# Identify a header.
result = identify(read_header("sample.bam"), cat)
print(result.best[0].verdict, [c.flavor for c in result.best])

# Materialize a flavor (or some of its sequences) as an Arrow stream: one row per
# sequence, with name, description and sequence, following the CompoSeq Sequence schema.
chr21 = materialize(cat, "UCSC_hg38.analysisSet", names=["chr21"]).read_all()

# Fetch bases at intervals: 0-based half-open by default, polars-bio column names,
# "-" strands reverse-complemented. Also takes Polars or pandas frames.
intervals = pa.table({"chrom": ["chr1", "chrY"], "start": [1_000_000, 10_000],
                      "end": [1_000_100, 10_050], "strand": ["+", "-"]})
seqs = fetch(cat, "GRCh38_no_alt_analysis_set", intervals, strand="strand")

# Any cataloged sequence by its MD5.
chrM = sequence_by_md5(cat, "c68f52674c9fb33aef52dcf399755519")
```

Every sequence `materialize` builds is checked against the recipe's MD5 and
`SQ.` digests. `fetch` honors polars-bio's coordinate-system metadata, so its
1-based frames are converted correctly; an interval outside its sequence is an
error unless `clip=True`.

## The catalog

Release 0.1.0 (CC-BY-4.0) reproduces 17 published GRCh38 files, which reduce to
13 distinct sequence sets:

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
across naming conventions, each file's recipe, GA4GH seqcol digests, and the
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
  alphabet (IUPAC→N), rename and order. They are data, in `recipes/*.json`.
- **Reconstruction is the verification.** A file counts as cataloged only when
  its recipe reproduces it, sequence by sequence: names, lengths, MD5 and `SQ.`
  digests. The rebuild also turned up details that no publisher documents: the
  order UCSC uses, which patches Ensembl leaves out, and how bwakit chose its HLA
  alleles.

[`SCOPE.md`](SCOPE.md) is the design document.

## Building the catalog

The pipeline in `pipeline/` builds a catalog from the original downloads; it
runs on the lab server and needs about 15 GB.

```bash
R=/path/to/registry
pipeline/fetch_grch38.sh $R          # INSDC assemblies, hs38d1, EBV, GRC analysis sets, IMGT/HLA
pipeline/fetch_flavors.sh $R         # published files used as reproduction targets
uv run python -I pipeline/build_roots.py $R
uv run python -I pipeline/build_external_roots.py $R
uv run python -I pipeline/build_layers.py $R
uv run python -I pipeline/check_gaps.py $R
uv run python -I pipeline/verify_roots.py $R <GRC full_plus_hs38d1 analysis set .fna.gz>
uv run python -I pipeline/observe_fasta.py <published FASTA> $R/build/grch38/observed/<flavor>.parquet  # per file
uv run python -I pipeline/run_recipes.py $R recipes/<file>.json        # per recipe file
uv run python -I pipeline/build_catalog.py $R recipes/*.json
uv run python -I pipeline/family_tree.py $R recipes/*.json
uv run python -I pipeline/check_materialize.py $R
uv run python -I pipeline/export_catalog.py $R $R/catalog/<version> <version>
```

Each script's docstring says what it reads, writes and checks.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/refbook/` | The library: `catalog`, `identify`, `materialize`, `fetch`, `refcache`, `parse`, `seqcol`, `blocks`, `remote` |
| `pipeline/` | Scripts that build, check and export the catalog |
| `recipes/` | The recipes, one JSON file per publisher |
| `tests/` | Tests, with real ENCODE, gnomAD and GIAB headers as fixtures |
| `experiments/` | Measurements behind design decisions, e.g. the Parquet layout |
| `pages/` | The family tree page template |

## Development

```bash
uv sync --extra datafusion
uv run pytest
```

Tests that need the catalog look for it at `$REFBOOK_CATALOG` (default: the lab
server's build directory) and are skipped when it is absent.

## License

The code is released under the [MIT License](LICENSE). The catalog data is
CC-BY-4.0.
