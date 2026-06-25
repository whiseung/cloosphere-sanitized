// Shared geometry for the DBSphere ERD (TableNode + dagre layout).
// The row-height constants are the SINGLE SOURCE OF TRUTH: `ErdView` uses them
// to tell dagre each node's size, and `TableNode` applies the same values as
// inline CSS heights. If they drift, dagre lays nodes out at the wrong size and
// edges/handles misalign — so both consumers import from here.
import type { JoinGraphColumn } from '$lib/apis/dbsphere';

export const ERD_HEADER_H = 42;
export const ERD_ROW_H = 26;
export const ERD_NODE_W = 216;

/** Columns shown when a node is collapsed: keys + any column that is an FK/PK
 * edge endpoint (so every rendered edge always has a visible handle to attach to). */
export const collapsedColumns = (
	columns: JoinGraphColumn[],
	edgeCols: Set<string>
): JoinGraphColumn[] =>
	columns.filter((c) => c.is_primary_key || c.is_foreign_key || edgeCols.has(c.name));

export const visibleColumns = (
	columns: JoinGraphColumn[],
	edgeCols: Set<string>,
	expanded: boolean
): JoinGraphColumn[] => (expanded ? columns : collapsedColumns(columns, edgeCols));

/** True when collapsing actually hides something (drives the expand/collapse toggle). */
export const hasHiddenColumns = (columns: JoinGraphColumn[], edgeCols: Set<string>): boolean =>
	columns.length > collapsedColumns(columns, edgeCols).length;

/** Pixel height dagre must reserve for a node — must match TableNode's rendered height.
 * Header (always) + one row per visible column. Expand/collapse is a header disclosure
 * caret (not a bottom button), so there is no separate toggle row to reserve. */
export const nodeHeight = (
	columns: JoinGraphColumn[],
	edgeCols: Set<string>,
	expanded: boolean
): number => {
	const rows = visibleColumns(columns, edgeCols, expanded).length;
	return ERD_HEADER_H + rows * ERD_ROW_H;
};

// ── Isolated-table grid (tables with no relationships) ──
// Isolated nodes are packed into a compact grid below the relationship graph so a
// large number of unrelated tables doesn't stretch into one long dagre row.
export const ERD_REGION_GAP = 60; // vertical gap between the graph and the grid
export const ERD_GRID_GAP_X = 24;
export const ERD_GRID_GAP_Y = 20;
export const ERD_LABEL_H = 22; // section-label node height

/** Height of a compact (header-only) isolated card. */
export const compactHeight = (): number => ERD_HEADER_H;

/** Column count for the isolated grid: matched to the graph's width when present,
 * otherwise a near-square grid. Clamped to a sane range and never wider than count. */
export const gridColumns = (count: number, graphWidth: number): number => {
	if (count <= 0) return 1;
	const target =
		graphWidth > 0
			? Math.floor(graphWidth / (ERD_NODE_W + ERD_GRID_GAP_X)) || 2
			: Math.ceil(Math.sqrt(count * 1.6));
	return Math.max(2, Math.min(12, Math.min(target, count)));
};
