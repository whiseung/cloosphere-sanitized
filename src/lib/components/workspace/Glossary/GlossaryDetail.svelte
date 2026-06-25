<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { onMount, onDestroy, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { user, models } from '$lib/stores';

	import {
		getGlossaryById,
		updateGlossaryById,
		getGlossaryCategories,
		getGlossaryExtractJob,
		getGlossaryEntries,
		acceptGlossaryExtractEntry,
		rejectGlossaryExtractEntry,
		updateGlossaryExtractEntry,
		acceptAllGlossaryExtractEntries,
		discardGlossaryExtractJob,
		cancelGlossaryExtractJob,
		createGlossaryEntry,
		updateGlossaryEntry,
		deleteGlossaryEntry,
		bulkDeleteGlossaryEntries,
		renameGlossaryCategory,
		deleteGlossaryCategory,
		deleteUncategorizedGlossaryEntries
	} from '$lib/apis/glossary';
	import type { GlossaryExtractJob } from '$lib/apis/glossary';
	import { getDbSpheres } from '$lib/apis/dbsphere';
	import { getGroups } from '$lib/apis/groups';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import WorkspaceDetailHeader from '../common/WorkspaceDetailHeader.svelte';
	import ToolDescriptionSection from '../common/ToolDescriptionSection.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import CopyGlossaryModal from './CopyGlossaryModal.svelte';
	import GlossaryImportModal from './GlossaryImportModal.svelte';
	import DocumentDuplicate from '$lib/components/icons/DocumentDuplicate.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { formatBackendError } from '$lib/utils/error';

	type GlossaryEntry = {
		id: string;
		term: string;
		synonyms: string[];
		description: string;
		example: string;
		category?: string | null;
		created_via?: string | null;
		created_at: number;
		updated_at: number;
		_pending?: boolean;
	};

	type Glossary = {
		id: string;
		name: string;
		description: string;
		data: {
			entries: GlossaryEntry[];
		};
		meta?: Record<string, any> | null;
		user_id?: string;
		access_control: any;
	};

	let toolDescription = '';
	let generatingToolDesc = false;
	let aiModelId = '';

	let id: string | null = null;
	let glossary: Glossary | null = null;
	let query = '';
	let filteredEntries: GlossaryEntry[] = [];

	let showAccessControlModal = false;
	let showDeleteEntryConfirmModal = false;

	let group_ids: string[] = [];
	let userGroups: { id: string; name: string }[] = [];
	let showCopyModal = false;

	$: isOwnerOrAdmin = $user?.role === 'admin' || glossary?.user_id === $user?.id;

	$: canWrite = $user?.role === 'admin' || (
		$user?.permissions?.workspace?.glossaries === 'write' && (
			glossary?.user_id === $user?.id
			|| glossary?.access_control?.write?.user_ids?.includes($user?.id)
			|| glossary?.access_control?.write?.group_ids?.some((gid: string) => group_ids.includes(gid))
		)
	);
	let tagSelector: any;
	let entryToDelete: string | null = null;

	let saving = false;

	// Import/Export
	// 헤더의 "Import JSON" 버튼: 기존 JSON 일괄 import 흐름 그대로 유지 (단일 파일 read → importTerms).
	// 하단 액션바의 "데이터/파일 가져오기" 버튼: 통합 모달 (DB 추출 + XLSX/CSV/MD 파일 업로드).
	let importInputElement: HTMLInputElement | undefined;
	let importFiles: FileList | undefined;
	let showImportModal = false;
	let importModalInitialFile: File | null = null;

	// Selected & Form state
	let selectedEntryId: string | null = null;
	let isEditing = false;
	let isNewEntry = false;
	let formTerm = '';
	let formSynonyms = '';
	let formDescription = '';
	let formExample = '';
	let formCategory = '';
	let existingCategories: string[] = [];

	// DB 값 추출 — Form state (extractDbId, extractTableName 등) 는 자식 컴포넌트 (BulkImportDbStage) 가 보유.
	// 부모는 job/polling state + DbSphere 이름 매핑용 캐시만 유지 (critique H1/H2).
	let allDbspheres: { id: string; name: string }[] = [];

	// 백그라운드 추출 잡 상태
	let extractJob: GlossaryExtractJob | null = null;
	let extractJobPolling: ReturnType<typeof setInterval> | null = null;
	let acceptingAll = false;
	let discardingJob = false;
	let processingEntryId: string | null = null;
	let pendingFilter: 'all' | 'pending' = 'all';

	// 서버 페이지네이션 entries
	const ENTRIES_PAGE_SIZE = 50;
	let loadedEntries: GlossaryEntry[] = [];
	let totalEntries = 0;
	let entriesLoading = false;
	let entriesHasMore = false;
	// 정렬은 항상 이름 순 (카가/알파벳). UI 셀렉트 제거 — 의미가 적어 공간 낭비였음.
	const sortOption: 'name' = 'name';
	let debouncedQuery = '';
	let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
	let termListScrollEl: HTMLElement | null = null;

	// 카테고리 멀티 셀렉트 필터
	// - selectedCategorySet: 체크된 카테고리 이름 set
	// - selectedIncludeUncategorized: "미분류" 체크 여부
	// - 디폴트: 모두 체크 (= 전체 표시)
	// - serverCategories 가 로드되면 set 을 동기화해 신규 카테고리도 자동 체크
	let serverCategories: string[] = []; // 서버에서 받은 카테고리 목록 (관리 모달 기준)
	let selectedCategorySet: Set<string> = new Set();
	let selectedIncludeUncategorized = true;
	let categoryDropdownOpen = false;
	let showCategoryManageModal = false;
	let renamingCategory: string | null = null;
	let renameTargetName = '';
	let categoryToDelete: string | null = null; // null = 카테고리 없음 삭제
	let showDeleteCategoryConfirm = false;
	let deleteCategoryKeepEntries = false; // true = 카테고리만 제거하고 용어는 미분류로 이동
	let categoryActionBusy = false;

	// 체크박스 다중 선택 삭제
	let bulkSelectedIds: Set<string> = new Set();
	let showBulkDeleteConfirm = false;
	let bulkDeleteBusy = false;

	$: bulkSelectedCount = bulkSelectedIds.size;

	// 현재 로드된 entries 중 pending 이 아닌 것들 (실제 등록된 용어만 삭제 대상)
	$: bulkSelectableIds = loadedEntries
		.filter((e) => !e._pending)
		.map((e) => e.id);
	$: isAllVisibleSelected =
		bulkSelectableIds.length > 0 &&
		bulkSelectableIds.every((eid) => bulkSelectedIds.has(eid));

	const toggleEntrySelect = (entryId: string) => {
		const next = new Set(bulkSelectedIds);
		if (next.has(entryId)) next.delete(entryId);
		else next.add(entryId);
		bulkSelectedIds = next;
	};

	const toggleSelectAllVisible = () => {
		if (isAllVisibleSelected) {
			bulkSelectedIds = new Set();
		} else {
			bulkSelectedIds = new Set(bulkSelectableIds);
		}
	};

	const clearBulkSelection = () => {
		bulkSelectedIds = new Set();
	};

	const requestBulkDelete = () => {
		if (bulkSelectedIds.size === 0) return;
		showBulkDeleteConfirm = true;
	};

	const confirmBulkDelete = async () => {
		if (!id || bulkSelectedIds.size === 0) return;
		const ids = Array.from(bulkSelectedIds);
		bulkDeleteBusy = true;
		try {
			const res = await bulkDeleteGlossaryEntries(localStorage.token, id, ids);
			toast.success(
				$i18n.t('Deleted {{count}} terms.', { count: res.deleted_count })
			);
			// 로컬 캐시에서 즉시 제거 (스크롤 유지)
			const removed = new Set(ids);
			loadedEntries = loadedEntries.filter((e) => !removed.has(e.id));
			totalEntries = Math.max(0, totalEntries - res.deleted_count);
			if (selectedEntryId && removed.has(selectedEntryId)) {
				selectedEntryId = null;
				isEditing = false;
			}
			bulkSelectedIds = new Set();
			showBulkDeleteConfirm = false;
			// 카테고리가 비었을 가능성 — 서버 메타로 재조회
			await reloadCategories();
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? `${e}`));
		} finally {
			bulkDeleteBusy = false;
		}
	};

	// 카테고리 목록 변화 시 신규 카테고리는 자동 체크 (사용자 경험: import/추가 즉시 보이도록)
	let _lastServerCategories: string[] = [];
	$: {
		const newOnes = serverCategories.filter((c) => !_lastServerCategories.includes(c));
		if (newOnes.length > 0) {
			const next = new Set(selectedCategorySet);
			for (const c of newOnes) next.add(c);
			selectedCategorySet = next;
		}
		_lastServerCategories = serverCategories;
	}

	// 모든 카테고리 + 미분류가 체크되어 있으면 "전체" 상태
	$: isAllCategorySelected =
		selectedIncludeUncategorized &&
		serverCategories.length === selectedCategorySet.size &&
		serverCategories.every((c) => selectedCategorySet.has(c));

	$: isNoCategorySelected =
		!selectedIncludeUncategorized && selectedCategorySet.size === 0;

	// 트리거 버튼 라벨 — 전체 / 미분류 / 단일 카테고리명 / N개 선택
	$: categoryFilterLabel = (() => {
		if (isAllCategorySelected) return $i18n.t('All categories');
		if (isNoCategorySelected) return $i18n.t('None selected');
		const count = selectedCategorySet.size + (selectedIncludeUncategorized ? 1 : 0);
		if (count === 1) {
			if (selectedIncludeUncategorized) return $i18n.t('Uncategorized');
			return Array.from(selectedCategorySet)[0];
		}
		return $i18n.t('{{count}} selected', { count });
	})();

	const toggleCategoryInFilter = (cat: string) => {
		const next = new Set(selectedCategorySet);
		if (next.has(cat)) next.delete(cat);
		else next.add(cat);
		selectedCategorySet = next;
	};

	const setAllCategoriesInFilter = (checked: boolean) => {
		if (checked) {
			selectedCategorySet = new Set(serverCategories);
			selectedIncludeUncategorized = true;
		} else {
			selectedCategorySet = new Set();
			selectedIncludeUncategorized = false;
		}
	};

	// 추출 잡의 pending entries (보통 작아서 full 로드)
	$: pendingEntries = (extractJob?.status === 'succeeded'
		? (extractJob.result?.entries ?? []).map((e: any) => ({ ...e, _pending: true }))
		: []) as GlossaryEntry[];

	// 신규 필터 시 검색/정렬은 클라이언트 사이드에서 처리 (pending 은 작음)
	$: filteredPendingEntries = (() => {
		if (!debouncedQuery) return pendingEntries;
		const q = debouncedQuery.toLowerCase();
		return pendingEntries.filter(
			(e) =>
				(e.term || '').toLowerCase().includes(q) ||
				(e.description || '').toLowerCase().includes(q) ||
				(e.synonyms || []).some((s) => s.toLowerCase().includes(q))
		);
	})();

	// 전체 보기: pending 을 상단에, 그 뒤에 서버에서 로드된 real entries
	$: combinedEntries = (
		pendingFilter === 'pending'
			? filteredPendingEntries
			: [...filteredPendingEntries, ...loadedEntries]
	) as GlossaryEntry[];

	// 화면용 alias (기존 템플릿 호환)
	$: filteredEntries = combinedEntries;

	$: pendingCount = pendingEntries.length;

	// pending 이 새로 생기면 자동으로 "신규" 탭, 0 이 되면 "전체"
	let _prevPendingCount = 0;
	$: {
		if (pendingCount > _prevPendingCount && pendingCount > 0) {
			pendingFilter = 'pending';
		}
		if (pendingCount === 0 && pendingFilter === 'pending') {
			pendingFilter = 'all';
		}
		_prevPendingCount = pendingCount;
	}

	$: selectedEntry = combinedEntries.find((e) => e.id === selectedEntryId) ?? null;

	// 카테고리 → 추출 출처 매핑 (worker 가 glossary.meta.extraction_sources 에 기록)
	$: extractionSources = ((glossary?.meta as any)?.extraction_sources ?? {}) as Record<
		string,
		{ dbsphere_id: string; table: string; column: string; extracted_at: number }
	>;

	$: selectedEntrySource = (() => {
		const cat = selectedEntry?.category;
		if (!cat) return null;
		const src = extractionSources[cat];
		if (!src) return null;
		const dbName = allDbspheres.find((d) => d.id === src.dbsphere_id)?.name ?? src.dbsphere_id;
		return { dbName, table: src.table, column: src.column };
	})();

	$: if (loadedEntries.length || pendingEntries.length) {
		const cats = new Set<string>();
		for (const e of [...loadedEntries, ...pendingEntries]) {
			if (e.category) cats.add(e.category);
		}
		existingCategories = [...cats].sort();
	}

	const loadEntriesPage = async (skip: number) => {
		if (!id) return;
		// "아무것도 체크 안 함" 의도 → 0건 (서버 호출 생략)
		if (isNoCategorySelected) {
			if (skip === 0) {
				loadedEntries = [];
				totalEntries = 0;
				entriesHasMore = false;
			}
			return;
		}
		try {
			// 전체 체크 상태 → category 필터 미지정 (서버가 전체 반환)
			// 일부 체크 → categories 멀티 + includeUncategorized
			const opts: Parameters<typeof getGlossaryEntries>[2] = {
				skip,
				limit: ENTRIES_PAGE_SIZE,
				search: debouncedQuery || undefined,
				sort: sortOption
			};
			if (!isAllCategorySelected) {
				opts.categories = Array.from(selectedCategorySet);
				opts.includeUncategorized = selectedIncludeUncategorized;
			}
			const res = await getGlossaryEntries(localStorage.token, id, opts);
			if (skip === 0) {
				loadedEntries = res.entries as GlossaryEntry[];
			} else {
				loadedEntries = [...loadedEntries, ...(res.entries as GlossaryEntry[])];
			}
			totalEntries = res.total;
			entriesHasMore = loadedEntries.length < res.total;
		} catch (e) {
			console.error('failed to load entries', e);
		}
	};

	// 사용자가 빠르게 여러 카테고리를 토글하면 reactive 가 reload 를 연속 트리거 →
	// 이전 fetch 가 미완료 상태라 기존 가드(if entriesLoading return)가 두 번째
	// 클릭을 무시했음. pending 플래그 + finally 재호출로 마지막 상태를 반드시 반영.
	let _reloadPending = false;
	const resetAndReloadEntries = async () => {
		if (entriesLoading) {
			_reloadPending = true;
			return;
		}
		entriesLoading = true;
		// 검색/필터 변경 시 stale 선택을 들고 있으면 사용자 혼란 → reset
		if (bulkSelectedIds.size > 0) bulkSelectedIds = new Set();
		try {
			loadedEntries = [];
			entriesHasMore = false;
			await loadEntriesPage(0);
		} finally {
			entriesLoading = false;
			if (_reloadPending) {
				_reloadPending = false;
				resetAndReloadEntries();
			}
		}
	};

	const loadMoreEntries = async () => {
		if (entriesLoading || !entriesHasMore) return;
		entriesLoading = true;
		try {
			await loadEntriesPage(loadedEntries.length);
		} finally {
			entriesLoading = false;
		}
	};

	const onTermListScroll = (e: Event) => {
		const el = e.currentTarget as HTMLElement;
		if (el.scrollHeight - el.scrollTop - el.clientHeight < 150) {
			loadMoreEntries();
		}
	};

	const reloadCategories = async () => {
		if (!id) return;
		try {
			serverCategories = await getGlossaryCategories(localStorage.token, id);
		} catch (e) {
			console.warn('failed to reload categories', e);
		}
	};

	const refreshGlossaryMeta = async () => {
		if (!id) return;
		try {
			const res = await getGlossaryById(localStorage.token, id);
			if (res) {
				glossary = { ...res, data: { ...(res.data ?? {}), entries: [] } };
				extractJob = (res?.meta as any)?.extract_job ?? null;
			}
		} catch (e) {
			console.warn('failed to refresh glossary meta', e);
		}
	};

	const startRenameCategory = (cat: string) => {
		renamingCategory = cat;
		renameTargetName = cat;
	};

	const cancelRenameCategory = () => {
		renamingCategory = null;
		renameTargetName = '';
	};

	const submitRenameCategory = async () => {
		if (!id || !renamingCategory) return;
		const from = renamingCategory;
		const to = renameTargetName.trim();
		if (!to) {
			toast.error($i18n.t('Category name is required.'));
			return;
		}
		if (to === from) {
			cancelRenameCategory();
			return;
		}
		if (serverCategories.includes(to)) {
			toast.error($i18n.t('Category name already exists.'));
			return;
		}
		categoryActionBusy = true;
		try {
			await renameGlossaryCategory(localStorage.token, id, from, to);
			toast.success($i18n.t('Category renamed.'));
			// 필터 set 도 from → to 로 마이그레이션
			if (selectedCategorySet.has(from)) {
				const next = new Set(selectedCategorySet);
				next.delete(from);
				next.add(to);
				selectedCategorySet = next;
			}
			cancelRenameCategory();
			await reloadCategories();
			await refreshGlossaryMeta();
			await resetAndReloadEntries();
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? `${e}`));
		} finally {
			categoryActionBusy = false;
		}
	};

	const requestDeleteCategory = (cat: string | null) => {
		categoryToDelete = cat;
		deleteCategoryKeepEntries = false;
		showDeleteCategoryConfirm = true;
	};

	const confirmDeleteCategory = async () => {
		if (!id) return;
		const target = categoryToDelete; // null = 카테고리 없음
		const keepEntries = deleteCategoryKeepEntries;
		categoryActionBusy = true;
		try {
			if (target === null) {
				// uncategorized 는 keep_entries 가 무의미하므로 기존 endpoint 사용
				await deleteUncategorizedGlossaryEntries(localStorage.token, id);
			} else {
				await deleteGlossaryCategory(localStorage.token, id, target, keepEntries);
				// 필터 set 에서 삭제된 카테고리 제거. entries 유지(keepEntries)면
				// 그 entries 가 uncategorized 로 이동하므로 include_uncategorized 도 on.
				if (selectedCategorySet.has(target)) {
					const next = new Set(selectedCategorySet);
					next.delete(target);
					selectedCategorySet = next;
				}
				if (keepEntries) {
					selectedIncludeUncategorized = true;
				}
			}
			toast.success(
				keepEntries
					? $i18n.t('Category removed. Terms moved to uncategorized.')
					: $i18n.t('Category deleted.')
			);
			categoryToDelete = null;
			deleteCategoryKeepEntries = false;
			showDeleteCategoryConfirm = false;
			await reloadCategories();
			await refreshGlossaryMeta();
			await resetAndReloadEntries();
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? `${e}`));
		} finally {
			categoryActionBusy = false;
		}
	};

	// 검색어 300ms 디바운스
	$: {
		if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
		const _q = query;
		searchDebounceTimer = setTimeout(() => {
			if (debouncedQuery !== _q) {
				debouncedQuery = _q;
			}
		}, 300);
	}

	// debouncedQuery / 카테고리 필터 변경 시 서버 재요청 (id 가 있을 때만)
	let _lastQueryKey = '';
	$: {
		// 카테고리 set 을 정렬해서 안정적인 key 로 — set 동등성 비교 안 됨
		const catKey = isAllCategorySelected
			? '__all__'
			: Array.from(selectedCategorySet).sort().join(',') +
				(selectedIncludeUncategorized ? '|+uncat' : '');
		const key = `${id ?? ''}|${debouncedQuery}|${catKey}`;
		if (id && key !== _lastQueryKey) {
			_lastQueryKey = key;
			resetAndReloadEntries();
		}
	}

	const selectEntry = (entry: GlossaryEntry) => {
		selectedEntryId = entry.id;
		isEditing = false;
		isNewEntry = false;
	};

	const startEdit = (entry: GlossaryEntry | null = null) => {
		if (entry) {
			selectedEntryId = entry.id;
			formTerm = entry.term;
			formSynonyms = entry.synonyms?.join(', ') ?? '';
			formDescription = entry.description ?? '';
			formExample = entry.example ?? '';
			formCategory = entry.category ?? '';
			isNewEntry = false;
		} else {
			selectedEntryId = null;
			formTerm = '';
			formSynonyms = '';
			formDescription = '';
			formExample = '';
			formCategory = '';
			isNewEntry = true;
		}
		isEditing = true;
	};

	const cancelEdit = () => {
		isEditing = false;
		isNewEntry = false;
	};

	const saveEntry = async () => {
		if (!glossary) return;
		if (formTerm.trim() === '') {
			toast.error($i18n.t('Term is required.'));
			return;
		}

		saving = true;

		const synonymsArray = formSynonyms
			.split(',')
			.map((s) => s.trim())
			.filter((s) => s.length > 0);

		// pending entry 편집은 별도 API
		const editingPending =
			!isNewEntry && selectedEntryId && selectedEntry?._pending;
		if (editingPending && id && selectedEntryId) {
			try {
				const res = await updateGlossaryExtractEntry(
					localStorage.token,
					id,
					selectedEntryId,
					{
						term: formTerm.trim(),
						synonyms: synonymsArray,
						description: formDescription.trim(),
						example: formExample.trim(),
						category: formCategory.trim() || undefined
					}
				);
				if (res) {
					glossary = res;
					extractJob = (res?.meta as any)?.extract_job ?? null;
					toast.success($i18n.t('Term updated successfully.'));
					isEditing = false;
				}
			} catch (e) {
				toast.error($i18n.t(`${e}`));
			} finally {
				saving = false;
			}
			return;
		}

		try {
			if (isNewEntry) {
				const created = await createGlossaryEntry(localStorage.token, id!, {
					term: formTerm.trim(),
					synonyms: synonymsArray,
					description: formDescription.trim(),
					example: formExample.trim(),
					category: formCategory.trim() || undefined
				});
				if (created) {
					selectedEntryId = created.id;
					toast.success($i18n.t('Term added successfully.'));
					isEditing = false;
					isNewEntry = false;
					await resetAndReloadEntries();
					await reloadCategories();
				}
			} else if (selectedEntryId) {
				const prevCategory =
					loadedEntries.find((e) => e.id === selectedEntryId)?.category ?? null;
				const nextCategory = formCategory.trim() || null;
				const updated = await updateGlossaryEntry(
					localStorage.token,
					id!,
					selectedEntryId,
					{
						term: formTerm.trim(),
						synonyms: synonymsArray,
						description: formDescription.trim(),
						example: formExample.trim(),
						category: nextCategory
					}
				);
				if (updated) {
					// 로컬 캐시 in-place 업데이트 (스크롤 위치 유지)
					loadedEntries = loadedEntries.map((e) =>
						e.id === selectedEntryId ? { ...e, ...updated } : e
					);
					toast.success($i18n.t('Term updated successfully.'));
					isEditing = false;
					// 카테고리 변경 시 카테고리 칩/관리 목록도 갱신
					if (prevCategory !== nextCategory) {
						await reloadCategories();
					}
				}
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			saving = false;
		}
	};

	const deleteEntry = async (entryId: string) => {
		if (!id) return;
		try {
			const removed = loadedEntries.find((e) => e.id === entryId) ?? null;
			await deleteGlossaryEntry(localStorage.token, id, entryId);
			// in-place 제거 (스크롤 유지)
			loadedEntries = loadedEntries.filter((e) => e.id !== entryId);
			totalEntries = Math.max(0, totalEntries - 1);
			toast.success($i18n.t('Term deleted successfully.'));
			if (selectedEntryId === entryId) {
				selectedEntryId = null;
				isEditing = false;
			}
			// 마지막 entry 였던 카테고리가 비었는지 서버 메타로 재조회
			if (removed?.category) {
				await reloadCategories();
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const saveHandler = async () => {
		if (!glossary) return;
		if (glossary.name.trim() === '') {
			toast.error($i18n.t('Please fill in all fields.'));
			return;
		}

		// 태그 변경사항 커밋
		if (tagSelector?.commitChanges) {
			try {
				await tagSelector.commitChanges();
			} catch (e) {
				console.error('Failed to commit tag changes:', e);
			}
		}

		const res = await updateGlossaryById(localStorage.token, id!, {
			name: glossary.name,
			description: glossary.description,
			meta: { ...(glossary.meta ?? {}), tool_description: toolDescription },
			access_control: glossary.access_control
		}).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Glossary updated successfully.'));
			goto('/workspace/glossary');
		}
	};

	const aiGenerateToolDescription = async () => {
		if (!glossary || generatingToolDesc) return;
		generatingToolDesc = true;
		try {
			const { generateText } = await import('$lib/apis');
			// 샘플용으로 20개만 페이지네이션 API 로 가져옴
			const samplePage = await getGlossaryEntries(localStorage.token, id!, {
				skip: 0,
				limit: 20,
				sort: 'name'
			}).catch(() => null);
			const sampleTerms = (samplePage?.entries ?? loadedEntries)
				.slice(0, 20)
				.map((e: any) => e.term)
				.filter(Boolean)
				.join(', ');
			const prompt = `용어집 이름: ${glossary.name}
설명: ${glossary.description || '없음'}
샘플 용어: ${sampleTerms}

위 용어집을 AI 에이전트가 언제 조회해야 하는지 설명하는 1~3문장을 한국어로 작성해주세요.
설명만 출력하고 다른 텍스트는 포함하지 마세요.`;
			const result = await generateText(localStorage.token, prompt, aiModelId);
			if (result) {
				toolDescription = result.trim();
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) ?? e?.message ?? $i18n.t('Something went wrong.'));
		} finally {
			generatingToolDesc = false;
		}
	};

	// ─── DB 값 추출 ───
	// Form state + start handler 는 자식 컴포넌트 (BulkImportDbStage) 가 소유.
	// 부모는 job 상태 + polling 만 관리한다 (critique H1/H2).
	// db-job-started 핸들러는 inline 처리 — 별도 함수가 의미 없음 (인수 미사용).

	const handleJsonFilePicked = (file: File) => {
		// .json 은 기존 frontend importer 로 위임 (wrapper 가 닫힌 직후 read).
		const reader = new FileReader();
		reader.onload = async (event) => {
			const content = event.target?.result;
			if (typeof content === 'string') {
				await importTerms(content);
			}
		};
		reader.readAsText(file);
	};

	const refreshExtractJob = async () => {
		if (!id) return;
		try {
			extractJob = await getGlossaryExtractJob(localStorage.token, id);
		} catch (e) {
			console.warn('failed to fetch extract job', e);
		}
	};

	const startJobPolling = () => {
		stopJobPolling();
		extractJobPolling = setInterval(async () => {
			await refreshExtractJob();
			if (
				!extractJob ||
				(extractJob.status !== 'queued' && extractJob.status !== 'running')
			) {
				stopJobPolling();
			}
		}, 3000);
	};

	const stopJobPolling = () => {
		if (extractJobPolling) {
			clearInterval(extractJobPolling);
			extractJobPolling = null;
		}
	};

	const acceptOnePending = async (entryId: string) => {
		if (!id) return;
		processingEntryId = entryId;
		try {
			const res = await acceptGlossaryExtractEntry(localStorage.token, id, entryId);
			if (res) {
				glossary = res;
				extractJob = (res?.meta as any)?.extract_job ?? null;
				toast.success($i18n.t('Term added.'));
				if (selectedEntryId === entryId) selectedEntryId = null;
				await resetAndReloadEntries();
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			processingEntryId = null;
		}
	};

	const rejectOnePending = async (entryId: string) => {
		if (!id) return;
		processingEntryId = entryId;
		try {
			const res = await rejectGlossaryExtractEntry(localStorage.token, id, entryId);
			if (res) {
				glossary = res;
				extractJob = (res?.meta as any)?.extract_job ?? null;
				if (selectedEntryId === entryId) selectedEntryId = null;
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			processingEntryId = null;
		}
	};

	const acceptAllPending = async () => {
		if (!id || pendingCount === 0) return;
		acceptingAll = true;
		try {
			const addedCount = pendingCount;
			const res = await acceptAllGlossaryExtractEntries(localStorage.token, id);
			if (res) {
				glossary = res;
				extractJob = (res?.meta as any)?.extract_job ?? null;
				toast.success($i18n.t('{{count}} terms added.', { count: addedCount }));
				await resetAndReloadEntries();
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			acceptingAll = false;
		}
	};

	const discardAllPending = async () => {
		if (!id) return;
		discardingJob = true;
		try {
			const res = await discardGlossaryExtractJob(localStorage.token, id);
			if (res) {
				glossary = res;
				extractJob = null;
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			discardingJob = false;
		}
	};

	const cancelRunningJob = async () => {
		if (!id) return;
		try {
			const res = await cancelGlossaryExtractJob(localStorage.token, id);
			if (res) {
				glossary = res;
				extractJob = (res?.meta as any)?.extract_job ?? null;
				stopJobPolling();
				toast.success($i18n.t('Extraction canceled.'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const exportTerms = async () => {
		if (!id) return;
		// 전체 entries 를 가져오기 위해 큰 limit 사용
		try {
			const page = await getGlossaryEntries(localStorage.token, id, {
				skip: 0,
				limit: 100000,
				sort: 'name'
			});
			if (!page.entries || page.entries.length === 0) {
				toast.error($i18n.t('No terms to export.'));
				return;
			}
			const exportData = page.entries.map((entry: any) => ({
				term: entry.term,
				synonyms: entry.synonyms,
				description: entry.description,
				example: entry.example
			}));
			const blob = new Blob([JSON.stringify(exportData, null, 2)], {
				type: 'application/json'
			});
			saveAs(
				blob,
				`glossary-${glossary?.name?.replace(/\s+/g, '-').toLowerCase()}-${Date.now()}.json`
			);
			toast.success($i18n.t('Terms exported successfully.'));
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const importTerms = async (jsonData: string) => {
		if (!id) return;
		try {
			const importedTerms = JSON.parse(jsonData);
			if (!Array.isArray(importedTerms)) {
				toast.error($i18n.t('Invalid JSON format. Expected an array of terms.'));
				return;
			}
			// 전체 기존 entries 를 받아와 merge 후 일괄 update
			const page = await getGlossaryEntries(localStorage.token, id, {
				skip: 0,
				limit: 100000,
				sort: 'name'
			});
			const now = Date.now();
			const existingEntries = [...(page.entries as GlossaryEntry[])];
			const newEntries: GlossaryEntry[] = [];
			for (const term of importedTerms) {
				if (!term.term || typeof term.term !== 'string') continue;
				const existingEntry = existingEntries.find(
					(e) => e.term.toLowerCase() === term.term.toLowerCase()
				);
				if (existingEntry) {
					existingEntry.synonyms = Array.isArray(term.synonyms) ? term.synonyms : [];
					existingEntry.description = term.description ?? '';
					existingEntry.example = term.example ?? '';
					existingEntry.category =
						typeof term.category === 'string' && term.category.trim()
							? term.category.trim()
							: undefined;
					existingEntry.updated_at = now;
				} else {
					newEntries.push({
						id: uuidv4(),
						term: term.term.trim(),
						synonyms: Array.isArray(term.synonyms) ? term.synonyms : [],
						description: term.description ?? '',
						example: term.example ?? '',
						category:
							typeof term.category === 'string' && term.category.trim()
								? term.category.trim()
								: undefined,
						created_at: now,
						updated_at: now
					});
				}
			}
			const allEntries = [...existingEntries, ...newEntries];
			const res = await updateGlossaryById(localStorage.token, id, {
				data: { entries: allEntries }
			}).catch((e) => {
				toast.error($i18n.t(`${e}`));
				return null;
			});
			if (res) {
				glossary = res;
				toast.success(
					$i18n.t('Imported {{count}} terms successfully.', { count: importedTerms.length })
				);
				await resetAndReloadEntries();
				await reloadCategories();
			}
		} catch (e) {
			toast.error($i18n.t('Failed to parse JSON. Please check the format.'));
		}
	};

	onMount(async () => {
		id = $page.params.id;

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
			userGroups = groups.map((g: any) => ({ id: g.id, name: g.name }));
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		const res = await getGlossaryById(localStorage.token, id).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			// data.entries 는 렌더링에 사용하지 않으므로 메모리에 쌓지 않음
			glossary = { ...res, data: { ...(res.data ?? {}), entries: [] } };
			toolDescription = (res?.meta as any)?.tool_description ?? '';
			extractJob = (res?.meta as any)?.extract_job ?? null;
			if (
				extractJob &&
				(extractJob.status === 'queued' || extractJob.status === 'running')
			) {
				startJobPolling();
			}
			// 첫 페이지 entries 로드는 id 설정 직후 reactive 블록이 자동 트리거
		} else {
			goto('/workspace/glossary');
		}

		// 카테고리 출처(extraction_sources) 표시에 dbsphere 이름이 필요해 미리 로드
		try {
			const dbs = await getDbSpheres(localStorage.token);
			allDbspheres = dbs.map((d: any) => ({ id: d.id, name: d.name }));
		} catch {
			// 추출 모달 열 때 다시 시도하므로 여기서는 무시
		}

		// 카테고리 필터 칩/관리 모달용 카테고리 목록
		await reloadCategories();
	});

	onDestroy(() => {
		stopJobPolling();
	});
</script>

<DeleteConfirmDialog
	bind:show={showDeleteEntryConfirmModal}
	title={$i18n.t('Delete Term')}
	message={$i18n.t('Are you sure you want to delete this term?')}
	on:confirm={() => {
		if (entryToDelete) {
			deleteEntry(entryToDelete);
			entryToDelete = null;
		}
	}}
/>

<DeleteConfirmDialog
	bind:show={showBulkDeleteConfirm}
	title={$i18n.t('Delete selected terms')}
	message={$i18n.t('Delete {{count}} selected terms? This cannot be undone.', {
		count: bulkSelectedCount
	})}
	on:confirm={confirmBulkDelete}
	on:cancel={() => (showBulkDeleteConfirm = false)}
/>

<DeleteConfirmDialog
	bind:show={showDeleteCategoryConfirm}
	title={$i18n.t('Delete category')}
	on:confirm={confirmDeleteCategory}
	on:cancel={() => {
		categoryToDelete = null;
		deleteCategoryKeepEntries = false;
		showDeleteCategoryConfirm = false;
	}}
>
	<div class="text-sm text-[var(--cloo-text-muted)] flex-1 whitespace-pre-line">
		{#if categoryToDelete === null}
			{$i18n.t('Delete all uncategorized terms?')}
		{:else}
			<div class="mb-3">
				{$i18n.t('Delete category "{{name}}"?', { name: categoryToDelete })}
			</div>
			<div class="flex flex-col gap-2 text-[var(--cloo-text-default)]">
				<label class="flex items-start gap-2 cursor-pointer">
					<input
						type="radio"
						name="delete-category-mode"
						class="mt-1"
						checked={!deleteCategoryKeepEntries}
						on:change={() => (deleteCategoryKeepEntries = false)}
					/>
					<span>
						<span class="font-medium">
							{$i18n.t('Delete category and all of its terms')}
						</span>
						<span class="block text-xs text-[var(--cloo-text-muted)] mt-0.5">
							{$i18n.t('Terms belonging to this category will be permanently removed.')}
						</span>
					</span>
				</label>
				<label class="flex items-start gap-2 cursor-pointer">
					<input
						type="radio"
						name="delete-category-mode"
						class="mt-1"
						checked={deleteCategoryKeepEntries}
						on:change={() => (deleteCategoryKeepEntries = true)}
					/>
					<span>
						<span class="font-medium">
							{$i18n.t('Remove category only (keep terms)')}
						</span>
						<span class="block text-xs text-[var(--cloo-text-muted)] mt-0.5">
							{$i18n.t('Terms remain and are moved to "Uncategorized".')}
						</span>
					</span>
				</label>
			</div>
		{/if}
	</div>
</DeleteConfirmDialog>

<Modal bind:show={showCategoryManageModal} size="md">
	<div class="px-5 py-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
		<div class="text-base font-semibold text-gray-900 dark:text-gray-100">
			{$i18n.t('Manage categories')}
		</div>
		<button
			class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500"
			on:click={() => {
				showCategoryManageModal = false;
				cancelRenameCategory();
			}}
			aria-label="Close"
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
			</svg>
		</button>
	</div>
	<div class="px-5 py-4 max-h-[60vh] overflow-y-auto">
		<div class="flex flex-col gap-1">
			<!-- 카테고리 없음 행 (항상 표시, rename 미지원) -->
			<div
				class="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-gray-50 dark:hover:bg-gray-850 group"
			>
				<span class="flex-1 text-sm text-gray-500 dark:text-gray-400 italic">
					{$i18n.t('Uncategorized')}
				</span>
				<Tooltip content={$i18n.t('Delete all uncategorized terms')}>
					<button
						class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-red-600 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition"
						disabled={categoryActionBusy}
						on:click={() => requestDeleteCategory(null)}
					>
						<GarbageBin className="size-3.5" />
					</button>
				</Tooltip>
			</div>
		</div>
		{#if serverCategories.length === 0}
			<div class="text-sm text-gray-400 dark:text-gray-500 italic text-center py-6">
				{$i18n.t('No named categories yet')}
			</div>
		{:else}
			<div class="flex flex-col gap-1 mt-1">
				{#each serverCategories as cat (cat)}
					<div
						class="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-gray-50 dark:hover:bg-gray-850 group"
					>
						{#if renamingCategory === cat}
							<input
								type="text"
								bind:value={renameTargetName}
								class="flex-1 text-sm px-2 py-1 rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100"
								disabled={categoryActionBusy}
								on:keydown={(e) => {
									if (e.key === 'Enter') submitRenameCategory();
									else if (e.key === 'Escape') cancelRenameCategory();
								}}
							/>
							<Button
								kind="filled"
								size="sm"
								disabled={categoryActionBusy}
								on:click={submitRenameCategory}
							>
								{$i18n.t('Save')}
							</Button>
							<Button
								kind="text"
								size="sm"
								disabled={categoryActionBusy}
								on:click={cancelRenameCategory}
							>
								{$i18n.t('Cancel')}
							</Button>
						{:else}
							<span class="flex-1 text-sm text-gray-800 dark:text-gray-200 truncate">{cat}</span>
							<Tooltip content={$i18n.t('Rename category')}>
								<button
									class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 opacity-0 group-hover:opacity-100 transition"
									disabled={categoryActionBusy}
									on:click={() => startRenameCategory(cat)}
								>
									<Pencil className="size-3.5" />
								</button>
							</Tooltip>
							<Tooltip content={$i18n.t('Delete category')}>
								<button
									class="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-red-600 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition"
									disabled={categoryActionBusy}
									on:click={() => requestDeleteCategory(cat)}
								>
									<GarbageBin className="size-3.5" />
								</button>
							</Tooltip>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</Modal>

<!--
  Unified import modal: pick (DB | file) → file stage / db stage.
  - file stage = BulkImportFileStage (자식 상태 자체 reset)
  - db stage   = BulkImportDbStage (자식 상태 자체 reset)
  - extractJob / polling 은 부모(이 컴포넌트)가 계속 소유 (critique H1/H2)
-->
<GlossaryImportModal
	bind:show={showImportModal}
	glossaryId={id ?? ''}
	{aiModelId}
	{canWrite}
	{extractJob}
	initialFile={importModalInitialFile}
	on:file-completed={async () => {
		importModalInitialFile = null;
		await resetAndReloadEntries();
		await reloadCategories();
		await refreshGlossaryMeta();
	}}
	on:db-job-started={async () => {
		importModalInitialFile = null;
		await refreshExtractJob();
		startJobPolling();
	}}
	on:json-file-picked={(e) => handleJsonFilePicked(e.detail)}
/>

<div class="flex flex-col w-full h-full translate-y-1">
	{#if glossary}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={glossary.access_control}
			allowPublic={$user?.permissions?.sharing?.public_glossaries || $user?.role === 'admin'}
			accessRoles={['read', 'write']}
		/>

		<CopyGlossaryModal
			bind:show={showCopyModal}
			glossary={glossary && { id: glossary.id, name: glossary.name }}
			{userGroups}
		/>

		<!-- Header -->
		<WorkspaceDetailHeader
			backHref="/workspace/glossary"
			badgeContent={$i18n.t('Glossary')}
			bind:name={glossary.name}
			namePlaceholder={$i18n.t('Glossary Name')}
			bind:description={glossary.description}
			descriptionPlaceholder={$i18n.t('Glossary Description')}
			resourceType="glossary"
			resourceId={id}
			bind:tagSelector
			showAccess={isOwnerOrAdmin && canWrite}
			{canWrite}
			on:access={() => (showAccessControlModal = true)}
			on:save={saveHandler}
		>
			<svelte:fragment slot="actions-prefix">
				{#if canWrite}
					<Tooltip content={$i18n.t('Copy to scope')}>
						<Button kind="text" size="sm" on:click={() => (showCopyModal = true)}>
							<DocumentDuplicate className="size-4" strokeWidth="2" />
						</Button>
					</Tooltip>
				{/if}
				<Tooltip content={$i18n.t('Import JSON')}>
					<Button kind="text" size="sm" disabled={!canWrite} on:click={() => importInputElement?.click()}>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4">
							<path fill-rule="evenodd" d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 9.5a.75.75 0 0 1-.75-.75V8.06l-.72.72a.75.75 0 0 1-1.06-1.06l2-2a.75.75 0 0 1 1.06 0l2 2a.75.75 0 1 1-1.06 1.06l-.72-.72v2.69a.75.75 0 0 1-.75.75Z" clip-rule="evenodd" />
						</svg>
					</Button>
				</Tooltip>
				<Tooltip content={$i18n.t('Export JSON')}>
					<Button kind="text" size="sm" disabled={!canWrite} on:click={exportTerms}>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-4">
							<path fill-rule="evenodd" d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 3.5a.75.75 0 0 1 .75.75v2.69l.72-.72a.75.75 0 1 1 1.06 1.06l-2 2a.75.75 0 0 1-1.06 0l-2-2a.75.75 0 0 1 1.06-1.06l.72.72V6.25A.75.75 0 0 1 8 5.5Z" clip-rule="evenodd" />
						</svg>
					</Button>
				</Tooltip>
				<div class="w-px h-5 bg-gray-200 dark:bg-gray-700 mx-0.5" />
			</svelte:fragment>

			<svelte:fragment slot="below">
				<ToolDescriptionSection
					bind:value={toolDescription}
					bind:aiModelId
					generating={generatingToolDesc}
					aiDisabled={totalEntries === 0}
					helpText={$i18n.t('Describe when the agent should look up this glossary.')}
					placeholder={$i18n.t('e.g. Use for domain-specific terminology lookups in finance reports.')}
					on:generate={aiGenerateToolDescription}
				/>
			</svelte:fragment>
		</WorkspaceDetailHeader>

		<!-- Hidden file input — 헤더의 "Import JSON" 버튼 전용 (.json 만 receive). -->
		<input
			bind:this={importInputElement}
			bind:files={importFiles}
			type="file"
			accept=".json"
			hidden
			on:change={() => {
				if (!importFiles || importFiles.length === 0) return;
				const file = importFiles[0];
				const reader = new FileReader();
				reader.onload = async (event) => {
					const content = event.target?.result;
					if (typeof content === 'string') {
						await importTerms(content);
					}
					importFiles = undefined;
					if (importInputElement) importInputElement.value = '';
				};
				reader.readAsText(file);
			}}
		/>

		<!-- Bottom-aligned actions bar — "데이터/파일 가져오기" 통합 진입 (DB + XLSX/CSV/MD). -->
		{#if canWrite}
			<div class="ml-8 flex items-center justify-end gap-[var(--cloo-space-2)] mb-[var(--cloo-space-3)]">
				<Button
					kind="outlined"
					size="sm"
					on:click={() => {
						importModalInitialFile = null;
						showImportModal = true;
					}}
				>
					<svelte:fragment slot="prefix">
						<Plus className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('Import from database or file')}
				</Button>
			</div>
		{/if}

		<!-- Extract Job Status Banner -->
		{#if extractJob}
			<div class="ml-8 mb-[var(--cloo-space-3)]">
				{#if extractJob.status === 'queued' || extractJob.status === 'running'}
					<div class="rounded-xl border border-blue-200 dark:border-blue-900/50 bg-blue-50/60 dark:bg-blue-900/20 px-4 py-3 flex items-center justify-between gap-3">
						<div class="flex items-center gap-2 text-sm text-blue-900 dark:text-blue-200">
							<svg class="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
								<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" />
								<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v3a5 5 0 00-5 5H4z" />
							</svg>
							<span class="font-medium">
								{$i18n.t('Extracting in background. We will notify you when done.')}
							</span>
						</div>
						<Button kind="text" size="sm" on:click={cancelRunningJob}>{$i18n.t('Cancel')}</Button>
					</div>
				{:else if extractJob.status === 'succeeded' && pendingCount > 0}
					<div class="rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/60 dark:bg-emerald-900/20 px-4 py-3 flex items-center justify-between gap-3">
						<div class="flex items-center gap-2 text-sm text-emerald-900 dark:text-emerald-200">
							<svg class="size-4" fill="currentColor" viewBox="0 0 20 20">
								<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.7-9.3a1 1 0 00-1.4-1.4L9 10.6 7.7 9.3a1 1 0 00-1.4 1.4l2 2a1 1 0 001.4 0l4-4z" clip-rule="evenodd" />
							</svg>
							<span class="font-medium">
								{$i18n.t('{{count}} new terms ready for review', { count: pendingCount })}
							</span>
							{#if extractJob.result?.skipped}
								<span class="text-xs text-emerald-700 dark:text-emerald-300">
									({$i18n.t('{{skipped}} duplicates skipped', { skipped: extractJob.result.skipped })})
								</span>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							<Button kind="filled" size="sm" loading={acceptingAll} on:click={acceptAllPending}>
								{$i18n.t('Add all')}
							</Button>
							<Button kind="outlined" size="sm" loading={discardingJob} on:click={discardAllPending}>
								{$i18n.t('Exclude all')}
							</Button>
						</div>
					</div>
				{:else if extractJob.status === 'failed'}
					<div class="rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50/60 dark:bg-red-900/20 px-4 py-3 flex items-center justify-between gap-3">
						<div class="flex items-start gap-2 text-sm text-red-900 dark:text-red-200">
							<svg class="size-4 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
								<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.3 7.3a1 1 0 011.4 0L10 7.6l.3-.3a1 1 0 011.4 1.4l-.3.3.3.3a1 1 0 01-1.4 1.4l-.3-.3-.3.3a1 1 0 01-1.4-1.4l.3-.3-.3-.3a1 1 0 010-1.4z" clip-rule="evenodd" />
							</svg>
							<div>
								<div class="font-medium">{$i18n.t('Extraction failed')}</div>
								{#if extractJob.error}
									<div class="text-xs mt-0.5 text-red-700 dark:text-red-300">{extractJob.error}</div>
								{/if}
							</div>
						</div>
						<Button kind="text" size="sm" on:click={discardAllPending}>{$i18n.t('Dismiss')}</Button>
					</div>
				{:else if extractJob.status === 'canceled'}
					<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-850 px-4 py-3 flex items-center justify-between gap-3">
						<span class="text-sm text-gray-600 dark:text-gray-400">{$i18n.t('Extraction canceled.')}</span>
						<Button kind="text" size="sm" on:click={discardAllPending}>{$i18n.t('Dismiss')}</Button>
					</div>
				{/if}
			</div>
		{/if}

		<!-- Main Content: Left (Terms List) + Right (Detail/Edit) -->
		<div class="flex flex-1 min-h-0 gap-4 pb-2 ml-8">
			<!-- Left: Terms List -->
			<div class="w-96 shrink-0 flex flex-col border border-gray-200 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-900 overflow-hidden">
				<!-- List Header -->
				<div class="p-3 border-b border-gray-100 dark:border-gray-800">
					<div class="flex items-center justify-between mb-2">
						<div class="text-sm font-medium text-gray-700 dark:text-gray-300">
							{$i18n.t('Terms')}
						</div>
						<div class="flex items-center gap-1.5">
							{#if totalEntries > 0}
								<span class="text-xs text-gray-400">{totalEntries}</span>
							{/if}
							{#if canWrite}
								<Tooltip content={$i18n.t('Add Term')} placement="top">
									<button
										class="p-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
										on:click={() => startEdit(null)}
									>
										<Plus className="size-3.5" />
									</button>
								</Tooltip>
							{/if}
						</div>
					</div>
					<Input
						bind:value={query}
						placeholder={$i18n.t('Search terms...')}
						type="search"
						size="sm"
					>
						<svelte:fragment slot="prefix">
							<Search className="size-3" />
						</svelte:fragment>
					</Input>

					{#if pendingCount > 0}
						<div class="flex items-center gap-1 mt-2">
							<button
								type="button"
								class="text-[11px] px-2 py-0.5 rounded-full transition border
									{pendingFilter === 'all'
										? 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700'
										: 'bg-transparent text-gray-500 dark:text-gray-500 border-transparent hover:bg-gray-50 dark:hover:bg-gray-850'}"
								on:click={() => (pendingFilter = 'all')}
							>
								{$i18n.t('All')}
								<span class="ml-0.5 text-gray-400">{totalEntries + pendingCount}</span>
							</button>
							<button
								type="button"
								class="text-[11px] px-2 py-0.5 rounded-full transition border flex items-center gap-1
									{pendingFilter === 'pending'
										? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800'
										: 'bg-transparent text-emerald-600 dark:text-emerald-400 border-transparent hover:bg-emerald-50 dark:hover:bg-emerald-900/20'}"
								on:click={() => (pendingFilter = 'pending')}
							>
								{$i18n.t('New')}
								<span class="font-semibold">{pendingCount}</span>
							</button>
						</div>
					{/if}

					<!-- Single row: 카테고리 멀티 셀렉트 트리거 (확장) + 카테고리 관리 버튼 -->
					<div class="flex items-center gap-1 mt-2">
						<Dropdown bind:show={categoryDropdownOpen} align="start">
							<button
								type="button"
								class="flex-1 min-w-0 text-[11px] px-2.5 py-1 rounded-md transition border flex items-center justify-between gap-2
									{isAllCategorySelected
										? 'bg-transparent text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850'
										: 'bg-[var(--cloo-color-info)]/10 text-[var(--cloo-color-info)] border-[var(--cloo-color-info)]/30 hover:bg-[var(--cloo-color-info)]/15'}"
								on:click={(e) => {
									e.stopPropagation();
									categoryDropdownOpen = !categoryDropdownOpen;
								}}
							>
								<span class="truncate" title={categoryFilterLabel}>
									{categoryFilterLabel}
								</span>
								<ChevronDown className="size-3 shrink-0" strokeWidth="2" />
							</button>

							<div slot="content">
								<DropdownMenu.Content
									class="rounded-xl py-1 px-1 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-md max-h-80 overflow-y-auto w-64"
									sideOffset={6}
									side="bottom"
									align="start"
									transition={flyAndScale}
								>
									<!--
										bits-ui 0.19 의 DropdownMenu.Item 은 click 시 자동 close.
										멀티 셀렉트를 위해 일반 button 으로 교체 — Content 내부
										클릭은 outside-click 으로 인식되지 않아 dropdown 열린 상태 유지.
									-->
									<button
										type="button"
										class="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs font-semibold cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md text-gray-700 dark:text-gray-100 text-left"
										on:click={() => setAllCategoriesInFilter(!isAllCategorySelected)}
									>
										<Checkbox
											state={isAllCategorySelected ? 'checked' : 'unchecked'}
											indeterminate={!isAllCategorySelected && !isNoCategorySelected}
										/>
										<span>{$i18n.t('All categories')}</span>
										<span class="ml-auto text-[10px] text-gray-400">
											{serverCategories.length + 1}
										</span>
									</button>

									<div class="my-1 border-t border-gray-200 dark:border-gray-700/60" />

									<button
										type="button"
										class="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md text-gray-600 dark:text-gray-300 text-left"
										on:click={() =>
											(selectedIncludeUncategorized = !selectedIncludeUncategorized)}
									>
										<Checkbox
											state={selectedIncludeUncategorized ? 'checked' : 'unchecked'}
										/>
										<span class="italic">{$i18n.t('Uncategorized')}</span>
									</button>

									{#each serverCategories as cat (cat)}
										<button
											type="button"
											class="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md text-gray-700 dark:text-gray-200 text-left"
											on:click={() => toggleCategoryInFilter(cat)}
										>
											<Checkbox
												state={selectedCategorySet.has(cat) ? 'checked' : 'unchecked'}
											/>
											<span class="truncate flex-1" title={cat}>{cat}</span>
										</button>
									{/each}
								</DropdownMenu.Content>
							</div>
						</Dropdown>

						{#if canWrite}
							<Tooltip content={$i18n.t('Manage categories')} placement="top">
								<button
									type="button"
									class="p-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 shrink-0"
									on:click={() => {
										reloadCategories();
										showCategoryManageModal = true;
									}}
								>
									<svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
										<path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.751-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
										<path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
									</svg>
								</button>
							</Tooltip>
						{/if}
					</div>

				</div>

				<!-- Bulk action bar (1개 이상 체크 시 노출) -->
				{#if canWrite && bulkSelectedCount > 0}
					<div
						class="mt-2 px-3 py-1.5 rounded-md bg-[var(--cloo-color-info)]/10 border border-[var(--cloo-color-info)]/30 flex items-center justify-between gap-2"
					>
						<div class="flex items-center gap-2 text-xs text-[var(--cloo-color-info)]">
							<Checkbox
								state={isAllVisibleSelected ? 'checked' : 'unchecked'}
								indeterminate={!isAllVisibleSelected && bulkSelectedCount > 0}
							/>
							<button
								type="button"
								class="font-medium hover:underline"
								on:click={toggleSelectAllVisible}
							>
								{isAllVisibleSelected
									? $i18n.t('Deselect all loaded')
									: $i18n.t('Select all loaded')}
							</button>
							<span>·</span>
							<span class="font-semibold">
								{$i18n.t('{{count}} selected', { count: bulkSelectedCount })}
							</span>
						</div>
						<div class="flex items-center gap-1 shrink-0">
							<button
								type="button"
								class="text-[11px] px-2 py-0.5 rounded text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
								on:click={clearBulkSelection}
							>
								{$i18n.t('Clear')}
							</button>
							<button
								type="button"
								class="text-[11px] px-2 py-0.5 rounded bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
								disabled={bulkDeleteBusy}
								on:click={requestBulkDelete}
							>
								{$i18n.t('Delete selected')}
							</button>
						</div>
					</div>
				{/if}

				<!-- Terms Scroll List -->
				<div
					class="flex-1 overflow-y-auto"
					bind:this={termListScrollEl}
					on:scroll={onTermListScroll}
				>
					{#if filteredEntries.length === 0 && !entriesLoading}
						<div class="flex flex-col items-center justify-center py-12 text-center px-4">
							<svg class="size-8 text-gray-300 dark:text-gray-600 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
							</svg>
							<p class="text-xs text-gray-400 dark:text-gray-500">
								{query ? $i18n.t('No terms found') : $i18n.t('No terms registered yet')}
							</p>
						</div>
					{:else}
						{#each filteredEntries as entry (entry.id)}
							<div
								class="w-full px-3 py-2.5 border-b border-gray-50 dark:border-gray-800 transition group flex items-start gap-2
									{entry._pending
										? 'bg-emerald-50/40 dark:bg-emerald-900/10 hover:bg-emerald-50 dark:hover:bg-emerald-900/20'
										: 'hover:bg-gray-50 dark:hover:bg-gray-850'}
									{selectedEntryId === entry.id
										? entry._pending
											? 'bg-emerald-50 dark:bg-emerald-900/20 border-l-2 border-l-emerald-500'
											: 'bg-gray-50 dark:bg-gray-850 border-l-2 border-l-[var(--cloo-color-info)]'
										: 'border-l-2 border-l-transparent'}"
							>
								{#if canWrite && !entry._pending}
									<div
										class="pt-0.5 shrink-0"
										on:click|stopPropagation={() => toggleEntrySelect(entry.id)}
										role="presentation"
									>
										<Checkbox
											state={bulkSelectedIds.has(entry.id) ? 'checked' : 'unchecked'}
										/>
									</div>
								{/if}
								<button
									type="button"
									class="flex-1 min-w-0 text-left"
									on:click={() => selectEntry(entry)}
								>
									<div class="flex items-center justify-between gap-1">
										<div class="font-medium text-sm text-gray-900 dark:text-gray-100 truncate flex items-center gap-1.5">
											{#if entry._pending}
												<span class="text-[9px] font-bold px-1 py-0.5 rounded bg-emerald-500 text-white shrink-0">
													NEW
												</span>
											{/if}
											<span class="truncate">{entry.term}</span>
										</div>
										{#if entry.synonyms?.length}
											<span class="text-[10px] text-gray-400 shrink-0 ml-1">+{entry.synonyms.length}</span>
										{/if}
									</div>
									{#if entry.category}
										<span class="inline-block text-[10px] px-1.5 py-0.5 mt-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
											{entry.category}
										</span>
									{/if}
									{#if entry.description}
										<div class="text-xs text-gray-400 dark:text-gray-500 truncate mt-0.5">
											{entry.description}
										</div>
									{/if}
								</button>
							</div>
						{/each}
						{#if entriesLoading}
							<div class="flex items-center justify-center py-3">
								<Spinner className="size-4" />
							</div>
						{:else if entriesHasMore && pendingFilter !== 'pending'}
							<div class="flex items-center justify-center py-3 text-[10px] text-gray-400">
								{$i18n.t('Scroll to load more')}
							</div>
						{/if}
					{/if}
				</div>
			</div>

			<!-- Right: Detail / Edit Panel -->
			<div class="flex-1 min-w-0 border border-gray-200 dark:border-gray-800 rounded-xl bg-white dark:bg-gray-900 overflow-y-auto">
				{#if isEditing}
					<!-- Edit/New Form -->
					<div class="p-6">
						<div class="flex items-center justify-between mb-5">
							<h3 class="text-lg font-semibold text-gray-900 dark:text-white">
								{isNewEntry ? $i18n.t('Add New Term') : $i18n.t('Edit Term')}
							</h3>
						</div>

						<div class="flex flex-col gap-4 max-w-2xl">
							<Input
								bind:value={formTerm}
								label={$i18n.t('Term')}
								placeholder={$i18n.t('Enter term')}
								size="md"
								required
							/>

							<Input
								bind:value={formSynonyms}
								label={$i18n.t('Synonyms')}
								caption={$i18n.t('Comma separated')}
								placeholder={$i18n.t('e.g. synonym1, synonym2')}
								size="md"
							/>

							<div>
								<label class="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
									{$i18n.t('Category')}
								</label>
								<div class="relative">
									<input
										bind:value={formCategory}
										list="glossary-categories"
										placeholder={$i18n.t('Select or type a new category')}
										class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
									/>
									<datalist id="glossary-categories">
										{#each existingCategories as cat}
											<option value={cat} />
										{/each}
									</datalist>
								</div>
								{#if existingCategories.length > 0}
									<div class="flex flex-wrap gap-1.5 mt-2">
										{#each existingCategories as cat}
											<button
												type="button"
												class="px-2 py-0.5 text-xs rounded-md transition-colors {formCategory === cat
													? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-700'
													: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 hover:bg-gray-200 dark:hover:bg-gray-700'}"
												on:click={() => { formCategory = formCategory === cat ? '' : cat; }}
											>
												{cat}
											</button>
										{/each}
									</div>
								{/if}
							</div>

							<Textarea
								bind:value={formDescription}
								label={$i18n.t('Description')}
								placeholder={$i18n.t('Enter detailed description of the term')}
								size="md"
								rows={4}
							/>

							<Textarea
								bind:value={formExample}
								label={$i18n.t('Example')}
								placeholder={$i18n.t('Enter example sentence using the term')}
								size="md"
								rows={3}
							/>

							<div class="flex items-center gap-2 pt-2">
								{#if isNewEntry}
									<Button kind="filled" size="md" loading={saving} disabled={!formTerm.trim()} on:click={saveEntry}>
										<svelte:fragment slot="prefix"><Plus className="size-3.5" /></svelte:fragment>
										{$i18n.t('Add')}
									</Button>
								{:else}
									<Button kind="filled" size="md" loading={saving} disabled={!formTerm.trim()} on:click={saveEntry}>
										{$i18n.t('Save')}
									</Button>
								{/if}
								<Button kind="outlined" size="md" on:click={cancelEdit}>
									{$i18n.t('Cancel')}
								</Button>
							</div>
						</div>
					</div>
				{:else if selectedEntry}
					<!-- Detail View -->
					<div class="p-6">
						<div class="flex items-start justify-between mb-5">
							<div>
								<h3 class="text-xl font-semibold text-gray-900 dark:text-white">
									{selectedEntry.term}
								</h3>
								{#if selectedEntry.synonyms?.length}
									<div class="flex items-center gap-1.5 mt-1.5 flex-wrap">
										{#each selectedEntry.synonyms as synonym}
											<Badge status="secondary" size="sm" content={synonym} />
										{/each}
									</div>
								{/if}
							</div>
							{#if canWrite}
								<div class="flex items-center gap-1 shrink-0">
									{#if selectedEntry._pending}
										<Button
											kind="filled"
											size="sm"
											loading={processingEntryId === selectedEntry.id}
											on:click={() => acceptOnePending(selectedEntry.id)}
										>
											{$i18n.t('Accept')}
										</Button>
										<Tooltip content={$i18n.t('Edit')}>
											<Button kind="text" size="sm" on:click={() => startEdit(selectedEntry)}>
												<Pencil className="size-4" />
											</Button>
										</Tooltip>
										<Tooltip content={$i18n.t('Reject')}>
											<Button
												kind="text"
												size="sm"
												status="error"
												loading={processingEntryId === selectedEntry.id}
												on:click={() => rejectOnePending(selectedEntry.id)}
											>
												<GarbageBin className="size-4" />
											</Button>
										</Tooltip>
									{:else}
										<Tooltip content={$i18n.t('Edit')}>
											<Button kind="text" size="sm" on:click={() => startEdit(selectedEntry)}>
												<Pencil className="size-4" />
											</Button>
										</Tooltip>
										<Tooltip content={$i18n.t('Delete')}>
											<Button kind="text" size="sm" status="error" on:click={() => {
												entryToDelete = selectedEntry.id;
												showDeleteEntryConfirmModal = true;
											}}>
												<GarbageBin className="size-4" />
											</Button>
										</Tooltip>
									{/if}
								</div>
							{/if}
						</div>

						{#if selectedEntry.category}
							<div class="mb-4 flex flex-col gap-1">
								<Badge status="info" size="sm" content={selectedEntry.category} />
								{#if selectedEntrySource}
									<div class="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1">
										<span class="opacity-70">{$i18n.t('Source')}:</span>
										<span class="font-mono">
											{selectedEntrySource.dbName} · {selectedEntrySource.table}.{selectedEntrySource.column}
										</span>
									</div>
								{/if}
							</div>
						{/if}

						{#if selectedEntry.description}
							<div class="mb-5">
								<div class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
									{$i18n.t('Description')}
								</div>
								<div class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">
									{selectedEntry.description}
								</div>
							</div>
						{/if}

						{#if selectedEntry.example}
							<div class="mb-5">
								<div class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
									{$i18n.t('Example')}
								</div>
								<div class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed whitespace-pre-wrap bg-gray-50 dark:bg-gray-850 rounded-lg p-3 border border-gray-100 dark:border-gray-800">
									{selectedEntry.example}
								</div>
							</div>
						{/if}

						{#if !selectedEntry.description && !selectedEntry.example}
							<div class="text-sm text-gray-400 dark:text-gray-500 italic">
								{$i18n.t('No details added yet.')}
								{#if canWrite}
									<button
										class="text-[var(--cloo-color-info)] hover:underline ml-1"
										on:click={() => startEdit(selectedEntry)}
									>
										{$i18n.t('Add details')}
									</button>
								{/if}
							</div>
						{/if}
					</div>
				{:else}
					<!-- Empty State -->
					<div class="flex flex-col items-center justify-center h-full text-center px-8">
						<svg class="size-12 text-gray-200 dark:text-gray-700 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
							<path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
						</svg>
						<p class="text-sm text-gray-400 dark:text-gray-500 mb-3">
							{$i18n.t('Select a term to view details')}
						</p>
						{#if canWrite}
							<Button kind="outlined" size="md" on:click={() => startEdit(null)}>
								<svelte:fragment slot="prefix"><Plus className="size-3.5" /></svelte:fragment>
								{$i18n.t('Add New Term')}
							</Button>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	{:else}
		<div class="w-full h-full flex justify-center items-center">
			<Spinner />
		</div>
	{/if}
</div>

