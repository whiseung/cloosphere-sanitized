<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { user, WEBUI_NAME } from '$lib/stores';
	import { getSharedDashboard } from '$lib/apis/bi-dashboards';
	import SharedDashboardView from '$lib/components/admin/Monitoring/BiDashboard/SharedDashboardView.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let dashboard: any = null;
	let error = '';

	onMount(async () => {
		if (!$user) {
			await goto(`/auth?redirect=/dashboard/${$page.params.id}`);
			return;
		}
		try {
			dashboard = await getSharedDashboard(localStorage.token, $page.params.id);
			loaded = true;
		} catch (e: any) {
			error = e?.detail || $i18n.t('Dashboard not found or access denied');
		}
	});
</script>

<svelte:head>
	<title>{dashboard?.name || $i18n.t('Shared Dashboard')} | {$WEBUI_NAME}</title>
</svelte:head>

{#if loaded && dashboard}
	<SharedDashboardView {dashboard} shareId={$page.params.id} />
{:else if error}
	<div class="flex flex-col items-center justify-center h-screen bg-white dark:bg-gray-950">
		<div class="text-center">
			<div class="text-6xl mb-4">🔒</div>
			<h1 class="text-xl font-semibold dark:text-gray-100 mb-2">{$i18n.t('Access Denied')}</h1>
			<p class="text-gray-500 dark:text-gray-400 mb-6">{error}</p>
			<Button kind="filled" size="md" on:click={() => goto('/')}>
				{$i18n.t('Go Home')}
			</Button>
		</div>
	</div>
{:else}
	<div class="flex items-center justify-center h-screen bg-white dark:bg-gray-950">
		<Spinner className="size-8" />
	</div>
{/if}
