<script context="module" lang="ts">
	type TippyLikeInstance = { hide: () => void; popper: HTMLElement };
	// Singleton: 한 번에 하나의 popover 만 열림 — 새 popover 가 열리면 이전 것 자동 닫힘.
	// 모듈 스코프 변수는 클라이언트 상호작용(onShow)에서만 set 되므로 SSR 누수 없음.
	let currentInstance: TippyLikeInstance | undefined;
</script>

<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { copyToClipboard } from '$lib/utils';
	import {
		type Citation,
		buildCitationCopyText,
		escapeHtml,
		getDecodedName,
		getFaviconUrl,
		getFirstSnippet,
		getHostname,
		getPageNumber,
		getRelevanceColorClass,
		getRelevancePercentage
	} from '$lib/utils/citations';

	export let index: number;
	export let citation: Citation;
	export let messageId: string;
	export let showPercentage = false;
	export let showRelevance = true;

	const i18n = getContext('i18n') as any;

	let tooltipRef: Tooltip | undefined;
	let popperListener: ((e: MouseEvent) => void) | undefined;

	$: name = getDecodedName(citation);
	$: snippet = getFirstSnippet(citation, 1200);
	$: page = getPageNumber(citation);
	$: distance = citation.distances?.[0];
	$: percentage = getRelevancePercentage(distance);
	$: copyText = buildCitationCopyText(citation);

	// 웹 source 분기 — source.url 존재 시 외부 링크 chip 으로 렌더
	$: webUrl = citation.source?.url ?? '';
	$: isWeb = !!webUrl;
	$: host = isWeb ? getHostname(webUrl) : '';
	$: faviconUrl = isWeb ? getFaviconUrl(webUrl) : '';
	let faviconFailed = false;
	$: if (faviconUrl) faviconFailed = false;

	$: ariaLabel =
		page !== null
			? `${$i18n.t('Citation')} ${index}: ${name}, ${$i18n.t('page')} ${page}`
			: `${$i18n.t('Citation')} ${index}: ${name}`;

	// 인자로 명시 — Svelte reactive 가 함수 호출 인자만 추적하므로
	// closure 변수 사용 시 첫 frame 에 page=undefined 가 박혀 굳는 버그 방지
	$: popoverContent = buildPopoverHtml(
		name,
		snippet,
		page,
		distance,
		percentage,
		showRelevance,
		showPercentage,
		$i18n.t('Copy Citation'),
		$i18n.t('page')
	);

	function buildPopoverHtml(
		_name: string,
		_snippet: string,
		_page: number | null,
		_distance: number | undefined,
		_percentage: number | null,
		_showRelevance: boolean,
		_showPercentage: boolean,
		tCopy: string,
		tPage: string
	): string {
		const escName = escapeHtml(_name);
		const escSnippet = escapeHtml(_snippet);

		const pageHtml =
			_page !== null ? `<span class="cloo-cb__meta-page">${tPage} ${_page}</span>` : '';

		let relevanceHtml = '';
		if (_showRelevance && _distance !== undefined) {
			const cls = getRelevanceColorClass(_percentage ?? 0);
			const text =
				_showPercentage && _percentage !== null
					? `${_percentage.toFixed(0)}%`
					: `${_distance.toFixed(3)}`;
			relevanceHtml = `<span class="cloo-cb__relevance ${cls}">${text}</span>`;
		}

		const snippetHtml = escSnippet ? `<div class="cloo-cb__snippet">${escSnippet}</div>` : '';
		const metaHtml =
			pageHtml || relevanceHtml
				? `<div class="cloo-cb__meta">${pageHtml}${relevanceHtml}</div>`
				: '';

		return `
<div class="cloo-cb">
  <div class="cloo-cb__title" title="${escName}">${escName || '&nbsp;'}</div>
  ${metaHtml}
  ${snippetHtml}
  <div class="cloo-cb__actions">
    <button type="button" data-action="copy" class="cloo-cb__btn cloo-cb__btn--primary">${tCopy}</button>
  </div>
</div>`;
	}

	async function copyHandler() {
		const ok = await copyToClipboard(copyText);
		if (ok) {
			toast.success($i18n.t('Citation Copied'));
		} else {
			toast.error(copyText);
		}
	}

	function handlePopperClick(e: MouseEvent) {
		const trigger = (e.target as HTMLElement | null)?.closest(
			'[data-action]'
		) as HTMLElement | null;
		if (!trigger) return;
		const action = trigger.getAttribute('data-action');
		if (action === 'copy') {
			void copyHandler();
		}
	}

	function handleShow(inst: TippyLikeInstance) {
		if (currentInstance && currentInstance !== inst) {
			try {
				currentInstance.hide();
			} catch {
				// noop
			}
		}
		currentInstance = inst;
		if (!popperListener) {
			popperListener = handlePopperClick;
			inst.popper?.addEventListener('click', popperListener);
		}
	}

	function handleHide(inst: TippyLikeInstance) {
		if (popperListener) {
			inst.popper?.removeEventListener('click', popperListener);
			popperListener = undefined;
		}
		if (currentInstance === inst) {
			currentInstance = undefined;
		}
	}
</script>

<Tooltip
	bind:this={tooltipRef}
	content={popoverContent}
	interactive
	trigger="mouseenter focus click"
	placement="top"
	appendTo={() => document.body}
	hideOnClick={true}
	interactiveBorder={10}
	tippyOptions={{ delay: [150, 100] }}
	maxWidth={360}
	theme="cloo-citation"
	className="inline-flex align-baseline"
	wrapperTag="span"
	onShow={handleShow}
	onHide={handleHide}
