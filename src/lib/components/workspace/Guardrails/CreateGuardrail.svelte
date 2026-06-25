<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { createGuardrail, getGuardrails } from '$lib/apis/guardrails';
	import { guardrails, user, userPermissions } from '$lib/stores';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';
	import Button from '$lib/components/common/Button.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let loading = false;
	let importInputElement: HTMLInputElement;

	let name = '';
	let description = '';
	let importedData: any = null; // Clone 또는 Import된 전체 데이터
	let accessControl: any = {
		read: { group_ids: [], user_ids: [$user?.id], org_unit_ids: [] },
		write: { group_ids: [], user_ids: [$user?.id], org_unit_ids: [] }
	};

	// 구버전 export 호환: read/write 에 org_unit_ids 가 없으면 보강.
	const normalizeAcl = (acl: any) => {
		if (acl === null || acl === undefined) return null;
		return {
			read: {
				group_ids: acl?.read?.group_ids ?? [],
				user_ids: acl?.read?.user_ids ?? [$user?.id],
				org_unit_ids: acl?.read?.org_unit_ids ?? []
			},
			write: {
				group_ids: acl?.write?.group_ids ?? [],
				user_ids: acl?.write?.user_ids ?? [$user?.id],
				org_unit_ids: acl?.write?.org_unit_ids ?? []
			}
		};
	};

	const loadFromImport = (data: any) => {
		name = data.name || '';
		description = data.description || '';
		if (data.access_control !== undefined) {
			accessControl = normalizeAcl(data.access_control);
		}
		// 나머지 규칙 필드는 생성 후 편집 페이지에서 설정하도록 보존
		importedData = data;
	};

	const handleFileImport = (event: Event) => {
		const input = event.target as HTMLInputElement;
		const file = input?.files?.[0];
		if (!file) return;
		const reader = new FileReader();
		reader.onload = (e) => {
			try {
				const data = JSON.parse(e.target?.result as string);
				loadFromImport(data);
				toast.success($i18n.t('Guardrail imported. Review and save.'));
			} catch {
				toast.error($i18n.t('Failed to parse JSON file.'));
			}
			input.value = '';
		};
		reader.readAsText(file);
	};

	onMount(() => {
		// Clone 데이터 로드 (sessionStorage 경유)
		const stored = sessionStorage.guardrail;
		if (stored) {
			try {
				loadFromImport(JSON.parse(stored));
			} catch {
				// ignore
			}
			sessionStorage.removeItem('guardrail');
		}
	});

	// Import/Clone 된 데이터가 있으면 규칙 기본값으로 사용, 없으면 기본 설정.
	const ruleDefaults = () =>
		importedData
			? {
					pii_types: importedData.pii_types ?? [],
					pii_strategy: importedData.pii_strategy ?? 'redact',
					custom_patterns: importedData.custom_patterns ?? [],
					blocked_words: importedData.blocked_words ?? [],
					apply_to_input: importedData.apply_to_input ?? true,
					apply_to_output: importedData.apply_to_output ?? false,
					llm_judge_enabled: importedData.llm_judge_enabled ?? false,
					llm_judge_model: importedData.llm_judge_model ?? undefined,
					llm_judge_prompt: importedData.llm_judge_prompt ?? undefined,
					llm_judge_pass_examples: importedData.llm_judge_pass_examples ?? [],
					llm_judge_block_examples: importedData.llm_judge_block_examples ?? [],
					llm_judge_apply_to_input: importedData.llm_judge_apply_to_input ?? true,
					llm_judge_apply_to_output: importedData.llm_judge_apply_to_output ?? false
				}
			: {
					pii_types: [],
					pii_strategy: 'redact',
					custom_patterns: [],
					blocked_words: [],
					apply_to_input: true,
					apply_to_output: false,
					llm_judge_enabled: false,
					llm_judge_model: undefined,
					llm_judge_prompt: undefined,
					llm_judge_pass_examples: [],
					llm_judge_block_examples: [],
					llm_judge_apply_to_input: true,
					llm_judge_apply_to_output: false
				};

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		loading = true;
		const res = await createGuardrail(localStorage.token, {
			...ruleDefaults(),
			name: e.detail.name,
			description: e.detail.description,
			access_control: e.detail.accessControl
		}).catch((err) => {
			toast.error($i18n.t(`${err}`));
			return null;
		});
		if (res) {
			toast.success($i18n.t('Guardrail created successfully.'));
			guardrails.set(await getGuardrails(localStorage.token));
			goto(`/workspace/guardrails/${res.id}`);
		}
		loading = false;
	};
</script>

<!-- Hidden file input for JSON import -->
<input
	bind:this={importInputElement}
	type="file"
	accept=".json"
	hidden
	on:change={handleFileImport}
/>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a guardrail')}
	nameLabel={$i18n.t('What are you working on?')}
	namePlaceholder={$i18n.t('Name your guardrail')}
	descriptionLabel={$i18n.t('How can this data be utilized?')}
	descriptionPlaceholder={$i18n.t('Describe your guardrail and objectives')}
	backHref="/workspace/guardrails"
	allowPublic={$userPermissions?.sharing?.public_guardrails || $user?.role === 'admin'}
	bind:name
	bind:description
	bind:accessControl
	bind:loading
	on:submit={handleSubmit}
>
	<Button
		slot="actions-prefix"
		kind="outlined"
		size="md"
		on:click={() => importInputElement?.click()}
	>
		<svelte:fragment slot="prefix">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 16 16"
				fill="currentColor"
				class="size-3.5"
			>
				<path
					fill-rule="evenodd"
					d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 9.5a.75.75 0 0 1-.75-.75V8.06l-.72.72a.75.75 0 0 1-1.06-1.06l2-2a.75.75 0 0 1 1.06 0l2 2a.75.75 0 1 1-1.06 1.06l-.72-.72v2.69a.75.75 0 0 1-.75.75Z"
					clip-rule="evenodd"
				/>
			</svg>
		</svelte:fragment>
		{$i18n.t('Import')}
	</Button>
</WorkspaceCreateScaffold>
