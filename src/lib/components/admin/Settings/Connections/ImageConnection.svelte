<script lang="ts">
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Cog6 from '$lib/components/icons/Cog6.svelte';
	import AddImageConnectionModal from './AddImageConnectionModal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	export let onDelete = () => {};
	export let onSubmit = () => {};

	export let url = '';
	export let key = '';
	export let config: any = {};

	let showConfigModal = false;
	let showDeleteConfirmDialog = false;

	const engineLabels: Record<string, string> = {
		openai: 'OpenAI',
		azure_openai: 'Azure OpenAI',
		gemini: 'Gemini',
		vertex_ai: 'Vertex AI'
	};

	$: engineLabel = engineLabels[config?.engine] ?? config?.engine ?? 'Unknown';
	$: displayName = config?.name || config?.model || '';
	$: displayInfo =
		config?.engine === 'vertex_ai'
			? `${config?.vertex_project_id || 'No project ID'} (${config?.vertex_location || 'us-central1'})`
			: url || 'No URL';
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		onDelete();
	}}
/>

<AddImageConnectionModal
	edit
	bind:show={showConfigModal}
	{url}
	{key}
	{config}
	onDelete={() => {
		showDeleteConfirmDialog = true;
	}}
	onSubmit={(connection) => {
		url = connection.url;
		key = connection.key;
		config = connection.config;
		onSubmit(connection);
	}}
/>

<div class="flex w-full gap-2 items-center">
	<Tooltip
		className="w-full relative"
		content={displayName ? `${engineLabel}: ${displayName}` : engineLabel}
		placement="top-start"
	>
		{#if !(config?.enable ?? true)}
			<div
				class="absolute top-0 bottom-0 left-0 right-0 opacity-60 bg-white dark:bg-gray-900 z-10"
			></div>
		{/if}
		<div class="flex w-full">
			<div class="shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400 self-center mr-2">
				{engineLabel}
			</div>
			<div class="flex-1 text-sm truncate text-gray-500 dark:text-gray-400 self-center">
				{#if displayName}
					<span class="text-gray-700 dark:text-gray-300">{displayName}</span>
					<span class="mx-1">•</span>
				{/if}
				<span class="text-xs">{displayInfo}</span>
			</div>
		</div>
	</Tooltip>

	<div class="flex gap-1">
		<Tooltip content={$i18n.t('Configure')} className="self-start">
			<button
				class="self-center p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition"
				on:click={() => {
					showConfigModal = true;
				}}
				type="button"
			>
				<Cog6 />
			</button>
		</Tooltip>
	</div>
</div>
