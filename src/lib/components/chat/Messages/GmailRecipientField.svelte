<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { searchOrganizationMembers } from '$lib/apis/users';

	import XMark from '$lib/components/icons/XMark.svelte';
	import UsersSolid from '$lib/components/icons/UsersSolid.svelte';

	const i18n = getContext('i18n');

	// 수신자 토큰 — 개별 이메일 또는 그룹/부서 참조(발송 시 멤버 이메일로 펼침).
	// 단일 칩으로 표시되어 그룹/부서를 통째로 제거하기 쉽다.
	type Recipient = {
		type: 'email' | 'group' | 'unit';
		value?: string; // email 일 때
		id?: string; // group/unit 일 때
		name?: string; // group/unit 일 때
		count?: number; // group/unit 멤버 수(표시용)
	};

	export let label: string = '';
	export let recipients: Recipient[] = [];
	export let groups: Array<{ id: string; name: string; user_ids?: string[] }> = [];
	export let units: Array<{
		id: string;
		name: string;
		member_ids?: string[];
		meta?: { members?: unknown[] };
	}> = [];
	export let isExternal: (email: string) => boolean = () => true;
	export let placeholder: string = '';

	type UserResult = {
		id: string;
		name: string;
		email: string;
		job_title?: string;
		profile_image_url?: string;
	};
	type EntityResult = { id: string; name: string; count: number };

	let input = '';
	let userResults: UserResult[] = [];
	let groupResults: EntityResult[] = [];
	let unitResults: EntityResult[] = [];
	let showDropdown = false;
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let searchSeq = 0;

	function hasEmail(email: string): boolean {
		return recipients.some((r) => r.type === 'email' && r.value === email);
	}
	function hasEntity(type: string, id: string): boolean {
		return recipients.some((r) => r.type === type && r.id === id);
	}

	function tokenKey(r: Recipient): string {
		return r.type === 'email' ? `e:${r.value}` : `${r.type}:${r.id}`;
	}

	function addEmail(raw: string): boolean {
		const v = (raw || '').trim().replace(/,$/, '');
		if (!v) return false;
		if (!v.includes('@')) {
			toast.error($i18n.t('Invalid email address'));
			return false;
		}
		if (!hasEmail(v)) recipients = [...recipients, { type: 'email', value: v }];
		return true;
	}

	function addEntity(type: 'group' | 'unit', e: EntityResult) {
		if (!hasEntity(type, e.id)) {
			recipients = [...recipients, { type, id: e.id, name: e.name, count: e.count }];
		}
	}

	function removeAt(idx: number) {
		recipients = recipients.filter((_, i) => i !== idx);
	}

	function resetInput() {
		input = '';
		userResults = [];
		groupResults = [];
		unitResults = [];
		showDropdown = false;
	}

	function unitCount(u: { member_ids?: string[]; meta?: { members?: unknown[] } }): number {
		const metaLen = u.meta && Array.isArray(u.meta.members) ? u.meta.members.length : 0;
		return metaLen || (u.member_ids ? u.member_ids.length : 0);
	}

	function onInput() {
		showDropdown = true;
		if (searchTimer) clearTimeout(searchTimer);
		const q = (input || '').trim();
		if (!q) {
			userResults = [];
			groupResults = [];
			unitResults = [];
			return;
		}
		const ql = q.toLowerCase();
		groupResults = (groups || [])
			.filter((g) => (g.name || '').toLowerCase().includes(ql))
			.map((g) => ({ id: g.id, name: g.name, count: (g.user_ids || []).length }))
			.slice(0, 5);
		unitResults = (units || [])
			.filter((u) => (u.name || '').toLowerCase().includes(ql))
			.map((u) => ({ id: u.id, name: u.name, count: unitCount(u) }))
			.slice(0, 5);
		const seq = ++searchSeq;
		searchTimer = setTimeout(async () => {
			try {
				const results = await searchOrganizationMembers(localStorage.token, q);
				if (seq !== searchSeq) return;
				userResults = (results || []).filter(
					(u: { email: string }) => u.email && !hasEmail(u.email)
				);
			} catch (e) {
				if (seq === searchSeq) userResults = [];
			}
		}, 250);
	}

	function selectUser(u: UserResult) {
		addEmail(u.email);
		resetInput();
	}
	function selectGroup(g: EntityResult) {
		addEntity('group', g);
		resetInput();
	}
	function selectUnit(u: EntityResult) {
		addEntity('unit', u);
		resetInput();
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ',') {
			e.preventDefault();
			if (groupResults.length > 0) selectGroup(groupResults[0]);
			else if (unitResults.length > 0) selectUnit(unitResults[0]);
			else if (userResults.length > 0) selectUser(userResults[0]);
			else if (addEmail(input)) resetInput();
		} else if (e.key === 'Escape') {
			showDropdown = false;
		}
	}

	function onBlur() {
		if (
			input.trim() &&
			groupResults.length === 0 &&
			unitResults.length === 0 &&
			userResults.length === 0
		) {
			if (addEmail(input)) resetInput();
		}
		setTimeout(() => (showDropdown = false), 150);
	}

	onDestroy(() => {
		if (searchTimer) clearTimeout(searchTimer);
	});
