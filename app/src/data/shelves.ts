// What the Editor offers for each book: its masks, the sequences it can add, the other mitochondria it can carry,
// the guide's goals and the notes. The rest of the shelf (releases, roles and their counts, names, whether IUPAC
// codes or placements exist) comes from the catalog's tables (design.ts).
import type { Recipe } from "./design.ts";
import * as edit from "./recipeEdit.ts";

/** A sequence a recipe can add: whether it has it, and the edit that adds or removes it. */
export interface Extra {
  id: "ebv" | "hs38d1" | "hla" | "hs37d5";
  label: string;
  has: (r: Recipe) => boolean;
  set: (r: Recipe, on: boolean, ctx: Context) => Recipe;
}

/** What a goal's or an extra's edit needs from the tables: the HLA groups there are, and the release's own
 * mitochondrion. */
export interface Context { hla: string[]; mito: string | null }

/** The guide: analysis goals, and the choices commonly made for them, each a toggle: whether the recipe has the
 * choice, and the edit that adds or removes it. */
export interface Goal {
  goal: string;
  choice: string;
  has: (r: Recipe, ctx: Context) => boolean;
  set: (r: Recipe, on: boolean, ctx: Context) => Recipe;
}

export interface Shelf {
  /** The masks the shelf offers, by layer (an edition's other masks are kept, and shown in its recipe). */
  masks: { layer: string; label: string }[];
  extras: Extra[];
  /** Mitochondria besides the release's own an edition of the book carries. */
  mitochondria: string[];
  guide: Goal[];
  /** Footnotes to the shelf, under its headings: what each choice is, where it comes from. */
  notes: [string, [string, string][]][];
}

const EXTRAS: Record<Extra["id"], Extra> = {
  ebv: { id: "ebv", label: "EBV", has: edit.hasEbv, set: (r, on) => edit.setEbv(r, on) },
  hs38d1: { id: "hs38d1", label: "hs38d1 decoys", has: edit.hasDecoys, set: (r, on) => edit.setDecoys(r, on) },
  hla: { id: "hla", label: "HLA alleles", has: (r) => edit.hlaGroups(r).length > 0,
         set: (r, on, ctx) => edit.setHla(r, on ? edit.HLA_TYPING_GROUPS : [], ctx.hla) },
  hs37d5: { id: "hs37d5", label: "hs37d5 decoy", has: (r) => edit.hasRoot(r, edit.HS37D5), set: (r, on) => edit.setHs37d5(r, on) },
};

const SCAFFOLDS = ["unlocalized-scaffold", "unplaced-scaffold"];
const COMPLETE_PRIMARY: Goal = {
  goal: "Most alignment tasks",
  choice: "the complete primary assembly: the chromosomes with the unlocalized and unplaced scaffolds, so reads from those sequences don't land on similar sequence elsewhere (bwa: \"recommended … for all analyses\")",
  has: (r) => SCAFFOLDS.every((x) => edit.primary(r)?.roles.includes(x)),
  set: (r, on) => SCAFFOLDS.reduce((acc, x) => edit.setRole(acc, x, on), r),
};
const EBV_GOAL: Goal = {
  goal: "Catch EBV contamination",
  choice: "the EBV genome, for reads from EBV (in EBV-transformed cell lines, for example) to align to",
  has: edit.hasEbv, set: (r, on) => edit.setEbv(r, on),
};
const ALTS: Goal = {
  goal: "Alternate haplotypes",
  choice: "the alt scaffolds; without an ALT-aware aligner and their alignments (bwa-mem with an .alt file), reads in those regions lose mapping quality",
  has: (r) => !!edit.primary(r)?.roles.includes("alt-scaffold"), set: (r, on) => edit.setRole(r, "alt-scaffold", on),
};
const iupacGoal = (assembly: string): Goal => ({
  goal: "Tools that reject IUPAC codes",
  choice: `IUPAC → N: the few ambiguity codes in ${assembly} written as N`,
  has: (r) => !!r.alphabet, set: (r, on) => edit.setIupacToN(r, on),
});
const maskGoal = (goal: string, choice: string, layer: string): Goal => ({
  goal, choice, has: (r) => edit.hasMask(r, layer), set: (r, on) => edit.setMask(r, layer, on),
});
/** A goal met by carrying another mitochondrion than the release's own (or the own again, switched off). */
const mitoGoal = (goal: string, choice: string, root: string): Goal => ({
  goal, choice, has: (r, ctx) => edit.mitochondrion(r, ctx.mito) === root,
  set: (r, on, ctx) => edit.setMitochondrion(r, ctx.mito, on ? root : ctx.mito),
});

