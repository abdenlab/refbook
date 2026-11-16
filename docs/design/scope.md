# Design notes: the original scope

!!! note "A historical document"

## The problem in one paragraph

"Aligned to hg38" does not identify a reference. Every distributor (GRC/NCBI,
UCSC, Ensembl, GENCODE, Broad, 1000 Genomes, Illumina, 10x, iGenomes) ships a
different FASTA. They differ in which contigs are present (alts, decoys, HLA,
EBV, unplaced, patches), in what the contigs are called, in their order, and in
the bases themselves. Hard-masked PAR on chrY, masked false duplications,
alt-masking, and IUPAC codes turned into `N` all change the bases. The
information needed to tell these apart exists, but it is scattered. It sits in
NCBI assembly reports, in tag-values on GRC FASTA deflines, in UCSC `chromAlias`
files, in Illumina blog posts and in READMEs on FTP sites. No single service
answers "what is this reference, and is it the same as that one, for my
purpose?"

## How bad it is: a survey of GRCh38 editions

We checked about a dozen GRCh38 distributions. We read only their metadata,
plus individual contigs fetched by byte range, without downloading whole
FASTAs.

**One chr21, four sequences.** Every source below names it `chr21` (or `21`) at
length 46,709,983:

| chr21 MD5 | Source | Why it differs |
| --- | --- | --- |
| `eefe014d…` | INSDC `CM000683.2` / `NC_000021.9` | The original |
| `974dc7ae…` | GRC analysis sets, Broad/GATK, 1000 Genomes | Duplicated CEN/WGS regions hard-masked |
| `2f45a345…` | UCSC hg38, Ensembl | IUPAC codes → `N` (2bit can't store them) |
| `3a6a8640…` | UCSC analysisSet, iGenomes UCSC | Both of the above |

All four are the same coordinate axis. ENA's CRAM refget server knows only the
first two. A CRAM aligned to UCSC or Ensembl hg38 can't be decoded from any
public server.

The other things that would trip a user up:

- **The difference between UCSC and NCBI is systematic, not an exception.** 14
  of 24 nuclear chromosomes differ between the two families because of
  IUPAC→N. UCSC's analysisSet README says it is "otherwise identical" to NCBI's,
  and that is false at the byte level.
- **The same URL has meant different genomes over time.** UCSC
  `bigZips/hg38.fa.gz` is the 2014 release with 455 sequences. `latest/` is
  p14, with 711. UCSC p14 also keeps two superseded patch versions next to their
  replacements, so it has 711 sequences where NCBI has 709.
- **"No-alt" is not the same as "primary".** The GRC no-alt sets have 195
  sequences, including chrEBV. Ensembl, GENCODE and 10x primary assemblies have
  194, without it.
- **Ensembl 116 lacks 3 of the p14 fix patches** (about 7.3 Mb), and it names
  alts by GRC name (`HSCHR6_MHC_COX_CTG1`) rather than by accession.
- **Same names and lengths, different bases.** DRAGEN alt-masking replaces
  100.7 Mb across all 261 alts and the HLA contigs with N. A check on names and
  lengths, which is what Picard/GATK do, can't see it.
- **Identical content, different files.** Broad and 1000 Genomes have identical
  names and per-contig MD5s, but they wrap lines at different widths. The
  `.fai` files and file checksums differ, so a file-level checksum is the wrong
  identity.
- **Labels in existing catalogs are unreliable.** In refgenie, entries
  labeled "GRCh38-igenomes-build37" are GRCh37 by content.

## What already exists, and what it leaves open

The standards side is better than its reputation, but nobody has curated the
content or made it easy to use.

| Layer | Standard / tool | Gap |
| --- | --- | --- |
| One sequence by digest | GA4GH **refget sequences** v2 (MD5 and `SQ.` sha512t24u, range retrieval) | Public servers each hold only their own provider's sequences. ENA has INSDC sequences and answers MD5 only. Ensembl has Ensembl sequences and doesn't know INSDC chr1. Since htslib 1.22, htslib has no default server |
| A set of sequences | GA4GH **refget sequence collections (seqcol)** v1.0, approved March 2025: the "assembly standard" | Digest over `names` + `sequences` only. The comparison endpoint returns overlap counts and leaves interpretation to the client. It has no roles, no aliases and no labels, and by its own account it doesn't explain differences between individual sequences. Only one populated server (databio): 79 collections, no CHM13 |
| Labels on collections | refgenie v1 (pre-release) | Labels are curated by hand, and some are wrong: some "GRCh38" iGenomes entries are actually GRCh37 or NCBI36 |
| Contig roles | NCBI assembly reports; GRC analysis-set deflines (`rl:`, `hm:`, `M5:`) | Cover INSDC sequences only. Roles live in text files and FASTA headers |
| Name conventions | UCSC chromAlias, GenomeInfoDb, dpryan79/ChromosomeMappings | Map names to names only, with no digests, so they can't detect that two "chr1"s differ |
| Sequence aliases | biocommons SeqRepo | Sequence-level only. No collections |

None of these tools stores where an edition came from. Each records what an
edition is (its digests, its names), not how it was made. That is the approach
taken here: store the lossless sources once, and treat every edition as a recipe
applied to them.

## The model: roots, layers, recipes

### Roots

Almost every human reference in use is derived from a small set of lossless
sources by operations that discard information. Nothing is ever added, apart
from the extra sequences listed below. The lossless sources are the **roots**.

| Root set | Source | Used by |
| --- | --- | --- |
| GRCh38, every sequence in any release p0–p14: 711 sequences, including 2 superseded patch versions | GenBank `GCA_000001405.15`–`.29` (accession.version), plus the AGP files | All GRCh38/hg38 editions |
| GRCh37.p13 | GenBank `GCA_000001405.14` + AGP | GRCh37, hg19, hs37d5 |
| hs38d1 decoys | GenBank `GCA_000786075.2` | hs38DH, Broad, 1000 Genomes, GRC `plus_hs38d1` sets |
| hs37d5 decoy | 1000 Genomes FTP (INSDC status not checked) | hs37d5 |
| EBV | INSDC `AJ507799.2` / `NC_007605.1` | GRC analysis sets, hs38DH, hs37d5 |
| Mitochondria | rCRS `J01415.2` / `NC_012920.1`; Yoruba `NC_001807.4` (hg19 chrM) | Everything; hg19 |
| HLA alleles | IMGT/HLA, at a pinned release | hs38DH |
| T2T-CHM13v2.0 | GenBank `GCA_009914755.4` (CHM13 v1.1 + HG002 chrY), with CHM13's own chrM `CP068254.1` | CHM13, hs1 |

GRCh38's patch releases only ever add sequences, with one exception. Across the assembly reports
for p0–p14:
- The 455 sequences of p0 (25 assembled molecules, 42 unlocalized, 127 unplaced
  and 261 alt scaffolds) keep the same accession.version and length in every
  release. INSDC changes the version on any change to the sequence, so the
  bases are unchanged as well.
- Each release adds fix and novel patches. p14 has 164 fix and 90 novel
  patches.
- Nothing is ever removed or given a new role. The only exception is in p14:
  two fix patches were replaced by new versions of different lengths.
  - `KQ759759.1` (196,940 bp) became `KQ759759.2` (204,999 bp).
  - `KQ759762.1` (101,037 bp) became `KQ759762.2` (101,040 bp).

So the GRCh38 roots are the union of all releases: 711 sequences. Each release
p*N* is then just a list of members. This matches what UCSC ships: the
original `hg38.fa` has 455 sequences (p0), and `latest/` has 711 (the union,
superseded versions included).

Two of these need care:

- **GenBank, not RefSeq, is the root.** The GRCh38.p14 assembly report marks 705
  of 709 sequences as identical in both, and 4 GenBank scaffolds have no RefSeq
  copy. For T2T, RefSeq replaces CHM13's own chrM with rCRS. RefSeq is therefore
  itself an edition, although a very small one.
- **A root sequence keeps everything**, including its IUPAC codes, and its gaps
  are recorded as gaps. The flat GenBank chromosome record is itself built from
  component sequences by AGP. Storing the AGP keeps the information that every
  derived file loses: which `N`s are gaps, and which `N`s are masked bases.

#### Background: how GRC assemblies are versioned

There are three separate identifiers, and they are easy to confuse:

| Level | Example | Changes when |
| --- | --- | --- |
| Sequence accession.version | chr1 = `CM000663.2` (GenBank), `NC_000001.11` (RefSeq) | Its bases change, at any length. INSDC: "when any change is made to a sequence … the version part of its accession number is incremented". Annotation-only updates don't change it |
| Assembly accession.version | `GCA_000001405.29` | Every release, patch or major. GRCh37 = `.1`, GRCh37.p13 = `.14`, GRCh38 = `.15`, GRCh38.p14 = `.29` |
| Build name | GRCh38, GRCh38.p14 | Just a name |

A sequence's version follows that sequence's own history, not the build.
GRCh38's chr1 is `CM000663.2` because `CM000663.1` was GRCh37's chr1, which
had a different length. GRCh38 p0 mixes 391 `.1` sequences, 63 `.2` and one
`.3` (`GL383563.3`). A sequence can be carried over unchanged between builds,
as chrM (`J01415.2`) was. **So the roots form one pool keyed by sequence
accession.version, shared across assemblies**, and each assembly version is a
membership list over that pool.

The guarantees of the GRC's [patch model](https://www.ncbi.nlm.nih.gov/grc/help/patches/):

- **Patch releases do not change chromosome coordinates.** This is the written
  guarantee, about coordinates and therefore lengths. In practice the GRC
  doesn't change the base sequences at all: no p0 sequence changed version
  across GRCh38.p1–p14, alts and unplaced scaffolds included. The model relies
  on the guarantee, and a CI check over the assembly reports verifies the
  practice.
- **Patches are scaffolds with no coordinates of their own**, placed onto a
  region of a parent chromosome by an alignment that NCBI publishes. A patch
  can be replaced by a new version of a different length and name within a
  major release (`HG107_PATCH`/`KQ759759.1` → `HG107_HG2565_PATCH`/`.2`).
- **At the next major release,** fix-patch accessions are retired and their
  corrections are written into the new chromosomes, which get new versions and
  new coordinates. Novel patches keep their accessions and become alternate
  loci.

There will probably be no next major release. The GRC has postponed GRCh39
indefinitely while it evaluates pangenome-based models, and GRCh38.p14 (2022)
is still the latest release: there is no `GCA_000001405.30`. **GRCh38's roots
are effectively a closed set**, so the GRCh38 core can be built once and
verified. New sequences will come from the T2T and pangenome assemblies below.

#### Background: CHM13, HG002 and HPRC

- **CHM13** is a hydatidiform-mole cell line. It is effectively homozygous,
  which is what made it the first human genome assembled gapless, telomere to
  telomere. It is 46,XX, so it has no chrY.
- **HG002** (NA24385) is the son in an Ashkenazi trio from the Personal Genome
  Project. Genome in a Bottle (NIST) has characterized it more than any other
  genome, and its truth sets are the standard benchmark for variant callers. It
  plays two roles here:
  - CHM13v2.0's chrY comes from HG002, so "the T2T reference" is a composite of
    two people.
  - The T2T and GIAB "Q100" project produced a near-perfect **diploid**
    assembly of HG002: separate maternal and paternal haplotypes, each telomere
    to telomere. It is becoming the basis for new benchmarks.
- **HPRC** (Human Pangenome Reference Consortium) assembles many individuals
  with their haplotypes resolved.
  [Release 2](https://humanpangenome.org/hprc-data-release-2/) (May 2025) has
  470 phased haplotype assemblies from 232 individuals. These are mostly
  contig-level, not T2T.
  - They are consumed mainly as pangenome graphs (Minigraph-Cactus, PGGB) for
    graph aligners such as vg giraffe, with GRCh38 and CHM13 embedded as
    reference paths.
  - Graph sequences are named with the PanSN convention,
    `sample#haplotype#contig` (`GRCh38#0#chr1`, `HG002#1#chr1`).

How these fit the model:

- **CHM13 already has the same variety of editions as GRCh38.** The T2T project
  ships versions with the chrY PAR masked and with rCRS swapped in for CHM13's
  chrM, and UCSC republishes it as hs1. These are roots plus layers plus
  recipes, with nothing new.
- **Diploid HG002 needs a haplotype grouping:** a membership attribute (maternal
  and paternal, or PanSN haplotype 1/2) that groups collections into an
  individual. PanSN becomes one more alias namespace.
- **HPRC changes the storage arithmetic.** 470 haplotypes at about 3 Gb each is
  about 1.4 Tb, and deduplication saves almost nothing because no two
  haplotypes are identical. Indexing their digests, names and lengths is cheap.
  Hosting their bases is a separate decision.
- **Graphs remain out of scope.** The registry can still identify the linear
  reference paths embedded in a graph. "Is the `GRCh38#0#chr1` path in this
  graph the INSDC chr1 or the UCSC one?" is exactly the question it answers.

### Layers

These are annotations in root coordinates. A layer is computed or imported
once, and recipes refer to it by name and version.

| Layer | Content | Source |
| --- | --- | --- |
| **Roles** | `assembled-molecule`, `unlocalized`, `unplaced`, `alt-scaffold`, `fix-patch`, `novel-patch`, `decoy`, `hla`, `viral`, `mitochondrion`; assigned molecule; assembly unit | NCBI assembly reports; added by us for the non-assembly roots |
| **Placement** | Where each alt or patch sits on its parent chromosome: the GRC region it belongs to, its orientation, the aligned span on each side and the unaligned tails. Plus the full base-level alignment, with identity statistics. Each assembly version has its own placement, since a patch's placement can change with its version | NCBI `assembly_structure/*/alt_scaffolds/`: `alt_scaffold_placement.txt`, `alignments/*.gff` (GFF3 `Gap`) and `.asn`, `patch_type`. Third-party placements are imported as separate, attributed layers, e.g. bwa's `hs38DH.fa.alt` |
| **Curation evidence** | The GRC's record of each join between components it reviewed: category, supporting evidence, status and a comment | NCBI `assembly_structure/*/join_certificate.xml` |
| **Components and gaps** | AGP: component accession, orientation, and gap type and size (centromere, telomere, contig, scaffold, known/unknown) | GRC AGP |
| **Ambiguity** | Positions of IUPAC codes | Derived from the roots |
| **Hard masks** | PAR-Y; GRC centromere/WGS false-duplication masks; DRAGEN alt-masking; GRC exclusions (contamination) | GRC analysis-set files, Illumina's published BED |
| **Soft masks** | Repeat tracks as published by each provider (UCSC rmsk + simpleRepeat, Ensembl repeat features) | Imported, not recomputed |
| **Aliases** | Names by namespace (`genbank`, `refseq`, `ucsc`, `ensembl`/GRC name, `assembly`) | Assembly reports, UCSC chromAlias, Ensembl |

Components and gaps are an annotation almost nobody checks, and nobody serves
in a form that can be queried. A pile-up at a clone boundary, or reads mapped
across a gap of unknown size, become visible once the layer is there to join
against.

### Recipes

An **edition** is a recipe applied to roots. The operations:

1. **select** sequences, by identifier, role, molecule or assembly unit;
2. **place** sequences onto a coordinate frame. In AGP terms this covers
   Ensembl toplevel, which pads each patch with `N` to full chromosome length,
   and it is also how roots themselves are assembled;
3. **mask** with a hard-mask (`N`) or soft-mask (lowercase) layer;
4. **change the alphabet**: IUPAC→`N`, or a change of case;
5. **rename** into a namespace, or with an explicit map;
6. ~~**order** the sequences~~ and 7. ~~**format** the output~~: removed
   2026-11-04. An edition is a named sequence set ([glossary](../concepts/glossary.md)), so order and
   formatting are recorded from each published file, not reproduced.

A root after the sequence-level operations (mask, alphabet) is a
**derivative**: one distinct sequence, with its own MD5 and `SQ.` digest. Most
sequences in published files are a root as submitted, the identity
derivative. The others are, for example, chrY with the GRC hard-mask, or chr1
with IUPAC→`N`. ("Variant" would read as a mutation, so it isn't used.)

**Reconstruction is the verification.** An edition counts as cataloged only
once running its recipe reproduces the per-sequence digests of the published
file. A label can't be wrong because it isn't asserted; it is the name of a
recipe that has been checked. An edition that doesn't reproduce is a finding in
its own right: it has a root we lack, or an operation we haven't modeled.
Examples are DRAGEN's graph haplotypes, spike-ins (phiX, lambda, ERCC), and
UCSC's superseded patches.

### What falls out

The identity questions from the first draft follow without extra machinery:

- **Same coordinate axis** (cognates): two sequences come from the same root
  and differ only in masking or alphabet. The definition can be checked by
  anyone: S is a cognate of root R if they have the same length and, ignoring
  case, every base of S equals R's base or is `N`. A cognate class is named by
  its root's refget digest.
- **Coordinate system:** the ordered list of placed roots, without names.
- **Explained diff** between two editions: the difference between their
  recipes, e.g. "B = A + hs38d1 decoys, PAR-Y masked, renamed to UCSC". This
  answers "are these compatible for my purpose?". Seqcol's comparison counts
  are the shadow of it.
- **Identify:** given a header (names, lengths, perhaps M5s), find the recipe
  whose output matches. If the header matches no recipe, the closest one, with
  a diff, is still a useful answer.

## Distribution: static Parquet plus a library

Everything is hosted statically as canonical Parquet files. The library does the
work.

**Tables.**
- `roots`: root ID, accession.version, length, refget MD5 and `SQ.` digests.
- `root_blocks`: the bases themselves, in fixed-size blocks (for example
  `root_id, start, bases`, 64 kb per row, ZSTD-compressed, uppercase with IUPAC
  codes kept). About 50k rows for GRCh38. A range query becomes row-group
  pruning over HTTP range requests, which DuckDB, Polars and pyarrow already do.
- `components` and `gaps` (AGP), `roles`, `placements`, `aliases`.
- `masks`: one table per layer, as intervals with a layer name and version.
- `recipes`, and the expected per-sequence digests of each edition:
  `edition_sequences` (edition, order, name, root, length, MD5, `SQ.`).
- Seqcol JSON documents generated for each edition, so any seqcol client can
  read them.

**The library** (Rust core, Python first) can:
- materialize any edition or subset as an Arrow stream conforming to the
  CompoSeq Sequence schema, or as FASTA, 2bit, `.fai`, `.dict` (with M5),
  chrom.sizes or seqcol JSON;
- fetch a region of an edition, as Arrow. This is the input for the slicing RFC
  the sequence schema defers to;
- identify a FASTA, `.fai`, `.dict`, BAM/CRAM header or VCF header offline,
  against the catalog;
- rename a BED, VCF or BAM header from one edition's names to another's,
  refusing when the coordinate systems differ;
- fill htslib's `REF_CACHE` for a CRAM: read the `@SQ` M5s, identify the
  edition, and write out the derived sequences htslib asks for.

Size: the GRCh38 roots are about 3.2 Gb of sequence. With ZSTD, all the human
roots fit in a few GB. Layers and recipes are megabytes.

### CRAM reference resolution

This section was checked against htslib `develop` (`cram/cram_io.c`,
`cram_populate_ref`) and against htslib 1.21 as bundled with pysam, on
2026-10-29.

**What a CRAM carries.**
- Each `@SQ` line has `SN`, `LN` and `M5`: the MD5 of the whole contig,
  uppercased, with no newlines.
- Records carry only a reference index and a position.
- Each slice header carries the MD5 of the reference span that slice covers.
  The decoder uses it to check that it decoded against the right bases.
- `UR` is optional, and is usually a path on the machine that wrote the file.
  Since htslib 1.22, a `UR` that points to a remote location is an error. So the
  file says *which* sequence it needs, by MD5, but not *where* to get it.

**How htslib resolves a contig.**

1. An explicit reference (`-T`/`--reference`), looked up by name. A wrong
   reference is caught by the slice MD5s.
2. Otherwise, `REF_CACHE`, by `M5`.
3. Then `REF_PATH`, a colon-separated list of local-directory or URL templates
   (`%s` = MD5, `%2s` = the next two characters of it). For a URL, htslib does
   a plain GET of the whole contig into memory, e.g.
   `https://www.ebi.ac.uk/ena/cram/md5/%s`. This is not the refget API: there
   are no range requests and no JSON. A refget server's `GET /sequence/{md5}`
   returns raw bases and should work as a template too, but this is untested.
4. Then a local `UR` path.

**The cache** is one file per contig, named by MD5 and sharded by template, e.g.
`REF_CACHE=~/.cache/hts-ref/%2s/%2s/%s`. Each file holds the raw uppercase
sequence, with no header and no newlines. htslib checks the MD5 before writing
the file, writes it atomically, and makes it read-only. Because files are named
by content, a contig shared by several editions is stored once.

**htslib 1.22 (May 2025) removed the defaults.** Up to 1.21, an unset `REF_PATH`
meant the EBI server, with a `~/.cache/hts-ref` cache turned on automatically.
Now neither is set by default. A CRAM opened without `-T` and with no
configuration fails to decode. The release ships `ref-cache`, a caching proxy,
for sites to run themselves.

**How the registry plugs in.** htslib only ever asks for "the full bytes with
MD5 X". Applying a recipe therefore happens outside htslib. There are two ways
to do it, and neither needs a hosted server:

1. **Fill the cache ahead of time** (`… refcache populate sample.cram`). Read the
   CRAM's `@SQ` M5s and look each up in `edition_sequences`. Apply the recipe to
   the root, check the MD5, and write the file into `REF_CACHE`. Only the
   contigs the CRAM names are built, and contigs already present are skipped.
   The cost is the full contig length on disk per distinct derivative:
   about 3 GB for a whole human edition, less what editions share.
2. **Serve lazily on localhost.** Point `REF_PATH=http://localhost:PORT/%s` at a
   small process that builds sequences from the Parquet roots on request.
   htslib then caches them itself. The same process can be the upstream of a
   site-wide `ref-cache`.

Both depend on the catalog knowing the MD5. A CRAM aligned to an edition that
hasn't been reproduced (milestone 2) can't be resolved. Hosting the most-used
derived sequences, or running a recipe-applying edge function as a public
`REF_PATH`, is possible later. It is a hosting decision, not a design one.

## Scope

**In:** the human roots above, with their layers, and recipes for the editions
in the survey. Mouse (GRCm38/39 and their editions) next. Static Parquet
distribution and the library.

**Out, for now:**
- Stewarding assemblies.
- Gene annotations, and other assets unrelated to identity.
- Liftover between non-cognate assemblies, such as GRCh37→38.
- Pangenomes.
- Recomputing soft-masking.
- A hosted refget/seqcol server, until there is a reason to run one.

## Milestones

1. **GRCh38 roots and layers.** Fetch GenBank `GCA_000001405.29` and its AGP,
   plus hs38d1, EBV and rCRS. Build `roots`, `root_blocks`, `components`,
   `gaps`, `roles`, `placements`, `aliases` and the ambiguity layer. Check the
   result against NCBI's own MD5s and lengths.
2. **Recipes for the surveyed editions**, starting with the cheapest to verify:
   the GRC analysis sets (whose deflines carry `M5:`), Broad/1000 Genomes
   (`.dict` M5s), UCSC hg38 (initial and p14) and the analysisSet, Ensembl
   primary and toplevel, GENCODE, iGenomes. Every recipe reproduces its
   published digests or is reported as a finding. The result is the "GRCh38
   family tree".
3. **Library v0:** materialize, fetch, identify, rename, `REF_CACHE`. Test
   identify on real headers from ENCODE, gnomAD, 1000 Genomes and GIAB.
4. **GRCh37 and CHM13**, which add the hs37d5, Yoruba chrM and IMGT/HLA roots.
   **Then mouse.**

## What would make this a mistake

- Some widely used editions can't be reproduced from public roots: their masks
  or added sequences aren't published. DRAGEN is the most likely case. If that
  is common, the catalog falls back to recording the digests it observes for
  those editions, and loses the explained diffs it is meant to provide.
- Users never ask for derived editions, only for "the" reference plus a check,
  so the recipe machinery is more than they need.
- Static Parquet range reads are too slow for the access patterns that matter,
  such as many small random regions for model training, compared with
  `.fai`/2bit on local disk. Users would then always materialize locally, which
  is fine, but the library has to make that easy.

## Open questions

1. **IMGT/HLA license.** Can we redistribute pinned allele sequences? If not,
   the HLA root is fetched from IMGT by the library and never hosted.
2. **Does soft-masking reproduce?** Do UCSC's published rmsk and simpleRepeat
   tracks reproduce `hg38.fa`'s lowercase exactly? It isn't part of identity,
   but it is a test of whether the soft-mask layers are faithful.
3. **Block size and layout of `root_blocks`.** Settled (measured in
   the experiment script `experiments/root_blocks_layout.py`, since removed;
   it is in git history). Keep fixed 64 kb rows. Gaps cost
   nothing (all 2,219 all-N blocks compress to ~17 kB), and AGP components vary
   from <1 kb to 4.8 Mb, which would make fetch cost uneven and need a lookup.
   Use row groups of 32 blocks that never span roots, statistics on
   `root_id`/`start` only (statistics on `bases` made the footer 9 MB), and a
   page index with one row per page. A 1 kb fetch then reads ~0.5 MB in any
   engine (row-group pruning) and ~18 kB in DataFusion/polars-bio (page
   pruning; DuckDB from duckdb/duckdb#27326). Pages must be limited by rows,
   not bytes, because pruning happens on the small `start` column.
4. **Patch release membership.** Settled: patch releases add sequences and never change existing ones
   (see Roots). What remains is to find which patch release each provider's
   build actually corresponds to. For example, Ensembl 116 lacks 3 of the p14
   fix patches. Is it a clean earlier release, or a mix?
5. **Seqcol interoperability.** How the coordinate-system and cognate notions
   are exposed to seqcol. Deferred for now.
6. **Name.** Settled: **refbook**, a reference book and the referee's rulebook
   (recipes are the rules; an edition counts once it is reproduced "by the
   book"). "Registry" suggested stewardship, which isn't claimed here.
