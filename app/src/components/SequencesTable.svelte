<script lang="ts">
  // An edition's sequences, in a chosen order (the caller sorts them), with each
  // one's place in it; filterable by name or root. All of them scroll in a
  // box of fixed height, and only the rows in view are drawn (rows are of one
  // height, columns of fixed widths, so nothing shifts as rows come and go).
  import type { Place } from "../data/exports.ts";
  import type { ManifestRow } from "../data/editions.ts";
  import { OPERATION_LABELS } from "../data/editions.ts";
  import { n } from "../format.ts";
  import { editionHref } from "../data/books.ts";
  import Icon from "./Icon.svelte";

  let { edition, rows, places, orders, order = $bindable() }: {
    edition: string; rows: ManifestRow[];
    /** Each root's assembly role and unit, or its collection. */
    places: Map<string, Place> | null;
    /** The orders offered: [value, label]. */
    orders: [string, string][];
    order: string;
  } = $props();
  let q = $state("");

  const ROW = 36;   // px a row, as the CSS sets it
  const OVER = 10;  // rows drawn beyond the view
  let box = $state<HTMLDivElement>();
  let scrollTop = $state(0);
  let height = $state(0);

  const shown = $derived.by(() => {
    const t = q.trim().toLowerCase();
    return rows.map((r, i) => ({ r, i })).filter(({ r }) => !t || r.name.toLowerCase().includes(t) || r.root_id.toLowerCase().includes(t));
  });
  // The header row takes one row's height at the top of the box.
  const from = $derived(Math.max(0, Math.floor(scrollTop / ROW) - 1 - OVER));
  const to = $derived(Math.min(shown.length, Math.ceil((scrollTop + height) / ROW) + OVER));

  // A new filter or order starts at the top.
  $effect(() => {
    void shown;
    if (box) box.scrollTop = scrollTop = 0;
  });
</script>

<div>
  <div class="table-controls">
    <input type="search" placeholder="Filter by name or root" class="filter" aria-label="Filter sequences" bind:value={q} />
    <label class="order" title="The order of the sequences">
      <Icon name="sort" />
      <select aria-label="Order" bind:value={order}>
        {#each orders as [k, label] (k)}<option value={k}>{label}</option>{/each}
      </select>
    </label>
    <span class="muted small">{q.trim() ? `${n(shown.length)} of ${n(rows.length)}` : n(rows.length)} sequences</span>
  </div>
  <div class="table-wrap seqs" bind:this={box} bind:clientHeight={height} onscroll={() => (scrollTop = box!.scrollTop)} style:--row={`${ROW}px`}>
    <table>
      <colgroup>
        <col class="c-i" /><col class="c-name" /><col class="c-role" /><col class="c-unit" /><col class="c-root" /><col class="c-ops" /><col class="c-len" />
      </colgroup>
      <thead><tr><th class="num">#</th><th>Name</th><th>Role</th><th>Unit</th><th>Root</th><th>Operations</th><th class="num">Length</th></tr></thead>
      <tbody>
        {#if from > 0}<tr class="pad" style:height={`${from * ROW}px`}><td colspan="7"></td></tr>{/if}
        {#each shown.slice(from, to) as { r, i } (r.name)}
          {@const p = places?.get(r.root_id)}
          <tr>
            <td class="num muted">{n(i + 1)}</td>
            <td title={r.name}><a href={editionHref(edition, r.name)}>{r.name}</a></td>
            {#if p && "role" in p}
              <td>{p.role}</td>
              <td>{p.unit}{#if !p.primary}{" "}<span class="muted">({p.assembly})</span>{/if}</td>
            {:else if p}
              <td class="muted">—</td><td class="muted" title={p.collection}>{p.collection}</td>
            {:else}
              <td class="muted">—</td><td class="muted">—</td>
            {/if}
            <td title={r.root_id}><code>{r.root_id}</code></td>
            <td>{#each r.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{/each}</td>
            <td class="num">{n(r.length)}</td>
          </tr>
        {/each}
        {#if to < shown.length}<tr class="pad" style:height={`${(shown.length - to) * ROW}px`}><td colspan="7"></td></tr>{/if}
        {#if !shown.length}<tr><td colspan="7" class="muted">No sequence matches.</td></tr>{/if}
      </tbody>
    </table>
  </div>
</div>
