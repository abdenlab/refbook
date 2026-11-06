// Design your own flavor: compile a recipe in the browser (the core's
// compiler, over the catalog's tables), give each sequence its digests from
// the catalog's derivations, and say what the result is.
import * as rb from "@abdenlab/refbook";
import type { Catalog } from "./catalog.ts";
import type { Place } from "./exports.ts";
import type { Flavor, ManifestRow } from "./flavors.ts";
import { measure } from "./meter.ts";

/** A recipe, in the grammar the core compiles (docs: catalog/40_recipes.py). */
export interface Recipe {
  select: SelectEntry[];
  mask?: { layer: string; with: "N" }[];
  alphabet?: { iupac: "N" };
  rename: { namespace: string; by_role?: Record<string, string>; map?: Record<string, string>; template?: Record<string, string> };
}
export type SelectEntry =
  | { assembly: string; roles: string[]; accessions?: string[]; placed_on?: string[] }
  | { roots: string[] }
  | { collection: string; groups: string[] };

export interface DesignTables {
  compiler: rb.RecipeTables;
  /** root_id -> length, every root. */
  rootLength: Map<string, number>;
  /** "root_id ops..." -> {sha512t24u, md5} of every known derivation. */
  derived: Map<string, { sha512t24u: string; md5: string }>;
  /** Assembly releases: accession -> name (GRCh38, GRCh38.p1, ..., hs38d1). */
  assemblies: Map<string, string>;
  /** External collections: name -> groups, in rank order. */
  collections: Map<string, string[]>;
  /** The mask layers there are. */
  layers: string[];
  /** Assembly accession -> role -> how many sequences it has. */
  roleCounts: Map<string, Map<string, number>>;
  /** root_id -> where it goes in karyotypic order (exports.ts). */
  places: Map<string, Place>;
}

const key = (root: string, ops: string[]) => [root, ...ops].join(" ");
const GRCH38 = "GCA_000001405.";

let loaded: Promise<DesignTables> | null = null;

type PlaceMember = { assembly_accession: string; assembly_name: string; genbank_accession: string; role: string; assembly_unit: string; assigned_molecule: string | null };

/** Where each root belongs: its assembly, role, unit and molecule (the first record; none differs), or its external collection. */
function placesOf(members: PlaceMember[], external: { root_id: string; collection: string; rank: number }[]): Map<string, Place> {
  const places = new Map<string, Place>();
  for (const m of members) {
    if (places.has(m.genbank_accession)) continue;
    const grch38 = m.assembly_accession.startsWith(GRCH38);
    places.set(m.genbank_accession, { grch38, assembly: grch38 ? "GRCh38" : m.assembly_name, role: m.role, unit: m.assembly_unit, molecule: m.assigned_molecule ?? "" });
  }
  for (const e of external) places.set(e.root_id, { collection: e.collection, rank: e.rank });
  return places;
}

let placed: Promise<Map<string, Place>> | null = null;

/** Just the places (about 0.1 MB, once): for showing roles and units without the compiler's tables. */
export function rootPlaces(cat: Catalog): Promise<Map<string, Place>> {
  return (placed ??= Promise.all([
    cat.table<PlaceMember>("assembly_members.parquet"),
    cat.table<{ root_id: string; collection: string; rank: number }>("roots_external.parquet"),
  ]).then(([m, e]) => placesOf(m, e)));
}

