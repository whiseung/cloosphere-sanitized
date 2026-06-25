<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';

	dayjs.extend(relativeTime);

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import PromptDiff from './PromptDiff.svelte';

	import {
		getAgentVersions,
		getAgentVersion,
		restoreAgentVersion,
		updateAgentVersionLabel
	} from '$lib/apis/models';

	const i18n: Writable<any> = getContext('i18n');

	export let show = false;
	export let agentId: string = '';
	export let canWrite: boolean = false;
	// 현재 편집 중인 값 (선택 버전과 비교용)
	export let currentSystem: string = '';
	export let currentFormat: string = '';
	// 복원 성공 시 부모(에디터)가 모델을 다시 로드하도록
	export let onRestored: (() => void) | null = null;

	let loading = false;
	let versions: any[] = [];
	let selected: any = null;
	let selectedNo: number | null = null;
	let detailLoading = false;
	let labelDraft = '';
	let showRestoreConfirm = false;
	let restoring = false;
	let lastLoadedId = '';

	const loadVersions = async () => {
		if (!agentId) return;
		loading = true;
		try {
			versions = (await getAgentVersions(localStorage.token, agentId)) || [];
			if (versions.length) {
				await selectVersion(versions[0].version_number);
			} else {
				selected = null;
				selectedNo = null;
			}
		} catch (e) {
			toast.error((e as any)?.detail || $i18n.t('Failed to load versions'));
		} finally {
			loading = false;
		}
	};

	const selectVersion = async (no: number) => {
		selectedNo = no;
		// HEAD(최신)는 현재 설정과 동일 → 상세 API 없이 현재 값으로 즉시 표시 (불필요한 직렬 호출 제거)
		if (versions.length && no === versions[0].version_number) {
			selected = {
				version_number: no,
				label: versions[0].label,
				snapshot: { params: { system: currentSystem, format_prompt: currentFormat } }
			};
			labelDraft = versions[0].label || '';
			detailLoading = false;
			return;
		}
		detailLoading = true;
		try {
			selected = await getAgentVersion(localStorage.token, agentId, no);
			labelDraft = selected?.label || '';
		} catch (e) {
			toast.error((e as any)?.detail || $i18n.t('Failed to load version'));
		} finally {
			detailLoading = false;
		}
	};

	const saveLabel = async () => {
		if (!selectedNo) return;
		try {
			const updated = await updateAgentVersionLabel(
				localStorage.token,
				agentId,
				selectedNo,
				labelDraft.trim() || null
			);
			if (updated) {
				toast.success($i18n.t('Label saved'));
				versions = versions.map((v) =>
					v.version_number === selectedNo ? { ...v, label: updated.label } : v
				);
			}
		} catch (e) {
			toast.error((e as any)?.detail || $i18n.t('Failed to save label'));
		}
	};

	const doRestore = async () => {
		if (!selectedNo) return;
		restoring = true;
		try {
			const res = await restoreAgentVersion(localStorage.token, agentId, selectedNo);
			if (res) {
				toast.success($i18n.t('Restored to v{{n}}', { n: selectedNo }));
				showRestoreConfirm = false;
				show = false;
				if (onRestored) onRestored();
			}
		} catch (e) {
			toast.error((e as any)?.detail || $i18n.t('Failed to restore version'));
		} finally {
			restoring = false;
		}
	};

	const fmt = (ts: number) => (ts ? dayjs(ts * 1000).fromNow() : '');
	const snapSystem = (s: any) => s?.snapshot?.params?.system || '';
	const snapFormat = (s: any) => s?.snapshot?.params?.format_prompt || '';

	// 모달이 열릴 때 1회 로드 (agentId 가 바뀌면 재로드)
	$: if (show && agentId && lastLoadedId !== agentId) {
		lastLoadedId = agentId;
		loadVersions();
	}
	$: if (!show) {
		lastLoadedId = '';
	}
	$: isHead = selectedNo !== null && versions.length > 0 && selectedNo === versions[0].version_number;
</script>

