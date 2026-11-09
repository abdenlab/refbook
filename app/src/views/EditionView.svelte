<script lang="ts">
  // An edition: its identity, its recipe (roots → operations → names → output),
  // the files that reproduce it, exports, and its sequences.
  import * as rb from "@abdenlab/refbook";
  import type { Catalog } from "../data/catalog.ts";
  import { DESIGN_BOOK, rootPlaces } from "../data/design.ts";
  import { bookHref, editionHref, editorHref, relations, type Book } from "../data/books.ts";
  import { chromSizes, ordered as inOrder, ORDERS, sequenceDictionary, type Order } from "../data/exports.ts";
  import { inOrder as fileOrder } from "../data/exports.ts";
  import { editions, manifest, targetOrder, targets, type ManifestRow } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { bp, download, n } from "../format.ts";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Icon from "../components/Icon.svelte";
  import RecipeDiagram from "../components/RecipeDiagram.svelte";
  import SequencesTable from "../components/SequencesTable.svelte";
  import type { Recipe } from "./recipe.ts";

  let { cat, book, label }: { cat: Catalog; book: Book; label: string } = $props();
  const places = () => rootPlaces(cat, book.book, book.assembly);

  async function assemblyNames(): Promise<Map<string, string>> {
    const members = await cat.table<{ assembly_accession: string; assembly_name: string }>("assembly_members.parquet");
    return new Map(members.map((m) => [m.assembly_accession, m.assembly_name]));
  }

  const loaded = $derived(measure(`edition ${label}`, async () => {
    const [fs, ts, rows, names, pl, rel] = await Promise.all([editions(cat), targets(cat), manifest(cat, label), assemblyNames(),
                                                             places(), relations(cat, label)]);
    const f = fs.find((x) => x.edition === label && x.book === book.book);
    return { f, rows, names, places: pl, rel, mine: ts.filter((t) => t.edition === label),
             recipe: f ? (JSON.parse(f.recipe) as Recipe) : null };
  }));

  // Exports, by name or karyotypic by role.
  let order = $state<Order>("name");
  const stem = () => label;
  async function ordered(rows: ManifestRow[]) {
    return inOrder(rows, order, await places());
  }
  // The table: by name, karyotypic by role, or as in one of the edition's published files (file:<target>).
  let tableOrder = $state("karyotypic");
  let sorted = $state<ManifestRow[] | null>(null);
  const tableOrders = (mine: { target: string; publisher: string; alias: string }[]): [string, string][] => [
    ...ORDERS,
    ...mine.map((t) => [`file:${t.target}`, `as in ${t.publisher}: ${t.alias}`] as [string, string]),
  ];
  async function sortRows(rows: ManifestRow[], o: string): Promise<ManifestRow[]> {
    if (o.startsWith("file:")) return fileOrder(rows, await targetOrder(cat, o.slice(5)));
    return inOrder(rows, o as Order, await places());
  }
  $effect(() => {
    const o = tableOrder;
    loaded.then(({ rows }) => sortRows(rows, o)).then((r) => { if (o === tableOrder) sorted = r; });
  });

  async function seqcol(rows: ManifestRow[]) {
    const r = await ordered(rows);
    return JSON.stringify(rb.seqcolLevel2(r.map((x) => x.name), r.map((x) => x.length), r.map((x) => x.sha512t24u)), null, 1);
  }
</script>

{#await loaded then { f, rows, names, places, rel, mine, recipe }}
  <section>
    <p class="crumbs"><a href="#/">Home</a> / <a href="#/catalog">Catalog</a> / <a href={bookHref(book.book)}>{book.assembly}</a> / {label}</p>
    {#if !f || !recipe}
      <h1>No such edition</h1>
      <p><a href={bookHref(book.book)}>Back to {book.assembly}</a></p>
    {:else}
      <h1>{label}</h1>
      <h2>Assembly</h2>
      <dl class="ids">
        <dt>Release</dt>
        <dd>{f.assembly}{f.patch_release !== null ? `.p${f.patch_release}` : ""}</dd>
        <dt>Sequences</dt>
        <dd>{n(f.n_sequences)}</dd>
        <dt>Total length</dt>
        <dd>{bp(f.total_length)}</dd>
      </dl>
      <h2 class="act">Identity
        <a class="action" href={`#/identify?${new URLSearchParams({ from: label, tab: "compare" })}`} title="Compare with another edition or published file"><Icon name="compare" /> Compare</a></h2>
      <dl class="ids">
        <dt>Edition digest</dt>
        <dd><Digest value={f.id} /><div class="muted">Identifies the collection of named sequences regardless of sequence order.</div></dd>
        <dt>Seqcol digest</dt>
        <dd><Digest value={f.seqcol_digest} /><div class="muted">Identifies the collection of named sequences ordered by sequence name.</div></dd>
      </dl>

      <h2 class="act">Recipe
        {#if book.book === DESIGN_BOOK}
          <a class="action" href={editorHref(book.book, new URLSearchParams({ from: label, tab: "recipe" }))} title="Open this recipe in the Editor"><Icon name="load" /> Edit</a>
        {/if}</h2>
      <p class="muted">The recipe builds this edition from root sequences. The result is uppercase: no soft masking is applied.</p>
      <RecipeDiagram edition={f} {recipe} {rows} {names} />

      <h2>Publisher's files</h2>
      <p class="muted">Each target file was reproduced by the recipe above, sequence by sequence, and matched (ignoring soft masking).</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Publisher</th><th>File</th><th>Checked by</th><th>Seqcol digest (from file's order)</th></tr></thead>
          <tbody>
            {#each mine as t (t.target)}
              <tr>
                <td>{t.publisher}</td>
                <td><a href={t.published} rel="noopener">{t.alias}</a></td>
                <td>{t.evidence === "content" ? "every sequence's bases" : "its .dict (names, lengths, MD5s)"}</td>
                <td><code class="small">{t.seqcol_digest}</code></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <h2>Sequences</h2>
      <SequencesTable edition={label} rows={sorted ?? rows} {places} orders={tableOrders(mine)} bind:order={tableOrder} />

      {#if rel.length}
        <h2>Related editions</h2>
        <p class="muted">How this edition stands to the other {book.assembly} editions it is simply related to, nearest first.</p>
        <ul class="relations">
          {#each rel as r (r.other)}
            <li>{#if r.kind === "within"}
                <a href={editionHref(r.other)}>{r.other}</a> is this edition plus {n(r.added.length)}
                {r.added.length === 1 ? "sequence" : "sequences"}{#if r.added.length <= 4}: {r.added.join(", ")}{/if}.
              {:else if r.kind === "adds"}
                This edition is <a href={editionHref(r.other)}>{r.other}</a> plus {n(r.added.length)}
                {r.added.length === 1 ? "sequence" : "sequences"}{#if r.added.length <= 4}: {r.added.join(", ")}{/if}.
              {:else if r.kind === "renamed"}
                <a href={editionHref(r.other)}>{r.other}</a> has the same sequences, {n(r.renamed)} of them named otherwise.
              {:else}
                <a href={editionHref(r.other)}>{r.other}</a> has the same names on the same roots; {n(r.differ)}
                {r.differ === 1 ? "sequence differs" : "sequences differ"} by their operations.
              {/if}</li>
          {/each}
        </ul>
      {/if}
    {/if}
  </section>
{:catch e}
  <ErrorBox error={e} />
{/await}
