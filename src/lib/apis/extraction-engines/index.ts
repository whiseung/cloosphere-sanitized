import { WEBUI_API_BASE_URL } from '$lib/constants';

export type ExtractionEngineProfile = {
	id: string;
	user_id: string;
	name: string;
	engine_type: string;
	config: Record<string, any> | null;
	pdf_extract_images: boolean;
	created_at: number;
	updated_at: number;
};

export type ExtractionEngineProfileForm = {
	name: string;
	engine_type?: string;
	config?: Record<string, any> | null;
	pdf_extract_images?: boolean;
};

export type EngineTypeMeta = {
	type: string;
	label: string;
	supported_extensions: string[];
	required_config_fields: string[];
	optional_config_fields?: string[];
	default_config?: Record<string, string>;
};

export const getExtractionEngines = async (token: string): Promise<ExtractionEngineProfile[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/extraction-engines/`, {
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

export const getEngineTypes = async (token: string): Promise<EngineTypeMeta[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/extraction-engines/engine-types`, {
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

export const createExtractionEngine = async (
	token: string,
	data: ExtractionEngineProfileForm
): Promise<ExtractionEngineProfile> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/extraction-engines/create`, {
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

export const updateExtractionEngine = async (
	token: string,
	id: string,
	data: ExtractionEngineProfileForm
): Promise<ExtractionEngineProfile> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/extraction-engines/${id}/update`, {
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

export const deleteExtractionEngine = async (token: string, id: string): Promise<boolean> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/extraction-engines/${id}/delete`, {
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
