<script lang="ts">
  // Sequences, across books: search every root and stored sequence by name, accession or digest (?q=), and see
  // which books each appears in, under which names. A stored sequence's own page is SequenceView.
  import { untrack } from "svelte";
  import { bookHref, bookOf, sequenceHref, sequencesHref } from "../data/books.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { OPERATION_LABELS } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { search } from "../data/sequences.ts";
  import { bp, n, ncbiUrl } from "../format.ts";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Icon from "../components/Icon.svelte";

  let { cat, query }: { cat: Catalog; query: URLSearchParams } = $props();

  let q = $state(untrack(() => query.get("q") ?? ""));
  let asked = $state(untrack(() => query.get("q") ?? ""));
  const found = $derived(asked ? measure(`sequences ${asked}`, () => search(cat, asked)) : null);

  function submit(e: SubmitEvent) {
    e.preventDefault();
    asked = q.trim();
    history.replaceState(null, "", sequencesHref(asked));
  }

  const assemblyOf = (book: string) => bookOf.get(book)?.assembly ?? book;
  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(", ") : "original");
  const NAMESPACES: Record<string, string> = { genbank: "GenBank", refseq: "RefSeq", ucsc: "UCSC", grc: "GRC", ensembl: "Ensembl",
                                               imgt: "IMGT/HLA", imgt_accession: "IMGT/HLA accession" };
</script>

<section>
  <p class="crumbs"><a href="#/">Home</a> / <a href="#/catalog">Catalog</a> / Sequences</p>
  <h1>Sequences</h1>
  <p class="lede">Find sequences by name, accession, or digest, in every cataloged assembly. The same name can refer to different
    sequences in different assemblies.</p>
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
            <h2>{#if ncbiUrl(h.root_id)}<a class="external" href={ncbiUrl(h.root_id)} target="_blank" rel="noopener" title={`${h.root_id} at NCBI, in a new tab`}>{h.root_id}<Icon name="external" /></a>{:else}{h.root_id}{/if} {#if h.length !== null}<span class="length muted small">{bp(h.length)}</span>{/if}</h2>
            {#if h.global.length}
              <p class="small">{#each h.global.filter((g) => g.alias !== h.root_id) as g, i (g.namespace + g.alias)}{i ? " · " : ""}{NAMESPACES[g.namespace] ?? g.namespace} {#if g.namespace === "refseq" && ncbiUrl(g.alias)}<a class="external" href={ncbiUrl(g.alias)} target="_blank" rel="noopener" title={`${g.alias} at NCBI, in a new tab`}><code>{g.alias}</code><Icon name="external" /></a>{:else}<code>{g.alias}</code>{/if}{/each}</p>
            {/if}
            <!-- The stored sequences made from the root: each its own page, by digest. -->
            <div class="versions">
              <span class="label small">Appears as:</span>
              {#each h.stored as s (s.sha512t24u)}
                <a class="version" href={sequenceHref(s.sha512t24u)} title={`The sequence ${s.sha512t24u}`}>
                  <span>{ops(s.operations)}{#if s.book}{" "}<span class="muted">({assemblyOf(s.book)})</span>{/if}</span>
                  <code class="digest">{s.sha512t24u.slice(0, 11)}…</code>
                  <Icon name="arrow" />
                </a>
              {/each}
            </div>
            <p class="label small">Appears in:</p>
            <table class="books">
              <thead><tr><th>Book</th><th>Role</th><th>Names</th></tr></thead>
              <tbody>
                {#each h.books as b (b.book)}
                  <tr>
                    <td><a href={bookHref(b.book)}>{assemblyOf(b.book)}</a></td>
                    <td>{b.role ?? "ancillary"}</td>
                    <td>{#each b.names as x, i (x.namespace + x.alias)}{i ? " · " : ""}{NAMESPACES[x.namespace] ?? x.namespace} <code>{x.alias}</code>{/each}</td>
                  </tr>
                {:else}
                  <tr><td colspan="3" class="muted">In no assembly's releases; an external root.</td></tr>
                {/each}
              </tbody>
            </table>
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
  .hit h2 .length { margin-left: 0.6rem; font-weight: normal; }
  .books { width: 100%; font-size: 0.9rem; }
  .books td, .books th { padding: 0.2rem 0.5rem; text-align: left; vertical-align: top; }
  .small { font-size: 0.85rem; }
  .versions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.5rem; margin: 0.5rem 0 0.7rem; }
  .versions .label { color: var(--muted); margin-right: 0.2rem; }
  p.label { color: var(--muted); margin: 0 0 0.2rem; }
  .version {
    display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0.7rem; font-size: 0.88rem; color: var(--text);
    background: var(--surface); border: 1px solid var(--line); border-radius: 8px; transition: border-color 120ms;
  }
  .version:hover { text-decoration: none; border-color: var(--accent); }
  .version .digest { font-size: 0.78rem; color: var(--muted); }
  .version :global(.icon) { color: var(--muted); font-size: 0.85em; transition: transform 120ms; }
  .version:hover :global(.icon) { color: var(--accent); transform: translateX(2px); }
</style>
