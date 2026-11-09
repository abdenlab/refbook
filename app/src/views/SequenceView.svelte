<script lang="ts">
  // One sequence of an edition, base by base: an overview of the whole sequence
  // (its runs of N, what the operations change, where the view is) above a
  // scroller of its bases, built in the browser from the root's bases and the
  // edition's operations, with what the operations changed marked. Coordinates
  // are shown 1-based, inclusive, as genome browsers show them; the URL keeps
  // them 0-based, half-open (?start=&end=), and follows the view.
  import type { Blocks } from "../data/blocks.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { bookHref, editionHref, type Book } from "../data/books.ts";
  import { IUPAC_TO_N, ORIENT, PAD, manifest, onSequence, OPERATION_LABELS, padding, region, rootWindow, spans,
           type ManifestRow } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { bp, n } from "../format.ts";
  import BaseScroller from "../components/BaseScroller.svelte";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Overview from "../components/Overview.svelte";
  import { parseLocus } from "./bases.ts";

  let { cat, blocks, book, label, name, query }: {
    cat: Catalog; blocks: () => Promise<Blocks>; book: Book; label: string; name: string; query: URLSearchParams;
  } = $props();

  type Span = [number, number];
  const runs = () => cat.table<{ root_id: string; start: number; end: number }>("layer_n_runs.parquet");

  /** Where to start by default: after a leading run of N (chromosomes begin with telomere gaps; a padded
   * sequence, with its padding). */
  function firstBase(row: ManifestRow, gaps: Span[]): number {
    let at = 0;
    for (const [s, e] of gaps) if (s <= at && e > at) at = e;
    return at < row.length ? at : 0;
  }

  /** What the overview draws, in the sequence's coordinates: the runs of N (padding among them), and the spans the
   * edition's operations change. */
  async function tracks(row: ManifestRow): Promise<{ gaps: Span[]; changed: Span[] }> {
    const p = await padding(cat, row);
    const gaps = (await runs()).filter((r) => r.root_id === row.root_id).map((r) => onSequence(p, [r.start, r.end]));
    if (p) gaps.push([0, p.before], [p.before + p.root_length, row.length]);
    const changed: Span[] = [];
    for (const op of row.operations) {
      if (op === PAD || op === ORIENT) continue;
      if (op === IUPAC_TO_N) {
        const codes = await cat.table<{ root_id: string; pos: number }>("layer_iupac.parquet");
        changed.push(...codes.filter((c) => c.root_id === row.root_id).map((c) => onSequence(p, [c.pos, c.pos + 1])));
      } else changed.push(...(await spans(cat, op, row.root_id)).map((s) => onSequence(p, s)));
    }
    const sorted = (xs: Span[]) => xs.filter(([s, e]) => e > s).sort((a, b) => a[0] - b[0]);
    return { gaps: sorted(gaps), changed: sorted(changed) };
  }

  const loaded = $derived((async () => {
    const row = (await manifest(cat, label)).find((r) => r.name === name);
    if (!row) return null;
    const store = await blocks();
    if (!store.hosts(row.root_id)) return { row, store, hosted: false as const };
    const asked = query.has("start") ? Math.max(0, Math.min(row.length - 1, Number(query.get("start")))) : null;
    const t = await tracks(row);
    return { row, store, hosted: true as const, top: asked ?? firstBase(row, t.gaps), ...t };
  })());

  let scroller = $state<BaseScroller>();
  let input = $state<HTMLInputElement>();
  let view = $state<Span>([0, 0]);
  let mark = $state<Span | null>(null);
  let unmasked = $state(false);

  /** The view settled: show its range, and put it in the URL (replacing, not adding to history). */
  function onview(s: number, e: number) {
    view = [s, e];
    if (input && document.activeElement !== input) input.value = `${n(s + 1)}-${n(e)}`;
    history.replaceState(null, "", `${editionHref(label, name)}?${new URLSearchParams({ start: String(s), end: String(e) })}`);
  }

  function submit(e: SubmitEvent, row: ManifestRow) {
    e.preventDefault();
    const r = parseLocus(input!.value, row.length);
    if (r) {
      mark = r;
      scroller?.jump(r[0]);
      input!.blur();
    } else {
      input!.setCustomValidity(`A region within 1-${n(row.length)}, e.g. 1,000,001-1,001,200`);
      input!.reportValidity();
    }
  }

  /** Centre the view on a position, as the overview asks. */
  const centre = (pos: number) => scroller?.jump(Math.max(0, pos - Math.floor((view[1] - view[0]) / 2)));
</script>

<section>
  <p class="crumbs"><a href="#/">Home</a> / <a href="#/catalog">Catalog</a> / <a href={bookHref(book.book)}>{book.assembly}</a> / <a href={editionHref(label)}>{label}</a> / {name}</p>
  {#await loaded then v}
    {#if !v}
      <h1>No such sequence</h1>
    {:else if !v.hosted}
      <h1>{name}</h1>
      <p class="lede">{bp(v.row.length)}, from root <code>{v.row.root_id}</code>: an external root, listed with its digests but not hosted, so its bases aren't shown here.</p>
      <dl class="ids">
        <dt>MD5</dt><dd><Digest value={v.row.md5} /></dd>
        <dt><abbr title="GA4GH refget's sequence identifier (sha512t24u)">Refget digest</abbr></dt><dd><Digest value={v.row.sha512t24u} /></dd>
      </dl>
    {:else}
      {@const { row, store, top, gaps, changed } = v}
      <h1>{name}</h1>
      <p class="lede">
        {bp(row.length)}, from root <code>{row.root_id}</code>{row.operations.length
          ? ` with ${row.operations.map((o) => OPERATION_LABELS[o] ?? o).join(" and ")}` : ", as submitted"}.
      </p>
      <dl class="ids">
        <dt>MD5</dt><dd><Digest value={row.md5} /></dd>
        <dt><abbr title="GA4GH refget's sequence identifier (sha512t24u)">Refget digest</abbr></dt><dd><Digest value={row.sha512t24u} /></dd>
      </dl>
      <form class="controls" onsubmit={(e) => submit(e, row)}>
        <input class="locus" name="locus" bind:this={input} aria-label="Region, 1-based inclusive"
               oninput={(e) => e.currentTarget.setCustomValidity("")} />
        <button type="submit">Go</button>
      </form>
      <Overview length={row.length} {gaps} {changed} {view} onjump={centre} />
      <p class="legend">
        Hard masked bases shown as {#if row.operations.length} &nbsp;<span class="changed">N</span>.
          <label class="unmask"><input type="checkbox" bind:checked={unmasked} /> unmask</label>{/if}
      </p>
      <div class="view">
        <BaseScroller bind:this={scroller} length={row.length} {top} {mark} submitted={unmasked} {onview} onmove={(s, e) => (view = [s, e])}
                      read={(s, e) => measure(`bases ${name}:${n(s + 1)}-${n(e)}`, () => region(cat, store, row, s, e))}
                      warm={(s, e) => void rootWindow(cat, row, s, e).then(([a, z]) => store.read(row.root_id, a, z)).catch(() => {})} />
      </div>
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
