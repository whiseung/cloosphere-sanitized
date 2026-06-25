import { WEBUI_API_BASE_URL } from '$lib/constants';

export type IdpType = 'entra' | 'google';

export type TrustedAudience = {
	id: string;
	idp_type: IdpType;
	audience: string;
	tenant_id?: string | null;
	issuer?: string | null;
	name?: string | null;
	enabled: boolean;
	auto_provision: boolean;
	default_role: string;
	default_group_ids?: string[] | null;
	meta?: Record<string, unknown> | null;
	created_at: number;
	updated_at: number;
};

export type TrustedAudienceForm = {
	idp_type: IdpType;
	audience: string;
	tenant_id?: string;
	issuer?: string;
	name?: string;
	enabled: boolean;
	auto_provision: boolean;
	default_role: string;
	default_group_ids?: string[] | null;
};

const BASE = `${WEBUI_API_BASE_URL}/trusted-audiences`;

async function req<T>(
	token: string,
	path: string,
	init?: RequestInit & { body?: BodyInit }
): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		...init,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`,
			...(init?.headers ?? {})
		}
	});
	if (!res.ok) throw await res.json();
	return res.json();
}

export const listTrustedAudiences = (token: string) =>
	req<TrustedAudience[]>(token, '/', { method: 'GET' });

export const createTrustedAudience = (token: string, form: TrustedAudienceForm) =>
	req<TrustedAudience>(token, '/', { method: 'POST', body: JSON.stringify(form) });

export const updateTrustedAudience = (
	token: string,
	id: string,
	form: TrustedAudienceForm
) => req<TrustedAudience>(token, `/${id}`, { method: 'POST', body: JSON.stringify(form) });

export const deleteTrustedAudience = (token: string, id: string) =>
	req<{ ok: boolean }>(token, `/${id}`, { method: 'DELETE' });
