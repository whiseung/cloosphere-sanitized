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

	$: modelName = data?.config?.modelId?.split('/').pop() || data?.config?.modelId || '';
	$: hasSystemPrompt = !!data?.config?.systemPrompt;
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[180px]
		{selected ? 'border-indigo-500 shadow-lg' : 'border-indigo-400'}
		bg-indigo-50 dark:bg-indigo-900/30"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-indigo-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-indigo-700 dark:text-indigo-300">
				{$i18n?.t?.('Model') || 'Model'}
			</div>
			<div class="text-[10px] text-indigo-600 dark:text-indigo-400 truncate">
				{#if modelName}
					{modelName}
				{:else}
					{$i18n?.t?.('Select model') || 'Select model'}
				{/if}
			</div>
		</div>
		{#if hasSystemPrompt}
			<div class="w-2 h-2 rounded-full bg-indigo-500" title={$i18n?.t?.('Has system prompt')}></div>
		{/if}
	</div>

	<Handle
		type="source"
		position={Position.Bottom}
		class="!w-3 !h-3 !bg-indigo-500 !border-2 !border-white dark:!border-gray-800"
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
