<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { onMount, getContext, onDestroy, tick } from 'svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	const i18n = getContext('i18n');

	import { goto, beforeNavigate } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		mobile,
		showSidebar,
		knowledge as _knowledge,
		config,
		user,
		socket,
		models
	} from '$lib/stores';
	import { toastHistory } from '$lib/stores/toast-history';

	import { updateFileDataContentById, uploadFile, deleteFileById } from '$lib/apis/files';
	import {
		addFileToKnowledgeById,
		batchClearFilterMetadataByKnowledgeById,
		batchRemoveFilesFromKnowledgeById,
		checkKnowledgeDuplicateFilenames,
		extractAllMetadata,
		extractFileMetadata,
		getKnowledgeById,
		getKnowledgeBases,
		getKnowledgeFileIds,
		getKnowledgeFiles,
		removeFileFromKnowledgeById,
		retryFileInKnowledgeById,
		retryFailedFilesInKnowledge,
		setFileMetadata,
		updateFileFromKnowledgeById,
		updateKnowledgeById,
		type DuplicatePolicy
	} from '$lib/apis/knowledge';

	import { generateText } from '$lib/apis';
	import { transcribeAudio } from '$lib/apis/audio';
	import { blobToFile } from '$lib/utils';
	import { processFile } from '$lib/apis/retrieval';
	import { getGroups } from '$lib/apis/groups';

	import { createPicker } from '$lib/utils/google-drive-picker';
	import { pickAndDownloadFile } from '$lib/utils/onedrive-file-picker';
	import { pickDirectoryFiles } from '$lib/utils/directory-picker';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Files from './KnowledgeBase/Files.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	import AddContentMenu from './KnowledgeBase/AddContentMenu.svelte';
	import AddTextContentModal from './KnowledgeBase/AddTextContentModal.svelte';
	import SharePointBrowser from '$lib/components/common/SharePointBrowser.svelte';
	import RichTextInput from '$lib/components/common/RichTextInput.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import EllipsisVertical from '$lib/components/icons/EllipsisVertical.svelte';
	import Drawer from '$lib/components/common/Drawer.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import Cog6 from '$lib/components/icons/Cog6.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import WorkspaceDetailHeader from '../common/WorkspaceDetailHeader.svelte';
	import ToolDescriptionSection from '../common/ToolDescriptionSection.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import SearchSettingsModal from './SearchSettingsModal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import GlossarySelector from '$lib/components/workspace/Agents/Glossary/Selector.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import RadioGroup from '$lib/components/common/RadioGroup.svelte';
	import Radio from '$lib/components/common/Radio.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import { slide } from 'svelte/transition';
	import { formatBackendError } from '$lib/utils/error';

	let tagSelector: any;
	let largeScreen = true;

	let pane;
	let showSidepanel = true;
	let minSize = 0;

	type Knowledge = {
		id: string;
		name: string;
		description: string;
		data: {
			file_ids?: string[];
			file_metadata?: Record<string, any>;
			[key: string]: any;
		};
		meta?: Record<string, any>;
		user_id?: string;
		access_control?: any;
		[key: string]: any;
	};

	let id = null;
	let knowledge: Knowledge | null = null;
	let query = '';

	let showAddTextContentModal = false;
	let showSharePointBrowser = false;
	let showAccessControlModal = false;
	let showSearchSettingsModal = false;
	let searchSettings: Record<string, any> | null = null;

	let group_ids: string[] = [];

	$: isOwnerOrAdmin = $user?.role === 'admin' || knowledge?.user_id === $user?.id;

	$: canWrite = $user?.role === 'admin' || (
		$user?.permissions?.workspace?.knowledge === 'write' && (
			knowledge?.user_id === $user?.id
			|| knowledge?.access_control?.write?.user_ids?.includes($user?.id)
			|| knowledge?.access_control?.write?.group_ids?.some((gid: string) => group_ids.includes(gid))
		)
	);

	let inputFiles = null;

	// ── Paginated file list state ─────────────────────────────────────────────
	let loadedFiles: any[] = [];
	let totalFiles = 0;
	let isLoadingFiles = false;
	let hasMore = true;
	const pageSize = 50;
	let debouncedQuery = '';
	let sort: 'newest' | 'oldest' | 'name' = 'newest';
	let searchDebounceTimer: any = null;
	let fileListScroll: HTMLElement | null = null;

	let selectedFile = null;
	let selectedFileId = null;

	$: if (selectedFileId) {
		const file = loadedFiles.find((file) => file.id === selectedFileId);
		if (file) {
			file.data = file.data ?? { content: '' };
			selectedFile = file;
		} else {
			selectedFile = null;
		}
	} else {
		selectedFile = null;
	}

	let mediaQuery;
	let dragged = false;

	// ── Filter schema state ────────────────────────────────────────────────────
	let showFilterSettings = false;
	let filterSchema: { label: string; type: string; slot: string; description?: string; options?: string[] }[] = [];

	// 모달 한정 dirty 추적 — 토글 / 입력 변경이 즉시 KB.meta 에 저장되지 않으므로
	// "변경 사항 미저장" 인디케이터 + Cancel/X 시 confirm 으로 사용자에게 명시한다.
	let filterModalSnapshot = '';
	$: filterModalDirty =
		showFilterSettings &&
		filterModalSnapshot !== '' &&
		JSON.stringify({ filterSchema, filterExtractionMode, aiModelId }) !==
			filterModalSnapshot;

	const _snapshotFilterModal = () =>
		JSON.stringify({ filterSchema, filterExtractionMode, aiModelId });

	const openFilterModal = () => {
		filterModalSnapshot = _snapshotFilterModal();
		showFilterSettings = true;
	};

	const closeFilterModal = (force = false) => {
		if (filterModalDirty && !force) {
			const ok = window.confirm(
				$i18n.t('You have unsaved filter changes. Discard them?')
			);
			if (!ok) return;
		}
		showFilterSettings = false;
		filterModalSnapshot = '';
	};

	// ── Tool description state ─────────────────────────────────────────────────
	let toolDescription = '';

	// ── Settings save state ────────────────────────────────────────────────────
	let isSavingSettings = false;
	let settingsDirty = false;  // 미저장 변경사항 있음 여부

	// ── File metadata state ────────────────────────────────────────────────────
	let fileMetadataValues: Record<string, Record<string, any>> = {};
	let selectedMetaFileId: string | null = null;
	let savingMetaFileId: string | null = null;

	// ── AI generation state ────────────────────────────────────────────────────
	let generatingToolDesc = false;
	let generatingFilterIdx: number | null = null;
	let aiModelId = '';
	$: needsAiModel =
		filterExtractionMode === 'ai' ||
		(Array.isArray(filterSchema) &&
			filterSchema.some((f) => f?.type === 'glossary' && f?.use_ai));

	// ── AI extraction state ───────────────────────────────────────────────────
	let filterExtractionMode: 'manual' | 'ai' = 'manual';
	let extractingFileIds: Set<string> = new Set();
	let extractingAll = false;
	let extractProgress = { completed: 0, total: 0, success: 0, failed: 0 };
	let checkedFileIds: Set<string> = new Set();
	// 배치 삭제 상태
	let deletingSelected = false;
	let activeDeleteJobId: string | null = null;
	let deleteJobTotal = 0;

	$: checkedCount = checkedFileIds.size;
	$: allChecked = totalFiles > 0 && checkedCount >= totalFiles;

	let selectingAll = false;
	const toggleAllChecked = async () => {
		if (allChecked) {
			checkedFileIds = new Set();
			return;
		}
		// 페이지네이션 / limit 상한 과 무관하게 전체 파일 ID 만 받는 경량
		// 엔드포인트를 호출. `getKnowledgeFiles` 는 백엔드 limit 상한(500) 에
		// 걸려 50개로 clamp 되므로 "전체 선택" 용도로 쓸 수 없다.
		selectingAll = true;
		try {
			const res = await getKnowledgeFileIds(localStorage.token, id, {
				search: debouncedQuery || undefined
			});
			checkedFileIds = new Set(res.ids ?? []);
		} catch (e) {
			console.error('Failed to select all matching files:', e);
			toast.error($i18n.t('Failed to select all matching files'));
		} finally {
			selectingAll = false;
		}
	};

	// ── Paginated load helpers ────────────────────────────────────────────────
	const loadMoreFiles = async () => {
		if (!id || isLoadingFiles || !hasMore) return;
		isLoadingFiles = true;
		try {
			const res = await getKnowledgeFiles(localStorage.token, id, {
				skip: loadedFiles.length,
				limit: pageSize,
				search: debouncedQuery || undefined,
				sort
			});
			if (res) {
				const existingIds = new Set(loadedFiles.map((f) => f.id));
				const fresh = (res.files ?? []).filter((f: any) => !existingIds.has(f.id));
				loadedFiles = [...loadedFiles, ...fresh];
				totalFiles = res.total ?? loadedFiles.length;
				hasMore = loadedFiles.length < totalFiles;
			}
		} catch (e) {
			console.error('Failed to load files:', e);
		} finally {
			isLoadingFiles = false;
		}
		// 컨테이너가 아직 스크롤 가능한 상태가 아니면 (content < container height)
		// 스크롤바가 생길 때까지 한 번 더 로드 — 스크롤 이벤트를 트리거할 수단을 확보
		await tick();
		if (hasMore && fileListScroll) {
			const { scrollHeight, clientHeight } = fileListScroll;
			if (scrollHeight <= clientHeight + 1) {
				await loadMoreFiles();
			}
		}
	};

	const resetAndReload = async () => {
		loadedFiles = [];
		totalFiles = 0;
		hasMore = true;
		selectedFileId = null;
		await loadMoreFiles();
	};

	const onSearchInput = () => {
		if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
		searchDebounceTimer = setTimeout(() => {
			debouncedQuery = query.trim();
			resetAndReload();
		}, 300);
	};

	const onSortChange = (next: 'newest' | 'oldest' | 'name') => {
		if (sort === next) return;
		sort = next;
		resetAndReload();
	};

	const handleSortSelectorChange = (e: CustomEvent<{ value: string }>) => {
		const v = e.detail.value;
		if (v === 'newest' || v === 'oldest' || v === 'name') {
			onSortChange(v);
		}
	};

	$: sortItems = [
		{ value: 'newest', label: $i18n.t('Newest') },
		{ value: 'oldest', label: $i18n.t('Oldest') },
		{ value: 'name', label: $i18n.t('Name') }
	];

	const onFileListScroll = () => {
		if (!fileListScroll || !hasMore || isLoadingFiles) return;
		const { scrollTop, scrollHeight, clientHeight } = fileListScroll;
		// 바닥에서 150px 이내면 다음 페이지 로드
		if (scrollHeight - (scrollTop + clientHeight) < 150) {
			loadMoreFiles();
		}
	};

	// knowledge가 처음 로드될 때만 파생 상태 초기화
	// $: reactive 블록 대신 명시적 함수 사용 — knowledge.files 등 프로퍼티 변경 시 filterSchema가 초기화되는 버그 방지
	function syncFromKnowledge(k: typeof knowledge) {
		filterSchema = JSON.parse(JSON.stringify(k?.meta?.filter_schema ?? []));
		fileMetadataValues = JSON.parse(JSON.stringify(k?.data?.file_metadata ?? {}));
		toolDescription = k?.meta?.tool_description ?? '';
		filterExtractionMode = k?.meta?.filter_extraction_mode ?? 'manual';
		searchSettings = k?.meta?.search_settings ?? null;
		if (k?.meta?.filter_extraction_model) {
			aiModelId = k.meta.filter_extraction_model;
		}
	}

	$: canAddMoreFilters = (() => {
		const enumCount = filterSchema.filter((f) => f.type === 'enum' || f.type === 'string').length;
		const intCount = filterSchema.filter((f) => f.type === 'int').length;
		const dateCount = filterSchema.filter((f) => f.type === 'date').length;
		const colCount = filterSchema.filter((f) => f.type === 'collection' || f.type === 'glossary').length;
		return enumCount < 4 || intCount < 2 || dateCount < 2 || colCount < 4;
	})();

	function assignSlot(type: string): string {
		const prefixMap: Record<string, string> = {
			enum: 'f_str_',
			string: 'f_str_',
			int: 'f_int_',
			date: 'f_date_',
			collection: 'f_col_',
			glossary: 'f_col_'
		};
		const maxMap: Record<string, number> = { enum: 4, string: 4, int: 2, date: 2, collection: 4, glossary: 4 };
		const prefix = prefixMap[type] ?? 'f_str_';
		const max = maxMap[type] ?? 4;
		const usedSlots = new Set(filterSchema.filter((f) => f.slot.startsWith(prefix)).map((f) => f.slot));
		for (let i = 1; i <= max; i++) {
			const slot = `${prefix}${i}`;
			if (!usedSlots.has(slot)) return slot;
		}
		return '';
	}

	// 마스터-디테일 패턴: 좌측 리스트에서 선택된 필터 인덱스
	let selectedFilterIdx: number | null = null;
	const selectFilter = (idx: number) => {
		selectedFilterIdx = idx;
	};
	$: if (
		showFilterSettings &&
		filterSchema.length > 0 &&
		(selectedFilterIdx === null || selectedFilterIdx >= filterSchema.length)
	) {
		selectedFilterIdx = 0;
	}
	$: if (showFilterSettings && filterSchema.length === 0) {
		selectedFilterIdx = null;
	}

	// 카드 헤더에 노출할 type 라벨 — 백엔드 enum 값은 유지하면서 사용자에게 의미를 전달.
	function filterTypeLabel(type: string): string {
		switch (type) {
			case 'enum':
				return $i18n.t('Single Select');
			case 'collection':
				return $i18n.t('Multi Select');
			case 'glossary':
				return $i18n.t('Glossary');
			case 'date':
				return $i18n.t('Date');
			case 'int':
				return $i18n.t('Number');
			default:
				return type;
		}
	}

	function filterTypeHelp(type: string): string {
		switch (type) {
			case 'enum':
				return $i18n.t('Single-select: pick one value per document');
			case 'collection':
				return $i18n.t('Multi-select: pick zero or more values');
			default:
				return '';
		}
	}

	function addFilterField() {
		const enumCount = filterSchema.filter((f) => f.type === 'enum' || f.type === 'string').length;
		const intCount = filterSchema.filter((f) => f.type === 'int').length;
		const dateCount = filterSchema.filter((f) => f.type === 'date').length;
		const colCount = filterSchema.filter((f) => f.type === 'collection' || f.type === 'glossary').length;
		const type = enumCount < 4 ? 'enum' : colCount < 4 ? 'collection' : intCount < 2 ? 'int' : 'date';
		const slot = assignSlot(type);
		filterSchema = [...filterSchema, { label: '', type, slot, options: [], required: false }];
		// 신규 추가는 우측 상세에 자동 포커스
		selectedFilterIdx = filterSchema.length - 1;
		filterSchemaChangeHandler();
	}

	function removeFilterField(idx: number) {
		filterSchema = filterSchema.filter((_, i) => i !== idx);
		// 선택된 인덱스 시프트
		if (selectedFilterIdx !== null) {
			if (filterSchema.length === 0) {
				selectedFilterIdx = null;
			} else if (selectedFilterIdx === idx) {
				selectedFilterIdx = Math.min(idx, filterSchema.length - 1);
			} else if (selectedFilterIdx > idx) {
				selectedFilterIdx = selectedFilterIdx - 1;
			}
		}
		filterSchemaChangeHandler();
	}

	const filterSchemaChangeHandler = () => {
		settingsDirty = true;
	};

	const toolDescriptionChangeHandler = () => {
		settingsDirty = true;
	};

	async function aiGenerateFilterDescription(idx: number) {
		if (!knowledge || generatingFilterIdx === idx) return;
		const field = filterSchema[idx];
		if (!field?.label?.trim()) return;
		const modelId = aiModelId || $models.find((m) => !m?.preset && !(m?.arena ?? false))?.id || '';
		if (!modelId) {
			toast.error($i18n.t('Please select an AI model first.'));
			return;
		}
		generatingFilterIdx = idx;
		try {
			const typeKr: Record<string, string> = { enum: '선택값', string: '선택값', date: '날짜', int: '숫자', collection: '다중값', glossary: '용어집' };
			const optionsHint =
				(field.type === 'enum' || field.type === 'string' || field.type === 'collection') && (field.options ?? []).length > 0
					? ` (선택 가능한 값: ${(field.options ?? []).join(', ')})`
					: '';
			const prompt = `지식기반 이름: ${knowledge.name}
필터 항목: ${field.label} (유형: ${typeKr[field.type] ?? field.type}${optionsHint})

위 필터 항목에 대한 AI 에이전트용 설명을 한국어로 1~2문장으로 작성해주세요.
이 필터가 무엇을 의미하는지, 어떤 값을 선택해야 하는지 설명하세요.
설명만 출력하고 다른 텍스트는 포함하지 마세요.`;
			const result = await generateText(localStorage.token, prompt, modelId);
			if (result) {
				filterSchema[idx] = { ...filterSchema[idx], description: result.trim() };
				filterSchema = filterSchema;
				filterSchemaChangeHandler();
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || String(e));
		} finally {
			generatingFilterIdx = null;
		}
	}

	async function aiGenerateToolDescription() {
		if (!knowledge || generatingToolDesc) return;
		const modelId = aiModelId || $models.find((m) => !m?.preset && !(m?.arena ?? false))?.id || '';
		if (!modelId) {
			toast.error($i18n.t('Please select an AI model first.'));
			return;
		}
		generatingToolDesc = true;
		try {
			const filterInfo =
				filterSchema.length > 0
					? '\n사용 가능한 필터: ' +
						filterSchema
							.map((f) => {
								const typeKr: Record<string, string> = { enum: '선택값', string: '문자열', date: '날짜', int: '숫자' };
								let info = `${f.label}(${typeKr[f.type] ?? f.type})`;
								if ((f.type === 'enum' || f.type === 'string') && (f.options ?? []).length > 0) {
									info += ` [${(f.options ?? []).join('|')}]`;
								}
								return info;
							})
							.join(', ')
					: '';
			const prompt = `지식기반 이름: ${knowledge.name}
설명: ${knowledge.description || '없음'}
파일 목록: ${loadedFiles.slice(0, 30).map((f) => f.meta?.name ?? f.name ?? '').filter(Boolean).join(', ')}${filterInfo}

위 지식기반을 AI 에이전트가 언제 사용해야 하는지 설명하는 1~3문장을 한국어로 작성해주세요.
${filterInfo ? '필터 사용 규칙도 반드시 포함하세요: 필터는 질문에서 높은 확신으로 특정할 수 있을 때만 사용하고, 애매하면 필터 없이 검색하라.' : ''}
설명만 출력하고 다른 텍스트는 포함하지 마세요.`;
			const result = await generateText(localStorage.token, prompt, modelId);
			if (result) {
				toolDescription = result.trim();
				toolDescriptionChangeHandler();
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || String(e));
		} finally {
			generatingToolDesc = false;
		}
	}

	function toggleFileMeta(fileId: string) {
		if (!fileMetadataValues[fileId]) {
			fileMetadataValues[fileId] = {};
		}
		selectedMetaFileId = selectedMetaFileId === fileId ? null : fileId;
	}

	function buildEnumItems(options: string[] | undefined) {
		const opts = options ?? [];
		return [
			{ value: '', label: '—' },
			...opts.map((opt) => ({ value: opt, label: opt }))
		];
	}

	function handleFilterTypeChange(idx: number, nextType: string) {
		filterSchema[idx].type = nextType;
		filterSchema[idx].slot = assignSlot(nextType);
		if (nextType === 'glossary') {
			filterSchema[idx].options = [];
			filterSchema[idx].extraction_prompt = '';
		} else if (nextType !== 'enum' && nextType !== 'collection') {
			filterSchema[idx].options = [];
		}
		if (nextType !== 'glossary') {
			delete filterSchema[idx].glossary_id;
			delete filterSchema[idx].glossary_name;
			delete filterSchema[idx].category;
		}
		filterSchema = filterSchema;
		filterSchemaChangeHandler();
	}

	// 글로서리 sub-section 아코디언 상태 (현재 선택된 필터에 한정 — 글로벌 1개)
	let glossarySectionsOpen: { source: boolean; ai: boolean } = { source: true, ai: true };
	function toggleGlossarySection(key: 'source' | 'ai') {
		glossarySectionsOpen = { ...glossarySectionsOpen, [key]: !glossarySectionsOpen[key] };
	}

	$: MODE_OPTIONS = [
		{ value: 'manual', label: $i18n.t('Manual') },
		{ value: 'ai', label: 'AI' }
	];

	$: CONTENT_RANGE_OPTIONS = [
		{ value: 'full', label: $i18n.t('Full content') },
		{ value: 'partial', label: $i18n.t('Partial content') }
	];

	function handleModeChange(e: CustomEvent<{ value: string }>) {
		const v = e.detail.value;
		if (v === 'manual' || v === 'ai') {
			filterExtractionMode = v;
			filterSchemaChangeHandler();
		}
	}

	function disconnectGlossary(idx: number) {
		filterSchema[idx].glossary_id = undefined;
		filterSchema[idx].glossary_name = undefined;
		filterSchema[idx].label = '';
		filterSchema = filterSchema;
		filterSchemaChangeHandler();
	}

	function connectGlossary(idx: number, item: { id: string; name: string }) {
		filterSchema[idx].glossary_id = item.id;
		filterSchema[idx].glossary_name = item.name;
		if (!filterSchema[idx].label) {
			filterSchema[idx].label = item.name;
		}
		filterSchema = filterSchema;
		filterSchemaChangeHandler();
	}

	function handleFilterOptionsChange(idx: number, e: CustomEvent<Event>) {
		const target = e.detail.currentTarget as HTMLInputElement | null;
		const raw = target?.value ?? '';
		filterSchema[idx].options = raw.split(',').map((s) => s.trim()).filter(Boolean);
		filterSchemaChangeHandler();
	}

	function handleCharsInput(idx: number, key: 'content_prefix_chars' | 'content_suffix_chars', e: CustomEvent<Event>) {
		const target = e.detail.currentTarget as HTMLInputElement | null;
		const v = parseInt(target?.value ?? '') || 0;
		(filterSchema[idx] as any)[key] = v > 0 ? v : undefined;
		filterSchema = filterSchema;
		filterSchemaChangeHandler();
	}

	function handleContentRangeChange(idx: number, e: CustomEvent<{ value: string }>) {
		const v = e.detail.value;
		if (v === 'full' || v === 'partial') {
			filterSchema[idx].content_range = v;
			if (v === 'partial' && !filterSchema[idx].content_prefix_chars && !filterSchema[idx].content_suffix_chars) {
				filterSchema[idx].content_prefix_chars = 3000;
			}
			filterSchema = filterSchema;
			filterSchemaChangeHandler();
		}
	}

	$: FILTER_TYPE_ITEMS = [
		{ value: 'enum', label: $i18n.t('Single Select') },
		{ value: 'collection', label: $i18n.t('Multi Select') },
		{ value: 'glossary', label: $i18n.t('Glossary') },
		{ value: 'date', label: $i18n.t('Date') },
		{ value: 'int', label: $i18n.t('Number') }
	];

	const saveFileMetadataHandler = async (fileId: string) => {
		savingMetaFileId = fileId;
		try {
			const metadata = fileMetadataValues[fileId] ?? {};
			const res = await setFileMetadata(localStorage.token, id, fileId, metadata);
			if (res) {
				// knowledge는 메타/데이터 필드만 갱신 (loadedFiles는 건드리지 않음)
				knowledge = { ...(knowledge as Knowledge), data: res.data, meta: res.meta ?? knowledge?.meta } as Knowledge;
				fileMetadataValues = JSON.parse(JSON.stringify(res?.data?.file_metadata ?? {}));
				toast.success($i18n.t('File metadata updated successfully.'));
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			savingMetaFileId = null;
		}
	};

	// ── AI extraction computed state ──────────────────────────────────────────
	$: hasExtractionPrompts =
		(filterExtractionMode === 'ai' && filterSchema.some((f) => f.type !== 'glossary' && f.extraction_prompt?.trim())) ||
		filterSchema.some((f) => f.type === 'glossary' && f.glossary_id);

	const extractFileMetadataHandler = async (fileId: string, silent = false) => {
		const hasLlmFields = filterSchema.some((f) => f.type !== 'glossary' && f.extraction_prompt?.trim()) || filterSchema.some((f) => f.type === 'glossary' && f.use_ai && f.extraction_prompt?.trim());
		const modelId = aiModelId || $models.find(m => !m?.preset && !(m?.arena ?? false))?.id || '';
		if (hasLlmFields && !modelId) {
			if (!silent) toast.error($i18n.t('Please select an AI model first.'));
			return;
		}
		extractingFileIds.add(fileId);
		extractingFileIds = extractingFileIds;
		try {
			// 큐에 등록 → 결과는 Socket.IO extraction:file-complete 이벤트로 수신
			await extractFileMetadata(localStorage.token, id, fileId, modelId);
			if (!silent) toast.info($i18n.t('Extraction started'));
		} catch (e) {
			if (!silent) toast.error($i18n.t('Extraction failed') + `: ${e}`);
			extractingFileIds.delete(fileId);
			extractingFileIds = extractingFileIds;
		}
	};

	// ── 재추출 확인 다이얼로그 상태 ───────────────────────────────────────
	let showReextractDialog = false;
	let reextractPolicy: 'overwrite' | 'skip' = 'overwrite';
	let reextractAlreadyCount = 0;
	let reextractPendingCount = 0;
	let reextractPendingIds: string[] = []; // 미추출 파일 ID
	let reextractAllIds: string[] = []; // 선택된 전체 파일 ID

	/** 파일이 이미 추출된 것으로 볼 수 있는지 — filter_schema 의 slot 중
	 *  하나라도 값이 존재하면 추출됨으로 간주. */
	function isFileExtracted(fileId: string): boolean {
		const meta = fileMetadataValues[fileId];
		if (!meta) return false;
		return filterSchema.some((f) => {
			const slot = f?.slot;
			if (!slot) return false;
			const v = meta[slot];
			if (v === undefined || v === null || v === '') return false;
			if (Array.isArray(v) && v.length === 0) return false;
			return true;
		});
	}

	// 배치 추출 진행률 dedupe — 같은 file_id 가 워커 재시도 / chain 등으로 두 번
	// 통보돼도 카운터를 한 번만 올린다. Extract 시작 시 reset.
	let extractCountedFileIds: Set<string> = new Set();

	const extractSelectedMetadataHandler = async () => {
		if (checkedCount === 0) return;
		const selectedIds = Array.from(checkedFileIds);
		const already = selectedIds.filter((fid) => isFileExtracted(fid));
		const pending = selectedIds.filter((fid) => !isFileExtracted(fid));
		// 이미 추출된 파일이 선택에 포함되어 있으면 처리 방식 확인.
		if (already.length > 0) {
			reextractAllIds = selectedIds;
			reextractPendingIds = pending;
			reextractAlreadyCount = already.length;
			reextractPendingCount = pending.length;
			// 전체가 이미 추출된 경우 "미추출만" 은 동작이 없으므로 덮어쓰기를 기본.
			reextractPolicy = 'overwrite';
			showReextractDialog = true;
			return;
		}
		await _runExtractForIds(selectedIds);
	};

	const confirmReextract = async () => {
		const fileIds =
			reextractPolicy === 'skip' ? reextractPendingIds : reextractAllIds;
		if (fileIds.length === 0) {
			toast.info($i18n.t('No files to extract.'));
			return;
		}
		await _runExtractForIds(fileIds);
	};

	const _runExtractForIds = async (fileIds: string[]) => {
		if (fileIds.length === 0) return;
		const hasLlmFields = filterSchema.some((f) => f.type !== 'glossary' && f.extraction_prompt?.trim()) || filterSchema.some((f) => f.type === 'glossary' && f.use_ai && f.extraction_prompt?.trim());
		const modelId = aiModelId || $models.find(m => !m?.preset && !(m?.arena ?? false))?.id || '';
		if (hasLlmFields && !modelId) {
			toast.error($i18n.t('Please select an AI model first.'));
			return;
		}
		extractingAll = true;
		extractProgress = { completed: 0, total: fileIds.length, success: 0, failed: 0 };
		extractCountedFileIds = new Set();
		try {
			const res = await extractAllMetadata(localStorage.token, id, modelId, fileIds);
			if (res?.status === 'accepted') {
				extractProgress.total = res.total;
				toast.info($i18n.t('Extraction started for {{count}} files', { count: res.total }));
				// 글로벌 알림 센터에 진행률 entry 선점 생성 — 파일별
				// extraction:file-complete 이벤트가 들어올 때마다 current++.
				toastHistory.upsert(`kb-filter-extract:${id}`, {
					type: 'running',
					message: `${knowledge?.name ?? id.slice(0, 8)} · ${$i18n.t('Filter extraction')}`,
					progress: { current: 0, total: res.total, label: null },
					linkTo: `/workspace/knowledge/${id}`,
					persistent: true
				});
			}
		} catch (e) {
			toast.error($i18n.t('Extraction failed') + `: ${e}`);
			extractingAll = false;
		}
	};

	// ── 배치 파일 삭제 (체크된 항목) ────────────────────────────────────────
	let showBatchDeleteDialog = false;
	let batchDeletePendingIds: string[] = [];

	const fileHasMetadata = (fileId: string): boolean => {
		const schema = knowledge?.meta?.filter_schema ?? [];
		if (!schema.length) return false;
		const meta = fileMetadataValues[fileId];
		if (!meta) return false;
		return schema.some((f: any) => {
			const val = meta[f.slot];
			if (Array.isArray(val)) return val.length > 0;
			return val !== undefined && val !== null && val !== '';
		});
	};

	$: selectedWithMetadataCount = Array.from(checkedFileIds).filter(fileHasMetadata).length;
	$: batchDeleteMetaCount = batchDeletePendingIds.filter(fileHasMetadata).length;

	const requestBatchDeleteSelected = () => {
		if (deletingSelected || checkedCount === 0) return;
		batchDeletePendingIds = Array.from(checkedFileIds);
		showBatchDeleteDialog = true;
	};

	const confirmBatchDeleteSelected = async () => {
		const fileIds = batchDeletePendingIds;
		if (fileIds.length === 0) return;
		deletingSelected = true;
		try {
			const res = await batchRemoveFilesFromKnowledgeById(
				localStorage.token,
				id,
				fileIds
			);
			if (res?.status === 'accepted') {
				activeDeleteJobId = res.job_id;
				deleteJobTotal = res.total;
				toast.info(
					$i18n.t('Deleting {{count}} files...', { count: res.total })
				);
				// ToastHistory 에 진행률 entry 선점 (파일별 progress 이벤트가
				// current 를 증가시킴).
				toastHistory.upsert(`kb-delete:${id}:${res.job_id}`, {
					type: 'running',
					message: `${knowledge?.name ?? id.slice(0, 8)} · ${$i18n.t('Deleting files')}`,
					progress: { current: 0, total: res.total, label: null },
					linkTo: `/workspace/knowledge/${id}`,
					persistent: true
				});
				// 삭제된 파일은 선택 해제
				checkedFileIds = new Set();
			}
		} catch (e) {
			toast.error($i18n.t('Delete failed') + `: ${e}`);
			deletingSelected = false;
		} finally {
			batchDeletePendingIds = [];
		}
	};

	// ── 배치 메타데이터 비우기 (체크된 항목) ───────────────────────────────────
	// 파일/chunk/embedding 은 보존, filter slot (f_*) 만 삭제하는 경량 액션.
	// "문서 삭제" 와 시각적/기능적으로 명확히 분리한다.
	let showBatchClearMetadataDialog = false;
	let batchClearMetadataPendingIds: string[] = [];
	let clearingMetadata = false;

	const requestBatchClearMetadataSelected = () => {
		if (clearingMetadata || checkedCount === 0) return;
		batchClearMetadataPendingIds = Array.from(checkedFileIds);
		showBatchClearMetadataDialog = true;
	};

	const confirmBatchClearMetadataSelected = async () => {
		const fileIds = batchClearMetadataPendingIds;
		if (fileIds.length === 0) return;
		clearingMetadata = true;
		try {
			const res = await batchClearFilterMetadataByKnowledgeById(
				localStorage.token,
				id,
				fileIds
			);
			if (res) {
				toast.success(
					$i18n.t('Cleared filter metadata for {{count}} files', {
						count: res.cleared
					})
				);
				// 비워진 파일들의 로컬 메타 캐시도 슬롯 키만 비움.
				for (const fid of res.files) {
					if (fileMetadataValues[fid]) {
						const next = { ...fileMetadataValues[fid] };
						for (const k of Object.keys(next)) {
							if (
								k.startsWith('f_str_') ||
								k.startsWith('f_int_') ||
								k.startsWith('f_date_') ||
								k.startsWith('f_col_')
							) {
								delete next[k];
							}
						}
						fileMetadataValues[fid] = next;
					}
				}
				fileMetadataValues = fileMetadataValues;
				checkedFileIds = new Set();
				await refreshKnowledge();
			}
		} catch (e) {
			toast.error($i18n.t('Clear metadata failed') + `: ${e}`);
		} finally {
			clearingMetadata = false;
			batchClearMetadataPendingIds = [];
		}
	};

	// Track files that are being processed in background
	let processingFileIds: Set<string> = new Set();

	// ── Batch upload state (디렉토리/다수 파일 일괄 처리) ────────────────────
	const BATCH_THRESHOLD = 5;
	const BATCH_CONCURRENCY = 3;
	const BATCH_POLL_INTERVAL_MS = 4000;
	const BATCH_POLL_MAX_MS = 30 * 60 * 1000; // 30분 상한
	const BATCH_STATE_TTL_MS = 60 * 60 * 1000; // localStorage 1h TTL
	let batchMode = false;
	// 재시도 배치 여부 — 재시도는 파일이 이미 서버에 있어 처리(fire-and-forget)가
	// 네비게이션과 무관하게 계속된다. 따라서 업로드 배치용 이탈 가드(beforeNavigate /
	// onBeforeUnload)를 retry 에는 적용하지 않는다.
	let retryMode = false;
	// 현재 배치의 고유 id — 백엔드 file-processing 알림에 echo 되어 (a) 알림센터(벨)
	// 진행률 엔트리 키, (b) 발신 세션 식별, (c) layout 토스트 결정론적 억제에 쓰인다.
	let currentBatchId = '';
	let batchFileIds: Set<string> = new Set();
	// 폴링 fallback 에서 이미 counter 에 반영한 id (중복 집계 방지)
	let batchAccountedIds: Set<string> = new Set();
	// 실패 파일 이름 누적 (완료 토스트에서 상위 몇 개 노출)
	let batchFailedNames: string[] = [];
	let batchPollTimer: any = null;
	let batchPollStartedAt = 0;
	// 단일 파일(비배치) 처리 안전망 폴러 상태 — socket 이벤트 유실/미발송/백엔드
	// 재시작으로 인한 무한 스피너를 방지하고, 서버측 stale 복구(>600s)를 자동 반영한다.
	let singleFilePollTimer: any = null;
	let singleFilePollStartedAt = 0;
	let singleFilePollGaveUp = false;
	const SINGLE_FILE_POLL_INTERVAL_MS = 5000;
	const SINGLE_FILE_POLL_MAX_MS = 30 * 60 * 1000; // 30분 상한 (배치와 동일)
	// 단건/타 세션 업로드 완료 알림이 몰릴 때 목록 reload 를 합쳐 1회만 수행 (reload 폭주 방지)
	let debouncedRefreshTimer: any = null;
	// finalizeBatch 직후 도착하는 잔여(straggler) 알림이 추가 refresh 를 또 거는 것을 막는 윈도우.
	// finalize 가 이미 1회 refresh 하므로 이 시간 동안의 straggler refresh 는 건너뛴다.
	let suppressStragglerRefreshUntil = 0;
	// KB 내 처리 실패 파일 수 — 툴바의 "실패 N건 재시도" 버튼 노출/카운트에 사용
	let failedCount = 0;
	let retryingFailed = false;
	let batchProgress = {
		total: 0,
		uploaded: 0,
		uploadFailed: 0,
		processCompleted: 0,
		processFailed: 0,
		processSkipped: 0
	};
	// 현재 배치에 적용 중인 중복 처리 정책
	let batchDuplicatePolicy: DuplicatePolicy = 'overwrite';

	// ── 중복 파일 확인 모달 상태 ────────────────────────────────
	// ConfirmDialog 포맷을 사용하되 Promise 기반 API로 래핑한다.
	// 해결 경로:
	//   1) 사용자가 Continue 클릭 → ConfirmDialog.onConfirm prop 이 sync 로 실행됨 →
	//      여기서 resolver 를 nullify + policy 로 resolve
	//   2) 사용자가 Cancel/Esc/오버레이 클릭 → show = false 만 내려오고 dispatch 가
	//      오거나 오지 않거나 함. 이 케이스는 reactive 블록에서 resolver 가 아직
	//      남아 있으면 null 로 resolve (orphan promise 방지)
	let showDuplicateDialog = false;
	let duplicateDialogFilenames: string[] = [];
	let duplicateDialogPolicy: DuplicatePolicy = 'overwrite';
	let duplicateDialogResolve: ((v: DuplicatePolicy | null) => void) | null = null;
	let prevShowDuplicateDialog = false;

	const openDuplicateDialog = (filenames: string[]): Promise<DuplicatePolicy | null> => {
		duplicateDialogFilenames = filenames;
		duplicateDialogPolicy = 'overwrite';
		showDuplicateDialog = true;
		return new Promise((resolve) => {
			duplicateDialogResolve = resolve;
		});
	};

	// ConfirmDialog.onConfirm prop — sync 로 호출되어 reactive flush 이전에
	// resolver 를 정리할 수 있다. await 기반 event 콜백(on:confirm) 은 microtask
	// 경계를 넘어 race 가 생기므로 prop 쪽이 안전.
	const handleDuplicateConfirm = () => {
		const r = duplicateDialogResolve;
		duplicateDialogResolve = null;
		r?.(duplicateDialogPolicy);
	};

	// show 의 true→false 전이를 감지해 orphan promise 방지.
	// - confirm 경로: handleDuplicateConfirm 에서 이미 resolver 를 null 로 만들어서 여기선 no-op
	// - cancel/esc/overlay 경로: resolver 가 아직 남아있으므로 null 로 resolve
	$: {
		if (prevShowDuplicateDialog && !showDuplicateDialog && duplicateDialogResolve) {
			const r = duplicateDialogResolve;
			duplicateDialogResolve = null;
			r(null);
		}
		prevShowDuplicateDialog = showDuplicateDialog;
	}

	const batchStateKey = () => `cloo.kbBatchState.${id ?? $page.params.id ?? ''}`;

	const persistBatchState = () => {
		if (typeof window === 'undefined') return;
		try {
			const key = batchStateKey();
			if (!batchMode) {
				window.localStorage.removeItem(key);
				return;
			}
			window.localStorage.setItem(
				key,
				JSON.stringify({
					active: true,
					batchId: currentBatchId,
					retry: retryMode,
					startedAt: batchPollStartedAt || Date.now(),
					progress: batchProgress,
					fileIds: [...batchFileIds],
					accountedIds: [...batchAccountedIds],
					failedNames: batchFailedNames,
					ts: Date.now()
				})
			);
		} catch {
			// quota/private 모드 무시
		}
	};

	const loadPersistedBatchState = async () => {
		if (typeof window === 'undefined') return;
		try {
			const raw = window.localStorage.getItem(batchStateKey());
			if (!raw) return;
			const parsed = JSON.parse(raw);
			if (!parsed || !parsed.active || typeof parsed.ts !== 'number') return;
			if (Date.now() - parsed.ts > BATCH_STATE_TTL_MS) {
				window.localStorage.removeItem(batchStateKey());
				return;
			}
			const recoveredIds: string[] = Array.isArray(parsed.fileIds) ? parsed.fileIds : [];
			if (recoveredIds.length === 0) {
				window.localStorage.removeItem(batchStateKey());
				return;
			}
			batchMode = true;
			// 복원 시점 기준: JS 메모리에만 있던 미업로드 파일은 복구 불가.
			// 따라서 이미 서버에 올라간 파일(recoveredIds)만을 배치 범위로 재정의하고
			// 업로드 phase 는 이미 완료된 상태로 간주한다 — 이제 필요한 건 처리(process) 완료 뿐.
			// batchId 는 원래 백엔드로 보낸 값을 그대로 복원해야 알림(batch_id)과 매칭된다.
			currentBatchId = parsed.batchId || uuidv4();
			// 재시도 배치였다면 복원 후에도 이탈 가드 비적용 유지.
			retryMode = parsed.retry ?? false;
			batchProgress = {
				total: recoveredIds.length,
				uploaded: recoveredIds.length,
				uploadFailed: 0,
				processCompleted: Math.min(parsed.progress?.processCompleted ?? 0, recoveredIds.length),
				processFailed: Math.min(parsed.progress?.processFailed ?? 0, recoveredIds.length),
				processSkipped: Math.min(parsed.progress?.processSkipped ?? 0, recoveredIds.length)
			};
			batchFileIds = new Set(recoveredIds);
			batchAccountedIds = new Set(parsed.accountedIds ?? []);
			batchFailedNames = Array.isArray(parsed.failedNames) ? [...parsed.failedNames] : [];
			batchPollStartedAt = parsed.startedAt ?? Date.now();
			persistBatchState();

			// 새로고침으로 사라진 알림센터(벨) 진행률 엔트리를 재생성 — 같은 batchId 키 사용
			const _doneSoFar =
				batchProgress.processCompleted +
				batchProgress.processFailed +
				batchProgress.processSkipped;
			toastHistory.upsert(`kb-upload:${currentBatchId}`, {
				type: 'running',
				message: `${knowledge?.name ?? id.slice(0, 8)} · ${$i18n.t('Uploading files')}`,
				progress: { current: _doneSoFar, total: recoveredIds.length, label: null },
				linkTo: `/workspace/knowledge/${id}`,
				persistent: true
			});

			// 즉시 한 번 reconcile — 이미 서버에서 처리 완료됐을 수 있음
			await reconcileBatchFromServer();
			maybeFinishBatch();
			if (batchMode) {
				scheduleBatchPoll();
			}
		} catch (e) {
			console.error('batch restore error:', e);
		}
	};


	const resetBatchProgress = () => {
		batchProgress = {
			total: 0,
			uploaded: 0,
			uploadFailed: 0,
			processCompleted: 0,
			processFailed: 0,
			processSkipped: 0
		};
	};

	// 새로고침 / 탭 닫기 시 브라우저 네이티브 경고. 메시지 커스터마이즈는 최신 브라우저에서 막혀있어
	// 일반 "변경사항이 저장되지 않을 수 있습니다" 계열 문구가 표시된다.
	const onBeforeUnload = (e: BeforeUnloadEvent) => {
		// 업로드 배치만 가드 — 재시도는 서버 측에서 계속되므로 이탈 경고 불필요.
		if (batchMode && !retryMode) {
			e.preventDefault();
			e.returnValue = '';
			return '';
		}
	};

	// SvelteKit 클라이언트 네비게이션(링크 클릭, goto 등) 가드
	// 네이티브 confirm 대신 커스텀 ConfirmDialog 사용
	let showNavGuardDialog = false;
	let navGuardTargetUrl: string | null = null;

	const handleNavGuardConfirm = () => {
		// 사용자가 Continue 클릭 — 배치 중단 후 목적지로 이동
		const url = navGuardTargetUrl;
		navGuardTargetUrl = null;
		batchMode = false;
		if (url) {
			goto(url);
		}
	};

	beforeNavigate((nav) => {
		// 업로드 배치만 이탈 가드 — 재시도는 서버 fire-and-forget 이라 막을 필요 없음.
		if (!batchMode || retryMode) return;
		// 새로고침이나 탭 닫기(unload)는 onBeforeUnload 에서 이미 처리되므로 스킵
		if (nav.type === 'leave') return;
		nav.cancel();
		navGuardTargetUrl = nav.to?.url?.pathname ?? null;
		showNavGuardDialog = true;
	});

	const stopBatchPolling = () => {
		if (batchPollTimer) {
			clearTimeout(batchPollTimer);
			batchPollTimer = null;
		}
	};

	// 단건/타 세션 업로드 완료 시 목록을 서버 상태로 맞춘다. 다수 알림이 몰려도
	// reload 를 1회로 합쳐 "파일 하나당 전체 재조회·재정렬" 폭주를 막는다.
	const scheduleDebouncedRefresh = () => {
		if (debouncedRefreshTimer) clearTimeout(debouncedRefreshTimer);
		debouncedRefreshTimer = setTimeout(() => {
			debouncedRefreshTimer = null;
			refreshKnowledge();
		}, 1500);
	};

	// 처리 실패 파일 수 갱신 — 툴바 "실패 N건 재시도" 버튼 노출 판단용.
	const refreshFailedCount = async () => {
		if (!id) return;
		try {
			const res = await getKnowledgeFileIds(localStorage.token, id, { status: 'failed' });
			failedCount = res?.total ?? 0;
		} catch (e) {
			console.error('Failed to load failed-file count:', e);
		}
	};

	// 실패 파일 일괄 재시도 — 업로드와 동일하게 하나의 batch_id 로 묶어 조용히 처리하고
	// 진행상황은 알림센터(벨) 엔트리로만 추적한다.
	const retryAllFailed = async () => {
		if (batchMode || retryingFailed) return;
		retryingFailed = true;
		try {
			// 1) 실패 파일 id 확보 (배치 추적 셋업의 소스)
			const res = await getKnowledgeFileIds(localStorage.token, id, { status: 'failed' });
			const ids = res?.ids ?? [];
			if (ids.length === 0) {
				failedCount = 0;
				toast.info($i18n.t('No failed files to retry.'));
				return;
			}

			// 2) 배치 추적 셋업을 알림 도착 전에 먼저 — 업로드 phase 는 이미 끝났으므로 uploaded=total.
			batchMode = true;
			retryMode = true; // 재시도 배치 → 이탈 가드 비적용 (서버 fire-and-forget)
			currentBatchId = uuidv4();
			resetBatchProgress();
			batchProgress.total = ids.length;
			batchProgress.uploaded = ids.length;
			batchProgress = batchProgress;
			batchFileIds = new Set(ids);
			batchAccountedIds = new Set();
			batchFailedNames = [];
			stopBatchPolling();
			batchPollStartedAt = Date.now();
			persistBatchState();
			failedCount = 0;

			toast.info($i18n.t('Retrying {{count}} failed files', { count: ids.length }));
			toastHistory.upsert(`kb-upload:${currentBatchId}`, {
				type: 'running',
				message: `${knowledge?.name ?? id.slice(0, 8)} · ${$i18n.t('Retrying failed files')}`,
				progress: { current: 0, total: ids.length, label: null, failed: 0 },
				linkTo: `/workspace/knowledge/${id}`,
				persistent: true
			});

			// 3) 백엔드 재처리 큐 등록 (같은 batch_id 로 알림 echo)
			await retryFailedFilesInKnowledge(localStorage.token, id, {
				fileIds: ids,
				batchId: currentBatchId,
				clientSessionId: $socket?.id
			});

			// 4) 소켓 유실 대비 폴링 reconcile
			scheduleBatchPoll();
		} catch (e) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to retry'));
			// 백엔드 큐 등록 실패 → 배치를 시작하지 않은 것으로 되돌린다 (batchMode 고착 방지).
			batchMode = false;
			retryMode = false;
			currentBatchId = '';
			stopBatchPolling();
			resetBatchProgress();
			if (typeof window !== 'undefined') {
				try {
					window.localStorage.removeItem(batchStateKey());
				} catch {
					// ignore
				}
			}
			await refreshFailedCount();
		} finally {
			retryingFailed = false;
		}
	};

	// 업로드 phase 종료 후 socket notification 이 유실된 파일을 KB 파일 목록으로 reconcile.
	// 백엔드 페이지 limit 상한(500)을 준수하며, 미정산 배치 파일이 남아있는 동안만
	// newest 정렬로 앞쪽 페이지를 훑는다.
	const reconcileBatchFromServer = async () => {
		if (!batchMode) return;
		try {
			const pageLimit = 500;
			// 배치 크기를 덮을 만큼만 페이지를 본다 (+여유 1페이지). limit > 500 이면
			// 백엔드가 조용히 50 으로 떨어뜨리므로 절대 초과하지 않는다.
			const maxPages = Math.ceil((batchFileIds.size + 50) / pageLimit) + 1;
			let dirty = false;
			for (let page = 0; page < maxPages; page++) {
				const hasUnaccounted = [...batchFileIds].some((fid) => !batchAccountedIds.has(fid));
				if (!hasUnaccounted) break;
				const res = await getKnowledgeFiles(localStorage.token, id, {
					skip: page * pageLimit,
					limit: pageLimit,
					sort: 'newest'
				});
				const files: any[] = res?.files ?? [];
				if (files.length === 0) break;
				for (const f of files) {
					if (!batchFileIds.has(f.id) || batchAccountedIds.has(f.id)) continue;
					const st = f?.data?.processing_job?.status;
					if (st === 'completed') {
						batchProgress.processCompleted += 1;
						batchAccountedIds.add(f.id);
						dirty = true;
					} else if (st === 'failed') {
						batchProgress.processFailed += 1;
						batchAccountedIds.add(f.id);
						batchFailedNames.push(f.filename || f.meta?.name || f.id);
						dirty = true;
					}
					// pending/processing/상태없음 → 아직 미완료. 성공으로 단정하지 않는다(과집계 방지).
				}
				const total = res?.total ?? 0;
				if ((page + 1) * pageLimit >= total) break;
			}
			if (dirty) {
				batchProgress = batchProgress;
				persistBatchState();
			}
		} catch (e) {
			console.error('batch reconcile error:', e);
		}
	};

	const scheduleBatchPoll = () => {
		stopBatchPolling();
		if (!batchMode) return;
		batchPollTimer = setTimeout(async () => {
			if (!batchMode) return;
			await reconcileBatchFromServer();
			// 완료됐는지 확인 (notification race 와 무관하게 서버 상태 기준)
			maybeFinishBatch();
			if (!batchMode) return; // 위에서 finish 됐으면 중단
			// 상한 시간 초과 시 강제 종료
			if (Date.now() - batchPollStartedAt > BATCH_POLL_MAX_MS) {
				console.warn('[batch] poll timeout — forcing finish');
				forceFinishBatch();
				return;
			}
			scheduleBatchPoll();
		}, BATCH_POLL_INTERVAL_MS);
	};

	// ── 단일 파일(비배치) 처리 안전망 폴러 ──
	// 배치 업로드는 scheduleBatchPoll 가 담당. 단일 파일 추가(addFileHandler)는
	// 원래 socket 이벤트에만 의존했기 때문에, 이벤트가 유실되거나 백엔드/WSL 이
	// 재시작돼 작업이 고아가 되면 행이 영원히 "처리 중" 스피너로 남았다.
	// 주기적으로 서버 상태를 재조회해 completed/failed(서버측 >600s stale 복구 포함)
	// 를 반영하고, 처리 중 파일이 없어지면 스스로 멈춘다.
	const stopSingleFilePolling = () => {
		if (singleFilePollTimer) {
			clearTimeout(singleFilePollTimer);
			singleFilePollTimer = null;
		}
	};

	const reconcileProcessingFromServer = async () => {
		if (processingFileIds.size === 0) return;
		try {
			// getKnowledgeById 는 백엔드의 lazy stale 복구(처리 timeout 초과 → failed)를
			// 트리거하고, 현재 처리 중(pending)인 파일 목록을 돌려준다. 목록 전용
			// getKnowledgeFiles 로는 복구가 트리거되지 않으므로 반드시 이쪽을 호출한다.
			const res = await getKnowledgeById(localStorage.token, id, false);
			if (!res) return;
			const pendingIds = new Set((res.pending_files ?? []).map((f: any) => f.id));
			let changed = false;
			for (const fid of [...processingFileIds]) {
				// 서버 기준 더 이상 pending 이 아니면 종료(완료/실패/stale-failed)된 것
				if (!pendingIds.has(fid)) {
					processingFileIds.delete(fid);
					changed = true;
				}
			}
			if (changed) {
				processingFileIds = processingFileIds;
				await refreshKnowledge(); // 목록/상태 화면 갱신 (failed 행 노출)
			}
		} catch (e) {
			console.error('single-file reconcile error:', e);
		}
	};

	const scheduleSingleFilePoll = () => {
		if (singleFilePollTimer) return; // 이미 예약됨
		singleFilePollTimer = setTimeout(async () => {
			singleFilePollTimer = null;
			if (batchMode || processingFileIds.size === 0) return; // 배치에 위임 / 종료
			if (Date.now() - singleFilePollStartedAt > SINGLE_FILE_POLL_MAX_MS) {
				console.warn('[single-file] poll timeout — giving up');
				singleFilePollGaveUp = true;
				return;
			}
			await reconcileProcessingFromServer();
			if (!batchMode && processingFileIds.size > 0 && !singleFilePollGaveUp) {
				scheduleSingleFilePoll();
			}
		}, SINGLE_FILE_POLL_INTERVAL_MS);
	};

	const ensureSingleFilePolling = () => {
		if (batchMode || singleFilePollGaveUp) return;
		if (processingFileIds.size === 0) return;
		if (singleFilePollTimer) return; // 이미 실행 중
		singleFilePollStartedAt = Date.now();
		scheduleSingleFilePoll();
	};

	const appendFailedNamesToMessage = (base: string): string => {
		if (batchFailedNames.length === 0) return base;
		const seen = new Set<string>();
		const unique = batchFailedNames.filter((n) => {
			if (seen.has(n)) return false;
			seen.add(n);
			return true;
		});
		const display = unique.slice(0, 3);
		const remaining = unique.length - display.length;
		let msg = base + '\n' + display.join(', ');
		if (remaining > 0) {
			msg += ` ${$i18n.t('and {{count}} more', { count: remaining })}`;
		}
		return msg;
	};

	const finalizeBatch = (forced: boolean) => {
		const { total, uploadFailed, processCompleted, processFailed, processSkipped } = batchProgress;
		const succeeded = processCompleted;
		const failed = uploadFailed + processFailed;
		const skipped = processSkipped;
		const missing = Math.max(0, total - succeeded - failed - skipped);

		// 요약 한 줄(KB 이름/실패 파일명 제외) — 벨 메시지와 완료 토스트가 공유한다.
		const entryId = `kb-upload:${currentBatchId}`;
		const baseLabel = knowledge?.name ?? id.slice(0, 8);
		const linkTo = `/workspace/knowledge/${id}`;
		let summaryType: 'success' | 'warning';
		let summaryCore: string;
		if (forced && missing > 0) {
			summaryType = 'warning';
			summaryCore = $i18n.t(
				'{{succeeded}} succeeded, {{failed}} failed, {{skipped}} skipped, {{missing}} unknown',
				{ succeeded, failed, skipped, missing }
			);
		} else if (failed === 0 && skipped === 0) {
			summaryType = 'success';
			summaryCore = $i18n.t('{{count}} files added successfully', { count: succeeded });
		} else if (failed === 0) {
			summaryType = 'success';
			summaryCore = $i18n.t('{{succeeded}} files added, {{skipped}} skipped (duplicates)', {
				succeeded,
				skipped
			});
		} else {
			summaryType = 'warning';
			summaryCore = $i18n.t('{{succeeded}} succeeded, {{failed}} failed, {{skipped}} skipped', {
				succeeded,
				failed,
				skipped
			});
		}

		// 알림센터(벨): KB 이름 + 요약 + (실패 시) 실패 파일명 — 지속 노출, 클릭 시 KB 이동.
		toastHistory.upsert(entryId, {
			type: summaryType,
			message: appendFailedNamesToMessage(`${baseLabel} · ${summaryCore}`),
			progress: null,
			linkTo,
			// 실패/미상 포함 시 사용자가 확인하도록 유지, 전부 성공이면 일반 항목
			persistent: summaryType === 'warning'
		});

		// 완료 팝업 토스트 1회 (발신 세션 한정 — finalizeBatch 는 업로드 시작 탭에서만 실행되므로
		// 크로스세션 스팸 없음) + "보기" 버튼으로 해당 지식기반으로 이동.
		const viewAction = { label: $i18n.t('View'), onClick: () => goto(linkTo) };
		if (summaryType === 'warning') {
			toast.warning(summaryCore, { action: viewAction });
		} else {
			toast.success(summaryCore, { action: viewAction });
		}

		batchFileIds = new Set();
		batchAccountedIds = new Set();
		batchFailedNames = [];
		batchMode = false;
		retryMode = false;
		currentBatchId = '';
		stopBatchPolling();
		resetBatchProgress();
		// localStorage 에서 배치 상태 제거
		if (typeof window !== 'undefined') {
			try {
				window.localStorage.removeItem(batchStateKey());
			} catch {
				// ignore
			}
		}

		// 배치가 모두 끝난 후 한 번만 실제 서버 상태로 동기화. finalize 직후 도착하는
		// straggler 알림이 또 refresh 를 거는 것을 막아 refresh 를 1회로 유지한다.
		suppressStragglerRefreshUntil = Date.now() + 3000;
		refreshKnowledge();
	};

	const maybeFinishBatch = () => {
		if (!batchMode) return;
		const { total, uploadFailed, processCompleted, processFailed } = batchProgress;
		const done = uploadFailed + processCompleted + processFailed;
		if (done < total) return;
		finalizeBatch(false);
	};

	const forceFinishBatch = () => {
		if (!batchMode) return;
		finalizeBatch(true);
	};

	// 배치 업로드는 KB 창에 라이브 행/배너를 그리지 않는다. 진행상황은 알림센터(벨)
	// 엔트리에서만 보여주고, 목록은 finalizeBatch 에서 1회만 새로고침한다 (KG sync 패턴).
	const uploadOneForBatch = async (file: File, policy: DuplicatePolicy) => {
		if (file.size === 0) {
			batchProgress.uploadFailed += 1;
			batchProgress = batchProgress;
			batchFailedNames.push(file.name);
			return;
		}
		if (
			($config?.file?.max_size ?? null) !== null &&
			file.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			batchProgress.uploadFailed += 1;
			batchProgress = batchProgress;
			batchFailedNames.push(file.name);
			return;
		}

		try {
			const uploaded = await uploadFile(localStorage.token, file, 'local', false, 'knowledge').catch(
				() => null
			);
			if (!uploaded) {
				batchProgress.uploadFailed += 1;
				batchProgress = batchProgress;
				batchFailedNames.push(file.name);
				return;
			}

			batchProgress.uploaded += 1;
			batchProgress = batchProgress;
			batchFileIds.add(uploaded.id);

			// batch_id / client_session_id 는 백엔드가 file-processing 알림에 echo 한다 →
			// 모든 세션이 결정론적으로 토스트를 억제하고 진행률을 벨에만 집계.
			const result = await addFileToKnowledgeById(localStorage.token, id, uploaded.id, {
				duplicatePolicy: policy,
				batchId: currentBatchId,
				clientSessionId: $socket?.id
			}).catch(() => null);
			if (!result) {
				batchProgress.uploadFailed += 1;
				batchProgress = batchProgress;
				batchFailedNames.push(file.name);
				batchFileIds.delete(uploaded.id);
				return;
			}

			// 서버 사이드 skip: filename 이 이미 있었고 policy="skip" 인 경우
			if (result.status === 'skipped') {
				batchProgress.processSkipped += 1;
				batchProgress = batchProgress;
				batchAccountedIds.add(uploaded.id);
				batchFileIds.delete(uploaded.id);
				return;
			}

			if (result.status === 'processing' || result.status === 'processing_started') {
				processingFileIds.add(uploaded.id);
				processingFileIds = processingFileIds;
				// 완료 카운트는 socket notification / reconcile 에서 집계
			} else {
				// 동기 처리 성공 — 즉시 집계 (sync 경로는 알림이 오지 않음)
				if (!batchAccountedIds.has(uploaded.id)) {
					batchProgress.processCompleted += 1;
					batchProgress = batchProgress;
					batchAccountedIds.add(uploaded.id);
				}
				batchFileIds.delete(uploaded.id);
			}
		} catch (e) {
			console.error('batch upload error:', e);
			batchProgress.uploadFailed += 1;
			batchProgress = batchProgress;
		}
	};

	// 디렉토리 업로드 진입점 — File System Access API 우선, 미지원 시 input 폴백.
	// 템플릿에서 type assertion 을 피하려고 script 쪽으로 분리.
	const handleDirectoryUpload = async () => {
		const el = document.getElementById('directory-input') as HTMLInputElement | null;
		const files = await pickDirectoryFiles(el);
		if (files.length === 0) {
			// 사용자 취소 또는 빈 폴더 — 아무것도 안 함
			return;
		}
		await batchUploadFiles(files);
	};

	// ── 업로드 확인 모달 상태 ────────────────────────────────────────
	let showUploadConfirmDialog = false;
	let uploadConfirmFileCount = 0;
	let uploadConfirmResolve: ((ok: boolean) => void) | null = null;
	let prevShowUploadConfirmDialog = false;

	const openUploadConfirmDialog = (count: number): Promise<boolean> => {
		uploadConfirmFileCount = count;
		showUploadConfirmDialog = true;
		return new Promise((resolve) => {
			uploadConfirmResolve = resolve;
		});
	};

	const handleUploadConfirm = () => {
		const r = uploadConfirmResolve;
		uploadConfirmResolve = null;
		r?.(true);
	};

	// cancel/esc/overlay 경로 — orphan promise 방지
	$: {
		if (prevShowUploadConfirmDialog && !showUploadConfirmDialog && uploadConfirmResolve) {
			const r = uploadConfirmResolve;
			uploadConfirmResolve = null;
			r(false);
		}
		prevShowUploadConfirmDialog = showUploadConfirmDialog;
	}

	const batchUploadFiles = async (files: File[]) => {
		if (!files || files.length === 0) return;

		// ── 업로드 확인 ────────────────────────────────────────────────
		const confirmed = await openUploadConfirmDialog(files.length);
		if (!confirmed) return;

		// ── 선제 중복 스캔 ─────────────────────────────────────────────
		// 동일 filename 이 KB에 이미 있는 경우 사용자에게 처리 방식 (덮어쓰기/건너뛰기)
		// 을 먼저 물어본다. skip 선택 시 업로드 자체를 스킵해 트래픽/처리시간 절약.
		let policy: DuplicatePolicy = 'overwrite';
		let effectiveFiles = files;
		try {
			const dupFilenames = await checkKnowledgeDuplicateFilenames(
				localStorage.token,
				id,
				files.map((f) => f.name)
			);
			if (dupFilenames.length > 0) {
				const choice = await openDuplicateDialog(dupFilenames);
				if (choice === null) {
					// 취소 — 배치 시작하지 않음
					return;
				}
				policy = choice;
				if (policy === 'skip') {
					const dupSet = new Set(dupFilenames);
					effectiveFiles = files.filter((f) => !dupSet.has(f.name));
					const skippedCount = files.length - effectiveFiles.length;
					if (effectiveFiles.length === 0) {
						toast.info(
							$i18n.t('All {{count}} files already exist, nothing to upload', {
								count: skippedCount
							})
						);
						return;
					}
					if (skippedCount > 0) {
						toast.info(
							$i18n.t('{{count}} duplicate files will be skipped', { count: skippedCount })
						);
					}
				}
			}
		} catch (e) {
			// 선제 스캔 실패는 치명적이지 않음 — 서버 정책이 safety net
			console.warn('duplicate pre-scan failed, proceeding:', e);
		}

		batchMode = true;
		currentBatchId = uuidv4();
		batchDuplicatePolicy = policy;
		resetBatchProgress();
		batchProgress.total = effectiveFiles.length;
		batchProgress = batchProgress;
		batchFileIds = new Set();
		batchAccountedIds = new Set();
		batchFailedNames = [];
		stopBatchPolling();
		batchPollStartedAt = Date.now();
		persistBatchState();

		// 시작 안내: "N개 처리 시작" 토스트 1회만 (발신 탭 한정, 작업이 시작됐다는 확인용).
		// 이후 진행상황/완료/실패는 토스트 없이 아래 벨 엔트리로만 노출한다.
		toast.info(
			$i18n.t('{{count}} files are being processed. They will be added automatically when ready.', {
				count: effectiveFiles.length
			})
		);

		// 진행상황은 토스트 없이 알림센터(벨) 엔트리에서만 노출한다 (KG sync 패턴). KB 창에는
		// 배너/라이브 행을 그리지 않는다. file-processing 알림이 파일별로 올 때마다 current++.
		toastHistory.upsert(`kb-upload:${currentBatchId}`, {
			type: 'running',
			message: `${knowledge?.name ?? id.slice(0, 8)} · ${$i18n.t('Uploading files')}`,
			progress: { current: 0, total: effectiveFiles.length, label: null },
			linkTo: `/workspace/knowledge/${id}`,
			persistent: true
		});

		let idx = 0;
		const worker = async () => {
			while (idx < effectiveFiles.length) {
				const i = idx++;
				try {
					await uploadOneForBatch(effectiveFiles[i], policy);
				} catch (err) {
					console.error('batch upload error on', effectiveFiles[i]?.name, err);
				}
				persistBatchState();
			}
		};
		const workerCount = Math.min(BATCH_CONCURRENCY, effectiveFiles.length);
		await Promise.all(Array.from({ length: workerCount }, () => worker()));

		persistBatchState();

		// 업로드 단계 완료 후 처리가 전부 동기로 끝났으면 즉시 finish
		maybeFinishBatch();

		// 아직 처리 대기 중인 파일이 있다면 폴링으로 reconcile (socket notification 유실 대비)
		if (batchMode) {
			scheduleBatchPoll();
		}
	};

	const createFileFromText = (name, content) => {
		const blob = new Blob([content], { type: 'text/plain' });
		const file = blobToFile(blob, `${name}.txt`);

		console.log(file);
		return file;
	};

	// 연속 개행을 최대 2개로 제한
	const normalizeLineBreaks = (text: string): string => {
		if (!text) return '';
		return text.replace(/\n{3,}/g, '\n\n');
	};

	const uploadFileHandler = async (file) => {
		console.log(file);

		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name: file.name,
			size: file.size,
			status: 'uploading',
			error: '',
			itemId: tempItemId
		};

		if (fileItem.size == 0) {
			toast.error($i18n.t('You cannot upload an empty file.'));
			return null;
		}

		if (
			($config?.file?.max_size ?? null) !== null &&
			file.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			console.log('File exceeds max size limit:', {
				fileSize: file.size,
				maxSize: ($config?.file?.max_size ?? 0) * 1024 * 1024
			});
			toast.error(
				$i18n.t(`File size should not exceed {{maxSize}} MB.`, {
					maxSize: $config?.file?.max_size
				})
			);
			return;
		}

		loadedFiles = [fileItem, ...loadedFiles];
		totalFiles += 1;

		try {
			const uploadedFile = await uploadFile(localStorage.token, file, 'local', false, 'knowledge').catch((e) => {
				toast.error($i18n.t(`${e}`));
				return null;
			});

			if (uploadedFile) {
				console.log(uploadedFile);
				loadedFiles = loadedFiles.map((item) => {
					if (item.itemId === tempItemId) {
						item.id = uploadedFile.id;
					}
					delete item.itemId;
					return item;
				});
				await addFileHandler(uploadedFile.id);
			} else {
				toast.error($i18n.t('Failed to upload file.'));
				loadedFiles = loadedFiles.filter((f) => f.itemId !== tempItemId);
				totalFiles = Math.max(0, totalFiles - 1);
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const addFileHandler = async (fileId, isRetry = false) => {
		const result = await addFileToKnowledgeById(localStorage.token, id, fileId).catch(
			(e) => {
				toast.error($i18n.t(`${e}`));
				return null;
			}
		);

		if (result) {
			// Check if it's a processing status response
			if (result.status === 'processing' || result.status === 'processing_started') {
				// Keep file in list with processing status
				processingFileIds.add(fileId);
				processingFileIds = processingFileIds; // trigger reactivity
				// 안전망 폴러 시작 (socket 이벤트 유실/백엔드 재시작 대비)
				singleFilePollGaveUp = false;
				ensureSingleFilePolling();

				// Update file status in the list
				loadedFiles = loadedFiles.map((file) =>
					file.id === fileId ? { ...file, status: 'processing' } : file
				);

				if (!isRetry) {
					toast.info(result.message || $i18n.t('File is being processed. It will be added automatically when ready.'));
				}
			} else {
				// Normal success response (KnowledgeFilesResponse)
				processingFileIds.delete(fileId);
				processingFileIds = processingFileIds; // trigger reactivity
				knowledge = { ...(knowledge as Knowledge), data: result.data, meta: result.meta ?? knowledge?.meta } as Knowledge;
				// Replace the temp/processing file entry with the real one from response
				const resolved = (result.files ?? []).find((f: any) => f.id === fileId);
				if (resolved) {
					loadedFiles = loadedFiles.map((f) => (f.id === fileId ? resolved : f));
				}
				if (isRetry) {
					toast.success($i18n.t('File processing completed and added to knowledge base.'));
				} else {
					toast.success($i18n.t('File added successfully.'));
				}

				// 필터 추출은 서버 사이드에서 자동 체이닝 (task_queue._chain_filter_extract)
			}
		} else {
			toast.error($i18n.t('Failed to add file.'));
			processingFileIds.delete(fileId);
			processingFileIds = processingFileIds;
			loadedFiles = loadedFiles.filter((file) => file.id !== fileId);
			totalFiles = Math.max(0, totalFiles - 1);
		}
	};

	const deleteFileHandler = async (fileId) => {
		const isProcessing = processingFileIds.has(fileId);

		// Optimistically remove this file from UI immediately
		if (isProcessing) {
			processingFileIds.delete(fileId);
			processingFileIds = processingFileIds;
		}
		loadedFiles = loadedFiles.filter((file) => file.id !== fileId);
		totalFiles = Math.max(0, totalFiles - 1);

		try {
			console.log('Starting file deletion process for:', fileId);

			const updatedKnowledge = await removeFileFromKnowledgeById(localStorage.token, id, fileId);

			console.log('Knowledge base updated:', updatedKnowledge);

			if (updatedKnowledge) {
				knowledge = { ...(knowledge as Knowledge), data: updatedKnowledge.data, meta: updatedKnowledge.meta ?? knowledge?.meta } as Knowledge;
				toast.success($i18n.t('File removed successfully.'));
			}
		} catch (e) {
			console.error('Error in deleteFileHandler:', e);
			toast.error($i18n.t(`${e}`));
		}
	};

	const updateFileContentHandler = async () => {
		const fileId = selectedFile.id;
		const content = selectedFile.data.content;

		const res = updateFileDataContentById(localStorage.token, fileId, content).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		const updatedKnowledge = await updateFileFromKnowledgeById(
			localStorage.token,
			id,
			fileId
		).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res && updatedKnowledge) {
			knowledge = { ...(knowledge as Knowledge), data: updatedKnowledge.data, meta: updatedKnowledge.meta ?? knowledge?.meta } as Knowledge;
			// 편집된 파일을 loadedFiles 쪽에서도 동기화
			const freshFile = (updatedKnowledge.files ?? []).find((f: any) => f.id === fileId);
			if (freshFile) {
				loadedFiles = loadedFiles.map((f) => (f.id === fileId ? freshFile : f));
				if (selectedFile?.id === fileId) {
					selectedFile = freshFile;
				}
			}
			toast.success($i18n.t('File content updated successfully.'));
		}
	};

	const changeDebounceHandler = () => {
		settingsDirty = true;
	};

	const saveSettingsHandler = async (showToast = true, navigateOnSuccess = false) => {
		if (!knowledge) return;
		if (knowledge.name.trim() === '') {
			toast.error($i18n.t('Please fill in all fields.'));
			return;
		}
		isSavingSettings = true;
		try {
			// 태그 변경사항 커밋
			if (tagSelector?.commitChanges) {
				try {
					await tagSelector.commitChanges();
				} catch (e) {
					console.error('Failed to commit tag changes:', e);
				}
			}
			const res = await updateKnowledgeById(localStorage.token, id, {
				...knowledge,
				name: knowledge.name,
				description: knowledge.description,
				access_control: knowledge.access_control,
				meta: {
					tool_description: toolDescription,
					filter_schema: filterSchema,
					filter_extraction_mode: filterExtractionMode,
					filter_extraction_model: aiModelId,
					search_settings: searchSettings ?? null
				}
			});
			if (res) {
				settingsDirty = false;
				// 저장 성공 — 필터 모달 dirty 비교 기준도 함께 갱신.
				if (showFilterSettings) {
					filterModalSnapshot = _snapshotFilterModal();
				}
				if (showToast) toast.success($i18n.t('Knowledge updated successfully'));
				_knowledge.set(await getKnowledgeBases(localStorage.token));
				if (navigateOnSuccess) {
					goto('/workspace/knowledge');
				}
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			isSavingSettings = false;
		}
	};

	const handleMediaQuery = async (e) => {
		if (e.matches) {
			largeScreen = true;
		} else {
			largeScreen = false;
		}
	};

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		} else {
			dragged = false;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		dragged = false;

		if (e.dataTransfer?.types?.includes('Files')) {
			if (e.dataTransfer?.files) {
				const droppedFiles = Array.from(e.dataTransfer.files) as File[];

				if (droppedFiles.length > 0) {
					if (droppedFiles.length >= BATCH_THRESHOLD) {
						await batchUploadFiles(droppedFiles);
					} else {
						for (const file of droppedFiles) {
							await uploadFileHandler(file);
						}
					}
				} else {
					toast.error($i18n.t(`File not found.`));
				}
			}
		}
	};

	onMount(async () => {
		// listen to resize 1024px
		mediaQuery = window.matchMedia('(min-width: 1024px)');

		mediaQuery.addEventListener('change', handleMediaQuery);
		handleMediaQuery(mediaQuery);

		// Select the container element you want to observe
		const container = document.getElementById('collection-container');

		// initialize the minSize based on the container width
		minSize = !largeScreen ? 100 : Math.floor((300 / container.clientWidth) * 100);

		// Create a new ResizeObserver instance
		const resizeObserver = new ResizeObserver((entries) => {
			for (let entry of entries) {
				const width = entry.contentRect.width;
				// calculate the percentage of 300
				const percentage = (300 / width) * 100;
				// set the minSize to the percentage, must be an integer
				minSize = !largeScreen ? 100 : Math.floor(percentage);

				if (showSidepanel) {
					if (pane && pane.isExpanded() && pane.getSize() < minSize) {
						pane.resize(minSize);
					}
				}
			}
		});

		// Start observing the container's size changes
		resizeObserver.observe(container);

		if (pane) {
			pane.expand();
		}

		id = $page.params.id;

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		const res = await getKnowledgeById(localStorage.token, id, false).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			knowledge = res;
			syncFromKnowledge(res);

			// Load first page of files from paginated endpoint
			await loadMoreFiles();

			// Prepend pending files (processing status) so they surface at top
			if (res.pending_files && res.pending_files.length > 0) {
				const pendingWithStatus = res.pending_files.map((file) => ({
					...file,
					status: 'processing'
				}));
				res.pending_files.forEach((file) => processingFileIds.add(file.id));
				processingFileIds = processingFileIds;
				const loadedIds = new Set(loadedFiles.map((f) => f.id));
				const extra = pendingWithStatus.filter((f) => !loadedIds.has(f.id));
				loadedFiles = [...extra, ...loadedFiles];
			}
		} else {
			goto('/workspace/knowledge');
		}

		const dropZone = document.querySelector('body');
		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);

		// Listen for file processing events via notification
		// Note: Toast is handled in +layout.svelte, here we only refresh data
		if ($socket) {
			// 등록 전에 한 번 off 해서 HMR / 재마운트로 인한 listener 누적 방지
			$socket.off('notification', handleNotification);
			$socket.on('notification', handleNotification);
		}

		// 새로고침/탭 닫기 경고
		window.addEventListener('beforeunload', onBeforeUnload);

		// 새로고침/재진입 시 진행 중인 배치가 있으면 상태 복원 + 폴러 재개 (안전망)
		loadPersistedBatchState();

		// 처리 실패 파일 수 초기 로드 — 툴바 "실패 N건 재시도" 버튼 노출 판단용
		refreshFailedCount();
	});

	let lastProcessedEventId: string | null = null;

	const handleNotification = (notification: { type: string; data: any; timestamp?: number }) => {
		const { type, data, timestamp } = notification;

		// Dedupe check for file-processing events (extraction events skip dedupe)
		const isExtractionEvent = type === 'extraction:progress' || type === 'extraction:complete' || type === 'extraction:file-complete';
		if (!isExtractionEvent) {
			const eventId = `${data?.file_id}-${timestamp}`;
			if (eventId === lastProcessedEventId) {
				return;
			}
			lastProcessedEventId = eventId;
		}

		if (type === 'file-processing-completed') {
			handleFileProcessingCompleted(data);
		} else if (type === 'file-processing-failed') {
			handleFileProcessingFailed(data);
		} else if (type === 'file-delete-batch:progress') {
			if (data?.kb_id === id) {
				// ToastHistory 진행률만 갱신 — 파일별 토스트는 내지 않음.
				const jobId = data.job_id ?? activeDeleteJobId;
				if (jobId) {
					toastHistory.upsert(`kb-delete:${id}:${jobId}`, {
						progress: { current: data.done ?? 0, total: data.total ?? 0, label: null }
					});
				}
			}
		} else if (type === 'file-delete-batch:complete') {
			if (data?.kb_id === id) {
				const jobId = data.job_id ?? activeDeleteJobId;
				deletingSelected = false;
				if (jobId === activeDeleteJobId) {
					activeDeleteJobId = null;
					deleteJobTotal = 0;
				}
				if (jobId) {
					toastHistory.upsert(`kb-delete:${id}:${jobId}`, {
						type: (data.failed ?? 0) > 0 ? 'warning' : 'success',
						progress: undefined,
						persistent: false
					});
				}
				if ((data.failed ?? 0) > 0) {
					toast.warning(
						$i18n.t('Deleted {{success}}/{{total}} files, {{failed}} failed', {
							success: data.success ?? 0,
							total: data.total ?? 0,
							failed: data.failed ?? 0
						})
					);
				} else {
					toast.success(
						$i18n.t('Deleted {{count}} files', { count: data.total ?? 0 })
					);
				}
				refreshKnowledge();
			}
		} else if (type === 'kb-clone-completed') {
			if (data?.kb_id === id) {
				toast.success(
					$i18n.t('Clone complete — {{cloned}}/{{total}} files copied', {
						cloned: data.cloned ?? 0,
						total: data.total ?? 0
					})
				);
				if (knowledge) {
					knowledge = {
						...(knowledge as Knowledge),
						meta: { ...(knowledge.meta ?? {}), clone_state: 'ready' }
					} as Knowledge;
				}
				refreshKnowledge();
			}
		} else if (type === 'kb-clone-failed') {
			if (data?.kb_id === id) {
				toast.error(
					$i18n.t('Clone failed — {{failed}}/{{total}} files failed', {
						failed: data.failed ?? 0,
						total: data.total ?? 0
					})
				);
				if (knowledge) {
					knowledge = {
						...(knowledge as Knowledge),
						meta: {
							...(knowledge.meta ?? {}),
							clone_state: 'failed',
							clone_error: data?.error
						}
					} as Knowledge;
				}
				refreshKnowledge();
			}
		} else if (type === 'extraction:file-complete') {
			if (data?.kb_id === id) {
				// 추출 완료된 파일 — 메타데이터 갱신
				extractingFileIds.delete(data.file_id);
				extractingFileIds = extractingFileIds;
				// 배치 추출 여부는 알림 payload 의 job_id 로 판단한다 (프런트 state
				// 인 `extractingAll` 은 페이지 새로고침/이탈 시 소실되므로 신뢰 불가).
				const isBatch = !!data.job_id;
				const suppressPerFile = batchMode || extractingAll || isBatch;
				// 배치 추출 중이면 진행률 local 집계. 서버가 별도 progress 이벤트를
				// 보내지 않으므로 파일별 이벤트로 counter 를 올린다. 같은 file_id 가
				// 두 번 통보돼도 한 번만 카운트 (워커 재시도 / chain 등으로 인한 중복).
				if (isBatch && data.file_id && !extractCountedFileIds.has(data.file_id)) {
					extractCountedFileIds.add(data.file_id);
					const newCompleted = (extractProgress.completed ?? 0) + 1;
					const newSuccess = (extractProgress.success ?? 0) + (data.status === 'success' ? 1 : 0);
					const newFailed = (extractProgress.failed ?? 0) + (data.status === 'failed' ? 1 : 0);
					// extraction:complete 에서 total 을 서버가 보내므로 total 은 덮지 않음.
					extractProgress = {
						...extractProgress,
						completed: newCompleted,
						success: newSuccess,
						failed: newFailed
					};
					if (!extractingAll) extractingAll = true;
				}
				if (data.status === 'success') {
					if (!suppressPerFile) {
						refreshKnowledge();
						if (data.extracted_count > 0) {
							toast.success(
								$i18n.t('Metadata extracted: {{count}}/{{total}} fields', {
									count: String(data.extracted_count ?? 0),
									total: String(data.total_fields ?? 0)
								})
							);
						}
						if (data.missing_required?.length) {
							toast.warning(
								$i18n.t('Required fields not extracted: {{fields}}', {
									fields: data.missing_required.join(', ')
								})
							);
						}
					}
				} else if (data.status === 'failed') {
					if (!suppressPerFile) {
						toast.error($i18n.t('Extraction failed') + (data.error ? `: ${data.error}` : ''));
					}
				}
			}
		} else if (type === 'extraction:single-complete') {
			// 단일 파일 추출의 finalize. batch 의 'extraction:complete' 와 상호 배타.
			// 'extraction:file-complete' 가 점등/툴팁 갱신 + toast 를 이미 처리하므로
			// 여기서는 KB 메타 새로고침으로 우측 요약 영역(filter slot 표시) 즉시 동기화.
			if (data?.kb_id === id) {
				refreshKnowledge();
			}
		} else if (type === 'extraction:progress') {
			if (data?.kb_id === id) {
				extractProgress = {
					completed: data.completed,
					total: data.total,
					success: data.success,
					failed: data.failed,
				};
			}
		} else if (type === 'extraction:complete') {
			if (data?.kb_id === id) {
				extractingAll = false;
				extractProgress = {
					completed: data.total,
					total: data.total,
					success: data.success,
					failed: data.failed,
				};
				if (data.failed > 0) {
					const failedResults = (data.results ?? []).filter((r) => r.status === 'failed');
					const failedNames = failedResults.map((r) => r.file_name || r.file_id);
					const displayNames = failedNames.slice(0, 3);
					const remaining = failedNames.length - displayNames.length;

					// Console: full details for debugging
					console.warn(
						`[Extraction] ${data.failed} files failed:`,
						failedResults.map((r) => `${r.file_name || r.file_id}: ${r.error}`)
					);

					// Toast: file names only
					let msg = $i18n.t('Extraction completed: {{success}}/{{total}} succeeded, {{failed}} failed', {
						success: data.success,
						total: data.total,
						failed: data.failed,
					});
					if (displayNames.length > 0) {
						msg += '\n' + displayNames.join(', ');
						if (remaining > 0) {
							msg += ` ${$i18n.t('and {{count}} more', { count: remaining })}`;
						}
					}
					toast.warning(msg);
				} else {
					toast.success(
						$i18n.t('Extraction completed: {{success}}/{{total}} succeeded', {
							success: data.success,
							total: data.total,
						})
					);
				}
				refreshKnowledge();
			}
		}
	};

	const refreshKnowledge = async () => {
		try {
			const res = await getKnowledgeById(localStorage.token, id, false);
			if (res) {
				knowledge = { ...res } as Knowledge;
				// 추출 완료 후 file_metadata 변경분을 파생 state 에 반영 — 그렇지 않으면
				// 사용자가 수동 새로고침하기 전까지 추출 결과가 화면에 안 나타남.
				// syncFromKnowledge() 통째로 호출하면 사용자가 편집 중인 filterSchema /
				// toolDescription 등도 reset 되므로 fileMetadataValues 만 좁게 갱신.
				fileMetadataValues = JSON.parse(
					JSON.stringify(res?.data?.file_metadata ?? {})
				);
				// pending 상태 동기화
				if (res.pending_files && res.pending_files.length > 0) {
					res.pending_files.forEach((file) => processingFileIds.add(file.id));
					processingFileIds = processingFileIds;
				}
			}
			// 파일 목록은 현재 보이는 페이지 범위만 재조회
			await resetAndReload();
			// 실패 파일 수 갱신 — 배치/재시도 종료 후 "실패 N건 재시도" 버튼 상태 동기화
			await refreshFailedCount();
		} catch (e) {
			console.error('Failed to refresh knowledge:', e);
		}
	};

	// 우리 세션이 시작한 배치인지 — file_id 추적 또는 echo 된 batch_id 로 판별.
	const isOwnBatchEvent = (data: { file_id?: string; batch_id?: string }) =>
		batchMode &&
		((data.file_id ? batchFileIds.has(data.file_id) : false) ||
			(!!data.batch_id && data.batch_id === currentBatchId));

	const handleFileProcessingCompleted = async (data: {
		file_id: string;
		filename: string;
		knowledge_id?: string;
		collection_name?: string;
		batch_id?: string;
		client_session_id?: string;
		message?: string;
	}) => {
		console.log('File processing completed:', data);

		// 우리 배치 카운트 집계. 목록은 라이브로 건드리지 않고 finalizeBatch 에서 1회 refresh.
		const inBatch = isOwnBatchEvent(data);
		if (inBatch && !batchAccountedIds.has(data.file_id)) {
			batchProgress.processCompleted += 1;
			batchProgress = batchProgress;
			batchAccountedIds.add(data.file_id);
			persistBatchState();
		}

		// 목록 새로고침 정책:
		//  - 우리 배치 → finalizeBatch 가 1회 refresh (여기선 skip, 페이지 calm 유지)
		//  - 단건 업로드 / 타 세션 배치 → 디바운스로 합쳐 1회만 refresh (reload 폭주 방지)
		//  - finalize 직후 straggler 는 suppress 윈도우로 건너뜀 (이중 refresh 방지)
		const forThisKb = data.knowledge_id === id || data.collection_name === id;
		if (!inBatch && forThisKb && Date.now() > suppressStragglerRefreshUntil) {
			scheduleDebouncedRefresh();
		}

		if (processingFileIds.has(data.file_id)) {
			processingFileIds.delete(data.file_id);
			processingFileIds = processingFileIds;
		}

		// 필터 추출은 서버 사이드에서 자동 체이닝 (task_queue._chain_filter_extract)

		maybeFinishBatch();
	};

	const handleFileProcessingFailed = async (data: {
		file_id: string;
		filename: string;
		knowledge_id?: string;
		collection_name?: string;
		batch_id?: string;
		client_session_id?: string;
		error?: string;
		message?: string;
	}) => {
		console.log('File processing failed:', data);

		// toast 는 띄우지 않는다 — 실패도 알림센터(벨) 요약으로만 노출 (완전 무음).
		const inBatch = isOwnBatchEvent(data);
		if (inBatch && !batchAccountedIds.has(data.file_id)) {
			batchProgress.processFailed += 1;
			batchProgress = batchProgress;
			batchAccountedIds.add(data.file_id);
			batchFailedNames.push(data.filename || data.file_id);
			persistBatchState();
		}

		if (processingFileIds.has(data.file_id)) {
			processingFileIds.delete(data.file_id);
			processingFileIds = processingFileIds;
		}

		// 목록은 라이브로 건드리지 않는다. 우리 배치는 finalizeBatch 에서, 그 외엔
		// 디바운스 refresh 로 서버 상태(failed 태그 + 재시도 버튼)를 반영한다.
		// finalize 직후 straggler 는 suppress 윈도우로 건너뜀 (이중 refresh 방지).
		const forThisKb = data.knowledge_id === id || data.collection_name === id;
		if (!inBatch && forThisKb && Date.now() > suppressStragglerRefreshUntil) {
			scheduleDebouncedRefresh();
		}

		maybeFinishBatch();
	};

	onDestroy(() => {
		mediaQuery?.removeEventListener('change', handleMediaQuery);
		const dropZone = document.querySelector('body');
		dropZone?.removeEventListener('dragover', onDragOver);
		dropZone?.removeEventListener('drop', onDrop);
		dropZone?.removeEventListener('dragleave', onDragLeave);

		if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
		if (debouncedRefreshTimer) clearTimeout(debouncedRefreshTimer);
		stopBatchPolling();
		stopSingleFilePolling();
		window.removeEventListener('beforeunload', onBeforeUnload);

		// Cleanup socket listener
		if ($socket) {
			$socket.off('notification', handleNotification);
		}
	});

	const decodeString = (str: string) => {
		try {
			return decodeURIComponent(str);
		} catch (e) {
			return str;
		}
	};
