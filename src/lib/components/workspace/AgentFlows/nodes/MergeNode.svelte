<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

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

	$: mergeType = data?.config?.mergeType || 'concat';
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[200px]
		{selected ? 'border-teal-500 shadow-lg' : 'border-teal-400'}
		bg-teal-50 dark:bg-teal-900/30"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-teal-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-teal-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-teal-700 dark:text-teal-300">
				{data?.label || $i18n?.t?.('Merge') || 'Merge'}
			</div>
			<div class="text-[10px] text-teal-600 dark:text-teal-400 truncate">
				{mergeType === 'template' ? '📝 Template' : mergeType === 'json' ? '{ } JSON' : '📋 Concat'}
			</div>
		</div>
	</div>

	<Handle
		type="source"
		position={Position.Bottom}
		class="!w-3 !h-3 !bg-teal-500 !border-2 !border-white dark:!border-gray-800"
	/>
</div>

<style>
	.flow-node { transition: all 0.2s ease; }
	.flow-node:hover { transform: translateY(-1px); }
</style>
