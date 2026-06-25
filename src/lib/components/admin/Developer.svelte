<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';

	import Locales from './Developer/Locales.svelte';
	import LicenseManagement from './Developer/LicenseManagement.svelte';
	import WorkManagement from './Developer/WorkManagement.svelte';
	import { getCloocusStatus } from '$lib/apis/cloocus';

	const i18n = getContext('i18n');

	let selectedTab = 'locales';
	let loaded = false;
	let cloocusAvailable = false;

	onMount(async () => {
		if ($user?.role !== 'admin') {
			await goto('/');
		}

		// Cloocus DB 연결 여부 확인 후 탭 결정 (loaded 이전에 실행)
		try {
			await getCloocusStatus(localStorage.token);
			cloocusAvailable = true;
			selectedTab = 'license_management';
		} catch {
			cloocusAvailable = false;
			selectedTab = 'locales';
		}

		loaded = true;

		const containerElement = document.getElementById('developer-tabs-container');

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
			id="developer-tabs-container"
			class="flex flex-row overflow-x-auto gap-2.5 max-w-full lg:gap-1 lg:flex-col lg:flex-none lg:w-40 dark:text-gray-200 text-sm font-medium text-left scrollbar-none"
		>
			{#if cloocusAvailable}
				<button
					class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
					'license_management'
						? ''
						: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
					on:click={() => {
						selectedTab = 'license_management';
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
								d="M8 1a2 2 0 0 1 2 2v1h1.5A1.5 1.5 0 0 1 13 5.5v8A1.5 1.5 0 0 1 11.5 15h-7A1.5 1.5 0 0 1 3 13.5v-8A1.5 1.5 0 0 1 4.5 4H6V3a2 2 0 0 1 2-2Zm0 1.5a.5.5 0 0 0-.5.5v1h1V3a.5.5 0 0 0-.5-.5ZM6 5.5H4.5v8h7v-8H10v.75a.75.75 0 0 1-1.5 0V5.5h-1v.75a.75.75 0 0 1-1.5 0V5.5Z"
								clip-rule="evenodd"
							/>
						</svg>
					</div>
					<div class="self-center">{$i18n.t('License Management')}</div>
				</button>

				<button
					class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
					'work_management'
						? ''
						: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
					on:click={() => {
						selectedTab = 'work_management';
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
								d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z"
								clip-rule="evenodd"
							/>
						</svg>
					</div>
					<div class="self-center">{$i18n.t('Work Management')}</div>
				</button>
			{/if}

			<button
				class="px-0.5 py-1 min-w-fit rounded-lg lg:flex-none flex text-right transition {selectedTab ===
				'locales'
					? ''
					: ' text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'}"
				on:click={() => {
					selectedTab = 'locales';
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
							d="M11 5a.75.75 0 0 1 .688.452l3.25 7.5a.75.75 0 1 1-1.376.596L12.89 12H9.109l-.67 1.548a.75.75 0 1 1-1.377-.596l3.25-7.5A.75.75 0 0 1 11 5Zm-1.24 5.5h2.48L11 7.636 9.76 10.5ZM5 1a.75.75 0 0 1 .75.75v1.261a25.27 25.27 0 0 1 2.598.211.75.75 0 1 1-.196 1.487A25.334 25.334 0 0 0 5.75 4.5V5a.75.75 0 0 1-1.5 0v-.5A25.334 25.334 0 0 0 1.848 4.71a.75.75 0 1 1-.196-1.487c.856-.113 1.72-.194 2.598-.211V1.75A.75.75 0 0 1 5 1Zm-.25 6.5a.75.75 0 0 1 .75-.75h.01a.75.75 0 0 1 0 1.5H5.5a.75.75 0 0 1-.75-.75ZM5 9.25a.75.75 0 0 0 0 1.5h.01a.75.75 0 0 0 0-1.5H5Zm-.75 3.25a.75.75 0 0 1 .75-.75h.01a.75.75 0 0 1 0 1.5H5a.75.75 0 0 1-.75-.75ZM2.5 7.5a.75.75 0 0 0 0 1.5h.01a.75.75 0 0 0 0-1.5H2.5Zm-.75 3.25a.75.75 0 0 1 .75-.75h.01a.75.75 0 0 1 0 1.5H2.5a.75.75 0 0 1-.75-.75ZM2.5 13a.75.75 0 0 0 0 1.5h.01a.75.75 0 0 0 0-1.5H2.5Z"
							clip-rule="evenodd"
						/>
					</svg>
				</div>
				<div class="self-center">{$i18n.t('Locale Management')}</div>
			</button>
		</div>

		<div class="flex-1 overflow-y-auto pt-3 lg:pt-0">
			{#if selectedTab === 'locales'}
				<Locales />
			{:else if selectedTab === 'license_management'}
				<LicenseManagement />
			{:else if selectedTab === 'work_management'}
				<WorkManagement />
			{/if}
		</div>
	</div>
{/if}
