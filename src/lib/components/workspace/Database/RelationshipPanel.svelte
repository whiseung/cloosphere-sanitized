<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import ErdView from './ErdView.svelte';
	import type { RelationshipGraphResponse } from '$lib/apis/dbsphere';

	type I18nStore = Readable<{ t: (key: string, params?: Record<string, unknown>) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let joinGraph: RelationshipGraphResponse | null = null;
	export let loading: boolean = false;
	/** Parent passes true while a schema extraction job is running. */
	export let extracting: boolean = false;

	$: hasGraph = !!joinGraph && joinGraph.success;
	$: noRelationships =
		hasGraph &&
		joinGraph!.extracted &&
		joinGraph!.edges.length === 0 &&
		joinGraph!.nodes.length > 0;
</script>

{#if loading}
	<div class="flex h-full items-center justify-center gap-2 text-sm text-[var(--cloo-text-muted)]">
		<Spinner className="size-4" />
		{$i18n.t('Loading relationships')}
	</div>
{:else if extracting}
	<div class="flex h-full items-center justify-center gap-2 text-sm text-[var(--cloo-text-muted)]">
		<Spinner className="size-4" />
		{$i18n.t('Schema extraction in progress…')}
	</div>
{:else if !joinGraph || !joinGraph.success}
	<div class="flex h-full items-center justify-center text-sm text-[var(--cloo-text-muted)]">
		{$i18n.t('Failed to load relationships')}
	</div>
{:else if !joinGraph.extracted}
	<div class="flex h-full items-center justify-center text-sm text-[var(--cloo-text-muted)]">
		{$i18n.t('Extract the schema first to see table relationships')}
	</div>
{:else}
	<div class="flex h-full flex-col">
		{#if joinGraph.truncated}
			<div
				class="shrink-0 px-3 py-2 text-xs bg-[var(--cloo-color-info-soft,#dbeafe)] text-[var(--cloo-color-info,#155dfc)]"
			>
				{$i18n.t('Relationship graph may be incomplete (large schema)')}
			</div>
		{/if}
		{#if noRelationships}
			<div
				class="shrink-0 px-3 py-2 text-xs bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-muted)]"
			>
				{$i18n.t('No relationships detected between the extracted tables')}
			</div>
		{/if}
		<div class="flex-1 min-h-0">
			<ErdView nodes={joinGraph.nodes} edges={joinGraph.edges} />
		</div>
	</div>
{/if}
