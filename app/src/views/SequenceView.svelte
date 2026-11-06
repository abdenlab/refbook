<script lang="ts">
  // A region of one sequence of a flavor: its bases, built in the browser from
  // the root's bases and the flavor's operations, with what the operations
  // changed marked. Coordinates are shown 1-based, inclusive, as genome
  // browsers show them.
  import type { Blocks } from "../data/blocks.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { manifest, OPERATION_LABELS, region, verify, type ManifestRow } from "../data/flavors.ts";
  import { measure } from "../data/meter.ts";
  import { bp, message, n } from "../format.ts";
  import { href } from "../route.svelte.ts";
  import Bases from "../components/Bases.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import { parseLocus } from "./bases.ts";

  const WIDTHS = [600, 1200, 6000];

  let { cat, blocks, label, name, query }: {
    cat: Catalog; blocks: () => Promise<Blocks>; label: string; name: string; query: URLSearchParams;
  } = $props();

  /** Where to start by default: after a leading run of N (chromosomes begin with telomere gaps). */
  async function firstBase(row: ManifestRow): Promise<number> {
    const runs = await cat.table<{ root_id: string; start: number; end: number }>("layer_n_runs.parquet");
    const lead = runs.find((r) => r.root_id === row.root_id && r.start === 0);
    return lead && lead.end < row.length ? lead.end : 0;
  }

  const loaded = $derived((async () => {
    const row = (await manifest(cat, label)).find((r) => r.name === name);
    if (!row) return null;
    const store = await blocks();
    if (!store.hosts(row.root_id)) return { row, store, hosted: false, start: 0, end: 0, width: 0 };
    const width = WIDTHS.includes(Number(query.get("width"))) ? Number(query.get("width")) : 1200;
    let start = query.has("start") ? Math.max(0, Number(query.get("start"))) : await firstBase(row);
    start = Math.min(start, Math.max(0, row.length - 1));
    const end = Math.min(row.length, query.has("end") ? Number(query.get("end")) : start + width);
    return { row, store, hosted: true, start, end, width };
  })());

  function go(row: ManifestRow, s: number, e: number, w: number) {
    const p = new URLSearchParams({ start: String(Math.max(0, s)), end: String(Math.min(row.length, e)), width: String(w) });
    location.hash = `${href("flavor", label, "seq", name)}?${p}`;
  }

  function submit(e: SubmitEvent, row: ManifestRow, width: number) {
    e.preventDefault();
    const input = (e.currentTarget as HTMLFormElement).elements.namedItem("locus") as HTMLInputElement;
    const r = parseLocus(input.value, row.length);
    if (r) go(row, r[0], r[1], width);
    else {
      input.setCustomValidity(`A region within 1-${n(row.length)}, e.g. ${name}:1,000,001-1,001,200`);
      input.reportValidity();
    }
  }

  let checking = $state(false);
  let checked = $state<{ text: string; cls: string } | null>(null);
  async function check(store: Blocks, row: ManifestRow) {
    checking = true;
    checked = { text: ` building ${bp(row.length, true)}…`, cls: "muted" };
    try {
      const ok = await measure(`check ${name}`, () => verify(cat, store, row));
      checked = ok ? { text: " ✓ matches its MD5 and SQ. digest", cls: "ok" } : { text: " ✗ does not match its digests", cls: "bad" };
    } catch (e) {
      checked = { text: ` ${message(e)}`, cls: "muted" };
    } finally {
      checking = false;
    }
  }
</script>

<section>
  <p class="crumbs"><a href="#/catalog">Catalog</a> / <a href={href("flavor", label)}>{label}</a> / {name}</p>
  {#await loaded then v}
    {#if !v}
      <h1>No such sequence</h1>
    {:else if !v.hosted}
      <h1>{name}</h1>
      <p>{v.row.root_id} is an external root: refbook lists it with its digests, but does not host its bases.</p>
    {:else}
      {@const { row, store, start, end, width } = v}
      {@const span = end - start}
      <h1>{name}</h1>
      <p class="lede">
        {bp(row.length)}, from root <code>{row.root_id}</code>{row.operations.length
          ? ` with ${row.operations.map((o) => OPERATION_LABELS[o] ?? o).join(" and ")}` : ", as submitted"}.
      </p>
      <form class="controls" onsubmit={(e) => submit(e, row, width)}>
        <button type="button" onclick={() => go(row, start - span, start, width)} disabled={start === 0}>←</button>
        <input class="locus" name="locus" value={`${name}:${n(start + 1)}-${n(end)}`} aria-label="Region, 1-based inclusive"
               oninput={(e) => e.currentTarget.setCustomValidity("")} />
        <button type="submit">Go</button>
        <button type="button" onclick={() => go(row, end, end + span, width)} disabled={end >= row.length}>→</button>
        <select aria-label="Bases shown" value={width}
                onchange={(e) => { const w = Number(e.currentTarget.value); go(row, start, start + w, w); }}>
          {#each WIDTHS as w (w)}<option value={w}>{n(w)} bp</option>{/each}
        </select>
      </form>
      {#if row.operations.length}
        <p class="legend"><span class="changed">ACGT</span> changed by the operations (hover for the bases as submitted) &nbsp;<span class="n">N</span> unknown</p>
      {/if}
      <div class="view">
        {#await measure(`view ${name}:${start + 1}-${end}`, () => region(cat, store, row, start, end))}
          <p class="muted">Reading bases…</p>
        {:then r}
          <Bases {start} bases={r.bases} root={r.root} />
        {:catch e}
          <ErrorBox error={e} />
        {/await}
      </div>
      <p>
        <button type="button" onclick={() => check(store, row)} disabled={checking}>Check the whole sequence</button>
        {#if checked}<span class={checked.cls}>{checked.text}</span>{/if}
      </p>
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
