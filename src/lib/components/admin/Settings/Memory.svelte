<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import {
		getRetentionPolicies,
		updateRetentionPolicy,
		getMemoryAuditLogs,
		getOrgMemories,
		createOrgMemory,
		deleteOrgMemory,
		getUserMemories,
		deleteUserMemory,
		getEntityTypes,
		addEntityType,
		deleteEntityType,
		getEntities,
		getMemoryExtractionConfig,
		updateMemoryExtractionConfig
	} from '$lib/apis/admin/memory';
	import { getUsers } from '$lib/apis/users';
	import { models } from '$lib/stores';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let loading = true;

	// ---- Configuration Section ----
	let extractionModel = '';
	let extractionConfidence = 0.8;
	let extractionSaving = false;

	let retentionPolicies: any[] = [];
	let retentionEdits: Record<string, number | null> = {};
	let retentionSaving = false;

	// ---- Management Section ----
	let activeTab: 'audit' | 'users' | 'org' | 'entities' = 'audit';
	let tabDataLoaded: Record<string, boolean> = {};

	// Audit Log
	let auditLogs: any = { items: [], total: 0, page: 1, limit: 20 };
	let auditEventFilter = '';
	let auditUserFilter = '';
	let auditPage = 1;
	let auditLoading = false;
	let auditDebounceTimer: ReturnType<typeof setTimeout> | null = null;

	// User Memories
	let users: any[] = [];
	let selectedUserId = '';
	let userMemories: any[] = [];
	let userMemoriesLoading = false;

	// Organization Memory
	let orgMemories: any[] = [];
	let orgMemoryInput = '';
	let orgError = '';
	let orgLoading = false;

	// Knowledge Entities
	let entityTypes: any[] = [];
	let entityGroups: any[] = [];
	let newEntityTypeName = '';
	let newEntityTypeDesc = '';
	let showAddEntityType = false;

	// Confirm Dialog
	let showConfirm = false;
	let confirmTitle = '';
	let confirmMessage = '';
	let confirmAction: () => void = () => {};

	// ---- Helpers ----
	const formatTimestamp = (ts: number): string => {
		return new Intl.DateTimeFormat(undefined, {
			dateStyle: 'short',
			timeStyle: 'short'
		}).format(new Date(ts * 1000));
	};

	type BadgeStatus = 'default' | 'info' | 'success' | 'warning' | 'danger';

	const eventBadgeStatus = (event: string): BadgeStatus => {
		switch (event) {
			case 'CREATE':
				return 'success';
			case 'UPDATE':
				return 'warning';
			case 'DELETE':
				return 'danger';
			default:
				return 'default';
		}
	};

	const retentionBadgeStatus = (cls: string): BadgeStatus => {
		switch (cls) {
			case 'permanent':
				return 'info';
			case 'temporary':
				return 'warning';
			default:
				return 'default';
		}
	};

	const sourceBadgeStatus = (source: string): BadgeStatus => {
		switch (source) {
			case 'auto':
				return 'success';
			case 'manual':
				return 'info';
			default:
				return 'default';
		}
	};

	const formatAuditDetail = (meta: any): string => {
		if (!meta) return '-';
		const parts: string[] = [];
		if (meta.source) parts.push(`source: ${meta.source}`);
		if (meta.retention_class) parts.push(meta.retention_class);
		if (meta.field) parts.push(`field: ${meta.field}`);
		if (meta.content_length_after) parts.push(`${meta.content_length_after} chars`);
		if (meta.memory_age_days) parts.push(`${meta.memory_age_days}d`);
		if (meta.ttl_days) parts.push(`TTL: ${meta.ttl_days}d`);
		return parts.length > 0 ? parts.join(' \u00b7 ') : JSON.stringify(meta).slice(0, 80);
	};

	const confirmDelete = (title: string, message: string, action: () => void) => {
		confirmTitle = title;
		confirmMessage = message;
		confirmAction = action;
		showConfirm = true;
	};

	// ---- Derived ----
	$: modelItems = [
		{ value: '', label: $i18n.t('(Use Task Model or Chat Model)') },
		...$models
			.filter((m: any) => !m.base_model_id && !m.preset && !(m.arena ?? false))
			.map((m) => ({ value: m.id, label: m.name || m.id }))
	];

	$: userItems = users.map((u) => ({ value: u.id, label: `${u.name} (${u.email})` }));

	$: auditEventItems = [
		{ value: '', label: $i18n.t('All Events') },
		{ value: 'CREATE', label: $i18n.t('CREATE') },
		{ value: 'UPDATE', label: $i18n.t('UPDATE') },
		{ value: 'DELETE', label: $i18n.t('DELETE') },
		{ value: 'SETTINGS_CHANGE', label: $i18n.t('SETTINGS_CHANGE') }
	];

	const managementTabs = [
		{ id: 'audit', labelKey: 'Audit Log' },
		{ id: 'users', labelKey: 'User Memories' },
		{ id: 'org', labelKey: 'Organization Memory' },
		{ id: 'entities', labelKey: 'Knowledge Entities' }
	] as const;

	// ---- Tab Switching ----
	const switchTab = (tabId: typeof activeTab) => {
		activeTab = tabId;
		if (!tabDataLoaded[tabId]) {
			tabDataLoaded[tabId] = true;
			if (tabId === 'audit') loadAuditLogs();
			else if (tabId === 'org') loadOrgMemories();
			else if (tabId === 'entities') loadEntityData();
		}
	};

	// ---- Data Loading ----
	const loadRetentionPolicies = async () => {
		try {
			retentionPolicies = await getRetentionPolicies(localStorage.token);
			retentionEdits = {};
			for (const p of retentionPolicies) {
				retentionEdits[p.id] = p.ttl_days;
			}
		} catch (err) {
			toast.error(err || $i18n.t('Failed to load retention policies'));
		}
	};

	const loadAuditLogs = async () => {
		auditLoading = true;
		try {
			auditLogs = await getMemoryAuditLogs(localStorage.token, {
				event_type: auditEventFilter || undefined,
				user_id: auditUserFilter || undefined,
				page: auditPage,
				limit: 20
			});
		} catch (err) {
			toast.error(err || $i18n.t('Failed to load audit logs'));
		} finally {
			auditLoading = false;
		}
	};

	const loadUsers = async () => {
		try {
			users = await getUsers(localStorage.token);
		} catch (err) {
			// Non-critical
		}
	};

	const loadUserMemories = async () => {
		if (!selectedUserId) {
			userMemories = [];
			return;
		}
		userMemoriesLoading = true;
		try {
			userMemories = await getUserMemories(localStorage.token, selectedUserId);
		} catch (err) {
			toast.error(err || $i18n.t('Failed to load user memories'));
		} finally {
			userMemoriesLoading = false;
		}
	};

	const loadOrgMemories = async () => {
		orgError = '';
		orgLoading = true;
		try {
			orgMemories = await getOrgMemories(localStorage.token);
		} catch (err) {
			orgError = typeof err === 'string' ? err : $i18n.t('User not in any organization');
			orgMemories = [];
		} finally {
			orgLoading = false;
		}
	};

	const loadEntityData = async () => {
		try {
			[entityTypes, entityGroups] = await Promise.all([
				getEntityTypes(localStorage.token),
				getEntities(localStorage.token)
			]);
		} catch (err) {
			toast.error(err || $i18n.t('Failed to load entity data'));
		}
	};

	// ---- Handlers ----
	const saveExtractionConfig = async () => {
		extractionSaving = true;
		try {
			await updateMemoryExtractionConfig(localStorage.token, {
				MEMORY_EXTRACTION_MODEL: extractionModel,
				MEMORY_EXTRACTION_CONFIDENCE: extractionConfidence
			});
			toast.success($i18n.t('Extraction config saved'));
		} catch (err) {
			toast.error(err || $i18n.t('Failed to save extraction config'));
		} finally {
			extractionSaving = false;
		}
	};

	const saveRetentionPolicies = async () => {
		retentionSaving = true;
		try {
			for (const p of retentionPolicies) {
				if (p.retention_class === 'permanent') continue;
				const newTtl = retentionEdits[p.id];
				if (newTtl !== p.ttl_days) {
					await updateRetentionPolicy(localStorage.token, p.id, newTtl);
				}
			}
			toast.success($i18n.t('Retention policies saved'));
			await loadRetentionPolicies();
		} catch (err) {
			toast.error(err || $i18n.t('Failed to save retention policies'));
		} finally {
			retentionSaving = false;
		}
	};

	const handleAuditEventFilterChange = () => {
		auditPage = 1;
		loadAuditLogs();
	};

	const handleAuditUserFilterInput = () => {
		if (auditDebounceTimer) clearTimeout(auditDebounceTimer);
		auditDebounceTimer = setTimeout(() => {
			auditPage = 1;
			loadAuditLogs();
		}, 500);
	};

	const handleDeleteUserMemory = async (memoryId: string) => {
		if (!selectedUserId) return;
		try {
			await deleteUserMemory(localStorage.token, selectedUserId, memoryId);
			toast.success($i18n.t('Memory deleted'));
			await loadUserMemories();
		} catch (err) {
			toast.error(err || $i18n.t('Failed to delete memory'));
		}
	};

	const handleAddOrgMemory = async () => {
		if (!orgMemoryInput.trim()) return;
		try {
			await createOrgMemory(localStorage.token, orgMemoryInput.trim());
			orgMemoryInput = '';
			toast.success($i18n.t('Organization memory added'));
			await loadOrgMemories();
		} catch (err) {
			toast.error(err || $i18n.t('Failed to add organization memory'));
		}
	};

	const handleDeleteOrgMemory = async (id: string) => {
		try {
			await deleteOrgMemory(localStorage.token, id);
			toast.success($i18n.t('Organization memory deleted'));
			await loadOrgMemories();
		} catch (err) {
			toast.error(err || $i18n.t('Failed to delete organization memory'));
		}
	};

	const handleAddEntityType = async () => {
		if (!newEntityTypeName.trim()) return;
		try {
			await addEntityType(
				localStorage.token,
				newEntityTypeName.trim(),
				newEntityTypeDesc.trim() || undefined
			);
			newEntityTypeName = '';
			newEntityTypeDesc = '';
			showAddEntityType = false;
			toast.success($i18n.t('Entity type added'));
			await loadEntityData();
		} catch (err) {
			toast.error(err || $i18n.t('Failed to add entity type'));
		}
	};

	const handleDeleteEntityType = async (id: string) => {
		try {
			await deleteEntityType(localStorage.token, id);
			toast.success($i18n.t('Entity type deleted'));
			await loadEntityData();
		} catch (err) {
			toast.error(err || $i18n.t('Failed to delete entity type'));
		}
	};

	const loadExtractionConfig = async () => {
		try {
			const config = await getMemoryExtractionConfig(localStorage.token);
			if (config) {
				extractionModel = config.MEMORY_EXTRACTION_MODEL || '';
				extractionConfidence = config.MEMORY_EXTRACTION_CONFIDENCE ?? 0.8;
			}
		} catch (err) {
			// Non-critical
		}
	};

	onMount(async () => {
		await Promise.all([loadRetentionPolicies(), loadUsers(), loadExtractionConfig()]);
		// Load default tab data
		tabDataLoaded['audit'] = true;
		loadAuditLogs();
		loading = false;
	});
