<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, user, userPermissions, showSidebar } from '$lib/stores';
	import { goto } from '$app/navigation';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ToastHistory from '$lib/components/layout/ToastHistory.svelte';
	import GuidePanel from '$lib/components/common/GuidePanel.svelte';

	let showGuidePanel = false;

	const i18n = getContext('i18n');

	let loaded = false;

	onMount(async () => {
		if ($user?.role !== 'admin') {
			// sessionUser.permissions가 stale일 수 있으므로 userPermissions 스토어를 fallback
			const featureOn =
				$user?.permissions?.features?.scheduled_tasks ??
				$userPermissions?.features?.scheduled_tasks;
			const workspaceLevel =
				$user?.permissions?.workspace?.schedules ?? $userPermissions?.workspace?.schedules;
			const hasWorkspaceAccess = ['access', 'read', 'write'].includes(workspaceLevel);
			if (!featureOn || !hasWorkspaceAccess) {
				await goto('/');
				return;
			}
		}
		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Schedules')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class="workspace-page-shell relative transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<div class="workspace-page-header">
			<div class="md:hidden self-center flex flex-none items-center">
				<button
					id="sidebar-toggle-button"
					class="cursor-pointer p-1.5 flex rounded-[var(--cloo-radius-default)] hover:bg-[var(--cloo-surface-hover)] transition"
					on:click={() => {
						showSidebar.set(!$showSidebar);
					}}
					aria-label="Toggle Sidebar"
				>
					<div class="m-auto self-center">
						<MenuLines />
					</div>
				</button>
			</div>
			<h1 class="text-2xl font-semibold text-[var(--cloo-text-primary)] flex-1">
				{$i18n.t('Schedules')}
			</h1>
			<div class="flex items-center gap-1">
				<Tooltip content={$i18n.t('Guide Q&A')} placement="bottom">
					<button
						class="p-1.5 rounded-lg hover:bg-[var(--cloo-bg-neutral-hovered)] transition"
						aria-label={$i18n.t('Guide Q&A')}
						on:click={() => (showGuidePanel = !showGuidePanel)}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5 text-[var(--cloo-text-muted)]">
							<path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM8.94 6.94a.75.75 0 1 1-1.061-1.061 3 3 0 1 1 2.871 5.026v.345a.75.75 0 0 1-1.5 0v-.5c0-.72.57-1.172 1.081-1.287A1.5 1.5 0 1 0 8.94 6.94ZM10 15a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
						</svg>
					</button>
				</Tooltip>
				<ToastHistory />
			</div>
		</div>

		<div class="workspace-page-divider" />

		<div class="workspace-page-content schedule-page-content" id="schedules-container">
			<slot />
		</div>
	</div>
{/if}

<GuidePanel bind:show={showGuidePanel} />
