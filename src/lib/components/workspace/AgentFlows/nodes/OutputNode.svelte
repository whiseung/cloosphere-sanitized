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

	$: actionType = data?.config?.actionType || 'passthrough';
	$: usePrompt = data?.config?.usePrompt || false;

	const actionIcons: Record<string, string> = {
		passthrough: '➡️',
		response: '💬',
		error: '⚠️'
	};

	// Action label keys for i18n
	const actionLabelKeys: Record<string, string> = {
		passthrough: 'Passthrough',
		response: 'Generate Response',
		error: 'Return Error'
	};
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[200px]
		{selected ? 'border-emerald-500 shadow-lg' : 'border-emerald-400'}
		{actionType === 'error' ? 'bg-orange-50 dark:bg-orange-900/30' : 'bg-emerald-50 dark:bg-emerald-900/30'}"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-emerald-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full {actionType === 'error' ? 'bg-orange-500' : 'bg-emerald-500'} flex items-center justify-center">
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
				<polyline points="7 10 12 15 17 10" />
				<line x1="12" y1="15" x2="12" y2="3" />
			</svg>
		</div>
		<div>
			<div class="text-xs font-semibold {actionType === 'error' ? 'text-orange-700 dark:text-orange-300' : 'text-emerald-700 dark:text-emerald-300'}">
				{$i18n.t('Output')}
			</div>
			<div class="text-[10px] {actionType === 'error' ? 'text-orange-600 dark:text-orange-400' : 'text-emerald-600 dark:text-emerald-400'}">
				{actionIcons[actionType]} {$i18n.t(actionLabelKeys[actionType] || 'Flow End')}
			</div>
		</div>
	</div>

	{#if usePrompt && actionType === 'response'}
		<div class="mt-2 pt-2 border-t border-emerald-200 dark:border-emerald-700">
			<div class="text-[10px] text-emerald-500 dark:text-emerald-400 truncate">
				📝 {$i18n.t('Using Prompt')}
			</div>
		</div>
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
