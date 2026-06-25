<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { user } from '$lib/stores';
	import { formatBackendError } from '$lib/utils/error';

	import {
		getCloocusStatus,
		listCloocusCustomers,
		listWorkCategories,
		createWorkCategory,
		updateWorkCategory,
		deleteWorkCategory,
		listWorkLogs,
		previewWorkLogEmail,
		previewExistingWorkLogEmail,
		createWorkLog,
		updateWorkLog,
		deleteWorkLog,
		resendWorkLogEmail
	} from '$lib/apis/cloocus';

	import Badge from '$lib/components/common/Badge.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n = getContext('i18n');

	let loading = true;
	let activeTab: 'work_logs' | 'categories' = 'work_logs';
	let dbStatus: Record<string, any> | null = null;

	// 고객사
	let customers: any[] = [];
	let customerTotal = 0;

	// 카테고리
	let categories: any[] = [];
	let categoriesLoading = false;

	// 작업 내역
	let workLogs: any[] = [];
	let workLogTotal = 0;
	let workLogPage = 1;
	let workLogFilterCustomer: number | null = null;
	let workLogFilterCategory: number | null = null;
	let workLogFilterStatus: string = '';
	let workLogsLoading = false;
	let workLogsLoaded = false;

	// 모달 - 작업 내역 생성/수정
	let showWorkLogModal = false;
	let workLogModalMode: 'add' | 'edit' = 'add';
	let editWorkLogId: number | null = null;
	let workLogForm = {
		customer_id: 0,
		category_id: 0,
		title: '',
		work_date: '',
		created_by: '',
		notes: ''
	};
	let workLogTasks: { content: string; detail: string; hours: number }[] = [];
	let workLogText: string = '';
	let editWorkLogRejectReason: string = '';
	let workLogSaving = false;

	// 이메일 미리보기 모달
	let showPreviewModal = false;
	let previewHtml = '';
	let previewRecipients: string[] = [];
	let previewSubject = '';
	let previewLoading = false;
	let previewMode: 'create' | 'resend' = 'create';
	let resendWorkLogId: number | null = null;

	// 모달 - 카테고리 추가/수정
	let showCategoryModal = false;
	let categoryModalMode: 'add' | 'edit' = 'add';
	let categoryEditId: number | null = null;
	let categoryForm = { name: '', sort_order: 0 };
	let categorySaving = false;

	onMount(async () => {
		try {
			dbStatus = await getCloocusStatus(localStorage.token);
		} catch {
			dbStatus = null;
		}
		await Promise.all([loadCustomers(), loadCategories()]);

		loading = false;
	});

	async function loadCustomers() {
		try {
			let page = 1;
			let all: any[] = [];
			while (true) {
				const res = await listCloocusCustomers(localStorage.token, page);
				all = [...all, ...res.items];
				customerTotal = res.total;
				if (all.length >= res.total) break;
				page++;
			}
			customers = all;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load customers'));
		}
	}

	async function loadCategories() {
		categoriesLoading = true;
		try {
			categories = await listWorkCategories(localStorage.token);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load categories'));
		} finally {
			categoriesLoading = false;
		}
	}

	async function loadWorkLogs() {
		workLogsLoading = true;
		try {
			const params: any = { page: workLogPage };
			if (workLogFilterCustomer) params.customer_id = workLogFilterCustomer;
			if (workLogFilterCategory) params.category_id = workLogFilterCategory;
			if (workLogFilterStatus) params.status = workLogFilterStatus;
			const res = await listWorkLogs(localStorage.token, params);
			workLogs = res.items;
			workLogTotal = res.total;
			workLogsLoaded = true;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load work logs'));
			workLogsLoaded = true;
		} finally {
			workLogsLoading = false;
		}
	}

	// 기본 내용 문구 생성
	function _getDefaultWorkLogText(customerName?: string): string {
		const name = customerName ? `<strong>"${customerName}"</strong> ` : '';
		return `안녕하세요, ${name}담당자님.\n아래 작업에 대한 크레딧 차감 승인을 요청드립니다.`;
	}

	let _prevDefaultText = '';

	function _handleCustomerChange() {
		if (workLogModalMode !== 'add') return;
		const customer = customers.find((c) => c.id === workLogForm.customer_id);
		const newDefault = _getDefaultWorkLogText(customer?.company_name);
		// 사용자가 기본값을 수정하지 않은 경우에만 자동 업데이트
		if (!workLogText.trim() || workLogText === _prevDefaultText) {
			workLogText = newDefault;
		}
		_prevDefaultText = newDefault;
	}

	// 작업 내역 생성
	function openWorkLogModal() {
		workLogModalMode = 'add';
		editWorkLogId = null;
		editWorkLogRejectReason = '';
		workLogForm = {
			customer_id: 0,
			category_id: 0,
			title: '',
			work_date: new Date().toISOString().split('T')[0],
			created_by: $user?.name || '',
			notes: ''
		};
		workLogTasks = [{ content: '', detail: '', hours: 1 }];
		_prevDefaultText = _getDefaultWorkLogText();
		workLogText = _prevDefaultText;
		showWorkLogModal = true;
	}

	function openEditWorkLogModal(wl: any) {
		workLogModalMode = 'edit';
		editWorkLogId = wl.id;
		editWorkLogRejectReason = wl.reject_reason || '';
		workLogForm = {
			customer_id: wl.customer_id,
			category_id: wl.category_id,
			title: wl.title,
			work_date: timestampToDate(wl.work_date),
			created_by: wl.created_by || '',
			notes: wl.notes || ''
		};
		// description에서 문구/태스크 파싱
		// 문구: "> 내용", 태스크: "- 제목 (Xh)\n  상세내역"
		workLogTasks = [];
		workLogText = '';
		if (wl.description) {
			const textLines: string[] = [];
			const lines = wl.description.split('\n');
			let current: { content: string; detail: string; hours: number } | null = null;
			for (const line of lines) {
				const taskMatch = line.match(/^-\s*(.+?)\s*\((\d+(?:\.\d+)?)h\)\s*$/);
				const noteMatch = line.match(/^>\s*(.*)$/);
				if (taskMatch) {
					const hours = parseFloat(taskMatch[2]);
					if (!Number.isFinite(hours)) continue;
					if (current) workLogTasks.push(current);
					current = { content: taskMatch[1], detail: '', hours };
				} else if (noteMatch) {
					if (current) {
						workLogTasks.push(current);
						current = null;
					}
					textLines.push(noteMatch[1]);
				} else if (current && line.trim()) {
					current.detail = current.detail
						? current.detail + '\n' + line.replace(/^\s{2}/, '')
						: line.replace(/^\s{2}/, '');
				}
			}
			if (current) workLogTasks.push(current);
			workLogText = textLines.join('\n');
		}
		if (workLogTasks.length === 0) {
			workLogTasks = [{ content: '', detail: '', hours: wl.work_hours || 1 }];
		}
		showWorkLogModal = true;
	}

	function dateToTimestamp(dateStr: string): number {
		return Math.floor(new Date(dateStr + 'T00:00:00Z').getTime() / 1000);
	}

	function timestampToDate(ts: number): string {
		return new Date(ts * 1000).toISOString().split('T')[0];
	}

	// Input.svelte의 type="number" 가 string 값을 그대로 반환하기 때문에
	// 합산·비교 직전에 숫자로 강제 변환한다.
	function toHours(v: number | string): number {
		const n = parseFloat(v as unknown as string);
		return Number.isFinite(n) ? n : 0;
	}

	function _buildWorkLogPayload() {
		const validTasks = workLogTasks
			.filter((t) => t.content.trim())
			.map((t) => ({ ...t, hours: toHours(t.hours) }));
		const totalHours = validTasks.reduce((sum, t) => sum + t.hours, 0);

		// 문구를 > 접두사로 상단에, 태스크를 - 접두사로 하단에
		const parts: string[] = [];
		if (workLogText.trim()) {
			parts.push(
				...workLogText
					.trim()
					.split('\n')
					.map((l) => `> ${l}`)
			);
		}
		parts.push(
			...validTasks.map((t) => {
				let line = `- ${t.content} (${t.hours}h)`;
				if (t.detail && t.detail.trim()) {
					const detailLines = t.detail
						.trim()
						.split('\n')
						.map((l) => `  ${l}`)
						.join('\n');
					line += '\n' + detailLines;
				}
				return line;
			})
		);
		const description = parts.join('\n');
		return {
			customer_id: workLogForm.customer_id,
			category_id: workLogForm.category_id,
			title: workLogForm.title,
			description,
			work_hours: totalHours,
			work_date: dateToTimestamp(workLogForm.work_date),
			created_by: workLogForm.created_by || undefined,
			notes: workLogForm.notes || undefined
		};
	}

	async function handleSaveWorkLog() {
		const validTasks = workLogTasks.filter((t) => t.content.trim());
		if (
			!workLogForm.customer_id ||
			!workLogForm.category_id ||
			!workLogForm.title.trim() ||
			!workLogForm.work_date
		) {
			toast.error($i18n.t('Please fill in all required fields'));
			return;
		}
		if (validTasks.length === 0) {
			toast.error($i18n.t('Please add at least one task'));
			return;
		}
		const invalidHours = validTasks.find((t) => toHours(t.hours) <= 0);
		if (invalidHours) {
			toast.error($i18n.t('Please enter a valid hours value (must be greater than 0)'));
			return;
		}

		// 생성 모드: 이메일 미리보기 먼저 표시
		if (workLogModalMode === 'add') {
			previewLoading = true;
			try {
				const payload = _buildWorkLogPayload();
				const res = await previewWorkLogEmail(localStorage.token, payload);
				previewHtml = res.html;
				previewRecipients = res.recipients;
				previewSubject = res.subject;
				previewMode = 'create';
				resendWorkLogId = null;
				showWorkLogModal = false;
				showPreviewModal = true;
			} catch (e: any) {
				toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to preview email'));
			} finally {
				previewLoading = false;
			}
			return;
		}

		// 수정 모드: 바로 저장
		const payload = _buildWorkLogPayload();
		workLogSaving = true;
		try {
			if (editWorkLogId) {
				await updateWorkLog(localStorage.token, editWorkLogId, {
					category_id: payload.category_id,
					title: payload.title,
					description: payload.description,
					work_hours: payload.work_hours,
					work_date: payload.work_date,
					created_by: payload.created_by,
					notes: payload.notes
				});
				toast.success($i18n.t('Work log updated'));
			}
			showWorkLogModal = false;
			await loadWorkLogs();
	
		} catch (e: any) {
			toast.error(
				formatBackendError(e, $i18n) ||
					$i18n.t(
						workLogModalMode === 'add' ? 'Failed to create work log' : 'Failed to update work log'
					)
			);
		} finally {
			workLogSaving = false;
		}
	}

	async function handleConfirmSend() {
		workLogSaving = true;
		try {
			if (previewMode === 'create') {
				const payload = _buildWorkLogPayload();
				const res = await createWorkLog(localStorage.token, payload);
				if (res.email_sent) {
					toast.success($i18n.t('Work log created and approval email sent'));
				} else {
					toast.warning(
						$i18n.t('Work log created (email not sent - check email configuration)')
					);
				}
			} else if (previewMode === 'resend' && resendWorkLogId) {
				await resendWorkLogEmail(localStorage.token, resendWorkLogId);
				toast.success($i18n.t('Approval email resent'));
			}
			showPreviewModal = false;
			await loadWorkLogs();
	
		} catch (e: any) {
			toast.error(
				formatBackendError(e, $i18n) ||
					$i18n.t(previewMode === 'create' ? 'Failed to create work log' : 'Failed to resend email')
			);
		} finally {
			workLogSaving = false;
		}
	}

	function handleBackToEdit() {
		showPreviewModal = false;
		showWorkLogModal = true;
	}

	async function handleDeleteWorkLog(id: number) {
		if (!confirm($i18n.t('Delete this work log?'))) return;
		try {
			await deleteWorkLog(localStorage.token, id);
			toast.success($i18n.t('Work log deleted'));
			await loadWorkLogs();
	
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete work log'));
		}
	}

	async function handleResendEmail(id: number) {
		previewLoading = true;
		try {
			const res = await previewExistingWorkLogEmail(localStorage.token, id);
			previewHtml = res.html;
			previewRecipients = res.recipients;
			previewSubject = res.subject;
			previewMode = 'resend';
			resendWorkLogId = id;
			showPreviewModal = true;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to preview email'));
		} finally {
			previewLoading = false;
		}
	}

	// 카테고리 모달
	function openAddCategoryModal() {
		categoryModalMode = 'add';
		categoryEditId = null;
		categoryForm = { name: '', sort_order: 0 };
		showCategoryModal = true;
	}

	function openEditCategoryModal(cat: any) {
		categoryModalMode = 'edit';
		categoryEditId = cat.id;
		categoryForm = { name: cat.name, sort_order: cat.sort_order };
		showCategoryModal = true;
	}

	async function handleSaveCategory() {
		if (!categoryForm.name.trim()) {
			toast.error($i18n.t('Category name is required'));
			return;
		}
		categorySaving = true;
		try {
			if (categoryModalMode === 'add') {
				await createWorkCategory(localStorage.token, categoryForm);
				toast.success($i18n.t('Category created'));
			} else if (categoryEditId) {
				await updateWorkCategory(localStorage.token, categoryEditId, categoryForm);
				toast.success($i18n.t('Category updated'));
			}
			showCategoryModal = false;
			await loadCategories();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to save category'));
		} finally {
			categorySaving = false;
		}
	}

	async function handleDeleteCategory(id: number) {
		if (!confirm($i18n.t('Delete this category?'))) return;
		try {
			const res = await deleteWorkCategory(localStorage.token, id);
			if (res.soft_deleted) {
				toast.success($i18n.t('Category deactivated (in use by work logs)'));
			} else {
				toast.success($i18n.t('Category deleted'));
			}
			await loadCategories();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete category'));
		}
	}

	function getStatusBadgeType(status: string): string {
		switch (status) {
			case 'pending':
				return 'warning';
			case 'accepted':
				return 'success';
			case 'rejected':
				return 'error';
			default:
				return 'muted';
		}
	}

	function getStatusLabel(status: string): string {
		switch (status) {
			case 'pending':
				return $i18n.t('Pending');
			case 'accepted':
				return $i18n.t('Accepted');
			case 'rejected':
				return $i18n.t('Rejected');
			default:
				return status;
		}
	}

	$: activeCategories = categories.filter((c) => c.is_active);
	$: workLogTotalPages = Math.ceil(workLogTotal / 20);
	$: totalWorkHours = workLogTasks.reduce((sum, t) => sum + toHours(t.hours), 0);

	function generateWorkLogTitle(categoryId: number): string {
		const category = categories.find((c) => c.id === categoryId);
		if (!category) return '';
		return `[Cloosphere] 크레딧 차감 안내 (${category.name})`;
	}

	$: if (activeTab === 'work_logs' && !workLogsLoaded && !workLogsLoading) {
		loadWorkLogs();
	}

	// Selector items / handlers
	$: customerFilterItems = [
		{ value: '', label: $i18n.t('All Customers') },
		...customers.map((c) => ({ value: String(c.id), label: c.company_name }))
	];
	$: categoryFilterItems = [
		{ value: '', label: $i18n.t('All Categories') },
		...categories.map((c) => ({ value: String(c.id), label: c.name }))
	];
	$: statusFilterItems = [
		{ value: '', label: $i18n.t('All Status') },
		{ value: 'pending', label: $i18n.t('Pending') },
		{ value: 'accepted', label: $i18n.t('Accepted') },
		{ value: 'rejected', label: $i18n.t('Rejected') }
	];
	$: modalCustomerItems = [
		{ value: '0', label: $i18n.t('Select Customer') },
		...customers
			.filter((c) => c.is_active)
			.map((c) => ({ value: String(c.id), label: c.company_name }))
	];
	$: modalCategoryItems = [
		{ value: '0', label: $i18n.t('Select Category') },
		...activeCategories.map((c) => ({ value: String(c.id), label: c.name }))
	];

	const handleFilterCustomerChange = (value: string) => {
		workLogFilterCustomer = value ? Number(value) : null;
		workLogPage = 1;
		loadWorkLogs();
	};
	const handleFilterCategoryChange = (value: string) => {
		workLogFilterCategory = value ? Number(value) : null;
		workLogPage = 1;
		loadWorkLogs();
	};
	const handleFilterStatusChange = (value: string) => {
		workLogFilterStatus = value;
		workLogPage = 1;
		loadWorkLogs();
	};
	const handleModalCustomerChange = (value: string) => {
		workLogForm.customer_id = Number(value) || 0;
		_handleCustomerChange();
	};
	const handleModalCategoryChange = (value: string) => {
		workLogForm.category_id = Number(value) || 0;
		if (workLogModalMode === 'add') {
			workLogForm.title = generateWorkLogTitle(workLogForm.category_id);
		}
	};
