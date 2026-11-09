// Edits to a recipe, one part at a time, for the design form. Each takes a
// recipe and returns a new one; whatever an edit doesn't touch (other select
// entries, maps, templates) is kept, so the form never loses what the JSON
// says. The edits know no book: what a book offers (its masks, extras, guide)
// is in shelves.ts.
import type { Recipe, SelectEntry } from "./design.ts";

export const HS38D1 = "GCA_000786075.2";
export const EBV = "AJ507799.2";
export const HS37D5 = "1000G:hs37d5";
export const HLA = "IMGT/HLA 3.18.0";
export const HLA_TYPING_GROUPS = ["A", "B", "C", "DQA", "DQB", "DRB1"];   // hs38DH's
/** Assemblies a recipe adds to its book's (the decoys): never the recipe's own assembly entry. */
const ADDON_ASSEMBLIES = [HS38D1];
export const ROLES = ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold", "alt-scaffold", "fix-patch", "novel-patch"];
/** The roles in the form's order: novel patches (alternate loci) next to the alts. */
export const ROLES_SHOWN = ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold", "alt-scaffold", "novel-patch", "fix-patch"];
/** The roles that are placed on a parent: what `placed_on`, `pad` and `orient` act on. */
export const PLACED_ROLES = ["alt-scaffold", "fix-patch", "novel-patch"];
export const NAMESPACES = ["ucsc", "grc", "genbank", "refseq"];

/** The mitochondria the catalog has, by root: an edition carries its assembly's own, another or none. */
export const MITOCHONDRIA: Record<string, string> = {
  "J01415.2": "rCRS", "AF347015.1": "Yoruba", "CP068254.1": "CHM13's",
};

type Assembly = Extract<SelectEntry, { assembly: string }>;
type Roots = Extract<SelectEntry, { roots: string[] }>;
const isAssembly = (e: SelectEntry): e is Assembly => "assembly" in e;
const isRoots = (e: SelectEntry): e is Roots => "roots" in e;
const clone = (r: Recipe): Recipe => structuredClone($raw(r));
// Svelte's $state proxies can't be structuredCloned; JSON is enough for recipes.
function $raw<T>(x: T): T { return JSON.parse(JSON.stringify(x)); }

/** The recipe's own assembly entry: the first of a release of its book (not the decoys, not a list of accessions). */
export function primary(r: Recipe): Assembly | undefined {
  return r.select.find((e): e is Assembly => isAssembly(e) && !ADDON_ASSEMBLIES.includes(e.assembly) && !e.accessions);
}

/** Roots the form adds and removes (EBV, the hs37d5 decoy, a mitochondrion). */
const FORM_ROOTS = new Set([EBV, HS37D5, ...Object.keys(MITOCHONDRIA)]);

/** Select entries the form doesn't edit (shown, edited as JSON). */
export function others(r: Recipe): SelectEntry[] {
  const p = primary(r);
  return r.select.filter((e) => e !== p && !(isAssembly(e) && e.assembly === HS38D1)
    && !(isRoots(e) && e.roots.every((x) => FORM_ROOTS.has(x))) && !("collection" in e && e.collection === HLA));
}

/** A new recipe: the chromosomes of a release, by UCSC name. */
export function fromScratch(assembly: string): Recipe {
  return { select: [{ assembly, roles: ["assembled-molecule"] }], rename: { namespace: "ucsc" } };
}

/** Another release, keeping the same mitochondrion (`mito` gives a release's own, or null): a member of the new
 * release if it has it, else added as a root. */
