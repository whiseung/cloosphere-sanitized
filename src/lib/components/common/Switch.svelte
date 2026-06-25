<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	export let state = true;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let className = '';
	export let ariaLabel: string | undefined = undefined;
	export let ariaLabelledby: string | undefined = undefined;
	export let ariaDescribedby: string | undefined = undefined;

	const dispatch = createEventDispatcher<{ change: boolean }>();

	function handleToggle() {
		if (disabled || loading) {
			return;
		}

		state = !state;
		dispatch('change', state);
	}
</script>

<button
	type="button"
	role="switch"
	aria-checked={state}
	aria-invalid={error ? 'true' : undefined}
	aria-busy={loading ? 'true' : undefined}
	aria-label={ariaLabel}
	aria-labelledby={ariaLabelledby}
	aria-describedby={ariaDescribedby}
	class={`cloo-switch ${state ? 'is-on' : 'is-off'} ${disabled ? 'is-disabled' : ''} ${loading ? 'is-loading' : ''} ${error ? 'is-error' : ''} ${className}`.trim()}
	disabled={disabled || loading}
	on:click={handleToggle}
>
	<span class="cloo-switch__thumb" aria-hidden="true">
		{#if loading}
			<svg class="cloo-switch__spinner" viewBox="0 0 24 24" fill="none">
				<circle class="cloo-switch__spinner-track" cx="12" cy="12" r="9" />
				<path class="cloo-switch__spinner-head" d="M12 3a9 9 0 0 1 9 9" />
			</svg>
		{:else if state}
			<svg class="cloo-switch__icon cloo-switch__icon-check" viewBox="0 0 24 24" fill="none">
				<path d="m6.75 12.75 3.5 3.5 7-7.5" />
			</svg>
		{:else}
			<svg class="cloo-switch__icon cloo-switch__icon-close" viewBox="0 0 24 24" fill="none">
				<path d="M8.25 8.25 15.75 15.75" />
				<path d="M15.75 8.25 8.25 15.75" />
			</svg>
		{/if}
	</span>
</button>

<style>
	.cloo-switch {
		display: inline-flex;
		align-items: center;
		justify-content: flex-start;
		flex-shrink: 0;
		width: 40px;
		min-width: 40px;
		height: 24px;
		padding: var(--cloo-space-1);
		border: 0;
		border-radius: 9999px;
		background-color: var(--cloo-surface-active);
		color: var(--cloo-text-muted);
		cursor: pointer;
		transition:
			background-color 150ms ease,
			box-shadow 150ms ease,
			opacity 150ms ease;
	}

	.cloo-switch.is-on {
		justify-content: flex-end;
		background-color: var(--cloo-color-info);
		color: var(--cloo-color-info);
	}

	.cloo-switch.is-on:hover:not(.is-disabled):not(.is-loading) {
		background-color: var(--token-scale-info-700);
	}

	.cloo-switch.is-off:hover:not(.is-disabled):not(.is-loading) {
		background-color: var(--cloo-border-subtle);
	}

	.cloo-switch:focus-visible {
		outline: none;
		box-shadow: 0 0 0 2px var(--cloo-bg-surface), 0 0 0 4px var(--cloo-focus-ring);
	}

	.cloo-switch.is-error {
		box-shadow: 0 0 0 1px var(--cloo-color-danger-border);
	}

	.cloo-switch.is-error:focus-visible {
		box-shadow:
			0 0 0 1px var(--cloo-color-danger-border),
			0 0 0 3px var(--cloo-bg-surface),
			0 0 0 5px var(--cloo-color-danger);
	}

	.cloo-switch.is-disabled,
	.cloo-switch.is-loading {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.cloo-switch__thumb {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border-radius: 9999px;
		background-color: var(--cloo-bg-surface);
		box-shadow: 0 1px 2px rgb(3 7 18 / 0.12);
	}

	.cloo-switch__icon,
	.cloo-switch__spinner {
		width: 10px;
		height: 10px;
	}

	.cloo-switch__icon {
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.cloo-switch__icon-check {
		width: 10px;
		height: 10px;
	}

	.cloo-switch__icon-close {
		width: 8px;
		height: 8px;
	}

	.cloo-switch__spinner-track,
	.cloo-switch__spinner-head {
		stroke: currentColor;
		stroke-width: 2;
		stroke-linecap: round;
	}

	.cloo-switch__spinner-track {
		opacity: 0.25;
	}

	.cloo-switch__spinner-head {
		animation: cloo-switch-spin 1s linear infinite;
		transform-origin: center;
	}

	@keyframes cloo-switch-spin {
		from {
			transform: rotate(0deg);
		}

		to {
			transform: rotate(360deg);
		}
	}
</style>
