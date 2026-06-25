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
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[200px]
		{selected ? 'border-green-500 shadow-lg' : 'border-green-400'}
		bg-green-50 dark:bg-green-900/30"
>
	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center">
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
				<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
				<polyline points="17 8 12 3 7 8" />
				<line x1="12" y1="3" x2="12" y2="15" />
			</svg>
		</div>
		<div>
			<div class="text-xs font-semibold text-green-700 dark:text-green-300">
				Start
			</div>
			<div class="text-[10px] text-green-600 dark:text-green-400">
				{$i18n?.t?.('Flow Start') || 'Flow Start'}
			</div>
		</div>
	</div>

	<Handle
		type="source"
		position={Position.Bottom}
		class="!w-3 !h-3 !bg-green-500 !border-2 !border-white dark:!border-gray-800"
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
