import { WEBUI_API_BASE_URL } from '$lib/constants';

// Helper to extract error message from API response (mirrors tool-connections client)
const extractErrorMessage = (err: unknown): string => {
	if (typeof err === 'string') return err;
	if (err && typeof err === 'object') {
		const e = err as { detail?: unknown; message?: string };
		if (e.detail) {
			if (Array.isArray(e.detail)) {
				return e.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(', ');
			}
			if (typeof e.detail === 'string') return e.detail;
			return JSON.stringify(e.detail);
		}
		if (e.message) return e.message;
	}
	return JSON.stringify(err);
};

export type MarketplaceServiceField = {
	key: string;
	label: string;
	type: string;
	default?: string;
	required?: boolean;
};

// 마켓플레이스 카탈로그 항목(읽기 전용 메타데이터). 실제 연결은 tool_connection 으로 생성된다.
export type MarketplaceService = {
	id: string;
	name: string;
	description: string;
	category: string;
	tags?: string[];
	connection_kind: 'rest-config' | 'mcp';
	icon: string;
	auth_type?: string;
	docs?: string;
	fields: MarketplaceServiceField[];
};

// 워크스페이스 > 마켓플레이스 생성 페이지의 서비스 picker 가 사용하는 카탈로그.
export const getMarketplaceServices = async (token: string): Promise<MarketplaceService[]> => {
	let error: string | null = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/marketplace/`, {
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
			error = extractErrorMessage(err);
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
