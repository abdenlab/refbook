<script lang="ts">
  // A digest in monospace with a copy button.
  let { value }: { value: string } = $props();
  let copied = $state(false);

  async function copy() {
    await navigator.clipboard?.writeText(value);
    copied = true;
    setTimeout(() => (copied = false), 1200);
  }
</script>

<span class="digest"><code>{value}</code><button class="copy" title="Copy" type="button" onclick={copy}>{copied ? "copied" : "copy"}</button></span>
