<script lang="ts" context="module">
	/**
	 * Per-column filter state:
	 *   - mode='all'  → no filter, every row passes
	 *   - mode='none' → every row in this column is filtered out (Clear)
	 *   - mode='set'  → only values present in `values` pass
	 *
	 * 'all' is the resting state — a fresh menu open keeps everything visible.
	 */
	export type ColumnFilter =
		| { mode: 'all' }
		| { mode: 'none' }
		| { mode: 'set'; values: Set<string> };

	export const filterIsActive = (f: ColumnFilter | undefined): boolean =>
		!!f && f.mode !== 'all';

	/** True if the given column value passes the filter. */
	export const filterAccepts = (f: ColumnFilter | undefined, v: string): boolean => {
		if (!f || f.mode === 'all') return true;
		if (f.mode === 'none') return false;
		return f.values.has(v);
	};
</script>

<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';

	import { portal } from '$lib/actions/portal';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	/** All unique stringified values present in the column. */
	export let values: string[] = [];
	/** Current filter state for this column. */
	export let filter: ColumnFilter = { mode: 'all' };
	/** Anchor element (the funnel button) — used to position the dropdown. */
	export let anchor: HTMLElement | null = null;

	const dispatch = createEventDispatcher<{
		change: { filter: ColumnFilter };
		close: void;
	}>();

	let search = '';
	let menuEl: HTMLElement | null = null;
	let position = { top: 0, left: 0 };

	$: filtered = values.filter((v) =>
		!search.trim() ? true : v.toLowerCase().includes(search.toLowerCase())
	);

	const isChecked = (v: string): boolean => {
		if (filter.mode === 'all') return true;
		if (filter.mode === 'none') return false;
		return filter.values.has(v);
	};

	const checkedCount = (): number => {
		if (filter.mode === 'all') return values.length;
		if (filter.mode === 'none') return 0;
		return filter.values.size;
	};

	const computePosition = () => {
		if (!anchor) return;
		const rect = anchor.getBoundingClientRect();
		const menuWidth = 260;
		const margin = 8;
		let left = rect.left;
		if (left + menuWidth + margin > window.innerWidth) {
			left = Math.max(margin, window.innerWidth - menuWidth - margin);
		}
		position = { top: rect.bottom + 4, left };
	};

	/** Normalize a checked-set into the smallest equivalent ColumnFilter. */
	const normalize = (checked: Set<string>): ColumnFilter => {
		if (checked.size === values.length) return { mode: 'all' };
		if (checked.size === 0) return { mode: 'none' };
		return { mode: 'set', values: checked };
	};

	const toggleValue = (value: string) => {
		const current = new Set<string>(
			filter.mode === 'all' ? values : filter.mode === 'set' ? filter.values : []
		);
		if (current.has(value)) current.delete(value);
		else current.add(value);
		dispatch('change', { filter: normalize(current) });
	};

	const selectAll = () => dispatch('change', { filter: { mode: 'all' } });
	const clearAll = () => dispatch('change', { filter: { mode: 'none' } });
	const invert = () => {
		const inverted = new Set<string>();
		values.forEach((v) => {
			if (!isChecked(v)) inverted.add(v);
		});
		dispatch('change', { filter: normalize(inverted) });
	};

	// Outside-click strategy (after several attempts at capture-phase
	// listeners failed in production):
	//  1. The menu element itself swallows mousedown via stopPropagation,
	//     so any mousedown bubbling up to the window MUST have originated
	//     outside the menu.
	//  2. The window-level mousedown listener only needs to filter out
	//     clicks on the anchor (the funnel button) — clicking the same
	//     funnel that opened the menu would otherwise toggle off and then
	//     back on as click() reaches the parent.
	//  3. `armed` gates the very click that opened the menu (RAF tick).
	let armed = false;

	const handleWindowMouseDown = (e: MouseEvent) => {
		if (!armed) return;
		const path = e.composedPath();
		if (menuEl && path.includes(menuEl)) return; // click inside the menu — keep open
		if (anchor && path.includes(anchor)) return; // funnel click — parent's toggle handles it
		dispatch('close');
	};
	const handleKeyDown = (e: KeyboardEvent) => {
		if (e.key === 'Escape') dispatch('close');
	};

	onMount(() => {
		computePosition();
		window.addEventListener('scroll', computePosition, true);
		requestAnimationFrame(() => {
			armed = true;
		});
		return () => {
			window.removeEventListener('scroll', computePosition, true);
		};
	});
</script>

<!-- Capture phase: stopPropagation calls in any ancestor cannot hide
     events from this listener — capture runs window → ... → target before
     any bubble-phase handler. We tell "inside" from "outside" via
     composedPath() (works in both phases). -->
<svelte:window
	on:mousedown|capture={handleWindowMouseDown}
	on:keydown={handleKeyDown}
	on:resize={computePosition}
/>

<!-- Portaled to body to escape the result table's overflow:auto ancestor. -->
<div
	bind:this={menuEl}
	use:portal
	class="cloo-col-filter"
	style="top: {position.top}px; left: {position.left}px"
	role="dialog"
	aria-label={$i18n.t('Filter column')}
