<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import DashboardView from './DashboardView.svelte';
	import { getDashboards, createDashboard, deleteDashboard } from '$lib/apis/bi-dashboards';
	import type { BiDashboard } from '$lib/apis/bi-dashboards';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	let dashboards: BiDashboard[] = [];
	let loading = true;
	let selectedDashboardId: string | null = null;

	// Create modal
	let showCreateModal = false;
	let createName = '';
	let createDescription = '';
	let creating = false;

	onMount(async () => {
		await loadDashboards();
	});

	async function loadDashboards() {
		loading = true;
		try {
			dashboards = await getDashboards(localStorage.token);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load dashboards'));
		} finally {
			loading = false;
		}
	}

	function openCreateModal() {
		showCreateModal = true;
		createName = '';
		createDescription = '';
	}

	async function handleCreate() {
		if (!createName.trim()) {
			toast.error($i18n.t('Dashboard name is required'));
			return;
		}
		creating = true;
		try {
			const dashboard = await createDashboard(localStorage.token, {
				name: createName,
				description: createDescription
			});
			showCreateModal = false;
			createName = '';
			createDescription = '';
			selectedDashboardId = dashboard.id;
			await loadDashboards();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to create dashboard'));
		} finally {
			creating = false;
		}
	}

	async function handleDelete(id: string) {
		if (!confirm($i18n.t('Are you sure you want to delete this dashboard?'))) return;
		try {
			await deleteDashboard(localStorage.token, id);
			await loadDashboards();
			toast.success($i18n.t('Dashboard deleted'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete dashboard'));
		}
	}

	function formatDate(ts: number) {
		return new Date(ts * 1000).toLocaleDateString('ko-KR', {
			year: 'numeric',
			month: '2-digit',
			day: '2-digit'
		});
	}
</script>

{#if selectedDashboardId}
	<DashboardView
		dashboardId={selectedDashboardId}
		on:back={() => {
			selectedDashboardId = null;
			loadDashboards();
		}}
	/>
{:else}
	<div class="flex flex-col gap-4">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<h2 class="text-lg font-semibold dark:text-gray-100">
				{$i18n.t('Dashboards')}
			</h2>
			<Button kind="filled" size="sm" on:click={openCreateModal}>
				<svelte:fragment slot="prefix">
					<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" viewBox="0 0 20 20" fill="currentColor">
						<path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
					</svg>
				</svelte:fragment>
				{$i18n.t('Create Dashboard')}
			</Button>
		</div>

		<!-- Dashboard List -->
		{#if loading}
			<div class="flex items-center justify-center h-48">
				<Spinner className="size-6" />
			</div>
		{:else if dashboards.length === 0}
			<div
				class="flex flex-col items-center justify-center h-48 text-gray-400 dark:text-gray-500 gap-3"
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="size-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
					<path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5" />
				</svg>
				<p class="text-sm">{$i18n.t('No dashboards yet')}</p>
			</div>
		{:else}
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
				{#each dashboards as dashboard}
					<button
						class="flex flex-col text-left p-4 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl hover:border-gray-300 dark:hover:border-gray-600 transition group"
						on:click={() => (selectedDashboardId = dashboard.id)}
					>
						<div class="flex items-start justify-between w-full">
							<div class="min-w-0">
								<h3 class="font-medium dark:text-gray-200 truncate">{dashboard.name}</h3>
								{#if dashboard.description}
									<p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
										{dashboard.description}
									</p>
								{/if}
							</div>
							<button
								class="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 dark:hover:bg-red-900/20 transition text-gray-400 hover:text-red-500"
								on:click|stopPropagation={() => handleDelete(dashboard.id)}
								title={$i18n.t('Delete')}
							>
								<svg xmlns="http://www.w3.org/2000/svg" class="size-4" viewBox="0 0 20 20" fill="currentColor">
									<path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5z" clip-rule="evenodd" />
								</svg>
							</button>
						</div>
						<div class="flex items-center gap-3 mt-3 text-xs text-gray-400 dark:text-gray-500">
							<span>{dashboard.panel_count ?? 0} {$i18n.t('panels')}</span>
							<span>{formatDate(dashboard.updated_at)}</span>
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Create Modal -->
	<Modal bind:show={showCreateModal} size="sm">
		<div class="px-5 py-4">
			<div class="text-lg font-semibold mb-4 dark:text-gray-100">
				{$i18n.t('Create Dashboard')}
			</div>

			<div class="flex flex-col gap-3">
				<Input
					bind:value={createName}
					label={$i18n.t('Name')}
					placeholder={$i18n.t('Dashboard name')}
					size="md"
					required
				/>
				<Input
					bind:value={createDescription}
					label={$i18n.t('Description')}
					placeholder={$i18n.t('Optional description')}
					size="md"
				/>
			</div>

			<p class="text-xs text-gray-400 dark:text-gray-500 mt-3">
				{$i18n.t('You can use the AI Assistant inside the dashboard to generate panels automatically.')}
			</p>

			<div class="flex justify-end gap-2 mt-4">
				<Button kind="outlined" size="md" on:click={() => { showCreateModal = false; }}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={creating} on:click={handleCreate}>
					{$i18n.t('Create')}
				</Button>
			</div>
		</div>
	</Modal>
{/if}
