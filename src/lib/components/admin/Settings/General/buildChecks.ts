// 웹 검색 엔진별 필수 키 매핑 — Settings/WebSearch.svelte 의 conditional 블록 기반
const WEB_SEARCH_REQUIRED_KEYS: Record<string, string[]> = {
	searxng: ['SEARXNG_QUERY_URL'],
	google_pse: ['GOOGLE_PSE_API_KEY', 'GOOGLE_PSE_ENGINE_ID'],
	brave: ['BRAVE_SEARCH_API_KEY'],
	kagi: ['KAGI_SEARCH_API_KEY'],
	mojeek: ['MOJEEK_SEARCH_API_KEY'],
	bocha: ['BOCHA_SEARCH_API_KEY'],
	serpstack: ['SERPSTACK_API_KEY'],
	serper: ['SERPER_API_KEY'],
	serply: ['SERPLY_API_KEY'],
	searchapi: ['SEARCHAPI_API_KEY'],
	serpapi: ['SERPAPI_API_KEY'],
	tavily: ['TAVILY_API_KEY'],
	jina: ['JINA_API_KEY'],
	bing: ['BING_SEARCH_V7_ENDPOINT', 'BING_SEARCH_V7_SUBSCRIPTION_KEY'],
	exa: ['EXA_API_KEY'],
	perplexity: ['PERPLEXITY_API_KEY'],
	sougou: ['SOUGOU_API_SID', 'SOUGOU_API_SK'],
	duckduckgo: [] // 키 불필요
};

export type CheckStatus = 'ok' | 'ng' | 'info';

export type CheckRow = {
	id: string;
	labelKey?: string; // i18n key (label 이 없을 때 사용)
	label?: string; // 원문 라벨 (i18n 우회 — 프로파일 이름 등). 있으면 우선.
	detail: string; // 보조 텍스트 (formatDetail 에서 i18n 치환)
	status: CheckStatus;
	isHeader?: boolean; // 섹션 헤더 행
	isDefault?: boolean; // 기본값 뱃지 표시
	nested?: boolean; // 헤더 하위 — 들여쓰기 표시
	infoKey?: string; // 미설정 시 영향 안내 i18n 키 (status !== 'ok' 행에서만 노출)
};

export type ConfigBundle = {
	ollama: { ENABLE_OLLAMA_API?: boolean; OLLAMA_BASE_URLS?: string[] } | null;
	openai: {
		ENABLE_OPENAI_API?: boolean;
		OPENAI_API_BASE_URLS?: string[];
		OPENAI_API_KEYS?: string[];
	} | null;
	models: Array<{ owned_by?: string }> | null;
	embedding: { embedding_engine?: string; embedding_model?: string } | null;
	rag: { CONTENT_EXTRACTION_ENGINE?: string; web?: Record<string, unknown> | null } | null;
	searchEngine: { engine_type?: string } | null;
	webhookUrl: string;
	audio: { stt?: { ENGINE?: string }; tts?: { ENGINE?: string } } | null;
	image: {
		enabled?: boolean;
		engine?: string;
		models?: Array<{ id?: string; name?: string }>;
	} | null;
	extractionEngines: Array<{ id?: string; name?: string; engine_type?: string }> | null;
	documentProfiles: Array<{
		id?: string;
		name?: string;
		content_extraction_engine?: string;
		is_default?: boolean;
	}> | null;
	codeExecution: { ENABLE_CODE_EXECUTION?: boolean; CODE_EXECUTION_ENGINE?: string } | null;
	codeGateway: {
		enable?: boolean;
		providers?: Record<string, { enable?: boolean; type?: string; name?: string }>;
	} | null;
	kms: { KMS_PROVIDER?: string } | null;
	license: {
		enforcement_enabled?: boolean;
		has_license?: boolean;
		expires_at?: number | null;
		tier?: string | null;
	} | null;
};

// formatDetail(ConnectionCheckModal) 에서 i18n 으로 치환되는 placeholder
const NOT_CONFIGURED = '(미설정)';
const CONFIGURED = '설정됨';
const EXPIRED = '만료됨';

