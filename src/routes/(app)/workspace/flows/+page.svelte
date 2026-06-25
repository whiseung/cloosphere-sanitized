<script>
	import { onMount } from 'svelte';
	import Flows from '$lib/components/workspace/Flows.svelte';

	let loaded = false;

	onMount(async () => {
		loaded = true;
	});
</script>

{#if loaded}
	<Flows />
{/if}
