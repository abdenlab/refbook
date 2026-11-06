<script lang="ts" module>
  // The pasted list, kept for the session: leaving for a flavor's page and
  // coming back finds it still here.
  let kept: { text: string; source: string | null } | null = null;
</script>

<script lang="ts">
  // A pasted sequence list (or a file from the catalog), and three views of
  // it below: what each sequence is (refbook-core identify, in the browser),
  // how it compares with a flavor or published file, and an alias file that
  // renames it into a namespace or a flavor's names. Nothing leaves the browser.
  import * as rb from "@abdenlab/refbook";
  import { untrack } from "svelte";
  import type { Catalog } from "../data/catalog.ts";
  import { inOrder, sequenceDictionary } from "../data/exports.ts";
  import { flavors, manifest, OPERATION_LABELS, targetOrder, targets, type ManifestRow } from "../data/flavors.ts";
  import {
    aliasFile, distance, identifyTables, level2, matches, mine, parseHeader, renameAs, renameTo,
    type Header, type Match, type Mine,
  } from "../data/identify.ts";
  import { measure } from "../data/meter.ts";
  import { download, n } from "../format.ts";
  import { href } from "../route.svelte.ts";
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
      identifyTables(cat), flavors(cat), targets(cat), cat.table<ManifestRow>("manifests.parquet"),
      cat.table<{ root_id: string; namespace: string; alias: string }>("aliases.parquet"),
    ]);
    const present = new Set(aliases.map((a) => a.namespace));
    return {
      tables, fs, ts, aliases,
      manifests: Map.groupBy(all, (r) => r.flavor),
      byFlavor: Map.groupBy(ts, (t) => t.flavor),
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
  let editing = $state(true);
  let result = $state<{ header: Header; ids: rb.Identity[]; ms: Mine[] } | null>(null);
  let error = $state<unknown>(null);
  let busy = $state(false);
  let onlyNotes = $state(false);
  let copied = $state(false);

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
      editing = !header.entries.length;
    } catch (e) {
      error = e;
    } finally {
      busy = false;
      remember();
    }
  }

  /** A flavor's sequences by name, or a published file's in its own order. */
  async function rowsOf(choice: string): Promise<ManifestRow[]> {
    const t = (await targets(cat)).find((x) => x.target === choice);
    if (!t) return manifest(cat, choice);
    return inOrder(await manifest(cat, t.flavor), await targetOrder(cat, t.target));
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
  const shown = $derived(onlyNotes ? rows.filter((r) => r.id.notes.length || r.id.evidence === "nothing") : rows);
  const tally = $derived(Object.groupBy(rows, (r) => r.id.evidence));
  const digested = $derived(result ? result.ms.filter((m) => m.digested).length : 0);

  /** Every flavor, nearest first: how many sequences differ, and how many only a digest could confirm. */
  function ranked(ms: Mine[], manifests: Map<string, ManifestRow[]>) {
    return [...manifests].map(([flavor, rs]) => ({ flavor, ...distance(matches(ms, rs)) }))
      .sort((a, b) => a.missing - b.missing || a.extra - b.extra || a.unsure - b.unsure || a.flavor.localeCompare(b.flavor));
  }

  /** The published files of a flavor whose order the pasted list has. */
  async function sameOrder(flavor: string, ts: { target: string; flavor: string; publisher: string; alias: string }[]) {
    const names = result!.ms.map((m) => m.name).join("\n");
    const out = [];
    for (const t of ts.filter((x) => x.flavor === flavor)) if ((await targetOrder(cat, t.target)).join("\n") === names) out.push(t);
    return out;
  }

  const EVIDENCE: Record<rb.Identity["evidence"], string> = {
    digest: "by digest", name_and_length: "by name and length", name: "by name only", nothing: "unknown",
  };
  const KINDS: [Match["kind"], string][] = [
    ["same", "the same sequence, under the same name"],
    ["unsure", "the same root and length, under the same name: without a digest, which version can't be told"],
    ["operations", "the same root under the same name, with other bases"],
    ["different", "the same name for another sequence"],
    ["renamed", "the same sequence under another name"],
    ["a_only", "only in yours"],
    ["b_only", "only in theirs"],
  ];
  const ops = (o: string[] | null) => (o === null ? "" : o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "as submitted");
  const order = (v: boolean | null) => (v === null ? "—" : v ? "yes" : "no");
  const root = (m: Mine) => m.root_id ?? "unidentified";
  const fileName = (ts: { target: string; publisher: string; alias: string }[], s: string) => {
    const t = ts.find((x) => x.target === s);
    return t ? `${t.publisher}: ${t.alias}` : s;
  };
  function note(x: rb.Note): string {
    switch (x.kind) {
      case "unknown_digest": return `digest ${x.digest} is not in the catalog`;
      case "digests_disagree": return "its MD5 and SQ. digest are of different sequences";
      case "length_differs": return `length should be ${n(x.expected)}`;
      case "name_of_other_roots": return `the name names ${x.roots.join(", ")}`;
      case "ambiguous_name": return `the name names several roots: ${x.roots.join(", ")}`;
      case "no_root_of_this_length": return `no root of this length named so (${x.roots.join(", ")})`;
    }
  }
  const flavorsOf = (id: rb.Identity) => [...new Set(id.flavors.map((u) => u.flavor))];

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

<section class="identify-page">
  <h1>Identify sequences</h1>
  {#await ready}
    <p class="muted">Loading the catalog…</p>
  {:then { fs, ts, manifests, byFlavor, aliases, namespaces }}
    {#if editing}
      <p class="lede">
        Paste a <code>.fai</code>, a chrom.sizes, a <code>.dict</code> or SAM header (<code>samtools view -H</code>), VCF
        <code>##contig</code> lines, a small FASTA, or a seqcol collection (level 2 JSON). A digest pins a sequence; a name and length give its root.
        Nothing leaves your browser.
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
          <optgroup label="Flavors (by name)">{#each fs as f (f.flavor)}<option value={f.flavor}>{f.flavor}</option>{/each}</optgroup>
          <optgroup label="Published files (their order)">{#each ts as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}</optgroup>
        </select>
      </p>
    {:else if result}
      <p class="pasted">
        <button type="button" class="icon" title="Edit the list" aria-label="Edit the list" onclick={() => (editing = true)}><Icon name="load" /></button>
        <span><strong>{n(rows.length)} sequences</strong>, {result.header.format}{#if digested}, {digested === rows.length ? "all" : n(digested)} with digests{/if}{#if source}
          <span class="muted">{" · "}the .dict of {fileName(ts, source)}</span>{/if}</span>
      </p>
    {/if}
    {#if error}<ErrorBox {error} />{/if}

    {#if result && rows.length}
      {@const near = ranked(result.ms, manifests)}
      {@const theirs = against || near[0]?.flavor || ""}
      <div class="tabs strip" role="tablist">
        {#each TABS as [k, label] (k)}
          <button type="button" role="tab" aria-selected={tab === k} class:here={tab === k} onclick={() => show(k)}>{label}</button>
        {/each}
      </div>

      {#if tab === "identify"}
        {@const exact = near.filter((x) => x.off === 0 && x.unsure === 0)}
        {@const fits = near.filter((x) => x.off === 0 && x.unsure > 0)}
        <div class="whole" class:match={exact.length > 0}>
          {#if exact.length}
            <p><Icon name="check" /> Exactly the flavor <a href={href("flavor", exact[0].flavor)}>{exact[0].flavor}</a>, published as
              {#each byFlavor.get(exact[0].flavor) ?? [] as t, i (t.target)}{i ? "; " : ""}{t.publisher} <span class="alias">{t.alias}</span>{/each}.
              {#await sameOrder(exact[0].flavor, ts) then same}
                {@const all = byFlavor.get(exact[0].flavor) ?? []}
                {#if same.length && same.length === all.length}In {all.length > 1 ? "their" : "its"} order.{:else if same.length}In the order of {same.map((t) => t.publisher).join(" and ")}.{:else}In an order of its own.{/if}
              {/await}
            </p>
          {:else if fits.length}
            <p>The names and lengths are those of {#each fits as x, i (x.flavor)}{i ? (i === fits.length - 1 ? " or " : ", ") : ""}<a href={href("flavor", x.flavor)}>{x.flavor}</a>{/each}.
              <span class="muted">Without digests the bases can't be told apart: paste a .dict with MD5s, or FASTA, to know which.</span></p>
          {:else}
            <p>Not a flavor in the catalog. The nearest:
              {#each near.slice(0, 3) as x, i (x.flavor)}{i ? ", " : ""}<button type="button" class="link" onclick={() => { against = x.flavor; show("compare"); }}>{x.flavor}</button>
                <span class="muted">({x.missing ? `${n(x.missing)} of yours not in it` : "all of yours"}{x.extra ? `, ${n(x.extra)} more of its own` : ""})</span>{/each}.
            </p>
          {/if}
        </div>
        <p>
          {#each Object.entries(EVIDENCE) as [k, label] (k)}
            {#if tally[k as rb.Identity["evidence"]]?.length}<span class="tag">{n(tally[k as rb.Identity["evidence"]]!.length)} {label}</span>{/if}
          {/each}
          <label class="muted"><input type="checkbox" bind:checked={onlyNotes} /> only those with notes or unknown</label>
        </p>
        <div class="table-wrap">
          <table class="identify">
            <thead><tr><th>Name</th><th class="num">Length</th><th>Evidence</th><th>What it is</th><th>Used by</th><th>Notes</th></tr></thead>
            <tbody>
              {#each shown.slice(0, LIMIT) as { e, id }, i (i)}
                <tr class={`ev-${id.evidence}`}>
                  <td>{e.name ?? ""}</td>
                  <td class="num">{e.length != null ? n(e.length) : ""}</td>
                  <td>{EVIDENCE[id.evidence]}</td>
                  <td>
                    {#if id.root_id}<code>{id.root_id}</code>{/if}
                    {#if id.operations}{" "}{ops(id.operations)}
                    {:else if id.root_id}{" "}<span class="muted">{id.cognates.length > 1 ? `one of ${id.cognates.length} cataloged versions` : id.cognates.length ? "its one cataloged version" : "a version the catalog lacks"}</span>{/if}
                  </td>
                  <td>
                    {#if id.flavors.length}
                      <details><summary>{flavorsOf(id).length} flavor{flavorsOf(id).length === 1 ? "" : "s"}</summary>
                        <ul class="plain">{#each id.flavors as u (u.flavor + u.name + u.sequence)}<li><a href={href("flavor", u.flavor, "seq", u.name)}>{u.flavor}</a> as {u.name}</li>{/each}</ul>
                      </details>
                    {/if}
                  </td>
                  <td>{#each id.notes as x, j (j)}<div class="bad">{note(x)}</div>{/each}</td>
                </tr>
              {/each}
              {#if shown.length > LIMIT}<tr><td colspan="6" class="muted">and {n(shown.length - LIMIT)} more</td></tr>{/if}
            </tbody>
          </table>
        </div>

      {:else if tab === "compare"}
        <p class="exports">
          <label>Against
            <select value={theirs} onchange={(e) => { against = e.currentTarget.value; remember(); }}>
              <optgroup label="Flavors (by name)">{#each fs as f (f.flavor)}<option value={f.flavor}>{f.flavor}</option>{/each}</optgroup>
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
          <h2>What differs, sequence by sequence</h2>
          {#each KINDS as [kind, label] (kind)}
            {@const g = groups[kind] ?? []}
            {#if g.length}
              <details open={kind !== "same" && g.length <= 50}>
                <summary><strong>{n(g.length)}</strong> {label}</summary>
                <div class="table-wrap">
                  <table>
                    <tbody>
                      {#each g.slice(0, LIMIT) as m, i (i)}
                        <tr>
                          {#if m.kind === "same" || m.kind === "unsure"}<td>{m.name}</td><td><code>{m.b.root_id}</code> {ops(m.b.operations)}</td>
                          {:else if m.kind === "operations"}<td>{m.name}</td><td><code>{m.b.root_id}</code>: theirs {ops(m.b.operations)}; yours other bases</td>
                          {:else if m.kind === "different"}<td>{m.name}</td><td>yours <code>{root(m.a)}</code>; theirs <code>{m.b.root_id}</code> {ops(m.b.operations)}</td>
                          {:else if m.kind === "renamed"}<td>{m.a.name} → {m.b.name}</td><td><code>{m.b.root_id}</code> {ops(m.b.operations)}{#if m.by !== "digest"} <span class="muted">({m.by === "root" ? "same root, other bases" : "by root and length"})</span>{/if}</td>
                          {:else if m.kind === "a_only"}<td>{m.a.name}</td><td><code>{root(m.a)}</code>{#if m.a.length !== null}, {n(m.a.length)} bp{/if}</td>
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

          <h2>Seqcol comparison</h2>
          <p class="muted">GA4GH seqcol's <code>/comparison</code>: each attribute counted on its own. Shared elements come in the same order, or not (— when fewer than two are shared).
            {#if !sc.full}Not every sequence of yours has a digest, so it is compared by names{result.ms.every((m) => m.length !== null) ? " and lengths" : ""} only.{/if}</p>
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
          <details><summary>The comparison as JSON</summary><pre class="json">{JSON.stringify(sc.cmp, null, 2)}</pre></details>
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
              <optgroup label="A flavor's names">{#each fs as f (f.flavor)}<option value={f.flavor}>{f.flavor}</option>{/each}</optgroup>
              <optgroup label="A published file's names">{#each ts as t (t.target)}<option value={t.target}>{t.publisher}: {t.alias}</option>{/each}</optgroup>
            </select>
          </label>
          {#await job then renames}
            {@const file = aliasFile(renames)}
            {@const stem = `${ns ?? to}.aliases.tsv`}
            <span class="actions">
              <button type="button" class="icon" disabled={!file} title="Copy to the clipboard" aria-label="Copy to the clipboard"
                      onclick={() => copy(file)}><Icon name={copied ? "check" : "copy"} /></button>
              <button type="button" class="icon" disabled={!file} title={`Download ${stem}`} aria-label={`Download ${stem}`}
                      onclick={() => download(stem, file)}><Icon name="download" /></button>
            </span>
          {/await}
        </div>
        {#await job}
          <p class="muted">Matching…</p>
        {:then renames}
          {@const missing = renames.filter((r) => r.to === null).length}
          <p class="muted small">
            {n(renames.length - missing)} of {n(renames.length)} names have a match{#if missing}; the {n(missing)} without one are left out of the file{/if}.
            One rename a line, tab-separated, as <code>bcftools annotate --rename-chrs</code> reads it.
          </p>
          <div class="table-wrap">
            <table class="renames">
              <thead><tr><th>Yours</th><th>Becomes</th><th>Matched</th></tr></thead>
              <tbody>
                {#each renames.slice(0, LIMIT) as r, i (i)}
                  <tr>
                    <td>{r.from}</td>
                    <td>{#if r.to !== null}{r.to}{:else}<span class="muted">—</span>{/if}</td>
                    <td class:bad={r.to === null} class:muted={r.to !== null && !r.weak} class:warn={r.weak}>{r.how}</td>
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