</script>

<div>
	<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
		{label}
	</div>
	<div class="relative">
		<div
			class="flex flex-wrap gap-1.5 items-center px-2 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
		>
			{#each recipients as r, i (tokenKey(r))}
				{#if r.type === 'email'}
					<span
						class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs {isExternal(
							r.value || ''
						)
							? 'bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200 border border-amber-200 dark:border-amber-800'
							: 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200'}"
					>
						<span>{r.value}</span>
						<span class="text-[10px] opacity-70">
							({isExternal(r.value || '') ? $i18n.t('external') : $i18n.t('internal')})
						</span>
						<button
							type="button"
							class="opacity-70 hover:opacity-100"
							on:click={() => removeAt(i)}
							aria-label={$i18n.t('Remove')}
						>
							<XMark className="size-3" />
						</button>
					</span>
				{:else}
					<span
						class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border {r.type ===
						'group'
							? 'bg-blue-50 dark:bg-blue-900/30 text-blue-800 dark:text-blue-200 border-blue-200 dark:border-blue-800'
							: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-200 border-emerald-200 dark:border-emerald-800'}"
					>
						<UsersSolid className="size-3" />
						<span>{r.name}</span>
						<span class="text-[10px] opacity-80">{$i18n.t('{{count}} member(s)', { count: r.count || 0 })}</span>
						<button
							type="button"
							class="opacity-70 hover:opacity-100"
							on:click={() => removeAt(i)}
							aria-label={$i18n.t('Remove')}
						>
							<XMark className="size-3" />
						</button>
					</span>
				{/if}
			{/each}
			<input
				type="text"
				{placeholder}
				class="flex-1 min-w-[150px] text-xs bg-transparent outline-hidden px-1 py-0.5 text-gray-900 dark:text-gray-100"
				bind:value={input}
				on:keydown={onKeydown}
				on:input={onInput}
				on:focus={() => (showDropdown = true)}
				on:blur={onBlur}
			/>
		</div>
		{#if showDropdown && (groupResults.length > 0 || unitResults.length > 0 || userResults.length > 0)}
			<div
				class="absolute z-10 mt-1 w-full max-h-60 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg"
			>
				{#if groupResults.length > 0}
					<div
						class="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500"
					>
						{$i18n.t('Groups')}
					</div>
					{#each groupResults as g (g.id)}
						<button
							type="button"
							class="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700"
							on:mousedown|preventDefault={() => selectGroup(g)}
						>
							<div
								class="shrink-0 size-6 rounded-full flex items-center justify-center bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-300"
							>
								<UsersSolid className="size-3.5" />
							</div>
							<div class="min-w-0 flex-1">
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
									{g.name}
								</div>
								<div class="text-xs text-gray-500 dark:text-gray-400">
									{$i18n.t('{{count}} member(s)', { count: g.count })}
								</div>
							</div>
						</button>
					{/each}
				{/if}
				{#if unitResults.length > 0}
					{#if groupResults.length > 0}
						<div class="border-t border-gray-100 dark:border-gray-700"></div>
					{/if}
					<div
						class="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500"
					>
						{$i18n.t('Departments')}
					</div>
					{#each unitResults as u (u.id)}
						<button
							type="button"
							class="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700"
							on:mousedown|preventDefault={() => selectUnit(u)}
						>
							<div
								class="shrink-0 size-6 rounded-full flex items-center justify-center bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-300"
							>
								<UsersSolid className="size-3.5" />
							</div>
							<div class="min-w-0 flex-1">
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
									{u.name}
								</div>
								<div class="text-xs text-gray-500 dark:text-gray-400">
									{$i18n.t('{{count}} member(s)', { count: u.count })}
								</div>
							</div>
						</button>
					{/each}
				{/if}
				{#if userResults.length > 0}
					{#if groupResults.length > 0 || unitResults.length > 0}
						<div class="border-t border-gray-100 dark:border-gray-700"></div>
					{/if}
					<div
						class="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500"
					>
						{$i18n.t('People')}
					</div>
					{#each userResults as u (u.id)}
						<button
							type="button"
							class="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700"
							on:mousedown|preventDefault={() => selectUser(u)}
						>
							<img
								src={u.profile_image_url || '/user.png'}
								alt={u.name}
								class="size-6 rounded-full object-cover"
							/>
							<div class="min-w-0">
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
									{u.name}
								</div>
								<div class="text-xs text-gray-500 dark:text-gray-400 truncate">
									{u.email}{u.job_title ? ` · ${u.job_title}` : ''}
								</div>
							</div>
						</button>
					{/each}
				{/if}
			</div>
		{/if}
	</div>
</div>
