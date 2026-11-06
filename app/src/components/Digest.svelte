<script lang="ts">
  // A digest in monospace with a copy button.
  import Icon from "./Icon.svelte";

  let { value }: { value: string } = $props();
  let copied = $state(false);

  async function copy() {
    await navigator.clipboard?.writeText(value);
    copied = true;
    setTimeout(() => (copied = false), 1200);
  }
</script>

<span class="digest"><code>{value}</code><button class="copy icon" title={copied ? "Copied" : "Copy to the clipboard"} aria-label="Copy to the clipboard" type="button" onclick={copy}><Icon name={copied ? "check" : "copy"} /></button></span>
