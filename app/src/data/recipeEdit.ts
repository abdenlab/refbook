// Edits to a recipe, one part at a time, for the design form. Each takes a
// recipe and returns a new one; whatever an edit doesn't touch (other select
// entries, maps, templates) is kept, so the form never loses what the JSON
// says.
import type { Recipe, SelectEntry } from "./design.ts";

export const GRCH38 = "GCA_000001405";
export const HS38D1 = "GCA_000786075.2";
export const EBV = "AJ507799.2";
export const HLA = "IMGT/HLA 3.18.0";
export const HLA_TYPING_GROUPS = ["A", "B", "C", "DQA", "DQB", "DRB1"];   // hs38DH's
export const ROLES = ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold", "alt-scaffold", "fix-patch", "novel-patch"];
/** The roles in the form's order: novel patches (alternate loci) next to the alts. */
export const ROLES_SHOWN = ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold", "alt-scaffold", "novel-patch", "fix-patch"];
export const NAMESPACES = ["ucsc", "grc", "genbank", "refseq"];
/** Each namespace as the form shows it, with examples (a chromosome, an unlocalized scaffold). */
export const NAMESPACE_LABELS: Record<string, string> = {
  ucsc: "UCSC (chr1, chr1_KI270706v1_random)",
  grc: "GRC (1, HSCHR1_CTG1_UNLOCALIZED)",
  genbank: "GenBank (CM000663.2, KI270706.1)",
  refseq: "RefSeq (NC_000001.11, NT_187361.1)",
};

type Assembly = Extract<SelectEntry, { assembly: string }>;
const isAssembly = (e: SelectEntry): e is Assembly => "assembly" in e;
const clone = (r: Recipe): Recipe => structuredClone($raw(r));
// Svelte's $state proxies can't be structuredCloned; JSON is enough for recipes.
function $raw<T>(x: T): T { return JSON.parse(JSON.stringify(x)); }

/** The GRCh38 entry: the first select entry of a GRCh38 release. */
export function primary(r: Recipe): Assembly | undefined {
  return r.select.find((e): e is Assembly => isAssembly(e) && e.assembly.startsWith(GRCH38) && !e.accessions);
}

/** Select entries the form doesn't edit (shown, edited as JSON). */
export function others(r: Recipe): SelectEntry[] {
  const p = primary(r);
  return r.select.filter((e) => e !== p && !(isAssembly(e) && e.assembly === HS38D1)
    && !("roots" in e && e.roots.length === 1 && e.roots[0] === EBV) && !("collection" in e && e.collection === HLA));
}

export function fromScratch(): Recipe {
  return { select: [{ assembly: `${GRCH38}.15`, roles: ["assembled-molecule"] }], rename: { namespace: "ucsc" } };
}

export function setRelease(r: Recipe, accession: string): Recipe {
  const out = clone(r);
  const p = primary(out);
  if (p) p.assembly = accession;
  else out.select.unshift({ assembly: accession, roles: ["assembled-molecule"] });
  return out;
}

export function setRole(r: Recipe, role: string, on: boolean): Recipe {
  const out = clone(r);
  const p = primary(out);
  if (!p) return out;
  const roles = new Set(p.roles);
  if (on) roles.add(role); else roles.delete(role);
  p.roles = ROLES.filter((x) => roles.has(x));
  return out;
}

/** Parent types an alt or patch can be placed on (layer_placements.parent_type). */
export const PARENT_TYPES = ["chromosome", "scaffold"];

/** The parent types the GRCh38 entry keeps alts and patches placed on (all, without `placed_on`). */
export function placedOn(r: Recipe): string[] {
  return primary(r)?.placed_on ?? PARENT_TYPES;
}

/** Keep, or leave out, alts and patches placed on a parent type. Every alt and
 * patch is placed; in p14 all are on chromosomes but 3 fix patches, placed on
 * the alt scaffolds they fix (Ensembl and GENCODE leave those out). An empty
 * `placed_on` would mean no filter, so the last type can't be left out. */
export function setPlacedOn(r: Recipe, type: string, on: boolean): Recipe {
  const out = clone(r);
  const p = primary(out);
  if (!p) return out;
  const kept = new Set(placedOn(out));
  if (on) kept.add(type); else kept.delete(type);
  if (!kept.size) return out;
  if (PARENT_TYPES.every((t) => kept.has(t))) delete p.placed_on;
  else p.placed_on = PARENT_TYPES.filter((t) => kept.has(t));
  return out;
}

export const hasEbv = (r: Recipe) => r.select.some((e) => "roots" in e && e.roots.includes(EBV));
export const hasDecoys = (r: Recipe) => r.select.some((e) => isAssembly(e) && e.assembly === HS38D1);
export const hlaGroups = (r: Recipe) =>
  (r.select.find((e): e is Extract<SelectEntry, { collection: string }> => "collection" in e && e.collection === HLA)?.groups) ?? [];

/** Which HLA alleles a recipe has: none, hs38DH's six genes, or another set (edited as JSON). */
export function hlaKind(r: Recipe): "none" | "typing" | "custom" {
  const g = hlaGroups(r);
  if (!g.length) return "none";
  return g.length === HLA_TYPING_GROUPS.length && HLA_TYPING_GROUPS.every((x) => g.includes(x)) ? "typing" : "custom";
}

