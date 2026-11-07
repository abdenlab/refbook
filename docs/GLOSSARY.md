# Glossary

The terms refbook uses, grouped from the genome outward.

## The model

**root sequence**
: A source sequence exactly as its issuer released it: an INSDC record
  (accession.version, e.g. `CM000663.2`) or a sequence from an external
  collection at a pinned release (e.g. `IMGTHLA:3.18.0:HLA00001`). Bases are
  stored uppercase, with IUPAC codes kept. Roots are the top-level sequences
  that are used to build target sequence collections: every sequence in a
  cataloged target collection is derived from exactly one root sequence, with
  the same length and coordinates.

**external root sequence**
: A root sequence whose bases refbook may not redistribute (the IPD-IMGT/HLA
  alleles). The catalog holds its identity and digests; a library fetches the
  bases from the source and checks them against the digests.

**annotation layer**
: An annotation of a root sequence in root coordinates, 0-based half-open.
  These include AGP parts, N-runs, IUPAC positions, soft-masking, regions,
  placements, hard-masks.

**nucleotide operation**
: A change to a root sequence's bases that preserves its length. There are
  currently two, both setting positions to `N`: **mask** (a layer's spans,
  e.g. the GRC hard-mask) and **alphabet** (IUPAC codes → `N`).

**derivative sequence**
: A sequence generated from a root sequence by applying nucleotide operations.
  The root sequence with no operations applied is the **identity derivative**.
  Like any sequence, a derivative is identified by the digest of its own
  bases. The root and the operations record how to make a derivative, but they
  don't identify it, because different sets and orderings of operations can
  produce the same bases.

**identifier**
: A computed value, usually a digest, used to determine or compare the
  identity of a sequence, sequence set, named sequence set, or sequence
  collection.

