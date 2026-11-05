<script lang="ts">
  // A flavor's sequences, filterable by name or root; the first 500 shown.
  import type { ManifestRow } from "../data/flavors.ts";
  import { OPERATION_LABELS } from "../data/flavors.ts";
  import { n } from "../format.ts";
  import { href } from "../route.svelte.ts";

  const LIMIT = 500;
  let { flavor, rows }: { flavor: string; rows: ManifestRow[] } = $props();
  let q = $state("");

  const shown = $derived.by(() => {
    const t = q.trim().toLowerCase();
    return rows.filter((r) => !t || r.name.toLowerCase().includes(t) || r.root_id.toLowerCase().includes(t));
  });
</script>

<div>
  <input type="search" placeholder="Filter by name or root" class="filter" aria-label="Filter sequences" bind:value={q} />
  <div class="table-wrap">
    <table>
      <thead><tr><th>Name</th><th>Root</th><th>Operations</th><th class="num">Length</th><th>MD5</th></tr></thead>
      <tbody>
        {#each shown.slice(0, LIMIT) as r (r.name)}
          <tr>
            <td><a href={href("flavor", flavor, "seq", r.name)}>{r.name}</a></td>
            <td><code>{r.root_id}</code></td>
            <td>{#each r.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{/each}</td>
            <td class="num">{n(r.length)}</td>
            <td><code class="small">{r.md5}</code></td>
          </tr>
        {/each}
        {#if shown.length > LIMIT}
          <tr><td colspan="5" class="muted">and {n(shown.length - LIMIT)} more: filter to find them</td></tr>
        {/if}
      </tbody>
    </table>
  </div>
</div>