/** The tables the compiler and the digests need (about 0.4 MB, once). */
export function designTables(cat: Catalog): Promise<DesignTables> {
  return (loaded ??= measure("design tables", async () => {
    type Member = { assembly_accession: string; assembly_name: string; genbank_accession: string; role: string;
      assigned_molecule: string | null; assembly_unit: string; ucsc_name: string | null; sequence_name: string | null; refseq_accession: string | null };
    const [members, placements, hardmask, iupac, external, sequences, derivations] = await Promise.all([
      cat.table<Member>("assembly_members.parquet"),
      cat.table<{ root_id: string; parent_type: string }>("layer_placements.parquet"),
      cat.table<{ root_id: string }>("layer_hardmask_grc.parquet"),
      cat.table<{ root_id: string }>("layer_iupac.parquet"),
      cat.table<{ root_id: string; collection: string; group: string; name: string | null; rank: number }>("roots_external.parquet"),
      cat.table<{ sha512t24u: string; md5: string; length: number; root_id: string; operations: string[] }>("sequences.parquet"),
      cat.table<{ sha512t24u: string; root_id: string; operations: string[] }>("derivations.parquet"),
    ]);
    const md5 = new Map(sequences.map((s) => [s.sha512t24u, s.md5]));
    const rootLength = new Map(sequences.filter((s) => !s.operations.length).map((s) => [s.root_id, s.length]));
    const ext = [...external].sort((a, b) => a.rank - b.rank);
    const compiler = rb.recipeTables({
      members: members.map((m) => ({ assembly_accession: m.assembly_accession, genbank_accession: m.genbank_accession, role: m.role,
        ucsc_name: m.ucsc_name, sequence_name: m.sequence_name, refseq_accession: m.refseq_accession })),
      roots: [...rootLength.keys()],
      iupac: [...new Set(iupac.map((r) => r.root_id))],
      layers: { hardmask_grc: [...new Set(hardmask.map((r) => r.root_id))] },
      external: ext.map((e) => ({ root_id: e.root_id, collection: e.collection, group: e.group, name: e.name })),
      placements: placements.map((p) => ({ root_id: p.root_id, parent_type: p.parent_type })),
    });
    const roleCounts = new Map<string, Map<string, number>>();
    for (const m of members) {
      const c = roleCounts.get(m.assembly_accession) ?? new Map<string, number>();
      c.set(m.role, (c.get(m.role) ?? 0) + 1);
      roleCounts.set(m.assembly_accession, c);
    }
    const collections = new Map<string, string[]>();
    for (const e of ext) {
      const g = collections.get(e.collection) ?? [];
      if (!g.includes(e.group)) g.push(e.group);
      collections.set(e.collection, g);
    }
    const places = placesOf(members, ext);
    return {
      compiler, rootLength, collections, roleCounts, places, layers: ["hardmask_grc"],
      derived: new Map(derivations.map((d) => [key(d.root_id, [...d.operations]), { sha512t24u: d.sha512t24u, md5: md5.get(d.sha512t24u)! }])),
      assemblies: new Map(members.map((m) => [m.assembly_accession, m.assembly_name])),
    };
  }));
}

/** A designed sequence: a manifest row, with digests if the catalog knows its derivation. */
export interface DesignRow extends Omit<ManifestRow, "md5" | "sha512t24u"> {
  md5: string | null;
  sha512t24u: string | null;
}

export interface Design {
  rows: DesignRow[];
  /** Rows whose (root, operations) the catalog has never built: digests unknown without their bases. */
  novel: DesignRow[];
  /** With every digest known: the flavor ID and seqcol digest (the seqcol digest's order is by name). */
  id: string | null;
  seqcolDigest: string | null;
  /** The cataloged flavor it is, if any. */
  equals: string | null;
}

/** Compile a recipe and say what it makes. Throws the compiler's error. */
export function design(recipe: Recipe, t: DesignTables, flavors: Flavor[]): Design {
  const compiled = rb.compileRecipe(recipe, t.compiler);
  const rows: DesignRow[] = compiled.map((r) => {
    const d = t.derived.get(key(r.root_id, r.operations));
    return { flavor: "", name: r.name, root_id: r.root_id, operations: r.operations, length: t.rootLength.get(r.root_id) ?? 0,
             md5: d?.md5 ?? null, sha512t24u: d?.sha512t24u ?? null };
  });
  const novel = rows.filter((r) => !r.sha512t24u);
  if (novel.length) return { rows, novel, id: null, seqcolDigest: null, equals: null };
  const names = rows.map((r) => r.name), sqs = rows.map((r) => r.sha512t24u!);
  const id = rb.namedSetDigest(names, sqs);
  return { rows, novel, id, seqcolDigest: rb.seqcolDigests(names, rows.map((r) => r.length), sqs).digest,
           equals: flavors.find((f) => f.id === id)?.flavor ?? null };
}

/** Rows as manifest rows, for the comparison and the exports (only when every digest is known). */
export const asManifest = (rows: DesignRow[]): ManifestRow[] =>
  rows.map((r) => ({ ...r, md5: r.md5!, sha512t24u: r.sha512t24u! }));

/** GRC's Sequence-Names were the `sequence` namespace before they were `grc`; the compiler takes both. */
export function grcNames(rename: Recipe["rename"]): Recipe["rename"] {
  const g = (ns: string) => (ns === "sequence" ? "grc" : ns);
  const out = { ...rename, namespace: g(rename.namespace) };
  if (rename.by_role) out.by_role = Object.fromEntries(Object.entries(rename.by_role).map(([k, v]) => [k, g(v)]));
  return out;
}

/** The recipe without metadata (flavor, published, ...): only what the compiler reads. */
export function plainRecipe(r: Recipe & Record<string, unknown>): Recipe {
  const out: Recipe = { select: r.select, rename: grcNames(r.rename) };
  if (r.mask?.length) out.mask = r.mask;
  if (r.alphabet) out.alphabet = r.alphabet;
  return out;
}

/** The recipe as a URL-safe string (for a shareable link), and back. */
export const encodeRecipe = (r: Recipe) =>
  btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(r)))).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
export function decodeRecipe(s: string): Recipe {
  const b = atob(s.replaceAll("-", "+").replaceAll("_", "/"));
  const r: Recipe = JSON.parse(new TextDecoder().decode(Uint8Array.from(b, (c) => c.charCodeAt(0))));
  return { ...r, rename: grcNames(r.rename) };
}

