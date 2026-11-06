/**
 * refbook's core (crates/refbook-core), compiled to WebAssembly: refget and
 * seqcol digests, nucleotide operations, the recipe compiler.
 *
 * Call `init()` once before anything else (in the browser it fetches the
 * .wasm next to this module; pass a URL, Response or bytes to load it from
 * elsewhere), or `initSync({ module: bytes })` where the bytes are at hand,
 * as in Node.
 *
 * Function names are camelCase; data keys keep the catalog's and the seqcol
 * spec's names (root_id, sorted_name_length_pairs, ...), as in the Python
 * library.
 */

import init, * as core from "../pkg/refbook_wasm.js";

export { init, core };
export const initSync = core.initSync;

/** Half-open interval [start, end), 0-based. */
export type Span = [number, number];

// refget

/** The bases refget digests: whitespace removed, uppercased, A-Z only.
 * Throws on any other character, with its position. */
export const canonicalBases = (seq: Uint8Array): Uint8Array => core.canonicalBases(seq);

/** The bytes with whitespace removed. */
export const removeWhitespace = (seq: Uint8Array): Uint8Array => core.removeWhitespace(seq);

/** [MD5, SQ. digest] of canonical bases. */
export const digests = (bases: Uint8Array): [string, string] =>
  core.digests(bases) as [string, string];

/** The GA4GH digest: SHA-512 truncated to 24 bytes, base64url. */
export const sha512t24u = (data: Uint8Array): string => core.sha512t24u(data);

export interface Scan {
  bases: Uint8Array;
  md5: string;
  sha512t24u: string;
  /** Runs of lowercase in the input. */
  lower: Span[];
  /** Runs of N in the canonical bases. */
  n_runs: Span[];
  /** Positions and codes of IUPAC codes (anything but A, C, G, T, N). */
  iupac: [number, string][];
}

/** One sequence (whitespace removed): its canonical bases, digests, lowercase
 * runs, N-runs and IUPAC positions. */
export const scan = (seq: Uint8Array): Scan => core.scan(seq);

// seqcol

/** A value seqcol digests: strings, integers, arrays and objects. */
export type SeqcolJson = string | number | SeqcolJson[] | { [key: string]: SeqcolJson };

/** RFC-8785 canonical JSON. */
export const canonicalJson = (value: SeqcolJson): string => core.canonicalJson(value);

/** The level-1 digest of an attribute's level-2 value. */
export const level1 = (value: SeqcolJson): string => core.level1(value);

export interface SeqcolDigests {
  /** The top-level digest. */
  digest: string;
  level1: { names: string; lengths: string; sequences: string };
}

/** A collection's digests; sequences are SQ. digests. */
export const seqcolDigests = (names: string[], lengths: number[], sequences: string[]): SeqcolDigests =>
  core.seqcolDigests(names, lengths, sequences);

export interface Ancillary {
  name_length_pairs: { name: string; length: number }[];
  sorted_name_length_pairs: string[];
  sorted_sequences: string[];
  named_sequences: string[];
  sorted_named_sequences: string[];
}

/** Level-2 values of the ancillary attributes refbook computes. */
export const seqcolAncillary = (names: string[], lengths: number[], sequences: string[]): Ancillary =>
  core.seqcolAncillary(names, lengths, sequences);

/** The order-independent identifier of a named sequence set (an edition's id). */
export const namedSetDigest = (names: string[], sequences: string[]): string =>
  core.namedSetDigest(names, sequences);

/** A collection as seqcol attributes: arrays at level 2, digests at level 1. */
export type Collection = Record<string, SeqcolJson>;

/** The seqcol schema refbook serves: the spec's extended schema plus
 * named_sequences and sorted_named_sequences. */
export const seqcolSchema = (): Record<string, unknown> => JSON.parse(core.seqcolSchema());

/** The level-2 representation: every attribute but the transient ones. */
export const seqcolLevel2 = (names: string[], lengths: number[], sequences: string[]): Collection =>
  core.seqcolLevel2(names, lengths, sequences);

/** The level-1 representation: the digest of every attribute, transient ones included. */
export const seqcolLevel1 = (names: string[], lengths: number[], sequences: string[]): Record<string, string> =>
  core.seqcolLevel1(names, lengths, sequences);

/** The top-level digest of a collection (level 2 or 1), or undefined without
 * the inherent attributes. */
