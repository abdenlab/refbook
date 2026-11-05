// What the pages show: flavors, their manifests and targets, and the bases of
// a flavor's sequence, built from its root with the core's operations.
import * as rb from "@abdenlab/refbook";
import type { Catalog } from "./catalog.ts";
import type { Blocks } from "./blocks.ts";

export interface Flavor {
  flavor: string; id: string; seqcol_digest: string; n_sequences: number; total_length: number;
  assembly: string; patch_release: number | null; contents: { kind: string; count: number }[];
  excluded: string[]; operations: string[]; naming: string; recipe: string; n_targets: number;
}

export interface ManifestRow {
  flavor: string; name: string; root_id: string; operations: string[];
  length: number; md5: string; sha512t24u: string;
}

export interface Target {
  target: string; flavor: string; publisher: string; alias: string; published: string;
  checked_against: string; evidence: string; checked_sha256: string; checked_bytes: number;
  checked_last_modified: string; n_sequences: number; seqcol_digest: string;
}

export const IUPAC_TO_N = "iupac_to_n";

export const OPERATION_LABELS: Record<string, string> = {
  hardmask_grc: "GRC hard-mask", [IUPAC_TO_N]: "IUPAC → N",
};

export const flavors = (cat: Catalog) => cat.table<Flavor>("flavors.parquet");
export const targets = (cat: Catalog) => cat.table<Target>("targets.parquet");

export async function manifest(cat: Catalog, flavor: string): Promise<ManifestRow[]> {
  return (await cat.table<ManifestRow>("manifests.parquet")).filter((r) => r.flavor === flavor);
}

/** A target's sequence names in its own order. */
export async function targetOrder(cat: Catalog, target: string): Promise<string[]> {
  const rows = await cat.table<{ target: string; position: number; name: string }>("target_sequences.parquet");
  return rows.filter((r) => r.target === target).sort((a, b) => a.position - b.position).map((r) => r.name);
}

/** The spans a mask layer has on a root. */
export async function spans(cat: Catalog, layer: string, root: string): Promise<rb.Span[]> {
  const rows = await cat.table<{ root_id: string; start: number; end: number }>(`layer_${layer}.parquet`);
  return rows.filter((r) => r.root_id === root).map((r) => [r.start, r.end] as rb.Span);
}

export interface Region {
  /** The root's bases, as stored. */
  root: Uint8Array;
  /** The flavor's bases: the root's with the row's operations applied. */
  bases: Uint8Array;
}

/** A flavor sequence's bases at [start, end): the root's, then its operations. */
export async function region(cat: Catalog, blocks: Blocks, row: ManifestRow, start: number, end: number): Promise<Region> {
  const root = await blocks.read(row.root_id, start, end);
  const masks = await Promise.all(row.operations.filter((op) => op !== IUPAC_TO_N).map((op) => spans(cat, op, row.root_id)));
  const bases = rb.applyOperations(root, start, masks.flat(), row.operations.includes(IUPAC_TO_N));
  return { root, bases };
}

/** Build a whole sequence and check it against its MD5 and SQ. digest. */
export async function verify(cat: Catalog, blocks: Blocks, row: ManifestRow): Promise<boolean> {
  const { bases } = await region(cat, blocks, row, 0, row.length);
  const [md5, sq] = rb.digests(bases);
  return bases.length === row.length && md5 === row.md5 && sq === row.sha512t24u;
}
