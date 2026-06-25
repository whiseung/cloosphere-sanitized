<script lang="ts">
	import { getContext } from 'svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';

	const i18n = getContext('i18n');

	export let name = '';
	export let color = '';
	export let description = '';
</script>

<Input
	bind:value={name}
	label={$i18n.t('Name')}
	placeholder={$i18n.t('Group Name')}
	size="md"
	autocomplete="off"
	required
/>

<div class="mt-2">
	<Textarea
		bind:value={description}
		label={$i18n.t('Description')}
		placeholder={$i18n.t('Group Description')}
		rows={4}
		size="md"
	/>
</div>
