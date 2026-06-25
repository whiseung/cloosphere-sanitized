<script lang="ts">
	// Renders nothing. It exists to live INSIDE <SvelteFlow> (like Controls/MiniMap)
	// so it can call useSvelteFlow(), which only works within the flow context.
	// ErdView's toolbar/list sit OUTSIDE that context and reach these helpers via
	// `bind:this`. (xyflow 0.1.x `on:init` passes no instance — `e.detail` is
	// undefined — so the event route can't supply fitView/setCenter.)
	import { useSvelteFlow } from '@xyflow/svelte';

	const sf = useSvelteFlow();

	export const fitView = (options?: Record<string, unknown>): void => {
		sf.fitView(options);
	};
	export const setCenter = (x: number, y: number, options?: Record<string, unknown>): void => {
		sf.setCenter(x, y, options);
	};
</script>
