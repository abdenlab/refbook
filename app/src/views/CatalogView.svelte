<script lang="ts">
  // The catalog: every edition, what it holds and who publishes it. The top of
  // the breadcrumbs: Catalog / edition / sequence.
  import type { Catalog } from "../data/catalog.ts";
  import { editions, OPERATION_LABELS, targets } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { bp, n } from "../format.ts";
  import { href } from "../route.svelte.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat }: { cat: Catalog } = $props();

  const loaded = measure("catalog", async () => {
    const [fs, ts] = await Promise.all([editions(cat), targets(cat)]);
    const byEdition = Map.groupBy(ts, (t) => t.edition);
    const rows = [...fs].sort((a, b) => a.n_sequences - b.n_sequences || a.edition.localeCompare(b.edition));
    return { rows, byEdition, nFiles: ts.length };
  });
</script>

<section>
  <p class="crumbs">Catalog</p>
  <h1>GRCh38, as published</h1>
  {#await loaded then { rows, byEdition, nFiles }}
    <p class="lede">
      {n(nFiles)} published files reduce to {n(rows.length)} editions: distinct sets of named sequences, each a recipe over the same original
      sequences, checked by rebuilding the file.
    </p>
    <div class="table-wrap">
      <table class="editions">
        <thead>
          <tr><th>Edition</th><th class="num">Sequences</th><th class="num">Length</th><th>Operations</th><th>Naming</th><th>Published as</th></tr>
        </thead>
        <tbody>
          {#each rows as f (f.edition)}
            <tr>
              <td><a href={href("edition", f.edition)}>{f.edition}</a>{#if f.patch_release !== null}<span class="tag">p{f.patch_release}</span>{/if}</td>
              <td class="num">{n(f.n_sequences)}</td>
              <td class="num">{bp(f.total_length, true)}</td>
              <td>
                {#each f.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{:else}<span class="muted">none</span>{/each}
              </td>
              <td class="naming">{f.naming.split(";")[0]}</td>
              <td>
                <ul class="plain">
                  {#each byEdition.get(f.edition) ?? [] as t (t.target)}
                    <li><span class="publisher">{t.publisher}</span> <span class="alias">{t.alias}</span></li>
                  {/each}
                </ul>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
