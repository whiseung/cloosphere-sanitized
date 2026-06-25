<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, userPermissions } from '$lib/stores';
	import { hasPermission } from '$lib/utils/permissions';

	import AuditLogs from './Monitoring/AuditLogs.svelte';
	import KmsAuditLogs from './Monitoring/KmsAuditLogs.svelte';
	import GuardrailLogs from './Monitoring/GuardrailLogs.svelte';
	import ConversationLogs from './Monitoring/ConversationLogs.svelte';
	import FileLogs from './Monitoring/FileLogs.svelte';
	import Usage from './Monitoring/Usage.svelte';
	import DashboardList from './Monitoring/BiDashboard/DashboardList.svelte';
	import { isMenuVisible } from '$lib/config/menuConfig';
	import { config } from '$lib/stores';
	import { isFeatureAllowed } from '$lib/utils/license';

	const i18n = getContext('i18n');

	let selectedTab = 'audit-logs';
	let loaded = false;

	onMount(async () => {
		if ($user?.role !== 'admin' && !hasPermission($userPermissions?.admin?.monitoring)) {
			await goto('/');
		}
		loaded = true;

		const containerElement = document.getElementById('monitoring-tabs-container');

		if (containerElement) {
			containerElement.addEventListener('wheel', function (event) {
				if (event.deltaY !== 0) {
					containerElement.scrollLeft += event.deltaY;
				}
			});
		}
	});
</script>

{#if loaded}
	<div class="flex flex-col lg:flex-row w-full h-full pb-2 lg:space-x-4">
		<div
			id="monitoring-tabs-container"
			class="flex flex-row overflow-x-auto gap-2.5 max-w-full lg:gap-1 lg:flex-col lg:flex-none lg:w-40 dark:text-gray-200 text-sm font-medium text-left scrollbar-none"
		>
			{#if isMenuVisible('audit-logs') && isFeatureAllowed($config, 'audit_log')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'audit-logs'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'audit-logs';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							fill-rule="evenodd"
							d="M4.5 1.5a3 3 0 0 0-3 3v7a3 3 0 0 0 3 3h7a3 3 0 0 0 3-3v-7a3 3 0 0 0-3-3h-7Zm.5 4a.5.5 0 0 0 0 1h6a.5.5 0 0 0 0-1H5Zm0 2.5a.5.5 0 0 0 0 1h6a.5.5 0 0 0 0-1H5Zm0 2.5a.5.5 0 0 0 0 1h4a.5.5 0 0 0 0-1H5Z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Audit Logs')}</div>
			</button>
			{/if}

			{#if isMenuVisible('kms-audit-logs') && isFeatureAllowed($config, 'encryption')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'kms-audit-logs'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'kms-audit-logs';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							fill-rule="evenodd"
							d="M8 1a3.5 3.5 0 0 0-3.5 3.5V7H3.75A1.75 1.75 0 0 0 2 8.75v5.5C2 15.216 2.784 16 3.75 16h8.5A1.75 1.75 0 0 0 14 14.25v-5.5A1.75 1.75 0 0 0 12.25 7H11.5V4.5A3.5 3.5 0 0 0 8 1Zm2 6V4.5a2 2 0 1 0-4 0V7h4Zm-2.25 3a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5a.75.75 0 0 1 .75-.75Z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('KMS Audit')}</div>
			</button>
			{/if}

			{#if isMenuVisible('guardrail-logs')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'guardrail-logs'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'guardrail-logs';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							fill-rule="evenodd"
							d="M8 1a3.5 3.5 0 0 0-3.5 3.5V7A1.5 1.5 0 0 0 3 8.5v5A1.5 1.5 0 0 0 4.5 15h7a1.5 1.5 0 0 0 1.5-1.5v-5A1.5 1.5 0 0 0 11.5 7V4.5A3.5 3.5 0 0 0 8 1Zm2 6V4.5a2 2 0 1 0-4 0V7h4Zm-1 2.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Guardrail Logs')}</div>
			</button>
			{/if}

			{#if isMenuVisible('conversation-logs')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'conversation-logs'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'conversation-logs';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							d="M1 8.849c0 1 .738 1.851 1.734 1.947L3 10.82v2.429a.75.75 0 0 0 1.28.53l2.72-2.72H11.5A2.5 2.5 0 0 0 14 8.56V4.5A2.5 2.5 0 0 0 11.5 2h-7A2.5 2.5 0 0 0 2 4.5v4.349Z"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Conversation Logs')}</div>
			</button>
			{/if}

			{#if isMenuVisible('file-logs')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'file-logs'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'file-logs';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							d="M3.5 2A1.5 1.5 0 0 0 2 3.5v9A1.5 1.5 0 0 0 3.5 14h9a1.5 1.5 0 0 0 1.5-1.5v-7A1.5 1.5 0 0 0 12.5 5H7.621a1.5 1.5 0 0 1-1.06-.44L5.439 3.44A1.5 1.5 0 0 0 4.378 3H3.5Z"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('File Logs')}</div>
			</button>
			{/if}

			{#if isMenuVisible('usage')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'usage'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'usage';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							d="M12 2a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1h-1ZM6.5 6a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-1a1 1 0 0 1-1-1V6ZM2 9a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V9Z"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Usage')}</div>
			</button>
			{/if}

			{#if isMenuVisible('dashboards') && isFeatureAllowed($config, 'ai_dashboard')}
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'dashboards'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'dashboards';
				}}
			>
				<div class="self-center mr-2">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path fill-rule="evenodd" d="M4 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4Zm.75 7a.75.75 0 0 0-.75.75v1.5a.75.75 0 0 0 1.5 0v-1.5A.75.75 0 0 0 4.75 9Zm2.5-2a.75.75 0 0 0-.75.75v3.5a.75.75 0 0 0 1.5 0v-3.5A.75.75 0 0 0 7.25 7Zm2.5-2a.75.75 0 0 0-.75.75v5.5a.75.75 0 0 0 1.5 0v-5.5A.75.75 0 0 0 9.75 5Zm2.5 1a.75.75 0 0 0-.75.75v4.5a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-.75-.75Z" clip-rule="evenodd" />
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Dashboards')}</div>
			</button>
			{/if}
		</div>

		<div class="flex-1 overflow-y-auto pt-3 lg:pt-0">
			{#if selectedTab === 'audit-logs'}
				<AuditLogs />
			{:else if selectedTab === 'kms-audit-logs'}
				<KmsAuditLogs />
			{:else if selectedTab === 'guardrail-logs'}
				<GuardrailLogs />
			{:else if selectedTab === 'conversation-logs'}
				<ConversationLogs />
			{:else if selectedTab === 'file-logs'}
				<FileLogs />
			{:else if selectedTab === 'usage'}
				<Usage />
			{:else if selectedTab === 'dashboards'}
				<DashboardList />
			{/if}
		</div>
	</div>
{/if}
