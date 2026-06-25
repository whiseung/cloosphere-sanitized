/**
 * 기본 엣지 타입 시드 (seed).
 *
 * KG 카탈로그 추천 LLM 결과에 관계없이 **반드시 포함되어야 하는** 범용 엣지 타입 목록.
 * 사용자가 "LLM 추천 후보 받기" 또는 "LLM 자동 생성" 을 누를 때 카탈로그 최상단에
 * 주입된다. 사용자가 삭제/편집하면 그 상태를 존중한다 (재클릭해도 재주입 안 함).
 *
 * 새 시드 추가 시:
 * 1. DEFAULT_EDGE_TYPE_SEEDS 배열에 항목 추가
 * 2. i18n 키 (display_name / description / recommendation_reason) 를 ko-KR + en-US
 *    translation.json 에 추가
 */

import type { KGEdgeTypeCatalogItem } from '$lib/apis/knowledge-graph';

export type DefaultEdgeTypeSeed = {
	/** snake_case edge type key (used for kg_edge.edge_type) */
	key: string;
	/** 표시 이름 i18n 키 */
	displayNameKey: string;
	/** 설명 i18n 키 — src→dst 방향 기술 */
	descriptionKey: string;
	/** 추천 이유 i18n 키 — 사용자가 왜 기본인지 이해하도록 */
	reasonKey: string;
	/**
	 * scope
	 * - null: 범용 (모든 카테고리에 적용)
	 * - 단일 category 이름: intra
	 * - [src, dst]: cross
	 */
	scope?: null | string | [string, string];
};

// 새로운 LLM 추천 seed 가 필요하면 아래 배열에 추가.
export const DEFAULT_EDGE_TYPE_SEEDS: DefaultEdgeTypeSeed[] = [];

/**
 * 시드 하나를 카탈로그 row 형태로 빌드. i18n 해석 함수를 받아서 현재 로케일의 텍스트를
 * 주입한다.
 */
export function buildSeedRow(
	seed: DefaultEdgeTypeSeed,
	t: (key: string) => string
): KGEdgeTypeCatalogItem {
	let category: string | null = null;
	let src_category: string | null = null;
	let dst_category: string | null = null;
	if (typeof seed.scope === 'string') {
		category = seed.scope;
	} else if (Array.isArray(seed.scope)) {
		src_category = seed.scope[0];
		dst_category = seed.scope[1];
	}
	return {
		key: seed.key,
		display_name: t(seed.displayNameKey),
		description: t(seed.descriptionKey),
		examples: [],
		source: 'manual',
		recommendation_reason: t(seed.reasonKey),
		category,
		src_category,
		dst_category
	};
}

/** 시드 키 집합 — dedup/존재 여부 체크에 사용 */
export const DEFAULT_EDGE_TYPE_SEED_KEYS: Set<string> = new Set(
	DEFAULT_EDGE_TYPE_SEEDS.map((s) => s.key)
);
