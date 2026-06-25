import { WEBUI_API_BASE_URL } from '$lib/constants';

export type DocumentTemplateKind = 'pptx' | 'docx' | 'xlsx';

export type DocumentTemplateMeta = {
	is_custom?: boolean;
	original_filename?: string;
	uploaded_at?: number;
	uploaded_by?: string;
};

export type DocumentTemplatesConfig = Record<DocumentTemplateKind, DocumentTemplateMeta>;

export type PresentonConfig = {
	enabled: boolean;
	base_url: string;
	timeout: number;
	default_template: string;
};

export type PresentonTemplate = { id: string; name: string };

export const getDocumentTemplatesConfig = async (
	token: string
): Promise<DocumentTemplatesConfig> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/config`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res as DocumentTemplatesConfig;
};

export const uploadDocumentTemplate = async (
	token: string,
	kind: DocumentTemplateKind,
	file: File
): Promise<DocumentTemplateMeta> => {
	let error = null;

	const formData = new FormData();
	formData.append('file', file);

	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/upload/${kind}`, {
		method: 'POST',
		headers: {
			authorization: `Bearer ${token}`
		},
		body: formData
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err;
			return null;
		});

	if (error) throw error;
	return res as DocumentTemplateMeta;
};

export const downloadDocumentTemplate = async (
	token: string,
	kind: DocumentTemplateKind
): Promise<Blob> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/${kind}/download`, {
		method: 'GET',
		headers: {
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) {
				const err = await res.json().catch(() => ({ detail: res.statusText }));
				throw err;
			}
			return res.blob();
		})
		.catch((err) => {
			console.log(err);
			error = err;
			return null;
		});

	if (error) throw error;
	return res as Blob;
};

export const getPresentonConfig = async (token: string): Promise<PresentonConfig> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/presenton/config`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res as PresentonConfig;
};

// 연결(base_url/timeout)은 마켓플레이스(PPT Generator)가 관리. 이 탭은 엔진 사용 여부
// (enabled)와 기본 템플릿(default_template)만 갱신한다.
export type PresentonEngineForm = { enabled: boolean; default_template?: string };

export const updatePresentonConfig = async (
	token: string,
	config: PresentonEngineForm
): Promise<PresentonConfig> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/presenton/config`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res as PresentonConfig;
};

export const testPresentonConnection = async (
	token: string,
	baseUrl?: string
): Promise<{ ok: boolean; template_count: number }> => {
	let error = null;
	const qs = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : '';
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/presenton/test${qs}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export type PresentonTemplateJob = {
	status: 'pending' | 'completed' | 'failed';
	message: string;
	template_id: string | null;
	error: string | null;
};

export const createPresentonTemplate = async (
	token: string,
	opts: { name: string; indices?: string; fromMaster?: boolean; file?: File }
): Promise<{ job_id: string }> => {
	let error = null;
	const formData = new FormData();
	formData.append('name', opts.name);
	formData.append('indices', opts.indices ?? '0,1,2,3,4');
	formData.append('from_master', String(!!opts.fromMaster));
	if (opts.file) formData.append('file', opts.file);

	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/presenton/templates/create`, {
		method: 'POST',
		headers: {
			authorization: `Bearer ${token}`
		},
		body: formData
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getPresentonTemplateJob = async (
	token: string,
	jobId: string
): Promise<PresentonTemplateJob> => {
	let error = null;
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/document-templates/presenton/templates/job/${jobId}`,
		{
			method: 'GET',
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res as PresentonTemplateJob;
};

export const getPresentonTemplates = async (token: string): Promise<PresentonTemplate[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/presenton/templates`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.log(err);
			error = err;
			return null;
		});

	if (error) throw error;
	return (res as PresentonTemplate[]) ?? [];
};

export const deleteDocumentTemplate = async (
	token: string,
	kind: DocumentTemplateKind
): Promise<{ status: string }> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/document-templates/${kind}`, {
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
			error = err;
			return null;
		});

	if (error) throw error;
	return res;
};
