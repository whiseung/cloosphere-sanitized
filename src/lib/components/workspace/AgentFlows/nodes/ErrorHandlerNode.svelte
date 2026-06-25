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
		{selected ? 'border-rose-500 shadow-lg' : 'border-rose-400'}
		bg-rose-50 dark:bg-rose-900/30"
>
	<Handle type="target" position={Position.Top} class="!w-3 !h-3 !bg-rose-500 !border-2 !border-white dark:!border-gray-800" />

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-rose-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-rose-700 dark:text-rose-300">
				{$i18n?.t?.('Error Handler') || 'Error Handler'}
			</div>
			<div class="text-[10px] text-rose-600 dark:text-rose-400 truncate">
				{data?.label || $i18n?.t?.('Handle Failures') || 'Handle Failures'}
			</div>
		</div>
	</div>

	<div class="flex justify-between mt-2 text-[9px]">
		<div class="flex items-center gap-1 text-rose-600 dark:text-rose-400">
			<div class="w-2 h-2 rounded-full bg-rose-500"></div>
			{$i18n?.t?.('Retry') || 'Retry'}
		</div>
		<div class="flex items-center gap-1 text-amber-600 dark:text-amber-400">
			{$i18n?.t?.('Fallback') || 'Fallback'}
			<div class="w-2 h-2 rounded-full bg-amber-500"></div>
		</div>
	</div>

	<Handle type="source" position={Position.Bottom} id="retry" style="left: 25%;" class="!w-3 !h-3 !bg-rose-500 !border-2 !border-white dark:!border-gray-800" />
	<Handle type="source" position={Position.Bottom} id="fallback" style="left: 75%;" class="!w-3 !h-3 !bg-amber-500 !border-2 !border-white dark:!border-gray-800" />
</div>

<style>
	.flow-node { transition: all 0.2s ease; }
	.flow-node:hover { transform: translateY(-1px); }
</style>
