<script lang="ts">
  // Design a flavor: edit a recipe (a form for the common parts, JSON for the
  // rest), compiled live by the core in the browser, with what it makes: its
  // digests, whether it is a cataloged flavor, what differs from the closest,
  // exports, and a link that carries the recipe.
  import * as rb from "@abdenlab/refbook";
  import type { Catalog } from "../data/catalog.ts";
  import { decodeRecipe, design, designTables, encodeRecipe, plainRecipe, type Recipe } from "../data/design.ts";
  import { chromSizes, sequenceDictionary } from "../data/exports.ts";
  import { flavors, manifest, OPERATION_LABELS, type Flavor, type ManifestRow } from "../data/flavors.ts";
  import { pairs } from "../data/identify.ts";
  import * as edit from "../data/recipeEdit.ts";
  import { bp, download, message, n } from "../format.ts";
  import { href } from "../route.svelte.ts";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import { role } from "./recipe.ts";

  let { cat, query }: { cat: Catalog; query: URLSearchParams } = $props();

  const ready = $derived(Promise.all([designTables(cat), flavors(cat)]).then(async ([t, fs]) => {
    const manifests = new Map(await Promise.all(fs.map(async (f) => [f.flavor, await manifest(cat, f.flavor)] as const)));
    return { t, fs, manifests };
  }));

  function initial(fs: Flavor[]): Recipe {
    try {
      const r = query.get("r");
      if (r) return decodeRecipe(r);
    } catch { /* a bad link: start from scratch */ }
    const from = fs.find((f) => f.flavor === query.get("from"));
    if (from) start = from.flavor;
    return from ? plainRecipe(JSON.parse(from.recipe)) : edit.fromScratch();
  }

  let recipe = $state<Recipe | null>(null);
  let jsonText = $state("");
  let jsonError = $state<string | null>(null);
  let start = $state("");

  function set(r: Recipe) {
    recipe = r;
    jsonText = JSON.stringify(r, null, 2);
    jsonError = null;
    history.replaceState(null, "", `#/design?r=${encodeRecipe(r)}`);
  }

  function fromJson(text: string) {
    jsonText = text;
    try {
      recipe = JSON.parse(text);
      jsonError = null;
      history.replaceState(null, "", `#/design?r=${encodeRecipe(recipe!)}`);
    } catch (e) {
      jsonError = message(e);
    }
  }

  function startFrom(fs: Flavor[], label: string) {
    start = label;
    const f = fs.find((x) => x.flavor === label);
    set(f ? plainRecipe(JSON.parse(f.recipe)) : edit.fromScratch());
  }

  $effect(() => {
    ready.then(({ fs }) => { if (recipe === null) set(initial(fs)); });
  });

  /** The design, or the compiler's error. */
  function attempt(r: Recipe, t: Parameters<typeof design>[1], fs: Flavor[]) {
    try { return { d: design(r, t, fs), error: null }; } catch (e) { return { d: null, error: e }; }
  }

  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "as submitted");

  /** The cataloged flavor with the fewest differences, and the differences. */
  function closest(rows: ManifestRow[], manifests: Map<string, ManifestRow[]>) {
    let best: { flavor: string; diffs: ReturnType<typeof pairs> } | null = null;
    for (const [flavor, m] of manifests) {
      const diffs = pairs(rows, m).filter((p) => p.kind !== "same");
      if (!best || diffs.length < best.diffs.length) best = { flavor, diffs };
    }
    return best!;
  }

  const KIND: Record<string, string> = {
    operations: "other operations", different: "other sequences under the name", renamed: "renamed",
    a_only: "only in yours", b_only: "only in it",
  };
</script>

