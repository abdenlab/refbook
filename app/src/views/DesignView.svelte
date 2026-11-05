<script lang="ts">
  // Design a flavor: a recipe editor. The choices stay in view on the left; on
  // the right, tabs show the same recipe as analysis goals, as JSON, in detail,
  // and against the catalog (to load a flavor's recipe). The recipe is compiled
  // live by the core in the browser; a strip on top says what it makes.
  import * as rb from "@abdenlab/refbook";
  import type { Catalog } from "../data/catalog.ts";
  import { decodeRecipe, design, designTables, encodeRecipe, grcNames, plainRecipe, type Recipe } from "../data/design.ts";
  import { chromSizes, sequenceDictionary } from "../data/exports.ts";
  import { flavors, manifest, OPERATION_LABELS, type Flavor, type ManifestRow } from "../data/flavors.ts";
  import { pairs, type Pair } from "../data/identify.ts";
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

  let recipe = $state<Recipe | null>(null);
  let loaded = $state("");          // the recipe as last loaded, to know if it was edited
  let jsonText = $state("");
  let jsonError = $state<string | null>(null);
  let tab = $state<"goals" | "json" | "details" | "catalog">("goals");
  let catalogFilter = $state("");

  function initial(fs: Flavor[]): Recipe {
    try {
      const r = query.get("r");
      if (r) return decodeRecipe(r);
    } catch { /* a bad link: a new recipe */ }
    const from = fs.find((f) => f.flavor === query.get("from"));
    return from ? plainRecipe(JSON.parse(from.recipe)) : edit.fromScratch();
  }

  function set(r: Recipe) {
    recipe = r;
    jsonText = JSON.stringify(r, null, 2);
    jsonError = null;
    history.replaceState(null, "", `#/design?r=${encodeRecipe(r)}`);
  }

  function load(r: Recipe) {
    set(r);
    loaded = JSON.stringify(r);
  }

  function fromJson(text: string) {
    jsonText = text;
    try {
      const parsed: Recipe = JSON.parse(text);
      recipe = parsed?.rename ? { ...parsed, rename: grcNames(parsed.rename) } : parsed;
      jsonError = null;
      history.replaceState(null, "", `#/design?r=${encodeRecipe(recipe!)}`);
    } catch (e) {
      jsonError = message(e);
    }
  }

  function loadFlavor(f: Flavor | null) {
    const edited = recipe && JSON.stringify(recipe) !== loaded;
    if (edited && !confirm(`Replace the recipe you are editing with ${f ? f.flavor + "'s" : "a new one"}?`)) return;
    load(f ? plainRecipe(JSON.parse(f.recipe)) : edit.fromScratch());
  }

  $effect(() => {
    ready.then(({ fs }) => { if (recipe === null) load(initial(fs)); });
  });

  /** The design, or the compiler's error. */
  function attempt(r: Recipe, t: Parameters<typeof design>[1], fs: Flavor[]) {
    try { return { d: design(r, t, fs), error: null }; } catch (e) { return { d: null, error: e }; }
  }

  /** Every cataloged flavor, by how many sequences differ from the design. */
  function ranked(rows: ManifestRow[], manifests: Map<string, ManifestRow[]>) {
    return [...manifests].map(([flavor, m]) => ({ flavor, diffs: pairs(rows, m).filter((p) => p.kind !== "same") }))
      .sort((a, b) => a.diffs.length - b.diffs.length || a.flavor.localeCompare(b.flavor));
  }

  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "as submitted");
  const nameOf = (x: Pair) => ("name" in x ? x.name : "a" in x ? x.a.name : x.b.name);
  const KIND: Record<string, string> = {
    operations: "with other operations", different: "other sequences under the same name", renamed: "renamed",
    a_only: "only in yours", b_only: "only in it",
  };
  const SHORT: Record<string, string> = { ucsc: "UCSC", grc: "GRC", genbank: "GenBank", refseq: "RefSeq" };
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
      {@const releases = [...t.assemblies].filter(([acc]) => acc.startsWith(edit.GRCH38)).sort(([a], [b]) => Number(a.split(".")[1]) - Number(b.split(".")[1]))}
      {@const latest = releases.at(-1)?.[0]}
      {@const counts = p ? t.roleCounts.get(p.assembly) : undefined}
      {@const release = p ? edit.releaseLabel(t.assemblies.get(p.assembly) ?? p.assembly, p.assembly === latest).split(" ")[0] : ""}
      {@const hlaAll = t.collections.get(edit.HLA) ?? []}
      {@const groups = edit.hlaGroups(recipe)}
      {@const attempted = attempt(recipe, t, fs)}
      {@const ranks = attempted.d && !attempted.d.novel.length ? ranked(attempted.d.rows as ManifestRow[], manifests) : null}

      <div class="strip" aria-live="polite">
        {#if attempted.error}
          <p class="bad compile-error">The recipe doesn't compile: {message(attempted.error)}</p>
        {:else if attempted.d}
          {@const d = attempted.d}
          <p class="verdict" class:ok={!!d.equals}>
            {#if d.equals}This is <a href={href("flavor", d.equals)}>{d.equals}</a>.
            {:else if ranks}A flavor the catalog doesn't have; closest:
              <a href={href("flavor", ranks[0].flavor)}>{ranks[0].flavor}</a>, {n(ranks[0].diffs.length)} sequence{ranks[0].diffs.length === 1 ? "" : "s"} differ.
            {:else}A flavor the catalog doesn't have.{/if}
          </p>
          <p class="muted">{n(d.rows.length)} sequences, {bp(d.rows.reduce((s, r) => s + r.length, 0), true)}
            {#if d.id}· flavor ID <code>{d.id.slice(0, 12)}…</code>{:else}· <span class="bad">{n(d.novel.length)} never built</span>{/if}</p>
          <div class="exports">
            <button type="button" onclick={() => download("recipe.json", JSON.stringify(recipe, null, 2), "application/json")}>recipe</button>
            {#if !d.novel.length}
              {@const rows = d.rows as ManifestRow[]}
              <button type="button" onclick={() => download("design.chrom.sizes", chromSizes(rows))}>chrom.sizes</button>
              <button type="button" onclick={() => download("design.dict", sequenceDictionary(rows))}>.dict</button>
              <button type="button" onclick={() => download("design.seqcol.json", JSON.stringify(rb.seqcolLevel2(rows.map((r) => r.name), rows.map((r) => r.length), rows.map((r) => r.sha512t24u)), null, 1), "application/json")}>seqcol</button>
            {/if}
            <button type="button" onclick={() => navigator.clipboard?.writeText(location.href)}>copy link</button>
          </div>
        {/if}
      </div>

      <div class="design">
        <div class="form">
          <fieldset>
            <legend>GRCh38</legend>
            {#if p}
              <div class="row-head">
                <label>Release
                  <select value={p.assembly} onchange={(e) => set(edit.setRelease(recipe!, e.currentTarget.value))}>
                    {#each releases as [acc, name] (acc)}<option value={acc} title={acc}>{edit.releaseLabel(name, acc === latest)}</option>{/each}
                  </select>
                </label>
              </div>
              {@const overrides = Object.keys(recipe.rename.by_role ?? {}).length}
              <div class="group names-head">
                <span><strong>Names</strong> <span class="muted">of all sequences, unless a role says otherwise</span></span>
                <select class="naming" aria-label="Names of all sequences" value={recipe.rename.namespace}
                        onchange={(e) => set(edit.setNamespace(recipe!, e.currentTarget.value))}>
                  {#each edit.NAMESPACES as x (x)}<option value={x} title={edit.NAMESPACE_LABELS[x]}>{SHORT[x]}</option>{/each}
                </select>
              </div>
              {#each edit.ROLES_SHOWN as r (r)}
                {@const on = p.roles.includes(r)}
                {@const count = counts?.get(r) ?? 0}
                <div class="group">
                  <label class="check"><input type="checkbox" checked={on} disabled={!on && !count}
                    onchange={(e) => set(edit.setRole(recipe!, r, e.currentTarget.checked))} />
                    <span>{role(r)}{#if count}{" "}<span class="muted">({n(count)})</span>{:else}<span class="muted">: none in {release}</span>{/if}</span></label>
                  {#if on}
                    {@const own = recipe.rename.by_role?.[r] ?? ""}
                    <select class="naming" class:inherit={!own} aria-label={`Names of ${role(r)}`} value={own}
                            onchange={(e) => set(edit.setRoleNames(recipe!, r, e.currentTarget.value || null))}>
                      <option value="">default: {SHORT[recipe.rename.namespace]}</option>
                      {#each edit.NAMESPACES as x (x)}<option value={x} title={edit.NAMESPACE_LABELS[x]}>{SHORT[x]}</option>{/each}
                    </select>
                  {/if}
                </div>
              {/each}
              {#if overrides}
                <p class="clear"><button type="button" class="link" onclick={() => set(edit.clearRoleNames(recipe!))}>
                  clear {overrides === 1 ? "the override" : `${overrides} overrides`}: every role by the default</button></p>
              {/if}
            {:else}
              <p class="muted">No GRCh38 entry. <button type="button" onclick={() => set(edit.setRelease(recipe!, `${edit.GRCH38}.15`))}>Add one</button></p>
            {/if}
          </fieldset>

          {#if p && p.roles.some((r) => ["alt-scaffold", "fix-patch", "novel-patch"].includes(r))}
            {@const kept = edit.placedOn(recipe)}
            <fieldset>
              <legend>Filters</legend>
              <p class="small">Alts and patches placed on</p>
              {#each edit.PARENT_TYPES as type (type)}
                <label class="check"><input type="checkbox" checked={kept.includes(type)}
                  disabled={kept.length === 1 && kept.includes(type)}
                  onchange={(e) => set(edit.setPlacedOn(recipe!, type, e.currentTarget.checked))} />
                  {type === "chromosome" ? "chromosomes" : "other scaffolds"}</label>
              {/each}
              <p class="muted small">Every alt and patch is placed on the sequence it is an alternative to or fixes. In GRCh38.p14 all
                are placed on chromosomes but 3 fix patches, which fix alt scaffolds; Ensembl and GENCODE leave those out.</p>
            </fieldset>
          {/if}

          <fieldset>
            <legend>Other sequences</legend>
            <div class="group">
              <label class="check"><input type="checkbox" checked={edit.hasEbv(recipe)} onchange={(e) => set(edit.setEbv(recipe!, e.currentTarget.checked))} />
                <span>EBV <span class="muted">(<code>{edit.EBV}</code>)</span></span></label>
            </div>
            <div class="group">
              <label class="check"><input type="checkbox" checked={edit.hasDecoys(recipe)} onchange={(e) => set(edit.setDecoys(recipe!, e.currentTarget.checked))} />
                <span>hs38d1 decoys <span class="muted">({n(t.roleCounts.get(edit.HS38D1)?.get("unplaced-scaffold") ?? 0)})</span></span></label>
            </div>
            <div class="group">
              <label class="check"><input type="checkbox" checked={groups.length > 0}
                onchange={(e) => set(edit.setHla(recipe!, e.currentTarget.checked ? edit.HLA_TYPING_GROUPS : [], hlaAll))} />
                <span>HLA alleles <span class="muted">(hs38DH's six genes; not hosted)</span></span></label>
            </div>
            {#if edit.hlaKind(recipe) === "custom"}
              <p class="muted small">A custom set of {groups.length} HLA gene{groups.length === 1 ? "" : "s"} ({groups.join(", ")}): edit it in the JSON.
                Switching HLA off and on gives hs38DH's six.</p>
            {/if}
            {#if edit.others(recipe).length}<p class="muted small">And {edit.others(recipe).length} more entries: edit them in the JSON.</p>{/if}
          </fieldset>

          <fieldset>
            <legend>Bases</legend>
            <label class="check"><input type="checkbox" checked={edit.hasMask(recipe, "hardmask_grc")} onchange={(e) => set(edit.setMask(recipe!, "hardmask_grc", e.currentTarget.checked))} /> GRC hard-mask</label>
            <label class="check"><input type="checkbox" checked={!!recipe.alphabet} onchange={(e) => set(edit.setIupacToN(recipe!, e.currentTarget.checked))} /> IUPAC → N</label>
          </fieldset>
        </div>

        <div class="panel">
          <div class="tabs" role="tablist">
            {#each [["goals", "Goals"], ["json", "JSON"], ["details", "Details"], ["catalog", "Catalog"]] as [k, label] (k)}
              <button type="button" role="tab" aria-selected={tab === k} class:here={tab === k} onclick={() => (tab = k as typeof tab)}>{label}</button>
            {/each}
          </div>

          {#if tab === "goals"}
            <p class="muted small">Choices commonly made for an analysis goal. Switch one on or off, and watch the choices follow.</p>
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
          {:else if tab === "json"}
            <p class="muted small">The recipe, in full. Edit it for anything the choices don't show.</p>
            <textarea class="paste" rows="24" spellcheck="false" aria-label="Recipe JSON" value={jsonText}
                      oninput={(e) => fromJson(e.currentTarget.value)}></textarea>
            {#if jsonError}<p class="bad">Not JSON: {jsonError}</p>{/if}
          {:else if tab === "details"}
            {#if attempted.error}
              <p class="bad">The recipe doesn't compile: {message(attempted.error)}</p>
            {:else if attempted.d}
              {@const d = attempted.d}
              <h3>Sequences</h3>
              <ul class="plain">
                {#each Object.entries(Object.groupBy(d.rows, (r) => ops(r.operations))) as [o, rs] (o)}<li>{n(rs!.length)} {o}</li>{/each}
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
              {#if ranks && !d.equals}
                <h3>What differs from {ranks[0].flavor}</h3>
                <ul class="plain">
                  {#each Object.entries(Object.groupBy(ranks[0].diffs, (x) => x.kind)) as [k, xs] (k)}
                    <li>{n(xs!.length)} {KIND[k]}{#if xs!.length <= 5}: {xs!.map(nameOf).join(", ")}{/if}</li>
                  {/each}
                </ul>
              {/if}
            {/if}
          {:else}
            <p class="muted small">The catalog's flavors, closest to your recipe first. Load one to start from its recipe.</p>
            <p><button type="button" onclick={() => loadFlavor(null)}>A new recipe (GRCh38 chromosomes)</button></p>
            <input type="search" class="filter" placeholder="Filter flavors" aria-label="Filter flavors" bind:value={catalogFilter} />
            <ul class="plain catalog-list">
              {#each (ranks ?? fs.map((f) => ({ flavor: f.flavor, diffs: null }))).filter((x) => x.flavor.includes(catalogFilter.trim())) as x (x.flavor)}
                {@const f = fs.find((y) => y.flavor === x.flavor)!}
                <li>
                  <span><a href={href("flavor", x.flavor)}>{x.flavor}</a> <span class="muted">{n(f.n_sequences)} sequences</span></span>
                  <span class="muted">{x.diffs === null ? "" : x.diffs.length ? `${n(x.diffs.length)} differ` : "the same"}</span>
                  <button type="button" onclick={() => loadFlavor(f)}>Load</button>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </div>
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