export function setEbv(r: Recipe, on: boolean): Recipe {
  const out = clone(r);
  out.select = out.select.filter((e) => !("roots" in e && e.roots.length === 1 && e.roots[0] === EBV));
  if (out.rename.map) delete out.rename.map[EBV];
  if (on) {
    out.select.push({ roots: [EBV] });
    if (out.rename.namespace === "ucsc") out.rename.map = { ...out.rename.map, [EBV]: "chrEBV" };
  }
  if (out.rename.map && !Object.keys(out.rename.map).length) delete out.rename.map;
  return out;
}

export function setDecoys(r: Recipe, on: boolean): Recipe {
  const out = clone(r);
  out.select = out.select.filter((e) => !(isAssembly(e) && e.assembly === HS38D1));
  if (out.rename.template) delete out.rename.template[HS38D1];
  if (on) {
    out.select.push({ assembly: HS38D1, roles: ["unplaced-scaffold"] });
    if (out.rename.namespace === "ucsc") out.rename.template = { ...out.rename.template, [HS38D1]: "chrUn_{accession_v}_decoy" };
  }
  if (out.rename.template && !Object.keys(out.rename.template).length) delete out.rename.template;
  return out;
}

/** HLA alleles of these groups (none: no HLA). */
export function setHla(r: Recipe, groups: string[], all: string[]): Recipe {
  const out = clone(r);
  out.select = out.select.filter((e) => !("collection" in e && e.collection === HLA));
  if (out.rename.template) delete out.rename.template[HLA];
  if (groups.length) {
    out.select.push({ collection: HLA, groups: all.filter((g) => groups.includes(g)) });
    out.rename.template = { ...out.rename.template, [HLA]: "HLA-{name}" };
  }
  if (out.rename.template && !Object.keys(out.rename.template).length) delete out.rename.template;
  return out;
}

export const hasMask = (r: Recipe, layer: string) => !!r.mask?.some((m) => m.layer === layer);

export function setMask(r: Recipe, layer: string, on: boolean): Recipe {
  const out = clone(r);
  const mask = (out.mask ?? []).filter((m) => m.layer !== layer);
  if (on) mask.push({ layer, with: "N" });
  if (mask.length) out.mask = mask; else delete out.mask;
  return out;
}

export function setIupacToN(r: Recipe, on: boolean): Recipe {
  const out = clone(r);
  if (on) out.alphabet = { iupac: "N" }; else delete out.alphabet;
  return out;
}

export function setNamespace(r: Recipe, namespace: string): Recipe {
  const out = clone(r);
  out.rename.namespace = namespace;
  return out;
}

/** The chromosomes' names, if not the default namespace's (Ensembl names them as GRC does, "1"; GENCODE as UCSC, "chr1"). */
export function setChromosomeNames(r: Recipe, namespace: string | null): Recipe {
  const out = clone(r);
  const by = { ...out.rename.by_role };
  if (namespace && namespace !== out.rename.namespace) by["assembled-molecule"] = namespace;
  else delete by["assembled-molecule"];
  if (Object.keys(by).length) out.rename.by_role = by; else delete out.rename.by_role;
  return out;
}

/** The guide: analysis goals, and the choices commonly made for them, each a
 * toggle: whether the recipe has the choice, and the edit that adds or removes it. */
export interface Goal {
  goal: string;
  choice: string;
  has: (r: Recipe) => boolean;
  set: (r: Recipe, on: boolean, all: { hla: string[] }) => Recipe;
}

const SCAFFOLDS = ["unlocalized-scaffold", "unplaced-scaffold"];

export const GUIDE: Goal[] = [
  { goal: "Most alignment tasks",
    choice: "the complete primary assembly: the chromosomes with the unlocalized and unplaced scaffolds, so reads from those sequences don't land on similar sequence elsewhere (bwa: \"recommended … for all analyses\")",
    has: (r) => SCAFFOLDS.every((x) => primary(r)?.roles.includes(x)),
    set: (r, on) => SCAFFOLDS.reduce((acc, x) => setRole(acc, x, on), r) },
  { goal: "Catch EBV contamination",
    choice: "the EBV genome, for reads from EBV (in EBV-transformed cell lines, for example) to align to",
    has: hasEbv, set: (r, on) => setEbv(r, on) },
  { goal: "Fewer false positives from reads of unassembled sequence",
    choice: "the hs38d1 decoys: sequence missing from GRCh38, so its reads don't land on similar sequence in it",
    has: hasDecoys, set: (r, on) => setDecoys(r, on) },
  { goal: "Alternate haplotypes",
    choice: "the alt scaffolds; without an ALT-aware aligner and their alignments (bwa-mem with an .alt file), reads in those regions lose mapping quality",
    has: (r) => !!primary(r)?.roles.includes("alt-scaffold"), set: (r, on) => setRole(r, "alt-scaffold", on) },
  { goal: "HLA typing",
    choice: `HLA alleles (${HLA_TYPING_GROUPS.join(", ")}, as hs38DH)`,
    has: (r) => hlaGroups(r).length > 0, set: (r, on, all) => setHla(r, on ? HLA_TYPING_GROUPS : [], all.hla) },
  { goal: "Masking duplicated sequence",
    choice: "the GRC hard-mask: chrY's PARs (chrX keeps them), and duplicate copies of centromeric and acrocentric arrays on chr5, 14, 19, 21 and 22",
    has: (r) => hasMask(r, "hardmask_grc"), set: (r, on) => setMask(r, "hardmask_grc", on) },
  { goal: "Tools that reject IUPAC codes",
    choice: "IUPAC → N: the few ambiguity codes in GRCh38 written as N",
    has: (r) => !!r.alphabet, set: (r, on) => setIupacToN(r, on) },
];
