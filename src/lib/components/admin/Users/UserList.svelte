<script>
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { WEBUI_NAME, config, user, showSidebar } from '$lib/stores';
	import { goto } from '$app/navigation';
	import { onMount, getContext } from 'svelte';

	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	import localizedFormat from 'dayjs/plugin/localizedFormat';
	dayjs.extend(relativeTime);
	dayjs.extend(localizedFormat);

	import { toast } from 'svelte-sonner';

	import { updateUserRole, getUsers, deleteUserById } from '$lib/apis/users';
	import { getAdminDetails } from '$lib/apis/auths';

	import Pagination from '$lib/components/common/Pagination.svelte';
	import ChatBubbles from '$lib/components/icons/ChatBubbles.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	import EditUserModal from '$lib/components/admin/Users/UserList/EditUserModal.svelte';
	import UserChatsModal from '$lib/components/admin/Users/UserList/UserChatsModal.svelte';
	import AddUserModal from '$lib/components/admin/Users/UserList/AddUserModal.svelte';

	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import About from '$lib/components/chat/Settings/About.svelte';
	import Banner from '$lib/components/common/Banner.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	const i18n = getContext('i18n');

	export let users = [];

	let superAdminEmail = '';
	let search = '';
	let selectedUser = null;

	let page = 1;

	let showDeleteConfirmDialog = false;
	let showAddUserModal = false;

	let showUserChatsModal = false;
	let showEditUserModal = false;
	let refreshing = false;

	const refreshUsersHandler = async () => {
		if (refreshing) return;
		refreshing = true;
		try {
			users = await getUsers(localStorage.token);
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			refreshing = false;
		}
	};

	const updateRoleHandler = async (id, role) => {
		const res = await updateUserRole(localStorage.token, id, role).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			users = await getUsers(localStorage.token);
		}
	};

	const deleteUserHandler = async (id) => {
		const res = await deleteUserById(localStorage.token, id).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});
		if (res) {
			users = await getUsers(localStorage.token);
		}
	};

	let sortKey = 'created_at'; // default sort key
	let sortOrder = 'asc'; // default sort order

	function setSortKey(key) {
		if (sortKey === key) {
			sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
		} else {
			sortKey = key;
			sortOrder = 'asc';
		}
	}

	let filteredUsers;
	let filteredCount = 0;

	// 검색어 변경 시 페이지를 1로 리셋
	$: if (search !== undefined) {
		page = 1;
	}

	onMount(async () => {
		const details = await getAdminDetails(localStorage.token).catch(() => null);
		superAdminEmail = details?.email ?? '';
	});

	$: {
		const sorted = users
			.filter((user) => {
				if (search === '') {
					return true;
				} else {
					let name = user.name.toLowerCase();
					let email = user.email.toLowerCase();
					const query = search.toLowerCase();
					return name.includes(query) || email.includes(query);
				}
			})
			.sort((a, b) => {
				if (a[sortKey] < b[sortKey]) return sortOrder === 'asc' ? -1 : 1;
				if (a[sortKey] > b[sortKey]) return sortOrder === 'asc' ? 1 : -1;
				return 0;
			});
		filteredCount = sorted.length;
		filteredUsers = sorted.slice((page - 1) * 20, page * 20);
	}
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		deleteUserHandler(selectedUser.id);
	}}
/>

