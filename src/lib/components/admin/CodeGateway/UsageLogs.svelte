<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		getCodeGatewayUsageLogs,
		getCodeGatewayUsageStats,
		getCodeGatewayFilterModels,
		getCodeGatewayFilterUsers,
		type CodeGatewayUsageLog,
		type CodeGatewayUsageStats
	} from '$lib/apis/code-gateway';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	// Filters
	let dateRange = '7d';
	let customFrom = '';
	let customTo = '';
	let selectedUserId = '';
	let selectedModelId = '';

	// Pagination
	let page = 1;
	let limit = 50;
	let totalPages = 1;
	let total = 0;

	// Data
	let logs: CodeGatewayUsageLog[] = [];
	let stats: CodeGatewayUsageStats = {
		total_requests: 0,
		total_tokens: 0,
		unique_users: 0,
		unique_models: 0
	};
	let filterModels: { id: string; name: string }[] = [];
	let filterUsers: { id: string; name: string }[] = [];

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
			const result = await getCodeGatewayUsageLogs(localStorage.token, {
				page,
				limit,
				user_id: selectedUserId || undefined,
				model_id: selectedModelId || undefined,
				...dateParams
			});
			logs = result.items;
			total = result.total;
			totalPages = result.total_pages;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load usage logs'));
		}
		loading = false;
	}

	async function loadStats() {
		try {
			const dateParams = getDateRange();
			stats = await getCodeGatewayUsageStats(localStorage.token, dateParams);
		} catch {
			// ignore
		}
	}

	async function loadFilters() {
		try {
			filterModels = await getCodeGatewayFilterModels(localStorage.token);
		} catch {
			filterModels = [];
		}
		try {
			filterUsers = await getCodeGatewayFilterUsers(localStorage.token);
		} catch {
			filterUsers = [];
		}
	}

	async function refresh() {
		page = 1;
		expandedId = null;
		await Promise.all([loadLogs(), loadStats()]);
	}

	function formatTime(ts: number): string {
		return new Date(ts * 1000).toLocaleString();
	}

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
		if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
		return String(n);
	}

	function setDateRange(range: string) {
		dateRange = range;
		refresh();
	}

	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	function truncateArgs(args: string | undefined, maxLen = 200): string {
		if (!args) return '';
		return args.length > maxLen ? args.slice(0, maxLen) + '...' : args;
	}

	onMount(async () => {
		await loadFilters();
		await refresh();
	});
</script>

