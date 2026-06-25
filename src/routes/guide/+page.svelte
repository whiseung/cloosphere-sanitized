<script lang="ts">
	import { onMount, getContext } from 'svelte';

	const i18n = getContext('i18n');

	onMount(() => {
		window.location.replace('/guide/index.html');
	});
</script>

<div class="flex items-center justify-center min-h-screen bg-white">
	<div class="text-center">
		<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-4"></div>
		<p class="text-gray-600">{$i18n.t('Redirecting to documentation...')}</p>
	</div>
</div>
