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
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[180px]
		{selected ? 'border-fuchsia-500 shadow-lg' : 'border-fuchsia-400'}
		bg-fuchsia-50 dark:bg-fuchsia-900/30"
>
	<Handle type="target" position={Position.Top} class="!w-3 !h-3 !bg-fuchsia-500 !border-2 !border-white dark:!border-gray-800" />

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-fuchsia-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-fuchsia-700 dark:text-fuchsia-300">
				{$i18n?.t?.('Subflow') || 'Subflow'}
			</div>
			<div class="text-[10px] text-fuchsia-600 dark:text-fuchsia-400 truncate">
				{data?.label || data?.resourceId || $i18n?.t?.('Select Flow') || 'Select Flow'}
			</div>
		</div>
	</div>

	{#if !data?.resourceId}
		<div class="mt-2 text-[10px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
			<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
			</svg>
			{$i18n?.t?.('Not configured') || 'Not configured'}
		</div>
	{/if}

	<Handle type="source" position={Position.Bottom} class="!w-3 !h-3 !bg-fuchsia-500 !border-2 !border-white dark:!border-gray-800" />
</div>

<style>
	.flow-node { transition: all 0.2s ease; }
	.flow-node:hover { transform: translateY(-1px); }
</style>
