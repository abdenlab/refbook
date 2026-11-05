// Identify a pasted sequence list, entry by entry, with the core's identify;
// and compare two collections with the core's seqcol comparison, explained
// per sequence.
import * as rb from "@abdenlab/refbook";
import type { Catalog } from "./catalog.ts";
import type { ManifestRow } from "./flavors.ts";
import { measure } from "./meter.ts";

export interface Header { format: string; entries: rb.Entry[] }

const SAM_SQ = /^@SQ\t/;
const CONTIG = /^##contig=<(.*)>\s*$/;

/**
 * A sequence list from pasted text: SAM header (@SQ SN/LN/M5, as in a .dict or
 * `samtools view -H`), VCF ##contig lines, FASTA (digested here), or
 * whitespace-separated name and length (.fai, chrom.sizes). Lines it doesn't
 * know are skipped.
 */
export function parseHeader(text: string): Header {
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
      cat.table<{ flavor: string; name: string; sha512t24u: string }>("manifests.parquet"),
    ]);
    // Every root is in the store as itself (no operations): its length is the root's.
    const roots = sequences.filter((s) => s.operations.length === 0).map((s) => ({ root_id: s.root_id, length: s.length }));
    return rb.identifyTables({
      sequences: sequences.map((s) => ({ ...s, operations: [...s.operations] })),
      roots,
      aliases: aliases.map((a) => ({ root_id: a.root_id, alias: a.alias })),
      manifests: manifests.map((m) => ({ flavor: m.flavor, name: m.name, sha512t24u: m.sha512t24u })),
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
