<script lang="ts">
  // About: why one genome has many files, shown with the mitochondrion, and how refbook tells them apart.
  import { books, editionHref, type Book } from "../data/books.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { OPERATION_LABELS, type ManifestRow } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { MITOCHONDRIA } from "../data/recipeEdit.ts";
  import { n } from "../format.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat }: { cat: Catalog } = $props();

  /** The mitochondrion in each book's editions: which one (a root), what it is named and done to, each with the
   * editions that have it; and the editions with none. */
  async function mitochondria(bs: Book[]) {
    const rows = (await cat.table<ManifestRow>("manifests.parquet")).filter((r) => r.root_id in MITOCHONDRIA);
    return [...bs].sort((a, b) => b.assembly.localeCompare(a.assembly)).map((b) => {
      const labels = b.editions.map((e) => e.edition);
      const mine = rows.filter((r) => labels.includes(r.edition));
      const versions = [...Map.groupBy(mine, (r) => `${r.root_id}\t${r.name}\t${[...r.operations].join(" ")}`).values()]
        .map((rs) => ({ root: rs[0].root_id, name: rs[0].name, operations: [...rs[0].operations], editions: rs.map((r) => r.edition).sort() }))
        .sort((x, y) => x.root.localeCompare(y.root) || y.editions.length - x.editions.length || x.name.localeCompare(y.name));
      const none = labels.filter((e) => !mine.some((r) => r.edition === e)).sort();
      return { book: b, versions, none };
    });
  }

  const loaded = measure("about", async () => {
    const bs = await books(cat);
    return { bs, nFiles: bs.reduce((s, b) => s + b.targets.length, 0), nEditions: bs.reduce((s, b) => s + b.editions.length, 0),
             mito: await mitochondria(bs) };
  });
</script>

<section class="about">
  <p class="crumbs"><a href="#/">Home</a> / About</p>
  {#await loaded then { bs, nFiles, nEditions, mito }}
    <h1>One genome, many files</h1>
    <p>
      An assembly such as GRCh38 is published once, by the Genome Reference Consortium. What people align to is a
      FASTA file someone made from it, and there are many: UCSC's, Ensembl's, GENCODE's, the GRC's own analysis sets,
      Broad's, 1000 Genomes', Illumina's. They differ in which sequences they hold, what they call them, and whether
      some bases are masked or rewritten. Two files that are both "hg19" can disagree on chrM.
    </p>
    <p>
      refbook catalogs {n(nFiles)} such files of {n(bs.length)} assemblies. Rebuilt from the original sequences, they
      reduce to {n(nEditions)} distinct editions.
    </p>

    <h2>The mitochondrion, for example</h2>
    <p>
      Three different mitochondrial genomes travel as <code>chrM</code>: rCRS, the standard reference; the
      mitochondrion of a Yoruba individual, which UCSC's hg19 carries; and CHM13's own, which starts at another point
      of the circle. The same rCRS is <code>chrM</code>, <code>MT</code> or <code>chrMT</code>, depending on the file.
      Some files have none; one has two.
    </p>
    {#each mito as c (c.book.book)}
      <h3 class="assembly">{c.book.assembly}</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Mitochondrion</th><th>Named</th><th>In the editions</th></tr></thead>
          <tbody>
            {#each c.versions as v (v.root + v.name + v.operations.join())}
              <tr>
                <td class="which">{MITOCHONDRIA[v.root]} <span class="muted">{v.root}</span>{#each v.operations as o (o)} <span class="op">{OPERATION_LABELS[o] ?? o}</span>{/each}</td>
                <td><code>{v.name}</code></td>
                <td>{#each v.editions as e, i (e)}{i ? ", " : ""}<a href={editionHref(e)}>{e}</a>{/each}</td>
              </tr>
            {/each}
            {#if c.none.length}
              <tr>
                <td class="muted">none</td><td></td>
                <td>{#each c.none as e, i (e)}{i ? ", " : ""}<a href={editionHref(e)}>{e}</a>{/each}</td>
              </tr>
            {/if}
          </tbody>
        </table>
      </div>
    {/each}

    <h2>How refbook tells them apart</h2>
    <dl class="terms">
      <dt>Roots</dt>
      <dd>The original sequences, as submitted to GenBank: every release of each assembly, and the few sequences
        files add from elsewhere (EBV, decoys, HLA alleles).</dd>
      <dt>Recipes</dt>
      <dd>Each published file, written as which roots it selects, what it does to their bases (masks, IUPAC codes
        to N, padding), and what it names them.</dd>
      <dt>Editions</dt>
      <dd>What a recipe makes: a set of named sequences, identified by digest whatever its order. Files that differ
        only in order are one edition.</dd>
      <dt>Checks</dt>
      <dd>A file is cataloged only when its recipe rebuilds it, sequence by sequence, from the roots.</dd>
    </dl>
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>

<style>
  .about > p { max-width: 70ch; }
  .assembly { text-transform: none; letter-spacing: normal; font-size: 1rem; color: var(--text); margin: 1.2rem 0 0.5rem; }
  .terms { display: grid; grid-template-columns: max-content 1fr; gap: 0.5rem 1.2rem; max-width: 70ch; }
  .terms dt { font-weight: 600; }
  .which { white-space: nowrap; }
  .terms dd { margin: 0; }
</style>
