<script lang="ts">
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { writable } from 'svelte/store';
	import { browser } from '$app/environment';
	import { theme, user } from '$lib/stores';
	const i18n = getContext('i18n');
	import {
		SvelteFlow,
		Background,
		Controls,
		MiniMap,
		BackgroundVariant,
		type Node,
		type Edge,
		type OnConnect
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';

	import type { FlowData, FlowNode, FlowEdge } from '$lib/apis/agent-flows';

	let mounted = false;
	let flowContainer: HTMLDivElement;
	let flowInstance: any = null;

	onMount(() => {
		mounted = true;
	});

	function handleFlowInit(event: CustomEvent) {
		flowInstance = event.detail;
	}

	// Node components
	import InputNode from './nodes/InputNode.svelte';
	import OutputNode from './nodes/OutputNode.svelte';
	import AgentNode from './nodes/AgentNode.svelte';
	import ModelNode from './nodes/ModelNode.svelte';
	import ConditionNode from './nodes/ConditionNode.svelte';
	import TransformNode from './nodes/TransformNode.svelte';
	import GuardrailNode from './nodes/GuardrailNode.svelte';
	import RouterNode from './nodes/RouterNode.svelte';
	import MergeNode from './nodes/MergeNode.svelte';
	import GlossaryNode from './nodes/GlossaryNode.svelte';

	const dispatch = createEventDispatcher();

	// Props
	export let flowData: FlowData | null = null;
	export let readonly: boolean = false;

	// Define node types (avoid reserved names 'input' and 'output')
	const nodeTypes = {
		flowInput: InputNode,
		flowOutput: OutputNode,
		agent: AgentNode,
		model: ModelNode,
		condition: ConditionNode,
		router: RouterNode,
		merge: MergeNode,
		glossary: GlossaryNode,
		transform: TransformNode,
		guardrail: GuardrailNode
	};

	// Reactive flow state
	const nodes = writable<Node[]>([]);
	const edges = writable<Edge[]>([]);

	// Selected node for config panel
	let selectedNode: Node | null = null;
	let selectedEdgeId: string | null = null;

	// Undo/Redo history
	let undoStack: Array<{ nodes: Node[]; edges: Edge[] }> = [];
	let redoStack: Array<{ nodes: Node[]; edges: Edge[] }> = [];
	const MAX_HISTORY = 50;

	function pushHistory() {
		undoStack = [
			...undoStack.slice(-(MAX_HISTORY - 1)),
			{ nodes: JSON.parse(JSON.stringify($nodes)), edges: JSON.parse(JSON.stringify($edges)) }
		];
		redoStack = []; // Clear redo on new action
	}

	export function undo() {
		if (undoStack.length === 0) return;
		redoStack = [...redoStack, { nodes: JSON.parse(JSON.stringify($nodes)), edges: JSON.parse(JSON.stringify($edges)) }];
		const prev = undoStack[undoStack.length - 1];
		undoStack = undoStack.slice(0, -1);
		nodes.set(prev.nodes);
		edges.set(prev.edges);
		dispatch('change', { flowData: getFlowData() });
	}

	export function redo() {
		if (redoStack.length === 0) return;
		undoStack = [...undoStack, { nodes: JSON.parse(JSON.stringify($nodes)), edges: JSON.parse(JSON.stringify($edges)) }];
		const next = redoStack[redoStack.length - 1];
		redoStack = redoStack.slice(0, -1);
		nodes.set(next.nodes);
		edges.set(next.edges);
		dispatch('change', { flowData: getFlowData() });
	}

	export let canUndo = false;
	export let canRedo = false;
	$: canUndo = undoStack.length > 0;
	$: canRedo = redoStack.length > 0;

	// Clipboard for copy/paste
	let clipboard: { nodes: Node[]; edges: Edge[] } | null = null;

	function copySelected() {
		const selected = $nodes.filter((n: Node) => n.selected);
		if (selected.length === 0 && selectedNode) {
			clipboard = { nodes: [JSON.parse(JSON.stringify(selectedNode))], edges: [] };
		} else if (selected.length > 0) {
			const selectedIds = new Set(selected.map((n: Node) => n.id));
			const relatedEdges = $edges.filter((e: Edge) => selectedIds.has(e.source) && selectedIds.has(e.target));
			clipboard = {
				nodes: JSON.parse(JSON.stringify(selected)),
				edges: JSON.parse(JSON.stringify(relatedEdges))
			};
		}
	}

	function pasteClipboard() {
		if (!clipboard || clipboard.nodes.length === 0) return;
		pushHistory();
		const idMap: Record<string, string> = {};
		const newNodes: Node[] = clipboard.nodes.map((n: Node) => {
			const newId = `${n.type}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
			idMap[n.id] = newId;
			return {
				...n,
				id: newId,
				position: { x: n.position.x + 50, y: n.position.y + 50 },
				selected: false
			};
		});
		const newEdges: Edge[] = clipboard.edges.map((e: Edge) => ({
			...e,
			id: `edge_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
			source: idMap[e.source] || e.source,
			target: idMap[e.target] || e.target
		}));
		nodes.update((n) => [...n, ...newNodes]);
		edges.update((e) => [...e, ...newEdges]);
		dispatchChange();
	}

	// Collected state keys from all nodes
	export let collectedStateKeys: Array<{ key: string; source: string; nodeId: string; type: string }> = [];

	// Collect state keys from all nodes in the flow
	function collectStateKeys(nodeList: Node[]): typeof collectedStateKeys {
		const keys: typeof collectedStateKeys = [];

		for (const node of nodeList) {
			const config = node.data?.config || {};
			const label = node.data?.label || node.type;

			switch (node.type) {
				case 'model':
					// JSON output fields
					if (config.responseFormat === 'json' && config.jsonFields?.length > 0) {
						for (const field of config.jsonFields) {
							if (field.name) {
								keys.push({
									key: `${label}.${field.name}`,
									source: label,
									nodeId: node.id,
									type: field.type || 'string'
								});
							}
						}
					}
					keys.push({ key: `${label}.response`, source: label, nodeId: node.id, type: 'string' });
					break;

				case 'agent':
					keys.push({ key: `${label}.response`, source: label, nodeId: node.id, type: 'string' });
					break;

				case 'transform':
					keys.push({ key: `${label}.result`, source: label, nodeId: node.id, type: 'string' });
					break;

				case 'guardrail':
					keys.push({ key: `${label}.passed`, source: label, nodeId: node.id, type: 'boolean' });
					break;

				case 'router':
					keys.push({ key: `${label}.route`, source: label, nodeId: node.id, type: 'string' });
					break;

				case 'merge':
					keys.push({ key: `${label}.result`, source: label, nodeId: node.id, type: 'string' });
					break;

				case 'glossary':
					keys.push({ key: `${label}.matched`, source: label, nodeId: node.id, type: 'array' });
					keys.push({ key: `${label}.context`, source: label, nodeId: node.id, type: 'string' });
					break;

				case 'condition':
					keys.push({ key: `${label}.result`, source: label, nodeId: node.id, type: 'boolean' });
					break;
			}
		}

		// Remove duplicates (keep first occurrence)
		const seen = new Set<string>();
		return keys.filter(k => {
			if (seen.has(k.key)) return false;
			seen.add(k.key);
			return true;
		});
	}

	// Update collected state keys when nodes change
	$: collectedStateKeys = collectStateKeys($nodes);

	// Initialize from flowData
	$: if (flowData) {
		const initialNodes: Node[] = (flowData.nodes || []).map((n: FlowNode) => ({
			id: n.id,
			type: n.type,
			position: n.position,
			data: {
				...n.data,
				label: n.data?.label || getDefaultLabel(n.type)
			}
		}));
		const initialEdges: Edge[] = (flowData.edges || []).map((e: FlowEdge) => ({
			id: e.id,
			source: e.source,
			target: e.target,
			sourceHandle: e.sourceHandle,
			targetHandle: e.targetHandle,
			type: 'smoothstep',
			animated: true,
			// LangGraph conversion fields
			label: e.label,
			labelBgStyle: e.label ? 'fill: rgba(255,255,255,0.85); rx: 4; ry: 4;' : undefined,
			data: e.condition ? { condition: e.condition } : undefined
		}));
		nodes.set(initialNodes);
		edges.set(initialEdges);
	}

	function getDefaultLabel(type: string): string {
		const labels: Record<string, string> = {
			flowInput: $i18n.t('Start'),
			flowOutput: $i18n.t('Output'),
			agent: $i18n.t('Agent'),
			model: $i18n.t('Model'),
			condition: $i18n.t('Condition'),
			router: $i18n.t('Router'),
			merge: $i18n.t('Merge'),
			glossary: $i18n.t('Glossary'),
			transform: $i18n.t('Transform'),
			guardrail: $i18n.t('Guardrail')
		};
		return labels[type] || type;
	}

	// Generate unique ID
	function generateId(): string {
		return `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
	}

	// Add a new node
	export function addNode(type: string, position: { x: number; y: number }) {
		pushHistory();
		const newNode: Node = {
			id: generateId(),
			type,
			position,
			data: {
				label: getDefaultLabel(type),
				resourceId: null,
				config: {}
			}
		};
		nodes.update((n) => [...n, newNode]);
		dispatchChange();
	}

	// Delete selected node
	export function deleteNode(nodeId: string) {
		pushHistory();
		nodes.update((n) => n.filter((node) => node.id !== nodeId));
		edges.update((e) => e.filter((edge) => edge.source !== nodeId && edge.target !== nodeId));
		if (selectedNode?.id === nodeId) {
			selectedNode = null;
		}
		dispatchChange();
	}

	// Update node data
	export function updateNodeData(nodeId: string, data: Partial<Node['data']>) {
		nodes.update((n) =>
			n.map((node) => {
				if (node.id === nodeId) {
					return { ...node, data: { ...node.data, ...data } };
				}
				return node;
			})
		);
		dispatchChange();
	}

	// Handle connection
	const onConnect: OnConnect = (connection) => {
		if (!connection.source || !connection.target) return;
		pushHistory();

		// Find source node to get branch information
		const sourceNode = $nodes.find((n: Node) => n.id === connection.source);
		let edgeLabel: string | undefined;
		let branchKey: string | undefined;

		// Handle Condition node (true/false branches)
		if (sourceNode?.type === 'condition') {
			const handle = connection.sourceHandle;
			if (handle === 'true') {
				edgeLabel = 'True';
				branchKey = 'true';
			} else if (handle === 'false') {
				edgeLabel = 'False';
				branchKey = 'false';
			}
		}

		// Handle Guardrail node (pass/block branches)
		if (sourceNode?.type === 'guardrail') {
			const handle = connection.sourceHandle;
			if (handle === 'pass') {
				edgeLabel = 'Pass';
				branchKey = 'pass';
			} else if (handle === 'block') {
				edgeLabel = 'Block';
				branchKey = 'block';
			}
		}

		// Handle Router node (dynamic routes)
		if (sourceNode?.type === 'router') {
			const routes = sourceNode.data?.config?.routes || [];
			const route = routes.find((r: any) => r.id === connection.sourceHandle);
			if (route) {
				edgeLabel = route.label || route.id;
				branchKey = route.id;
			}
		}

		const newEdge: Edge = {
			id: `edge_${connection.source}_${connection.target}_${connection.sourceHandle || 'default'}`,
			source: connection.source,
			target: connection.target,
			sourceHandle: connection.sourceHandle ?? undefined,
			targetHandle: connection.targetHandle ?? undefined,
			type: 'smoothstep',
			animated: true,
			// LangGraph conversion fields
			label: edgeLabel,
			labelBgStyle: edgeLabel ? 'fill: rgba(255,255,255,0.85); rx: 4; ry: 4;' : undefined,
			data: branchKey ? { condition: { branch_key: branchKey } } : undefined
		};

		edges.update((e) => {
			// Prevent duplicate edges (same source, target, and handle)
			const exists = e.some(
				(edge) =>
					edge.source === newEdge.source &&
					edge.target === newEdge.target &&
					edge.sourceHandle === newEdge.sourceHandle
			);
			if (exists) return e;
			return [...e, newEdge];
		});
		dispatchChange();
	};

	// Get upstream nodes (nodes that connect to the given node)
	function getUpstreamNodes(nodeId: string): Node[] {
		const upstreamNodeIds = new Set<string>();

		// Find all edges that target this node
		$edges.forEach((edge: Edge) => {
			if (edge.target === nodeId) {
				upstreamNodeIds.add(edge.source);
			}
		});

		// Return the actual node objects
		return $nodes.filter((n: Node) => upstreamNodeIds.has(n.id));
	}

	// Handle node click
	function onNodeClick(event: CustomEvent<{ node: Node }>) {
		selectedNode = event.detail.node;
		const upstreamNodes = selectedNode ? getUpstreamNodes(selectedNode.id) : [];
		dispatch('nodeselect', { node: selectedNode, upstreamNodes, stateKeys: collectedStateKeys });
	}

	// Handle pane click (deselect)
	function onPaneClick() {
		selectedNode = null;
		selectedEdgeId = null;
		dispatch('nodeselect', { node: null, stateKeys: collectedStateKeys });
	}

	// Handle edge click (for deletion with Delete key)
	function onEdgeClick(event: CustomEvent<{ edge: Edge }>) {
		selectedEdgeId = event.detail.edge.id;
		selectedNode = null;
		dispatch('nodeselect', { node: null });
	}

	// Handle keyboard events
	function handleKeyDown(event: KeyboardEvent) {
		if (readonly) return;

		// Undo: Ctrl+Z
		if ((event.ctrlKey || event.metaKey) && event.key === 'z' && !event.shiftKey) {
			event.preventDefault();
			undo();
			return;
		}
		// Redo: Ctrl+Shift+Z or Ctrl+Y
		if ((event.ctrlKey || event.metaKey) && (event.key === 'Z' || event.key === 'y')) {
			event.preventDefault();
			redo();
			return;
		}
		// Copy: Ctrl+C
		if ((event.ctrlKey || event.metaKey) && event.key === 'c') {
			copySelected();
			return;
		}
		// Paste: Ctrl+V
		if ((event.ctrlKey || event.metaKey) && event.key === 'v') {
			event.preventDefault();
			pasteClipboard();
			return;
		}
		// Delete edge
		if (event.key === 'Delete' || event.key === 'Backspace') {
			if (selectedEdgeId) {
				pushHistory();
				edges.update((e) => e.filter((edge) => edge.id !== selectedEdgeId));
				selectedEdgeId = null;
				dispatchChange();
				event.preventDefault();
			}
		}
	}

	// Delete edge by ID
	export function deleteEdge(edgeId: string) {
		edges.update((e) => e.filter((edge) => edge.id !== edgeId));
		selectedEdgeId = null;
		dispatchChange();
	}

	// Handle node drag end
	function onNodeDragStop(event: CustomEvent<{ node: Node }>) {
		const node = event.detail.node;
		nodes.update((n) =>
			n.map((nd) => {
				if (nd.id === node.id) {
					return { ...nd, position: node.position };
				}
				return nd;
			})
		);
		dispatchChange();
	}

	// Handle edge delete
	function onEdgesDelete(event: CustomEvent<{ edges: Edge[] }>) {
		const deletedIds = new Set(event.detail.edges.map((e: Edge) => e.id));
		edges.update((e) => e.filter((edge) => !deletedIds.has(edge.id)));
		dispatchChange();
	}

	// Handle nodes delete
	function onNodesDelete(event: CustomEvent<{ nodes: Node[] }>) {
		const deletedIds = new Set(event.detail.nodes.map((n: Node) => n.id));
		nodes.update((n) => n.filter((node) => !deletedIds.has(node.id)));
		edges.update((e) => e.filter((edge) => !deletedIds.has(edge.source) && !deletedIds.has(edge.target)));
		if (selectedNode && deletedIds.has(selectedNode.id)) {
			selectedNode = null;
		}
		dispatchChange();
	}

	// Dispatch change event with current flow data
	function dispatchChange() {
		const currentFlowData: FlowData = {
			nodes: $nodes.map((n: Node) => ({
				id: n.id,
				type: n.type as FlowNode['type'],
				position: n.position,
				data: n.data
			})),
			edges: $edges.map((e: Edge) => ({
				id: e.id,
				source: e.source,
				target: e.target,
				sourceHandle: e.sourceHandle,
				targetHandle: e.targetHandle
			})),
			variables: flowData?.variables || {}
		};
		dispatch('change', { flowData: currentFlowData });
	}

	// Get current flow data
	export function getFlowData(): FlowData {
		return {
			nodes: $nodes.map((n: Node) => ({
				id: n.id,
				type: n.type as FlowNode['type'],
				position: n.position,
				data: n.data
			})),
			edges: $edges.map((e: Edge) => ({
				id: e.id,
				source: e.source,
				target: e.target,
				sourceHandle: e.sourceHandle,
				targetHandle: e.targetHandle,
				// LangGraph conversion fields
				label: e.label as string | undefined,
				condition: (e.data as any)?.condition
			})),
			variables: flowData?.variables || {}
		};
	}

	// Handle drop from palette
	export function handleDrop(event: DragEvent) {
		event.preventDefault();
		const type = event.dataTransfer?.getData('application/reactflow');
		if (!type) return;

		let position: { x: number; y: number };

		// Use flow instance to convert screen to flow coordinates
		if (flowInstance?.screenToFlowPosition) {
			position = flowInstance.screenToFlowPosition({
				x: event.clientX,
				y: event.clientY
			});
		} else if (flowContainer) {
			// Fallback: use viewport transform from the flow container
			const bounds = flowContainer.getBoundingClientRect();
			const flowElement = flowContainer.querySelector('.svelte-flow__viewport');
			if (flowElement) {
				const transform = window.getComputedStyle(flowElement).transform;
				const matrix = new DOMMatrix(transform);
				const scale = matrix.a; // zoom level
				const translateX = matrix.e;
				const translateY = matrix.f;
				position = {
					x: (event.clientX - bounds.left - translateX) / scale,
					y: (event.clientY - bounds.top - translateY) / scale
				};
			} else {
				position = {
					x: event.clientX - bounds.left,
					y: event.clientY - bounds.top
				};
			}
		} else {
			position = { x: 100, y: 100 };
		}

		// Offset to center the node on the drop point
		position.x -= 75;
		position.y -= 25;

		addNode(type, position);
	}

	function handleDragOver(event: DragEvent) {
		event.preventDefault();
		event.dataTransfer!.dropEffect = 'move';
	}

	// Determine color mode
	$: colorMode =
		$theme.includes('dark')
			? 'dark'
			: $theme === 'system'
				? typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light'
				: 'light';
</script>

{#if mounted}
	<div
		bind:this={flowContainer}
		class="w-full h-full relative"
		on:drop={handleDrop}
		on:dragover={handleDragOver}
		on:keydown={handleKeyDown}
		role="application"
		aria-label="Flow Builder Canvas"
		tabindex="0"
	>
		<!-- Edge selection toolbar -->
		{#if selectedEdgeId && !readonly}
			<div class="absolute top-3 left-1/2 -translate-x-1/2 z-10 flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white dark:bg-gray-800 shadow-lg border border-gray-200 dark:border-gray-700 text-xs">
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Edge selected')}</span>
				<button
					type="button"
					class="flex items-center gap-1 px-2 py-1 rounded-md bg-red-50 hover:bg-red-100 dark:bg-red-900/20 dark:hover:bg-red-900/40 text-red-600 dark:text-red-400 font-medium transition-colors"
					on:click={() => { if (selectedEdgeId) { deleteEdge(selectedEdgeId); } }}
				>
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
					</svg>
					{$i18n.t('Delete')}
				</button>
				<span class="text-gray-400 dark:text-gray-500">|</span>
				<span class="text-gray-400 dark:text-gray-500">{$i18n.t('or press Delete key')}</span>
			</div>
		{/if}
		<SvelteFlow
			{nodes}
			{edges}
			{nodeTypes}
			{colorMode}
			minZoom={0.1}
			maxZoom={2}
			defaultViewport={{ x: 100, y: 100, zoom: 1 }}
			nodesConnectable={!readonly}
			nodesDraggable={!readonly}
			elementsSelectable={!readonly}
			edgesSelectable={!readonly}
			deleteKeyCode={readonly ? null : ['Delete', 'Backspace']}
			selectionKeyCode={null}
			multiSelectionKeyCode="Shift"
			connectionRadius={30}
			on:nodeclick={onNodeClick}
			on:paneclick={onPaneClick}
			on:nodedragstop={onNodeDragStop}
			on:edgeclick={onEdgeClick}
			on:edgesdelete={onEdgesDelete}
			on:init={handleFlowInit}
			on:nodesdelete={onNodesDelete}
			onconnect={onConnect}
			defaultEdgeOptions={{
				type: 'smoothstep',
				animated: true,
				style: 'stroke-width: 2.5; stroke: #94a3b8;',
				interactionWidth: 20
			}}
		>
			<Controls showLock={false} />
			<MiniMap />
			<Background variant={BackgroundVariant.Dots} gap={12} />
		</SvelteFlow>
	</div>
{:else}
	<div class="w-full h-full flex items-center justify-center">
		<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-white"></div>
	</div>
{/if}

<style>
	:global(.svelte-flow) {
		background-color: var(--xy-background-color, #fafafa);
	}

	:global(.svelte-flow.dark) {
		--xy-background-color: #1e1e1e;
	}

	/* Edge interaction area */
	:global(.svelte-flow .svelte-flow__edge-interaction) {
		stroke-width: 20px !important;
		stroke: transparent !important;
		cursor: pointer !important;
	}

	/* Edge default */
	:global(.svelte-flow .svelte-flow__edge-path) {
		stroke-width: 2.5 !important;
		stroke: #94a3b8 !important;
		transition: stroke 0.15s, stroke-width 0.15s;
	}

	:global(.dark .svelte-flow .svelte-flow__edge-path) {
		stroke: #64748b !important;
	}

	/* Edge hover */
	:global(.svelte-flow .svelte-flow__edge:hover .svelte-flow__edge-path) {
		stroke: #3b82f6 !important;
		stroke-width: 3 !important;
	}

	/* Edge selected */
	:global(.svelte-flow .svelte-flow__edge.selected .svelte-flow__edge-path) {
		stroke: #ef4444 !important;
		stroke-width: 3.5 !important;
		stroke-dasharray: 8 4 !important;
	}

	/* Edge labels (True/False, route names) */
	:global(.svelte-flow .svelte-flow__edgelabel) {
		font-size: 11px !important;
		font-weight: 500 !important;
	}

	:global(.svelte-flow .svelte-flow__edgelabel span) {
		padding: 2px 8px !important;
		border-radius: 10px !important;
		background: rgba(255, 255, 255, 0.92) !important;
		border: 1px solid rgba(0, 0, 0, 0.08) !important;
		color: #374151 !important;
	}

	:global(.dark .svelte-flow .svelte-flow__edgelabel span) {
		background: rgba(30, 30, 30, 0.92) !important;
		border: 1px solid rgba(255, 255, 255, 0.08) !important;
		color: #e5e7eb !important;
	}

	/* Make handles (connection points) easier to click - use padding for larger hit area */
	:global(.svelte-flow .svelte-flow__handle) {
		width: 12px !important;
		height: 12px !important;
		/* Use box-sizing and padding for larger clickable area without affecting position */
		box-sizing: content-box !important;
		padding: 8px !important;
		margin: -8px !important;
		background-clip: content-box !important;
	}

	/* Handle hover effect - only use box-shadow, no transform */
	:global(.svelte-flow .svelte-flow__handle:hover) {
		box-shadow: 0 0 10px rgba(59, 130, 246, 0.7);
	}

	/* Connecting state - make target handles more visible */
	:global(.svelte-flow .svelte-flow__handle.connectingto),
	:global(.svelte-flow .svelte-flow__handle.connectingfrom) {
		box-shadow: 0 0 14px rgba(59, 130, 246, 0.9);
	}

	/* Valid connection target indicator */
	:global(.svelte-flow .svelte-flow__handle.valid) {
		background-color: #22c55e !important;
		box-shadow: 0 0 14px rgba(34, 197, 94, 0.9);
	}
</style>
