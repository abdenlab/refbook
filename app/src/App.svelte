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
  import ErrorBox from "./components/ErrorBox.svelte";
  import CompareView from "./views/CompareView.svelte";
  import DesignView from "./views/DesignView.svelte";
  import IdentifyView from "./views/IdentifyView.svelte";
  import FlavorView from "./views/FlavorView.svelte";
  import SequenceView from "./views/SequenceView.svelte";

  // The catalog: ?catalog=<url> on the page, else VITE_CATALOG_URL at build
  // time, else /catalog/ (the dev server's copy of the repository's build).
  const catalogUrl = new URLSearchParams(location.search).get("catalog") ?? import.meta.env.VITE_CATALOG_URL ?? "/catalog/";

  const opened = (async () => {
    await init();
    return measure("open catalog", () => Catalog.open(catalogUrl));
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
  <a class="brand" href="#/">refbook</a>
  <span class="tagline">Genome: get the book, in any edition.</span>
  <nav>
    <a href="#/" class:here={!parts.length || parts[0] === "flavor" || parts[0] === "design"}>Catalog</a>
    <a href="#/identify" class:here={parts[0] === "identify"}>Identify</a>
    <a href="#/compare" class:here={parts[0] === "compare"}>Compare</a>
  </nav>
</header>
<main>
  {#await opened}
    <p class="muted">Loading the catalog…</p>
  {:then cat}
    {#key route.current}
      {#if parts[0] === "flavor" && parts[2] === "seq" && parts[3]}
        <SequenceView {cat} blocks={() => openBlocks(cat)} label={parts[1]} name={parts[3]} query={route.current.query} />
      {:else if parts[0] === "identify"}
        <IdentifyView {cat} />
      {:else if parts[0] === "compare"}
        <CompareView {cat} query={route.current.query} />
      {:else if parts[0] === "flavor" && parts[1]}
        <FlavorView {cat} label={parts[1]} />
      {:else}
        <!-- The catalog and the recipe editor are one page; #/design is its old address. -->
        <DesignView {cat} query={route.current.query} />
      {/if}
    {/key}
  {:catch e}
    <ErrorBox error={e} />
    <p class="muted">Catalog: {catalogUrl}</p>
  {/await}
</main>
{#if total.requests}
  <footer class="meter" aria-live="polite">
    <span class="total">Downloaded this session: {total.requests} requests, {bytes(total.bytes)}</span>
    <ul>
      {#each log as { action, t }, i (i)}
        <li><span class="action">{action}</span> {t.requests} req, {bytes(t.bytes)}, {t.ms.toFixed(0)} ms</li>
      {/each}
    </ul>
  </footer>
{/if}
