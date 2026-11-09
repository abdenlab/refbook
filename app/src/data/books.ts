// Books: one per assembly (grch37, grch38), each with its releases and its editions. Every edition belongs to one
// book; its label is unique across books (the pipeline refuses a label used twice), so a label alone finds its book.
import type { Catalog } from "./catalog.ts";
import { editions, manifest, targets, type Edition, type ManifestRow, type Target } from "./editions.ts";

export interface Book {
  book: string;
  /** The assembly's name, as its editions record it (GRCh37). */
  assembly: string;
  /** Its releases, p0 first (GRCh37, GRCh37.p1, ...). */
  releases: string[];
  /** Distinct sequences across its releases. */
  nSequences: number;
  editions: Edition[];
  targets: Target[];
}

type Member = { book: string; assembly_name: string; genbank_accession: string };

/** A release of `assembly`, and its patch number: GRCh37 is 0, GRCh37.p13 is 13; anything else (hs38d1) is null. */
export function releaseNumber(name: string, assembly: string): number | null {
  if (name === assembly) return 0;
  const m = name.startsWith(`${assembly}.p`) ? /^\d+$/.exec(name.slice(assembly.length + 2)) : null;
  return m ? Number(m[0]) : null;
}

let loaded: Promise<Book[]> | null = null;

/** Every book, in name order. */
export function books(cat: Catalog): Promise<Book[]> {
  return (loaded ??= (async () => {
    const [fs, ts, members] = await Promise.all([editions(cat), targets(cat), cat.table<Member>("assembly_members.parquet")]);
    const out: Book[] = [];
    for (const [book, eds] of Map.groupBy(fs, (f) => f.book)) {
      const assembly = eds[0].assembly;
      const mine = members.filter((m) => m.book === book && releaseNumber(m.assembly_name, assembly) !== null);
      const releases = [...new Set(mine.map((m) => m.assembly_name))]
        .sort((a, b) => releaseNumber(a, assembly)! - releaseNumber(b, assembly)!);
      const labels = new Set(eds.map((e) => e.edition));
      out.push({ book, assembly, releases, nSequences: new Set(mine.map((m) => m.genbank_accession)).size,
                 editions: eds, targets: ts.filter((t) => labels.has(t.edition)) });
    }
    out.forEach((b) => bookOf.set(b.book, b));
    for (const b of out) for (const e of b.editions) editionBook.set(e.edition, b.book);
    return out.sort((a, b) => a.book.localeCompare(b.book));
  })());
}

/** Filled by books(): a book by name, and an edition's book by label (for links made without waiting). */
export const bookOf = new Map<string, Book>();
export const editionBook = new Map<string, string>();

const path = (...parts: string[]) => "#/" + parts.map(encodeURIComponent).join("/");

/** A book's segment in addresses: its assembly's name (GRCh38), which reads better than the book's key. */
const segment = (book: string) => bookOf.get(book)?.assembly ?? book;

/** The book a segment of an address names: by its assembly's name or its key, in any case (GRCh38, grch38). */
export function bookFor(seg: string | undefined, bs: Book[]): Book | undefined {
  const s = seg?.toLowerCase();
  return s ? bs.find((b) => b.assembly.toLowerCase() === s || b.book === s) : undefined;
}

/** A book's page in the catalog: #/catalog/<assembly>. */
export const bookHref = (book: string) => path("catalog", segment(book));

/** A book's Editor: #/editor/<assembly>, with a query (the recipe to open, the tab). */
export const editorHref = (book: string, query?: URLSearchParams) =>
  path("editor", segment(book)) + (query?.size ? `?${query}` : "");

/** The address of an edition, or of one of its sequences: #/catalog/<assembly>/edition/<label>[/seq/<name>]. Its
 * book is known once books() has loaded, which the app does before it shows any page. */
export function editionHref(label: string, seq?: string): string {
  const book = editionBook.get(label);
  if (!book) throw new Error(`${label}: no such edition, or the books aren't loaded`);
  return path("catalog", segment(book), "edition", label, ...(seq !== undefined ? ["seq", seq] : []));
}

