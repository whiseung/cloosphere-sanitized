<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import type { MenuItem } from '$lib/config/menuConfig';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	// Props
	export let items: MenuItem[] = [];
	export let selectedId: string = '';
	export let containerId: string = 'tabs-container';

	// 탭 클릭 핸들러
	function handleClick(item: MenuItem) {
		selectedId = item.id;
		dispatch('select', { id: item.id, item });
	}

	// 스타일 클래스
	const baseClass =
		'tabs flex flex-row overflow-x-auto gap-2.5 max-w-full lg:gap-1 lg:flex-col lg:flex-none lg:w-40 dark:text-gray-200 text-sm font-medium text-left scrollbar-none';
	const itemClass = 'px-0.5 py-1 min-w-fit rounded-lg flex-1 lg:flex-none flex text-left transition';
	const activeClass = '';
	const inactiveClass = 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white';
</script>

<div id={containerId} class={baseClass}>
	{#each items as item (item.id)}
		<button
			class="{itemClass} {selectedId === item.id ? activeClass : inactiveClass}"
			on:click={() => handleClick(item)}
		>
			{#if $$slots.icon}
				<div class="self-center mr-2">
					<slot name="icon" {item} id={item.id} />
				</div>
			{/if}
			<div class="self-center">{$i18n.t(item.labelKey)}</div>
		</button>
	{/each}
</div>
