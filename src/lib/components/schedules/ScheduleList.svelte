<script lang="ts">
	import Fuse from 'fuse.js';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, user, models } from '$lib/stores';
	import {
		getSchedules,
		deleteScheduleById,
		toggleSchedule,
		runScheduleNow
	} from '$lib/apis/schedules';
	import type { Schedule } from '$lib/apis/schedules';

	import { goto } from '$app/navigation';

	import DeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import ScheduleItemMenu from './ScheduleItemMenu.svelte';
	import Badge from '../common/Badge.svelte';
	import Button from '../common/Button.svelte';
	import Input from '../common/Input.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import Spinner from '../common/Spinner.svelte';
	import { capitalizeFirstLetter } from '$lib/utils';
	import Tooltip from '../common/Tooltip.svelte';
	import WorkspaceCard from '../common/WorkspaceCard.svelte';

	let loaded = false;

	let query = '';
	let selectedItem: Schedule | null = null;
	let showDeleteConfirm = false;

	$: canCreate =
		$user?.role === 'admin' || $user?.permissions?.workspace?.schedules === 'write';

	let fuse: Fuse<Schedule> | null = null;

	let schedules: Schedule[] = [];
	let filteredItems: Schedule[] = [];

	$: if (schedules) {
		fuse = new Fuse(schedules, {
			keys: ['name', 'description', 'prompt']
		});
	}

	$: if (fuse) {
		filteredItems = query
			? fuse.search(query).map((e) => {
					return e.item;
				})
			: schedules;
	}

	const deleteHandler = async (item: Schedule) => {
		const res = await deleteScheduleById(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			schedules = await getSchedules(localStorage.token);
			toast.success($i18n.t('Schedule deleted'));
		}
	};

	const toggleHandler = async (item: Schedule) => {
		const res = await toggleSchedule(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			schedules = await getSchedules(localStorage.token);
		}
	};

	const runHandler = async (item: Schedule) => {
		const res = await runScheduleNow(localStorage.token, item.id).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			toast.success($i18n.t('Task enqueued'));
		}
	};

	const getModelName = (modelId: string): string => {
		const model = $models.find((m) => m.id === modelId);
		return model?.name ?? modelId;
	};

	onMount(async () => {
		schedules = await getSchedules(localStorage.token);
		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Schedules')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			if (selectedItem) deleteHandler(selectedItem);
		}}
	/>

	<div class="schedule-list-shell">
		<div class="workspace-section-header schedule-section-header">
			<div class="workspace-section-title-row">
				<h2 class="workspace-section-title">{$i18n.t('Schedules')}</h2>
				<span class="workspace-section-count">{filteredItems.length}</span>
			</div>

			<div class="workspace-section-actions schedule-section-actions">
				<div class="workspace-section-search schedule-section-search">
					<Input
						bind:value={query}
						placeholder={$i18n.t('Search Schedules')}
						type="search"
						size="md"
					>
						<svelte:fragment slot="prefix">
							<Search className="size-3.5" />
						</svelte:fragment>
					</Input>
				</div>

				{#if canCreate}
					<div class="schedule-section-create">
						<Button
							kind="filled"
							size="md"
							aria-label={$i18n.t('Create Schedule')}
							on:click={() => {
								goto('/schedules/create');
							}}
						>
							<svelte:fragment slot="prefix">
								<Plus className="size-3.5" />
							</svelte:fragment>
							{$i18n.t('New Schedule')}
						</Button>
					</div>
				{/if}
			</div>
		</div>

		{#if filteredItems.length > 0}
			<div class="workspace-cards-grid schedule-cards-grid mb-5">
				{#each filteredItems as item (item.id)}
					<WorkspaceCard
						name={item.name}
						description={item.description || item.prompt || ''}
						isActive={item.is_active}
						on:click={() => {
							goto(`/schedules/${item.id}`);
						}}
					>
						<svelte:fragment slot="badge">
							<div class="flex items-center gap-1.5">
								{#if item.is_active}
									<Badge type="success" content={$i18n.t('Active')} />
								{:else}
									<Badge type="muted" content={$i18n.t('Inactive')} />
								{/if}
								{#if item.meta?.copied_from}
									<span class="text-xs text-gray-400 dark:text-gray-500 line-clamp-1">
										({$i18n.t('from {{name}}', { name: item.meta.copied_from.user_name })})
									</span>
								{/if}
							</div>
						</svelte:fragment>

						<svelte:fragment slot="actions">
							<ScheduleItemMenu
								on:delete={() => {
									selectedItem = item;
									showDeleteConfirm = true;
								}}
								on:toggle={() => {
									toggleHandler(item);
								}}
								on:run={() => {
									runHandler(item);
								}}
							/>
						</svelte:fragment>

						<svelte:fragment slot="meta">
							<div class="schedule-card-meta-grid">
								<span class="schedule-card-meta-pill" title={getModelName(item.target_model_id)}>
									<span class="truncate">{getModelName(item.target_model_id)}</span>
								</span>
								<span
									class="schedule-card-meta-pill schedule-card-meta-pill-mono"
									title={item.cron_expression}
								>
									<span class="truncate">{item.cron_expression}</span>
								</span>
								<span class="schedule-card-meta-pill" title={item.timezone}>
									<span class="truncate">{item.timezone}</span>
								</span>
							</div>
						</svelte:fragment>

						<svelte:fragment slot="footer-left">
							<div class="text-xs text-gray-500">
								<Tooltip
									content={item?.user?.email ?? $i18n.t('Deleted User')}
									className="flex shrink-0"
									placement="top-start"
								>
									{$i18n.t('By {{name}}', {
										name: capitalizeFirstLetter(
											item?.user?.name ?? item?.user?.email ?? $i18n.t('Deleted User')
										)
									})}
								</Tooltip>
							</div>
						</svelte:fragment>

						<svelte:fragment slot="footer-right">
							<div class="text-xs text-gray-500 line-clamp-1">
								{#if item.next_run_at && item.is_active}
									{$i18n.t('Next')}: {dayjs(item.next_run_at * 1000).fromNow()}
								{:else}
									{$i18n.t('Updated')}
									{dayjs(item.updated_at * 1000).fromNow()}
								{/if}
							</div>
						</svelte:fragment>
					</WorkspaceCard>
				{/each}
			</div>
		{:else}
			<div class="flex flex-col items-center justify-center h-64 text-gray-500 dark:text-gray-400">
				<div class="text-6xl mb-4">&#128340;</div>
				<div class="text-xl font-medium mb-2">{$i18n.t('No schedules yet')}</div>
				<div class="text-sm">{$i18n.t('Create a schedule to automate agent tasks')}</div>
			</div>
		{/if}

		<div class="schedule-list-info">
			&#9432; {$i18n.t('Schedules automatically run agents at specified times.')}
		</div>
	</div>
{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
