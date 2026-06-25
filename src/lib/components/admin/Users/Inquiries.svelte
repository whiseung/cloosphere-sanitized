<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext, tick } from 'svelte';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	import Sortable from 'sortablejs';
	dayjs.extend(relativeTime);

	import { getAllInquiries, updateInquiry, deleteInquiry } from '$lib/apis/inquiries';
	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext('i18n');

	export let users = [];

	let inquiries = [];
	let loaded = false;
	let viewMode: 'kanban' | 'list' = 'kanban';

	// Sortable instances
	let sortableInstances: Sortable[] = [];
	let columnElements: Record<string, HTMLElement> = {};

	// Detail modal
	let showDetailModal = false;
	let selectedInquiry = null;
	let adminNote = '';
	let selectedStatus = '';
	let saving = false;

	// Delete
	let showDeleteConfirmDialog = false;

	const TYPE_LABELS = {
		usage_limit: 'Usage Limit',
		feature: 'Feature Inquiry',
		bug: 'Bug Report',
		account: 'Account / Permission',
		other: 'Other'
	};

	const SUBTYPE_LABELS = {
		limit_increase: 'Limit Increase Request',
		limit_check: 'Limit Check',
		chat: 'Chat',
		agent: 'Agent',
		knowledge: 'Knowledge Base',
		database: 'Database',
		tool: 'Tool',
		chat_error: 'Chat Error',
		agent_error: 'Agent Error',
		upload_error: 'Upload Error',
		other_error: 'Other Error',
		permission_request: 'Permission Request',
		account_issue: 'Account Issue',
		improvement: 'Improvement Suggestion',
		other: 'Other'
	};

	const STATUS_LABELS = {
		open: 'Open',
		in_progress: 'In Progress',
		resolved: 'Resolved',
		closed: 'Closed'
	};

	const STATUS_COLORS = {
		open: 'bg-amber-500',
		in_progress: 'bg-blue-500',
		resolved: 'bg-green-500',
		closed: 'bg-gray-400'
	};

	const STATUS_ORDER = ['open', 'in_progress', 'resolved', 'closed'];

	$: columns = STATUS_ORDER.map((status) => ({
		status,
		items: inquiries.filter((i) => i.status === status)
	}));

	$: statusOptions = Object.entries(STATUS_LABELS).map(([value, label]) => ({
		value,
		label: $i18n.t(label)
	}));

	const loadInquiries = async () => {
		try {
			const result = await getAllInquiries(localStorage.token);
			inquiries = result ?? [];
		} catch (error) {
			console.error('Failed to load inquiries:', error);
			toast.error($i18n.t(`${error}`));
			inquiries = [];
		}
		loaded = true;
		if (viewMode === 'kanban') {
			await tick();
			initSortable();
		}
	};

	const initSortable = () => {
		destroySortable();
		for (const status of STATUS_ORDER) {
			const el = columnElements[status];
			if (!el) continue;
			const instance = Sortable.create(el, {
				group: 'kanban',
				animation: 150,
				ghostClass: 'kanban-ghost',
				dragClass: 'kanban-drag',
				onEnd: async (evt) => {
					const inquiryId = evt.item.dataset.id;
					const newStatus = evt.to.dataset.status;
					if (!inquiryId || !newStatus) return;

					const inquiry = inquiries.find((i) => i.id === inquiryId);
					if (inquiry && inquiry.status !== newStatus) {
						if (newStatus === 'closed') {
							toast.warning(
								$i18n.t(
									'Closing an inquiry directly may prevent the user from seeing the result. Use "Resolved" instead so the user can review and close it themselves.'
								)
							);
							await loadInquiries();
							return;
						}
						try {
							await updateInquiry(localStorage.token, inquiryId, { status: newStatus });
							await loadInquiries();
						} catch (error) {
							toast.error($i18n.t(`${error}`));
							await loadInquiries();
						}
					}
				}
			});
			sortableInstances.push(instance);
		}
	};

	const destroySortable = () => {
		sortableInstances.forEach((s) => s.destroy());
		sortableInstances = [];
	};

	const openDetail = (inquiry) => {
		selectedInquiry = inquiry;
		adminNote = inquiry.admin_note || '';
		selectedStatus = inquiry.status;
		showDetailModal = true;
	};

	const saveInquiry = async () => {
		if (!selectedInquiry) return;
		if (selectedStatus === 'closed') {
			toast.warning(
				$i18n.t(
					'Closing an inquiry directly may prevent the user from seeing the result. Use "Resolved" instead so the user can review and close it themselves.'
				)
			);
			selectedStatus = 'resolved';
			return;
		}
		saving = true;
		try {
			const res = await updateInquiry(localStorage.token, selectedInquiry.id, {
				status: selectedStatus,
				admin_note: adminNote
			});
			if (res) {
				toast.success($i18n.t('Saved successfully'));
				await loadInquiries();
				showDetailModal = false;
			}
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			saving = false;
		}
	};

	const handleDelete = async () => {
		if (!selectedInquiry) return;
		try {
			await deleteInquiry(localStorage.token, selectedInquiry.id);
			toast.success($i18n.t('Deleted successfully'));
			showDetailModal = false;
			await loadInquiries();
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		}
	};

	onMount(() => {
		loadInquiries();
		return () => destroySortable();
	});
