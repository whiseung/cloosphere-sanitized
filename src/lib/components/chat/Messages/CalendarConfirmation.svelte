<script lang="ts">
	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		confirmCalendarCreate,
		type CalendarConfirmResponse
	} from '$lib/apis/google-actions';
	import { searchOrganizationMembers } from '$lib/apis/users';

	import CalendarSolid from '$lib/components/icons/CalendarSolid.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	type AttendeeMeta = {
		email: string;
		is_external: boolean;
	};

	type Payload = {
		message_id: string;
		risk_level: 'low' | 'high';
		draft: {
			title: string;
			description?: string;
			start: string; // ISO 8601 naive ('2026-05-20T10:00:00')
			end: string;
			timezone: string; // IANA ('Asia/Seoul')
			attendees?: Array<{ email: string }>;
			send_updates: 'all' | 'externalOnly' | 'none';
			create_meet: boolean;
		};
		attendees_meta?: AttendeeMeta[];
	};

	export let payload: Payload;
	export let conversationId: string | null = null;

	// ---------- Editable draft state ----------
	let draftTitle = payload.draft.title || '';
	let draftDescription = payload.draft.description || '';
	let draftStart = payload.draft.start || '';
	let draftEnd = payload.draft.end || '';
	let draftTimezone = payload.draft.timezone || 'UTC';
	let draftAttendees: string[] = (payload.draft.attendees || []).map((a) => a.email);
	let draftSendUpdates: 'all' | 'externalOnly' | 'none' =
		payload.draft.send_updates ?? 'all';
	let draftCreateMeet: boolean = payload.draft.create_meet ?? false;

	let attendeeInput = '';

	// Risk-level (anti cargo-cult, plan §5.9).
	$: requiresExplicitConfirm = payload.risk_level === 'high';
	let confirmToggle = false;

	// Cooldown (5초, plan §5.9).
	let cooldownActive = false;

	// 발송 상태.
	let sending = false;
	let finalState: '' | 'created' | 'already_created' | 'previously_failed' | 'error' = '';
	let finalMessage = '';
	let resultLink = '';

	// start < end 검증.
	$: startEndValid = isStartBeforeEnd(draftStart, draftEnd);

	function isStartBeforeEnd(s: string, e: string): boolean {
		if (!s || !e) return false;
		// datetime-local 값은 naive ISO ("2026-05-20T10:00").  lexicographic 비교 가능.
		return s < e;
	}

	$: canSend =
		!sending &&
		!cooldownActive &&
		finalState === '' &&
		draftTitle.trim().length > 0 &&
		startEndValid &&
		(!requiresExplicitConfirm || confirmToggle);

	// ---------- attendees_meta lookup ----------
	const attendeeIndex: Record<string, AttendeeMeta> = {};
	for (const m of payload.attendees_meta || []) {
		attendeeIndex[m.email] = m;
	}

	function domainOf(email: string): string {
		const at = email.lastIndexOf('@');
		return at >= 0 ? email.slice(at + 1).toLowerCase() : '';
	}

	function isExternal(email: string): boolean {
		const meta = attendeeIndex[email];
		if (meta) return meta.is_external;
		return true; // 안전 default
	}

	// ---------- 참석자 chip 조작 ----------
	function addAttendee() {
		const v = (attendeeInput || '').trim();
		if (!v) return;
		if (!v.includes('@')) {
			toast.error($i18n.t('Invalid email address'));
			return;
		}
		if (draftAttendees.includes(v)) {
			attendeeInput = '';
			return;
		}
		draftAttendees = [...draftAttendees, v];
		attendeeInput = '';
	}

	function removeAttendee(email: string) {
		draftAttendees = draftAttendees.filter((e) => e !== email);
	}

	function attendeeKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ',') {
			e.preventDefault();
			if (showUserDropdown && userResults.length > 0) {
				selectUser(userResults[0]); // 드롭다운에 매칭이 있으면 첫 항목 선택
			} else {
				addAttendee(); // 외부 이메일 직접입력
			}
		}
		if (e.key === 'Escape') {
			showUserDropdown = false;
			userResults = [];
		}
	}

	// ---------- 참석자 자동완성 ----------
	let userResults: Array<{
		id: string;
		name: string;
		email: string;
		job_title?: string;
		profile_image_url?: string;
	}> = [];
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let showUserDropdown = false;
	let searchSeq = 0;

	function onAttendeeInput() {
		showUserDropdown = true;
		if (searchTimer) clearTimeout(searchTimer);
		const q = (attendeeInput || '').trim();
		if (!q) {
			userResults = [];
			return;
		}
		const seq = ++searchSeq;
		searchTimer = setTimeout(async () => {
			try {
				const results = await searchOrganizationMembers(localStorage.token, q);
				if (seq !== searchSeq) return; // 더 최신 검색이 있으면 폐기
				userResults = (results || []).filter(
					(u: { email: string }) => u.email && !draftAttendees.includes(u.email)
				);
			} catch (e) {
				if (seq === searchSeq) userResults = [];
			}
		}, 250);
	}

	onDestroy(() => {
		if (searchTimer) clearTimeout(searchTimer);
	});

	function selectUser(u: { email: string }) {
		if (u.email && !draftAttendees.includes(u.email)) {
			draftAttendees = [...draftAttendees, u.email];
		}
		attendeeInput = '';
		userResults = [];
		showUserDropdown = false;
	}

	function closeUserDropdown() {
		// 드롭다운에서 선택 중이 아니라 직접 타이핑한 이메일이면 blur 시 커밋(기존 동작 보존).
		// 드롭다운 항목 클릭 시에는 blur 가 먼저 발생하지만 userResults 가 남아 있어 스킵되고,
		// 이어지는 selectUser 가 처리한다.
		if (attendeeInput.trim() && userResults.length === 0) {
			addAttendee();
		}
		setTimeout(() => {
			showUserDropdown = false;
		}, 150);
	}

	// ---------- Send updates 세그먼트 라벨 ----------
	const SEND_UPDATES_OPTIONS: Array<'all' | 'externalOnly' | 'none'> = [
		'all',
		'externalOnly',
		'none'
	];

	function sendUpdatesLabel(value: 'all' | 'externalOnly' | 'none'): string {
		if (value === 'all') return $i18n.t('Notify all attendees');
		if (value === 'externalOnly') return $i18n.t('Notify external only');
		return $i18n.t("Don't notify");
	}

	// ---------- Submit / Cancel ----------
	async function handleCreate() {
		if (!canSend) return;
		sending = true;
		cooldownActive = true;
		try {
			const result: CalendarConfirmResponse = await confirmCalendarCreate(
				localStorage.token,
				payload.message_id,
				{
					title: draftTitle,
					description: draftDescription || null,
					start: draftStart,
					end: draftEnd,
					timezone: draftTimezone,
					attendees: draftAttendees.length ? draftAttendees : null,
					send_updates: draftSendUpdates,
					create_meet: draftCreateMeet,
					conversation_id: conversationId
				}
			);
			finalState = result.status;
			resultLink = result.html_link || '';
			if (result.status === 'created') {
				finalMessage = $i18n.t('Event created successfully');
				toast.success(finalMessage);
			} else if (result.status === 'already_created') {
				finalMessage = $i18n.t('Event was already created earlier');
				toast.info(finalMessage);
			} else {
				finalMessage =
					result.error ||
					$i18n.t('Previous attempt failed; please start a new draft.');
				toast.warning(finalMessage);
			}
			dispatch('confirmed', result);
		} catch (e) {
			finalState = 'error';
			finalMessage =
				(e as { detail?: string; message?: string })?.detail ||
				(e as { message?: string })?.message ||
				$i18n.t('Failed to create event');
			toast.error(finalMessage);
		} finally {
			sending = false;
			setTimeout(() => {
				cooldownActive = false;
			}, 5000);
		}
	}

	function handleCancel() {
		finalState = 'previously_failed';
		finalMessage = $i18n.t('Event creation cancelled');
		toast.info(finalMessage);
		dispatch('cancelled');
	}

	// datetime-local input 은 분 단위까지만 지원 → backend 의 초 포함 ISO 와 호환되도록
	// 표시할 때 초 제거.
	function trimSeconds(iso: string): string {
		// ``2026-05-20T10:00:00`` → ``2026-05-20T10:00``
		if (!iso) return '';
		const m = iso.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(:\d{2})?/);
		return m ? m[1] : iso;
	}
	// 초기 normalize (한 번만).
	draftStart = trimSeconds(draftStart);
	draftEnd = trimSeconds(draftEnd);
