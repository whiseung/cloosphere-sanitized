<script lang="ts">
	import { Select } from 'bits-ui';
	import { getContext } from 'svelte';
	import { createEventDispatcher } from 'svelte';
	import type { Readable } from 'svelte/store';

	import { flyAndScale } from '$lib/utils/transitions';

	import Check from '../icons/Check.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import Search from '../icons/Search.svelte';
	import Spinner from './Spinner.svelte';

	type SelectorItem = {
		value: string;
		label: string;
		disabled?: boolean;
	};

	type I18nStore = Readable<{
		t: (key: string) => string;
	}>;

	const i18n = getContext<I18nStore>('i18n');

	const dispatch = createEventDispatcher<{
		change: {
			value: string;
			item: SelectorItem | undefined;
		};
		openChange: boolean;
	}>();

	export let value = '';
	export let placeholder = '';
	export let searchEnabled = true;
	export let searchPlaceholder = '';
	export let emptyMessage = '';
	export let size: 'sm' | 'md' = 'sm';
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let className = '';
	export let contentClassName = '';
	export let itemClassName = '';
	export let ariaLabel: string | undefined = undefined;
	export let portal: string | HTMLElement | null | undefined = undefined;

	export let items: SelectorItem[] = [
		{ value: 'mango', label: 'Mango' },
		{ value: 'watermelon', label: 'Watermelon' },
		{ value: 'apple', label: 'Apple' },
		{ value: 'pineapple', label: 'Pineapple' },
		{ value: 'orange', label: 'Orange' }
	];

	let searchValue = '';

	$: isDisabled = disabled || loading;
	// Defaults are generic — callers should pass context-specific copy via
	// `placeholder`/`searchPlaceholder` (e.g. ModelSelector overrides both).
	$: resolvedPlaceholder = placeholder || $i18n.t('Select');
	$: resolvedSearchPlaceholder = searchPlaceholder || $i18n.t('Search');
	$: resolvedEmptyMessage = emptyMessage || $i18n.t('No results found');
	$: selectedItem = items.find((item) => item.value === value);
	$: selectedLabel = selectedItem?.label ?? resolvedPlaceholder;
	$: filteredItems = searchValue.trim()
		? items.filter((item) => {
				const query = searchValue.trim().toLowerCase();
				return item.label.toLowerCase().includes(query) || item.value.toLowerCase().includes(query);
			})
		: items;
	$: triggerClass = [
		'cloo-selector__trigger',
		`is-${size}`,
		isDisabled ? 'is-disabled' : '',
		loading ? 'is-loading' : '',
		error ? 'is-error' : '',
		className
	]
		.filter(Boolean)
		.join(' ');
	$: contentClass = [
		'cloo-selector__content',
		searchEnabled ? 'has-search' : '',
		error ? 'is-error' : '',
		contentClassName
	]
		.filter(Boolean)
		.join(' ');

	function handleOpenChange(open: boolean) {
		searchValue = '';
		dispatch('openChange', open);
	}

	function handleSelectedChange(selected: { value: string } | undefined) {
		value = selected?.value ?? '';
		dispatch('change', {
			value,
			item: items.find((item) => item.value === value)
		});
	}
</script>

<Select.Root
	{items}
	{portal}
	selected={selectedItem}
	onOpenChange={handleOpenChange}
	onSelectedChange={handleSelectedChange}
