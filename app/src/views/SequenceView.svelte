<script lang="ts">
  // A stored sequence, by its digest (#/catalog/sequences/<SQ.>) or by its name in an edition (…/edition/<label>/seq/<name>,
  // a lookup: the same page, with the edition kept in the crumbs). The same digest is the same bases, so this is the
  // one page for them: its digests and how it is made, an overview of the whole sequence (its runs of N, what the
  // operations change, where the view is) above a scroller of its bases, built in the browser from the root's bases
  // and the operations, with what they changed marked, and every edition that has it, under which name.
  // Coordinates are shown 1-based, inclusive, as genome browsers show them; the URL keeps them 0-based, half-open
  // (?start=&end=), and follows the view.
  import type { Blocks } from "../data/blocks.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { bookHref, bookOf, editionHref, sequenceHref, sequencesHref, type Book } from "../data/books.ts";
  import { IUPAC_TO_N, ORIENT, PAD, manifest, onSequence, OPERATION_LABELS, padding, region, rootWindow, spans,
           type ManifestRow } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { storedSequence } from "../data/sequences.ts";
  import { bp, n, ncbiUrl } from "../format.ts";
  import BaseScroller from "../components/BaseScroller.svelte";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Icon from "../components/Icon.svelte";
  import Overview from "../components/Overview.svelte";
  import { parseLocus } from "./bases.ts";

  let { cat, blocks, query, sq = null, at = null }: {
    cat: Catalog; blocks: () => Promise<Blocks>; query: URLSearchParams;
    /** The sequence by its digest; or `at`, by its name in an edition. */
    sq?: string | null; at?: { book: Book; label: string; name: string } | null;
  } = $props();

  type Span = [number, number];
  /** A sequence as the page draws it: a manifest row's fields, and the book whose placement pads or orients it. */
  type Row = ManifestRow & { book?: string | null };
  const runs = () => cat.table<{ root_id: string; start: number; end: number }>("layer_n_runs.parquet");

  /** Where to start by default: after a leading run of N (chromosomes begin with telomere gaps; a padded
   * sequence, with its padding). */
  function firstBase(row: Row, gaps: Span[]): number {
    let at = 0;
    for (const [s, e] of gaps) if (s <= at && e > at) at = e;
    return at < row.length ? at : 0;
  }

  /** What the overview draws, in the sequence's coordinates: the runs of N (padding among them), and the spans the
   * operations change. */
  async function tracks(row: Row): Promise<{ gaps: Span[]; changed: Span[] }> {
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

  /** The sequence: the edition's row for its name, or the stored sequence's record; and what the catalog says of it. */
  async function find(): Promise<{ row: Row; stored: NonNullable<Awaited<ReturnType<typeof storedSequence>>> } | null> {
    if (at) {
      const r = (await manifest(cat, at.label)).find((x) => x.name === at!.name);
      if (!r) return null;
      const stored = await storedSequence(cat, r.sha512t24u);
      return stored && { row: { ...r, book: at.book.book }, stored };
    }
    const stored = await storedSequence(cat, sq!);
    if (!stored) return null;
    const { rec } = stored;
    return { row: { edition: "", name: rec.root_id, root_id: rec.root_id, operations: rec.operations, length: rec.length,
                    md5: rec.md5, sha512t24u: rec.sha512t24u, book: rec.book }, stored };
  }

  const loaded = $derived(measure(`sequence ${at ? `${at.label} ${at.name}` : sq}`, async () => {
    const found = await find();
    if (!found) return null;
    const { row, stored } = found;
    const store = await blocks();
    if (!store.hosts(row.root_id)) return { row, stored, store, hosted: false as const };
    const asked = query.has("start") ? Math.max(0, Math.min(row.length - 1, Number(query.get("start")))) : null;
    const t = await tracks(row);
    return { row, stored, store, hosted: true as const, top: asked ?? firstBase(row, t.gaps), ...t };
  }));

  /** The page's own address, which the view's range follows. */
  const here = () => (at ? editionHref(at.label, at.name) : sequenceHref(sq!));
  const title = $derived(at ? at.name : sq!);

  let scroller = $state<BaseScroller>();
  let input = $state<HTMLInputElement>();
  let view = $state<Span>([0, 0]);
  let mark = $state<Span | null>(null);
  let unmasked = $state(false);

  /** The view settled: show its range, and put it in the URL (replacing, not adding to history). */
  function onview(s: number, e: number) {
    view = [s, e];
    if (input && document.activeElement !== input) input.value = `${n(s + 1)}-${n(e)}`;
    history.replaceState(null, "", `${here()}?${new URLSearchParams({ start: String(s), end: String(e) })}`);
  }

  function submit(e: SubmitEvent, row: Row) {
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
  const assemblyOf = (book: string) => bookOf.get(book)?.assembly ?? book;
  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" and ") : "");
