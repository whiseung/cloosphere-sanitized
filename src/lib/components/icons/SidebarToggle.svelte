<script lang="ts">
	export let className = 'size-5';
	export let strokeWidth = '1.5';
	export let direction: 'left' | 'right' = 'right';
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	fill="none"
	viewBox="0 0 24 24"
	stroke-width={strokeWidth}
	stroke="currentColor"
	class={className}
>
	<!-- Main frame -->
	<rect
		x="4"
		y="5"
		width="16"
		height="14"
		rx="2.5"
		stroke="currentColor"
		stroke-linecap="round"
		stroke-linejoin="round"
		fill="none"
	/>
	<!-- Sidebar panel (shaded) -->
	<path
		d="M4 7.5C4 6.12 5.12 5 6.5 5H11V19H6.5C5.12 19 4 17.88 4 16.5V7.5Z"
		fill="currentColor"
		fill-opacity="0.12"
		stroke="none"
	/>
	<!-- Divider line -->
	<line x1="11" y1="5" x2="11" y2="19" stroke="currentColor" stroke-linecap="round" />
	<!-- Toggle indicator (chevron) -->
	{#if direction === 'right'}
		<path
			d="M7 10.5L8.5 12L7 13.5"
			stroke="currentColor"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
	{:else}
		<path
			d="M8.5 10.5L7 12L8.5 13.5"
			stroke="currentColor"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
	{/if}
</svg>
