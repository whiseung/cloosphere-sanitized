import { WEBUI_API_BASE_URL } from '$lib/constants';

export type DocumentProfile = {
	id: string;
	user_id: string;
	name: string;
	is_default: boolean;
	/** @deprecated 신규 경로는 extension_engine_map 사용. legacy 경로 호환을 위해 유지. */
	content_extraction_engine: string;
	/** @deprecated engine profile 의 pdf_extract_images 가 우선. */
	pdf_extract_images: boolean;
	text_splitter: string;
	chunk_size: number;
	chunk_overlap: number;
	/** @deprecated engine profile 의 config 가 우선. */
	config: Record<string, any> | null;
	/** 확장자(소문자 + leading dot) -> ExtractionEngineProfile.id. 비어있으면 legacy 동작. */
	extension_engine_map: Record<string, string> | null;
	/** 매핑에 없는 확장자의 기본 엔진. null 이면 기본 내장 엔진(engine_type="") 사용. */
	default_engine_id: string | null;
	created_at: number;
	updated_at: number;
};

export type DocumentProfileForm = {
	name: string;
	is_default?: boolean;
	content_extraction_engine?: string;
	pdf_extract_images?: boolean;
	text_splitter?: string;
	chunk_size?: number;
	chunk_overlap?: number;
	config?: Record<string, any> | null;
	extension_engine_map?: Record<string, string> | null;
	default_engine_id?: string | null;
};

export const getDocumentProfiles = async (token: string): Promise<DocumentProfile[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/`, {
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
	return res ?? [];
};

export const getDocumentProfileList = async (token: string): Promise<DocumentProfile[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/list`, {
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
	return res ?? [];
};

export const createDocumentProfile = async (
	token: string,
	data: DocumentProfileForm
): Promise<DocumentProfile> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(data)
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

export const updateDocumentProfile = async (
	token: string,
	id: string,
	data: DocumentProfileForm
): Promise<DocumentProfile> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(data)
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

export const setDefaultDocumentProfile = async (
	token: string,
	id: string
): Promise<DocumentProfile> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/${id}/set-default`, {
		method: 'POST',
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

export const migrateDocumentProfileToMapping = async (
	token: string,
	id: string
): Promise<DocumentProfile> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/${id}/migrate-to-mapping`, {
		method: 'POST',
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

export const deleteDocumentProfile = async (token: string, id: string): Promise<boolean> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-profiles/${id}/delete`, {
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
