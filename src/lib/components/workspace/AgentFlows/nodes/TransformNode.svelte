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

	$: transformType = data?.config?.transformType || 'extract';

	function getTransformTypeLabel(type: string): string {
		const labels: Record<string, string> = {
			extract: $i18n?.t?.('Extract Field') || 'Extract Field',
			format: $i18n?.t?.('Format Text') || 'Format Text'
		};
		return labels[type] || labels.extract;
	}

	function getTransformIcon(type: string): string {
		switch (type) {
			case 'format': return 'M4 6h16M4 12h16m-7 6h7';
			default: return 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2';
		}
	}

	$: description = (() => {
		if (data?.config?.useAdvanced && data?.config?.template) {
			return data.config.template.substring(0, 25) + (data.config.template.length > 25 ? '...' : '');
		}
		switch (transformType) {
			case 'format':
				return data?.config?.formatTemplate?.substring(0, 25) || $i18n?.t?.('No template') || 'No template';
			default:
				return data?.config?.sourceField || $i18n?.t?.('No field selected') || 'No field selected';
		}
	})();
</script>

<div
	class="flow-node transform-node px-4 py-3 rounded-xl border-2 min-w-[180px]
		{selected ? 'border-cyan-500 shadow-lg' : 'border-cyan-400'}
		bg-cyan-50 dark:bg-cyan-900/30"
>
	<Handle
		type="target"
		position={Position.Top}
		class="!w-3 !h-3 !bg-cyan-500 !border-2 !border-white dark:!border-gray-800"
	/>

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-cyan-500 flex items-center justify-center">
			<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={getTransformIcon(transformType)} />
			</svg>
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-cyan-700 dark:text-cyan-300">
				{$i18n?.t?.('Transform') || 'Transform'}
			</div>
			<div class="text-[10px] text-cyan-600 dark:text-cyan-400 truncate">
				{getTransformTypeLabel(transformType)}
			</div>
		</div>
	</div>

	<div class="mt-2 text-[9px] bg-cyan-100 dark:bg-cyan-900/50 rounded px-2 py-1 truncate text-cyan-600 dark:text-cyan-400">
		{description}
	</div>

	<Handle
		type="source"
		position={Position.Bottom}
		class="!w-3 !h-3 !bg-cyan-500 !border-2 !border-white dark:!border-gray-800"
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
