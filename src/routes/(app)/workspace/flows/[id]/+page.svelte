<script>
	import { page } from '$app/stores';
	import FlowEditor from '$lib/components/workspace/Flows/FlowEditor.svelte';
</script>

<FlowEditor mode="edit" flowId={$page.params.id} />
