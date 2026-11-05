// Files made in the browser from a flavor's manifest, in a chosen order.
import type { ManifestRow } from "./flavors.ts";

export function chromSizes(rows: ManifestRow[]): string {
  return rows.map((r) => `${r.name}\t${r.length}\n`).join("");
}

/** A SAM-style sequence dictionary, as Picard's CreateSequenceDictionary writes (with M5). */
export function sequenceDictionary(rows: ManifestRow[]): string {
  return "@HD\tVN:1.6\n" + rows.map((r) => `@SQ\tSN:${r.name}\tLN:${r.length}\tM5:${r.md5}\n`).join("");
}

/** The rows in a given order of names (a target's), or canonical order without one. */
export function inOrder(rows: ManifestRow[], names?: string[]): ManifestRow[] {
  if (!names) return rows;
  const by = new Map(rows.map((r) => [r.name, r]));
  return names.map((n) => {
    const r = by.get(n);
    if (!r) throw new Error(`${n} is not in the flavor`);
    return r;
  });
}