</script>

{#if loading}
	<div class="flex justify-center py-20">
		<Spinner />
	</div>
{:else}
	<div class="flex flex-col gap-3">
		<!-- 상단 상태 배지 -->
		<div class="flex items-center gap-2 flex-wrap">
			<span
				class="text-xs font-medium px-2 py-0.5 rounded-sm {dbStatus
					? 'bg-green-500/20 text-green-700 dark:text-green-200'
					: 'bg-red-500/20 text-red-700 dark:text-red-200'}"
			>
				{dbStatus ? $i18n.t('Cloocus DB Connected') : $i18n.t('Cloocus DB Not Available')}
			</span>
			{#if dbStatus}
				<span class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Customers')}: {dbStatus.active_customer_count}/{dbStatus.customer_count}
				</span>
			{/if}
		</div>

		<!-- 탭 -->
		<div class="flex items-center gap-1">
			{#each [{ id: 'work_logs', label: 'Work Logs' }, { id: 'categories', label: 'Category Management' }] as tab}
				<Button
					kind={activeTab === tab.id ? 'filled' : 'text'}
					size="sm"
					type="button"
					on:click={() => (activeTab = tab.id)}
				>
					{$i18n.t(tab.label)}
				</Button>
			{/each}
		</div>
	</div>

	<!-- 작업 내역 탭 -->
	{#if activeTab === 'work_logs'}
		<!-- 필터 + 추가 버튼 -->
		<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
			<div class="flex gap-1.5 flex-wrap">
				<div class="min-w-[10rem]">
					<Selector
						value={workLogFilterCustomer ? String(workLogFilterCustomer) : ''}
						items={customerFilterItems}
						size="sm"
						on:change={(e) => handleFilterCustomerChange(e.detail.value)}
					/>
				</div>

				<div class="min-w-[10rem]">
					<Selector
						value={workLogFilterCategory ? String(workLogFilterCategory) : ''}
						items={categoryFilterItems}
						size="sm"
						on:change={(e) => handleFilterCategoryChange(e.detail.value)}
					/>
				</div>

				<div class="min-w-[10rem]">
					<Selector
						value={workLogFilterStatus}
						items={statusFilterItems}
						size="sm"
						on:change={(e) => handleFilterStatusChange(e.detail.value)}
					/>
				</div>
			</div>

			<div class="flex gap-1">
				<Tooltip content={$i18n.t('Refresh')}>
					<Button kind="text" size="sm" type="button" on:click={loadWorkLogs}>
						<svelte:fragment slot="prefix">
							<ArrowPath className="size-4" />
						</svelte:fragment>
					</Button>
				</Tooltip>
				<Button kind="filled" size="md" type="button" on:click={openWorkLogModal}>
					<svelte:fragment slot="prefix">
						<Plus className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('New Work Log')}
				</Button>
			</div>
		</div>

		{#if workLogsLoading}
			<div class="flex justify-center py-12">
				<Spinner />
			</div>
		{:else}
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
				<!-- 헤더 -->
				<div class="hidden md:flex text-xs font-medium text-gray-500 dark:text-gray-400 px-1 mb-1 uppercase">
					<div class="flex-[2] min-w-0">{$i18n.t('Company Name')}</div>
					<div class="flex-[1.5] min-w-0">{$i18n.t('Category')}</div>
					<div class="flex-[3] min-w-0">{$i18n.t('Title')}</div>
					<div class="flex-none w-14 text-right">{$i18n.t('Hours')}</div>
					<div class="hidden lg:flex flex-none w-24 text-center">{$i18n.t('Work Date')}</div>
					<div class="flex-none w-20 text-center">{$i18n.t('Status')}</div>
					<div class="flex-none w-56"></div>
				</div>
				<hr class="mb-1 border-gray-50 dark:border-gray-850 hidden md:block" />

				{#each workLogs as wl}
					<div
						class="flex flex-col md:flex-row md:items-center py-2 px-1 hover:bg-gray-50 dark:hover:bg-gray-950 rounded-lg gap-1 md:gap-0"
					>
						<div class="flex-[2] min-w-0 text-sm text-gray-900 dark:text-gray-100 font-medium truncate">
							{wl.customer_name}
						</div>
						<div class="flex-[1.5] min-w-0 text-sm text-gray-500 dark:text-gray-400 truncate">
							{wl.category_name}
						</div>
						<div class="flex-[3] min-w-0 text-sm text-gray-700 dark:text-gray-300 truncate">
							{wl.title}
						</div>
						<div class="flex-none w-14 text-sm text-right text-gray-600 dark:text-gray-400">
							{wl.work_hours}{$i18n.t('h')}
						</div>
						<div class="hidden lg:block flex-none w-24 text-sm text-center text-gray-500 dark:text-gray-400">
							{timestampToDate(wl.work_date)}
						</div>
						<div class="flex-none w-20 text-center">
							{#if wl.status === 'rejected' && wl.reject_reason}
								<Tooltip content={wl.reject_reason}>
									<Badge type={getStatusBadgeType(wl.status)} content={getStatusLabel(wl.status)} />
								</Tooltip>
							{:else}
								<Badge type={getStatusBadgeType(wl.status)} content={getStatusLabel(wl.status)} />
							{/if}
						</div>
						<div class="flex-none w-56 flex gap-1.5 justify-end">
							{#if wl.status === 'pending' || wl.status === 'rejected'}
								<Button kind="outlined" size="sm" type="button" on:click={() => openEditWorkLogModal(wl)}>
									{$i18n.t('Edit')}
								</Button>
								<Button kind="outlined" size="sm" type="button" on:click={() => handleResendEmail(wl.id)}>
									{$i18n.t('Resend')}
								</Button>
							{/if}
							<Button
								kind="outlined"
								size="sm"
								status="error"
								type="button"
								on:click={() => handleDeleteWorkLog(wl.id)}
							>
								{$i18n.t('Delete')}
							</Button>
						</div>
					</div>
				{/each}

				{#if workLogs.length === 0}
					<div class="flex flex-col items-center justify-center py-12 text-center">
						<p class="text-gray-500 dark:text-gray-400">
							{$i18n.t('No work logs found')}
						</p>
					</div>
				{/if}
			</div>

			<!-- 페이지네이션 -->
			{#if workLogTotalPages > 1}
				<div
					class="flex items-center justify-center gap-2 mt-4 pt-4 border-t border-gray-50 dark:border-gray-850"
				>
					<Button
						kind="text"
						size="sm"
						type="button"
						disabled={workLogPage <= 1}
						on:click={() => {
							workLogPage--;
							loadWorkLogs();
						}}
					>
						<svelte:fragment slot="prefix">
							<ChevronLeft className="size-4" />
						</svelte:fragment>
					</Button>
					<span class="text-sm text-gray-600 dark:text-gray-400">
						{workLogPage} / {workLogTotalPages}
					</span>
					<Button
						kind="text"
						size="sm"
						type="button"
						disabled={workLogPage >= workLogTotalPages}
						on:click={() => {
							workLogPage++;
							loadWorkLogs();
						}}
					>
						<svelte:fragment slot="prefix">
							<ChevronRight className="size-4" />
						</svelte:fragment>
					</Button>
				</div>
			{/if}
		{/if}
	{/if}

	<!-- 카테고리 관리 탭 -->
	{#if activeTab === 'categories'}
		<div class="mt-0.5 mb-2 flex justify-end">
			<Button kind="filled" size="md" type="button" on:click={openAddCategoryModal}>
				<svelte:fragment slot="prefix">
					<Plus className="size-3.5" />
				</svelte:fragment>
				{$i18n.t('New Category')}
			</Button>
		</div>

		{#if categoriesLoading}
			<div class="flex justify-center py-12">
				<Spinner />
			</div>
		{:else}
			<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
				<div class="hidden md:flex text-xs font-medium text-gray-500 dark:text-gray-400 px-1 mb-1 uppercase">
					<div class="flex-1">{$i18n.t('Name')}</div>
					<div class="flex-none w-24 text-right">{$i18n.t('Sort Order')}</div>
					<div class="flex-none w-24 text-center">{$i18n.t('Status')}</div>
					<div class="flex-none w-40"></div>
				</div>
				<hr class="mb-1 border-gray-50 dark:border-gray-850 hidden md:block" />

				{#each categories as cat}
					<div
						class="flex flex-col md:flex-row md:items-center py-2 px-1 hover:bg-gray-50 dark:hover:bg-gray-950 rounded-lg gap-1 md:gap-0 {!cat.is_active
							? 'opacity-50'
							: ''}"
					>
						<div class="flex-1 text-sm text-gray-900 dark:text-gray-100">{cat.name}</div>
						<div class="flex-none w-24 text-sm text-right text-gray-500 dark:text-gray-400">
							{cat.sort_order}
						</div>
						<div class="flex-none w-24 text-center">
							<Badge
								type={cat.is_active ? 'success' : 'muted'}
								content={cat.is_active ? $i18n.t('Active') : $i18n.t('Inactive')}
							/>
						</div>
						<div class="flex-none w-40 flex gap-1.5 justify-end">
							<Button kind="outlined" size="sm" type="button" on:click={() => openEditCategoryModal(cat)}>
								{$i18n.t('Edit')}
							</Button>
							<Button
								kind="outlined"
								size="sm"
								status="error"
								type="button"
								on:click={() => handleDeleteCategory(cat.id)}
							>
								{$i18n.t('Delete')}
							</Button>
						</div>
					</div>
				{/each}

				{#if categories.length === 0}
					<div class="flex flex-col items-center justify-center py-12 text-center">
						<p class="text-gray-500 dark:text-gray-400">
							{$i18n.t('No categories found')}
						</p>
					</div>
				{/if}
			</div>
		{/if}
	{/if}
{/if}

<!-- 작업 내역 생성/수정 모달 -->
<Modal bind:show={showWorkLogModal} size="md">
	<div class="px-5 py-4">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
				{workLogModalMode === 'add' ? $i18n.t('New Work Log') : $i18n.t('Edit Work Log')}
			</h2>
		</div>

		<div class="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
			{#if editWorkLogRejectReason}
				<div class="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 p-3">
					<div class="text-xs font-medium text-red-700 dark:text-red-400 mb-1">
						{$i18n.t('Reject Reason')}
					</div>
					<p class="text-sm text-red-600 dark:text-red-300 whitespace-pre-wrap">{editWorkLogRejectReason}</p>
				</div>
			{/if}

			{#if workLogModalMode === 'add'}
				<div class="flex flex-col gap-1">
					<LabelBase label={$i18n.t('Customer')} required size="md" />
					<Selector
						value={workLogForm.customer_id ? String(workLogForm.customer_id) : '0'}
						items={modalCustomerItems}
						size="sm"
						portal="body"
						contentClassName="z-[10000]"
						on:change={(e) => handleModalCustomerChange(e.detail.value)}
					/>
				</div>
			{/if}

			<div class="flex flex-col gap-1">
				<LabelBase label={$i18n.t('Category')} required size="md" />
				<Selector
					value={workLogForm.category_id ? String(workLogForm.category_id) : '0'}
					items={modalCategoryItems}
					size="sm"
					portal="body"
					contentClassName="z-[10000]"
					on:change={(e) => handleModalCategoryChange(e.detail.value)}
				/>
			</div>

			<div class="flex gap-3">
				<div class="flex-1">
					<Input bind:value={workLogForm.title} label={$i18n.t('Title')} required size="md" />
				</div>
				<div class="flex-none w-36 flex flex-col gap-1">
					<LabelBase label={$i18n.t('Work Date')} required size="md" />
					<input
						type="date"
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						bind:value={workLogForm.work_date}
					/>
				</div>
			</div>

			<!-- 내용 (이메일 본문에 포함) -->
			<Textarea
				bind:value={workLogText}
				label={$i18n.t('Content')}
				placeholder={$i18n.t('Text to include in email')}
				size="md"
				rows={3}
			/>

			<!-- 태스크 목록 -->
			<div>
				<LabelBase label={$i18n.t('Tasks')} required size="md">
					<svelte:fragment slot="right">
						<span class="text-xs text-gray-500">
							{$i18n.t('Deduction')}: {totalWorkHours}{$i18n.t('h')}
						</span>
					</svelte:fragment>
				</LabelBase>

				<div class="space-y-2 mt-1">
					{#each workLogTasks as task, idx}
						<div class="rounded-lg border border-gray-200 dark:border-gray-700 p-2.5">
							<div class="flex items-center gap-1.5">
								<div class="flex-1">
									<Input
										bind:value={task.content}
										placeholder={$i18n.t('Task title')}
										size="md"
									/>
								</div>
								<div class="flex-none w-20">
									<Input
										bind:value={task.hours}
										type="number"
										step="0.5"
										min="0.5"
										size="md"
									/>
								</div>
								<span class="flex-none text-xs text-gray-400">{$i18n.t('h')}</span>
								{#if workLogTasks.length > 1}
									<Button
										kind="text"
										size="sm"
										status="error"
										type="button"
										on:click={() => {
											workLogTasks = workLogTasks.filter((_, i) => i !== idx);
										}}
									>
										<svelte:fragment slot="prefix">
											<XMark className="size-3.5" />
										</svelte:fragment>
									</Button>
								{:else}
									<div class="flex-none w-5"></div>
								{/if}
							</div>
							<div class="mt-1.5">
								<Textarea
									bind:value={task.detail}
									placeholder={$i18n.t('Task detail (optional)')}
									rows={2}
									size="md"
								/>
							</div>
						</div>
					{/each}
				</div>

				<div class="mt-2">
					<Button
						kind="text"
						size="sm"
						type="button"
						on:click={() => {
							workLogTasks = [...workLogTasks, { content: '', detail: '', hours: 1 }];
						}}
					>
						<svelte:fragment slot="prefix">
							<Plus className="size-3.5" />
						</svelte:fragment>
						{$i18n.t('Add Task')}
					</Button>
				</div>
			</div>

			<Input
				bind:value={workLogForm.created_by}
				label={$i18n.t('Created By')}
				size="md"
				disabled
			/>

			<Textarea bind:value={workLogForm.notes} label={$i18n.t('Notes')} size="md" rows={2} />
		</div>

		<div class="flex gap-1.5 mt-6">
			<Button kind="outlined" size="md" className="flex-1" on:click={() => (showWorkLogModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button
				kind="filled"
				size="md"
				className="flex-1"
				loading={workLogSaving || previewLoading}
				disabled={workLogSaving}
				on:click={handleSaveWorkLog}
			>
				{workLogModalMode === 'add' ? $i18n.t('Preview & Send') : $i18n.t('Save')}
			</Button>
		</div>
	</div>
</Modal>

<!-- 카테고리 추가/수정 모달 -->
<Modal bind:show={showCategoryModal} size="xs">
	<div class="px-5 py-4">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
				{categoryModalMode === 'add' ? $i18n.t('New Category') : $i18n.t('Edit Category')}
			</h2>
		</div>

		<div class="space-y-3">
			<Input bind:value={categoryForm.name} label={$i18n.t('Name')} required size="md" />
			<Input
				bind:value={categoryForm.sort_order}
				type="number"
				min="0"
				label={$i18n.t('Sort Order')}
				size="md"
			/>
		</div>

		<div class="flex gap-1.5 mt-6">
			<Button kind="outlined" size="md" className="flex-1" on:click={() => (showCategoryModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" className="flex-1" loading={categorySaving} on:click={handleSaveCategory}>
				{$i18n.t('Save')}
			</Button>
		</div>
	</div>
</Modal>

<!-- 이메일 미리보기 모달 -->
<Modal bind:show={showPreviewModal} size="lg">
	<div class="px-5 py-4">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100">
				{$i18n.t('Email Preview')}
			</h2>
		</div>

		<!-- 수신자/제목 정보 -->
		<div class="mb-3 space-y-1.5">
			<div class="flex items-center gap-2 text-sm">
				<span class="flex-none text-gray-500 dark:text-gray-400 w-12">{$i18n.t('To')}:</span>
				<span class="text-gray-900 dark:text-gray-100">
					{previewRecipients.length > 0 ? previewRecipients.join(', ') : $i18n.t('No recipients configured')}
				</span>
			</div>
			<div class="flex items-center gap-2 text-sm">
				<span class="flex-none text-gray-500 dark:text-gray-400 w-12">{$i18n.t('Subject')}:</span>
				<span class="text-gray-900 dark:text-gray-100">{previewSubject}</span>
			</div>
		</div>

		<hr class="border-gray-100 dark:border-gray-800 mb-3" />

		<!-- 이메일 HTML 미리보기 -->
		<div class="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden bg-white max-h-[55vh] overflow-y-auto">
			{@html previewHtml}
		</div>

		<div class="flex gap-1.5 mt-6">
			<Button
				kind="outlined"
				size="md"
				className="flex-1"
				on:click={() => {
					if (previewMode === 'create') {
						handleBackToEdit();
					} else {
						showPreviewModal = false;
					}
				}}
			>
				{previewMode === 'create' ? $i18n.t('Back to Edit') : $i18n.t('Cancel')}
			</Button>
			<Button
				kind="filled"
				size="md"
				className="flex-1"
				loading={workLogSaving}
				on:click={handleConfirmSend}
			>
				{previewMode === 'create' ? $i18n.t('Confirm & Send') : $i18n.t('Resend')}
			</Button>
		</div>
	</div>
</Modal>
