<script lang="ts">
  // Home: where to go. Three doors (the catalog, the Editor, identify), nothing else.
  import Icon from "../components/Icon.svelte";

  const doors = [
    { href: "#/catalog", icon: "books", title: "Browse the catalog",
      text: "Published editions of the major human reference assemblies, and every sequence in them. Learn their quirks and how they differ." },
    { href: "#/editor", icon: "load", title: "Customize your own",
      text: "Choose sequences, what they are called, and how their bases are modified. Fit to purpose." },
    { href: "#/identify", icon: "question", title: "What's my reference?",
      text: "Paste a FASTA index, sequence dictionary, or BAM or VCF header to find out which edition it describes." },
  ] as const;
</script>

<section class="home">
  <!-- <h1>The human reference genome, in every edition</h1> -->
  <blockquote class="motto"><p>Genome: Bought the book? Which edition?</p></blockquote>
  <p class="lede"><i>Refbook</i> is a catalog of commonly used reference sequence collections for genomic analysis, as published by different authorities. We call different collections derived from the same genome assembly <b>editions</b>.</p><p class="lede">Using a small rule set, <i>refbook</i> reproduces all published editions from original submitted sequences. This provenance makes editions identifiable, specifiable, comparable, and lets you reason about how they affect your analysis.</p>
  <nav class="doors three" aria-label="Start here">
    {#each doors as d (d.href)}
      <a class="door" href={d.href}>
        <span class="glyph"><Icon name={d.icon} /></span>
        <span class="title">{d.title} <Icon name="arrow" /></span>
        <span class="text">{d.text}</span>
      </a>
    {/each}
  </nav>
</section>

<style>
  .home { margin: 3rem 0 0; }
  .lede { color: var(--muted); margin: 0 0 2rem; }
  .motto { position: relative; margin: 0 0 1.6rem; padding: 0.1rem 0 0.1rem 3.6rem; }
  .motto::before {
    content: "\201C"; position: absolute; left: 0; top: -0.7rem;
    font: 700 5rem/1 Georgia, "Times New Roman", serif; color: var(--accent); opacity: 0.75;
  }
  .motto p { margin: 0; font: italic 2rem/1.3 Georgia, "Times New Roman", serif; color: var(--text); }
  @media (max-width: 640px) {
    .home { margin-top: 1.5rem; }
    .motto { padding-left: 2.6rem; }
    .motto::before { font-size: 3.6rem; top: -0.5rem; }
    .motto p { font-size: 1.45rem; }
  }
</style>
