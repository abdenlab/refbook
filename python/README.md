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

Not yet on PyPI. From a clone of
[abdenlab/refbook](https://github.com/abdenlab/refbook), with a Rust toolchain
([rustup](https://rustup.rs/)), since the core is compiled into the package:

```bash
pip install ./python                 # the library and the `refbook` command
pip install "./python[datafusion]"   # also DataFusion, for faster fetches from a local catalog
```

The catalog is downloaded on demand from Hugging Face
([abdenlab/refbook](https://huggingface.co/datasets/abdenlab/refbook)): only
the small tables, about 1.3 MB, are cached; bases are read with HTTP range
requests as needed.

## Command line

```bash
# Which reference was this aligned to?
$ refbook identify sample.cram
sample.cram
  cram, 3366 sequences, with MD5s
  EXACT: hs38dh
    hs38dh: in the order of Broad Institute Homo_sapiens_assembly38; 1000 Genomes GRCh38_full_analysis_set_plus_decoy_hla; ...

# A VCF without MD5s can only be narrowed down, and the output says how the candidates differ.
$ refbook identify HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz
  vcf, 195 sequences, without MD5s
  CONSISTENT (names and lengths; no MD5s to check bases): grch38-no-alt, hg38-analysis-set
    hg38-analysis-set vs grch38-no-alt: 14 sequences differ in bases (12: as submitted (INSDC) vs IUPAC -> N; ...)
    grch38-no-alt: in the order of GRC GCA_000001405.15_GRCh38_no_alt_analysis_set; Illumina iGenomes NCBI/GRCh38

# Fill htslib's reference cache so a CRAM decodes without its FASTA.
$ refbook populate-ref-cache sample.cram --root ~/refcache
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

## More

The catalog, how it is built and checked, and the terms used here
(root, flavor, recipe, ...) are described in the repository's
[README](https://github.com/abdenlab/refbook#readme) and
[glossary](https://github.com/abdenlab/refbook/blob/main/docs/GLOSSARY.md).
