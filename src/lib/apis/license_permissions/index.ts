import { WEBUI_API_BASE_URL } from '$lib/constants';

export interface LicensePermission {
	enhanced_kbsphere: boolean;
	enhanced_dbsphere: boolean;
	enhanced_tool_use: boolean;
}

export const getLicensePermissions = async (token: string): Promise<LicensePermission | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/license_permissions/`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
