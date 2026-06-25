<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import Display from './Display.svelte';
	import Permissions from './Permissions.svelte';
	import Users from './Users.svelte';
	import Organizations from './Organizations.svelte';
	import UserPlusSolid from '$lib/components/icons/UserPlusSolid.svelte';
	import WrenchSolid from '$lib/components/icons/WrenchSolid.svelte';
	import Building from '$lib/components/icons/Building.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import { getGuardrails } from '$lib/apis/guardrails';
	import { getRAGConfig } from '$lib/apis/retrieval';
	import { config, guardrails } from '$lib/stores';

	import type { OrganizationalUnit } from '$lib/apis/organizations';

	export let onSubmit: Function = () => {};
	export let onDelete: Function = () => {};

	export let show = false;
	export let edit = false;

	export let users = [];
	export let group = null;

	/** 전체 조직 단위 목록 */
	export let orgUnits: OrganizationalUnit[] = [];
	/** 다른 그룹에 이미 할당된 org unit ID (현재 그룹 제외) */
	export let assignedOrgUnitIds: string[] = [];

	export let custom = true;

	export let tabs = ['general', 'permissions', 'organizations', 'users'];

	export let selectedTab = 'general';
	let loading = false;
	let showDeleteConfirmDialog = false;

	export let name = '';
	export let description = '';

	export let permissions = {
		workspace: {
			models: false,
			knowledge: false,
			prompts: false,
			tools: false,
			databases: false,
			glossaries: false
		},
		sharing: {
			public_models: false,
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
			temporary: true
		},
		features: {
			direct_tool_servers: false,
			web_search: true,
			image_generation: true,
			code_interpreter: true
		}
	};
	export let userIds = [];
	let orgUnitIds: string[] = [];

	let chatGuardrailId = '';
	let loadingGuardrails = false;
	let globalGuardrailIds: string[] = [];

	$: chatGuardrailOptions = [
		{ value: '', label: $i18n.t('None') },
		...(($guardrails ?? [])
			.filter((g) => !globalGuardrailIds.includes(g.id))
			.map((g) => ({ value: g.id, label: g.name })))
	];

	const loadGuardrails = async () => {
		const [guardrailsRes, ragConfig] = await Promise.all([
			$guardrails === null && !loadingGuardrails
				? getGuardrails(localStorage.token).catch(() => null)
				: Promise.resolve(null),
			getRAGConfig(localStorage.token).catch(() => null)
		]);

		if (guardrailsRes !== null) {
			guardrails.set(guardrailsRes ?? []);
		}

		globalGuardrailIds = ragConfig?.global_guardrail?.GLOBAL_GUARDRAIL_IDS ?? [];
	};

	const submitHandler = async () => {
		loading = true;

		const groupData = {
			name,
			description,
			permissions,
			user_ids: userIds,
			meta: {
				...(group?.meta ?? {}),
				...(chatGuardrailId
					? { chat_guardrail_id: chatGuardrailId }
					: { chat_guardrail_id: undefined }),
				org_unit_ids: orgUnitIds.length > 0 ? orgUnitIds : undefined
			}
		};

		await onSubmit(groupData);

		loading = false;
		show = false;
	};

	const init = () => {
		if (group) {
			name = group.name;
			description = group.description;
			permissions = group?.permissions ?? {};

			userIds = group?.user_ids ?? [];
			orgUnitIds = group?.meta?.org_unit_ids ?? [];
			chatGuardrailId = group?.meta?.chat_guardrail_id ?? '';
		}
	};

	$: if (show) {
		init();
		loadGuardrails();
	}

	onMount(() => {
		console.log(tabs);
		selectedTab = tabs[0];
		init();
	});
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		onDelete();
		show = false;
	}}
/>

