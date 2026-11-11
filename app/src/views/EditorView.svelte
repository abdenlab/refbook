<script lang="ts" module>
  // The recipe being edited in each book, kept for the session: leaving for an edition's page
  // and coming back (or clicking Editor) returns to it.
  const keptBy = new Map<string, { recipe: string; loaded: string }>();
</script>

<script lang="ts">
  // The editor: a workbench for recipes, with the catalog to start from. A shelf on the
  // left holds every choice of the recipe, always in the same place (a choice
  // that doesn't apply is disabled, not hidden). The stage on the right shows
  // the guide first (analysis goals and the choices made for them), the catalog (fixed, with how far each edition
  // is from the recipe), the recipe and the files it makes, and the details. The
  // recipe is compiled live by the core in the browser.
  import * as rb from "@abdenlab/refbook";
  import { untrack } from "svelte";
  import type { Catalog } from "../data/catalog.ts";
  import { editionHref, editorHref, inCatalogOrder, type Book } from "../data/books.ts";
  import { decodeRecipe, design, designTables, encodeRecipe, grcNames, plainRecipe, type Recipe } from "../data/design.ts";
  import { chromSizes, inOrder as fileOrder, ordered, ORDERS, sequenceDictionary, type Order } from "../data/exports.ts";
  import { coordinateSystem, editions, manifest, OPERATION_LABELS, targetOrder, targets, type Edition, type ManifestRow } from "../data/editions.ts";
  import { pairs } from "../data/identify.ts";
  import { measure } from "../data/meter.ts";
  import * as edit from "../data/recipeEdit.ts";
  import { shelfOf } from "../data/shelves.ts";
  import { bp, download, message, n } from "../format.ts";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Icon from "../components/Icon.svelte";
  import { role } from "./recipe.ts";

  let { cat, query, book, bs }: { cat: Catalog; query: URLSearchParams; book: Book; bs: Book[] } = $props();
  /** The books to switch between, in the catalog's order. */
  const switchable = untrack(() => inCatalogOrder(bs));

  // The view is made anew for each book (App keys it), so the book is read once.
  const b = untrack(() => book);
  const shelf = shelfOf(b.book);
  const kept = keptBy.get(b.book) ?? null;
  let start = $state("");   // the release a new recipe starts from (the tables say)
  const scratch = () => edit.fromScratch(start);

  const ready = $derived(measure("catalog", async () => {
    const [t, all, ts] = await Promise.all([designTables(cat, b.book, shelf.masks.map((m) => m.layer)), editions(cat), targets(cat)]);
    start = t.start;
    const fs = all.filter((f) => f.book === b.book);  // the book's editions only
    const manifests = new Map(await Promise.all(fs.map(async (f) => [f.edition, await manifest(cat, f.edition)] as const)));
    // The catalog's order is fixed: smallest first.
    const listed = [...fs].sort((a, b) => a.n_sequences - b.n_sequences || a.edition.localeCompare(b.edition));
    const published = new Map(Map.groupBy(ts, (x) => x.edition));
    const publishers = new Map([...published].map(([f, xs]) => [f, [...new Set(xs.map((x) => x.publisher))]]));
    return { t, fs, listed, publishers, published, manifests };
  }));

  type Tab = "catalog" | "guide" | "recipe" | "export" | "info";
  const TABS: [Tab, string][] = [["guide", "Guide"], ["catalog", "Catalog"], ["recipe", "Recipe"], ["info", "Info"], ["export", "Export"]];
  type Format = "sizes" | "dict" | "seqcol";
  const FORMATS: [Format, string][] = [["sizes", "chrom.sizes"], ["dict", ".dict"], ["seqcol", "seqcol.json"]];

  let recipe = $state<Recipe | null>(null);
  let loaded = $state("");          // the recipe as last loaded, to know if it was edited
  let jsonText = $state("");
  let jsonError = $state<string | null>(null);
  // The view is made anew on each navigation, so the link is read once.
  const asked = untrack(() => query.get("tab"));
  let tab = $state<Tab>(TABS.some(([k]) => k === asked) ? (asked as Tab) : "guide");
  let format = $state<Format>("sizes");
  // The export's order: by name, karyotypic by role (the default), or, when the recipe makes a cataloged edition, as
  // in one of its published files (file:<target>, the file's own order, loaded when chosen).
  let order = $state<string>("karyotypic");
  let fileOrders = $state<Record<string, string[]>>({});
  $effect(() => {
    const target = order.startsWith("file:") ? order.slice(5) : null;
    if (target && !(target in untrack(() => fileOrders))) {
      targetOrder(cat, target).then((names) => { fileOrders = { ...fileOrders, [target]: names }; });
    }
  });
  let copied = $state<string | null>(null);

  function initial(fs: Edition[]): Recipe {
    if (kept && !query.has("r") && !query.has("from")) return JSON.parse(kept.recipe);
    try {
      const r = query.get("r");
      if (r) return decodeRecipe(r);
    } catch { /* a bad link: a new recipe */ }
    const from = fs.find((f) => f.edition === query.get("from"));
    return from ? plainRecipe(JSON.parse(from.recipe)) : scratch();
  }

  /** The page's link: the tab, and the recipe once it has been edited or loaded. */
  function remember() {
    const q = new URLSearchParams();
    if (tab !== "guide") q.set("tab", tab);
    if (recipe && JSON.stringify(recipe) !== JSON.stringify(scratch())) q.set("r", encodeRecipe(recipe));
    history.replaceState(null, "", editorHref(b.book, q));
    if (recipe) keptBy.set(b.book, { recipe: JSON.stringify(recipe), loaded });
  }

  function set(r: Recipe) {
    recipe = r;
    jsonText = JSON.stringify(r, null, 2);
    jsonError = null;
    remember();
  }

  function load(r: Recipe) {
    loaded = JSON.stringify(r);
    set(r);
  }

  function fromJson(text: string) {
    jsonText = text;
    try {
      const parsed: Recipe = JSON.parse(text);
      recipe = parsed?.rename ? { ...parsed, rename: grcNames(parsed.rename) } : parsed;
      jsonError = null;
      remember();
    } catch (e) {
      jsonError = message(e);
    }
  }

  function loadEdition(f: Edition | null) {
    const edited = recipe && JSON.stringify(recipe) !== loaded;
    if (edited && !confirm(`Replace the recipe you are editing with ${f ? f.edition + "'s" : "a new one"}?`)) return;
    load(f ? plainRecipe(JSON.parse(f.recipe)) : scratch());
  }

  function show(k: Tab) {
    tab = k;
    remember();
  }

  $effect(() => {
    ready.then(({ fs }) => {
      if (recipe !== null) return;
      const resumed = kept && !query.has("r") && !query.has("from") ? kept.loaded : null;
      load(initial(fs));
      if (resumed !== null) loaded = resumed;
    });
  });

  /** The design, or the compiler's error. */
  function attempt(r: Recipe, t: Parameters<typeof design>[1], fs: Edition[]) {
    try { return { d: design(r, t, fs), error: null }; } catch (e) { return { d: null, error: e }; }
  }

  /** How each cataloged edition differs from the design, sequence by sequence. */
  function differences(rows: ManifestRow[], manifests: Map<string, ManifestRow[]>) {
    return new Map([...manifests].map(([edition, m]) => [edition, pairs(rows, m).filter((p) => p.kind !== "same")]));
  }

  /** A file the recipe makes, in order `o`, or why it can't be made yet. */
  function file(k: Format, d: NonNullable<ReturnType<typeof attempt>["d"]>, places: Parameters<typeof ordered>[2], o: string): { text: string } | { missing: string } {
    let rows: ManifestRow[];
    if (o.startsWith("file:")) {
      const names = fileOrders[o.slice(5)];
      if (!names) return { missing: "waits for the published file's order" };
      rows = fileOrder(d.rows as ManifestRow[], names);
    } else rows = ordered(d.rows as ManifestRow[], o as Order, places);
    if (k === "sizes") return { text: chromSizes(rows) };
    if (d.novel.length) return { missing: `needs every sequence's digests, and ${n(d.novel.length)} have never been built` };
    if (k === "dict") return { text: sequenceDictionary(rows) };
    return { text: JSON.stringify(rb.seqcolLevel2(rows.map((r) => r.name), rows.map((r) => r.length), rows.map((r) => r.sha512t24u)), null, 1) };
  }
  const filename = (k: Format, stem: string) => `${stem}.${{ sizes: "chrom.sizes", dict: "dict", seqcol: "seqcol.json" }[k]}`;

  async function copy(what: string, text: string) {
    await navigator.clipboard?.writeText(text);
    copied = what;
    setTimeout(() => (copied = null), 1200);
  }

  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "original");
  const SHORT: Record<string, string> = { ucsc: "UCSC", grc: "GRC", genbank: "GenBank", refseq: "RefSeq" };
  const LAYOUTS: [edit.Layout, string][] = [["none", "as submitted"], ["pad", "N-padded to their parent"], ["orient", "turned to their parent's strand"]];
  /** A namespace's names for the release's first chromosome (and an unlocalized scaffold), as the menu shows them. */
  const example = (names: string[] | undefined) => {
    const shown = (names ?? []).filter((x) => x);
    return shown.length ? shown.join(", ") : "none in this release";
  };
