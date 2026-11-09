<script lang="ts">
  // A book: one assembly, its releases, and its editions grouped by who makes them. The top of the breadcrumbs
  // below home: assembly / edition / sequence.
  import Icon from "../components/Icon.svelte";
  import { editionHref, editorHref, familyOf, FAMILIES, type Book } from "../data/books.ts";
  import { OPERATION_LABELS } from "../data/editions.ts";
  import { bp, n } from "../format.ts";

  let { book }: { book: Book } = $props();

  const byEdition = $derived(Map.groupBy(book.targets, (t) => t.edition));
  const groups = $derived(FAMILIES.map((f) => ({
    ...f,
    rows: book.editions.filter((e) => familyOf(e.edition, book.targets) === f.key)
      .sort((a, b) => a.n_sequences - b.n_sequences || a.edition.localeCompare(b.edition)),
  })).filter((g) => g.rows.length));
</script>

<section>
  <p class="crumbs"><a href="#/">Home</a> / <a href="#/catalog">Catalog</a> / {book.assembly}</p>
  <h1 class="act">{book.assembly}, as published
    <a class="action" href={editorHref(book.book, new URLSearchParams({ tab: "catalog" }))} title={`Design a ${book.assembly} edition of your own, starting from the catalog's`}><Icon name="load" /> Editor</a></h1>
  <p class="lede">
    {n(book.targets.length)} published files reduce to {n(book.editions.length)} editions: distinct sets of named
    sequences, each a recipe over the same original sequences, checked by rebuilding the file. They are drawn from
    {n(book.releases.length)} releases ({book.releases[0]} – {book.releases.at(-1)}), {n(book.nSequences)} sequences
    in all.
  </p>

  {#each groups as g (g.key)}
    <h2>{g.name}</h2>
    <p class="muted">{g.about}</p>
    <div class="table-wrap">
      <table class="editions">
        <thead>
          <tr><th>Edition</th><th class="num">Sequences</th><th class="num">Length</th><th>Operations</th><th>Naming</th><th>Published as</th></tr>
        </thead>
        <tbody>
          {#each g.rows as f (f.edition)}
            <tr>
              <td><a href={editionHref(f.edition)}>{f.edition}</a>{#if f.patch_release !== null}<span class="tag">p{f.patch_release}</span>{/if}</td>
              <td class="num">{n(f.n_sequences)}</td>
              <td class="num">{bp(f.total_length, true)}</td>
              <td>
                {#each f.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{:else}<span class="muted">none</span>{/each}
              </td>
              <td class="naming">{f.naming.split(";")[0]}</td>
              <td>
                <ul class="plain">
                  {#each byEdition.get(f.edition) ?? [] as t (t.target)}
                    <li><span class="publisher">{t.publisher}</span> <span class="alias">{t.alias}</span></li>
                  {/each}
                </ul>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/each}
</section>