const NAMES_NOTE: [string, string] = ["Name style", "Every sequence is named from one namespace: UCSC (chr1), the GRC's sequence names (1), GenBank accessions or RefSeq accessions. A role's override names that role from another."];
const ROLE_NOTE: [string, string] = ["Role", "Each sequence's role in the assembly, from its assembly report: chromosomes (1–22, X, Y and the mitochondrion); unlocalized scaffolds, on a known chromosome at an unknown position (chr1_…_random); unplaced scaffolds, on no known chromosome (chrUn_…); alt scaffolds, alternate haplotypes of a region (…_alt); and the patches, novel (new alternates) and fix (corrections). The counts are the release's."];
const MITO_NOTE: [string, string] = ["Mitochondrion", "rCRS (J01415.2, NC_012920.1) is the standard mitochondrial reference: haplogroups, mtDNA variant databases and heteroplasmy tools use its coordinates. Another mitochondrion replaces the release's own and is named as the chromosomes are (chrM, MT, or its accession)."];
const EBV_NOTE: [string, string] = ["EBV", `The Epstein–Barr virus genome (${edit.EBV}), in no assembly: for reads from EBV-transformed cell lines. Named chrEBV with UCSC names, by accession otherwise.`];
const IUPAC_NOTE: [string, string] = ["IUPAC → N", "Every ambiguity code (R, Y, M, …) becomes N, as some tools need."];
const LAYOUT_NOTE: [string, string] = ["Laid out", "As submitted, or laid out in their parent's coordinates (N-padded to the chromosome's length, as Ensembl's GRCh37 toplevel), or turned to their parent's strand (as GENCODE 19)."];

