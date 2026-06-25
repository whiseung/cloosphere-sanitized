import { describe, it, expect } from 'vitest';
import { buildChecks, type ConfigBundle } from './buildChecks';

const emptyBundle: ConfigBundle = {
	ollama: null,
	openai: null,
	models: null,
	embedding: null,
	rag: null,
	searchEngine: null,
	webhookUrl: '',
	audio: null,
	image: null,
	extractionEngines: null,
	documentProfiles: null,
	codeExecution: null,
	codeGateway: null,
	kms: null,
	license: null
};

describe('buildChecks', () => {
	it('전체 비어있을 때 ok/ng 행 모두 NG, 핵심 행 노출', () => {
		const rows = buildChecks(emptyBundle);
		const cat = rows.filter((r) => r.status === 'ok' || r.status === 'ng');
		expect(cat.every((r) => r.status === 'ng')).toBe(true);
		const ids = rows.map((r) => r.id);
		for (const id of [
			'llm',
			'embedding',
			'doc_profile_empty',
			'vector_db',
			'web_search',
			'webhook',
			'image_empty',
			'code_execution',
			'code_gateway_empty',
			'speech',
			'encryption',
			'license'
		]) {
			expect(ids).toContain(id);
		}
		// 음성도 항상 표시 — 미설정이면 NG
		expect(rows.find((r) => r.id === 'speech')?.status).toBe('ng');
	});

	it('추출 엔진: 헤더 + 엔진별 nested 행 (이름+타입, 초록)', () => {
		const rows = buildChecks({
			...emptyBundle,
			extractionEngines: [
				{ id: '1', name: 'Azure DI', engine_type: 'document_intelligence' },
				{ id: '2', name: 'Gemma - Primary', engine_type: 'llm_vision' }
			]
		});
		expect(rows.find((r) => r.isHeader && r.labelKey === 'Extraction Engines')).toBeTruthy();
		const eng = rows.filter((r) => r.id.startsWith('extraction_engine_') && !r.isHeader);
		expect(eng.map((r) => r.label)).toEqual(['Azure DI', 'Gemma - Primary']);
		expect(eng.every((r) => r.status === 'ok' && r.nested)).toBe(true);
		expect(eng[0].detail).toContain('document_intelligence');
	});

	it('추출 엔진 없어도 내장 추출로 동작 → 중립(info) nested 행, 영향 안내는 헤더', () => {
		const rows = buildChecks(emptyBundle);
		const row = rows.find((r) => r.id === 'extraction_engine_empty');
		expect(row?.status).toBe('info');
		expect(row?.infoKey).toBeFalsy();
		expect(rows.find((r) => r.id === 'extraction_engines_header')?.infoKey).toBeTruthy();
	});

	it('문서 프로파일 하나도 없으면 헤더 + 빨강(NG) 행', () => {
		const rows = buildChecks(emptyBundle);
		const header = rows.find((r) => r.isHeader && r.labelKey === 'Document Processing Profiles');
		expect(header).toBeTruthy();
		const empty = rows.find((r) => r.id === 'doc_profile_empty');
		expect(empty?.status).toBe('ng');
	});

	it('문서 프로파일 있으면 각 행 초록(OK), 이름+엔진+기본 표시', () => {
		const rows = buildChecks({
			...emptyBundle,
			documentProfiles: [
				{ id: 'a', name: 'Default', content_extraction_engine: 'document_intelligence', is_default: true },
				{ id: 'b', name: 'Gemma', content_extraction_engine: 'llm_vision', is_default: false }
			]
		});
		const pf = rows.filter((r) => r.id.startsWith('doc_profile_') && !r.isHeader);
		expect(pf.map((r) => r.label)).toEqual(['Default', 'Gemma']);
		expect(pf.every((r) => r.status === 'ok')).toBe(true);
		expect(pf.every((r) => r.nested)).toBe(true);
		expect(pf[0].isDefault).toBe(true);
		expect(pf[0].detail).toContain('document_intelligence');
		expect(pf[1].detail).toContain('llm_vision');
	});

	it('OpenAI 활성 + endpoint 있으면 LLM OK, detail에 endpoint·model 수 (ollama 제외)', () => {
		const rows = buildChecks({
			...emptyBundle,
			openai: {
				ENABLE_OPENAI_API: true,
				OPENAI_API_BASE_URLS: ['u1', 'u2', 'u3'],
				OPENAI_API_KEYS: ['k1', 'k2', 'k3']
			},
			models: [
				{ owned_by: 'openai' },
				{ owned_by: 'openai' },
				{ owned_by: 'arena' },
				{ owned_by: 'ollama' }
			]
		});
		const row = rows.find((r) => r.id === 'llm');
		expect(row?.status).toBe('ok');
		expect(row?.detail).toContain('3 endpoints');
		expect(row?.detail).toContain('3 models'); // 4개 중 ollama 1개 제외
	});

	it('OpenAI 비활성이면 LLM NG (Ollama 활성이어도 무시)', () => {
		const rows = buildChecks({
			...emptyBundle,
			ollama: { ENABLE_OLLAMA_API: true, OLLAMA_BASE_URLS: ['http://localhost:11434'] },
			openai: { ENABLE_OPENAI_API: false, OPENAI_API_BASE_URLS: [] }
		});
		expect(rows.find((r) => r.id === 'llm')?.status).toBe('ng');
	});

	it('임베딩 engine 만 있고 model 비어있으면 NG', () => {
		const rows = buildChecks({
			...emptyBundle,
			embedding: { embedding_engine: 'ollama', embedding_model: '' }
		});
		expect(rows.find((r) => r.id === 'embedding')?.status).toBe('ng');
	});

	it('Vector DB engine_type 채워지면 OK', () => {
		const rows = buildChecks({
			...emptyBundle,
			searchEngine: { engine_type: 'qdrant' }
		});
		expect(rows.find((r) => r.id === 'vector_db')?.status).toBe('ok');
	});

	it('웹 검색 google_pse 선택 + 두 키 모두 채워지면 OK', () => {
		const rows = buildChecks({
			...emptyBundle,
			rag: {
				CONTENT_EXTRACTION_ENGINE: '',
				web: {
					ENABLE_WEB_SEARCH: true,
					WEB_SEARCH_ENGINE: 'google_pse',
					GOOGLE_PSE_API_KEY: 'k',
					GOOGLE_PSE_ENGINE_ID: 'id'
				}
			}
		});
		expect(rows.find((r) => r.id === 'web_search')?.status).toBe('ok');
	});

	it('웹 검색 google_pse 선택 + 키 하나 비어있으면 NG', () => {
		const rows = buildChecks({
			...emptyBundle,
			rag: {
				CONTENT_EXTRACTION_ENGINE: '',
				web: {
					ENABLE_WEB_SEARCH: true,
					WEB_SEARCH_ENGINE: 'google_pse',
					GOOGLE_PSE_API_KEY: 'k',
					GOOGLE_PSE_ENGINE_ID: ''
				}
			}
		});
		expect(rows.find((r) => r.id === 'web_search')?.status).toBe('ng');
	});

	it('웹 검색 ENABLE_WEB_SEARCH=false 면 NG (정책: 항상 표시)', () => {
		const rows = buildChecks({
			...emptyBundle,
			rag: { CONTENT_EXTRACTION_ENGINE: '', web: { ENABLE_WEB_SEARCH: false, WEB_SEARCH_ENGINE: '' } }
		});
		expect(rows.find((r) => r.id === 'web_search')?.status).toBe('ng');
	});

	it('duckduckgo 선택 시 키 없이도 OK', () => {
		const rows = buildChecks({
			...emptyBundle,
			rag: {
				CONTENT_EXTRACTION_ENGINE: '',
				web: { ENABLE_WEB_SEARCH: true, WEB_SEARCH_ENGINE: 'duckduckgo' }
			}
		});
		expect(rows.find((r) => r.id === 'web_search')?.status).toBe('ok');
	});

	it('webhookUrl 채워지면 OK', () => {
		const rows = buildChecks({ ...emptyBundle, webhookUrl: 'https://example.com/hook' });
		expect(rows.find((r) => r.id === 'webhook')?.status).toBe('ok');
	});

	it('음성: 항상 표시 — STT/TTS 둘 다 미설정이면 NG, 하나라도 설정 시 OK', () => {
		const off = buildChecks({ ...emptyBundle, audio: { stt: { ENGINE: '' }, tts: { ENGINE: '' } } });
		const offRow = off.find((r) => r.id === 'speech');
		expect(offRow?.status).toBe('ng');
		expect(offRow?.infoKey).toBeTruthy();

		const on = buildChecks({
			...emptyBundle,
			audio: { stt: { ENGINE: 'openai' }, tts: { ENGINE: '' } }
		});
		expect(on.find((r) => r.id === 'speech')?.status).toBe('ok');
	});

	it('이미지 생성: 헤더 + 모델(연결) 리스트 전부 nested OK', () => {
		const on = buildChecks({
			...emptyBundle,
			image: {
				enabled: true,
				engine: 'azure_openai',
				models: [{ name: 'gpt-image-1.5' }, { name: 'gpt-image-2' }]
			}
		});
		expect(on.find((r) => r.isHeader && r.labelKey === 'Image Generation')).toBeTruthy();
		const im = on.filter((r) => r.id.startsWith('image_model_'));
		expect(im.map((r) => r.label)).toEqual(['gpt-image-1.5', 'gpt-image-2']);
		expect(im.every((r) => r.status === 'ok' && r.nested)).toBe(true);
	});

	it('이미지 생성: 비활성/모델 없으면 빨강(NG) nested 행', () => {
		const off = buildChecks({ ...emptyBundle, image: { enabled: false } });
		const row = off.find((r) => r.id === 'image_empty');
		expect(row?.status).toBe('ng');
		expect(row?.nested).toBe(true);
	});

	it('코드 실행: 엔진 설정되면 OK + 엔진명, 비활성이면 NG', () => {
		const on = buildChecks({
			...emptyBundle,
			codeExecution: { ENABLE_CODE_EXECUTION: true, CODE_EXECUTION_ENGINE: 'jupyter' }
		});
		const row = on.find((r) => r.id === 'code_execution');
		expect(row?.status).toBe('ok');
		expect(row?.detail).toContain('jupyter');

		const off = buildChecks({
			...emptyBundle,
			codeExecution: { ENABLE_CODE_EXECUTION: false, CODE_EXECUTION_ENGINE: 'jupyter' }
		});
		expect(off.find((r) => r.id === 'code_execution')?.status).toBe('ng');
	});

	it('암호화: KMS provider 설정되면 OK + provider명', () => {
		const rows = buildChecks({ ...emptyBundle, kms: { KMS_PROVIDER: 'azkv-env' } });
		const row = rows.find((r) => r.id === 'encryption');
		expect(row?.status).toBe('ok');
		expect(row?.detail).toContain('azkv-env');
	});

	it('암호화: KMS 미설정이어도 기본 fernet → 중립(info) + 영향 안내', () => {
		const row = buildChecks(emptyBundle).find((r) => r.id === 'encryption');
		expect(row?.status).toBe('info');
		expect(row?.infoKey).toBeTruthy();
	});

	it('코드 게이트웨이: 헤더 + 프로바이더별 행 (활성=OK / 비활성=NG)', () => {
		const rows = buildChecks({
			...emptyBundle,
			codeGateway: {
				enable: true,
				providers: {
					azure_openai: { enable: true, type: 'azure_openai', name: 'azure_openai' },
					'claude-sykim': { enable: false, type: 'anthropic', name: 'claude-sykim' }
				}
			}
		});
		expect(
			rows.find((r) => r.isHeader && r.labelKey === 'Code Gateway')
		).toBeTruthy();
		const prov = rows.filter((r) => r.id.startsWith('code_gateway_') && !r.isHeader);
		expect(prov.map((r) => r.label)).toEqual(['azure_openai', 'claude-sykim']);
		expect(prov.every((r) => r.nested)).toBe(true);
		expect(prov.find((r) => r.label === 'azure_openai')?.status).toBe('ok');
		expect(prov.find((r) => r.label === 'claude-sykim')?.status).toBe('ng');
	});

	it('코드 게이트웨이: 프로바이더 없으면 빨강(NG) 행', () => {
		const rows = buildChecks({ ...emptyBundle, codeGateway: { enable: true, providers: {} } });
		expect(rows.find((r) => r.id === 'code_gateway_empty')?.status).toBe('ng');
	});

	it('코드 게이트웨이: master enable=false 면 프로바이더 있어도 빨강 행만', () => {
		const rows = buildChecks({
			...emptyBundle,
			codeGateway: {
				enable: false,
				providers: { azure_openai: { enable: true, type: 'azure_openai', name: 'azure_openai' } }
			}
		});
		expect(rows.find((r) => r.id === 'code_gateway_empty')?.status).toBe('ng');
		const provRows = rows.filter(
			(r) => r.id.startsWith('code_gateway_') && !r.isHeader && r.id !== 'code_gateway_empty'
		);
		expect(provRows).toHaveLength(0);
	});

	it('라이선스: 항상 표시 — 미적용이면 NG', () => {
		const rows = buildChecks({ ...emptyBundle, license: { has_license: false } });
		expect(rows.find((r) => r.id === 'license')?.status).toBe('ng');
	});

	it('라이선스: 적용 + 만료일 없으면 OK (tier 표시)', () => {
		const rows = buildChecks({
			...emptyBundle,
			license: { has_license: true, expires_at: null, tier: 'enterprise' }
		});
		const row = rows.find((r) => r.id === 'license');
		expect(row?.status).toBe('ok');
		expect(row?.detail).toContain('enterprise');
	});

	it('라이선스: 적용 + 미래 만료면 OK', () => {
		const rows = buildChecks({
			...emptyBundle,
			license: { has_license: true, expires_at: 9999999999 }
		});
		expect(rows.find((r) => r.id === 'license')?.status).toBe('ok');
	});

	it('라이선스: 적용됐어도 만료되면 NG', () => {
		const rows = buildChecks({
			...emptyBundle,
			license: { has_license: true, expires_at: 1000000000 }
		});
		expect(rows.find((r) => r.id === 'license')?.status).toBe('ng');
	});

	it('영향 안내(infoKey): 단독 행 + 그룹 섹션 헤더가 보유 (모달 노출 대상)', () => {
		const rows = buildChecks(emptyBundle);
		const withInfo = rows.filter((r) => r.infoKey);
		// 단독 행 9개(음성 포함) + 그룹 섹션 헤더 4개 = 13
		expect(withInfo).toHaveLength(13);
		// 모달은 status !== 'ok' 행에서만 노출 → 빈 설정에선 전부 노출 대상 (헤더 status 'info')
		expect(withInfo.every((r) => r.status !== 'ok')).toBe(true);
		// 그룹 섹션은 헤더에 부착, nested empty 행엔 미부착
		for (const h of [
			'extraction_engines_header',
			'doc_profiles_header',
			'code_gateway_header',
			'image_header'
		]) {
			expect(rows.find((r) => r.id === h)?.infoKey).toBeTruthy();
		}
		for (const e of [
			'extraction_engine_empty',
			'doc_profile_empty',
			'code_gateway_empty',
			'image_empty'
		]) {
			expect(rows.find((r) => r.id === e)?.infoKey).toBeFalsy();
		}
	});

	it('그룹 섹션 헤더: 항목 있으면 status ok(i 숨김), 없으면 info(i 노출)', () => {
		const groupHeaders = [
			'extraction_engines_header',
			'doc_profiles_header',
			'code_gateway_header',
			'image_header'
		];
		// 전부 비어있으면 → 헤더 info (i 노출 대상)
		const empty = buildChecks(emptyBundle);
		for (const h of groupHeaders) {
			expect(empty.find((r) => r.id === h)?.status).toBe('info');
		}
		// 각 섹션에 항목 채우면 → 헤더 ok (i 숨김)
		const filled = buildChecks({
			...emptyBundle,
			extractionEngines: [{ id: '1', name: 'A', engine_type: 'tika' }],
			documentProfiles: [{ id: 'a', name: 'P', content_extraction_engine: 'tika' }],
			codeGateway: { enable: true, providers: { p: { enable: true, type: 'openai', name: 'p' } } },
			image: { enabled: true, models: [{ name: 'm' }] }
		});
		for (const h of groupHeaders) {
			expect(filled.find((r) => r.id === h)?.status).toBe('ok');
		}
	});
});
