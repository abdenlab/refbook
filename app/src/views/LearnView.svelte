<script lang="ts">
  // Learn more: why one genome has many files, shown with chromosome 1, and how refbook tells them apart.
  import { books, editionHref, type Book } from "../data/books.ts";
  import type { Catalog } from "../data/catalog.ts";
  import { OPERATION_LABELS, type ManifestRow } from "../data/editions.ts";
  import { measure } from "../data/meter.ts";
  import { n } from "../format.ts";
  import ErrorBox from "../components/ErrorBox.svelte";

  let { cat }: { cat: Catalog } = $props();

  type Member = { book: string; assembly_name: string; genbank_accession: string; role: string; assigned_molecule: string | null };

  /** Chromosome 1 in each book: its root, and its versions across the book's editions (a name, the operations on
   * its bases), each with the editions that have it. */
  async function chr1(bs: Book[]) {
    const [rows, members] = await Promise.all([
      cat.table<ManifestRow>("manifests.parquet"), cat.table<Member>("assembly_members.parquet")]);
    return [...bs].sort((a, b) => b.assembly.localeCompare(a.assembly)).map((b) => {
      const root = members.find((m) => m.book === b.book && m.assembly_name === b.assembly
        && m.role === "assembled-molecule" && m.assigned_molecule === "1")?.genbank_accession;
      const labels = new Set(b.editions.map((e) => e.edition));
      const mine = rows.filter((r) => r.root_id === root && labels.has(r.edition));
      const versions = [...Map.groupBy(mine, (r) => `${r.name}\t${[...r.operations].join(" ")}`).values()]
        .map((rs) => ({ name: rs[0].name, operations: [...rs[0].operations], editions: rs.map((r) => r.edition).sort() }))
        .sort((x, y) => y.editions.length - x.editions.length || x.name.localeCompare(y.name));
      return { book: b, root, versions };
    });
  }

  const loaded = measure("learn", async () => {
    const bs = await books(cat);
    return { bs, nFiles: bs.reduce((s, b) => s + b.targets.length, 0), nEditions: bs.reduce((s, b) => s + b.editions.length, 0),
             chr1: await chr1(bs) };
  });
</script>

<section class="learn">
  <p class="crumbs"><a href="#/">Home</a> / Learn more</p>
  {#await loaded then { bs, nFiles, nEditions, chr1 }}
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

    <h2>Chromosome 1, for example</h2>
    {#each chr1 as c (c.book.book)}
      <h3 class="assembly">{c.book.assembly} <span class="muted">{c.root}</span></h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Named</th><th>Bases</th><th>In the editions</th></tr></thead>
          <tbody>
            {#each c.versions as v (v.name + v.operations.join())}
              <tr>
                <td><code>{v.name}</code></td>
                <td>{#each v.operations as o (o)}<span class="op">{OPERATION_LABELS[o] ?? o}</span>{:else}<span class="muted">as submitted</span>{/each}</td>
                <td>{#each v.editions as e, i (e)}{i ? ", " : ""}<a href={editionHref(e)}>{e}</a>{/each}</td>
              </tr>
            {/each}
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
  .learn { max-width: 60rem; margin: 0 auto; }
  .learn > p { max-width: 70ch; }
  .assembly { text-transform: none; letter-spacing: normal; font-size: 1rem; color: var(--text); margin: 1.2rem 0 0.5rem; }
  .terms { display: grid; grid-template-columns: max-content 1fr; gap: 0.5rem 1.2rem; max-width: 70ch; }
  .terms dt { font-weight: 600; }
  .terms dd { margin: 0; }
</style>
