<script lang="ts">
	import { getContext } from 'svelte';
	import CitationBadge from './CitationBadge.svelte';
	import {
		type Citation,
		calculateShowRelevance,
		dedupSources,
		extractCitedIndices,
		shouldShowPercentage
	} from '$lib/utils/citations';

	const i18n = getContext('i18n') as any;

	export let id = '';
	export let sources: any[] = [];
	// 답변 본문 — `[N]` marker 추출로 cited-only 표시 (없으면 legacy 전체 표시 fallback)
	export let content: string = '';

	// chip 의 가시 인덱스를 본문 `[N]` marker 와 정확히 일치시키기 위해 원본 인덱스 보존
	let citations: { citation: Citation; originalIndex: number }[] = [];
	let citationList: Citation[] = [];
	let showPercentage = false;
	let showRelevance = true;

	$: {
		const allCitations = dedupSources(sources);
		const indexed = allCitations.map((c, idx) => ({ citation: c, originalIndex: idx + 1 }));
		const citedIndices = extractCitedIndices(content);
		const trimmed = (content || '').trim();
		// Cited-only 정책:
		// - marker 추출됨 → cited filter 적용 (cross-domain noise 자동 차단)
		// - streaming 시작 단계 (content 짧음) → chip 숨김 (5건→1건 flicker 방지)
		// - 답변 완료 but marker 0 (non-citing prompt) → legacy fallback (전체 표시)
		if (citedIndices.size > 0) {
			citations = indexed.filter((x) => citedIndices.has(x.originalIndex));
		} else if (trimmed.length < 30) {
			// streaming 초기 — LLM 이 아직 marker 박지 않음. chip 보류
			citations = [];
		} else {
			citations = indexed;
		}
		citationList = citations.map((x) => x.citation);
	}
	$: showRelevance = calculateShowRelevance(citationList);
	$: showPercentage = shouldShowPercentage(citationList);
</script>

{#if citations.length > 0}
	<div
		class="flex flex-wrap items-center gap-1.5 py-1"
		id={`citations-${id}`}
		aria-label={$i18n.t('Sources')}
	>
		<span class="text-xs text-[var(--cloo-text-muted)] mr-1">
			{$i18n.t('{{count}} Sources', { count: citations.length })}
		</span>
		{#each citations as { citation, originalIndex } (citation.id + originalIndex)}
			<CitationBadge
				index={originalIndex}
				messageId={id}
				{citation}
				{showPercentage}
				{showRelevance}
			/>
		{/each}
	</div>
{/if}
