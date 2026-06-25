<script>
	import { onMount } from 'svelte';
	import { guardrails } from '$lib/stores';

	import { getGuardrails } from '$lib/apis/guardrails';
	import Guardrails from '$lib/components/workspace/Guardrails.svelte';

	let loaded = false;

	onMount(async () => {
		try {
			const result = await getGuardrails(localStorage.token);
			guardrails.set(result || []);
		} catch (e) {
			console.error('Failed to load guardrails:', e);
			guardrails.set([]);
		}
		loaded = true;
	});
</script>

{#if loaded}
	<Guardrails />
{/if}