</script>

{#if dragged}
	<div
		class="fixed {$showSidebar
			? 'left-0 md:left-[260px] md:w-[calc(100%-260px)]'
			: 'left-0'}  w-full h-full flex z-50 touch-none pointer-events-none"
		id="dropzone"
		role="region"
		aria-label="Drag and Drop Container"
	>
		<div class="absolute w-full h-full backdrop-blur-sm bg-gray-800/40 flex justify-center">
			<div class="m-auto pt-64 flex flex-col justify-center">
				<div class="max-w-md">
					<AddFilesPlaceholder>
						<div class=" mt-2 text-center text-sm dark:text-gray-200 w-full">
							Drop any files here to add to my documents
						</div>
					</AddFilesPlaceholder>
				</div>
			</div>
		</div>
	</div>
{/if}

<SharePointBrowser
	bind:show={showSharePointBrowser}
	on:select={async (e) => {
		const { files } = e.detail;
		for (const file of files) {
			await uploadFileHandler(file);
		}
	}}
	on:cancel={() => {
		showSharePointBrowser = false;
	}}
/>

<AddTextContentModal
	bind:show={showAddTextContentModal}
	on:submit={(e) => {
		const file = createFileFromText(e.detail.name, e.detail.content);
		uploadFileHandler(file);
	}}