</script>

<ConfirmDialog bind:show={showDeleteConfirmDialog} on:confirm={handleDelete} />

<div class="flex flex-col h-full">
	<!-- View Toggle -->
	<div class="flex items-center justify-between mb-3">
		<span class="text-xs text-gray-500 dark:text-gray-400">
			{inquiries.length} {$i18n.t('items')}
		</span>
		<div class="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-0.5">
			<button
				class="p-1.5 rounded-md transition {viewMode === 'kanban'
					? 'bg-white dark:bg-gray-700 shadow-sm'
					: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
				on:click={() => {
					viewMode = 'kanban';
					tick().then(initSortable);
				}}
				title={$i18n.t('Kanban')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="w-3.5 h-3.5"
				>
					<path
						d="M2 3.5A1.5 1.5 0 0 1 3.5 2h2A1.5 1.5 0 0 1 7 3.5v9A1.5 1.5 0 0 1 5.5 14h-2A1.5 1.5 0 0 1 2 12.5v-9ZM9 3.5A1.5 1.5 0 0 1 10.5 2h2A1.5 1.5 0 0 1 14 3.5v5a1.5 1.5 0 0 1-1.5 1.5h-2A1.5 1.5 0 0 1 9 8.5v-5Z"
					/>
				</svg>
			</button>
			<button
				class="p-1.5 rounded-md transition {viewMode === 'list'
					? 'bg-white dark:bg-gray-700 shadow-sm'
					: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
				on:click={() => {
					destroySortable();
					viewMode = 'list';
				}}
				title={$i18n.t('List')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="w-3.5 h-3.5"
				>
					<path
						fill-rule="evenodd"
						d="M2 4a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-11A.5.5 0 0 1 2 4Zm0 4a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-11A.5.5 0 0 1 2 8Zm0 4a.5.5 0 0 1 .5-.5h11a.5.5 0 0 1 0 1h-11A.5.5 0 0 1 2 12Z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		</div>
	</div>

	{#if !loaded}
		<div class="text-center text-gray-500 py-8">{$i18n.t('Loading...')}</div>
	{:else if viewMode === 'kanban'}
		<!-- Kanban Board -->
		<div class="flex gap-3 h-full overflow-x-auto pb-2 scrollbar-hidden">
			{#each columns as col}
				<div class="flex flex-col flex-1 min-w-[180px] min-h-0">
					<!-- Column Header -->
					<div class="flex items-center gap-2 mb-2 px-1">
						<div class="w-2.5 h-2.5 rounded-full {STATUS_COLORS[col.status]}"></div>
						<span class="text-xs font-semibold text-gray-700 dark:text-gray-300">
							{$i18n.t(STATUS_LABELS[col.status])}
						</span>
						<span class="text-xs text-gray-400 dark:text-gray-500">{col.items.length}</span>
					</div>

					<!-- Cards (sortable container) -->
					<div
						class="kanban-column flex flex-col gap-2 flex-1 overflow-y-auto scrollbar-hidden rounded-lg p-1 min-h-[60px]"
						data-status={col.status}
						bind:this={columnElements[col.status]}
					>
						{#each col.items as inquiry (inquiry.id)}
							<div
								class="kanban-card w-full text-left p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:border-gray-300 dark:hover:border-gray-600 hover:shadow-sm transition cursor-grab active:cursor-grabbing"
								data-id={inquiry.id}
							>
								<!-- svelte-ignore a11y-click-events-have-key-events -->
								<div
									role="button"
									tabindex="0"
									on:click={() => openDetail(inquiry)}
								>
									<div
										class="text-sm font-medium text-gray-900 dark:text-gray-100 line-clamp-2 mb-2"
									>
										{inquiry.title}
									</div>

									<div class="flex items-center gap-1 mb-1.5">
										<span
											class="inline-block px-1.5 py-0.5 text-[10px] rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
										>
											{$i18n.t(TYPE_LABELS[inquiry.type] || inquiry.type)}
										</span>
									</div>

									<div
										class="flex items-center justify-between text-[11px] text-gray-400 dark:text-gray-500"
									>
										<span class="truncate max-w-[100px]"
											>{inquiry.user_name || inquiry.user_email}</span
										>
										<span>{dayjs(inquiry.created_at * 1000).fromNow()}</span>
									</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<!-- List View -->
		{#if inquiries.length === 0}
			<div class="text-center text-gray-500 py-8">{$i18n.t('No inquiries found')}</div>
		{:else}
			<div class="flex flex-col gap-0.5">
				{#each inquiries as inquiry}
					<button
						class="flex items-center gap-3 py-2.5 px-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 transition cursor-pointer w-full text-left"
						on:click={() => openDetail(inquiry)}
					>
						<div
							class="flex-none w-2.5 h-2.5 rounded-full {STATUS_COLORS[inquiry.status]}"
						></div>
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2">
								<span
									class="text-sm font-medium truncate text-gray-900 dark:text-gray-100"
									>{inquiry.title}</span
								>
								<span
									class="flex-none inline-block px-1.5 py-0.5 text-[10px] rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
								>
									{$i18n.t(TYPE_LABELS[inquiry.type] || inquiry.type)}
								</span>
							</div>
							<div
								class="flex items-center gap-1.5 mt-0.5 text-xs text-gray-400 dark:text-gray-500"
							>
								<span>{inquiry.user_name || inquiry.user_email}</span>
								<span>·</span>
								<span>{$i18n.t(STATUS_LABELS[inquiry.status])}</span>
								<span>·</span>
								<span>{dayjs(inquiry.created_at * 1000).fromNow()}</span>
							</div>
						</div>
					</button>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<!-- Detail Modal -->
<Modal size="md" bind:show={showDetailModal}>
	{#if selectedInquiry}
		<div class="p-5 dark:text-gray-200">
			<div class="flex justify-between items-start mb-4">
				<div>
					<h3 class="text-lg font-medium">{selectedInquiry.title}</h3>
					<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
						{selectedInquiry.user_name || selectedInquiry.user_email}
						· {$i18n.t(TYPE_LABELS[selectedInquiry.type] || selectedInquiry.type)}
						/ {$i18n.t(SUBTYPE_LABELS[selectedInquiry.subtype] || selectedInquiry.subtype)}
						· {dayjs(selectedInquiry.created_at * 1000).format('YYYY-MM-DD HH:mm')}
					</div>
				</div>
				<Button
					kind="text"
					size="sm"
					type="button"
					on:click={() => {
						showDetailModal = false;
					}}
				>
					<XMark className="size-5" />
				</Button>
			</div>

			<!-- Content -->
			<div class="bg-gray-50 dark:bg-gray-850 rounded-lg p-4 mb-4 text-sm whitespace-pre-wrap">
				{selectedInquiry.content}
			</div>

			<!-- Status -->
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs leading-4 font-medium text-[var(--cloo-text-primary)]">
						{$i18n.t('Status')}
					</div>
					<Selector
						value={selectedStatus}
						items={statusOptions}
						size="md"
						searchEnabled={false}
						on:change={(e) => {
							selectedStatus = e.detail.value;
						}}
					/>
				</div>

				<Textarea
					bind:value={adminNote}
					label={$i18n.t('Admin Note')}
					placeholder={$i18n.t('Add a note for this inquiry')}
					size="md"
					rows={3}
				/>
			</div>

			<!-- Actions -->
			<div class="flex justify-between pt-4 mt-4 border-t border-gray-100 dark:border-gray-800">
				<Button
					kind="outlined"
					size="md"
					status="error"
					on:click={() => {
						showDeleteConfirmDialog = true;
					}}
				>
					{$i18n.t('Delete')}
				</Button>
				<Button kind="filled" size="md" disabled={saving} on:click={saveInquiry}>
					{$i18n.t('Save')}
				</Button>
			</div>
		</div>
	{/if}
</Modal>

<style>
	:global(.kanban-ghost) {
		opacity: 0.4;
	}
	:global(.kanban-drag) {
		opacity: 0.9;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
		transform: rotate(2deg);
	}
</style>