**sequence set**
: An unordered collection of sequences, ignoring any names. Identifiable by
  the digest of its sorted `SQ.` digests (seqcol's `sorted_sequences`).
  Strictly this is a multiset: if two entries have identical bases, both are
  kept. A **subset** is identifiable by comparing the individual sequence
  digests.

**named sequence set**
: An unordered collection of named sequences, where no name is repeated.
  Identifiable by an order-independent digest of its (name, sequence) pairs:
  digest each pair, sort the pair digests, and digest the sorted list. A 
  subset is identifiable by comparing the pair digests. 

**edition**
: A named sequence set that refbook catalogs, together with a recipe that
  derives it from root sequences and a label chosen by refbook. An edition is
  identified by its named sequence set's digest, so order, formatting and file
  type play no part, and neither do who made it or how it was found. Each
  target collection that reproduces it is recorded as having that edition. The
  names the targets' publishers use (e.g. "UCSC hg38.analysisSet", "iGenomes
  UCSC/hg38") are **aliases** of the edition, and one edition often has several:
  the GRC no-alt analysis set and iGenomes NCBI/GRCh38 are the same edition.

**sequence collection**
: An ordered collection of named sequences. Identifiable by a digest that
  depends on the names, the sequences and their order (the seqcol top-level
  digest). Forgetting a collection's order gives its named sequence set; many
  collections can share one.

**sequence order**
: The order of a sequence collection. It is not part of an edition's identity: a
  target's order is recorded as an observation, and one edition can appear in
  several orders (UCSC's `hg38.fa` and `hg38.chrom.sizes`). Order matters to
  formats that refer to sequences by position: BAM and CRAM reference IDs,
  coordinate-sorted files, and genome-wide offsets. A FASTA's order on disk
  means nothing in itself, since an indexed FASTA can be read in any order,
  but tools that build a sequence dictionary from a FASTA usually adopt its
  order.

**coordinate system**
: The names and lengths of a collection's sequences, without the bases. The
  seqcol spec defines it as ordered (`name_length_pairs`, "the ordered
  coordinate system") and also gives an order-invariant form
  (`sorted_name_length_pairs`). Data files such as BED are compatible with a
  reference when their coordinate systems match.

**refget Sequence Collection representation** (seqcol)
: The data structure defined by the GA4GH Sequence Collections standard, whose
  stated goal is to standardize identifiers for collections of sequences. It
  consists of parallel (collated) arrays of names, lengths and sequence
  digests, where position *i* in each array describes the same sequence. Two
  of these arrays, `names` and `sequences`, are the **inherent** attributes:
  only they determine the collection's identity. `lengths` is required but not
  inherent, since the sequences imply it, and a representation may carry
  further non-inherent attributes. A level is the number of lookups from the
  top-level digest:
  - **Level 0**, the top-level digest, is the digest of the level-1 digests of
    `names` and `sequences`. It identifies the collection and depends on the
    names, the sequences and their order.
  - **Level 1**, one lookup away, has one digest per attribute (RFC-8785
    canonical JSON of the array, then `sha512t24u`), for inherent and
    non-inherent attributes alike. **Passthru** attributes appear here
    undigested, with the same value as at level 2.
  - **Level 2**, two lookups away, is the **canonical seqcol representation**:
    an object of arrays, with the sequences given as `SQ.` digests.
    **Transient** attributes are absent here; they exist only as level-1
    digests.

  Resolving the `SQ.` digests of level 2 gives the fully undigested collection
  of named sequences; that step goes through a refget sequences server and is
  outside the seqcol spec. All levels can be computed from a FASTA, from the
  bases. A `.dict` or BAM header with MD5s gives `names` and `lengths`
  directly; its `sequences` digest, and so the top-level digest, can be
  recovered only through a precomputed mapping from MD5 to `SQ.` digests. A
  `.fai` or `chrom.sizes` gives only names, order and lengths: enough for the
  `names` and `lengths` digests and the coordinate system, but not for
  `sequences` or the top level.

**resolve**
: To replace a digest with the content it identifies; an `SQ.` digest resolves
  to bases. Files hold a sequence collection resolved to different depths:
  - a **FASTA** is fully resolved: names, order and bases;
  - a **`.dict`** is at seqcol level 2: names, order, lengths and sequence
    digests (MD5), nothing resolved;
  - a **`.fai`** or **`chrom.sizes`** is a partial level 2: names, order and
    lengths, with no sequence identities.

  Formatting (line width, case, compression) is never part of an identity.

**target**
: A collection or file that refbook reproduces: a FASTA, or a `.dict` when the
  FASTA isn't fetched, from wherever it was found and whoever made it. Its
  observation is recorded in the release.

**recipe**
: How an edition is generated from root sequences: **select** (which roots are
  used), nucleotide operations, and **rename** (what each is called). Recipes
  are data, in `catalog/books/<book>/recipes/`.

**manifest**
: A recipe's resolved result: one row per sequence with its name, root
  sequence, nucleotide operations and digests. It is what every consumer
  (materialize, fetch, identify, seqcol) reads. Its rows are a seqcol
  representation of the edition, with the root and operations as non-inherent
  collated attributes.

**reproduction**
: Running a recipe and checking that its named sequence set equals a target's:
  the same names, each with the same length and digest. The target's order is
  recorded as an observation, not matched. An edition is cataloged only once it
  reproduces. "Reconstruction is the verification."

**observation**
: What a target was found to contain, per sequence, in file order: names,
  lengths, digests, and formatting such as line width. Digests come from the
  FASTA itself (computed by us) or from a `.dict` (MD5s claimed by its
  publisher). Recorded in the release.

**catalog**, **release**
: The published tables (roots, bases, layers, aliases, manifests, seqcol,
  observations) at a version, with an index of file hashes (`catalog.json`).

## Digests and identifiers

**MD5** (refget)
: MD5 of the uppercased bases. Refget removes everything outside A–Z before
  digesting; refbook's canonicalization policy rejects such characters first,
  so nothing is removed. Used by SAM/BAM `M5`, CRAM and htslib's `REF_CACHE`.

**`SQ.` digest** (`sha512t24u`, refget "ga4gh")
: The characters `SQ.` followed by the base64url of the first 24 bytes of
  SHA-512, over the same canonical bases. `SQ` is the type prefix for a
  sequence in GA4GH computed identifiers, from the Variation Representation
  Specification (VRS), which introduced `sha512t24u`.

**canonicalization policy**
: The rule turning a raw FASTA record into the bytes that are stored, measured
  and digested: whitespace removed, lowercase recorded then uppercased, any
  other character outside A–Z an error.

**seqcol digests**
: The level-0 and level-1 digests of a seqcol representation; see that entry.
  Order-independent ones are `sorted_name_length_pairs` (the coordinate
  system), `sorted_sequences` (the sequence set) and, a new one proposed here,
  `sorted_named_sequences` (the named sequence set, an edition's identity).

The examples are for a toy collection with `names = ["chr2", "chr1"]`,
`lengths = [20, 10]` and `sequences = ["SQ.bbb", "SQ.aaa"]`. `d(x)` stands
for the `sha512t24u` digest of the canonical JSON of `x`, and "sorted" means
sorted as strings.

| Attribute | Names? | Bases? | Order? | Identifies | Level 2 example |
| --- | --- | --- | --- | --- | --- |
| `name_length_pairs` | ✓ | ✗ | ✓ | the ordered coordinate system | `[{"name":"chr2","length":20}, {"name":"chr1","length":10}]` |
| `sorted_name_length_pairs` | ✓ | ✗ | ✗ | the order-invariant coordinate system | sorted `[d({"length":20,"name":"chr2"}), d({"length":10,"name":"chr1"})]` |
| `sorted_sequences` | ✗ | ✓ | ✗ | the sequence set | `["SQ.aaa", "SQ.bbb"]` |
| **`sorted_named_sequences`** | ✓ | ✓ | ✗ | **the named sequence set (an edition)** | sorted `[d({"name":"chr2","sequence":"SQ.bbb"}), d({"name":"chr1","sequence":"SQ.aaa"})]` |

`name_length_pairs` and `sorted_name_length_pairs` are recommended by the
seqcol spec and `sorted_sequences` is optional; `named_sequences` is
suggested in its footnote F1, and `sorted_named_sequences` is refbook's
proposal, built from `named_sequences` the way `sorted_name_length_pairs` is
built from `name_length_pairs`.

**alias**, **namespace**
: Another name for a root sequence in a naming convention (namespace):
  `genbank`, `refseq`, `ucsc`, `grc` (the GRC Sequence-Name), `ensembl`,
  `imgt`. The seqcol spec also uses "alias" for a human-readable name of a
  collection; refbook uses it that way for editions.

## Assemblies (GRCh38)

**assembly**, **major release**, **patch release**
: GRCh38, officially with no `.p` suffix (`.p0` is shorthand used by others),
  is the major release, GenBank `GCA_000001405.15`. Patch releases go from
  `.16` (p1) to `.29` (p14). Patch releases add sequences (patches) and never
  change the original sequences of the major release. Patches are standalone
  sequences placed against the original chromosomes; they don't stack, so a
  patch whose span needs a further fix is replaced by a new version, as two
  fix patches from p13 were in p14. Only a major release changes the
  chromosomes and their coordinates.

**assembly report**
: NCBI's per-release table of top-level sequences: role, assigned molecule,
  assembly unit, GenBank and RefSeq accessions, UCSC name. Defines which
  sequences are in a release.

**role**
: A sequence's kind in the report: **assembled-molecule** (a chromosome or
  chrM), **unlocalized-scaffold** (known chromosome, unknown position),
  **unplaced-scaffold** (unknown chromosome), **alt-scaffold** (an alternate
  haplotype of a region), **fix-patch** (a correction to the primary
  assembly), **novel-patch** (new alternate sequence).

**assembly unit**
: A partition of the assembly: Primary Assembly, the ALT_REF_LOCI_* units,
  PATCHES, non-nuclear (chrM).

**component**, **scaffold**, **placed scaffold**
: The assembly is built in levels: components (clone or WGS sequences) are
  joined, as slices with gaps between them, into scaffolds, and placed
  scaffolds plus gaps are joined into chromosomes. A placed scaffold (e.g.
  `GL000001.2`) is a slice of a chromosome: it has an INSDC record and appears
  in the release's AGP files, but it is not one of the release's top-level
  sequences, so no target contains it. Unlocalized and unplaced scaffolds are
  top-level sequences.

**AGP**
: The file format describing how an **object** (the sequence a row builds) is
  built from components and gaps, 1-based inclusive. "Object" and "component"
  are roles within one file: `GL000001.2` is a component of chr1 in one AGP
  and the object in another.

**gap**
: An AGP row of `N`s with a type (contig, scaffold, centromere, telomere, …)
  and linkage evidence. Not every run of `N` is a gap: some lie inside
  components.

**region**
: A named span on a chromosome: alt-loci regions (where alts and patches
  attach), centromeres (CEN), pseudoautosomal regions (PAR), heterochromatin
  (HET). Spans can change between releases.

**placement**
: Where an alt scaffold or patch aligns to its parent sequence. It splits the
  scaffold into up to three pieces: an **aligned span** (matched to a span of
  the parent by alignment, not by identical sequence) and, at either end,
  **tails** that don't align to the parent. Most placements have no tails. A
  placement is not a coordinate mapping; the alignments themselves are
  separate files.

**hard-mask**, **cognate**
: Bases replaced with `N` so reads don't map to two identical copies. The GRC
  masks chrY's PARs and some centromere and acrocentric duplicates in its
  analysis sets; each masked span's identical, unmasked copy is its cognate.

**soft-mask**
: Repeats shown in lowercase. An annotation, not part of any digest.

**IUPAC code**
: An ambiguity letter other than A, C, G, T, N (e.g. `R`, `Y`, `M`). GRCh38
  keeps a few; many publishers convert them to `N`.

**decoy**
: Extra sequences (hs38d1, `GCA_000786075.2`) that soak up reads which would
  otherwise mismap. Similarly EBV, and the HLA alleles in hs38DH.

**analysis set**
: A reference built for alignment pipelines: the GRC's four sets, UCSC's
  `analysisSet`, Broad's and 1000 Genomes' versions of hs38DH. Typically
  hard-masked, with EBV and sometimes decoys.
