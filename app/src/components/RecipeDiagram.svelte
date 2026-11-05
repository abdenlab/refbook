<script lang="ts">
  // A recipe as four cards: roots selected → operations → names → the flavor.
  import type { Flavor, ManifestRow } from "../data/flavors.ts";
  import { OPERATION_LABELS } from "../data/flavors.ts";
  import { bp, n } from "../format.ts";
  import { role, type Recipe } from "../views/recipe.ts";

  let { flavor: f, recipe, rows, names }: { flavor: Flavor; recipe: Recipe; rows: ManifestRow[]; names: Map<string, string> } = $props();

  const affected = (op: string) => rows.filter((r) => r.operations.includes(op)).length;
  const r = $derived(recipe.rename);
</script>

<div class="recipe">
  <div class="card">
    <h3>Select</h3>
    {#each recipe.select as e, i (i)}
      <div class="entry">
        {#if "assembly" in e}
          <div><strong>{names.get(e.assembly) ?? e.assembly}</strong> <code>{e.assembly}</code></div>
          <div>{e.roles.map(role).join(", ")}</div>
          {#if e.placed_on}<div class="muted">only those placed on: {e.placed_on.join(", ")}</div>{/if}
          {#if e.accessions}<div class="muted">only {e.accessions.join(", ")}</div>{/if}
        {:else if "roots" in e}
          <strong>Roots in no assembly</strong>
          <div>{#each e.roots as root (root)}<code>{root} </code>{/each}</div>
        {:else}
          <strong>{e.collection}</strong>
          <div>groups {e.groups.join(", ")}</div>
          <div class="muted">external roots: listed, not hosted</div>
        {/if}
      </div>
    {/each}
  </div>
  <div class="arrow" aria-hidden="true">→</div>
  <div class="card">
    <h3>Operations</h3>
    {#each f.operations as op (op)}
      <div class="entry"><strong>{OPERATION_LABELS[op] ?? op}</strong><div>changes {n(affected(op))} of {n(rows.length)} sequences</div></div>
    {:else}
      <div class="muted entry">None: the roots' bases as submitted</div>
    {/each}
  </div>
  <div class="arrow" aria-hidden="true">→</div>
  <div class="card">
    <h3>Rename</h3>
    <div class="entry">Default: <strong>{r.namespace}</strong> names</div>
    {#each Object.entries(r.by_role ?? {}) as [k, v] (k)}<div class="entry">{role(k)}: <strong>{v}</strong> names</div>{/each}
    {#each Object.entries(r.template ?? {}) as [k, v] (k)}<div class="entry">{names.get(k) ?? k}: <code>{v}</code></div>{/each}
    {#each Object.entries(r.map ?? {}) as [k, v] (k)}<div class="entry"><code>{k}</code> → <code>{v}</code></div>{/each}
  </div>
  <div class="arrow" aria-hidden="true">→</div>
  <div class="card">
    <h3>Flavor</h3>
    <div class="entry"><strong>{n(f.n_sequences)} sequences</strong><div>{bp(f.total_length)}</div></div>
    <ul class="plain">{#each f.contents as c (c.kind)}<li>{n(c.count)} {role(c.kind)}</li>{/each}</ul>
    {#if f.excluded.length}<div class="muted">Left out: {f.excluded.join("; ")}</div>{/if}
  </div>
</div>
