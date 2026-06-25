<script>
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';

	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { page } from '$app/stores';
	import { config, models, settings } from '$lib/stores';

	import { getModelById, updateModelById } from '$lib/apis/models';

	import { getModels } from '$lib/apis';
	import AgentEditor from '$lib/components/workspace/Agents/AgentEditor.svelte';

	let model = null;
	let reloadKey = 0;

	const loadModel = async (redirectIfMissing = true) => {
		const _id = $page.url.searchParams.get('id');
		if (_id) {
			model = await getModelById(localStorage.token, _id).catch((e) => {
				return null;
			});

			if (!model && redirectIfMissing) {
				goto('/workspace/agents');
			}
		} else if (redirectIfMissing) {
			goto('/workspace/agents');
		}
	};

	onMount(() => loadModel());

	// 버전 복원 후: 모델만 다시 불러와 에디터를 재마운트 (전체 새로고침 없이 부드럽게 반영)
	const onRestored = async () => {
		await loadModel(false);
		reloadKey++;
	};

	const onSubmit = async (modelInfo) => {
		const res = await updateModelById(localStorage.token, modelInfo.id, modelInfo);

		if (res) {
			await models.set(
				await getModels(
					localStorage.token,
					$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
				)
			);
			toast.success($i18n.t('Agent updated successfully'));
			await goto('/workspace/agents');
		}
	};
</script>

{#if model}
	{#key reloadKey}
		<AgentEditor edit={true} {model} {onSubmit} {onRestored} onBack={() => goto('/workspace/agents')} />
	{/key}
{/if}
