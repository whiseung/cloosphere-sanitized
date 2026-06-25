<script lang="ts">
	import { getContext } from 'svelte';

	type LegacyBadgeType = 'info' | 'success' | 'warning' | 'error' | 'muted';
	type BadgeStatus = 'default' | 'secondary' | 'info' | 'success' | 'warning' | 'danger' | 'accent';
	type BadgeSize = 'sm' | 'md' | 'md*' | 'lg';

	type BadgeVariant = {
		status: BadgeStatus;
		invert: boolean;
	};

	export let type: LegacyBadgeType | undefined = 'info';
	export let content = '';
	export let badgeName = '';
	export let kind: 'text' = 'text';
	export let shape: 'full rounded' = 'full rounded';
	export let status: BadgeStatus | undefined = undefined;
	export let size: BadgeSize = 'sm';
	export let invert: boolean | undefined = undefined;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let ariaLabel = '';
	export let className = '';

	const i18n = getContext<{ t?: (key: string) => string } | undefined>('i18n');

	const legacyVariants: Record<LegacyBadgeType, BadgeVariant> = {
		info: { status: 'info', invert: true },
		success: { status: 'success', invert: true },
		warning: { status: 'warning', invert: true },
		error: { status: 'danger', invert: true },
		muted: { status: 'default', invert: true }
	};

	const sizeStyles: Record<'sm' | 'md' | 'lg', string> = {
		sm: 'min-h-5 gap-[var(--cloo-space-1)] px-[var(--cloo-space-1-5)] text-xs leading-4',
		md: 'min-h-6 gap-[var(--cloo-space-1-5)] px-[var(--cloo-space-2)] text-sm leading-5',
		lg: 'min-h-7 gap-[var(--cloo-space-1-5)] px-[var(--cloo-space-2-5)] text-base leading-6'
	};

	const spinnerSizes: Record<'sm' | 'md' | 'lg', string> = {
		sm: 'size-3',
		md: 'size-3.5',
		lg: 'size-4'
	};

	const variantStyles: Record<BadgeStatus, Record<'solid' | 'soft', string>> = {
		default: {
			solid:
				'bg-[var(--cloo-color-primary)] text-[var(--cloo-color-on-primary)] border-transparent hover:bg-[var(--cloo-color-primary-hover)] active:bg-[var(--cloo-color-primary-active)]',
			soft:
				'bg-[var(--cloo-bg-default)] text-[var(--cloo-text-primary)] border-transparent hover:bg-[var(--cloo-bg-neutral-hovered)] active:bg-[var(--cloo-surface-active)]'
		},
		secondary: {
			solid:
				'bg-[var(--cloo-bg-surface)] text-[var(--cloo-color-primary)] border-[var(--cloo-color-primary)] hover:bg-[var(--cloo-surface-hover)] active:bg-[var(--cloo-surface-active)]',
			soft:
				'bg-[var(--cloo-bg-surface)] text-[var(--cloo-color-primary)] border-[var(--cloo-color-primary)] hover:bg-[var(--cloo-surface-hover)] active:bg-[var(--cloo-surface-active)]'
		},
		accent: {
			solid:
				'bg-[var(--cloo-color-accent)] text-[var(--cloo-color-accent-contrast)] border-transparent hover:bg-[var(--cloo-color-accent-hover)] active:bg-[var(--token-scale-accent-800)]',
			soft:
				'bg-[var(--cloo-color-accent-soft)] text-[var(--cloo-color-accent)] border-transparent hover:bg-[var(--token-scale-accent-200)] active:bg-[var(--token-scale-accent-300)]'
		},
		info: {
			solid:
				'bg-[var(--cloo-color-info)] text-[var(--token-text-on-dark)] border-transparent hover:bg-[var(--token-scale-info-700)] active:bg-[var(--token-scale-info-800)]',
			soft:
				'bg-[var(--token-scale-info-100)] text-[var(--token-scale-info-700)] border-transparent hover:bg-[var(--token-scale-info-200)] active:bg-[var(--token-scale-info-300)]'
		},
		success: {
			solid:
				'bg-[var(--cloo-color-success)] text-[var(--token-text-on-dark)] border-transparent hover:bg-[var(--token-scale-success-700)] active:bg-[var(--token-scale-success-800)]',
			soft:
				'bg-[var(--token-scale-success-100)] text-[var(--token-scale-success-700)] border-transparent hover:bg-[var(--token-scale-success-200)] active:bg-[var(--token-scale-success-300)]'
		},
		warning: {
			solid:
				'bg-[var(--cloo-color-warning)] text-[var(--token-text-on-dark)] border-transparent hover:bg-[var(--token-scale-warning-700)] active:bg-[var(--token-scale-warning-800)]',
			soft:
				'bg-[var(--token-scale-warning-100)] text-[var(--token-scale-warning-700)] border-transparent hover:bg-[var(--token-scale-warning-200)] active:bg-[var(--token-scale-warning-300)]'
		},
		danger: {
			solid:
				'bg-[var(--cloo-danger-solid)] text-[var(--cloo-danger-solid-contrast)] border-transparent hover:bg-[var(--cloo-danger-solid-hover)] active:bg-[var(--cloo-danger-solid-active)]',
			soft:
				'bg-[var(--cloo-color-danger-soft)] text-[var(--cloo-color-danger)] border-transparent hover:bg-[var(--cloo-color-danger-softer)] active:bg-[var(--token-scale-danger-200)]'
		}
	};

	const disabledStyles =
		'bg-[var(--cloo-bg-disabled)] text-[var(--cloo-text-muted)] border-[var(--cloo-border-subtle)] cursor-not-allowed opacity-70 pointer-events-none';

	$: normalizedSize = size === 'md*' ? 'md' : size;
	$: resolvedSize = normalizedSize in sizeStyles ? (normalizedSize as 'sm' | 'md' | 'lg') : 'sm';
	$: hasExplicitVariant = status !== undefined || invert !== undefined;
	$: legacyVariant = !hasExplicitVariant && type ? legacyVariants[type] : undefined;
	$: resolvedStatus = status ?? legacyVariant?.status ?? 'default';
	$: resolvedInvert = invert ?? legacyVariant?.invert ?? false;
	$: resolvedPalette = variantStyles[resolvedStatus] ?? variantStyles.default;
	$: resolvedVariant = resolvedPalette[resolvedInvert ? 'soft' : 'solid'];
	$: isDisabled = disabled || loading;
	$: resolvedText = badgeName || content;
	$: resolvedAriaLabel =
		ariaLabel || (loading && !resolvedText && !$$slots.default ? i18n?.t?.('Loading') ?? 'Loading' : undefined);
	$: classes = [
		'inline-flex w-fit max-w-full items-center justify-center rounded-[var(--cloo-radius-default)] border font-normal whitespace-nowrap transition-[background-color,border-color,color,box-shadow,opacity] duration-150 select-none',
		'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--cloo-bg-surface)]',
		error
			? 'ring-1 ring-[var(--cloo-color-danger-border)] focus-visible:ring-[var(--cloo-color-danger)]'
			: 'focus-visible:ring-[var(--cloo-focus-ring)]',
		sizeStyles[resolvedSize],
		isDisabled ? disabledStyles : resolvedVariant,
		kind !== 'text' ? 'opacity-100' : '',
		shape !== 'full rounded' ? 'rounded-[var(--cloo-radius-default)]' : '',
		className
	]
		.filter(Boolean)
		.join(' ');
