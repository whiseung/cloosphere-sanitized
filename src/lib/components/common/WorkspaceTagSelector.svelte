<script lang="ts">
	import { onMount, getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { workspaceTags, user } from '$lib/stores';
	import {
		getWorkspaceTags,
		createWorkspaceTag,
		getResourceTags,
		assignTag,
		unassignTag,
		type WorkspaceTag
	} from '$lib/apis/workspace-tags';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let resourceType: string;
	export let resourceId: string;

	// 새 태그 생성 권한: workspace.tags === 'write' (admin 포함). read 권한자는 기존 태그 어사인만 가능.
	$: canCreateTag = $user?.role === 'admin' || $user?.permissions?.workspace?.tags === 'write';

	// 원본 (DB에 저장된 상태)
	let originalTagIds: string[] = [];
	// 현재 로컬 상태 (사용자가 추가/제거한 결과)
	let currentTags: WorkspaceTag[] = [];

	$: availableTags = ($workspaceTags ?? []).filter(
		(t: WorkspaceTag) => !currentTags.some((c) => c.id === t.id)
	);

	let showInput = false;
	let newTagName = '';

	const loadTags = async () => {
		if (!resourceId) return;
		try {
			const tags = await getResourceTags(localStorage.token, resourceType, resourceId);
			currentTags = tags;
			originalTagIds = tags.map((t) => t.id);
			workspaceTags.set(await getWorkspaceTags(localStorage.token));
		} catch (e) {
			console.error('Failed to load workspace tags:', e);
		}
	};

	/** 로컬에서 태그 추가 (API 호출 안 함) */
	const addTagLocally = (tag: WorkspaceTag) => {
		if (!currentTags.some((t) => t.id === tag.id)) {
			currentTags = [...currentTags, tag];
			dispatch('change', currentTags);
		}
	};

	/** 로컬에서 태그 제거 (API 호출 안 함) */
	const removeTagLocally = (tagId: string) => {
		currentTags = currentTags.filter((t) => t.id !== tagId);
		dispatch('change', currentTags);
	};

	const submitTag = async () => {
		const name = newTagName.trim();
		if (!name) return;

		// 기존 태그 중 이름 매칭
		const existing = ($workspaceTags ?? []).find(
			(t: WorkspaceTag) => t.name.toLowerCase() === name.toLowerCase()
		);

		if (existing) {
			addTagLocally(existing);
		} else if (!canCreateTag) {
			// read 권한자: 새 태그 생성 차단, 기존 태그만 어사인 가능
			toast.error(
				$i18n.t('No permission to create new tags. Pick an existing tag or contact admin.')
			);
		} else {
			// 새 태그는 즉시 생성 (태그 자체는 공용이므로)
			try {
				const tag = await createWorkspaceTag(localStorage.token, name);
				if (tag) {
					workspaceTags.set(await getWorkspaceTags(localStorage.token));
					addTagLocally(tag);
				}
			} catch (e) {
				toast.error($i18n.t(`${e}`));
			}
		}

		newTagName = '';
		showInput = false;
	};

	/**
	 * 부모 폼에서 Save 시 호출.
	 * 로컬 상태와 원본을 비교하여 추가/제거 API 호출.
	 */
	export const commitChanges = async () => {
		// 입력 중인 태그가 있으면 먼저 제출
		if (newTagName.trim()) {
			await submitTag();
		}

		const currentIds = currentTags.map((t) => t.id);
		const toAssign = currentIds.filter((id) => !originalTagIds.includes(id));
		const toUnassign = originalTagIds.filter((id) => !currentIds.includes(id));

		for (const tagId of toAssign) {
			await assignTag(localStorage.token, resourceType, resourceId, tagId);
		}
		for (const tagId of toUnassign) {
			await unassignTag(localStorage.token, resourceType, resourceId, tagId);
		}

		originalTagIds = [...currentIds];
	};

	/** 부모 폼에서 Cancel 시 호출. 원본 상태로 복구. */
	export const resetChanges = () => {
		currentTags = currentTags.filter((t) => originalTagIds.includes(t.id));
		// 원본에 있었는데 제거된 것 복구
		const allTags = $workspaceTags ?? [];
		for (const id of originalTagIds) {
			if (!currentTags.some((t) => t.id === id)) {
				const tag = allTags.find((t: WorkspaceTag) => t.id === id);
				if (tag) currentTags = [...currentTags, tag];
			}
		}
	};

	$: if (resourceId) {
		loadTags();
	}
</script>

<div class="flex items-center gap-1 flex-wrap">
	{#each currentTags as tag (tag.id)}
		<span
			class="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full
				bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
		>
			{tag.name}
			<button
				type="button"
				class="hover:text-red-500 transition"
				on:click|stopPropagation={() => removeTagLocally(tag.id)}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
					<path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
				</svg>
			</button>
		</span>
	{/each}

	{#if showInput}
		<div class="flex items-center gap-0.5">
			<input
				class="px-2 py-0.5 text-xs bg-transparent outline-hidden border border-gray-200 dark:border-gray-700 rounded-full w-24"
				placeholder={canCreateTag ? $i18n.t('New tag...') : $i18n.t('Pick an existing tag')}
				bind:value={newTagName}
				autocomplete="off"
				list="workspace-tag-options-{resourceId}"
				on:keydown={(e) => {
					if (e.key === 'Enter') {
						e.preventDefault();
						e.stopPropagation();
						submitTag();
					} else if (e.key === 'Escape') {
						showInput = false;
						newTagName = '';
					}
				}}
			/>
			<button
				type="button"
				class="p-0.5 text-gray-400 hover:text-green-600 dark:hover:text-green-400 transition"
				on:click|stopPropagation={submitTag}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
					<path fill-rule="evenodd" d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z" clip-rule="evenodd" />
				</svg>
			</button>
			<datalist id="workspace-tag-options-{resourceId}">
				{#each availableTags as tag}
					<option value={tag.name} />
				{/each}
			</datalist>
		</div>
	{/if}

	<button
		type="button"
		class="p-0.5 rounded-full border border-dashed border-gray-300 dark:border-gray-600
			hover:bg-gray-100 dark:hover:bg-gray-800 transition"
		on:click|stopPropagation={() => {
			showInput = !showInput;
		}}
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 16 16"
			fill="currentColor"
			class="size-3 {showInput ? 'rotate-45' : ''} transition-transform"
		>
			<path d="M8.75 3.75a.75.75 0 0 0-1.5 0v3.5h-3.5a.75.75 0 0 0 0 1.5h3.5v3.5a.75.75 0 0 0 1.5 0v-3.5h3.5a.75.75 0 0 0 0-1.5h-3.5v-3.5Z" />
		</svg>
	</button>
</div>
