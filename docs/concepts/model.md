# The model

Almost every human reference in use is made from a small set of original
sequences by a few operations that discard information: leaving sequences
out, masking bases, rewriting ambiguity codes, renaming. refbook stores the
originals once and describes each published file as a recipe applied to them.
The [glossary](glossary.md) defines each term precisely.

## Roots

A **root** is a sequence exactly as its submitter deposited it: an INSDC record
keyed by accession.version (`CM000663.2` is GRCh38's chr1), or, for the few
sequences with no INSDC record, an identifier refbook assigns (`1000G:hs37d5`)
or one from an external collection at a pinned release
(`IMGTHLA:3.18.0:HLA00001`). Bases are stored uppercase, with IUPAC codes kept.

The roots form one pool shared by every book. A sequence that GRCh37 and
GRCh38 both carry, such as the rCRS mitochondrion, is one root. Release 0.2.0
has 3,417:

- every sequence of every release of GRCh37 (p0–p13), GRCh38 (p0–p14, two
  superseded patch versions included) and T2T-CHM13 (v1.0, v1.1, v2.0);
- the sequences editions add from outside an assembly: the hs38d1 and hs37d5
  decoys, the Epstein–Barr virus, the Yoruba mitochondrion of hg19;
- the IMGT/HLA alleles of hs38DH, as **external roots**: refbook may not
  redistribute their bases, so the catalog holds only their identifiers and
  digests, and the library reads the bases from the IMGT/HLA release.

## Layers

A **layer** annotates roots in their own coordinates (0-based, half-open): AGP
components and gaps, where alt scaffolds and patches are placed on their
parents, named regions (centromeres, pseudoautosomal regions), IUPAC
positions, runs of `N`, soft-masking, and the hard-masks publishers apply
(the GRC's, chrY's PARs, T2T's acrocentric masks). Where no publisher gives a
mask's spans, refbook reads them from the masked files themselves.

## Operations

Four **nucleotide operations** change a root's bases:

| Operation | What it does | Length kept? |
| --- | --- | --- |
| mask | sets a layer's spans to `N` | yes |
| alphabet | turns every IUPAC code (`R`, `Y`, `M`, …) into `N` | yes |
| pad | writes an alt scaffold or patch in its parent's coordinates: `N` up to where it is placed, the scaffold, then `N` to the parent's end (Ensembl's GRCh37 files) | no |
| orient | reverse-complements a scaffold placed on the parent's minus strand, unpadded (GENCODE 19) | yes |

A root with operations applied is a **derivative**: a sequence of its own, with
its own digests. The root itself is the identity derivative. Every distinct
sequence in the catalog, and how to make it, is in the **sequence store**.

## Recipes

A **recipe** says how to make an edition from roots. It is data, one JSON
object, in `catalog/books/<book>/recipes/`. This is the GRC's GRCh38 no-alt
analysis set:

```json
{
  "select": [
    {"assembly": "GCA_000001405.15",
     "roles": ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold"]},
    {"roots": ["AJ507799.2"]}
  ],
  "mask": [{"layer": "hardmask_grc", "with": "N"}],
  "rename": {"namespace": "ucsc", "map": {"AJ507799.2": "chrEBV"}}
}
```

- **select** chooses roots: an assembly release's members by role (optionally
  `exclude`-ing some, such as the release's own mitochondrion when an edition
  carries another), loose roots such as EBV, or external roots by group.
- **mask**, **alphabet**, **pad** and **orient** apply the operations above.
- **rename** names each sequence: a naming convention (`ucsc`, `genbank`,
  `refseq`, `ensembl`, `grc`), per role if need be, with explicit names or a
  template for the exceptions.

Order and formatting are not part of a recipe. A published file's order is
recorded as observed (see [Order](#order)).

## Editions

The output of a recipe is an **edition**: a set of named sequences. An edition
is identified by a digest of its (name, sequence) pairs that ignores their
order, so two files with the same sequences under the same names are the same
edition, whatever their order, line width or compression. refbook gives each
edition a label (`grch38-no-alt`, `hs38dh`, `chm13v2.0-maskedY`).

The published files a recipe reproduces are its **targets**, and each
publisher's name for a file (`hg38.analysisSet`, `GATK/GRCh38`) is an
**alias** of its edition. One edition often has several: the GRC's no-alt
analysis set and iGenomes' `NCBI/GRCh38` are the same edition, as are the
Broad's `Homo_sapiens_assembly38` and 1000 Genomes'
`GRCh38_full_analysis_set_plus_decoy_hla`.

## Books

A **book** is an assembly, every release of it, the sequences its editions add
from elsewhere, and the editions made from them: GRCh37, GRCh38 and
T2T-CHM13 so far. Each book also records what is particular to it: where its
hard-masks come from, how alt scaffolds are placed in it, and where names come
from beyond the assembly reports.

## Order

Order is recorded, not reproduced. One edition can appear in several orders
(Ensembl's GRCh37 toplevel lists its chromosomes first in release 75, its
patches first in release 116), and each published file's order is kept as an
observation.
Order matters to formats that refer to sequences by position: BAM and CRAM
reference IDs, coordinate-sorted files, genome-wide offsets. So identification
reports it separately: which published files list the sequences in the order
your header does.

## Reconstruction is the verification

A file counts as cataloged only once its recipe reproduces it, sequence by
sequence: every name, length, MD5 and `SQ.` digest. A label can't be wrong,
because it isn't asserted: it names a recipe that has been checked. A file
that doesn't reproduce is a finding in its own right: a root we lack, or an
operation we haven't modeled. Rebuilding the files turned up details no
publisher documents, among them the order UCSC uses, which patches Ensembl
leaves out, how bwakit chose its HLA alleles, and an off-by-one in two of
T2T's masked sets that leaves chrY's first base unmasked.
