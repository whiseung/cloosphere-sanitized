<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Button from '$lib/components/common/Button.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import { models } from '$lib/stores';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let show: boolean = false;
	export let value: string = '';
	export let aiModelId: string = '';
	export let aiDisabled: boolean = false;
	export let placeholder: string = '';
	export let saving: boolean = false;
	export let generating: boolean = false;
	/** When false (unsaved/required state) the editor can't be dismissed —
	 * Close/Cancel are hidden so the user is nudged to fill it in. */
	export let dismissible: boolean = true;

	let draftValue = '';
	let draftAiModelId = '';

	// Seed the draft on open so the user can Cancel without losing the saved value.
	$: if (show) {
		draftValue = value;
		draftAiModelId = aiModelId;
	}

	$: modelItems = (
		($models ?? []) as Array<{ id: string; name?: string; preset?: boolean; arena?: boolean }>
	)
		.filter((m) => !m?.preset && !(m?.arena ?? false))
		.map((m) => ({ value: m.id, label: m.name ?? m.id }));

	$: dropdownItems = [
		{ value: '', label: $i18n.t('AI Model (Default)') },
		...modelItems
	];

	const handleAiModelChange = (e: CustomEvent<{ value: string | number }>) => {
		draftAiModelId = String(e.detail.value);
	};

	const handleClose = () => {
		dispatch('close');
	};

	const handleCancel = () => {
		handleClose();
	};

	const handleSave = () => {
		aiModelId = draftAiModelId;
		value = draftValue;
		dispatch('save', { value: draftValue, aiModelId: draftAiModelId });
	};

	const handleGenerate = () => {
		if (generating || aiDisabled) return;
		// Surface the user's current draft model choice so the parent can use
		// it when calling /tasks/generate.
		aiModelId = draftAiModelId;
		dispatch('generate');
	};
</script>

{#if show}
	<section
		class="cloo-tool-desc-inline flex flex-col rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)]"
	>
		<!-- Header -->
		<header
			class="flex items-start justify-between px-6 py-3 border-b border-[var(--cloo-border-subtle)]"
		>
			<div class="flex-1 min-w-0">
				<h2 class="text-base font-semibold text-[var(--cloo-text-primary)]">
					{$i18n.t('Tool Description')}
				</h2>
				<p class="text-[11px] leading-snug text-[var(--cloo-text-tertiary)] mt-0.5">
					{$i18n.t(
						'The agent reads this to decide when to query this database. Leave it empty and the agent may skip this database even when relevant.'
					)}
				</p>
			</div>
			{#if dismissible}
				<button
					type="button"
					class="p-1.5 rounded-full hover:bg-[var(--cloo-surface-hover)]"
					aria-label={$i18n.t('Close')}
					on:click={handleClose}
				>
					<svg
						class="size-5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			{/if}
		</header>

		<!-- Body -->
		<div class="px-3.5 py-3 flex flex-col gap-2.5">
			<div class="flex items-start gap-2">
				<div class="flex-1 min-w-0">
					<Selector
						value={draftAiModelId}
						items={dropdownItems}
						size="sm"
						placeholder={$i18n.t('AI Model (Default)')}
						on:change={handleAiModelChange}
					/>
				</div>
				<Button
					kind="outlined"
					size="md"
					loading={generating}
					disabled={generating || aiDisabled}
					on:click={handleGenerate}
				>
					<SparklesSolid slot="prefix" className="size-3.5" />
					{$i18n.t('Generate')}
				</Button>
			</div>

			<Textarea
				size="sm"
				rows={4}
				placeholder={placeholder ||
					$i18n.t('e.g. Use for sales data, revenue reports, and customer order queries.')}
				bind:value={draftValue}
			/>
		</div>

		<!-- Footer -->
		<footer
			class="flex items-center justify-end gap-2 px-3.5 py-3 border-t border-[var(--cloo-border-subtle)]"
		>
			{#if dismissible}
				<Button kind="outlined" size="md" on:click={handleCancel}>
					{$i18n.t('Cancel')}
				</Button>
			{/if}
			<Button
				kind="filled"
				size="md"
				loading={saving}
				disabled={saving}
				on:click={handleSave}
			>
				{$i18n.t('Save')}
			</Button>
		</footer>
	</section>
{/if}