export const SHELVES: Record<string, Shelf> = {
  grch38: {
    masks: [{ layer: "hardmask_grc", label: "GRC hard-mask" }],
    extras: [EXTRAS.ebv, EXTRAS.hs38d1, EXTRAS.hla],
    mitochondria: [],
    guide: [
      COMPLETE_PRIMARY, EBV_GOAL,
      { goal: "Fewer false positives from reads of unassembled sequence",
        choice: "the hs38d1 decoys: sequence missing from GRCh38, so its reads don't land on similar sequence in it",
        has: edit.hasDecoys, set: (r, on) => edit.setDecoys(r, on) },
      ALTS,
      { goal: "HLA typing",
        choice: `HLA alleles (${edit.HLA_TYPING_GROUPS.join(", ")}, as hs38DH)`,
        has: (r) => edit.hlaGroups(r).length > 0, set: (r, on, ctx) => edit.setHla(r, on ? edit.HLA_TYPING_GROUPS : [], ctx.hla) },
      maskGoal("Masking duplicated sequence",
        "the GRC hard-mask: chrY's PARs (chrX keeps them), and duplicate copies of centromeric and acrocentric arrays on chr5, 14, 19, 21 and 22",
        "hardmask_grc"),
      iupacGoal("GRCh38"),
    ],
    notes: [
      ["GRCh38", [
        ["Release", "p0 is GRCh38 as first released (GCA_000001405.15). Each patch release adds fix and novel patches; none changes the chromosomes."],
        ROLE_NOTE, NAMES_NOTE, MITO_NOTE,
      ]],
      ["Alts and patches", [
        ["Placed on", "Every alt and patch is placed on the sequence it is an alternative to, or fixes. In p14 all are placed on chromosomes but 3 fix patches, which fix alt scaffolds; Ensembl and GENCODE leave those 3 out."],
        LAYOUT_NOTE,
      ]],
      ["Additional sequences", [
        EBV_NOTE,
        ["hs38d1 decoys", `Sequence missing from GRCh38 (${edit.HS38D1}), so its reads don't land on similar sequence elsewhere. Named like chrUn_JTFH01000001v1_decoy with UCSC names, by accession otherwise.`],
        ["HLA alleles", `Alleles of the six genes hs38DH has (${edit.HLA_TYPING_GROUPS.join(", ")}) from ${edit.HLA}, named like HLA-A*01:01:01:01. Their licence (CC BY-ND) keeps refbook from hosting their bases.`],
      ]],
      ["Bases", [
        ["GRC hard-mask", "The spans the GRC replaces with N in its analysis sets: duplicated centromeric and WGS arrays on chromosomes 5, 14, 19, 21 and 22, and the pseudoautosomal regions on chrY."],
        IUPAC_NOTE,
      ]],
    ],
  },
  grch37: {
    masks: [{ layer: "par_y", label: "chrY's PARs" }],
    extras: [EXTRAS.ebv, EXTRAS.hs37d5],
    mitochondria: ["AF347015.1"],
    guide: [
      COMPLETE_PRIMARY, EBV_GOAL,
      { goal: "Fewer false positives from reads of unassembled sequence",
        choice: "the hs37d5 decoy: sequence missing from GRCh37, gathered by the 1000 Genomes Project, so its reads don't land on similar sequence in it",
        has: (r) => edit.hasRoot(r, edit.HS37D5), set: (r, on) => edit.setHs37d5(r, on) },
      maskGoal("Reads from the pseudoautosomal regions on chrX only",
        "chrY's PARs as N, as the 1000 Genomes references (b37, hs37d5), Ensembl and the GRC's analysis sets do, so PAR reads aren't split between X and Y",
        "par_y"),
      mitoGoal("Matching UCSC's hg19",
        "the Yoruba mitochondrion (NC_001807, AF347015.1), which hg19 carries as chrM instead of GRCh37's rCRS: its coordinates differ, so mitochondrial calls on one don't carry to the other",
        "AF347015.1"),
      ALTS,
      iupacGoal("GRCh37"),
    ],
    notes: [
      ["GRCh37", [
        ["Release", "p0 is GRCh37 as first released (GCA_000001405.1), and UCSC's hg19; p13 is the last. Each patch release adds fix and novel patches; none changes the chromosomes. p0 and p1 have no mitochondrion: the GRC added rCRS in p2."],
        ROLE_NOTE, NAMES_NOTE, MITO_NOTE,
        ["Yoruba", "The mitochondrion of a Yoruba individual (AF347015.1, NC_001807), UCSC's chrM in hg19: 16,571 bp, two longer than rCRS, on another numbering."],
      ]],
      ["Alts and patches", [
        ["Placed on", "Every alt and patch is placed on the sequence it is an alternative to, or fixes."],
        LAYOUT_NOTE,
      ]],
      ["Additional sequences", [
        EBV_NOTE,
        ["hs37d5 decoy", "The 1000 Genomes Project's decoy for GRCh37: one sequence of 35.5 Mb, named hs37d5, of human sequence missing from GRCh37. The hs37d5 reference is b37 with EBV (named NC_007605) and this decoy."],
      ]],
      ["Bases", [
        ["chrY's PARs", "The pseudoautosomal regions on chrY as N, from GRCh37's region definitions, so their reads align to chrX only."],
        IUPAC_NOTE,
      ]],
    ],
  },
  "t2t-chm13": {
    masks: [
      { layer: "par_y", label: "chrY's PARs" },
      { layer: "chry", label: "all of chrY" },
      { layer: "t2t_dj_rdna_phr", label: "acrocentric DJ, rDNA, PHR" },
      { layer: "t2t_5s_rdna", label: "5S rDNA array" },
    ],
    extras: [EXTRAS.ebv],
    mitochondria: ["J01415.2"],
    guide: [
      { goal: "Short-read variant calling",
        choice: "chrY's PARs as N and rCRS for the mitochondrion: chm13v2.0_maskedY_rCRS, which the consortium recommends for mapping short reads (github.com/marbl/CHM13)",
        has: (r) => edit.hasMask(r, "par_y") && edit.mitochondrion(r, "CP068254.1") === "J01415.2",
        set: (r, on, ctx) => edit.setMitochondrion(edit.setMask(r, "par_y", on), ctx.mito, on ? "J01415.2" : ctx.mito) },
      maskGoal("XX samples",
        "all of chrY as N, so no read lands on it (T2T-Ref's masked sets for XX samples)",
        "chry"),
      maskGoal("Copy number and variants in the acrocentric short arms",
        "the near-identical distal junctions, rDNA arrays and pseudo-homologous regions of the acrocentric short arms masked but for one copy each, on chr13, for reads to land on (T2T-Ref)",
        "t2t_dj_rdna_phr"),
      maskGoal("5S rDNA",
        "the chr1 5S rDNA array masked but its first unit, as T2T-Ref's _5S sets",
        "t2t_5s_rdna"),
      mitoGoal("Mitochondrial variants comparable with other data",
        "rCRS in place of CHM13's own mitochondrion: CHM13's is rotated to start 576 bases into rCRS, so its coordinates differ by about 16 kb",
        "J01415.2"),
      EBV_GOAL,
    ],
    notes: [
      ["T2T-CHM13", [
        ["Release", "v1.0 and v1.1 are the gapless CHM13 assembly, without chrY: CHM13 has none. v2.0 adds chrY, from a different individual (HG002). The consortium's chm13v2.0_noY is v1.1, for benchmarking assemblies of CHM13."],
        ["Role", "T2T-CHM13 is chromosomes only: no scaffolds, alts or patches."],
        NAMES_NOTE, MITO_NOTE,
        ["CHM13's mitochondrion", "CP068254.1, assembled with the rest: 16,569 bp like rCRS, but rotated to start at rCRS's 577 (tRNA-Phe), and three differences."],
      ]],
      ["Additional sequences", [EBV_NOTE]],
      ["Bases", [
        ["chrY's PARs", "The pseudoautosomal regions on chrY as N (chm13v2.0_maskedY), so their reads align to chrX only."],
        ["All of chrY", "chrY as N, for XX samples (T2T-Ref's forXX sets). The _noY masked sets leave its first base, as published; that mask is chry_from_2, set in the recipe."],
        ["Acrocentric", "The distal junctions (DJ) and rDNA arrays of chr14, 15, 21 and 22, the pseudo-homologous regions (PHR) of chr14 and 21, and chr13's rDNA but its first unit: chr13 keeps one copy of each for reads to land on. The regions are those of Arang Rhie's T2T-Ref README, checked against the consortium's masked sets."],
        ["5S rDNA", "The 5S rDNA array on chr1 but its first unit (T2T-Ref's _5S sets)."],
      ]],
    ],
  },
};

/** A book's shelf: an empty one for a book the Editor has no words for yet. */
export const shelfOf = (book: string): Shelf => SHELVES[book] ?? { masks: [], extras: [], mitochondria: [], guide: [], notes: [] };
