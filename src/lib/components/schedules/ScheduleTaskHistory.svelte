<script lang="ts">
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { getContext } from 'svelte';
	import type { ScheduleTask } from '$lib/apis/schedules';
	import Badge from '../common/Badge.svelte';

	const i18n = getContext('i18n');

	export let tasks: ScheduleTask[] = [];
	export let scheduleChatId: string = '';

	function formatDate(ts: number | undefined): string {
		if (!ts) return '-';
		return dayjs(ts * 1000).format('YYYY-MM-DD HH:mm:ss');
	}

	function statusBadgeType(status: string): string {
		switch (status) {
			case 'completed':
				return 'success';
			case 'failed':
				return 'error';
			case 'running':
				return 'info';
			case 'pending':
				return 'warning';
			default:
				return 'muted';
		}
	}
</script>

{#if tasks.length === 0}
	<div class="flex flex-col items-center justify-center h-40 text-gray-500 dark:text-gray-400">
		<div class="text-sm">{$i18n.t('No execution history')}</div>
	</div>
{:else}
	<div class="flex flex-col gap-1">
		{#each tasks as task (task.id)}
			{@const linkChatId = (task.chat_id || scheduleChatId || '').trim()}
			<div
				class="flex items-center gap-3 px-3 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
			>
				<div class="shrink-0">
					<Badge type={statusBadgeType(task.status)} content={task.status} />
				</div>

				<div class="flex-1 min-w-0">
					<div class="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
						<span>{formatDate(task.scheduled_at)}</span>
						{#if task.started_at}
							<span>·</span>
							<span>{$i18n.t('Duration')}: {task.completed_at && task.started_at
								? `${task.completed_at - task.started_at}s`
								: '-'}</span>
						{/if}
						{#if task.retry_count > 0}
							<span>·</span>
							<span>{$i18n.t('Retries')}: {task.retry_count}/{task.max_retries}</span>
						{/if}
					</div>

					{#if task.error_message}
						<div class="text-xs text-red-600 dark:text-red-400 mt-0.5 line-clamp-1">
							{task.error_message}
						</div>
					{/if}
				</div>

				{#if linkChatId}
					<a
						href="/c/{linkChatId}"
						class="shrink-0 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition"
					>
						{$i18n.t('View Chat')}
					</a>
				{/if}
			</div>
		{/each}
	</div>
{/if}
