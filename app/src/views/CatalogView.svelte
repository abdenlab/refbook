<script lang="ts">
  // The catalog: every flavor, what it holds, and the files that reproduce it.
  import type { Catalog } from "../data/catalog.ts";
  import { flavors, OPERATION_LABELS, targets } from "../data/flavors.ts";
  import { measure } from "../data/meter.ts";
  import { bp, n } from "../format.ts";
  import { href } from "../route.svelte.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat }: { cat: Catalog } = $props();

  const loaded = measure("catalog", async () => {
    const [fs, ts] = await Promise.all([flavors(cat), targets(cat)]);
    const byFlavor = Map.groupBy(ts, (t) => t.flavor);
    const rows = [...fs].sort((a, b) => a.n_sequences - b.n_sequences || a.flavor.localeCompare(b.flavor));
    return { rows, byFlavor, nFiles: ts.length };
  });
</script>

{#await loaded then { rows, byFlavor, nFiles }}
  <section>
    <h1>GRCh38, as published</h1>
    <p class="lede">
      "GRCh38" names many different files. They include different sequences, name and order them differently, and some mask or rewrite bases.
      refbook describes each as a recipe over the same original INSDC sequences, and checks it by rebuilding the published file.
      The {n(nFiles)} files below reduce to {n(rows.length)} flavors: distinct sets of named sequences.
    </p>
    <div class="table-wrap">
      <table class="flavors">
        <thead>
          <tr><th>Flavor</th><th class="num">Sequences</th><th class="num">Length</th><th>Operations</th><th>Naming</th><th>Published as</th></tr>
        </thead>
        <tbody>
          {#each rows as f (f.flavor)}
            <tr>
              <td><a href={href("flavor", f.flavor)}>{f.flavor}</a>{#if f.patch_release !== null}<span class="tag">p{f.patch_release}</span>{/if}</td>
              <td class="num">{n(f.n_sequences)}</td>
              <td class="num">{bp(f.total_length, true)}</td>
              <td>
                {#each f.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{:else}<span class="muted">none</span>{/each}
              </td>
              <td class="naming">{f.naming.split(";")[0]}</td>
              <td>
                <ul class="plain">
                  {#each byFlavor.get(f.flavor) ?? [] as t (t.target)}
                    <li><span class="publisher">{t.publisher}</span> <span class="alias">{t.alias}</span></li>
                  {/each}
                </ul>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
{:catch e}
  <ErrorBox error={e} />
{/await}
