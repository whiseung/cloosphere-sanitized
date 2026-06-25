<script lang="ts">
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onDestroy, onMount, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	const i18n = getContext<{ t: (key: string, params?: Record<string, unknown>) => string }>(
		'i18n'
	);

	import { WEBUI_NAME, user, models, socket } from '$lib/stores';
	import {
		exportKnowledgeGraph,
		extractKnowledgeGraphKbEntities,
		previewKnowledgeGraphKbEntities,
		getKnowledgeGraphJobs,
		getKnowledgeGraphById,
		getKnowledgeGraphNodes,
		getKnowledgeGraphEdges,
		getKnowledgeGraphEdgeTypes,
		type KGEdge,
		getKnowledgeGraphStats,
		searchKnowledgeGraph,
		syncKnowledgeGraph,
		updateKnowledgeGraphById,
		type KGNode,
		type KGSearchResult,
		type KnowledgeGraph,
		type KnowledgeLink,
		getKnowledgeLinks,
		createKnowledgeLink,
		deleteKnowledgeLink,
		syncKnowledgeLink,
		testKgTool,
		getDbSphereColumns,
		type DbSphereColumnInfo
	} from '$lib/apis/knowledge-graph';
	import { getGlossaries, getGlossaryById } from '$lib/apis/glossary';
	import { getDbSpheres } from '$lib/apis/dbsphere';
	import { getKnowledgeBases } from '$lib/apis/knowledge';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import EdgeTypeCatalogModal from '$lib/components/workspace/KnowledgeGraph/EdgeTypeCatalogModal.svelte';
	import NodeFilterModal from '$lib/components/workspace/KnowledgeGraph/NodeFilterModal.svelte';
	import {
		KG_NODE_TYPES,
		getNodeTypeBadgeClass
	} from '$lib/components/workspace/KnowledgeGraph/nodeTypes';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import AccessControlModal from '$lib/components/workspace/common/AccessControlModal.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import WorkspaceDetailHeader from '$lib/components/workspace/common/WorkspaceDetailHeader.svelte';
	import ToolDescriptionSection from '$lib/components/workspace/common/ToolDescriptionSection.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	let loaded = false;
	let kg: KnowledgeGraph | null = null;
	let stats: { node_count: number; edge_count: number; stats: Record<string, unknown> } | null =
		null;
	let nodes: KGNode[] = [];

	let allGlossaries: Array<{ id: string; name: string }> = [];
	// 링크별 sync 진행 상태 (지식 연결 카드의 Sync 버튼 토글)
	let linkSyncing: Record<string, boolean> = {};
	// 미리보기: 용어집별 전체 데이터 캐시 (meta.extraction_sources + data.entries 포함)
	// 지식 연결 카드가 펼쳐질 때 link.glossary_id 로 조회한다.
	let glossaryDetails: Record<
		string,
		{
			meta?: { extraction_sources?: Record<string, { dbsphere_id?: string; table?: string; column?: string; extracted_at?: number }> };
			data?: { entries?: Array<{ term?: string; category?: string | null }> };
		} | null
	> = {};
	let glossaryExpanded: Record<string, boolean> = {};
	let glossaryDetailLoading: Record<string, boolean> = {};
	// 테이블 컬럼 캐시 — 키는 `${dbsphere_id}:${table}`
	let tableColumnsCache: Record<string, DbSphereColumnInfo[]> = {};
	let tableColumnsLoading: Record<string, boolean> = {};
	let tableColumnsExpanded: Record<string, boolean> = {};

	// dbsphere 이름 매핑 (미리보기 라벨용)
	let allDbspheres: Array<{ id: string; name: string }> = [];

	let allKnowledges: Array<{
		id: string;
		name: string;
		description?: string;
		data?: { file_ids?: string[] };
		meta?: { filter_schema?: Array<{ type?: string; glossary_id?: string; slot?: string }> };
	}> = [];
	let attachedKnowledgeIds: string[] = [];

	let toolDescription = '';
	let generatingToolDesc = false;

	// sync/추출용 LLM (카테고리 정의 생성, KB 매칭, KB 청크 엔티티 추출)
	let llmModelId = '';
	// 도구 설명(AI 생성) 전용 LLM — sync와 목적이 달라 별도 저장
	let toolDescModelId = '';
	let kbExtracting = false;
	let kbCleaningUp = false;
	// KB 추출 시 1회 호출 안전 캡 — 비워두면 미처리 청크 *전체* 처리.
	// string으로 보관해서 빈 문자열도 표현 가능 (Input number bind 호환)
	let kbMaxChunks = '';
	// true면 이번 KB의 처리 이력을 비우고 처음부터 다시 추출
	let kbResetProcessed = false;

	let saving = false;
	let showAccessControlModal = false;
	let tagSelector: any;

	// Semantic search state
	let searchQuery = '';
	let searchResults: KGSearchResult[] = [];
	let searching = false;
	let searchAvailable = true;
	let lastSearchedQuery = '';

	// Knowledge Links (용어집 → KB 매핑)
	let knowledgeLinks: KnowledgeLink[] = [];
	let showAddLinkModal = false;
	let linkGlossaryId = '';
	let linkSaving = false;

	// 용어집 선택 시 자동 탐지된 연결 가능 KB (glossary 필터가 설정된 KB만)
	$: linkedKbs = linkGlossaryId
		? allKnowledges.filter((k) =>
				(k.meta?.filter_schema ?? []).some(
					(f) => f?.type === 'glossary' && f?.glossary_id === linkGlossaryId
				)
			)
		: [];
	// 용어집 선택 시 연결된 DB (extraction_sources에서)
	$: linkedDbs = (() => {
		if (!linkGlossaryId) return [];
		const detail = glossaryDetails[linkGlossaryId];
		if (!detail?.meta?.extraction_sources) return [];
		const dbIds = new Set<string>();
		for (const src of Object.values(detail.meta.extraction_sources)) {
			if (src?.dbsphere_id) dbIds.add(src.dbsphere_id);
		}
		return allDbspheres.filter((d) => dbIds.has(d.id));
	})();

	// Add Link 모달 — 체크박스 선택 상태.
	// 기본값은 "연결 가능한 모든 KB/DB 선택". glossary 를 바꾸면 초기화하고,
	// glossary detail 이 비동기로 늦게 도착해 candidates 가 뒤늦게 늘어나는
	// 경우에도 사용자가 아직 수동 토글하지 않았으면 새 candidates 도 자동
	// 체크한다. 사용자가 한 번이라도 토글하면 이후 자동 동기화 중단.
	let selectedLinkKbIds: Set<string> = new Set();
	let selectedLinkDbIds: Set<string> = new Set();
	let lastInitializedLinkGlossaryId = '';
	let linkSelectionTouched = false;
	$: if (linkGlossaryId !== lastInitializedLinkGlossaryId) {
		selectedLinkKbIds = new Set(linkedKbs.map((k) => k.id));
		selectedLinkDbIds = new Set(linkedDbs.map((d) => d.id));
		lastInitializedLinkGlossaryId = linkGlossaryId;
		linkSelectionTouched = false;
	}
	// candidates (linkedKbs/linkedDbs) 가 비동기 로드로 늘어난 경우 사용자가
	// 수동 변경하지 않았으면 전체 선택으로 재동기화.
	$: if (
		linkGlossaryId &&
		linkGlossaryId === lastInitializedLinkGlossaryId &&
		!linkSelectionTouched
	) {
		const candKb = new Set(linkedKbs.map((k) => k.id));
		const candDb = new Set(linkedDbs.map((d) => d.id));
		const kbSame =
			candKb.size === selectedLinkKbIds.size &&
			[...candKb].every((i) => selectedLinkKbIds.has(i));
		const dbSame =
			candDb.size === selectedLinkDbIds.size &&
			[...candDb].every((i) => selectedLinkDbIds.has(i));
		if (!kbSame) selectedLinkKbIds = candKb;
		if (!dbSame) selectedLinkDbIds = candDb;
	}
	function toggleLinkKb(kbId: string) {
		linkSelectionTouched = true;
		const next = new Set(selectedLinkKbIds);
		if (next.has(kbId)) next.delete(kbId);
		else next.add(kbId);
		selectedLinkKbIds = next;
	}
	function toggleLinkDb(dbId: string) {
		linkSelectionTouched = true;
		const next = new Set(selectedLinkDbIds);
		if (next.has(dbId)) next.delete(dbId);
		else next.add(dbId);
		selectedLinkDbIds = next;
	}

	// 공용 확인 모달 — 삭제/동기화 공용으로 사용
	let showConfirmDialog = false;
	let confirmTitle = '';
	let confirmMessage = '';
	let confirmLabel = '';
	let confirmAction: () => void | Promise<void> = () => {};
	const openConfirm = (opts: {
		title: string;
		message: string;
		confirmLabel?: string;
		onConfirm: () => void | Promise<void>;
	}) => {
		confirmTitle = opts.title;
		confirmMessage = opts.message;
		confirmLabel = opts.confirmLabel ?? $i18n.t('Confirm');
		confirmAction = opts.onConfirm;
		showConfirmDialog = true;
	};

	// Node/Edge list — 서버 사이드 페이징/필터링
	let entityTab: 'nodes' | 'edges' = 'nodes';
	let nodeSearchQuery = '';
	let nodeFilterType = '';
	let nodePage = 0;
	const nodePageSize = 20;
	let nodeTotal = 0;
	let nodesLoading = false;
	let nodeFetchSeq = 0;
	let nodeSearchDebounce: ReturnType<typeof setTimeout> | null = null;

	// Edge state
	let edges: KGEdge[] = [];
	let edgeTotal = 0;
	let edgesLoading = false;
	let edgePage = 0;
	let edgeFetchSeq = 0;
	let edgeFilterType = '';
	let edgeTypeOptions: { edge_type: string; count: number }[] = [];

	let showEdgeTypeCatalogModal = false;
	let edgeTypeCatalogLinkId = '';
	let edgeTypeCatalogLinkTitle = '';
	let edgeTypeCatalogGlossaryId = '';
	let edgeTypeCatalogDefaultModelId = '';
	let savingLlmModel = false;

	let showNodeFilterModal = false;
	let nodeFilterLinkId = '';
	let nodeFilterLinkTitle = '';
	let nodeFilterLinkedKbs: Array<{ id: string; name: string; meta?: any }> = [];

	// 링크에 엣지 타입 카탈로그가 하나라도 정의되어 있는지 — 없으면 sync 버튼 비활성화.
	// (link.config.edge_types 는 key→항목 dict. 비어 있으면 카탈로그 미설정으로 본다.)
	const hasEdgeTypeCatalog = (link: KnowledgeLink): boolean => {
		const types = link?.config?.edge_types;
		if (!types || typeof types !== 'object') return false;
		return Object.keys(types).length > 0;
	};

	const openEdgeTypeCatalog = (
		linkId: string,
		glossaryName: string,
		glossaryId: string
	) => {
		edgeTypeCatalogLinkId = linkId;
		edgeTypeCatalogLinkTitle = glossaryName;
		edgeTypeCatalogGlossaryId = glossaryId;
		edgeTypeCatalogDefaultModelId = llmModelId;
		showEdgeTypeCatalogModal = true;
	};

	const openNodeFilterSettings = (linkId: string, glossaryName: string) => {
		const link = knowledgeLinks.find((l) => l.id === linkId);
		const linkKbIds = new Set((link?.knowledge_ids ?? []) as string[]);
		nodeFilterLinkId = linkId;
		nodeFilterLinkTitle = glossaryName;
		nodeFilterLinkedKbs = allKnowledges
			.filter((k) => linkKbIds.has(k.id))
			.map((k) => ({ id: k.id, name: k.name, meta: k.meta }));
		showNodeFilterModal = true;
	};

	const autoSaveLlmModel = async (modelId: string) => {
		if (!kg) return;
		llmModelId = modelId;
		savingLlmModel = true;
		try {
			const existingOptions = ((kg?.data ?? {}).options ?? {}) as Record<
				string,
				unknown
			>;
			const data = {
				...(kg?.data ?? {}),
				options: {
					...existingOptions,
					llm_model_id: modelId || undefined
				}
			};
			await updateKnowledgeGraphById(localStorage.token, id, {
				name: kg.name,
				description: kg.description,
				data,
				meta: kg.meta,
				access_control: kg.access_control
			});
			// local kg state 갱신 (다른 컴포넌트들이 kg.data 를 읽어도 최신 반영)
			kg = { ...kg, data };
			toast.success($i18n.t('LLM model saved'));
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			savingLlmModel = false;
		}
	};

	$: pagedNodes = nodes;
	$: pagedEdges = edges;
	$: nodePageCount = Math.max(1, Math.ceil(nodeTotal / nodePageSize));
	$: edgePageCount = Math.max(1, Math.ceil(edgeTotal / nodePageSize));

	// 검색어 변경 → debounce 후 첫 페이지 fetch (loaded 이후에만)
	let _lastSearchQuery = '';
	$: if (loaded && nodeSearchQuery !== _lastSearchQuery) {
		_lastSearchQuery = nodeSearchQuery;
		if (nodeSearchDebounce) clearTimeout(nodeSearchDebounce);
		nodeSearchDebounce = setTimeout(() => {
			nodePage = 0;
			edgePage = 0;
			if (entityTab === 'nodes') fetchNodesPage();
			else fetchEdgesPage();
		}, 250);
	}

	const fetchNodesPage = async () => {
		const seq = ++nodeFetchSeq;
		nodesLoading = true;
		try {
			const page = await getKnowledgeGraphNodes(localStorage.token, id, {
				node_type: nodeFilterType || undefined,
				q: nodeSearchQuery.trim() || undefined,
				limit: nodePageSize,
				offset: nodePage * nodePageSize
			});
			// 늦게 도착한 응답은 무시 (race 방지)
			if (seq !== nodeFetchSeq) return;
			nodes = page.items;
			nodeTotal = page.total;
		} catch (e) {
			if (seq !== nodeFetchSeq) return;
			console.error(e);
			nodes = [];
			nodeTotal = 0;
		} finally {
			if (seq === nodeFetchSeq) nodesLoading = false;
		}
	};

	const fetchEdgesPage = async () => {
		const seq = ++edgeFetchSeq;
		edgesLoading = true;
		try {
			const page = await getKnowledgeGraphEdges(localStorage.token, id, {
				edge_type: edgeFilterType || undefined,
				q: nodeSearchQuery.trim() || undefined,
				limit: nodePageSize,
				offset: edgePage * nodePageSize
			});
			if (seq !== edgeFetchSeq) return;
			edges = page.items;
			edgeTotal = page.total;
		} catch (e) {
			if (seq !== edgeFetchSeq) return;
			console.error(e);
			edges = [];
			edgeTotal = 0;
		} finally {
			if (seq === edgeFetchSeq) edgesLoading = false;
		}
	};

	const fetchEdgeTypeOptions = async () => {
		try {
			edgeTypeOptions = await getKnowledgeGraphEdgeTypes(localStorage.token, id);
		} catch (e) {
			console.error(e);
			edgeTypeOptions = [];
		}
	};

	const onEdgeFilterChange = (newType: string) => {
		edgeFilterType = newType;
		edgePage = 0;
		fetchEdgesPage();
	};

	// 필터 변경 → 첫 페이지로 + 즉시 fetch
	const onNodeFilterChange = (newType: string) => {
		nodeFilterType = newType;
		nodePage = 0;
		fetchNodesPage();
	};
	const onNodePageChange = (newPage: number) => {
		nodePage = Math.max(0, Math.min(newPage, nodePageCount - 1));
		fetchNodesPage();
	};
	const onEdgePageChange = (newPage: number) => {
		edgePage = Math.max(0, Math.min(newPage, edgePageCount - 1));
		fetchEdgesPage();
	};

	const switchEntityTab = (tab: 'nodes' | 'edges') => {
		if (entityTab === tab) return;
		entityTab = tab;
		if (tab === 'edges') {
			if (edgeTypeOptions.length === 0) fetchEdgeTypeOptions();
			if (edges.length === 0) fetchEdgesPage();
		}
	};

	// Tool tester
	let showToolTester = false;
	let testerToolName = 'kg_resolve_term';
	let testerInput = '';
	let testerResult = '';
	let testerError = '';
	let testerRunning = false;

	// Selector reset trigger (값이 변할 때마다 Selector value를 ''로 강제 리셋하기 위해)
	let knowledgeSelectorValue = '';

	$: attachedKnowledges = allKnowledges.filter((k) => attachedKnowledgeIds.includes(k.id));
	$: availableKnowledgeItems = allKnowledges
		.filter((k) => !attachedKnowledgeIds.includes(k.id))
		.map((k) => ({ value: k.id, label: k.name }));

	// LLM 모델 선택용 — Cloosphere에 등록된 base 모델만 노출
	// (커스텀 에이전트는 base_model_id가 있어 제외)
	// Model 타입에 base_model_id/preset/arena가 미선언이라 unknown으로 캐스팅 후 좁힌다.
	$: modelItems = (($models ?? []) as unknown as Array<
		{ id: string; name: string } & {
			base_model_id?: string | null;
			preset?: boolean;
			arena?: boolean;
		}
	>)
		.filter((m) => !m.base_model_id && !m.preset && !(m.arena ?? false))
		.map((m) => ({ value: m.id, label: m.name }));

	const id = $page.params.id;

	const reload = async () => {
		try {
			kg = await getKnowledgeGraphById(localStorage.token, id);
		} catch (e) {
			console.error(e);
			toast.error(`${e}`);
			await goto('/workspace/knowledge-graph');
			return;
		}

		// KB: data.sources.knowledge_ids
		attachedKnowledgeIds = (
			kg?.data?.sources?.knowledge_ids ?? []
		) as string[];

		const opts = (kg?.data?.options ?? {}) as Record<string, unknown>;
		if (typeof opts.llm_model_id === 'string') llmModelId = opts.llm_model_id;
		if (typeof opts.tool_description_model_id === 'string')
			toolDescModelId = opts.tool_description_model_id;

		toolDescription = ((kg?.meta as any)?.tool_description as string) ?? '';

		try {
			stats = await getKnowledgeGraphStats(localStorage.token, id);
		} catch (e) {
			console.error(e);
		}

		// 노드는 서버 사이드 페이징으로 별도 fetch — fetchNodesPage() 가 처리
		// 엣지도 초기에 fetch 해서 탭 라벨 카운트/드롭다운을 채운다.
		await Promise.all([fetchNodesPage(), fetchEdgesPage(), fetchEdgeTypeOptions()]);
	};

	const saveHandler = async () => {
		if (!kg) return;
		saving = true;
		try {
			const existingOptions = ((kg?.data ?? {}).options ?? {}) as Record<
				string,
				unknown
			>;
			const data = {
				...(kg?.data ?? {}),
				options: {
					...existingOptions,
					llm_model_id: llmModelId || undefined,
					tool_description_model_id: toolDescModelId || undefined
				}
			};
			// 용어집/KB 연결은 지식 연결(knowledge_links) 테이블로만 관리한다.
			// legacy 필드(data.glossary_ids / data.sources) 는 더 이상 저장하지 않음.
			await updateKnowledgeGraphById(localStorage.token, id, {
				name: kg.name,
				description: kg.description,
				data,
				meta: { ...((kg.meta as Record<string, unknown>) ?? {}), tool_description: toolDescription },
				access_control: kg.access_control
			});

			// Tag 커밋
			if (tagSelector?.commitChanges) {
				try {
					await tagSelector.commitChanges();
				} catch (e) {
					console.error('Failed to commit tag changes:', e);
				}
			}

			toast.success($i18n.t('Save & Update'));
			await reload();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			saving = false;
		}
	};

	const aiGenerateToolDescription = async () => {
		if (!kg || generatingToolDesc) return;
		generatingToolDesc = true;
		try {
			const { generateText } = await import('$lib/apis');
			const sampleNodes = (nodes ?? [])
				.slice(0, 20)
				.map((n) => n.label)
				.filter(Boolean)
				.join(', ');
			const linkedGlossaries = Array.from(
				new Set(knowledgeLinks.map((l) => l.glossary_id).filter(Boolean))
			)
				.map((gid) => allGlossaries.find((g) => g.id === gid)?.name ?? gid)
				.join(', ') || '없음';
			const kbNames = attachedKnowledges.map((k) => k.name).filter(Boolean).join(', ') || '없음';
			const linkDescriptions =
				(knowledgeLinks ?? [])
					.map((l: any) => {
						const g = allGlossaries.find((x) => x.id === l?.glossary_id);
						const gname = g?.name ?? l?.glossary_id ?? 'glossary';
						const kbCount = (l?.knowledge_ids ?? []).length;
						return `${gname} → ${kbCount} KB(s)`;
					})
					.filter(Boolean)
					.join(', ') || '없음';

			const prompt = `지식 그래프 이름: ${kg.name}
설명: ${kg.description || '없음'}
연결된 용어집: ${linkedGlossaries}
연결된 지식기반(비정형 문서): ${kbNames}
용어집-KB 매핑: ${linkDescriptions}
샘플 엔티티: ${sampleNodes}
노드 수: ${stats?.node_count ?? 0}, 엣지 수: ${stats?.edge_count ?? 0}

위 지식 그래프를 AI 에이전트가 언제 조회해야 하는지 설명하는 1~3문장을 한국어로 작성해주세요.
- 용어집이 연결된 DB 스키마와 어떤 KB 문서에 매칭되는지 포함하세요.
- 비정형 문서 기반 엔티티 검색이 가능하다면 명시하세요.
설명만 출력하고 다른 텍스트는 포함하지 마세요.`;
			const result = await generateText(localStorage.token, prompt, toolDescModelId || llmModelId);
			if (result) {
				toolDescription = result.trim();
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			generatingToolDesc = false;
		}
	};

	const loadGlossaryDetail = async (gid: string) => {
		if (glossaryDetails[gid] || glossaryDetailLoading[gid]) return;
		glossaryDetailLoading = { ...glossaryDetailLoading, [gid]: true };
		try {
			const full = await getGlossaryById(localStorage.token, gid);
			glossaryDetails = { ...glossaryDetails, [gid]: full ?? null };
		} catch (e) {
			console.error(e);
			glossaryDetails = { ...glossaryDetails, [gid]: null };
		} finally {
			glossaryDetailLoading = { ...glossaryDetailLoading, [gid]: false };
		}
	};

	const toggleGlossaryExpanded = async (gid: string) => {
		const next = !glossaryExpanded[gid];
		glossaryExpanded = { ...glossaryExpanded, [gid]: next };
		if (next) {
			await loadGlossaryDetail(gid);
		}
	};

	const loadTableColumns = async (dbsphereId: string, tableName: string) => {
		const key = `${dbsphereId}:${tableName}`;
		if (tableColumnsCache[key] || tableColumnsLoading[key]) return;
		tableColumnsLoading = { ...tableColumnsLoading, [key]: true };
		try {
			const cols = await getDbSphereColumns(localStorage.token, dbsphereId, tableName);
			tableColumnsCache = { ...tableColumnsCache, [key]: cols ?? [] };
		} catch (e) {
			console.error(e);
			tableColumnsCache = { ...tableColumnsCache, [key]: [] };
		} finally {
			tableColumnsLoading = { ...tableColumnsLoading, [key]: false };
		}
	};

	const toggleTableExpanded = async (dbsphereId: string, tableName: string) => {
		const key = `${dbsphereId}:${tableName}`;
		const next = !tableColumnsExpanded[key];
		tableColumnsExpanded = { ...tableColumnsExpanded, [key]: next };
		if (next) {
			await loadTableColumns(dbsphereId, tableName);
		}
	};

	// 용어집 상세를 (dbsphere_id, table) → [{ category, column, term_count, sample_terms }] 형태로 그룹핑.
	// 미리보기 UI 렌더링용.
	type ExtractionGroup = {
		dbsphere_id: string;
		dbsphere_name: string;
		tables: Array<{
			table_name: string;
			mappings: Array<{ category: string; column: string; term_count: number; sample_terms: string[] }>;
		}>;
	};
	const groupExtractionSources = (gid: string): ExtractionGroup[] => {
		const detail = glossaryDetails[gid];
		if (!detail) return [];
		const sources = detail.meta?.extraction_sources ?? {};
		const entries = detail.data?.entries ?? [];

		// category → entries 집계
		const entriesByCategory: Record<string, Array<{ term?: string }>> = {};
		for (const e of entries) {
			const c = e.category ?? '';
			if (!entriesByCategory[c]) entriesByCategory[c] = [];
			entriesByCategory[c].push(e);
		}

		// (dbsphere, table) 로 그룹핑
		const byDb: Record<string, ExtractionGroup> = {};
		for (const [category, src] of Object.entries(sources)) {
			if (!src || !src.dbsphere_id || !src.table || !src.column) continue;
			const dbId = src.dbsphere_id;
			const dbName = allDbspheres.find((d) => d.id === dbId)?.name ?? dbId;
			if (!byDb[dbId]) {
				byDb[dbId] = { dbsphere_id: dbId, dbsphere_name: dbName, tables: [] };
			}
			let tableGroup = byDb[dbId].tables.find((t) => t.table_name === src.table);
			if (!tableGroup) {
				tableGroup = { table_name: src.table, mappings: [] };
				byDb[dbId].tables.push(tableGroup);
			}
			const catEntries = entriesByCategory[category] ?? [];
			tableGroup.mappings.push({
				category,
				column: src.column,
				term_count: catEntries.length,
				sample_terms: catEntries
					.slice(0, 5)
					.map((e) => (e.term ?? '').trim())
					.filter(Boolean)
			});
		}
		return Object.values(byDb);
	};

	const requestSyncLink = async (linkId: string, gid: string | null) => {
		if (!linkId || linkSyncing[linkId]) return;
		if (!llmModelId) {
			toast.error($i18n.t('Please select an LLM model first.'));
			return;
		}

		const link = knowledgeLinks.find((l) => l.id === linkId);
		const linkKbIds = link?.knowledge_ids || [];
		const kbCount = linkKbIds.length;

		const baseMessage = $i18n.t(
			'This will sync the glossary, databases, and knowledge bases attached to this link.'
		);
		const kbLine = kbCount > 0
			? '\n\n' + $i18n.t('{{count}} knowledge base(s) will be matched.', { count: kbCount })
			: '';

		openConfirm({
			title: $i18n.t('Sync knowledge link?'),
			message: baseMessage + kbLine,
			confirmLabel: $i18n.t('Sync'),
			onConfirm: () => syncLink(linkId, gid)
		});
	};

	const syncLink = async (linkId: string, gid: string | null) => {
		if (!linkId || linkSyncing[linkId]) return;
		// llmModelId 검증은 requestSyncLink 가 했음. 여기서는 폼 저장 후 sync.
		linkSyncing = { ...linkSyncing, [linkId]: true };
		try {
			await saveHandler();
			await syncKnowledgeLink(localStorage.token, id, linkId);
			toast.success(
				$i18n.t('Link sync started in background. You will be notified when it completes.')
			);
			// 다음 reload 시 최신 extraction_sources 가 반영되도록 상세 캐시 무효화
			if (gid) {
				glossaryDetails = { ...glossaryDetails, [gid]: null };
				delete glossaryDetails[gid];
				glossaryDetails = { ...glossaryDetails };
			}
			// 잡 완료 폴링 시작 — 완료 시 reload + linkSyncing clear
			startJobPolling();
		} catch (e) {
			toast.error(`${e}`);
			linkSyncing = { ...linkSyncing, [linkId]: false };
		}
	};

	const addKnowledge = (kid: string) => {
		if (kid && !attachedKnowledgeIds.includes(kid)) {
			attachedKnowledgeIds = [...attachedKnowledgeIds, kid];
		}
		knowledgeSelectorValue = '';
	};

	const removeKnowledge = (kid: string) => {
		attachedKnowledgeIds = attachedKnowledgeIds.filter((x) => x !== kid);
	};

	// saveSources는 saveHandler로 통합됨

	let syncing = false;

	// ── 백그라운드 잡 완료 감지 폴링 ──
	// Socket.IO 알림이 누락되거나 reload 시점 이후에 늦게 도착해도 UI 가
	// stale 상태로 남지 않도록, 잡이 하나라도 떠 있는 동안은 5초마다
	// running/pending 을 확인하고, 전부 비면 reload() + 폴링 중단.
	let jobPollInterval: ReturnType<typeof setInterval> | null = null;
	let jobPollStartedAt = 0;

	const startJobPolling = () => {
		if (jobPollInterval) return;
		jobPollStartedAt = Date.now();
		jobPollInterval = setInterval(async () => {
			// 첫 polling 은 3 초 대기 — backend 가 job row 를 commit 할 시간 확보
			if (Date.now() - jobPollStartedAt < 3000) return;
			try {
				const [running, pending] = await Promise.all([
					getKnowledgeGraphJobs(localStorage.token, id, { job_status: 'running' }),
					getKnowledgeGraphJobs(localStorage.token, id, { job_status: 'pending' })
				]);
				const activeCount = (running?.length ?? 0) + (pending?.length ?? 0);
				if (activeCount === 0) {
					stopJobPolling();
					await reload();
					await reloadLinks();
					kbExtracting = false;
					kbCleaningUp = false;
					syncing = false;
					linkSyncing = {};
					toast.success($i18n.t('Sync completed. Data refreshed.'));
				}
			} catch (e) {
				console.warn('[job poll] failed:', e);
			}
		}, 5000);
	};

	const stopJobPolling = () => {
		if (jobPollInterval) {
			clearInterval(jobPollInterval);
			jobPollInterval = null;
		}
	};

	const requestTriggerSync = async () => {
		if (syncing) return;
		if (knowledgeLinks.length === 0) {
			toast.error($i18n.t('No knowledge links to sync.'));
			return;
		}
		if (!llmModelId) {
			toast.error($i18n.t('Please select an LLM model first.'));
			return;
		}

		const totalKbs = new Set(knowledgeLinks.flatMap((l) => l.knowledge_ids || [])).size;

		const baseMessage = $i18n.t(
			'This will run a full sync of this knowledge graph — every linked glossary, database, and knowledge base will be re-extracted. It may take a few minutes.'
		);
		const kbLine = totalKbs > 0
			? '\n\n' + $i18n.t('{{count}} knowledge base(s) will be matched.', { count: totalKbs })
			: '';

		openConfirm({
			title: $i18n.t('Start full sync?'),
			message: baseMessage + kbLine,
			confirmLabel: $i18n.t('Start sync'),
			onConfirm: () => triggerSync()
		});
	};

	const triggerSync = async () => {
		// llmModelId 검증은 requestTriggerSync 가 했음.
		syncing = true;
		try {
			await saveHandler();
			await syncKnowledgeGraph(localStorage.token, id);
			toast.success($i18n.t('Sync started in background.'));
			// 잡 완료 폴링 시작 — 완료 시 reload + syncing=false
			startJobPolling();
		} catch (e) {
			toast.error(`${e}`);
			syncing = false;
		}
	};

	const formatLastSynced = (ts: unknown): string => {
		if (typeof ts !== 'number' || ts === 0) return $i18n.t('Never');
		return dayjs(ts * 1000).fromNow();
	};

	const runSearch = async () => {
		const q = searchQuery.trim();
		if (!q) {
			searchResults = [];
			lastSearchedQuery = '';
			return;
		}
		searching = true;
		try {
			const res = await searchKnowledgeGraph(localStorage.token, id, { q, top_k: 20 });
			searchAvailable = res.available;
			searchResults = res.results;
			lastSearchedQuery = q;
		} catch (e) {
			console.error(e);
			toast.error(`${e}`);
			searchResults = [];
		} finally {
			searching = false;
		}
	};

	const onSearchKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			runSearch();
		}
	};

	const clearSearch = () => {
		searchQuery = '';
		searchResults = [];
		lastSearchedQuery = '';
	};

	const triggerKbCleanup = async () => {
		if (attachedKnowledgeIds.length === 0) {
			toast.error($i18n.t('Attach at least one knowledge base first.'));
			return;
		}
		kbCleaningUp = true;
		try {
			const res = await extractKnowledgeGraphKbEntities(localStorage.token, id, {
				cleanup_only: true
			});
			toast.success(
				$i18n.t('KB cleanup started for {{count}} knowledge base(s).', {
					count: res.knowledge_ids.length
				})
			);
			// 잡 완료 폴링 시작 — 완료 시 reload + kbCleaningUp=false
			startJobPolling();
		} catch (e) {
			toast.error(`${e}`);
			kbCleaningUp = false;
		}
	};

	const _runKbExtract = async (parsedMaxChunks: number | null) => {
		kbExtracting = true;
		try {
			const res = await extractKnowledgeGraphKbEntities(localStorage.token, id, {
				model_id: llmModelId,
				max_chunks: parsedMaxChunks,
				min_confidence: 0.6,
				reset: kbResetProcessed
			});
			toast.success(
				$i18n.t('KB extraction started for {{count}} knowledge base(s).', {
					count: res.knowledge_ids.length
				})
			);
			// reset 토글은 한 번 쓰고 끄기 (실수 방지)
			kbResetProcessed = false;
			// 잡 완료 폴링 시작 — 완료 시 reload + kbExtracting=false
			startJobPolling();
		} catch (e) {
			toast.error(`${e}`);
			kbExtracting = false;
		}
	};

	const triggerKbExtract = async () => {
		if (attachedKnowledgeIds.length === 0) {
			toast.error($i18n.t('Attach at least one knowledge base first.'));
			return;
		}
		if (!llmModelId) {
			toast.error($i18n.t('Please select a model.'));
			return;
		}
		// 빈 값이면 max_chunks 미지정 (전체 처리). 값이 있으면 1~10000 범위로 클램프.
		const trimmed = kbMaxChunks.trim();
		const parsedMaxChunks = trimmed
			? Math.max(1, Math.min(10000, parseInt(trimmed, 10) || 0)) || null
			: null;

		// ── 사전 조회로 예상 LLM 호출 횟수 계산 후 경고 ──
		let preview;
		kbExtracting = true;
		try {
			preview = await previewKnowledgeGraphKbEntities(localStorage.token, id, {
				max_chunks: parsedMaxChunks,
				reset: kbResetProcessed
			});
		} catch (e) {
			toast.error(`${e}`);
			kbExtracting = false;
			return;
		}
		kbExtracting = false;

		if (!preview || preview.pending_total === 0) {
			toast.info($i18n.t('No pending chunks to extract.'));
			return;
		}

		// KB별 내역 — 가독성 있게 한 줄 요약
		const kbCount = Object.keys(preview.chunks_per_kb).length;
		const message = $i18n.t(
			'This will make approximately {{calls}} LLM calls across {{kbs}} knowledge base(s) ({{chunks}} pending chunks). Continue?',
			{
				calls: preview.estimated_llm_calls,
				kbs: kbCount,
				chunks: preview.pending_total
			}
		);

		openConfirm({
			title: $i18n.t('Confirm entity extraction'),
			message,
			confirmLabel: $i18n.t('Start extraction'),
			onConfirm: () => _runKbExtract(parsedMaxChunks)
		});
	};

	// ─── Knowledge Links (지식 연결) 핸들러 ───

	const reloadLinks = async () => {
		try {
			knowledgeLinks = await getKnowledgeLinks(localStorage.token, id);
		} catch (e) {
			console.error(e);
			knowledgeLinks = [];
		}
	};

	const addLink = async () => {
		if (!linkGlossaryId) {
			toast.error($i18n.t('Please select a glossary.'));
			return;
		}
		// 사용자가 체크박스로 선택한 KB / DB 만 연결.
		const knowledgeIds = Array.from(selectedLinkKbIds);
		const dbsphereIds = Array.from(selectedLinkDbIds);
		linkSaving = true;
		try {
			await createKnowledgeLink(localStorage.token, id, {
				glossary_id: linkGlossaryId,
				knowledge_ids: knowledgeIds,
				dbsphere_ids: dbsphereIds
			});
			toast.success($i18n.t('Knowledge link created'));
			showAddLinkModal = false;
			linkGlossaryId = '';
			lastInitializedLinkGlossaryId = '';
			linkSelectionTouched = false;
			selectedLinkKbIds = new Set();
			selectedLinkDbIds = new Set();
			await reloadLinks();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			linkSaving = false;
		}
	};

	const requestRemoveLink = (linkId: string, glossaryName: string) => {
		openConfirm({
			title: $i18n.t('Delete knowledge link?'),
			message: $i18n.t(
				'"{{name}}" and all entity nodes extracted for this link (glossary, database, and knowledge base entities) will be removed from this knowledge graph. This cannot be undone.',
				{ name: glossaryName }
			),
			confirmLabel: $i18n.t('Delete'),
			onConfirm: () => removeLink(linkId)
		});
	};

	const removeLink = async (linkId: string) => {
		try {
			await deleteKnowledgeLink(localStorage.token, id, linkId);
			toast.success($i18n.t('Knowledge link deleted'));
			await reloadLinks();
			await reload();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	// ─── Tool Tester ───

	const TOOL_ARGS_MAP: Record<string, (input: string) => Record<string, unknown>> = {
		kg_resolve_term: (v) => ({ term: v }),
		kg_search_concepts: (v) => ({ query: v, top_k: 10 }),
		kg_explore_context: (v) => ({ seed: v, hops: 2, max_nodes: 30 }),
		kg_neighbors: (v) => ({ node_id: v, hops: 1 }),
		kg_find_related_tables: (v) => ({ table_name: v, hops: 1 }),
		kg_fetch_data: (v) => ({ sql: v }),
		kg_fetch_document: (v) => ({ query: v, top_k: 5 })
	};

	const doExport = async () => {
		try {
			const data = await exportKnowledgeGraph(localStorage.token, id);
			const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `kg-${kg?.name || id}.json`;
			a.click();
			URL.revokeObjectURL(url);
			toast.success($i18n.t('Exported'));
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const runToolTest = async () => {
		if (!testerInput.trim()) return;
		testerRunning = true;
		testerResult = '';
		testerError = '';
		try {
			const argsFn = TOOL_ARGS_MAP[testerToolName];
			const args = argsFn ? argsFn(testerInput.trim()) : { term: testerInput.trim() };
			const res = await testKgTool(localStorage.token, id, testerToolName, args);
			if (res.error) {
				testerError = res.error;
			} else {
				testerResult = res.result ?? '(empty)';
			}
		} catch (e) {
			testerError = `${e}`;
		} finally {
			testerRunning = false;
		}
	};

	// Socket.IO 실시간 알림 — 백그라운드 작업 완료/실패 시 토스트 + reload
	const handleSocketNotification = async (payload: {
		type: string;
		data: { kg_id?: string; link_id?: string; glossary_id?: string };
	}) => {
		if (payload.data?.kg_id !== id) return;
		if (
			payload.type === 'kg-job-completed' ||
			payload.type === 'kg-link-sync-completed'
		) {
			toast.success($i18n.t('Link sync completed'));
			await reload();
			await reloadLinks();
		} else if (payload.type === 'kg-link-sync-failed') {
			toast.error($i18n.t('Link sync failed'));
			await reload();
		}
	};

	onMount(async () => {
		if (!$user) {
			await goto('/auth');
			return;
		}
		await reload();
		try {
			allGlossaries = (await getGlossaries(localStorage.token)) ?? [];
		} catch (e) {
			console.error(e);
			allGlossaries = [];
		}
		try {
			allDbspheres = (await getDbSpheres(localStorage.token)) ?? [];
		} catch (e) {
			console.error(e);
			allDbspheres = [];
		}
		try {
			allKnowledges = (await getKnowledgeBases(localStorage.token)) ?? [];
		} catch (e) {
			console.error(e);
			allKnowledges = [];
		}
		await reloadLinks();

		// socket 알림 구독 (잡 완료 실시간 반영)
		if ($socket) {
			$socket.on('notification', handleSocketNotification);
		}

		loaded = true;
	});

	onDestroy(() => {
		if ($socket) {
			$socket.off('notification', handleSocketNotification);
		}
		stopJobPolling();
	});
</script>

<svelte:head>
	<title>{kg?.name ?? $i18n.t('Knowledge Graph')} | {$WEBUI_NAME}</title>
</svelte:head>

{#if loaded && kg}
	<div class="flex flex-col w-full h-full translate-y-1 pb-2">
		<!-- Header (워크스페이스 공통 패턴) -->
		<WorkspaceDetailHeader
			backHref="/workspace/knowledge-graph"
			badgeContent={$i18n.t('Knowledge Graph')}
			bind:name={kg.name}
			namePlaceholder={$i18n.t('Knowledge Graph Name')}
			bind:description={kg.description}
			descriptionPlaceholder={$i18n.t('Add a description...')}
			resourceType="knowledge_graph"
			resourceId={id}
			bind:tagSelector
			showAccess={$user?.role === 'admin' || kg.user_id === $user?.id}
			{saving}
			on:access={() => (showAccessControlModal = true)}
			on:save={saveHandler}
		>
			<svelte:fragment slot="below">
				<ToolDescriptionSection
					bind:value={toolDescription}
					bind:aiModelId={toolDescModelId}
					generating={generatingToolDesc}
					aiDisabled={!(stats?.node_count)}
					helpText={$i18n.t('Describe when the agent should query this knowledge graph.')}
					placeholder={$i18n.t('e.g. Use for entity relationship queries across customer and product hierarchies.')}
					on:generate={aiGenerateToolDescription}
				/>
			</svelte:fragment>
		</WorkspaceDetailHeader>

		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={kg.access_control}
			accessRoles={['read', 'write']}
		/>

		<!-- Content area: 2-panel (nodes list on left, details on right) -->
		<div class="flex flex-row-reverse flex-1 min-h-0 gap-3 ml-8 pb-2.5 pr-2 sm:pr-0">
			<!-- Right panel: Stats, Graph, DB, Glossary, KB, Search, Tool Tester -->
			<div class="flex-1 min-w-0 flex flex-col gap-6 border border-gray-200 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-900 p-4 overflow-y-auto">

		<!-- Stats -->
		<div class="grid grid-cols-3 gap-[var(--cloo-space-3)]">
			<div class="flex flex-col items-center justify-center py-4 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/40">
				<span class="text-3xl font-bold text-blue-600 dark:text-blue-400">{stats?.node_count ?? 0}</span>
				<span class="text-xs text-blue-500 dark:text-blue-400 mt-1">{$i18n.t('Nodes')}</span>
			</div>
			<div class="flex flex-col items-center justify-center py-4 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800/40">
				<span class="text-3xl font-bold text-emerald-600 dark:text-emerald-400">{stats?.edge_count ?? 0}</span>
				<span class="text-xs text-emerald-500 dark:text-emerald-400 mt-1">{$i18n.t('Edges')}</span>
			</div>
			<div class="flex flex-col items-center justify-center py-4 rounded-xl bg-[var(--cloo-bg-surface)] border border-[var(--cloo-border-subtle)]">
				<span class="text-xs text-[var(--cloo-text-muted)]">{$i18n.t('Last synced')}</span>
				<span class="text-sm font-medium text-[var(--cloo-text-primary)] mt-1">{formatLastSynced(stats?.stats?.last_synced_at)}</span>
			</div>
		</div>

		<!-- Knowledge Links (용어집 + 연결된 DB + KB 통합 소스 묶음) -->
		<section class="flex flex-col gap-4">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-medium text-[var(--cloo-text-primary)]">
					{$i18n.t('Knowledge Links')}
				</h2>
				<div class="flex items-center gap-1.5">
					<div class="flex items-center gap-1.5">
						<span class="text-xs font-medium text-[var(--cloo-text-muted)] shrink-0">
							{$i18n.t('LLM model')}
						</span>
						<div class="w-56">
							<Selector
								value={llmModelId}
								items={[
									{ value: '', label: $i18n.t('Not set') },
									...modelItems
								]}
								placeholder={$i18n.t('Select model')}
								searchEnabled
								size="sm"
								disabled={savingLlmModel}
								on:change={(e) => autoSaveLlmModel(e.detail.value || '')}
							/>
						</div>
					</div>
					<Button
						kind="outlined"
						size="sm"
						className="h-9"
						on:click={() => (showAddLinkModal = true)}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('Add knowledge link')}
					</Button>
					<Button
						kind="filled"
						size="sm"
						className="h-9"
						loading={syncing}
						on:click={requestTriggerSync}
					>
						<svelte:fragment slot="prefix">
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
								<path fill-rule="evenodd" d="M13.836 2.477a.75.75 0 0 1 .75.75v3.182a.75.75 0 0 1-.75.75h-3.182a.75.75 0 0 1 0-1.5h1.37l-.84-.841a4.5 4.5 0 0 0-7.08.932.75.75 0 0 1-1.3-.75 6 6 0 0 1 9.44-1.242l.842.84V3.227a.75.75 0 0 1 .75-.75Zm-.911 7.5A.75.75 0 0 1 13.199 11a6 6 0 0 1-9.44 1.241l-.84-.84v1.371a.75.75 0 0 1-1.5 0V9.591a.75.75 0 0 1 .75-.75H5.35a.75.75 0 0 1 0 1.5H3.98l.841.841a4.5 4.5 0 0 0 7.08-.932.75.75 0 0 1 1.025-.273Z" clip-rule="evenodd" />
							</svg>
						</svelte:fragment>
						{syncing ? $i18n.t('Syncing...') : $i18n.t('Sync all')}
					</Button>
				</div>
			</div>

			<div class="text-xs text-gray-500">
				{$i18n.t('Each link bundles a glossary, the databases it references, and knowledge bases. Click "Sync entities" to extract everything together.')}
			</div>

			{#if knowledgeLinks.length === 0}
				<div class="text-sm text-gray-500 italic px-3 py-4 border border-dashed border-[var(--cloo-border-subtle)] rounded-xl">
					{$i18n.t('No knowledge links yet. Add one to bundle a glossary with knowledge bases.')}
				</div>
			{:else}
				<div class="flex flex-col gap-2">
					{#each knowledgeLinks as link}
						{@const glossary = allGlossaries.find((g) => g.id === link.glossary_id)}
						{@const expanded = link.glossary_id
							? Boolean(glossaryExpanded[link.glossary_id])
							: false}
						{@const detailLoading = link.glossary_id
							? Boolean(glossaryDetailLoading[link.glossary_id])
							: false}
						{@const groups =
							expanded && link.glossary_id ? groupExtractionSources(link.glossary_id) : []}
						<div
							class="flex flex-col border border-[var(--cloo-border-subtle)] rounded-xl bg-[var(--cloo-bg-surface)]"
						>
							<div class="flex items-center justify-between gap-2 px-3 py-2">
								<button
									type="button"
									class="flex items-center gap-2 min-w-0 flex-1 text-left"
									on:click={() =>
										link.glossary_id && toggleGlossaryExpanded(link.glossary_id)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="size-4 text-gray-400 transition-transform {expanded
											? 'rotate-90'
											: ''}"
									>
										<path
											fill-rule="evenodd"
											d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z"
											clip-rule="evenodd"
										/>
									</svg>
									<span class="text-sm font-medium text-[var(--cloo-text-primary)] truncate">
										{glossary?.name ?? link.glossary_id ?? '(unknown glossary)'}
									</span>
								</button>
								<div class="flex items-center gap-2">
									<Button
										kind="outlined"
										size="sm"
										on:click={() =>
											openNodeFilterSettings(link.id, glossary?.name ?? '')}
										title={$i18n.t(
											'Select which KB filter values become nodes in this link.'
										)}
									>
										{$i18n.t('Node settings')}
									</Button>
									<Button
										kind="outlined"
										size="sm"
										on:click={() =>
											openEdgeTypeCatalog(
												link.id,
												glossary?.name ?? '',
												link.glossary_id ?? ''
											)}
										title={$i18n.t('Define edge type catalog used by extraction.')}
									>
										{$i18n.t('Edge settings')}
									</Button>
									<Button
										kind="filled"
										size="sm"
										loading={Boolean(linkSyncing[link.id])}
										disabled={!hasEdgeTypeCatalog(link)}
										on:click={() => requestSyncLink(link.id, link.glossary_id)}
										title={hasEdgeTypeCatalog(link)
											? $i18n.t('Sync entities from this link to the knowledge graph.')
											: $i18n.t('Add at least one edge type in Edge settings before syncing.')}
									>
										{linkSyncing[link.id]
											? $i18n.t('Syncing...')
											: $i18n.t('Sync entities')}
									</Button>
									<button
										class="text-xs text-red-500 hover:text-red-700 dark:hover:text-red-400"
										on:click={() => requestRemoveLink(link.id, glossary?.name ?? link.glossary_id ?? '')}
										title={$i18n.t('Remove')}
									>
										<GarbageBin className="size-4" />
									</button>
								</div>
							</div>

							<!-- KB 태그 + 매칭 통계 -->
							<div class="flex flex-wrap items-center gap-1.5 px-3 pb-2 text-xs text-gray-500">
								{#if (link.knowledge_ids ?? []).length === 0}
									<span class="italic text-gray-400">{$i18n.t('No knowledge bases linked')}</span>
								{:else}
									{#each link.knowledge_ids ?? [] as kbId}
										{@const kb = allKnowledges.find((k) => k.id === kbId)}
										<span
											class="px-2 py-0.5 rounded bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-default)]"
										>
											{kb?.name ?? kbId}
										</span>
									{/each}
								{/if}
								{#if link.status?.documents_matched}
									<span class="ml-auto italic">
										{link.status.documents_matched} {$i18n.t('documents matched')}
									</span>
								{/if}
							</div>

							{#if expanded}
								<div
									class="border-t border-[var(--cloo-border-subtle)] px-3 py-3 flex flex-col gap-4"
								>
									{#if detailLoading}
										<div class="text-xs text-gray-500 italic">{$i18n.t('Loading...')}</div>
									{:else}
									{#if groups.length === 0}
										<div class="text-xs text-gray-500 italic">
											{$i18n.t('This glossary has no category → database column mappings yet.')}
										</div>
									{:else}
										{#each groups as grp}
											<div class="flex flex-col gap-2">
												<div
													class="flex items-center gap-1.5 text-xs font-medium text-[var(--cloo-text-primary)]"
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="size-3.5 text-blue-500"
													>
														<path
															d="M10 2c-4.42 0-8 1.5-8 3.5v9C2 16.5 5.58 18 10 18s8-1.5 8-3.5v-9C18 3.5 14.42 2 10 2ZM3.5 5.5c0-.57 2.64-2 6.5-2s6.5 1.43 6.5 2-2.64 2-6.5 2-6.5-1.43-6.5-2ZM10 16.5c-3.86 0-6.5-1.43-6.5-2v-2.16c1.47.79 3.86 1.16 6.5 1.16s5.03-.37 6.5-1.16v2.16c0 .57-2.64 2-6.5 2Zm0-4.5c-3.86 0-6.5-1.43-6.5-2V7.84C4.97 8.63 7.36 9 10 9s5.03-.37 6.5-1.16V10c0 .57-2.64 2-6.5 2Z"
														/>
													</svg>
													<span>{grp.dbsphere_name}</span>
												</div>
												<div class="flex flex-col gap-2 pl-5">
													{#each grp.tables as t}
														{@const tkey = `${grp.dbsphere_id}:${t.table_name}`}
														{@const tExpanded = Boolean(tableColumnsExpanded[tkey])}
														{@const tLoading = Boolean(tableColumnsLoading[tkey])}
														{@const cols = tableColumnsCache[tkey]}
														<div
															class="flex flex-col gap-1 rounded-lg border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-default)] px-2.5 py-2"
														>
															<button
																type="button"
																class="flex items-center gap-1.5 text-left"
																on:click={() =>
																	toggleTableExpanded(grp.dbsphere_id, t.table_name)}
															>
																<svg
																	xmlns="http://www.w3.org/2000/svg"
																	viewBox="0 0 20 20"
																	fill="currentColor"
																	class="size-3 text-gray-400 transition-transform {tExpanded
																		? 'rotate-90'
																		: ''}"
																>
																	<path
																		fill-rule="evenodd"
																		d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z"
																		clip-rule="evenodd"
																	/>
																</svg>
																<span class="text-xs font-medium text-[var(--cloo-text-primary)]"
																	>{t.table_name}</span
																>
															</button>
															<div class="flex flex-col gap-1 pl-4">
																{#each t.mappings as m}
																	<div class="flex flex-col gap-0.5">
																		<div class="flex items-center gap-1.5 text-[11px] text-gray-500">
																			<span class="font-mono text-[var(--cloo-text-default)]"
																				>{m.column}</span
																			>
																			<span>→</span>
																			<span
																				class="px-1.5 py-0.5 rounded bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-default)]"
																			>
																				{m.category || $i18n.t('(uncategorized)')}
																			</span>
																			<span class="text-gray-400"
																				>· {m.term_count} {$i18n.t('terms')}</span
																			>
																		</div>
																		{#if m.sample_terms.length > 0}
																			<div class="flex flex-wrap gap-1 pl-0.5">
																				{#each m.sample_terms as term}
																					<span
																						class="text-[11px] px-1.5 py-0.5 rounded bg-[var(--cloo-bg-surface)] border border-[var(--cloo-border-subtle)] text-[var(--cloo-text-default)]"
																					>
																						{term}
																					</span>
																				{/each}
																				{#if m.term_count > m.sample_terms.length}
																					<span class="text-[11px] text-gray-400">
																						+{m.term_count - m.sample_terms.length}
																					</span>
																				{/if}
																			</div>
																		{/if}
																	</div>
																{/each}
															</div>
															{#if tExpanded}
																<div class="mt-1 pl-4 border-t border-[var(--cloo-border-subtle)] pt-1.5">
																	{#if tLoading}
																		<div class="text-[11px] text-gray-500 italic">
																			{$i18n.t('Loading...')}
																		</div>
																	{:else if !cols || cols.length === 0}
																		<div class="text-[11px] text-gray-500 italic">
																			{$i18n.t('No columns found. Run schema extraction on this DbSphere first.')}
																		</div>
																	{:else}
																		<div class="flex flex-col gap-0.5">
																			{#each cols as c}
																				<div class="flex items-center gap-1.5 text-[11px]">
																					<span class="font-mono text-[var(--cloo-text-default)]"
																						>{c.name}</span
																					>
																					<span class="text-gray-400">{c.data_type}</span>
																					{#if c.is_primary_key}
																						<span
																							class="px-1 py-0 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 text-[10px]"
																							>PK</span
																						>
																					{/if}
																					{#if c.is_foreign_key}
																						<span
																							class="px-1 py-0 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-[10px]"
																							>FK</span
																						>
																					{/if}
																					{#if c.description}
																						<span class="text-gray-500 truncate">— {c.description}</span>
																					{/if}
																				</div>
																			{/each}
																		</div>
																	{/if}
																</div>
																{/if}
														</div>
													{/each}
												</div>
											</div>
										{/each}
									{/if}

									<!-- 연결된 지식 기반 (KB) -->
									{#if (link.knowledge_ids ?? []).length > 0}
										{@const docEntityMap = link.status?.doc_entity_map ?? {}}
										<div class="flex flex-col gap-2">
											<div
												class="flex items-center gap-1.5 text-xs font-medium text-[var(--cloo-text-primary)]"
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 20 20"
													fill="currentColor"
													class="size-3.5 text-pink-500"
												>
													<path
														d="M10.75 16.82A7.62 7.62 0 0 1 16.5 18a8.5 8.5 0 0 0 1.7-.18 1 1 0 0 0 .8-.98V4.62A1 1 0 0 0 17.78 3.6c-.55.07-1.1.1-1.66.1A7.62 7.62 0 0 0 10 5.06v11.76Z"
													/>
													<path
														d="M9.25 5.06A7.62 7.62 0 0 0 3.46 3.7a17 17 0 0 1-1.66-.1A1 1 0 0 0 .58 4.46l-.08.16v12.1a1 1 0 0 0 .8.98 8.5 8.5 0 0 0 1.7.18 7.62 7.62 0 0 1 5.75 1.18l.5.34V5.4l-.5-.34Z"
													/>
												</svg>
												<span>{$i18n.t('Knowledge bases')}</span>
											</div>
											<div class="flex flex-col gap-1.5 pl-5">
												{#each link.knowledge_ids ?? [] as kbId}
													{@const kb = allKnowledges.find((k) => k.id === kbId)}
													{@const fileCount = (kb?.data?.file_ids ?? []).length}
													{@const hasGlossaryFilter = (kb?.meta?.filter_schema ?? []).some(
														(f) => f?.type === 'glossary' && f?.glossary_id === link.glossary_id
													)}
													{@const kbFileIds = kb?.data?.file_ids ?? []}
													{@const matchedFiles = kbFileIds.filter((fid) => docEntityMap[fid])}
													<div
														class="flex flex-col gap-1 rounded-lg border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-default)] px-2.5 py-2"
													>
														<div class="flex items-center gap-2 min-w-0">
															<span
																class="text-xs font-medium text-[var(--cloo-text-primary)] truncate"
															>
																{kb?.name ?? kbId}
															</span>
															<span
																class="text-[10px] px-1.5 py-0.5 rounded bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-default)] shrink-0"
															>
																{fileCount} {$i18n.t('files')}
															</span>
															{#if hasGlossaryFilter}
																<span
																	class="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 shrink-0"
																>
																	{$i18n.t('Filter configured')}
																</span>
															{:else}
																<span
																	class="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 shrink-0"
																>
																	{$i18n.t('No glossary filter')}
																</span>
															{/if}
															{#if matchedFiles.length > 0}
																<span class="text-[10px] text-gray-500 shrink-0 ml-auto">
																	{matchedFiles.length}/{fileCount} {$i18n.t('matched')}
																</span>
															{/if}
														</div>
														{#if kb?.description}
															<div class="text-[11px] text-gray-500 line-clamp-2">
																{kb.description}
															</div>
														{/if}
													</div>
												{/each}
											</div>
										</div>
									{/if}
								{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</section>

		<!-- Add Knowledge Link Modal -->
		{#if showAddLinkModal}
			<Modal bind:show={showAddLinkModal} size="sm">
				<div class="flex flex-col gap-4 p-6">
					<h3 class="text-lg font-semibold text-[var(--cloo-text-primary)]">
						{$i18n.t('Add Knowledge Link')}
					</h3>

					<div class="flex flex-col gap-3">
						<div>
							<LabelBase label={$i18n.t('Glossary')} />
							<Selector
								value={linkGlossaryId}
								items={allGlossaries
									.filter((g) => !knowledgeLinks.some((l) => l.glossary_id === g.id))
									.map((g) => ({ value: g.id, label: g.name }))}
								placeholder={$i18n.t('Select glossary')}
								searchEnabled
								size="md"
								portal="body"
								contentClassName="z-[10000]"
								on:change={async (e) => {
									linkGlossaryId = e.detail.value;
									// glossary detail 로드 (extraction_sources 확인용)
									if (linkGlossaryId && !glossaryDetails[linkGlossaryId]) {
										try {
											const g = await getGlossaryById(localStorage.token, linkGlossaryId);
											if (g) glossaryDetails[linkGlossaryId] = g;
										} catch (_) { /* ignore */ }
									}
								}}
							/>
							<div class="text-xs text-gray-500 mt-1">
								{$i18n.t('Glossaries already linked to this KG are hidden.')}
							</div>
						</div>

						{#if linkGlossaryId}
							<!-- 연결 가능 KB (체크박스 선택) -->
							<div>
								<LabelBase label={$i18n.t('Knowledge bases to connect')} />
								<div class="text-xs text-gray-500 mb-1">
									{$i18n.t('Select which knowledge bases to include in this link. Only KBs with a glossary filter for the selected glossary are shown.')}
								</div>
								{#if linkedKbs.length > 0}
									<div class="flex flex-col gap-1">
										{#each linkedKbs as kb}
											<label
												class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-[var(--cloo-bg-default)] border border-[var(--cloo-border-subtle)] cursor-pointer hover:bg-[var(--cloo-bg-neutral-hovered)]"
											>
												<Checkbox
													state={selectedLinkKbIds.has(kb.id) ? 'checked' : 'unchecked'}
													on:change={() => toggleLinkKb(kb.id)}
												/>
												<span class="text-xs font-medium text-[var(--cloo-text-primary)] flex-1">{kb.name}</span>
												<span class="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">
													{$i18n.t('Filter configured')}
												</span>
											</label>
										{/each}
									</div>
								{:else}
									<div class="text-xs text-amber-600 dark:text-amber-400 italic">
										{$i18n.t('No knowledge bases have a glossary filter for this glossary. Configure a glossary filter on a KB first.')}
									</div>
								{/if}
							</div>

							<!-- 연결 가능 DB (체크박스 선택) -->
							{#if linkedDbs.length > 0}
								<div>
									<LabelBase label={$i18n.t('Databases to connect')} />
									<div class="text-xs text-gray-500 mb-1">
										{$i18n.t('Select which databases referenced by this glossary to include.')}
									</div>
									<div class="flex flex-col gap-1">
										{#each linkedDbs as db}
											<label
												class="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-[var(--cloo-bg-default)] border border-[var(--cloo-border-subtle)] cursor-pointer hover:bg-[var(--cloo-bg-neutral-hovered)]"
											>
												<Checkbox
													state={selectedLinkDbIds.has(db.id) ? 'checked' : 'unchecked'}
													on:change={() => toggleLinkDb(db.id)}
												/>
												<span class="text-xs font-medium text-[var(--cloo-text-primary)]">{db.name}</span>
											</label>
										{/each}
									</div>
								</div>
							{/if}
						{/if}
					</div>

					<div class="flex justify-end gap-2 mt-2">
						<Button kind="outlined" size="md" on:click={() => (showAddLinkModal = false)}>
							{$i18n.t('Cancel')}
						</Button>
						<Button kind="filled" size="md" disabled={linkSaving} on:click={addLink}>
							{linkSaving ? $i18n.t('Creating...') : $i18n.t('Create')}
						</Button>
					</div>
				</div>
			</Modal>
		{/if}

		<!-- Semantic search -->
		<section class="flex flex-col gap-3">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-medium text-[var(--cloo-text-primary)]">
					{$i18n.t('Semantic search')}
				</h2>
				{#if lastSearchedQuery}
					<button
						type="button"
						class="text-xs text-gray-500 hover:underline"
						on:click={clearSearch}
					>
						{$i18n.t('Clear')}
					</button>
				{/if}
			</div>

			<div class="flex items-center gap-2">
				<div class="flex-1">
					<Input
						bind:value={searchQuery}
						placeholder={$i18n.t('Search nodes by meaning (e.g. "VIP customer", "user table")')}
						type="search"
						size="md"
						on:keydown={onSearchKeydown}
					>
						<svelte:fragment slot="prefix">
							<Search className="size-3.5" />
						</svelte:fragment>
					</Input>
				</div>
				<Button kind="outlined" size="md" disabled={searching} on:click={runSearch}>
					{searching ? $i18n.t('Searching...') : $i18n.t('Search')}
				</Button>
			</div>

			{#if !searchAvailable}
				<div
					class="text-xs text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2"
				>
					⚠ {$i18n.t('Semantic search requires the search engine to be configured in Admin > Settings > Documents.')}
				</div>
			{:else if lastSearchedQuery}
				<div class="text-xs text-gray-500">
					{$i18n.t('{{count}} results for "{{query}}"', {
						count: searchResults.length,
						query: lastSearchedQuery
					})}
				</div>
				{#if searchResults.length > 0}
					<div
						class="border border-[var(--cloo-border-subtle)] rounded-xl divide-y divide-[var(--cloo-border-subtle)] overflow-hidden"
					>
						{#each searchResults as r}
							<div
								class="flex items-center gap-3 px-3 py-2 hover:bg-[var(--cloo-bg-neutral-hovered)]"
							>
								<span
									class="text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded {getNodeTypeBadgeClass(
										r.node_type
									)}"
								>
									{r.node_type}
								</span>
								<span class="text-sm text-[var(--cloo-text-primary)] flex-1 truncate">
									{r.label}
								</span>
								<span class="text-[10px] text-gray-400 font-mono">
									{r.score.toFixed(3)}
								</span>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</section>

		<!-- Tool Tester (관리자용) -->
		<section class="flex flex-col gap-3">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-medium text-[var(--cloo-text-primary)]">
					{$i18n.t('Try KG Tools')}
				</h2>
				<Button
					kind="outlined"
					size="sm"
					on:click={() => (showToolTester = !showToolTester)}
				>
					{showToolTester ? $i18n.t('Hide') : $i18n.t('Show')}
				</Button>
			</div>

			{#if showToolTester}
				<div class="flex flex-col gap-3 p-4 border border-[var(--cloo-border-subtle)] rounded-xl bg-[var(--cloo-bg-surface)]">
					<div class="flex flex-col gap-2">
						<div class="flex items-end gap-2">
						<div class="w-[220px]">
							<LabelBase label={$i18n.t('Tool')} size="sm" />
							<select
								class="w-full text-sm rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-default)] px-3 py-1.5"
								bind:value={testerToolName}
							>
								<option value="kg_resolve_term">resolve_term</option>
								<option value="kg_explore_context">explore_context</option>
								<option value="kg_search_concepts">search_concepts</option>
								<option value="kg_find_related_tables">find_related_tables</option>
								<option value="kg_neighbors">neighbors</option>
								<option value="kg_fetch_data">fetch_data</option>
								<option value="kg_fetch_document">fetch_document</option>
							</select>
						</div>
						<div class="flex-1">
							<LabelBase label={$i18n.t('Input')} size="sm" />
							<Input
								bind:value={testerInput}
								placeholder={testerToolName === 'kg_neighbors'
									? $i18n.t('Node ID')
									: testerToolName === 'kg_fetch_data'
									? $i18n.t('SELECT ... FROM ...')
									: testerToolName === 'kg_fetch_document'
									? $i18n.t('e.g. 카테고리 변경 절차')
									: $i18n.t('e.g. 갤럭시S26, VIP 고객, products')}
								size="md"
								on:keydown={(e) => { if (e.key === 'Enter') runToolTest(); }}
							/>
						</div>
						<Button kind="filled" size="md" disabled={testerRunning || !testerInput.trim()} on:click={runToolTest}>
							{testerRunning ? $i18n.t('Running...') : $i18n.t('Run')}
						</Button>
					</div>

					<!-- 도구별 설명 -->
					<div class="text-xs text-gray-500 bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2">
						{#if testerToolName === 'kg_resolve_term'}
							<strong>resolve_term</strong> — {$i18n.t('Look up a business term and return its database column mappings with WHERE filters.')}
						{:else if testerToolName === 'kg_explore_context'}
							<strong>explore_context</strong> — {$i18n.t('Explore the knowledge graph around a topic. Returns features, DB mappings, related tables, glossary terms — everything connected within 1-3 hops.')}
						{:else if testerToolName === 'kg_search_concepts'}
							<strong>search_concepts</strong> — {$i18n.t('Hybrid vector+graph search. Finds nodes by semantic similarity and expands top results with their 1-hop neighbors.')}
						{:else if testerToolName === 'kg_find_related_tables'}
							<strong>find_related_tables</strong> — {$i18n.t('Find tables joinable to a given table via FK relationships. Returns ready-to-use JOIN hints.')}
						{:else if testerToolName === 'kg_neighbors'}
							<strong>neighbors</strong> — {$i18n.t('Traverse N-hop neighborhood of a specific node (requires node ID from search results).')}
						{:else if testerToolName === 'kg_fetch_data'}
							<strong>fetch_data</strong> — {$i18n.t('Execute a SELECT SQL query against the linked database and return real data rows (max 100). Falls back to document search if 0 rows.')}
						{:else if testerToolName === 'kg_fetch_document'}
							<strong>fetch_document</strong> — {$i18n.t('Search the knowledge base linked to this KG and return relevant document chunks.')}
						{/if}
					</div>
					</div>

					{#if testerError}
						<div class="text-sm text-red-500 bg-red-50 dark:bg-red-950/20 p-3 rounded-lg">
							{testerError}
						</div>
					{/if}

					{#if testerResult}
						<pre class="text-xs font-mono bg-gray-50 dark:bg-gray-900 p-3 rounded-lg overflow-x-auto whitespace-pre-wrap max-h-[400px] overflow-y-auto border border-[var(--cloo-border-subtle)]">{testerResult}</pre>
					{/if}

					<div class="text-xs text-gray-500">
						ⓘ {$i18n.t('Test KG tools directly without creating an agent. Results show what the agent would see.')}
					</div>
				</div>
			{/if}
		</section>
		</div><!-- /Right panel -->

		<!-- Left panel: Nodes / Edges list -->
		<div class="w-96 shrink-0 flex flex-col border border-gray-200 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-900 overflow-hidden">
			<div class="p-3 border-b border-gray-100 dark:border-gray-800">
				<!-- Top: Open graph fullscreen button -->
				<div class="mb-2">
					<Button
						kind="filled"
						size="sm"
						className="w-full"
						on:click={() =>
							window.open(
								`/workspace/knowledge-graph/${id}/graph`,
								'_blank',
								'noopener,noreferrer'
							)}
					>
						{$i18n.t('Show graph')}
					</Button>
				</div>

				<!-- Tabs: Nodes / Edges -->
				<div class="flex items-center gap-1 mb-2">
					<button
						type="button"
						class="flex-1 text-xs font-medium px-2 py-1.5 rounded transition
							{entityTab === 'nodes'
							? 'bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-primary)]'
							: 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800'}"
						on:click={() => switchEntityTab('nodes')}
					>
						{$i18n.t('Nodes')} <span class="text-[10px] text-gray-400 ml-1">{nodeTotal}</span>
					</button>
					<button
						type="button"
						class="flex-1 text-xs font-medium px-2 py-1.5 rounded transition
							{entityTab === 'edges'
							? 'bg-[var(--cloo-bg-neutral-hovered)] text-[var(--cloo-text-primary)]'
							: 'text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800'}"
						on:click={() => switchEntityTab('edges')}
					>
						{$i18n.t('Edges')} <span class="text-[10px] text-gray-400 ml-1">{edgeTotal}</span>
					</button>
				</div>

				<div class="flex flex-col gap-2">
					<Input
						bind:value={nodeSearchQuery}
						placeholder={entityTab === 'nodes'
							? $i18n.t('Search nodes...')
							: $i18n.t('Search edges (src/dst label or type)...')}
						type="search"
						size="sm"
					>
						<svelte:fragment slot="prefix">
							<Search className="size-3" />
						</svelte:fragment>
					</Input>
					{#if entityTab === 'nodes'}
						<Selector
							value={nodeFilterType}
							items={[
								{ value: '', label: $i18n.t('All types') },
								...KG_NODE_TYPES.map((t) => ({ value: t.key, label: t.label }))
							]}
							size="sm"
							searchEnabled
							on:change={(e) => onNodeFilterChange(e.detail.value)}
						/>
					{:else}
						<Selector
							value={edgeFilterType}
							items={[
								{ value: '', label: $i18n.t('All edge types') },
								...edgeTypeOptions.map((o) => ({
									value: o.edge_type,
									label: `${o.edge_type} (${o.count})`
								}))
							]}
							size="sm"
							searchEnabled
							on:change={(e) => onEdgeFilterChange(e.detail.value)}
						/>
					{/if}
				</div>
			</div>
			<div class="flex-1 min-h-0 overflow-y-auto">
				{#if entityTab === 'nodes'}
					{#if nodeTotal === 0 && !nodesLoading}
						<div class="text-xs text-gray-500 italic px-3 py-6 text-center">
							{nodeFilterType || nodeSearchQuery
								? $i18n.t('No nodes match the filter.')
								: $i18n.t('No nodes yet. Attach a glossary and click "Sync entities".')}
						</div>
					{:else}
						{#each pagedNodes as n}
							<div class="flex items-center gap-2 px-3 py-2 border-b border-gray-50 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-850">
								<span
									class="text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0 {getNodeTypeBadgeClass(
										n.node_type
									)}"
								>
									{n.node_type}
								</span>
								<div class="flex-1 min-w-0">
									<div class="text-sm text-[var(--cloo-text-primary)] truncate">{n.label}</div>
									{#if n.properties?.description}
										<div class="text-[10px] text-gray-400 truncate">{n.properties.description}</div>
									{/if}
								</div>
							</div>
						{/each}
					{/if}
				{:else}
					<!-- Edges tab -->
					{#if edgeTotal === 0 && !edgesLoading}
						<div class="text-xs text-gray-500 italic px-3 py-6 text-center">
							{nodeSearchQuery
								? $i18n.t('No edges match the filter.')
								: $i18n.t('No edges yet.')}
						</div>
					{:else}
						{#each pagedEdges as e}
							<div class="flex flex-col gap-0.5 px-3 py-2 border-b border-gray-50 dark:border-gray-850 hover:bg-gray-50 dark:hover:bg-gray-850">
								<div class="flex items-center gap-1.5">
									<span class="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 shrink-0">
										{e.edge_type}
									</span>
									{#if e.weight !== null && e.weight !== undefined}
										<span class="text-[9px] text-gray-400">w={e.weight}</span>
									{/if}
								</div>
								<div class="text-xs text-gray-600 dark:text-gray-300 font-mono truncate">
									{e.src_id.split('__').slice(-1)[0] || e.src_id}
									<span class="text-gray-400">→</span>
									{e.dst_id.split('__').slice(-1)[0] || e.dst_id}
								</div>
							</div>
						{/each}
					{/if}
				{/if}
			</div>
			{#if entityTab === 'nodes' && nodePageCount > 1}
				<div class="flex items-center justify-center gap-2 text-xs text-gray-500 py-2 border-t border-gray-100 dark:border-gray-800">
					<button
						class="px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
						disabled={nodePage === 0 || nodesLoading}
						on:click={() => onNodePageChange(nodePage - 1)}
					>
						← {$i18n.t('Prev')}
					</button>
					<span>{nodePage + 1} / {nodePageCount}</span>
					<button
						class="px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
						disabled={nodePage >= nodePageCount - 1 || nodesLoading}
						on:click={() => onNodePageChange(nodePage + 1)}
					>
						{$i18n.t('Next')} →
					</button>
				</div>
			{:else if entityTab === 'edges' && edgePageCount > 1}
				<div class="flex items-center justify-center gap-2 text-xs text-gray-500 py-2 border-t border-gray-100 dark:border-gray-800">
					<button
						class="px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
						disabled={edgePage === 0 || edgesLoading}
						on:click={() => onEdgePageChange(edgePage - 1)}
					>
						← {$i18n.t('Prev')}
					</button>
					<span>{edgePage + 1} / {edgePageCount}</span>
					<button
						class="px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
						disabled={edgePage >= edgePageCount - 1 || edgesLoading}
						on:click={() => onEdgePageChange(edgePage + 1)}
					>
						{$i18n.t('Next')} →
					</button>
				</div>
			{/if}
		</div><!-- /Left panel -->
		</div><!-- /Content area -->
	</div>

	<ConfirmDialog
		bind:show={showConfirmDialog}
		title={confirmTitle}
		message={confirmMessage}
		{confirmLabel}
		onConfirm={() => confirmAction()}
	/>

	<EdgeTypeCatalogModal
		bind:show={showEdgeTypeCatalogModal}
		kgId={id}
		linkId={edgeTypeCatalogLinkId}
		linkTitle={edgeTypeCatalogLinkTitle}
		glossaryId={edgeTypeCatalogGlossaryId}
		defaultModelId={edgeTypeCatalogDefaultModelId}
		on:saved={() => {
			fetchEdgeTypeOptions();
			// 카탈로그 items 변경 시 sync 버튼의 disabled 상태가 달라져야 하므로
			// link 목록을 다시 로드해 link.config.edge_types 를 갱신한다.
			reloadLinks();
		}}
	/>

	<NodeFilterModal
		bind:show={showNodeFilterModal}
		kgId={id}
		linkId={nodeFilterLinkId}
		linkTitle={nodeFilterLinkTitle}
		linkedKbs={nodeFilterLinkedKbs}
	/>

{:else}
	<div class="w-full h-full flex justify-center items-center">
		<Spinner />
	</div>
{/if}
