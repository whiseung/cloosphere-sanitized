<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Badge from '$lib/components/common/Badge.svelte';
	import type { JoinGraphColumn, TableRole } from '$lib/apis/dbsphere';
	import { ERD_HEADER_H, ERD_ROW_H, ERD_NODE_W } from './tableNodeLayout';

	type I18nStore = Readable<{ t: (key: string, params?: Record<string, unknown>) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	type TableNodeData = {
		table: string;
		schema_name?: string | null;
		role: TableRole;
		role_confidence?: 'high' | 'likely' | null;
		self_ref: boolean;
		columns: JoinGraphColumn[];
		/** Column names that are an endpoint of some edge (always kept visible). */
		edgeCols: string[];
		expanded: boolean;
		hasHidden: boolean;
		/** True for isolated (no-relationship) tables — rendered in the compact grid. */
		isolated: boolean;
		onToggle: (table: string) => void;
		/** Hover in/out → drives ErdView focus-highlight (null = unfocus). */
		onHover: (table: string | null) => void;
		/** True when this table is the sticky (clicked) focus target → ring. */
		pinned: boolean;
	};

	// @xyflow injects the full node-prop set (id, draggable, width, …); this
	// read-only node only uses `data` + `selected`. Referencing `$$restProps`
	// opts out of Svelte's "unknown prop" dev warnings without declaring each.
	export let data: Record<string, unknown> = {};
	export let selected: boolean = false;
	$: void $$restProps;

	$: d = (data ?? {}) as unknown as TableNodeData;

	// Role → Badge status.
	const roleBadgeStatus = (role: string): 'info' | 'success' | 'warning' | 'default' => {
		if (role === 'fact') return 'info';
		if (role === 'dimension') return 'success';
		if (role === 'bridge') return 'warning';
		return 'default';
	};
	const roleLabel = (role: string): string => $i18n.t(role.charAt(0).toUpperCase() + role.slice(1));

	// Role accent via --cloo semantic tokens only (no invented palette — the whole
	// point of the @xyflow pivot is DS-native styling).
	const roleAccent = (role: string): string => {
		if (role === 'fact') return 'var(--cloo-color-info, #155dfc)';
		if (role === 'dimension') return 'var(--cloo-color-success, #008236)';
		if (role === 'bridge') return 'var(--cloo-color-warning, #d08700)';
		return 'var(--cloo-border-default, #d1d5db)';
	};

	// Postgres' information_schema returns verbose type names (character varying,
	// timestamp without time zone); abbreviate to the familiar canonical short forms so
	// they fit the column. Length/precision suffix kept; full type stays in the tooltip.
	const TYPE_ABBR: Record<string, string> = {
		'character varying': 'varchar',
		character: 'char',
		'timestamp without time zone': 'timestamp',
		'timestamp with time zone': 'timestamptz',
		'time without time zone': 'time',
		'time with time zone': 'timetz',
		'double precision': 'double',
		boolean: 'bool',
		integer: 'int'
	};
	const normalizeType = (t: string | null | undefined): string => {
		if (!t) return '';
		const i = t.indexOf('(');
		const base = (i >= 0 ? t.slice(0, i) : t).trim();
		const suffix = i >= 0 ? t.slice(i).replace(/\s+/g, '') : '';
		return (TYPE_ABBR[base.toLowerCase()] ?? base) + suffix;
	};

	// Expand/collapse is a disclosure caret IN THE HEADER (not a bottom button) so the
	// collapse control stays pinned at the top however tall the card grows. Isolated
	// tables collapse to header-only; connected tables collapse to key columns.
	$: toggleable = d.isolated ? true : d.hasHidden;
	$: visibleCols =
		d.isolated && !d.expanded
			? []
			: d.expanded
				? d.columns
				: d.columns.filter(
						(c) => c.is_primary_key || c.is_foreign_key || d.edgeCols.includes(c.name)
					);
	$: toggleTitle = d.expanded
		? d.isolated
			? $i18n.t('Show header only')
			: $i18n.t('Show key columns only')
		: $i18n.t('Show all columns ({{n}})', { n: d.columns.length });
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<div
	class="erd-node {d.pinned ? 'is-pinned' : ''} {selected ? 'is-selected' : ''}"
	style="width: {ERD_NODE_W}px; border-left-color: {roleAccent(d.role)};"
	on:mouseenter={() => d.onHover(d.table)}
	on:mouseleave={() => d.onHover(null)}
>
	{#if toggleable}
		<!-- Header IS the expand/collapse control: a disclosure caret that never leaves
		     the top, so a tall card is always one click from collapsing. -->
		<button
			type="button"
			class="erd-node__header erd-node__header--btn {visibleCols.length === 0
				? 'is-headeronly'
				: ''}"
			style="height: {ERD_HEADER_H}px;"
			on:click|stopPropagation={() => d.onToggle(d.table)}
			aria-expanded={d.expanded}
			title={toggleTitle}
		>
			<span class="erd-node__title" title={d.table}>{d.table}</span>
			{#if d.self_ref}
				<span class="erd-node__selfref" title={$i18n.t('Self-referencing')}>↻</span>
			{/if}
			<Badge status={roleBadgeStatus(d.role)} size="sm" content={roleLabel(d.role)} />
			<span class="erd-node__count">{d.columns.length}</span>
			<span class="erd-node__caret" aria-hidden="true">{d.expanded ? '▾' : '▸'}</span>
		</button>
	{:else}
		<div class="erd-node__header" style="height: {ERD_HEADER_H}px;">
			<span class="erd-node__title" title={d.table}>{d.table}</span>
			{#if d.self_ref}
				<span class="erd-node__selfref" title={$i18n.t('Self-referencing')}>↻</span>
			{/if}
			<Badge status={roleBadgeStatus(d.role)} size="sm" content={roleLabel(d.role)} />
		</div>
	{/if}

	{#each visibleCols as c (c.name)}
		<div class="erd-col" style="height: {ERD_ROW_H}px;">
			<Handle
				type="target"
				position={Position.Left}
				id={`t-${c.name}`}
				isConnectable={false}
				class="erd-handle"
			/>
			<span class="erd-col__name {c.is_primary_key ? 'is-pk' : ''}" title={c.name}>{c.name}</span>
			{#if c.is_primary_key}
				<span class="erd-col__key erd-col__key--pk" title={$i18n.t('Primary key')}>PK</span>
			{/if}
			{#if c.is_foreign_key}
				<span class="erd-col__key erd-col__key--fk" title={`FK → ${c.foreign_table ?? '?'}`}
					>FK</span
				>
			{/if}
			{#if c.data_type}
				<span class="erd-col__type" title={c.data_type}>{normalizeType(c.data_type)}</span>
			{/if}
			<Handle
				type="source"
				position={Position.Right}
				id={`s-${c.name}`}
				isConnectable={false}
				class="erd-handle"
			/>
		</div>
	{/each}
</div>

<style>
	.erd-node {
		box-sizing: border-box;
		background: var(--cloo-bg-surface, #fff);
		border: 1px solid var(--cloo-border-default, #d1d5db);
		border-left-width: 4px;
		border-radius: var(--cloo-radius-default, 6px);
		overflow: hidden;
		font-size: 12px;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
	}
	.erd-node.is-selected {
		box-shadow: 0 0 0 2px var(--cloo-color-info, #155dfc);
	}
	/* Sticky (clicked) focus target — a ring so a pinned table reads as locked, distinct
	   from the transient hover highlight (which only lights neighbours, no ring). */
	.erd-node.is-pinned {
		box-shadow: 0 0 0 2px var(--cloo-color-info, #155dfc);
	}
	.erd-node__header {
		box-sizing: border-box;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 10px;
		background: var(--cloo-bg-neutral-hovered, #f3f4f6);
		border-bottom: 1px solid var(--cloo-border-default, #d1d5db);
	}
	/* Header doubles as the disclosure control. Reset button chrome so it matches the
	   plain header; keep the bottom divider when columns follow, drop it for a
	   header-only (collapsed isolated) card so there's no line above the card edge. */
	.erd-node__header--btn {
		width: 100%;
		border: none;
		border-bottom: 1px solid var(--cloo-border-default, #d1d5db);
		cursor: pointer;
		text-align: left;
		font: inherit;
		color: inherit;
	}
	.erd-node__header--btn.is-headeronly {
		border-bottom: none;
	}
	.erd-node__header--btn:hover {
		background: var(--cloo-surface-hover, #eef0f3);
	}
	.erd-node__caret {
		font-size: 10px;
		color: var(--cloo-text-muted, #6b7280);
		flex-shrink: 0;
		width: 10px;
		text-align: center;
	}
	.erd-node__count {
		font-size: 10px;
		color: var(--cloo-text-muted, #6b7280);
		flex-shrink: 0;
		font-variant-numeric: tabular-nums;
	}
	.erd-node__title {
		font-weight: 600;
		color: var(--cloo-text-primary, #111827);
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.erd-node__selfref {
		color: var(--cloo-text-muted, #6b7280);
		flex-shrink: 0;
	}
	.erd-col {
		box-sizing: border-box;
		position: relative;
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 0 10px;
		border-bottom: 1px solid var(--cloo-border-subtle, #eceef1);
		color: var(--cloo-text-default, #1a1a1a);
	}
	.erd-col__name {
		flex: 0 1 auto;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.erd-col__name.is-pk {
		font-weight: 600;
	}
	.erd-col__key {
		font-size: 10px;
		font-weight: 600;
		flex-shrink: 0;
		letter-spacing: 0.02em;
	}
	.erd-col__key--pk {
		color: var(--cloo-color-warning, #d08700);
	}
	.erd-col__key--fk {
		color: var(--cloo-color-info, #155dfc);
	}
	.erd-col__type {
		color: var(--cloo-text-muted, #6b7280);
		font-size: 11px;
		margin-left: auto;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 96px;
		flex-shrink: 0;
	}
	/* Handles are invisible edge anchors only (read-only graph). Hidden — not just
	   subtle — because the node uses overflow:hidden (for the rounded header), which
	   would clip the outer half of any visible dot sitting on the border. Edges
	   render in a separate SVG layer, so they still attach at the exact border. */
	.erd-node :global(.erd-handle) {
		width: 1px;
		height: 1px;
		min-width: 0;
		min-height: 0;
		background: transparent;
		border: none;
		opacity: 0;
		pointer-events: none;
	}
</style>
