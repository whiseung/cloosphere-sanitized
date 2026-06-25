<script lang="ts">
	import { onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import type { Readable } from 'svelte/store';
	import { models, user } from '$lib/stores';

	import AdvancedParams from '$lib/components/chat/Settings/Advanced/AdvancedParams.svelte';
	import Tags from '$lib/components/common/Tags.svelte';
	import Knowledge from '$lib/components/workspace/Agents/Knowledge.svelte';
	import DbSphere from '$lib/components/workspace/Agents/DbSphere.svelte';
	import Glossary from '$lib/components/workspace/Agents/Glossary.svelte';
	import KnowledgeGraph from '$lib/components/workspace/Agents/KnowledgeGraph.svelte';
	import GuardrailsSection from '$lib/components/workspace/Agents/Guardrails.svelte';
	import AutoEvaluationSection from '$lib/components/workspace/Agents/AutoEvaluation.svelte';
	import ResponseFormatSection from '$lib/components/workspace/Agents/ResponseFormat.svelte';
	import ToolConnections from '$lib/components/workspace/Agents/ToolConnections.svelte';
	import MarketplaceTools from '$lib/components/workspace/Agents/MarketplaceTools.svelte';
	import { isMenuVisible } from '$lib/config/menuConfig';
	import Capabilities from '$lib/components/workspace/Agents/Capabilities.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import { getLicensePermissions, type LicensePermission } from '$lib/apis/license_permissions';
	import AccessControl from '../common/AccessControl.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import AgentVersionHistoryModal from './AgentVersionHistoryModal.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import { toast } from 'svelte-sonner';
	import { brandingUrls } from '$lib/stores/branding';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import { formatBackendError } from '$lib/utils/error';

	type I18nStore = Readable<{
		t: (key: string, options?: Record<string, unknown>) => string;
	}>;

	const i18n = getContext<I18nStore>('i18n');

	export let onSubmit: Function;
	export let onBack: null | Function = null;
	export let onRestored: null | Function = null;

	export let model = null;
	export let edit = false;

	export let preset = true;

	let loading = false;
	let showAccessControlModal = false;
	let showVersionHistory = false;
	let tagSelector: any;
	let success = false;

	let filesInputElement;
	let inputFiles;

	let showAdvanced = false;
	let showPreview = false;

	$: canWrite = $user?.role === 'admin' || $user?.permissions?.workspace?.agents === 'write';

	let loaded = false;

	// Sphere 관련 상태
	let licensePermissions: LicensePermission | null = null;
	let formatPrompt = '';
	let generatingTaskPrompt = false;
	let generatingFormatPrompt = false;
	let aiTaskModelId = '';
	let aiFormatModelId = '';
	let baseModelValue = '';
	$: info.base_model_id = baseModelValue || null;

	// ///////////
	// model
	// ///////////

	let id = '';
	let name = '';

	let enableDescription = true;

	$: if (!edit) {
		if (name) {
			id = name
				.replace(/\s+/g, '-')
				.replace(/[^a-zA-Z0-9-]/g, '')
				.toLowerCase();
		}
	}

	let info = {
		id: '',
		base_model_id: null as string | null,
		name: '',
		meta: {
			profile_image_url: $brandingUrls.favicon,
			description: '',
			suggestion_prompts: null,
			tags: []
		},
		params: {
			system: ''
		}
	};

	let params = {
		system: ''
	};
	let capabilities: Record<string, string | boolean> = {
		web_search: 'off',
		image_generation: 'off',
		gmail: 'off',
		calendar: 'off',
		drive: 'off',
		// 추론 과정 노출 수준 — 기본 brief(기존 단순 표시). 저장은
		// meta.capabilities.show_reasoning = 'brief'|'detailed'|'off'.
		show_reasoning: 'brief',
		// grounding — 엄격 근거 준수 모드. 컨텍스트 기본: 에이전트(preset)=on,
		// 기본 모델=off. 저장은 meta.capabilities.grounding = 'on'|'off'.
		grounding: preset ? 'on' : 'off',
		// ask_user(HITL) — 정보 부족/의도 모호 시 사용자에게 되묻기. 기본 off(opt-in).
		// 저장은 meta.capabilities.ask_user = 'on'/'off'. (Capabilities 패널에서 토글)
		ask_user: 'off'
	};

	let webSearchConfig = {
		result_count: null as number | null,
		domain_filter_list: null as string[] | null
	};
	let imageGenerationConfig = {
		connection_ids: [] as number[],
		names: [] as string[]
	};

	let knowledge = [];
	let dbspheres: any[] = [];
	let glossaries: any[] = [];
	let knowledgeGraphs: any[] = [];

	// KG → resource 자동 머지로 들어오는 ID 셋. KnowledgeGraph 컴포넌트가 채워주고
	// Knowledge/DbSphere/Glossary 서브컴포넌트에 excludeIds로 전달돼서 picker에서 숨김.
	let inheritedKnowledgeIds: string[] = [];
	let inheritedDbsphereIds: string[] = [];
	let inheritedGlossaryIds: string[] = [];
	let toolConnections: any[] = [];
	let marketplaceTools: any[] = [];
	let guardrailsList: any[] = [];
	let autoEvaluation = {
		enabled: false,
		samplingRate: 0.1,
		evaluationTypes: [] as string[],
		judgeModelId: null as string | null
	};
	let responseFormat: {
		type: 'text' | 'json_schema';
		json_schema?: {
			name: string;
			description?: string;
			schema: object;
			strict?: boolean;
		};
	} = { type: 'text' };

	let accessControl: any = {
		read: {
			group_ids: [],
			user_ids: [$user?.id]
		},
		write: {
			group_ids: [],
			user_ids: [$user?.id]
		}
	};

	type SelectorModelOption = {
		id: string;
		name: string;
		preset?: boolean;
		arena?: boolean;
		owned_by?: string;
	};

	function getBaseModelSelectorItems() {
		return [
			{
				value: '',
				label: $i18n.t('Select a base model')
			},
			...((($models as SelectorModelOption[]) ?? [])
			.filter((candidate) => (model ? candidate.id !== model.id : true) && !candidate.preset && candidate.owned_by !== 'arena')
			.map((candidate) => ({
				value: candidate.id,
				label: candidate.name
			})))
		];
	}

	function getAiGenerationModelItems() {
		return [
			{
				value: '',
				label: $i18n.t('Select AI Model (Default)')
			},
			...((($models as SelectorModelOption[]) ?? [])
			.filter((candidate) => !candidate.preset && !candidate.arena)
			.map((candidate) => ({
				value: candidate.id,
				label: candidate.name
			})))
		];
	}

	async function aiGenerate(prompt: string, modelId: string = ''): Promise<string> {
		const body: Record<string, any> = { prompt, max_completion_tokens: 4096 };
		if (modelId) body.model = modelId;
		const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/generate`, {
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${localStorage.token}`
			},
			body: JSON.stringify(body)
		});

		if (!res.ok) {
			const err = await res.json().catch(() => ({}));
			throw new Error(formatBackendError(err, $i18n) ?? `HTTP ${res.status}`);
		}

		const data = await res.json();
		const content =
			data?.choices?.[0]?.message?.content ??
			data?.response ??
			data?.content ??
			(typeof data === 'string' ? data : '');

		if (!content && data?.choices?.[0]?.finish_reason === 'content_filter') {
			throw new Error($i18n.t('Content was filtered by the AI safety system. Please modify your input.'));
		}
		return content;
	}

	function buildResourceSummary(): string {
		const parts: string[] = [];
		if (knowledge.length > 0)
			parts.push(`지식베이스(RAG 문서검색): ${knowledge.map((k) => k.name || k.id).join(', ')}`);
		if (dbspheres.length > 0)
			parts.push(`데이터베이스(자연어→SQL 조회): ${dbspheres.map((d) => d.name || d.id).join(', ')}`);
		if (glossaries.length > 0)
			parts.push(`용어집(도메인 용어 참조): ${glossaries.map((g) => g.name || g.id).join(', ')}`);
		if (knowledgeGraphs.length > 0)
			parts.push(
				`지식그래프(용어 매핑/스키마 관계 추론): ${knowledgeGraphs.map((g) => g.name || g.id).join(', ')}`
			);
		if (toolConnections.length > 0)
			parts.push(`외부 도구: ${toolConnections.map((t) => t.name || t.id).join(', ')}`);
		const caps: string[] = [];
		if (capabilities.web_search && capabilities.web_search !== 'off') caps.push('웹 검색');
		if (capabilities.image_generation && capabilities.image_generation !== 'off') caps.push('이미지 생성');
		if (caps.length > 0) parts.push(`기능: ${caps.join(', ')}`);
		return parts.map((p) => `- ${p}`).join('\n');
	}

	async function aiGenerateTaskPrompt() {
		if (generatingTaskPrompt) return;
		generatingTaskPrompt = true;
		try {
			const resources = buildResourceSummary();
			const hasDraft = !!info.params.system?.trim();

			const prompt = `에이전트 시스템 프롬프트(작업 프롬프트)를 작성하라.

[작업 프롬프트란?]
에이전트의 역할, 행동 원칙, 제약 사항을 정의하는 시스템 프롬프트다.
답변 형식(마크다운, 어조, 길이 등)은 여기서 다루지 않는다. 별도의 "답변 포맷 프롬프트"가 담당한다.

[플랫폼 구조 - 반드시 숙지]
이 에이전트는 Cloosphere 플랫폼 위에서 동작한다.
문서 검색, DB 조회, 용어집 참조 등은 플랫폼이 자동으로 수행하며, 에이전트가 직접 SQL을 작성하거나 도구를 호출하지 않는다.
에이전트는 플랫폼이 수집한 정보를 받아 사용자에게 답변하는 역할만 한다.
따라서 작업 프롬프트에 도구 사용법, SQL 작성 규칙, 검색 방법 등 기술적 지침을 포함하지 마라.

[에이전트]
이름: ${name || '미정'}
설명: ${info.meta.description || '없음'}
${resources ? `사용 가능한 리소스: ${resources.replace(/\n/g, ', ').replace(/- /g, '')}` : ''}
${hasDraft ? `\n[사용자 초안]\n${info.params.system.trim()}` : ''}

[규칙]
${hasDraft ? '- 초안의 의도를 살려 역할, 행동 지침, 제약 사항을 구체화하라' : '- 에이전트 이름, 설명, 리소스를 참고하여 역할, 행동 지침, 제약 사항을 작성하라'}
- 답변 형식/어조/길이, 도구 사용법/SQL/검색 방법은 작성하지 마라
- 간결하게 작성하라
- 프롬프트 본문만 출력하라`;

			const result = await aiGenerate(prompt, aiTaskModelId);
			if (result) {
				info.params.system = result.trim();
				info = info;
			} else {
				toast.warning($i18n.t('No result generated. Please try again.'));
			}
		} catch (e: any) {
			toast.error(e?.message ?? formatBackendError(e, $i18n) ?? `${e}`);
		} finally {
			generatingTaskPrompt = false;
		}
	}

	async function aiGenerateFormatPrompt() {
		if (generatingFormatPrompt) return;
		generatingFormatPrompt = true;
		try {
			const hasDraft = !!formatPrompt?.trim();

			const prompt = `에이전트의 답변 포맷 프롬프트를 작성하라.

[답변 포맷 프롬프트란?]
에이전트가 최종 답변을 생성할 때 따르는 출력 형식 지침이다.
역할/행동/제약은 별도의 "작업 프롬프트"가 담당하므로 여기서 다루지 않는다.
이 지침은 시스템 프롬프트의 "## Response Format Instructions" 섹션에 삽입된다.

[에이전트]
이름: ${name || '미정'}
작업 프롬프트 요약: ${info.params.system ? info.params.system.substring(0, 300) : '없음'}
${hasDraft ? `\n[사용자 초안]\n${formatPrompt.trim()}` : ''}

[규칙]
${hasDraft ? '- 초안의 의도를 살려 답변 출력 형식을 구체화하라' : '- 에이전트 이름과 작업 프롬프트를 참고하여 적절한 답변 출력 형식을 작성하라'}
- 마크다운 스타일, 답변 구조, 어조, 길이 등 형식 관련 사항만 다뤄라
- 에이전트 역할/행동/제약은 작성하지 마라
- 간결하게 작성하라
- 포맷 지침 본문만 출력하라`;

			const result = await aiGenerate(prompt, aiFormatModelId);
			if (result) {
				formatPrompt = result.trim();
			} else {
				toast.warning($i18n.t('No result generated. Please try again.'));
			}
		} catch (e: any) {
			toast.error(e?.message ?? formatBackendError(e, $i18n) ?? `${e}`);
		} finally {
			generatingFormatPrompt = false;
		}
	}

	const submitHandler = async () => {
		loading = true;

		info.id = id;
		info.name = name;
		info.base_model_id = baseModelValue || null;

		if (preset && !baseModelValue) {
			toast.error($i18n.t('Base Model is required.'));
			loading = false;
			return;
		}

		if (id === '') {
			toast.error($i18n.t('Model ID is required.'));
		}

		if (name === '') {
			toast.error($i18n.t('Model Name is required.'));
		}

		info.access_control = accessControl;
		info.meta.capabilities = {
			...capabilities,
			...(capabilities.web_search !== 'off' && (webSearchConfig.result_count !== null || webSearchConfig.domain_filter_list !== null)
				? { web_search_config: webSearchConfig }
				: {}),
			...(capabilities.image_generation !== 'off' && imageGenerationConfig.connection_ids.length > 0
				? { image_generation_config: imageGenerationConfig }
				: {})
		};

		if (enableDescription) {
			info.meta.description = info.meta.description.trim() === '' ? null : info.meta.description;
		} else {
			info.meta.description = null;
		}

		if (knowledge.length > 0) {
			info.meta.knowledge = knowledge;
		} else if (info.meta.knowledge) {
			delete info.meta.knowledge;
		}

		if (dbspheres.length > 0) {
			info.meta.dbspheres = dbspheres;
		} else if (info.meta.dbspheres) {
			delete info.meta.dbspheres;
		}

		if (glossaries.length > 0) {
			info.meta.glossaries = glossaries;
		} else if (info.meta.glossaries) {
			delete info.meta.glossaries;
		}

		if (knowledgeGraphs.length > 0) {
			info.meta.knowledge_graphs = knowledgeGraphs;
		} else if (info.meta.knowledge_graphs) {
			delete info.meta.knowledge_graphs;
		}

		if (toolConnections.length > 0) {
			info.meta.toolConnections = toolConnections;
		} else if (info.meta.toolConnections) {
			delete info.meta.toolConnections;
		}

		if (marketplaceTools.length > 0) {
			info.meta.marketplaceTools = marketplaceTools;
		} else if (info.meta.marketplaceTools) {
			delete info.meta.marketplaceTools;
		}

		// Save guardrails
		if (guardrailsList.length > 0) {
			info.meta.guardrails = guardrailsList.map((g) => g.id);
		} else if (info.meta.guardrails) {
			delete info.meta.guardrails;
		}

		// Save auto evaluation settings
		if (autoEvaluation.enabled) {
			info.meta.autoEvaluation = {
				enabled: autoEvaluation.enabled,
				samplingRate: autoEvaluation.samplingRate,
				evaluationTypes: autoEvaluation.evaluationTypes,
				judgeModelId: autoEvaluation.judgeModelId
			};
		} else if (info.meta.autoEvaluation) {
			delete info.meta.autoEvaluation;
		}

		// Save response format settings
		if (responseFormat.type === 'json_schema' && responseFormat.json_schema) {
			info.meta.responseFormat = responseFormat;
		} else if (info.meta.responseFormat) {
			delete info.meta.responseFormat;
		}

		info.params.stop = params.stop ? params.stop.split(',').filter((s) => s.trim()) : null;

		// 답변 포멧 프롬프트 저장
		if (formatPrompt.trim()) {
			info.params.format_prompt = formatPrompt.trim();
		} else {
			delete info.params.format_prompt;
		}

		// 레거시 플래그 정리
		delete info.params.enable_kbsphere;
		delete info.params.enable_dbsphere;
		delete info.params.email_provider;

		Object.keys(info.params).forEach((key) => {
			if (info.params[key] === '' || info.params[key] === null) {
				delete info.params[key];
			}
		});

		// 태그 변경사항 커밋 (onSubmit이 페이지 이동할 수 있으므로 먼저 실행)
		if (tagSelector?.commitChanges) {
			try {
				await tagSelector.commitChanges();
			} catch (e) {
				console.error('Failed to commit tag changes:', e);
			}
		}

		await onSubmit(info);

		loading = false;
		success = false;
	};

	function handleCancel() {
		if (onBack) {
			onBack();
			return;
		}

		goto('/workspace/agents');
	}

	onMount(async () => {
		// License permissions 로드
		licensePermissions = await getLicensePermissions(localStorage.token).catch(() => null);

		// Scroll to top 'workspace-container' element
		const workspaceContainer = document.getElementById('workspace-container');
		if (workspaceContainer) {
			workspaceContainer.scrollTop = 0;
		}

		if (model) {
			name = model.name;
			await tick();

			id = model.id;

			enableDescription = model?.meta?.description !== null;

			if (model.base_model_id) {
				const base_model = $models
					.filter((m) => !m?.preset && !(m?.arena ?? false))
					.find((m) => [model.base_model_id, `${model.base_model_id}:latest`].includes(m.id));

				console.log('base_model', base_model);

				if (base_model) {
					model.base_model_id = base_model.id;
				} else {
					model.base_model_id = null;
				}
			}

			baseModelValue = model.base_model_id ?? '';

			params = { ...params, ...model?.params };
			params.stop = params?.stop
				? (typeof params.stop === 'string' ? params.stop.split(',') : (params?.stop ?? [])).join(
						','
					)
				: null;

			knowledge = (model?.meta?.knowledge ?? []).map((item) => {
				if (item?.collection_name) {
					return {
						id: item.collection_name,
						name: item.name,
						legacy: true
					};
				} else if (item?.collection_names) {
					return {
						name: item.name,
						type: 'collection',
						collection_names: item.collection_names,
						legacy: true
					};
				} else {
					return item;
				}
			});
			const savedCaps = model?.meta?.capabilities ?? {};
		// Normalize legacy boolean → string enum
		const normCap = (v: any) => {
			if (v === true) return 'on';
			if (v === false || v === undefined || v === null) return 'off';
			if (['off', 'on', 'user'].includes(v)) return v;
			return 'off';
		};
		// show_reasoning 은 노출 수준(off/brief/detailed) — capability normCap
		// (off/on/user) 과 값 도메인이 달라 별도 정규화. legacy on/true → detailed.
		const normShowReasoning = (v: any) => {
			if (v === true || v === 'on' || v === 'detailed') return 'detailed';
			if (v === false || v === 'off' || v === 'none') return 'off';
			return 'brief';
		};
		// grounding — binary(on/off). 명시값(on/off)은 존중하고, 미설정/legacy 는
		// 백엔드와 동일하게 컨텍스트 기본(에이전트 preset=on / 기본 모델=off) 적용.
		const groundingDefault = preset ? 'on' : 'off';
		const normGrounding = (v: any) => {
			if (v === false || v === 'off') return 'off';
			if (v === true || v === 'on') return 'on';
			return groundingDefault;
		};
		capabilities = {
			web_search: normCap(savedCaps.web_search),
			image_generation: normCap(savedCaps.image_generation),
			gmail: normCap(savedCaps.gmail),
			calendar: normCap(savedCaps.calendar),
			drive: normCap(savedCaps.drive),
			show_reasoning: normShowReasoning(savedCaps.show_reasoning),
			grounding: normGrounding(savedCaps.grounding),
			// ask_user(HITL): 기본 off(opt-in). 구 키 human_in_the_loop fallback —
			// 명시 저장돼 있으면 존중. normCap 미설정→'off'.
			ask_user: normCap(savedCaps.ask_user ?? savedCaps.human_in_the_loop)
		};
		const savedWsConfig = savedCaps.web_search_config ?? {};
		webSearchConfig = {
			result_count: savedWsConfig.result_count ?? null,
			domain_filter_list: savedWsConfig.domain_filter_list ?? null
		};
		const savedImgConfig = savedCaps.image_generation_config ?? {};
		// Support both new multi-select and legacy single-select
		let connIds = savedImgConfig.connection_ids ?? [];
		let connNames = savedImgConfig.names ?? [];
		if (connIds.length === 0 && savedImgConfig.connection_idx != null) {
			connIds = [savedImgConfig.connection_idx];
			connNames = savedImgConfig.name ? [savedImgConfig.name] : [];
		}
		imageGenerationConfig = {
			connection_ids: connIds,
			names: connNames
		};

			if ('access_control' in model) {
				accessControl = model.access_control;
			} else {
				accessControl = null;
			}

			console.log(model?.access_control);
			console.log(accessControl);

			// Sphere 관련 데이터 복원
			formatPrompt = model?.params?.format_prompt ?? '';

			knowledgeGraphs = (model?.meta as any)?.knowledge_graphs ?? [];
			// Load dbspheres, glossaries, toolConnections, and guardrails
			dbspheres = model?.meta?.dbspheres ?? [];
			glossaries = model?.meta?.glossaries ?? [];
			toolConnections = model?.meta?.toolConnections ?? [];
			marketplaceTools = model?.meta?.marketplaceTools ?? [];

			// Load guardrails by IDs
			const guardrailIds = model?.meta?.guardrails ?? [];
			if (guardrailIds.length > 0) {
				const { getGuardrails } = await import('$lib/apis/guardrails');
				const allGuardrails = await getGuardrails(localStorage.token);
				guardrailsList = allGuardrails.filter((g) => guardrailIds.includes(g.id));
			} else {
				guardrailsList = [];
			}

			// Load auto evaluation settings
			if (model?.meta?.autoEvaluation) {
				autoEvaluation = {
					enabled: model.meta.autoEvaluation.enabled ?? false,
					samplingRate: model.meta.autoEvaluation.samplingRate ?? 0.1,
					evaluationTypes: model.meta.autoEvaluation.evaluationTypes ?? [],
					judgeModelId: model.meta.autoEvaluation.judgeModelId ?? null
				};
			}

			// Load response format settings
			if (model?.meta?.responseFormat) {
				responseFormat = model.meta.responseFormat;
			}

			info = {
				...info,
				...JSON.parse(
					JSON.stringify(
						model
							? model
							: {
									id: model.id,
									name: model.name
								}
					)
				)
			};

			console.log(model);
		}

		loaded = true;
	});
