<script lang="ts">
  // The catalog: its two ways in, the books (an assembly's editions) and the sequences (by name, accession or digest).
  import { inCatalogOrder, sequencesHref, type Book } from "../data/books.ts";
  import { n } from "../format.ts";
  import Icon from "../components/Icon.svelte";

  let { bs }: { bs: Book[] } = $props();
  const nEditions = $derived(bs.reduce((s, b) => s + b.editions.length, 0));
</script>

<section>
  <p class="crumbs"><a href="#/">Home</a> / Catalog</p>
  <h1>Catalog</h1>
  <p class="lede">Every cataloged edition belongs to a <b>book</b>: one assembly, with all its releases. The editions are
    made of <b>sequences</b>, each identified by its digest, and the same sequence can appear in many editions under
    different names.</p>
  <nav class="doors" aria-label="The catalog">
    <a class="door" href="#/catalog/books">
      <span class="glyph"><Icon name="books" /></span>
      <span class="title">Books <Icon name="arrow" /></span>
      <span class="text">{inCatalogOrder(bs).map((b) => b.assembly).join(", ")}: {n(nEditions)} editions, each with its
        published files, recipe and sequences.</span>
    </a>
    <a class="door" href={sequencesHref()}>
      <span class="glyph"><Icon name="search" /></span>
      <span class="title">Sequences <Icon name="arrow" /></span>
      <span class="text">Find a sequence by name, accession, or digest, and see the editions it appears in.</span>
    </a>
  </nav>
</section>

<style>
  .lede { margin-bottom: 1.6rem; }
</style>
