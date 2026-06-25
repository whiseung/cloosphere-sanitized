<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';

	import { config, user, userPermissions } from '$lib/stores';
	import { hasPermission } from '$lib/utils/permissions';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import Building from '$lib/components/icons/Building.svelte';
	import {
		getOrganizations,
		getOrganizationalUnitsTree,
		getOrganizationalUnitPermissions,
		updateOrganizationalUnit,
		getSyncProviders,
		syncFromGoogle,
		syncFromJson,
		syncFromKeycloak,
		syncFromMSGraph,
		deleteOrganization,
		getUnitGuardrails,
		updateUnitGuardrails,
		type Organization,
		type OrganizationalUnit,
		type SyncProvider,
		type UnitPermissions
	} from '$lib/apis/organizations';
	import { getGuardrails } from '$lib/apis/guardrails';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');

	export let users = [];

	let loaded = false;
	let syncing = false;
	let organizations: Organization[] = [];
	let organizationalUnits: OrganizationalUnit[] = [];
	let selectedOrganization: Organization | null = null;
	let syncProviders: SyncProvider[] = [];

	let search = '';
	let showSyncModal = false;
	let selectedSyncProvider = 'json';

	// Users modal
	let showUsersModal = false;
	let selectedUnit: OrganizationalUnit | null = null;

	// Permissions modal
	let showPermissionsModal = false;
	let permissionsUnit: OrganizationalUnit | null = null;
	let unitPermissions: UnitPermissions | null = null;
	let loadingPermissions = false;

	// Guardrails modal (per unit)
	let showGuardrailsModal = false;
	let guardrailsUnit: OrganizationalUnit | null = null;
	let unitGuardrailIds: string[] = [];
	let unitFollowGlobal = false;
	let allGuardrails: any[] = [];
	let savingGuardrails = false;

	// Delete confirmation
	let showDeleteConfirmDialog = false;
	let deleting = false;

	const loadAllGuardrails = async () => {
		try {
			allGuardrails = (await getGuardrails(localStorage.token)) ?? [];
		} catch (e) {
			allGuardrails = [];
		}
	};

	const openUnitGuardrails = async (unit: OrganizationalUnit) => {
		guardrailsUnit = unit;
		showGuardrailsModal = true;
		await loadAllGuardrails();
		try {
			const result = await getUnitGuardrails(localStorage.token, unit.id);
			unitGuardrailIds = result?.guardrail_ids ?? [];
			unitFollowGlobal = result?.follow_global ?? false;
		} catch (e) {
			console.error('Failed to load unit guardrails:', e);
			unitGuardrailIds = [];
			unitFollowGlobal = false;
		}
	};

	const saveUnitGuardrails = async () => {
		if (!guardrailsUnit) return;
		savingGuardrails = true;
		try {
			await updateUnitGuardrails(
				localStorage.token,
				guardrailsUnit.id,
				unitGuardrailIds,
				unitFollowGlobal
			);
			toast.success($i18n.t('Guardrail settings saved'));
			showGuardrailsModal = false;
		} catch (e) {
			toast.error($i18n.t('Failed to save guardrail settings'));
		} finally {
			savingGuardrails = false;
		}
	};

	const loadUnitPermissions = async (unit: OrganizationalUnit) => {
		permissionsUnit = unit;
		showPermissionsModal = true;
		loadingPermissions = true;
		try {
			unitPermissions = await getOrganizationalUnitPermissions(localStorage.token, unit.id);
		} catch (e) {
			console.error('Failed to load permissions:', e);
			toast.error($i18n.t('Failed to load permissions'));
		} finally {
			loadingPermissions = false;
		}
	};

	// meta.members (Azure AD/Google sync) + member_ids (OAuth 자동 할당) 두 소스를 union
	$: unitMembers = selectedUnit?.meta?.members ?? [];
	// oauth_sub 또는 이메일로 매칭
	$: unitUsers = selectedUnit?.member_ids
		? users.filter((u) => {
				const memberIds = selectedUnit?.member_ids ?? [];
				const memberEmails = (selectedUnit?.meta?.members ?? []).map((m: any) => m.email?.toLowerCase());
				return memberIds.includes(u.oauth_sub)
					|| memberIds.includes(u.email?.toLowerCase())
					|| memberEmails.includes(u.email?.toLowerCase());
			})
		: [];
	// meta.members에 이미 표시된 사용자는 unitUsers 렌더링에서 제외 (중복 방지)
	$: extraUnitUsers = unitUsers.filter((u) => {
		const memberEmails = unitMembers.map((m: any) => m.email?.toLowerCase());
		const memberIds = unitMembers.map((m: any) => m.id);
		return !memberEmails.includes(u.email?.toLowerCase()) && !memberIds.includes(u.oauth_sub);
	});
	$: totalMemberCount = unitMembers.length + extraUnitUsers.length;

	// 기본 provider 목록 (API 실패 시 fallback)
	const defaultProviders: SyncProvider[] = [
		{
			type: 'json',
			name: 'JSON',
			description: 'JSON 데이터로 직접 입력'
		},
		{
			type: 'msgraph',
			name: 'Microsoft Entra ID',
			description: 'Azure AD에서 조직 구조 동기화'
		},
		{
			type: 'keycloak',
			name: 'Keycloak',
			description: 'Keycloak 그룹/조직 동기화'
		},
		{
			type: 'google',
			name: 'Google Workspace',
			description: 'Google Workspace 조직/그룹 동기화'
		}
	];

	// JSON Sync form
	let jsonInput = '';

	// MS Graph Sync options
	let msgraphOptions = {
		use_admin_units: true,
		use_groups: false,
		use_departments: false,
		group_filter: ''
	};

	// Keycloak Sync options
	let keycloakOptions = {
		use_groups: true,
		use_organizations: false
	};

	// Google Workspace Sync options
	let googleOptions = {
		use_org_units: true,
		use_groups: false
	};

	// 조직 단위 목록 탭: 'all' 또는 type 문자열 (provider별 동적 생성)
	let unitTab: string = 'all';

	// type별 라벨 맵 — $i18n.t()로 번역되는 영문 키 사용
	const unitTypeLabels: Record<string, string> = {
		organizational_unit: 'Organizational Unit',
		google_group: 'Group',
		administrative_unit: 'Administrative Unit',
		security_group: 'Security Group',
		microsoft_365_group: 'Microsoft 365 Group',
		dynamic_group: 'Dynamic Group',
		department: 'Department',
		group: 'Group',
		organization: 'Organization'
	};

	const labelForUnitType = (t: string | null | undefined): string => {
		if (!t) return 'Other';
		return unitTypeLabels[t] ?? t;
	};

	// 현재 조직에 존재하는 unique type들 (탭 동적 생성용, 개수 내림차순)
	$: unitTypeCounts = organizationalUnits.reduce((acc: Record<string, number>, u) => {
		const t = u.type ?? 'unknown';
		acc[t] = (acc[t] ?? 0) + 1;
		return acc;
	}, {});
	$: unitTypeTabs = Object.entries(unitTypeCounts).sort(([, a], [, b]) => b - a);
	$: showTypeTabs = unitTypeTabs.length >= 2;

	// 선택된 탭이 존재하지 않으면 'all'로 리셋 (조직 전환 시 stale tab 방지)
	$: if (unitTab !== 'all' && !(unitTab in unitTypeCounts)) {
		unitTab = 'all';
	}

	$: filteredUnits = unitTab === 'all'
		? organizationalUnits
		: organizationalUnits.filter((u) => (u.type ?? 'unknown') === unitTab);

	$: filteredOrganizations = organizations.filter((org) => {
		if (search === '') {
			return true;
		} else {
			const name = org.name.toLowerCase();
			const displayName = org.display_name?.toLowerCase() ?? '';
			const query = search.toLowerCase();
			return name.includes(query) || displayName.includes(query);
		}
	});

	const loadOrganizations = async () => {
		try {
			organizations = await getOrganizations(localStorage.token);
		} catch (error) {
			console.error('Failed to load organizations:', error);
			organizations = [];
		}
	};

	const flattenUnitsTree = (
		nodes: OrganizationalUnit[],
		level = 0,
		out: OrganizationalUnit[] = []
	): OrganizationalUnit[] => {
		for (const node of nodes) {
			out.push({ ...node, level: node.level ?? level, children: [] });
			if (node.children?.length) {
				flattenUnitsTree(node.children, (node.level ?? level) + 1, out);
			}
		}
		return out;
	};

	const loadOrganizationalUnits = async (organizationId: string) => {
		try {
			const tree = await getOrganizationalUnitsTree(localStorage.token, organizationId);
			organizationalUnits = flattenUnitsTree(tree);
		} catch (error) {
			console.error('Failed to load organizational units:', error);
			organizationalUnits = [];
		}
	};

	const loadSyncProviders = async () => {
		try {
			const result = await getSyncProviders(localStorage.token);
			syncProviders = result.providers;
		} catch (error) {
			console.error('Failed to load sync providers:', error);
			syncProviders = [];
		}
	};

	const selectOrganization = async (org: Organization) => {
		selectedOrganization = org;
		await loadOrganizationalUnits(org.id);
	};

	const handleDeleteOrganization = async () => {
		if (!selectedOrganization) return;

		deleting = true;
		try {
			await deleteOrganization(localStorage.token, selectedOrganization.id);
			toast.success($i18n.t('Organization deleted successfully'));

			// Reset state
			selectedOrganization = null;
			organizationalUnits = [];

			// Reload organizations list
			await loadOrganizations();
		} catch (error) {
			console.error('Failed to delete organization:', error);
			toast.error($i18n.t('Failed to delete organization'));
		} finally {
			deleting = false;
		}
	};

	// handleSaveUnitUsageLimit removed — 조직 단위 토큰 한도는 모델 페이지의 오버라이드 모달로 이전됨

	const handleSync = async () => {
		syncing = true;
		try {
			let result;
			if (selectedSyncProvider === 'json') {
				const data = JSON.parse(jsonInput);
				result = await syncFromJson(localStorage.token, data);
			} else if (selectedSyncProvider === 'msgraph') {
				result = await syncFromMSGraph(localStorage.token, {
					use_admin_units: msgraphOptions.use_admin_units,
					use_groups: msgraphOptions.use_groups,
					use_departments: msgraphOptions.use_departments,
					group_filter: msgraphOptions.group_filter || undefined
				});
			} else if (selectedSyncProvider === 'keycloak') {
				result = await syncFromKeycloak(localStorage.token, {
					use_groups: keycloakOptions.use_groups,
					use_organizations: keycloakOptions.use_organizations
				});
			} else if (selectedSyncProvider === 'google') {
				result = await syncFromGoogle(localStorage.token, {
					use_org_units: googleOptions.use_org_units,
					use_groups: googleOptions.use_groups
				});
			}

			if (result?.success) {
				const r = result.result;
				const orgCount = (r?.organization?.created || 0) + (r?.organization?.updated || 0);
				const unitCount = (r?.units?.created || 0) + (r?.units?.updated || 0);

				if (orgCount === 0 && unitCount === 0) {
					toast.warning($i18n.t('Sync completed but no data was found. Try enabling different options.'));
				} else {
					toast.success($i18n.t('Synced {{orgCount}} organization(s), {{unitCount}} unit(s)', { orgCount, unitCount }));
				}
				await loadOrganizations();
				showSyncModal = false;
			}
		} catch (error) {
			console.error('Sync failed:', error);
			toast.error($i18n.t('Sync failed: {{error}}', { error: String(error) }));
		} finally {
			syncing = false;
		}
	};

	onMount(async () => {
		if ($user?.role !== 'admin' && !hasPermission($userPermissions?.admin?.users)) {
			await goto('/');
		} else {
			await Promise.all([loadOrganizations(), loadSyncProviders()]);
		}
		loaded = true;
	});
