<script>
	import { page } from '$app/stores';
	import GuardrailEditor from '$lib/components/workspace/Guardrails/GuardrailEditor.svelte';

	$: id = $page.params.id;
</script>

{#if id}
	<GuardrailEditor {id} />
{/if}
