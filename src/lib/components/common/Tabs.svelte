<script context="module" lang="ts">
	export type TabState = 'default' | 'selected' | 'disabled' | 'loading' | 'error';

	export type TabItem = {
		id: string;
		label?: string;
		labelKey?: string;
		href: string;
		state?: TabState;
		ariaLabel?: string;
	};
</script>

<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import Spinner from './Spinner.svelte';

	export let items: TabItem[] = [];
	export let ariaLabel = 'Tabs';
	export let className = '';
	export let listClassName = '';
	/** `pill` (default) — rounded pill chips. `underline` — text + bottom underline
	 * (Figma 1305:12301, workspace navigation). */
	export let variant: 'pill' | 'underline' = 'pill';

	const i18n = getContext<Readable<{ t: (key: string) => string }>>('i18n');

	const disabledStates = new Set<TabState>(['disabled', 'loading']);

	function resolveState(item: TabItem): TabState {
		return item.state ?? 'default';
	}

	function handleClick(event: MouseEvent, item: TabItem) {
		if (disabledStates.has(resolveState(item))) {
			event.preventDefault();
			event.stopPropagation();
		}
	}
</script>

<nav class={`cloo-tabs is-${variant} ${className}`.trim()} aria-label={ariaLabel}>
	<div class={`cloo-tabs__list ${listClassName}`.trim()}>
		{#each items as item (item.id)}
			{@const state = resolveState(item)}
			<a
				class={`cloo-tab is-${state} is-${variant}`}
				href={item.href}
				aria-label={item.ariaLabel ?? (item.labelKey ? $i18n.t(item.labelKey) : item.label)}
				aria-current={state === 'selected' ? 'page' : undefined}
				aria-disabled={disabledStates.has(state) ? 'true' : undefined}
				aria-busy={state === 'loading' ? 'true' : undefined}
				tabindex={disabledStates.has(state) ? -1 : undefined}
				on:click={(event) => handleClick(event, item)}
			>
				{#if state === 'loading'}
					<Spinner className="cloo-tab__spinner" />
				{/if}
				<span class="cloo-tab__label">{item.labelKey ? $i18n.t(item.labelKey) : item.label}</span>
			</a>
		{/each}
	</div>
</nav>

<style>
	.cloo-tabs {
		display: flex;
		width: 100%;
		min-width: 0;
	}

	.cloo-tabs__list {
		display: flex;
		gap: var(--cloo-space-2);
		width: fit-content;
		max-width: 100%;
		overflow-x: auto;
		padding-block: var(--cloo-space-1);
		text-align: center;
		font-size: 0.8125rem;
		font-weight: 500;
		touch-action: auto;
		pointer-events: auto;
	}

	.cloo-tab {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--cloo-space-1);
		min-width: fit-content;
		flex-shrink: 0;
		padding: var(--cloo-space-1-5) var(--cloo-space-2-5);
		border: var(--cloo-border-width-default) solid var(--cloo-border-subtle);
		border-radius: 9999px;
		background: var(--cloo-bg-surface);
		color: var(--cloo-text-muted);
		line-height: 1.125rem;
		text-decoration: none;
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			color 150ms ease,
			box-shadow 150ms ease,
			opacity 150ms ease;
	}

	.cloo-tab:focus-visible {
		outline: none;
		box-shadow: 0 0 0 2px var(--cloo-bg-surface), 0 0 0 4px var(--cloo-focus-ring);
	}

	.cloo-tab:hover:not(.is-selected):not(.is-disabled):not(.is-loading) {
		background: var(--cloo-bg-neutral-hovered);
		border-color: var(--cloo-border-subtle);
		color: var(--cloo-text-default);
	}

	.cloo-tab.is-selected {
		border-color: var(--cloo-color-primary);
		background: var(--cloo-color-primary);
		color: var(--cloo-color-on-primary);
	}

	.cloo-tab.is-error {
		border-color: var(--cloo-color-danger-border);
		background: var(--cloo-color-danger-soft);
		color: var(--cloo-color-danger);
	}

	.cloo-tab.is-error:hover {
		background: var(--cloo-color-danger-softer);
		color: var(--cloo-color-danger-hover);
	}

	.cloo-tab.is-disabled,
	.cloo-tab.is-loading {
		background: var(--cloo-bg-disabled);
		border-color: transparent;
		color: var(--cloo-text-muted);
		cursor: not-allowed;
	}

	.cloo-tab.is-loading {
		cursor: progress;
	}

	.cloo-tab__label {
		display: inline-flex;
		align-items: center;
		white-space: nowrap;
	}

	.cloo-tab__spinner {
		width: 0.875rem;
		height: 0.875rem;
		flex-shrink: 0;
	}

	/* ───── Underline variant (Figma 1305:12303, workspace nav) ─────────────
	   Spacing comes from each tab's own px-3.5 py-2.5 padding (not container gap)
	   so the bottom border sits flush against the row's underline. */
	.cloo-tabs.is-underline .cloo-tabs__list {
		gap: 0;
		font-size: 0.875rem;
		font-weight: 400;
		padding-block: 0;
	}

	.cloo-tab.is-underline {
		padding: 0.625rem 0.875rem; /* py-2.5 px-3.5 — Figma spec */
		border: 0;
		border-bottom: 2px solid transparent;
		border-radius: 0;
		background: transparent;
		color: var(--cloo-text-tertiary, var(--cloo-text-muted));
		line-height: 1.25rem;
		min-width: auto;
	}

	.cloo-tab.is-underline:hover:not(.is-selected):not(.is-disabled):not(.is-loading) {
		background: transparent;
		border-bottom-color: transparent;
		color: var(--cloo-text-default);
	}

	.cloo-tab.is-underline.is-selected {
		background: transparent;
		border-color: transparent;
		border-bottom-color: var(--cloo-color-primary);
		color: var(--cloo-text-primary);
		font-weight: 600;
	}

	.cloo-tab.is-underline.is-disabled,
	.cloo-tab.is-underline.is-loading {
		background: transparent;
		color: var(--cloo-text-muted);
		border-bottom-color: transparent;
		opacity: 0.5;
	}

	.cloo-tab.is-underline.is-error {
		background: transparent;
		border-color: transparent;
		border-bottom-color: var(--cloo-color-danger);
		color: var(--cloo-color-danger);
	}
</style>
