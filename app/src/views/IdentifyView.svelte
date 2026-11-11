<script lang="ts" module>
  // The pasted list, kept for the session: leaving for an edition's page and
  // coming back finds it still here.
  let kept: { text: string; source: string | null } | null = null;
</script>

<script lang="ts">
  // A pasted sequence list (or a file from the catalog), and three views of
  // it below: what each sequence is (refbook-core identify, in the browser),
  // how it compares with an edition or published file, and an alias file that
  // renames it into a namespace or an edition's names. Nothing leaves the browser.
  import * as rb from "@abdenlab/refbook";
  import { untrack } from "svelte";
  import type { Catalog } from "../data/catalog.ts";
  import { editionHref, sequenceHref } from "../data/books.ts";
  import { inOrder, sequenceDictionary } from "../data/exports.ts";
  import { editions, manifest, OPERATION_LABELS, targetOrder, targets, type ManifestRow } from "../data/editions.ts";
  import {
    aliasFile, aliasJson, distance, identifyTables, level2, matches, mine, parseHeader, renameAs, renameTo,
    type Header, type Match, type Mine,
  } from "../data/identify.ts";
  import { measure } from "../data/meter.ts";
  import { download, n } from "../format.ts";
  import ErrorBox from "../components/ErrorBox.svelte";
  import Icon from "../components/Icon.svelte";

  let { cat, query }: { cat: Catalog; query: URLSearchParams } = $props();

  type Tab = "identify" | "compare" | "aliases";
  const TABS: [Tab, string][] = [["identify", "Identify"], ["compare", "Compare"], ["aliases", "Aliases"]];
  const NAMESPACES: [string, string][] = [
    ["ucsc", "UCSC (chr1)"], ["grc", "GRC (1)"], ["ensembl", "Ensembl (1)"], ["genbank", "GenBank (CM000663.2)"],
    ["refseq", "RefSeq (NC_000001.11)"], ["imgt", "IMGT/HLA allele (HLA-A*01:01:01:01)"], ["imgt_accession", "IMGT/HLA accession (HLA00001)"],
  ];

  const ready = measure("identify", async () => {
    const [tables, fs, ts, all, aliases] = await Promise.all([
      identifyTables(cat), editions(cat), targets(cat), cat.table<ManifestRow>("manifests.parquet"),
      cat.table<{ root_id: string; namespace: string; alias: string }>("aliases.parquet"),
    ]);
    const present = new Set(aliases.map((a) => a.namespace));
    return {
      tables, fs, ts, aliases,
      manifests: Map.groupBy(all, (r) => r.edition),
      byEdition: Map.groupBy(ts, (t) => t.edition),
      namespaces: NAMESPACES.filter(([k]) => present.has(k)),
    };
  });

  const asked = untrack(() => query.get("tab"));
  let tab = $state<Tab>(TABS.some(([k]) => k === asked) ? (asked as Tab) : "identify");
  let against = $state(untrack(() => query.get("against") ?? ""));
  let to = $state(untrack(() => query.get("to") ?? "ns:ucsc"));

  const LIMIT = 500;
  let text = $state("");
  let source = $state<string | null>(null);   // the catalog file the text came from, while unedited
  let result = $state<{ header: Header; ids: rb.Identity[]; ms: Mine[] } | null>(null);
  let error = $state<unknown>(null);
  let busy = $state(false);
  let copied = $state(false);
  let aliasFormat = $state<"tsv" | "json">("tsv");

  /** The page's address: the tab and choices, and the catalog file pasted (a pasted list isn't put in the URL). */
  function remember() {
    kept = { text, source };
    const q = new URLSearchParams();
    if (source) q.set("from", source);
    if (tab !== "identify") q.set("tab", tab);
    if (against) q.set("against", against);
    if (to !== "ns:ucsc") q.set("to", to);
    history.replaceState(null, "", `#/identify${q.size ? `?${q}` : ""}`);
  }
  const show = (t: Tab) => { tab = t; remember(); };

  async function run() {
    busy = true;
    error = null;
    try {
      const header = parseHeader(text);
      const { tables } = await ready;
      const ids = rb.identifySequences(header.entries, tables);
      result = { header, ids, ms: mine(header.entries, ids) };
    } catch (e) {
      error = e;
    } finally {
      busy = false;
      remember();
    }
  }

  /** An edition's sequences by name, or a published file's in its own order. */
  async function rowsOf(choice: string): Promise<ManifestRow[]> {
    const t = (await targets(cat)).find((x) => x.target === choice);
    if (!t) return manifest(cat, choice);
    return inOrder(await manifest(cat, t.edition), await targetOrder(cat, t.target));
  }

  /** Paste a file from the catalog: its .dict, with MD5s, in its order. */
  async function fill(choice: string) {
    if (!choice) return;
    const rows = await rowsOf(choice);
    if (!rows.length) { error = new Error(`the catalog has no ${choice}`); return; }
    text = sequenceDictionary(rows);
    source = choice;
    await run();
  }

  // Examples from the catalog itself, plus a sequence it doesn't have.
  async function example(kind: "fai" | "dict") {
    const rows = (await manifest(cat, "hg38-analysis-set")).filter((r) => ["chr1", "chr2", "chrY", "chrM", "chrEBV"].includes(r.name));
    const lines = rows.map((r) => (kind === "fai" ? `${r.name}\t${r.length}` : `@SQ\tSN:${r.name}\tLN:${r.length}\tM5:${r.md5}`));
    lines.push(kind === "fai" ? "phiX174\t5386" : "@SQ\tSN:chr3\tLN:198295559\tM5:00000000000000000000000000000000");
    text = (kind === "dict" ? "@HD\tVN:1.6\n" : "") + lines.join("\n") + "\n";
    source = null;
    await run();
  }

  // The list this page was opened with: a catalog file (?from=), or the one kept from before.
  untrack(() => {
    const from = query.get("from");
    if (from) fill(from);
    else if (kept?.text) { text = kept.text; source = kept.source; run(); }
  });

  const rows = $derived(result ? result.header.entries.map((e, i) => ({ e, id: result!.ids[i] })) : []);
  const digested = $derived(result ? result.ms.filter((m) => m.digested).length : 0);

  /** Every edition, nearest first: how many sequences differ, and how many only a digest could confirm. */
  function ranked(ms: Mine[], manifests: Map<string, ManifestRow[]>) {
    return [...manifests].map(([edition, rs]) => ({ edition, ...distance(matches(ms, rs)) }))
      .sort((a, b) => a.missing - b.missing || a.extra - b.extra || a.unsure - b.unsure || a.edition.localeCompare(b.edition));
  }

  /** The published files of an edition whose order the pasted list has. */
  async function sameOrder(edition: string, ts: { target: string; edition: string; publisher: string; alias: string }[]) {
    const names = result!.ms.map((m) => m.name).join("\n");
    const out = [];
    for (const t of ts.filter((x) => x.edition === edition)) if ((await targetOrder(cat, t.target)).join("\n") === names) out.push(t);
    return out;
  }

  const KINDS: [Match["kind"], string][] = [
    ["same", "share the same sequence, using the same name"],
    ["unsure", "share same length and name"],
    ["operations", "share the same name and are derived from the same root"],
    ["different", "share the same name but describe different sequences"],
    ["renamed", "share the same sequence under different names"],
    ["a_only", "exist only in your set"],
    ["b_only", "exist only in their set"],
  ];
  const ops = (o: string[] | null) => (o === null ? "" : o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "original");
  const order = (v: boolean | null) => (v === null ? "—" : v ? "yes" : "no");
  const fileName = (ts: { target: string; publisher: string; alias: string }[], s: string) => {
    const t = ts.find((x) => x.target === s);
    return t ? `${t.publisher}: ${t.alias}` : s;
  };
  /** What was done to your sequence's root, as far as its digest says: its operations, or that the catalog lacks it. */
  const yoursOps = (m: Mine) => (m.operations ? ops(m.operations) : "not in the catalog");

  function note(x: rb.Note): string {
    switch (x.kind) {
      case "unknown_digest": return `digest not in catalog`;
      case "digests_disagree": return "its MD5 and SQ. digest are of different sequences";
      case "length_differs": return `length should be ${n(x.expected)}`;
      case "name_of_other_roots": return `the name names ${x.roots.join(", ")}`;
      case "ambiguous_name": return `the name names several roots: ${x.roots.join(", ")}`;
      case "no_root_of_this_length": return `no root of this length named so (${x.roots.join(", ")})`;
    }
  }
  /** How sure a row's identity is, as its Match badge shows it. */
  function matchOf(id: rb.Identity, several: string[]) {
    if (id.evidence === "digest") return { kind: "exact", icon: "check" as const, label: "exact", title: "By digest: this sequence, base for base" };
    if (several.length) return { kind: "ambiguous", icon: "question" as const, label: "ambiguous",
      title: `Its name and length fit ${several.length} roots; a digest would tell which` };
    if (id.root_id) return { kind: "likely", icon: "question" as const, label: id.evidence === "name" ? "by name" : "by name and length",
      title: id.cognates.length > 1 ? `The root, but not which of its ${id.cognates.length} cataloged versions: a digest would tell` : "The root; a digest would confirm its bases" };
    return { kind: "unknown", icon: "info" as const, label: "unknown", title: "Nothing in the catalog matches" };
  }
  /** The roots a name and length fit, when they fit several (chrM at 16,569 bp: rCRS, or CHM13's own). */
  const severalRoots = (id: rb.Identity) =>
    id.notes.flatMap((x) => (x.kind === "ambiguous_name" ? x.roots : []));

  /** Seqcol's comparison, over the attributes the pasted list has. */
  function seqcol(ms: Mine[], theirs: ManifestRow[]) {
    const names = ms.map((m) => m.name);
    const lengths = ms.every((m) => m.length !== null) ? ms.map((m) => m.length!) : null;
    const sqs = ms.every((m) => m.sq) ? ms.map((m) => m.sq!) : null;
    const a = lengths && sqs ? rb.seqcolLevel2(names, lengths, sqs) : { names, ...(lengths ? { lengths } : {}) };
    return { cmp: rb.seqcolCompare(a, level2(theirs)), full: !!(lengths && sqs) };
  }

  async function copy(t: string) {
    await navigator.clipboard?.writeText(t);
    copied = true;
    setTimeout(() => (copied = false), 1200);
  }
