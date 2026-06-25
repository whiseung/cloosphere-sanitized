import { WEBUI_API_BASE_URL } from '$lib/constants';
import type { Banner } from '$lib/types';

export const importConfig = async (
	token: string,
	config,
	expectedVersion: number | null = null
) => {
	let error = null;

	const body: Record<string, unknown> = { config };
	if (expectedVersion !== null) {
		body.expected_version = expectedVersion;
	}

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/import`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(body)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			if (err?.detail?.error === 'CONFIG_VERSION_CONFLICT') {
				error = err.detail.message;
			} else {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getConfigVersion = async (token: string): Promise<number> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/version`, {
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

	return res?.version ?? 0;
};

export const exportConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/export`, {
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

export const getDirectConnectionsConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/direct_connections`, {
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

export const setDirectConnectionsConfig = async (token: string, config: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/direct_connections`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...config
		})
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

export const getGoogleCloudConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/google_cloud`, {
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

export type KMSConfig = {
	KMS_PROVIDER: string;
	KMS_AZURE_KEY_VAULT_KEY_URI?: string;
	KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED?: string;
	KMS_AZURE_TENANT_ID?: string;
	KMS_AZURE_CLIENT_ID?: string;
	KMS_AZURE_CLIENT_SECRET?: string;
};

export const getKMSConfig = async (token: string): Promise<KMSConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms`, {
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

export const setKMSConfig = async (token: string, config: KMSConfig): Promise<KMSConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

export type KMSMigrateCounts = {
	touched: number;
	skipped: number;
	failed: number;
};

export type KMSMigrateResult = {
	ok: boolean;
	counts: Record<string, KMSMigrateCounts>;
};

export type KMSRotateForm = {
	new_key_uri: string;
	new_tenant_id?: string;
	new_client_id?: string;
	new_client_secret?: string;
};

export type KMSRotateResult = {
	ok: boolean;
	from_kek: string | null;
	to_kek: string;
	counts: Record<string, KMSMigrateCounts>;
};

export type KMSRotationConfig = {
	KMS_ROTATION_AUTO_ENABLED: boolean;
	KMS_ROTATION_CHECK_INTERVAL_HOURS: number;
	KMS_ROTATION_DRY_RUN: boolean;
};

export type KMSRotationTier = {
	classification: string;
	status: string; // up-to-date | rotated | would-rotate | error | skipped:not-configured
	current_version?: string;
	from_version?: string;
	to_version?: string;
	to_uri?: string;
	from_uri?: string;
	counts?: Record<string, KMSMigrateCounts>;
	error?: string;
};

export type KMSRotationCheckResult = {
	ok: boolean;
	checked_at: number;
	dry_run: boolean;
	tiers: KMSRotationTier[];
	skipped_reason?: string;
};

export type KMSRotationStatus = KMSRotationConfig & {
	last_check_at: number;
	last_result: KMSRotationCheckResult | null;
};

export const getKMSRotationConfig = async (token: string): Promise<KMSRotationStatus> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/rotation`, {
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
			error = err.detail ?? err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const setKMSRotationConfig = async (
	token: string,
	config: KMSRotationConfig
): Promise<KMSRotationStatus> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/rotation`, {
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
			console.log(err);
			error = err.detail ?? err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const triggerKMSRotationCheck = async (
	token: string,
	dryRun?: boolean
): Promise<KMSRotationCheckResult> => {
	const params = new URLSearchParams();
	if (dryRun !== undefined) params.set('dry_run', String(dryRun));
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/configs/kms/rotation/check?${params.toString()}`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail ?? err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const rotateKMS = async (
	token: string,
	form: KMSRotateForm
): Promise<KMSRotateResult> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/rotate`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify(form)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const migrateKMS = async (token: string): Promise<KMSMigrateResult> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/migrate`, {
		method: 'POST',
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
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export type KMSAuditRow = {
	id: number;
	timestamp_ms: number;
	actor_type: string;
	actor_id: string | null;
	org_id: string | null;
	operation: string;
	config_path: string | null;
	kek_uri: string | null;
	kek_version: string | null;
	classification: string | null;
	success: boolean;
	error_code: string | null;
	request_id: string | null;
	client_ip: string | null;
	prev_hash: string;
	row_hash: string;
};

export type KMSAuditListResponse = {
	rows: KMSAuditRow[];
	total: number;
	page: number;
	limit: number;
};

export type KMSAuditVerifyResult = {
	checked: number;
	ok: boolean;
	first_break_id: number | null;
	first_break_reason: string | null;
	from_id: number | null;
	to_id: number | null;
};

export type KMSAuditQuery = {
	page?: number;
	limit?: number;
	operation?: string;
	success?: boolean;
	actor_id?: string;
	org_id?: string;
	config_path?: string;
	from_ts_ms?: number;
	to_ts_ms?: number;
};

export const listKMSAudit = async (
	token: string,
	query: KMSAuditQuery = {}
): Promise<KMSAuditListResponse> => {
	let error = null;
	const params = new URLSearchParams();
	if (query.page) params.set('page', String(query.page));
	if (query.limit) params.set('limit', String(query.limit));
	if (query.operation) params.set('operation', query.operation);
	if (query.success !== undefined) params.set('success', String(query.success));
	if (query.actor_id) params.set('actor_id', query.actor_id);
	if (query.org_id) params.set('org_id', query.org_id);
	if (query.config_path) params.set('config_path', query.config_path);
	if (query.from_ts_ms) params.set('from_ts_ms', String(query.from_ts_ms));
	if (query.to_ts_ms) params.set('to_ts_ms', String(query.to_ts_ms));

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/audit?${params.toString()}`, {
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
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const verifyKMSAudit = async (
	token: string,
	from_id?: number,
	to_id?: number
): Promise<KMSAuditVerifyResult> => {
	let error = null;
	const params = new URLSearchParams();
	if (from_id) params.set('from_id', String(from_id));
	if (to_id) params.set('to_id', String(to_id));

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/audit/verify?${params.toString()}`, {
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
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const exportKMSAuditCSV = async (
	token: string,
	reason: string,
	query: KMSAuditQuery = {}
): Promise<Blob> => {
	const params = new URLSearchParams();
	if (reason) params.set('reason', reason);
	if (query.operation) params.set('operation', query.operation);
	if (query.success !== undefined) params.set('success', String(query.success));
	if (query.actor_id) params.set('actor_id', query.actor_id);
	if (query.org_id) params.set('org_id', query.org_id);
	if (query.config_path) params.set('config_path', query.config_path);
	if (query.from_ts_ms) params.set('from_ts_ms', String(query.from_ts_ms));
	if (query.to_ts_ms) params.set('to_ts_ms', String(query.to_ts_ms));

	const res = await fetch(
		`${WEBUI_API_BASE_URL}/configs/kms/audit/export.csv?${params.toString()}`,
		{
			method: 'GET',
			headers: {
				authorization: `Bearer ${token}`
			}
		}
	);

	if (!res.ok) {
		const detail = await res.json().catch(() => ({}));
		throw detail.detail ?? `Export failed (HTTP ${res.status})`;
	}
	return await res.blob();
};

export const testKMSConnection = async (
	token: string,
	config: KMSConfig
): Promise<{ ok: boolean; detail: string }> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/kms/test`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err.detail ?? err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const setGoogleCloudConfig = async (
	token: string,
	config: { GOOGLE_CLOUD_ENABLED: boolean; GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY: string }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/google_cloud`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...config
		})
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

export type GoogleIntegrationConfig = {
	ENABLE_GMAIL_INTEGRATION: boolean | null;
	ENABLE_CALENDAR_INTEGRATION: boolean | null;
	ENABLE_DRIVE_INTEGRATION: boolean | null;
	// read-only — Google OAuth 자격증명(GOOGLE_CLIENT_ID/SECRET) 설정 여부
	GOOGLE_OAUTH_CONFIGURED?: boolean | null;
};

export const getGoogleIntegrationConfig = async (
	token: string
): Promise<GoogleIntegrationConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/google_integration`, {
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

	if (error) throw error;
	return res;
};

/**
 * Gmail / Calendar 채팅 통합 admin 토글 설정.
 *
 * 두 필드 모두 Optional — 한쪽만 업데이트해도 다른 쪽은 서버가 기존 값 유지.
 */
export const setGoogleIntegrationConfig = async (
	token: string,
	config: Partial<GoogleIntegrationConfig>
): Promise<GoogleIntegrationConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/google_integration`, {
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
			console.log(err);
			error = err?.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getToolServerConnections = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/tool_servers`, {
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

export const setToolServerConnections = async (token: string, connections: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/tool_servers`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...connections
		})
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

export const verifyToolServerConnection = async (token: string, connection: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/tool_servers/verify`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...connection
		})
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

export const getCodeExecutionConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/code_execution`, {
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

export const setCodeExecutionConfig = async (token: string, config: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/code_execution`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...config
		})
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

export const getModelsConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/models`, {
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

export const setModelsConfig = async (token: string, config: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/models`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...config
		})
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

export const setDefaultPromptSuggestions = async (token: string, promptSuggestions: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/suggestions`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			suggestions: promptSuggestions
		})
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

export const getBanners = async (token: string): Promise<Banner[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/banners`, {
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

export const setBanners = async (token: string, banners: Banner[]) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/banners`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			banners: banners
		})
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

// Storage Config Types
export interface S3Config {
	bucket_name: string;
	region_name: string;
	endpoint_url: string;
	access_key_id: string;
	secret_access_key: string;
	key_prefix: string;
}

export interface AzureConfig {
	endpoint: string;
	container_name: string;
	storage_key: string;
}

export interface GCSConfig {
	bucket_name: string;
	credentials_json: string;
}

export interface StorageConfig {
	image_upload_mode: string;
	provider: string;
	s3: S3Config | null;
	azure: AzureConfig | null;
	gcs: GCSConfig | null;
}

export const getStorageConfig = async (token: string): Promise<StorageConfig | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/storage`, {
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

export const setStorageConfig = async (token: string, config: StorageConfig) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/storage`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

// File Storage Config
export interface FileStorageConfig {
	provider: string;
	s3: S3Config | null;
	azure: AzureConfig | null;
	gcs: GCSConfig | null;
}

export const testFileStorageConnection = async (
	token: string,
	config: { provider: string; s3?: S3Config; azure?: AzureConfig; gcs?: GCSConfig }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/file-storage/test`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

export const getFileStorageConfig = async (token: string): Promise<FileStorageConfig | null> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/file-storage`, {
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

export const setFileStorageConfig = async (token: string, config: FileStorageConfig) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/file-storage`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

export const testStorageConnection = async (
	token: string,
	config: { provider: string; s3?: S3Config; azure?: AzureConfig; gcs?: GCSConfig }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/storage/test`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

export const updateMonitoringConfig = async (
	token: string,
	config: { ENABLE_OTEL: boolean; OTEL_EXPORTER_OTLP_ENDPOINT: string }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/monitoring`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(config)
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

export const getMonitoringConfig = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/monitoring`, {
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

export const downloadMonitoringBundle = async (token: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/monitoring/download`, {
		method: 'GET',
		headers: {
			Authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const err = await res.json();
		throw err.detail || 'Download failed';
	}

	const blob = await res.blob();
	const url = window.URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = 'cloosphere-monitor.tar.gz';
	document.body.appendChild(a);
	a.click();
	window.URL.revokeObjectURL(url);
	a.remove();
};
