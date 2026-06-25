<script lang="ts">
	import { onMount, createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from './Modal.svelte';
	import Spinner from './Spinner.svelte';
	import Checkbox from './Checkbox.svelte';
	import XMark from '../icons/XMark.svelte';

	import {
		getSites,
		getDrives,
		getItems,
		downloadFile,
		formatFileSize,
		formatDate,
		type Site,
		type Drive,
		type DriveItem
	} from '$lib/utils/sharepoint-client';

	const i18n: any = getContext('i18n');

	export let show = false;

	const dispatch = createEventDispatcher<{
		select: { files: File[] };
		cancel: void;
	}>();

	// State
	let loading = false;
	let downloading = false;
	let error = '';

	let sites: Site[] = [];
	let drives: Drive[] = [];
	let items: DriveItem[] = [];

	let selectedSite: Site | null = null;
	let selectedDrive: Drive | null = null;

	// 반응성을 위해 배열 사용 (Set 대신)
	let selectedItemIds: string[] = [];

	// Navigation stack for breadcrumbs
	let navigationStack: { id: string; name: string }[] = [];

	// 선택된 아이템 수 (반응성)
	$: selectedCount = selectedItemIds.length;

	// show가 변경될 때 초기화
	$: if (show) {
		resetState();
		loadSites();
	}

	function resetState() {
		selectedSite = null;
		selectedDrive = null;
		selectedItemIds = [];
		items = [];
		drives = [];
		navigationStack = [];
		error = '';
	}

	async function loadSites() {
		if (sites.length > 0) return; // 이미 로드됨

		loading = true;
		error = '';
		try {
			sites = await getSites();
			if (sites.length === 0) {
				error = $i18n.t('No SharePoint sites found. Please check your permissions.');
			} else if (sites.length === 1) {
				await selectSite(sites[0]);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : $i18n.t('Failed to load sites');
			console.error('SharePoint loadSites error:', e);
		} finally {
			loading = false;
		}
	}

	async function selectSite(site: Site) {
		selectedSite = site;
		selectedDrive = null;
		selectedItemIds = [];
		items = [];
		navigationStack = [];

		loading = true;
		error = '';
		try {
			drives = await getDrives(site.id);
			if (drives.length === 1) {
				await selectDrive(drives[0]);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : $i18n.t('Failed to load document libraries');
		} finally {
			loading = false;
		}
	}

	async function selectDrive(drive: Drive) {
		selectedDrive = drive;
		selectedItemIds = [];
		navigationStack = [{ id: 'root', name: drive.name }];

		await loadItems();
	}

	async function loadItems(folderId?: string) {
		if (!selectedDrive) return;

		loading = true;
		error = '';
		try {
			items = await getItems(selectedDrive.id, folderId || undefined);
			selectedItemIds = [];
		} catch (e) {
			error = e instanceof Error ? e.message : $i18n.t('Failed to load items');
		} finally {
			loading = false;
		}
	}

	async function navigateToFolder(item: DriveItem) {
		if (!item.folder) return;

		navigationStack = [...navigationStack, { id: item.id, name: item.name }];
		await loadItems(item.id);
	}

	async function navigateToBreadcrumb(index: number) {
		if (index === 0) {
			navigationStack = [navigationStack[0]];
			await loadItems();
		} else {
			const target = navigationStack[index];
			navigationStack = navigationStack.slice(0, index + 1);
			await loadItems(target.id === 'root' ? undefined : target.id);
		}
	}

	function toggleItemSelection(itemId: string) {
		const idx = selectedItemIds.indexOf(itemId);
		if (idx >= 0) {
			selectedItemIds = selectedItemIds.filter((id) => id !== itemId);
		} else {
			selectedItemIds = [...selectedItemIds, itemId];
		}
	}

	function handleItemClick(item: DriveItem) {
		if (item.folder) {
			navigateToFolder(item);
		} else {
			toggleItemSelection(item.id);
		}
	}

	async function handleSelect() {
		if (selectedCount === 0 || !selectedDrive) return;

		downloading = true;
		error = '';

		try {
			const selectedItems = items.filter((item) => selectedItemIds.includes(item.id));
			const allFiles: File[] = [];

			for (const item of selectedItems) {
				const blob = await downloadFile(selectedDrive.id, item.id);
				const file = new File([blob], item.name, {
					type: blob.type || 'application/octet-stream'
				});
				allFiles.push(file);
			}

			if (allFiles.length > 0) {
				dispatch('select', { files: allFiles });
				toast.success($i18n.t('{{count}} files added', { count: allFiles.length }));
			}

			show = false;
		} catch (e) {
			error = e instanceof Error ? e.message : $i18n.t('Failed to download');
			toast.error(error);
		} finally {
			downloading = false;
		}
	}

	function handleCancel() {
		dispatch('cancel');
		show = false;
	}

	function handleSiteChange(event: Event) {
		const select = event.target as HTMLSelectElement;
		const siteId = select.value;
		const site = sites.find((s) => s.id === siteId);
		if (site) {
			selectSite(site);
		}
	}

	function handleDriveChange(event: Event) {
		const select = event.target as HTMLSelectElement;
		const driveId = select.value;
		const drive = drives.find((d) => d.id === driveId);
		if (drive) {
			selectDrive(drive);
		}
	}
</script>

<Modal bind:show size="md">
	<div class="font-primary flex flex-col max-h-[80vh]">
		<!-- Header -->
		<div class="flex items-start justify-between px-5 py-4">
			<div class="flex items-center gap-3">
				<div class="p-2 rounded-lg bg-gray-100 dark:bg-gray-800">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" class="size-5" fill="none">
						<circle cx="16" cy="14" r="10" fill="#036C70" />
						<circle cx="10" cy="22" r="8" fill="#1A9BA1" />
						<circle cx="20" cy="24" r="6" fill="#37C6D0" />
					</svg>
				</div>
				<div>
					<div class="font-medium text-lg dark:text-gray-100">
						{$i18n.t('SharePoint')}
					</div>
					<div class="text-xs text-gray-500">
						{$i18n.t('Select files or folders')}
					</div>
				</div>
			</div>
			<button
				class="self-center hover:bg-gray-100 dark:hover:bg-gray-800 rounded-full p-1.5 transition"
				on:click={handleCancel}
			>
				<XMark />
			</button>
		</div>

		<!-- Selectors -->
		<div class="px-5 pb-3 space-y-2">
			<!-- Site Selector -->
			<div class="flex items-center gap-2">
				<label for="site-select" class="text-sm text-gray-600 dark:text-gray-400 w-20 shrink-0">
					{$i18n.t('Site')}
				</label>
				<select
					id="site-select"
					class="flex-1 px-3 py-2 text-sm rounded-lg
						bg-gray-50 dark:bg-gray-850
						border border-gray-200 dark:border-gray-700
						text-gray-900 dark:text-white
						focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600
						disabled:opacity-50 disabled:cursor-not-allowed"
					value={selectedSite?.id ?? ''}
					on:change={handleSiteChange}
					disabled={loading || sites.length === 0}
				>
					<option value="">{$i18n.t('Select a site...')}</option>
					{#each sites as site (site.id)}
						<option value={site.id}>{site.displayName || site.name}</option>
					{/each}
				</select>
			</div>

			<!-- Drive Selector -->
			{#if selectedSite && drives.length > 0}
				<div class="flex items-center gap-2">
					<label for="drive-select" class="text-sm text-gray-600 dark:text-gray-400 w-20 shrink-0">
						{$i18n.t('Library')}
					</label>
					<select
						id="drive-select"
						class="flex-1 px-3 py-2 text-sm rounded-lg
							bg-gray-50 dark:bg-gray-850
							border border-gray-200 dark:border-gray-700
							text-gray-900 dark:text-white
							focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600
							disabled:opacity-50 disabled:cursor-not-allowed"
						value={selectedDrive?.id ?? ''}
						on:change={handleDriveChange}
						disabled={loading || drives.length === 0}
					>
						<option value="">{$i18n.t('Select a library...')}</option>
						{#each drives as drive (drive.id)}
							<option value={drive.id}>{drive.name}</option>
						{/each}
					</select>
				</div>
			{/if}
		</div>

		<!-- Breadcrumbs -->
		{#if navigationStack.length > 0}
			<div class="px-5 py-2 flex items-center gap-1 text-sm border-t border-gray-100 dark:border-gray-850 overflow-x-auto scrollbar-hidden">
				{#each navigationStack as crumb, index (crumb.id + index)}
					{#if index > 0}
						<span class="text-gray-400 dark:text-gray-600">/</span>
					{/if}
					<button
						class="px-1 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800 whitespace-nowrap transition
							{index === navigationStack.length - 1
								? 'font-medium text-gray-900 dark:text-white'
								: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
						on:click={() => navigateToBreadcrumb(index)}
					>
						{crumb.name}
					</button>
				{/each}
			</div>
		{/if}

		<!-- File List -->
		<div class="flex-1 overflow-y-auto min-h-[280px] max-h-[400px] border-t border-gray-100 dark:border-gray-850">
			{#if loading}
				<div class="flex items-center justify-center h-full py-12">
					<div class="flex flex-col items-center gap-2">
						<Spinner className="size-6" />
						<span class="text-sm text-gray-500">{$i18n.t('Loading...')}</span>
					</div>
				</div>
			{:else if error}
				<div class="flex items-center justify-center h-full p-6">
					<div class="text-center max-w-sm">
						<div class="w-10 h-10 mx-auto mb-2 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
							<svg class="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
							</svg>
						</div>
						<p class="text-sm text-gray-600 dark:text-gray-400 mb-3">{error}</p>
						<button
							class="px-3 py-1.5 text-sm rounded-lg
								bg-gray-100 dark:bg-gray-800
								text-gray-700 dark:text-gray-300
								hover:bg-gray-200 dark:hover:bg-gray-700
								transition"
							on:click={() => { error = ''; loadSites(); }}
						>
							{$i18n.t('Try again')}
						</button>
					</div>
				</div>
			{:else if !selectedDrive}
				<div class="flex items-center justify-center h-full text-gray-400 dark:text-gray-500 py-12">
					<div class="text-center">
						<svg class="w-10 h-10 mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
						</svg>
						<p class="text-sm">{$i18n.t('Select a site and document library to browse files')}</p>
					</div>
				</div>
			{:else if items.length === 0}
				<div class="flex items-center justify-center h-full text-gray-400 dark:text-gray-500 py-12">
					<div class="text-center">
						<svg class="w-10 h-10 mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z" />
						</svg>
						<p class="text-sm">{$i18n.t('No items in this folder')}</p>
					</div>
				</div>
			{:else}
				<div class="divide-y divide-gray-50 dark:divide-gray-850">
					{#each items as item (item.id)}
						<button
							class="w-full flex items-center gap-3 px-5 py-2.5 text-left group transition
								hover:bg-gray-50 dark:hover:bg-gray-900
								{selectedItemIds.includes(item.id) ? 'bg-gray-100 dark:bg-gray-800' : ''}"
							on:click={() => handleItemClick(item)}
						>
						{#if !item.folder}
							<Checkbox
								state={selectedItemIds.includes(item.id) ? 'checked' : 'unchecked'}
							/>
						{/if}

							<!-- Icon -->
							<div class="shrink-0">
								{#if item.folder}
									<svg class="w-5 h-5 text-amber-500" fill="currentColor" viewBox="0 0 20 20">
										<path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
									</svg>
								{:else}
									<svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
										<path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd" />
									</svg>
								{/if}
							</div>

							<!-- Name and details -->
							<div class="flex-1 min-w-0">
								<p class="text-sm text-gray-900 dark:text-white truncate">
									{item.name}
								</p>
								<p class="text-xs text-gray-500">
									{#if item.folder}
										{$i18n.t('{{count}} items', { count: item.folder.childCount })}
									{:else}
										{formatFileSize(item.size)}
										{#if item.lastModifiedDateTime}
											<span class="mx-1">·</span>
											{formatDate(item.lastModifiedDateTime)}
										{/if}
									{/if}
								</p>
							</div>

							<!-- Folder arrow -->
							{#if item.folder}
								<svg class="w-4 h-4 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
								</svg>
							{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<div class="flex items-center justify-between px-5 py-3 border-t border-gray-100 dark:border-gray-850">
			<div class="text-sm text-gray-500">
				{#if selectedCount > 0}
					{$i18n.t('{{count}} selected', { count: selectedCount })}
				{:else}
					{$i18n.t('No items selected')}
				{/if}
			</div>
			<div class="flex items-center gap-2">
				<button
					class="px-4 py-1.5 text-sm rounded-lg
						text-gray-700 dark:text-gray-300
						hover:bg-gray-100 dark:hover:bg-gray-800
						transition"
					on:click={handleCancel}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-1.5 text-sm font-medium rounded-lg transition flex items-center gap-2
						{selectedCount > 0 && !downloading
							? 'bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:bg-gray-700 dark:hover:bg-gray-100'
							: 'bg-gray-200 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'}"
					disabled={selectedCount === 0 || downloading}
					on:click={handleSelect}
				>
					{#if downloading}
						<Spinner className="size-4" />
						{$i18n.t('Downloading...')}
					{:else}
						{$i18n.t('Select')}
					{/if}
				</button>
			</div>
		</div>
	</div>
</Modal>