>
	<Select.Trigger
		class={triggerClass}
		disabled={isDisabled}
		aria-label={ariaLabel ?? selectedLabel}
		aria-invalid={error ? 'true' : undefined}
		aria-busy={loading ? 'true' : undefined}
	>
		<span class="cloo-selector__label">{selectedLabel}</span>

		<span class="cloo-selector__icon" aria-hidden="true">
			{#if loading}
				<Spinner className={size === 'md' ? 'size-3.5' : 'size-3'} />
			{:else}
				<ChevronDown className={size === 'md' ? 'size-3.5' : 'size-3'} strokeWidth="2.25" />
			{/if}
		</span>
	</Select.Trigger>

	<Select.Content
		class={contentClass}
		style="width: min(var(--bits-select-anchor-width, 100%), calc(100vw - 2rem)); min-width: min(var(--bits-select-anchor-width, 100%), calc(100vw - 2rem)); max-width: calc(100vw - 2rem); z-index: 99999;"
		transition={flyAndScale}
		sideOffset={4}
	>
		<slot>
			{#if searchEnabled}
				<div class="cloo-selector__search">
					<span class="cloo-selector__search-icon" aria-hidden="true">
						<Search className="size-3.5" strokeWidth="2.25" />
					</span>

					<input
						bind:value={searchValue}
						class="cloo-selector__search-input"
						placeholder={resolvedSearchPlaceholder}
						aria-label={resolvedSearchPlaceholder}
						disabled={isDisabled}
					/>
				</div>
			{/if}

			<div class="cloo-selector__list" role="presentation">
				{#each filteredItems as item}
					<Select.Item
						class={`cloo-selector__item ${itemClassName}`.trim()}
						value={item.value}
						label={item.label}
						disabled={isDisabled || Boolean(item.disabled)}
					>
						<span class="cloo-selector__item-label">{item.label}</span>

						{#if value === item.value}
							<span class="cloo-selector__item-check" aria-hidden="true">
								<Check />
							</span>
						{/if}
					</Select.Item>
				{:else}
					<div class="cloo-selector__empty">{resolvedEmptyMessage}</div>
				{/each}
			</div>
		</slot>
	</Select.Content>
</Select.Root>

<style>
	:global(.cloo-selector__trigger) {
		display: inline-flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--cloo-space-2);
		width: 100%;
		min-width: 0;
		min-height: 2.25rem;
		padding: var(--cloo-space-1) var(--cloo-space-1-5);
		border: var(--cloo-border-width-default) solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
		background-color: var(--cloo-bg-surface);
		color: var(--cloo-text-primary);
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			box-shadow 150ms ease,
			color 150ms ease,
			opacity 150ms ease;
	}

	:global(.cloo-selector__trigger.is-sm) {
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
	}

	:global(.cloo-selector__trigger.is-md) {
		font-size: 0.875rem;
		line-height: 1.25rem;
		font-weight: 500;
		padding-inline: var(--cloo-space-2);
	}

	:global(.cloo-selector__trigger:hover:not(.is-disabled):not(.is-loading)) {
		background-color: var(--cloo-bg-neutral-hovered);
	}

	:global(.cloo-selector__trigger:active:not(.is-disabled):not(.is-loading)),
	:global(.cloo-selector__trigger[data-state='open']:not(.is-disabled):not(.is-loading)) {
		background-color: var(--cloo-surface-active);
	}

	:global(.cloo-selector__trigger:focus-visible) {
		outline: none;
		border-color: var(--cloo-focus-ring);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--cloo-focus-ring) 18%, transparent);
	}

	:global(.cloo-selector__trigger.is-error) {
		border-color: var(--cloo-color-danger-border);
	}

	:global(.cloo-selector__trigger.is-error:focus-visible) {
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--cloo-color-danger) 18%, transparent);
	}

	:global(.cloo-selector__trigger.is-disabled),
	:global(.cloo-selector__trigger.is-loading) {
		background-color: var(--cloo-bg-disabled);
		color: var(--cloo-text-muted);
		cursor: not-allowed;
	}

	.cloo-selector__label {
		flex: 1 1 auto;
		min-width: 0;
		text-align: left;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.cloo-selector__icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		color: inherit;
	}

	:global(.cloo-selector__content) {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-1);
		padding: var(--cloo-space-1);
		border: var(--cloo-border-width-default) solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
		background-color: var(--cloo-bg-surface);
		color: var(--cloo-text-default);
		box-shadow:
			0 1px 3px color-mix(in srgb, var(--cloo-text-default) 10%, transparent),
			0 1px 2px color-mix(in srgb, var(--cloo-text-default) 6%, transparent);
		outline: none;
	}

	:global(.cloo-selector__content.is-error) {
		border-color: var(--cloo-color-danger-border);
	}

	.cloo-selector__search {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
		padding: var(--cloo-space-2) var(--cloo-space-3);
		border-bottom: var(--cloo-border-width-default) solid var(--cloo-border-subtle);
	}

	.cloo-selector__search-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		color: var(--cloo-text-muted);
	}

	.cloo-selector__search-input {
		width: 100%;
		min-width: 0;
		border: 0;
		background: transparent;
		color: var(--cloo-text-default);
		font-size: 0.75rem;
		line-height: 1rem;
		outline: none;
	}

	.cloo-selector__search-input::placeholder {
		color: var(--cloo-text-muted);
	}

	.cloo-selector__search-input:disabled {
		cursor: not-allowed;
	}

	.cloo-selector__list {
		display: flex;
		flex-direction: column;
		max-height: 20rem;
		overflow-y: auto;
		overflow-x: hidden;
	}

	:global(.cloo-selector__item),
	.cloo-selector__empty {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
		width: 100%;
		min-width: 0;
		max-width: 100%;
		padding: var(--cloo-space-2) var(--cloo-space-3);
		border-radius: var(--cloo-radius-default);
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-default);
		background-color: transparent;
		transition:
			background-color 150ms ease,
			color 150ms ease,
			opacity 150ms ease;
	}

	:global(.cloo-selector__item) {
		cursor: pointer;
		user-select: none;
	}

	:global(.cloo-selector__item:hover),
	:global(.cloo-selector__item[data-highlighted]) {
		background-color: var(--cloo-surface-hover);
	}

	:global(.cloo-selector__item[data-selected]) {
		background-color: var(--cloo-bg-default);
	}

	:global(.cloo-selector__item[data-disabled]) {
		color: var(--cloo-text-muted);
		background-color: transparent;
		cursor: not-allowed;
		opacity: 0.7;
	}

	.cloo-selector__item-label {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cloo-selector__item-check {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		color: var(--cloo-text-muted);
	}

	.cloo-selector__empty {
		color: var(--cloo-text-muted);
	}
</style>
