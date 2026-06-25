<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	import { getCodeExecutionConfig, setCodeExecutionConfig } from '$lib/apis/configs';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let config = null;

	const engines = ['pyodide', 'jupyter'];

	$: engineOptions = engines.map((engine) => ({ value: engine, label: engine }));

	$: jupyterAuthOptions = [
		{ value: '', label: $i18n.t('None') },
		{ value: 'token', label: $i18n.t('Token') },
		{ value: 'password', label: $i18n.t('Password') }
	];

	const submitHandler = async () => {
		const res = await setCodeExecutionConfig(localStorage.token, config);
	};

	onMount(async () => {
		const res = await getCodeExecutionConfig(localStorage.token);

		if (res) {
			config = res;
		}
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		await submitHandler();
		saveHandler();
	}}
>
	<div class=" space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		{#if config}
			<div>
				<div class="mb-3.5">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('General')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-3 pr-2">
						<LabelBase label={$i18n.t('Enable Code Execution')} size="md">
							<svelte:fragment slot="right">
								<Switch bind:state={config.ENABLE_CODE_EXECUTION} />
							</svelte:fragment>
						</LabelBase>

						<div>
							<LabelBase
								label={$i18n.t('Code Execution Engine')}
								caption={config.CODE_EXECUTION_ENGINE === 'jupyter'
									? $i18n.t(
											'Warning: Jupyter execution enables arbitrary code execution, posing severe security risks—proceed with extreme caution.'
										)
									: ''}
								size="md"
							>
								<svelte:fragment slot="right">
									<div class="min-w-[14rem]">
										<Selector
											value={config.CODE_EXECUTION_ENGINE ?? ''}
											items={engineOptions}
											placeholder={$i18n.t('Select a engine')}
											size="sm"
											searchEnabled={false}
											on:change={(event) => {
												config.CODE_EXECUTION_ENGINE = event.detail.value;
											}}
										/>
									</div>
								</svelte:fragment>
							</LabelBase>
						</div>

						{#if config.CODE_EXECUTION_ENGINE === 'jupyter'}
							<Input
								bind:value={config.CODE_EXECUTION_JUPYTER_URL}
								label={$i18n.t('Jupyter URL')}
								placeholder={$i18n.t('Enter Jupyter URL')}
								size="md"
								autocomplete="off"
							/>

							<LabelBase label={$i18n.t('Jupyter Auth')} size="md">
								<svelte:fragment slot="right">
									<div class="min-w-[14rem]">
										<Selector
											value={config.CODE_EXECUTION_JUPYTER_AUTH ?? ''}
											items={jupyterAuthOptions}
											placeholder={$i18n.t('Select an auth method')}
											size="sm"
											searchEnabled={false}
											on:change={(event) => {
												config.CODE_EXECUTION_JUPYTER_AUTH = event.detail.value;
											}}
										/>
									</div>
								</svelte:fragment>
							</LabelBase>

							{#if config.CODE_EXECUTION_JUPYTER_AUTH}
								{#if config.CODE_EXECUTION_JUPYTER_AUTH === 'password'}
									<SensitiveInput
										type="text"
										placeholder={$i18n.t('Enter Jupyter Password')}
										bind:value={config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD}
										autocomplete="off"
									/>
								{:else}
									<SensitiveInput
										type="text"
										placeholder={$i18n.t('Enter Jupyter Token')}
										bind:value={config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN}
										autocomplete="off"
									/>
								{/if}
							{/if}

							<Input
								bind:value={config.CODE_EXECUTION_JUPYTER_TIMEOUT}
								label={$i18n.t('Code Execution Timeout')}
								caption={$i18n.t('Enter timeout in seconds')}
								placeholder={$i18n.t('e.g. 60')}
								type="number"
								size="md"
								autocomplete="off"
							/>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
