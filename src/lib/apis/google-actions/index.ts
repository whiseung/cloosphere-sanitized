/**
 * Google Workspace HITL confirm API client.
 *
 * Gmail / Calendar / Drive tool 이 LLM 에게 ``confirmation_required`` 응답을
 * 돌려주면 Frontend (``GmailConfirmation.svelte`` / ``CalendarConfirmation.svelte`` /
 * ``DriveConfirmation.svelte``) 가 사용자에게 미리보기를 보여준 뒤 "Send" /
 * "Create" 클릭 시 이 client 를 호출한다.
 *
 * 서버는 (a) HMAC owner / (b) features.{gmail,calendar,drive} / (c) admin enable flag /
 * (d) audit log idempotency / (e) atomic Lock 의 5축 게이트를 재검증한 뒤
 * 실제 외부 API 호출 → audit log 기록 → 결과 반환.
 *
 * 응답 status:
 * - ``sent`` / ``created`` — 정상 완료
 * - ``already_sent`` / ``already_created`` — 이미 처리됨 (idempotent replay)
 * - ``previously_failed`` — 이전 시도 실패, 새 draft mint 필요
 */

import { WEBUI_API_BASE_URL } from '$lib/constants';

// ---------------------------------------------------------------------------
// Gmail confirm
// ---------------------------------------------------------------------------

export type GmailConfirmBody = {
	to: string[];
	subject: string;
	body: string;
	cc?: string[] | null;
	bcc?: string[] | null;
	in_reply_to?: string | null;
	conversation_id?: string | null;
};

export type GmailConfirmResponse = {
	status: 'sent' | 'already_sent' | 'previously_failed';
	message_id: string;
	gmail_message_id?: string | null;
	thread_id?: string | null;
	error?: string | null;
};

export const confirmGmailSend = async (
	token: string,
	messageId: string,
	edited: GmailConfirmBody
): Promise<GmailConfirmResponse> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/google/gmail/confirm/${encodeURIComponent(messageId)}`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(edited)
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

// ---------------------------------------------------------------------------
// Calendar confirm
// ---------------------------------------------------------------------------

export type CalendarConfirmBody = {
	title: string;
	start: string;
	end: string;
	timezone: string;
	description?: string | null;
	attendees?: string[] | null;
	/** "all" | "externalOnly" | "none" — F2 회피 default "all". */
	send_updates?: 'all' | 'externalOnly' | 'none';
	create_meet?: boolean;
	conversation_id?: string | null;
};

export type CalendarConfirmResponse = {
	status: 'created' | 'already_created' | 'previously_failed';
	message_id: string;
	event_id?: string | null;
	html_link?: string | null;
	hangout_link?: string | null;
	error?: string | null;
};

export const confirmCalendarCreate = async (
	token: string,
	messageId: string,
	edited: CalendarConfirmBody
): Promise<CalendarConfirmResponse> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/google/calendar/confirm/${encodeURIComponent(messageId)}`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(edited)
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

// ---------------------------------------------------------------------------
// Drive confirm
// ---------------------------------------------------------------------------

export type DriveConfirmBody = {
	name: string;
	content: string;
	folder_id?: string | null;
	conversation_id?: string | null;
};

export type DriveConfirmResponse = {
	status: 'created' | 'already_created' | 'previously_failed';
	message_id: string;
	doc_id?: string | null;
	web_link?: string | null;
	error?: string | null;
};

export const confirmDriveCreate = async (
	token: string,
	messageId: string,
	edited: DriveConfirmBody
): Promise<DriveConfirmResponse> => {
	let error = null;

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/google/drive/confirm/${encodeURIComponent(messageId)}`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			},
			body: JSON.stringify(edited)
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};
