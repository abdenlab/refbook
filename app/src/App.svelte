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
  import AboutView from "./views/AboutView.svelte";
  import EditorLandingView from "./views/EditorLandingView.svelte";
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
  // Shown by the dev server, and in a build with ?meter in the address.
  const showMeter = import.meta.env.DEV || new URLSearchParams(location.search).has("meter");

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
    <button type="button" class="theme" title={`${LABEL[theme.current]} (click for ${NEXT[theme.current] === "system" ? "the system's" : NEXT[theme.current]})`}
            aria-label={LABEL[theme.current]} onclick={() => setTheme(NEXT[theme.current])}>
      <Icon name={theme.current === "system" ? "system" : theme.current === "light" ? "sun" : "moon"} />
    </button>
    <a href="#/catalog" class:here={parts[0] === "catalog"}>Catalog</a>
    <a href="#/sequences" class:here={parts[0] === "sequences" || parts[0] === "sequence"}>Sequences</a>
    <a href="#/identify" class:here={parts[0] === "identify"}>Identify</a>
    <a href="#/editor" class:here={parts[0] === "editor"}>Editor</a>
    <a href="#/about" class:here={parts[0] === "about"}>About</a>
  </nav>
</header>
<main>
  {#await opened}
    <p class="muted">Loading the catalog…</p>
  {:then { cat, bs }}
    {@const book = parts[0] === "catalog" || parts[0] === "editor" ? bookFor(parts[1], bs) : undefined}
    {#key route.current}
      {#if parts[0] === "catalog" && book && parts[2] === "edition" && parts[3] && parts[4] === "seq" && parts[5]}
        <SequenceView {cat} {book} blocks={() => openBlocks(cat)} label={parts[3]} name={parts[5]} query={route.current.query} />
      {:else if parts[0] === "catalog" && book && parts[2] === "edition" && parts[3]}
        <EditionView {cat} {book} label={parts[3]} />
      {:else if parts[0] === "catalog" && book}
        <BookView {book} />
      {:else if parts[0] === "catalog"}
        <CatalogView {bs} />
      {:else if parts[0] === "editor" && book}
        <EditorView {cat} {book} query={route.current.query} />
      {:else if parts[0] === "editor"}
        <EditorLandingView {bs} />
      {:else if parts[0] === "about"}
        <AboutView {cat} />
      {:else if parts[0] === "sequences"}
        <SequencesView {cat} query={route.current.query} />
      {:else if parts[0] === "sequence" && parts[1]}
        <SequencesView {cat} query={route.current.query} sq={parts[1]} />
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
