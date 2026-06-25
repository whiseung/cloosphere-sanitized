<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Tabs, { type TabItem } from '$lib/components/common/Tabs.svelte';
	import TokenInput from '$lib/components/common/TokenInput.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import {
		listModelUsageLimitOverrides,
		type OverrideEntry
	} from '$lib/apis/models';
	import { searchUsers, updateUserUsageLimit, getUserUsageLimit } from '$lib/apis/users';
	import {
		getGroups,
		getGroupUsageLimit,
		updateGroupUsageLimit
	} from '$lib/apis/groups';
	import {
		getOrganizationalUnits,
		getOrgUnitUsageLimit,
		updateOrgUnitUsageLimit
	} from '$lib/apis/organizations';

	export let show = false;
	export let modelId: string = '';
	export let tier: 'users' | 'groups' | 'org_units' = 'users';

	let loading = false;
	let entries: OverrideEntry[] = [];
	let query = '';

	// add picker state — 다중 선택 지원
	let pickerQuery = '';
	let pickerCandidates: { id: string; name: string }[] = [];
	let pickerLoading = false;
	let pickerSelectedIds = new Set<string>();
	let pickerTokens = 0;

	$: pickerSelectedCount = pickerSelectedIds.size;
	$: visibleAllSelected =
		pickerCandidates.length > 0 &&
		pickerCandidates.every((c) => pickerSelectedIds.has(c.id));

	$: if (show && modelId && tier) {
		void init();
	}
	$: if (!show) {
		entries = [];
		query = '';
		pickerQuery = '';
		pickerCandidates = [];
		pickerSelectedIds = new Set();
		pickerTokens = 0;
	}

	const togglePickerCandidate = (id: string) => {
		if (pickerSelectedIds.has(id)) pickerSelectedIds.delete(id);
		else pickerSelectedIds.add(id);
		pickerSelectedIds = new Set(pickerSelectedIds); // trigger reactivity
	};

	const toggleAllVisible = () => {
		if (visibleAllSelected) {
			pickerCandidates.forEach((c) => pickerSelectedIds.delete(c.id));
		} else {
			pickerCandidates.forEach((c) => pickerSelectedIds.add(c.id));
		}
		pickerSelectedIds = new Set(pickerSelectedIds);
	};

	const removeSelectedId = (id: string) => {
		pickerSelectedIds.delete(id);
		pickerSelectedIds = new Set(pickerSelectedIds);
	};

	const candidateName = (id: string): string => {
		const fromVisible = pickerCandidates.find((c) => c.id === id);
		if (fromVisible) return fromVisible.name;
		return id;
	};

	const tierLabel = (t: typeof tier): string => {
		if (t === 'users') return $i18n.t('Users');
		if (t === 'groups') return $i18n.t('Groups');
		return $i18n.t('Organizational Units');
	};

	const modalTitle = (t: typeof tier): string => {
		if (t === 'users') return $i18n.t('Per-model user exceptions');
		if (t === 'groups') return $i18n.t('Per-model group exceptions');
		return $i18n.t('Per-model org-unit exceptions');
	};

	const addSectionTitle = (t: typeof tier): string => {
		if (t === 'users') return $i18n.t('Add user exception');
		if (t === 'groups') return $i18n.t('Add group exception');
		return $i18n.t('Add org-unit exception');
	};

	const switchTier = (next: typeof tier) => {
		if (next === tier) return;
		tier = next;
		// reset picker state on tier switch
		query = '';
		pickerQuery = '';
		pickerCandidates = [];
		pickerSelectedIds = new Set();
		pickerTokens = 0;
	};

	const TIER_HREF: Record<typeof tier, string> = {
		users: '#tier-users',
		groups: '#tier-groups',
		org_units: '#tier-org-units'
	};
	const HREF_TO_TIER: Record<string, typeof tier> = {
		'#tier-users': 'users',
		'#tier-groups': 'groups',
		'#tier-org-units': 'org_units'
	};

	$: tierTabItems = [
		{
			id: 'users',
			labelKey: 'Users',
			href: TIER_HREF.users,
			state: tier === 'users' ? 'selected' : 'default'
		},
		{
			id: 'groups',
			labelKey: 'Groups',
			href: TIER_HREF.groups,
			state: tier === 'groups' ? 'selected' : 'default'
		},
		{
			id: 'org_units',
			labelKey: 'Organizational Units',
			href: TIER_HREF.org_units,
			state: tier === 'org_units' ? 'selected' : 'default'
		}
	] satisfies TabItem[];

	const handleTierTabClick = (event: MouseEvent) => {
		const anchor = (event.target as HTMLElement | null)?.closest('a');
		if (!anchor) return;
		event.preventDefault();
		const href = anchor.getAttribute('href') ?? '';
		const next = HREF_TO_TIER[href];
		if (next) switchTier(next);
	};

	const init = async () => {
		loading = true;
		try {
			entries = await listModelUsageLimitOverrides(localStorage.token, modelId, tier, query);
		} catch {
			toast.error($i18n.t('Failed to load overrides'));
			entries = [];
		}
		loading = false;
	};

	const reload = async () => {
		await init();
	};

	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	const onSearch = () => {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => void init(), 200);
	};

	// per-tier API helpers
	const readSubject = async (subjectId: string): Promise<Record<string, number>> => {
		if (tier === 'users') {
			const r = await getUserUsageLimit(localStorage.token, subjectId);
			return r?.per_model || {};
		}
		if (tier === 'groups') {
			const r = await getGroupUsageLimit(localStorage.token, subjectId);
			return r?.per_model || {};
		}
		const r = await getOrgUnitUsageLimit(localStorage.token, subjectId);
		return r?.per_model || {};
	};

	const writeSubject = async (subjectId: string, perModel: Record<string, number>) => {
		if (tier === 'users') {
			await updateUserUsageLimit(localStorage.token, subjectId, perModel);
		} else if (tier === 'groups') {
			await updateGroupUsageLimit(localStorage.token, subjectId, perModel);
		} else {
			await updateOrgUnitUsageLimit(localStorage.token, subjectId, perModel);
		}
	};

	const saveEntry = async (entry: OverrideEntry, newTokens: number) => {
		try {
			const current = await readSubject(entry.id);
			const next = { ...current, [modelId]: Math.max(0, Math.floor(Number(newTokens) || 0)) };
			await writeSubject(entry.id, next);
			toast.success($i18n.t('Override saved'));
			await reload();
		} catch {
			toast.error($i18n.t('Failed to save override'));
		}
	};

	const deleteEntry = async (entry: OverrideEntry) => {
		try {
			const current = await readSubject(entry.id);
			const next = { ...current };
			delete next[modelId];
			await writeSubject(entry.id, next);
			toast.success($i18n.t('Override removed'));
			await reload();
		} catch {
			toast.error($i18n.t('Failed to remove override'));
		}
	};

	let pickerTimer: ReturnType<typeof setTimeout> | null = null;
	const onPickerSearch = () => {
		if (pickerTimer) clearTimeout(pickerTimer);
		pickerTimer = setTimeout(() => void loadPicker(), 200);
	};

	const loadPicker = async () => {
		pickerLoading = true;
		try {
			const existingIds = new Set(entries.map((e) => e.id));
			if (tier === 'users') {
				const list = (await searchUsers(localStorage.token, pickerQuery, 30)) || [];
				pickerCandidates = list
					.filter((u: any) => !existingIds.has(u.id))
					.map((u: any) => ({ id: u.id, name: u.name || u.email || u.id }));
			} else if (tier === 'groups') {
				const list = (await getGroups(localStorage.token)) || [];
				const q = pickerQuery.toLowerCase();
				pickerCandidates = list
					.filter((g: any) => !existingIds.has(g.id))
					.filter(
						(g: any) =>
							!q ||
							(g.name || '').toLowerCase().includes(q) ||
							(g.id || '').toLowerCase().includes(q)
					)
					.map((g: any) => ({ id: g.id, name: g.name || g.id }));
			} else {
				const list = (await getOrganizationalUnits(localStorage.token)) || [];
				const q = pickerQuery.toLowerCase();
				pickerCandidates = list
					.filter((u: any) => !existingIds.has(u.id))
					.filter(
						(u: any) =>
							!q ||
							(u.display_name || u.name || '').toLowerCase().includes(q) ||
							(u.id || '').toLowerCase().includes(q)
					)
					.map((u: any) => ({
						id: u.id,
						name: u.display_name || u.name || u.id
					}));
			}
		} catch {
			pickerCandidates = [];
		}
		pickerLoading = false;
	};

	const addOverride = async () => {
		if (pickerSelectedIds.size === 0 || !pickerTokens) {
			toast.error($i18n.t('Select a subject and enter a token amount'));
			return;
		}
		const tokens = Math.max(0, Math.floor(Number(pickerTokens) || 0));
		const targetIds = Array.from(pickerSelectedIds);
		let successCount = 0;
		const failed: string[] = [];

		await Promise.all(
			targetIds.map(async (id) => {
				try {
					const current = await readSubject(id);
					const next = { ...current, [modelId]: tokens };
					await writeSubject(id, next);
					successCount += 1;
				} catch {
					failed.push(candidateName(id));
				}
			})
		);

		if (successCount > 0) {
			toast.success(
				$i18n.t('{{count}} exceptions saved', { count: successCount })
			);
		}
		if (failed.length > 0) {
			toast.error(
				$i18n.t('Failed to save {{count}} exceptions', { count: failed.length })
			);
		}
		pickerSelectedIds = new Set();
		pickerTokens = 0;
		pickerQuery = '';
		pickerCandidates = [];
		await reload();
	};