</script>

<!-- Your sequence, as far as the catalog can say: its root and operations (a cataloged digest), its root (a name and
     length), or, for a digest the catalog lacks, that it isn't a cataloged sequence (its name and length's root a guess). -->
{#snippet yours(m: Mine)}
  {#if m.digested && m.operations === null}not in the catalog{#if m.root_id}{" "}<span class="muted">(its name and length fit <code>{m.root_id}</code>)</span>{/if}
  {:else if m.root_id}<code>{m.root_id}</code>{#if m.operations}{" "}{ops(m.operations)}{/if}
  {:else}unidentified{/if}
{/snippet}

<section class="identify-page">
  <p class="crumbs"><a href="#/">Home</a> / Identify</p>
  <h1>Identify sequences</h1>
  {#await ready}
    <p class="muted">Loading the catalog…</p>
  {:then { fs, ts, manifests, byEdition, aliases, namespaces }}
    <!-- The list stays as pasted: identifying shows what it is below, without hiding the box. -->
    <p class="lede">
      Paste a <code>.fai</code>, a chrom.sizes, a <code>.dict</code> or SAM header (<code>samtools view -H</code>), VCF
      <code>##contig</code> lines, a small FASTA, or a seqcol collection (level 2 JSON). A digest pins down a sequence exactly; a name and length can identify a likely root.
    </p>
    <textarea class="paste" rows="8" spellcheck="false" aria-label="Sequence list" bind:value={text} oninput={() => (source = null)}
              placeholder={"chr1\t248956422\nchr2\t242193529\n..."}></textarea>
    <p class="controls">
      <button type="button" onclick={run} disabled={busy || !text.trim()}>{busy ? "Identifying…" : "Identify"}</button>
      <span class="muted">or try</span>
      <button type="button" onclick={() => example("fai")}>a .fai</button>
      <button type="button" onclick={() => example("dict")}>a .dict with MD5s</button>
      <span class="muted">or a file from the catalog</span>
      <select aria-label="A file from the catalog" value="" onchange={(e) => fill(e.currentTarget.value)}>
        <option value="">choose…</option>
        <optgroup label="Editions (by name)">{#each fs as f (f.edition)}<option value={f.edition}>{f.edition}</option>{/each}</optgroup>
        <optgroup label="Published files (their order)">{#each ts as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}</optgroup>
      </select>
    </p>
    {#if result}
      <p class="pasted">
        <span><strong>{n(rows.length)} sequences</strong>, {result.header.format}{#if digested}, {digested === rows.length ? "all" : n(digested)} with digests{/if}{#if source}
          <span class="muted">{" · "}the .dict of {fileName(ts, source)}</span>{/if}</span>
      </p>
    {/if}
    {#if error}<ErrorBox {error} />{/if}

    {#if result && rows.length}
      {@const near = ranked(result.ms, manifests)}
      {@const theirs = against || near[0]?.edition || ""}
      <div class="tabs strip" role="tablist">
        {#each TABS as [k, label] (k)}
          <button type="button" role="tab" aria-selected={tab === k} class:here={tab === k} onclick={() => show(k)}>{label}</button>
        {/each}
      </div>

      {#if tab === "identify"}
        {@const exact = near.filter((x) => x.off === 0 && x.unsure === 0)}
        {@const fits = near.filter((x) => x.off === 0 && x.unsure > 0)}
        <!-- The sequences: a box of its own, scrolled within the page, the header kept in view. -->
        <div class="table-wrap scroller">
          <table class="identify">
            <thead><tr><th>Name</th><th class="num">Length</th><th>Match</th><th>Root</th><th>Operations</th><th>Notes</th></tr></thead>
            <tbody>
              {#each rows.slice(0, LIMIT) as { e, id }, i (i)}
                {@const several = severalRoots(id)}
                {@const m = matchOf(id, several)}
                <tr class={`m-${m.kind}`}>
                  <td>{e.name ?? ""}</td>
                  <td class="num">{e.length != null ? n(e.length) : ""}</td>
                  <!-- How sure: exact (a digest), the root but not its version (a name and length), several roots, nothing. -->
                  <td><span class={`match ${m.kind}`} title={m.title}><Icon name={m.icon} /> {m.label}</span></td>
                  <!-- The root: known (exact: a link to the sequence), or the ones a name and length fit. -->
                  <td>{#if id.root_id && id.sequence}<a href={sequenceHref(id.sequence)} title={`The sequence ${id.sequence}`}><code>{id.root_id}</code></a>
                    {:else if id.root_id}<code>{id.root_id}</code>
                    {:else if several.length}{#each several as r, j (r)}{j ? " or " : ""}<code>{r}</code>{/each}{/if}</td>
                  <!-- What was done to it: known only from a digest. -->
                  <td>{#if id.operations}{ops(id.operations)}{:else if id.root_id}<span class="muted">unknown</span>{/if}</td>

                  <td>{#each id.notes.filter((x) => x.kind !== "ambiguous_name") as x, j (j)}<div class="bad">{note(x)}</div>{/each}</td>
                </tr>
              {/each}
              {#if rows.length > LIMIT}<tr><td colspan="6" class="muted">and {n(rows.length - LIMIT)} more</td></tr>{/if}
            </tbody>
          </table>
        </div>
        <!-- What the list is, as a whole: after its sequences. -->
        <div class="whole" class:match={exact.length > 0}>
          {#if exact.length}
            <p><Icon name="check" /> Exactly the edition <a href={editionHref(exact[0].edition)}>{exact[0].edition}</a>, published as
              {#each byEdition.get(exact[0].edition) ?? [] as t, i (t.target)}{i ? "; " : ""}{t.publisher} <span class="alias">{t.alias}</span>{/each}.
              {#await sameOrder(exact[0].edition, ts) then same}
                {@const all = byEdition.get(exact[0].edition) ?? []}
                {#if same.length && same.length === all.length}In {all.length > 1 ? "their" : "its"} order.{:else if same.length}In the order of {same.map((t) => t.publisher).join(" and ")}.{:else}In an order of its own.{/if}
              {/await}
            </p>
          {:else if fits.length}
            <p>The names and lengths are those of {#each fits as x, i (x.edition)}{i ? (i === fits.length - 1 ? " or " : ", ") : ""}<a href={editionHref(x.edition)}>{x.edition}</a>{/each}.
              <span class="muted">Without digests the bases can't be told apart: paste a .dict with MD5s, or FASTA, to know which.</span></p>
          {:else}
            <p>Does not match an edition in the catalog. The most similar ones are 
              {#each near.slice(0, 3) as x, i (x.edition)}{i ? ", " : ""}<button type="button" class="link" onclick={() => { against = x.edition; show("compare"); }}>{x.edition}</button>
              {/each}.
            </p>
          {/if}
        </div>

      {:else if tab === "compare"}
        <p class="exports">
          <label>Against
            <select value={theirs} onchange={(e) => { against = e.currentTarget.value; remember(); }}>
              <optgroup label="Editions (by name)">{#each fs as f (f.edition)}<option value={f.edition}>{f.edition}</option>{/each}</optgroup>
              <optgroup label="Published files (their order)">{#each ts as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}</optgroup>
            </select>
          </label>
        </p>
        {#await measure(`compare ${theirs}`, () => rowsOf(theirs))}
          <p class="muted">Comparing…</p>
        {:then b}
          {@const ms = matches(result.ms, b)}
          {@const groups = Object.groupBy(ms, (m) => m.kind)}
          {@const sc = seqcol(result.ms, b)}
          <h2 class="act">GA4GH seqcol comparison
            <button type="button" class="icon" title="Copy the comparison (JSON)" aria-label="Copy the comparison as JSON"
                    onclick={() => copy(JSON.stringify(sc.cmp, null, 2))}><Icon name={copied ? "check" : "copy"} /></button></h2>
                    <p>Comparing against editions orders their sequences by name; against published versions uses their published order.</p>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Attribute</th><th class="num">Yours</th><th class="num">Theirs</th><th class="num">Shared</th><th>Same order</th></tr></thead>
              <tbody>
                {#each sc.cmp.attributes.a_and_b as k (k)}
                  {@const e = sc.cmp.array_elements}
                  <tr><td><code>{k}</code></td><td class="num">{n(e.a_count[k])}</td><td class="num">{n(e.b_count[k])}</td>
                    <td class="num">{n(e.a_and_b_count[k])}</td><td>{order(e.a_and_b_same_order[k])}</td></tr>
                {/each}
              </tbody>
            </table>
          </div>

          <h2>Differences by sequence</h2>
          {#each KINDS as [kind, label] (kind)}
            {@const g = groups[kind] ?? []}
            {#if g.length}
              <details class={`kind-${kind}`}>
                <summary><strong>{n(g.length)}</strong> {label}</summary>
                <div class="table-wrap">
                  <table>
                    <tbody>
                      {#each g.slice(0, LIMIT) as m, i (i)}
                        <tr>
                          {#if m.kind === "same" || m.kind === "unsure"}<td>{m.name}</td><td><code>{m.b.root_id}</code> {ops(m.b.operations)}</td>
                          {:else if m.kind === "operations"}<td>{m.name}</td><td><code>{m.b.root_id}</code>: yours: {yoursOps(m.a)}; theirs: {ops(m.b.operations)}</td>
                          {:else if m.kind === "different"}<td>{m.name}</td><td>yours: {@render yours(m.a)}; theirs: <code>{m.b.root_id}</code> {ops(m.b.operations)}</td>
                          {:else if m.kind === "renamed"}<td>{m.a.name} → {m.b.name}</td><td><code>{m.b.root_id}</code> {ops(m.b.operations)}{#if m.by === "root"} <span class="muted">(same root; yours {yoursOps(m.a)})</span>{:else if m.by !== "digest"} <span class="muted">(by root and length)</span>{/if}</td>
                          {:else if m.kind === "a_only"}<td>{m.a.name}</td><td>{@render yours(m.a)}{#if m.a.length !== null}, {n(m.a.length)} bp{/if}</td>
                          {:else}<td>{m.b.name}</td><td><code>{m.b.root_id}</code> {ops(m.b.operations)}, {n(m.b.length)} bp</td>{/if}
                        </tr>
                      {/each}
                      {#if g.length > LIMIT}<tr><td colspan="2" class="muted">and {n(g.length - LIMIT)} more</td></tr>{/if}
                    </tbody>
                  </table>
                </div>
              </details>
            {/if}
          {/each}

        {:catch e}
          <ErrorBox error={e} />
        {/await}

      {:else if tab === "aliases"}
        {@const ns = to.startsWith("ns:") ? to.slice(3) : null}
        {@const job = ns ? Promise.resolve(renameTo(result.ms, ns, aliases)) : rowsOf(to).then((b) => renameAs(matches(result!.ms, b)))}
        <div class="filebar">
          <label class="exports">Rename into
            <select value={to} onchange={(e) => { to = e.currentTarget.value; remember(); }}>
              <optgroup label="A namespace">{#each namespaces as [k, label] (k)}<option value={`ns:${k}`}>{label}</option>{/each}</optgroup>
              <optgroup label="An edition's names">{#each fs as f (f.edition)}<option value={f.edition}>{f.edition}</option>{/each}</optgroup>
              <optgroup label="A published file's names">{#each ts as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}</optgroup>
            </select>
          </label>
          {#await job then renames}
            {@const file = aliasFormat === "tsv" ? aliasFile(renames) : renames.some((r) => r.to !== null) ? aliasJson(renames) : ""}
            {@const stem = `${ns ?? to}.aliases.${aliasFormat}`}
            <span class="actions">
              <!-- Two exports: the table (tab-separated, as bcftools reads it), and a dictionary (JSON). -->
              <span class="formats" role="radiogroup" aria-label="File">
                {#each [["tsv", "aliases.tsv"], ["json", "aliases.json"]] as [k, label] (k)}
                  <button type="button" role="radio" aria-checked={aliasFormat === k} class:here={aliasFormat === k}
                          onclick={() => (aliasFormat = k as "tsv" | "json")}>{label}</button>
                {/each}
              </span>
              <button type="button" class="icon" disabled={!file} title="Copy to the clipboard" aria-label="Copy to the clipboard"
                      onclick={() => copy(file)}><Icon name={copied ? "check" : "copy"} /></button>
              <button type="button" class="icon" disabled={!file} title={`Download ${stem}`} aria-label={`Download ${stem}`}
                      onclick={() => download(stem, file, aliasFormat === "json" ? "application/json" : "text/plain")}><Icon name="download" /></button>
            </span>
          {/await}
        </div>
        {#await job}
          <p class="muted">Matching…</p>
        {:then renames}
          {@const missing = renames.filter((r) => r.to === null).length}
          <p class="muted small">
            {n(renames.length - missing)} of {n(renames.length)} names have a match{#if missing}; the unmatched sequences are excluded from the export{/if}.
          </p>
          <div class="table-wrap">
            <table class="renames">
              <thead><tr><th>Yours</th><th>Becomes</th><th>Matched</th></tr></thead>
              <tbody>
                {#each renames.slice(0, LIMIT) as r, i (i)}
                  <tr>
                    <td>{r.from}</td>
                    <td>{#if r.to !== null}{r.to}{:else}<span class="muted">—</span>{/if}</td>
                    <td><span class={`match ${r.kind === "other" ? "likely" : r.kind === "none" ? "unknown" : r.kind}`}>
                      <Icon name={r.kind === "exact" ? "check" : r.kind === "none" ? "info" : "question"} /> {r.how}</span></td>
                  </tr>
                {/each}
                {#if renames.length > LIMIT}<tr><td colspan="3" class="muted">and {n(renames.length - LIMIT)} more</td></tr>{/if}
              </tbody>
            </table>
          </div>
        {:catch e}
          <ErrorBox error={e} />
        {/await}
      {/if}
    {/if}
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>
