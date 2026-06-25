<script lang="ts">
	import DOMPurify from 'dompurify';

	import { onDestroy } from 'svelte';
	import { marked } from 'marked';

	import tippy from 'tippy.js';
	import type { Instance } from 'tippy.js';
	import { roundArrow } from 'tippy.js';

	export let placement = 'top';
	export let content = `I'm a tooltip!`;
	export let touch = true;
	export let className = 'flex';
	export let theme = '';
	export let offset = [0, 4];
	export let allowHTML = true;
	export let tippyOptions: Record<string, unknown> = {};

	// === Interactive popover 확장 props ===
	export let interactive = false;
	export let trigger: string | undefined = undefined;
	export let appendTo: 'parent' | (() => HTMLElement) | undefined = undefined;
	export let hideOnClick: boolean | 'toggle' | undefined = undefined;
	export let interactiveBorder = 0;
	export let hideOnEsc = true;
	export let maxWidth: number | string | undefined = undefined;
	export let onShow: ((instance: Instance) => boolean | void) | undefined = undefined;
	export let onHide: ((instance: Instance) => boolean | void) | undefined = undefined;
	export let onMount: ((instance: Instance) => void) | undefined = undefined;
	export let wrapperTag: 'div' | 'span' = 'div';

	let tooltipElement: HTMLElement;
	let tooltipInstance: Instance | undefined;
	let escHandler: ((e: KeyboardEvent) => void) | undefined;

	function buildOptions(): Record<string, unknown> {
		return {
			content: DOMPurify.sanitize(content),
			placement,
			allowHTML,
			touch,
			...(theme !== '' ? { theme } : { theme: 'dark' }),
			arrow: false,
			offset,
			interactive,
			...(trigger ? { trigger } : {}),
			...(appendTo ? { appendTo } : {}),
			...(hideOnClick !== undefined ? { hideOnClick } : {}),
			...(maxWidth !== undefined ? { maxWidth } : {}),
			...(interactive ? { interactiveBorder } : {}),
			onShow: (inst: Instance) => {
				if (hideOnEsc) {
					escHandler = (e: KeyboardEvent) => {
						if (e.key === 'Escape') inst.hide();
					};
					document.addEventListener('keydown', escHandler);
				}
				return onShow ? onShow(inst) : undefined;
			},
			onHide: (inst: Instance) => {
				if (escHandler) {
					document.removeEventListener('keydown', escHandler);
					escHandler = undefined;
				}
				return onHide ? onHide(inst) : undefined;
			},
			...(onMount ? { onMount } : {}),
			...tippyOptions
		};
	}

	$: if (tooltipElement && content) {
		if (tooltipInstance) {
			tooltipInstance.setContent(DOMPurify.sanitize(content));
		} else {
			tooltipInstance = tippy(tooltipElement, buildOptions() as Parameters<typeof tippy>[1]);
		}
	} else if (tooltipInstance && content === '') {
		tooltipInstance.destroy();
		tooltipInstance = undefined;
	}

	export function show() {
		tooltipInstance?.show();
	}
	export function hide() {
		tooltipInstance?.hide();
	}
	export function getInstance(): Instance | undefined {
		return tooltipInstance;
	}

	onDestroy(() => {
		if (escHandler) {
			document.removeEventListener('keydown', escHandler);
		}
		if (tooltipInstance) {
			tooltipInstance.destroy();
		}
	});
</script>

<svelte:element
	this={wrapperTag}
	bind:this={tooltipElement}
	aria-label={interactive ? undefined : DOMPurify.sanitize(content)}
	class={className}
>
	<slot />
</svelte:element>
