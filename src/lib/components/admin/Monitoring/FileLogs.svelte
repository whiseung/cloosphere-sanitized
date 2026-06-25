<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { getFileLogs, type FileLogItem } from '$lib/apis/file-logs';

	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';

	const i18n = getContext('i18n');

	let items: FileLogItem[] = [];
	let total = 0;
	let totalPages = 0;
	let loading = true;

	// 고정 옵션
	const availableSources = ['chat', 'knowledge', 'project'];
	const availableCategories = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED'];
	const availableStatuses = ['flagged', 'blocked'];

	// Filters (multi-select)
	let selectedSources: string[] = [...availableSources];
	let selectedCategories: string[] = [...availableCategories];
	let selectedStatuses: string[] = [...availableStatuses];
	let searchQuery = '';

	// Dropdown state
	let showSourceDropdown = false;
	let showCategoryDropdown = false;
	let showStatusDropdown = false;

	// Date range (기본값: 최근 7일)
	let dateRange = '7d';
	let fromDate: number | null = null;
	let toDate: number | null = null;

	// 직접 지정용 날짜
	let customFromDate = '';
	let customToDate = '';
	let customDateLabel = '';
	let showCustomDateModal = false;

	const toDateTimeLocal = (date: Date) => {
		const pad = (n: number) => n.toString().padStart(2, '0');
		return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
	};

	const setDateRange = (range: string) => {
		if (range === 'custom') {
			const now = new Date();
			const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
			customFromDate = toDateTimeLocal(weekAgo);
			customToDate = toDateTimeLocal(now);
			customDateLabel = `${formatDateTimeLabel(customFromDate)} ~ ${formatDateTimeLabel(customToDate)}`;
			showCustomDateModal = true;
			return;
		}

		dateRange = range;
		const now = Math.floor(Date.now() / 1000);
		toDate = now;

		switch (range) {
			case '1h':
				fromDate = now - 3600;
				break;
			case '6h':
				fromDate = now - 3600 * 6;
				break;
			case '1d':
				fromDate = now - 86400;
				break;
			case '7d':
				fromDate = now - 86400 * 7;
				break;
			case '30d':
				fromDate = now - 86400 * 30;
				break;
			case 'all':
				fromDate = null;
				toDate = null;
				break;
			default:
				fromDate = now - 86400 * 7;
		}
	};

	const applyCustomDateRange = () => {
		if (customFromDate && customToDate) {
			fromDate = Math.floor(new Date(customFromDate).getTime() / 1000);
			toDate = Math.floor(new Date(customToDate).getTime() / 1000);
			customDateLabel = `${formatDateTimeLabel(customFromDate)} ~ ${formatDateTimeLabel(customToDate)}`;
			dateRange = 'custom';
			showCustomDateModal = false;
			handleSearch();
		}
	};

	const formatDateTimeLabel = (dateStr: string) => {
		if (!dateStr) return '';
		const date = new Date(dateStr);
		const month = (date.getMonth() + 1).toString().padStart(2, '0');
		const day = date.getDate().toString().padStart(2, '0');
		const hours = date.getHours().toString().padStart(2, '0');
		const minutes = date.getMinutes().toString().padStart(2, '0');
		return `${month}/${day} ${hours}:${minutes}`;
	};

	// 초기 날짜 범위 설정
	setDateRange('7d');

	// Pagination
	let page = 1;
	const limit = 20;

	// Detail modal
	let selectedFile: FileLogItem | null = null;
	let showDetail = false;

	function getSourceLabel(source: string): string {
		switch (source) {
			case 'chat':
				return $i18n.t('Chat');
			case 'knowledge':
				return $i18n.t('Knowledge');
			case 'project':
				return $i18n.t('Project');
			default:
				return '-';
		}
	}

	function getSourceBadgeClass(source: string): string {
		switch (source) {
			case 'chat':
				return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300';
			case 'knowledge':
				return 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300';
			case 'project':
				return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300';
			default:
				return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400';
		}
	}

	function getAction(file: FileLogItem): string {
		const cat = file.meta?.classification?.category;
		if (!cat) return '';
		const actionMap: Record<string, string> = {
			PUBLIC: 'allow',
			INTERNAL: 'allow',
			CONFIDENTIAL: 'flag',
			RESTRICTED: 'block'
		};
		return actionMap[cat] || '';
	}

	function getCategoryBadgeClass(category: string): string {
		switch (category) {
			case 'PUBLIC':
				return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
			case 'INTERNAL':
				return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300';
			case 'CONFIDENTIAL':
				return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300';
			case 'RESTRICTED':
				return 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300';
			default:
				return 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400';
		}
	}

	function formatDate(ts: number | null): string {
		if (!ts) return '';
		return new Date(ts * 1000).toLocaleDateString(undefined, {
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function getUserName(item: FileLogItem): string {
		return item.user_name || item.user_email || item.user_id?.substring(0, 8) || '-';
	}

	// 토글 함수
	const toggleSource = (s: string) => { selectedSources = selectedSources.includes(s) ? selectedSources.filter((x) => x !== s) : [...selectedSources, s]; };
	const toggleAllSources = () => { selectedSources = selectedSources.length === availableSources.length ? [] : [...availableSources]; };
	const toggleCategory = (c: string) => { selectedCategories = selectedCategories.includes(c) ? selectedCategories.filter((x) => x !== c) : [...selectedCategories, c]; };
	const toggleAllCategories = () => { selectedCategories = selectedCategories.length === availableCategories.length ? [] : [...availableCategories]; };
	const toggleStatus = (s: string) => { selectedStatuses = selectedStatuses.includes(s) ? selectedStatuses.filter((x) => x !== s) : [...selectedStatuses, s]; };
	const toggleAllStatuses = () => { selectedStatuses = selectedStatuses.length === availableStatuses.length ? [] : [...availableStatuses]; };

	// 라벨
	const getSourceFilterLabel = (s: string) => ({ chat: $i18n.t('Chat'), knowledge: $i18n.t('Knowledge'), project: $i18n.t('Project') }[s] || s);
	const getCategoryFilterLabel = (c: string) => c;
	const getStatusFilterLabel = (s: string) => ({ flagged: $i18n.t('Flagged'), blocked: $i18n.t('Blocked') }[s] || s);

	$: sourceLabel = selectedSources.length === 0 || selectedSources.length === availableSources.length ? $i18n.t('All Sources') : selectedSources.length === 1 ? getSourceFilterLabel(selectedSources[0]) : `${selectedSources.length} ${$i18n.t('selected')}`;
	$: categoryLabel = selectedCategories.length === 0 || selectedCategories.length === availableCategories.length ? $i18n.t('All Categories') : selectedCategories.length === 1 ? getCategoryFilterLabel(selectedCategories[0]) : `${selectedCategories.length} ${$i18n.t('selected')}`;
	$: statusLabel = selectedStatuses.length === 0 || selectedStatuses.length === availableStatuses.length ? $i18n.t('All Status') : selectedStatuses.length === 1 ? getStatusFilterLabel(selectedStatuses[0]) : `${selectedStatuses.length} ${$i18n.t('selected')}`;

	// 활성 필터 (부분 선택 시만)
	const getActiveFilter = (selected: string[], all: string[]) => selected.length > 0 && selected.length < all.length ? selected.join(',') : undefined;

	async function loadFileLogs() {
		loading = true;
		try {
			const res = await getFileLogs(localStorage.token, {
				page,
				limit,
				source: getActiveFilter(selectedSources, availableSources),
				category: getActiveFilter(selectedCategories, availableCategories),
				status: getActiveFilter(selectedStatuses, availableStatuses),
				search: searchQuery || undefined,
				from_date: fromDate ?? undefined,
				to_date: toDate ?? undefined
			});
			items = res.items;
			total = res.total;
			totalPages = res.total_pages;
		} catch (e) {
			toast.error($i18n.t('Failed to load file logs'));
			console.error(e);
		} finally {
			loading = false;
		}
	}

	const handleSearch = () => {
		page = 1;
		if (dateRange && dateRange !== 'custom' && dateRange !== 'all') {
			setDateRange(dateRange);
		}
		loadFileLogs();
	};

	const handleSearchKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail.key === 'Enter') {
			handleSearch();
		}
	};

	let initialized = false;

	$: if (initialized && page) {
		loadFileLogs();
	}

	onMount(async () => {
		await loadFileLogs();
		initialized = true;
	});
</script>

<!-- Header -->
<div class="mt-0.5 mb-2 flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<div class="flex items-center text-lg font-bold px-0.5">
			{$i18n.t('File Logs')}
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
			<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{total}</span>
		</div>
	</div>

	<div class="flex gap-1.5 flex-wrap items-center">
		<!-- Date Range Filter (pill buttons) -->
		<div class="flex items-center rounded-lg bg-gray-50 dark:bg-gray-950 p-0.5 gap-0.5">
			{#each [
				{ value: '1h', label: '1h' },
				{ value: '6h', label: '6h' },
				{ value: '1d', label: '1d' },
				{ value: '7d', label: '7d' },
				{ value: '30d', label: '30d' },
				{ value: 'all', label: $i18n.t('All') }
			] as opt}
				<button
					class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {dateRange === opt.value
						? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm'
						: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
					on:click={() => {
						dateRange = opt.value;
						setDateRange(opt.value);
						handleSearch();
					}}
				>
					{opt.label}
				</button>
			{/each}
			<button
				class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {dateRange === 'custom'
					? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm'
					: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
				on:click={() => setDateRange('custom')}
			>
				{dateRange === 'custom' && customDateLabel ? customDateLabel : $i18n.t('Custom')}
			</button>
		</div>

		<!-- Source Filter (Multi-select) -->
		<DropdownMenu.Root open={showSourceDropdown} onOpenChange={(open) => { showSourceDropdown = open; if (!open) handleSearch(); }}>
			<DropdownMenu.Trigger>
				<button class="flex items-center gap-2 px-3 py-1.5 min-w-[130px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition">
					<span class="flex-1 text-left truncate">{sourceLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content class="w-48 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50" sideOffset={4} transition={flyAndScale}>
				<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleAllSources()}>
					<Checkbox state={selectedSources.length === availableSources.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />
				{#each availableSources as s}
					<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleSource(s)}>
						<Checkbox state={selectedSources.includes(s) ? 'checked' : 'unchecked'} />
						<span>{getSourceFilterLabel(s)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Category Filter (Multi-select) -->
		<DropdownMenu.Root open={showCategoryDropdown} onOpenChange={(open) => { showCategoryDropdown = open; if (!open) handleSearch(); }}>
			<DropdownMenu.Trigger>
				<button class="flex items-center gap-2 px-3 py-1.5 min-w-[140px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition">
					<span class="flex-1 text-left truncate">{categoryLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content class="w-52 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50" sideOffset={4} transition={flyAndScale}>
				<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleAllCategories()}>
					<Checkbox state={selectedCategories.length === availableCategories.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />
				{#each availableCategories as c}
					<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleCategory(c)}>
						<Checkbox state={selectedCategories.includes(c) ? 'checked' : 'unchecked'} />
						<span>{getCategoryFilterLabel(c)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Status Filter (Multi-select) -->
		<DropdownMenu.Root open={showStatusDropdown} onOpenChange={(open) => { showStatusDropdown = open; if (!open) handleSearch(); }}>
			<DropdownMenu.Trigger>
				<button class="flex items-center gap-2 px-3 py-1.5 min-w-[120px] text-sm bg-gray-50 dark:bg-gray-950 rounded-lg outline-none cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-900 transition">
					<span class="flex-1 text-left truncate">{statusLabel}</span>
					<ChevronDown className="size-4 flex-shrink-0" />
				</button>
			</DropdownMenu.Trigger>
			<DropdownMenu.Content class="w-44 max-h-72 overflow-y-auto rounded-lg p-1 border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 shadow-lg z-50" sideOffset={4} transition={flyAndScale}>
				<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleAllStatuses()}>
					<Checkbox state={selectedStatuses.length === availableStatuses.length ? 'checked' : 'unchecked'} />
					<span class="font-medium">{$i18n.t('Select All')}</span>
				</button>
				<div class="h-px bg-gray-100 dark:bg-gray-800 my-1" />
				{#each availableStatuses as st}
					<button class="flex w-full items-center gap-2 px-3 py-2 text-sm rounded-md cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-850 transition" on:click|stopPropagation={() => toggleStatus(st)}>
						<Checkbox state={selectedStatuses.includes(st) ? 'checked' : 'unchecked'} />
						<span>{getStatusFilterLabel(st)}</span>
					</button>
				{/each}
			</DropdownMenu.Content>
		</DropdownMenu.Root>

		<!-- Search -->
		<div class="w-56">
			<Input
				bind:value={searchQuery}
				placeholder={$i18n.t('File or User')}
				size="sm"
				on:keydown={handleSearchKeydown}
			>
				<svelte:fragment slot="prefix">
					<MagnifyingGlass className="size-4" />
				</svelte:fragment>
			</Input>
		</div>

		<!-- Refresh -->
		<Tooltip content={$i18n.t('Refresh')}>
			<Button kind="text" size="sm" type="button" on:click={() => handleSearch()}>
				<svelte:fragment slot="prefix">
					<ArrowPath className="size-4" />
				</svelte:fragment>
			</Button>
		</Tooltip>
	</div>
</div>

<hr class="mb-3 border-gray-50 dark:border-gray-850" />

<!-- Table -->
{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else if items.length === 0}
	<div class="flex flex-col items-center justify-center py-12 text-center">
		<p class="text-gray-500 dark:text-gray-400">
			{$i18n.t('No files found')}
		</p>
	</div>
{:else}
	<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-800">
		<table class="w-full text-sm">
			<thead>
				<tr
					class="bg-gray-50 dark:bg-gray-900 text-left text-xs text-gray-500 dark:text-gray-400"
				>
					<th class="px-4 py-2 font-medium">{$i18n.t('Filename')}</th>
					<th class="px-4 py-2 font-medium">{$i18n.t('Uploader')}</th>
					<th class="px-4 py-2 font-medium">{$i18n.t('Source')}</th>
					<th class="px-4 py-2 font-medium">{$i18n.t('Classification')}</th>
					<th class="px-4 py-2 font-medium">{$i18n.t('Uploaded')}</th>
					<th class="px-4 py-2 font-medium">{$i18n.t('Status')}</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-gray-100 dark:divide-gray-850">
				{#each items as item (item.id)}
					<tr
						class="hover:bg-gray-50 dark:hover:bg-gray-900/50 cursor-pointer transition-colors"
						on:click={() => {
							selectedFile = item;
							showDetail = true;
						}}
					>
						<td class="px-4 py-2.5">
							<div class="font-medium text-gray-900 dark:text-gray-100 line-clamp-1 max-w-[300px]" title={item.filename}>
								{item.filename}
							</div>
							<div class="text-xs text-gray-400 dark:text-gray-500">{item.meta?.content_type || ''}</div>
						</td>
						<td class="px-4 py-2.5">
							<div class="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">{getUserName(item)}</div>
							<div class="text-xs text-gray-500 dark:text-gray-400 truncate">{item.user_email || ''}</div>
						</td>
						<td class="px-4 py-2.5">
							{#if item.meta?.source}
								<span
									class="text-xs px-1.5 py-0.5 rounded {getSourceBadgeClass(item.meta.source)}"
								>
									{getSourceLabel(item.meta.source)}
								</span>
							{:else}
								<span class="text-xs text-gray-400">-</span>
							{/if}
						</td>
						<td class="px-4 py-2.5">
							{#if item.meta?.classification?.category}
								<span
									class="text-xs px-1.5 py-0.5 rounded {getCategoryBadgeClass(item.meta.classification.category)}"
								>
									{item.meta.classification.category}
								</span>
							{:else}
								<span class="text-xs text-gray-400">-</span>
							{/if}
						</td>
						<td class="px-4 py-2.5 text-gray-500 dark:text-gray-400 text-xs">
							{formatDate(item.created_at)}
						</td>
						<td class="px-4 py-2.5">
							{#if item.meta?.guardrail_blocked}
								<span
									class="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
								>
									{$i18n.t('Blocked')}
								</span>
							{:else if item.meta?.classification?.category && getAction(item) === 'flag'}
								<span
									class="text-xs px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300"
								>
									{$i18n.t('Flagged')}
								</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Pagination -->
	{#if total > limit}
		<div class="mt-4 flex justify-center">
			<Pagination bind:page count={total} perPage={limit} />
		</div>
	{/if}
{/if}

<!-- Custom Date Range Modal -->
<Modal bind:show={showCustomDateModal} size="xs">
	<div class="px-5 py-4">
		<div class="text-lg font-semibold mb-4">{$i18n.t('Custom Range')}</div>
		<div class="flex flex-col gap-3">
			<div class="flex flex-col gap-1">
				<LabelBase label={$i18n.t('From')} size="md" />
				<input
					type="datetime-local"
					bind:value={customFromDate}
					class="w-full px-3 py-2 text-sm rounded-lg bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 outline-none"
				/>
			</div>
			<div class="flex flex-col gap-1">
				<LabelBase label={$i18n.t('To')} size="md" />
				<input
					type="datetime-local"
					bind:value={customToDate}
					class="w-full px-3 py-2 text-sm rounded-lg bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-200 outline-none"
				/>
			</div>
		</div>
		<div class="flex justify-end gap-2 mt-4">
			<Button kind="outlined" size="md" on:click={() => { showCustomDateModal = false; }}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" on:click={applyCustomDateRange}>
				{$i18n.t('Apply')}
			</Button>
		</div>
	</div>
</Modal>

<!-- Detail Modal -->
{#if showDetail && selectedFile}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
		on:click={() => {
			showDetail = false;
		}}
	>
		<!-- svelte-ignore a11y-click-events-have-key-events -->
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div
			class="bg-white dark:bg-gray-900 rounded-2xl max-w-lg w-full max-h-[80vh] overflow-y-auto p-6"
			on:click|stopPropagation
		>
			<div class="flex items-center justify-between mb-4">
				<h3 class="text-lg font-medium text-gray-900 dark:text-gray-100">{$i18n.t('File Details')}</h3>
				<button
					type="button"
					class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={() => {
						showDetail = false;
					}}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="size-5"
						viewBox="0 0 20 20"
						fill="currentColor"
					>
						<path
							d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
						/>
					</svg>
				</button>
			</div>

			<div class="space-y-3 text-sm">
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{$i18n.t('Filename')}</div>
					<div class="font-medium text-gray-900 dark:text-gray-100">{selectedFile.filename}</div>
				</div>

				<div class="flex gap-4">
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{$i18n.t('Content Type')}</div>
						<div class="text-gray-900 dark:text-gray-100">{selectedFile.meta?.content_type || '-'}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{$i18n.t('Size')}</div>
						<div class="text-gray-900 dark:text-gray-100">
							{selectedFile.meta?.size
								? `${(selectedFile.meta.size / 1024).toFixed(1)} KB`
								: '-'}
						</div>
					</div>
				</div>

				<div class="flex gap-4">
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{$i18n.t('Uploader')}</div>
						<div class="font-medium text-gray-900 dark:text-gray-100">{getUserName(selectedFile)}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400">{selectedFile.user_email || ''}</div>
					</div>
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{$i18n.t('Source')}</div>
						{#if selectedFile.meta?.source}
							<span
								class="text-xs px-1.5 py-0.5 rounded {getSourceBadgeClass(selectedFile.meta.source)}"
							>
								{getSourceLabel(selectedFile.meta.source)}
							</span>
						{:else}
							<div>-</div>
						{/if}
					</div>
				</div>

				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{$i18n.t('Uploaded')}</div>
					<div class="text-gray-900 dark:text-gray-100">{formatDate(selectedFile.created_at)}</div>
				</div>

				{#if selectedFile.meta?.classification}
					<div class="border-t border-gray-200 dark:border-gray-800 pt-3">
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">{$i18n.t('Classification')}</div>
						<div class="space-y-2">
							<div class="flex items-center gap-2">
								<span class="text-xs font-medium text-gray-900 dark:text-gray-100">{$i18n.t('Category')}:</span>
								<span
									class="text-xs px-1.5 py-0.5 rounded {getCategoryBadgeClass(selectedFile.meta.classification.category)}"
								>
									{selectedFile.meta.classification.category}
								</span>
							</div>
							{#if selectedFile.meta.classification.confidence != null}
								<div>
									<span class="text-xs font-medium text-gray-900 dark:text-gray-100">{$i18n.t('Confidence')}:</span>
									<span class="text-xs ml-1 text-gray-900 dark:text-gray-100"
										>{(selectedFile.meta.classification.confidence * 100).toFixed(0)}%</span
									>
								</div>
							{/if}
							{#if selectedFile.meta.classification.reason}
								<div>
									<span class="text-xs font-medium text-gray-900 dark:text-gray-100">{$i18n.t('Reason')}:</span>
									<span class="text-xs ml-1 text-gray-900 dark:text-gray-100">{selectedFile.meta.classification.reason}</span>
								</div>
							{/if}
							{#if selectedFile.meta.classification.model}
								<div>
									<span class="text-xs font-medium text-gray-900 dark:text-gray-100">{$i18n.t('Model')}:</span>
									<span class="text-xs ml-1 text-gray-900 dark:text-gray-100">{selectedFile.meta.classification.model}</span>
								</div>
							{/if}
							{#if selectedFile.meta.classification.error}
								<div class="text-xs text-red-500">
									{$i18n.t('Error')}: {selectedFile.meta.classification.error}
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if selectedFile.meta?.guardrail_blocked}
					<div class="border-t border-gray-200 dark:border-gray-800 pt-3">
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">{$i18n.t('Guardrail Details')}</div>
						{#if selectedFile.meta?.guardrail_details}
							<pre
								class="text-xs bg-gray-50 dark:bg-gray-850 text-gray-900 dark:text-gray-200 rounded-lg p-2 overflow-x-auto">{JSON.stringify(selectedFile.meta.guardrail_details, null, 2)}</pre>
						{/if}
					</div>
				{/if}

				{#if selectedFile.meta?.guardrail_exif_strip}
					<div>
						<span class="text-xs font-medium text-gray-900 dark:text-gray-100">{$i18n.t('EXIF Stripped')}:</span>
						<span class="text-xs ml-1 text-gray-900 dark:text-gray-100"
							>{selectedFile.meta.guardrail_exif_strip.stripped
								? $i18n.t('Yes')
								: $i18n.t('No')}</span
						>
					</div>
				{/if}

				{#if selectedFile.meta?.guardrail_nsfw_detection}
					<div>
						<span class="text-xs font-medium text-gray-900 dark:text-gray-100">{$i18n.t('NSFW Check')}:</span>
						<span class="text-xs ml-1 text-gray-900 dark:text-gray-100"
							>{selectedFile.meta.guardrail_nsfw_detection.raw_response || '-'}</span
						>
					</div>
				{/if}
			</div>

			<div class="flex justify-end mt-6">
				<Button kind="outlined" size="md" on:click={() => { showDetail = false; }}>
					{$i18n.t('Close')}
				</Button>
			</div>
		</div>
	</div>
{/if}
