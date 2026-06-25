<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import XMark from '$lib/components/icons/XMark.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;

	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let name = '';
	export let description = '';
	export let badge = '';
	export let badgeTone: 'gray' | 'green' | 'blue' | 'purple' | 'amber' = 'gray';
	export let dismissible = true;

	const toneClass: Record<string, string> = {
		gray: 'bg-gray-500/15 text-gray-700 dark:text-gray-200',
		green: 'bg-green-500/15 text-green-700 dark:text-green-200',
		blue: 'bg-blue-500/15 text-blue-700 dark:text-blue-200',
		purple: 'bg-purple-500/15 text-purple-700 dark:text-purple-200',
		amber: 'bg-amber-500/15 text-amber-700 dark:text-amber-200'
	};

	$: hasDescription = !!(description && String(description).trim());
</script>

{#if hasDescription}
	<div
		class="inline-flex items-start gap-2 px-2.5 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 text-xs w-full sm:w-[22rem]"
		title={description}
	>
		<div class="flex flex-col min-w-0 flex-1 gap-0.5 py-0.5">
			<div class="flex items-center gap-1.5 min-w-0">
				{#if badge}
					<span
						class="shrink-0 px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none {toneClass[
							badgeTone
						]}"
					>
						{badge}
					</span>
				{/if}
				<span class="font-medium text-gray-800 dark:text-gray-100 truncate">
					{name}
				</span>
			</div>
			<p
				class="text-[11px] text-gray-500 dark:text-gray-400 line-clamp-2 leading-snug min-h-[1.85rem]"
			>
				{description}
			</p>
		</div>
		{#if dismissible}
			<button
				type="button"
				class="shrink-0 size-5 rounded-full flex items-center justify-center text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-200"
				aria-label={$i18n.t('Remove')}
				on:click={() => dispatch('dismiss')}
			>
				<XMark className="size-3" strokeWidth="2.5" />
			</button>
		{/if}
	</div>
{:else}
	<span
		class="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-full bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 text-xs max-w-full"
	>
		{#if badge}
			<span
				class="px-1.5 py-0.5 rounded-sm uppercase text-[10px] font-bold leading-none {toneClass[
					badgeTone
				]}"
			>
				{badge}
			</span>
		{/if}
		<span class="font-medium text-gray-800 dark:text-gray-100 truncate max-w-[14rem]">
			{name}
		</span>
		{#if dismissible}
			<button
				type="button"
				class="size-5 rounded-full flex items-center justify-center text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700 hover:text-gray-700 dark:hover:text-gray-200"
				aria-label={$i18n.t('Remove')}
				on:click={() => dispatch('dismiss')}
			>
				<XMark className="size-3" strokeWidth="2.5" />
			</button>
		{:else}
			<span class="w-1"></span>
		{/if}
	</span>
{/if}
