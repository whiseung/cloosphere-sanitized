<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';

	type I18nStore = Readable<{
		t: (key: string) => string;
	}>;

	type AccessGroup = {
		id: string;
		name: string;
	};

	const i18n = getContext<I18nStore>('i18n');

	import { getGroups, getGroupsByIds } from '$lib/apis/groups';
	import {
		getOrganizations,
		getOrganizationalUnitsTree,
		type OrganizationalUnit
	} from '$lib/apis/organizations';
	import Selector from '$lib/components/common/Selector.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';
	import Building from '$lib/components/icons/Building.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Badge from '$lib/components/common/Badge.svelte';

	export let onChange: (value: unknown) => void = () => {};

	export let accessRoles = ['read'];
	export let accessControl: any = null;

	export let allowPublic = true;

	let groups: AccessGroup[] = [];
	let orgUnits: OrganizationalUnit[] = [];
	let initialized = false; // 초기화 완료 플래그
	let lastAccessControlJson = ''; // 변경 감지용
	let selectedGroupId = '';
	let selectedOrgUnitId = '';

	// 조직 단위를 평탄화 (계층 구조 -> flat 리스트)
	function flattenOrgUnits(units: OrganizationalUnit[], prefix = ''): OrganizationalUnit[] {
		let result: OrganizationalUnit[] = [];
		for (const unit of units) {
			const displayName = prefix
				? `${prefix} / ${unit.display_name ?? unit.name}`
				: (unit.display_name ?? unit.name);
			result.push({ ...unit, display_name: displayName });
			if (unit.children?.length) {
				result = result.concat(flattenOrgUnits(unit.children, displayName));
			}
		}
		return result;
	}

	$: if (!allowPublic && accessControl === null) {
		accessControl = {
			read: {
				group_ids: [],
				user_ids: [],
				org_unit_ids: []
			},
			write: {
				group_ids: [],
				user_ids: [],
				org_unit_ids: []
			}
		};
		// 초기화 시에는 onChange 호출하지 않음
	}

	$: visibilityItems = [
		{
			value: 'private',
			label: $i18n.t('Private')
		},
		...(allowPublic
			? [
					{
						value: 'public',
						label: $i18n.t('Public')
					}
				]
			: [])
	];

	$: availableGroupItems = groups
		.filter(
			(group) =>
				!(accessControl?.read?.group_ids ?? []).includes(group.id) &&
				!(accessControl?.write?.group_ids ?? []).includes(group.id)
		)
		.map((group) => ({
			value: group.id,
			label: group.name
		}));

	$: availableOrgUnitItems = orgUnits
		.filter((unit) => !(accessControl?.read?.org_unit_ids ?? []).includes(unit.id))
		.map((unit) => ({
			value: unit.id,
			label: unit.display_name ?? unit.name
		}));

	$: if (accessControl === null) {
		selectedGroupId = '';
		selectedOrgUnitId = '';
	}

	onMount(async () => {
		groups = await getGroups(localStorage.token);

		// access_control에 포함된 그룹 중 현재 사용자 그룹 목록에 없는 것을 보충 조회
		// read/write 모두 조회하여 고아 엔트리(write-only)도 UI에 노출되도록 함
		{
			const referencedIds = [
				...(accessControl?.read?.group_ids ?? []),
				...(accessControl?.write?.group_ids ?? [])
			];
			if (referencedIds.length > 0) {
				const knownIds = new Set(groups.map((g) => g.id));
				const missingIds = [...new Set(referencedIds)].filter(
					(gid: string) => !knownIds.has(gid)
				);
				if (missingIds.length > 0) {
					try {
						const resolved = await getGroupsByIds(localStorage.token, missingIds);
						if (resolved && resolved.length > 0) {
							groups = [...groups, ...resolved];
						}
					} catch (e) {
						console.error('Failed to resolve group names:', e);
					}
				}
			}
		}

		// 모든 조직에서 조직 단위 로드
		try {
			const organizations = await getOrganizations(localStorage.token);
			let allOrgUnits: OrganizationalUnit[] = [];

			for (const org of organizations) {
				const treeUnits = await getOrganizationalUnitsTree(localStorage.token, org.id);
				// 조직 이름을 prefix로 추가하여 구분
				const flatUnits = flattenOrgUnits(
					treeUnits,
					organizations.length > 1 ? (org.display_name ?? org.name) : ''
				);
				allOrgUnits = allOrgUnits.concat(flatUnits);
			}

			orgUnits = allOrgUnits;
		} catch (e) {
			console.error('Failed to load organizational units:', e);
		}

		if (accessControl === null) {
			if (allowPublic) {
				accessControl = null;
			} else {
				accessControl = {
					read: {
						group_ids: [],
						user_ids: [],
						org_unit_ids: []
					},
					write: {
						group_ids: [],
						user_ids: [],
						org_unit_ids: []
					}
				};
				// 초기화 시에는 onChange 호출하지 않음
			}
		} else {
			accessControl = {
				read: {
					group_ids: accessControl?.read?.group_ids ?? [],
					user_ids: accessControl?.read?.user_ids ?? [],
					org_unit_ids: accessControl?.read?.org_unit_ids ?? []
				},
				write: {
					group_ids: accessControl?.write?.group_ids ?? [],
					user_ids: accessControl?.write?.user_ids ?? [],
					org_unit_ids: accessControl?.write?.org_unit_ids ?? []
				}
			};
		}

		// 초기화 완료 - 현재 상태를 저장하여 변경 감지에 사용
		lastAccessControlJson = JSON.stringify(accessControl);
		initialized = true;
	});

	// 초기화 완료 후, 실제 변경이 있을 때만 onChange 호출
	$: if (initialized) {
		const currentJson = JSON.stringify(accessControl);
		if (currentJson !== lastAccessControlJson) {
			lastAccessControlJson = currentJson;
			onChange(accessControl);
		}
	}

	function handleVisibilityChange(nextValue: string) {
		if (nextValue === 'public') {
			accessControl = null;
			return;
		}

		accessControl = {
			read: {
				group_ids: [],
				user_ids: [],
				org_unit_ids: []
			},
			write: {
				group_ids: [],
				user_ids: [],
				org_unit_ids: []
			}
		};
	}

	function handleGroupSelect(groupId: string) {
		if (groupId && accessControl) {
			accessControl.read.group_ids = [...accessControl.read.group_ids, groupId];
			selectedGroupId = '';
		}
	}

	function handleOrgUnitSelect(unitId: string) {
		if (unitId && accessControl) {
			// org_unit_ids가 없으면 초기화
			if (!accessControl.read.org_unit_ids) {
				accessControl.read.org_unit_ids = [];
			}
			if (!accessControl.write.org_unit_ids) {
				accessControl.write.org_unit_ids = [];
			}

			accessControl.read.org_unit_ids = [...accessControl.read.org_unit_ids, unitId];
			selectedOrgUnitId = '';
		}
	}

	function toggleGroupWrite(groupId: string) {
		if (!accessRoles.includes('write')) {
			return;
		}

		if (accessControl.write.group_ids.includes(groupId)) {
			accessControl.write.group_ids = accessControl.write.group_ids.filter(
				(id: string) => id !== groupId
			);
			return;
		}

		accessControl.write.group_ids = [...accessControl.write.group_ids, groupId];
	}

	function removeGroup(groupId: string) {
		accessControl.read.group_ids = (accessControl.read.group_ids ?? []).filter(
			(id: string) => id !== groupId
		);
		accessControl.write.group_ids = (accessControl.write.group_ids ?? []).filter(
			(id: string) => id !== groupId
		);
	}

	function toggleOrgUnitWrite(unitId: string) {
		if (!accessRoles.includes('write')) {
			return;
		}

		if (!accessControl.write.org_unit_ids) {
			accessControl.write.org_unit_ids = [];
		}

		if (accessControl.write.org_unit_ids.includes(unitId)) {
			accessControl.write.org_unit_ids = accessControl.write.org_unit_ids.filter(
				(id: string) => id !== unitId
			);
			return;
		}

		accessControl.write.org_unit_ids = [...accessControl.write.org_unit_ids, unitId];
	}

	function removeOrgUnit(unitId: string) {
		accessControl.read.org_unit_ids = (accessControl.read.org_unit_ids ?? []).filter(
			(id: string) => id !== unitId
		);
		accessControl.write.org_unit_ids = (accessControl.write.org_unit_ids ?? []).filter(
			(id: string) => id !== unitId
		);
	}
