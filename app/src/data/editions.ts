// What the pages show: editions, their manifests and targets, and the bases of
// an edition's sequence, built from its root with the core's operations.
import * as rb from "@abdenlab/refbook";
import type { Catalog } from "./catalog.ts";
import type { Blocks } from "./blocks.ts";

export interface Edition {
  edition: string; book: string; id: string; seqcol_digest: string; n_sequences: number; total_length: number;
  assembly: string; patch_release: number | null; contents: { kind: string; count: number }[];
  excluded: string[]; operations: string[]; naming: string; recipe: string; n_targets: number;
}

export interface ManifestRow {
  edition: string; name: string; root_id: string; operations: string[];
  length: number; md5: string; sha512t24u: string;
}

export interface Target {
  target: string; edition: string; publisher: string; alias: string; published: string;
  checked_against: string; evidence: string; checked_sha256: string; checked_bytes: number;
  checked_last_modified: string; n_sequences: number; seqcol_digest: string;
}

export const IUPAC_TO_N = "iupac_to_n";
export const PAD = "pad";
export const ORIENT = "orient";

export const OPERATION_LABELS: Record<string, string> = {
  hardmask_grc: "GRC hard-mask", par_y: "chrY PARs → N", [IUPAC_TO_N]: "IUPAC → N",
  [PAD]: "N-padding into its parent's coordinates", [ORIENT]: "turned to its parent's strand",
};

/** The operations that mask a layer's spans (the rest: IUPAC → N, padding and orienting). */
export const maskLayers = (operations: string[]) =>
  operations.filter((op) => op !== IUPAC_TO_N && op !== PAD && op !== ORIENT);

export const editions = (cat: Catalog) => cat.table<Edition>("editions.parquet");
export const targets = (cat: Catalog) => cat.table<Target>("targets.parquet");

export async function manifest(cat: Catalog, edition: string): Promise<ManifestRow[]> {
  return (await cat.table<ManifestRow>("manifests.parquet")).filter((r) => r.edition === edition);
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

type PaddingRow = {
  book?: string; root_id: string; parent_start: number; parent_end: number; orientation: string; parent_length: number;
};

/** How a row lays its root out by its placement in its edition's book (layer_padding: a root can be placed in two
 * books, on other parents): padded (pad), or only turned to its parent's strand (orient: no Ns); null if neither. */
export async function padding(cat: Catalog, row: ManifestRow): Promise<rb.Padding | null> {
  const orient = row.operations.includes(ORIENT);
  if (!row.operations.includes(PAD) && !orient) return null;
  const book = (await editions(cat)).find((e) => e.edition === row.edition)?.book;
  const p = (await cat.table<PaddingRow>("layer_padding.parquet"))
    .find((r) => r.root_id === row.root_id && (r.book === undefined || r.book === book));
  if (!p) throw new Error(`${row.root_id}: no placement in layer_padding for ${book}`);
  const reverse = p.orientation === "-";
  if (orient) return { before: 0, after: 0, root_length: row.length, reverse };
  const before = p.parent_start, after = p.parent_length - p.parent_end;
  return { before, after, root_length: row.length - before - after, reverse };
}

/** A span of the root in the sequence's coordinates: where padding puts it. */
export function onSequence(p: rb.Padding | null, [s, e]: rb.Span): rb.Span {
  if (!p) return [s, e];
  return p.reverse ? [p.before + p.root_length - e, p.before + p.root_length - s] : [p.before + s, p.before + e];
}

/** The root bases that bases [start, end) of a row are made from. */
export async function rootWindow(cat: Catalog, row: ManifestRow, start: number, end: number): Promise<rb.Span> {
  const p = await padding(cat, row);
  return p ? rb.padRootRange(start, end, p) : [start, end];
}

export interface Region {
  /** The root's bases, as stored. */
  root: Uint8Array;
  /** The edition's bases: the root's with the row's operations applied. */
  bases: Uint8Array;
}

/** An edition sequence's bases at [start, end): the root's, then its operations, padding last. With padding,
 * `root` is the root's bases padded the same way, so the two line up. */
export async function region(cat: Catalog, blocks: Blocks, row: ManifestRow, start: number, end: number): Promise<Region> {
  const p = await padding(cat, row);
  const [a, z] = p ? rb.padRootRange(start, end, p) : [start, end];
  const root = await blocks.read(row.root_id, a, z);
  const masks = await Promise.all(maskLayers(row.operations).map((op) => spans(cat, op, row.root_id)));
  const bases = rb.applyOperations(root, a, masks.flat(), row.operations.includes(IUPAC_TO_N));
  if (!p) return { root, bases };
  return { root: rb.pad(root, start, end, p), bases: rb.pad(bases, start, end, p) };
}

/** Build a whole sequence and check it against its MD5 and SQ. digest. */
export async function verify(cat: Catalog, blocks: Blocks, row: ManifestRow): Promise<boolean> {
  const { bases } = await region(cat, blocks, row, 0, row.length);
  const [md5, sq] = rb.digests(bases);
  return bases.length === row.length && md5 === row.md5 && sq === row.sha512t24u;
}
