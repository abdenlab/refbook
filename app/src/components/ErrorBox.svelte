<script lang="ts">
  import { message } from "../format.ts";

  let { error }: { error: unknown } = $props();
</script>

<div class="error"><strong>Something went wrong. </strong>{message(error)}</div>
