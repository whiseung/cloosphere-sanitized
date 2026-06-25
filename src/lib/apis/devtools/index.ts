import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface LocaleInfo {
	code: string;
	title: string;
}

export interface LocaleTranslations {
	locale: string;
	translations: Record<string, string>;
}

export const getLocales = async (token: string): Promise<LocaleInfo[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/devtools/locales`, {
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
			error = err.detail ?? 'Failed to get locales';
			console.error(error);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getLocaleTranslations = async (
	token: string,
	localeCode: string
): Promise<LocaleTranslations> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/devtools/locales/${localeCode}`, {
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
			error = err.detail ?? 'Failed to get locale translations';
			console.error(error);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateLocaleTranslations = async (
	token: string,
	localeCode: string,
	translations: Record<string, string>
): Promise<{ success: boolean; locale: string; message: string }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/devtools/locales/${localeCode}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ translations })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? 'Failed to update locale translations';
			console.error(error);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateSingleTranslation = async (
	token: string,
	localeCode: string,
	key: string,
	value: string
): Promise<{ success: boolean; locale: string; key: string; value: string }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/devtools/locales/${localeCode}`, {
		method: 'PATCH',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ key, value })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? 'Failed to update translation';
			console.error(error);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteTranslationKey = async (
	token: string,
	localeCode: string,
	key: string
): Promise<{ success: boolean; locale: string; key: string; deleted: boolean }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/devtools/locales/${localeCode}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ key })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? 'Failed to delete translation key';
			console.error(error);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export interface SyncResult {
	translated: number;
	failed: number;
	errors: string[];
}

export interface SyncTranslationsResponse {
	success: boolean;
	results: Record<string, SyncResult>;
}

export const syncTranslations = async (
	token: string,
	modelId: string,
	sourceLocales: string[],
	targetLocales: string[]
): Promise<SyncTranslationsResponse> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/devtools/locales/sync`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model_id: modelId,
			source_locales: sourceLocales,
			target_locales: targetLocales
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? 'Failed to sync translations';
			console.error(error);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
