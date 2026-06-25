<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import { createEventDispatcher } from 'svelte';
	import { onMount, getContext } from 'svelte';

	import { updateUserById, getUserOrganizationalUnits } from '$lib/apis/users';
	import { setSuperAdmin } from '$lib/apis/auths';
	import { getGroups, updateGroupById } from '$lib/apis/groups';

	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Tabs, { type TabItem } from '$lib/components/common/Tabs.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import UserUsageTab from './UserUsageTab.svelte';
	import localizedFormat from 'dayjs/plugin/localizedFormat';
	import { config } from '$lib/stores';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();
	dayjs.extend(localizedFormat);

	export let show = false;
	export let selectedUser;
	export let sessionUser;
	export let superAdminEmail = '';

	let _user = {
		profile_image_url: '',
		name: '',
		email: '',
		password: '',
		role: 'user'
	};

	let allGroups: any[] = [];
	let userGroupIds: Set<string> = new Set();

	let groupsExpanded = false;
	let showSetSuperAdminConfirm = false;
	type EditUserTab = 'info' | 'usage';
	let activeTab: EditUserTab = 'info';

	const confirmSetSuperAdmin = async () => {
		const res = await setSuperAdmin(localStorage.token, _user.email).catch((e) => {
			toast.error(e ?? $i18n.t('An error occurred'));
			return null;
		});
		if (res) {
			toast.success($i18n.t('Super admin set to {{email}}', { email: _user.email }));
			dispatch('setSuperAdmin', _user.email);
			show = false;
		}
	};

	$: if (!show) {
		activeTab = 'info';
	}

	$: roleOptions = [
		{ value: 'pending', label: $i18n.t('pending') },
		{ value: 'user', label: $i18n.t('user') },
		{ value: 'admin', label: $i18n.t('admin') }
	];

	$: tabItems = [
		{
			id: 'info',
			labelKey: 'Information',
			href: '#info',
			state: activeTab === 'info' ? 'selected' : 'default'
		},
		{
			id: 'usage',
			labelKey: 'Usage',
			href: '#usage',
			state: activeTab === 'usage' ? 'selected' : 'default'
		}
	] satisfies TabItem[];

	const handleTabClick = (event: MouseEvent) => {
		const anchor = (event.target as HTMLElement | null)?.closest('a');
		if (!anchor) return;
		event.preventDefault();
		const href = anchor.getAttribute('href') ?? '';
		if (href === '#info') activeTab = 'info';
		else if (href === '#usage') activeTab = 'usage';
	};

	$: userOrgUnitIdSet = new Set(userOrgUnits.map((u) => u.id));
	$: groupIdsViaOrgUnit = new Set(
		allGroups
			.filter((g) => {
				const ouIds: string[] = g?.meta?.org_unit_ids ?? [];
				return ouIds.some((id) => userOrgUnitIdSet.has(id));
			})
			.map((g) => g.id)
	);

	$: sortedGroups = [...allGroups].sort((a, b) => {
		const rank = (g: any) =>
			userGroupIds.has(g.id) ? 0 : groupIdsViaOrgUnit.has(g.id) ? 1 : 2;
		const ra = rank(a);
		const rb = rank(b);
		if (ra !== rb) return ra - rb;
		return (a.name ?? '').localeCompare(b.name ?? '');
	});

	let userOrgUnits: Array<{
		id: string;
		name: string;
		display_name?: string | null;
		type?: string | null;
		level: number;
		organization_name?: string | null;
	}> = [];

	const submitHandler = async () => {
		const res = await updateUserById(localStorage.token, selectedUser.id, _user).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});

		if (res) {
			for (const group of allGroups) {
				const wasMember = group.user_ids.includes(selectedUser.id);
				const isMember = userGroupIds.has(group.id);

				if (wasMember !== isMember) {
					const newUserIds = isMember
						? [...group.user_ids, selectedUser.id]
						: group.user_ids.filter((id: string) => id !== selectedUser.id);

					await updateGroupById(localStorage.token, group.id, {
						...group,
						user_ids: newUserIds
					}).catch((error) => {
						toast.error($i18n.t(`${error}`));
					});
				}
			}

			toast.success($i18n.t('User updated successfully'));
			dispatch('save');
			show = false;
		}
	};

	onMount(async () => {
		if (selectedUser) {
			_user = { ...selectedUser, password: '' };

			allGroups = (await getGroups(localStorage.token).catch(() => [])) ?? [];
			userGroupIds = new Set(
				allGroups.filter((g) => g.user_ids.includes(selectedUser.id)).map((g) => g.id)
			);

			userOrgUnits =
				(await getUserOrganizationalUnits(localStorage.token, selectedUser.id).catch(
					() => []
				)) ?? [];
		}
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 py-4">
			<div class=" text-lg font-medium self-center">{$i18n.t('Edit User')}</div>
			<Button
				kind="text"
				size="sm"
				type="button"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-5" />
			</Button>
		</div>
		<hr class="border-gray-100 dark:border-gray-850" />

		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div class="px-5 pt-3" on:click={handleTabClick}>
			<Tabs items={tabItems} />
		</div>

		{#if activeTab === 'usage'}
			<div class="px-5 py-4 dark:text-gray-200">
				<UserUsageTab userId={selectedUser?.id ?? ''} />
			</div>
		{:else}
		<div class="flex flex-col md:flex-row w-full p-5 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					<div class=" flex items-center rounded-md py-2 px-4 w-full">
						<div class=" self-center mr-5">
							<img
								src={_user.profile_image_url || selectedUser.profile_image_url}
								class=" max-w-[55px] object-cover rounded-full"
								alt="User profile"
							/>
						</div>

						<div>
							<div class=" self-center capitalize font-semibold">{selectedUser.name}</div>

							<div class="text-xs text-gray-500">
								{$i18n.t('Created at')}
								{dayjs(selectedUser.created_at * 1000).format('LL')}
							</div>
						</div>
					</div>

					<div class="w-full px-4 mb-1">
						<Input
							bind:value={_user.profile_image_url}
							label={$i18n.t('Profile Image URL')}
							placeholder="https://example.com/avatar.png"
							size="md"
							autocomplete="off"
						/>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-3 w-full" />

					<div class=" flex flex-col gap-2.5">
						<Input
							bind:value={_user.email}
							label={$config?.features?.enable_email_deidentify
								? $i18n.t('Account ID')
								: $i18n.t('Email')}
							type={$config?.features?.enable_email_deidentify ? 'text' : 'email'}
							size="md"
							autocomplete="off"
							required
							disabled={_user.id == sessionUser.id}
						/>

						<Input
							bind:value={_user.name}
							label={$i18n.t('Name')}
							size="md"
							autocomplete="off"
							required
						/>

						<div class="flex flex-col w-full">
							<div class="mb-1 text-xs leading-4 font-medium text-[var(--cloo-text-primary)]">
								{$i18n.t('Role')}
							</div>
							<Selector
								value={_user.role}
								items={roleOptions}
								size="md"
								searchEnabled={false}
								disabled={selectedUser.id === sessionUser.id}
								on:change={(e) => {
									_user.role = e.detail.value;
								}}
							/>
						</div>

						<Input
							bind:value={_user.password}
							label={$i18n.t('New Password')}
							type="password"
							size="md"
							autocomplete="new-password"
						/>
					</div>

					<!-- 사용자별 토큰 한도는 [관리자 > 설정 > 모델] accordion 의 "사용자 오버라이드" 에서 관리 -->

					{#if userOrgUnits.length > 0}
						<hr class="border-gray-100 dark:border-gray-850 my-3 w-full" />

						<div class="flex flex-col w-full">
							<div class="mb-1.5 text-xs text-gray-500">
								{$i18n.t('Organizational Units')}
							</div>
							<div class="flex flex-wrap gap-1.5">
								{#each userOrgUnits as unit (unit.id)}
									<Tooltip
										content={unit.organization_name ?? ''}
										placement="top"
									>
										<span
											class="px-2.5 py-1 text-xs rounded-lg bg-blue-600/10 text-blue-700 dark:text-blue-400 ring-1 ring-blue-600/30 font-medium"
										>
											{unit.display_name || unit.name}
											{#if unit.type}
												<span class="ml-1 text-[10px] opacity-70">({unit.type})</span>
											{/if}
										</span>
									</Tooltip>
								{/each}
							</div>
						</div>
					{/if}

					{#if allGroups.length > 0}
						<hr class="border-gray-100 dark:border-gray-850 my-3 w-full" />

						<div class="flex flex-col w-full">
							<button
								type="button"
								class="flex items-center justify-between w-full mb-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
								on:click={() => (groupsExpanded = !groupsExpanded)}
							>
								<span>
									{$i18n.t('Groups')}
									<span class="ml-1 text-gray-400 dark:text-gray-600">
										({new Set([...userGroupIds, ...groupIdsViaOrgUnit]).size}/{allGroups.length})
									</span>
								</span>
								{#if groupsExpanded}
									<ChevronUp className="size-3" strokeWidth="2.5" />
								{:else}
									<ChevronDown className="size-3" strokeWidth="2.5" />
								{/if}
							</button>

							{#if groupsExpanded}
								<div class="flex flex-wrap gap-1.5">
									{#each sortedGroups as group (group.id)}
										{@const isDirect = userGroupIds.has(group.id)}
										{@const isViaOrg = groupIdsViaOrgUnit.has(group.id)}
										{@const orgOnly = isViaOrg && !isDirect}
										<Tooltip
											content={orgOnly ? $i18n.t('Member via organizational unit') : ''}
											placement="top"
										>
											<button
												type="button"
												disabled={orgOnly}
												class="px-2.5 py-1 text-xs rounded-lg transition font-medium
													{isDirect
													? 'bg-emerald-600/15 text-emerald-700 dark:text-emerald-400 ring-1 ring-emerald-600/30'
													: orgOnly
														? 'bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500 ring-1 ring-gray-300 dark:ring-gray-700 opacity-70 cursor-not-allowed'
														: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'}"
												on:click={() => {
													if (orgOnly) return;
													if (userGroupIds.has(group.id)) {
														userGroupIds.delete(group.id);
													} else {
														userGroupIds.add(group.id);
													}
													userGroupIds = userGroupIds;
												}}
											>
												{group.name}
											</button>
										</Tooltip>
									{/each}
								</div>
							{/if}
						</div>
					{/if}

					<div class="flex justify-between pt-3 text-sm font-medium">
						{#if _user.role === 'admin'}
							<Tooltip
								content={$i18n.t('Sets the contact admin shown on the account activation pending screen')}
								placement="top"
							>
								<button
									class="px-4 py-2 transition rounded-lg text-white
										{superAdminEmail && _user.email === superAdminEmail
										? 'bg-yellow-400 cursor-not-allowed opacity-60'
										: 'bg-yellow-600 hover:bg-yellow-700'}"
									type="button"
									disabled={superAdminEmail !== '' && _user.email === superAdminEmail}
									on:click={() => {
										showSetSuperAdminConfirm = true;
									}}
								>
									{$i18n.t('Set as SA')}
								</button>
							</Tooltip>
						{:else}
							<div />
						{/if}

						<Button kind="filled" size="md" type="submit">
							{$i18n.t('Save')}
						</Button>
					</div>
				</form>
			</div>
		</div>
		{/if}
	</div>
</Modal>

<ConfirmDialog
	bind:show={showSetSuperAdminConfirm}
	title={$i18n.t('Set as Super Admin?')}
	message={$i18n.t(
		'{{email}} will become the Super Admin shown on the account activation pending screen.',
		{ email: _user.email }
	)}
	confirmLabel={$i18n.t('Set as SA')}
	cancelLabel={$i18n.t('Cancel')}
	onConfirm={confirmSetSuperAdmin}
/>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		/* display: none; <- Crashes Chrome on hover */
		-webkit-appearance: none;
		margin: 0; /* <-- Apparently some margin are still there even though it's hidden */
	}

	.tabs::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.tabs {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	input[type='number'] {
		-moz-appearance: textfield; /* Firefox */
	}
</style>
