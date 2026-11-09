<script lang="ts">
  // The catalog: one card per assembly, newest first. Each opens its book.
  import { bookHref, familyOf, FAMILIES, type Book } from "../data/books.ts";
  import { n } from "../format.ts";
  import Icon from "../components/Icon.svelte";

  let { bs }: { bs: Book[] } = $props();

  /** The species a book's assembly is of: every book is human so far (a column of books.parquet, once one isn't). */
  const SPECIES = { name: "Homo sapiens", icon: "human" } as const;

  /** A spine's bands, as the mark draws them (chromosome-like, [start, end] in % of its height), different per
   * book so each reads as its own volume. */
  const BANDS = [
    [[8, 12], [30, 37], [55, 63], [78, 81]],
    [[6, 9], [24, 32], [47, 51], [66, 74], [86, 90]],
    [[10, 15], [36, 40], [52, 61], [80, 86]],
  ];
  const spine = (bands: number[][]) =>
    `linear-gradient(to bottom, ${bands.flatMap(([a, b]) => [`transparent ${a}%`, `var(--band) ${a}%`, `var(--band) ${b}%`, `transparent ${b}%`]).join(", ")})`;

  const cards = $derived([...bs].sort((a, b) => b.assembly.localeCompare(a.assembly)).map((b, i) => {
    const fams = new Set(b.editions.map((e) => familyOf(e.edition, b.targets)));
    return { b, publishers: FAMILIES.filter((f) => fams.has(f.key)).map((f) => f.name), bands: spine(BANDS[i % BANDS.length]) };
  }));
</script>

<section class="catalog">
  <p class="crumbs"><a href="#/">Home</a> / Catalog</p>
  <h1>Catalog</h1>
  <p class="lede">Each <b>book</b> in <i>refbook</i> corresponds to a reference genome assembly. Published FASTA files and their summaries and digests reduce to <b>editions</b>, independent of sequence order.</p>
  <div class="books">
    {#each cards as { b, publishers, bands } (b.book)}
      <a class="book" href={bookHref(b.book)}>
        <span class="spine" style:background-image={bands} aria-hidden="true"></span>
        <span class="series"><Icon name={SPECIES.icon} /> <i>{SPECIES.name}</i></span>
        <span class="name">{b.assembly} <Icon name="arrow" /></span>
        <span class="releases">{b.releases[0]} – {b.releases.at(-1)}</span>
        <span class="counts">
          <span><b>{n(b.editions.length)}</b> editions</span>
          <span><b>{n(b.targets.length)}</b> published files</span>
          <span><b>{n(b.releases.length)}</b> releases</span>
          <span><b>{n(b.nSequences)}</b> sequences</span>
        </span>
        <span class="publishers">{publishers.join(" · ")}</span>
      </a>
    {/each}
  </div>
</section>

<style>
  .lede { color: var(--muted); }
  .books { display: grid; grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr)); gap: 1rem; margin-top: 1.5rem; }
  /* A book: a banded spine down the left, as the mark draws them. */
  .book {
    position: relative;
    display: flex; flex-direction: column; gap: 0.6rem; padding: 1.4rem 1.7rem 1.6rem calc(1.7rem + 14px); color: var(--text);
    background: var(--surface); border: 1px solid var(--line); border-radius: 4px 12px 12px 4px;
    transition: border-color 120ms, box-shadow 120ms, transform 120ms;
  }
  .book:hover { text-decoration: none; border-color: var(--accent); box-shadow: 0 2px 12px rgb(0 0 0 / 0.06); transform: translateY(-1px); }
  .spine {
    --band: var(--mark-band);
    position: absolute; left: -1px; top: -1px; bottom: -1px; width: 14px; border-radius: 4px 0 0 4px;
    background-color: var(--mark-spine); transition: background-color 120ms;
  }
  .book:hover .spine { --band: var(--mark-ed-band); background-color: var(--mark-ed); }
  .series { display: inline-flex; align-items: center; gap: 0.35rem; color: var(--muted); font-size: 0.85rem; }
  .series :global(.icon) { font-size: 1.15em; }
  .name { font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; display: inline-flex; align-items: center; gap: 0.5rem; }
  .name :global(.icon) { font-size: 0.6em; color: var(--muted); transition: transform 120ms; }
  .book:hover .name :global(.icon) { transform: translateX(3px); color: var(--accent); }
  .releases { color: var(--muted); font-size: 0.95rem; }
  .counts { display: grid; grid-template-columns: repeat(2, auto); justify-content: start; gap: 0.2rem 1.6rem; font-size: 0.95rem; }
  .counts b { font-variant-numeric: tabular-nums; }
  .publishers { color: var(--muted); font-size: 0.85rem; border-top: 1px solid var(--line); padding-top: 0.6rem; margin-top: 0.2rem; }
</style>