</script>

<section>
  {#if at}
    <p class="crumbs"><a href="#/">Home</a> / <a href="#/catalog">Catalog</a> / <a href="#/catalog/books">Books</a> / <a href={bookHref(at.book.book)}>{at.book.assembly}</a> / <a href={editionHref(at.label)}>{at.label}</a> / {at.name}</p>
  {:else}
    <p class="crumbs"><a href="#/">Home</a> / <a href="#/catalog">Catalog</a> / <a href={sequencesHref()}>Sequences</a> / {sq}</p>
  {/if}
  {#await loaded then v}
    {#if !v}
      <h1>No such sequence</h1>
      <p>{at ? `${at.label} has no sequence named ${at.name}.` : `The catalog stores no sequence with the digest ${sq}.`}</p>
    {:else}
      {@const { row, stored } = v}
      <h1>{at ? at.name : row.root_id}</h1>
      <p class="lede">
        {bp(row.length)}, from root <a href={sequencesHref(row.root_id)}><code>{row.root_id}</code></a>{#if ncbiUrl(row.root_id)}{" "}<a class="external" href={ncbiUrl(row.root_id)} target="_blank" rel="noopener" title={`${row.root_id} at NCBI, in a new tab`} aria-label={`${row.root_id} at NCBI`}><Icon name="external" /></a>{/if}{row.operations.length
          ? ` with ${ops(row.operations)}` : " (original)"}{#if row.book && row.operations.some((o) => o === PAD || o === ORIENT)}{" "}(by its placement in {assemblyOf(row.book)}){/if}.
      </p>
      <dl class="ids">
        <dt>MD5</dt><dd><Digest value={row.md5} /></dd>
        <dt><abbr title="GA4GH refget's sequence identifier (sha512t24u)">Refget digest</abbr></dt><dd><Digest value={row.sha512t24u} />{#if at}
          <div class="muted">This page by digest: <a href={sequenceHref(row.sha512t24u)}>{sequenceHref(row.sha512t24u)}</a></div>{/if}</dd>
      </dl>
      {#if !v.hosted}
        <p class="muted">An external root, listed with its digests but not hosted, so its bases aren't shown here.</p>
      {:else}
        {@const { store, top, gaps, changed } = v}
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
                        read={(s, e) => measure(`bases ${title}:${n(s + 1)}-${n(e)}`, () => region(cat, store, row, s, e))}
                        warm={(s, e) => void rootWindow(cat, row, s, e).then(([a, z]) => store.read(row.root_id, a, z)).catch(() => {})} />
        </div>
      {/if}

      <h2>In the editions</h2>
      {#each stored.byBook as [book, uses] (book)}
        <h3>{assemblyOf(book)}</h3>
        <ul class="plain">{#each uses as u (u.edition + u.name)}<li><a href={editionHref(u.edition)}>{u.edition}</a> as <code>{u.name}</code>{#if at && u.edition === at.label && u.name === at.name}{" "}<span class="muted">(this one)</span>{/if}</li>{/each}</ul>
      {:else}
        <p class="muted">No edition has it: it is an original root that every edition changes or leaves out.</p>
      {/each}
      {#if stored.ways.length > 1}
        <h2>Ways to make it</h2>
        <ul>{#each stored.ways as w (w.root_id + w.operations.join() + (w.book ?? ""))}<li>{w.root_id}{w.operations.length ? `, with ${ops(w.operations)}` : " (original)"}{#if w.book} ({assemblyOf(w.book)}){/if}</li>{/each}</ul>
      {/if}
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