>
	<div class="cloo-col-filter__search">
		<!-- svelte-ignore a11y-autofocus -->
		<input
			type="text"
			bind:value={search}
			placeholder={$i18n.t('Search values')}
			class="cloo-col-filter__search-input"
			autofocus
		/>
	</div>

	<div class="cloo-col-filter__actions">
		<button type="button" class="cloo-col-filter__action" on:click={selectAll}>
			{$i18n.t('Select all')}
		</button>
		<button type="button" class="cloo-col-filter__action" on:click={clearAll}>
			{$i18n.t('Clear all')}
		</button>
		<button type="button" class="cloo-col-filter__action" on:click={invert}>
			{$i18n.t('Invert')}
		</button>
	</div>

	<div class="cloo-col-filter__list">
		{#if filtered.length === 0}
			<div class="cloo-col-filter__empty">{$i18n.t('No results')}</div>
		{:else}
			{#each filtered as v (v)}
				<!-- Inline expression (not isChecked() call) so Svelte tracks the
				     `filter` dependency in {@const} re-evaluation. A function call
				     hides its body from the compiler, so updates to `filter`
				     wouldn't trigger checked-state recomputation here. -->
				{@const checked =
					filter.mode === 'all' ||
					(filter.mode === 'set' && filter.values.has(v))}
				<!-- svelte-ignore a11y-click-events-have-key-events -->
				<div
					class="cloo-col-filter__item"
					role="checkbox"
					aria-checked={checked}
					tabindex="0"
					on:click={() => toggleValue(v)}
					on:keydown={(e) => {
						if (e.key === ' ' || e.key === 'Enter') {
							e.preventDefault();
							toggleValue(v);
						}
					}}
				>
					<!-- Inline checkbox visual — drives directly off the reactive
					     `checked` derived value. Using the <Checkbox> common
					     component here caused desync because that component
					     buffers its own internal state via `$: _state = state`
					     and (being a <button>) added a second click handler. -->
					<span class="cloo-col-filter__cb" class:is-checked={checked} aria-hidden="true">
						{#if checked}
							<svg viewBox="0 0 24 24" fill="none" class="cloo-col-filter__cb-mark">
								<path
									stroke="currentColor"
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="3"
									d="m5 12 4.7 4.5 9.3-9"
								/>
							</svg>
						{/if}
					</span>
					<span class="cloo-col-filter__item-label" title={v}>
						{v === '' ? $i18n.t('(empty)') : v}
					</span>
				</div>
			{/each}
		{/if}
	</div>

	<div class="cloo-col-filter__footer">
		<span class="cloo-col-filter__count">
			{filter.mode === 'all'
				? $i18n.t('Showing all')
				: filter.mode === 'none'
					? $i18n.t('None selected')
					: `${checkedCount()} / ${values.length}`}
		</span>
	</div>
</div>

<style>
	.cloo-col-filter {
		position: fixed;
		z-index: 100;
		width: 260px;
		max-height: 380px;
		display: flex;
		flex-direction: column;
		background: var(--cloo-bg-surface, #fff);
		border: 1px solid var(--cloo-border-default, #d5d5da);
		border-radius: 8px;
		box-shadow:
			0 8px 24px rgba(0, 0, 0, 0.12),
			0 2px 6px rgba(0, 0, 0, 0.06);
		font-family: 'Pretendard Variable', 'Pretendard', sans-serif;
		font-size: 12px;
	}

	.cloo-col-filter__search {
		padding: 8px;
		border-bottom: 1px solid var(--cloo-border-subtle, #e3e4e9);
	}
	.cloo-col-filter__search-input {
		width: 100%;
		padding: 6px 8px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		border-radius: 4px;
		font-size: 12px;
		font-family: inherit;
		outline: none;
		background: var(--cloo-bg-default, #fff);
		color: var(--cloo-text-default, #1a1a1a);
	}
	.cloo-col-filter__search-input:focus {
		border-color: var(--cloo-color-primary, #155dfc);
	}

	.cloo-col-filter__actions {
		display: flex;
		gap: 4px;
		padding: 4px 8px;
		border-bottom: 1px solid var(--cloo-border-subtle, #e3e4e9);
	}
	.cloo-col-filter__action {
		font-size: 11px;
		font-weight: 500;
		color: var(--cloo-color-primary, #155dfc);
		padding: 4px 6px;
		border-radius: 3px;
		background: transparent;
		border: none;
		cursor: pointer;
	}
	.cloo-col-filter__action:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
	}

	.cloo-col-filter__list {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 4px 0;
	}
	.cloo-col-filter__item {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 5px 10px;
		cursor: pointer;
	}
	.cloo-col-filter__item:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
	}
	.cloo-col-filter__cb {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 1rem;
		height: 1rem;
		border-radius: var(--cloo-radius-default, 4px);
		border: 1px solid var(--cloo-control-border, #d5d5da);
		background: var(--cloo-bg-surface, #fff);
		color: var(--cloo-text-default, #1a1a1a);
		transition: background-color 120ms ease, border-color 120ms ease;
		pointer-events: none;
	}
	.cloo-col-filter__cb.is-checked {
		background: var(--cloo-color-info, #155dfc);
		border-color: var(--cloo-color-info, #155dfc);
		color: var(--cloo-text-inverse, #fff);
	}
	.cloo-col-filter__cb-mark {
		width: 0.875rem;
		height: 0.875rem;
	}
	.cloo-col-filter__item-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--cloo-text-default, #1a1a1a);
		font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace;
	}
	.cloo-col-filter__empty {
		padding: 12px;
		text-align: center;
		color: var(--cloo-text-muted, #6b7280);
	}

	.cloo-col-filter__footer {
		padding: 6px 10px;
		border-top: 1px solid var(--cloo-border-subtle, #e3e4e9);
		font-size: 11px;
		color: var(--cloo-text-muted, #6b7280);
	}
</style>
