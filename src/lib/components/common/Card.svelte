<script lang="ts">
	export let className: string = '';
	export let bodyClassName: string = '';
	export let headerClassName: string = '';
	export let footerClassName: string = '';
	export let padding: 'none' | 'sm' | 'md' | 'lg' = 'md';

	const paddingMap: Record<string, string> = {
		none: '',
		sm: 'p-[var(--cloo-space-2)]',
		md: 'p-[var(--cloo-space-3)]',
		lg: 'p-[var(--cloo-space-4)]'
	};

	$: bodyPadding = paddingMap[padding];
</script>

<section
	class="cloo-card flex flex-col rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)] text-[var(--cloo-text-default)] {className}"
>
	{#if $$slots.header}
		<header
			class="cloo-card__header border-b border-[var(--cloo-border-subtle)] {bodyPadding} {headerClassName}"
		>
			<slot name="header" />
		</header>
	{/if}

	<div class="cloo-card__body {bodyPadding} {bodyClassName}">
		<slot />
	</div>

	{#if $$slots.footer}
		<footer
			class="cloo-card__footer border-t border-[var(--cloo-border-subtle)] {bodyPadding} {footerClassName}"
		>
			<slot name="footer" />
		</footer>
	{/if}
</section>
