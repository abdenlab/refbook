<script lang="ts">
  // Sequences, across books: search every root and stored sequence by name, accession or digest (?q=), and see
  // which books each appears in, under which names. A stored sequence's own page is SequenceView.
  import { untrack } from "svelte";
  import { bookHref, bookOf } from "../data/books.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { OPERATION_LABELS } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { search } from "../data/sequences.ts";
  import { bp, n } from "../format.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat, query }: { cat: Catalog; query: URLSearchParams } = $props();

  let q = $state(untrack(() => query.get("q") ?? ""));
  let asked = $state(untrack(() => query.get("q") ?? ""));
  const found = $derived(asked ? measure(`sequences ${asked}`, () => search(cat, asked)) : null);

  function submit(e: SubmitEvent) {
    e.preventDefault();
    asked = q.trim();
    history.replaceState(null, "", `#/sequences${asked ? `?${new URLSearchParams({ q: asked })}` : ""}`);
  }

  const assemblyOf = (book: string) => bookOf.get(book)?.assembly ?? book;
  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(", ") : "as submitted");
  const NAMESPACES: Record<string, string> = { genbank: "GenBank", refseq: "RefSeq", ucsc: "UCSC", grc: "GRC", ensembl: "Ensembl",
                                               imgt: "IMGT/HLA", imgt_accession: "IMGT/HLA accession" };
</script>

<section>
  <p class="crumbs"><a href="#/">Home</a> / Sequences</p>
  <h1>Sequences</h1>
  <p class="lede">Find a sequence by name, accession or digest, in every assembly. A name can mean different
    sequences in different assemblies: chr1 is CM000663.1 in GRCh37 and CM000663.2 in GRCh38, and chrM is the Yoruba
    mitochondrion in hg19 but rCRS everywhere else.</p>
  <form class="search" onsubmit={submit}>
    <input type="search" bind:value={q} placeholder="chrM, GL000194.1, HSCHR6_MHC_COX, an MD5 or SQ. digest" aria-label="Find a sequence" />
    <button type="submit">Find</button>
  </form>
  {#if found}
    {#await found then { hits, exact, more }}
      {#if !hits.length}
        <p>Nothing in the catalog is called or digests to <code>{asked}</code>.</p>
      {:else}
        <p class="muted">{exact ? "" : "No exact match; names containing it: "}{n(hits.length)}{more ? "+" : ""} {hits.length === 1 ? "root" : "roots"}.</p>
        {#each hits as h (h.root_id)}
          <div class="card hit">
            <h2>{h.root_id} {#if h.length !== null}<span class="muted small">{bp(h.length)}</span>{/if}</h2>
            {#if h.global.length}
              <p class="small">{#each h.global.filter((g) => g.alias !== h.root_id) as g, i (g.namespace + g.alias)}{i ? " · " : ""}{NAMESPACES[g.namespace] ?? g.namespace} <code>{g.alias}</code>{/each}</p>
            {/if}
            <table class="books">
              <thead><tr><th>Assembly</th><th>Role</th><th>Names</th></tr></thead>
              <tbody>
                {#each h.books as b (b.book)}
                  <tr>
                    <td><a href={bookHref(b.book)}>{assemblyOf(b.book)}</a></td>
                    <td>{b.role ?? "added by its editions"}</td>
                    <td>{#each b.names as x, i (x.namespace + x.alias)}{i ? " · " : ""}{NAMESPACES[x.namespace] ?? x.namespace} <code>{x.alias}</code>{/each}</td>
                  </tr>
                {:else}
                  <tr><td colspan="3" class="muted">In no assembly's releases; an external root.</td></tr>
                {/each}
              </tbody>
            </table>
            <p class="small">Available:
              {#each h.stored as s, i (s.sha512t24u)}{i ? " · " : ""}<a href={`#/sequence/${encodeURIComponent(s.sha512t24u)}`}>{ops(s.operations)}{#if s.book}{" "}({assemblyOf(s.book)}){/if}</a>{/each}</p>
          </div>
        {/each}
      {/if}
    {:catch e}
      <ErrorBox error={e} />
    {/await}
  {/if}
</section>

<style>
  .search { display: flex; gap: 0.5rem; margin: 0.8rem 0 1rem; max-width: 42rem; }
  .search input { flex: 1; }
  .hit { margin-bottom: 0.8rem; }
  .hit h2 { margin: 0 0 0.3rem; font-size: 1.05rem; }
  .books { width: 100%; font-size: 0.9rem; }
  .books td, .books th { padding: 0.2rem 0.5rem; text-align: left; vertical-align: top; }
  .small { font-size: 0.85rem; }
</style>
