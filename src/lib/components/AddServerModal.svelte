<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import { models } from '$lib/stores';
	import { verifyOpenAIConnection } from '$lib/apis/openai';
	import { verifyOllamaConnection } from '$lib/apis/ollama';

	import Modal from '$lib/components/common/Modal.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Minus from '$lib/components/icons/Minus.svelte';
	import PencilSolid from '$lib/components/icons/PencilSolid.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Tags from './common/Tags.svelte';
	import { getToolServerData } from '$lib/apis';
	import { verifyToolServerConnection } from '$lib/apis/configs';
	import AccessControl from './workspace/common/AccessControl.svelte';

	export let onSubmit: Function = () => {};
	export let onDelete: Function = () => {};

	export let show = false;
	export let edit = false;

	export let direct = false;

	export let connection = null;

	let url = '';
	let path = 'openapi.json';

	let auth_type = 'bearer';
	let key = '';

	let accessControl: any = null;

	let enable = true;

	let loading = false;

	const verifyHandler = async () => {
		if (url === '') {
			toast.error($i18n.t('Please enter a valid URL'));
			return;
		}

		if (path === '') {
			toast.error($i18n.t('Please enter a valid path'));
			return;
		}

		if (direct) {
			const res = await getToolServerData(
				auth_type === 'bearer' ? key : localStorage.token,
				`${url}/${path}`
			).catch((err) => {
				toast.error($i18n.t('Connection failed'));
			});

			if (res) {
				toast.success($i18n.t('Connection successful'));
				console.debug('Connection successful', res);
			}
		} else {
			const res = await verifyToolServerConnection(localStorage.token, {
				url,
				path,
				auth_type,
				key,
				config: {
					enable: enable,
					access_control: accessControl
				}
			}).catch((err) => {
				toast.error($i18n.t('Connection failed'));
			});

			if (res) {
				toast.success($i18n.t('Connection successful'));
				console.debug('Connection successful', res);
			}
		}
	};

	const submitHandler = async () => {
		loading = true;

		// remove trailing slash from url
		url = url.replace(/\/$/, '');

		const connection = {
			url,
			path,
			auth_type,
			key,
			config: {
				enable: enable,
				access_control: accessControl
			}
		};

		await onSubmit(connection);

		loading = false;
		show = false;

		url = '';
		path = 'openapi.json';
		key = '';
		auth_type = 'bearer';

		enable = true;
		accessControl = null;
	};

	const init = () => {
		if (connection) {
			url = connection.url;
			path = connection?.path ?? 'openapi.json';

			auth_type = connection?.auth_type ?? 'bearer';
			key = connection?.key ?? '';

			enable = connection.config?.enable ?? true;
			accessControl = connection.config?.access_control ?? null;
		}
	};

	$: if (show) {
		init();
	}

	$: authTypeOptions = [
		{ value: 'bearer', label: 'Bearer' },
		{ value: 'session', label: 'Session' }
	];

	onMount(() => {
		init();
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between items-center dark:text-gray-100 px-5 pt-4 pb-2">
			<div class=" text-lg font-semibold self-center font-primary">
				{#if edit}
					{$i18n.t('Edit Connection')}
				{:else}
					{$i18n.t('Add Connection')}
				{/if}
			</div>
			<button
				type="button"
				class="self-center p-1 rounded-md hover:bg-[var(--cloo-bg-neutral-hovered)] transition"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="px-1 space-y-2.5">
						<div class="flex gap-2 items-end">
							<div class="flex-1">
								<Input
									bind:value={url}
									label={$i18n.t('URL')}
									placeholder={$i18n.t('API Base URL')}
									size="md"
									autocomplete="off"
									required
								/>
							</div>

							<Tooltip content={$i18n.t('Verify Connection')}>
								<Button
									kind="outlined"
									size="md"
									on:click={() => {
										verifyHandler();
									}}
								>
									<svelte:fragment slot="prefix">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 20 20"
											fill="currentColor"
											class="w-4 h-4"
										>
											<path
												fill-rule="evenodd"
												d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0V5.36l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z"
												clip-rule="evenodd"
											/>
										</svg>
									</svelte:fragment>
									{$i18n.t('Verify')}
								</Button>
							</Tooltip>

							<Tooltip content={enable ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
								<div class="pb-[0.5rem]">
									<Switch bind:state={enable} />
								</div>
							</Tooltip>
						</div>

						<div class="flex items-end gap-1">
							<div class="self-end pb-[0.625rem] text-sm">/</div>
							<div class="flex-1">
								<Input
									bind:value={path}
									label={$i18n.t('OpenAPI Path')}
									placeholder={$i18n.t('openapi.json Path')}
									size="md"
									autocomplete="off"
									required
								/>
							</div>
						</div>

						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t(`WebUI will make requests to "{{url}}"`, {
								url: `${url}/${path}`
							})}
						</div>

						<div>
							<LabelBase label={$i18n.t('Auth')} size="md" />
							<div class="flex gap-2 items-start">
								<div class="w-[7rem] shrink-0">
									<Selector
										value={auth_type}
										items={authTypeOptions}
										size="sm"
										searchEnabled={false}
										portal="body"
										contentClassName="z-[10000]"
										on:change={(e) => {
											auth_type = e.detail.value;
										}}
									/>
								</div>

								<div class="flex-1">
									{#if auth_type === 'bearer'}
										<SensitiveInput
											bind:value={key}
											placeholder={$i18n.t('API Key')}
											required={false}
										/>
									{:else if auth_type === 'session'}
										<div class="text-xs text-gray-500 pt-2">
											{$i18n.t('Forwards system user session credentials to authenticate')}
										</div>
									{/if}
								</div>
							</div>
						</div>

						{#if !direct}
							<hr class="border-gray-50 dark:border-gray-850 my-3" />

							<div class="-mx-2">
								<div class="px-3 py-2 bg-gray-50 dark:bg-gray-950 rounded-lg">
									<AccessControl bind:accessControl />
								</div>
							</div>
						{/if}
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
						{#if edit}
							<Button
								kind="outlined"
								size="md"
								on:click={() => {
									onDelete();
									show = false;
								}}
							>
								{$i18n.t('Delete')}
							</Button>
						{/if}

						<Button kind="filled" size="md" type="submit" {loading}>
							{$i18n.t('Save')}
						</Button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
