<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	export let checked = false;
	export let label = 'Radio';
	export let value: string | number = 'radio';
	export let name: string | undefined = undefined;
	export let id: string | undefined = undefined;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let required = false;
	export let className = '';
	export let ariaLabel: string | undefined = undefined;
	export let ariaLabelledby: string | undefined = undefined;
	export let ariaDescribedby: string | undefined = undefined;

	const dispatch = createEventDispatcher<{
		change: {
			checked: boolean;
			value: string | number;
			name: string | undefined;
		};
	}>();

	function handleChange(event: Event) {
		if (disabled || loading) {
			return;
		}

		const target = event.currentTarget as HTMLInputElement;
		checked = target.checked;

		dispatch('change', {
			checked,
			value,
			name
		});
	}
</script>

<label
	class={`cloo-radio ${checked ? 'is-checked' : 'is-unchecked'} ${disabled ? 'is-disabled' : ''} ${loading ? 'is-loading' : ''} ${error ? 'is-error' : ''} ${className}`.trim()}
>
	<input
		class="cloo-radio__input"
		type="radio"
		{id}
		{name}
		{value}
		{checked}
		disabled={disabled || loading}
		required={required && !disabled && !loading}
		aria-busy={loading ? 'true' : undefined}
		aria-label={ariaLabel}
		aria-labelledby={ariaLabelledby}
		aria-describedby={ariaDescribedby}
		{...$$restProps}
		on:change={handleChange}
	/>

	<span class="cloo-radio__control" aria-hidden="true">
		{#if loading}
			<svg class="cloo-radio__spinner" viewBox="0 0 24 24" fill="none">
				<circle class="cloo-radio__spinner-track" cx="12" cy="12" r="9" />
				<path class="cloo-radio__spinner-head" d="M12 3a9 9 0 0 1 9 9" />
			</svg>
		{:else if checked}
			<span class="cloo-radio__dot" />
		{/if}
	</span>

	{#if label}
		<span class="cloo-radio__label text-sm leading-5">{label}</span>
	{/if}
</label>

<style>
	.cloo-radio {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: var(--cloo-space-1-5);
		padding-block: var(--cloo-space-2);
		width: fit-content;
		max-width: 100%;
		color: var(--cloo-text-primary);
		cursor: pointer;
	}

	.cloo-radio.is-disabled,
	.cloo-radio.is-loading {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.cloo-radio__input {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		margin: 0;
		opacity: 0;
		cursor: inherit;
	}

	.cloo-radio__control {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: var(--cloo-space-4);
		height: var(--cloo-space-4);
		border: var(--cloo-border-width-default) solid var(--cloo-control-border);
		border-radius: 50%;
		background-color: var(--cloo-bg-surface);
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			box-shadow 150ms ease,
			color 150ms ease;
	}

	.cloo-radio.is-unchecked:hover:not(.is-disabled):not(.is-loading) .cloo-radio__control {
		background-color: var(--cloo-bg-neutral-hovered);
	}

	.cloo-radio.is-checked .cloo-radio__control {
		border-color: var(--cloo-color-info);
		color: var(--cloo-color-info);
	}

	.cloo-radio.is-error .cloo-radio__control {
		border-color: var(--cloo-color-danger);
	}

	.cloo-radio.is-error.is-checked .cloo-radio__control {
		color: var(--cloo-color-danger);
	}

	.cloo-radio__input:focus-visible + .cloo-radio__control {
		outline: none;
		box-shadow: 0 0 0 2px var(--cloo-bg-surface), 0 0 0 4px var(--cloo-focus-ring);
	}

	.cloo-radio.is-error .cloo-radio__input:focus-visible + .cloo-radio__control {
		box-shadow:
			0 0 0 1px var(--cloo-color-danger-border),
			0 0 0 3px var(--cloo-bg-surface),
			0 0 0 5px var(--cloo-color-danger);
	}

	.cloo-radio__dot {
		width: var(--cloo-space-2);
		height: var(--cloo-space-2);
		border-radius: 50%;
		background-color: currentColor;
	}

	.cloo-radio__label {
		color: inherit;
		min-width: 0;
		word-break: break-word;
	}

	.cloo-radio__spinner {
		width: calc(var(--cloo-space-4) - var(--cloo-space-1));
		height: calc(var(--cloo-space-4) - var(--cloo-space-1));
		color: inherit;
	}

	.cloo-radio__spinner-track,
	.cloo-radio__spinner-head {
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
	}

	.cloo-radio__spinner-track {
		opacity: 0.25;
	}

	.cloo-radio__spinner-head {
		animation: cloo-radio-spin 1s linear infinite;
		transform-origin: center;
	}

	@keyframes cloo-radio-spin {
		from {
			transform: rotate(0deg);
		}

		to {
			transform: rotate(360deg);
		}
	}
</style>