<div class="w-full max-w-full">
	<!-- Stats Cards -->
	<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
		<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
			<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Total Requests')}</div>
			<div class="text-xl font-semibold mt-0.5">{stats.total_requests.toLocaleString()}</div>
		</div>
		<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
			<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Total Tokens')}</div>
			<div class="text-xl font-semibold mt-0.5">{formatTokens(stats.total_tokens)}</div>
		</div>
		<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
			<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Unique Users')}</div>
			<div class="text-xl font-semibold mt-0.5">{stats.unique_users}</div>
		</div>
		<div class="rounded-xl bg-gray-50 dark:bg-gray-850 p-3">
			<div class="text-xs text-gray-500 dark:text-gray-500">{$i18n.t('Unique Models')}</div>
			<div class="text-xl font-semibold mt-0.5">{stats.unique_models}</div>
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

		<!-- Model filter -->
		{#if filterModels.length > 0}
			<select
				class="text-xs rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1 outline-hidden"
				bind:value={selectedModelId}
				on:change={refresh}
			>
				<option value="">{$i18n.t('All Models')}</option>
				{#each filterModels as m}
					<option value={m.id}>{m.name}</option>
				{/each}
			</select>
		{/if}

		<!-- User filter -->
		{#if filterUsers.length > 0}
			<select
				class="text-xs rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1 outline-hidden"
				bind:value={selectedUserId}
				on:change={refresh}
			>
				<option value="">{$i18n.t('All Users')}</option>
				{#each filterUsers as u}
					<option value={u.id}>{u.name}</option>
				{/each}
			</select>
		{/if}

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
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Model')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Provider')}</th>
					<th class="px-3 py-2 text-left font-medium">{$i18n.t('Platform')}</th>
					<th class="px-3 py-2 text-right font-medium">{$i18n.t('Input')}</th>
					<th class="px-3 py-2 text-right font-medium">{$i18n.t('Output')}</th>
					<th class="px-3 py-2 text-right font-medium">{$i18n.t('Total')}</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100 dark:divide-gray-800">
				{#if loading}
					<tr>
						<td colspan="8" class="px-3 py-8 text-center text-gray-400 dark:text-gray-500">
							{$i18n.t('Loading...')}
						</td>
					</tr>
				{:else if logs.length === 0}
					<tr>
						<td colspan="8" class="px-3 py-8 text-center text-gray-400 dark:text-gray-500">
							{$i18n.t('No usage logs found')}
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
									class="size-3.5 transition-transform {expandedId === log.id ? 'rotate-90' : ''}"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
								</svg>
							</td>
							<td class="px-3 py-2 whitespace-nowrap text-gray-600 dark:text-gray-400">
								{formatTime(log.created_at)}
							</td>
							<td class="px-3 py-2">
								<Tooltip content={log.user_email}>
									<span class="text-gray-800 dark:text-gray-200"
										>{log.user_name || log.user_email}</span
									>
								</Tooltip>
							</td>
							<td class="px-3 py-2">
								<span
									class="inline-flex px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 font-mono"
								>
									{log.model_id}
								</span>
							</td>
							<td class="px-3 py-2 text-gray-600 dark:text-gray-400">
								{log.provider}
							</td>
							<td class="px-3 py-2">
								{#if log.client_type}
									<span class="inline-flex px-1.5 py-0.5 rounded text-xs
										{log.client_type === 'cursor' ? 'bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300' :
										 log.client_type === 'claude-code' ? 'bg-orange-50 dark:bg-orange-900/20 text-orange-700 dark:text-orange-300' :
										 log.client_type === 'codex-cli' ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300' :
										 log.client_type === 'gemini-cli' ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300' :
										 'bg-gray-50 dark:bg-gray-900/20 text-gray-700 dark:text-gray-300'}">
										{log.client_type === 'cursor' ? 'Cursor' :
										 log.client_type === 'claude-code' ? 'Claude Code' :
										 log.client_type === 'codex-cli' ? 'Codex CLI' :
										 log.client_type === 'gemini-cli' ? 'Gemini CLI' :
										 log.client_type}
									</span>
								{/if}
							</td>
							<td
								class="px-3 py-2 text-right tabular-nums text-gray-600 dark:text-gray-400"
							>
								{log.input_tokens.toLocaleString()}
							</td>
							<td
								class="px-3 py-2 text-right tabular-nums text-gray-600 dark:text-gray-400"
							>
								{log.output_tokens.toLocaleString()}
							</td>
							<td
								class="px-3 py-2 text-right tabular-nums font-medium text-gray-800 dark:text-gray-200"
							>
								{log.total_tokens.toLocaleString()}
							</td>
						</tr>

						<!-- Expanded detail row -->
						{#if expandedId === log.id}
							<tr>
								<td colspan="8" class="px-0 py-0">
									<div
										class="mx-3 my-2 p-4 rounded-lg bg-gray-50 dark:bg-gray-850 space-y-3 text-xs"
									>
										<!-- Request section -->
										{#if log.input_preview || log.message_count}
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
															d="M4.5 12.75l6 6 9-13.5"
														/>
													</svg>
													{$i18n.t('Request')}
													{#if log.message_count}
														<span
															class="text-gray-400 dark:text-gray-500 font-normal"
															>({log.message_count}
															{$i18n.t('messages')}{#if log.tools_count},
																{log.tools_count}
																{$i18n.t('tools')}{/if})</span
														>
													{/if}
												</div>
												{#if log.input_preview}
													<div
														class="pl-5.5 text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-all leading-relaxed max-h-32 overflow-y-auto"
													>
														{log.input_preview}
													</div>
												{/if}
											</div>
										{/if}

										<!-- Response section -->
										{#if log.output_preview}
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
															d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z"
														/>
													</svg>
													{$i18n.t('Response')}
													{#if log.finish_reason}
														<span
															class="text-gray-400 dark:text-gray-500 font-normal"
															>({log.finish_reason})</span
														>
													{/if}
												</div>
												<div
													class="pl-5.5 text-gray-600 dark:text-gray-400 whitespace-pre-wrap break-all leading-relaxed max-h-48 overflow-y-auto"
												>
													{log.output_preview}
												</div>
											</div>
										{/if}

										<!-- Tool calls section -->
										{#if log.tool_calls && log.tool_calls.length > 0}
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
															d="M11.42 15.17l-5.1-5.1m0 0L11.42 4.97m-5.1 5.1H21M3 21V3"
														/>
													</svg>
													{$i18n.t('Function Calls')}
													<span
														class="text-gray-400 dark:text-gray-500 font-normal"
														>({log.tool_calls.length})</span
													>
												</div>
												<div class="pl-5.5 space-y-1.5">
													{#each log.tool_calls as tc}
														<div
															class="flex items-start gap-2 rounded-md bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 px-2.5 py-1.5"
														>
															<span
																class="font-mono font-medium text-amber-700 dark:text-amber-400 shrink-0"
																>{tc.name}</span
															>
															{#if tc.arguments}
																<span
																	class="text-gray-500 dark:text-gray-500 font-mono break-all"
																	>{truncateArgs(tc.arguments)}</span
																>
															{/if}
														</div>
													{/each}
												</div>
											</div>
										{/if}

										<!-- Token details -->
										{#if log.token_details && Object.keys(log.token_details).length > 0}
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
															d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5"
														/>
													</svg>
													{$i18n.t('Token Details')}
												</div>
												<div class="pl-5.5 flex flex-wrap gap-3">
													{#if log.token_details.input}
														{@const inputDetails = log.token_details.input}
														{#if typeof inputDetails === 'object' && inputDetails !== null}
															{#each Object.entries(inputDetails) as [key, val]}
																<span
																	class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700"
																>
																	<span
																		class="text-gray-500 dark:text-gray-500"
																		>{key}:</span
																	>
																	<span
																		class="font-medium text-gray-700 dark:text-gray-300"
																		>{val}</span
																	>
																</span>
															{/each}
														{/if}
													{/if}
													{#if log.token_details.output}
														{@const outputDetails = log.token_details.output}
														{#if typeof outputDetails === 'object' && outputDetails !== null}
															{#each Object.entries(outputDetails) as [key, val]}
																<span
																	class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700"
																>
																	<span
																		class="text-gray-500 dark:text-gray-500"
																		>{key}:</span
																	>
																	<span
																		class="font-medium text-gray-700 dark:text-gray-300"
																		>{val}</span
																	>
																</span>
															{/each}
														{/if}
													{/if}
												</div>
											</div>
										{/if}

										<!-- No detail data -->
										{#if !log.input_preview && !log.output_preview && (!log.tool_calls || log.tool_calls.length === 0)}
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
