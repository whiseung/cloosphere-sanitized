<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import {
		getScheduleById,
		getScheduleTasks,
		runScheduleNow,
		deleteScheduleById,
		toggleSchedule,
		shareSchedule
	} from '$lib/apis/schedules';
	import type { Schedule, ScheduleTask } from '$lib/apis/schedules';
	import { user } from '$lib/stores';
	import ScheduleForm from '$lib/components/schedules/ScheduleForm.svelte';
	import ScheduleTaskHistory from '$lib/components/schedules/ScheduleTaskHistory.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import ShareModal from '$lib/components/common/ShareModal.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	const i18n = getContext('i18n');

	let schedule: Schedule | null = null;
	let tasks: ScheduleTask[] = [];
	let showDeleteConfirm = false;
	let showShareModal = false;
	let sharedUserIds: string[] = [];
	let runLoading = false;

	let activeTab: 'settings' | 'history' = 'settings';

	$: isOwner = $user?.id === schedule?.user_id;

	$: id = $page.params.id;

	async function loadData() {
		schedule = await getScheduleById(localStorage.token, id);
		if (!schedule) {
			await goto('/schedules');
			return;
		}
		sharedUserIds = [];
		tasks = (await getScheduleTasks(localStorage.token, id)) || [];
	}

	onMount(async () => {
		await loadData();
	});

	async function handleRun() {
		runLoading = true;
		try {
			await runScheduleNow(localStorage.token, id);
			toast.success($i18n.t('Task enqueued'));
			// Switch to history tab and refresh
			activeTab = 'history';
			setTimeout(async () => {
				tasks = (await getScheduleTasks(localStorage.token, id)) || [];
			}, 2000);
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			runLoading = false;
		}
	}

	async function handleToggle() {
		const res = await toggleSchedule(localStorage.token, id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});
		if (res) {
			schedule = await getScheduleById(localStorage.token, id);
		}
	}

	async function handleDelete() {
		const res = await deleteScheduleById(localStorage.token, id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			toast.success($i18n.t('Schedule deleted'));
			await goto('/schedules');
		}
	}

	async function saveSharedUsers() {
		if (!schedule || sharedUserIds.length === 0) return;
		try {
			const res = await shareSchedule(localStorage.token, id, sharedUserIds);
			showShareModal = false;
			sharedUserIds = [];
			toast.success($i18n.t('Schedule copied to {{count}} user(s)', { count: res.copied_count }));
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	}
</script>

{#if schedule}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			handleDelete();
		}}
	/>

	<!-- Share Modal -->
	<ShareModal
		bind:show={showShareModal}
		bind:selectedUserIds={sharedUserIds}
		description={$i18n.t('Selected users will receive an independent copy of this schedule.')}
		saveLabel="Copy to Users"
		on:save={saveSharedUsers}
	/>

	<div class="schedule-detail-page">
		<!-- Header -->
		<div class="schedule-detail-back-row">
			<button
				class="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition"
				on:click={() => goto('/schedules')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-4 h-4"
				>
					<path
						fill-rule="evenodd"
						d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
						clip-rule="evenodd"
					/>
				</svg>
				{$i18n.t('Schedules')}
			</button>
		</div>

		<div class="schedule-detail-header">
			<div class="schedule-detail-title-row">
				<div class="text-xl font-medium font-primary schedule-detail-title">{schedule.name}</div>
				{#if schedule.is_active}
					<Badge type="success" content={$i18n.t('Active')} />
				{:else}
					<Badge type="muted" content={$i18n.t('Inactive')} />
				{/if}
				{#if schedule.meta?.copied_from}
					<span class="text-sm text-gray-400 dark:text-gray-500 schedule-detail-copied-from"
						>({$i18n.t('from {{name}}', { name: schedule.meta.copied_from.user_name })})</span
					>
				{/if}
			</div>

			{#if isOwner}
				<div class="schedule-detail-actions">
					<button
						class="text-xs px-2.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition flex items-center gap-1.5"
						on:click={() => (showShareModal = true)}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="2"
							stroke="currentColor"
							class="w-3.5 h-3.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M7.217 10.907a2.25 2.25 0 1 0 0 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186 9.566-5.314m-9.566 7.5 9.566 5.314m0 0a2.25 2.25 0 1 0 3.935 2.186 2.25 2.25 0 0 0-3.935-2.186Zm0-12.814a2.25 2.25 0 1 0 3.933-2.185 2.25 2.25 0 0 0-3.933 2.185Z"
							/>
						</svg>
						{$i18n.t('Copy to Users')}
					</button>

					<button
						class="text-xs px-2.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition flex items-center gap-1.5"
						on:click={handleRun}
						disabled={runLoading}
					>
						{#if runLoading}
							<Spinner className="size-3" />
						{/if}
						{$i18n.t('Run Now')}
					</button>

					<button
						class="text-xs px-2.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
						on:click={handleToggle}
					>
						{schedule.is_active ? $i18n.t('Deactivate') : $i18n.t('Activate')}
					</button>

					<button
						class="text-xs px-2.5 py-1.5 rounded-lg text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition"
						on:click={() => {
							showDeleteConfirm = true;
						}}
					>
						{$i18n.t('Delete')}
					</button>
				</div>
			{/if}
		</div>

		<!-- Tabs -->
		<div class="schedule-detail-tabs">
			<button
				class="schedule-detail-tab-button px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px {activeTab ===
				'settings'
					? 'border-gray-900 dark:border-white text-gray-900 dark:text-white'
					: 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
				on:click={() => (activeTab = 'settings')}
			>
				{$i18n.t('Settings')}
			</button>
			<button
				class="schedule-detail-tab-button px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px {activeTab ===
				'history'
					? 'border-gray-900 dark:border-white text-gray-900 dark:text-white'
					: 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
				on:click={async () => {
					activeTab = 'history';
					tasks = (await getScheduleTasks(localStorage.token, id)) || [];
				}}
			>
				{$i18n.t('Execution History')}
				<span class="text-xs text-gray-400 dark:text-gray-500 ml-1">({tasks.length})</span>
			</button>
		</div>

		<!-- Tab content -->
		{#if activeTab === 'settings'}
			<div class="schedule-detail-content schedule-detail-panel">
				<ScheduleForm
					edit={true}
					{id}
					name={schedule.name}
					description={schedule.description || ''}
					targetModelId={schedule.target_model_id}
					prompt={schedule.prompt}
					cronExpression={schedule.cron_expression}
					timezone={schedule.timezone}
					startAt={schedule.start_at ?? null}
					endAt={schedule.end_at ?? null}
					delivery={schedule.delivery || {}}
					meta={schedule.meta || {}}
					accessControl={schedule.access_control ?? null}
				/>
			</div>
		{:else if activeTab === 'history'}
			<div class="schedule-detail-content schedule-detail-panel">
				{#if tasks.length > 0}
					<ScheduleTaskHistory {tasks} scheduleChatId={schedule?.chat_id ?? ''} />
				{:else}
					<div
						class="flex flex-col items-center justify-center py-16 text-gray-400 dark:text-gray-500"
					>
						<div class="text-4xl mb-3">&#128340;</div>
						<div class="text-sm">{$i18n.t('No execution history')}</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
