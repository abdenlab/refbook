<script lang="ts">
  // Home: where to go. Four doors, nothing else.
  import Icon from "../components/Icon.svelte";

  const doors = [
    { href: "#/catalog", icon: "books", title: "Browse the catalog",
      text: "Every published version of each human reference assembly, and how they differ." },
    { href: "#/sequences", icon: "search", title: "Browse sequences",
      text: "Find any sequence by name, accession or digest, and every assembly it appears in." },
    { href: "#/identify", icon: "question", title: "What is my reference?",
      text: "Paste a FASTA index, sequence dictionary, or BAM or VCF header to find out which edition it is." },
    { href: "#/learn", icon: "info", title: "Learn more",
      text: "Why one genome has so many files, and how refbook tells them apart." },
  ] as const;
</script>

<section class="home">
  <h1>The human reference genome, in every edition</h1>
  <blockquote class="motto"><p>Genome: Bought the book? Which edition?</p></blockquote>
  <p class="lede">Refbook is a catalog of commonly used reference genome sequence collections, rebuilt from the original sequences.</p>
  <nav class="doors" aria-label="Start here">
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
  .home { max-width: 60rem; margin: 3rem auto 0; }
  h1 { font-size: 2rem; letter-spacing: -0.02em; margin: 0 0 0.5rem; }
  .lede { color: var(--muted); margin: 0 0 2rem; }
  .motto { position: relative; margin: 1.4rem 0 1.2rem; padding: 0.1rem 0 0.1rem 2.6rem; max-width: 36rem; }
  .motto::before {
    content: "\201C"; position: absolute; left: 0; top: -0.55rem;
    font: 700 3.6rem/1 Georgia, "Times New Roman", serif; color: var(--accent); opacity: 0.75;
  }
  .motto p { margin: 0; font: italic 1.3rem/1.4 Georgia, "Times New Roman", serif; color: var(--text); }
  .doors { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
  .door {
    display: grid; grid-template-columns: auto 1fr; grid-template-rows: auto 1fr; column-gap: 1rem; row-gap: 0.35rem;
    padding: 1.4rem 1.5rem; min-height: 9rem; color: var(--text);
    background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
    transition: border-color 120ms, box-shadow 120ms, transform 120ms;
  }
  .door:hover { text-decoration: none; border-color: var(--accent); box-shadow: 0 2px 12px rgb(0 0 0 / 0.06); transform: translateY(-1px); }
  .glyph { grid-row: span 2; font-size: 1.6rem; color: var(--accent); line-height: 1; padding-top: 0.1rem; }
  .title { font-weight: 600; font-size: 1.1rem; display: inline-flex; align-items: center; gap: 0.4rem; }
  .title :global(.icon) { color: var(--muted); font-size: 0.9em; transition: transform 120ms; }
  .door:hover .title :global(.icon) { transform: translateX(3px); color: var(--accent); }
  .text { color: var(--muted); font-size: 0.95rem; }
  @media (max-width: 640px) {
    .home { margin-top: 1.5rem; }
    h1 { font-size: 1.5rem; }
    .doors { grid-template-columns: 1fr; }
  }
</style>
