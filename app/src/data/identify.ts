// Identify a pasted sequence list, entry by entry, with the core's identify;
// and compare two collections with the core's seqcol comparison, explained
// per sequence.
import * as rb from "@abdenlab/refbook";
import type { Catalog } from "./catalog.ts";
import type { ManifestRow } from "./editions.ts";
import { measure } from "./meter.ts";

export interface Header { format: string; entries: rb.Entry[] }

const SAM_SQ = /^@SQ\t/;
const CONTIG = /^##contig=<(.*)>\s*$/;

/**
 * A sequence list from pasted text: a level-2 seqcol collection (JSON), SAM
 * header (@SQ SN/LN/M5, as in a .dict or `samtools view -H`), VCF ##contig
 * lines, FASTA (digested here), or
 * whitespace-separated name and length (.fai, chrom.sizes). Lines it doesn't
 * know are skipped.
 */
export function parseHeader(text: string): Header {
  if (text.trimStart().startsWith("{")) return { format: "seqcol (level 2)", entries: seqcolEntries(JSON.parse(text)) };
  const lines = text.split(/\r?\n/);
  if (lines.some((l) => l.startsWith(">"))) return { format: "FASTA", entries: fasta(lines) };
  if (lines.some((l) => SAM_SQ.test(l))) {
    return {
      format: "SAM header",
      entries: lines.filter((l) => SAM_SQ.test(l)).map((l) => {
        const tags = Object.fromEntries(l.split("\t").slice(1).map((t) => [t.slice(0, 2), t.slice(3)]));
        return { name: tags.SN, length: tags.LN ? Number(tags.LN) : null, md5: tags.M5 || null };
      }),
    };
  }
  if (lines.some((l) => CONTIG.test(l))) {
    return {
      format: "VCF",
      entries: lines.map((l) => CONTIG.exec(l)?.[1]).filter((x): x is string => !!x).map((inner) => {
        const f = Object.fromEntries(inner.split(",").map((kv) => kv.split("=", 2) as [string, string]));
        return { name: f.ID, length: f.length ? Number(f.length) : null, md5: f.md5?.replaceAll('"', "") || null };
      }),
    };
  }
  const entries = lines.map((l) => l.trim().split(/\s+/)).filter((c) => c.length >= 2 && /^\d+$/.test(c[1]) && !c[0].startsWith("#"))
    .map(([name, length]) => ({ name, length: Number(length) }));
  return { format: entries.length ? "names and lengths" : "nothing recognized", entries };
}

/** The entries of a level-2 seqcol collection; level 1 (array digests only) names no sequences. */
function seqcolEntries(doc: Record<string, unknown>): rb.Entry[] {
  const { names, lengths, sequences } = doc;
  if ([names, lengths, sequences].some((a) => typeof a === "string")) {
    throw new Error("a level-1 seqcol collection has array digests only; identify needs level 2");
  }
  if (!Array.isArray(names) || !Array.isArray(sequences)) throw new Error("a seqcol collection needs names and sequences");
  const ls = Array.isArray(lengths) ? lengths : [];
  if (names.length !== sequences.length || (ls.length && ls.length !== names.length)) {
    throw new Error("names, lengths and sequences differ in length");
  }
  return names.map((name, i) => ({ name: String(name), length: ls.length ? Number(ls[i]) : null, sq: String(sequences[i]) }));
}

function fasta(lines: string[]): rb.Entry[] {
  const out: rb.Entry[] = [];
  let name: string | null = null, parts: string[] = [];
  const done = () => {
    if (name === null) return;
    const bases = rb.canonicalBases(new TextEncoder().encode(parts.join("")));
    const [md5, sq] = rb.digests(bases);
    out.push({ name, length: bases.length, md5, sq });
  };
  for (const l of lines) {
    if (l.startsWith(">")) { done(); name = l.slice(1).trim().split(/\s+/)[0]; parts = []; }
    else parts.push(l);
  }
  done();
  return out;
}

let tables: Promise<rb.IdentifyTables> | null = null;

/** The identify tables: the sequence store, the aliases and the manifests (about 0.5 MB, once). */
export function identifyTables(cat: Catalog): Promise<rb.IdentifyTables> {
  return (tables ??= measure("identify tables", async () => {
    const [sequences, aliases, manifests] = await Promise.all([
      cat.table<{ sha512t24u: string; md5: string; length: number; root_id: string; operations: string[] }>("sequences.parquet"),
      cat.table<{ root_id: string; alias: string }>("aliases.parquet"),
      cat.table<{ edition: string; name: string; sha512t24u: string }>("manifests.parquet"),
    ]);
    // Every root is in the store as itself (no operations): its length is the root's.
    const roots = sequences.filter((s) => s.operations.length === 0).map((s) => ({ root_id: s.root_id, length: s.length }));
    return rb.identifyTables({
      sequences: sequences.map((s) => ({ ...s, operations: [...s.operations] })),
      roots,
      aliases: aliases.map((a) => ({ root_id: a.root_id, alias: a.alias })),
      manifests: manifests.map((m) => ({ edition: m.edition, name: m.name, sha512t24u: m.sha512t24u })),
    });
  }));
}

