import { WEBUI_API_BASE_URL } from '$lib/constants';

// Types
export interface FileLogItem {
	id: string;
	user_id: string;
	user_name: string | null;
	user_email: string | null;
	filename: string;
	meta: Record<string, any> | null;
	created_at: number | null;
	updated_at: number | null;
}

export interface FileLogListResponse {
	items: FileLogItem[];
	total: number;
	page: number;
	limit: number;
	total_pages: number;
}

export interface FileLogQueryParams {
	page?: number;
	limit?: number;
	source?: string;
	category?: string;
	status?: string;
	search?: string;
	user_id?: string;
	from_date?: number;
	to_date?: number;
}

export const getFileLogs = async (
	token: string,
	params: FileLogQueryParams = {}
): Promise<FileLogListResponse> => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (params.page) searchParams.append('page', `${params.page}`);
	if (params.limit) searchParams.append('limit', `${params.limit}`);
	if (params.source) searchParams.append('source', params.source);
	if (params.category) searchParams.append('category', params.category);
	if (params.status) searchParams.append('status', params.status);
	if (params.search) searchParams.append('search', params.search);
	if (params.user_id) searchParams.append('user_id', params.user_id);
	if (params.from_date) searchParams.append('from_date', `${params.from_date}`);
	if (params.to_date) searchParams.append('to_date', `${params.to_date}`);

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/file-logs/?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
