<script lang="ts">
	import QueryExecutionModal from './QueryExecutionModal.svelte';

	export let queryExecutions: any[] = [];

	let selectedQueryExecution: any = null;
	let showQueryExecutionModal = false;
</script>

<QueryExecutionModal bind:show={showQueryExecutionModal} queryExecution={selectedQueryExecution} />

{#if queryExecutions.length > 0}
	<div class="mt-1 mb-2 w-full flex gap-1 items-center flex-wrap">
		{#each queryExecutions as execution (execution.id)}
			<div class="flex gap-1 text-xs font-semibold">
				<button
					class="flex items-center dark:text-gray-300 py-1 px-2 bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-xl max-w-96"
					on:click={() => {
						selectedQueryExecution = execution;
						showQueryExecutionModal = true;
					}}
				>
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5 flex-shrink-0">
						<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
					</svg>
					<span class="ml-1.5 line-clamp-1">{execution.name}</span>
				</button>
			</div>
		{/each}
	</div>
{/if}
