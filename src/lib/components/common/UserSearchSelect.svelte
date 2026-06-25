<script lang="ts">
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { searchUsers, getUserById } from '$lib/apis/users';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	export let selectedUserIds: string[] = [];
	export let excludeUserIds: string[] = [];
	export let excludeAdmins: boolean = true;
	export let maxHeight: string = 'max-h-[22rem]';
	export let searchFirst: boolean = false;

	let selectedUsers: any[] = [];
	let searchResults: any[] = [];
	let query = '';
	let loading = false;
	let initialLoading = true;
	let debounceTimer: ReturnType<typeof setTimeout>;

	// Load selected users' info on mount
	onMount(async () => {
		await loadSelectedUsers();
		initialLoading = false;
	});

	async function loadSelectedUsers() {
		if (selectedUserIds.length === 0) {
			selectedUsers = [];
			return;
		}
		const users: any[] = [];
		for (const uid of selectedUserIds) {
			if (excludeUserIds.includes(uid)) continue;
			try {
				const u = await getUserById(localStorage.token, uid);
				if (u) users.push(u);
			} catch {
				// user may have been deleted
			}
		}
		selectedUsers = users;
	}

	// Keep selectedUsers in sync when selectedUserIds changes externally
	$: {
		const currentIds = new Set(selectedUsers.map((u) => u.id));
		const removed = selectedUsers.filter((u) => !selectedUserIds.includes(u.id));
		if (removed.length > 0) {
			selectedUsers = selectedUsers.filter((u) => selectedUserIds.includes(u.id));
		}
	}

	async function doSearch(q: string) {
		if (!q.trim()) {
			searchResults = [];
			return;
		}
		loading = true;
		try {
			const results = await searchUsers(localStorage.token, q.trim());
			searchResults = results.filter((u: any) => {
				if (excludeAdmins && u?.role === 'admin') return false;
				if (excludeUserIds.includes(u.id)) return false;
				if (selectedUserIds.includes(u.id)) return false;
				return true;
			});
		} catch (e) {
			console.error('Failed to search users:', e);
			searchResults = [];
		}
		loading = false;
	}

	$: {
		// Debounced reactive search when query changes
		clearTimeout(debounceTimer);
		const q = query;
		debounceTimer = setTimeout(() => {
			doSearch(q);
		}, 300);
	}

	function addUser(user: any) {
		selectedUserIds = [...selectedUserIds, user.id];
		selectedUsers = [...selectedUsers, user];
		// Remove from search results
		searchResults = searchResults.filter((u) => u.id !== user.id);
	}

	function removeUser(userId: string) {
		selectedUserIds = selectedUserIds.filter((id) => id !== userId);
		selectedUsers = selectedUsers.filter((u) => u.id !== userId);
	}
</script>

<div>
	<div class="flex w-full">
		<div class="flex flex-1">
			<div class="self-center mr-3">
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
				class="w-full text-sm pr-4 rounded-r-xl outline-hidden bg-transparent dark:text-white"
				bind:value={query}
				placeholder={$i18n.t('Search')}
			/>
		</div>
	</div>

	<div class="mt-3 {maxHeight} overflow-y-auto scrollbar-hidden">
		<div class="flex flex-col gap-2.5">
			{#if initialLoading}
				<div class="flex justify-center py-4">
					<Spinner className="size-4" />
				</div>
			{:else}
				<!-- Selected users always shown at top -->
				{#each selectedUsers as user (user.id)}
					<div class="flex flex-row items-center gap-3 w-full text-sm">
						<div class="flex items-center">
							<Checkbox
								state="checked"
								on:change={() => {
									removeUser(user.id);
								}}
							/>
						</div>
						<div class="flex w-full items-center justify-between">
							<Tooltip content={user.email} placement="top-start">
								<div class="flex items-center">
									<img
										class="rounded-full size-5 object-cover mr-2.5"
										src={user.profile_image_url.startsWith(WEBUI_BASE_URL) ||
										user.profile_image_url.startsWith('https://www.gravatar.com/avatar/') ||
										user.profile_image_url.startsWith('data:')
											? user.profile_image_url
											: `/user.png`}
										alt="user"
									/>
									<div class="font-medium self-center dark:text-white">{user.name}</div>
								</div>
							</Tooltip>
						</div>
					</div>
				{/each}

				<!-- Search results -->
				{#if loading}
					<div class="flex justify-center py-2">
						<Spinner className="size-4" />
					</div>
				{:else if searchFirst && query === ''}
					{#if selectedUsers.length === 0}
						<div class="text-gray-500 text-xs text-center py-2 px-10">
							{$i18n.t('Search for users to share with')}
						</div>
					{/if}
				{:else if searchResults.length > 0}
					{#each searchResults as user (user.id)}
						<div class="flex flex-row items-center gap-3 w-full text-sm">
							<div class="flex items-center">
								<Checkbox
									state="unchecked"
									on:change={() => {
										addUser(user);
									}}
								/>
							</div>
							<div class="flex w-full items-center justify-between">
								<Tooltip content={user.email} placement="top-start">
									<div class="flex items-center">
										<img
											class="rounded-full size-5 object-cover mr-2.5"
											src={user.profile_image_url.startsWith(WEBUI_BASE_URL) ||
											user.profile_image_url.startsWith('https://www.gravatar.com/avatar/') ||
											user.profile_image_url.startsWith('data:')
												? user.profile_image_url
												: `/user.png`}
											alt="user"
										/>
										<div class="font-medium self-center dark:text-white">{user.name}</div>
									</div>
								</Tooltip>
							</div>
						</div>
					{/each}
				{:else if query !== ''}
					<div class="text-gray-500 text-xs text-center py-2 px-10">
						{$i18n.t('No users were found.')}
					</div>
				{/if}
			{/if}
		</div>
	</div>
</div>
