// Files made in the browser from a flavor's manifest, in a chosen order.
import type { ManifestRow } from "./flavors.ts";

export function chromSizes(rows: ManifestRow[]): string {
  return rows.map((r) => `${r.name}\t${r.length}\n`).join("");
}

/** A SAM-style sequence dictionary, as Picard's CreateSequenceDictionary writes (with M5). */
export function sequenceDictionary(rows: ManifestRow[]): string {
  return "@HD\tVN:1.6\n" + rows.map((r) => `@SQ\tSN:${r.name}\tLN:${r.length}\tM5:${r.md5}\n`).join("");
}

/** Where a root goes in karyotypic order: an assembly member's role and molecule, or an external root's rank. */
export type Place = { grch38: boolean; role: string; molecule: string } | { collection: string; rank: number };

/** The two orders offered for exports. Neither is an identity: digests don't depend on order. */
export type Order = "name" | "karyotypic";
export const ORDERS: [Order, string][] = [["name", "by name"], ["karyotypic", "karyotypic, by role"]];

const ROLES = ["assembled-molecule", "unlocalized-scaffold", "unplaced-scaffold", "alt-scaffold", "novel-patch", "fix-patch"];
const MOLECULES = [...Array.from({ length: 22 }, (_, i) => String(i + 1)), "X", "Y", "MT"];
const byteOrder = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** Karyotypic, by role: the GRCh38 assembly's sequences role by role (chromosomes,
 * unlocalized, unplaced, alts, novel patches, fix patches), then roots in no
 * assembly (EBV), then other assemblies' (the hs38d1 decoys), then external
 * collections (HLA) in their rank order. Within a role: by chromosome
 * (1-22, X, Y, MT, then none), then accession. Pure: the rows aren't changed. */
export function karyotypic<R extends { root_id: string; name: string }>(rows: R[], places: Map<string, Place>): R[] {
  const key = (r: R): [number, number, number, number, string] => {
    const p = places.get(r.root_id);
    if (!p) return [1, 0, 0, 0, r.root_id];
    if ("rank" in p) return [3, 0, 0, p.rank, p.collection];
    const role = ROLES.indexOf(p.role), mol = MOLECULES.indexOf(p.molecule);
    return [p.grch38 ? 0 : 2, role < 0 ? ROLES.length : role, mol < 0 ? MOLECULES.length : mol, 0, r.root_id];
  };
  const keyed = rows.map((r) => ({ r, k: key(r) }));
  keyed.sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.k[2] - b.k[2] || a.k[3] - b.k[3]
    || byteOrder(a.k[4], b.k[4]) || byteOrder(a.r.name, b.r.name));
  return keyed.map((x) => x.r);
}

/** The rows in one of the two orders. */
export function ordered<R extends { root_id: string; name: string }>(rows: R[], order: Order, places: Map<string, Place>): R[] {
  return order === "karyotypic" ? karyotypic(rows, places) : [...rows].sort((a, b) => byteOrder(a.name, b.name));
}

/** The rows in a given order of names (a published file's), or as given without one. */
export function inOrder(rows: ManifestRow[], names?: string[]): ManifestRow[] {
  if (!names) return rows;
  const by = new Map(rows.map((r) => [r.name, r]));
  return names.map((n) => {
    const r = by.get(n);
    if (!r) throw new Error(`${n} is not in the flavor`);
    return r;
  });
}
