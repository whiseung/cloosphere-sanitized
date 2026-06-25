<script lang="ts">
	import { getContext, tick } from 'svelte';
	const i18n = getContext('i18n');

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Cog6 from '$lib/components/icons/Cog6.svelte';
	import AddConnectionModal from '$lib/components/AddConnectionModal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	import { connect } from 'socket.io-client';

	export let onDelete = () => {};
	export let onSubmit = () => {};

	export let pipeline = false;

	export let url = '';
	export let key = '';
	export let config: any = {};

	let showConfigModal = false;
	let showDeleteConfirmDialog = false;

	// Check if this is a Vertex AI connection
	$: isVertexAI = config?.provider_type === 'vertex-ai';
	$: displayUrl = isVertexAI
		? `Vertex AI: ${config?.project_id || 'No Project ID'} (${config?.location || 'us-central1'})`
		: url;
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		onDelete();
	}}
/>

<AddConnectionModal
	edit
	bind:show={showConfigModal}
	connection={{
		url,
		key,
		config
	}}
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
		content={isVertexAI
			? $i18n.t('Vertex AI connection: {{projectId}} ({{location}})', {
					projectId: config?.project_id || 'N/A',
					location: config?.location || 'us-central1'
				})
			: $i18n.t(`WebUI will make requests to "{{url}}/chat/completions"`, { url })}
		placement="top-start"
	>
		{#if !(config?.enable ?? true)}
			<div
				class="absolute top-0 bottom-0 left-0 right-0 opacity-60 bg-white dark:bg-gray-900 z-10"
			></div>
		{/if}
		<div class="flex w-full">
			<div class="flex-1 relative">
				{#if isVertexAI}
					<div class="w-full text-sm py-1 text-gray-600 dark:text-gray-400 {pipeline ? 'pr-8' : ''}">
						<span class="font-medium text-blue-600 dark:text-blue-400">Vertex AI</span>
						<span class="mx-1">•</span>
						<span>{config?.project_id || 'No Project ID'}</span>
						<span class="mx-1">•</span>
						<span class="text-xs">{config?.location || 'us-central1'}</span>
					</div>
				{:else}
					<input
						class=" outline-hidden w-full bg-transparent {pipeline ? 'pr-8' : ''}"
						placeholder={$i18n.t('API Base URL')}
						bind:value={url}
						autocomplete="off"
					/>
				{/if}

				{#if pipeline}
					<div class=" absolute top-0.5 right-2.5">
						<Tooltip content="Pipelines">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="currentColor"
								class="size-4"
							>
								<path
									d="M11.644 1.59a.75.75 0 0 1 .712 0l9.75 5.25a.75.75 0 0 1 0 1.32l-9.75 5.25a.75.75 0 0 1-.712 0l-9.75-5.25a.75.75 0 0 1 0-1.32l9.75-5.25Z"
								/>
								<path
									d="m3.265 10.602 7.668 4.129a2.25 2.25 0 0 0 2.134 0l7.668-4.13 1.37.739a.75.75 0 0 1 0 1.32l-9.75 5.25a.75.75 0 0 1-.71 0l-9.75-5.25a.75.75 0 0 1 0-1.32l1.37-.738Z"
								/>
								<path
									d="m10.933 19.231-7.668-4.13-1.37.739a.75.75 0 0 0 0 1.32l9.75 5.25c.221.12.489.12.71 0l9.75-5.25a.75.75 0 0 0 0-1.32l-1.37-.738-7.668 4.13a2.25 2.25 0 0 1-2.134-.001Z"
								/>
							</svg>
						</Tooltip>
					</div>
				{/if}
			</div>

			{#if !isVertexAI}
				<SensitiveInput
					inputClassName=" outline-hidden bg-transparent w-full"
					placeholder={$i18n.t('API Key')}
					bind:value={key}
				/>
			{/if}
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
