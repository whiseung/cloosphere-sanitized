<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import type { Readable } from 'svelte/store';

	import Tabs from '$lib/components/common/Tabs.svelte';
	import type { TabItem } from '$lib/components/common/Tabs.svelte';
	import { WEBUI_NAME, showSidebar, user, userPermissions } from '$lib/stores';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import { page } from '$app/stores';
	import { isMenuVisible } from '$lib/config/menuConfig';
	import { hasPermission } from '$lib/utils/permissions';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ToastHistory from '$lib/components/layout/ToastHistory.svelte';
	import GuidePanel from '$lib/components/common/GuidePanel.svelte';

	let showGuidePanel = false;

	const i18n = getContext<Readable<{ t: (key: string) => string }>>('i18n');

	let loaded = false;

	// Check if user is admin or has specific admin permission
	$: isAdmin = $user?.role === 'admin';

	// Define all admin tabs with their configuration
	// isMenuVisible is automatically applied to all tabs
	type AdminTab = {
		id: string;
		label: string;
		href: string;
		pathMatch: (p: string) => boolean;
		permissionKey?: string; // key in $userPermissions.admin, undefined = admin only
	};

	const allTabs: AdminTab[] = [
		{
			id: 'users',
			label: 'Users',
			href: '/admin',
			pathMatch: (p: string) => p === '/admin' || p === '/admin/users',
			permissionKey: 'users'
		},
		{
			id: 'evaluations',
			label: 'Evaluations',
			href: '/admin/evaluations',
			pathMatch: (p: string) => p.includes('/admin/evaluations'),
			permissionKey: 'evaluations'
		},
		{
			id: 'functions',
			label: 'Functions',
			href: '/admin/functions',
			pathMatch: (p: string) => p.includes('/admin/functions'),
			permissionKey: 'functions'
		},
		{
			id: 'settings',
			label: 'Settings',
			href: '/admin/settings',
			pathMatch: (p: string) => p.includes('/admin/settings'),
			permissionKey: 'settings'
		},
		{
			id: 'monitoring',
			label: 'Monitoring',
			href: '/admin/monitoring',
			pathMatch: (p: string) => p.includes('/admin/monitoring'),
			permissionKey: 'monitoring'
		},
		{
			id: 'developer',
			label: 'Developer Mode',
			href: '/admin/developer',
			pathMatch: (p: string) => p.includes('/admin/developer')
			// no permissionKey = admin only
		}
	];

	// Filter tabs by menu visibility and permission
	// New tabs only need to be added to allTabs array - isMenuVisible is auto-applied
	$: adminPermissions = ($userPermissions?.admin ?? {}) as Record<string, string | null | undefined>;
	$: visibleTabs = allTabs.filter((tab) => {
		if (!isMenuVisible(tab.id)) return false;
		if (isAdmin) return true;
		if (tab.permissionKey && hasPermission(adminPermissions[tab.permissionKey])) return true;
		return false;
	});

	// Check if user has any admin access
	$: hasAnyAdminAccess = visibleTabs.length > 0;
	$: adminTabs = visibleTabs.map<TabItem>((tab) => ({
		id: tab.id,
		labelKey: tab.label,
		href: tab.href,
		state: tab.pathMatch($page.url.pathname) ? 'selected' : 'default'
	}));

	// Get the first available tab
	function getFirstAvailableTab(): string {
		return visibleTabs.length > 0 ? visibleTabs[0].href : '/';
	}

	// Check if current path is allowed
	function isPathAllowed(pathname: string): boolean {
		return visibleTabs.some((tab) => tab.pathMatch(pathname));
	}

	onMount(async () => {
		// Wait for permissions to load
		await new Promise((resolve) => setTimeout(resolve, 100));

		if (!hasAnyAdminAccess) {
			await goto('/');
			return;
		}

		// Check if current path is allowed
		if (!isPathAllowed($page.url.pathname)) {
			const firstTab = getFirstAvailableTab();
			await goto(firstTab);
			return;
		}

		loaded = true;
	});

	// Watch for route changes and redirect if not allowed
	$: if (loaded && $page.url.pathname) {
		if (!isPathAllowed($page.url.pathname)) {
			const firstTab = getFirstAvailableTab();
			if (firstTab !== '/') {
				goto(firstTab);
			} else {
				goto('/');
			}
		}
	}
</script>

<svelte:head>
	<title>
		{$i18n.t('Admin Panel')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class=" flex flex-col w-full h-screen max-h-[100dvh] bg-[var(--cloo-bg-canvas)] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<!-- Page Header -->
		<div class="admin-page-header">
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
				{$i18n.t('Admin Panel')}
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

		<!-- Tab Navigation — Figma 1305:12303 (underline variant) -->
		<nav class="px-8 backdrop-blur-xl drag-region border-b border-[var(--cloo-border-subtle)]">
			<Tabs
				ariaLabel={$i18n.t('Admin navigation tabs')}
				items={adminTabs}
				variant="underline"
			/>
		</nav>

		<div class="pb-1 px-8 pt-2 flex-1 max-h-full overflow-y-auto">
			<slot />
		</div>
	</div>
{/if}

<GuidePanel bind:show={showGuidePanel} />

<style>
	.admin-page-header {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
		padding: 20px 32px 8px;
	}
</style>