</script>

<ConfirmDialog
	bind:show={showConfirm}
	title={confirmTitle}
	message={confirmMessage}
	onConfirm={confirmAction}
/>

{#if loading}
	<div class="flex justify-center py-8">
		<Spinner />
	</div>
{:else}
	<div class="flex flex-col h-full text-sm">
		<div class="overflow-y-scroll scrollbar-hidden h-full space-y-5">
			<!-- ================================================================ -->
			<!-- CONFIGURATION — always visible, 2-column grid                     -->
			<!-- ================================================================ -->
			<section>
				<h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">
					{$i18n.t('Configuration')}
				</h3>

				<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
					<!-- Left: Extraction Config -->
					<div class="p-3 rounded-lg border border-gray-100 dark:border-gray-850 space-y-3">
						<div class="text-sm font-medium mb-1">{$i18n.t('Extraction Model')}</div>

						<div>
							<LabelBase
								label={$i18n.t('Model for memory extraction')}
								caption={$i18n.t('Fallback: Extraction Model → Task Model → Chat Model')}
								size="md"
							/>
							<Selector
								value={extractionModel}
								items={modelItems}
								size="sm"
								on:change={(e) => {
									extractionModel = e.detail.value;
								}}
							/>
						</div>

						<div>
							<LabelBase
								label={$i18n.t('Confidence Threshold')}
								caption={$i18n.t('Facts below this confidence will be filtered out (default: 0.8)')}
								size="md"
							/>
							<div class="flex items-center gap-3">
								<input
									id="confidence-range"
									type="range"
									min="0"
									max="1"
									step="0.05"
									value={extractionConfidence}
									on:input={(e) => {
										const target = e.target;
										if (target instanceof HTMLInputElement)
											extractionConfidence = parseFloat(target.value);
									}}
									class="flex-1 h-1.5 rounded-full appearance-none cursor-pointer accent-black dark:accent-white bg-gray-200 dark:bg-gray-700"
								/>
								<span class="text-sm font-mono w-10 text-right tabular-nums text-gray-600 dark:text-gray-400">
									{extractionConfidence.toFixed(2)}
								</span>
							</div>
						</div>

						<div class="flex justify-end">
							<Button kind="filled" size="sm" loading={extractionSaving} on:click={saveExtractionConfig}>
								{$i18n.t('Save')}
							</Button>
						</div>
					</div>

					<!-- Right: Retention Policies -->
					<div class="p-3 rounded-lg border border-gray-100 dark:border-gray-850 space-y-3">
						<div class="text-sm font-medium mb-1">{$i18n.t('Retention Policies')}</div>

						<p class="text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'Configure TTL (time-to-live) for each memory retention class. Permanent class cannot be modified.'
							)}
						</p>

						{#each retentionPolicies as policy}
							<div class="flex w-full items-center justify-between gap-3">
								<div class="flex flex-col min-w-0">
									<Badge status={retentionBadgeStatus(policy.retention_class)} size="sm">
										{$i18n.t(policy.retention_class)}
									</Badge>
									<span class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
										{$i18n.t('On expire')}: {$i18n.t(policy.on_expire)}
									</span>
								</div>
								<div class="flex items-center gap-1.5 shrink-0">
									{#if policy.retention_class === 'permanent'}
										<span class="text-xs text-gray-400 dark:text-gray-500 italic">
											{$i18n.t('Indefinite')}
										</span>
									{:else}
										<input
											type="number"
											min="1"
											aria-label="{$i18n.t(policy.retention_class)} TTL"
											class="w-16 sm:w-20 text-right rounded-lg py-1.5 px-2 text-sm tabular-nums bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-none focus-visible:ring-2 focus-visible:ring-black dark:focus-visible:ring-white"
											bind:value={retentionEdits[policy.id]}
											placeholder="30"
										/>
										<span class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap">
											{$i18n.t('days')}
										</span>
									{/if}
								</div>
							</div>
						{/each}

						<div class="flex justify-end">
							<Button kind="filled" size="sm" loading={retentionSaving} on:click={saveRetentionPolicies}>
								{$i18n.t('Save Policies')}
							</Button>
						</div>
					</div>
				</div>
			</section>

			<!-- ================================================================ -->
			<!-- MANAGEMENT — tab-based switching                                  -->
			<!-- ================================================================ -->
			<section>
				<h3 class="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-3">
					{$i18n.t('Management')}
				</h3>

				<!-- Tab bar -->
				<div class="flex gap-1.5 mb-4" role="tablist" aria-label={$i18n.t('Memory management')}>
					{#each managementTabs as tab}
						<button
							type="button"
							role="tab"
							aria-selected={activeTab === tab.id}
							class="px-3 py-1.5 text-xs font-medium rounded-full border transition-colors
								{activeTab === tab.id
								? 'border-black bg-black text-white dark:border-white dark:bg-white dark:text-black'
								: 'border-gray-200 dark:border-gray-700 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800'}"
							on:click={() => switchTab(tab.id)}
						>
							{$i18n.t(tab.labelKey)}
						</button>
					{/each}
				</div>

				<!-- Tab content -->
				<div role="tabpanel">
					<!-- ======== Audit Log ======== -->
					{#if activeTab === 'audit'}
						<div class="space-y-3">
							<div class="flex flex-col sm:flex-row gap-2">
								<div class="w-full sm:w-40">
									<Selector
										value={auditEventFilter}
										items={auditEventItems}
										size="sm"
										on:change={(e) => {
											auditEventFilter = e.detail.value;
											handleAuditEventFilterChange();
										}}
									/>
								</div>
								<div class="w-full sm:w-48">
									<Input
										bind:value={auditUserFilter}
										placeholder={$i18n.t('Filter by user ID\u2026')}
										size="sm"
										on:input={handleAuditUserFilterInput}
									/>
								</div>
							</div>

							{#if auditLoading}
								<div class="flex justify-center py-6">
									<Spinner className="size-4" />
								</div>
							{:else if auditLogs.items.length === 0}
								<div class="text-xs text-gray-400 dark:text-gray-500 py-6 text-center">
									{$i18n.t('No audit logs found')}
								</div>
							{:else}
								<div class="overflow-x-auto">
									<table class="w-full text-xs">
										<thead>
											<tr class="text-left text-gray-500 dark:text-gray-400 border-b border-gray-100 dark:border-gray-850">
												<th class="pb-2 pr-3 font-medium">{$i18n.t('Time')}</th>
												<th class="pb-2 pr-3 font-medium">{$i18n.t('Event')}</th>
												<th class="pb-2 pr-3 font-medium">{$i18n.t('Actor')}</th>
												<th class="pb-2 pr-3 font-medium">{$i18n.t('User Email')}</th>
												<th class="pb-2 font-medium">{$i18n.t('Details')}</th>
											</tr>
										</thead>
										<tbody>
											{#each auditLogs.items as log}
												<tr class="border-b border-gray-50 dark:border-gray-850/50">
													<td class="py-2 pr-3 text-gray-500 dark:text-gray-400 whitespace-nowrap tabular-nums">
														{formatTimestamp(log.created_at)}
													</td>
													<td class="py-2 pr-3">
														<Badge status={eventBadgeStatus(log.action)} size="sm">
															{$i18n.t(log.action)}
														</Badge>
													</td>
													<td class="py-2 pr-3 text-gray-600 dark:text-gray-300 max-w-[120px] truncate">
														{log.meta?.actor || log.user_name || '-'}
													</td>
													<td class="py-2 pr-3 text-gray-600 dark:text-gray-300">
														{log.user_email || '-'}
													</td>
													<td
														class="py-2 text-gray-400 dark:text-gray-500 max-w-[200px] truncate"
														title={log.meta ? JSON.stringify(log.meta) : ''}
													>
														{formatAuditDetail(log.meta)}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>

								<div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
									<span class="tabular-nums">
										{$i18n.t('Page {{page}} of {{total}}', {
											page: auditPage,
											total: Math.max(1, Math.ceil(auditLogs.total / 20))
										})}
										({auditLogs.total} {$i18n.t('records')})
									</span>
									<div class="flex gap-2">
										<Button kind="outlined" size="sm" disabled={auditPage <= 1} on:click={() => { auditPage -= 1; loadAuditLogs(); }}>
											{$i18n.t('Prev')}
										</Button>
										<Button kind="outlined" size="sm" disabled={auditPage >= Math.ceil(auditLogs.total / 20)} on:click={() => { auditPage += 1; loadAuditLogs(); }}>
											{$i18n.t('Next')}
										</Button>
									</div>
								</div>
							{/if}
						</div>

					<!-- ======== User Memories ======== -->
					{:else if activeTab === 'users'}
						<div class="space-y-3">
							<Selector
								value={selectedUserId}
								items={userItems}
								placeholder={$i18n.t('Select a user\u2026')}
								searchEnabled
								size="sm"
								on:change={(e) => {
									selectedUserId = e.detail.value;
									loadUserMemories();
								}}
							/>

							{#if userMemoriesLoading}
								<div class="flex justify-center py-6">
									<Spinner className="size-4" />
								</div>
							{:else if selectedUserId && userMemories.length === 0}
								<div class="text-xs text-gray-400 dark:text-gray-500 py-6 text-center">
									{$i18n.t('No memories found for this user')}
								</div>
							{:else if userMemories.length > 0}
								<div class="space-y-2">
									{#each userMemories as memory}
										<div class="flex items-start justify-between gap-2 p-2.5 rounded-lg bg-gray-50 dark:bg-gray-850">
											<div class="flex-1 min-w-0">
												<div class="text-xs text-gray-700 dark:text-gray-300 break-words">
													{memory.content}
												</div>
												<div class="flex items-center gap-1.5 mt-1.5 flex-wrap">
													<Badge status={sourceBadgeStatus(memory.source)} size="sm">
														{$i18n.t(memory.source)}
													</Badge>
													<Badge status={retentionBadgeStatus(memory.retention_class)} size="sm">
														{$i18n.t(memory.retention_class)}
													</Badge>
													<span class="text-xs text-gray-400 dark:text-gray-500 tabular-nums">
														{formatTimestamp(memory.created_at)}
													</span>
												</div>
											</div>
											<button
												type="button"
												class="shrink-0 p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500 transition-colors focus-visible:ring-2 focus-visible:ring-red-500"
												aria-label={$i18n.t('Delete')}
												on:click={() =>
													confirmDelete(
														$i18n.t('Delete'),
														$i18n.t('Are you sure you want to delete this memory?'),
														() => handleDeleteUserMemory(memory.id)
													)}
											>
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5" aria-hidden="true">
													<path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
												</svg>
											</button>
										</div>
									{/each}
								</div>
							{/if}
						</div>

					<!-- ======== Organization Memory ======== -->
					{:else if activeTab === 'org'}
						<div class="space-y-3">
							<p class="text-xs text-gray-500 dark:text-gray-400">
								{$i18n.t(
									'Organization memories are shared across all members of your organization and injected into every conversation.'
								)}
							</p>

							{#if orgError}
								<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-xs" role="alert">
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4 shrink-0" aria-hidden="true">
										<path fill-rule="evenodd" d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 1 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
									</svg>
									{orgError}
								</div>
							{:else if orgLoading}
								<div class="flex justify-center py-6">
									<Spinner className="size-4" />
								</div>
							{:else}
								<form class="flex gap-2" on:submit|preventDefault={handleAddOrgMemory}>
									<div class="flex-1">
										<Input
											bind:value={orgMemoryInput}
											placeholder={$i18n.t('Add organization memory\u2026')}
											size="sm"
										/>
									</div>
									<Button kind="filled" size="sm" type="submit">
										{$i18n.t('Add')}
									</Button>
								</form>

								{#if orgMemories.length === 0}
									<div class="text-xs text-gray-400 dark:text-gray-500 py-6 text-center">
										{$i18n.t('No organization memories yet')}
									</div>
								{:else}
									<div class="space-y-2">
										{#each orgMemories as memory}
											<div class="flex items-start justify-between gap-2 p-2.5 rounded-lg bg-gray-50 dark:bg-gray-850">
												<div class="flex-1 min-w-0">
													<div class="text-xs text-gray-700 dark:text-gray-300 break-words">
														{memory.content}
													</div>
													<div class="text-xs text-gray-400 dark:text-gray-500 mt-1 tabular-nums">
														{formatTimestamp(memory.created_at)}
													</div>
												</div>
												<button
													type="button"
													class="shrink-0 p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500 transition-colors focus-visible:ring-2 focus-visible:ring-red-500"
													aria-label={$i18n.t('Delete')}
													on:click={() =>
														confirmDelete(
															$i18n.t('Delete'),
															$i18n.t('Are you sure you want to delete this memory?'),
															() => handleDeleteOrgMemory(memory.id)
														)}
												>
													<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5" aria-hidden="true">
														<path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
													</svg>
												</button>
											</div>
										{/each}
									</div>
								{/if}
							{/if}
						</div>

					<!-- ======== Knowledge Entities ======== -->
					{:else if activeTab === 'entities'}
						<div class="space-y-3">
							<p class="text-xs text-gray-500 dark:text-gray-400">
								{$i18n.t(
									'Entity types define categories for knowledge entities extracted from user memories.'
								)}
							</p>

							{#if entityTypes.length > 0}
								<div class="space-y-2">
									{#each entityTypes as et}
										{@const group = entityGroups.find((g) => g.entity_type === et.name)}
										<div class="flex items-center justify-between gap-2 p-2.5 rounded-lg bg-gray-50 dark:bg-gray-850">
											<div class="flex-1 min-w-0">
												<div class="flex items-center gap-2">
													<Badge status="info" size="sm">{et.name}</Badge>
													<span class="text-xs text-gray-400 dark:text-gray-500 tabular-nums">
														{group ? group.count : 0} {$i18n.t('entities')}
													</span>
												</div>
												{#if et.description}
													<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
														{et.description}
													</div>
												{/if}
												{#if group && group.examples.length > 0}
													<div class="flex flex-wrap gap-1 mt-1">
														{#each group.examples as example}
															<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-gray-200/50 dark:bg-gray-700/50 text-gray-600 dark:text-gray-400">
																{example}
															</span>
														{/each}
													</div>
												{/if}
											</div>
											<button
												type="button"
												class="shrink-0 p-1.5 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-400 hover:text-red-500 transition-colors focus-visible:ring-2 focus-visible:ring-red-500"
												aria-label="{$i18n.t('Delete')} {et.name}"
												on:click={() =>
													confirmDelete(
														$i18n.t('Delete'),
														$i18n.t('Are you sure you want to delete this entity type?'),
														() => handleDeleteEntityType(et.id)
													)}
											>
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5" aria-hidden="true">
													<path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
												</svg>
											</button>
										</div>
									{/each}
								</div>
							{:else}
								<div class="text-xs text-gray-400 dark:text-gray-500 py-6 text-center">
									{$i18n.t('No entity types configured')}
								</div>
							{/if}

							{#if showAddEntityType}
								<div class="flex flex-col gap-2 p-2.5 rounded-lg bg-gray-50 dark:bg-gray-850">
									<Input bind:value={newEntityTypeName} placeholder={$i18n.t('Type name (e.g., skill, domain)')} size="sm" />
									<Input bind:value={newEntityTypeDesc} placeholder={$i18n.t('Description (optional)')} size="sm" />
									<div class="flex justify-end gap-2">
										<Button kind="text" size="sm" on:click={() => { showAddEntityType = false; newEntityTypeName = ''; newEntityTypeDesc = ''; }}>
											{$i18n.t('Cancel')}
										</Button>
										<Button kind="filled" size="sm" on:click={handleAddEntityType}>
											{$i18n.t('Add')}
										</Button>
									</div>
								</div>
							{:else}
								<Button
									kind="text"
									size="sm"
									type="button"
									on:click={() => {
										showAddEntityType = true;
									}}
								>
									<svelte:fragment slot="prefix">
										<Plus className="size-3.5" strokeWidth="2" />
									</svelte:fragment>
									{$i18n.t('Add Entity Type')}
								</Button>
							{/if}
						</div>
					{/if}
				</div>
			</section>
		</div>
	</div>
{/if}