<Modal size="md" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 mb-1.5">
			<div class=" text-lg font-medium self-center font-primary">
				{#if custom}
					{#if edit}
						{$i18n.t('Edit User Group')}
					{:else}
						{$i18n.t('Add User Group')}
					{/if}
				{:else}
					{$i18n.t('Edit Default Permissions')}
				{/if}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="flex flex-col lg:flex-row w-full h-full pb-2 lg:space-x-4">
						<div
							id="admin-settings-tabs-container"
							class="tabs flex flex-row overflow-x-auto gap-2.5 max-w-full lg:gap-1 lg:flex-col lg:flex-none lg:w-40 dark:text-gray-200 text-sm font-medium text-left scrollbar-none"
						>
							{#if tabs.includes('general')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'general'
										? ''
										: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
									on:click={() => {
										selectedTab = 'general';
									}}
									type="button"
								>
									<div class=" self-center mr-2">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 16 16"
											fill="currentColor"
											class="w-4 h-4"
										>
											<path
												fill-rule="evenodd"
												d="M6.955 1.45A.5.5 0 0 1 7.452 1h1.096a.5.5 0 0 1 .497.45l.17 1.699c.484.12.94.312 1.356.562l1.321-1.081a.5.5 0 0 1 .67.033l.774.775a.5.5 0 0 1 .034.67l-1.08 1.32c.25.417.44.873.561 1.357l1.699.17a.5.5 0 0 1 .45.497v1.096a.5.5 0 0 1-.45.497l-1.699.17c-.12.484-.312.94-.562 1.356l1.082 1.322a.5.5 0 0 1-.034.67l-.774.774a.5.5 0 0 1-.67.033l-1.322-1.08c-.416.25-.872.44-1.356.561l-.17 1.699a.5.5 0 0 1-.497.45H7.452a.5.5 0 0 1-.497-.45l-.17-1.699a4.973 4.973 0 0 1-1.356-.562L4.108 13.37a.5.5 0 0 1-.67-.033l-.774-.775a.5.5 0 0 1-.034-.67l1.08-1.32a4.971 4.971 0 0 1-.561-1.357l-1.699-.17A.5.5 0 0 1 1 8.548V7.452a.5.5 0 0 1 .45-.497l1.699-.17c.12-.484.312-.94.562-1.356L2.629 4.107a.5.5 0 0 1 .034-.67l.774-.774a.5.5 0 0 1 .67-.033L5.43 3.71a4.97 4.97 0 0 1 1.356-.561l.17-1.699ZM6 8c0 .538.212 1.026.558 1.385l.057.057a2 2 0 0 0 2.828-2.828l-.058-.056A2 2 0 0 0 6 8Z"
												clip-rule="evenodd"
											/>
										</svg>
									</div>
									<div class=" self-center">{$i18n.t('General')}</div>
								</button>
							{/if}

							{#if tabs.includes('permissions')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'permissions'
										? ''
										: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
									on:click={() => {
										selectedTab = 'permissions';
									}}
									type="button"
								>
									<div class=" self-center mr-2">
										<WrenchSolid />
									</div>
									<div class=" self-center">{$i18n.t('Permissions')}</div>
								</button>
							{/if}

							{#if tabs.includes('organizations')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'organizations'
										? ''
										: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
									on:click={() => {
										selectedTab = 'organizations';
									}}
									type="button"
								>
									<div class="self-center mr-2">
										<Building className="size-4" />
									</div>
									<div class="self-center">{$i18n.t('Organizations')} ({orgUnitIds.length})</div>
								</button>
							{/if}

							{#if tabs.includes('users')}
								<button
									class="px-0.5 py-1 max-w-fit w-fit rounded-lg flex-1 lg:flex-none flex text-right transition {selectedTab ===
									'users'
										? ''
										: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
									on:click={() => {
										selectedTab = 'users';
									}}
									type="button"
								>
									<div class=" self-center mr-2">
										<UserPlusSolid />
									</div>
									<div class=" self-center">{$i18n.t('Users')} ({userIds.length})</div>
								</button>
							{/if}
						</div>

						<div
							class="flex-1 mt-1 lg:mt-1 lg:h-[22rem] lg:max-h-[22rem] overflow-y-auto scrollbar-hidden"
						>
							{#if selectedTab == 'general'}
								<Display bind:name bind:description />

								<hr class="border-gray-100 dark:border-gray-850 my-3" />

								<div class="flex flex-col w-full">
									<LabelBase label={$i18n.t('Chat Guardrail')} size="md">
										<svelte:fragment slot="right">
											<div class="min-w-[14rem]">
												<Selector
													value={chatGuardrailId ?? ''}
													items={chatGuardrailOptions}
													size="sm"
													searchEnabled={chatGuardrailOptions.length > 10}
													on:change={(event) => {
														chatGuardrailId = event.detail.value;
													}}
												/>
											</div>
										</svelte:fragment>
									</LabelBase>
									<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
										{$i18n.t(
											'Select guardrails to apply input/output validation and filtering.'
										)}
									</div>
								</div>

								<!-- 그룹 토큰 한도는 [관리자 > 설정 > 모델] accordion 의 "그룹 오버라이드" 에서 관리 -->
							{:else if selectedTab == 'permissions'}
								<Permissions bind:permissions />
							{:else if selectedTab == 'organizations'}
								<Organizations
									bind:orgUnitIds
									{orgUnits}
									{assignedOrgUnitIds}
								/>
							{:else if selectedTab == 'users'}
								<Users bind:userIds {users} />
							{/if}
						</div>
					</div>

					<!-- <div
						class=" tabs flex flex-row overflow-x-auto gap-2.5 text-sm font-medium border-b border-b-gray-800 scrollbar-hidden"
					>
						{#if tabs.includes('display')}
							<button
								class="px-0.5 pb-1.5 min-w-fit flex text-right transition border-b-2 {selectedTab ===
								'display'
									? ' dark:border-white'
									: 'border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
								on:click={() => {
									selectedTab = 'display';
								}}
								type="button"
							>
								{$i18n.t('Display')}
							</button>
						{/if}

						{#if tabs.includes('permissions')}
							<button
								class="px-0.5 pb-1.5 min-w-fit flex text-right transition border-b-2 {selectedTab ===
								'permissions'
									? '  dark:border-white'
									: 'border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
								on:click={() => {
									selectedTab = 'permissions';
								}}
								type="button"
							>
								{$i18n.t('Permissions')}
							</button>
						{/if}

						{#if tabs.includes('users')}
							<button
								class="px-0.5 pb-1.5 min-w-fit flex text-right transition border-b-2 {selectedTab ===
								'users'
									? ' dark:border-white'
									: ' border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
								on:click={() => {
									selectedTab = 'users';
								}}
								type="button"
							>
								{$i18n.t('Users')} ({userIds.length})
							</button>
						{/if}
					</div> -->

					<div class="flex justify-between pt-3 text-sm font-medium gap-1.5">
						{#if edit}
							<Button
								kind="outlined"
								size="md"
								on:click={() => {
									showDeleteConfirmDialog = true;
								}}
							>
								{$i18n.t('Delete')}
							</Button>
						{:else}
							<div></div>
						{/if}

						<Button kind="filled" size="md" type="submit" {loading}>
							{$i18n.t('Save')}
						</Button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
