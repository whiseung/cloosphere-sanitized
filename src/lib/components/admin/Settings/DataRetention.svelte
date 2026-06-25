<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { formatBackendError } from '$lib/utils/error';
	import {
		getDataRetentionConfig,
		setDataRetentionConfig,
		getDataRetentionStats,
		executeDataRetentionCleanup,
		type DataRetentionConfig,
		type DataRetentionStats
	} from '$lib/apis/configs/data-retention';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let loading = true;
	let cleanupLoading = false;

	// Task Queue status
	let queueStatus: { redis: { connected: boolean }; queue: { total: number; pending: number; consumers: number } } | null = null;
	let queueTasks: any[] = [];
	let showQueueTasks = false;

	// Consumer / Pending (좀비 정리)
	let consumers: Array<{ name: string; pending: number; idle_ms: number; is_zombie: boolean }> = [];
	let pendingMessages: Array<{ msg_id: string; consumer: string; idle_ms: number; deliveries: number }> = [];
	let showConsumers = false;

	async function loadQueueStatus() {
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/status`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (res.ok) queueStatus = await res.json();
		} catch { /* silent */ }
	}

	async function loadQueueTasks() {
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/tasks`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (res.ok) queueTasks = await res.json();
		} catch { /* silent */ }
	}

	async function deleteQueueTask(msgId: string) {
		if (!confirm($i18n.t('Delete this task? It will NOT be processed and is permanently lost.'))) return;
		try {
			await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/tasks/${msgId}`, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			queueTasks = queueTasks.filter(t => t.msg_id !== msgId);
			await loadQueueStatus();
		} catch { /* silent */ }
	}

	async function clearQueue() {
		if (!confirm($i18n.t('Clear ALL tasks in the queue? None of them will be processed and all are permanently lost.'))) return;
		try {
			await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/tasks`, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			queueTasks = [];
			toast.success($i18n.t('Queue cleared'));
			await loadQueueStatus();
		} catch { /* silent */ }
	}

	async function loadConsumers() {
		try {
			const [cRes, pRes] = await Promise.all([
				fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/consumers`, {
					headers: { Authorization: `Bearer ${localStorage.token}` }
				}),
				fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/pending?count=20`, {
					headers: { Authorization: `Bearer ${localStorage.token}` }
				})
			]);
			if (cRes.ok) consumers = await cRes.json();
			if (pRes.ok) pendingMessages = await pRes.json();
		} catch { /* silent */ }
	}

	async function deleteConsumer(name: string, pending: number) {
		// pending이 있으면 "Reclaim & Delete"로 안내 (별도 버튼 호출)
		if (pending > 0) {
			toast.error($i18n.t('Consumer has {{n}} pending message(s). Use Reclaim & Delete instead.', { n: pending }));
			return;
		}
		if (!confirm($i18n.t('Delete consumer "{{name}}"?', { name }))) return;
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/consumers/${encodeURIComponent(name)}`, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			const body = await res.json();
			if (body.success) {
				toast.success($i18n.t('Consumer deleted'));
			} else {
				toast.error($i18n.t('Failed to delete consumer'));
			}
			await loadConsumers();
			await loadQueueStatus();
		} catch { /* silent */ }
	}

	async function reclaimAndDeleteConsumer(name: string, pending: number) {
		const msg = $i18n.t(
			'Consumer "{{name}}" has {{n}} pending message(s). They will be force-ack\'d and dropped (the actual work will NOT run). Continue?',
			{ name, n: pending }
		);
		if (!confirm(msg)) return;
		try {
			const url = `${WEBUI_API_BASE_URL}/configs/external-worker/consumers/${encodeURIComponent(name)}?reclaim_pending=true`;
			const res = await fetch(url, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			const body = await res.json();
			if (body.success) {
				toast.success(
					$i18n.t('Reclaimed {{r}} message(s) and deleted consumer', { r: body.reclaimed })
				);
			} else {
				toast.error($i18n.t('Failed to reclaim & delete'));
			}
			await loadConsumers();
			await loadQueueStatus();
		} catch { /* silent */ }
	}

	async function cleanupZombies() {
		if (!confirm($i18n.t('Cleanup all zombie consumers (idle > 1h, no pending)?'))) return;
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/cleanup-zombies`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			const body = await res.json();
			toast.success($i18n.t('Cleaned up {{n}} zombie consumer(s)', { n: body.deleted }));
			await loadConsumers();
			await loadQueueStatus();
		} catch { /* silent */ }
	}

	async function deletePendingMessage(msgId: string, consumer: string, idleMs: number) {
		const msg = $i18n.t(
			'Force-ack and delete this pending message?\n\nmsg_id: {{id}}\nconsumer: {{c}}\nidle: {{idle}}\n\nThe actual work will NOT run and the message is permanently lost.',
			{ id: msgId, c: consumer, idle: formatIdle(idleMs) }
		);
		if (!confirm(msg)) return;
		try {
			const res = await fetch(
				`${WEBUI_API_BASE_URL}/configs/external-worker/pending/${encodeURIComponent(msgId)}`,
				{
					method: 'DELETE',
					headers: { Authorization: `Bearer ${localStorage.token}` }
				}
			);
			const body = await res.json();
			if (body.success) {
				toast.success($i18n.t('Pending message deleted'));
				pendingMessages = pendingMessages.filter((p) => p.msg_id !== msgId);
				await loadConsumers();
				await loadQueueStatus();
			} else {
				toast.error(
					$i18n.t('Failed to delete pending message: {{err}}', {
						err: body.error || 'unknown'
					})
				);
			}
		} catch {
			toast.error($i18n.t('Failed to delete pending message'));
		}
	}

	async function reclaimStuck() {
		if (!confirm($i18n.t('Force-ack stuck pending messages (idle > 5m)?'))) return;
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/reclaim-stuck`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			const body = await res.json();
			toast.success($i18n.t('Reclaimed {{n}} stuck message(s)', { n: body.reclaimed }));
			await loadConsumers();
			await loadQueueStatus();
		} catch { /* silent */ }
	}

	function formatTime(ts: number) {
		if (!ts) return '-';
		return new Date(ts * 1000).toLocaleString();
	}

	function formatIdle(ms: number): string {
		if (ms < 1000) return `${ms}ms`;
		const s = ms / 1000;
		if (s < 60) return `${s.toFixed(0)}s`;
		const m = s / 60;
		if (m < 60) return `${m.toFixed(0)}m`;
		const h = m / 60;
		if (h < 24) return `${h.toFixed(1)}h`;
		return `${(h / 24).toFixed(1)}d`;
	}
	let retentionConfig: DataRetentionConfig | null = null;
	let stats: DataRetentionStats | null = null;

	const cleanupHourOptions = Array.from({ length: 24 }, (_, h) => ({
		value: String(h),
		label: `${String(h).padStart(2, '0')}:00`
	}));

	// Worker Auto Cleanup 설정
	type WorkerCleanupConfig = {
		ENABLE_WORKER_AUTO_CLEANUP: boolean;
		WORKER_ZOMBIE_IDLE_HOURS: number;
		WORKER_STUCK_IDLE_HOURS: number;
		WORKER_CLEANUP_INTERVAL_MINUTES: number;
	};
	let workerCleanupConfig: WorkerCleanupConfig | null = null;

	async function loadWorkerCleanupConfig() {
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/data-retention/worker-cleanup`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (res.ok) workerCleanupConfig = await res.json();
		} catch {
			/* silent */
		}
	}

	async function saveWorkerCleanupConfig() {
		if (!workerCleanupConfig) return false;
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/data-retention/worker-cleanup`, {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${localStorage.token}`,
					'Content-Type': 'application/json'
				},
				body: JSON.stringify(workerCleanupConfig)
			});
			if (res.ok) {
				workerCleanupConfig = await res.json();
				return true;
			}
			return false;
		} catch {
			return false;
		}
	}

	const TABLE_CONFIG_KEYS: Record<string, keyof DataRetentionConfig> = {
		log_usage: 'RETENTION_DAYS_USAGE',
		audit_log: 'RETENTION_DAYS_AUDIT_LOG',
		log_guardrail: 'RETENTION_DAYS_GUARDRAIL_LOG',
		message_trace: 'RETENTION_DAYS_TRACE',
		trace_analysis: 'RETENTION_DAYS_TRACE_ANALYSIS',
		auto_evaluation: 'RETENTION_DAYS_AUTO_EVALUATION'
	};

	const TABLE_LABELS: Record<string, string> = {
		log_usage: 'Usage Logs',
		audit_log: 'Audit Logs',
		log_guardrail: 'Guardrail Logs',
		message_trace: 'Traces',
		trace_analysis: 'Trace Analysis',
		auto_evaluation: 'Auto Evaluations'
	};

	const loadData = async () => {
		try {
			[retentionConfig, stats] = await Promise.all([
				getDataRetentionConfig(localStorage.token),
				getDataRetentionStats(localStorage.token)
			]);
		} catch (err) {
			toast.error(formatBackendError(err, $i18n) || $i18n.t('Failed to load data retention settings'));
		} finally {
			loading = false;
		}
	};

	const submitHandler = async () => {
		if (!retentionConfig) return;

		try {
			retentionConfig = await setDataRetentionConfig(localStorage.token, retentionConfig);
			if (workerCleanupConfig) {
				await saveWorkerCleanupConfig();
			}
			toast.success($i18n.t('Settings saved successfully!'));
		} catch (err) {
			toast.error(formatBackendError(err, $i18n) || $i18n.t('Failed to save settings'));
		}
	};

	const handleCleanup = async () => {
		if (!retentionConfig) return;

		const hasRetention = Object.values(TABLE_CONFIG_KEYS).some(
			(key) => (retentionConfig as any)[key] > 0
		);

		if (!hasRetention) {
			toast.error($i18n.t('Set retention period for at least one log type before cleanup'));
			return;
		}

		try {
			retentionConfig = await setDataRetentionConfig(localStorage.token, retentionConfig);
		} catch (err) {
			toast.error(formatBackendError(err, $i18n) || $i18n.t('Failed to save settings'));
			return;
		}

		cleanupLoading = true;
		try {
			const result = await executeDataRetentionCleanup(localStorage.token);
			if (result.total_deleted > 0) {
				toast.success(
					$i18n.t('Cleanup completed: {{count}} records deleted', {
						count: result.total_deleted
					})
				);
			} else {
				toast.success($i18n.t('No records to delete'));
			}
			stats = await getDataRetentionStats(localStorage.token);
		} catch (err) {
			toast.error(formatBackendError(err, $i18n) || $i18n.t('Cleanup failed'));
		} finally {
			cleanupLoading = false;
		}
	};

	onMount(async () => {
		await loadData();
		await loadQueueStatus();
		await loadWorkerCleanupConfig();
	});
