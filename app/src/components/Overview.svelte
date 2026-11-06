<script lang="ts">
  // The whole sequence as one bar: its runs of N, what the flavor's
  // operations change, and where the view is. Click or drag to go anywhere.
  import { n } from "../format.ts";

  let { length, gaps, changed, view, onjump }: {
    length: number;
    gaps: [number, number][];
    changed: [number, number][];
    view: [number, number];
    /** Go to a position (0-based): the view centred on it. */
    onjump: (pos: number) => void;
  } = $props();

  const H = 22;
  let width = $state(0);
  let dragging = false;
  const x = (pos: number) => (pos / length) * width;
  const w = (s: number, e: number) => Math.max(1, x(e) - x(s));

  /** Round positions to mark: a step of 1, 2 or 5 × 10^k giving at most about eight. */
  const ticks = $derived.by(() => {
    const raw = length / 8;
    const p = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw)!;
    const out: number[] = [];
    for (let t = step; t < length - step / 3; t += step) out.push(t);
    return { step, out };
  });
  const label = (t: number) => (ticks.step >= 1e6 ? `${n(t / 1e6)} Mb` : ticks.step >= 1e3 ? `${n(t / 1e3)} kb` : n(t));

  function at(e: PointerEvent) {
    const r = (e.currentTarget as SVGElement).getBoundingClientRect();
    onjump(Math.round(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * (length - 1)));
  }
</script>

<div class="overview" bind:clientWidth={width}>
  {#if width}
    <svg width={width} height={H + 16} role="slider" tabindex="-1" aria-label="Position in the sequence" aria-valuemin={1} aria-valuemax={length} aria-valuenow={view[0] + 1}
         onpointerdown={(e) => { dragging = true; (e.currentTarget as SVGElement).setPointerCapture(e.pointerId); at(e); }}
         onpointermove={(e) => dragging && at(e)}
         onpointerup={() => (dragging = false)} onpointercancel={() => (dragging = false)}>
      <rect class="track" x="0" y="0" width={width} height={H} rx="3" />
      {#each gaps as [s, e] (s)}<rect class="gap" x={x(s)} y="0" width={w(s, e)} height={H} />{/each}
      {#each changed as [s, e] (s)}<rect class="changed" x={x(s)} y="0" width={w(s, e)} height={H} />{/each}
      <rect class="here" x={Math.min(x(view[0]), width - 3)} y="-0.5" width={Math.max(3, x(view[1]) - x(view[0]))} height={H + 1} rx="1" />
      {#each ticks.out as t (t)}
        <line class="tick" x1={x(t)} x2={x(t)} y1={H} y2={H + 4} />
        <text class="tick" x={x(t)} y={H + 14} text-anchor="middle">{label(t)}</text>
      {/each}
    </svg>
  {/if}
</div>
