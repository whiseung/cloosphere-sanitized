<script lang="ts">
	import { getContext } from 'svelte';
	import { saveAs } from 'file-saver';
	import { format as formatSql } from 'sql-formatter';
	import CodeBlock from './CodeBlock.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	const i18n = getContext('i18n');

	export let show = false;
	export let queryExecution: any = null;

	// The default "sql" dialect can't parse vendor-specific syntax (e.g. PostgreSQL
	// "::numeric" casts) and throws. A throw here would break the reactive render and
	// the modal would never open, so fall back to the raw SQL on any parse failure.
	const prettifySql = (raw: string): string => {
		if (!raw || !raw.trim()) return raw;
		try {
			return formatSql(raw, { language: 'sql', tabWidth: 2, keywordCase: 'upper' });
		} catch {
			return raw;
		}
	};

	$: formattedSql = queryExecution?.sql ? prettifySql(queryExecution.sql) : '';

	const downloadCsv = () => {
		if (!queryExecution?.result?.data?.length) return;
		const columns = queryExecution.result.columns || [];
		const rows = queryExecution.result.data || [];
		const csv = [
			columns.join(','),
			...rows.map((row: any) => columns.map((col: string) => JSON.stringify(row[col] ?? '')).join(','))
		].join('\n');
		const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
		saveAs(blob, `query-result-${queryExecution.id || 'data'}.csv`);
	};

	const copySql = () => {
		if (!queryExecution?.sql) return;
		navigator.clipboard.writeText(queryExecution.sql);
	};
</script>

<Modal size="lg" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center flex flex-col gap-0.5">
				{#if queryExecution?.result}
					<Badge type="success" content="success" />
				{:else}
					<Badge type="warning" content="no result" />
				{/if}
				<div class="flex gap-2 items-center">
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-5">
						<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
					</svg>
					<div>{queryExecution?.name ?? $i18n.t('SQL Query')}</div>
				</div>
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
					queryExecution = null;
				}}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
				</svg>
			</button>
		</div>

		<div class="flex flex-col w-full px-4 pb-5 dark:text-gray-200 overflow-y-auto max-h-[70vh]">
			<!-- SQL -->
			<div class="mb-3">
				<div class="flex items-center justify-between mb-1">
					<div class="text-gray-500 text-xs font-medium">{$i18n.t('SQL')}</div>
					<Tooltip content={$i18n.t('Copy')}>
						<button
							class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition"
							on:click={copySql}
						>
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9.75a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184" />
							</svg>
						</button>
					</Tooltip>
				</div>
				<CodeBlock
					id="query-exec-{queryExecution?.id}-sql"
					lang="sql"
					code={formattedSql}
					className=""
					stickyButtonsClassName="top-0"
					run={false}
				/>
			</div>

			<!-- Result Table -->
			{#if queryExecution?.result?.data?.length}
				<div>
					<div class="flex items-center justify-between mb-1">
						<div class="text-gray-500 text-xs font-medium">
							{$i18n.t('Result')}
							<span class="text-gray-400 ml-1">
								({queryExecution.result.total_rows ?? queryExecution.result.data.length} {$i18n.t('rows')})
							</span>
						</div>
						<Tooltip content={$i18n.t('Download CSV')}>
							<button
								class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition"
								on:click={downloadCsv}
							>
								<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
									<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
								</svg>
							</button>
						</Tooltip>
					</div>
					<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
						<table class="w-full text-xs">
							<thead>
								<tr class="bg-gray-50 dark:bg-gray-800">
									{#each queryExecution.result.columns as col}
										<th class="px-3 py-2 text-left font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap border-b border-gray-200 dark:border-gray-700">
											{col}
										</th>
									{/each}
								</tr>
							</thead>
							<tbody>
								{#each queryExecution.result.data as row, idx}
									<tr class="{idx % 2 === 0 ? 'bg-white dark:bg-gray-900' : 'bg-gray-50 dark:bg-gray-850'}">
										{#each queryExecution.result.columns as col}
											<td class="px-3 py-1.5 whitespace-nowrap border-b border-gray-100 dark:border-gray-800 max-w-xs truncate">
												{row[col] ?? ''}
											</td>
										{/each}
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
					{#if queryExecution.result.total_rows > queryExecution.result.data.length}
						<div class="text-xs text-gray-400 mt-1 text-center">
							{$i18n.t('Showing {{shown}} of {{total}} rows', {
								shown: queryExecution.result.data.length,
								total: queryExecution.result.total_rows
							})}
						</div>
					{/if}
				</div>
			{:else if queryExecution?.result === null}
				<div class="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">
					{$i18n.t('No results returned')}
				</div>
			{/if}
		</div>
	</div>
</Modal>
