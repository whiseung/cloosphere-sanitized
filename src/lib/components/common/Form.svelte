<script context="module" lang="ts">
	export type FormItem = {
		id: string;
		label: string;
		caption?: string;
		required?: boolean;
		state: boolean;
		disabled?: boolean;
		loading?: boolean;
		error?: boolean;
	};
</script>

<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import LabelBase from './LabelBase.svelte';
	import Switch from './Switch.svelte';

	export let label = '';
	export let caption = '';
	export let required = false;
	export let id: string | undefined = undefined;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let items: FormItem[] = [];
	export let className = '';

	const dispatch = createEventDispatcher<{
		change: {
			index: number;
			nextState: boolean;
			item: FormItem;
			items: FormItem[];
		};
	}>();

	$: isDisabled = disabled || loading;
	$: groupLabelId = id && label ? `${id}-label` : undefined;
	$: groupCaptionId = id && caption ? `${id}-caption` : undefined;
	$: resolvedAriaLabel = !groupLabelId
		? [label, !groupCaptionId ? caption : ''].filter(Boolean).join('. ')
		: undefined;

	function handleItemChange(index: number, nextState: boolean) {
		const item = items[index];

		if (!item) {
			return;
		}

		const nextItems = items.map((currentItem, currentIndex) =>
			currentIndex === index
				? {
						...currentItem,
						state: nextState
					}
				: currentItem
		);

		dispatch('change', {
			index,
			nextState,
			item: {
				...item,
				state: nextState
			},
			items: nextItems
		});
	}
</script>

<div class={`cloo-form ${className}`.trim()}>
	<LabelBase
		{label}
		{caption}
		{required}
		size="lg"
		labelId={groupLabelId}
		captionId={groupCaptionId}
		disabled={isDisabled}
		{loading}
		{error}
	/>

	<div
		class={`cloo-form__body ${isDisabled ? 'is-disabled' : ''} ${loading ? 'is-loading' : ''} ${error ? 'is-error' : ''}`.trim()}
		role="group"
		aria-busy={loading ? 'true' : undefined}
		aria-labelledby={groupLabelId}
		aria-describedby={groupCaptionId}
		aria-label={resolvedAriaLabel}
	>
		{#each items as item, index (item.id)}
			{@const itemLabelId = `${item.id}-label`}
			{@const itemCaptionId = item.caption ? `${item.id}-caption` : undefined}
			<div class="cloo-form__item">
				<LabelBase
					label={item.label}
					caption={item.caption ?? ''}
					required={item.required ?? false}
					size="md"
					disabled={isDisabled || Boolean(item.disabled)}
					loading={Boolean(item.loading)}
					error={Boolean(item.error)}
					labelId={itemLabelId}
					captionId={itemCaptionId}
				>
					<div slot="right">
						<Switch
							state={item.state}
							disabled={isDisabled || Boolean(item.disabled)}
							loading={Boolean(item.loading)}
							error={Boolean(item.error)}
							ariaLabelledby={itemLabelId}
							ariaDescribedby={itemCaptionId}
							on:change={(event) => {
								handleItemChange(index, event.detail);
							}}
						/>
					</div>
				</LabelBase>
			</div>
		{/each}
	</div>
</div>

<style>
	.cloo-form {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		width: 100%;
	}

	.cloo-form__body {
		display: flex;
		flex-direction: column;
		width: 100%;
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-space-3);
		background-color: var(--cloo-bg-surface);
		overflow: hidden;
	}

	.cloo-form__body.is-disabled {
		opacity: 0.8;
	}

	.cloo-form__body.is-loading {
		opacity: 0.9;
	}

	.cloo-form__body.is-error {
		border-color: var(--cloo-color-danger-border);
		box-shadow: 0 0 0 1px var(--cloo-color-danger-soft);
	}

	.cloo-form__item {
		padding:
			var(--cloo-space-2)
			calc(var(--cloo-space-4) + var(--cloo-space-2));
	}

	.cloo-form__item + .cloo-form__item {
		border-top: 1px solid var(--cloo-border-subtle);
	}
</style>
