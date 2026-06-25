import { WEBUI_API_BASE_URL } from '$lib/constants';

export type ProviderConnectionStatus = {
	provider: 'microsoft' | 'google';
	connected: boolean;
	account_email: string | null;
	expires_at: number | null;
	scopes: string[] | null;
	// google 전용 — 채팅 통합 기능별 필수 scope 충족 여부 (토큰이 있어도
	// GWS delegated scope 이전 로그인이면 false)
	features: { gmail: boolean; calendar: boolean; drive: boolean } | null;
};

export const getMyEmailConnections = async (
	token: string
): Promise<ProviderConnectionStatus[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/email/connections`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const disconnectMyEmailProvider = async (
	token: string,
	provider: 'microsoft' | 'google'
): Promise<boolean> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/email/connections/${provider}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};