</script>

<section class="bench">
  <div class="bench-head">
    <p class="crumbs"><a href="#/">Home</a> / Editor</p>
    <!-- One button per book: switching keeps the tab, and each book keeps its recipe for the session. -->
    <nav class="book-switch" aria-label="Assembly">
      {#each switchable as x (x.book)}
        <a href={editorHref(x.book, tab === "guide" ? undefined : new URLSearchParams({ tab }))} class:here={x.book === b.book}
           aria-current={x.book === b.book ? "page" : undefined}>{x.assembly}</a>
      {/each}
    </nav>
  </div>
  {#await ready}
    <p class="muted">Loading the catalog…</p>
  {:then { t, fs, listed, publishers, published, manifests }}

    {#if recipe}
      {@const p = edit.primary(recipe)}
      {@const releases = t.releases}
      {@const latest = releases.at(-1)?.accession}
      {@const counts = p ? t.roleCounts.get(p.assembly) : undefined}
      {@const release = p ? edit.releaseLabel(t.assemblies.get(p.assembly) ?? p.assembly, b.assembly, false).split(" ")[0] : ""}
      {@const rolesShown = edit.ROLES_SHOWN.filter((r) => releases.some((x) => t.roleCounts.get(x.accession)?.get(r)))}
      {@const own = p ? t.mito.get(p.assembly) ?? null : null}
      {@const carried = edit.mitochondria(recipe, own)}
      {@const mito = carried[0] ?? null}
      {@const ctx = { hla: t.collections.get(edit.HLA) ?? [], mito: own }}
      {@const examples = p ? t.examples.get(p.assembly) : undefined}
      {@const anyIupac = [...t.iupac].some((x) => t.places.has(x))}
      {@const groups = edit.hlaGroups(recipe)}
      {@const attempted = attempt(recipe, t, fs)}
      {@const d = attempted.d}
      {@const diffs = d && !d.novel.length ? differences(d.rows as ManifestRow[], manifests) : null}
      {@const overrides = Object.keys(recipe.rename.by_role ?? {}).length}
      {@const placed = !!p && p.roles.some((r) => edit.PLACED_ROLES.includes(r))}
      {@const kept = edit.placedOn(recipe)}
      {@const fresh = JSON.stringify(recipe) === JSON.stringify(scratch())}

      <div class="design workbench">
        <div class="form shelf">
          <p class="status band" class:match={!!d?.equals} aria-live="polite">
            <span class="label">Edition:</span>
            {#if attempted.error}<span class="bad">doesn't compile</span>
            {:else if d?.equals}<Icon name="check" /><a href={editionHref(d.equals)}>{d.equals}</a>
            {:else if d}not in catalog{/if}
            <button type="button" class="icon reset" disabled={fresh} onclick={() => loadEdition(null)}
                    title={fresh ? `A new recipe: the ${b.assembly} chromosomes` : `Start over: a new recipe, the ${b.assembly} chromosomes`}
                    aria-label="Start over with a new recipe"><Icon name="reset" /></button>
          </p>
          <div class="pane">
          <fieldset>
            <legend>Assembly</legend>
            <div class="group names-head">
              <label class="release"><strong>Release</strong>
                <select value={p?.assembly ?? ""} onchange={(e) => set(edit.setRelease(recipe!, e.currentTarget.value, (a) => t.mito.get(a) ?? null))}>
                  {#if !p}<option value="" disabled>none</option>{/if}
                  {#each releases as r (r.accession)}<option value={r.accession} title={r.accession}>{edit.releaseLabel(r.name, b.assembly, r.accession === latest)}</option>{/each}
                </select>
              </label>
              <span class="picker">
                <strong class="ns-label">Name style</strong>
                <button type="button" class="icon" disabled={!overrides} onclick={() => set(edit.clearRoleNames(recipe!))}
                        title={overrides ? `Clear ${overrides === 1 ? "the override" : `${overrides} overrides`}: every role by the name style` : "No overrides"}
                        aria-label="Clear the name overrides"><Icon name="reset" /></button>
                <select class="naming" aria-label="Names of all sequences" value={recipe.rename.namespace}
                        onchange={(e) => set(edit.setNamespace(recipe!, e.currentTarget.value))}>
                  {#each edit.NAMESPACES as x (x)}<option value={x} title={`${SHORT[x]}: ${example(examples?.[x])}`}>{SHORT[x]}</option>{/each}
                </select>
              </span>
            </div>
            <div class="group cols muted small"><span>Role</span><span class="naming">Name override</span></div>
            {#each rolesShown as r (r)}
              {@const on = !!p && p.roles.includes(r)}
              {@const count = counts?.get(r) ?? 0}
              {@const own = recipe.rename.by_role?.[r] ?? ""}
              <div class="group">
                <label class="check"><input type="checkbox" checked={on} disabled={!p || (!on && !count)}
                  onchange={(e) => set(edit.setRole(recipe!, r, e.currentTarget.checked))} />
                  <span>{role(r)}{#if count}{" "}<span class="muted">({n(count)})</span>{:else if p}<span class="muted">: none in {release}</span>{/if}</span></label>
                <select class="naming" class:inherit={!own} aria-label={`Names of ${role(r)}`} value={own} disabled={!on}
                        onchange={(e) => set(edit.setRoleNames(recipe!, r, e.currentTarget.value || null))}>
                  <option value="" title={`No override: ${SHORT[recipe.rename.namespace]}`}>—</option>
                  {#each edit.NAMESPACES as x (x)}<option value={x} title={`${SHORT[x]}: ${example(examples?.[x])}`}>{SHORT[x]}</option>{/each}
                </select>
              </div>
            {/each}
          </fieldset>

          <fieldset>
            <legend>Non-nuclear</legend>
            <label class="choice"><span>Mitochondrial</span>
              {#if carried.length > 1}
                <span class="muted small" title={carried.join(", ")}>{carried.map((x) => edit.MITOCHONDRIA[x] ?? x).join(" and ")}, set in the recipe</span>
              {:else}
                <select value={mito ?? ""} disabled={!p} onchange={(e) => set(edit.setMitochondrion(recipe!, own, e.currentTarget.value || null))}>
                  {#each Object.keys(edit.MITOCHONDRIA) as x (x)}<option value={x} title={x}>{edit.MITOCHONDRIA[x]}</option>{/each}
                  <option value="">none</option>
                </select>
                {@const named = mito ? edit.mitochondrionOverride(recipe, mito) : null}
                {@const names = mito ? [...new Set([...edit.MITOCHONDRION_NAMES, mito])] : []}
                <select class="naming" class:inherit={!named} aria-label="Name of the mitochondrion" value={named ?? ""} disabled={!mito}
                        onchange={(e) => set(edit.setMitochondrionName(recipe!, own, mito!, e.currentTarget.value || null))}>
                  <option value="" title={mito ? `No override: ${edit.mitochondrionName(recipe, mito)}` : ""}>—</option>
                  {#each names as x (x)}<option value={x}>{x}</option>{/each}
                </select>
              {/if}
            </label>
          </fieldset>

          {#if t.placed}
          <fieldset disabled={!placed} class:off={!placed}>
            <legend>Alts and patches</legend>
            <p class="small">Include those placed on</p>
            {#each edit.PARENT_TYPES as type (type)}
              <label class="check"><input type="checkbox" checked={kept.includes(type)}
                disabled={kept.length === 1 && kept.includes(type)}
                onchange={(e) => set(edit.setPlacedOn(recipe!, type, e.currentTarget.checked))} />
                {type === "chromosome" ? "chromosomes" : "other scaffolds"}</label>
            {/each}
            <label class="choice"><span class="small">Laid out</span>
              <select value={edit.layoutOf(recipe)} onchange={(e) => set(edit.setLayout(recipe!, e.currentTarget.value as edit.Layout))}>
                {#each LAYOUTS as [k, label] (k)}<option value={k}>{label}</option>{/each}
              </select>
            </label>
          </fieldset>
          {/if}

          <fieldset>
            <legend>Additional sequences</legend>
            {#each shelf.extras as x (x.id)}
              <label class="check"><input type="checkbox" checked={x.has(recipe)} onchange={(e) => set(x.set(recipe!, e.currentTarget.checked, ctx))} />
                <span>{x.label} <span class="muted">({#if x.id === "ebv"}<code>{edit.EBV}</code>{:else if x.id === "hs38d1"}{n(t.roleCounts.get(edit.HS38D1)?.get("unplaced-scaffold") ?? 0)}{:else if x.id === "hla"}{edit.hlaKind(recipe) === "custom" ? `${groups.length} genes, set in the recipe` : "six genes"} from {edit.HLA}{:else}{bp(t.rootLength.get(edit.HS37D5) ?? 0, true)}{/if})</span></span></label>
            {/each}
            {#if edit.others(recipe).length}<p class="muted small">And {edit.others(recipe).length} more entries, set in the recipe.</p>{/if}
          </fieldset>

          <fieldset>
            <legend>Base operations</legend>
            {#each shelf.masks as m (m.layer)}
              <label class="check"><input type="checkbox" checked={edit.hasMask(recipe, m.layer)} onchange={(e) => set(edit.setMask(recipe!, m.layer, e.currentTarget.checked))} /> {m.label} → N</label>
            {/each}
            {#each (recipe.mask ?? []).filter((m) => !shelf.masks.some((x) => x.layer === m.layer)) as m (m.layer)}
              <p class="muted small">And {OPERATION_LABELS[m.layer] ?? m.layer}, set in the recipe.</p>
            {/each}
            <label class="check"><input type="checkbox" checked={!!recipe.alphabet} disabled={!anyIupac && !recipe.alphabet} onchange={(e) => set(edit.setIupacToN(recipe!, e.currentTarget.checked))} />
              <span>IUPAC → N{#if !anyIupac}<span class="muted">: none in {b.assembly}</span>{/if}</span></label>
          </fieldset>
          </div>
        </div>

        <div class="stage">
          <div class="tabs band" role="tablist">
            {#each TABS as [k, label] (k)}
              <button type="button" role="tab" aria-selected={tab === k} class:here={tab === k} onclick={() => show(k)}>{label}</button>
            {/each}
          </div>
          <div class="pane">

          {#if tab === "catalog"}
            <div class="table-wrap flat">
              <table class="editions">
                <thead>
                  <tr><th class="edit"><span class="sr">Edit</span></th><th>Edition</th><th class="num">Sequences</th><th class="num">Length</th><th>Operations</th><th>Published by</th>
                    <th class="num" title="Sequences that differ from your recipe's">Differ</th></tr>
                </thead>
                <tbody>
                  {#each listed as f (f.edition)}
                    {@const x = diffs?.get(f.edition)}
                    <tr class:here={d?.equals === f.edition}>
                      <td class="edit"><button type="button" class="icon" title={`Edit ${f.edition}'s recipe`} aria-label={`Edit ${f.edition}'s recipe`}
                                  onclick={() => loadEdition(f)}><Icon name="load" /></button></td>
                      <td class="edition"><a href={editionHref(f.edition)} target="_blank" rel="noopener" title={`${f.edition}, in a new tab`}>{f.edition}</a>{#if f.patch_release !== null}<span class="tag">p{f.patch_release}</span>{/if}</td>
                      <td class="num">{n(f.n_sequences)}</td>
                      <td class="num">{bp(f.total_length, true)}</td>
                      <td>{#each f.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{:else}<span class="muted">none</span>{/each}</td>
                      <td class="muted">{(publishers.get(f.edition) ?? []).join(", ")}</td>
                      <td class="num">{#if !x}<span class="muted">–</span>{:else if !x.length}<span class="ok" title="Your recipe makes this edition"><Icon name="check" /></span>{:else}{n(x.length)}{/if}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {:else if tab === "guide"}
            <p class="muted small">Choices commonly made for an analysis goal. Switch each one on or off.</p>
            <ul class="guide">
              {#each shelf.guide as g (g.goal)}
                {@const on = g.has(recipe, ctx)}
                <li>
                  <label class="switch">
                    <input type="checkbox" role="switch" checked={on} aria-checked={on}
                           onchange={(e) => set(g.set(recipe!, e.currentTarget.checked, ctx))} />
                    <span class="goal">{g.goal}</span>
                  </label>
                  <span class="muted">{g.choice}</span>
                </li>
              {/each}
            </ul>
          {:else if tab === "recipe"}
            {@const stem = d?.equals ?? "design"}
            <div class="filebar">
              <p class="muted small">The recipe, in full: edit it for anything the shelf doesn't show.</p>
              <span class="actions">
                <button type="button" class="icon" title="Copy the recipe" aria-label="Copy the recipe"
                        onclick={() => copy("recipe", jsonText)}><Icon name={copied === "recipe" ? "check" : "copy"} /></button>
                <button type="button" class="icon" title={`Download ${stem}.recipe.json`} aria-label={`Download ${stem}.recipe.json`}
                        onclick={() => download(`${stem}.recipe.json`, jsonText, "application/json")}><Icon name="download" /></button>
                <button type="button" class="icon" title="Copy a link to this recipe" aria-label="Copy a link to this recipe"
                        onclick={() => copy("link", location.href)}><Icon name={copied === "link" ? "check" : "link"} /></button>
              </span>
            </div>
            <textarea class="paste" rows="24" spellcheck="false" aria-label="Recipe JSON" value={jsonText}
                      oninput={(e) => fromJson(e.currentTarget.value)}></textarea>
            {#if jsonError}<p class="bad small">Not JSON: {jsonError}</p>{/if}
          {:else if tab === "export"}
            {@const stem = d?.equals ?? "design"}
            {@const orders = [...ORDERS, ...(d?.equals ? published.get(d.equals) ?? [] : [])
              .map((x) => [`file:${x.target}`, `as in ${x.publisher}: ${x.alias}`] as [string, string])]}
            {@const o = orders.some(([k]) => k === order) ? order : "karyotypic"}
            {@const made = d ? file(format, d, t.places, o) : { missing: "needs a recipe that compiles" }}
            <div class="filebar">
              <div class="formats" role="radiogroup" aria-label="File">
                {#each FORMATS as [k, label] (k)}
                  <button type="button" role="radio" aria-checked={format === k} class:here={format === k} onclick={() => (format = k)}>{label}</button>
                {/each}
              </div>
              <span class="actions">
                <label class="order" title="The order of the sequences in the file">
                  <Icon name="sort" />
                  <select aria-label="Order" value={o} onchange={(e) => (order = e.currentTarget.value)}>
                    {#each orders as [k, label] (k)}<option value={k}>{label}</option>{/each}
                  </select>
                </label>
                <button type="button" class="icon" disabled={!("text" in made)} title="Copy to the clipboard" aria-label="Copy to the clipboard"
                        onclick={() => "text" in made && copy("file", made.text)}><Icon name={copied === "file" ? "check" : "copy"} /></button>
                <button type="button" class="icon" disabled={!("text" in made)} title={`Download ${filename(format, stem)}`} aria-label={`Download ${filename(format, stem)}`}
                        onclick={() => "text" in made && download(filename(format, stem), made.text, format === "seqcol" ? "application/json" : "text/plain")}><Icon name="download" /></button>
              </span>
            </div>
            {#if "text" in made}
              <textarea class="paste" rows="24" spellcheck="false" readonly aria-label={FORMATS.find(([k]) => k === format)![1]} value={made.text}></textarea>
              <p class="muted small">{n(d?.rows.length ?? 0)} sequences, {orders.find(([k]) => k === o)![1]}.{#if format === "seqcol"}
                A seqcol digest depends on the order: this file's differs from the one in Info unless the order is by name.{/if}</p>
            {:else}
              <p class="muted">This file {made.missing}.</p>
            {/if}
          {:else}
            <h3>Current recipe</h3>
            {#if attempted.error}
              <p class="bad">The recipe doesn't compile: {message(attempted.error)}</p>
            {:else if d}
              <dl class="ids">
                <dt>Sequences</dt><dd>{n(d.rows.length)}, {bp(d.rows.reduce((s, r) => s + r.length, 0), true)}
                  <ul class="plain muted">{#each Object.entries(Object.groupBy(d.rows, (r) => ops(r.operations))) as [o, rs] (o)}<li>{n(rs!.length)} {o}</li>{/each}</ul></dd>
                {#if d.novel.length}
                  <dt>Digests</dt><dd class="bad">{n(d.novel.length)} sequences the catalog has never built, so their digests need their bases:
                    {d.novel.slice(0, 5).map((r) => `${r.name} (${r.root_id} ${ops(r.operations)})`).join(", ")}{d.novel.length > 5 ? ", …" : ""}</dd>
                {:else}
                  <dt>Edition digest</dt><dd><Digest value={d.id!} /><div class="muted">doesn't depend on the order of the sequences</div></dd>
                  <dt>Seqcol digest</dt><dd><Digest value={d.seqcolDigest!} /><div class="muted">with the sequences in order by name</div></dd>
                {/if}
                <!-- Names and lengths only: known even when some digests aren't. -->
                <dt>Coordinate system digest</dt><dd><Digest value={coordinateSystem(d.rows)} /><div class="muted">its names and lengths, in any order, whatever the bases</div></dd>
              </dl>
            {/if}
            <div class="notes">
              <h3>Notes</h3>
              {#each shelf.notes as [section, items] (section)}
                <h4>{section}</h4>
                <dl>{#each items as [term, note] (term)}<dt>{term}</dt><dd>{note}</dd>{/each}</dl>
              {/each}
            </div>
          {/if}
          </div>
        </div>
      </div>
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