</script>

{#if loaded}
	<input
		bind:this={filesInputElement}
		bind:files={inputFiles}
		type="file"
		hidden
		accept="image/*"
		on:change={() => {
			let reader = new FileReader();
			reader.onload = (event) => {
				let originalImageUrl = `${event.target.result}`;

				const img = new Image();
				img.src = originalImageUrl;

				img.onload = function () {
					const canvas = document.createElement('canvas');
					const ctx = canvas.getContext('2d');

					const aspectRatio = img.width / img.height;

					let newWidth, newHeight;
					if (aspectRatio > 1) {
						newWidth = 250 * aspectRatio;
						newHeight = 250;
					} else {
						newWidth = 250;
						newHeight = 250 / aspectRatio;
					}

					canvas.width = 250;
					canvas.height = 250;

					const offsetX = (250 - newWidth) / 2;
					const offsetY = (250 - newHeight) / 2;

					ctx.drawImage(img, offsetX, offsetY, newWidth, newHeight);

					const compressedSrc = canvas.toDataURL();

					info.meta.profile_image_url = compressedSrc;

					inputFiles = null;
					filesInputElement.value = '';
				};
			};

			if (
				inputFiles &&
				inputFiles.length > 0 &&
				['image/gif', 'image/webp', 'image/jpeg', 'image/png', 'image/svg+xml'].includes(
					inputFiles[0]['type']
				)
			) {
				reader.readAsDataURL(inputFiles[0]);
			} else {
				console.log(`Unsupported File Type '${inputFiles[0]['type']}'.`);
				inputFiles = null;
			}
		}}
	/>

	{#if !edit || (edit && model)}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl
			allowPublic={$user?.permissions?.sharing?.public_models || $user?.role === 'admin'}
			onChange={() => {}}
			accessRoles={['read', 'write']}
		/>

		<AgentVersionHistoryModal
			bind:show={showVersionHistory}
			agentId={id}
			{canWrite}
			currentSystem={info?.params?.system ?? ''}
			currentFormat={formatPrompt}
			onRestored={onRestored ?? (() => location.reload())}
		/>

		<form
			class="agent-editor"
			on:submit|preventDefault={() => {
				submitHandler();
			}}
		>
			<div class="agent-editor__shell">
				<div class="agent-editor__header">
					<div class="agent-editor__title-wrap">
						<div class="flex items-center gap-2">
							{#if onBack}
								<button
									class="p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850"
									type="button"
									on:click={() => {
										onBack();
									}}
								>
									<ChevronLeft strokeWidth="2.5" className="size-4" />
								</button>
							{/if}
							<h1 class="agent-editor__title">
								{#if edit}
									{$i18n.t('Edit Agent')}
								{:else}
									{$i18n.t('Create Agent')}
								{/if}
							</h1>
						</div>
					</div>

					<div class="agent-editor__header-actions">
						<slot name="header-actions" />

						{#if edit && id}
							<WorkspaceTagSelector bind:this={tagSelector} resourceType="agent" resourceId={id} />
							<Button kind="outlined" size="md" on:click={() => (showVersionHistory = true)}>
								{$i18n.t('Version History')}
							</Button>
						{/if}

						{#if canWrite}
							<Button kind="outlined" size="md" on:click={() => (showAccessControlModal = true)}>
								<svelte:fragment slot="prefix">
									<LockClosed strokeWidth="2.5" className="size-3.5" />
								</svelte:fragment>
								{$i18n.t('Access')}
							</Button>
						{/if}

						<Button kind="outlined" size="md" on:click={handleCancel}>
							{$i18n.t('Cancel')}
						</Button>

						<Button kind="filled" size="md" type="submit" disabled={loading || !canWrite} loading={loading}>
							{#if edit}
								{$i18n.t('Save & Update')}
							{:else}
								{$i18n.t('Save & Create')}
							{/if}
						</Button>
					</div>
				</div>

				<div class="agent-editor__basic-grid">
					<div class="agent-editor__basic-fields">
						<Input
							bind:value={name}
							label={$i18n.t('Agent Name')}
							caption={$i18n.t('Add a clear, user-facing name for this agent.')}
							placeholder={$i18n.t('Agent Name')}
							size="md"
							required
						/>

						<Input
							bind:value={id}
							label={$i18n.t('Agent ID')}
							caption={$i18n.t(
								'Unique identifier used in API URL path. Lowercase, numbers, hyphens, underscores only.'
							)}
							placeholder={$i18n.t('Agent ID')}
							size="md"
							disabled={edit}
							required
						/>
					</div>

					<div class="agent-editor__image-panel">
						<LabelBase label={$i18n.t('Agent Image')} size="md" />

						<div class="agent-editor__image-stack">
							<button
								class="agent-editor__image-button"
								type="button"
								on:click={() => {
									filesInputElement.click();
								}}
							>
								<img
									src={info.meta.profile_image_url || $brandingUrls.favicon}
									alt={$i18n.t('Agent Image')}
									class="agent-editor__image-preview"
								/>
							</button>

							<div class="agent-editor__image-actions">
								<button
									class="agent-editor__secondary-button"
									type="button"
									on:click={() => {
										filesInputElement.click();
									}}
								>
									{$i18n.t('Update Image')}
								</button>

								<button
									class="agent-editor__inline-link"
									type="button"
									on:click={() => {
										info.meta.profile_image_url = $brandingUrls.favicon;
									}}
								>
									{$i18n.t('Reset Image')}
								</button>
							</div>
						</div>
					</div>
				</div>

				<div class="agent-editor__section">
					<div class="agent-editor__section-heading is-inline">
						<div>
							<h2>{$i18n.t('Description')}</h2>
							<p>{$i18n.t('Help teammates understand what this agent is for.')}</p>
						</div>

						<button
							class="agent-editor__secondary-button"
							type="button"
							on:click={() => {
								enableDescription = !enableDescription;
								if (!enableDescription) {
									info.meta.description = '';
								}
							}}
						>
							{#if enableDescription}
								{$i18n.t('Default')}
							{:else}
								{$i18n.t('Custom')}
							{/if}
						</button>
					</div>

					{#if enableDescription}
						<Textarea
							bind:value={info.meta.description}
							placeholder={$i18n.t('Add a short description about what this model does')}
							rows={3}
							size="md"
							autoResize={false}
							containerClassName="agent-editor__textarea-surface"
						/>
					{/if}
				</div>

				{#if preset}
					<div class="agent-editor__section">
						<div class="agent-editor__field-panel agent-editor__field-panel--plain">
							<LabelBase
								label={$i18n.t('Base Model (From)')}
								caption={$i18n.t('Base model used to run this agent.')}
								required
								size="md"
							>
								<svelte:fragment slot="right">
									<div class="agent-editor__selector-wrap">
										<Selector
											value={baseModelValue}
											items={getBaseModelSelectorItems()}
											placeholder={$i18n.t('Select a base model')}
											searchPlaceholder={$i18n.t('Search a base model')}
											ariaLabel={$i18n.t('Base Model (From)')}
											size="md"
											on:change={(event) => {
												baseModelValue = event.detail.value;
											}}
										/>
									</div>
								</svelte:fragment>
							</LabelBase>
						</div>
					</div>
				{/if}

				<div class="agent-editor__section">
					<div class="agent-editor__section-heading">
						<h2>{$i18n.t('Model Params')}</h2>
						<p>{$i18n.t('Configure the system prompt and answer formatting used by this agent.')}</p>
					</div>

					<div class="agent-editor__stack">
						<Textarea
							bind:value={info.params.system}
							label={$i18n.t('Task Prompt')}
							placeholder={$i18n.t(
								"Leave empty to use the default system prompt.\nDescribe the agent's role, behavior, and constraints.\nTip: Write a brief draft and click the AI button to refine it."
							)}
							rows={4}
							size="md"
							autoResize={false}
							containerClassName="agent-editor__textarea-surface agent-editor__textarea-tall"
						>
							<svelte:fragment slot="right">
								<div class="agent-editor__prompt-actions">
									<button
										class="agent-editor__ai-button"
										disabled={generatingTaskPrompt || !canWrite}
										on:click={aiGenerateTaskPrompt}
										title={$i18n.t('Generate with AI')}
										type="button"
									>
										{#if generatingTaskPrompt}
											<svg
												class="size-3 animate-spin"
												viewBox="0 0 24 24"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
												<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
											</svg>
										{:else}
											<SparklesSolid className="size-3" />
										{/if}
										<span>AI</span>
									</button>

									<div class="agent-editor__selector-wrap is-compact">
										<Selector
											bind:value={aiTaskModelId}
											items={getAiGenerationModelItems()}
											placeholder={$i18n.t('Select AI Model (Default)')}
											searchPlaceholder={$i18n.t('Search AI Model')}
											size="md"
											ariaLabel={$i18n.t('AI Generation Model')}
										/>
									</div>
								</div>
							</svelte:fragment>
						</Textarea>

						<Textarea
							bind:value={formatPrompt}
							label={$i18n.t('Response Format Prompt')}
							placeholder={$i18n.t(
								"Leave empty to use the default format.\nSpecify markdown style, structure, tone, and length for responses.\nTip: Write a brief draft and click the AI button to refine it."
							)}
							rows={4}
							size="md"
							autoResize={false}
							containerClassName="agent-editor__textarea-surface agent-editor__textarea-tall"
						>
							<svelte:fragment slot="right">
								<div class="agent-editor__prompt-actions">
									<button
										class="agent-editor__ai-button"
										disabled={generatingFormatPrompt || !canWrite}
										on:click={aiGenerateFormatPrompt}
										title={$i18n.t('Generate with AI')}
										type="button"
									>
										{#if generatingFormatPrompt}
											<svg
												class="size-3 animate-spin"
												viewBox="0 0 24 24"
												fill="none"
												xmlns="http://www.w3.org/2000/svg"
											>
												<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
												<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
											</svg>
										{:else}
											<SparklesSolid className="size-3" />
										{/if}
										<span>AI</span>
									</button>

									<div class="agent-editor__selector-wrap is-compact">
										<Selector
											bind:value={aiFormatModelId}
											items={getAiGenerationModelItems()}
											placeholder={$i18n.t('Select AI Model (Default)')}
											searchPlaceholder={$i18n.t('Search AI Model')}
											size="md"
											ariaLabel={$i18n.t('AI Generation Model')}
										/>
									</div>
								</div>
							</svelte:fragment>
						</Textarea>

						<div class="agent-editor__section">
							<div class="agent-editor__section-heading is-inline">
								<h2>{$i18n.t('Advanced Params')}</h2>
								<button
									class="agent-editor__secondary-button"
									type="button"
									on:click={() => {
										showAdvanced = !showAdvanced;
									}}
								>
									{#if showAdvanced}
										{$i18n.t('Hide')}
									{:else}
										{$i18n.t('Show')}
									{/if}
								</button>
							</div>

							{#if showAdvanced}
								<div class="agent-editor__contained-panel">
									<AdvancedParams
										admin={true}
										bind:params
										on:change={() => {
											info.params = { ...info.params, ...params };
										}}
									/>
								</div>
							{/if}
						</div>
					</div>
				</div>

				<div class="agent-editor__divider"></div>

				<div class="agent-editor__section">
					<div class="agent-editor__section-heading is-inline">
						<div>
							<h2>{$i18n.t('Prompt suggestions')}</h2>
							<p>{$i18n.t('Suggested starter prompts shown to users.')}</p>
						</div>

						<div class="agent-editor__header-actions">
							<button
								class="agent-editor__secondary-button"
								type="button"
								on:click={() => {
									if ((info?.meta?.suggestion_prompts ?? null) === null) {
										info.meta.suggestion_prompts = [{ content: '' }];
									} else {
										info.meta.suggestion_prompts = null;
									}
								}}
							>
								{#if (info?.meta?.suggestion_prompts ?? null) === null}
									{$i18n.t('Default')}
								{:else}
									{$i18n.t('Custom')}
								{/if}
							</button>

							{#if (info?.meta?.suggestion_prompts ?? null) !== null}
								<button
									class="agent-editor__secondary-button"
									type="button"
									on:click={() => {
										if (
											info.meta.suggestion_prompts.length === 0 ||
											info.meta.suggestion_prompts.at(-1).content !== ''
										) {
											info.meta.suggestion_prompts = [
												...info.meta.suggestion_prompts,
												{ content: '' }
											];
										}
									}}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="w-4 h-4"
									>
										<path
											d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z"
										/>
									</svg>
								</button>
							{/if}
						</div>
					</div>

					{#if info?.meta?.suggestion_prompts}
						<div class="agent-editor__contained-panel">
							{#if info.meta.suggestion_prompts.length > 0}
								<div class="agent-editor__suggestions">
									{#each info.meta.suggestion_prompts as prompt, promptIdx}
										<div class="agent-editor__suggestion-row">
											<input
												class="agent-editor__suggestion-input"
												placeholder={$i18n.t('Write a prompt suggestion (e.g. Who are you?)')}
												bind:value={prompt.content}
											/>

											<button
												class="agent-editor__icon-button"
												type="button"
												on:click={() => {
													info.meta.suggestion_prompts.splice(promptIdx, 1);
													info.meta.suggestion_prompts = info.meta.suggestion_prompts;
												}}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 20 20"
													fill="currentColor"
													class="w-4 h-4"
												>
													<path
														d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
													/>
												</svg>
											</button>
										</div>
									{/each}
								</div>
							{:else}
								<div class="agent-editor__empty-state">{$i18n.t('No suggestion prompts')}</div>
							{/if}
						</div>
					{/if}
				</div>

				<div class="agent-editor__divider"></div>

				<div class="agent-editor__section agent-editor__stack">
					<KnowledgeGraph
						bind:selectedKnowledgeGraphs={knowledgeGraphs}
						bind:inheritedKnowledgeIds
						bind:inheritedDbsphereIds
						bind:inheritedGlossaryIds
						{canWrite}
					/>
					<Knowledge
						bind:selectedKnowledge={knowledge}
						excludeIds={inheritedKnowledgeIds}
						{canWrite}
					/>
					<DbSphere
						bind:selectedDbSpheres={dbspheres}
						excludeIds={inheritedDbsphereIds}
						{canWrite}
					/>
					<ToolConnections bind:selectedToolConnections={toolConnections} {canWrite} />
					{#if isMenuVisible('marketplace')}
						<MarketplaceTools bind:selectedMarketplaceTools={marketplaceTools} {canWrite} />
					{/if}
					<Glossary
						bind:selectedGlossaries={glossaries}
						excludeIds={inheritedGlossaryIds}
						{canWrite}
					/>
					<GuardrailsSection bind:selectedGuardrails={guardrailsList} {canWrite} />
					<AutoEvaluationSection bind:autoEvaluation />
					<ResponseFormatSection bind:responseFormat />
					<Capabilities
						bind:capabilities
						bind:webSearchConfig
						bind:imageGenerationConfig
						groundingDefaultOn={preset}
					/>
				</div>

				<div class="agent-editor__section">
					<div class="agent-editor__section-heading is-inline">
						<div>
							<h2>{$i18n.t('JSON Preview')}</h2>
							<p>{$i18n.t('Preview the payload that will be saved for this agent.')}</p>
						</div>

						<button
							class="agent-editor__secondary-button"
							type="button"
							on:click={() => {
								showPreview = !showPreview;
							}}
						>
							{#if showPreview}
								{$i18n.t('Hide')}
							{:else}
								{$i18n.t('Show')}
							{/if}
						</button>
					</div>

					{#if showPreview}
						<div class="agent-editor__contained-panel">
							<textarea
								class="agent-editor__json-preview"
								rows="10"
								value={JSON.stringify(info, null, 2)}
								disabled
								readonly
							/>
						</div>
					{/if}
				</div>
			</div>
		</form>
	{/if}
{/if}

<style>
	.agent-editor {
		display: flex;
		justify-content: center;
		width: 100%;
		padding: var(--cloo-space-3) 0 calc(var(--cloo-space-4) * 2);
	}

	.agent-editor__shell {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-4);
		width: min(100%, 860px);
	}

	.agent-editor__back {
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
		width: fit-content;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--cloo-text-primary);
		font-size: 0.875rem;
		line-height: 1.25rem;
		font-weight: 500;
	}

	.agent-editor__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--cloo-space-3);
		padding-bottom: var(--cloo-space-2);
		border-bottom: 1px solid var(--cloo-border-subtle);
	}

	.agent-editor__title-wrap {
		flex: 1 1 auto;
		min-width: 0;
	}

	.agent-editor__title {
		margin: 0;
		color: var(--cloo-text-primary);
		font-size: 1.125rem;
		line-height: 1.75rem;
		font-weight: 600;
	}

	.agent-editor__header-actions {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.agent-editor__primary-button,
	.agent-editor__secondary-button,
	.agent-editor__ai-button,
	.agent-editor__icon-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.375rem;
		min-height: 1.75rem;
		padding: var(--cloo-space-1) var(--cloo-space-2-5);
		border-radius: var(--cloo-radius-default);
		font-size: 0.8125rem;
		line-height: 1.125rem;
		font-weight: 500;
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			color 150ms ease,
			opacity 150ms ease;
	}

	.agent-editor__primary-button {
		border: 0;
		background: var(--cloo-color-primary);
		color: var(--cloo-color-on-primary);
	}

	.agent-editor__primary-button:hover:not(:disabled) {
		background: var(--cloo-color-primary-hover);
	}

	.agent-editor__primary-button:disabled,
	.agent-editor__secondary-button:disabled,
	.agent-editor__ai-button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.agent-editor__secondary-button,
	.agent-editor__icon-button {
		border: 1px solid var(--cloo-border-subtle);
		background: var(--cloo-bg-surface);
		color: var(--cloo-text-primary);
	}

	.agent-editor__secondary-button:hover:not(:disabled),
	.agent-editor__icon-button:hover:not(:disabled) {
		background: var(--cloo-surface-hover);
	}

	.agent-editor__ai-button {
		border: 1px solid color-mix(in srgb, var(--cloo-color-accent) 28%, transparent);
		background: color-mix(in srgb, var(--cloo-color-accent-soft) 80%, var(--cloo-bg-surface));
		color: var(--cloo-color-accent);
	}

	.agent-editor__ai-button:hover:not(:disabled) {
		background: color-mix(in srgb, var(--cloo-color-accent-soft) 92%, var(--cloo-bg-surface));
	}

	.agent-editor__inline-link {
		border: 0;
		background: transparent;
		color: var(--cloo-text-muted);
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
	}

	.agent-editor__divider {
		width: 100%;
		height: 1px;
		background: var(--cloo-border-subtle);
		margin: var(--cloo-space-2) 0;
	}

	.agent-editor__basic-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 130px;
		gap: calc(var(--cloo-space-4) + var(--cloo-space-1));
		align-items: start;
	}

	.agent-editor__basic-fields,
	.agent-editor__stack {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-3);
	}

	.agent-editor__image-panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
	}

	.agent-editor__image-stack {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
	}

	.agent-editor__image-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 130px;
		height: 130px;
		padding: 0;
		border: 0;
		border-radius: 9999px;
		background: var(--cloo-bg-default);
		overflow: hidden;
	}

	.agent-editor__image-preview {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.agent-editor__image-actions {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.375rem;
		width: 100%;
	}

	.agent-editor__section {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
	}

	.agent-editor__section-heading {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-1);
	}

	.agent-editor__section-heading.is-inline {
		flex-direction: row;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}

	.agent-editor__section-heading h2 {
		margin: 0;
		color: var(--cloo-text-primary);
		font-size: 1rem;
		line-height: 1.5rem;
		font-weight: 600;
	}

	.agent-editor__section-heading p {
		margin: 0;
		color: var(--cloo-text-muted);
		font-size: 0.75rem;
		line-height: 1rem;
	}

	.agent-editor__field-panel,
	.agent-editor__contained-panel {
		padding: var(--cloo-space-3);
		border: 1px solid var(--cloo-border-default);
		border-radius: var(--cloo-radius-xl);
		background: var(--cloo-bg-surface);
	}

	.agent-editor__contained-panel {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-3);
	}

	.agent-editor__field-panel--plain,
	.agent-editor__contained-panel--plain {
		padding: 0;
		border: 0;
		border-radius: 0;
		background: transparent;
	}

	/* LabelBase 안에서 좌측 라벨 1/3, 우측 셀렉터 1/4 + 우측 정렬 */
	.agent-editor__field-panel--plain :global(.cloo-label-base__left) {
		flex: 0 0 33%;
	}

	.agent-editor__field-panel--plain :global(.cloo-label-base__right) {
		flex: 0 0 25%;
		justify-content: flex-end;
	}

	.agent-editor__selector-wrap {
		width: 100%;
	}

	.agent-editor__selector-wrap.is-compact {
		flex-shrink: 0;
		width: min(100%, 208px);
	}

	:global(.agent-editor__textarea-surface) {
		border-color: var(--cloo-border-default);
		background: var(--cloo-bg-default);
	}

	:global(.agent-editor__textarea-tall .cloo-textarea__native) {
		min-height: 6rem;
	}

	.agent-editor__prompt-actions {
		display: inline-flex;
		align-items: center;
		gap: var(--cloo-space-2);
		flex-wrap: nowrap;
		white-space: nowrap;
	}

	.agent-editor__prompt-actions .agent-editor__selector-wrap.is-compact {
		flex: 0 0 220px;
		width: 220px;
	}

	.agent-editor__suggestions {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
	}

	.agent-editor__suggestion-row {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
		padding: var(--cloo-space-1) 0;
	}

	.agent-editor__suggestion-input {
		flex: 1 1 auto;
		min-width: 0;
		padding: 0.5rem 0;
		border: 0;
		border-bottom: 1px solid var(--cloo-border-subtle);
		background: transparent;
		color: var(--cloo-text-default);
		font-size: 0.875rem;
		line-height: 1.25rem;
		outline: none;
	}

	.agent-editor__empty-state {
		color: var(--cloo-text-muted);
		font-size: 0.75rem;
		line-height: 1rem;
		text-align: center;
		padding: var(--cloo-space-3);
		border: 1px dashed var(--cloo-border-default);
		border-radius: var(--cloo-radius-default);
	}

	.agent-editor__json-preview {
		width: 100%;
		border: 0;
		background: transparent;
		color: var(--cloo-text-default);
		font-size: 0.875rem;
		line-height: 1.25rem;
		resize: vertical;
		outline: none;
	}

	@media (max-width: 767px) {
		.agent-editor__header,
		.agent-editor__section-heading.is-inline {
			flex-direction: column;
			align-items: stretch;
		}

		.agent-editor__basic-grid {
			grid-template-columns: minmax(0, 1fr);
		}

		.agent-editor__image-panel {
			align-items: flex-start;
		}

		.agent-editor__image-stack {
			align-items: flex-start;
		}

		.agent-editor__selector-wrap,
		.agent-editor__selector-wrap.is-compact {
			width: 100%;
		}
	}
</style>