</script>

<span
	class={classes}
	aria-label={resolvedAriaLabel}
	aria-busy={loading ? 'true' : undefined}
	aria-disabled={isDisabled ? 'true' : undefined}
	aria-invalid={error ? 'true' : undefined}
	data-kind={kind}
	data-shape={shape}
	data-status={resolvedStatus}
	data-size={resolvedSize}
	data-invert={resolvedInvert}
	{...$$restProps}
>
	{#if loading}
		<span class="inline-flex shrink-0 items-center justify-center {spinnerSizes[resolvedSize]}">
			<svg
				class={spinnerSizes[resolvedSize]}
				viewBox="0 0 24 24"
				fill="currentColor"
				xmlns="http://www.w3.org/2000/svg"
				aria-hidden="true"
			>
				<path
					d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
					opacity=".25"
				/>
				<path
					class="cloo-badge__spinner-head"
					d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
				/>
			</svg>
		</span>
	{/if}

	{#if $$slots.default}
		<span class:opacity-0={loading} class="truncate"><slot /></span>
	{:else if resolvedText}
		<span class:opacity-0={loading} class="truncate">{resolvedText}</span>
	{/if}
</span>

<style>
	.cloo-badge__spinner-head {
		transform-origin: center;
		animation: cloo-badge-spin 0.75s linear infinite;
	}

	@keyframes cloo-badge-spin {
		100% {
			transform: rotate(360deg);
		}
	}
</style>
