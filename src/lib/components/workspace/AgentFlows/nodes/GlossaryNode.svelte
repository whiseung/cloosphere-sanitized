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
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[200px]
		{selected ? 'border-purple-500 shadow-lg' : 'border-purple-400'}
		bg-purple-50 dark:bg-purple-900/30"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-purple-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-purple-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-purple-700 dark:text-purple-300">
				{$i18n?.t?.('Glossary') || 'Glossary'}
			</div>
			<div class="text-[10px] text-purple-600 dark:text-purple-400 truncate">
				{data?.label || data?.resourceId || $i18n?.t?.('Select Glossary') || 'Select Glossary'}
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

	<Handle
		type="source"
		position={Position.Bottom}
		class="!w-3 !h-3 !bg-purple-500 !border-2 !border-white dark:!border-gray-800"
	/>
</div>

<style>
	.flow-node { transition: all 0.2s ease; }
	.flow-node:hover { transform: translateY(-1px); }
</style>
