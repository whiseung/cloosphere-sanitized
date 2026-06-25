<script lang="ts">
	export let label = '';
	export let caption = '';
	export let required = false;
	export let size: 'sm' | 'md' | 'lg' = 'sm';
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let htmlFor: string | undefined = undefined;
	export let labelId: string | undefined = undefined;
	export let captionId: string | undefined = undefined;
	export let className = '';

	const sizeClasses: Record<'sm' | 'md' | 'lg', { label: string; star: string }> = {
		sm: {
			label: 'text-xs leading-4 font-medium',
			star: 'text-xs leading-4'
		},
		md: {
			label: 'text-sm leading-5 font-medium',
			star: 'text-sm leading-5'
		},
		lg: {
			label: 'text-base leading-6 font-semibold',
			star: 'text-base leading-6'
		}
	};

	$: labelStateClass = disabled || loading ? 'is-muted' : error ? 'is-error' : '';
	$: hasHeader = Boolean(label) || required || Boolean($$slots.right);
</script>

<div class={`cloo-label-base ${className}`.trim()}>
	<div class="cloo-label-base__left">
		{#if hasHeader}
			<div class="cloo-label-base__header">
				{#if label}
					<label
						class={`cloo-label-base__label ${sizeClasses[size].label} ${labelStateClass}`.trim()}
						id={labelId}
						for={htmlFor}
					>
						{label}
					</label>
				{/if}

				{#if required}
					<span
						class={`cloo-label-base__required ${sizeClasses[size].star} ${disabled || loading ? 'is-muted' : ''}`.trim()}
						aria-hidden="true"
					>
						*
					</span>
				{/if}
			</div>
		{/if}

		{#if caption}
			<p class="cloo-label-base__caption" id={captionId}>
				{caption}
			</p>
		{/if}
	</div>

	{#if $$slots.right}
		<div class="cloo-label-base__right">
			<slot name="right" />
		</div>
	{/if}
</div>

<style>
	.cloo-label-base {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--cloo-space-2);
		width: 100%;
	}

	.cloo-label-base__left {
		display: flex;
		flex: 1 1 0%;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.cloo-label-base__header {
		display: inline-flex;
		align-items: flex-start;
		gap: 2px;
		min-width: 0;
	}

	.cloo-label-base__label {
		color: var(--cloo-text-primary);
		min-width: 0;
		word-break: break-word;
	}

	.cloo-label-base__label.is-muted {
		color: var(--cloo-text-muted);
	}

	.cloo-label-base__label.is-error {
		color: var(--cloo-color-danger);
	}

	.cloo-label-base__required {
		color: var(--cloo-color-danger);
		font-weight: 500;
		flex-shrink: 0;
	}

	.cloo-label-base__required.is-muted {
		color: var(--cloo-text-muted);
	}

	.cloo-label-base__caption {
		color: var(--cloo-text-muted);
		font-size: 0.75rem;
		line-height: 1rem;
		word-break: break-word;
	}

	.cloo-label-base__right {
		display: inline-flex;
		flex-shrink: 0;
		align-items: center;
	}
</style>
