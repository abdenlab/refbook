<script lang="ts">
  // Two collections compared: seqcol's /comparison (counts per attribute), and
  // refbook's account of each sequence (same, other operations on the same
  // root, other sequences, renamed, in one only).
  import * as rb from "@abdenlab/refbook";
  import type { Catalog } from "../data/catalog.ts";
  import { inOrder } from "../data/exports.ts";
  import { flavors, manifest, OPERATION_LABELS, targetOrder, targets, type ManifestRow } from "../data/flavors.ts";
  import { level2, pairs, type Pair } from "../data/identify.ts";
  import { measure } from "../data/meter.ts";
  import { n } from "../format.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat, query }: { cat: Catalog; query: URLSearchParams } = $props();

  const a = $derived(query.get("a") ?? "");
  const b = $derived(query.get("b") ?? "");
  const choices = $derived(Promise.all([flavors(cat), targets(cat)]));

  function choose(which: "a" | "b", value: string) {
    const p = new URLSearchParams({ a, b, [which]: value });
    location.hash = `#/compare?${p}`;
  }

  /** A flavor's sequences in canonical order, or a published file's in its own. */
  async function rows(choice: string): Promise<ManifestRow[]> {
    const t = (await targets(cat)).find((x) => x.target === choice);
    if (!t) return manifest(cat, choice);
    return inOrder(await manifest(cat, t.flavor), await targetOrder(cat, t.target));
  }

  const compared = $derived(a && b ? measure(`compare ${a} ${b}`, async () => {
    const [ra, rb_] = await Promise.all([rows(a), rows(b)]);
    return { seqcol: rb.seqcolCompare(level2(ra), level2(rb_)), pairs: pairs(ra, rb_) };
  }) : null);

  const KINDS: [Pair["kind"], string][] = [
    ["same", "the same sequence, under the same name"],
    ["operations", "the same root under the same name, with other nucleotide operations"],
    ["different", "the same name for other sequences"],
    ["renamed", "the same sequence under other names"],
    ["a_only", "only in A"],
    ["b_only", "only in B"],
  ];
  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "as submitted");
  const order = (v: boolean | null) => (v === null ? "—" : v ? "yes" : "no");
</script>

<section>
  <p class="crumbs"><a href="#/">Catalog</a> / Compare</p>
  <h1>Compare two collections</h1>
  {#await choices then [fs, ts]}
    <div class="exports">
      {#each [["a", a], ["b", b]] as [which, value] (which)}
        <label>{which.toUpperCase()}
          <select value={value} onchange={(e) => choose(which as "a" | "b", e.currentTarget.value)}>
            <option value="">choose…</option>
            <optgroup label="Flavors (canonical order)">{#each fs as f (f.flavor)}<option value={f.flavor}>{f.flavor}</option>{/each}</optgroup>
            <optgroup label="Published files (their order)">{#each ts as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}</optgroup>
          </select>
        </label>
      {/each}
    </div>
  {/await}

  {#if compared}
    {#await compared}
      <p class="muted">Comparing…</p>
    {:then { seqcol, pairs: ps }}
      <h2>What differs, sequence by sequence</h2>
      {@const groups = Object.groupBy(ps, (p) => p.kind)}
      {#each KINDS as [kind, label] (kind)}
        {@const g = groups[kind] ?? []}
        {#if g.length}
          <details open={kind !== "same" && g.length <= 50}>
            <summary><strong>{n(g.length)}</strong> {label}</summary>
            <div class="table-wrap">
              <table>
                <tbody>
                  {#each g.slice(0, 500) as p, i (i)}
                    <tr>
                      {#if p.kind === "same"}<td>{p.name}</td><td><code>{p.a.root_id}</code> {ops(p.a.operations)}</td>
                      {:else if p.kind === "operations"}<td>{p.name}</td><td><code>{p.a.root_id}</code>: A {ops(p.a.operations)}; B {ops(p.b.operations)}</td>
                      {:else if p.kind === "different"}<td>{p.name}</td><td>A <code>{p.a.root_id}</code> {ops(p.a.operations)}; B <code>{p.b.root_id}</code> {ops(p.b.operations)}</td>
                      {:else if p.kind === "renamed"}<td>{p.a.name} → {p.b.name}</td><td><code>{p.a.root_id}</code> {ops(p.a.operations)}</td>
                      {:else if p.kind === "a_only"}<td>{p.a.name}</td><td><code>{p.a.root_id}</code> {ops(p.a.operations)}, {n(p.a.length)} bp</td>
                      {:else}<td>{p.b.name}</td><td><code>{p.b.root_id}</code> {ops(p.b.operations)}, {n(p.b.length)} bp</td>{/if}
                    </tr>
                  {/each}
                  {#if g.length > 500}<tr><td colspan="2" class="muted">and {n(g.length - 500)} more</td></tr>{/if}
                </tbody>
              </table>
            </div>
          </details>
        {/if}
      {/each}

      <h2>Seqcol comparison</h2>
      <p class="muted">GA4GH seqcol's <code>/comparison</code>: each attribute counted on its own. Shared elements come in the same order, or not (— when fewer than two are shared).</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Attribute</th><th class="num">A</th><th class="num">B</th><th class="num">Shared</th><th>Same order</th></tr></thead>
          <tbody>
            {#each seqcol.attributes.a_and_b as k (k)}
              {@const e = seqcol.array_elements}
              <tr><td><code>{k}</code></td><td class="num">{n(e.a_count[k])}</td><td class="num">{n(e.b_count[k])}</td>
                <td class="num">{n(e.a_and_b_count[k])}</td><td>{order(e.a_and_b_same_order[k])}</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
      <details><summary>The comparison as JSON</summary><pre class="json">{JSON.stringify(seqcol, null, 2)}</pre></details>
    {:catch e}
      <ErrorBox error={e} />
    {/await}
  {:else}
    <p class="muted">Choose two flavors or published files.</p>
  {/if}
</section>
