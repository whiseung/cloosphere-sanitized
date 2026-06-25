<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { showArchivedChats, showSidebar, user } from '$lib/stores';

	import { slide } from 'svelte/transition';
	import { page } from '$app/stores';

	import MenuLines from '../icons/MenuLines.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ToastHistory from '$lib/components/layout/ToastHistory.svelte';
	import GuidePanel from '$lib/components/common/GuidePanel.svelte';

	const i18n = getContext('i18n');

	export let channel;

	let showGuidePanel = false;
</script>

<nav class="sticky top-0 z-30 w-full px-1.5 py-1.5 -mb-8 flex items-center drag-region">
	<div
		class=" bg-linear-to-b via-50% from-white via-white to-transparent dark:from-gray-900 dark:via-gray-900 dark:to-transparent pointer-events-none absolute inset-0 -bottom-7 z-[-1]"
	></div>

	<div class=" flex max-w-full w-full mx-auto px-1 pt-0.5 bg-transparent">
		<div class="flex items-center w-full max-w-full">
			<div
				class="md:hidden mr-1 self-start flex flex-none items-center text-gray-600 dark:text-gray-400"
			>
				<button
					id="sidebar-toggle-button"
					class="cursor-pointer px-2 py-2 flex rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
					on:click={() => {
						showSidebar.set(!$showSidebar);
					}}
					aria-label="Toggle Sidebar"
				>
					<div class=" m-auto self-center">
						<MenuLines />
					</div>
				</button>
			</div>

			<div
				class="flex-1 overflow-hidden max-w-full py-0.5
			{$showSidebar ? 'ml-1' : ''}
			"
			>
				{#if channel}
					<div class="line-clamp-1 capitalize font-medium font-primary text-lg">
						{channel.name}
					</div>
				{/if}
			</div>

			<div class="self-start flex flex-none items-center text-gray-600 dark:text-gray-400">
				<Tooltip content={$i18n.t('Guide Q&A')}>
					<button
						class="flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						on:click={() => (showGuidePanel = !showGuidePanel)}
						aria-label={$i18n.t('Guide Q&A')}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
							<path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM8.94 6.94a.75.75 0 1 1-1.061-1.061 3 3 0 1 1 2.871 5.026v.345a.75.75 0 0 1-1.5 0v-.5c0-.72.57-1.172 1.081-1.287A1.5 1.5 0 1 0 8.94 6.94ZM10 15a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd" />
						</svg>
					</button>
				</Tooltip>

				<ToastHistory />
			</div>
		</div>
	</div>
</nav>

<GuidePanel bind:show={showGuidePanel} />