</script>

<div
	class="my-3 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 shadow-sm"
>
	<!-- Header -->
	<div class="flex items-center gap-2 mb-3">
		<div class="shrink-0 text-[var(--cloo-color-accent)]">
			<CalendarSolid className="size-5" />
		</div>
		<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
			{$i18n.t('Confirm Event')}
		</h3>
		{#if payload.risk_level === 'high'}
			<span
				class="ml-auto text-xs px-2 py-0.5 rounded-full bg-[var(--cloo-color-accent-soft)] text-[var(--cloo-color-accent)]"
			>
				{$i18n.t('Review required')}
			</span>
		{/if}
	</div>

	{#if finalState}
		<div
			class="text-sm py-3 text-center {finalState === 'created'
				? 'text-green-600 dark:text-green-400'
				: finalState === 'error'
					? 'text-red-600 dark:text-red-400'
					: 'text-gray-600 dark:text-gray-400'}"
		>
			{finalMessage}
			{#if resultLink}
				<div class="mt-1">
					<a
						href={resultLink}
						target="_blank"
						rel="noopener noreferrer"
						class="text-xs text-[var(--cloo-color-accent)] hover:underline"
					>
						{$i18n.t('Open in Google Calendar')}
					</a>
				</div>
			{/if}
		</div>
	{:else}
		<div class="space-y-3">
			<!-- Title -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Title')}
				</div>
				<input
					type="text"
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)]"
					bind:value={draftTitle}
				/>
			</div>

			<!-- Start / End -->
			<div class="grid grid-cols-2 gap-3">
				<div>
					<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
						{$i18n.t('Start')}
					</div>
					<input
						type="datetime-local"
						class="w-full text-sm px-3 py-2 rounded-lg border bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden {startEndValid ||
						!draftStart ||
						!draftEnd
							? 'border-gray-200 dark:border-gray-700 focus:border-[var(--cloo-color-accent)]'
							: 'border-red-400 dark:border-red-500'}"
						bind:value={draftStart}
					/>
				</div>
				<div>
					<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
						{$i18n.t('End')}
					</div>
					<input
						type="datetime-local"
						class="w-full text-sm px-3 py-2 rounded-lg border bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden {startEndValid ||
						!draftStart ||
						!draftEnd
							? 'border-gray-200 dark:border-gray-700 focus:border-[var(--cloo-color-accent)]'
							: 'border-red-400 dark:border-red-500'}"
						bind:value={draftEnd}
					/>
				</div>
			</div>
			{#if draftStart && draftEnd && !startEndValid}
				<div class="text-xs text-red-600 dark:text-red-400">
					{$i18n.t('Start must be before End')}
				</div>
			{/if}

			<!-- Timezone -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Timezone')}
				</div>
				<input
					type="text"
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)]"
					placeholder="Asia/Seoul"
					bind:value={draftTimezone}
				/>
				<div class="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
					{$i18n.t('IANA timezone ID only (e.g. Asia/Seoul, America/New_York).')}
				</div>
			</div>

			<!-- Attendees -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Attendees')}
				</div>
				<div class="relative">
					<div
						class="flex flex-wrap gap-1.5 items-center px-2 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
					>
						{#each draftAttendees as email}
							<span
								class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs {isExternal(
									email
								)
									? 'bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200 border border-amber-200 dark:border-amber-800'
									: 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200'}"
							>
								<span>{email}</span>
								<span class="text-[10px] opacity-70">
									@{domainOf(email)} ({isExternal(email)
										? $i18n.t('external')
										: $i18n.t('internal')})
								</span>
								<button
									type="button"
									class="opacity-70 hover:opacity-100"
									on:click={() => removeAttendee(email)}
									aria-label={$i18n.t('Remove')}
								>
									<XMark className="size-3" />
								</button>
							</span>
						{/each}
						<input
							type="text"
							placeholder={$i18n.t('Add attendee (name or email)')}
							class="flex-1 min-w-[150px] text-xs bg-transparent outline-hidden px-1 py-0.5 text-gray-900 dark:text-gray-100"
							bind:value={attendeeInput}
							on:keydown={attendeeKeydown}
							on:input={onAttendeeInput}
							on:focus={() => (showUserDropdown = true)}
							on:blur={closeUserDropdown}
						/>
					</div>
					{#if showUserDropdown && userResults.length > 0}
						<div
							class="absolute z-10 mt-1 w-full max-h-56 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg"
						>
							{#each userResults as u (u.id)}
								<button
									type="button"
									class="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700"
									on:click={() => selectUser(u)}
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
						</div>
					{/if}
				</div>
			</div>

			<!-- Send updates (3-option button group) -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Notify attendees')}
				</div>
				<div class="flex gap-1 text-xs">
					{#each SEND_UPDATES_OPTIONS as opt}
						<button
							type="button"
							class="flex-1 px-3 py-1.5 rounded-lg border transition {draftSendUpdates === opt
								? 'bg-[var(--cloo-color-accent-soft)] border-[var(--cloo-color-accent)] text-[var(--cloo-color-accent)]'
								: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'}"
							on:click={() => (draftSendUpdates = opt)}
						>
							{sendUpdatesLabel(opt)}
						</button>
					{/each}
				</div>
			</div>

			<!-- Create Meet toggle -->
			<div class="flex items-center justify-between gap-3 text-xs">
				<div>
					<div class="font-medium text-gray-700 dark:text-gray-300">
						{$i18n.t('Add Google Meet link')}
					</div>
					<div class="text-[11px] text-gray-500 dark:text-gray-400">
						{$i18n.t(
							'Meet link is generated asynchronously and may not appear immediately.'
						)}
					</div>
				</div>
				<Switch bind:state={draftCreateMeet} />
			</div>

			<!-- Description -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Description')}
				</div>
				<textarea
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)] resize-y min-h-[80px]"
					bind:value={draftDescription}
				></textarea>
			</div>

			<!-- High-risk 2-click confirm toggle -->
			{#if requiresExplicitConfirm}
				<div
					class="flex items-center gap-3 text-xs text-gray-800 dark:text-gray-200 bg-[var(--cloo-color-accent-soft)] rounded-lg p-3 border border-[var(--cloo-color-accent)]"
				>
					<Switch bind:state={confirmToggle} />
					<span>
						{$i18n.t(
							'I have reviewed the attendees and details above and want to create this event.'
						)}
					</span>
				</div>
			{/if}

			<!-- Actions -->
			<div class="flex justify-end gap-2 pt-1">
				<button
					type="button"
					class="text-sm px-4 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 disabled:opacity-50"
					on:click={handleCancel}
					disabled={sending}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					type="button"
					class="text-sm px-4 py-1.5 rounded-lg bg-[var(--cloo-color-accent)] hover:bg-[var(--cloo-color-accent-hover)] text-white disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:text-gray-500 dark:disabled:text-gray-400 disabled:cursor-not-allowed"
					on:click={handleCreate}
					disabled={!canSend}
				>
					{#if sending}
						{$i18n.t('Creating...')}
					{:else if cooldownActive && finalState === ''}
						{$i18n.t('Please wait...')}
					{:else}
						{$i18n.t('Create Event')}
					{/if}
				</button>
			</div>
		</div>
	{/if}
</div>
