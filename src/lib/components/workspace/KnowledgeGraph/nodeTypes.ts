/**
 * KG 노드 타입 카탈로그 — UI 공용.
 *
 * 노드 타입 키, 표시 라벨, 리스트/검색 결과 뱃지 tailwind 클래스를 한 곳에서 관리.
 * 신규 노드 타입 추가 시 이 파일 한 곳만 수정하면 페이지 필터/리스트/검색결과가 동시 반영됨.
 *
 * 그래프 캔버스(Cytoscape) 는 hex 기반 팔레트를 GraphView.svelte 내부에서 별도 관리한다.
 * (Tailwind 클래스 ↔ hex 색상 두 용도가 달라 굳이 공유하지 않음.)
 */

export type KGNodeTypeKey =
	| 'term'
	| 'concept'
	| 'table'
	| 'column'
	| 'doc_entity'
	| 'doc_attr'
	| 'database'
	| 'knowledge_base'
	| 'glossary'
	| 'document';

export const KG_NODE_TYPES: { key: KGNodeTypeKey; label: string }[] = [
	{ key: 'term', label: 'Term' },
	{ key: 'concept', label: 'Concept' },
	{ key: 'table', label: 'Table' },
	{ key: 'column', label: 'Column' },
	{ key: 'doc_entity', label: 'Doc Entity' },
	{ key: 'doc_attr', label: 'Doc Attribute' },
	{ key: 'database', label: 'Database' },
	{ key: 'knowledge_base', label: 'Knowledge Base' },
	{ key: 'glossary', label: 'Glossary' },
	{ key: 'document', label: 'Document' }
];

/** 리스트 뱃지용 Tailwind 클래스 (bg + text + dark variant). */
export const KG_NODE_TYPE_BADGE: Record<string, string> = {
	term: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
	concept: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
	table: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
	column: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
	doc_entity: 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300',
	doc_attr: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300',
	database: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
	knowledge_base: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
	glossary: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
	document: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
};

const DEFAULT_BADGE = 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';

export function getNodeTypeBadgeClass(type: string): string {
	return KG_NODE_TYPE_BADGE[type] ?? DEFAULT_BADGE;
}

export function getNodeTypeLabel(type: string): string {
	const found = KG_NODE_TYPES.find((t) => t.key === type);
	return found?.label ?? type;
}
