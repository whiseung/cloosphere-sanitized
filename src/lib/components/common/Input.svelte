<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import LabelBase from './LabelBase.svelte';
	import Spinner from './Spinner.svelte';

	export let value = '';
	export let label = '';
	export let caption = '';
	export let placeholder = '';
	export let required = false;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let readOnly = false;
	export let size: 'sm' | 'md' = 'sm';
	export let type: 'text' | 'email' | 'password' | 'search' | 'number' | 'url' | 'tel' = 'text';
	export let id: string | undefined = undefined;
	export let name: string | undefined = undefined;
	export let autocomplete: string | undefined = undefined;
	export let className = '';
	export let inputClassName = '';
	export let ariaLabel: string | undefined = undefined;
	export let ariaLabelledby: string | undefined = undefined;
	export let ariaDescribedby: string | undefined = undefined;

	const dispatch = createEventDispatcher();

	$: inputId = id;
	$: captionId = id && caption ? `${id}-caption` : undefined;
	$: labelId = id && label ? `${id}-label` : undefined;
	$: isDisabled = disabled || loading;
	$: isFilled = String(value ?? '').length > 0;
	$: resolvedAriaLabel = ariaLabel ?? (!ariaLabelledby && !labelId && label ? label : undefined);
	$: resolvedAriaDescribedby = ariaDescribedby ?? captionId;
	$: fieldStateClass = [
		'cloo-input__field',
		`is-${size}`,
		isFilled ? 'is-filled' : '',
		readOnly ? 'is-readonly' : '',
		isDisabled ? 'is-disabled' : '',
		loading ? 'is-loading' : '',
		error ? 'is-error' : '',
		className
	]
		.filter(Boolean)
		.join(' ');

	function handleInput(event: Event) {
		value = (event.currentTarget as HTMLInputElement).value;
		dispatch('input', event);
	}
</script>

<div class="cloo-input">
	{#if label || caption || required || $$slots.right}
		<LabelBase
			{label}
			{caption}
			{required}
			{size}
			disabled={isDisabled}
			{loading}
			{error}
			htmlFor={inputId}
			{labelId}
			{captionId}
		>
			<svelte:fragment slot="right">
				{#if $$slots.right}
					<slot name="right" />
				{/if}
			</svelte:fragment>
		</LabelBase>
	{/if}

	<div class={fieldStateClass}>
		{#if $$slots.prefix}
			<span class="cloo-input__icon is-prefix" aria-hidden="true">
				<slot name="prefix" />
			</span>
		{/if}

		<input
			{value}
			id={inputId}
			{name}
			{type}
			{placeholder}
			{autocomplete}
			readonly={readOnly}
			disabled={isDisabled}
			required={required && !readOnly && !isDisabled}
			aria-invalid={error ? 'true' : undefined}
			aria-busy={loading ? 'true' : undefined}
			aria-label={resolvedAriaLabel}
			aria-labelledby={ariaLabelledby ?? labelId}
			aria-describedby={resolvedAriaDescribedby}
			class={`cloo-input__native ${inputClassName}`.trim()}
			{...$$restProps}
			on:input={handleInput}
			on:change={(event) => {
				dispatch('change', event);
			}}
			on:focus={(event) => {
				dispatch('focus', event);
			}}
			on:blur={(event) => {
				dispatch('blur', event);
			}}
			on:keydown={(event) => {
				dispatch('keydown', event);
			}}
		/>

		{#if loading}
			<span class="cloo-input__icon is-suffix is-spinner" aria-hidden="true">
				<Spinner className="size-3" />
			</span>
		{:else if $$slots.suffix}
			<span class="cloo-input__icon is-suffix" aria-hidden="true">
				<slot name="suffix" />
			</span>
		{/if}
	</div>
</div>

<style>
	.cloo-input {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		width: 100%;
	}

	.cloo-input__field {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
		width: 100%;
		border: 1px solid var(--cloo-surface-border);
		border-radius: var(--cloo-radius-default);
		background-color: var(--cloo-bg-surface);
		color: var(--cloo-text-default);
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			box-shadow 150ms ease,
			opacity 150ms ease;
	}

	.cloo-input__field.is-sm {
		min-height: 2rem;
		padding: var(--cloo-space-2);
	}

	.cloo-input__field.is-md {
		min-height: 2.25rem;
		padding: var(--cloo-space-2);
	}

	/*
	 * State machine mirrors Figma _Input Base (1175:14066). Rules share specificity
	 * (0,2,0) so order decides the winner: hover < filled < focus < readonly < disabled < error.
	 */

	/* hover (empty) — neutral fill, borderless */
	.cloo-input__field:hover {
		background-color: var(--cloo-bg-neutral-hovered);
		border-color: transparent;
	}

	/* filled (has content) — subtle fill, borderless */
	.cloo-input__field.is-filled {
		background-color: var(--cloo-bg-default);
		border-color: transparent;
	}

	/* pressed / focus — subtle fill + strong border (no ring, per Figma) */
	.cloo-input__field:focus-within {
		background-color: var(--cloo-bg-default);
		border-color: var(--cloo-border-default);
	}

	.cloo-input__field.is-readonly {
		background-color: var(--cloo-bg-neutral-hovered);
		border-color: transparent;
	}

	.cloo-input__field.is-disabled,
	.cloo-input__field.is-loading {
		background-color: var(--cloo-bg-disabled);
		border-color: transparent;
		opacity: 0.8;
		cursor: not-allowed;
	}

	.cloo-input__field.is-error {
		border-color: var(--cloo-color-danger-border);
	}

	.cloo-input__field.is-error:focus-within {
		box-shadow:
			0 0 0 1px var(--cloo-color-danger-border),
			0 0 0 3px var(--cloo-color-danger-soft);
	}

	.cloo-input__native {
		flex: 1 1 0%;
		min-width: 0;
		border: 0;
		background: transparent;
		color: inherit;
		padding: 0;
		outline: none;
	}

	.cloo-input__field.is-sm .cloo-input__native {
		font-size: 0.75rem;
		line-height: 1rem;
	}

	.cloo-input__field.is-md .cloo-input__native {
		font-size: 0.875rem;
		line-height: 1.25rem;
	}

	.cloo-input__native::placeholder {
		color: var(--cloo-text-muted);
	}

	.cloo-input__native:disabled {
		cursor: not-allowed;
	}

	.cloo-input__icon {
		display: inline-flex;
		flex-shrink: 0;
		align-items: center;
		justify-content: center;
		color: var(--cloo-text-muted);
	}

	.cloo-input__field.is-sm .cloo-input__icon {
		width: 0.75rem;
		height: 0.75rem;
	}

	.cloo-input__field.is-md .cloo-input__icon {
		width: 0.875rem;
		height: 0.875rem;
	}

	.cloo-input__field.is-error .cloo-input__icon {
		color: var(--cloo-color-danger);
	}

	.cloo-input__field.is-loading .cloo-input__icon {
		color: var(--cloo-text-muted);
	}

	.is-spinner :global(svg) {
		display: block;
	}
</style>
