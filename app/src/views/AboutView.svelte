<script lang="ts">
  // About: why one genome has many files, shown with the mitochondrion, and how refbook tells them apart.
  import { books, editionHref, inCatalogOrder, type Book } from "../data/books.ts";
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
    return inCatalogOrder(bs).map((b) => {
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
      A reference genome assembly like GRCh38 is deposited by a submitter (the Genome Reference Consortium) to GenBank. 
      In practice, what users align to is not that original submission but an "analysis set" derived from it.
      There are many of these, curated by different authorities: UCSC, Ensembl, GENCODE, the Broad, 1000 Genomes, Illumina.
    </p>
    <p>Analysis sets differ in which sequences they include or exclude, how the sequences are named, and whether
      some bases are masked or rewritten. Furthermore, ancillary sequences may be included as decoys or to capture alternative alleles or known species or contaminants.
    </p>
    <p>
      <i>Refbook</i> catalogs {n(nEditions)} distinct editions covering {n(nFiles)} published collections across {n(bs.length)} genome assemblies. With a small rule set, each can be rebuilt from the original submitted sequences using a simple recipe.
    </p>

    <h2>How refbook sorts it out</h2>
    <dl class="terms">
      <dt>Roots</dt>
      <dd>The original sequences, as submitted to GenBank. These come from the releases of each assembly and ancillary sequences from elsewhere.</dd>
      <dt>Recipes</dt>
      <dd>A declarative grammar describing the roots to select, operations to apply to bases, and renaming.</dd>
      <dt>Editions</dt>
      <dd>The result of applying a recipe: a set of named sequences, ignoring the order they appear in. Published files that differ
        only in order are one edition.</dd>
      <dt>Checks</dt>
      <dd>An edition is cataloged only when its recipe reproduces each target sequence from its roots.</dd>
    </dl>

    <h2>The mitochondrion, for example</h2>
    <p>
      Three different mitochondrial genomes appear as <code>chrM</code> in the wild: rCRS, the standard reference; the
      mitochondrion of a Yoruba individual, and that of CHM13, which has the same length as rCRS but starts at another point
      along the circular genome. The rCRS sequence itself is variably called <code>chrM</code>, <code>MT</code> or <code>chrMT</code>, depending on the publisher.
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
  {:catch e}
    <ErrorBox error={e} />
  {/await}
</section>

<style>
  .assembly { text-transform: none; letter-spacing: normal; font-size: 1rem; color: var(--text); margin: 1.2rem 0 0.5rem; }
  .terms { display: grid; grid-template-columns: max-content 1fr; gap: 0.5rem 1.2rem; }
  .terms dt { font-weight: 600; }
  .which { white-space: nowrap; }
  .terms dd { margin: 0; }
</style>
