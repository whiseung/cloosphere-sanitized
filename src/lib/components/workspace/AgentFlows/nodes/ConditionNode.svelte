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
	class="flow-node condition-node px-4 py-3 rounded-xl border-2 min-w-[180px]
		{selected ? 'border-amber-500 shadow-lg' : 'border-amber-400'}
		bg-amber-50 dark:bg-amber-900/30"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-amber-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-amber-500 flex items-center justify-center">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="w-4 h-4 text-white"
			>
				<path d="m16 3 4 4-4 4" />
				<path d="M20 7H4" />
				<path d="m8 21-4-4 4-4" />
				<path d="M4 17h16" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-amber-700 dark:text-amber-300">
				{$i18n?.t?.('Condition') || 'Condition'}
			</div>
			<div class="text-[10px] text-amber-600 dark:text-amber-400 truncate">
				{data?.config?.conditionType || $i18n?.t?.('Configure condition') || 'Configure condition'}
			</div>
		</div>
	</div>

	<div class="flex justify-between mt-2 text-[9px]">
		<div class="flex items-center gap-1 text-green-600 dark:text-green-400">
			<div class="w-2 h-2 rounded-full bg-green-500"></div>
			{$i18n?.t?.('True') || 'True'}
		</div>
		<div class="flex items-center gap-1 text-red-600 dark:text-red-400">
			{$i18n?.t?.('False') || 'False'}
			<div class="w-2 h-2 rounded-full bg-red-500"></div>
		</div>
	</div>

	<Handle
		type="source"
		position={Position.Bottom}
		id="true"
		style="left: 25%;"
		class="!w-3 !h-3 !bg-green-500 !border-2 !border-white dark:!border-gray-800"
	/>
	<Handle
		type="source"
		position={Position.Bottom}
		id="false"
		style="left: 75%;"
		class="!w-3 !h-3 !bg-red-500 !border-2 !border-white dark:!border-gray-800"
	/>
</div>

<style>
	.flow-node {
		transition: all 0.2s ease;
	}
	.flow-node:hover {
		transform: translateY(-1px);
	}
</style>
