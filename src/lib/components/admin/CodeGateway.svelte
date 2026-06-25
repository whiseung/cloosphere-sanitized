<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user, userPermissions, config } from '$lib/stores';
	import { hasPermission } from '$lib/utils/permissions';
	import { isMenuVisible } from '$lib/config/menuConfig';
	import { isFeatureAllowed } from '$lib/utils/license';

	import CodeGatewaySettings from '../admin/Settings/CodeGateway.svelte';
	import UsageLogs from './CodeGateway/UsageLogs.svelte';
	import GuardrailLogs from './CodeGateway/GuardrailLogs.svelte';

	import { toast } from 'svelte-sonner';
	import { tick } from 'svelte';
	import { getBackendConfig } from '$lib/apis';

	const i18n = getContext('i18n');

	let selectedTab = 'settings';
	let loaded = false;

	onMount(async () => {
		if (
			$user?.role !== 'admin' &&
			!hasPermission($userPermissions?.admin?.settings)
		) {
			await goto('/');
			return;
		}
		loaded = true;

		const containerElement = document.getElementById('code-gateway-tabs-container');
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
			id="code-gateway-tabs-container"
			class="flex flex-row overflow-x-auto gap-2.5 max-w-full lg:gap-1 lg:flex-col lg:flex-none lg:w-40 dark:text-gray-200 text-sm font-medium text-left scrollbar-none"
		>
			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'settings'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'settings';
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
							d="M6.955 1.45A.5.5 0 0 1 7.452 1h1.096a.5.5 0 0 1 .497.45l.17 1.699c.484.12.94.312 1.356.562l1.321-1.081a.5.5 0 0 1 .67.033l.774.775a.5.5 0 0 1 .034.67l-1.08 1.32c.25.417.44.873.561 1.357l1.699.17a.5.5 0 0 1 .45.497v1.096a.5.5 0 0 1-.45.497l-1.699.17c-.12.484-.312.94-.562 1.356l1.082 1.322a.5.5 0 0 1-.034.67l-.774.774a.5.5 0 0 1-.67.033l-1.322-1.08c-.416.25-.872.44-1.356.561l-.17 1.699a.5.5 0 0 1-.497.45H7.452a.5.5 0 0 1-.497-.45l-.17-1.699a4.973 4.973 0 0 1-1.356-.562L4.108 13.37a.5.5 0 0 1-.67-.033l-.774-.775a.5.5 0 0 1-.034-.67l1.08-1.32a4.971 4.971 0 0 1-.561-1.357l-1.699-.17A.5.5 0 0 1 1 8.548V7.452a.5.5 0 0 1 .45-.497l1.699-.17c.12-.484.312-.94.562-1.356L2.629 4.107a.5.5 0 0 1 .034-.67l.774-.774a.5.5 0 0 1 .67-.033L5.43 3.71a4.97 4.97 0 0 1 1.356-.561l.17-1.699ZM6 8c0 .538.212 1.026.558 1.385l.057.057a2 2 0 0 0 2.828-2.828l-.058-.056A2 2 0 0 0 6 8Z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Settings')}</div>
			</button>

			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'usage-logs'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'usage-logs';
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
				<div class="self-center">{$i18n.t('Usage Logs')}</div>
			</button>

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
		</div>

		<div class="flex-1 overflow-y-auto pt-3 lg:pt-0">
			{#if selectedTab === 'settings'}
				<CodeGatewaySettings
					on:save={async () => {
						toast.success($i18n.t('Settings saved successfully!'));

						await tick();
						await config.set(await getBackendConfig());
					}}
				/>
			{:else if selectedTab === 'usage-logs'}
				<UsageLogs />
			{:else if selectedTab === 'guardrail-logs'}
				<GuardrailLogs />
			{/if}
		</div>
	</div>
{/if}
