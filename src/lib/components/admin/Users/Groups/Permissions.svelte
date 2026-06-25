<script lang="ts">
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import Form, { type FormItem } from '$lib/components/common/Form.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { isMenuVisible } from '$lib/config/menuConfig';

	type PermissionLevel = 'none' | 'access' | 'read' | 'write';

	const ALL_LEVELS: PermissionLevel[] = ['none', 'access', 'read', 'write'];
	// 워크스페이스는 'access' 레벨 없음
	const WORKSPACE_LEVELS: PermissionLevel[] = ['none', 'read', 'write'];
	// 모니터링은 read-only 섹션이므로 'write' 레벨 없음
	const MONITORING_LEVELS: PermissionLevel[] = ['none', 'access', 'read'];

	$: LEVEL_LABELS = {
		none: $i18n.t('None'),
		access: $i18n.t('Access'),
		read: $i18n.t('Read'),
		write: $i18n.t('Write')
	};

	// Direct map so Svelte tracks LEVEL_LABELS dependency.
	$: allLevelOptions = ALL_LEVELS.map((level) => ({
		value: level,
		label: LEVEL_LABELS[level]
	}));
	$: workspaceLevelOptions = WORKSPACE_LEVELS.map((level) => ({
		value: level,
		label: LEVEL_LABELS[level]
	}));
	$: monitoringLevelOptions = MONITORING_LEVELS.map((level) => ({
		value: level,
		label: LEVEL_LABELS[level]
	}));

	// boolean 값 → PermissionLevel 마이그레이션 (기존 저장값 처리)
	function normalizeLevel(value: any): PermissionLevel {
		if (typeof value === 'boolean') return value ? 'write' : 'none';
		if (ALL_LEVELS.includes(value as PermissionLevel)) return value as PermissionLevel;
		return 'none';
	}

	// Default values for permissions
	const defaultPermissions = {
		admin: {
			users: 'none' as PermissionLevel,
			evaluations: 'none' as PermissionLevel,
			settings: 'none' as PermissionLevel,
			monitoring: 'none' as PermissionLevel
		},
		workspace: {
			agents: 'none' as PermissionLevel,
			agent_flows: 'none' as PermissionLevel,
			knowledge: 'none' as PermissionLevel,
			databases: 'none' as PermissionLevel,
			glossaries: 'none' as PermissionLevel,
			knowledge_graphs: 'none' as PermissionLevel,
			guardrails: 'none' as PermissionLevel,
			prompts: 'none' as PermissionLevel,
			tools: 'none' as PermissionLevel,
			schedules: 'read' as PermissionLevel,
			tags: 'write' as PermissionLevel,
			marketplace: 'none' as PermissionLevel
		},
		sharing: {
			public_agents: false,
			public_knowledge: false,
			public_prompts: false,
			public_tools: false,
			public_databases: false,
			public_glossaries: false
		},
		chat: {
			controls: true,
			file_upload: true,
			delete: true,
			edit: true,
			stt: true,
			tts: true,
			call: true,
			multiple_models: true,
			temporary: true,
			temporary_enforced: false
		},
		features: {
			direct_tool_servers: false,
			web_search: true,
			image_generation: true,
			gmail: true,
			calendar: true,
			drive: true,
			code_interpreter: true
		}
	};

	export let permissions: any = {};

	// Reactive statement to ensure all fields are present in `permissions`
	$: {
		permissions = fillMissingProperties(permissions, defaultPermissions);
	}

	function fillMissingProperties(obj: any, defaults: any) {
		const result = { ...defaults, ...obj };

		// admin/workspace: normalizeLevel 적용
		result.admin = {};
		for (const key of Object.keys(defaults.admin)) {
			result.admin[key] = normalizeLevel(obj?.admin?.[key] ?? defaults.admin[key]);
		}
		result.workspace = {};
		for (const key of Object.keys(defaults.workspace)) {
			result.workspace[key] = normalizeLevel(obj?.workspace?.[key] ?? defaults.workspace[key]);
		}

		// sharing/chat/features: boolean 그대로
		result.sharing = { ...defaults.sharing, ...obj?.sharing };
		result.chat = { ...defaults.chat, ...obj?.chat };
		result.features = { ...defaults.features, ...obj?.features };

		return result;
	}

	$: sharingItems = (permissions?.sharing
		? [
				{
					id: 'public_agents',
					label: $i18n.t('Agents Public Sharing'),
					state: !!permissions.sharing.public_agents
				},
				{
					id: 'public_knowledge',
					label: $i18n.t('Knowledge Public Sharing'),
					state: !!permissions.sharing.public_knowledge
				},
				{
					id: 'public_prompts',
					label: $i18n.t('Prompts Public Sharing'),
					state: !!permissions.sharing.public_prompts
				},
				{
					id: 'public_tools',
					label: $i18n.t('Tools Public Sharing'),
					state: !!permissions.sharing.public_tools
				},
				{
					id: 'public_databases',
					label: $i18n.t('Database Public Sharing'),
					state: !!permissions.sharing.public_databases
				},
				{
					id: 'public_glossaries',
					label: $i18n.t('Glossary Public Sharing'),
					state: !!permissions.sharing.public_glossaries
				}
			]
		: []) satisfies FormItem[];

	const handleSharingChange = (
		event: CustomEvent<{ index: number; nextState: boolean; item: FormItem }>
	) => {
		if (!permissions?.sharing) return;
		permissions.sharing[event.detail.item.id] = event.detail.nextState;
	};

	$: featuresItems = (permissions?.features
		? [
				{
					id: 'direct_tool_servers',
					label: $i18n.t('Direct Tool Servers'),
					state: !!permissions.features.direct_tool_servers
				},
				{
					id: 'web_search',
					label: $i18n.t('Web Search'),
					state: !!permissions.features.web_search
				},
				{
					id: 'image_generation',
					label: $i18n.t('Image Generation'),
					state: !!permissions.features.image_generation
				},
				{
					id: 'gmail',
					label: $i18n.t('Gmail'),
					state: !!permissions.features.gmail
				},
				{
					id: 'calendar',
					label: $i18n.t('Calendar'),
					state: !!permissions.features.calendar
				},
				{
					id: 'drive',
					label: $i18n.t('Google Drive'),
					state: !!permissions.features.drive
				},
				{
					id: 'code_interpreter',
					label: $i18n.t('Code Interpreter'),
					state: !!permissions.features.code_interpreter
				}
			]
		: []) satisfies FormItem[];

	const handleFeaturesChange = (
		event: CustomEvent<{ index: number; nextState: boolean; item: FormItem }>
	) => {
		if (!permissions?.features) return;
		permissions.features[event.detail.item.id] = event.detail.nextState;
	};

	onMount(() => {
		permissions = fillMissingProperties(permissions, defaultPermissions);
	});
