<script lang="ts">
	import Spinner from './Spinner.svelte';

	export let kind: 'filled' | 'outlined' | 'text' = 'filled';
	export let size: 'sm' | 'md' | 'lg' = 'sm';
	export let status: 'default' | 'error' = 'default';
	export let disabled: boolean = false;
	export let loading: boolean = false;
	export let className: string = '';
	export let type: 'button' | 'submit' | 'reset' = 'button';

	const sizeStyles: Record<string, string> = {
		sm: 'px-[var(--cloo-space-1-5)] py-[var(--cloo-space-2)] text-xs gap-1',
		md: 'px-[var(--cloo-space-2-5)] py-[var(--cloo-space-2)] text-sm gap-[var(--cloo-space-1-5)]',
		lg: 'px-[var(--cloo-space-3)] py-[var(--cloo-space-2)] text-base gap-[var(--cloo-space-2)]'
	};

	const iconSizes: Record<string, string> = {
		sm: 'size-3',
		md: 'size-3.5',
		lg: 'size-4'
	};

	const kindStyles: Record<string, Record<string, string>> = {
		default: {
			filled:
				'border border-transparent bg-[var(--cloo-color-primary)] text-[var(--cloo-color-on-primary)] hover:bg-[var(--cloo-color-primary-hover)] active:bg-[var(--cloo-color-primary-active)]',
			outlined:
				'bg-[var(--cloo-bg-surface)] text-[var(--cloo-text-default)] border border-[var(--cloo-border-subtle)] hover:bg-[var(--cloo-surface-hover)] active:bg-[var(--cloo-surface-active)]',
			text:
				'border border-transparent text-[var(--cloo-text-default)] hover:bg-[var(--cloo-surface-hover)] active:bg-[var(--cloo-surface-active)]'
		},
		error: {
			filled:
				'border border-transparent bg-[var(--cloo-danger-solid)] text-[var(--cloo-danger-solid-contrast)] hover:bg-[var(--cloo-danger-solid-hover)] active:bg-[var(--cloo-danger-solid-active)]',
			outlined:
				'bg-[var(--cloo-bg-surface)] text-[var(--cloo-color-danger)] border border-[var(--cloo-color-danger-border)] hover:bg-[var(--cloo-color-danger-soft)] active:bg-[var(--cloo-color-danger-softer)]',
			text:
				'border border-transparent text-[var(--cloo-color-danger)] hover:bg-[var(--cloo-color-danger-soft)] active:bg-[var(--cloo-color-danger-softer)]'
		}
	};

	const disabledStyles: Record<string, string> = {
		filled: 'border border-transparent bg-[var(--cloo-bg-disabled)] text-[var(--cloo-text-muted)]',
		outlined:
			'bg-[var(--cloo-bg-disabled)] text-[var(--cloo-text-muted)] border border-transparent',
		text: 'border border-transparent text-[var(--cloo-text-muted)]'
	};

	$: isDisabled = disabled || loading;
	$: classes = [
		'inline-flex items-center justify-center rounded-[var(--cloo-radius-default)] font-medium transition-colors',
		'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--cloo-focus-ring)]',
		sizeStyles[size],
		isDisabled ? disabledStyles[kind] : (kindStyles[status]?.[kind] ?? kindStyles['default'][kind]),
		isDisabled ? 'cursor-not-allowed' : '',
		className
	]
		.filter(Boolean)
		.join(' ');
</script>

<button
	{type}
	disabled={isDisabled}
	class={classes}
	on:click
	on:mousedown
	on:keydown
	{...$$restProps}
>
	{#if loading}
		<Spinner className={iconSizes[size]} />
	{:else if $$slots.prefix}
		<span class="shrink-0 inline-flex items-center justify-center {iconSizes[size]}">
			<slot name="prefix" />
		</span>
	{/if}

	{#if $$slots.default}
		<span class="truncate"><slot /></span>
	{/if}

	{#if !loading && $$slots.suffix}
		<span class="shrink-0 inline-flex items-center justify-center {iconSizes[size]}">
			<slot name="suffix" />
		</span>
	{/if}
</button>
