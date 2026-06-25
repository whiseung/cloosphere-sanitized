<script lang="ts">
	import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, Position } from '@xyflow/svelte';

	// @xyflow passes the full edge-prop set; we use geometry + style + data.
	export let sourceX: number = 0;
	export let sourceY: number = 0;
	export let targetX: number = 0;
	export let targetY: number = 0;
	export let sourcePosition: Position = Position.Right;
	export let targetPosition: Position = Position.Left;
	export let markerEnd: string | undefined = undefined;
	export let style: string | undefined = undefined;
	export let data: {
		tooltip?: string;
		label?: string;
		selfLoop?: boolean;
		showLabel?: boolean;
		anchorSource?: boolean;
	} = {};
	$: void $$restProps;

	// Stop the edge a few px short of the target card so the arrowhead sits in the gap
	// in front of it — the edges layer paints below the nodes layer, so a tip drawn at
	// the card border is covered by the card.
	const TIP_GAP = 9;
	$: tgtDX =
		targetPosition === Position.Left ? -TIP_GAP : targetPosition === Position.Right ? TIP_GAP : 0;
	$: tgtDY =
		targetPosition === Position.Top ? -TIP_GAP : targetPosition === Position.Bottom ? TIP_GAP : 0;
	$: smooth = getSmoothStepPath({
		sourceX,
		sourceY,
		targetX: targetX + tgtDX,
		targetY: targetY + tgtDY,
		sourcePosition,
		targetPosition
	});
	// Self-referencing FK (source === target): smooth-step degenerates, so arc a
	// compact loop over the top of the node back into it.
	$: edgePath = data?.selfLoop
		? `M ${sourceX},${sourceY} C ${sourceX + 60},${sourceY - 50} ${targetX - 60},${targetY - 50} ${targetX},${targetY}`
		: smooth[0];
	// ON-clause label shows when this edge's table is focused (data.showLabel, set by
	// ErdView on table hover — a large, discoverable target) OR while THIS edge is
	// hovered. It anchors at the NEIGHBOUR (non-focused) card end so labels always
	// spread across distinct cards instead of floating mid-canvas: by default the
	// target end (reads "joining into <target>"), but for an edge whose target IS the
	// focused table (data.anchorSource — i.e. inbound to a hub), the source end — else
	// every inbound edge piles its label onto the hub's single PK handle.
	let hovered = false;
	$: anchorSource = !!data?.anchorSource;
	$: anchorX = data?.selfLoop ? (sourceX + targetX) / 2 : anchorSource ? sourceX : targetX + tgtDX;
	$: anchorY = data?.selfLoop ? sourceY - 40 : anchorSource ? sourceY : targetY + tgtDY;
	$: anchorPos = anchorSource ? sourcePosition : targetPosition;
	$: labelTransform = data?.selfLoop
		? `translate(-50%, -120%) translate(${anchorX}px, ${anchorY}px)`
		: anchorPos === Position.Left
			? `translate(-100%, -50%) translate(${anchorX - 8}px, ${anchorY}px)`
			: anchorPos === Position.Right
				? `translate(0, -50%) translate(${anchorX + 8}px, ${anchorY}px)`
				: anchorPos === Position.Top
					? `translate(-50%, -100%) translate(${anchorX}px, ${anchorY - 8}px)`
					: `translate(-50%, 0) translate(${anchorX}px, ${anchorY + 8}px)`;
</script>

<BaseEdge path={edgePath} {markerEnd} {style} />
<!-- Wide transparent overlay = comfortable hover target + a native <title> tooltip
     (which column ↔ which column + relationship type). Hovering it thickens the
     visible edge via the CSS rule below (`.svelte-flow__edge:hover`). -->
<path
	d={edgePath}
	fill="none"
	stroke="transparent"
	stroke-width="16"
	class="erd-edge-hit"
	role="presentation"
	on:mouseenter={() => (hovered = true)}
	on:mouseleave={() => (hovered = false)}
>
	<title>{data?.tooltip ?? ''}</title>
</path>
{#if (data?.showLabel || hovered) && data?.label}
	<!-- ON-clause: shown on table focus (data.showLabel) or edge hover, anchored at the neighbour card end. -->
	<EdgeLabelRenderer>
		<div class="erd-edge-label nodrag nopan" style="transform: {labelTransform};">
			{data.label}
		</div>
	</EdgeLabelRenderer>
{/if}

<style>
	.erd-edge-hit {
		pointer-events: stroke;
		cursor: help;
	}
	/* Thicken the visible edge while its (wide, invisible) hit area is hovered. */
	:global(.svelte-flow__edge:hover .svelte-flow__edge-path) {
		stroke-width: 3 !important;
	}
	/* The label layer and the nodes layer are both z-index 0, but nodes come later in
	   the DOM → an ON-clause label sitting between two close cards gets covered by
	   them. Lift the label layer above the nodes so labels stay fully visible on focus. */
	:global(.svelte-flow__edgelabel-renderer) {
		z-index: 5;
	}
	.erd-edge-label {
		position: absolute;
		pointer-events: none;
		font-size: 10px;
		font-family: ui-monospace, Menlo, monospace;
		background: var(--cloo-bg-surface, #fff);
		color: var(--cloo-text-default, #1a1a1a);
		border: 1px solid var(--cloo-border-default, #d1d5db);
		border-radius: 4px;
		padding: 1px 5px;
		white-space: nowrap;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
	}
</style>