export const topLevelDigest = (collection: Collection): string | undefined => core.topLevelDigest(collection);

/** seqcol's /comparison (spec 3.3). */
export interface Comparison {
  digests: { a: string | null; b: string | null };
  attributes: { a_only: string[]; b_only: string[]; a_and_b: string[] };
  array_elements: {
    a_count: Record<string, number>;
    b_count: Record<string, number>;
    a_and_b_count: Record<string, number>;
    a_and_b_same_order: Record<string, boolean | null>;
  };
}

/** Compare two collections given as their level-2 attributes, as seqcol's
 * /comparison does. Shared elements count with multiplicity; the order of
 * fewer than 2 shared elements, or of unbalanced duplicates, is null. */
export const seqcolCompare = (a: Collection, b: Collection): Comparison => core.seqcolCompare(a, b);

// nucleotide operations

/** A root's bases (root positions start..start + length) with the spans set
 * to N and, if toN, every base other than A, C, G, T and N set to N. */
export const applyOperations = (bases: Uint8Array, start: number, spans: Span[], toN: boolean): Uint8Array =>
  core.applyOperations(bases, start, spans, toN);

// the recipe compiler

export interface Tables {
  /** assembly_members rows, in report order. */
  members: {
    assembly_accession: string;
    genbank_accession: string;
    role: string;
    ucsc_name: string | null;
    sequence_name: string | null;
    refseq_accession: string | null;
  }[];
  /** Every root id, hosted or external. */
  roots: string[];
  /** The roots with IUPAC codes. */
  iupac: string[];
  /** Mask layer -> the roots it has spans on. */
  layers: Record<string, string[]>;
  /** roots_external rows, in rank order. */
  external?: { root_id: string; collection: string; group: string; name: string | null }[];
  /** layer_placements rows. */
  placements?: { root_id: string; parent_type: string }[];
}

export interface ManifestRow {
  name: string;
  root_id: string;
  operations: string[];
}

export const RecipeTables = core.RecipeTables;
export type RecipeTables = core.RecipeTables;

/** Build the tables once; compile any number of recipes against them. */
export const recipeTables = (tables: Tables): RecipeTables => new core.RecipeTables(tables);

/** A recipe's manifest rows, in canonical order (by name). Throws if it
 * doesn't compile. */
export const compileRecipe = (recipe: object | string, tables: RecipeTables): ManifestRow[] =>
  core.compileRecipe(recipe, tables);

// identify

/** The catalog tables identify reads, in the catalog's column names. */
export interface IdentifyInput {
  /** sequences.parquet rows. */
  sequences: { sha512t24u: string; md5: string; length: number; root_id: string; operations: string[] }[];
  /** Every root, hosted and external. */
  roots: { root_id: string; length: number }[];
  /** aliases.parquet rows. */
  aliases: { root_id: string; alias: string }[];
  /** manifests.parquet rows. */
  manifests: { edition: string; name: string; sha512t24u: string }[];
}

export const IdentifyTables = core.IdentifyTables;
export type IdentifyTables = core.IdentifyTables;

/** Build the identify tables once; identify any number of entries against them. */
export const identifyTables = (tables: IdentifyInput): IdentifyTables => new core.IdentifyTables(tables);

/** An entry of a sequence list: any of name, length, MD5 and SQ. digest. */
export interface Entry {
  name?: string | null;
  length?: number | null;
  md5?: string | null;
  sq?: string | null;
}

export type Note =
  | { kind: "unknown_digest"; digest: string }
  | { kind: "digests_disagree" }
  | { kind: "length_differs"; expected: number }
  | { kind: "name_of_other_roots"; roots: string[] }
  | { kind: "ambiguous_name"; roots: string[] }
  | { kind: "no_root_of_this_length"; roots: string[] };

/** What one entry is, on its own evidence. */
export interface Identity {
  evidence: "digest" | "name_and_length" | "name" | "nothing";
  sequence: string | null;
  md5: string | null;
  length: number | null;
  root_id: string | null;
  /** The operations from the root, when a digest pins the sequence. */
  operations: string[] | null;
  /** Without a known digest: the stored sequences of the root it could be. */
  cognates: string[];
  editions: { edition: string; name: string; sequence: string }[];
  notes: Note[];
}

/** What each entry is: one identity per entry, in order. */
export const identifySequences = (entries: Entry[], tables: IdentifyTables): Identity[] =>
  core.identifySequences(entries, tables);

