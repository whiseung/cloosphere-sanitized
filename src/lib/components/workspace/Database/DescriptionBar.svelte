<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	/** Free-form description shown next to the title (Figma "Description bar"). */
	export let description: string = '';
	/** Workspace tag chips currently assigned to this resource. */
	export let tags: { id: string; name: string }[] = [];
	/** Snippet of the saved tool description — surfaces inline when present. */
	export let toolDescription: string = '';

	const handleEditTags = () => dispatch('editTags');
	const handleOpenToolDescription = () => dispatch('openToolDescription');
</script>

<div
	class="cloo-description-bar flex items-center gap-3 px-1 py-1 flex-wrap"
>
	{#if description}
		<p
			class="text-sm text-[var(--cloo-text-tertiary)] flex-1 min-w-[200px] truncate"
			title={description}
		>
			{description}
		</p>
	{/if}

	<div class="flex items-center gap-1.5 flex-wrap">
		{#each tags as tag (tag.id)}
			<Badge status="default" size="sm" content={tag.name} />
		{/each}
		{#if tags.length === 0}
			<Button kind="text" size="sm" on:click={handleEditTags}>
				+ {$i18n.t('Add Tag')}
			</Button>
		{:else}
			<Button kind="text" size="sm" on:click={handleEditTags}>
				{$i18n.t('Edit Tags')}
			</Button>
		{/if}

		<Button kind="outlined" size="sm" on:click={handleOpenToolDescription}>
			<SparklesSolid slot="prefix" className="size-3" />
			{toolDescription
				? $i18n.t('Tool Description')
				: $i18n.t('Add Tool Description')}
		</Button>
	</div>
</div>
