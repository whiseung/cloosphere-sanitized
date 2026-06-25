<script lang="ts">
	import Tooltip from './Tooltip.svelte';
	import QuestionMarkCircle from '$lib/components/icons/QuestionMarkCircle.svelte';

	export let label: string = '';
	export let hint: string = '';
	export let size: 'sm' | 'md' | 'lg' = 'md';
	export let required: boolean = false;
	export let htmlFor: string | undefined = undefined;

	const sizeClasses: Record<'sm' | 'md' | 'lg', string> = {
		sm: 'text-xs leading-4 font-medium',
		md: 'text-sm leading-5 font-medium',
		lg: 'text-base leading-6 font-semibold'
	};
</script>

<div class="flex items-center gap-1.5">
	{#if label}
		<label class={sizeClasses[size]} for={htmlFor}>{label}</label>
	{/if}
	{#if required}
		<span class="text-[var(--cloo-danger-solid)]" aria-hidden="true">*</span>
	{/if}
	{#if hint}
		<Tooltip content={hint} placement="top">
			<button
				type="button"
				class="shrink-0 p-0.5 text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)] transition rounded-full inline-flex"
				aria-label={hint}
				tabindex="-1"
			>
				<QuestionMarkCircle className="w-3.5 h-3.5" strokeWidth="2" />
			</button>
		</Tooltip>
	{/if}
</div>
