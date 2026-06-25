<script lang="ts">
	import { getContext } from 'svelte';
	import { writable } from 'svelte/store';
	import type { Readable } from 'svelte/store';
	import {
		SvelteFlow,
		Background,
		Controls,
		MiniMap,
		BackgroundVariant,
		MarkerType,
		type Node,
		type Edge,
		type ColorMode,
		type NodeTypes,
		type EdgeTypes
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import dagre from '@dagrejs/dagre';

	import { theme } from '$lib/stores';
	import Input from '$lib/components/common/Input.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import TableNode from './nodes/TableNode.svelte';
	import LabelNode from './nodes/LabelNode.svelte';
	import ErdViewportApi from './ErdViewportApi.svelte';
	import RelationshipEdge from './RelationshipEdge.svelte';
	import {
		ERD_NODE_W,
		nodeHeight,
		hasHiddenColumns,
		compactHeight,
		gridColumns,
		ERD_REGION_GAP,
		ERD_GRID_GAP_X,
		ERD_GRID_GAP_Y,
		ERD_LABEL_H
	} from './nodes/tableNodeLayout';
	import type { JoinGraphNode, JoinGraphEdge } from '$lib/apis/dbsphere';

	const ISOLATED_LABEL_ID = '__isolated_label__';
	const MINIMAP_THRESHOLD = 20;

	type I18nStore = Readable<{ t: (key: string, params?: Record<string, unknown>) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let nodes: JoinGraphNode[] = [];
	export let edges: JoinGraphEdge[] = [];

	// @xyflow-svelte 0.1.x types custom-node components too strictly for a
	// component-typed map; cast through unknown (standard workaround).
	const nodeTypes = { tableNode: TableNode, sectionLabel: LabelNode } as unknown as NodeTypes;
	const edgeTypes = { relationship: RelationshipEdge } as unknown as EdgeTypes;
	const flowNodes = writable<Node[]>([]);
	const flowEdges = writable<Edge[]>([]);

	// Viewport helpers (fit/center) live on a child rendered inside <SvelteFlow>
	// (ErdViewportApi) because useSvelteFlow() only works within the flow context.
	// xyflow 0.1.x `on:init` provides no instance, so we reach them via bind:this.
	let vp: {
		fitView?: (o?: Record<string, unknown>) => void;
		setCenter?: (x: number, y: number, o?: Record<string, unknown>) => void;
	} | null = null;

	const ROLE_KEYS = ['fact', 'dimension', 'bridge', 'unclassified'] as const;
	let activeRoles = new Set<string>(ROLE_KEYS);
	let searchQuery = '';
	let expanded = new Set<string>();
	let showList = true;
	// Focus drives highlight/dim. `hovered` is transient (mouse over a table); `pinned`
	// is sticky (click a node or edge to lock it, so you can zoom/pan while it stays
	// highlighted). A pinned target wins over hover. A table target lights the table + its
	// direct neighbours; an edge target lights its two endpoints + its ON-clause.
	type FocusTarget =
		| { kind: 'table'; table: string }
		| { kind: 'edge'; id: string; source: string; target: string };
	let hovered: FocusTarget | null = null;
	let pinned: FocusTarget | null = null;
	$: active = pinned ?? hovered;
	// Verified-only: hide inferred (dashed/candidate) edges so only real FKs show —
	// a pragmatic mute for inference noise (e.g. surrogate-id fan-out).
	let verifiedOnly = false;

	const roleLabel = (role: string): string => $i18n.t(role.charAt(0).toUpperCase() + role.slice(1));
	const roleDot = (role: string): string => {
		if (role === 'fact') return 'var(--cloo-color-info, #155dfc)';
		if (role === 'dimension') return 'var(--cloo-color-success, #008236)';
		if (role === 'bridge') return 'var(--cloo-color-warning, #d08700)';
		return 'var(--cloo-border-default, #9ca3af)';
	};
	// List ordering: group by role in the toolbar-chip order (fact → dimension →
	// bridge → unclassified), then alphabetical within a role — so the list reads the
	// same way the role chips up top do, instead of the backend's extraction order.
	const roleOrder = (role: string): number => {
		const i = (ROLE_KEYS as readonly string[]).indexOf(role);
		return i === -1 ? ROLE_KEYS.length : i;
	};

	// ── colorMode: mirror FlowBuilder.svelte:596-603 exactly (theme defaults to
	//    'system', which must resolve via matchMedia — a naive ===' dark' renders
	//    light in OS-dark mode). ──
	const resolveColorMode = (t: string): ColorMode =>
		t.includes('dark')
			? 'dark'
			: t === 'system'
				? typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light'
				: 'light';
	$: colorMode = resolveColorMode($theme);

	// ── derived indexes (recomputed on structure change) ──
	let edgeColsByTable = new Map<string, Set<string>>();
	let neighborsByTable = new Map<string, Set<string>>();
	let nodeIdByLower = new Map<string, string>();
	let positions = new Map<string, { x: number; y: number }>();
	let structureKey = '';
	// Tables with no relationship to ANY other table → laid out in the compact grid.
	let isolatedSet = new Set<string>();
	let isolatedLabelPos: { x: number; y: number } | null = null;

	const computeIndexes = () => {
		edgeColsByTable = new Map();
		neighborsByTable = new Map();
		nodeIdByLower = new Map();
		for (const n of nodes) nodeIdByLower.set(n.table.toLowerCase(), n.table);
		for (const e of edges) {
			const sl = e.source_table.toLowerCase();
			const tl = e.target_table.toLowerCase();
			if (!edgeColsByTable.has(sl)) edgeColsByTable.set(sl, new Set());
			if (!edgeColsByTable.has(tl)) edgeColsByTable.set(tl, new Set());
			e.source_columns.forEach((c) => edgeColsByTable.get(sl)?.add(c));
			e.target_columns.forEach((c) => edgeColsByTable.get(tl)?.add(c));
			if (sl !== tl) {
				if (!neighborsByTable.has(sl)) neighborsByTable.set(sl, new Set());
				if (!neighborsByTable.has(tl)) neighborsByTable.set(tl, new Set());
				neighborsByTable.get(sl)?.add(tl);
				neighborsByTable.get(tl)?.add(sl);
			}
		}
	};

	const edgeColsOf = (table: string): Set<string> =>
		edgeColsByTable.get(table.toLowerCase()) ?? new Set<string>();

	// The active target's context stays lit; everything else dims. Table target → the
	// table + its direct neighbours; edge target → its two endpoints.
	const isLit = (table: string): boolean => {
		if (!active) return true;
		const tl = table.toLowerCase();
		if (active.kind === 'edge')
			return tl === active.source.toLowerCase() || tl === active.target.toLowerCase();
		const f = active.table.toLowerCase();
		return tl === f || !!neighborsByTable.get(f)?.has(tl);
	};
	const setHover = (table: string | null) => {
		hovered = table ? { kind: 'table', table } : null;
	};
	// Click to pin (sticky focus). Re-clicking the same target unpins; clicking the empty
	// canvas (paneclick) clears. Pinning replaces any prior pin (table↔edge exclusive).
	const togglePinTable = (table: string) => {
		pinned = pinned?.kind === 'table' && pinned.table === table ? null : { kind: 'table', table };
	};
	const onNodeClick = (e: CustomEvent<{ node: { id: string } }>) =>
		togglePinTable(e.detail.node.id);
	const onEdgeClick = (
		e: CustomEvent<{ edge: { id: string; source: string; target: string } }>
	) => {
		const ed = e.detail.edge;
		pinned =
			pinned?.kind === 'edge' && pinned.id === ed.id
				? null
				: { kind: 'edge', id: ed.id, source: ed.source, target: ed.target };
	};
	const onPaneClick = () => {
		pinned = null;
	};
	// List click = pin that table (sticky focus) AND recentre the viewport on it.
	const selectFromList = (table: string) => {
		pinned = { kind: 'table', table };
		focusTable(table);
	};
	// Role filter HIDES; search + focus only DIM (so relationship context is kept).
	// A node dims when it's a search non-match, or — during focus — outside the lit set.
	const dimNode = (table: string, q: string): boolean =>
		(!!q && !table.toLowerCase().includes(q)) || (!!active && !isLit(table));

	const heightOf = (n: JoinGraphNode): number =>
		nodeHeight(n.columns, edgeColsOf(n.table), expanded.has(n.table));

	// Two-region layout: connected tables (≥1 relationship to another table) go
	// through dagre LR; isolated tables (no relationship) are packed into a compact
	// grid below — so a long tail of unrelated tables doesn't stretch into one row.
	// Positions stay stable across filtering (filter only toggles `hidden`).
	const computeLayout = () => {
		// Partition by connectivity (self-loops don't count as a relationship).
		const connectedTables = new Set<string>();
		for (const e of edges) {
			const s = nodeIdByLower.get(e.source_table.toLowerCase());
			const t = nodeIdByLower.get(e.target_table.toLowerCase());
			if (s && t && s !== t) {
				connectedTables.add(s);
				connectedTables.add(t);
			}
		}
		const connected = nodes.filter((n) => connectedTables.has(n.table));
		const isolated = nodes.filter((n) => !connectedTables.has(n.table));
		isolatedSet = new Set(isolated.map((n) => n.table));

		const pos = new Map<string, { x: number; y: number }>();

		// 1) connected → dagre LR
		let graphMinX = 0;
		let graphMaxY = 0;
		let graphWidth = 0;
		if (connected.length) {
			const g = new dagre.graphlib.Graph();
			g.setGraph({ rankdir: 'LR', nodesep: 36, ranksep: 90, marginx: 24, marginy: 24 });
			g.setDefaultEdgeLabel(() => ({}));
			for (const n of connected) g.setNode(n.table, { width: ERD_NODE_W, height: heightOf(n) });
			for (const e of edges) {
				const s = nodeIdByLower.get(e.source_table.toLowerCase());
				const t = nodeIdByLower.get(e.target_table.toLowerCase());
				if (s && t && s !== t) g.setEdge(s, t);
			}
			dagre.layout(g);
			let minX = Infinity;
			let maxX = -Infinity;
			let maxY = -Infinity;
			for (const n of connected) {
				const dn = g.node(n.table);
				if (!dn) continue;
				const h = heightOf(n);
				const x = dn.x - ERD_NODE_W / 2;
				const y = dn.y - h / 2;
				pos.set(n.table, { x, y });
				minX = Math.min(minX, x);
				maxX = Math.max(maxX, x + ERD_NODE_W);
				maxY = Math.max(maxY, y + h);
			}
			graphMinX = Number.isFinite(minX) ? minX : 0;
			graphMaxY = Number.isFinite(maxY) ? maxY : 0;
			graphWidth = Number.isFinite(maxX) && Number.isFinite(minX) ? maxX - minX : 0;
		}

		// 2) isolated → compact grid, packed row by row (row height = tallest in row,
		//    so an expanded card pushes only its own row down — no overlap).
		isolatedLabelPos = null;
		if (isolated.length) {
			const cols = gridColumns(isolated.length, graphWidth);
			const gridX = connected.length ? graphMinX : 24;
			const gridY = connected.length ? graphMaxY + ERD_REGION_GAP : ERD_LABEL_H + 24;
			isolatedLabelPos = { x: gridX, y: gridY - ERD_LABEL_H - 6 };
			let col = 0;
			let rowY = gridY;
			let rowH = 0;
			for (const n of isolated) {
				const h = expanded.has(n.table) ? heightOf(n) : compactHeight();
				pos.set(n.table, { x: gridX + col * (ERD_NODE_W + ERD_GRID_GAP_X), y: rowY });
				rowH = Math.max(rowH, h);
				col += 1;
				if (col >= cols) {
					col = 0;
					rowY += rowH + ERD_GRID_GAP_Y;
					rowH = 0;
				}
			}
		}
		positions = pos;
	};

	const onToggle = (table: string) => {
		if (expanded.has(table)) expanded.delete(table);
		else expanded.add(table);
		expanded = new Set(expanded); // reassign → structure key changes → relayout
	};
	const expandAll = () => {
		expanded = new Set(nodes.map((n) => n.table));
	};
	const collapseAll = () => {
		expanded = new Set();
	};

	const rebuild = () => {
		const q = searchQuery.trim().toLowerCase();
		const hidden = new Map<string, boolean>();
		// Role filter is the only thing that HIDES a node; search dims (below).
		for (const n of nodes) hidden.set(n.table, !activeRoles.has(n.role));

		const fNodes: Node[] = nodes.map((n) => {
			const ec = edgeColsOf(n.table);
			return {
				id: n.table,
				type: 'tableNode',
				position: positions.get(n.table) ?? { x: 0, y: 0 },
				hidden: hidden.get(n.table),
				style: dimNode(n.table, q) ? 'opacity:0.2;transition:opacity .15s' : undefined,
				data: {
					table: n.table,
					schema_name: n.schema_name,
					role: n.role,
					role_confidence: n.role_confidence,
					self_ref: n.self_ref,
					columns: n.columns,
					edgeCols: [...ec],
					expanded: expanded.has(n.table),
					hasHidden: hasHiddenColumns(n.columns, ec),
					isolated: isolatedSet.has(n.table),
					onToggle,
					onHover: setHover,
					pinned: pinned?.kind === 'table' && pinned.table === n.table
				}
			} as Node;
		});

		// Section label heading the isolated grid — hidden when the filter hides all
		// isolated tables (so the label doesn't dangle over an empty region).
		const visibleIsolated = nodes.filter(
			(n) => isolatedSet.has(n.table) && !hidden.get(n.table)
		).length;
		if (isolatedLabelPos && visibleIsolated > 0) {
			fNodes.push({
				id: ISOLATED_LABEL_ID,
				type: 'sectionLabel',
				position: isolatedLabelPos,
				selectable: false,
				draggable: false,
				data: { text: `${$i18n.t('Unrelated tables')} (${visibleIsolated})` }
			} as Node);
		}

		const fEdges: Edge[] = [];
		edges.forEach((e, ei) => {
			const s = nodeIdByLower.get(e.source_table.toLowerCase());
			const t = nodeIdByLower.get(e.target_table.toLowerCase());
			if (!s || !t) return;
			const inferred = e.relationship_type === 'inferred_name';
			if (verifiedOnly && inferred) return; // ② mute inferred-edge noise
			const eHidden = !!(hidden.get(s) || hidden.get(t));
			const searchMiss = !!q && !(s.toLowerCase().includes(q) || t.toLowerCase().includes(q));
			const selfLoop = s === t;
			const stroke = inferred ? '#94a3b8' : '#64748b';
			const relLabel = inferred ? $i18n.t('Inferred') : $i18n.t('Verified FK');
			const dash = inferred ? 'stroke-dasharray:6 4;' : '';
			// A table target lights every edge touching it; an edge target lights only
			// itself — resolved per pair below (each column-pair has its own id).
			// anchorSource only applies to a table-focused inbound edge.
			const tableFocus = active?.kind === 'table' && (s === active.table || t === active.table);
			const anchorSrc = active?.kind === 'table' && t === active.table;
			const pairs = Math.max(e.source_columns.length, e.target_columns.length, 1);
			for (let k = 0; k < pairs; k++) {
				const id = `e${ei}-${k}`;
				const onFocus = active?.kind === 'edge' ? id === active.id : tableFocus;
				const dimmed = (!!active && !onFocus) || searchMiss;
				const width = onFocus ? 2.5 : 1.5;
				const opacity = dimmed ? 'opacity:0.12;' : '';
				const sc = e.source_columns[k] ?? e.source_columns[0];
				const tc = e.target_columns[k] ?? e.target_columns[0];
				const tooltip = `${s}.${sc} → ${t}.${tc} · ${relLabel}`;
				fEdges.push({
					id,
					source: s,
					target: t,
					sourceHandle: sc ? `s-${sc}` : undefined,
					targetHandle: tc ? `t-${tc}` : undefined,
					type: 'relationship',
					// Carry the ON-clause text on every edge; RelationshipEdge reveals it when the
					// edge's table is focused (showLabel) or the edge itself is hovered — anchored at
					// its target end — so it's discoverable by hovering a table (a large target) yet
					// dense graphs aren't littered with always-on midpoint labels.
					data: {
						tooltip,
						label: sc && tc ? `${sc} = ${tc}` : undefined,
						selfLoop,
						showLabel: onFocus,
						// Inbound edge to the focused table (it's the target) → anchor the label at
						// the source card so a hub's many inbound labels spread out instead of
						// stacking on its single PK handle. Outbound keeps the target anchor.
						anchorSource: anchorSrc
					},
					animated: false,
					hidden: eHidden,
					// No raised z-index: the ON-clause label layer sits above edges, and the
					// arrowhead already clears the card via TIP_GAP — lifting the focused edge
					// (zIndex) would paint its arrowhead over the label. Prominence comes from
					// the bolder stroke + dimming the rest.
					style: `stroke:${stroke};stroke-width:${width};${dash}${opacity}`,
					markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 }
				} as Edge);
			}
		});

		flowNodes.set(fNodes);
		flowEdges.set(fEdges);
	};

	// Structure changed (nodes/edges props or expand) → reindex + relayout + rebuild.
	// Node-height changes (expand/collapse) realign handles automatically via
	// @xyflow's per-node ResizeObserver — no manual updateNodeInternals needed.
	$: {
		const key =
			nodes.map((n) => n.table).join('|') +
			'#' +
			edges.length +
			'#' +
			[...expanded].sort().join(',');
		if (key !== structureKey) {
			structureKey = key;
			computeIndexes();
			computeLayout();
			rebuild();
		}
	}
	// Filter/focus-only change (role/search/hover/pin) → rebuild styling, keep positions.
	$: if (structureKey) {
		activeRoles;
		searchQuery;
		active;
		pinned;
		verifiedOnly;
		rebuild();
	}

	$: roleCounts = nodes.reduce<Record<string, number>>((acc, n) => {
		acc[n.role] = (acc[n.role] ?? 0) + 1;
		return acc;
	}, {});
	$: allExpanded = nodes.length > 0 && nodes.every((n) => expanded.has(n.table));

	$: listTables = nodes
		.filter((n) => activeRoles.has(n.role))
		.filter((n) => {
			const q = searchQuery.trim().toLowerCase();
			return !q || n.table.toLowerCase().includes(q);
		})
		.sort((a, b) => roleOrder(a.role) - roleOrder(b.role) || a.table.localeCompare(b.table));

	const toggleRole = (r: string) => {
		if (activeRoles.has(r)) activeRoles.delete(r);
		else activeRoles.add(r);
		activeRoles = new Set(activeRoles);
	};

	const fitView = () => vp?.fitView?.({ duration: 400, padding: 0.15 });

	const focusTable = (table: string) => {
		const p = positions.get(table);
		const n = nodes.find((x) => x.table === table);
		if (!p || !n) return;
		const h = nodeHeight(n.columns, edgeColsOf(table), expanded.has(table));
		vp?.setCenter?.(p.x + ERD_NODE_W / 2, p.y + h / 2, { zoom: 1, duration: 400 });
	};
</script>

<div class="erd flex flex-col h-full w-full bg-[var(--cloo-bg-surface)]">
	<!-- Toolbar -->
	<div
		class="flex items-center gap-2 flex-wrap px-3 py-2 border-b border-[var(--cloo-border-default)]"
	>
		<div class="w-44">
			<Input bind:value={searchQuery} size="sm" placeholder={$i18n.t('Search tables')}>
				<svelte:fragment slot="prefix"><Search className="size-4" /></svelte:fragment>
			</Input>
		</div>

		<div class="flex items-center gap-1 flex-wrap">
			{#each ROLE_KEYS as rk}
				<button
					type="button"
					on:click={() => toggleRole(rk)}
					class="flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs transition-colors {activeRoles.has(
						rk
					)
						? 'border-[var(--cloo-border-default)] text-[var(--cloo-text-default)]'
						: 'border-transparent text-[var(--cloo-text-muted)] opacity-50'}"
					title={$i18n.t('Filter by role')}
				>
					<span class="inline-block size-2 rounded-full" style={`background:${roleDot(rk)}`}></span>
					{roleLabel(rk)}
					{roleCounts[rk] ?? 0}
				</button>
			{/each}
		</div>

		<div class="flex-1"></div>

		<button
			type="button"
			on:click={() => (verifiedOnly = !verifiedOnly)}
			class="px-2 py-0.5 rounded-full border text-xs transition-colors {verifiedOnly
				? 'border-[var(--cloo-color-info)] text-[var(--cloo-color-info)]'
				: 'border-[var(--cloo-border-default)] text-[var(--cloo-text-muted)]'}"
			title={$i18n.t('Verified FK only')}
		>
			{$i18n.t('Verified FK only')}
		</button>
		<Button kind="text" size="sm" on:click={() => (allExpanded ? collapseAll() : expandAll())}>
			{allExpanded ? $i18n.t('Collapse all') : $i18n.t('Expand all')}
		</Button>
		<Button kind="text" size="sm" on:click={fitView}>{$i18n.t('Fit to view')}</Button>
		<Button kind="text" size="sm" on:click={() => (showList = !showList)}>
			{showList ? $i18n.t('Hide list') : $i18n.t('Show list')}
		</Button>
	</div>

	<!-- Body: left list (also serves as the keyboard/SR-navigable fallback) + canvas -->
	<div class="flex flex-1 min-h-0">
		{#if showList}
			<aside
				class="w-60 shrink-0 overflow-y-auto border-r border-[var(--cloo-border-default)] p-3 text-sm"
			>
				<div class="font-semibold mb-2 text-[var(--cloo-text-primary)]">
					{$i18n.t('Tables')} ({listTables.length})
				</div>
				<ul class="flex flex-col gap-0.5">
					{#each listTables as n (n.table)}
						<li>
							<button
								type="button"
								class="w-full text-left flex items-center gap-2 px-2 py-1 rounded hover:bg-[var(--cloo-bg-neutral-hovered)]"
								on:click={() => selectFromList(n.table)}
								on:mouseenter={() => setHover(n.table)}
								on:mouseleave={() => setHover(null)}
								on:focus={() => setHover(n.table)}
								on:blur={() => setHover(null)}
							>
								<span
									class="inline-block size-2.5 rounded-sm shrink-0"
									style={`background:${roleDot(n.role)}`}
								></span>
								<span class="truncate text-[var(--cloo-text-default)]">{n.table}</span>
							</button>
						</li>
					{/each}
				</ul>
			</aside>
		{/if}

		<div class="relative flex-1 min-h-0">
			<SvelteFlow
				nodes={flowNodes}
				edges={flowEdges}
				{nodeTypes}
				{edgeTypes}
				{colorMode}
				fitView
				minZoom={0.2}
				maxZoom={2}
				nodesDraggable={false}
				nodesConnectable={false}
				elementsSelectable={false}
				proOptions={{ hideAttribution: true }}
				on:nodeclick={onNodeClick}
				on:edgeclick={onEdgeClick}
				on:paneclick={onPaneClick}
			>
				<ErdViewportApi bind:this={vp} />
				<Background variant={BackgroundVariant.Dots} gap={16} />
				<Controls showLock={false} />
				{#if nodes.length > MINIMAP_THRESHOLD}
					<MiniMap position="top-right" pannable zoomable />
				{/if}
			</SvelteFlow>

			{#if nodes.length === 0}
				<div
					class="absolute inset-0 flex items-center justify-center text-sm text-[var(--cloo-text-muted)] pointer-events-none"
				>
					{$i18n.t('No relationships to display')}
				</div>
			{:else if listTables.length === 0}
				<!-- All tables hidden by the role filter / search → tell the user, don't
				     leave a blank canvas. (listTables = nodes after filter + search.) -->
				<div
					class="absolute inset-0 flex items-center justify-center text-sm text-[var(--cloo-text-muted)] pointer-events-none"
				>
					{$i18n.t('No tables match')}
				</div>
			{/if}
		</div>
	</div>

	<!-- Legend: a static row below the canvas (not an overlay) so it never sits on
	     top of / clips fitView content behind it. -->
	<div
		class="flex items-center gap-3 flex-wrap px-3 py-1.5 text-xs border-t border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] text-[var(--cloo-text-muted)]"
	>
		{#each ROLE_KEYS as rk}
			<span class="flex items-center gap-1">
				<span class="inline-block size-2.5 rounded-sm" style={`background:${roleDot(rk)}`}
				></span>{roleLabel(rk)}
			</span>
		{/each}
		<span class="flex items-center gap-1">
			<span class="inline-block w-4 border-t-2 border-[#64748b]"></span>{$i18n.t('Verified FK')}
		</span>
		<span class="flex items-center gap-1">
			<span class="inline-block w-4 border-t-2 border-dashed border-[#94a3b8]"></span>{$i18n.t(
				'Inferred'
			)}
		</span>
	</div>
</div>

<style>
	/* @xyflow reads these CSS vars for its canvas chrome; map to --cloo tokens so
	   the graph background matches the design system in light/dark. */
	.erd :global(.svelte-flow) {
		background-color: var(--cloo-bg-default, #fafafa);
	}
</style>
