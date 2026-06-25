<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	export let state: 'unchecked' | 'checked' = 'unchecked';
	export let indeterminate: boolean = false;
	export let disabled: boolean = false;

	let _state: 'unchecked' | 'checked' = 'unchecked';

	$: _state = state;
	$: isActive = _state === 'checked' || indeterminate;
</script>

<button
	class="cloo-checkbox {isActive ? 'is-active' : 'is-inactive'}
		{disabled ? 'is-disabled' : ''}"
	on:click={() => {
		if (disabled) return;

		if (_state === 'unchecked') {
			_state = 'checked';
			dispatch('change', _state);
		} else if (_state === 'checked') {
			_state = 'unchecked';
			if (!indeterminate) {
				dispatch('change', _state);
			}
		} else if (indeterminate) {
			_state = 'checked';
			dispatch('change', _state);
		}
	}}
	type="button"
	{disabled}
>
	{#if _state === 'checked'}
		<svg
			class="w-3.5 h-3.5"
			aria-hidden="true"
			xmlns="http://www.w3.org/2000/svg"
			fill="none"
			viewBox="0 0 24 24"
		>
			<path
				stroke="currentColor"
				stroke-linecap="round"
				stroke-linejoin="round"
				stroke-width="3"
				d="m5 12 4.7 4.5 9.3-9"
			/>
		</svg>
	{:else if indeterminate}
		<svg
			class="w-3.5 h-3.5"
			aria-hidden="true"
			xmlns="http://www.w3.org/2000/svg"
			fill="none"
			viewBox="0 0 24 24"
		>
			<path
				stroke="currentColor"
				stroke-linecap="round"
				stroke-linejoin="round"
				stroke-width="3"
				d="M5 12h14"
			/>
		</svg>
	{/if}
</button>

<style>
	.cloo-checkbox {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 1rem;
		height: 1rem;
		border-radius: var(--cloo-radius-default);
		border-width: var(--cloo-border-width-default);
		border-style: solid;
		transition: all 150ms ease;
		cursor: pointer;
	}

	.cloo-checkbox:focus-visible {
		outline: none;
		box-shadow: 0 0 0 2px var(--cloo-bg-surface), 0 0 0 4px var(--cloo-focus-ring);
	}

	.cloo-checkbox.is-active {
		background-color: var(--cloo-color-info);
		border-color: var(--cloo-color-info);
		color: var(--cloo-text-inverse);
	}

	.cloo-checkbox.is-active:hover:not(.is-disabled) {
		background-color: var(--token-scale-info-700);
		border-color: var(--token-scale-info-700);
	}

	.cloo-checkbox.is-inactive {
		background-color: var(--cloo-bg-surface);
		border-color: var(--cloo-control-border);
		color: var(--cloo-text-default);
	}

	.cloo-checkbox.is-inactive:hover:not(.is-disabled) {
		background-color: var(--cloo-bg-neutral-hovered);
	}

	.cloo-checkbox.is-disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