/>

<!-- 이미 추출된 파일 재추출 확인 모달 -->
<ConfirmDialog
	bind:show={showReextractDialog}
	title={$i18n.t('Re-extract already extracted files?')}
	confirmLabel={$i18n.t('Continue')}
	onConfirm={confirmReextract}
>
	<div class="text-sm text-gray-500 dark:text-gray-400 flex-1">
		<div class="mb-3">
			{$i18n.t(
				'{{already}} of {{total}} selected files already have extracted metadata. How would you like to handle them?',
				{ already: reextractAlreadyCount, total: reextractAlreadyCount + reextractPendingCount }
			)}
		</div>
		<div class="flex flex-col gap-2">
			<label
				class="flex items-start gap-2 cursor-pointer rounded-[var(--cloo-radius-default)] border px-3 py-2 hover:bg-[var(--cloo-bg-neutral-hovered)]"
				style={reextractPolicy === 'overwrite'
					? 'border-color: var(--cloo-color-info)'
					: 'border-color: var(--cloo-border-subtle)'}
			>
				<Radio
					name="reextract-policy"
					value="overwrite"
					checked={reextractPolicy === 'overwrite'}
					on:change={(e) => { if (e.detail.checked) reextractPolicy = 'overwrite'; }}
					className="mt-1"
				/>
				<div class="flex flex-col">
					<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
						{$i18n.t('Overwrite')}
					</span>
					<span class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Re-extract all selected files, replacing existing metadata (including manual edits).')}
					</span>
				</div>
			</label>
			<label
				class="flex items-start gap-2 cursor-pointer rounded-[var(--cloo-radius-default)] border px-3 py-2 hover:bg-[var(--cloo-bg-neutral-hovered)]"
				class:opacity-50={reextractPendingCount === 0}
				style={reextractPolicy === 'skip'
					? 'border-color: var(--cloo-color-info)'
					: 'border-color: var(--cloo-border-subtle)'}
			>
				<Radio
					name="reextract-policy"
					value="skip"
					checked={reextractPolicy === 'skip'}
					disabled={reextractPendingCount === 0}
					on:change={(e) => { if (e.detail.checked) reextractPolicy = 'skip'; }}
					className="mt-1"
				/>
				<div class="flex flex-col">
					<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
						{$i18n.t('Extract only missing ({{count}})', { count: reextractPendingCount })}
					</span>
					<span class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Skip files that already have extracted metadata.')}
					</span>
				</div>
			</label>
		</div>
	</div>