</script>

<Modal size="md" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{modalTitle(tier)}
				<span class="text-sm text-gray-500 dark:text-gray-400 ml-2">{modelId}</span>
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="w-5 h-5" />
			</button>
		</div>

		<div class="px-5 pb-5 dark:text-gray-200 space-y-4">
			<!-- Tier switcher -->
			<!-- svelte-ignore a11y-click-events-have-key-events -->
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div on:click={handleTierTabClick}>
				<Tabs items={tierTabItems} ariaLabel={$i18n.t('Override tier')} />
			</div>

			<!-- Existing overrides -->
			<div class="space-y-2">
				<Input
					bind:value={query}
					size="sm"
					type="search"
					placeholder={$i18n.t('Search overrides...')}
					on:input={onSearch}
				/>

				{#if loading}
					<div class="flex justify-center py-4">
						<Spinner />
					</div>
				{:else if entries.length === 0}
					<div class="text-xs text-gray-500 dark:text-gray-400 py-2">
						{$i18n.t('No overrides set for this model.')}
					</div>
				{:else}
					<div class="max-h-64 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-850">
						{#each entries as entry (entry.id)}
							{@const used = entry.used_today ?? null}
							{@const pct =
								used !== null && entry.tokens > 0
									? Math.min(100, (used / entry.tokens) * 100)
									: 0}
							<div class="flex items-center gap-2 py-2">
								<div class="flex-1 min-w-0">
									<div class="text-sm font-medium truncate">{entry.name}</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 truncate">{entry.id}</div>
									{#if tier === 'users' && used !== null}
										<div class="flex items-center gap-1.5 mt-0.5">
											<div class="w-12 h-1 rounded bg-gray-100 dark:bg-gray-850 overflow-hidden">
												<div
													class="h-full {pct >= 95
														? 'bg-red-500'
														: pct >= 80
															? 'bg-yellow-500'
															: 'bg-blue-500'}"
													style="width: {pct}%"
												></div>
											</div>
											<span class="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
												{$i18n.t("Today's usage")}: {used.toLocaleString()}
												{#if entry.tokens > 0}
													/ {entry.tokens.toLocaleString()} ({Math.round(pct)}%)
												{/if}
											</span>
										</div>
									{/if}
								</div>
								<div class="w-40">
									<TokenInput bind:value={entry.tokens} />
								</div>
								<Button
									kind="filled"
									size="sm"
									on:click={() => void saveEntry(entry, entry.tokens ?? 0)}
								>
									{$i18n.t('Save')}
								</Button>
								<Button
									kind="outlined"
									size="sm"
									on:click={() => void deleteEntry(entry)}
								>
									{$i18n.t('Remove')}
								</Button>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Add new override (다중 선택) -->
			<div class="border-t border-gray-100 dark:border-gray-850 pt-3 space-y-2">
				<div class="text-sm font-medium">{addSectionTitle(tier)}</div>

				<Input
					bind:value={pickerQuery}
					size="sm"
					type="search"
					placeholder={$i18n.t('Search to add...')}
					on:input={onPickerSearch}
				/>

				{#if pickerLoading}
					<div class="flex justify-center py-2">
						<Spinner />
					</div>
				{:else if pickerCandidates.length > 0}
					<div class="border border-gray-100 dark:border-gray-850 rounded-md overflow-hidden">
						<div
							class="flex items-center gap-2 px-3 py-1.5 text-xs bg-gray-50 dark:bg-gray-850 border-b border-gray-100 dark:border-gray-800"
						>
							<Checkbox
								state={visibleAllSelected ? 'checked' : 'unchecked'}
								on:change={toggleAllVisible}
							/>
							<span class="text-gray-600 dark:text-gray-400">
								{$i18n.t('Select all')} ({pickerCandidates.length})
							</span>
						</div>
						<div class="max-h-40 overflow-y-auto">
							{#each pickerCandidates as cand (cand.id)}
								{@const isSelected = pickerSelectedIds.has(cand.id)}
								<div
									role="button"
									tabindex="0"
									class="w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-850 {isSelected
										? 'bg-gray-100 dark:bg-gray-800'
										: ''}"
									on:click={() => togglePickerCandidate(cand.id)}
									on:keydown={(e) => {
										if (e.key === 'Enter' || e.key === ' ') {
											e.preventDefault();
											togglePickerCandidate(cand.id);
										}
									}}
								>
									<div class="pointer-events-none">
										<Checkbox state={isSelected ? 'checked' : 'unchecked'} />
									</div>
									<div class="min-w-0 flex-1">
										<div class="font-medium truncate">{cand.name}</div>
										<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
											{cand.id}
										</div>
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				{#if pickerSelectedCount > 0}
					<div class="flex flex-wrap gap-1 pt-1">
						{#each Array.from(pickerSelectedIds) as id (id)}
							<span
								class="inline-flex items-center gap-1 text-xs bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-md px-2 py-0.5"
							>
								<span class="truncate max-w-[200px]">{candidateName(id)}</span>
								<button
									type="button"
									class="hover:text-red-500"
									on:click={() => removeSelectedId(id)}
									aria-label={$i18n.t('Remove')}
								>
									<XMark className="w-3 h-3" />
								</button>
							</span>
						{/each}
					</div>

					<div class="flex gap-2 items-center pt-1">
						<div class="text-xs text-gray-500 dark:text-gray-400 flex-shrink-0">
							{$i18n.t('Daily tokens')}
						</div>
						<div class="flex-1">
							<TokenInput bind:value={pickerTokens} />
						</div>
						<Button kind="filled" size="sm" on:click={() => void addOverride()}>
							{$i18n.t('Add ({{count}})', { count: pickerSelectedCount })}
						</Button>
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
