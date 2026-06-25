/**
 * Svelte action: portal an element to a different DOM location while keeping
 * it under Svelte's lifecycle. Useful for dropdowns/menus that need to escape
 * an `overflow: hidden / auto` ancestor.
 *
 * Usage:
 *   <div use:portal>...</div>                  // → document.body
 *   <div use:portal={'#some-target'}>...</div> // → matched element
 *   <div use:portal={null}>...</div>           // disable (stay in place)
 *
 * The action remembers the original parent (via a comment placeholder) and
 * restores the node to it on disable/destroy so Svelte can clean up safely.
 */
export type PortalTarget = string | HTMLElement | null | undefined;

export function portal(node: HTMLElement, target: PortalTarget = 'body') {
	const placeholder = document.createComment('portal-anchor');
	let portaled = false;

	const resolve = (t: PortalTarget): HTMLElement | null => {
		if (!t) return null;
		if (typeof t === 'string') return document.querySelector<HTMLElement>(t);
		return t;
	};

	const moveTo = (t: PortalTarget) => {
		const dest = resolve(t);
		if (!dest) {
			// Target falsy or missing → restore to original location.
			if (portaled && placeholder.parentNode) {
				placeholder.parentNode.insertBefore(node, placeholder);
				placeholder.remove();
				portaled = false;
			}
			return;
		}
		if (node.parentNode === dest) return; // already there
		if (!portaled && node.parentNode) {
			// First portal — drop a placeholder where the node currently is.
			node.parentNode.insertBefore(placeholder, node);
			portaled = true;
		}
		dest.appendChild(node);
	};

	moveTo(target);

	return {
		update(t: PortalTarget) {
			moveTo(t);
		},
		destroy() {
			// We moved the node to a new parent. The previous strategy
			// (restore-to-placeholder) failed when the original parent had
			// already been detached by the time this destroy ran — leaving
			// the node orphaned in `<body>` forever. Simpler and more robust:
			// always detach the node ourselves. Svelte's subsequent
			// removeChild on an already-detached node is a safe no-op.
			if (portaled) {
				node.remove();
				placeholder.remove();
				portaled = false;
			}
		}
	};
}
