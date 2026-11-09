<script lang="ts">
  // A recipe as four cards: roots selected → operations → names → the edition.
  import type { Edition, ManifestRow } from "../data/editions.ts";
  import { OPERATION_LABELS } from "../data/editions.ts";
  import { bp, n } from "../format.ts";
  import { role, type Recipe } from "../views/recipe.ts";

  let { edition: f, recipe, rows, names }: { edition: Edition; recipe: Recipe; rows: ManifestRow[]; names: Map<string, string> } = $props();

  const affected = (op: string) => rows.filter((r) => r.operations.includes(op)).length;
  const r = $derived(recipe.rename);
  const mapped = $derived(Object.entries(r.map ?? {}));
  /** Lists longer than this collapse to a summary; the names open below the diagram, at its full width. */
  const INLINE = 3;
  let showNames = $state(false);
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
          {#if e.accessions && e.accessions.length <= INLINE}<div class="muted">only {e.accessions.join(", ")}</div>
          {:else if e.accessions}
            <details class="long"><summary class="muted">only {n(e.accessions.length)} of them, by accession</summary>
              <div class="list">{#each e.accessions as a (a)}<code>{a}</code> {/each}</div></details>
          {/if}
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
    {#if mapped.length <= INLINE}
      {#each mapped as [k, v] (k)}<div class="entry"><code>{k}</code> → <code>{v}</code></div>{/each}
    {:else}
      <div class="entry">{n(mapped.length)} names set one by one
        <button type="button" class="link" aria-expanded={showNames} onclick={() => (showNames = !showNames)}>{showNames ? "hide" : "show"}</button></div>
    {/if}
  </div>
  <div class="arrow" aria-hidden="true">→</div>
  <div class="card">
    <h3>Edition</h3>
    <div class="entry"><strong>{n(f.n_sequences)} sequences</strong><div>{bp(f.total_length)}</div></div>
    <ul class="plain">{#each f.contents as c (c.kind)}<li>{n(c.count)} {role(c.kind)}</li>{/each}</ul>
    {#if f.excluded.length}<div class="muted">Left out: {f.excluded.join("; ")}</div>{/if}
  </div>
</div>
{#if showNames && mapped.length > INLINE}
  <div class="names" aria-label="Names set one by one">
    {#each mapped as [k, v] (k)}<div class="pair"><code class="k">{k}</code> <span class="muted">→</span> <code>{v}</code></div>{/each}
  </div>
{/if}

<style>
  .long summary { cursor: pointer; }
  .long .list { max-height: 12rem; overflow: auto; margin-top: 0.4rem; padding-right: 0.3rem; font-size: 0.85rem; overflow-wrap: anywhere; }
  .link { border: none; background: none; padding: 0; color: var(--accent); cursor: pointer; font: inherit; }
  .link:hover { text-decoration: underline; }
  .names { columns: 20rem; column-gap: 2rem; margin-top: 0.6rem; padding: 0.8rem 1rem; font-size: 0.85rem;
           background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
  .names .pair { break-inside: avoid; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .names code { font-size: 0.8rem; }
</style>