// Families: who makes an edition, from its publishers. iGenomes repackages others' files, so an edition belongs to
// iGenomes only when nobody else publishes it.
export const FAMILIES: { key: string; name: string; about: string }[] = [
  { key: "grc", name: "GRC",
    about: "The Genome Reference Consortium's analysis sets, made for read alignment: duplicated regions masked so reads map once." },
  { key: "ucsc", name: "UCSC",
    about: "The UCSC Genome Browser's builds: chr-style names, IUPAC codes written as N." },
  { key: "ensembl", name: "Ensembl and GENCODE",
    about: "Ensembl's genome FASTA files, and GENCODE's, which carry Ensembl's gene annotation." },
  { key: "projects", name: "1000 Genomes and Broad",
    about: "References made for large sequencing projects and GATK, some with decoys, EBV or HLA alleles added so reads from them don't land elsewhere." },
  { key: "igenomes", name: "Illumina iGenomes", about: "Illumina's iGenomes: others' editions, repackaged." },
];

function familyOfPublisher(p: string): string {
  if (p === "GRC") return "grc";
  if (p === "UCSC") return "ucsc";
  if (p.startsWith("Ensembl") || p.startsWith("GENCODE")) return "ensembl";
  if (p === "1000 Genomes" || p.startsWith("Broad")) return "projects";
  return "igenomes";
}

/** An edition's family, from its published files. */
export function familyOf(edition: string, ts: Target[]): string {
  const fams = ts.filter((t) => t.edition === edition).map((t) => familyOfPublisher(t.publisher));
  return FAMILIES.find((f) => f.key !== "igenomes" && fams.includes(f.key))?.key ?? "igenomes";
}

// Relations between editions of one book, from their manifests.

export type Relation =
  /** The other edition is this one plus some sequences (or this one is the other plus some). */
  | { kind: "adds"; other: string; added: string[] }
  | { kind: "within"; other: string; added: string[] }
  /** The same sequences (by digest), named otherwise. */
  | { kind: "renamed"; other: string; renamed: number }
  /** The same names on the same roots, other bases: the operations differ. */
  | { kind: "operations"; other: string; differ: number };

const pairKey = (r: ManifestRow) => `${r.name}\t${r.sha512t24u}`;

/** How `label` relates to each other edition of its book, where the relation is simple enough to name. */
export async function relations(cat: Catalog, label: string): Promise<Relation[]> {
  const book = bookOf.get(editionBook.get(label) ?? "");
  if (!book) return [];
  const mine = await manifest(cat, label);
  const pairs = new Set(mine.map(pairKey));
  const sqs = new Set(mine.map((r) => r.sha512t24u));
  const named = new Map(mine.map((r) => [r.name, r]));
  const out: Relation[] = [];
  for (const e of book.editions) {
    if (e.edition === label) continue;
    const theirs = await manifest(cat, e.edition);
    const theirPairs = new Set(theirs.map(pairKey));
    if (theirs.length > mine.length && mine.every((r) => theirPairs.has(pairKey(r)))) {
      out.push({ kind: "within", other: e.edition, added: theirs.filter((r) => !pairs.has(pairKey(r))).map((r) => r.name) });
    } else if (mine.length > theirs.length && theirs.every((r) => pairs.has(pairKey(r)))) {
      out.push({ kind: "adds", other: e.edition, added: mine.filter((r) => !theirPairs.has(pairKey(r))).map((r) => r.name) });
    } else if (theirs.length === mine.length && theirs.every((r) => sqs.has(r.sha512t24u))
               && new Set(theirs.map((r) => r.sha512t24u)).size === sqs.size) {
      out.push({ kind: "renamed", other: e.edition, renamed: theirs.filter((r) => !pairs.has(pairKey(r))).length });
    } else if (theirs.length === mine.length && theirs.every((r) => named.get(r.name)?.root_id === r.root_id)) {
      out.push({ kind: "operations", other: e.edition, differ: theirs.filter((r) => named.get(r.name)!.sha512t24u !== r.sha512t24u).length });
    }
  }
  // Nearest first: the fewest sequences apart.
  const distance = (r: Relation) => ("added" in r ? r.added.length : "renamed" in r ? r.renamed : r.differ);
  return out.sort((a, b) => distance(a) - distance(b) || a.other.localeCompare(b.other));
}
