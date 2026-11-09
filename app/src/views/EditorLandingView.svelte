<script lang="ts">
  // The Editor's landing: pick the assembly to design an edition of. The Editor knows one assembly so far.
  import { editorHref, type Book } from "../data/books.ts";
  import { DESIGN_BOOK } from "../data/design.ts";
  import { n } from "../format.ts";
  import Icon from "../components/Icon.svelte";

  let { bs }: { bs: Book[] } = $props();
  const sorted = $derived([...bs].sort((a, b) => b.assembly.localeCompare(a.assembly)));
</script>

<section class="editor-landing">
  <p class="crumbs"><a href="#/">Home</a> / Editor</p>
  <h1>Editor</h1>
  <p class="lede">Design an edition of your own: choose the sequences, what is done to their bases and what they are
    called, and get its digests and files. Start from scratch or from any cataloged edition.</p>
  <div class="books">
    {#each sorted as b (b.book)}
      {#if b.book === DESIGN_BOOK}
        <a class="book" href={editorHref(b.book)}>
          <span class="name">{b.assembly} <Icon name="arrow" /></span>
          <span class="muted">Start from any of its {n(b.editions.length)} editions.</span>
        </a>
      {:else}
        <div class="book soon" aria-disabled="true">
          <span class="name">{b.assembly}</span>
          <span class="muted">Not in the Editor yet.</span>
        </div>
      {/if}
    {/each}
  </div>
</section>

<style>
  .editor-landing { max-width: 60rem; margin: 0 auto; }
  .lede { color: var(--muted); max-width: 70ch; }
  .books { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 1rem; margin-top: 1.5rem; }
  .book {
    display: flex; flex-direction: column; gap: 0.5rem; padding: 1.4rem 1.6rem; color: var(--text);
    background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
    transition: border-color 120ms, box-shadow 120ms, transform 120ms;
  }
  a.book:hover { text-decoration: none; border-color: var(--accent); box-shadow: 0 2px 12px rgb(0 0 0 / 0.06); transform: translateY(-1px); }
  .soon { opacity: 0.6; }
  .name { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; display: inline-flex; align-items: center; gap: 0.5rem; }
  .name :global(.icon) { font-size: 0.6em; color: var(--muted); }
</style>
