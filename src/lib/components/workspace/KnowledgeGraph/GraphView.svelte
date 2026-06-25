<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import cytoscape from 'cytoscape';
	import fcose from 'cytoscape-fcose';
	import { toast } from 'svelte-sonner';
	import { getKnowledgeGraphGraph, type KGGraphResponse, type KGGraphNode, type KGGraphEdge } from '$lib/apis/knowledge-graph';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Search from '$lib/components/icons/Search.svelte';

	const i18n = getContext<{ t: (key: string, params?: Record<string, unknown>) => string }>(
		'i18n'
	);

	export let kgId: string;
	// Optional height override (e.g., "100vh" for fullscreen route, default "540px" inline)
	export let height: string = '540px';
	// 전체화면 라우트에서 켜면 좌측에 엣지 리스트 패널이 렌더된다.
	// 기본 false 라 기존 인라인 뷰 동작엔 영향 없음.
	export let showEdgeList: boolean = false;
	// 그래프 로드 시 노드 상한. 인라인 뷰 500, 전체화면 2000.
	export let maxNodes: number = 500;

	let containerEl: HTMLDivElement;
	let cy: cytoscape.Core | null = null;
	let loading = false;
	let graph: KGGraphResponse | null = null;
	let searchQuery = '';
	let registered = false;
	// 우선순위 노드 타입 — 사용자가 Legend 의 타입 버튼을 누르면 그 타입을
	// max_nodes 한도 내에서 모두 fetch 하고 1-hop 이웃으로 나머지를 채운다.
	let priorityNodeType: string | null = null;

	// --- Selection state ---
	type SelectedNode = {
		id: string;
		label: string;
		node_type: string;
		properties: Record<string, unknown> | null;
		edges: { edge_type: string; direction: 'in' | 'out'; neighbor: KGGraphNode }[];
	};
	let selectedNode: SelectedNode | null = null;

	type SelectedEdge = {
		id: string;
		edge_type: string;
		weight: number | null;
		properties: Record<string, unknown> | null;
		srcNode: KGGraphNode | null;
		dstNode: KGGraphNode | null;
	};
	let selectedEdge: SelectedEdge | null = null;

	// Lookup maps built from graph data
	let nodeMap: Map<string, KGGraphNode> = new Map();
	let edgesBySrc: Map<string, KGGraphEdge[]> = new Map();

	// ─── 좌측 패널 상태 (showEdgeList=true 일 때만 사용) ───
	let entityTab: 'nodes' | 'edges' = 'nodes';
	let listQuery = '';
	let nodeTypeFilter = '';
	let edgeTypeFilter = '';
	let edgesByDst: Map<string, KGGraphEdge[]> = new Map();

	const TYPE_COLORS: Record<string, { bg: string; border: string }> = {
		term: { bg: '#3b82f6', border: '#1d4ed8' },
		concept: { bg: '#a855f7', border: '#7e22ce' },
		table: { bg: '#22c55e', border: '#15803d' },
		column: { bg: '#f97316', border: '#c2410c' },
		doc_entity: { bg: '#ec4899', border: '#be185d' },
		doc_attr: { bg: '#06b6d4', border: '#0e7490' },
		// Phase 2 — 컨테이너 / 문서
		database: { bg: '#0ea5e9', border: '#0369a1' },
		glossary: { bg: '#8b5cf6', border: '#6d28d9' },
		knowledge_base: { bg: '#14b8a6', border: '#0f766e' },
		document: { bg: '#f59e0b', border: '#b45309' }
	};

	const DEFAULT_COLOR = { bg: '#94a3b8', border: '#475569' };

	function colorOf(t: string) {
		return TYPE_COLORS[t] ?? DEFAULT_COLOR;
	}

	const TYPE_LABELS: Record<string, string> = {
		term: 'Term',
		concept: 'Concept',
		table: 'Table',
		column: 'Column',
		doc_entity: 'Doc Entity',
		doc_attr: 'Doc Attribute',
		database: 'Database',
		glossary: 'Glossary',
		knowledge_base: 'Knowledge Base',
		document: 'Document'
	};

	const EDGE_LABELS: Record<string, string> = {
		// 글로서리 / 스키마 sync 고정 타입
		synonym_of: 'Synonym',
		broader_than: 'Broader',
		narrower_than: 'Narrower',
		related_to: 'Related',
		maps_to: 'Maps to',
		defined_as: 'Defined as',
		foreign_key: 'FK',
		belongs_to: 'Belongs to',
		computed_from: 'Computed from',
		has_feature: 'Has feature',
		// 계층 컨테인먼트
		contains_table: 'Contains table',
		contains_column: 'Contains column',
		contains_document: 'Contains document',
		contains_concept: 'Contains concept',
		contains_term: 'Contains term',
		// 문서/매칭/메타
		mentions: 'Mentions',
		extracted_from: 'Extracted from',
		// 예시 도메인 엣지
		produces: 'Produces',
		owned_by: 'Owned by',
		located_in: 'Located in',
		depends_on: 'Depends on',
		has_risk: 'Has risk',
		supplies_to: 'Supplies to',
		regulates: 'Regulates',
		part_of: 'Part of',
		uses: 'Uses'
	};

	function edgeLabel(t: string): string {
		return EDGE_LABELS[t] ?? t;
	}

	const ensureFcose = () => {
		if (!registered) {
			cytoscape.use(fcose);
			registered = true;
		}
	};

	// ─── 휠 줌 정규화 ───
	// 트랙패드 / 일반 마우스휠 / 다양한 OS 가 보내는 deltaY 값(deltaMode 0 픽셀,
	// 1 라인, 2 페이지)을 동일한 스텝으로 정규화해 환경에 무관하게 일정한 줌
	// 감도를 만든다. cytoscape 기본 휠은 userZoomingEnabled=false 로 꺼두고
	// 이 핸들러가 모든 처리를 한다.
	const handleWheel = (e: WheelEvent) => {
		if (!cy) return;
		e.preventDefault();
		e.stopPropagation();

		// deltaY 를 픽셀 단위로 정규화
		let dy = e.deltaY;
		if (e.deltaMode === 1) dy *= 16; // line → px
		if (e.deltaMode === 2) dy *= 100; // page → px

		// 한 스텝당 너무 큰 점프를 막기 위해 클램프
		const MAX = 240;
		if (dy > MAX) dy = MAX;
		if (dy < -MAX) dy = -MAX;

		// 지수형 줌 step — 일정한 비율로 변화
		const factor = Math.exp(-dy / 200);

		const zoom = cy.zoom();
		const newZoom = Math.max(0.1, Math.min(3, zoom * factor));
		if (newZoom === zoom) return;

		const rect = containerEl.getBoundingClientRect();
		cy.zoom({
			level: newZoom,
			renderedPosition: {
				x: e.clientX - rect.left,
				y: e.clientY - rect.top
			}
		});
	};

	const buildLookups = (g: KGGraphResponse) => {
		nodeMap = new Map(g.nodes.map((n) => [n.id, n]));
		edgesBySrc = new Map();
		edgesByDst = new Map();
		for (const e of g.edges) {
			if (!nodeMap.has(e.src_id) || !nodeMap.has(e.dst_id)) continue;
			if (!edgesBySrc.has(e.src_id)) edgesBySrc.set(e.src_id, []);
			edgesBySrc.get(e.src_id)!.push(e);
			if (!edgesByDst.has(e.dst_id)) edgesByDst.set(e.dst_id, []);
			edgesByDst.get(e.dst_id)!.push(e);
		}
	};

	const buildElements = (g: KGGraphResponse) => {
		const nodes = g.nodes.map((n) => ({
			data: {
				id: n.id,
				label: n.label,
				node_type: n.node_type,
				bg: colorOf(n.node_type).bg,
				border: colorOf(n.node_type).border
			}
		}));

		const nodeIds = new Set(g.nodes.map((n) => n.id));
		const edges = g.edges
			.filter((e) => nodeIds.has(e.src_id) && nodeIds.has(e.dst_id))
			.map((e) => ({
				data: {
					id: e.id,
					source: e.src_id,
					target: e.dst_id,
					edge_type: e.edge_type,
					weight: e.weight ?? 1
				}
			}));
		return { nodes, edges };
	};

	const selectNode = (nodeId: string) => {
		const n = nodeMap.get(nodeId);
		if (!n) return;

		const edges: SelectedNode['edges'] = [];
		for (const e of edgesBySrc.get(nodeId) ?? []) {
			const neighbor = nodeMap.get(e.dst_id);
			if (neighbor) edges.push({ edge_type: e.edge_type, direction: 'out', neighbor });
		}
		for (const e of edgesByDst.get(nodeId) ?? []) {
			const neighbor = nodeMap.get(e.src_id);
			if (neighbor) edges.push({ edge_type: e.edge_type, direction: 'in', neighbor });
		}

		selectedNode = {
			id: n.id,
			label: n.label,
			node_type: n.node_type,
			properties: n.properties,
			edges
		};
		selectedEdge = null;
	};

	const selectEdgeById = (edgeId: string) => {
		if (!graph) return;
		const e = graph.edges.find((x) => x.id === edgeId);
		if (!e) return;
		selectedEdge = {
			id: e.id,
			edge_type: e.edge_type,
			weight: e.weight,
			properties: e.properties,
			srcNode: nodeMap.get(e.src_id) ?? null,
			dstNode: nodeMap.get(e.dst_id) ?? null
		};
		selectedNode = null;
	};

	const navigateToNode = (nodeId: string) => {
		if (!cy) return;
		const node = cy.getElementById(nodeId);
		if (node.length === 0) return;
		clearHighlight();
		highlightNeighbors(nodeId);
		selectNode(nodeId);
		cy.animate({ center: { eles: node }, zoom: 1.5 }, { duration: 400 });
	};

	// 엣지 리스트에서 엣지 클릭 → 선택 + 캔버스에서 해당 엣지로 이동/강조.
	const navigateToEdge = (edgeId: string) => {
		selectEdgeById(edgeId);
		if (!cy) return;
		const edge = cy.getElementById(edgeId);
		if (edge.length === 0) return;
		cy.elements()
			.addClass('faded')
			.removeClass('highlighted')
			.removeClass('selected-node')
			.removeClass('selected-edge');
		edge.removeClass('faded').addClass('selected-edge');
		edge.connectedNodes().removeClass('faded').addClass('highlighted');
		cy.animate({ center: { eles: edge.connectedNodes() }, zoom: 1.2 }, { duration: 400 });
	};

	const clearSelection = () => {
		selectedNode = null;
		selectedEdge = null;
	};

	const renderGraph = () => {
		if (!containerEl || !graph) return;
		ensureFcose();
		buildLookups(graph);
		const { nodes, edges } = buildElements(graph);

		if (cy) {
			containerEl.removeEventListener('wheel', handleWheel);
			cy.destroy();
			cy = null;
		}

		cy = cytoscape({
			container: containerEl,
			elements: [...nodes, ...edges],
			minZoom: 0.1,
			maxZoom: 3,
			// cytoscape 기본 휠 줌은 OS/디바이스(트랙패드 vs 일반 마우스휠)별 deltaY
			// 단위 차이를 정규화하지 못해 어떤 환경에선 너무 미세하게 동작한다.
			// 직접 wheel 핸들러로 처리하기 위해 user zoom 은 비활성화.
			userZoomingEnabled: false,
			style: [
				{
					selector: 'node',
					style: {
						'background-color': 'data(bg)',
						'border-color': 'data(border)',
						'border-width': 2,
						label: 'data(label)',
						color: '#0f172a',
						'font-size': 11,
						'text-outline-color': '#ffffff',
						'text-outline-width': 2,
						'text-valign': 'center',
						'text-halign': 'center',
						width: 36,
						height: 36
					}
				},
				{
					selector: 'edge',
					style: {
						'line-color': '#cbd5e1',
						'target-arrow-color': '#cbd5e1',
						'target-arrow-shape': 'triangle',
						'curve-style': 'bezier',
						width: 1.5,
						opacity: 0.6,
						label: 'data(edge_type)',
						'font-size': 8,
						'text-rotation': 'autorotate',
						color: '#94a3b8',
						'text-outline-color': '#ffffff',
						'text-outline-width': 1.5,
						// 엣지 시각선(1.5px)은 그대로 두고 tap 판정 영역만
						// 넓혀서 사용자가 엣지를 쉽게 클릭할 수 있게 한다.
						'overlay-padding': 10
					}
				},
				{
					selector: 'edge:active',
					style: {
						'overlay-opacity': 0.15,
						'overlay-color': '#3b82f6'
					}
				},
				{
					selector: 'edge.selected-edge',
					style: {
						'line-color': '#ef4444',
						'target-arrow-color': '#ef4444',
						width: 3.5,
						opacity: 1,
						color: '#991b1b',
						'font-size': 10
					}
				},
				{
					selector: 'node.highlighted',
					style: {
						'border-width': 4,
						'border-color': '#fbbf24',
						width: 50,
						height: 50,
						'font-size': 13
					}
				},
				{
					selector: 'node.selected-node',
					style: {
						'border-width': 5,
						'border-color': '#ef4444',
						width: 55,
						height: 55,
						'font-size': 14
					}
				},
				{
					selector: 'edge.highlighted',
					style: {
						'line-color': '#fbbf24',
						'target-arrow-color': '#fbbf24',
						width: 3,
						opacity: 1,
						'font-size': 10,
						color: '#92400e'
					}
				},
				{
					selector: 'node.faded',
					style: { opacity: 0.15 }
				},
				{
					selector: 'edge.faded',
					style: { opacity: 0.05 }
				}
			],
			layout: {
				name: 'fcose',
				animate: false,
				randomize: true,
				nodeRepulsion: 5000,
				idealEdgeLength: 80,
				gravity: 0.3,
				numIter: 2500
			} as cytoscape.LayoutOptions
		});

		cy.on('tap', 'node', (evt) => {
			const node = evt.target;
			selectNode(node.id());
			highlightNeighbors(node.id());
			// Mark the selected node
			cy?.elements().removeClass('selected-node').removeClass('selected-edge');
			node.addClass('selected-node');
		});

		cy.on('tap', 'edge', (evt) => {
			const edge = evt.target;
			selectEdgeById(edge.id());
			if (!cy) return;
			// 엣지 강조 + 양 끝 노드만 남기고 나머지 fade
			cy.elements()
				.addClass('faded')
				.removeClass('highlighted')
				.removeClass('selected-node')
				.removeClass('selected-edge');
			edge.removeClass('faded').addClass('selected-edge');
			edge.connectedNodes().removeClass('faded').addClass('highlighted');
		});

		cy.on('tap', (evt) => {
			if (evt.target === cy) {
				clearHighlight();
				clearSelection();
				cy?.elements().removeClass('selected-edge');
			}
		});

		// 정규화된 휠 줌 핸들러 부착
		containerEl.addEventListener('wheel', handleWheel, { passive: false });
	};

	const highlightNeighbors = (nodeId: string) => {
		if (!cy) return;
		cy.elements().addClass('faded');
		const node = cy.getElementById(nodeId);
		const neighborhood = node.closedNeighborhood();
		neighborhood.removeClass('faded').addClass('highlighted');
	};

	const clearHighlight = () => {
		if (!cy) return;
		cy.elements().removeClass('faded').removeClass('highlighted').removeClass('selected-node');
	};

	const runSearch = () => {
		if (!cy || !searchQuery.trim()) {
			clearHighlight();
			clearSelection();
			return;
		}
		const q = searchQuery.trim().toLowerCase();
		const matched = cy.nodes().filter((n) => n.data('label').toLowerCase().includes(q));
		if (matched.length === 0) {
			toast.error($i18n.t('No nodes match'));
			return;
		}
		cy.elements().addClass('faded');
		matched.removeClass('faded').addClass('highlighted');
		cy.animate({ center: { eles: matched }, zoom: 1.2 }, { duration: 400 });
		// Select first match
		if (matched.length === 1) {
			selectNode(matched[0].id());
		} else {
			clearSelection();
		}
	};

	const onKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			runSearch();
		}
	};

	const reload = async () => {
		loading = true;
		clearSelection();
		try {
			graph = await getKnowledgeGraphGraph(localStorage.token, kgId, {
				max_nodes: maxNodes,
				priority_node_type: priorityNodeType ?? undefined
			});
			renderGraph();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			loading = false;
		}
	};

	const togglePriorityType = (t: string) => {
		priorityNodeType = priorityNodeType === t ? null : t;
		reload();
	};

	const fitView = () => cy?.fit(undefined, 30);

	// ─── 노드/엣지 리스트 derived ───
	type EdgeListItem = {
		id: string;
		edge_type: string;
		srcLabel: string;
		srcType: string;
		dstLabel: string;
		dstType: string;
	};

	$: allEdgeItems = ((graph?.edges ?? [])
		.map((e) => {
			const src = nodeMap.get(e.src_id);
			const dst = nodeMap.get(e.dst_id);
			if (!src || !dst) return null;
			return {
				id: e.id,
				edge_type: e.edge_type,
				srcLabel: src.label,
				srcType: src.node_type,
				dstLabel: dst.label,
				dstType: dst.node_type
			} as EdgeListItem;
		})
		.filter((x): x is EdgeListItem => x !== null)) as EdgeListItem[];

	$: edgeTypesInGraph = Array.from(new Set(allEdgeItems.map((e) => e.edge_type))).sort();
	$: nodeTypesInGraph = Array.from(new Set((graph?.nodes ?? []).map((n) => n.node_type))).sort();

	$: edgeListFiltered = allEdgeItems.filter((item) => {
		if (edgeTypeFilter && item.edge_type !== edgeTypeFilter) return false;
		if (listQuery.trim()) {
			const q = listQuery.trim().toLowerCase();
			if (
				!item.srcLabel.toLowerCase().includes(q) &&
				!item.dstLabel.toLowerCase().includes(q) &&
				!item.edge_type.toLowerCase().includes(q)
			) {
				return false;
			}
		}
		return true;
	});

	$: nodeListFiltered = (graph?.nodes ?? []).filter((n) => {
		if (nodeTypeFilter && n.node_type !== nodeTypeFilter) return false;
		if (listQuery.trim()) {
			const q = listQuery.trim().toLowerCase();
			if (!n.label.toLowerCase().includes(q)) return false;
		}
		return true;
	});

	const LIST_MAX = 2000;

	// Property display helpers
	function formatPropValue(val: unknown): string {
		if (val === null || val === undefined) return '-';
		if (typeof val === 'boolean') return val ? 'Yes' : 'No';
		if (typeof val === 'object') return JSON.stringify(val);
		return String(val);
	}

	function getDisplayProps(props: Record<string, unknown> | null): [string, string][] {
		if (!props) return [];
		return Object.entries(props)
			.filter(([_, v]) => v !== null && v !== undefined && v !== '')
			.map(([k, v]) => [k, formatPropValue(v)]);
	}

	onMount(() => {
		reload();
	});

	onDestroy(() => {
		if (containerEl) containerEl.removeEventListener('wheel', handleWheel);
		cy?.destroy();
		cy = null;
	});