export function setRelease(r: Recipe, accession: string, mito: (assembly: string) => string | null = () => null): Recipe {
  let out = clone(r);
  const p = primary(out);
  const carried = p ? mitochondria(out, mito(p.assembly)) : [];
  if (p) p.assembly = accession;
  else out.select.unshift({ assembly: accession, roles: ["assembled-molecule"] });
  if (p && carried.length <= 1) out = setMitochondrion(out, mito(accession), carried[0] ?? null);
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

/** The parent types the recipe's assembly entry keeps alts and patches placed on (all, without `placed_on`). */
export function placedOn(r: Recipe): string[] {
  return primary(r)?.placed_on ?? PARENT_TYPES;
}

/** Keep, or leave out, alts and patches placed on a parent type. Every alt and
 * patch is placed; in GRCh38.p14 all are on chromosomes but 3 fix patches, placed on
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

/** How alts and patches are laid out: as submitted, N-padded into their parent's coordinates, or turned to their
 * parent's strand. */
export type Layout = "none" | "pad" | "orient";
export const layoutOf = (r: Recipe): Layout => (r.pad ? "pad" : r.orient ? "orient" : "none");

export function setLayout(r: Recipe, layout: Layout): Recipe {
  const out = clone(r);
  delete out.pad;
  delete out.orient;
  if (layout !== "none") out[layout] = { roles: [...PLACED_ROLES] };
  return out;
}

// Roots in no assembly (EBV, hs37d5, a mitochondrion): in any roots entry; added as their own entry, with a name.

export const hasRoot = (r: Recipe, root: string) => r.select.some((e) => isRoots(e) && e.roots.includes(root));

function withoutRoot(r: Recipe, root: string): Recipe {
  const out = clone(r);
  out.select = out.select
    .map((e) => (isRoots(e) ? { roots: e.roots.filter((x) => x !== root) } : e))
    .filter((e) => !isRoots(e) || e.roots.length);
  if (out.rename.map) delete out.rename.map[root];
  if (out.rename.map && !Object.keys(out.rename.map).length) delete out.rename.map;
  return out;
}

/** Add or remove a root in no assembly, named `name` (it has no name in any namespace). */
export function setRoot(r: Recipe, root: string, on: boolean, name: string): Recipe {
  const out = withoutRoot(r, root);
  if (on) {
    out.select.push({ roots: [root] });
    out.rename.map = { ...out.rename.map, [root]: name };
  }
  return out;
}

export const hasEbv = (r: Recipe) => hasRoot(r, EBV);
export const hasDecoys = (r: Recipe) => r.select.some((e) => isAssembly(e) && e.assembly === HS38D1);
export const hlaGroups = (r: Recipe) =>
  (r.select.find((e): e is Extract<SelectEntry, { collection: string }> => "collection" in e && e.collection === HLA)?.groups) ?? [];

/** Which HLA alleles a recipe has: none, hs38DH's six genes, or another set (edited as JSON). */
export function hlaKind(r: Recipe): "none" | "typing" | "custom" {
  const g = hlaGroups(r);
  if (!g.length) return "none";
  return g.length === HLA_TYPING_GROUPS.length && HLA_TYPING_GROUPS.every((x) => g.includes(x)) ? "typing" : "custom";
}

/** EBV is in no assembly report, so it has no name in any namespace: a recipe names it. */
export const EBV_NAMES = ["chrEBV", EBV];

export const setEbv = (r: Recipe, on: boolean) => setRoot(r, EBV, on, r.rename.namespace === "ucsc" ? "chrEBV" : EBV);
/** The 1000 Genomes decoy for GRCh37 (hs37d5's), one sequence: named hs37d5 by every edition that has it. */
export const setHs37d5 = (r: Recipe, on: boolean) => setRoot(r, HS37D5, on, "hs37d5");

export const ebvName = (r: Recipe) => r.rename.map?.[EBV] ?? "";

export function setEbvName(r: Recipe, name: string): Recipe {
  const out = clone(r);
  out.rename.map = { ...out.rename.map, [EBV]: name.trim() || EBV };
  return out;
}

/** The mitochondria a recipe carries: its release's own (`own`, null if the release has none) unless its assembly
 * entry excludes it, and any it adds as roots. One or none, but for a file such as UCSC's hg19.p13.plusMT. */
export function mitochondria(r: Recipe, own: string | null): string[] {
  const p = primary(r);
  const kept = own && p?.roles.includes("assembled-molecule") && !p.exclude?.includes(own) ? [own] : [];
  return [...kept, ...Object.keys(MITOCHONDRIA).filter((x) => hasRoot(r, x))];
}

/** The mitochondrion a recipe carries (the first, if it carries two), or null. */
export const mitochondrion = (r: Recipe, own: string | null): string | null => mitochondria(r, own)[0] ?? null;

/** A mitochondrion's name, as the chromosomes are named: chrM, MT, or its accession. */
export function mitochondrionName(r: Recipe, root: string): string {
  const ns = roleNamespace(r, "assembled-molecule");
  return ns === "ucsc" ? "chrM" : ns === "grc" ? "MT" : root;
}

/** Names a mitochondrion is given besides the default (UCSC's hg19.p13 files name rCRS chrMT, beside hg19's chrM). */
export const MITOCHONDRION_NAMES = ["chrM", "chrMT", "MT"];

/** The name a recipe sets for a mitochondrion, if not the default (its chromosomes' style): null for the default. */
export function mitochondrionOverride(r: Recipe, root: string): string | null {
  const name = r.rename.map?.[root];
  return name === undefined || name === mitochondrionName(r, root) ? null : name;
}

/** Name a mitochondrion `name`, or by default (null): as the chromosomes are, which for the release's own (`own`)
 * needs no rule, and for one it adds is a map entry. */
export function setMitochondrionName(r: Recipe, own: string | null, root: string, name: string | null): Recipe {
  const out = clone(r);
  const map = { ...out.rename.map };
  if (name !== null) map[root] = name;
  else if (root === own) delete map[root];
  else map[root] = mitochondrionName(out, root);
  if (Object.keys(map).length) out.rename.map = map; else delete out.rename.map;
  return out;
}

/** After a change of the chromosomes' names (`before` -> `after`): an added mitochondrion named by default follows. */
function followNames(before: Recipe, after: Recipe): Recipe {
  for (const root of Object.keys(MITOCHONDRIA)) {
    if (hasRoot(after, root) && after.rename.map?.[root] === mitochondrionName(before, root)) {
      after.rename.map[root] = mitochondrionName(after, root);
    }
  }
  return after;
}

/** Carry `choice` as the only mitochondrion, whatever the release (`own` is its own, or null): the release's own
 * is kept as its member; any other is added as a root, named as the chromosomes are, and the release's own
 * excluded; none (null) excludes the release's own. */
export function setMitochondrion(r: Recipe, own: string | null, choice: string | null): Recipe {
  let out = clone(r);
  for (const x of Object.keys(MITOCHONDRIA)) out = withoutRoot(out, x);
  const p = primary(out);
  if (!p) return out;
  const exclude = (p.exclude ?? []).filter((x) => !(x in MITOCHONDRIA));
  if (own && choice !== own) exclude.push(own);
  if (exclude.length) p.exclude = exclude; else delete p.exclude;
  if (choice && choice !== own) out = setRoot(out, choice, true, mitochondrionName(out, choice));
  return out;
}

/** How the decoys and HLA alleles can be named: the decoys have no UCSC or RefSeq
 * names and the alleles none in any namespace, so a recipe names them by template. */
export const DECOY_NAMING = [
  { template: "chrUn_{accession_v}_decoy", example: "chrUn_JTFH01000001v1_decoy" },
  { template: "{accession}", example: "JTFH01000001.1" },
];
export const HLA_NAMING = [
  { template: "HLA-{name}", example: "HLA-A*01:01:01:01" },
  { template: "{name}", example: "A*01:01:01:01" },
];

export const groupTemplate = (r: Recipe, group: string) => r.rename.template?.[group] ?? "";

export function setGroupTemplate(r: Recipe, group: string, template: string): Recipe {
  const out = clone(r);
  out.rename.template = { ...out.rename.template, [group]: template };
  return out;
}

export function setDecoys(r: Recipe, on: boolean): Recipe {
  const out = clone(r);
  out.select = out.select.filter((e) => !(isAssembly(e) && e.assembly === HS38D1));
  if (out.rename.template) delete out.rename.template[HS38D1];
  if (on) {
    out.select.push({ assembly: HS38D1, roles: ["unplaced-scaffold"] });
    out.rename.template = { ...out.rename.template,
      [HS38D1]: out.rename.namespace === "ucsc" ? DECOY_NAMING[0].template : DECOY_NAMING[1].template };
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
  return followNames(r, out);
}

/** The namespace a role's sequences are named in: its own, or the default. */
export const roleNamespace = (r: Recipe, role: string) => r.rename.by_role?.[role] ?? r.rename.namespace;

/** Name a role's sequences in a namespace (null, or the default's: by the default). */
export function setRoleNames(r: Recipe, role: string, namespace: string | null): Recipe {
  const out = clone(r);
  const by = { ...out.rename.by_role };
  if (namespace && namespace !== out.rename.namespace) by[role] = namespace;
  else delete by[role];
  if (Object.keys(by).length) out.rename.by_role = by; else delete out.rename.by_role;
  return followNames(r, out);
}

/** Every role by the default namespace: no overrides. */
export function clearRoleNames(r: Recipe): Recipe {
  const out = clone(r);
  delete out.rename.by_role;
  return followNames(r, out);
}

/** The chromosomes' names, if not the default namespace's (Ensembl names them as GRC does, "1"; GENCODE as UCSC, "chr1"). */
export const setChromosomeNames = (r: Recipe, namespace: string | null) => setRoleNames(r, "assembled-molecule", namespace);

/** A release's name in the form, without its assembly's: GRCh38.p14 is p14, GRCh38 itself p0 (with no patches),
 * T2T-CHM13v2.0 v2.0. */
export function releaseLabel(name: string, assembly: string, latest: boolean): string {
  const rest = name.startsWith(assembly) ? name.slice(assembly.length).replace(/^\./, "") : name;
  const label = rest || "p0";
  return `${label}${!rest && /^p\d/.test(label) ? " (original)" : ""}${latest ? " (latest)" : ""}`;
}
