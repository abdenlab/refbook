<script lang="ts">
  // Identify a pasted sequence list: what each sequence is, on its own
  // evidence (refbook-core identify, in the browser).
  import * as rb from "@abdenlab/refbook";
  import type { Catalog } from "../data/catalog.ts";
  import { manifest, OPERATION_LABELS } from "../data/flavors.ts";
  import { identifyTables, parseHeader, type Header } from "../data/identify.ts";
  import { n } from "../format.ts";
  import { href } from "../route.svelte.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat }: { cat: Catalog } = $props();

  const LIMIT = 500;
  let text = $state("");
  let result = $state<{ header: Header; ids: rb.Identity[] } | null>(null);
  let error = $state<unknown>(null);
  let busy = $state(false);
  let onlyNotes = $state(false);

  async function run() {
    busy = true;
    error = null;
    try {
      const header = parseHeader(text);
      const t = await identifyTables(cat);
      result = { header, ids: rb.identifySequences(header.entries, t) };
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }

  // Examples from the catalog itself, plus a sequence it doesn't have.
  async function example(kind: "fai" | "dict") {
    const rows = (await manifest(cat, "hg38-analysis-set")).filter((r) => ["chr1", "chr2", "chrY", "chrM", "chrEBV"].includes(r.name));
    const lines = rows.map((r) => (kind === "fai" ? `${r.name}\t${r.length}` : `@SQ\tSN:${r.name}\tLN:${r.length}\tM5:${r.md5}`));
    lines.push(kind === "fai" ? "phiX174\t5386" : "@SQ\tSN:chr3\tLN:198295559\tM5:00000000000000000000000000000000");
    text = (kind === "dict" ? "@HD\tVN:1.6\n" : "") + lines.join("\n") + "\n";
    await run();
  }

  const rows = $derived(result ? result.header.entries.map((e, i) => ({ e, id: result!.ids[i] })) : []);
  const shown = $derived(onlyNotes ? rows.filter((r) => r.id.notes.length || r.id.evidence === "nothing") : rows);
  const tally = $derived(Object.groupBy(rows, (r) => r.id.evidence));

  const EVIDENCE: Record<rb.Identity["evidence"], string> = {
    digest: "by digest", name_and_length: "by name and length", name: "by name only", nothing: "unknown",
  };
  const ops = (o: string[]) => (o.length ? o.map((x) => OPERATION_LABELS[x] ?? x).join(" + ") : "as submitted");
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
</script>

<section>
  <p class="crumbs"><a href="#/">Catalog</a> / Identify</p>
  <h1>Identify sequences</h1>
  <p class="lede">
    Paste a <code>.fai</code>, a chrom.sizes, a <code>.dict</code> or SAM header (<code>samtools view -H</code>), VCF
    <code>##contig</code> lines or a small FASTA. Each sequence is identified on its own evidence: a digest pins the
    sequence; a name and length give the root, and the versions of it the catalog has. Nothing leaves your browser.
  </p>
  <textarea class="paste" rows="8" spellcheck="false" aria-label="Sequence list" bind:value={text}
            placeholder={"chr1\t248956422\nchr2\t242193529\n..."}></textarea>
  <p class="controls">
    <button type="button" onclick={run} disabled={busy || !text.trim()}>{busy ? "Identifying…" : "Identify"}</button>
    <span class="muted">or try</span>
    <button type="button" onclick={() => example("fai")}>a .fai</button>
    <button type="button" onclick={() => example("dict")}>a .dict with MD5s</button>
  </p>
  {#if error}<ErrorBox {error} />{/if}

  {#if result}
    <h2>{n(rows.length)} sequences <span class="muted">({result.header.format})</span></h2>
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
  {/if}
</section>
