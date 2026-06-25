<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { getGuardrailLogs } from '$lib/apis/guardrail-logs';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	// Filters
	let dateRange = '7d';
	let customFrom = '';
	let customTo = '';
	let selectedAction = '';

	// Pagination
	let page = 1;
	let limit = 50;
	let totalPages = 1;
	let total = 0;

	// Data
	let logs: any[] = [];
	let loading = false;
	let expandedId: string | null = null;

	function getDateRange(): { from_date?: number; to_date?: number } {
		const now = Math.floor(Date.now() / 1000);
		const ranges: Record<string, number> = {
			'1h': 3600,
			'6h': 21600,
			'1d': 86400,
			'7d': 604800,
			'30d': 2592000
		};

		if (dateRange === 'all') return {};
		if (dateRange === 'custom') {
			const result: { from_date?: number; to_date?: number } = {};
			if (customFrom) result.from_date = Math.floor(new Date(customFrom).getTime() / 1000);
			if (customTo)
				result.to_date = Math.floor(new Date(customTo).getTime() / 1000) + 86399;
			return result;
		}
		if (ranges[dateRange]) {
			return { from_date: now - ranges[dateRange] };
		}
		return {};
	}

	async function loadLogs() {
		loading = true;
		try {
			const dateParams = getDateRange();
			const res = await getGuardrailLogs(localStorage.token, {
				page,
				limit,
				source: 'code_gateway',
				action: selectedAction || undefined,
				...dateParams
			});
			if (res) {
				logs = res.items || [];
				total = res.total || 0;
				totalPages = res.total_pages || 1;
			}
		} catch {
			// ignore
		}
		loading = false;
	}

	async function refresh() {
		page = 1;
		expandedId = null;
		await loadLogs();
	}

	function formatTime(ts: number): string {
		return new Date(ts * 1000).toLocaleString();
	}

	function setDateRange(range: string) {
		dateRange = range;
		refresh();
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	// Stats
	$: blockCount = logs.filter((l) => l.action === 'block').length;
	$: warnCount = logs.filter((l) => l.action !== 'block').length;

	onMount(async () => {
		await refresh();
	});
</script>

<div class="w-full max-w-full">
	<!-- Stats Cards -->
	<div class="grid grid-cols-3 gap-3 mb-4">
		<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
			<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Total Events')}</div>
			<div class="text-xl font-semibold mt-0.5">{total.toLocaleString()}</div>
		</div>
		<div class="rounded-xl bg-red-50 dark:bg-red-900/10 p-3">
			<div class="text-xs text-red-500 dark:text-red-400">{$i18n.t('Blocked')}</div>
			<div class="text-xl font-semibold mt-0.5 text-red-700 dark:text-red-300">
				{blockCount}
			</div>
		</div>
		<div class="rounded-xl bg-amber-50 dark:bg-amber-900/10 p-3">
			<div class="text-xs text-amber-500 dark:text-amber-400">{$i18n.t('Warnings')}</div>
			<div class="text-xl font-semibold mt-0.5 text-amber-700 dark:text-amber-300">
				{warnCount}
			</div>
		</div>
	</div>

	<!-- Filters -->
	<div class="flex flex-wrap items-center gap-2 mb-3">
		<!-- Date range -->
		<div class="flex gap-1 text-xs">
			{#each [{ k: '1h', l: '1H' }, { k: '6h', l: '6H' }, { k: '1d', l: '1D' }, { k: '7d', l: '7D' }, { k: '30d', l: '30D' }, { k: 'all', l: 'All' }] as dr}
				<button
					class="px-2 py-1 rounded-lg transition {dateRange === dr.k
						? 'bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white'
						: 'text-gray-500 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}"
					on:click={() => setDateRange(dr.k)}
				>
					{dr.l}
				</button>
			{/each}
		</div>

		<!-- Action filter -->
		<select
			class="text-xs rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1 outline-hidden"
			bind:value={selectedAction}
			on:change={refresh}
		>
			<option value="">{$i18n.t('All Actions')}</option>
			<option value="block">{$i18n.t('Blocked')}</option>
			<option value="log">{$i18n.t('Warning')}</option>
		</select>

		<!-- Refresh button -->
		<button
			class="ml-auto text-xs px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
			on:click={refresh}
			disabled={loading}
		>
			{$i18n.t('Refresh')}
		</button>
	</div>

	<!-- Table -->
	<div class="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
		<table class="w-full text-xs">
			<thead>
				<tr class="bg-gray-50 dark:bg-gray-850 text-gray-500 dark:text-gray-400">
					<th class="px-3 py-2 text-left font-medium w-5"></th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Time')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('User')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Action')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Pattern')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Model')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Provider')}</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100 dark:divide-gray-800">
				{#if loading}
					<tr>
						<td colspan="7" class="px-3 py-8 text-center text-gray-400 dark:text-gray-500">
							{$i18n.t('Loading...')}
						</td>
					</tr>
				{:else if logs.length === 0}
					<tr>
						<td colspan="7" class="px-3 py-8 text-center">
							<div class="mb-3">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="currentColor"
									class="size-10 mx-auto text-gray-300 dark:text-gray-600"
								>
									<path
										fill-rule="evenodd"
										d="M12.516 2.17a.75.75 0 0 0-1.032 0 11.209 11.209 0 0 1-7.877 3.08.75.75 0 0 0-.722.515A12.74 12.74 0 0 0 2.25 9.75c0 5.942 4.064 10.933 9.563 12.348a.749.749 0 0 0 .374 0c5.499-1.415 9.563-6.406 9.563-12.348 0-1.39-.223-2.73-.635-3.985a.75.75 0 0 0-.722-.516l-.143.001c-2.996 0-5.717-1.17-7.734-3.08Zm3.094 8.016a.75.75 0 1 0-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 0 0-1.06 1.06l2.25 2.25a.75.75 0 0 0 1.14-.094l3.75-5.25Z"
										clip-rule="evenodd"
									/>
								</svg>
							</div>
							<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
								{$i18n.t('No Security Logs')}
							</div>
							<div
								class="text-xs text-gray-500 dark:text-gray-500 leading-relaxed max-w-sm mx-auto"
							>
								{$i18n.t(
									'Guardrail and file pattern detection logs will appear here when security events are triggered.'
								)}
							</div>
						</td>
					</tr>
				{:else}
					{#each logs as log (log.id)}
						<!-- svelte-ignore a11y-click-events-have-key-events -->
						<tr
							class="hover:bg-gray-50 dark:hover:bg-gray-900/50 transition cursor-pointer"
							on:click={() => toggleExpand(log.id)}
						>
							<td class="px-2 py-2 text-gray-400">
								<svg
									class="size-3.5 transition-transform {expandedId === log.id
										? 'rotate-90'
										: ''}"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M9 5l7 7-7 7"
									/>
								</svg>
							</td>
							<td class="px-3 py-2 whitespace-nowrap text-gray-600 dark:text-gray-400">
								{formatTime(log.created_at)}
							</td>
							<td class="px-3 py-2">
								<Tooltip content={log.user_email || log.user_id || ''}>
									<span class="text-gray-800 dark:text-gray-200">
										{log.user_name || log.user_email || log.user_id || '-'}
									</span>
								</Tooltip>
							</td>
							<td class="px-3 py-2">
								<span
									class="inline-flex px-1.5 py-0.5 rounded text-xs font-medium {log.action ===
									'block'
										? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300'
										: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'}"
								>
									{log.action === 'block' ? $i18n.t('Blocked') : $i18n.t('Warning')}
								</span>
							</td>
							<td class="px-3 py-2">
								<span
									class="inline-flex px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 font-mono"
								>
									{log.meta?.pattern || log.detection_detail || '-'}
								</span>
							</td>
							<td class="px-3 py-2">
								{#if log.meta?.model_id}
									<span
										class="inline-flex px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 font-mono"
									>
										{log.meta.model_id}
									</span>
								{:else}
									<span class="text-gray-400 dark:text-gray-600">-</span>
								{/if}
							</td>
							<td class="px-3 py-2 text-gray-600 dark:text-gray-400">
								{log.meta?.provider_id || '-'}
							</td>
						</tr>

						<!-- Expanded detail row -->
						{#if expandedId === log.id}
							<tr>
								<td colspan="7" class="px-0 py-0">
									<div
										class="mx-3 my-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-850 space-y-3 text-xs"
									>
										<!-- Detection Info -->
										<div>
											<div
												class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2"
											>
												<svg
													class="size-3.5"
													fill="none"
													viewBox="0 0 24 24"
													stroke="currentColor"
													stroke-width="2"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
													/>
												</svg>
												{$i18n.t('Detection Detail')}
											</div>
											<div class="pl-5.5 space-y-1">
												<div class="flex items-center gap-2">
													<span class="text-gray-500 dark:text-gray-500"
														>{$i18n.t('Source')}:</span
													>
													<span class="text-gray-700 dark:text-gray-300"
														>{log.detection_source}</span
													>
												</div>
												<div class="flex items-center gap-2">
													<span class="text-gray-500 dark:text-gray-500"
														>{$i18n.t('Detail')}:</span
													>
													<span class="text-gray-700 dark:text-gray-300"
														>{log.detection_detail || '-'}</span
													>
												</div>
												{#if log.guardrail_name}
													<div class="flex items-center gap-2">
														<span class="text-gray-500 dark:text-gray-500"
															>{$i18n.t('Guardrail')}:</span
														>
														<span class="text-gray-700 dark:text-gray-300"
															>{log.guardrail_name}</span
														>
													</div>
												{/if}
											</div>
										</div>

										<!-- Matched Content -->
										{#if log.original_content}
											<div>
												<div
													class="font-medium text-gray-700 dark:text-gray-300 mb-1 flex items-center gap-2"
												>
													<svg
														class="size-3.5"
														fill="none"
														viewBox="0 0 24 24"
														stroke="currentColor"
														stroke-width="2"
													>
														<path
															stroke-linecap="round"
															stroke-linejoin="round"
															d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
														/>
													</svg>
													{$i18n.t('Matched Content')}
												</div>
												<div
													class="pl-5.5 text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-all leading-relaxed max-h-32 overflow-y-auto font-mono bg-white dark:bg-gray-900 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2"
												>
													{log.original_content}
												</div>
											</div>
										{/if}

										<!-- No detail data -->
										{#if !log.original_content && !log.detection_detail}
											<div class="text-gray-400 dark:text-gray-500 text-center py-2">
												{$i18n.t('No detail data available')}
											</div>
										{/if}
									</div>
								</td>
							</tr>
						{/if}
					{/each}
				{/if}
			</tbody>
		</table>
	</div>

	<!-- Pagination -->
	{#if totalPages > 1}
		<div
			class="flex items-center justify-between mt-3 text-xs text-gray-500 dark:text-gray-400"
		>
			<div>
				{$i18n.t('Page')} {page} / {totalPages} ({total.toLocaleString()}
				{$i18n.t('records')})
			</div>
			<div class="flex gap-1">
				<button
					class="px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition disabled:opacity-40"
					disabled={page <= 1}
					on:click={() => {
						page--;
						loadLogs();
					}}
				>
					{$i18n.t('Previous')}
				</button>
				<button
					class="px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition disabled:opacity-40"
					disabled={page >= totalPages}
					on:click={() => {
						page++;
						loadLogs();
					}}
				>
					{$i18n.t('Next')}
				</button>
			</div>
		</div>
	{/if}
</div>
