<script lang="ts">
  // The app: open the catalog, then show the page the hash names, and what
  // each action downloaded (the measurement of whether a static catalog is
  // enough).
  import { init } from "@abdenlab/refbook";
  import { Blocks } from "./data/blocks.ts";
  import { Catalog } from "./data/catalog.ts";
  import { measure, onMeasure, type Tally } from "./data/meter.ts";
  import { bytes } from "./format.ts";
  import { route } from "./route.svelte.ts";
  import { LABEL, NEXT, setTheme, theme } from "./theme.svelte.ts";
  import Icon from "./components/Icon.svelte";
  import Mark from "./components/Mark.svelte";
  import ErrorBox from "./components/ErrorBox.svelte";
  import { bookFor, books } from "./data/books.ts";
  import BookView from "./views/BookView.svelte";
  import CatalogView from "./views/CatalogView.svelte";
  import CatalogHomeView from "./views/CatalogHomeView.svelte";
  import AboutView from "./views/AboutView.svelte";
  import EditorView from "./views/EditorView.svelte";
  import HomeView from "./views/HomeView.svelte";
  import SequencesView from "./views/SequencesView.svelte";
  import IdentifyView from "./views/IdentifyView.svelte";
  import EditionView from "./views/EditionView.svelte";
  import SequenceView from "./views/SequenceView.svelte";

  // The catalog: ?catalog=<url> on the page, else VITE_CATALOG_URL at build
  // time, else /catalog/ (the dev server's copy of the repository's build).
  const catalogUrl = new URLSearchParams(location.search).get("catalog") ?? import.meta.env.VITE_CATALOG_URL ?? "/catalog/";
  // The download meter (requests, bytes and time per action): a measurement of the static catalog, for development.
  // Shown only with ?meter in the address (dev server or build).
  const showMeter = new URLSearchParams(location.search).has("meter");

  const opened = (async () => {
    await init();
    const cat = await measure("open catalog", () => Catalog.open(catalogUrl));
    return { cat, bs: await books(cat) };
  })();

  let blocks: Promise<Blocks> | null = null;
  const openBlocks = (cat: Catalog) => (blocks ??= measure("open root_blocks", () => Blocks.open(cat)));

  let log = $state<{ action: string; t: Tally }[]>([]);
  let total = $state<Tally>({ requests: 0, bytes: 0, ms: 0 });
  onMeasure((action, t, all) => {
    log = [{ action, t: { ...t } }, ...log].slice(0, 4);
    total = { ...all };
  });

  const parts = $derived(route.current.parts);
  $effect(() => {
    document.title = parts.length ? `${parts.at(-1)} · refbook` : "refbook";
  });
</script>

<header class="top">
  <a class="brand" href="#/"><Mark />refbook</a>
  <!-- <span class="tagline">Genome: Bought the book? Which edition?</span> -->
  <nav>
    <a href="#/about" class:here={parts[0] === "about"}>About</a>
    <a href="#/catalog" class:here={parts[0] === "catalog"}>Catalog</a>
    <a href="#/editor" class:here={parts[0] === "editor"}>Edit</a>
    <a href="#/identify" class:here={parts[0] === "identify"}>Identify</a>
    <button type="button" class="theme" title={`${LABEL[theme.current]} (click for ${NEXT[theme.current] === "system" ? "the system's" : NEXT[theme.current]})`}
            aria-label={LABEL[theme.current]} onclick={() => setTheme(NEXT[theme.current])}>
      <Icon name={theme.current === "system" ? "system" : theme.current === "light" ? "sun" : "moon"} />
    </button>
    <a class="icon-link" href="https://github.com/abdenlab/refbook" title="refbook on GitHub" aria-label="refbook on GitHub"><Icon name="github" /></a>
  </nav>
</header>
<main>
  {#await opened}
    <p class="muted">Loading the catalog…</p>
  {:then { cat, bs }}
    <!-- The book an address names: #/catalog/books/<assembly>/..., #/editor/<assembly>. -->
    {@const book = parts[0] === "catalog" && parts[1] === "books" ? bookFor(parts[2], bs)
                 : parts[0] === "editor" ? bookFor(parts[1], bs) : undefined}
    {@const p = parts[0] === "catalog" && parts[1] === "books" ? parts.slice(3) : []}
    {#key route.current}
      {#if book && p[0] === "edition" && p[1] && p[2] === "seq" && p[3]}
        <SequenceView {cat} blocks={() => openBlocks(cat)} at={{ book, label: p[1], name: p[3] }} query={route.current.query} />
      {:else if book && p[0] === "edition" && p[1]}
        <EditionView {cat} {book} label={p[1]} />
      {:else if book && parts[0] === "catalog"}
        <BookView {book} />
      {:else if parts[0] === "catalog" && parts[1] === "books"}
        <CatalogView {bs} />
      {:else if parts[0] === "catalog" && parts[1] === "sequences" && parts[2]}
        <SequenceView {cat} blocks={() => openBlocks(cat)} sq={parts[2]} query={route.current.query} />
      {:else if parts[0] === "catalog" && parts[1] === "sequences"}
        <SequencesView {cat} query={route.current.query} />
      {:else if parts[0] === "catalog"}
        <CatalogHomeView {bs} />
      {:else if parts[0] === "editor"}
        <!-- The Editor: the book the address names, else GRCh38's (the one most used). -->
        <EditorView {cat} {bs} book={book ?? bs.find((b) => b.book === "grch38") ?? bs[0]} query={route.current.query} />
      {:else if parts[0] === "about"}
        <AboutView {cat} />
      {:else if parts[0] === "identify"}
        <IdentifyView {cat} query={route.current.query} />
      {:else}
        <HomeView />
      {/if}
    {/key}
  {:catch e}
    <ErrorBox error={e} />
    <p class="muted">Catalog: {catalogUrl}</p>
  {/await}
</main>
{#if showMeter && total.requests}
  <footer class="meter" aria-live="polite">
    <span class="total">Downloaded this session: {total.requests} requests, {bytes(total.bytes)}</span>
    <ul>
      {#each log as { action, t }, i (i)}
        <li><span class="action">{action}</span> {t.requests} req, {bytes(t.bytes)}, {t.ms.toFixed(0)} ms</li>
      {/each}
    </ul>
  </footer>
{/if}