// Comparing two collections.

/** A sequence present under one name in both, or in one only. */
export type Pair =
  | { kind: "same"; name: string; a: ManifestRow; b: ManifestRow }
  | { kind: "operations"; name: string; a: ManifestRow; b: ManifestRow }   // same root, other operations
  | { kind: "different"; name: string; a: ManifestRow; b: ManifestRow }    // other roots
  | { kind: "renamed"; a: ManifestRow; b: ManifestRow }                    // same sequence, other names
  | { kind: "a_only"; a: ManifestRow }
  | { kind: "b_only"; b: ManifestRow };

/** Pair two collections' sequences: by name, then the rest by sequence. */
export function pairs(a: ManifestRow[], b: ManifestRow[]): Pair[] {
  const byName = new Map(b.map((r) => [r.name, r]));
  const out: Pair[] = [];
  const restA: ManifestRow[] = [];
  const usedB = new Set<string>();
  for (const x of a) {
    const y = byName.get(x.name);
    if (!y) { restA.push(x); continue; }
    usedB.add(y.name);
    const kind = x.sha512t24u === y.sha512t24u ? "same" : x.root_id === y.root_id ? "operations" : "different";
    out.push({ kind, name: x.name, a: x, b: y });
  }
  const restB = new Map(b.filter((r) => !usedB.has(r.name)).map((r) => [r.sha512t24u, r]));
  for (const x of restA) {
    const y = restB.get(x.sha512t24u);
    if (y) { out.push({ kind: "renamed", a: x, b: y }); restB.delete(x.sha512t24u); }
    else out.push({ kind: "a_only", a: x });
  }
  for (const y of restB.values()) out.push({ kind: "b_only", b: y });
  return out;
}

/** A collection's level 2, in the given order. */
export const level2 = (rows: ManifestRow[]) =>
  rb.seqcolLevel2(rows.map((r) => r.name), rows.map((r) => r.length), rows.map((r) => r.sha512t24u));

// A pasted list against the catalog: identify's answers, compared with a
// edition or published file, and renamed into a namespace or an edition's names.

/** A pasted entry, with what identify made of it: as much as can be compared. */
export interface Mine {
  name: string;
  length: number | null;
  /** The entry came with a digest (MD5 or SQ.), so its bases are pinned, cataloged or not. */
  digested: boolean;
  /** Its SQ. digest: given, or the store's for its MD5. Null without a digest, or for an MD5 the catalog lacks. */
  sq: string | null;
  root_id: string | null;
  /** The roots it may be: its root, or, for a name several roots of its length go by (chrM: rCRS, and CHM13's own
   * mitochondrion), each of them. */
  candidates: string[];
  evidence: rb.Identity["evidence"];
}

export function mine(entries: rb.Entry[], ids: rb.Identity[]): Mine[] {
  return entries.map((e, i) => ({
    name: e.name ?? "",
    length: e.length ?? ids[i].length,
    digested: !!(e.md5 || e.sq),
    sq: ids[i].sequence ?? e.sq ?? null,
    root_id: ids[i].root_id,
    candidates: ids[i].root_id ? [ids[i].root_id!]
      : ((ids[i].notes.find((n) => n.kind === "ambiguous_name") as { roots?: string[] } | undefined)?.roots ?? []),
    evidence: ids[i].evidence,
  }));
}

/** A pasted sequence against a cataloged one: by name, then the rest by sequence (or root and length, without a digest). */
export type Match =
  | { kind: "same"; name: string; a: Mine; b: ManifestRow }
  | { kind: "unsure"; name: string; a: Mine; b: ManifestRow }       // same root and length; no digest to tell the version
  | { kind: "operations"; name: string; a: Mine; b: ManifestRow }   // same root, other bases
  | { kind: "different"; name: string; a: Mine; b: ManifestRow }    // another sequence
  | { kind: "renamed"; a: Mine; b: ManifestRow; by: "digest" | "root_and_length" | "root" }  // root: same root, other bases
  | { kind: "a_only"; a: Mine }
  | { kind: "b_only"; b: ManifestRow };

