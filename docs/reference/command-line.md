# Command line

The `refbook` command has three subcommands: `identify`, `populate-ref-cache`
and `serve`. Each takes `--catalog` (a URL or a local path; default:
`$REFBOOK_CATALOG`, else the current release on Hugging Face).

## identify

```
refbook identify FILE... [--sequences] [--json]
```

`identify` reads a file's sequence list and compares it with every cataloged
edition. It accepts `.fai`, `chrom.sizes`, `.dict`, SAM header text, BAM, CRAM
(2.x and 3.x), VCF, FASTA and seqcol collections (level-2 JSON). Only the
header is read; a FASTA's sequences are digested (MD5 and `SQ.`).

The comparison treats the header as a set of named sequences, so order plays
no part in the verdict:

| Verdict | Meaning |
| --- | --- |
| **exact** | The same names, each with the same length, and the same MD5 where the header has them |
| **consistent** | The same names and lengths, but the header has no MD5s, so editions that differ only in their bases can't be told apart |
| **contains** | The whole edition, unchanged, plus other sequences (spike-ins, other genomes) |
| **subset** | Every header sequence is in the edition, unchanged, but the edition has more (e.g. chr1–22, X, Y only) |
| **partial** | Anything else: the closest editions, with the differences itemized |

Order is reported separately: which published files list the sequences in the
header's order. That is what BAM reference IDs and coordinate-sorted files
depend on.

### With digests: an exact answer

A `.dict`, a BAM or CRAM header, or a FASTA gives an MD5 for every sequence:

```
$ refbook identify Homo_sapiens_assembly38.dict
Homo_sapiens_assembly38.dict
  dict, 3366 sequences, with digests
  EXACT: hs38dh
    hs38dh: in the order of Broad Institute Homo_sapiens_assembly38; 1000 Genomes GRCh38_full_analysis_set_plus_decoy_hla; Illumina iGenomes GATK/GRCh38
  seqcol digest: Cs-_YD8aP4e7Gz5GsfmxKt88hyJ00ZBL = Broad_Homo_sapiens_assembly38, 1000G_GRCh38_full_analysis_set_plus_decoy_hla, iGenomes_GATK_GRCh38
```

### Without digests: narrowed down, with the difference explained

A VCF has only names and lengths. GIAB's HG002 benchmark matches two editions,
and the output says how they differ:

```
$ refbook identify HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz
HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz
  vcf, 195 sequences, without digests
  CONSISTENT (names and lengths; no digests to check bases): grch38-no-alt, hg38-analysis-set
    hg38-analysis-set vs grch38-no-alt: 14 sequences differ in bases (12: as submitted (INSDC) vs IUPAC -> N; 2: GRC hard-mask vs GRC hard-mask + IUPAC -> N)
    grch38-no-alt: in the order of GRC GCA_000001405.15_GRCh38_no_alt_analysis_set; Illumina iGenomes NCBI/GRCh38
    hg38-analysis-set: in the order of Illumina iGenomes UCSC/hg38; UCSC hg38.analysisSet
```

### Extra sequences

An ENCODE alignment header (`samtools view -H`) with the fly genome and spike-ins alongside the human
one:

```
$ refbook identify ENCFF462XCI.sam
ENCFF462XCI.sam
  sam, 2066 sequences, without digests
  CONTAINS grch38-no-alt, hg38-analysis-set (all 195 sequences, unchanged), plus 1871 others
    - only in header: 1871 unknown to the catalog (U13369.1, dm6_chr2L, dm6_chr2R, ...)
```

### Each sequence on its own: `--sequences`

`--sequences` also says what each sequence is, on its own evidence. With a
digest the catalog knows: the sequence, its root, the operations that made it,
and the editions that use it. From a name and length: the root, and how many
cataloged versions of it there are. And notes on whatever disagrees: an
unknown digest, a length, a name that names another root.

```
$ refbook identify ENCFF462XCI.sam --sequences
  ...
  sequences:
    chr1	248956422	CM000663.2 (by name and length), one of 2 cataloged versions
    chr2	242193529	CM000664.2 (by name and length), one of 2 cataloged versions
    ...
```

### JSON

`--json` prints the same results as JSON: per file, the format, the number of
sequences, whether it has digests, and each matching edition with its verdict,
score and the published files (with their URLs) whose order it follows.

## populate-ref-cache

```
refbook populate-ref-cache FILE... --root DIR
```

Writes the sequences a CRAM, BAM, SAM header or `.dict` names by MD5 into an
htslib reference cache, building each from its root. Bare MD5s work too. Then:

```
REF_CACHE=DIR/%2s/%2s/%s samtools view sample.cram
```

See [Decoding CRAMs](../guides/cram.md).

## serve

```
refbook serve [--host 127.0.0.1] [--port 8000]
```

Serves the catalog over the GA4GH refget APIs: Sequences v2 and Sequence
Collections v1. See [A refget server](../guides/refget-server.md).
