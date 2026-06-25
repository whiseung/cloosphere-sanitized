<script context="module" lang="ts">
	let radioGroupInstanceCount = 0;
</script>

<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import Radio from '$lib/components/common/Radio.svelte';

	type RadioOption = {
		label: string;
		value: string | number;
		disabled?: boolean;
	};

	export let value: string | number | undefined = undefined;
	export let options: RadioOption[] = [];
	export let name: string | undefined = undefined;
	export let orientation: 'horizontal' | 'vertical' = 'vertical';
	export let disabled = false;
	export let className = '';
	export let ariaLabel: string | undefined = undefined;
	export let ariaLabelledby: string | undefined = undefined;
	export let ariaDescribedby: string | undefined = undefined;

	const dispatch = createEventDispatcher<{
		change: {
			value: string | number;
			option: RadioOption;
		};
	}>();

	const fallbackName = `radio-group-${++radioGroupInstanceCount}`;

	$: groupName = name ?? fallbackName;

	function handleOptionChange(option: RadioOption) {
		if (disabled || option.disabled) return;

		value = option.value;
		dispatch('change', {
			value: option.value,
			option
		});
	}
</script>

<div
	class={`cloo-radio-group cloo-radio-group--${orientation} ${className}`.trim()}
	role="radiogroup"
	aria-label={ariaLabel}
	aria-labelledby={ariaLabelledby}
	aria-describedby={ariaDescribedby}
	aria-disabled={disabled ? 'true' : undefined}
>
	{#each options as option}
		<Radio
			name={groupName}
			label={option.label}
			value={option.value}
			checked={value === option.value}
			disabled={disabled || !!option.disabled}
			className="cloo-radio-group__item"
			on:change={() => handleOptionChange(option)}
		/>
	{/each}
</div>

<style>
	.cloo-radio-group {
		display: flex;
		min-width: 0;
	}

	.cloo-radio-group--vertical {
		flex-direction: column;
		align-items: flex-start;
		gap: var(--cloo-space-1);
	}

	.cloo-radio-group--horizontal {
		flex-direction: row;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--cloo-space-3);
	}

	.cloo-radio-group :global(.cloo-radio-group__item) {
		padding-block: 0;
	}
</style>