</script>

<div class="flex flex-col gap-4">
	<!-- Admin Permissions -->
	<div>
		<div class=" mb-2 text-sm font-medium">{$i18n.t('Admin Permissions')}</div>

		<div class="flex flex-col gap-2 pr-2">
			<LabelBase label={$i18n.t('Users Management Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.admin.users}
							items={allLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Evaluations Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.admin.evaluations}
							items={allLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Settings Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.admin.settings}
							items={allLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Monitoring Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.admin.monitoring}
							items={monitoringLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>
		</div>
	</div>

	<hr class=" border-gray-100 dark:border-gray-850" />

	<!-- Workspace Permissions -->
	<div>
		<div class=" mb-2 text-sm font-medium">{$i18n.t('Workspace Permissions')}</div>

		<div class="flex flex-col gap-2 pr-2">
			<LabelBase label={$i18n.t('Agents Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.agents}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Flows Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.agent_flows}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Knowledge Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.knowledge}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Database Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.databases}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Glossary Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.glossaries}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Knowledge Graph Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.knowledge_graphs}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Guardrails Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.guardrails}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Prompts Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.prompts}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<div class="flex w-full justify-between items-center gap-2">
				<Tooltip
					className="flex items-center"
					content={$i18n.t(
						'Warning: Enabling this will allow users to upload arbitrary code on the server.'
					)}
					placement="top-start"
				>
					<div class="self-center text-xs font-medium">{$i18n.t('Tools Access')}</div>
				</Tooltip>
				<div class="min-w-[12rem]">
					<Selector
						bind:value={permissions.workspace.tools}
						items={workspaceLevelOptions}
						size="sm"
						searchEnabled={false}
					/>
				</div>
			</div>

			<LabelBase label={$i18n.t('Schedules Access')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[12rem]">
						<Selector
							bind:value={permissions.workspace.schedules}
							items={workspaceLevelOptions}
							size="sm"
							searchEnabled={false}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<!-- 마켓플레이스는 개발중 — 로컬(개발자 모드)에서만 권한 행 노출 -->
			{#if isMenuVisible('marketplace')}
				<LabelBase label={$i18n.t('Marketplace Access')} size="md">
					<svelte:fragment slot="right">
						<div class="min-w-[12rem]">
							<Selector
								bind:value={permissions.workspace.marketplace}
								items={workspaceLevelOptions}
								size="sm"
								searchEnabled={false}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			{/if}

			<div class="flex w-full justify-between items-center gap-2">
				<Tooltip
					className="flex items-center"
					content={$i18n.t(
						'Read = view & assign existing tags. Write = also create/edit/delete tags.'
					)}
					placement="top-start"
				>
					<div class="self-center text-xs font-medium">{$i18n.t('Tags Access')}</div>
				</Tooltip>
				<div class="min-w-[12rem]">
					<Selector
						bind:value={permissions.workspace.tags}
						items={workspaceLevelOptions}
						size="sm"
						searchEnabled={false}
					/>
				</div>
			</div>
		</div>
	</div>

	<hr class=" border-gray-100 dark:border-gray-850" />

	<!-- Sharing Permissions -->
	<div>
		<div class=" mb-2 text-sm font-medium">{$i18n.t('Sharing Permissions')}</div>

		<div class="pr-2">
			<Form items={sharingItems} on:change={handleSharingChange} />
		</div>
	</div>

	<hr class=" border-gray-100 dark:border-gray-850" />

	<!-- Chat Permissions -->
	<div>
		<div class=" mb-2 text-sm font-medium">{$i18n.t('Chat Permissions')}</div>

		<div class="flex flex-col gap-2 pr-2">
			<LabelBase label={$i18n.t('Allow File Upload')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.file_upload} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Chat Controls')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.controls} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Chat Delete')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.delete} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Chat Edit')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.edit} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Speech to Text')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.stt} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Text to Speech')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.tts} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Call')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.call} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Multiple Models in Chat')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.multiple_models} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow Temporary Chat')} size="md">
				<svelte:fragment slot="right">
					<Switch bind:state={permissions.chat.temporary} />
				</svelte:fragment>
			</LabelBase>

			{#if permissions.chat.temporary}
				<LabelBase label={$i18n.t('Enforce Temporary Chat')} size="md">
					<svelte:fragment slot="right">
						<Switch bind:state={permissions.chat.temporary_enforced} />
					</svelte:fragment>
				</LabelBase>
			{/if}
		</div>
	</div>

	<hr class=" border-gray-100 dark:border-gray-850" />

	<!-- Features Permissions -->
	<div>
		<div class=" mb-2 text-sm font-medium">{$i18n.t('Features Permissions')}</div>

		<div class="pr-2">
			<Form items={featuresItems} on:change={handleFeaturesChange} />
		</div>
	</div>
</div>