</script>

<div class="flex flex-col gap-3">
	<!-- Toolbar -->
	<div class="flex items-center gap-2 flex-wrap">
		<div class="flex-1 max-w-md">
			<Input
				bind:value={searchQuery}
				placeholder={$i18n.t('Find node by label')}
				type="search"
				size="md"
				on:keydown={onKeydown}
			>
				<svelte:fragment slot="prefix">
					<Search className="size-3.5" />
				</svelte:fragment>
			</Input>
		</div>
		<Button kind="filled" size="md" on:click={runSearch}>
			{$i18n.t('Find')}
		</Button>
		<Button
			kind="outlined"
			size="md"
			on:click={() => {
				searchQuery = '';
				clearHighlight();
				clearSelection();
			}}
		>
			{$i18n.t('Clear')}
		</Button>
		<Button kind="outlined" size="md" on:click={fitView}>
			{$i18n.t('Fit')}
		</Button>
		<Button kind="outlined" size="md" on:click={reload} disabled={loading}>
			{loading ? $i18n.t('Loading...') : $i18n.t('Reload')}
		</Button>
		<div class="ml-auto flex items-center gap-3 text-xs text-gray-500">
			{#if graph}
				<span>{graph.nodes.length}/{graph.total_nodes} {$i18n.t('Nodes')}</span>
				<span>{graph.edges.length}/{graph.total_edges} {$i18n.t('Edges')}</span>
				{#if graph.truncated}
					<span class="text-amber-600">⚠ {$i18n.t('Truncated')}</span>
				{/if}
			{/if}
		</div>
	</div>

	<!-- Legend / 우선순위 토글 -->
	<div class="flex items-center gap-2 flex-wrap text-xs">
		<span class="text-gray-500 dark:text-gray-400 mr-1">{$i18n.t('Focus')}:</span>
		{#each Object.entries(TYPE_COLORS) as [t, c]}
			{@const active = priorityNodeType === t}
			<button
				type="button"
				class="flex items-center gap-1.5 px-2 py-1 rounded-full border transition
					{active
					? 'bg-[var(--cloo-bg-neutral-hovered)] border-[var(--cloo-border-default)] ring-1 ring-[var(--cloo-color-primary)]'
					: 'bg-white dark:bg-gray-900 border-[var(--cloo-border-subtle)] hover:bg-gray-50 dark:hover:bg-gray-800'}"
				on:click={() => togglePriorityType(t)}
				disabled={loading}
				title={$i18n.t('Click to focus on this node type — all nodes of this type plus their 1-hop neighbors will be loaded.')}
			>
				<span
					class="inline-block w-3 h-3 rounded-full border-2"
					style:background-color={c.bg}
					style:border-color={c.border}
				></span>
				<span class="text-gray-700 dark:text-gray-300">{TYPE_LABELS[t] ?? t}</span>
			</button>
		{/each}
		{#if priorityNodeType}
			{@const _focused = priorityNodeType}
			<button
				type="button"
				class="text-[11px] text-gray-500 underline ml-1 hover:text-gray-700 dark:hover:text-gray-300"
				on:click={() => togglePriorityType(_focused)}
				disabled={loading}
			>
				{$i18n.t('Clear focus')}
			</button>
		{/if}
	</div>

	<!-- Main: Graph + Detail Panel -->
	<div class="flex gap-3" style="height: {height};">
		<!-- Left List Panel (fullscreen mode only) -->
		{#if showEdgeList}
			<div
				class="w-80 shrink-0 flex flex-col border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-900 overflow-hidden"
			>
				<div class="p-2 border-b border-gray-100 dark:border-gray-800 flex flex-col gap-2">
					<!-- Tabs: Nodes / Edges -->
					<div class="flex items-center gap-1">
						<button
							type="button"
							class="flex-1 text-xs font-medium px-2 py-1.5 rounded transition
								{entityTab === 'nodes'
								? 'bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-primary)]'
								: 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800'}"
							on:click={() => (entityTab = 'nodes')}
						>
							{$i18n.t('Nodes')}
							<span class="text-[10px] text-gray-400 ml-1">
								{nodeListFiltered.length}/{(graph?.nodes ?? []).length}
							</span>
						</button>
						<button
							type="button"
							class="flex-1 text-xs font-medium px-2 py-1.5 rounded transition
								{entityTab === 'edges'
								? 'bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-primary)]'
								: 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800'}"
							on:click={() => (entityTab = 'edges')}
						>
							{$i18n.t('Edges')}
							<span class="text-[10px] text-gray-400 ml-1">
								{edgeListFiltered.length}/{allEdgeItems.length}
							</span>
						</button>
					</div>

					<Input
						bind:value={listQuery}
						placeholder={entityTab === 'nodes'
							? $i18n.t('Search nodes...')
							: $i18n.t('Search edges (src/dst label or type)...')}
						type="search"
						size="sm"
					>
						<svelte:fragment slot="prefix">
							<Search className="size-3.5" />
						</svelte:fragment>
					</Input>

					{#if entityTab === 'nodes'}
						<Selector
							value={nodeTypeFilter}
							items={[
								{ value: '', label: $i18n.t('All types') },
								...nodeTypesInGraph.map((t) => ({ value: t, label: TYPE_LABELS[t] ?? t }))
							]}
							size="sm"
							on:change={(e) => (nodeTypeFilter = e.detail.value || '')}
						/>
					{:else}
						<Selector
							value={edgeTypeFilter}
							items={[
								{ value: '', label: $i18n.t('All edge types') },
								...edgeTypesInGraph.map((t) => ({ value: t, label: edgeLabel(t) }))
							]}
							size="sm"
							searchEnabled
							on:change={(e) => (edgeTypeFilter = e.detail.value || '')}
						/>
					{/if}
				</div>

				<div class="flex-1 overflow-y-auto">
					{#if entityTab === 'nodes'}
						{#if nodeListFiltered.length === 0}
							<div class="p-4 text-xs text-gray-400 italic text-center">
								{$i18n.t('No nodes match the filter.')}
							</div>
						{:else}
							{#each nodeListFiltered.slice(0, LIST_MAX) as n (n.id)}
								<button
									type="button"
									class="w-full text-left flex items-center gap-2 px-2.5 py-1.5 border-b border-gray-50 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition
										{selectedNode?.id === n.id
										? 'bg-red-50 dark:bg-red-900/20 border-l-2 border-l-red-500'
										: ''}"
									on:click={() => navigateToNode(n.id)}
								>
									<span
										class="inline-block w-2.5 h-2.5 rounded-full shrink-0"
										style:background-color={colorOf(n.node_type).bg}
									></span>
									<span class="text-[9px] uppercase text-gray-400 shrink-0">
										{TYPE_LABELS[n.node_type] ?? n.node_type}
									</span>
									<span class="text-xs text-gray-700 dark:text-gray-300 truncate">
										{n.label}
									</span>
								</button>
							{/each}
							{#if nodeListFiltered.length > LIST_MAX}
								<div class="p-2 text-[10px] text-gray-400 italic text-center">
									{$i18n.t('Showing first {{count}} — refine filter to see more', {
										count: LIST_MAX
									})}
								</div>
							{/if}
						{/if}
					{:else if edgeListFiltered.length === 0}
						<div class="p-4 text-xs text-gray-400 italic text-center">
							{$i18n.t('No edges match')}
						</div>
					{:else}
						{#each edgeListFiltered.slice(0, LIST_MAX) as item (item.id)}
							<button
								type="button"
								class="w-full text-left px-2.5 py-1.5 border-b border-gray-50 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition
									{selectedEdge?.id === item.id
									? 'bg-red-50 dark:bg-red-900/20 border-l-2 border-l-red-500'
									: ''}"
								on:click={() => navigateToEdge(item.id)}
							>
								<div class="flex items-center gap-1 mb-0.5">
									<span
										class="text-[9px] px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 shrink-0"
									>
										{edgeLabel(item.edge_type)}
									</span>
								</div>
								<div class="flex items-center gap-1 min-w-0">
									<span
										class="inline-block w-2 h-2 rounded-full shrink-0"
										style:background-color={colorOf(item.srcType).bg}
									></span>
									<span class="text-xs text-gray-700 dark:text-gray-300 truncate">
										{item.srcLabel}
									</span>
								</div>
								<div class="flex items-center gap-1 min-w-0 pl-3">
									<span class="text-[10px] text-gray-400 shrink-0">→</span>
									<span
										class="inline-block w-2 h-2 rounded-full shrink-0"
										style:background-color={colorOf(item.dstType).bg}
									></span>
									<span class="text-xs text-gray-700 dark:text-gray-300 truncate">
										{item.dstLabel}
									</span>
								</div>
							</button>
						{/each}
						{#if edgeListFiltered.length > LIST_MAX}
							<div class="p-2 text-[10px] text-gray-400 italic text-center">
								{$i18n.t('Showing first {{count}} — refine filter to see more', {
									count: LIST_MAX
								})}
							</div>
						{/if}
					{/if}
				</div>
			</div>
		{/if}

		<!-- Cytoscape canvas -->
		<div
			class="relative flex-1 bg-white dark:bg-gray-900 border border-[var(--cloo-border-subtle)] rounded-xl overflow-hidden"
		>
			{#if loading}
				<div class="absolute inset-0 flex items-center justify-center z-10 bg-white/60 dark:bg-gray-900/60">
					<Spinner />
				</div>
			{/if}
			<div bind:this={containerEl} class="w-full h-full"></div>
		</div>

		<!-- Detail Panel -->
		{#if selectedNode || selectedEdge}
			<div class="w-80 shrink-0 border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-900 overflow-y-auto">
				{#if selectedNode}
					<!-- Node Detail -->
					<div class="p-4">
						<!-- Header -->
						<div class="flex items-start justify-between mb-3">
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2 mb-1">
									<span
										class="inline-block w-3 h-3 rounded-full border-2 shrink-0"
										style:background-color={colorOf(selectedNode.node_type).bg}
										style:border-color={colorOf(selectedNode.node_type).border}
									></span>
									<span class="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
										{TYPE_LABELS[selectedNode.node_type] ?? selectedNode.node_type}
									</span>
								</div>
								<h4 class="text-base font-semibold text-gray-900 dark:text-white break-words">
									{selectedNode.label}
								</h4>
							</div>
							<button
								class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1 shrink-0"
								on:click={clearSelection}
							>
								<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						</div>

						<!-- Properties -->
						{#if selectedNode.properties && getDisplayProps(selectedNode.properties).length > 0}
							<div class="mb-4">
								<div class="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
									{$i18n.t('Properties')}
								</div>
								<div class="space-y-1.5">
									{#each getDisplayProps(selectedNode.properties) as [key, value]}
										<div class="flex flex-col">
											<span class="text-[10px] text-gray-400 dark:text-gray-500">{key}</span>
											<span class="text-xs text-gray-700 dark:text-gray-300 break-words">{value}</span>
										</div>
									{/each}
								</div>
							</div>
						{/if}

						<!-- Connected Edges -->
						{#if selectedNode.edges.length > 0}
							<div>
								<div class="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
									{$i18n.t('Connections')} ({selectedNode.edges.length})
								</div>
								<div class="space-y-1 max-h-64 overflow-y-auto">
									{#each selectedNode.edges as edge}
										<button
											class="w-full text-left px-2 py-1.5 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition group"
											on:click={() => navigateToNode(edge.neighbor.id)}
										>
											<div class="flex items-center gap-1.5">
												<span class="text-[10px] text-gray-400 shrink-0">
													{edge.direction === 'out' ? '→' : '←'}
												</span>
												<span class="text-[10px] px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 shrink-0">
													{edgeLabel(edge.edge_type)}
												</span>
												<span
													class="inline-block w-2 h-2 rounded-full shrink-0"
													style:background-color={colorOf(edge.neighbor.node_type).bg}
												></span>
												<span class="text-xs text-gray-700 dark:text-gray-300 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400">
													{edge.neighbor.label}
												</span>
											</div>
										</button>
									{/each}
								</div>
							</div>
						{:else}
							<div class="text-xs text-gray-400 italic">{$i18n.t('No connections')}</div>
						{/if}

						<!-- Node ID -->
						<div class="mt-4 pt-3 border-t border-gray-100 dark:border-gray-800">
							<div class="text-[10px] text-gray-400 dark:text-gray-500 break-all font-mono">
								ID: {selectedNode.id}
							</div>
						</div>
					</div>

				{:else if selectedEdge}
					<!-- Edge Detail -->
					<div class="p-4">
						<div class="flex items-start justify-between mb-3">
							<div>
								<div class="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-1">
									{$i18n.t('Edge')}
								</div>
								<Badge status="secondary" size="sm" content={edgeLabel(selectedEdge.edge_type)} />
							</div>
							<button
								class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1"
								on:click={clearSelection}
							>
								<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						</div>

						<!-- Source → Target -->
						<div class="space-y-2 mb-4">
							{#if selectedEdge.srcNode}
								<button
									class="w-full text-left px-2 py-2 rounded-md border border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
									on:click={() => selectedEdge?.srcNode && navigateToNode(selectedEdge.srcNode.id)}
								>
									<div class="text-[10px] text-gray-400 mb-0.5">Source</div>
									<div class="flex items-center gap-1.5">
										<span
											class="inline-block w-2.5 h-2.5 rounded-full"
											style:background-color={colorOf(selectedEdge.srcNode.node_type).bg}
										></span>
										<span class="text-sm text-gray-800 dark:text-gray-200">{selectedEdge.srcNode.label}</span>
										<span class="text-[10px] text-gray-400">({TYPE_LABELS[selectedEdge.srcNode.node_type] ?? selectedEdge.srcNode.node_type})</span>
									</div>
								</button>
							{/if}
							<div class="text-center text-gray-400 text-lg">↓</div>
							{#if selectedEdge.dstNode}
								<button
									class="w-full text-left px-2 py-2 rounded-md border border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
									on:click={() => selectedEdge?.dstNode && navigateToNode(selectedEdge.dstNode.id)}
								>
									<div class="text-[10px] text-gray-400 mb-0.5">Target</div>
									<div class="flex items-center gap-1.5">
										<span
											class="inline-block w-2.5 h-2.5 rounded-full"
											style:background-color={colorOf(selectedEdge.dstNode.node_type).bg}
										></span>
										<span class="text-sm text-gray-800 dark:text-gray-200">{selectedEdge.dstNode.label}</span>
										<span class="text-[10px] text-gray-400">({TYPE_LABELS[selectedEdge.dstNode.node_type] ?? selectedEdge.dstNode.node_type})</span>
									</div>
								</button>
							{/if}
						</div>

						<!-- Edge Properties -->
						{#if selectedEdge.weight !== null}
							<div class="text-xs text-gray-600 dark:text-gray-400 mb-2">
								Weight: <span class="font-medium">{selectedEdge.weight}</span>
							</div>
						{/if}
						{#if selectedEdge.properties && getDisplayProps(selectedEdge.properties).length > 0}
							<div class="mb-3">
								<div class="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
									{$i18n.t('Properties')}
								</div>
								<div class="space-y-1.5">
									{#each getDisplayProps(selectedEdge.properties) as [key, value]}
										<div class="flex flex-col">
											<span class="text-[10px] text-gray-400 dark:text-gray-500">{key}</span>
											<span class="text-xs text-gray-700 dark:text-gray-300 break-words">{value}</span>
										</div>
									{/each}
								</div>
							</div>
						{/if}

						<div class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
							<div class="text-[10px] text-gray-400 dark:text-gray-500 break-all font-mono">
								ID: {selectedEdge.id}
							</div>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<div class="text-xs text-gray-500">
		ⓘ {$i18n.t('Click a node to highlight its neighborhood. Click empty space to clear.')}
	</div>
</div>