</script>

{#if loaded}
	<!-- Header -->
	<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
		<div class="flex md:self-center text-lg font-medium px-0.5">
			{$i18n.t('Organizations')}
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
			<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
				>{organizations.length}</span
			>
		</div>

		<div class="flex gap-1">
			<div class="flex w-full space-x-2">
				<div class="flex flex-1">
					<div class="self-center ml-1 mr-3">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-4 h-4"
						>
							<path
								fill-rule="evenodd"
								d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
								clip-rule="evenodd"
							/>
						</svg>
					</div>
					<input
						class="w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
						bind:value={search}
						placeholder={$i18n.t('Search')}
					/>
				</div>

				<div>
					<Tooltip content={$i18n.t('Sync Organizations')}>
						<button
							class="p-2 rounded-xl hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 transition font-medium text-sm flex items-center space-x-1"
							on:click={() => {
								showSyncModal = true;
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="size-3.5"
							>
								<path
									fill-rule="evenodd"
									d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
									clip-rule="evenodd"
								/>
							</svg>
						</button>
					</Tooltip>
				</div>
			</div>
		</div>
	</div>

	<!-- Content -->
	<div>
		{#if filteredOrganizations.length === 0}
			<div class="flex flex-col items-center justify-center h-40">
				<div class="text-xl font-medium">
					{$i18n.t('Manage your organizations')}
				</div>

				<div class="mt-1 text-sm dark:text-gray-300">
					{$i18n.t('Organizations will be synced from your identity provider')}
				</div>

				<div class="mt-3">
					<button
						class="px-4 py-1.5 text-sm rounded-full bg-black hover:bg-gray-800 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition font-medium flex items-center space-x-1"
						aria-label={$i18n.t('Sync Organizations')}
						on:click={() => {
							showSyncModal = true;
						}}
					>
						{$i18n.t('Sync Now')}
					</button>
				</div>
			</div>
		{:else}
			<!-- Table Header -->
			<div class="flex items-center gap-3 justify-between text-xs uppercase px-1 font-bold">
				<div class="w-full">{$i18n.t('Organization')}</div>
				<div class="w-full">{$i18n.t('Domain')}</div>
				<div class="w-full">{$i18n.t('Units')}</div>
				<div class="w-20"></div>
			</div>

			<hr class="mt-1.5 border-gray-100 dark:border-gray-850" />

			<!-- Organization List -->
			{#each filteredOrganizations as org}
				<button
					class="flex items-center justify-between rounded-lg w-full transition py-2 hover:bg-gray-50 dark:hover:bg-gray-850 px-1"
					on:click={() => selectOrganization(org)}
				>
					<div class="flex items-center gap-2.5 w-full">
						<div class="p-1.5 bg-black/5 dark:bg-white/10 rounded-full">
							<Building className="size-4" />
						</div>
						<div class="text-left">
							<div class="text-sm font-medium">{org.display_name ?? org.name}</div>
						</div>
					</div>

					<div class="w-full text-left text-sm text-gray-500 dark:text-gray-400">
						{org.domain ?? '-'}
					</div>

					<div class="w-full text-left text-sm text-gray-500 dark:text-gray-400">
						{#if selectedOrganization?.id === org.id}
							{organizationalUnits.length}
						{:else}
							-
						{/if}
					</div>

					<div class="w-20 flex justify-end">
						<ChevronRight strokeWidth="2.5" />
					</div>
				</button>
			{/each}
		{/if}

		<!-- Selected Organization Units -->
		{#if selectedOrganization && organizationalUnits.length > 0}
			<hr class="my-3 border-gray-100 dark:border-gray-850" />

			<div class="mb-2 flex items-center justify-between">
				<div class="text-sm font-medium text-gray-500 dark:text-gray-400">
					{selectedOrganization.display_name ?? selectedOrganization.name}
				</div>
			</div>

			{#if showTypeTabs}
				<div class="flex gap-1 mb-2 p-0.5 bg-gray-100 dark:bg-gray-850 rounded-lg w-fit flex-wrap">
					<button
						class="px-3 py-1 text-xs font-medium rounded-md transition {unitTab === 'all' ? 'bg-white dark:bg-gray-700 shadow-sm text-gray-900 dark:text-gray-100' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
						on:click={() => { unitTab = 'all'; }}
					>
						{$i18n.t('All')} ({organizationalUnits.length})
					</button>
					{#each unitTypeTabs as [type, count]}
						<button
							class="px-3 py-1 text-xs font-medium rounded-md transition {unitTab === type ? 'bg-white dark:bg-gray-700 shadow-sm text-gray-900 dark:text-gray-100' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
							on:click={() => { unitTab = type; }}
						>
							{$i18n.t(labelForUnitType(type))} ({count})
						</button>
					{/each}
				</div>
			{/if}

			<div class="space-y-1">
				{#each filteredUnits as unit}
					<div
						class="flex items-center justify-between rounded-lg py-2 px-2 bg-gray-50 dark:bg-gray-850"
						style="margin-left: {(unit.level ?? 0) * 16}px"
					>
						<div class="flex items-center gap-2.5">
							<div class="p-1 bg-black/5 dark:bg-white/10 rounded">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 16 16"
									fill="currentColor"
									class="size-3"
								>
									<path
										d="M8.5 2.687c.654-.689 1.782-.886 3.112-.752 1.234.124 2.503.523 3.388.893v9.923c-.918-.35-2.107-.692-3.287-.81-1.094-.111-2.278-.039-3.213.492V2.687zM8 1.783C7.015.936 5.587.81 4.287.94c-1.514.153-3.042.672-3.994 1.105A.5.5 0 0 0 0 2.5v10a.5.5 0 0 0 .707.455c.882-.4 2.303-.881 3.68-1.02 1.409-.142 2.59.087 3.223.877a.5.5 0 0 0 .78 0c.633-.79 1.814-1.019 3.223-.877 1.377.139 2.798.62 3.68 1.02A.5.5 0 0 0 16 12.5v-10a.5.5 0 0 0-.293-.455c-.952-.433-2.48-.952-3.994-1.105C10.413.81 8.985.936 8 1.783z"
									/>
								</svg>
							</div>
							<div>
								<div class="text-sm font-medium">{unit.display_name ?? unit.name}</div>
								{#if unit.description}
									<div class="text-xs text-gray-500 dark:text-gray-400">
										{unit.description}
									</div>
								{/if}
							</div>
						</div>

						<div class="flex items-center gap-2">
							{#if unit.type}
								<span
									class="px-2 py-0.5 text-xs rounded-full bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
								>
									{unit.type}
								</span>
							{/if}
							<!-- <Tooltip content={$i18n.t('Guardrails')}>
								<button
									class="flex items-center gap-1 px-2 py-1 text-xs rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition text-gray-600 dark:text-gray-300"
									on:click|stopPropagation={() => openUnitGuardrails(unit)}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
										<path fill-rule="evenodd" d="M8 .982 2 3.57v3.712c0 3.86 2.56 7.276 6 8.218 3.44-.942 6-4.358 6-8.218V3.57L8 .982ZM7 5.75a1 1 0 1 1 2 0 1 1 0 0 1-2 0Zm1.75 2.5a.75.75 0 0 0-1.5 0v3a.75.75 0 0 0 1.5 0v-3Z" clip-rule="evenodd" />
									</svg>
								</button>
							</Tooltip>
							<Tooltip content={$i18n.t('View Permissions')}>
								<button
									class="flex items-center gap-1 px-2 py-1 text-xs rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition text-gray-600 dark:text-gray-300"
									on:click|stopPropagation={() => loadUnitPermissions(unit)}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
										<path fill-rule="evenodd" d="M8 1a3.5 3.5 0 0 0-3.5 3.5V7A1.5 1.5 0 0 0 3 8.5v5A1.5 1.5 0 0 0 4.5 15h7a1.5 1.5 0 0 0 1.5-1.5v-5A1.5 1.5 0 0 0 11.5 7V4.5A3.5 3.5 0 0 0 8 1Zm2 6V4.5a2 2 0 1 0-4 0V7h4Z" clip-rule="evenodd" />
									</svg>
								</button>
							</Tooltip> -->
							<button
								class="flex items-center gap-1 px-2 py-1 text-xs rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition text-gray-600 dark:text-gray-300"
								on:click|stopPropagation={() => {
									selectedUnit = unit;
									showUsersModal = true;
								}}
							>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
									<path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM12.735 14c.618 0 1.093-.561.872-1.139a6.002 6.002 0 0 0-11.215 0c-.22.578.254 1.139.872 1.139h9.47Z" />
								</svg>
								<span class="min-w-[1.5rem] text-right">{Math.max(unit.meta?.members?.length ?? 0, unit.member_ids?.length ?? 0)}</span>
							</button>
						</div>
					</div>

				{/each}
			</div>
		{/if}

		<!-- Delete Organization Section -->
		{#if selectedOrganization}
			<div class="mt-6 pt-4 border-t border-gray-200 dark:border-gray-800">
				<div class="flex items-center justify-between">
					<div class="flex-1">
						<div class="text-sm font-medium text-red-600 dark:text-red-400">
							{$i18n.t('Delete Organization')}
						</div>
						<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
							{$i18n.t('Permanently delete this organization and all its organizational units. This action cannot be undone.')}
						</p>
					</div>
					<button
						class="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 dark:bg-red-500 dark:hover:bg-red-600 rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
						disabled={deleting}
						on:click={() => {
							showDeleteConfirmDialog = true;
						}}
					>
						{#if deleting}
							<svg class="animate-spin size-4" viewBox="0 0 24 24">
								<circle
									class="opacity-25"
									cx="12"
									cy="12"
									r="10"
									stroke="currentColor"
									stroke-width="4"
									fill="none"
								/>
								<path
									class="opacity-75"
									fill="currentColor"
									d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
								/>
							</svg>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
								<path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.519.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 0-1.5.06l.3 7.5a.75.75 0 1 0 1.5-.06l-.3-7.5Zm4.34.06a.75.75 0 1 0-1.5-.06l-.3 7.5a.75.75 0 1 0 1.5.06l.3-7.5Z" clip-rule="evenodd" />
							</svg>
						{/if}
						{$i18n.t('Delete')}
					</button>
				</div>
			</div>
		{/if}
	</div>
{/if}

<!-- Delete Confirmation Dialog -->
<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	title={$i18n.t('Delete Organization')}
	onConfirm={handleDeleteOrganization}
>
	<div class="text-sm text-gray-500 dark:text-gray-400">
		<p class="mb-3">
			{$i18n.t('Are you sure you want to delete the organization "{{name}}"?', {
				name: selectedOrganization?.display_name ?? selectedOrganization?.name ?? ''
			})}
		</p>
		<div class="p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
			<div class="flex items-start gap-2">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5">
					<path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495ZM10 5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 10 5Zm0 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
				</svg>
				<div>
					<p class="font-medium text-red-600 dark:text-red-400">{$i18n.t('Warning')}</p>
					<ul class="mt-1 space-y-1 text-xs text-red-600 dark:text-red-400">
						<li>• {$i18n.t('All organizational units under this organization will be deleted')}</li>
						<li>• {$i18n.t('Member associations will be removed')}</li>
						<li>• {$i18n.t('This action cannot be undone')}</li>
					</ul>
				</div>
			</div>
		</div>
	</div>
</ConfirmDialog>

<!-- Sync Modal -->
{#if showSyncModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
		on:click|self={() => (showSyncModal = false)}
	>
		<div
			class="bg-white dark:bg-gray-900 rounded-2xl p-6 w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto"
		>
			<div class="flex justify-between items-center mb-4">
				<h3 class="text-lg font-medium">{$i18n.t('Sync Organizations')}</h3>
				<button
					class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition"
					on:click={() => (showSyncModal = false)}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						/>
					</svg>
				</button>
			</div>

			<!-- Provider Selection -->
			<div class="mb-4">
				<label class="block text-sm font-medium mb-2">{$i18n.t('Data Source')}</label>
				<select
					class="w-full px-4 py-2.5 rounded-xl text-sm bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 outline-none focus:border-gray-400 dark:focus:border-gray-500 transition"
					bind:value={selectedSyncProvider}
				>
					{#each (syncProviders.length > 0 ? syncProviders : defaultProviders) as provider}
						<option value={provider.type}>{provider.name}</option>
					{/each}
				</select>
			</div>

			<!-- Provider-specific options -->
			{#if selectedSyncProvider === 'json'}
				<div class="mb-4">
					<label class="block text-sm font-medium mb-2">{$i18n.t('JSON Data')}</label>
					<textarea
						class="w-full h-48 rounded-xl px-4 py-3 text-sm bg-gray-50 dark:bg-gray-850 outline-none font-mono border border-gray-200 dark:border-gray-700 focus:border-gray-400 dark:focus:border-gray-500 transition"
						placeholder={`{
  "organization": {
    "tenant_id": "my-company",
    "name": "My Company",
    "domain": "mycompany.com"
  },
  "units": [
    {
      "id": "dept-1",
      "name": "Engineering",
      "type": "department",
      "children": [...]
    }
  ]
}`}
						bind:value={jsonInput}
					/>
				</div>
			{:else if selectedSyncProvider === 'msgraph'}
				<div class="mb-4 space-y-4">
					<p class="text-sm text-gray-500 dark:text-gray-400">
						{$i18n.t('Sync organization structure from Microsoft Entra ID')}
					</p>

					<div class="space-y-3">
					<div
						class="flex items-start gap-3 p-3 rounded-lg transition {msgraphOptions.use_admin_units ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
					>
						<div class="mt-0.5">
							<Checkbox
								state={msgraphOptions.use_admin_units ? 'checked' : 'unchecked'}
								disabled={syncing}
								on:change={(e) => { msgraphOptions.use_admin_units = e.detail === 'checked'; }}
							/>
						</div>
						<div>
							<span class="text-sm font-medium">{$i18n.t('Administrative Units')}</span>
							<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
								{$i18n.t('Organizational management feature in Entra ID. Ideal for hierarchical structures.')}
							</p>
						</div>
					</div>

					<div
						class="flex items-start gap-3 p-3 rounded-lg transition {msgraphOptions.use_groups ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
					>
						<div class="mt-0.5">
							<Checkbox
								state={msgraphOptions.use_groups ? 'checked' : 'unchecked'}
								disabled={syncing}
								on:change={(e) => { msgraphOptions.use_groups = e.detail === 'checked'; }}
							/>
						</div>
						<div>
							<span class="text-sm font-medium">{$i18n.t('Security Groups')}</span>
							<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
								{$i18n.t('Use security groups as organizational units. Filter with OData query.')}
							</p>
						</div>
					</div>

					<div
						class="flex items-start gap-3 p-3 rounded-lg transition {msgraphOptions.use_departments ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
					>
						<div class="mt-0.5">
							<Checkbox
								state={msgraphOptions.use_departments ? 'checked' : 'unchecked'}
								disabled={syncing}
								on:change={(e) => { msgraphOptions.use_departments = e.detail === 'checked'; }}
							/>
						</div>
						<div>
							<span class="text-sm font-medium">{$i18n.t('Departments')}</span>
							<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
							{$i18n.t('Extract department names from user profiles automatically.')}
							</p>
						</div>
					</div>
				</div>

					{#if msgraphOptions.use_groups}
						<div class="pt-2">
							<label class="block text-sm font-medium mb-1.5">{$i18n.t('Group Filter (optional)')}</label>
							<input
								type="text"
								class="w-full rounded-xl px-4 py-2 text-sm bg-gray-50 dark:bg-gray-850 outline-none border border-gray-200 dark:border-gray-700 focus:border-gray-400 dark:focus:border-gray-500 transition"
								placeholder="startswith(displayName, 'Dept-')"
								bind:value={msgraphOptions.group_filter}
							/>
							<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
								{$i18n.t('OData filter expression to select specific groups')}
							</p>
						</div>
					{/if}
				</div>
			{:else if selectedSyncProvider === 'keycloak'}
				<div class="mb-4 space-y-4">
					<p class="text-sm text-[var(--cloo-text-muted)]">
						{$i18n.t('Sync organization structure from Keycloak. Server URL and credentials are configured via OPENID_PROVIDER_URL, OAUTH_CLIENT_ID, and OAUTH_CLIENT_SECRET environment variables.')}
					</p>

					<div class="space-y-3">
						<div
							class="flex items-start gap-3 p-3 rounded-lg transition {keycloakOptions.use_groups ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
						>
							<div class="mt-0.5">
								<Checkbox
									state={keycloakOptions.use_groups ? 'checked' : 'unchecked'}
									disabled={syncing}
									on:change={(e) => { keycloakOptions.use_groups = e.detail === 'checked'; }}
								/>
							</div>
							<div>
								<span class="text-sm font-medium">{$i18n.t('Groups')}</span>
								<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
									{$i18n.t('Sync Keycloak group hierarchy as organizational units')}
								</p>
							</div>
						</div>

						<div
							class="flex items-start gap-3 p-3 rounded-lg transition {keycloakOptions.use_organizations ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
						>
							<div class="mt-0.5">
								<Checkbox
									state={keycloakOptions.use_organizations ? 'checked' : 'unchecked'}
									disabled={syncing}
									on:change={(e) => { keycloakOptions.use_organizations = e.detail === 'checked'; }}
								/>
							</div>
							<div>
								<span class="text-sm font-medium">{$i18n.t('Organizations (v26+)')}</span>
								<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
									{$i18n.t('Use Keycloak Organizations feature (requires Keycloak 26 or later)')}
								</p>
							</div>
						</div>
					</div>
				</div>
			{:else if selectedSyncProvider === 'google'}
				<div class="mb-4 space-y-4">
					<p class="text-sm text-[var(--cloo-text-muted)]">
						{$i18n.t('Google Workspace의 조직 구조를 동기화합니다. 가져올 항목을 선택하세요.')}
					</p>

					<div class="space-y-3">
						<div
							class="flex items-start gap-3 p-3 rounded-lg transition {googleOptions.use_org_units ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
						>
							<div class="mt-0.5">
								<Checkbox
									state={googleOptions.use_org_units ? 'checked' : 'unchecked'}
									disabled={syncing}
									on:change={(e) => { googleOptions.use_org_units = e.detail === 'checked'; }}
								/>
							</div>
							<div>
								<span class="text-sm font-medium">{$i18n.t('group unit (OU)')}</span>
								<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
									{$i18n.t('Google Workspace의 조직 단위 계층 구조를 가져옵니다')}
								</p>
							</div>
						</div>

						<div
							class="flex items-start gap-3 p-3 rounded-lg transition {googleOptions.use_groups ? 'bg-[var(--cloo-bg-neutral-hovered)] ring-1 ring-[var(--cloo-border-default)]' : 'hover:bg-[var(--cloo-bg-neutral-hovered)]'} {syncing ? 'opacity-50' : ''}"
						>
							<div class="mt-0.5">
								<Checkbox
									state={googleOptions.use_groups ? 'checked' : 'unchecked'}
									disabled={syncing}
									on:change={(e) => { googleOptions.use_groups = e.detail === 'checked'; }}
								/>
							</div>
							<div>
								<span class="text-sm font-medium">{$i18n.t('Group')}</span>
								<p class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
									{$i18n.t('Google Groups를 조직 단위로 가져옵니다')}
								</p>
							</div>
						</div>
					</div>
				</div>
			{/if}

			<!-- Actions -->
			<div class="flex justify-end gap-2 mt-6">
				<button
					class="px-4 py-2 text-sm rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={() => (showSyncModal = false)}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-2 text-sm rounded-xl bg-black hover:bg-gray-800 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
					disabled={syncing}
					on:click={handleSync}
				>
					{#if syncing}
						<svg class="animate-spin size-4" viewBox="0 0 24 24">
							<circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="4"
								fill="none"
							/>
							<path
								class="opacity-75"
								fill="currentColor"
								d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
							/>
						</svg>
					{/if}
					{$i18n.t('Sync')}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Users Modal -->
{#if showUsersModal && selectedUnit}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
		on:click|self={() => {
			showUsersModal = false;
			selectedUnit = null;
		}}
	>
		<div
			class="bg-white dark:bg-gray-900 rounded-2xl p-6 w-full max-w-lg mx-4 max-h-[80vh] overflow-hidden flex flex-col"
		>
			<div class="flex justify-between items-center mb-4">
				<div>
					<h3 class="text-lg font-medium">{$i18n.t('Members')}</h3>
					<p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
						{selectedUnit.display_name ?? selectedUnit.name}
					</p>
				</div>
				<button
					class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition"
					on:click={() => {
						showUsersModal = false;
						selectedUnit = null;
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						/>
					</svg>
				</button>
			</div>

			<div class="flex-1 overflow-y-auto">
				{#if totalMemberCount === 0}
					<div class="flex flex-col items-center justify-center py-12 text-gray-500 dark:text-gray-400">
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-12 mb-3 opacity-50">
							<path fill-rule="evenodd" d="M8.25 6.75a3.75 3.75 0 1 1 7.5 0 3.75 3.75 0 0 1-7.5 0ZM15.75 9.75a3 3 0 1 1 6 0 3 3 0 0 1-6 0ZM2.25 9.75a3 3 0 1 1 6 0 3 3 0 0 1-6 0ZM6.31 15.117A6.745 6.745 0 0 1 12 12a6.745 6.745 0 0 1 6.709 7.498.75.75 0 0 1-.372.568A12.696 12.696 0 0 1 12 21.75c-2.305 0-4.47-.612-6.337-1.684a.75.75 0 0 1-.372-.568 6.787 6.787 0 0 1 1.019-4.38Z" clip-rule="evenodd" />
							<path d="M5.082 14.254a8.287 8.287 0 0 0-1.308 5.135 9.687 9.687 0 0 1-1.764-.44l-.115-.04a.563.563 0 0 1-.373-.487l-.01-.121a3.75 3.75 0 0 1 3.57-4.047ZM20.226 19.389a8.287 8.287 0 0 0-1.308-5.135 3.75 3.75 0 0 1 3.57 4.047l-.01.121a.563.563 0 0 1-.373.486l-.115.04c-.567.2-1.156.349-1.764.441Z" />
						</svg>
						<p class="text-sm">{$i18n.t('No members found')}</p>
						<p class="text-xs mt-1">{$i18n.t('This unit has no registered members')}</p>
					</div>
				{:else}
					<!-- Azure AD/Google sync 멤버 + OAuth 자동 할당 사용자 union 표시 -->
					<div class="space-y-1">
						{#each unitMembers as member}
							{@const systemUser = users.find((u) =>
								u.oauth_sub === member.id ||
								u.email?.toLowerCase() === member.email?.toLowerCase()
							)}
							<div class="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 transition">
								<div class="relative">
									{#if systemUser?.profile_image_url}
										<img
											src={systemUser.profile_image_url}
											alt={member.name}
											class="size-9 rounded-full object-cover"
										/>
									{:else}
										<div class="size-9 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-sm font-medium">
											{member.name?.charAt(0)?.toUpperCase() ?? '?'}
										</div>
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span class="text-sm font-medium truncate">{member.name}</span>
										{#if systemUser}
											<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
												{$i18n.t('Registered')}
											</span>
										{:else}
											<span class="px-1.5 py-0.5 text-xs rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
												{$i18n.t('Not registered')}
											</span>
										{/if}
									</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
										{member.email}
										{#if member.job_title}
											<span class="mx-1">·</span>
											{member.job_title}
										{/if}
									</div>
								</div>
							</div>
						{/each}
						{#each extraUnitUsers as member}
							<div class="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 transition">
								<div class="relative">
									{#if member.profile_image_url}
										<img
											src={member.profile_image_url}
											alt={member.name}
											class="size-9 rounded-full object-cover"
										/>
									{:else}
										<div class="size-9 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-sm font-medium">
											{member.name?.charAt(0)?.toUpperCase() ?? '?'}
										</div>
									{/if}
								</div>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span class="text-sm font-medium truncate">{member.name}</span>
										{#if member.role === 'admin'}
											<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
												Admin
											</span>
										{/if}
										<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
											{$i18n.t('Registered')}
										</span>
									</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
										{member.email}
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- 조직 단위별 토큰 한도는 [관리자 > 설정 > 모델] accordion 의 "조직 단위 오버라이드" 에서 관리 -->

			<div class="flex justify-between items-center pt-4 mt-4 border-t border-gray-100 dark:border-gray-800">
				<span class="text-sm text-gray-500 dark:text-gray-400">
					{totalMemberCount} {$i18n.t('members')}
				</span>
				<div class="flex gap-2">
					<button
						class="px-4 py-2 text-sm rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800 transition"
						on:click={() => {
							showUsersModal = false;
							selectedUnit = null;
						}}
					>
						{$i18n.t('Close')}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- Permissions Modal -->
{#if showPermissionsModal && permissionsUnit}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
		on:click|self={() => {
			showPermissionsModal = false;
			permissionsUnit = null;
			unitPermissions = null;
		}}
	>
		<div
			class="bg-white dark:bg-gray-900 rounded-2xl p-6 w-full max-w-2xl mx-4 max-h-[80vh] overflow-hidden flex flex-col"
		>
			<div class="flex justify-between items-center mb-4">
				<div>
					<h3 class="text-lg font-medium">{$i18n.t('Assigned Permissions')}</h3>
					<p class="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
						{permissionsUnit.display_name ?? permissionsUnit.name}
					</p>
				</div>
				<button
					class="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition"
					on:click={() => {
						showPermissionsModal = false;
						permissionsUnit = null;
						unitPermissions = null;
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						/>
					</svg>
				</button>
			</div>

			<div class="flex-1 overflow-y-auto">
				{#if loadingPermissions}
					<div class="flex items-center justify-center py-12">
						<svg class="animate-spin size-8 text-gray-400" viewBox="0 0 24 24">
							<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
							<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
						</svg>
					</div>
				{:else if unitPermissions}
					{@const hasAnyPermission = Object.values(unitPermissions.permissions).some(
						(arr) => (arr?.length ?? 0) > 0
					)}

					{#if !hasAnyPermission}
						<div class="flex flex-col items-center justify-center py-12 text-gray-500 dark:text-gray-400">
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-12 mb-3 opacity-50">
								<path fill-rule="evenodd" d="M12 1.5a5.25 5.25 0 0 0-5.25 5.25v3a3 3 0 0 0-3 3v6.75a3 3 0 0 0 3 3h10.5a3 3 0 0 0 3-3v-6.75a3 3 0 0 0-3-3v-3c0-2.9-2.35-5.25-5.25-5.25Zm3.75 8.25v-3a3.75 3.75 0 1 0-7.5 0v3h7.5Z" clip-rule="evenodd" />
							</svg>
							<p class="text-sm">{$i18n.t('No permissions assigned')}</p>
							<p class="text-xs mt-1">{$i18n.t('This organizational unit has no resource access')}</p>
						</div>
					{:else}
						<div class="space-y-4">
							<!-- Knowledge -->
							{#if unitPermissions.permissions.knowledge.length > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path d="M10.75 16.82A7.462 7.462 0 0 1 15 15.5c.71 0 1.396.098 2.046.282A.75.75 0 0 0 18 15.06v-11a.75.75 0 0 0-.546-.721A9.006 9.006 0 0 0 15 3a8.963 8.963 0 0 0-4.25 1.065V16.82ZM9.25 4.065A8.963 8.963 0 0 0 5 3c-.85 0-1.673.118-2.454.339A.75.75 0 0 0 2 4.06v11a.75.75 0 0 0 .954.721A7.506 7.506 0 0 1 5 15.5c1.579 0 3.042.487 4.25 1.32V4.065Z" />
										</svg>
										{$i18n.t('Knowledge')} ({unitPermissions.permissions.knowledge.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.knowledge as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="flex-1 min-w-0">
													<div class="text-sm font-medium truncate">{item.name}</div>
													{#if item.description}
														<div class="text-xs text-gray-500 truncate">{item.description}</div>
													{/if}
												</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Tools -->
							{#if unitPermissions.permissions.tools.length > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path fill-rule="evenodd" d="M14.5 10a4.5 4.5 0 0 0 4.284-5.882c-.105-.324-.51-.391-.752-.15L15.34 6.66a.454.454 0 0 1-.493.11 3.01 3.01 0 0 1-1.618-1.616.455.455 0 0 1 .11-.494l2.694-2.692c.24-.241.174-.647-.15-.752a4.5 4.5 0 0 0-5.873 4.575c.055.873-.128 1.808-.8 2.368l-7.23 6.024a2.724 2.724 0 1 0 3.837 3.837l6.024-7.23c.56-.672 1.495-.855 2.368-.8.096.007.193.01.291.01ZM5 16a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z" clip-rule="evenodd" />
										</svg>
										{$i18n.t('Tools')} ({unitPermissions.permissions.tools.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.tools as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="text-sm font-medium truncate">{item.name}</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Prompts -->
							{#if unitPermissions.permissions.prompts.length > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path fill-rule="evenodd" d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Zm2.25 8.5a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Zm0 3a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5h-6.5Z" clip-rule="evenodd" />
										</svg>
										{$i18n.t('Prompts')} ({unitPermissions.permissions.prompts.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.prompts as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="text-sm font-medium truncate">{item.name}</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Models -->
							{#if unitPermissions.permissions.models.length > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path d="M10 2.5a7.5 7.5 0 0 0-6.546 11.163L2 16l2.337-1.454A7.5 7.5 0 1 0 10 2.5ZM8.5 7a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-.5.5H9a.5.5 0 0 1-.5-.5V7Zm0 4a.5.5 0 0 1 .5-.5h2a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-.5.5H9a.5.5 0 0 1-.5-.5v-2Z" />
										</svg>
										{$i18n.t('Models')} ({unitPermissions.permissions.models.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.models as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="text-sm font-medium truncate">{item.name}</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Databases -->
							{#if (unitPermissions.permissions.databases?.length ?? 0) > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path fill-rule="evenodd" d="M10 1c3.866 0 7 1.79 7 4s-3.134 4-7 4-7-1.79-7-4 3.134-4 7-4Zm5.694 8.13c.464-.264.91-.583 1.306-.952V10c0 2.21-3.134 4-7 4s-7-1.79-7-4V8.178c.396.37.842.688 1.306.953C5.838 10.006 7.854 10.5 10 10.5s4.162-.494 5.694-1.37ZM3 13.179V15c0 2.21 3.134 4 7 4s7-1.79 7-4v-1.822c-.396.37-.842.688-1.306.953-1.532.875-3.548 1.369-5.694 1.369s-4.162-.494-5.694-1.37A7.009 7.009 0 0 1 3 13.179Z" clip-rule="evenodd" />
										</svg>
										{$i18n.t('Database')} ({unitPermissions.permissions.databases.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.databases as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="flex-1 min-w-0">
													<div class="text-sm font-medium truncate">{item.name}</div>
													{#if item.description}
														<div class="text-xs text-gray-500 truncate">{item.description}</div>
													{/if}
												</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Guardrails -->
							{#if (unitPermissions.permissions.guardrails?.length ?? 0) > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path fill-rule="evenodd" d="M10 1.5a.75.75 0 0 1 .564.256l7 8a.75.75 0 0 1 .186.494v6.5a.75.75 0 0 1-.75.75H3a.75.75 0 0 1-.75-.75v-6.5a.75.75 0 0 1 .186-.494l7-8A.75.75 0 0 1 10 1.5ZM8.75 10a1.25 1.25 0 1 1 2.5 0 1.25 1.25 0 0 1-2.5 0Z" clip-rule="evenodd" />
										</svg>
										{$i18n.t('Guardrails')} ({unitPermissions.permissions.guardrails.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.guardrails as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="flex-1 min-w-0">
													<div class="text-sm font-medium truncate">{item.name}</div>
													{#if item.description}
														<div class="text-xs text-gray-500 truncate">{item.description}</div>
													{/if}
												</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Glossaries -->
							{#if (unitPermissions.permissions.glossaries?.length ?? 0) > 0}
								<div>
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
											<path d="M10.75 16.82A7.462 7.462 0 0 1 15 15.5c.71 0 1.396.098 2.046.282A.75.75 0 0 0 18 15.06v-11a.75.75 0 0 0-.546-.721A9.006 9.006 0 0 0 15 3a8.963 8.963 0 0 0-4.25 1.065V16.82ZM9.25 4.065A8.963 8.963 0 0 0 5 3c-.85 0-1.673.118-2.454.339A.75.75 0 0 0 2 4.06v11a.75.75 0 0 0 .954.721A7.506 7.506 0 0 1 5 15.5c1.579 0 3.042.487 4.25 1.32V4.065Z" />
										</svg>
										{$i18n.t('Glossary')} ({unitPermissions.permissions.glossaries.length})
									</div>
									<div class="space-y-1">
										{#each unitPermissions.permissions.glossaries as item}
											<div class="flex items-center justify-between p-2 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="flex-1 min-w-0">
													<div class="text-sm font-medium truncate">{item.name}</div>
													{#if item.description}
														<div class="text-xs text-gray-500 truncate">{item.description}</div>
													{/if}
												</div>
												<div class="flex items-center gap-1.5 ml-2">
													{#if item.inherited}
														<span class="px-1.5 py-0.5 text-xs rounded bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400">
															{$i18n.t('Inherited')}
														</span>
													{/if}
													{#if item.write}
														<span class="px-1.5 py-0.5 text-xs rounded bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400">
															{$i18n.t('Write')}
														</span>
													{:else}
														<span class="px-1.5 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
															{$i18n.t('Read')}
														</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					{/if}
				{/if}
			</div>

			<div class="flex justify-end items-center pt-4 mt-4 border-t border-gray-100 dark:border-gray-800">
				<button
					class="px-4 py-2 text-sm rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={() => {
						showPermissionsModal = false;
						permissionsUnit = null;
						unitPermissions = null;
					}}
				>
					{$i18n.t('Close')}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Unit Guardrails Modal -->
{#if showGuardrailsModal && guardrailsUnit}
	<Modal
		size="sm"
		bind:show={showGuardrailsModal}
		className="bg-white dark:bg-gray-900 rounded-2xl overflow-visible"
		on:close={() => {
			showGuardrailsModal = false;
			guardrailsUnit = null;
		}}
	>
		<div class="px-5 py-4">
			<div class="text-lg font-semibold mb-1">
				{$i18n.t('Guardrails')}
			</div>
			<div class="text-sm text-[var(--cloo-text-muted)] mb-4">
				{guardrailsUnit.display_name ?? guardrailsUnit.name}
			</div>

			<div class="flex flex-col gap-[var(--cloo-space-3)]">
				<LabelBase
					label={$i18n.t('Follow global guardrail settings')}
					size="md"
				>
					<svelte:fragment slot="right">
						<Switch bind:state={unitFollowGlobal} />
					</svelte:fragment>
				</LabelBase>

				<div>
					<div class="text-xs text-[var(--cloo-text-muted)] mb-1.5">
						{$i18n.t('Additional guardrails for this organization')}
					</div>

					{#each unitGuardrailIds as gid, idx}
						{@const guardrail = allGuardrails.find((g) => g.id === gid)}
						<div class="flex items-center justify-between rounded-[var(--cloo-radius-default)] py-1.5 px-2.5 mb-1 bg-[var(--cloo-bg-neutral-hovered)]">
							<div class="flex items-center gap-2">
								{#if guardrail}
									<Badge status={guardrail.llm_judge_enabled ? 'info' : 'default'} size="sm">
										{guardrail.llm_judge_enabled ? 'LLM Judge' : 'Rule'}
									</Badge>
									<span class="text-sm">{guardrail.name}</span>
								{:else}
									<span class="text-sm text-[var(--cloo-text-muted)]">{gid}</span>
								{/if}
							</div>
							<Button kind="text" size="sm" status="error" on:click={() => { unitGuardrailIds = unitGuardrailIds.filter((_, i) => i !== idx); }}>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
									<path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
								</svg>
							</Button>
						</div>
					{/each}

					<Selector
						value=""
						items={allGuardrails
							.filter((g) => !unitGuardrailIds.includes(g.id))
							.map((g) => ({ value: g.id, label: g.name }))}
						placeholder={$i18n.t('Add guardrail...')}
						size="md"
						searchEnabled
						portal={null}
						on:change={(e) => {
							const val = e.detail.value;
							if (val && !unitGuardrailIds.includes(val)) {
								unitGuardrailIds = [...unitGuardrailIds, val];
							}
						}}
					/>
				</div>

				<div class="flex justify-end gap-2 pt-2">
					<Button kind="outlined" size="md" on:click={() => { showGuardrailsModal = false; guardrailsUnit = null; }}>
						{$i18n.t('Cancel')}
					</Button>
					<Button kind="filled" size="md" loading={savingGuardrails} on:click={saveUnitGuardrails}>
						{$i18n.t('Save')}
					</Button>
				</div>
			</div>
		</div>
	</Modal>
{/if}