<section>
  <p class="crumbs"><a href="#/">Catalog</a> / Design</p>
  <h1>Design a flavor</h1>
  <p class="lede">
    Choose the sequences, the operations on their bases, and their names. The recipe is compiled here, in your browser,
    by the same code that builds the catalog; every sequence's digests come from the catalog.
  </p>

  {#await ready}
    <p class="muted">Loading the catalog's tables…</p>
  {:then { t, fs, manifests }}
    {#if recipe}
      {@const p = edit.primary(recipe)}
      {@const releases = [...t.assemblies].filter(([acc]) => acc.startsWith(edit.GRCH38))}
      {@const hlaAll = t.collections.get(edit.HLA) ?? []}
      {@const groups = edit.hlaGroups(recipe)}
      {@const attempted = attempt(recipe, t, fs)}
      <div class="exports">
        <label>Start from
          <select value={start} onchange={(e) => startFrom(fs, e.currentTarget.value)}>
            <option value="">scratch (GRCh38 chromosomes)</option>
            {#each fs as f (f.flavor)}<option value={f.flavor}>{f.flavor}</option>{/each}
          </select>
        </label>
      </div>

      <div class="design">
        <div class="form">
          <fieldset>
            <legend>GRCh38</legend>
            {#if p}
              <label>Release
                <select value={p.assembly} onchange={(e) => set(edit.setRelease(recipe!, e.currentTarget.value))}>
                  {#each releases as [acc, name] (acc)}<option value={acc}>{name} ({acc})</option>{/each}
                </select>
              </label>
              {#each edit.ROLES as r (r)}
                <label class="check"><input type="checkbox" checked={p.roles.includes(r)}
                  onchange={(e) => set(edit.setRole(recipe!, r, e.currentTarget.checked))} /> {role(r)}</label>
              {/each}
              <label class="check"><input type="checkbox" checked={!!p.placed_on}
                onchange={(e) => set(edit.setPlacedOnChromosomes(recipe!, e.currentTarget.checked))} />
                only alts and patches placed on chromosomes</label>
            {:else}
              <p class="muted">No GRCh38 entry. <button type="button" onclick={() => set(edit.setRelease(recipe!, `${edit.GRCH38}.15`))}>Add one</button></p>
            {/if}
          </fieldset>
          <fieldset>
            <legend>Other sequences</legend>
            <label class="check"><input type="checkbox" checked={edit.hasEbv(recipe)} onchange={(e) => set(edit.setEbv(recipe!, e.currentTarget.checked))} /> EBV (<code>{edit.EBV}</code>)</label>
            <label class="check"><input type="checkbox" checked={edit.hasDecoys(recipe)} onchange={(e) => set(edit.setDecoys(recipe!, e.currentTarget.checked))} /> hs38d1 decoys (<code>{edit.HS38D1}</code>)</label>
            <label class="check"><input type="checkbox" checked={groups.length > 0}
              onchange={(e) => set(edit.setHla(recipe!, e.currentTarget.checked ? edit.HLA_TYPING_GROUPS : [], hlaAll))} />
              HLA alleles: hs38DH's six genes ({edit.HLA_TYPING_GROUPS.join(", ")}; {edit.HLA}, not hosted)</label>
            {#if edit.hlaKind(recipe) === "custom"}
              <p class="muted">This recipe has a custom set of {groups.length} HLA gene{groups.length === 1 ? "" : "s"}
                ({groups.join(", ")}): edit it in the JSON below. Switching HLA off and on gives hs38DH's six.</p>
            {/if}
            {#if edit.others(recipe).length}<p class="muted">And {edit.others(recipe).length} more entries: edit them in the JSON below.</p>{/if}
          </fieldset>
          <fieldset>
            <legend>Bases</legend>
            <label class="check"><input type="checkbox" checked={edit.hasMask(recipe, "hardmask_grc")} onchange={(e) => set(edit.setMask(recipe!, "hardmask_grc", e.currentTarget.checked))} /> GRC hard-mask</label>
            <label class="check"><input type="checkbox" checked={!!recipe.alphabet} onchange={(e) => set(edit.setIupacToN(recipe!, e.currentTarget.checked))} /> IUPAC → N</label>
          </fieldset>
          <fieldset>
            <legend>Names</legend>
            <label>Names
              <select value={recipe.rename.namespace} onchange={(e) => set(edit.setNamespace(recipe!, e.currentTarget.value))}>
                {#each edit.NAMESPACES as ns (ns)}<option value={ns}>{ns}</option>{/each}
              </select>
            </label>
            <label>Chromosomes
              <select value={recipe.rename.by_role?.["assembled-molecule"] ?? ""} onchange={(e) => set(edit.setChromosomeNames(recipe!, e.currentTarget.value || null))}>
                <option value="">the same</option>
                {#each edit.NAMESPACES as ns (ns)}<option value={ns}>{ns}</option>{/each}
              </select>
            </label>
          </fieldset>
        </div>

        <div class="result">
          {#if attempted.error}
            <p class="bad compile-error">The recipe doesn't compile: {message(attempted.error)}</p>
          {:else if attempted.d}
            {@const d = attempted.d}
            {@const total = d.rows.reduce((s, r) => s + r.length, 0)}
            {#if d.equals}
              <p class="verdict ok">This is <a href={href("flavor", d.equals)}>{d.equals}</a>.</p>
            {:else}
              {@const c = closest(d.rows as ManifestRow[], manifests)}
              {@const kinds = Object.groupBy(c.diffs, (x) => x.kind)}
              <p class="verdict">A flavor the catalog doesn't have. Closest: <a href={href("flavor", c.flavor)}>{c.flavor}</a>, with</p>
              <ul class="plain">
                {#each Object.entries(kinds) as [k, xs] (k)}
                  <li>{n(xs!.length)} {KIND[k]}{#if xs!.length <= 3}: {xs!.map((x) => "name" in x ? x.name : "a" in x ? x.a.name : x.b.name).join(", ")}{/if}</li>
                {/each}
              </ul>
            {/if}
            <p><strong>{n(d.rows.length)} sequences</strong>, {bp(total)}</p>
            <ul class="plain small">
              {#each Object.entries(Object.groupBy(d.rows, (r) => ops(r.operations))) as [o, rs] (o)}
                <li>{n(rs!.length)} {o}</li>
              {/each}
            </ul>
            {#if d.novel.length}
              <p class="bad">{n(d.novel.length)} sequences the catalog has never built, so their digests need their bases:
                {d.novel.slice(0, 5).map((r) => `${r.name} (${r.root_id} ${ops(r.operations)})`).join(", ")}{d.novel.length > 5 ? ", …" : ""}</p>
            {:else}
              <dl class="ids">
                <dt>Flavor ID</dt><dd><Digest value={d.id!} /></dd>
                <dt>Seqcol digest</dt><dd><Digest value={d.seqcolDigest!} /><div class="muted">in canonical order (by name)</div></dd>
              </dl>
            {/if}
            <div class="exports">
              <button type="button" onclick={() => download("recipe.json", JSON.stringify(recipe, null, 2), "application/json")}>recipe</button>
              {#if !d.novel.length}
                {@const rows = d.rows as ManifestRow[]}
                <button type="button" onclick={() => download("design.chrom.sizes", chromSizes(rows))}>chrom.sizes</button>
                <button type="button" onclick={() => download("design.dict", sequenceDictionary(rows))}>.dict (with MD5)</button>
                <button type="button" onclick={() => download("design.seqcol.json", JSON.stringify(rb.seqcolLevel2(rows.map((r) => r.name), rows.map((r) => r.length), rows.map((r) => r.sha512t24u)), null, 1), "application/json")}>seqcol (level 2)</button>
              {/if}
              <button type="button" onclick={() => navigator.clipboard?.writeText(location.href)}>copy link</button>
            </div>
          {/if}
        </div>
      </div>

      <h2>Guide</h2>
      <p class="muted">Choices commonly made for an analysis goal. Switch one on or off; the form and the recipe follow.</p>
      <ul class="guide">
        {#each edit.GUIDE as g (g.goal)}
          {@const on = g.has(recipe)}
          <li>
            <label class="switch">
              <input type="checkbox" role="switch" checked={on} aria-checked={on}
                     onchange={(e) => set(g.set(recipe!, e.currentTarget.checked, { hla: hlaAll }))} />
              <span class="goal">{g.goal}</span>
            </label>
            <span class="muted">{g.choice}</span>
          </li>
        {/each}
      </ul>

      <h2>Recipe</h2>
      <p class="muted">The recipe the form edits, in full. Edit it here for anything the form doesn't show.</p>
      <textarea class="paste" rows="14" spellcheck="false" aria-label="Recipe JSON" value={jsonText}
                oninput={(e) => fromJson(e.currentTarget.value)}></textarea>
      {#if jsonError}<p class="bad">Not JSON: {jsonError}</p>{/if}
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
