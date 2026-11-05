<script lang="ts">
  // A region's bases, 60 to a line, 1-based positions in the gutter.
  import { n } from "../format.ts";
  import { lines } from "../views/bases.ts";

  let { start, bases, root }: { start: number; bases: Uint8Array; root: Uint8Array } = $props();
  const shown = $derived(lines(start, bases, root));
  const gutter = $derived(n(start + bases.length).length);
</script>

<pre class="bases">{#each shown as line (line.pos)}<div class="line"><span class="pos">{n(line.pos).padStart(gutter)}</span> {#each line.segments as s, i (i)}{#if s.kind}<span class={s.kind} title={s.submitted ? `as submitted: ${s.submitted}` : undefined}>{s.text}</span>{:else}{s.text}{/if}{/each}</div>{/each}</pre>