</ConfirmDialog>

<!-- 체크된 파일 일괄 삭제 확인 모달 -->
<ConfirmDialog
	bind:show={showBatchDeleteDialog}
	title={$i18n.t('Delete selected files?')}
	confirmLabel={$i18n.t('Delete')}
	onConfirm={confirmBatchDeleteSelected}
>
	<div class="text-sm text-gray-500 dark:text-gray-400">
		{$i18n.t(
			'{{count}} files will be permanently removed from this knowledge base, including their chunks in the search index.',
			{ count: batchDeletePendingIds.length }
		)}
		{#if batchDeleteMetaCount > 0}
			<div class="mt-2 text-amber-600 dark:text-amber-400">
				{$i18n.t(
					'⚠️ Extracted filter metadata for {{count}} of these files will also be removed.',
					{ count: batchDeleteMetaCount }
				)}
			</div>
		{/if}
	</div>
</ConfirmDialog>

<!-- 체크된 파일 일괄 메타데이터 비우기 확인 모달 (파일/청크 보존) -->
<ConfirmDialog
	bind:show={showBatchClearMetadataDialog}
	title={$i18n.t('Clear filter metadata?')}
	confirmLabel={$i18n.t('Clear')}
	onConfirm={confirmBatchClearMetadataSelected}
>
	<div class="text-sm text-gray-500 dark:text-gray-400">
		{$i18n.t(
			'Filter values will be removed from {{count}} files. The files themselves and their search chunks remain intact.',
			{ count: batchClearMetadataPendingIds.length }
		)}
	</div>
</ConfirmDialog>

<!-- 중복 파일 처리 확인 모달 (배치 업로드 선제 스캔) —
     프로젝트 공용 ConfirmDialog 포맷 사용 (지식기반 삭제 팝업과 동일) -->
<ConfirmDialog
	bind:show={showDuplicateDialog}
	title={$i18n.t('Duplicate files detected')}
	confirmLabel={$i18n.t('Continue')}
	onConfirm={handleDuplicateConfirm}
>
	<div class="text-sm text-gray-500 dark:text-gray-400 flex-1">
		<div class="mb-3">
			{$i18n.t(
				'{{count}} files already exist in this knowledge base. How would you like to handle them?',
				{ count: duplicateDialogFilenames.length }
			)}
		</div>

		<!-- 중복 파일 이름 샘플 (최대 5개 + 나머지 개수) -->
		<div
			class="mb-4 max-h-28 overflow-y-auto rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)] px-3 py-2 text-xs text-[var(--cloo-text-muted)]"
		>
			{#each duplicateDialogFilenames.slice(0, 5) as name}
				<div class="truncate">{name}</div>
			{/each}
			{#if duplicateDialogFilenames.length > 5}
				<div class="text-[var(--cloo-text-default)] opacity-70">
					{$i18n.t('and {{count}} more', { count: duplicateDialogFilenames.length - 5 })}
				</div>
			{/if}
		</div>

		<!-- 정책 선택: 덮어쓰기 / 건너뛰기 -->
		<div class="flex flex-col gap-2">
			<label
				class="flex items-start gap-2 cursor-pointer rounded-[var(--cloo-radius-default)] border px-3 py-2 hover:bg-[var(--cloo-bg-neutral-hovered)]"
				style={duplicateDialogPolicy === 'overwrite'
					? 'border-color: var(--cloo-color-info)'
					: 'border-color: var(--cloo-border-subtle)'}
			>
				<Radio
					name="duplicate-policy"
					value="overwrite"
					checked={duplicateDialogPolicy === 'overwrite'}
					on:change={(e) => { if (e.detail.checked) duplicateDialogPolicy = 'overwrite'; }}
					className="mt-1"
				/>
				<div class="flex flex-col">
					<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
						{$i18n.t('Overwrite')}
					</span>
					<span class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Replace existing files with the new uploads')}
					</span>
				</div>
			</label>
			<label
				class="flex items-start gap-2 cursor-pointer rounded-[var(--cloo-radius-default)] border px-3 py-2 hover:bg-[var(--cloo-bg-neutral-hovered)]"
				style={duplicateDialogPolicy === 'skip'
					? 'border-color: var(--cloo-color-info)'
					: 'border-color: var(--cloo-border-subtle)'}
			>
				<Radio
					name="duplicate-policy"
					value="skip"
					checked={duplicateDialogPolicy === 'skip'}
					on:change={(e) => { if (e.detail.checked) duplicateDialogPolicy = 'skip'; }}
					className="mt-1"
				/>
				<div class="flex flex-col">
					<span class="text-sm font-medium text-gray-900 dark:text-gray-100">
						{$i18n.t('Skip')}
					</span>
					<span class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Keep existing files and do not upload duplicates')}
					</span>
				</div>
			</label>
		</div>
	</div>
</ConfirmDialog>

<!-- 업로드 확인 모달 -->
<ConfirmDialog
	bind:show={showUploadConfirmDialog}
	title={$i18n.t('Upload files')}
	message={$i18n.t('Do you want to upload {{count}} files?', { count: uploadConfirmFileCount })}
	confirmLabel={$i18n.t('Upload')}
	onConfirm={handleUploadConfirm}
/>

<!-- 배치 업로드 중 페이지 이탈 확인 모달 -->
<ConfirmDialog
	bind:show={showNavGuardDialog}
	title={$i18n.t('Leave page?')}
	message={$i18n.t('Batch upload in progress. Leaving may cause files to not be uploaded. Continue?')}
	confirmLabel={$i18n.t('Leave')}
	onConfirm={handleNavGuardConfirm}
/>

<input
	id="files-input"
	bind:files={inputFiles}
	type="file"
	multiple
	hidden
	on:change={async () => {
		if (inputFiles && inputFiles.length > 0) {
			const picked = Array.from(inputFiles);
			if (picked.length >= BATCH_THRESHOLD) {
				await batchUploadFiles(picked);
			} else {
				for (const file of picked) {
					await uploadFileHandler(file);
				}
			}

			inputFiles = null;
			const fileInputElement = document.getElementById('files-input');
			if (fileInputElement) {
				fileInputElement.value = '';
			}
		} else {
			toast.error($i18n.t(`File not found.`));
		}
	}}
/>

<!-- Fallback 전용: File System Access API 미지원 브라우저용 hidden input.
     실제 change 처리는 utils/directory-picker.ts 의 pickDirectoryViaInput 이 담당. -->
<input id="directory-input" type="file" multiple hidden webkitdirectory directory />

<div class="flex flex-col w-full h-full translate-y-1" id="collection-container">
	{#if id && knowledge}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={knowledge.access_control}
			allowPublic={$user?.permissions?.sharing?.public_knowledge || $user?.role === 'admin'}
			onChange={() => {
				changeDebounceHandler();
			}}
			accessRoles={['read', 'write']}
		/>
		<SearchSettingsModal
			bind:show={showSearchSettingsModal}
			searchSettings={searchSettings ?? {}}
			onSave={async (settings) => {
				searchSettings = settings;
				await saveSettingsHandler(true);
			}}
		/>
		<Modal bind:show={showFilterSettings} size="lg">
			<div class="flex flex-col h-[85vh] max-h-[720px]">
				<div class="px-5 pt-5 pb-3 flex items-center justify-between border-b border-gray-100 dark:border-gray-800">
					<div class="flex items-center gap-2">
						<h3 class="text-base font-semibold text-gray-900 dark:text-white">{$i18n.t('Filter Settings')}</h3>
						{#if filterModalDirty}
							<span
								class="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
								data-testid="filter-modal-dirty-badge"
							>
								{$i18n.t('Unsaved changes')}
							</span>
						{/if}
					</div>
					<Button kind="text" size="sm" ariaLabel={$i18n.t('Close')} on:click={() => closeFilterModal()}>
						<svelte:fragment slot="prefix">
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/></svg>
						</svelte:fragment>
					</Button>
				</div>
				<div class="flex-1 flex overflow-hidden min-h-0">
					<!-- LEFT — 모드/모델 헤더 + 필터 리스트 + Add -->
					<aside class="w-64 shrink-0 flex flex-col border-r border-gray-100 dark:border-gray-800 bg-gray-50/40 dark:bg-gray-900/30">
						<div class="px-3 pt-4 pb-3 border-b border-gray-100 dark:border-gray-800 shrink-0">
							<div class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500 mb-1.5">
								{$i18n.t('Extraction Mode')}
							</div>
							<RadioGroup
								value={filterExtractionMode}
								options={MODE_OPTIONS}
								orientation="horizontal"
								ariaLabel={$i18n.t('Extraction Mode')}
								on:change={handleModeChange}
							/>
							{#if needsAiModel}
								<div class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500 mt-3 mb-1.5">
									{$i18n.t('AI model')}
								</div>
								<Selector
									value={aiModelId}
									items={$models
										.filter((m) => !m?.preset && !(m?.arena ?? false))
										.map((m) => ({ value: m.id, label: m.name }))}
									placeholder={$i18n.t('Select AI model')}
									size="sm"
									portal="body"
									contentClassName="z-[10000]"
									on:change={(e) => {
										aiModelId = e.detail.value;
										filterSchemaChangeHandler();
									}}
								/>
								<p class="text-[10px] text-gray-400 dark:text-gray-500 mt-1.5 leading-tight">
									{$i18n.t('Used for AI extraction and AI description generation across all filters.')}
								</p>
							{/if}
						</div>
						<div class="flex-1 overflow-y-auto px-3 py-2 min-h-0">
							{#if filterSchema.length === 0}
								<div class="px-2 py-6 text-center text-xs text-gray-400 dark:text-gray-600 leading-relaxed">
									{$i18n.t('No filters yet')}
								</div>
							{:else}
								<div class="flex flex-col gap-1">
									{#each filterSchema as _field, idx}
										<button
											type="button"
											class="group flex items-center gap-2 px-3 py-1.5 rounded-md text-left transition w-full min-w-0 {selectedFilterIdx === idx
												? 'bg-white dark:bg-gray-850 border border-gray-200 dark:border-gray-700 shadow-sm'
												: 'border border-transparent hover:bg-white/60 dark:hover:bg-gray-850/60'}"
											on:click={() => selectFilter(idx)}
											aria-current={selectedFilterIdx === idx ? 'true' : undefined}
											data-testid="filter-card-header-{idx}"
										>
											<span class="flex-1 min-w-0 truncate text-xs text-gray-700 dark:text-gray-300">
												{filterSchema[idx].label || $i18n.t('(unnamed filter)')}
											</span>
											{#if filterSchema[idx].required}
												<span class="text-[10px] text-red-500 shrink-0" title={$i18n.t('Required')}>*</span>
											{/if}
											<span class="text-[10px] text-gray-500 dark:text-gray-400 px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 shrink-0">
												{filterTypeLabel(filterSchema[idx].type)}
											</span>
											<span
												class="shrink-0 w-5 h-5 inline-flex items-center justify-center rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
												role="button"
												tabindex="0"
												aria-label={$i18n.t('Remove filter')}
												on:click|stopPropagation={() => removeFilterField(idx)}
												on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); removeFilterField(idx); } }}
											>×</span>
										</button>
									{/each}
								</div>
							{/if}
						</div>
						<div class="px-3 py-2 border-t border-gray-100 dark:border-gray-800 shrink-0">
							<Button
								kind="outlined"
								size="sm"
								disabled={!canAddMoreFilters}
								className="w-full border-dashed"
								on:click={addFilterField}
							>
								<svelte:fragment slot="prefix">
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"/></svg>
								</svelte:fragment>
								{$i18n.t('Add Filter')}
							</Button>
						</div>
					</aside>

					<!-- RIGHT — 선택된 필터의 상세 편집 -->
					<section class="flex-1 overflow-y-auto min-w-0">
						{#if selectedFilterIdx === null || filterSchema.length === 0}
							<div class="h-full flex items-center justify-center px-6 py-10">
								<div class="text-center max-w-xs">
									<div class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
										{$i18n.t('No filter selected')}
									</div>
									<p class="text-xs text-gray-500 dark:text-gray-400 mb-4 leading-relaxed">
										{$i18n.t('Define search filter fields for this knowledge base.')}
									</p>
									<div class="flex justify-center">
										<Button
											kind="outlined"
											size="sm"
											disabled={!canAddMoreFilters}
											className="border-dashed"
											on:click={addFilterField}
										>
											<svelte:fragment slot="prefix">
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z"/></svg>
											</svelte:fragment>
											{$i18n.t('Add Filter')}
										</Button>
									</div>
								</div>
							</div>
						{:else}
							{@const idx = selectedFilterIdx}
							<div class="px-6 py-5 flex flex-col gap-4">
							<!-- Field name (full width) -->
							<div class="flex flex-col gap-1.5">
								<label class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
									{$i18n.t('Field Name')}
								</label>
								<Input
									size="md"
									placeholder={$i18n.t('Field Name')}
									bind:value={filterSchema[idx].label}
									on:input={() => filterSchemaChangeHandler()}
								/>
							</div>

							<!-- Type (full width) -->
							<div class="flex flex-col gap-1.5">
								<label class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
									{$i18n.t('Type')}
								</label>
								<Selector
									value={filterSchema[idx].type}
									items={FILTER_TYPE_ITEMS}
									size="md"
									searchEnabled={false}
									portal="body"
									contentClassName="z-[10000]"
									on:change={(e) => handleFilterTypeChange(idx, e.detail.value)}
								/>
								{#if filterTypeHelp(filterSchema[idx].type)}
									<span class="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">
										{filterTypeHelp(filterSchema[idx].type)}
									</span>
								{/if}
							</div>

							<!-- Required toggle (compact inline) -->
							<div class="flex items-center justify-between gap-3 px-3 py-2.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
								<div class="flex flex-col min-w-0">
									<span class="text-sm text-gray-700 dark:text-gray-200">
										{$i18n.t('Mark as required')}
									</span>
									<span class="text-[11px] text-gray-400 dark:text-gray-500 leading-snug">
										{$i18n.t('Files without this metadata will be flagged as incomplete')}
									</span>
								</div>
								<Switch
									state={!!filterSchema[idx].required}
									ariaLabel={$i18n.t('Mark as required')}
									on:change={(e) => {
										filterSchema[idx].required = e.detail;
										filterSchemaChangeHandler();
									}}
								/>
							</div>
							{#if filterSchema[idx].type === 'glossary'}
								<div class="flex flex-col gap-1.5">
									<div class="flex flex-col">
										<label class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
											{$i18n.t('Linked glossary')}
										</label>
										<span class="text-[11px] text-gray-400 dark:text-gray-500 leading-snug">
											{$i18n.t('The glossary this filter pulls terms from. Click × to disconnect.')}
										</span>
									</div>
									{#if filterSchema[idx].glossary_id}
										<div class="flex items-center gap-2 text-xs px-2 py-1.5 bg-purple-50 dark:bg-purple-950/20 border border-purple-200 dark:border-purple-800 rounded">
											<span class="flex-1 text-purple-700 dark:text-purple-300 font-medium truncate">{filterSchema[idx].glossary_name || filterSchema[idx].glossary_id}</span>
											<Button
												kind="text"
												size="sm"
												ariaLabel={$i18n.t('Disconnect glossary')}
												on:click={() => disconnectGlossary(idx)}
											>
												<svelte:fragment slot="prefix">
													<svg viewBox="0 0 20 20" fill="currentColor"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/></svg>
												</svelte:fragment>
											</Button>
										</div>
									{:else}
										<GlossarySelector on:select={(e) => connectGlossary(idx, e.detail)}>
											<Button
												kind="outlined"
												size="sm"
												className="w-full border-dashed text-purple-500 dark:text-purple-400 border-purple-300 dark:border-purple-700 hover:bg-purple-50 dark:hover:bg-purple-950/20"
											>
												<svelte:fragment slot="prefix">
													<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" /></svg>
												</svelte:fragment>
												{$i18n.t('Select Glossary')}
											</Button>
										</GlossarySelector>
									{/if}
									<div class="mt-3 flex flex-col gap-2">
										<!-- ── 아코디언: 추출 소스 ─────────────────────── -->
										<div class="rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden">
											<button
												type="button"
												class="w-full flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
												aria-expanded={glossarySectionsOpen.source}
												on:click={() => toggleGlossarySection('source')}
											>
												<span class="text-xs font-medium text-gray-700 dark:text-gray-300">
													{$i18n.t('Extraction source')}
												</span>
												<ChevronDown className="size-4 transition-transform text-gray-400 {glossarySectionsOpen.source ? 'rotate-180' : ''}" />
											</button>
											{#if glossarySectionsOpen.source}
												<div transition:slide={{ duration: 180 }} class="px-3 py-2.5 flex flex-col gap-2 bg-white dark:bg-gray-900">
													<p class="text-[11px] text-gray-500 dark:text-gray-400 leading-snug">
														{$i18n.t('Choose which parts of each document the matcher should scan for glossary terms.')}
													</p>
													<label class="flex items-center gap-2 cursor-pointer">
														<Checkbox
															state={filterSchema[idx].extract_title !== false ? 'checked' : 'unchecked'}
															on:change={(e) => {
																filterSchema[idx].extract_title = e.detail === 'checked';
																filterSchema = filterSchema;
																filterSchemaChangeHandler();
															}}
														/>
														<span class="text-xs text-gray-700 dark:text-gray-200">{$i18n.t('Filename')}</span>
													</label>
													<label class="flex items-center gap-2 cursor-pointer">
														<Checkbox
															state={filterSchema[idx].extract_content !== false ? 'checked' : 'unchecked'}
															on:change={(e) => {
																filterSchema[idx].extract_content = e.detail === 'checked';
																filterSchema = filterSchema;
																filterSchemaChangeHandler();
															}}
														/>
														<span class="text-xs text-gray-700 dark:text-gray-200">{$i18n.t('Document body')}</span>
													</label>
													{#if filterSchema[idx].extract_content !== false}
														<div class="ml-5 flex flex-col gap-1.5">
															<RadioGroup
																value={filterSchema[idx].content_range || 'full'}
																options={CONTENT_RANGE_OPTIONS}
																name="content_range_{idx}"
																orientation="vertical"
																ariaLabel={$i18n.t('Partial content')}
																on:change={(e) => handleContentRangeChange(idx, e)}
															/>
															{#if filterSchema[idx].content_range === 'partial'}
																<div class="ml-5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
																	<div class="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300">
																		<span>{$i18n.t('First')}</span>
																		<div class="w-24">
																			<Input
																				type="number"
																				size="sm"
																				value={String(filterSchema[idx].content_prefix_chars ?? '')}
																				placeholder="0"
																				on:input={(e) => handleCharsInput(idx, 'content_prefix_chars', e)}
																			/>
																		</div>
																		<span>{$i18n.t('chars')}</span>
																	</div>
																	<div class="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300">
																		<span>{$i18n.t('Last')}</span>
																		<div class="w-24">
																			<Input
																				type="number"
																				size="sm"
																				value={String(filterSchema[idx].content_suffix_chars ?? '')}
																				placeholder="0"
																				on:input={(e) => handleCharsInput(idx, 'content_suffix_chars', e)}
																			/>
																		</div>
																		<span>{$i18n.t('chars')}</span>
																	</div>
																</div>
															{/if}
														</div>
													{/if}
												</div>
											{/if}
										</div>

										<!-- ── 아코디언: AI & 동의어 ─────────────────────── -->
										<div class="rounded-md border border-gray-200 dark:border-gray-700 overflow-hidden">
											<button
												type="button"
												class="w-full flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
												aria-expanded={glossarySectionsOpen.ai}
												on:click={() => toggleGlossarySection('ai')}
											>
												<span class="text-xs font-medium text-gray-700 dark:text-gray-300">
													{$i18n.t('Synonyms & AI extraction')}
												</span>
												<ChevronDown className="size-4 transition-transform text-gray-400 {glossarySectionsOpen.ai ? 'rotate-180' : ''}" />
											</button>
											{#if glossarySectionsOpen.ai}
												<div transition:slide={{ duration: 180 }} class="px-3 py-2.5 flex flex-col gap-3 bg-white dark:bg-gray-900">
													<p class="text-[11px] text-gray-500 dark:text-gray-400 leading-snug">
														{$i18n.t('Glossary fields combine text matching (always on) with optional AI boosting.')}
													</p>
													<label class="flex items-start gap-2 cursor-pointer">
														<div class="mt-0.5">
															<Checkbox
																state={filterSchema[idx].include_synonyms ? 'checked' : 'unchecked'}
																on:change={(e) => {
																	filterSchema[idx].include_synonyms = e.detail === 'checked';
																	filterSchemaChangeHandler();
																}}
															/>
														</div>
														<div class="flex flex-col min-w-0">
															<span class="text-xs text-gray-700 dark:text-gray-200">{$i18n.t('Include synonyms')}</span>
															<span class="text-[11px] text-gray-400 dark:text-gray-500 leading-snug">
																{$i18n.t('Also search synonyms registered in the glossary, not just the canonical term.')}
															</span>
														</div>
													</label>
													<label class="flex items-start gap-2 cursor-pointer">
														<div class="mt-0.5">
															<Checkbox
																state={filterSchema[idx].use_ai ? 'checked' : 'unchecked'}
																on:change={(e) => {
																	filterSchema[idx].use_ai = e.detail === 'checked';
																	if (!filterSchema[idx].use_ai) {
																		filterSchema[idx].extraction_prompt = '';
																	}
																	filterSchema = filterSchema;
																	filterSchemaChangeHandler();
																}}
															/>
														</div>
														<div class="flex flex-col min-w-0 flex-1">
															<span class="text-xs text-gray-700 dark:text-gray-200">{$i18n.t('AI extraction')}</span>
															<span class="text-[11px] text-gray-400 dark:text-gray-500 leading-snug">
																{$i18n.t('Use the LLM to also catch terms that text matching missed (e.g. abbreviations, multilingual). Adds cost & latency.')}
															</span>
														</div>
													</label>
													{#if filterSchema[idx].use_ai}
														<Textarea
															bind:value={filterSchema[idx].extraction_prompt}
															placeholder={$i18n.t('Enter instructions for AI extraction...')}
															size="sm"
															rows={3}
															on:input={() => filterSchemaChangeHandler()}
														/>
													{/if}
												</div>
											{/if}
										</div>
									</div>
								</div>
							{:else if filterSchema[idx].type === 'enum' || filterSchema[idx].type === 'collection'}
								<div class="flex flex-col gap-1.5">
									<label class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
										{$i18n.t('Filter Options')}
									</label>
									<Input
										size="md"
										placeholder={filterSchema[idx].type === 'collection'
											? $i18n.t('Collection options (comma separated, multiple selectable)')
											: $i18n.t('Filter options (comma separated)')}
										value={(filterSchema[idx].options ?? []).join(', ')}
										on:change={(e) => handleFilterOptionsChange(idx, e)}
									/>
								</div>
							{/if}
							<div class="flex flex-col gap-1.5">
								<div class="flex items-center justify-between gap-2">
									<div class="flex flex-col min-w-0">
										<label class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
											{$i18n.t('Agent description')}
										</label>
										<span class="text-[11px] text-gray-400 dark:text-gray-500 leading-snug">
											{$i18n.t('Agent reads this when searching.')}
										</span>
									</div>
									<Button
										kind="outlined"
										size="sm"
										loading={generatingFilterIdx === idx}
										disabled={!filterSchema[idx]?.label?.trim()}
										on:click={() => aiGenerateFilterDescription(idx)}
										title={!filterSchema[idx]?.label?.trim() ? $i18n.t('Enter field name first') : $i18n.t('Generate with AI')}
									>
										<svelte:fragment slot="prefix">
											<SparklesSolid />
										</svelte:fragment>
										{generatingFilterIdx === idx ? $i18n.t('Generating...') : $i18n.t('AI Generate')}
									</Button>
								</div>
								<Textarea
									size="md"
									rows={4}
									placeholder={$i18n.t('e.g. Use when the user asks about documents from a specific year.')}
									bind:value={filterSchema[idx].description}
									on:input={() => filterSchemaChangeHandler()}
								/>
							</div>
							{#if filterExtractionMode === 'ai' && filterSchema[idx].type !== 'glossary'}
								<div class="flex flex-col gap-1.5">
									<div class="flex flex-col min-w-0">
										<label class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
											{$i18n.t('Extraction hint')}
										</label>
										<span class="text-[11px] text-gray-400 dark:text-gray-500 leading-snug">
											{$i18n.t('AI reads this when extracting from documents.')}
										</span>
									</div>
									<Textarea
										size="md"
										rows={6}
										placeholder={$i18n.t('e.g. Find the year next to "Published" in the header. Output as YYYY.')}
										bind:value={filterSchema[idx].extraction_prompt}
										on:input={() => filterSchemaChangeHandler()}
									/>
								</div>
							{/if}
							</div>
						{/if}
					</section>
				</div>
				<div class="px-5 py-3 flex justify-end gap-2 border-t border-gray-100 dark:border-gray-800">
					<Button kind="outlined" size="md" on:click={() => closeFilterModal()}>
						{$i18n.t('Cancel')}
					</Button>
					<Button kind="filled" size="md" loading={isSavingSettings} on:click={async () => {
						await saveSettingsHandler(true);
						closeFilterModal(true);
					}}>
						{$i18n.t('Save')}
					</Button>
				</div>
			</div>
		</Modal>

		<div class="w-full shrink-0 px-2 sm:px-0">
			<WorkspaceDetailHeader
				backHref="/workspace/knowledge"
				badgeContent={$i18n.t('Knowledge')}
				bind:name={knowledge.name}
				namePlaceholder={$i18n.t('Knowledge Name')}
				bind:description={knowledge.description}
				descriptionPlaceholder={$i18n.t('Knowledge Description')}
				resourceType="knowledge"
				resourceId={id}
				bind:tagSelector
				showAccess={isOwnerOrAdmin}
				{canWrite}
				saving={isSavingSettings}
				on:change={() => changeDebounceHandler()}
				on:access={() => (showAccessControlModal = true)}
				on:save={() => saveSettingsHandler(true, true)}
			>
				<svelte:fragment slot="below">
					<ToolDescriptionSection
						bind:value={toolDescription}
						bind:aiModelId
						generating={generatingToolDesc}
						aiDisabled={totalFiles === 0}
						helpText={$i18n.t('Describe when the agent should search this knowledge base.')}
						placeholder={$i18n.t('e.g. Use for company HR policy and internal guideline questions.')}
						on:generate={aiGenerateToolDescription}
						on:change={() => toolDescriptionChangeHandler()}
					/>
				</svelte:fragment>
			</WorkspaceDetailHeader>
		</div>

		{#if knowledge?.meta?.clone_state === 'cloning'}
			<div class="mx-2 sm:mx-0 ml-8 mb-2 px-3 py-2 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 text-blue-800 dark:text-blue-200 text-sm flex items-center gap-2">
				<Spinner className="size-4" />
				<span>{$i18n.t('Cloning in progress — copying files and chunks.')}</span>
			</div>
		{:else if knowledge?.meta?.clone_state === 'failed'}
			<div class="mx-2 sm:mx-0 ml-8 mb-2 px-3 py-2 rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-200 text-sm">
				{$i18n.t('Clone failed.')}
				{#if knowledge?.meta?.clone_error}
					<span class="opacity-80">{knowledge.meta.clone_error}</span>
				{/if}
			</div>
		{/if}

		<div class="flex items-center justify-end gap-1.5 mb-2 px-2 sm:px-0 ml-8">
			<Button kind="outlined" size="sm" on:click={openFilterModal}>
				<svelte:fragment slot="prefix">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5">
						<path fill-rule="evenodd" d="M2.628 1.601C5.028 1.206 7.49 1 10 1s4.973.206 7.372.601a.75.75 0 0 1 .628.74v2.288a2.25 2.25 0 0 1-.659 1.59l-4.682 4.683a2.25 2.25 0 0 0-.659 1.59v3.037c0 .684-.31 1.33-.844 1.757l-1.937 1.55A.75.75 0 0 1 8 18.25v-5.757a2.25 2.25 0 0 0-.659-1.591L2.659 6.22A2.25 2.25 0 0 1 2 4.629V2.34a.75.75 0 0 1 .628-.74Z" clip-rule="evenodd" />
					</svg>
				</svelte:fragment>
				{$i18n.t('Filter Settings')}
			</Button>
			<Button kind="outlined" size="sm" on:click={() => { showSearchSettingsModal = true; }}>
				<svelte:fragment slot="prefix">
					<Cog6 strokeWidth="2.5" className="size-3.5" />
				</svelte:fragment>
				{$i18n.t('Settings')}
			</Button>
		</div>

		<div class="flex flex-row-reverse flex-1 min-h-0 pb-2.5 gap-3 ml-8 px-2 sm:px-0">
			{#if largeScreen}
				<div class="flex-1 min-w-0 flex justify-start w-full border border-gray-200 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-900 overflow-hidden">
					{#if selectedFile}
						<div class=" flex flex-col w-full h-full min-h-0 p-4">
							<div class="shrink-0 mb-2 flex items-center">
								{#if !showSidepanel}
									<div class="-translate-x-2">
										<button
											class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
											on:click={() => {
												pane.expand();
											}}
										>
											<ChevronLeft strokeWidth="2.5" />
										</button>
									</div>
								{/if}

								<div class=" flex-1 text-xl font-medium">
									<a
										class="hover:text-gray-500 dark:hover:text-gray-100 hover:underline grow line-clamp-1"
										href={selectedFile.id ? `/api/v1/files/${selectedFile.id}/content` : '#'}
										target="_blank"
									>
										{decodeString(selectedFile?.meta?.name)}
									</a>
								</div>
							</div>

							{#if filterSchema.length > 0 && selectedMetaFileId === selectedFileId}
								<div class="shrink-0 mb-3 p-3 rounded-xl border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)]">
									<div class="flex items-center justify-between mb-2.5">
										<span class="text-xs font-medium text-[var(--cloo-text-muted)]">
											{$i18n.t('Metadata')}
										</span>
										<div class="flex items-center gap-1.5">
											{#if hasExtractionPrompts}
												<Button
													kind="outlined"
													size="sm"
													disabled={extractingFileIds.has(selectedMetaFileId)}
													on:click={() => selectedMetaFileId && extractFileMetadataHandler(selectedMetaFileId)}
													title={$i18n.t('AI Extract')}
												>
													<svelte:fragment slot="prefix">
														{#if extractingFileIds.has(selectedMetaFileId)}
															<svg class="size-3 animate-spin" viewBox="0 0 24 24" fill="none">
																<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
																<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
															</svg>
														{:else}
															<SparklesSolid className="size-3" />
														{/if}
													</svelte:fragment>
													{extractingFileIds.has(selectedMetaFileId) ? $i18n.t('Extracting...') : $i18n.t('AI Extract')}
												</Button>
											{/if}
											<Button
												kind="filled"
												size="sm"
												disabled={savingMetaFileId === selectedMetaFileId}
												on:click={() => selectedMetaFileId && saveFileMetadataHandler(selectedMetaFileId)}
											>
												{savingMetaFileId === selectedMetaFileId ? $i18n.t('Saving...') : $i18n.t('Save')}
											</Button>
										</div>
									</div>
									<div class="grid grid-cols-4 gap-x-3 gap-y-2">
										{#each filterSchema as field}
											<div class="flex flex-col gap-1 min-w-0">
												<label class="text-xs text-[var(--cloo-text-muted)] truncate">{field.label}{#if field.required}<span class="text-[var(--cloo-color-danger)] ml-0.5">*</span>{/if}</label>
												{#if field.type === 'glossary'}
													<div class="flex flex-wrap gap-1 min-h-[1.75rem]">
														{#each (fileMetadataValues[selectedMetaFileId][field.slot] ?? []) as term}
															<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">{term}</span>
														{/each}
														{#if (fileMetadataValues[selectedMetaFileId][field.slot] ?? []).length === 0}
															<span class="text-xs text-[var(--cloo-text-muted)] italic">{$i18n.t('No terms matched')}</span>
														{/if}
													</div>
												{:else if field.type === 'date'}
													<input
														type="date"
														class="w-full text-xs bg-[var(--cloo-bg-default)] text-[var(--cloo-text-default)] border border-[var(--cloo-border-subtle)] rounded-[var(--cloo-radius-default)] px-2 py-1.5 outline-none focus:border-[var(--cloo-color-primary)]"
														bind:value={fileMetadataValues[selectedMetaFileId][field.slot]}
													/>
												{:else if field.type === 'int'}
													<Input
														type="number"
														size="sm"
														bind:value={fileMetadataValues[selectedMetaFileId][field.slot]}
													/>
												{:else if field.type === 'collection'}
													<div class="flex flex-wrap gap-1">
														{#each (field.options ?? []) as opt}
															<div class="inline-flex items-center gap-1 text-xs">
																<Checkbox
																	state={(fileMetadataValues[selectedMetaFileId][field.slot] ?? []).includes(opt) ? 'checked' : 'unchecked'}
																	on:change={(e) => {
																		const current = fileMetadataValues[selectedMetaFileId][field.slot] ?? [];
																		const arr = Array.isArray(current) ? [...current] : [];
																		if (e.detail === 'checked') {
																			if (!arr.includes(opt)) arr.push(opt);
																		} else {
																			const i = arr.indexOf(opt);
																			if (i >= 0) arr.splice(i, 1);
																		}
																		fileMetadataValues[selectedMetaFileId][field.slot] = arr;
																	}}
																/>
																<span class="text-[var(--cloo-text-default)]">{opt}</span>
															</div>
														{/each}
													</div>
												{:else if field.type === 'enum'}
													<Selector
														size="sm"
														searchEnabled={false}
														placeholder="—"
														value={fileMetadataValues[selectedMetaFileId][field.slot] ?? ''}
														items={buildEnumItems(field.options)}
														on:change={(e) => {
															fileMetadataValues[selectedMetaFileId][field.slot] = e.detail.value;
														}}
													/>
												{:else}
													<Input
														type="text"
														size="sm"
														bind:value={fileMetadataValues[selectedMetaFileId][field.slot]}
													/>
												{/if}
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<div
								class=" flex-1 min-h-0 w-full text-sm bg-transparent overflow-y-auto scrollbar-hidden prose dark:prose-invert prose-sm max-w-none"
							>
								{#key selectedFile.id}
									<Markdown
										id={selectedFile.id}
										content={normalizeLineBreaks(selectedFile.data.content || '')}
										breaks={true}
									/>
								{/key}
							</div>
						</div>
					{:else}
						<div class="h-full flex w-full">
							<div class="m-auto text-xs text-center text-gray-200 dark:text-gray-700">
								{$i18n.t('Drag and drop a file to upload or select a file to view')}
							</div>
						</div>
					{/if}
				</div>
			{:else if !largeScreen && selectedFileId !== null}
				<Drawer
					className="h-full"
					show={selectedFileId !== null}
					on:close={() => {
						selectedFileId = null;
					}}
				>
					<div class="flex flex-col justify-start h-full max-h-full p-2">
						<div class=" flex flex-col w-full h-full max-h-full">
							<div class="shrink-0 mt-1 mb-2 flex items-center">
								<div class="mr-2">
									<button
										class="w-full text-left text-sm p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
										on:click={() => {
											selectedFileId = null;
										}}
									>
										<ChevronLeft strokeWidth="2.5" />
									</button>
								</div>
								<div class=" flex-1 text-xl line-clamp-1">
									{selectedFile?.meta?.name}
								</div>
							</div>

							<div
								class=" flex-1 w-full h-full max-h-full py-2.5 px-3.5 rounded-lg text-sm bg-transparent overflow-y-auto scrollbar-hidden prose dark:prose-invert prose-sm max-w-none"
							>
								{#key selectedFile.id}
									<Markdown
										id={selectedFile.id}
										content={normalizeLineBreaks(selectedFile.data.content || '')}
										breaks={true}
									/>
								{/key}
							</div>
						</div>
					</div>
				</Drawer>
			{/if}

			<div
				class="{largeScreen ? 'shrink-0 w-96 max-w-96' : 'flex-1'} flex flex-col border border-gray-200 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-900 overflow-hidden h-full"
			>
				<div class="w-full h-full flex flex-col">
					<div class="p-3 border-b border-gray-100 dark:border-gray-800">
						<div class="flex items-center justify-between mb-2">
							<div class="text-sm font-medium text-gray-700 dark:text-gray-300">
								{$i18n.t('Files')}
							</div>
							<div class="flex items-center gap-1.5">
								<span class="text-xs text-gray-400">
									{#if debouncedQuery}
										{$i18n.t('Search results')}: {totalFiles.toLocaleString()}
									{:else}
										{totalFiles.toLocaleString()}
									{/if}
								</span>
								<div class="shrink-0 w-28">
									<Selector
										size="sm"
										searchEnabled={false}
										value={sort}
										items={sortItems}
										ariaLabel={$i18n.t('Sort')}
										on:change={handleSortSelectorChange}
									/>
								</div>
								<div>
									<AddContentMenu
										on:upload={async (e) => {
											if (e.detail.type === 'text') {
												showAddTextContentModal = true;
											} else if (e.detail.type === 'google-drive') {
												try {
													const fileData = await createPicker();
													if (fileData) {
														const file = new File([fileData.blob], fileData.name, {
															type: fileData.blob.type
														});
														await uploadFileHandler(file);
													}
												} catch (error) {
													toast.error(
														$i18n.t('Error accessing Google Drive: {{error}}', {
															error: error.message
														})
													);
												}
											} else if (e.detail.type === 'onedrive') {
												try {
													const fileData = await pickAndDownloadFile();
													if (fileData) {
														const file = new File([fileData.blob], fileData.name, {
															type: fileData.blob.type || 'application/octet-stream'
														});
														await uploadFileHandler(file);
													}
												} catch (error) {
													console.error('OneDrive Error:', error);
												}
											} else if (e.detail.type === 'sharepoint') {
												showSharePointBrowser = true;
											} else if (e.detail.type === 'directory') {
												await handleDirectoryUpload();
											} else {
												document.getElementById('files-input').click();
											}
										}}
									/>
								</div>
							</div>
						</div>
						<Input
							size="sm"
							type="search"
							bind:value={query}
							placeholder={$i18n.t('Search Collection')}
							on:input={onSearchInput}
							on:focus={() => {
								selectedFileId = null;
							}}
						>
							<svelte:fragment slot="prefix">
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
									<path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
								</svg>
							</svelte:fragment>
						</Input>
					</div>

					{#if loadedFiles.length > 0}
						<div class="px-3 pb-1.5 flex flex-col gap-1.5">
							{#if failedCount > 0 && !batchMode}
								<!-- 처리 실패 파일 일괄 재시도 — 실패가 있을 때만 노출 -->
								<Button
									kind="outlined"
									size="sm"
									disabled={retryingFailed}
									className="w-full"
									on:click={retryAllFailed}
									title={$i18n.t('Retry all failed files in this knowledge base')}
								>
									<svelte:fragment slot="prefix">
										{#if retryingFailed}
											<svg class="size-3 animate-spin" viewBox="0 0 24 24" fill="none">
												<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
												<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
											</svg>
										{:else}
											<svg viewBox="0 0 20 20" fill="currentColor" class="size-3">
												<path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.311h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z" clip-rule="evenodd" />
											</svg>
										{/if}
									</svelte:fragment>
									{retryingFailed
										? $i18n.t('Retrying...')
										: `${$i18n.t('Retry failed files')} (${failedCount})`}
								</Button>
							{/if}
							{#if hasExtractionPrompts}
								<!-- row 1: 체크박스 + Extract (col-span-2 — 아래 두 버튼 합 폭과 동일) -->
								<div class="grid grid-cols-[1.25rem_1fr_1fr] gap-2 items-center">
									<div on:click|stopPropagation>
										<Checkbox
											state={allChecked ? 'checked' : checkedCount > 0 ? 'checked' : 'unchecked'}
											indeterminate={checkedCount > 0 && !allChecked}
											disabled={selectingAll}
											on:change={toggleAllChecked}
										/>
									</div>
									<Button
										kind="filled"
										size="sm"
										disabled={extractingAll || checkedCount === 0}
										className="col-span-2"
										on:click={extractSelectedMetadataHandler}
									>
										<svelte:fragment slot="prefix">
											{#if extractingAll}
												<svg class="size-3 animate-spin" viewBox="0 0 24 24" fill="none">
													<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
													<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
												</svg>
											{:else}
												<SparklesSolid className="size-3" />
											{/if}
										</svelte:fragment>
										{extractingAll
											? `${$i18n.t('Extracting...')} ${extractProgress.completed}/${extractProgress.total}`
											: `${$i18n.t('Extract')} (${checkedCount})`}
									</Button>
								</div>
								<!-- row 2: 빈 col1 + Clear + Delete -->
								<div class="grid grid-cols-[1.25rem_1fr_1fr] gap-2 items-center">
									<div></div>
									<Button
										kind="outlined"
										size="sm"
										disabled={clearingMetadata || extractingAll || selectedWithMetadataCount === 0}
										on:click={requestBatchClearMetadataSelected}
										title={selectedWithMetadataCount === 0
											? $i18n.t('No selected files have extracted metadata')
											: $i18n.t('Clear filter metadata for selected files (preserves files and chunks)')}
									>
										<svelte:fragment slot="prefix">
											<svg viewBox="0 0 20 20" fill="currentColor"><path d="M5 3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H5Zm2.5 4a.5.5 0 0 0-.5.5v5a.5.5 0 0 0 1 0v-5a.5.5 0 0 0-.5-.5ZM10 7a.5.5 0 0 0-.5.5v5a.5.5 0 0 0 1 0v-5A.5.5 0 0 0 10 7Zm2.5 0a.5.5 0 0 0-.5.5v5a.5.5 0 0 0 1 0v-5a.5.5 0 0 0-.5-.5Z"/></svg>
										</svelte:fragment>
										{$i18n.t('Clear metadata')} ({selectedWithMetadataCount})
									</Button>
									<Button
										kind="outlined"
										status="error"
										size="sm"
										disabled={deletingSelected || extractingAll || clearingMetadata || checkedCount === 0}
										on:click={requestBatchDeleteSelected}
										title={$i18n.t('Permanently delete selected files (removes chunks and extracted metadata)')}
									>
										<svelte:fragment slot="prefix">
											<GarbageBin />
										</svelte:fragment>
										{$i18n.t('Delete files')} ({checkedCount})
									</Button>
								</div>
							{:else}
								<!-- 필터 미설정: 단일 row — 체크박스 + 안내문 + Delete -->
								<div class="grid grid-cols-[1.25rem_1fr_1fr] gap-2 items-center">
									<div on:click|stopPropagation>
										<Checkbox
											state={allChecked ? 'checked' : checkedCount > 0 ? 'checked' : 'unchecked'}
											indeterminate={checkedCount > 0 && !allChecked}
											disabled={selectingAll}
											on:change={toggleAllChecked}
										/>
									</div>
									<div class="text-xs text-gray-400 dark:text-gray-500 leading-tight">
										{$i18n.t('Configure filters to extract metadata')}
									</div>
									<Button
										kind="outlined"
										status="error"
										size="sm"
										disabled={deletingSelected || extractingAll || clearingMetadata || checkedCount === 0}
										on:click={requestBatchDeleteSelected}
										title={$i18n.t('Permanently delete selected files (removes chunks and extracted metadata)')}
									>
										<svelte:fragment slot="prefix">
											<GarbageBin />
										</svelte:fragment>
										{$i18n.t('Delete files')} ({checkedCount})
									</Button>
								</div>
							{/if}
						</div>
						{#if extractingAll && extractProgress.total > 0}
							<div class="px-3 pb-1.5">
								<div class="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1.5">
									<div
										class="bg-violet-500 h-1.5 rounded-full transition-all duration-300"
										style="width: {(extractProgress.completed / extractProgress.total) * 100}%"
									></div>
								</div>
							</div>
						{/if}
					{/if}

					{#if loadedFiles.length > 0}
						<div bind:this={fileListScroll} on:scroll={onFileListScroll} class=" flex flex-col overflow-y-auto flex-1 min-h-0 w-full scrollbar-hidden text-xs" style="max-height: calc(100vh - 260px);">
							<Files
								small
								files={loadedFiles}
								{selectedFileId}
								selectable={true}
								bind:checkedFileIds
								filterSchema={knowledge?.meta?.filter_schema ?? []}
								{fileMetadataValues}
								{extractingFileIds}
								on:click={(e) => {
									selectedFileId = selectedFileId === e.detail ? null : e.detail;
									if (selectedFileId) {
										selectedMetaFileId = selectedFileId;
										if (!fileMetadataValues[selectedFileId]) {
											fileMetadataValues[selectedFileId] = {};
										}
									} else {
										selectedMetaFileId = null;
									}
								}}
								on:delete={(e) => {
									console.log(e.detail);

									selectedFileId = null;
									deleteFileHandler(e.detail);
								}}
								on:retry={async (e) => {
									const fileId = e.detail;
									try {
										await retryFileInKnowledgeById(localStorage.token, $page.params.id || knowledge.id, fileId);
										processingFileIds.add(fileId);
										processingFileIds = processingFileIds;
										loadedFiles = loadedFiles.map((f) =>
											f.id === fileId ? { ...f, status: 'processing', data: { ...f.data, processing_job: { status: 'processing' } } } : f
										);
										toast.success($i18n.t('File retry started'));
									} catch (err) {
										toast.error(formatBackendError(err, $i18n) || $i18n.t('Failed to retry'));
									}
								}}
							/>
							{#if isLoadingFiles}
								<div class="py-2 flex justify-center text-gray-400 dark:text-gray-500">
									<Spinner className="size-4" />
								</div>
							{/if}
						</div>
					{:else if isLoadingFiles}
						<div class="my-3 flex justify-center text-gray-400 dark:text-gray-500">
							<Spinner className="size-4" />
						</div>
					{:else}
						<div class="my-3 flex flex-col justify-center text-center text-gray-500 text-xs">
							<div>
								{$i18n.t('No content found')}
							</div>
						</div>
					{/if}
				</div>
			</div>
		</div>
	{:else}
		<Spinner />
	{/if}
</div>
