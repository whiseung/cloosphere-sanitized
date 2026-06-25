<script lang="ts">
	import { getContext, createEventDispatcher, onMount } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	import { models } from '$lib/stores';
	import Selector from '$lib/components/common/Selector.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher();

	export let value: string = '';
	export let aiModelId: string = '';
	export let generating: boolean = false;
	export let aiDisabled: boolean = false;
	export let helpText: string = '';
	export let placeholder: string = '';
	export let className: string = '';
	/**
	 * Bindable. When omitted, defaults to true if there is no value yet (so
	 * the user sees the empty textarea), else false. External callers can
	 * `bind:expanded` to drive this from a parent trigger (e.g. the Tool
	 * Description button in the redesigned DbSphere Detail description bar).
	 */
	export let expanded: boolean | null = null;

	let initialized = false;

	onMount(() => {
		if (expanded === null) {
			expanded = !(value && value.trim().length > 0);
		}
		initialized = true;
	});

	$: if (initialized && value !== undefined) {
		// keep expanded state untouched on value changes
	}

	const toggle = () => {
		expanded = !expanded;
	};

	type ModelLike = { id: string; name: string; preset?: boolean; arena?: boolean };
	$: modelItems = [
		{ value: '', label: $i18n.t('Select AI Model (Default)') },
		...(($models as unknown as ModelLike[]) ?? [])
			.filter((m) => !m.preset && !m.arena)
			.map((m) => ({ value: m.id, label: m.name }))
	];
</script>

<div class="mt-2 pl-10 pr-1 {className}">
	<div class="flex items-center gap-1 mb-1">
		<button
			type="button"
			class="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition"
			on:click={toggle}
		>
			<span>{$i18n.t('Tool Description')}</span>
			{#if expanded}
				<ChevronUp strokeWidth="2.5" className="size-3" />
			{:else}
				<ChevronDown strokeWidth="2.5" className="size-3" />
			{/if}
		</button>

		{#if expanded}
			<button
				type="button"
				class="flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded
					text-violet-500 hover:text-violet-600 dark:text-violet-400 dark:hover:text-violet-300
					hover:bg-violet-50 dark:hover:bg-violet-950/30 transition disabled:opacity-40"
				disabled={generating || aiDisabled}
				on:click={() => dispatch('generate')}
				title={$i18n.t('Generate with AI')}
			>
				{#if generating}
					<svg class="size-3 animate-spin" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
						<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
					</svg>
				{:else}
					<SparklesSolid className="size-3" />
				{/if}
				<span>AI</span>
			</button>

			<div class="text-xs" title={$i18n.t('AI Generation Model')}>
				<Selector
					size="sm"
					searchEnabled={true}
					items={modelItems}
					bind:value={aiModelId}
				/>
			</div>
		{:else if value}
			<span class="text-xs text-gray-400 dark:text-gray-500 truncate max-w-[60%]" title={value}>
				{value}
			</span>
		{/if}
	</div>

	{#if expanded}
		<div transition:slide={{ duration: 200, easing: quintOut, axis: 'y' }}>
			{#if helpText}
				<p class="text-xs text-gray-400 dark:text-gray-500 mb-1.5">{helpText}</p>
			{/if}
			<textarea
				class="w-full text-xs bg-transparent border border-gray-200 dark:border-gray-700
					rounded px-2 py-1.5 outline-none resize-none
					focus:border-gray-400 dark:focus:border-gray-500"
				rows="3"
				{placeholder}
				bind:value
				on:input={() => dispatch('change')}
			></textarea>
		</div>
	{/if}
</div>
