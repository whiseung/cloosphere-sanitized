<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	import CitationBadge from '../CitationBadge.svelte';
	import { decodeString, type Citation } from '$lib/utils/citations';

	export let id;
	export let token;
	export let onClick: Function = () => {};

	const citationsStore = getContext<Writable<Citation[]> | undefined>('citations');

	let attributes: Record<string, string | undefined> = {};

	function extractAttributes(input: string): Record<string, string> {
		const regex = /(\w+)="([^"]*)"/g;
		let match;
		let attrs: Record<string, string> = {};
		while ((match = regex.exec(input)) !== null) {
			attrs[match[1]] = match[2];
		}
		return attrs;
	}

	$: attributes = extractAttributes(token.text);
	$: decodedTitle = decodeString(attributes.title ?? '');
	$: index = Number.parseInt(attributes.data ?? '0', 10);
	$: citation = citationsStore && index > 0 ? $citationsStore?.[index - 1] : undefined;
</script>

{#if attributes.title !== 'N/A'}
	{#if citation}
		<CitationBadge {index} {citation} messageId={`inline-${id}`} />
	{:else}
		<button
			type="button"
			class="cloo-inline-source"
			title={decodedTitle}
			aria-label={`Citation ${attributes.data ?? ''}: ${decodedTitle}`}
			on:click={() => {
				onClick(id, attributes.data);
			}}
		>
			{attributes.data ?? ''}
		</button>
	{/if}
{/if}

<style>
	.cloo-inline-source {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 1.25rem;
		height: 1.25rem;
		padding: 0 0.375rem;
		margin: 0 0.125rem;
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-neutral-hovered);
		color: var(--cloo-text-primary);
		border: 1px solid var(--cloo-border-subtle);
		font-size: 0.6875rem;
		font-weight: 600;
		line-height: 1;
		cursor: pointer;
		vertical-align: baseline;
		transition: background-color 120ms ease;
	}
	.cloo-inline-source:hover {
		background: var(--cloo-surface-hover);
	}
	.cloo-inline-source:focus-visible {
		outline: 2px solid var(--cloo-focus-ring);
		outline-offset: 2px;
	}
</style>
