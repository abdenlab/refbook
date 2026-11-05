<script lang="ts">
  // A flavor: its identity, its recipe (roots → operations → names → output),
  // the files that reproduce it, exports, and its sequences.
  import * as rb from "@abdenlab/refbook";
  import type { Catalog } from "../data/catalog.ts";
  import { chromSizes, inOrder, sequenceDictionary } from "../data/exports.ts";
  import { flavors, manifest, targetOrder, targets } from "../data/flavors.ts";
  import { measure } from "../data/meter.ts";
  import { bp, download, n } from "../format.ts";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import RecipeDiagram from "../components/RecipeDiagram.svelte";
  import SequencesTable from "../components/SequencesTable.svelte";
  import type { Recipe } from "./recipe.ts";

  let { cat, label }: { cat: Catalog; label: string } = $props();

  async function assemblyNames(): Promise<Map<string, string>> {
    const members = await cat.table<{ assembly_accession: string; assembly_name: string }>("assembly_members.parquet");
    return new Map(members.map((m) => [m.assembly_accession, m.assembly_name]));
  }

  const loaded = $derived(measure(`flavor ${label}`, async () => {
    const [fs, ts, rows, names] = await Promise.all([flavors(cat), targets(cat), manifest(cat, label), assemblyNames()]);
    const f = fs.find((x) => x.flavor === label);
    return { f, rows, names, mine: ts.filter((t) => t.flavor === label), recipe: f ? (JSON.parse(f.recipe) as Recipe) : null };
  }));

  // Exports, in canonical order or in one published file's order.
  let order = $state("");
  const stem = () => order || label;
  async function ordered(rows: Parameters<typeof inOrder>[0]) {
    return inOrder(rows, order ? await targetOrder(cat, order) : undefined);
  }
  async function seqcol(rows: Parameters<typeof inOrder>[0]) {
    const r = await ordered(rows);
    return JSON.stringify(rb.seqcolLevel2(r.map((x) => x.name), r.map((x) => x.length), r.map((x) => x.sha512t24u)), null, 1);
  }
</script>

{#await loaded then { f, rows, names, mine, recipe }}
  <section>
    <p class="crumbs"><a href="#/">Catalog</a> / {label}</p>
    {#if !f || !recipe}
      <h1>No such flavor</h1>
      <p><a href="#/">Back to the catalog</a></p>
    {:else}
      <h1>{label}</h1>
      <p class="lede">
        {f.assembly}{f.patch_release !== null ? `, patch release ${f.patch_release}` : ""}:
        {n(f.n_sequences)} sequences, {bp(f.total_length)}. Published as {n(mine.length)} file{mine.length === 1 ? "" : "s"}.
      </p>

      <h2>Identity</h2>
      <dl class="ids">
        <dt>Flavor ID</dt>
        <dd><Digest value={f.id} /><div class="muted">The named sequence set, whatever the order: the level-1 digest of sorted_named_sequences.</div></dd>
        <dt>Seqcol digest</dt>
        <dd><Digest value={f.seqcol_digest} /><div class="muted">GA4GH sequence collection, in canonical order (by name). Each published file has its own, for its own order.</div></dd>
      </dl>

      <h2>Recipe</h2>
      <RecipeDiagram flavor={f} {recipe} {rows} {names} />

      <h2>Published files</h2>
      <p class="muted">Each file was rebuilt from the roots by the recipe, sequence by sequence, and matched.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Publisher</th><th>File</th><th>Checked by</th><th>Seqcol digest (its order)</th></tr></thead>
          <tbody>
            {#each mine as t (t.target)}
              <tr>
                <td>{t.publisher}</td>
                <td><a href={t.published} rel="noopener">{t.alias}</a></td>
                <td>{t.evidence === "content" ? "every sequence's bases" : "its .dict (names, lengths, MD5s)"}</td>
                <td><code class="small">{t.seqcol_digest}</code></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <h2>Export</h2>
      <div class="exports">
        <select aria-label="Order" bind:value={order}>
          <option value="">canonical order (by name)</option>
          {#each mine as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}
        </select>
        <button type="button" onclick={async () => download(`${stem()}.chrom.sizes`, chromSizes(await ordered(rows)))}>chrom.sizes</button>
        <button type="button" onclick={async () => download(`${stem()}.dict`, sequenceDictionary(await ordered(rows)))}>.dict (with MD5)</button>
        <button type="button" onclick={async () => download(`${stem()}.seqcol.json`, await seqcol(rows), "application/json")}>seqcol (level 2)</button>
        <button type="button" onclick={() => download(`${label}.recipe.json`, JSON.stringify(recipe, null, 2), "application/json")}>recipe</button>
      </div>

      <h2>Sequences</h2>
      <SequencesTable flavor={label} {rows} />
    {/if}
  </section>
{:catch e}
  <ErrorBox error={e} />
{/await}