<Modal bind:show size="lg">
	<div class="px-5 py-4">
		<div class="flex items-center justify-between mb-4">
			<div class="text-lg font-semibold text-gray-800 dark:text-gray-100">
				{$i18n.t('Version History')}
			</div>
			<button
				class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
				on:click={() => (show = false)}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="size-5" />
			</button>
		</div>

		{#if loading}
			<div class="flex justify-center py-12"><Spinner /></div>
		{:else if versions.length === 0}
			<div class="text-sm text-gray-500 dark:text-gray-400 py-12 text-center">
				{$i18n.t('No saved versions yet')}
			</div>
		{:else}
			<div class="flex gap-4" style="height: 64vh;">
				<!-- 좌: 버전 목록 (좁게 고정) -->
				<div
					class="w-[176px] shrink-0 overflow-y-auto border-r border-gray-100 dark:border-gray-800 pr-2"
				>
					{#each versions as v (v.version_number)}
						<button
							class="w-full text-left rounded-lg px-3 py-2 mb-1 transition
								{selectedNo === v.version_number
								? 'bg-gray-100 dark:bg-gray-800'
								: 'hover:bg-gray-50 dark:hover:bg-gray-850'}"
							on:click={() => selectVersion(v.version_number)}
						>
							<div class="flex items-center gap-1.5 min-w-0">
								<span class="text-sm font-medium text-gray-800 dark:text-gray-100 shrink-0"
									>v{v.version_number}</span
								>
								{#if v.label}
									<span class="text-xs text-gray-600 dark:text-gray-300 truncate">{v.label}</span>
								{/if}
							</div>
							<div
								class="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500 mt-1"
							>
								{#if v.version_number === versions[0].version_number}
									<Badge status="info" size="sm">{$i18n.t('Current')}</Badge>
								{/if}
								<span>{fmt(v.created_at)}</span>
							</div>
						</button>
					{/each}
				</div>

				<!-- 우: 선택 버전 상세 + 비교 -->
				<div class="flex-1 overflow-y-auto pr-1">
					{#if detailLoading}
						<div class="flex justify-center py-12"><Spinner /></div>
					{:else if selected}
						<!-- 라벨 -->
						<div class="flex items-end gap-2 mb-4">
							<div class="flex-1">
								<Input
									bind:value={labelDraft}
									label={$i18n.t('Label')}
									placeholder={$i18n.t('Optional name for this version')}
									size="sm"
									disabled={!canWrite}
								/>
							</div>
							{#if canWrite}
								<Button kind="outlined" size="sm" on:click={saveLabel}>{$i18n.t('Save')}</Button>
							{/if}
						</div>

						<!-- 작업 프롬프트 비교 -->
						<div class="mb-4">
							<div class="flex items-center gap-2 mb-1">
								<span class="text-sm font-medium text-gray-700 dark:text-gray-200"
									>{$i18n.t('Task Prompt')}</span
								>
								{#if snapSystem(selected) !== currentSystem}
									<Badge status="warning" size="sm">{$i18n.t('Differs from current')}</Badge>
								{/if}
							</div>
							<PromptDiff
								before={snapSystem(selected)}
								after={currentSystem}
								maxHeight="300px"
								single={isHead}
							/>
						</div>

						<!-- 답변 포맷 프롬프트 비교 -->
						<div class="mb-4">
							<div class="flex items-center gap-2 mb-1">
								<span class="text-sm font-medium text-gray-700 dark:text-gray-200"
									>{$i18n.t('Response Format Prompt')}</span
								>
								{#if snapFormat(selected) !== currentFormat}
									<Badge status="warning" size="sm">{$i18n.t('Differs from current')}</Badge>
								{/if}
							</div>
							<PromptDiff
								before={snapFormat(selected)}
								after={currentFormat}
								maxHeight="180px"
								single={isHead}
							/>
						</div>

						<!-- 복원 -->
						{#if canWrite}
							<div class="flex justify-end pt-2 border-t border-gray-100 dark:border-gray-800">
								<Button
									kind="filled"
									size="md"
									disabled={isHead || restoring}
									loading={restoring}
									on:click={() => (showRestoreConfirm = true)}
								>
									{isHead ? $i18n.t('This is the current version') : $i18n.t('Restore this version')}
								</Button>
							</div>
						{/if}
					{/if}
				</div>
			</div>
		{/if}
	</div>
</Modal>

<ConfirmDialog
	bind:show={showRestoreConfirm}
	title={$i18n.t('Restore this version?')}
	message={$i18n.t(
		'The current settings will be saved as a new version, then replaced with v{{n}}. Sharing permissions are kept as-is.',
		{ n: selectedNo }
	)}
	on:confirm={doRestore}
/>