export function matches(a: Mine[], b: ManifestRow[]): Match[] {
  const byName = new Map(b.map((r) => [r.name, r]));
  const out: Match[] = [];
  const restA: Mine[] = [];
  const used = new Set<string>();
  // Its root, or (an ambiguous name) one of the roots it may be, at its length: only a digest could tell more.
  const fits = (x: Mine, y: ManifestRow) => x.candidates.includes(y.root_id) && (x.length === null || x.length === y.length);
  for (const x of a) {
    const y = byName.get(x.name);
    if (!y || used.has(y.name)) { restA.push(x); continue; }
    used.add(y.name);
    const kind = x.digested
      ? x.sq === y.sha512t24u ? "same" : x.root_id === y.root_id ? "operations" : "different"
      : fits(x, y) ? "unsure" : "different";
    out.push({ kind, name: x.name, a: x, b: y });
  }
  const rest = b.filter((r) => !used.has(r.name));
  const bySq = new Map(rest.map((r) => [r.sha512t24u, r]));
  const byRoot = Map.groupBy(rest, (r) => r.root_id);
  const taken = new Set<ManifestRow>();
  const take = (y: ManifestRow) => {
    taken.add(y);
    bySq.delete(y.sha512t24u);
    const g = byRoot.get(y.root_id)!;
    g.splice(g.indexOf(y), 1);
  };
  for (const x of restA) {
    const exact = x.sq ? bySq.get(x.sq) : undefined;
    const y = exact ?? x.candidates.map((c) => byRoot.get(c)?.find((r) => fits(x, r))).find((r) => r);
    if (y) { out.push({ kind: "renamed", a: x, b: y, by: exact ? "digest" : x.digested ? "root" : "root_and_length" }); take(y); }
    else out.push({ kind: "a_only", a: x });
  }
  for (const y of rest) if (!taken.has(y)) out.push({ kind: "b_only", b: y });
  return out;
}

/**
 * How far a pasted list is from an edition: of yours, those not in it as they
 * are (missing); of its, those not in yours (extra); and of the matches,
 * those only a digest could confirm (unsure). Off is missing and extra.
 */
export function distance(ms: Match[]): { off: number; missing: number; extra: number; unsure: number } {
  let missing = 0, extra = 0, unsure = 0;
  for (const m of ms) {
    if (m.kind === "unsure" || (m.kind === "renamed" && m.by === "root_and_length")) unsure++;
    if (m.kind === "b_only") extra++;
    else if (m.kind !== "same" && m.kind !== "unsure") missing++;
  }
  return { off: missing + extra, missing, extra, unsure };
}

/** A line of an alias file: a pasted name and what it becomes, or why it can't. */
export interface Rename { from: string; to: string | null; how: string; weak: boolean }

const HOW: Record<rb.Identity["evidence"], string> = {
  digest: "by digest", name_and_length: "by name and length", name: "by name only", nothing: "",
};

/** Each pasted name in a namespace, by its root (from the aliases table). */
export function renameTo(ms: Mine[], namespace: string, aliases: { root_id: string; namespace: string; alias: string }[]): Rename[] {
  const of = new Map(aliases.filter((a) => a.namespace === namespace).map((a) => [a.root_id, a.alias]));
  return ms.map((x) => {
    if (!x.root_id) return { from: x.name, to: null, how: "not identified", weak: false };
    const to = of.get(x.root_id) ?? null;
    return { from: x.name, to, how: to ? HOW[x.evidence] : `${x.root_id} has no ${namespace} name`, weak: x.evidence === "name" };
  });
}

/** Each pasted name as an edition (or file) names the same sequence. */
export function renameAs(ms: Match[]): Rename[] {
  const out: Rename[] = [];
  for (const m of ms) {
    if (m.kind === "b_only") continue;
    const from = m.a.name, weak = m.a.evidence === "name";
    if (m.kind === "same" || m.kind === "unsure") out.push({ from, to: m.b.name, how: m.kind === "same" ? "by digest" : "same root and length", weak });
    else if (m.kind === "renamed") out.push({ from, to: m.b.name, how: { digest: "by digest", root_and_length: "same root and length", root: "same root, other bases" }[m.by], weak });
    else if (m.kind === "operations") out.push({ from, to: m.b.name, how: "same root, other bases", weak });
    else if (m.kind === "different") out.push({ from, to: null, how: "the name is used for another sequence", weak: false });
    else out.push({ from, to: null, how: "not in it", weak: false });
  }
  return out;
}

/** An alias file: from and to, tab-separated, one rename a line (as bcftools --rename-chrs reads). */
export const aliasFile = (rs: Rename[]) => rs.filter((r) => r.to !== null).map((r) => `${r.from}\t${r.to}\n`).join("");
