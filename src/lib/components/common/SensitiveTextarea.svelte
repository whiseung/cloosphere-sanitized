<script lang="ts">
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	export let value: string = '';
	export let placeholder = '';
	export let rows = 4;
	export let readOnly = false;
	export let className =
		'w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden resize-y font-mono';

	let show = false;

	/**
	 * 눈알 클릭 시 JSON 자동 pretty-print.
	 * JSON이면 포맷팅, 아니면 그대로 유지.
	 */
	function toggleShow() {
		if (!show && value) {
			const trimmed = value.trim();
			if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
				try {
					value = JSON.stringify(JSON.parse(trimmed), null, 2);
				} catch {
					// JSON 파싱 실패 시 원문 유지
				}
			}
		}
		show = !show;
	}
</script>

<div class="relative">
	{#if show}
		<textarea
			class={className}
			{placeholder}
			{rows}
			bind:value
			disabled={readOnly}
		/>
	{:else}
		<div
			class="{className} overflow-hidden whitespace-pre-wrap break-all"
			style="min-height: {rows * 1.5 + 0.75}rem;"
		>
			{#if value}
				<span class="text-gray-400 dark:text-gray-500 select-none flex items-center gap-1.5">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5 shrink-0">
						<path fill-rule="evenodd" d="M8 1a3.5 3.5 0 0 0-3.5 3.5V7A1.5 1.5 0 0 0 3 8.5v5A1.5 1.5 0 0 0 4.5 15h7a1.5 1.5 0 0 0 1.5-1.5v-5A1.5 1.5 0 0 0 11.5 7V4.5A3.5 3.5 0 0 0 8 1Zm2 6V4.5a2 2 0 1 0-4 0V7h4Z" clip-rule="evenodd" />
					</svg>
					<span class="text-xs">{$i18n.t('Configured')}</span>
				</span>
			{:else}
				<span class="text-gray-300 dark:text-gray-700">{placeholder}</span>
			{/if}
		</div>
	{/if}

	<button
		class="absolute top-1.5 right-1.5 p-1 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition"
		type="button"
		on:click={(e) => {
			e.preventDefault();
			toggleShow();
		}}
	>
		{#if show}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 16 16"
				fill="currentColor"
				class="size-4"
			>
				<path
					fill-rule="evenodd"
					d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l10.5 10.5a.75.75 0 1 0 1.06-1.06l-1.322-1.323a7.012 7.012 0 0 0 2.16-3.11.87.87 0 0 0 0-.567A7.003 7.003 0 0 0 4.82 3.76l-1.54-1.54Zm3.196 3.195 1.135 1.136A1.502 1.502 0 0 1 9.45 8.389l1.136 1.135a3 3 0 0 0-4.109-4.109Z"
					clip-rule="evenodd"
				/>
				<path
					d="m7.812 10.994 1.816 1.816A7.003 7.003 0 0 1 1.38 8.28a.87.87 0 0 1 0-.566 6.985 6.985 0 0 1 1.113-2.039l2.513 2.513a3 3 0 0 0 2.806 2.806Z"
				/>
			</svg>
		{:else}
			<!-- svelte-ignore a11y-click-events-have-key-events -->
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 16 16"
				fill="currentColor"
				class="size-4"
			>
				<path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
				<path
					fill-rule="evenodd"
					d="M1.38 8.28a.87.87 0 0 1 0-.566 7.003 7.003 0 0 1 13.238.006.87.87 0 0 1 0 .566A7.003 7.003 0 0 1 1.379 8.28ZM11 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
					clip-rule="evenodd"
				/>
			</svg>
		{/if}
	</button>
</div>