</script>

<div class="access-control">
	<div class="access-control__section">
		<div class="access-control__visibility-row">
			<div>
				<div class=" p-2 bg-black/5 dark:bg-white/5 rounded-full">
					{#if accessControl !== null}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-5 h-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z"
							/>
						</svg>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-5 h-5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M6.115 5.19l.319 1.913A6 6 0 008.11 10.36L9.75 12l-.387.775c-.217.433-.132.956.21 1.298l1.348 1.348c.21.21.329.497.329.795v1.089c0 .426.24.815.622 1.006l.153.076c.433.217.956.132 1.298-.21l.723-.723a8.7 8.7 0 002.288-4.042 1.087 1.087 0 00-.358-1.099l-1.33-1.108c-.251-.21-.582-.299-.905-.245l-1.17.195a1.125 1.125 0 01-.98-.314l-.295-.295a1.125 1.125 0 010-1.591l.13-.132a1.125 1.125 0 011.3-.21l.603.302a.809.809 0 001.086-1.086L14.25 7.5l1.256-.837a4.5 4.5 0 001.528-1.732l.146-.292M6.115 5.19A9 9 0 1017.18 4.64M6.115 5.19A8.965 8.965 0 0112 3c1.929 0 3.716.607 5.18 1.64"
							/>
						</svg>
					{/if}
				</div>
			</div>

			<!-- Figma 1305:12317 — LabelBase (label + caption flex-1) | Selector right slot.
			     Caption now uses left column's full width instead of being trapped under the Selector. -->
			<div class="access-control__visibility-content">
				<LabelBase
					label={$i18n.t('Permission')}
					caption={accessControl !== null
						? $i18n.t('Only select users and groups with permission can access')
						: $i18n.t('Accessible to all users')}
					size="md"
				>
					<svelte:fragment slot="right">
						<div class="w-[140px]">
							<Selector
								portal={null}
								value={accessControl !== null ? 'private' : 'public'}
								items={visibilityItems}
								searchEnabled={false}
								placeholder={$i18n.t('Visibility')}
								ariaLabel={$i18n.t('Visibility')}
								on:change={(event) => {
									handleVisibilityChange(event.detail.value);
								}}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			</div>
		</div>
	</div>
	{#if accessControl !== null && accessControl?.read?.group_ids && accessControl?.write?.group_ids}
		{@const accessGroupIds = [
			...new Set([
				...(accessControl.read.group_ids ?? []),
				...(accessControl.write.group_ids ?? [])
			])
		]}
		{@const accessGroups = groups.filter((group) => accessGroupIds.includes(group.id))}
		<div class="access-control__section">
			<div class="access-control__group-panel">
				<div class="access-control__panel-header">
					<div class="access-control__label">
						{$i18n.t('Groups')}
					</div>
				</div>

				<div class="access-control__selector-row">
					<div class="flex w-full">
						<div class="flex flex-1 items-center">
							<div class="w-full px-0.5">
								<Selector
									portal={null}
									bind:value={selectedGroupId}
									items={availableGroupItems}
									placeholder={$i18n.t('Select a group')}
									searchPlaceholder={$i18n.t('Search groups')}
									emptyMessage={$i18n.t('No groups available')}
									ariaLabel={$i18n.t('Select a group')}
									on:change={(event) => {
										handleGroupSelect(event.detail.value);
									}}
								/>
							</div>
							<!-- <div>
								<Tooltip content={$i18n.t('Add Group')}>
									<button
										class=" p-1 rounded-xl bg-transparent dark:hover:bg-white/5 hover:bg-black/5 transition font-medium text-sm flex items-center space-x-1"
										type="button"
										on:click={() => {}}
									>
										<Plus className="size-3.5" />
									</button>
								</Tooltip>
							</div> -->
						</div>
					</div>
				</div>

				<hr class="access-control__divider" />

				<div class="access-control__list">
					{#if accessGroups.length > 0}
						{#each accessGroups as group}
							<div class="flex items-center gap-3 justify-between text-xs w-full transition">
								<div class="flex items-center gap-1.5 w-full font-medium">
									<div>
										<UserCircleSolid className="size-4" />
									</div>

									<div>
										{group.name}
									</div>
								</div>

								<div class="w-full flex justify-end items-center gap-0.5">
									<button
										class=""
										type="button"
										on:click={() => {
											toggleGroupWrite(group.id);
										}}
									>
										{#if accessControl.write.group_ids.includes(group.id)}
											<Badge type={'success'} content={$i18n.t('Write')} />
										{:else}
											<Badge type={'info'} content={$i18n.t('Read')} />
										{/if}
									</button>

									<button
										class=" rounded-full p-1 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
										type="button"
										on:click={() => {
											removeGroup(group.id);
										}}
									>
										<XMark />
									</button>
								</div>
							</div>
						{/each}
					{:else}
						<div class="access-control__empty-wrap">
							<div class="access-control__empty-text">
								{$i18n.t('No groups with access, add a group to grant access')}
							</div>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Organizational Units Section -->
		{#if orgUnits.length > 0}
			{@const accessOrgUnits = orgUnits.filter((unit) =>
				(accessControl.read.org_unit_ids ?? []).includes(unit.id)
			)}
			<div class="access-control__section">
				<div class="access-control__group-panel">
					<div class="access-control__panel-header">
						<div class="access-control__label">
							{$i18n.t('Organizational Units')}
						</div>
					</div>

					<div class="access-control__selector-row">
						<div class="flex w-full">
							<div class="flex flex-1 items-center">
								<div class="w-full px-0.5">
									<Selector
										portal={null}
										bind:value={selectedOrgUnitId}
										items={availableOrgUnitItems}
										placeholder={$i18n.t('Select an organizational unit')}
										searchPlaceholder={$i18n.t('Search organizational units')}
										emptyMessage={$i18n.t('No organizational units available')}
										ariaLabel={$i18n.t('Select an organizational unit')}
										on:change={(event) => {
											handleOrgUnitSelect(event.detail.value);
										}}
									/>
								</div>
							</div>
						</div>
					</div>

					<hr class="access-control__divider" />

					<div class="access-control__list">
						{#if accessOrgUnits.length > 0}
							{#each accessOrgUnits as unit}
								<div class="flex items-center gap-3 justify-between text-xs w-full transition">
									<div class="flex items-center gap-1.5 w-full font-medium">
										<div>
											<Building className="size-4" />
										</div>

										<div class="truncate">
											{unit.display_name ?? unit.name}
										</div>
									</div>

									<div class="w-full flex justify-end items-center gap-0.5">
										<button
											class=""
											type="button"
											on:click={() => {
												toggleOrgUnitWrite(unit.id);
											}}
										>
											{#if (accessControl.write.org_unit_ids ?? []).includes(unit.id)}
												<Badge type={'success'} content={$i18n.t('Write')} />
											{:else}
												<Badge type={'info'} content={$i18n.t('Read')} />
											{/if}
										</button>

										<button
											class=" rounded-full p-1 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
											type="button"
											on:click={() => {
												removeOrgUnit(unit.id);
											}}
										>
											<XMark />
										</button>
									</div>
								</div>
							{/each}
						{:else}
							<div class="access-control__empty-wrap">
								<div class="access-control__empty-text">
									{$i18n.t('No organizational units with access')}
								</div>
							</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>

<style>
	.access-control {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-3);
	}

	.access-control__section {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
	}

	.access-control__label {
		font-size: 0.875rem;
		line-height: 1.25rem;
		font-weight: 600;
		color: var(--cloo-text-primary);
	}

	.access-control__visibility-row {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2-5);
	}

	.access-control__visibility-content {
		flex: 1 1 auto;
		min-width: 0;
	}

	.access-control__empty-text {
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
		color: var(--cloo-text-muted);
	}

	.access-control__group-panel {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		padding: var(--cloo-space-2);
		border: 0;
		border-radius: 0;
		background: transparent;
	}

	.access-control__panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.access-control__selector-row {
		margin-top: var(--cloo-space-1);
	}

	.access-control__divider {
		width: 100%;
		margin: var(--cloo-space-2) 0;
		border: 0;
		border-top: 1px solid var(--cloo-border-subtle);
	}

	.access-control__list {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
	}

	.access-control__empty-wrap {
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--cloo-space-2) var(--cloo-space-4);
	}
</style>
