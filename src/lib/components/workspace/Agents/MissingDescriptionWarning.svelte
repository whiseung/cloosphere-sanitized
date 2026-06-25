<script lang="ts">
	import { getContext } from 'svelte';

	const i18n = getContext<any>('i18n');

	export let missingNames: string[] = [];
</script>

{#if missingNames.length > 0}
	<div
		class="flex gap-2 items-start mt-2 px-2.5 py-1.5 rounded-md bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 text-xs"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 20 20"
			fill="currentColor"
			class="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5"
			aria-hidden="true"
		>
			<path
				fill-rule="evenodd"
				d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z"
				clip-rule="evenodd"
			/>
		</svg>
		<div class="flex-1 text-amber-800 dark:text-amber-200">
			<div class="font-medium">{$i18n.t('Tool description is missing')}</div>
			<div class="mt-0.5 text-amber-700 dark:text-amber-300">
				{$i18n.t(
					'These items have no description, which may prevent the LLM from using them correctly:'
				)}
				{missingNames.join(', ')}
			</div>
		</div>
	</div>
{/if}
