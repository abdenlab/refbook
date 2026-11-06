<script lang="ts">
  // A sequence's bases, 60 to a line, scrolled natively over a window of a few
  // Mb that moves along as the view nears its edge (a whole chromosome is too
  // tall to scroll as one element). Only the lines in view are drawn. Bases are
  // read when scrolling settles, with a margin either side, and the next stretch
  // ahead is read too, so slow scrolling never waits; the block store caches
  // what it read, so memory stays bounded.
  import { onMount, untrack } from "svelte";
  import { n } from "../format.ts";
  import { LINE, lines, type Line } from "../views/bases.ts";

  let { length, read, warm, top = 0, mark = null, submitted = false, onview, onmove }: {
    length: number;
    /** The edition's bases and the root's at [start, end). */
    read: (start: number, end: number) => Promise<{ bases: Uint8Array; root: Uint8Array }>;
    /** Read ahead into the block store's cache, nothing kept here. */
    warm: (start: number, end: number) => void;
    /** Where to open (0-based). */
    top?: number;
    /** A region to mark (0-based, half-open), as typed. */
    mark?: [number, number] | null;
    /** Show the root's bases where the operations changed them (still marked as changed). */
    submitted?: boolean;
    /** The bases in view (0-based, half-open), once scrolling settles. */
    onview: (start: number, end: number) => void;
    /** The bases in view as it moves, at most once a frame. */
    onmove?: (start: number, end: number) => void;
  } = $props();

  const LH = 20;            // px a line, as the CSS sets it
  const WINDOW = 60_000;    // lines in the scrolled window: 3.6 Mb, 1.2 M px
  const OVER = 30;          // lines drawn beyond the view
  const MARGIN = 1500;      // lines read beyond the view (90 kb)
  const AHEAD = 2 ** 21;    // bases warmed ahead: one row group of the block store
  const SETTLE = 150;       // ms without scrolling before reading

  // A sequence per page: its length and where it opens are fixed for this scroller.
  const total = untrack(() => Math.ceil(length / LINE));
  const span = Math.min(WINDOW, total);
  const clamp = (line: number) => Math.max(0, Math.min(total - span, line));

  let el: HTMLDivElement;
  let w0 = $state(clamp(Math.floor(untrack(() => top) / LINE) - span / 2));
  let scrollTop = $state(0);
  let height = $state(0);
  let data = $state<{ first: number; lines: Line[] } | null>(null);
  let token = 0, timer: ReturnType<typeof setTimeout> | undefined, last = 0, direction = 1, frame = 0;

  const first = $derived(w0 + Math.floor(scrollTop / LH));
  const count = $derived(Math.ceil(height / LH) + 1);
  const drawn = $derived.by(() => {
    const a = Math.max(w0, first - OVER), b = Math.min(w0 + span, first + count + OVER);
    return Array.from({ length: Math.max(0, b - a) }, (_, i) => a + i);
  });
  const gutter = untrack(() => n(length).length);

  /** Scroll so a line is at the top, moving the window if it's outside. */
  function place(line: number) {
    if (line < w0 || line >= w0 + span - count) w0 = clamp(line - span / 2);
    el.scrollTop = scrollTop = (line - w0) * LH;
    settle();
  }

  /** Go to a position (0-based): its line at the top. */
  export function jump(pos: number) { place(Math.floor(Math.max(0, Math.min(length - 1, pos)) / LINE)); }

  function onscroll() {
    scrollTop = el.scrollTop;
    const line = w0 + Math.floor(scrollTop / LH);
    direction = line >= last ? 1 : -1;
    last = line;
    // Near an edge of the window, and more beyond it: move the window, keep the view.
    const edge = span * 0.15;
    if ((line - w0 < edge && w0 > 0) || (w0 + span - line - count < edge && w0 + span < total)) {
      const next = clamp(line - span / 2);
      el.scrollTop = scrollTop = scrollTop + (w0 - next) * LH;
      w0 = next;
    }
    settle();
  }

  /** Where the view is now, by line (it can't wait for scrolling to settle). */
  const inView = (): [number, number] => {
    const a = w0 + Math.floor(el.scrollTop / LH);
    return [a * LINE, Math.min(length, (a + Math.ceil(el.clientHeight / LH)) * LINE)];
  };

  function settle() {
    if (onmove && !frame) frame = requestAnimationFrame(() => { frame = 0; onmove(...inView()); });
    clearTimeout(timer);
    timer = setTimeout(fetch, SETTLE);
  }

  async function fetch() {
    const a = first, b = Math.min(total, first + count);
    onview(a * LINE, Math.min(length, b * LINE));
    const have = data && data.first <= a - OVER && data.first + data.lines.length >= b + OVER;
    if (have) return;
    const s = Math.max(0, a - MARGIN), e = Math.min(total, b + MARGIN);
    const mine = ++token;
    const r = await read(s * LINE, Math.min(length, e * LINE));
    if (mine !== token) return;  // scrolled on since: a later read wins
    data = { first: s, lines: lines(s * LINE, r.bases, r.root) };
    const ahead = direction > 0 ? Math.min(length, e * LINE) : Math.max(0, s * LINE - AHEAD);
    if (direction > 0 ? ahead < length : s > 0) warm(ahead, Math.min(length, ahead + AHEAD));
  }

  onMount(() => {
    place(Math.floor(Math.min(length - 1, top) / LINE));
    return () => { clearTimeout(timer); cancelAnimationFrame(frame); };
  });

  const lineAt = (k: number) => (data && k >= data.first && k < data.first + data.lines.length ? data.lines[k - data.first] : null);
  const marked = (k: number) => !!mark && k * LINE < mark[1] && (k + 1) * LINE > mark[0];
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex: a scrolled region is focusable, so keys scroll it -->
<div class="scroller" bind:this={el} bind:clientHeight={height} {onscroll} tabindex="0" role="region" aria-label="Bases" style:--lh={`${LH}px`}>
  <div class="spacer" style:height={`${span * LH}px`}>
    <pre class="bases" style:transform={`translateY(${((drawn[0] ?? w0) - w0) * LH}px)`}>{#each drawn as k (k)}{@const line = lineAt(k)}<div class="line" class:mark={marked(k)}><span class="pos">{n(k * LINE + 1).padStart(gutter)}</span> {#if line}{#each line.segments as s, i (i)}{#if s.kind}<span class={s.kind}>{submitted && s.submitted !== undefined ? s.submitted : s.text}</span>{:else}{s.text}{/if}{/each}{:else}<span class="pending">{"·".repeat(Math.min(LINE, length - k * LINE))}</span>{/if}</div>{/each}</pre>
  </div>
</div>
