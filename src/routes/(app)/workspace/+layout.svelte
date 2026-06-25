<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import {
		WEBUI_NAME,
		showSidebar,
		functions,
		user,
		userPermissions,
		mobile,
		models,
		prompts,
		knowledge,
		tools,
		config
	} from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	import Tabs from '$lib/components/common/Tabs.svelte';
	import type { TabItem } from '$lib/components/common/Tabs.svelte';
	import MenuLines from '$lib/components/icons/MenuLines.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ToastHistory from '$lib/components/layout/ToastHistory.svelte';
	import GuidePanel from '$lib/components/common/GuidePanel.svelte';

	let showGuidePanel = false;
	import { isMenuVisible } from '$lib/config/menuConfig';
	import { isFeatureAllowed } from '$lib/utils/license';
	import { hasPermission } from '$lib/utils/permissions';
	import { getUserPermissions } from '$lib/apis/users';

	const i18n = getContext<Readable<{ t: (key: string) => string }>>('i18n');

	let loaded = false;

	function createTab(id: string, labelKey: string, href: string, selected: boolean): TabItem {
		return {
			id,
			labelKey,
			href,
			state: selected ? 'selected' : 'default'
		};
	}

	$: workspaceTabs = [
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.agents)) &&
		isMenuVisible('agents')
			? {
					...createTab(
						'agents',
						'Agents',
						'/workspace/agents',
						$page.url.pathname.includes('/workspace/agents')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.agent_flows)) &&
		isMenuVisible('flows') &&
		isFeatureAllowed($config, 'agent_flow')
			? {
					...createTab(
						'flows',
						'Flows',
						'/workspace/flows',
						$page.url.pathname.includes('/workspace/flows')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.knowledge)) &&
		isMenuVisible('knowledge') &&
		isFeatureAllowed($config, 'kbsphere')
			? {
					...createTab(
						'knowledge',
						'Knowledge',
						'/workspace/knowledge',
						$page.url.pathname.includes('/workspace/knowledge') &&
							!$page.url.pathname.includes('/workspace/knowledge-graph')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.databases)) &&
		isMenuVisible('database') &&
		isFeatureAllowed($config, 'dbsphere')
			? {
					...createTab(
						'database',
						'Database',
						'/workspace/database',
						$page.url.pathname.includes('/workspace/database')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.glossaries)) &&
		isMenuVisible('glossary') &&
		isFeatureAllowed($config, 'glossary')
			? {
					...createTab(
						'glossary',
						'Glossary',
						'/workspace/glossary',
						$page.url.pathname.includes('/workspace/glossary')
					)
				}
			: null,
		($user?.role === 'admin' ||
			hasPermission($userPermissions?.workspace?.knowledge_graphs)) &&
		isMenuVisible('knowledge-graph') &&
		isFeatureAllowed($config, 'knowledge_graph')
			? {
					...createTab(
						'knowledge-graph',
						'Knowledge Graph',
						'/workspace/knowledge-graph',
						$page.url.pathname.includes('/workspace/knowledge-graph')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.guardrails)) &&
		isMenuVisible('guardrails') &&
		isFeatureAllowed($config, 'guardrail')
			? {
					...createTab(
						'guardrails',
						'Guardrails',
						'/workspace/guardrails',
						$page.url.pathname.includes('/workspace/guardrails')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.prompts)) &&
		isMenuVisible('prompts')
			? {
					...createTab(
						'prompts',
						'Prompts',
						'/workspace/prompts',
						$page.url.pathname.includes('/workspace/prompts')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.tools)) &&
		isMenuVisible('tools') &&
		isFeatureAllowed($config, 'tools')
			? {
					...createTab(
						'tools',
						'Tools',
						'/workspace/tools',
						$page.url.pathname.includes('/workspace/tools')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.marketplace)) &&
		isMenuVisible('marketplace')
			? {
					...createTab(
						'marketplace',
						'Marketplace',
						'/workspace/marketplace',
						$page.url.pathname.includes('/workspace/marketplace')
					)
				}
			: null,
		($user?.role === 'admin' || hasPermission($userPermissions?.workspace?.tags)) &&
		isMenuVisible('tags')
			? {
					...createTab(
						'tags',
						'Tags',
						'/workspace/tags',
						$page.url.pathname.includes('/workspace/tags')
					)
				}
			: null
	].filter((tab): tab is TabItem => tab !== null);

	onMount(async () => {
		// 권한 stale 방지: admin 이 그룹/default 권한을 변경해도 로그인 캐시된 store 가
		// 갱신되지 않아 탭이 잘못 노출/숨겨지는 문제. 워크스페이스 진입 시마다 fresh fetch.
		// fresh 결과를 가드에 **직접** 사용 (store reactive 전파 타이밍 회피).
		let perms: any = $userPermissions;
		try {
			const fresh = await getUserPermissions(localStorage.token);
			if (fresh) {
				userPermissions.set(fresh);
				perms = fresh;
			}
		} catch (e) {
			console.error('Failed to refresh user permissions:', e);
		}

		if ($user?.role !== 'admin') {
			if (
				$page.url.pathname.includes('/agents') &&
				!hasPermission(perms?.workspace?.agents)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/knowledge') &&
				!$page.url.pathname.includes('/knowledge-graph') &&
				!hasPermission(perms?.workspace?.knowledge)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/prompts') &&
				!hasPermission(perms?.workspace?.prompts)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/tools') &&
				!hasPermission(perms?.workspace?.tools)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/database') &&
				!hasPermission(perms?.workspace?.databases)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/glossary') &&
				!hasPermission(perms?.workspace?.glossaries)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/knowledge-graph') &&
				(!hasPermission(perms?.workspace?.knowledge_graphs) ||
					!isMenuVisible('knowledge-graph') ||
					!isFeatureAllowed($config, 'knowledge_graph'))
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/guardrails') &&
				!hasPermission(perms?.workspace?.guardrails)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/flows') &&
				(!hasPermission(perms?.workspace?.agent_flows) ||
					!isMenuVisible('flows') ||
					!isFeatureAllowed($config, 'agent_flow'))
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/tags') &&
				!hasPermission(perms?.workspace?.tags)
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/marketplace') &&
				(!hasPermission(perms?.workspace?.marketplace) ||
					!isMenuVisible('marketplace'))
			) {
				goto('/');
			}
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Workspace')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class="workspace-page-shell relative transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-260px)]'
			: ''} max-w-full"
	>
		<!-- Page Header -->
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
				{$i18n.t('Workspace')}
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

		<!-- Tab Navigation — Figma 1305:12301 (underline variant) -->
		<nav class="px-8 backdrop-blur-xl drag-region border-b border-[var(--cloo-border-subtle)]">
			<Tabs
				ariaLabel={$i18n.t('Workspace navigation tabs')}
				items={workspaceTabs}
				variant="underline"
			/>
		</nav>

		<div class="workspace-page-content" id="workspace-container">
			<slot />
		</div>
	</div>
{/if}

<GuidePanel bind:show={showGuidePanel} />
