<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models } from '$lib/stores';
	import { createSchedule, updateScheduleById } from '$lib/apis/schedules';
	import type { ScheduleForm as ScheduleFormType } from '$lib/apis/schedules';
	import { getAccessibleDashboards } from '$lib/apis/bi-dashboards';
	import type { BiDashboard } from '$lib/apis/bi-dashboards';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import AccessControlModal from '$lib/components/workspace/common/AccessControlModal.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import ScheduleInput from './ScheduleInput.svelte';
	import ScheduleDelivery from './ScheduleDelivery.svelte';

	export let edit = false;
	export let id = '';
	export let name = '';
	export let description = '';
	export let targetModelId = '';
	export let prompt = '';
	export let cronExpression = '0 9 * * *';
	export let timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
	export let startAt: number | null = null;
	export let endAt: number | null = null;
	export let delivery: Record<string, unknown> = {};
	export let meta: Record<string, unknown> = {};
	export let accessControl: any = null;

	let showAccessControlModal = false;

	let notifications: any[] = (delivery?.notifications as any[]) || [];
	let titleTemplate: string = (delivery?.title_template as string) || '';

	let loading = false;
	let dashboards: BiDashboard[] = [];
	let timeRangePreset: string = (meta?.time_range as string) || 'yesterday';

	const timeRangeItems = [
		{ value: 'yesterday', label: 'Yesterday' },
		{ value: 'today', label: 'Today' },
		{ value: '7d', label: 'Last 7 Days' },
		{ value: '30d', label: 'Last 30 Days' },
		{ value: 'last_week', label: 'Last Week' },
		{ value: 'last_month', label: 'Last Month' },
		{ value: 'this_week', label: 'This Week' },
		{ value: 'this_month', label: 'This Month' },
	];

	onMount(async () => {
		try {
			dashboards = await getAccessibleDashboards(localStorage.token);
		} catch {
			/* silent — dashboards are optional */
		}
	});

	// Categorize models: agents (have base_model_id), flows (owned_by agent_flow), others (plain models)
	$: allModels = $models;
	$: agentModels = allModels.filter(
		(m) => m.owned_by !== 'agent_flow' && m.info?.base_model_id && m.info?.base_model_id !== ''
	);
	$: flowModels = allModels.filter((m) => m.owned_by === 'agent_flow');
	$: plainModels = allModels.filter(
		(m) => m.owned_by !== 'agent_flow' && (!m.info?.base_model_id || m.info?.base_model_id === '')
	);
	$: targetItems = [
		...dashboards.map((d) => ({
			value: d.id,
			label: `[${$i18n.t('Dashboards')}] ${d.name}`
		})),
		...agentModels.map((m) => ({
			value: m.id,
			label: `[${$i18n.t('Agents')}] ${m.name}`
		})),
		...flowModels.map((m) => ({
			value: m.id,
			label: `[${$i18n.t('Flows')}] ${m.name}`
		})),
		...plainModels.map((m) => ({
			value: m.id,
			label: `[${$i18n.t('Models')}] ${m.name}`
		}))
	];
	$: isDashboard = dashboards.some((d) => d.id === targetModelId);

	const submitHandler = async () => {
		loading = true;

		if (name.trim() === '' || !targetModelId) {
			toast.error($i18n.t('Please fill in all fields.'));
			loading = false;
			return;
		}

		if (!isDashboard && prompt.trim() === '') {
			toast.error($i18n.t('Please fill in all fields.'));
			loading = false;
			return;
		}

		// Derive target_type from selected model
		let targetType = 'model';
		if (isDashboard) {
			targetType = 'dashboard';
		} else {
			const selectedModel = allModels.find((m) => m.id === targetModelId);
			if (selectedModel) {
				if (selectedModel.owned_by === 'agent_flow') targetType = 'flow';
				else if (selectedModel.info?.base_model_id) targetType = 'agent';
			}
		}

		// Derive chat title_template from the first notification (if any)
		const firstTitleTpl =
			notifications.find((n) => n.title_template?.trim())?.title_template?.trim() || '';

		const formData: ScheduleFormType = {
			name: name.trim(),
			description: description.trim() || undefined,
			target_type: targetType,
			target_model_id: targetModelId,
			prompt: isDashboard ? `Dashboard export: ${timeRangePreset}` : prompt.trim(),
			cron_expression: cronExpression,
			timezone,
			start_at: startAt,
			end_at: endAt,
			delivery: {
				notifications,
				...(firstTitleTpl ? { title_template: firstTitleTpl } : {})
			},
			meta: isDashboard ? { time_range: timeRangePreset } : undefined,
			access_control: accessControl,
		};

		if (edit) {
			const res = await updateScheduleById(localStorage.token, id, formData).catch((e) => {
				toast.error($i18n.t(`${e}`));
			});

			if (res) {
				toast.success($i18n.t('Schedule updated'));
			}
		} else {
			const res = await createSchedule(localStorage.token, formData).catch((e) => {
				toast.error($i18n.t(`${e}`));
			});

			if (res) {
				toast.success($i18n.t('Schedule created'));
				goto('/schedules');
			}
		}

		loading = false;
	};
