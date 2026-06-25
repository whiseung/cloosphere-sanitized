import { WEBUI_API_BASE_URL } from '$lib/constants';

const BASE = `${WEBUI_API_BASE_URL}/cloocus`;

function cloocusHeaders(token: string): Record<string, string> {
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		authorization: `Bearer ${token}`
	};
	const secret = localStorage.getItem('cloocus_secret');
	if (secret) {
		headers['X-Cloocus-Secret'] = secret;
	}
	return headers;
}

export const getCloocusStatus = async (token: string) => {
	let error = null;
	const res = await fetch(`${BASE}/status`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const listCloocusCustomers = async (token: string, page = 1, search = '') => {
	let error = null;
	const params = new URLSearchParams({ page: String(page) });
	if (search) params.set('search', search);
	const res = await fetch(`${BASE}/customers?${params}`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const createCloocusCustomer = async (
	token: string,
	form: { company_name: string; contact_email?: string; contact_name?: string; notes?: string; license_type?: string | null; start_date?: number | null }
) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/create`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const getCloocusCustomer = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/${id}`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const updateCloocusCustomer = async (
	token: string,
	id: number,
	form: {
		company_name?: string;
		contact_email?: string;
		contact_name?: string;
		notes?: string;
		is_active?: boolean;
		license_type?: string | null;
		start_date?: number | null;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/${id}/update`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const deleteCloocusCustomer = async (token: string, id: number, hard = false) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/${id}/delete?hard=${hard}`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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

export const getCustomerLicenses = async (token: string, customerId: number) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/${customerId}/licenses`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const recordLicenseKey = async (
	token: string,
	form: {
		customer_id: number;
		tier: string;
		max_users?: number;
		expires_at?: number;
		token: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/licenses/record`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const revokeLicense = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/licenses/${id}/revoke`, {
		method: 'POST',
		headers: cloocusHeaders(token)
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

export const recordFeatureKey = async (
	token: string,
	form: {
		customer_id: number;
		module: string;
		expires_at?: number;
		token: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/feature-keys/record`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const revokeFeatureKey = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/feature-keys/${id}/revoke`, {
		method: 'POST',
		headers: cloocusHeaders(token)
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

export const deleteLicenseRecord = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/licenses/${id}/delete`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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

export const deleteFeatureKeyRecord = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/feature-keys/${id}/delete`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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

export const listCloocusFeatures = async (token: string) => {
	let error = null;
	const res = await fetch(`${BASE}/features`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const createCloocusFeature = async (
	token: string,
	form: {
		module_id: string;
		display_name: string;
		description?: string;
		tier_minimum?: string;
		is_active?: boolean;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/features/create`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const updateCloocusFeature = async (
	token: string,
	moduleId: string,
	form: {
		display_name?: string;
		description?: string;
		tier_minimum?: string;
		is_active?: boolean;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/features/${moduleId}/update`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const deleteCloocusFeature = async (token: string, moduleId: string) => {
	let error = null;
	const res = await fetch(`${BASE}/features/${moduleId}/delete`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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

export const generateLicenseKey = async (
	token: string,
	form: {
		customer_id: number;
		tier: string;
		max_users?: number;
		expires?: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/generate/license`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const generateFeatureKey = async (
	token: string,
	form: {
		customer_id: number;
		module: string;
		expires?: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/generate/feature-key`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

// ============================
// Credit Management
// ============================

export const updateCustomerCredit = async (
	token: string,
	customerId: number,
	form: { credit: number; approval_email?: string }
) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/${customerId}/credit`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const getCustomerCreditSummary = async (token: string, customerId: number) => {
	let error = null;
	const res = await fetch(`${BASE}/customers/${customerId}/credit-summary`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

// ============================
// Work Categories
// ============================

export const listWorkCategories = async (token: string) => {
	let error = null;
	const res = await fetch(`${BASE}/work-categories`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const createWorkCategory = async (
	token: string,
	form: { name: string; sort_order?: number }
) => {
	let error = null;
	const res = await fetch(`${BASE}/work-categories/create`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const updateWorkCategory = async (
	token: string,
	id: number,
	form: { name: string; sort_order?: number }
) => {
	let error = null;
	const res = await fetch(`${BASE}/work-categories/${id}/update`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const deleteWorkCategory = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/work-categories/${id}/delete`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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

// ============================
// Work Logs
// ============================

export const listWorkLogs = async (
	token: string,
	params: {
		page?: number;
		customer_id?: number;
		status?: string;
		category_id?: number;
	} = {}
) => {
	let error = null;
	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.customer_id) searchParams.set('customer_id', String(params.customer_id));
	if (params.status) searchParams.set('status', params.status);
	if (params.category_id) searchParams.set('category_id', String(params.category_id));

	const res = await fetch(`${BASE}/work-logs?${searchParams}`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const previewWorkLogEmail = async (
	token: string,
	form: {
		customer_id: number;
		category_id: number;
		title: string;
		description?: string;
		work_hours: number;
		work_date: number;
		created_by?: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/work-logs/preview-email`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const createWorkLog = async (
	token: string,
	form: {
		customer_id: number;
		category_id: number;
		title: string;
		description?: string;
		work_hours: number;
		work_date: number;
		created_by?: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/work-logs/create`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const updateWorkLog = async (
	token: string,
	id: number,
	form: {
		category_id?: number;
		title?: string;
		description?: string;
		work_hours?: number;
		work_date?: number;
		created_by?: string;
		notes?: string;
	}
) => {
	let error = null;
	const res = await fetch(`${BASE}/work-logs/${id}/update`, {
		method: 'POST',
		headers: cloocusHeaders(token),
		body: JSON.stringify(form)
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

export const deleteWorkLog = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/work-logs/${id}/delete`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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

export const previewExistingWorkLogEmail = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/work-logs/${id}/preview-email`, {
		method: 'GET',
		headers: cloocusHeaders(token)
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

export const resendWorkLogEmail = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/work-logs/${id}/resend`, {
		method: 'POST',
		headers: cloocusHeaders(token)
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

// Registry Tokens

export const createRegistryToken = async (
	token: string,
	data: { customer_id: number; token_name: string; token_key: string; notes?: string }
) => {
	let error = null;
	const res = await fetch(`${BASE}/registry-tokens/create`, {
		method: 'POST',
		headers: cloocusHeaders(token),
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

export const updateRegistryToken = async (
	token: string,
	id: number,
	data: { token_name?: string; token_key?: string; notes?: string }
) => {
	let error = null;
	const res = await fetch(`${BASE}/registry-tokens/${id}/update`, {
		method: 'POST',
		headers: cloocusHeaders(token),
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

export const deleteRegistryToken = async (token: string, id: number) => {
	let error = null;
	const res = await fetch(`${BASE}/registry-tokens/${id}/delete`, {
		method: 'DELETE',
		headers: cloocusHeaders(token)
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
