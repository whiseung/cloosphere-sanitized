<script lang="ts">
	import { createEventDispatcher, onMount, tick } from 'svelte';

	import LabelBase from './LabelBase.svelte';
	import Spinner from './Spinner.svelte';

	export let value = '';
	export let label = '';
	export let caption = '';
	export let placeholder = '';
	export let rows = 1;
	export let required = false;
	export let readOnly = false;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let autoResize = true;
	export let size: 'sm' | 'md' = 'sm';
	export let id: string | undefined = undefined;
	export let name: string | undefined = undefined;
	export let className = '';
	export let containerClassName = '';
	export let ariaLabel: string | undefined = undefined;
	export let ariaLabelledby: string | undefined = undefined;
	export let ariaDescribedby: string | undefined = undefined;

	let textareaElement: HTMLTextAreaElement | undefined;

	const dispatch = createEventDispatcher();

	$: textareaId = id;
	$: captionId = id && caption ? `${id}-caption` : undefined;
	$: labelId = id && label ? `${id}-label` : undefined;
	$: isDisabled = disabled || loading;
	$: isFilled = String(value ?? '').length > 0;
	$: resolvedAriaLabel = ariaLabel ?? (!ariaLabelledby && !labelId && label ? label : undefined);
	$: resolvedAriaDescribedby = ariaDescribedby ?? captionId;
	$: wrapperClass = [
		'cloo-textarea__field',
		`is-${size}`,
		isFilled ? 'is-filled' : '',
		readOnly ? 'is-readonly' : '',
		isDisabled ? 'is-disabled' : '',
		loading ? 'is-loading' : '',
		error ? 'is-error' : '',
		containerClassName
	]
		.filter(Boolean)
		.join(' ');

	async function resize() {
		if (!autoResize) {
			return;
		}

		await tick();

		if (textareaElement) {
			textareaElement.style.height = '';
			textareaElement.style.height = `${textareaElement.scrollHeight}px`;
		}
	}

	$: if (autoResize) {
		value;
		rows;
		resize();
	}

	onMount(() => {
		resize();
	});

	function handleInput(event: Event) {
		value = (event.currentTarget as HTMLTextAreaElement).value;
		dispatch('input', event);
	}
</script>

<div class="cloo-textarea">
	{#if label || caption || required || $$slots.right}
		<LabelBase
			{label}
			{caption}
			{required}
			{size}
			disabled={isDisabled}
			{loading}
			{error}
			htmlFor={textareaId}
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

	<div class={wrapperClass}>
		<textarea
			bind:this={textareaElement}
			bind:value
			id={textareaId}
			{name}
			{placeholder}
			{rows}
			readonly={readOnly}
			disabled={isDisabled}
			required={required && !readOnly && !isDisabled}
			aria-invalid={error ? 'true' : undefined}
			aria-busy={loading ? 'true' : undefined}
			aria-label={resolvedAriaLabel}
			aria-labelledby={ariaLabelledby ?? labelId}
			aria-describedby={resolvedAriaDescribedby}
			class={`cloo-textarea__native ${className}`.trim()}
			style={autoResize ? 'field-sizing: content;' : undefined}
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
			<span class="cloo-textarea__spinner" aria-hidden="true">
				<Spinner className="size-3" />
			</span>
		{/if}
	</div>
</div>

<style>
	.cloo-textarea {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		width: 100%;
	}

	.cloo-textarea__field {
		position: relative;
		display: flex;
		width: 100%;
		border: 1px solid var(--cloo-surface-border);
		border-radius: var(--cloo-radius-default);
		background-color: var(--cloo-bg-surface);
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			box-shadow 150ms ease,
			opacity 150ms ease;
	}

	/*
	 * State machine mirrors Figma _Input Base. Rules share specificity so order
	 * decides: hover < filled < focus < readonly < disabled < error.
	 */

	/* hover (empty) — neutral fill, borderless */
	.cloo-textarea__field:hover {
		background-color: var(--cloo-bg-neutral-hovered);
		border-color: transparent;
	}

	/* filled (has content) — subtle fill, borderless */
	.cloo-textarea__field.is-filled {
		background-color: var(--cloo-bg-default);
		border-color: transparent;
	}

	/* pressed / focus — subtle fill + strong border (no ring, per Figma) */
	.cloo-textarea__field:focus-within {
		background-color: var(--cloo-bg-default);
		border-color: var(--cloo-border-default);
	}

	.cloo-textarea__field.is-readonly {
		background-color: var(--cloo-bg-neutral-hovered);
		border-color: transparent;
	}

	.cloo-textarea__field.is-disabled,
	.cloo-textarea__field.is-loading {
		background-color: var(--cloo-bg-disabled);
		border-color: transparent;
		opacity: 0.8;
		cursor: not-allowed;
	}

	.cloo-textarea__field.is-error {
		border-color: var(--cloo-color-danger-border);
	}

	.cloo-textarea__field.is-error:focus-within {
		box-shadow:
			0 0 0 1px var(--cloo-color-danger-border),
			0 0 0 3px var(--cloo-color-danger-soft);
	}

	.cloo-textarea__native {
		width: 100%;
		border-radius: inherit;
		border: 0;
		background-color: inherit;
		color: var(--cloo-text-default);
		padding: var(--cloo-space-2);
		outline: none;
		resize: vertical;
	}

	.cloo-textarea__field.is-sm .cloo-textarea__native {
		font-size: 0.75rem;
		line-height: 1rem;
	}

	.cloo-textarea__field.is-md .cloo-textarea__native {
		font-size: 0.875rem;
		line-height: 1.25rem;
	}

	.cloo-textarea__native::placeholder {
		color: var(--cloo-text-muted);
	}

	.cloo-textarea__native:disabled {
		cursor: not-allowed;
	}

	.cloo-textarea__field.is-loading .cloo-textarea__native {
		padding-right: calc(var(--cloo-space-4) + var(--cloo-space-2));
	}

	.cloo-textarea__spinner {
		position: absolute;
		top: var(--cloo-space-2);
		right: var(--cloo-space-2);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		color: var(--cloo-text-muted);
	}
</style>
