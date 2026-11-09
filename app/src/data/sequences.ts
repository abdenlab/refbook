// Sequences across books: find roots and stored sequences by name, accession or digest, and say which books each
// appears in. The one place the app crosses books (a book's own pages never do).
import type { Catalog } from "./catalog.ts";
import type { ManifestRow } from "./editions.ts";

type Alias = { book: string | null; root_id: string; namespace: string; alias: string; source: string };
type Member = { book: string; assembly_name: string; genbank_accession: string; role: string; assigned_molecule: string | null };
export type Stored = { sha512t24u: string; md5: string; length: number; root_id: string; operations: string[];
                       book: string | null; n_derivations: number };
export type Derivation = { sha512t24u: string; root_id: string; operations: string[]; book: string | null; editions: string[] };

/** A root and where it appears: its names (by namespace) and role in each book, and its stored sequences. */
export interface RootHit {
  root_id: string;
  length: number | null;
  /** Names that mean the same in every book (accessions, IMGT names). */
  global: { namespace: string; alias: string }[];
  books: { book: string; role: string | null; assembly: string | null; names: { namespace: string; alias: string }[] }[];
  stored: Stored[];
}

const MAX = 50;

/** Names, each (namespace, alias) once: several sources (reports, chromAlias files, targets) give the same name. */
const distinct = (xs: Alias[]) =>
  [...new Map(xs.map(({ namespace, alias }) => [`${namespace}\t${alias}`, { namespace, alias }])).values()];
const isMd5 = (q: string) => /^[0-9a-f]{32}$/i.test(q);

/** The roots a query finds: by digest (an MD5 or SQ. digest names a stored sequence, hence its root), by exact name
 * or accession, else by names containing the query (at most 50 roots). */
export async function search(cat: Catalog, query: string): Promise<{ hits: RootHit[]; exact: boolean; more: boolean }> {
  const q = query.trim();
  if (!q) return { hits: [], exact: true, more: false };
  const [aliases, stored] = await Promise.all([cat.table<Alias>("aliases.parquet"), cat.table<Stored>("sequences.parquet")]);
  let roots: string[];
  let exact = true;
  if (q.startsWith("SQ.") || isMd5(q)) {
    const lc = q.toLowerCase();
    roots = stored.filter((s) => s.sha512t24u === q || s.md5 === lc).map((s) => s.root_id);
  } else {
    const lc = q.toLowerCase();
    roots = aliases.filter((a) => a.alias.toLowerCase() === lc || a.root_id.toLowerCase() === lc).map((a) => a.root_id);
    if (!roots.length) {
      exact = false;
      roots = aliases.filter((a) => a.alias.toLowerCase().includes(lc) || a.root_id.toLowerCase().includes(lc)).map((a) => a.root_id);
    }
  }
  const unique = [...new Set(roots)].sort();
  return { hits: await describe(cat, unique.slice(0, MAX), aliases, stored), exact, more: unique.length > MAX };
}

async function describe(cat: Catalog, roots: string[], aliases: Alias[], stored: Stored[]): Promise<RootHit[]> {
  const members = await cat.table<Member>("assembly_members.parquet");
  const want = new Set(roots);
  const byRoot = Map.groupBy(aliases.filter((a) => want.has(a.root_id)), (a) => a.root_id);
  const storedBy = Map.groupBy(stored.filter((s) => want.has(s.root_id)), (s) => s.root_id);
  const memberBy = Map.groupBy(members.filter((m) => want.has(m.genbank_accession)), (m) => m.genbank_accession);
  return roots.map((root) => {
    const as = byRoot.get(root) ?? [];
    const ss = (storedBy.get(root) ?? []).sort((a, b) => a.operations.length - b.operations.length);
    const books = [...new Set([...as.filter((a) => a.book).map((a) => a.book!), ...(memberBy.get(root) ?? []).map((m) => m.book)])].sort();
    return {
      root_id: root,
      length: ss.find((s) => !s.operations.length)?.length ?? ss[0]?.length ?? null,
      global: distinct(as.filter((a) => !a.book)),
      books: books.map((b) => {
        const m = (memberBy.get(root) ?? []).find((x) => x.book === b);
        return { book: b, role: m?.role ?? null, assembly: m?.assembly_name ?? null,
                 names: distinct(as.filter((a) => a.book === b)) };
      }),
      stored: ss,
    };
  });
}

/** One stored sequence: its record, every way to make it, and every edition (by book) that has it, with the name. */
export async function storedSequence(cat: Catalog, sq: string) {
  const [stored, derivations, manifests, editions] = await Promise.all([
    cat.table<Stored>("sequences.parquet"), cat.table<Derivation>("derivations.parquet"),
    cat.table<ManifestRow>("manifests.parquet"), cat.table<{ edition: string; book: string }>("editions.parquet")]);
  const rec = stored.find((s) => s.sha512t24u === sq);
  if (!rec) return null;
  const bookOf = new Map(editions.map((e) => [e.edition, e.book]));
  const uses = manifests.filter((r) => r.sha512t24u === sq).map((r) => ({ book: bookOf.get(r.edition) ?? "", edition: r.edition, name: r.name }));
  return { rec, ways: derivations.filter((d) => d.sha512t24u === sq),
           byBook: [...Map.groupBy(uses, (u) => u.book)].sort(([a], [b]) => a.localeCompare(b)) };
}
