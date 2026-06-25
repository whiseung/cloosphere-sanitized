import { WEBUI_API_BASE_URL } from '$lib/constants';

export type TeamsBotScope = 'personal' | 'team' | 'groupchat';
export type TeamsBotGroupCapability = '' | 'team' | 'groupchat' | 'meetings';

export type TeamsBotConfig = {
	enabled: boolean;
	app_id: string;
	app_password: string;
	tenant_id: string;
	model_id: string;
	name: string;
	description_short: string;
	description_full: string;
	developer_name: string;
	developer_website: string;
	has_color_icon?: boolean;
	has_outline_icon?: boolean;
	scopes: TeamsBotScope[];
	accent_color: string;
	default_group_capability: TeamsBotGroupCapability;
};

export type IconKind = 'color' | 'outline';

export type TeamsMessagingEndpoint = {
	messaging_endpoint: string;
	public_base: string;
};

export const getTeamsBotConfig = async (token: string): Promise<TeamsBotConfig> => {
	let error: any = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams-bot/config`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res as TeamsBotConfig;
};

export const updateTeamsBotConfig = async (
	token: string,
	config: TeamsBotConfig
): Promise<TeamsBotConfig> => {
	let error: any = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams-bot/config`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res as TeamsBotConfig;
};

export const getTeamsMessagingEndpoint = async (
	token: string
): Promise<TeamsMessagingEndpoint> => {
	let error: any = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams-bot/messaging-endpoint`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res as TeamsMessagingEndpoint;
};

export const downloadTeamsManifestUrl = (): string => {
	return `${WEBUI_API_BASE_URL}/teams-bot/manifest.zip`;
};

export const iconPreviewUrl = (kind: IconKind): string => {
	// cache-buster 는 호출 측에서 Date.now() 쿼리로 추가
	return `${WEBUI_API_BASE_URL}/teams-bot/icon/${kind}`;
};

export const uploadTeamsIcon = async (token: string, kind: IconKind, file: File) => {
	const form = new FormData();
	form.append('file', file);
	let error: any = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams-bot/icon/${kind}`, {
		method: 'POST',
		headers: { authorization: `Bearer ${token}` },
		body: form
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const deleteTeamsIcon = async (token: string, kind: IconKind) => {
	let error: any = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/teams-bot/icon/${kind}`, {
		method: 'DELETE',
		headers: { authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res;
};
