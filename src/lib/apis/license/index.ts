import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface LicenseStatus {
	has_license: boolean;
	tier: string | null;
	company: string | null;
	max_users: number;
	expires_at: number | null;
	license_keys: KeyInfo[];
	feature_keys: KeyInfo[];
	permissions: Record<string, boolean>;
	enforcement_enabled: boolean;
}

export interface KeyInfo {
	token: string;
	type: string;
	payload: Record<string, string | number | boolean | null>;
	valid: boolean;
	error: string | null;
}

export interface LicensePermissions {
	permissions: Record<string, boolean>;
	has_license: boolean;
	tier: string | null;
	enforcement_enabled: boolean;
	enhanced_kbsphere: boolean;
	enhanced_dbsphere: boolean;
	enhanced_tool_use: boolean;
}

export interface RegisterKeyResponse {
	success: boolean;
	type: string | null;
	payload: Record<string, unknown> | null;
	error: string | null;
}

export const getLicenseStatus = async (token: string): Promise<LicenseStatus | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/license/status`, {
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
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getLicensePermissions = async (token: string): Promise<LicensePermissions | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/license/permissions`, {
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
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const registerLicenseKey = async (
	token: string,
	key: string
): Promise<RegisterKeyResponse | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/license/register`, {
		method: 'POST',
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
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteLicenseKey = async (
	token: string,
	key: string
): Promise<{ success: boolean } | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/license/key`, {
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
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const setLicenseEnforcement = async (
	token: string,
	enabled: boolean
): Promise<{ success: boolean; enforcement_enabled: boolean } | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/license/enforcement`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ enabled })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
