<script lang="ts" module>
  // The recipe being edited, kept for the session: leaving for an edition's page
  // and coming back (or clicking Editor) returns to it.
  let kept: { recipe: string; loaded: string } | null = null;
</script>

<script lang="ts">
  // The editor: a workbench for recipes, with the catalog to start from. A shelf on the
  // left holds every choice of the recipe, always in the same place (a choice
  // that doesn't apply is disabled, not hidden). The stage on the right shows
  // the catalog (fixed, with how far each edition is from the recipe), the
  // analysis goals, the recipe and the files it makes, and the details. The
  // recipe is compiled live by the core in the browser.
  import * as rb from "@abdenlab/refbook";
  import { untrack } from "svelte";
  import type { Catalog } from "../data/catalog.ts";
  import { decodeRecipe, design, designTables, encodeRecipe, grcNames, plainRecipe, type Recipe } from "../data/design.ts";
  import { chromSizes, ordered, ORDERS, sequenceDictionary, type Order } from "../data/exports.ts";
  import { editions, manifest, OPERATION_LABELS, targets, type Edition, type ManifestRow } from "../data/editions.ts";
  import { pairs } from "../data/identify.ts";
  import { measure } from "../data/meter.ts";
  import * as edit from "../data/recipeEdit.ts";
  import { bp, download, message, n } from "../format.ts";
  import { href } from "../route.svelte.ts";
  import Digest from "../components/Digest.svelte";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Icon from "../components/Icon.svelte";
  import { role } from "./recipe.ts";

  let { cat, query }: { cat: Catalog; query: URLSearchParams } = $props();

  const ready = $derived(measure("catalog", async () => {
    const [t, fs, ts] = await Promise.all([designTables(cat), editions(cat), targets(cat)]);
    const manifests = new Map(await Promise.all(fs.map(async (f) => [f.edition, await manifest(cat, f.edition)] as const)));
    // The catalog's order is fixed: smallest first.
    const listed = [...fs].sort((a, b) => a.n_sequences - b.n_sequences || a.edition.localeCompare(b.edition));
    const publishers = new Map([...Map.groupBy(ts, (x) => x.edition)].map(([f, xs]) => [f, [...new Set(xs.map((x) => x.publisher))]]));
    return { t, fs, listed, publishers, manifests };
  }));

  type Tab = "catalog" | "goals" | "recipe" | "export" | "info";
  const TABS: [Tab, string][] = [["catalog", "Catalog"], ["goals", "Goals"], ["recipe", "Recipe"], ["export", "Export"], ["info", "Info"]];
  type Format = "sizes" | "dict" | "seqcol";
  const FORMATS: [Format, string][] = [["sizes", "chrom.sizes"], ["dict", ".dict"], ["seqcol", "seqcol.json"]];

  let recipe = $state<Recipe | null>(null);
  let loaded = $state("");          // the recipe as last loaded, to know if it was edited
  let jsonText = $state("");
  let jsonError = $state<string | null>(null);
  // The view is made anew on each navigation, so the link is read once.
  const asked = untrack(() => (query.get("tab") === "files" ? "recipe" : query.get("tab")));
  let tab = $state<Tab>(TABS.some(([k]) => k === asked) ? (asked as Tab) : "catalog");
  let format = $state<Format>("sizes");
  let order = $state<Order>("name");
  let copied = $state<string | null>(null);

  function initial(fs: Edition[]): Recipe {
    if (kept && !query.has("r") && !query.has("from")) return JSON.parse(kept.recipe);
    try {
      const r = query.get("r");
      if (r) return decodeRecipe(r);
    } catch { /* a bad link: a new recipe */ }
    const from = fs.find((f) => f.edition === query.get("from"));
    return from ? plainRecipe(JSON.parse(from.recipe)) : edit.fromScratch();
  }

  /** The page's link: the tab, and the recipe once it has been edited or loaded. */
  function remember() {
    const q = new URLSearchParams();
    if (tab !== "catalog") q.set("tab", tab);
    if (recipe && JSON.stringify(recipe) !== JSON.stringify(edit.fromScratch())) q.set("r", encodeRecipe(recipe));
    history.replaceState(null, "", `#/${q.size ? "?" + q : ""}`);
    if (recipe) kept = { recipe: JSON.stringify(recipe), loaded };
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
    load(f ? plainRecipe(JSON.parse(f.recipe)) : edit.fromScratch());
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

  /** A file the recipe makes, or why it can't be made yet. */
  function file(k: Format, d: NonNullable<ReturnType<typeof attempt>["d"]>, places: Parameters<typeof ordered>[2]): { text: string } | { missing: string } {
    const rows = ordered(d.rows as ManifestRow[], order, places);
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

  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "as submitted");
  /** Footnotes to the shelf, under its headings: what each choice is, where it comes from. */
  const NOTES: [string, [string, string][]][] = [
    ["GRCh38", [
      ["Release", "p0 is GRCh38 as first released (GCA_000001405.15). Each patch release adds fix and novel patches; none changes the chromosomes."],
      ["Role", "Each sequence's role in the assembly, from GRC's assembly report: chromosomes (1–22, X, Y and the mitochondrion); unlocalized scaffolds, on a known chromosome at an unknown position (chr1_…_random); unplaced scaffolds, on no known chromosome (chrUn_…); alt scaffolds, alternate haplotypes of a region (…_alt); and the patches, novel (new alternates) and fix (corrections). The counts are the release's."],
      ["Name style", "Every sequence is named from one namespace: UCSC (chr1), GRC's sequence names (1), GenBank accessions (CM000663.2) or RefSeq accessions (NC_000001.11). A role's override names that role from another."],
    ]],
    ["Filters", [
      ["Placed on", "Every alt and patch is placed on the sequence it is an alternative to, or fixes. In p14 all are placed on chromosomes but 3 fix patches, which fix alt scaffolds; Ensembl and GENCODE leave those 3 out."],
    ]],
    ["Additional sequences", [
      ["EBV", `The Epstein–Barr virus genome (${edit.EBV}), in no assembly: for reads from EBV-transformed cell lines. Named chrEBV with UCSC names, by accession otherwise.`],
      ["hs38d1 decoys", `Sequence missing from GRCh38 (${edit.HS38D1}), so its reads don't land on similar sequence elsewhere. Named like chrUn_JTFH01000001v1_decoy with UCSC names, by accession otherwise.`],
      ["HLA alleles", `Alleles of the six genes hs38DH has (${edit.HLA_TYPING_GROUPS.join(", ")}) from ${edit.HLA}, named like HLA-A*01:01:01:01. Their licence (CC BY-ND) keeps refbook from hosting their bases.`],
    ]],
    ["Bases", [
      ["GRC hard-mask", "The spans GRC replaces with N in its analysis sets: duplicated centromeric and WGS arrays on chromosomes 5, 14, 19, 21 and 22, and the pseudoautosomal regions on chrY."],
      ["IUPAC → N", "Every ambiguity code (R, Y, M, …) becomes N, as some tools need."],
    ]],
  ];
  const SHORT: Record<string, string> = { ucsc: "UCSC", grc: "GRC", genbank: "GenBank", refseq: "RefSeq" };
  const PLACED = ["alt-scaffold", "fix-patch", "novel-patch"];
</script>

<section class="bench">
  {#await ready}
    <p class="muted">Loading the catalog…</p>
  {:then { t, fs, listed, publishers, manifests }}

    {#if recipe}
      {@const p = edit.primary(recipe)}
      {@const releases = [...t.assemblies].filter(([acc]) => acc.startsWith(edit.GRCH38)).sort(([a], [b]) => Number(a.split(".")[1]) - Number(b.split(".")[1]))}
      {@const latest = releases.at(-1)?.[0]}
      {@const counts = p ? t.roleCounts.get(p.assembly) : undefined}
      {@const release = p ? edit.releaseLabel(t.assemblies.get(p.assembly) ?? p.assembly, p.assembly === latest).split(" ")[0] : ""}
      {@const hlaAll = t.collections.get(edit.HLA) ?? []}
      {@const groups = edit.hlaGroups(recipe)}
      {@const attempted = attempt(recipe, t, fs)}
      {@const d = attempted.d}
      {@const diffs = d && !d.novel.length ? differences(d.rows as ManifestRow[], manifests) : null}
      {@const overrides = Object.keys(recipe.rename.by_role ?? {}).length}
      {@const placed = !!p && p.roles.some((r) => PLACED.includes(r))}
      {@const kept = edit.placedOn(recipe)}
      {@const fresh = JSON.stringify(recipe) === JSON.stringify(edit.fromScratch())}

      <div class="design workbench">
        <div class="form shelf">
          <p class="status band" class:match={!!d?.equals} aria-live="polite">
            <span class="label">Recipe:</span>
            {#if attempted.error}<span class="bad">doesn't compile</span>
            {:else if d?.equals}<Icon name="check" /><a href={href("edition", d.equals)}>{d.equals}</a>
            {:else if d}not in catalog{/if}
            <button type="button" class="icon reset" disabled={fresh} onclick={() => loadEdition(null)}
                    title={fresh ? "A new recipe: the GRCh38 chromosomes" : "Start over: a new recipe, the GRCh38 chromosomes"}
                    aria-label="Start over with a new recipe"><Icon name="reset" /></button>
          </p>
          <div class="pane">
          <fieldset>
            <legend><b>GRCh38</b></legend>
            <div class="group names-head">
              <label class="release"><strong>Release</strong>
                <select value={p?.assembly ?? ""} onchange={(e) => set(edit.setRelease(recipe!, e.currentTarget.value))}>
                  {#if !p}<option value="" disabled>none</option>{/if}
                  {#each releases as [acc, name] (acc)}<option value={acc} title={acc}>{edit.releaseLabel(name, acc === latest)}</option>{/each}
                </select>
              </label>
              <span class="picker">
                <strong class="ns-label">Name style</strong>
                <button type="button" class="icon" disabled={!overrides} onclick={() => set(edit.clearRoleNames(recipe!))}
                        title={overrides ? `Clear ${overrides === 1 ? "the override" : `${overrides} overrides`}: every role by the name style` : "No overrides"}
                        aria-label="Clear the name overrides"><Icon name="reset" /></button>
                <select class="naming" aria-label="Names of all sequences" value={recipe.rename.namespace}
                        onchange={(e) => set(edit.setNamespace(recipe!, e.currentTarget.value))}>
                  {#each edit.NAMESPACES as x (x)}<option value={x} title={edit.NAMESPACE_LABELS[x]}>{SHORT[x]}</option>{/each}
                </select>
              </span>
            </div>
            <div class="group cols muted small"><span>Role</span><span class="naming">Name override</span></div>
            {#each edit.ROLES_SHOWN as r (r)}
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
                  {#each edit.NAMESPACES as x (x)}<option value={x} title={edit.NAMESPACE_LABELS[x]}>{SHORT[x]}</option>{/each}
                </select>
              </div>
            {/each}
          </fieldset>

          <fieldset disabled={!placed} class:off={!placed}>
            <legend>Filters</legend>
            <p class="small">Include alts and patches placed on</p>
            {#each edit.PARENT_TYPES as type (type)}
              <label class="check"><input type="checkbox" checked={kept.includes(type)}
                disabled={kept.length === 1 && kept.includes(type)}
                onchange={(e) => set(edit.setPlacedOn(recipe!, type, e.currentTarget.checked))} />
                {type === "chromosome" ? "chromosomes" : "other scaffolds"}</label>
            {/each}
          </fieldset>

          <fieldset>
            <legend>Additional sequences</legend>
            <label class="check"><input type="checkbox" checked={edit.hasEbv(recipe)} onchange={(e) => set(edit.setEbv(recipe!, e.currentTarget.checked))} />
              <span>EBV <span class="muted">(<code>{edit.EBV}</code>)</span></span></label>
            <label class="check"><input type="checkbox" checked={edit.hasDecoys(recipe)} onchange={(e) => set(edit.setDecoys(recipe!, e.currentTarget.checked))} />
              <span>hs38d1 decoys <span class="muted">({n(t.roleCounts.get(edit.HS38D1)?.get("unplaced-scaffold") ?? 0)})</span></span></label>
            <label class="check"><input type="checkbox" checked={groups.length > 0}
              onchange={(e) => set(edit.setHla(recipe!, e.currentTarget.checked ? edit.HLA_TYPING_GROUPS : [], hlaAll))} />
              <span>HLA alleles <span class="muted">({edit.hlaKind(recipe) === "custom" ? `${groups.length} genes, set in the recipe` : "six genes"} from {edit.HLA})</span></span></label>
            {#if edit.others(recipe).length}<p class="muted small">And {edit.others(recipe).length} more entries, set in the recipe.</p>{/if}
          </fieldset>

          <fieldset>
            <legend>Bases</legend>
            <label class="check"><input type="checkbox" checked={edit.hasMask(recipe, "hardmask_grc")} onchange={(e) => set(edit.setMask(recipe!, "hardmask_grc", e.currentTarget.checked))} /> GRC hard-mask</label>
            <label class="check"><input type="checkbox" checked={!!recipe.alphabet} onchange={(e) => set(edit.setIupacToN(recipe!, e.currentTarget.checked))} /> IUPAC → N</label>
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
                      <td class="edition"><a href={href("edition", f.edition)} target="_blank" rel="noopener" title={`${f.edition}, in a new tab`}>{f.edition}</a>{#if f.patch_release !== null}<span class="tag">p{f.patch_release}</span>{/if}</td>
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
          {:else if tab === "goals"}
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
            {@const made = d ? file(format, d, t.places) : { missing: "needs a recipe that compiles" }}
            <div class="filebar">
              <div class="formats" role="radiogroup" aria-label="File">
                {#each FORMATS as [k, label] (k)}
                  <button type="button" role="radio" aria-checked={format === k} class:here={format === k} onclick={() => (format = k)}>{label}</button>
                {/each}
              </div>
              <span class="actions">
                <label class="order" title="The order of the sequences in the file">
                  <Icon name="sort" />
                  <select aria-label="Order" bind:value={order}>
                    {#each ORDERS as [k, label] (k)}<option value={k}>{label}</option>{/each}
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
              <p class="muted small">{n(d?.rows.length ?? 0)} sequences, {ORDERS.find(([k]) => k === order)![1]}.{#if format === "seqcol"}
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
              </dl>
            {/if}
            <div class="notes">
              <h3>Notes</h3>
              {#each NOTES as [section, items] (section)}
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
