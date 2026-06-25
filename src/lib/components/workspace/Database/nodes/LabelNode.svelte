<script lang="ts">
	// Non-interactive section label rendered as an @xyflow node (so it pans/zooms
	// with the canvas). Used to head the "unrelated tables" grid region.
	// @xyflow injects the full node-prop set; we only need `data`. Referencing
	// $$restProps opts out of "unknown prop" dev warnings.
	export let data: Record<string, unknown> = {};
	$: void $$restProps;
	$: text = (data?.text as string) ?? '';
</script>

<div class="erd-section-label">{text}</div>

<style>
	.erd-section-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--cloo-text-muted, #6b7280);
		white-space: nowrap;
		pointer-events: none;
		user-select: none;
	}
</style>
