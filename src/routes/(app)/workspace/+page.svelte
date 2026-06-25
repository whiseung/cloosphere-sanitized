<script lang="ts">
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';
	import { hasPermission } from '$lib/utils/permissions';
	import { onMount } from 'svelte';

	onMount(() => {
		if ($user?.role !== 'admin') {
			if (hasPermission($user?.permissions?.workspace?.agents)) {
				goto('/workspace/agents');
			} else if (hasPermission($user?.permissions?.workspace?.knowledge)) {
				goto('/workspace/knowledge');
			} else if (hasPermission($user?.permissions?.workspace?.prompts)) {
				goto('/workspace/prompts');
			} else if (hasPermission($user?.permissions?.workspace?.tools)) {
				goto('/workspace/tools');
			} else {
				goto('/');
			}
		} else {
			goto('/workspace/agents');
		}
	});
</script>