// 미설정 시 영향 안내 — i18n 키(= 영문 문장). ko-KR 에 번역 존재.
// ConnectionCheckModal 은 status !== 'ok' 인 행에서만 info 아이콘으로 노출한다.
const INFO = {
	llm: 'Without an LLM connection, chat, agents, and all AI responses are unavailable.',
	embedding:
		'Without an embedding engine, knowledge base (RAG) document embedding and search do not work.',
	extraction:
		'Optional. Standard documents are processed by the built-in extractor; configure an engine only for advanced OCR/Office extraction.',
	docProfile:
		'Without a document processing profile, knowledge base creation and file uploads are blocked.',
	searchEngine:
		'Without a search engine (vector DB), knowledge base search, RAG, and semantic search are unavailable.',
	webSearch: 'When web search is off, the real-time web search tool is unavailable in chat.',
	codeExecution:
		'When code execution is off, the in-chat code interpreter (running and visualizing code) is unavailable.',
	codeGateway:
		'Without the code gateway, the LLM proxy and usage management for AI coding tools (Claude Code, Cursor, Codex) are unavailable. Requires an Enterprise license.',
	webhook:
		'Without a notifications webhook, system alerts cannot be sent to external services (e.g., Slack).',
	image:
		'When image generation is not configured, the image generation feature is unavailable in chat.',
	speech:
		'Without speech configured, voice input (STT) and voice output (TTS) are unavailable in chat.',
	encryption:
		'Optional. Sensitive values are encrypted with the built-in key (fernet) by default; configure a KMS provider for external key management.',
	license:
		'Without a valid license, license-protected features—knowledge base, DbSphere, agent flows, guardrails, tracing, and evaluation—are all blocked.'
} as const;

const nonEmpty = (s: unknown): s is string => typeof s === 'string' && s.trim() !== '';

function licenseDetail(tier: string | null | undefined, hasLicense: boolean, expired: boolean): string {
	if (!hasLicense) return NOT_CONFIGURED;
	if (expired) return EXPIRED;
	return tier || CONFIGURED;
}