</script>

<div class="w-full">
	{#if !edit}
		<button
			class="flex space-x-1"
			on:click={() => {
				goto('/schedules');
			}}
		>
			<div class="self-center">
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
			</div>
			<div class="self-center font-medium text-sm">{$i18n.t('Back')}</div>
		</button>
	{/if}

	<form
		class="schedule-form flex flex-col {edit
			? 'schedule-form-edit'
			: 'mb-10 max-w-lg mx-auto mt-6 sm:mt-10 px-4 sm:px-0'}"
		on:submit|preventDefault={() => {
			submitHandler();
		}}
	>
		<div class="w-full flex flex-col justify-center">
			{#if !edit}
				<div class="text-2xl font-medium font-primary mb-2.5">
					{$i18n.t('Create a schedule')}
				</div>
			{/if}

			<div class="schedule-form-fields">
				<!-- Name -->
				<div class="schedule-form-field schedule-form-field-name">
					<Input
						bind:value={name}
						label={$i18n.t('Name')}
						placeholder={$i18n.t('Schedule name')}
						size="md"
						required
					/>
				</div>

				<!-- Target Model -->
				<div class="schedule-form-field schedule-form-field-target">
					<div class="text-sm mb-2">{$i18n.t('Target')}</div>
					<Selector
						bind:value={targetModelId}
						items={targetItems}
						placeholder={$i18n.t('Select a model or agent')}
						size="md"
					/>
				</div>

				<!-- Description -->
				<div class="schedule-form-field schedule-form-field-description">
					<Input
						bind:value={description}
						label={$i18n.t('Description')}
						placeholder={$i18n.t('Optional description')}
						size="md"
					/>
				</div>

				<!-- Prompt or Time Range (conditional) -->
				{#if isDashboard}
					<div class="schedule-form-field schedule-form-field-time-range">
						<div class="text-sm mb-2">{$i18n.t('Time Range')}</div>
						<Selector
							bind:value={timeRangePreset}
							items={timeRangeItems.map((item) => ({
								value: item.value,
								label: $i18n.t(item.label)
							}))}
							size="md"
						/>
						<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
							{$i18n.t('Date range applied to dashboard panels at execution time')}
						</p>
					</div>
				{:else}
					<div class="schedule-form-field schedule-form-field-prompt">
						<Textarea
							bind:value={prompt}
							label={$i18n.t('Prompt')}
							placeholder={$i18n.t('Enter the prompt to execute on schedule')}
							rows={4}
							size="md"
							autoResize={false}
							required
						/>
					</div>
				{/if}

				<!-- Schedule Input -->
				<div class="schedule-form-field schedule-form-field-schedule">
					<div class="text-sm mb-2">{$i18n.t('Schedule')}</div>
					<div class="w-full mt-1">
						<ScheduleInput bind:cronExpression bind:timezone bind:startAt bind:endAt />
					</div>
				</div>

				<!-- Delivery / Notifications -->
				<div class="schedule-form-field schedule-form-field-delivery">
					<ScheduleDelivery bind:notifications bind:titleTemplate {targetModelId} />
				</div>

				<!-- Access Control -->
				<div class="schedule-form-field schedule-form-field-access">
					<div class="flex items-center justify-between">
						<div class="text-sm">{$i18n.t('Visibility')}</div>
						<Button
							kind="outlined"
							size="md"
							on:click={() => (showAccessControlModal = true)}
						>
							<div class="flex items-center gap-1.5">
								<LockClosed className="size-3.5" strokeWidth="2" />
								<span>
									{accessControl === null
										? $i18n.t('Public')
										: $i18n.t('Private')}
								</span>
							</div>
						</Button>
					</div>
					<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
						{accessControl === null
							? $i18n.t('Accessible to all users')
							: $i18n.t('Only select users and groups with permission can access')}
					</p>
				</div>
			</div>
		</div>

		<div class="flex justify-end mt-2">
			<Button type="submit" size="md" kind="filled" {loading}>
				{edit ? $i18n.t('Save') : $i18n.t('Create Schedule')}
			</Button>
		</div>
	</form>

	<AccessControlModal
		bind:show={showAccessControlModal}
		bind:accessControl
		accessRoles={['read', 'write']}
	/>
</div>