</script>

{#if loading}
	<div class="flex justify-center py-8">
		<Spinner />
	</div>
{:else if retentionConfig}
	<form
		class="flex flex-col h-full justify-between space-y-3 text-sm"
		on:submit|preventDefault={submitHandler}
	>
		<div class="mt-0.5 space-y-3 overflow-y-scroll scrollbar-hidden h-full">
			<!-- Auto Cleanup -->
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Auto Cleanup')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="mb-2.5 flex w-full items-center justify-between pr-2">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Enable Auto Cleanup')}
					</div>
					<Switch bind:state={retentionConfig.ENABLE_DATA_RETENTION} />
				</div>

				{#if retentionConfig.ENABLE_DATA_RETENTION}
					<div class="mb-2.5 flex w-full items-center justify-between gap-2">
						<div class="self-center text-xs font-medium">
							{$i18n.t('Cleanup Time')}
						</div>
						<div class="min-w-[120px]">
							<Selector
								value={String(retentionConfig.DATA_RETENTION_CLEANUP_HOUR ?? 0)}
								items={cleanupHourOptions}
								size="sm"
								searchEnabled={false}
								on:change={(e) => {
									if (retentionConfig) {
										retentionConfig.DATA_RETENTION_CLEANUP_HOUR = Number(e.detail.value);
									}
								}}
							/>
						</div>
					</div>
				{/if}
			</div>

			<!-- Retention Settings -->
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Retention Settings')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="flex items-start gap-2 text-xs text-gray-500 dark:text-gray-400 mb-3">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-3.5 shrink-0 mt-0.5 text-amber-500"
					>
						<path d="M8 1.5A4.5 4.5 0 0 0 3.5 6c0 1.56.768 2.938 1.945 3.782A.5.5 0 0 1 5.67 10H6v1.25a.75.75 0 0 0 1.5 0V10h1v1.25a.75.75 0 0 0 1.5 0V10h.33a.5.5 0 0 1 .225.218C11.732 8.938 12.5 7.56 12.5 6A4.5 4.5 0 0 0 8 1.5ZM5.75 13a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5Z" />
					</svg>
					<span>
						{$i18n.t(
							'Configure automatic cleanup of log data. Set retention period to 0 for permanent storage.'
						)}
					</span>
				</div>

				{#if stats}
					{#each stats.tables as table}
						<div class="mb-2.5 flex w-full items-center justify-between gap-3">
							<div class="flex flex-col min-w-0">
								<div class="text-xs font-medium">
									{$i18n.t(TABLE_LABELS[table.table_name] || table.label)}
								</div>
								<div class="text-xs text-gray-400 dark:text-gray-500 truncate">
									{table.row_count.toLocaleString()} {$i18n.t('records')}
									{#if table.total_size}
										· {table.total_size}
									{/if}
								</div>
							</div>
							<div class="flex items-center gap-1.5 shrink-0">
								<input
									type="number"
									min="0"
									class="w-16 sm:w-20 text-right rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
									bind:value={retentionConfig[TABLE_CONFIG_KEYS[table.table_name]]}
									placeholder="0"
								/>
								<span class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap"
									>{$i18n.t('days')}</span
								>
							</div>
						</div>
					{/each}
				{/if}

			</div>

			<!-- Manual Cleanup -->
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Manual Cleanup')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t('Save settings and immediately delete records exceeding the retention period.')}
				</div>

				<Button
					kind="outlined"
					size="sm"
					type="button"
					disabled={cleanupLoading}
					loading={cleanupLoading}
					on:click={handleCleanup}
				>
					<svelte:fragment slot="prefix">
						<GarbageBin className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('Run Cleanup Now')}
				</Button>
			</div>

		<!-- Task Queue -->
		{#if queueStatus}
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Task Queue')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t('Background processing queue for heavy tasks like file processing.')}
					{#if queueStatus.redis.connected}
						<span class="inline-flex items-center gap-1 ml-1">
							<span class="w-1.5 h-1.5 rounded-full bg-green-500 inline-block"></span>
							Redis
						</span>
					{:else}
						<span class="ml-1">({$i18n.t('In-process')})</span>
					{/if}
				</div>

				{#if queueStatus.redis.connected}
					<div class="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
						<button
							type="button"
							class="hover:text-gray-700 dark:hover:text-gray-300 transition-colors {queueStatus.queue.total > 0 ? 'underline cursor-pointer' : ''}"
							on:click={() => { if (queueStatus.queue.total > 0) { showQueueTasks = !showQueueTasks; if (showQueueTasks) loadQueueTasks(); } }}
						>
							{$i18n.t('Queued')}: {queueStatus.queue.total}
						</button>
						<span>{$i18n.t('Processing')}: {queueStatus.queue.pending}</span>
						<span>{$i18n.t('Workers')}: {queueStatus.queue.consumers}</span>
						<button
							type="button"
							class="ml-auto hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
							on:click={loadQueueStatus}
						>
							{$i18n.t('Refresh')}
						</button>
					</div>

					{#if showQueueTasks && queueTasks.length > 0}
						<div class="mt-2 space-y-1 max-h-40 overflow-y-auto">
							<div class="flex items-center justify-end mb-1">
								<Tooltip
									content={$i18n.t(
										'Delete ALL queued tasks. None will be processed (permanently lost).'
									)}
								>
									<Button
										kind="text"
										size="sm"
										status="error"
										type="button"
										on:click={clearQueue}
									>
										{$i18n.t('Clear All')}
									</Button>
								</Tooltip>
							</div>
							{#each queueTasks as task}
								<div class="flex items-center justify-between rounded border border-gray-100 dark:border-gray-800 p-2 text-xs">
									<div class="flex items-center gap-2 min-w-0">
										<span class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 font-mono text-[10px]">{task.task_type}</span>
										<span class="text-gray-400 truncate">{formatTime(task.created_at)}</span>
									</div>
									<Tooltip
										content={$i18n.t(
											'Delete this task. It will NOT be processed (permanently lost).'
										)}
									>
										<Button
											kind="text"
											size="sm"
											status="error"
											type="button"
											on:click={() => deleteQueueTask(task.msg_id)}
										>
											<XMark className="size-3" />
										</Button>
									</Tooltip>
								</div>
							{/each}
						</div>
					{/if}

					<!-- Worker Auto Cleanup 설정 -->
					{#if workerCleanupConfig}
						<div class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-850">
							<div class="flex items-center justify-between mb-2">
								<div class="text-xs font-medium text-gray-700 dark:text-gray-300">
									{$i18n.t('Worker Auto Cleanup')}
								</div>
								<Switch bind:state={workerCleanupConfig.ENABLE_WORKER_AUTO_CLEANUP} />
							</div>
							<div class="text-[11px] text-gray-500 dark:text-gray-400 mb-2.5">
								{$i18n.t(
									'Periodically clean up zombie consumers and stuck messages without manual action. Active workers and in-progress jobs are never affected.'
								)}
							</div>

							{#if workerCleanupConfig.ENABLE_WORKER_AUTO_CLEANUP}
								<div class="space-y-2 pl-1">
									<div class="flex items-center justify-between gap-3">
										<div class="flex flex-col min-w-0">
											<div class="text-xs">{$i18n.t('Zombie consumer idle threshold')}</div>
											<div class="text-[10px] text-gray-400 dark:text-gray-500">
												{$i18n.t('Delete consumers idle longer than this AND with 0 pending')}
											</div>
										</div>
										<div class="flex items-center gap-1.5 shrink-0">
											<input
												type="number"
												min="1"
												class="w-16 sm:w-20 text-right rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
												bind:value={workerCleanupConfig.WORKER_ZOMBIE_IDLE_HOURS}
											/>
											<span class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap"
												>{$i18n.t('hours')}</span
											>
										</div>
									</div>

									<div class="flex items-center justify-between gap-3">
										<div class="flex flex-col min-w-0">
											<div class="text-xs">{$i18n.t('Stuck message idle threshold')}</div>
											<div class="text-[10px] text-gray-400 dark:text-gray-500">
												{$i18n.t(
													'Force-ack pending messages older than this. Set longer than your longest job.'
												)}
											</div>
										</div>
										<div class="flex items-center gap-1.5 shrink-0">
											<input
												type="number"
												min="1"
												class="w-16 sm:w-20 text-right rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
												bind:value={workerCleanupConfig.WORKER_STUCK_IDLE_HOURS}
											/>
											<span class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap"
												>{$i18n.t('hours')}</span
											>
										</div>
									</div>

									<div class="flex items-center justify-between gap-3">
										<div class="flex flex-col min-w-0">
											<div class="text-xs">{$i18n.t('Cleanup interval')}</div>
											<div class="text-[10px] text-gray-400 dark:text-gray-500">
												{$i18n.t('How often the auto cleanup runs')}
											</div>
										</div>
										<div class="flex items-center gap-1.5 shrink-0">
											<input
												type="number"
												min="1"
												class="w-16 sm:w-20 text-right rounded-lg py-1.5 px-2 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
												bind:value={workerCleanupConfig.WORKER_CLEANUP_INTERVAL_MINUTES}
											/>
											<span class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap"
												>{$i18n.t('minutes')}</span
											>
										</div>
									</div>
								</div>
							{/if}
						</div>
					{/if}

					<!-- Consumer / Stuck Pending 관리 -->
					<div class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-850">
						<div class="flex items-center gap-3 text-xs">
							<button
								type="button"
								class="text-gray-600 dark:text-gray-400 hover:underline"
								on:click={() => { showConsumers = !showConsumers; if (showConsumers) loadConsumers(); }}
							>
								{showConsumers ? '▼' : '▶'} {$i18n.t('Consumers & Stuck Messages')}
							</button>
							{#if showConsumers}
								<button type="button" class="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300" on:click={loadConsumers}>
									{$i18n.t('Refresh')}
								</button>
								<button
									type="button"
									class="ml-auto text-orange-500 hover:underline"
									title={$i18n.t('Safely remove consumers that have been idle > 1 hour AND have no pending messages. No data loss.')}
									on:click={cleanupZombies}
								>
									{$i18n.t('Cleanup Zombies')}
								</button>
								<button
									type="button"
									class="text-red-500 hover:underline"
									title={$i18n.t('Force-acknowledge pending messages idle > 5 minutes. The messages are DROPPED (actual work will not run).')}
									on:click={reclaimStuck}
								>
									{$i18n.t('Reclaim Stuck (>5m)')}
								</button>
							{/if}
						</div>

						{#if showConsumers}
							<!-- Consumer 목록 -->
							<div class="mt-2">
								<div class="text-[11px] text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Consumers')} ({consumers.length})</div>
								{#if consumers.length === 0}
									<div class="text-xs text-gray-400 italic p-2">{$i18n.t('No consumers registered')}</div>
								{:else}
									<div class="space-y-1 max-h-48 overflow-y-auto">
										{#each consumers as c}
											<div class="flex items-center justify-between rounded border {c.is_zombie ? 'border-orange-300 dark:border-orange-900' : 'border-gray-100 dark:border-gray-800'} p-2 text-xs">
												<div class="flex items-center gap-2 min-w-0 flex-1">
													{#if c.is_zombie}
														<span class="w-1.5 h-1.5 rounded-full bg-orange-500 inline-block flex-shrink-0" title={$i18n.t('Zombie (idle > 1h, no pending)')}></span>
													{:else if c.pending > 0}
														<span class="w-1.5 h-1.5 rounded-full bg-green-500 inline-block flex-shrink-0" title={$i18n.t('Active (processing)')}></span>
													{:else}
														<span class="w-1.5 h-1.5 rounded-full bg-gray-300 dark:bg-gray-600 inline-block flex-shrink-0" title={$i18n.t('Idle')}></span>
													{/if}
													<span class="font-mono text-[10px] text-gray-700 dark:text-gray-300 truncate">{c.name}</span>
												</div>
												<div class="flex items-center gap-2 flex-shrink-0">
													<span class="text-gray-500 dark:text-gray-400">pending: <span class={c.pending > 0 ? 'text-gray-700 dark:text-gray-300 font-medium' : ''}>{c.pending}</span></span>
													<span class="text-gray-400 w-12 text-right">{formatIdle(c.idle_ms)}</span>
													{#if c.pending > 0}
													<!-- Pending > 0: Reclaim & Delete (주의 — 경고 트라이앵글 아이콘 유지) -->
													<Tooltip
														content={$i18n.t(
															'Reclaim & Delete: force-ack {{n}} pending message(s), drop them, then delete this consumer. The work will NOT run.',
															{ n: c.pending }
														)}
													>
														<button
															type="button"
															class="p-0.5 hover:bg-orange-100 dark:hover:bg-orange-900/30 text-orange-500 hover:text-orange-600 rounded"
															on:click={() => reclaimAndDeleteConsumer(c.name, c.pending)}
														>
															<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
																<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
															</svg>
														</button>
													</Tooltip>
												{:else}
													<!-- Pending == 0: 일반 삭제 (안전) -->
													<Tooltip
														content={$i18n.t(
															'Delete this consumer registration. Stream messages are unaffected.'
														)}
													>
														<Button
															kind="text"
															size="sm"
															status="error"
															type="button"
															on:click={() => deleteConsumer(c.name, c.pending)}
														>
															<XMark className="size-3" />
														</Button>
													</Tooltip>
												{/if}
												</div>
											</div>
										{/each}
									</div>
								{/if}
							</div>

							<!-- Pending (오래된 순 20개) -->
							<div class="mt-3">
								<div class="text-[11px] text-gray-500 dark:text-gray-400 mb-1">
									{$i18n.t('Oldest Pending Messages')} ({pendingMessages.length})
								</div>
								{#if pendingMessages.length === 0}
									<div class="text-xs text-gray-400 italic p-2">{$i18n.t('No stuck messages')}</div>
								{:else}
									<div class="space-y-1 max-h-40 overflow-y-auto">
										{#each pendingMessages as p}
											<div class="flex items-center justify-between rounded border border-red-200 dark:border-red-900/50 bg-red-50/30 dark:bg-red-950/20 p-2 text-xs">
												<div class="flex items-center gap-2 min-w-0 flex-1">
													<span class="font-mono text-[10px] text-gray-700 dark:text-gray-300">{p.msg_id}</span>
													<span class="text-gray-500 text-[10px] truncate">{p.consumer}</span>
												</div>
												<div class="flex items-center gap-2 flex-shrink-0">
													<span class="text-red-500 font-medium">{formatIdle(p.idle_ms)}</span>
													<span class="text-gray-400 text-[10px]">×{p.deliveries}</span>
													<Tooltip
														content={$i18n.t(
															'Force-ack & delete this message. The actual work will NOT run (permanently lost).'
														)}
													>
														<Button
															kind="text"
															size="sm"
															status="error"
															type="button"
															on:click={() =>
																deletePendingMessage(p.msg_id, p.consumer, p.idle_ms)}
														>
															<XMark className="size-3" />
														</Button>
													</Tooltip>
												</div>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				{:else}
					<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Tasks are processed directly without queuing.')}</div>
				{/if}
			</div>
		{/if}
		</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
	</form>
{/if}