export function buildChecks(b: ConfigBundle): CheckRow[] {
	const rows: CheckRow[] = [];

	// 1. LLM 연결 — OpenAI 엔드포인트 수 + 모델 수 (Ollama 제외)
	const openaiEndpoints = b.openai?.ENABLE_OPENAI_API
		? (b.openai.OPENAI_API_BASE_URLS ?? []).filter(nonEmpty).length
		: 0;
	const modelCount = (b.models ?? []).filter((m) => m?.owned_by !== 'ollama').length;
	const llmOk = openaiEndpoints > 0;
	rows.push({
		id: 'llm',
		labelKey: 'LLM Connections',
		detail: llmOk ? `${openaiEndpoints} endpoints / ${modelCount} models` : NOT_CONFIGURED,
		status: llmOk ? 'ok' : 'ng',
		infoKey: INFO.llm
	});

	// 2. 임베딩 엔진
	const embEngine = b.embedding?.embedding_engine;
	const embModel = b.embedding?.embedding_model;
	const embOk = nonEmpty(embEngine) && nonEmpty(embModel);
	rows.push({
		id: 'embedding',
		labelKey: 'Embedding Engine',
		detail: embOk ? `${embEngine} / ${embModel}` : NOT_CONFIGURED,
		status: embOk ? 'ok' : 'ng',
		infoKey: INFO.embedding
	});

	// 2.5 추출 엔진 (헤더 + 엔진별 nested — 설정>문서>추출 엔진)
	const extEngines = b.extractionEngines ?? [];
	rows.push({
		id: 'extraction_engines_header',
		labelKey: 'Extraction Engines',
		detail: '',
		// 항목 있으면 ok(헤더 i 숨김), 없으면 info(헤더 i 노출)
		status: extEngines.length > 0 ? 'ok' : 'info',
		isHeader: true,
		infoKey: INFO.extraction
	});
	if (extEngines.length === 0) {
		// 외부 추출 엔진 미설정이어도 내장 로더로 표준 문서는 처리됨 → ng 아닌 info(중립).
		// 영향 안내(infoKey)는 헤더(extraction_engines_header)에 부착.
		rows.push({
			id: 'extraction_engine_empty',
			labelKey: 'Not configured',
			detail: '',
			status: 'info',
			nested: true
		});
	} else {
		for (const e of extEngines) {
			rows.push({
				id: `extraction_engine_${e.id ?? e.name ?? ''}`,
				label: e.name ?? '',
				detail: e.engine_type ?? '',
				status: 'ok',
				nested: true
			});
		}
	}

	// 3. 문서 처리 프로파일 (정보 표시 — OK/NG 판정 없음)
	const profiles = b.documentProfiles ?? [];
	rows.push({
		id: 'doc_profiles_header',
		labelKey: 'Document Processing Profiles',
		detail: '',
		status: profiles.length > 0 ? 'ok' : 'info',
		isHeader: true,
		infoKey: INFO.docProfile
	});
	if (profiles.length === 0) {
		// 프로파일이 하나도 없으면 빨강(NG)
		rows.push({
			id: 'doc_profile_empty',
			labelKey: 'Not configured',
			detail: '',
			status: 'ng',
			nested: true
		});
	} else {
		// 프로파일이 있으면 각 행 초록(OK)
		for (const pf of profiles) {
			rows.push({
				id: `doc_profile_${pf.id ?? pf.name ?? ''}`,
				label: pf.name ?? '',
				detail: nonEmpty(pf.content_extraction_engine)
					? (pf.content_extraction_engine as string)
					: NOT_CONFIGURED,
				status: 'ok',
				isDefault: pf.is_default === true,
				nested: true
			});
		}
	}

	// 4. 검색 엔진 (Vector DB)
	const vdb = b.searchEngine?.engine_type;
	const vdbOk = nonEmpty(vdb);
	rows.push({
		id: 'vector_db',
		labelKey: 'Search Engine',
		detail: vdbOk ? (vdb as string) : NOT_CONFIGURED,
		status: vdbOk ? 'ok' : 'ng',
		infoKey: INFO.searchEngine
	});

	// 5. 웹 검색 API
	const web = b.rag?.web ?? {};
	const wsEngine = web.WEB_SEARCH_ENGINE as string | undefined;
	const wsEnabled = web.ENABLE_WEB_SEARCH === true;
	const required = nonEmpty(wsEngine) ? WEB_SEARCH_REQUIRED_KEYS[wsEngine] ?? null : null;
	const keysOk = required !== null && required.every((k) => nonEmpty(web[k]));
	const wsOk = wsEnabled && nonEmpty(wsEngine) && keysOk;
	rows.push({
		id: 'web_search',
		labelKey: 'Web Search',
		detail: wsOk ? (wsEngine as string) : NOT_CONFIGURED,
		status: wsOk ? 'ok' : 'ng',
		infoKey: INFO.webSearch
	});

	// 코드 실행 엔진 (항상 표시 — 웹 검색 다음)
	const ceEnabled = b.codeExecution?.ENABLE_CODE_EXECUTION === true;
	const ceEngine = b.codeExecution?.CODE_EXECUTION_ENGINE;
	const ceOk = ceEnabled && nonEmpty(ceEngine);
	rows.push({
		id: 'code_execution',
		labelKey: 'Code Execution',
		detail: ceOk ? (ceEngine as string) : NOT_CONFIGURED,
		status: ceOk ? 'ok' : 'ng',
		infoKey: INFO.codeExecution
	});

	// 코드 게이트웨이 (헤더 + 프로바이더별 행: 활성=OK / 비활성=NG)
	// master 스위치가 꺼져 있으면 프로바이더가 설정돼 있어도 비활성 (실제 게이트웨이 UI 동작과 일치)
	const cgEnabled = b.codeGateway?.enable === true;
	const cgProviders = Object.entries(b.codeGateway?.providers ?? {});
	rows.push({
		id: 'code_gateway_header',
		labelKey: 'Code Gateway',
		detail: '',
		status: cgEnabled && cgProviders.length > 0 ? 'ok' : 'info',
		isHeader: true,
		infoKey: INFO.codeGateway
	});
	if (!cgEnabled || cgProviders.length === 0) {
		rows.push({
			id: 'code_gateway_empty',
			labelKey: 'Not configured',
			detail: '',
			status: 'ng',
			nested: true
		});
	} else {
		for (const [key, pv] of cgProviders) {
			rows.push({
				id: `code_gateway_${key}`,
				label: pv?.name || key,
				detail: pv?.type ?? '',
				status: pv?.enable === true ? 'ok' : 'ng',
				nested: true
			});
		}
	}

	// 6. Webhook
	const hookOk = nonEmpty(b.webhookUrl);
	rows.push({
		id: 'webhook',
		labelKey: 'Notifications Webhook',
		detail: hookOk ? CONFIGURED : NOT_CONFIGURED,
		status: hookOk ? 'ok' : 'ng',
		infoKey: INFO.webhook
	});

	// 7. 음성 (항상 표시 — STT/TTS 둘 다 미설정이면 NG, 하나라도 설정 시 OK)
	const sttEngine = b.audio?.stt?.ENGINE;
	const ttsEngine = b.audio?.tts?.ENGINE;
	const speechActive = nonEmpty(sttEngine) || nonEmpty(ttsEngine);
	rows.push({
		id: 'speech',
		labelKey: 'Speech (STT/TTS)',
		detail: speechActive ? `${sttEngine || '-'} / ${ttsEngine || '-'}` : NOT_CONFIGURED,
		status: speechActive ? 'ok' : 'ng', // 활성 자체로 OK (presence-only)
		infoKey: INFO.speech
	});

	// 8. 이미지 생성 (헤더 + 모델 리스트)
	const imgEnabled = b.image?.enabled === true;
	const imgModels = b.image?.models ?? [];
	rows.push({
		id: 'image_header',
		labelKey: 'Image Generation',
		detail: '',
		status: imgEnabled && imgModels.length > 0 ? 'ok' : 'info',
		isHeader: true,
		infoKey: INFO.image
	});
	if (imgEnabled && imgModels.length > 0) {
		for (const m of imgModels) {
			rows.push({
				id: `image_model_${m.id ?? m.name ?? ''}`,
				label: m.name || m.id || '',
				detail: '',
				status: 'ok',
				nested: true
			});
		}
	} else {
		rows.push({
			id: 'image_empty',
			labelKey: 'Not configured',
			detail: '',
			status: 'ng',
			nested: true
		});
	}

	// 11. 암호화 (KMS — 항상 표시)
	const kmsProvider = b.kms?.KMS_PROVIDER;
	const kmsOk = nonEmpty(kmsProvider);
	rows.push({
		id: 'encryption',
		labelKey: 'Encryption',
		detail: kmsOk ? (kmsProvider as string) : NOT_CONFIGURED,
		// KMS 미설정이어도 기본 fernet 으로 암호화됨 → ng 아닌 info(중립)
		status: kmsOk ? 'ok' : 'info',
		infoKey: INFO.encryption
	});

	// 12. 라이선스 (항상 표시 — 적용 여부)
	const hasLicense = b.license?.has_license === true;
	const expiresAt = b.license?.expires_at;
	// expires_at: Unix 초. null/0 = 무기한
	const licenseExpired =
		hasLicense && typeof expiresAt === 'number' && expiresAt > 0 && expiresAt * 1000 < Date.now();
	const licenseOk = hasLicense && !licenseExpired;
	rows.push({
		id: 'license',
		labelKey: 'License',
		detail: licenseDetail(b.license?.tier, hasLicense, licenseExpired),
		status: licenseOk ? 'ok' : 'ng',
		infoKey: INFO.license
	});

	return rows;
}
