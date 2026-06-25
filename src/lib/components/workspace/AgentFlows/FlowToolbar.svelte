<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import Button from '$lib/components/common/Button.svelte';

	const dispatch = createEventDispatcher();

	export let flowName: string = '';
	export let isValid: boolean = true;
	export let isSaving: boolean = false;
	export let canUndo: boolean = false;
	export let canRedo: boolean = false;
	export let mode: 'create' | 'edit' = 'edit';
	export let canWrite: boolean = true;

	function handleSave() {
		dispatch('save');
	}

	function handleValidate() {
		dispatch('validate');
	}

	function handleExport() {
		dispatch('export');
	}

	function handleImport() {
		dispatch('import');
	}

	function handleUndo() {
		dispatch('undo');
	}

	function handleRedo() {
		dispatch('redo');
	}

	function handleFitView() {
		dispatch('fitview');
	}

	function handleBack() {
		dispatch('back');
	}
</script>

<div class="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
	<!-- Left section: Back and name -->
	<div class="flex items-center gap-3">
		<button
			class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
			on:click={handleBack}
			title={$i18n.t('Back to Flows')}
		>
			<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
			</svg>
		</button>

		<div class="flex items-center gap-2">
			<div class="w-2 h-2 rounded-full {isValid ? 'bg-green-500' : 'bg-amber-500'}"></div>
			<span class="font-medium text-gray-800 dark:text-gray-200">{flowName || $i18n.t('Untitled Flow')}</span>
		</div>
	</div>

	<!-- Center section: Edit controls -->
	<div class="flex items-center gap-1">
		<button
			class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 disabled:opacity-50"
			on:click={handleUndo}
			disabled={!canUndo}
			title={$i18n.t('Undo')}
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
			</svg>
		</button>

		<button
			class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 disabled:opacity-50"
			on:click={handleRedo}
			disabled={!canRedo}
			title={$i18n.t('Redo')}
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 10h-10a8 8 0 00-8 8v2M21 10l-6 6m6-6l-6-6" />
			</svg>
		</button>

		<div class="w-px h-6 bg-gray-200 dark:bg-gray-700 mx-1"></div>

		<button
			class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
			on:click={handleFitView}
			title={$i18n.t('Fit View')}
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
			</svg>
		</button>

		<div class="w-px h-6 bg-gray-200 dark:bg-gray-700 mx-1"></div>

		<button
			class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
			on:click={handleImport}
			title={$i18n.t('Import')}
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
			</svg>
		</button>

		<button
			class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400"
			on:click={handleExport}
			title={$i18n.t('Export')}
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
			</svg>
		</button>
	</div>

	<!-- Right section: Actions -->
	<div class="flex items-center gap-1.5">
		<Button kind="outlined" size="md" on:click={handleValidate}>
			{$i18n.t('Validate')}
		</Button>

		<slot name="actions" />

		<Button kind="outlined" size="md" on:click={handleBack}>
			{$i18n.t('Cancel')}
		</Button>

		<Button kind="filled" size="md" loading={isSaving} disabled={!canWrite} on:click={handleSave}>
			{#if mode === 'edit'}
				{$i18n.t('Save & Update')}
			{:else}
				{$i18n.t('Save & Create')}
			{/if}
		</Button>
	</div>
</div>
