export type CitationSource = {
	id: string;
	name: string;
	url?: string;
};

export type CitationMetadata = {
	name?: string;
	file_id?: string;
	page?: number;
	page_num?: number;
	source?: string;
	source_file?: string;
	chunk_index?: number;
	html?: boolean;
};

export type Citation = {
	id: string;
	source: CitationSource;
	document: string[];
	metadata: CitationMetadata[];
	distances?: number[];
};

export const decodeString = (str: string): string => {
	try {
		return decodeURIComponent(str);
	} catch {
		return str;
	}
};

export const getDecodedName = (citation: Citation): string => {
	return decodeString(citation.metadata?.[0]?.name ?? citation.source?.name ?? '');
};

export const getHostname = (url?: string): string => {
	if (!url) return '';
	try {
		return new URL(url).hostname.replace(/^www\./, '');
	} catch {
		return '';
	}
};

export const getFaviconUrl = (url?: string): string => {
	if (!url) return '';
	try {
		return new URL('/favicon.ico', new URL(url).origin).toString();
	} catch {
		return '';
	}
};

export const getPageNumber = (citation: Citation): number | null => {
	const md = citation.metadata?.[0];
	const raw = md?.page ?? md?.page_num;
	if (raw === null || raw === undefined) return null;
	const n = typeof raw === 'number' ? raw : Number(raw);
	return Number.isFinite(n) ? n + 1 : null;
};

export const getRelevancePercentage = (distance: number | undefined): number | null => {
	if (typeof distance !== 'number') return null;
	if (distance < 0) return 0;
	if (distance > 1) return 100;
	return Math.round(distance * 10000) / 100;
};

export const getRelevanceColorClass = (percentage: number): string => {
	if (percentage >= 80)
		return 'bg-[var(--token-scale-success-100)] text-[var(--token-scale-success-700)]';
	if (percentage >= 60)
		return 'bg-[var(--token-scale-warning-100)] text-[var(--token-scale-warning-700)]';
	if (percentage >= 40)
		return 'bg-[var(--token-scale-warning-200)] text-[var(--token-scale-warning-800)]';
	return 'bg-[var(--token-scale-danger-100)] text-[var(--token-scale-danger-700)]';
};

export const stripHtml = (html: string): string => {
	return (html ?? '')
		.replace(/<!--[\s\S]*?-->/g, '')
		.replace(/<\/(p|div|tr|li|h[1-6]|table|thead|tbody|section|article)>/gi, '\n')
		.replace(/<br\s*\/?>(?!\n)/gi, '\n')
		.replace(/<\/?[a-zA-Z][^>]*>/g, '')
		.replace(/[ \t]+/g, ' ')
		.replace(/\n[ \t]+/g, '\n')
		.replace(/\n{3,}/g, '\n\n')
		.trim();
};

export const truncateSnippet = (text: string, max = 200): string => {
	if (!text) return '';
	return text.length > max ? `${text.slice(0, max).trim()}…` : text;
};

export const getFirstSnippet = (citation: Citation, max = 200): string => {
	const raw = citation.document?.[0] ?? '';
	const hasHtmlTag = /<\/?[a-zA-Z][^>]*>|<!--/.test(raw);
	const isHtmlMeta = citation.metadata?.[0]?.html === true;
	return truncateSnippet(hasHtmlTag || isHtmlMeta ? stripHtml(raw) : raw, max);
};

export const buildCitationCopyText = (citation: Citation): string => {
	const name = getDecodedName(citation);
	const page = getPageNumber(citation);
	const snippet = getFirstSnippet(citation, 1200);
	const header = page !== null ? `${name} (page ${page})` : name;
	return snippet ? `${header}\n\n${snippet}` : header;
};

export const dedupSources = (rawSources: any[]): Citation[] => {
	return (rawSources ?? []).reduce<Citation[]>((acc, source) => {
		if (!source || Object.keys(source).length === 0) return acc;
		if (!Array.isArray(source.document)) return acc;

		source.document.forEach((document: string, index: number) => {
			const metadata = source.metadata?.[index];
			const distance = source.distances?.[index];

			const sid = metadata?.source ?? source?.source?.id ?? 'N/A';
			let _source = source?.source;

			if (metadata?.name) {
				_source = { ..._source, name: metadata.name };
			}

			if (sid.startsWith('http://') || sid.startsWith('https://')) {
				_source = { ..._source, name: sid, url: sid };
			}

			const existing = acc.find((item) => item.id === sid);
			if (existing) {
				existing.document.push(document);
				existing.metadata.push(metadata);
				if (distance !== undefined) {
					if (!existing.distances) existing.distances = [];
					existing.distances.push(distance);
				}
			} else {
				acc.push({
					id: sid,
					source: _source,
					document: [document],
					metadata: metadata ? [metadata] : [],
					distances: distance !== undefined ? [distance] : undefined
				});
			}
		});
		return acc;
	}, []);
};

export const calculateShowRelevance = (citations: Citation[]): boolean => {
	const distances = citations.flatMap((c) => c.distances ?? []);
	if (distances.length === 0) return false;
	const inRange = distances.filter((d) => d !== undefined && d >= -1 && d <= 1).length;
	const outOfRange = distances.filter((d) => d !== undefined && (d < -1 || d > 1)).length;
	if (
		(inRange === distances.length - 1 && outOfRange === 1) ||
		(outOfRange === distances.length - 1 && inRange === 1)
	) {
		return false;
	}
	return true;
};

export const shouldShowPercentage = (citations: Citation[]): boolean => {
	const distances = citations.flatMap((c) => c.distances ?? []);
	return distances.length > 0 && distances.every((d) => d !== undefined && d >= -1 && d <= 1);
};

export const escapeHtml = (s: string): string => {
	return (s ?? '')
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
};

/**
 * 답변 본문에서 inline citation marker `[N]` 의 N 값을 추출하여 1-based 인덱스 Set 으로 반환.
 *
 * 코드 블록 (``` ... ```), 인라인 코드 (`...`), 마크다운 이미지 (`![alt](url)`),
 * 마크다운 링크 (`[text](url)`) 안의 `[N]` 은 제외 — citation marker 가 아님.
 *
 * 정책: ACME v3.3.x 같은 인용 강제 prompt 면 marker 가 항상 있어 cited-only 표시.
 *      marker 0 개면 caller 가 legacy fallback (전체 sources) 적용 권장.
 */
export const extractCitedIndices = (content: string | undefined | null): Set<number> => {
	const result = new Set<number>();
	if (!content) return result;

	// 1. 코드 블록 제거 (fenced + indented)
	let stripped = content.replace(/```[\s\S]*?```/g, '');
	stripped = stripped.replace(/`[^`\n]*`/g, '');
	// 2. 마크다운 이미지 / 링크 제거 — `[text](url)` 안의 [N] 회피
	stripped = stripped.replace(/!?\[[^\]]*\]\([^)]*\)/g, '');

	// 3. 단일 정수 marker `[N]` (양의 정수)
	for (const m of stripped.matchAll(/\[(\d+)\]/g)) {
		const n = parseInt(m[1], 10);
		if (Number.isFinite(n) && n >= 1) result.add(n);
	}
	return result;
};
