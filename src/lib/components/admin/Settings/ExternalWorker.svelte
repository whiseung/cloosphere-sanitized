<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import Button from '$lib/components/common/Button.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let saveHandler: () => void;

	let loaded = false;

	// Redis & Queue status
	let redisStatus: { connected: boolean; message: string } = { connected: false, message: '' };
	let queueStats: { total: number; pending: number; consumers: number } = { total: 0, pending: 0, consumers: 0 };

	// Queue tasks list
	let queueTasks: any[] = [];
	let showQueueTasks = false;

	async function loadStatus() {
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/status`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (res.ok) {
				const data = await res.json();
				redisStatus = data.redis ?? { connected: false, message: 'Unknown' };
				queueStats = data.queue ?? { total: 0, pending: 0, consumers: 0 };
			}
		} catch {
			redisStatus = { connected: false, message: 'Failed to check status' };
		}
	}

	async function loadQueueTasks() {
		try {
			const res = await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/tasks`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (res.ok) {
				queueTasks = await res.json();
			}
		} catch { /* silent */ }
	}

	async function deleteTask(msgId: string) {
		try {
			await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/tasks/${msgId}`, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			queueTasks = queueTasks.filter(t => t.msg_id !== msgId);
			await loadStatus();
		} catch { /* silent */ }
	}

	async function clearQueue() {
		if (!confirm($i18n.t('Clear all tasks in the queue?'))) return;
		try {
			await fetch(`${WEBUI_API_BASE_URL}/configs/external-worker/tasks`, {
				method: 'DELETE',
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			queueTasks = [];
			toast.success($i18n.t('Queue cleared'));
			await loadStatus();
		} catch { /* silent */ }
	}

	function formatTime(ts: number) {
		if (!ts) return '-';
		return new Date(ts * 1000).toLocaleString();
	}

	onMount(async () => {
		await loadStatus();
		loaded = true;
	});
</script>

{#if !loaded}
	<div class="flex items-center justify-center h-64">
		<Spinner className="size-6" />
	</div>
{:else}
	<div class="flex flex-col h-full space-y-4 text-sm overflow-y-scroll scrollbar-hidden pr-1.5">
		<!-- Redis Status -->
		<div class="rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-default)] p-4">
			<div class="flex items-center justify-between mb-3">
				<div class="text-sm font-medium text-[var(--cloo-text-default)]">
					{$i18n.t('Background Worker')}
				</div>
				<div class="flex items-center gap-2">
					{#if redisStatus.connected}
						<div class="w-2.5 h-2.5 rounded-full bg-[var(--cloo-color-success)]"></div>
						<span class="text-xs text-[var(--cloo-text-muted)]">{$i18n.t('Active')}</span>
					{:else}
						<div class="w-2.5 h-2.5 rounded-full bg-[var(--cloo-text-muted)]"></div>
						<span class="text-xs text-[var(--cloo-text-muted)]">{$i18n.t('Inactive')}</span>
					{/if}
				</div>
			</div>

			{#if !redisStatus.connected}
				<p class="text-xs text-[var(--cloo-text-muted)]">
					{$i18n.t('Redis is not connected. Background tasks will be processed in the main server thread.')}
				</p>
			{:else}
				<div class="flex items-center gap-4 text-xs text-[var(--cloo-text-muted)]">
					<button
						type="button"
						class="hover:text-[var(--cloo-color-primary)] transition-colors {queueStats.total > 0 ? 'underline cursor-pointer' : ''}"
						on:click={() => { if (queueStats.total > 0) { showQueueTasks = !showQueueTasks; if (showQueueTasks) loadQueueTasks(); } }}
					>
						{$i18n.t('Queue')}: {queueStats.total} {$i18n.t('tasks')}
					</button>
					<span>{$i18n.t('Processing')}: {queueStats.pending}</span>
					<span>{$i18n.t('Workers')}: {queueStats.consumers}</span>
				</div>

				{#if showQueueTasks && queueTasks.length > 0}
					<div class="mt-3 space-y-1.5 max-h-48 overflow-y-auto">
						<div class="flex items-center justify-between mb-1">
							<span class="text-xs font-medium text-[var(--cloo-text-muted)]">{queueTasks.length} {$i18n.t('tasks')}</span>
							<button
								type="button"
								class="text-xs text-[var(--cloo-danger-solid)] hover:underline"
								on:click={clearQueue}
							>
								{$i18n.t('Clear All')}
							</button>
						</div>
						{#each queueTasks as task}
							<div class="flex items-center justify-between rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] p-2 text-xs">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span class="px-1.5 py-0.5 rounded-[var(--cloo-radius-default)] bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-default)] font-mono text-[10px]">
											{task.task_type}
										</span>
										<span class="text-[var(--cloo-text-muted)] truncate">{task.task_id?.slice(0, 8)}...</span>
									</div>
									<div class="text-[var(--cloo-text-muted)] mt-0.5">
										{formatTime(task.created_at)}
										{#if task.file_id}
											<span class="ml-2">file: {task.file_id?.slice(0, 8)}...</span>
										{/if}
									</div>
								</div>
								<button
									type="button"
									class="ml-2 p-1 rounded-[var(--cloo-radius-default)] hover:bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-danger-solid)]"
									on:click={() => deleteTask(task.msg_id)}
									title={$i18n.t('Delete')}
								>
									<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
									</svg>
								</button>
							</div>
						{/each}
					</div>
				{/if}
			{/if}

			<button
				type="button"
				class="mt-2 text-xs text-[var(--cloo-color-primary)] hover:underline"
				on:click={loadStatus}
			>
				{$i18n.t('Refresh Status')}
			</button>
		</div>

		<!-- Info -->
		<div class="rounded-[var(--cloo-radius-default)] bg-[var(--cloo-bg-neutral-hovered)] p-3 text-xs text-[var(--cloo-text-muted)]">
			<p class="font-medium mb-1 text-[var(--cloo-text-default)]">{$i18n.t('How it works')}</p>
			<ul class="list-disc list-inside space-y-0.5">
				<li>{$i18n.t('Heavy tasks (file processing) are queued via Redis Streams')}</li>
				<li>{$i18n.t('Internal workers consume and process tasks in the background')}</li>
				<li>{$i18n.t('If Redis is not available, tasks are processed directly in the main thread')}</li>
			</ul>
		</div>
	</div>
{/if}
