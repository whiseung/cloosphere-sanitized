<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { createNewProject } from '$lib/apis/projects';
	import { config, projectsLastUpdated } from '$lib/stores';
	import { toast } from 'svelte-sonner';

	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';

	let loading = false;

	let name = '';
	let description = '';
	let projectType = 'general';

	const projectTypeItems = [
		{ value: 'general', label: $i18n.t('General') },
		{ value: 'data_analysis', label: $i18n.t('Data Analysis') }
	];

	const submitHandler = async () => {
		loading = true;

		if (name.trim() === '') {
			toast.error($i18n.t('Please fill in all fields.'));
			loading = false;
			return;
		}

		if (projectType === 'data_analysis' && $config?.code?.engine !== 'jupyter') {
			toast.error(
				$i18n.t(
					'Data Analysis projects require Jupyter engine. Please configure it in Admin > Settings > Code Execution.'
				)
			);
			loading = false;
			return;
		}

		const res = await createNewProject(
			localStorage.token,
			name,
			description || null,
			null,
			{},
			projectType
		).catch((e) => {
			toast.error($i18n.t(`${e}`));
		});

		if (res) {
			$projectsLastUpdated = Date.now();
			toast.success($i18n.t('Project created successfully.'));
			goto(`/projects/${res.id}`);
		}

		loading = false;
	};
</script>

<div class="w-full max-h-full">
	<button
		class="flex space-x-1"
		on:click={() => {
			history.back();
		}}
	>
		<div class="self-center">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 20 20"
				fill="currentColor"
				class="w-4 h-4"
			>
				<path
					fill-rule="evenodd"
					d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
					clip-rule="evenodd"
				/>
			</svg>
		</div>
		<div class="self-center font-medium text-sm">{$i18n.t('Back')}</div>
	</button>

	<form
		class="flex flex-col max-w-lg mx-auto mt-6 sm:mt-10 mb-10 px-4 sm:px-0"
		on:submit|preventDefault={submitHandler}
	>
		<div class="w-full flex flex-col justify-center">
			<div class="text-2xl font-medium font-primary mb-2.5">
				{$i18n.t('Create Project')}
			</div>

			<div class="w-full flex flex-col gap-2.5">
				<div class="w-full">
					<div class="text-sm font-medium mb-1.5">{$i18n.t('Project Type')}</div>
					<Selector
						value={projectType}
						items={projectTypeItems}
						size="sm"
						on:change={(e) => {
							projectType = e.detail.value;
						}}
					/>
					{#if projectType === 'data_analysis'}
						<p class="text-xs text-[var(--cloo-text-muted)] mt-1">
							{$i18n.t(
								'Upload CSV/Excel files and analyze data with Python code (Code Interpreter)'
							)}
						</p>
					{/if}
				</div>

				<Input
					bind:value={name}
					label={$i18n.t('Name')}
					placeholder={$i18n.t('Name your project')}
					size="sm"
					required
				/>

				<Textarea
					bind:value={description}
					label={$i18n.t('Description')}
					placeholder={$i18n.t('Describe your project')}
					size="sm"
					rows={3}
				/>
			</div>
		</div>

		<div class="flex justify-end mt-4">
			<Button kind="filled" size="md" type="submit" {loading}>
				{$i18n.t('Create Project')}
			</Button>
		</div>
	</form>
</div>