>
	{#if isWeb}
		<a
			href={webUrl}
			target="_blank"
			rel="noopener noreferrer"
			class="cloo-cb__web-chip"
			aria-label={ariaLabel}
			data-citation-index={index}
			id={`source-${messageId}-${index}`}
		>
			{#if faviconUrl && !faviconFailed}
				<img
					class="cloo-cb__web-favicon"
					src={faviconUrl}
					alt=""
					width="14"
					height="14"
					loading="lazy"
					on:error={() => (faviconFailed = true)}
				/>
			{/if}
			{#if host}
				<span class="cloo-cb__web-host">{host}</span>
			{/if}
		</a>
	{:else}
		<button
			type="button"
			class="cloo-cb__chip"
			aria-label={ariaLabel}
			aria-haspopup="dialog"
			data-citation-index={index}
			id={`source-${messageId}-${index}`}
		>
			<Badge size="sm" status="info" invert>{index}</Badge>
		</button>
	{/if}
</Tooltip>

<style>
	.cloo-cb__chip {
		background: transparent;
		border: 0;
		padding: 0;
		cursor: pointer;
		line-height: 0;
	}
	.cloo-cb__chip:focus-visible {
		outline: 2px solid var(--cloo-focus-ring);
		outline-offset: 2px;
		border-radius: var(--cloo-radius-default);
	}

	.cloo-cb__web-chip {
		display: inline-flex;
		align-items: center;
		gap: var(--cloo-space-1);
		min-height: 1.25rem;
		padding: 0 var(--cloo-space-1-5);
		max-width: 220px;
		border: 0;
		border-radius: var(--cloo-radius-default);
		background: var(--token-scale-info-100);
		color: var(--token-scale-info-700);
		text-decoration: none;
		font-size: 0.75rem;
		line-height: 1rem;
		transition: background-color 150ms ease;
		vertical-align: baseline;
	}
	.cloo-cb__web-chip:hover {
		background: var(--token-scale-info-200);
	}
	.cloo-cb__web-chip:active {
		background: var(--token-scale-info-300);
	}
	.cloo-cb__web-chip:focus-visible {
		outline: 2px solid var(--cloo-focus-ring);
		outline-offset: 2px;
	}
	.cloo-cb__web-favicon {
		width: 14px;
		height: 14px;
		flex-shrink: 0;
		object-fit: contain;
	}
	.cloo-cb__web-host {
		font-size: inherit;
		color: inherit;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
		max-width: 160px;
	}

	:global(.tippy-box[data-theme~='cloo-citation']) {
		background-color: var(--cloo-bg-surface);
		color: var(--cloo-text-default);
		border: 1px solid var(--cloo-border-default);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
	}
	:global(.tippy-box[data-theme~='cloo-citation'] > .tippy-content) {
		padding: 12px 14px;
	}

	:global(.cloo-cb) {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 260px;
		max-width: 360px;
		max-height: min(60vh, 420px);
		font-size: 12px;
		line-height: 1.4;
	}
	:global(.cloo-cb__title) {
		font-weight: 600;
		color: var(--cloo-text-default);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		word-break: break-word;
		flex-shrink: 0;
	}
	:global(.cloo-cb__meta) {
		display: flex;
		gap: 6px;
		align-items: center;
		flex-wrap: wrap;
		flex-shrink: 0;
	}
	:global(.cloo-cb__meta-page) {
		font-size: 11px;
		color: var(--cloo-text-muted);
	}
	:global(.cloo-cb__relevance) {
		font-size: 10px;
		padding: 1px 6px;
		border-radius: var(--cloo-radius-default);
		font-weight: 500;
	}
	:global(.cloo-cb__snippet) {
		color: var(--cloo-text-muted);
		font-size: 11px;
		line-height: 1.5;
		max-height: 9em;
		overflow-y: auto;
		white-space: pre-wrap;
		word-break: break-word;
		padding-right: 4px;
	}
	:global(.cloo-cb__snippet::-webkit-scrollbar) {
		width: 6px;
	}
	:global(.cloo-cb__snippet::-webkit-scrollbar-thumb) {
		background: var(--cloo-border-default);
		border-radius: 3px;
	}
	:global(.cloo-cb__actions) {
		display: flex;
		gap: 6px;
		justify-content: flex-end;
		padding-top: 4px;
		border-top: 1px solid var(--cloo-border-subtle);
		flex-shrink: 0;
	}
	:global(.cloo-cb__btn) {
		font-size: 11px;
		padding: 4px 10px;
		border-radius: var(--cloo-radius-default);
		border: 1px solid var(--cloo-border-default);
		background: var(--cloo-bg-default);
		color: var(--cloo-text-primary);
		cursor: pointer;
		transition: background-color 120ms ease;
	}
	:global(.cloo-cb__btn:hover) {
		background: var(--cloo-bg-neutral-hovered);
	}
	:global(.cloo-cb__btn:disabled) {
		opacity: 0.5;
		cursor: not-allowed;
	}
	:global(.cloo-cb__btn--primary) {
		background: var(--cloo-color-primary);
		color: var(--cloo-color-on-primary);
		border-color: transparent;
	}
	:global(.cloo-cb__btn--primary:hover) {
		background: var(--cloo-color-primary-hover);
	}
</style>
