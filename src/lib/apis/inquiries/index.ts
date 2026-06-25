import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getInquiryTypes = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/types`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createInquiry = async (
	token: string,
	data: { title: string; type: string; subtype: string; content: string }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getMyInquiries = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/me`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? [];
};

export const getAllInquiries = async (
	token: string,
	statusFilter?: string,
	typeFilter?: string
) => {
	let error = null;

	const params = new URLSearchParams();
	if (statusFilter) params.set('status_filter', statusFilter);
	if (typeFilter) params.set('type_filter', typeFilter);
	const query = params.toString() ? `?${params.toString()}` : '';
	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/list${query}`, {
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
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? [];
};

export const getInquiryStats = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/stats`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res ?? {};
};

export const updateInquiry = async (
	token: string,
	inquiryId: string,
	data: { status?: string; admin_note?: string }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/${inquiryId}`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const closeInquiry = async (token: string, inquiryId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/${inquiryId}/close`, {
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
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteInquiry = async (token: string, inquiryId: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/inquiries/${inquiryId}`, {
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
			console.log(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