{#key selectedUser}
	<EditUserModal
		bind:show={showEditUserModal}
		{selectedUser}
		sessionUser={$user}
		{superAdminEmail}
		on:setSuperAdmin={(e) => {
			superAdminEmail = e.detail;
		}}
		on:save={async () => {
			users = await getUsers(localStorage.token);
		}}
	/>
{/key}

<AddUserModal
	bind:show={showAddUserModal}
	on:save={async () => {
		users = await getUsers(localStorage.token);
	}}
/>
<UserChatsModal bind:show={showUserChatsModal} user={selectedUser} />

{#if ($config?.license_metadata?.seats ?? null) !== null && users.length > $config?.license_metadata?.seats}
	<div class=" mt-1 mb-2 text-xs text-red-500">
		<Banner
			className="mx-0"
			banner={{
				type: 'error',
				title: 'License Error',
				content:
					'Exceeded the number of seats in your license. Please contact support to increase the number of seats.',
				dismissable: true
			}}
		/>
	</div>
{/if}

<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
	<div class="flex md:self-center text-lg font-medium px-0.5">
		<div class="flex-shrink-0">
			{$i18n.t('Users')}
		</div>
		<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />

		{#if ($config?.license_metadata?.seats ?? null) !== null}
			{#if users.length > $config?.license_metadata?.seats}
				<span class="text-lg font-medium text-red-500"
					>{users.length} of {$config?.license_metadata?.seats}
					<span class="text-sm font-normal">available users</span></span
				>
			{:else}
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300"
					>{users.length} of {$config?.license_metadata?.seats}
					<span class="text-sm font-normal">available users</span></span
				>
			{/if}
		{:else}
			<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{users.length}</span>
		{/if}
	</div>

	<div class="flex gap-2 items-center">
		<div class="flex-1 min-w-[200px]">
			<Input
				bind:value={search}
				placeholder={$i18n.t('Search')}
				size="sm"
			>
				<svelte:fragment slot="prefix">
					<Search className="size-4" />
				</svelte:fragment>
			</Input>
		</div>

		<Tooltip content={$i18n.t('Refresh')}>
			<Button
				kind="text"
				size="sm"
				type="button"
				ariaLabel={$i18n.t('Refresh')}
				loading={refreshing}
				on:click={refreshUsersHandler}
			>
				<ArrowPath className="size-3.5" />
			</Button>
		</Tooltip>

		<Tooltip content={$i18n.t('Add User')}>
			<Button
				kind="text"
				size="sm"
				type="button"
				on:click={() => {
					showAddUserModal = !showAddUserModal;
				}}
			>
				<Plus className="size-3.5" />
			</Button>
		</Tooltip>
	</div>
</div>

<div
	class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5"
>
	<table
		class="w-full text-sm text-left text-gray-500 dark:text-gray-400 table-auto max-w-full rounded-sm"
	>
		<thead
			class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-850 dark:text-gray-400 -translate-y-0.5"
		>
			<tr class="">
				<th
					scope="col"
					class="px-3 py-1.5 cursor-pointer select-none"
					on:click={() => setSortKey('role')}
				>
					<div class="flex gap-1.5 items-center">
						{$i18n.t('Role')}

						{#if sortKey === 'role'}
							<span class="font-normal"
								>{#if sortOrder === 'asc'}
									<ChevronUp className="size-2" />
								{:else}
									<ChevronDown className="size-2" />
								{/if}
							</span>
						{:else}
							<span class="invisible">
								<ChevronUp className="size-2" />
							</span>
						{/if}
					</div>
				</th>
				<th
					scope="col"
					class="px-3 py-1.5 cursor-pointer select-none"
					on:click={() => setSortKey('name')}
				>
					<div class="flex gap-1.5 items-center">
						{$i18n.t('Name')}

						{#if sortKey === 'name'}
							<span class="font-normal"
								>{#if sortOrder === 'asc'}
									<ChevronUp className="size-2" />
								{:else}
									<ChevronDown className="size-2" />
								{/if}
							</span>
						{:else}
							<span class="invisible">
								<ChevronUp className="size-2" />
							</span>
						{/if}
					</div>
				</th>
				<th
					scope="col"
					class="px-3 py-1.5 cursor-pointer select-none"
					on:click={() => setSortKey('email')}
				>
					<div class="flex gap-1.5 items-center">
						{$i18n.t('Email')}

						{#if sortKey === 'email'}
							<span class="font-normal"
								>{#if sortOrder === 'asc'}
									<ChevronUp className="size-2" />
								{:else}
									<ChevronDown className="size-2" />
								{/if}
							</span>
						{:else}
							<span class="invisible">
								<ChevronUp className="size-2" />
							</span>
						{/if}
					</div>
				</th>

				<th
					scope="col"
					class="px-3 py-1.5 cursor-pointer select-none"
					on:click={() => setSortKey('last_active_at')}
				>
					<div class="flex gap-1.5 items-center">
						{$i18n.t('Last Active')}

						{#if sortKey === 'last_active_at'}
							<span class="font-normal"
								>{#if sortOrder === 'asc'}
									<ChevronUp className="size-2" />
								{:else}
									<ChevronDown className="size-2" />
								{/if}
							</span>
						{:else}
							<span class="invisible">
								<ChevronUp className="size-2" />
							</span>
						{/if}
					</div>
				</th>
				<th
					scope="col"
					class="px-3 py-1.5 cursor-pointer select-none"
					on:click={() => setSortKey('created_at')}
				>
					<div class="flex gap-1.5 items-center">
						{$i18n.t('Created at')}
						{#if sortKey === 'created_at'}
							<span class="font-normal"
								>{#if sortOrder === 'asc'}
									<ChevronUp className="size-2" />
								{:else}
									<ChevronDown className="size-2" />
								{/if}
							</span>
						{:else}
							<span class="invisible">
								<ChevronUp className="size-2" />
							</span>
						{/if}
					</div>
				</th>

				<th
					scope="col"
					class="px-3 py-1.5 cursor-pointer select-none"
					on:click={() => setSortKey('oauth_sub')}
				>
					<div class="flex gap-1.5 items-center">
						{$i18n.t('OAuth ID')}

						{#if sortKey === 'oauth_sub'}
							<span class="font-normal"
								>{#if sortOrder === 'asc'}
									<ChevronUp className="size-2" />
								{:else}
									<ChevronDown className="size-2" />
								{/if}
							</span>
						{:else}
							<span class="invisible">
								<ChevronUp className="size-2" />
							</span>
						{/if}
					</div>
				</th>

				<th scope="col" class="px-3 py-2 text-right" />
			</tr>
		</thead>
		<tbody class="">
			{#each filteredUsers as user, userIdx}
				<tr class="bg-white dark:bg-gray-900 dark:border-gray-850 text-xs">
					<td class="px-3 py-1 min-w-[7rem] w-28">
						<div class="flex items-center gap-1 translate-y-0.5">
							<button
								on:click={() => {
									if (user.role === 'user') {
										updateRoleHandler(user.id, 'admin');
									} else if (user.role === 'pending') {
										updateRoleHandler(user.id, 'user');
									} else {
										updateRoleHandler(user.id, 'pending');
									}
								}}
							>
								<Badge
									type={user.role === 'admin' ? 'info' : user.role === 'user' ? 'success' : 'muted'}
									content={$i18n.t(user.role)}
								/>
							</button>
							{#if superAdminEmail && user.email === superAdminEmail}
								<Badge type="warning" content="SA" />
							{/if}
						</div>
					</td>
					<td class="px-3 py-1 font-medium text-gray-900 dark:text-white w-max">
						<button
							class="flex flex-row w-max cursor-pointer hover:underline"
							on:click={() => {
								showEditUserModal = true;
								selectedUser = user;
							}}
						>
							<img
								class=" rounded-full w-6 h-6 object-cover mr-2.5"
								src={user.profile_image_url.startsWith(WEBUI_BASE_URL) ||
								user.profile_image_url.startsWith('https://www.gravatar.com/avatar/') ||
								user.profile_image_url.startsWith('data:')
									? user.profile_image_url
									: `/user.png`}
								alt="user"
							/>

							<div class=" font-medium self-center">{user.name}</div>
						</button>
					</td>
					<td class=" px-3 py-1"> {user.email} </td>

					<td class=" px-3 py-1">
						{dayjs(user.last_active_at * 1000).fromNow()}
					</td>

					<td class=" px-3 py-1">
						{dayjs(user.created_at * 1000).format('LL')}
					</td>

					<td class=" px-3 py-1"> {user.oauth_sub ?? ''} </td>

					<td class="px-3 py-1 text-right">
						<div class="flex justify-end w-full">
							{#if $config.features.enable_admin_chat_access && user.role !== 'admin'}
								<Tooltip content={$i18n.t('Chats')}>
									<Button
										kind="text"
										size="sm"
										type="button"
										on:click={async () => {
											showUserChatsModal = !showUserChatsModal;
											selectedUser = user;
										}}
									>
										<ChatBubbles />
									</Button>
								</Tooltip>
							{/if}

							{#if user.role !== 'admin'}
								<Tooltip content={$i18n.t('Delete User')}>
									<Button
										kind="text"
										size="sm"
										status="error"
										type="button"
										on:click={async () => {
											showDeleteConfirmDialog = true;
											selectedUser = user;
										}}
									>
										<GarbageBin className="size-4" />
									</Button>
								</Tooltip>
							{/if}
						</div>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<div class=" text-gray-500 text-xs mt-1.5 text-right">
	ⓘ {$i18n.t("Click on the user role button to change a user's role.")}
</div>

<Pagination bind:page count={filteredCount} />

