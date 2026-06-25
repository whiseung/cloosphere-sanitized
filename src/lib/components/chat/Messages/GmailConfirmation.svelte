<script lang="ts">
	import { getContext, createEventDispatcher, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		confirmGmailSend,
		type GmailConfirmResponse
	} from '$lib/apis/google-actions';
	import { getGroups, getGroupMemberEmails } from '$lib/apis/groups';
	import { getOrganizationalUnits, getOrgUnitMemberEmails } from '$lib/apis/organizations';
	import { formatBackendError } from '$lib/utils/error';

	import EnvelopeSolid from '$lib/components/icons/EnvelopeSolid.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import GmailRecipientField from './GmailRecipientField.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	type RecipientMeta = {
		email: string;
		domain: string;
		is_external: boolean;
	};

	type Payload = {
		message_id: string;
		risk_level: 'low' | 'high';
		draft: {
			to: string[];
			cc?: string[];
			bcc?: string[];
			subject: string;
			body: string;
			in_reply_to?: string | null;
		};
		recipients_meta?: RecipientMeta[];
	};

	export let payload: Payload;
	export let conversationId: string | null = null;

	// 수신자 토큰 — 개별 이메일 또는 그룹/부서 참조(발송 시 멤버 이메일로 펼침).
	type Recipient = {
		type: 'email' | 'group' | 'unit';
		value?: string;
		id?: string;
		name?: string;
		count?: number;
	};
	const toToken = (e: string): Recipient => ({ type: 'email', value: e });

	// Editable draft state — payload 의 draft 를 토큰으로 변환해 안전 편집.
	let draftTo: Recipient[] = (payload.draft.to || []).map(toToken);
	let draftCc: Recipient[] = (payload.draft.cc || []).map(toToken);
	let draftBcc: Recipient[] = (payload.draft.bcc || []).map(toToken);
	let draftSubject: string = payload.draft.subject || '';
	let draftBody: string = payload.draft.body || '';

	let showCcBcc = draftCc.length > 0 || draftBcc.length > 0;

	// 그룹/부서 자동완성용 — 본인이 볼 수 있는 그룹·부서 목록을 한 번 받아둔다.
	let groups: Array<{ id: string; name: string; user_ids?: string[] }> = [];
	let units: Array<{
		id: string;
		name: string;
		member_ids?: string[];
		meta?: { members?: unknown[] };
	}> = [];
	onMount(async () => {
		try {
			groups = (await getGroups(localStorage.token)) || [];
		} catch (e) {
			groups = [];
		}
		try {
			units = (await getOrganizationalUnits(localStorage.token)) || [];
		} catch (e) {
			units = [];
		}
	});

	// Risk-level 분기 (plan §5.9 anti cargo-cult).
	// 백엔드 초기 risk_level 'high' 이거나, 사용자가 카드에서 편집한 현재 수신자에
	// 외부 주소(또는 그룹/부서 토큰)가 하나라도 있으면 명시 확인을 요구한다.
	// 수신자 빈칸으로 시작(예: 모델이 수신자 미상으로 호출)해 외부를 채워 넣어도
	// 2-클릭 확인이 빠지지 않도록 reactive 재평가.  isExternal 는 신규 주소를 보수적
	// 으로 external 처리하므로, 사용자가 직접 추가한 주소는 기본적으로 확인을 요구.
	$: requiresExplicitConfirm =
		payload.risk_level === 'high' ||
		[...draftTo, ...draftCc, ...draftBcc].some((r) =>
			r.type === 'email' ? !!r.value && isExternal(r.value) : true
		);
	let confirmToggle = false;

	// Cooldown (plan §5.9 — 동일 confirm 후 5초 동안 재발송 차단).
	let cooldownActive = false;

	// 발송 상태.
	let sending = false;
	let finalState: '' | 'sent' | 'already_sent' | 'previously_failed' | 'error' = '';
	let finalMessage = '';

	$: canSend =
		!sending &&
		!cooldownActive &&
		finalState === '' &&
		draftTo.length > 0 &&
		draftSubject.trim().length > 0 &&
		(!requiresExplicitConfirm || confirmToggle);

	// ---------- Domain / is_external resolution ----------
	// payload.recipients_meta 는 tool 호출 시점 원본만 — 사용자가 새로 추가한
	// 주소는 여기에 없음.  그런 주소는 fallback 도메인 추출 후 보수적으로 external 처리.
	const metaIndex: Record<string, RecipientMeta> = {};
	for (const m of payload.recipients_meta || []) {
		metaIndex[m.email] = m;
	}

	function isExternal(email: string): boolean {
		const meta = metaIndex[email];
		if (meta) return meta.is_external;
		// 새로 추가된 주소 — backend 의 internal 도메인 list 를 우리가 모르므로
		// 안전 default = external 표시.
		return true;
	}

	// 그룹/부서 토큰이 하나라도 있으면 "발송 시 펼침" 안내 노출.
	$: hasEntityToken = [...draftTo, ...draftCc, ...draftBcc].some((r) => r.type !== 'email');

	// 발송 직전 토큰 → 실제 이메일 목록으로 펼침 (그룹/부서 멤버 fetch + dedup).
	async function resolveRecipients(list: Recipient[]): Promise<string[]> {
		const out = new Set<string>();
		for (const r of list) {
			if (r.type === 'email' && r.value) {
				out.add(r.value);
			} else if (r.type === 'group' && r.id) {
				const members = await getGroupMemberEmails(localStorage.token, r.id);
				for (const m of members) if (m.email) out.add(m.email);
			} else if (r.type === 'unit' && r.id) {
				const members = await getOrgUnitMemberEmails(localStorage.token, r.id);
				for (const m of members) if (m.email) out.add(m.email);
			}
		}
		return [...out];
	}

	// ---------- Send / Cancel ----------
	async function handleSend() {
		if (!canSend) return;
		sending = true;
		cooldownActive = true;

		// 그룹/부서를 멤버 이메일로 펼친다. 실패하면 발송 중단(부분 발송 방지).
		let toEmails: string[];
		let ccEmails: string[];
		let bccEmails: string[];
		try {
			toEmails = await resolveRecipients(draftTo);
			ccEmails = await resolveRecipients(draftCc);
			bccEmails = await resolveRecipients(draftBcc);
		} catch (e) {
			sending = false;
			setTimeout(() => (cooldownActive = false), 5000);
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load members'));
			return;
		}
		if (toEmails.length === 0) {
			sending = false;
			setTimeout(() => (cooldownActive = false), 5000);
			toast.error($i18n.t('No recipients to send to'));
			return;
		}

		try {
			const result: GmailConfirmResponse = await confirmGmailSend(
				localStorage.token,
				payload.message_id,
				{
					to: toEmails,
					subject: draftSubject,
					body: draftBody,
					cc: ccEmails.length ? ccEmails : null,
					bcc: bccEmails.length ? bccEmails : null,
					in_reply_to: payload.draft.in_reply_to ?? null,
					conversation_id: conversationId
				}
			);
			finalState = result.status;
			if (result.status === 'sent') {
				finalMessage = $i18n.t('Email sent successfully');
				toast.success(finalMessage);
			} else if (result.status === 'already_sent') {
				finalMessage = $i18n.t('Email already sent earlier');
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
				$i18n.t('Failed to send email');
			toast.error(finalMessage);
		} finally {
			sending = false;
			// 5초 cooldown — 실패해도 적용 (rapid retry 차단).
			setTimeout(() => {
				cooldownActive = false;
			}, 5000);
		}
	}

	function handleCancel() {
		finalState = 'previously_failed';
		finalMessage = $i18n.t('Email cancelled');
		toast.info(finalMessage);
		dispatch('cancelled');
	}
</script>

<div
	class="my-3 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 shadow-sm"
>
	<!-- Header -->
	<div class="flex items-center gap-2 mb-3">
		<div class="shrink-0 text-[var(--cloo-color-accent)]">
			<EnvelopeSolid className="size-5" />
		</div>
		<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
			{$i18n.t('Confirm Email')}
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
		<!-- Final state — read-only summary -->
		<div
			class="text-sm py-3 text-center {finalState === 'sent'
				? 'text-green-600 dark:text-green-400'
				: finalState === 'error'
					? 'text-red-600 dark:text-red-400'
					: 'text-gray-600 dark:text-gray-400'}"
		>
			{finalMessage}
		</div>
	{:else}
		<div class="space-y-3">
			<!-- To recipients (사용자/그룹 자동완성) -->
			<GmailRecipientField
				label={$i18n.t('To')}
				bind:recipients={draftTo}
				{groups}
				{units}
				{isExternal}
				placeholder={$i18n.t('Add recipient, name, or group')}
			/>

			<!-- Cc/Bcc toggle -->
			{#if !showCcBcc}
				<button
					type="button"
					class="text-xs text-[var(--cloo-color-accent)] hover:underline"
					on:click={() => (showCcBcc = true)}
				>
					{$i18n.t('Add Cc / Bcc')}
				</button>
			{:else}
				<GmailRecipientField
					label={$i18n.t('Cc')}
					bind:recipients={draftCc}
					{groups}
					{units}
					{isExternal}
					placeholder={$i18n.t('Add Cc recipient or group')}
				/>
				<GmailRecipientField
					label={$i18n.t('Bcc')}
					bind:recipients={draftBcc}
					{groups}
					{units}
					{isExternal}
					placeholder={$i18n.t('Add Bcc recipient or group')}
				/>
			{/if}

			{#if hasEntityToken}
				<div class="text-[11px] text-gray-500 dark:text-gray-400 italic">
					{$i18n.t('Groups and departments are expanded to member emails when you send.')}
				</div>
			{/if}

			<!-- Subject -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Subject')}
				</div>
				<input
					type="text"
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)]"
					bind:value={draftSubject}
				/>
			</div>

			<!-- Body -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Body')}
				</div>
				<textarea
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)] resize-y min-h-[140px]"
					bind:value={draftBody}
				></textarea>
			</div>

			<!-- High-risk 2-click confirm toggle (plan §5.9) -->
			{#if requiresExplicitConfirm}
				<div
					class="flex items-center gap-3 text-xs text-gray-800 dark:text-gray-200 bg-[var(--cloo-color-accent-soft)] rounded-lg p-3 border border-[var(--cloo-color-accent)]"
				>
					<Switch bind:state={confirmToggle} />
					<span>
						{$i18n.t(
							'I have reviewed the recipients and contents above and want to send this email.'
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
					on:click={handleSend}
					disabled={!canSend}
				>
					{#if sending}
						{$i18n.t('Sending...')}
					{:else if cooldownActive && finalState === ''}
						{$i18n.t('Please wait...')}
					{:else}
						{$i18n.t('Send')}
					{/if}
				</button>
			</div>
		</div>
	{/if}
</div>
