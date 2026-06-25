<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	// Node props from @xyflow/svelte
	export let id: string = '';
	export let data: any = {};
	export let selected: boolean = false;
	export let selectable: boolean = true;
	export let deletable: boolean = true;
	export let draggable: boolean = true;
	export let dragging: boolean = false;
	export let dragHandle: string | undefined = undefined;
	export let type: string = '';
	export let zIndex: number = 0;
	export let parentId: string | undefined = undefined;
	export let isConnectable: boolean = true;
	export let positionAbsoluteX: number = 0;
	export let positionAbsoluteY: number = 0;
	export let sourcePosition: string | undefined = undefined;
	export let targetPosition: string | undefined = undefined;
	export let width: number | undefined = undefined;
	export let height: number | undefined = undefined;

	// Route colors for visual distinction
	const routeColors = ['#8b5cf6', '#06b6d4', '#f59e0b', '#ef4444', '#10b981', '#ec4899', '#6366f1', '#14b8a6'];

	$: routes = data?.config?.routes || [];
	$: routingType = data?.config?.routingType || 'rule';
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[200px]
		{selected ? 'border-violet-500 shadow-lg' : 'border-violet-400'}
		bg-violet-50 dark:bg-violet-900/30"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-violet-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-violet-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-violet-700 dark:text-violet-300">
				{data?.label || $i18n?.t?.('Router') || 'Router'}
			</div>
			<div class="text-[10px] text-violet-600 dark:text-violet-400 truncate">
				{routingType === 'llm' ? '🤖 ' : ''}{routes.length || 0} {$i18n?.t?.('routes') || 'routes'}
			</div>
		</div>
	</div>

	{#if routes.length === 0}
		<div class="mt-2 text-[10px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
			<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
			</svg>
			{$i18n?.t?.('No routes configured') || 'No routes configured'}
		</div>
	{:else}
		<!-- Route labels -->
		<div class="mt-2 flex flex-wrap gap-1">
			{#each routes as route, i}
				<span
					class="text-[9px] px-1.5 py-0.5 rounded-full text-white font-medium"
					style="background-color: {routeColors[i % routeColors.length]}"
				>
					{route.label || route.id}
				</span>
			{/each}
		</div>
	{/if}

	<!-- Dynamic output handles based on routes -->
	{#each routes as route, i}
		{@const total = routes.length}
		{@const position = total === 1 ? 50 : (15 + (i * 70) / (total - 1))}
		<Handle
			type="source"
			position={Position.Bottom}
			id={route.id}
			style="left: {position}%; background-color: {routeColors[i % routeColors.length]};"
			class="!w-3 !h-3 !border-2 !border-white dark:!border-gray-800"
		/>
	{/each}

	{#if routes.length === 0}
		<!-- Default single handle when no routes configured -->
		<Handle
			type="source"
			position={Position.Bottom}
			class="!w-3 !h-3 !bg-violet-500 !border-2 !border-white dark:!border-gray-800"
		/>
	{/if}
</div>

<style>
	.flow-node {
		transition: all 0.2s ease;
	}
	.flow-node:hover {
		transform: translateY(-1px);
	}
</style>
