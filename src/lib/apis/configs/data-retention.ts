import { WEBUI_API_BASE_URL } from '$lib/constants';

export type DataRetentionConfig = {
	ENABLE_DATA_RETENTION: boolean;
	DATA_RETENTION_CLEANUP_HOUR: number;
	RETENTION_DAYS_USAGE: number;
	RETENTION_DAYS_AUDIT_LOG: number;
	RETENTION_DAYS_GUARDRAIL_LOG: number;
	RETENTION_DAYS_TRACE: number;
	RETENTION_DAYS_TRACE_ANALYSIS: number;
	RETENTION_DAYS_AUTO_EVALUATION: number;
};

export type TableStatsItem = {
	table_name: string;
	label: string;
	row_count: number;
	total_size: string | null;
	data_size: string | null;
	index_size: string | null;
	retention_days: number;
};

export type DataRetentionStats = {
	tables: TableStatsItem[];
};

export type CleanupResult = {
	table_name: string;
	deleted_count: number;
};

export type CleanupResponse = {
	results: CleanupResult[];
	total_deleted: number;
};

export const getDataRetentionConfig = async (token: string): Promise<DataRetentionConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/data_retention/`, {
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
	return res;
};

export const setDataRetentionConfig = async (
	token: string,
	config: DataRetentionConfig
): Promise<DataRetentionConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/data_retention/`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

export const getDataRetentionStats = async (token: string): Promise<DataRetentionStats> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/data_retention/stats`, {
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
	return res;
};

export const executeDataRetentionCleanup = async (
	token: string
): Promise<CleanupResponse> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/data_retention/cleanup`, {
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
