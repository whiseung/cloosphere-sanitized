<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { getLanguages, changeLanguage } from '$lib/i18n';
	const dispatch = createEventDispatcher();

	import { models, settings, theme, user } from '$lib/stores';

	const i18n = getContext('i18n');

	import AdvancedParams from './Advanced/AdvancedParams.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';

	export let saveSettings: Function;
	export let getModels: Function;

	// General
	let themes = ['dark', 'light', 'rose-pine dark', 'rose-pine-dawn light', 'oled-dark', 'her'];
	let selectedTheme = 'system';

	let languages: Awaited<ReturnType<typeof getLanguages>> = [];
	let lang = $i18n.language;
	let notificationEnabled = false;
	let system = '';

	let showAdvanced = false;

	const handleNotificationToggle = async (newState: boolean) => {
		if (newState) {
			const permission = await Notification.requestPermission();
			if (permission === 'granted') {
				saveSettings({ notificationEnabled: true });
			} else {
				notificationEnabled = false;
				toast.error(
					$i18n.t(
						'Response notifications cannot be activated as the website permissions have been denied. Please visit your browser settings to grant the necessary access.'
					)
				);
			}
		} else {
			saveSettings({ notificationEnabled: false });
		}
	};

	// Advanced
	let requestFormat = null;
	let keepAlive: string | null = null;

	let params = {
		// Advanced
		stream_response: null,
		function_calling: null,
		seed: null,
		temperature: null,
		reasoning_effort: null,
		logit_bias: null,
		frequency_penalty: null,
		presence_penalty: null,
		repeat_penalty: null,
		repeat_last_n: null,
		mirostat: null,
		mirostat_eta: null,
		mirostat_tau: null,
		top_k: null,
		top_p: null,
		min_p: null,
		stop: null,
		tfs_z: null,
		num_ctx: null,
		num_batch: null,
		num_keep: null,
		max_tokens: null,
		num_gpu: null
	};

	const validateJSON = (json) => {
		try {
			const obj = JSON.parse(json);

			if (obj && typeof obj === 'object') {
				return true;
			}
		} catch (e) {}
		return false;
	};

	const toggleRequestFormat = async (newState: boolean) => {
		requestFormat = newState ? 'json' : null;
		saveSettings({ requestFormat: requestFormat !== null ? requestFormat : undefined });
	};

	const normalizeRequestFormat = (val: any): string | null => {
		if (val == null) return null;
		if (typeof val === 'string') {
			return val.trim() === '' ? null : val;
		}
		if (typeof val === 'object') {
			try {
				return JSON.stringify(val, null, 2);
			} catch {
				return null;
			}
		}
		// 숫자, 불리언 등 비정상 타입은 null로 초기화
		return null;
	};

	const saveHandler = async () => {
		requestFormat = normalizeRequestFormat(requestFormat);

		if (requestFormat !== null && requestFormat !== 'json') {
			if (validateJSON(requestFormat) === false) {
				toast.error($i18n.t('Invalid JSON schema'));
				return;
			} else {
				requestFormat = JSON.parse(requestFormat);
			}
		}

		saveSettings({
			system: system !== '' ? system : undefined,
			params: {
				stream_response: params.stream_response !== null ? params.stream_response : undefined,
				function_calling: params.function_calling !== null ? params.function_calling : undefined,
				seed: (params.seed !== null ? params.seed : undefined) ?? undefined,
				stop: params.stop ? params.stop.split(',').filter((e) => e) : undefined,
				temperature: params.temperature !== null ? params.temperature : undefined,
				reasoning_effort: params.reasoning_effort !== null ? params.reasoning_effort : undefined,
				logit_bias: params.logit_bias !== null ? params.logit_bias : undefined,
				frequency_penalty: params.frequency_penalty !== null ? params.frequency_penalty : undefined,
				presence_penalty: params.frequency_penalty !== null ? params.frequency_penalty : undefined,
				repeat_penalty: params.frequency_penalty !== null ? params.frequency_penalty : undefined,
				repeat_last_n: params.repeat_last_n !== null ? params.repeat_last_n : undefined,
				mirostat: params.mirostat !== null ? params.mirostat : undefined,
				mirostat_eta: params.mirostat_eta !== null ? params.mirostat_eta : undefined,
				mirostat_tau: params.mirostat_tau !== null ? params.mirostat_tau : undefined,
				top_k: params.top_k !== null ? params.top_k : undefined,
				top_p: params.top_p !== null ? params.top_p : undefined,
				min_p: params.min_p !== null ? params.min_p : undefined,
				tfs_z: params.tfs_z !== null ? params.tfs_z : undefined,
				num_ctx: params.num_ctx !== null ? params.num_ctx : undefined,
				num_batch: params.num_batch !== null ? params.num_batch : undefined,
				num_keep: params.num_keep !== null ? params.num_keep : undefined,
				max_tokens: params.max_tokens !== null ? params.max_tokens : undefined,
				use_mmap: params.use_mmap !== null ? params.use_mmap : undefined,
				use_mlock: params.use_mlock !== null ? params.use_mlock : undefined,
				num_thread: params.num_thread !== null ? params.num_thread : undefined,
				num_gpu: params.num_gpu !== null ? params.num_gpu : undefined
			},
			keepAlive: keepAlive ? (isNaN(keepAlive) ? keepAlive : parseInt(keepAlive)) : undefined,
			requestFormat: requestFormat !== null ? requestFormat : undefined
		});
		dispatch('save');

		requestFormat = normalizeRequestFormat(requestFormat);
	};

	onMount(async () => {
		selectedTheme = localStorage.theme ?? 'system';

		languages = await getLanguages();

		notificationEnabled = $settings.notificationEnabled ?? false;
		system = $settings.system ?? '';

		requestFormat = normalizeRequestFormat($settings.requestFormat);
		if (requestFormat !== null && requestFormat !== 'json') {
			requestFormat =
				typeof requestFormat === 'object' ? JSON.stringify(requestFormat, null, 2) : requestFormat;
		}

		keepAlive = $settings.keepAlive ?? null;

		params = { ...params, ...$settings.params };
		params.stop = $settings?.params?.stop ? ($settings?.params?.stop ?? []).join(',') : null;
	});

	const applyTheme = (_theme: string) => {
		let themeToApply = _theme === 'oled-dark' ? 'dark' : _theme;

		if (_theme === 'system') {
			themeToApply = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
		}

		if (themeToApply === 'dark' && !_theme.includes('oled')) {
			document.documentElement.style.setProperty('--color-gray-800', '#333');
			document.documentElement.style.setProperty('--color-gray-850', '#262626');
			document.documentElement.style.setProperty('--color-gray-900', '#171717');
			document.documentElement.style.setProperty('--color-gray-950', '#0d0d0d');
		}

		themes
			.filter((e) => e !== themeToApply)
			.forEach((e) => {
				e.split(' ').forEach((e) => {
					document.documentElement.classList.remove(e);
				});
			});

		themeToApply.split(' ').forEach((e) => {
			document.documentElement.classList.add(e);
		});

		const metaThemeColor = document.querySelector('meta[name="theme-color"]');
		if (metaThemeColor) {
			if (_theme.includes('system')) {
				const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light';
				console.log('Setting system meta theme color: ' + systemTheme);
				metaThemeColor.setAttribute('content', systemTheme === 'light' ? '#ffffff' : '#171717');
			} else {
				console.log('Setting meta theme color: ' + _theme);
				metaThemeColor.setAttribute(
					'content',
					_theme === 'dark'
						? '#171717'
						: _theme === 'oled-dark'
							? '#000000'
							: _theme === 'her'
								? '#983724'
								: '#ffffff'
				);
			}
		}

		if (typeof window !== 'undefined' && window.applyTheme) {
			window.applyTheme();
		}

		if (_theme.includes('oled')) {
			document.documentElement.style.setProperty('--color-gray-800', '#101010');
			document.documentElement.style.setProperty('--color-gray-850', '#050505');
			document.documentElement.style.setProperty('--color-gray-900', '#000000');
			document.documentElement.style.setProperty('--color-gray-950', '#000000');
			document.documentElement.classList.add('dark');
		}

		if (_theme === 'her') {
			document.documentElement.classList.add('dark');
			document.documentElement.classList.add('her');
		}

		console.log(_theme);
	};

	const themeChangeHandler = (_theme: string) => {
		theme.set(_theme);
		localStorage.setItem('theme', _theme);
		applyTheme(_theme);
	};

	$: themeOptions = [
		{ value: 'system', label: `⚙️ ${$i18n.t('System')}` },
		{ value: 'dark', label: `🌑 ${$i18n.t('Dark')}` },
		{ value: 'oled-dark', label: `🌃 ${$i18n.t('OLED Dark')}` },
		{ value: 'light', label: `☀️ ${$i18n.t('Light')}` },
		{ value: 'her', label: `🌷 ${$i18n.t('Her')}` }
	];

	$: languageOptions = languages.map((l) => ({ value: l.code, label: l.title }));
</script>

<div class="flex flex-col h-full justify-between text-sm">
	<div class="  overflow-y-scroll max-h-[28rem] lg:max-h-full">
		<div class="space-y-2.5">
			<div class=" mb-1 text-base font-semibold">{$i18n.t('WebUI Settings')}</div>

			<LabelBase label={$i18n.t('Theme')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[16rem]">
						<Selector
							value={selectedTheme}
							items={themeOptions}
							placeholder={$i18n.t('Select a theme')}
							size="sm"
							searchEnabled={false}
							portal="body"
							contentClassName="z-[10000]"
							on:change={(e) => {
								selectedTheme = e.detail.value;
								themeChangeHandler(selectedTheme);
							}}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Language')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[16rem]">
						<Selector
							value={lang}
							items={languageOptions}
							placeholder={$i18n.t('Select a language')}
							size="sm"
							searchEnabled
							searchPlaceholder={$i18n.t('Search a language')}
							portal="body"
							contentClassName="z-[10000]"
							on:change={(e) => {
								lang = e.detail.value;
								changeLanguage(lang);
							}}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>
			<div class="mb-2 text-xs text-gray-400 dark:text-gray-500">
				{$i18n.t("Couldn't find your language?")}
				<a class=" text-gray-300 font-medium underline" href="/guide" target="_blank">
					{$i18n.t('Help us translate Open WebUI!')}
				</a>
			</div>

			<LabelBase label={$i18n.t('Notifications')} size="md">
				<svelte:fragment slot="right">
					<Switch
						bind:state={notificationEnabled}
						on:change={(e) => handleNotificationToggle(e.detail)}
					/>
				</svelte:fragment>
			</LabelBase>
		</div>

		{#if $user?.role === 'admin' || $user?.permissions.chat?.controls}
			<hr class="border-gray-50 dark:border-gray-850 my-3" />

			<div>
				<Textarea
					bind:value={system}
					label={$i18n.t('System Prompt')}
					rows={4}
					size="md"
					placeholder={$i18n.t('Enter system prompt here')}
				/>
			</div>

			<div class="mt-2 space-y-3 pr-1.5">
				<LabelBase label={$i18n.t('Advanced Parameters')} size="md">
					<svelte:fragment slot="right">
						<Button
							kind="text"
							size="sm"
							className="flex-1 justify-center"
							on:click={() => {
								showAdvanced = !showAdvanced;
							}}
						>
							{#if showAdvanced}
								<ChevronUp className="size-4" strokeWidth="2" />
							{:else}
								<ChevronDown className="size-4" strokeWidth="2" />
							{/if}
						</Button>
					</svelte:fragment>
				</LabelBase>

				{#if showAdvanced}
					<AdvancedParams admin={$user?.role === 'admin'} bind:params />
					<hr class=" border-gray-100 dark:border-gray-850" />

					<div class="space-y-2">
						<LabelBase label={$i18n.t('Keep Alive')} size="md">
							<svelte:fragment slot="right">
								<div class="flex items-center gap-1 w-[10rem]">
									<Button
										kind={keepAlive === null ? 'filled' : 'outlined'}
										size="sm"
										className="flex-1 justify-center"
										on:click={() => {
											keepAlive = null;
										}}
									>
										{$i18n.t('Default')}
									</Button>
									<Button
										kind={keepAlive !== null ? 'filled' : 'outlined'}
										size="sm"
										className="flex-1 justify-center"
										on:click={() => {
											keepAlive = '5m';
										}}
									>
										{$i18n.t('Custom')}
									</Button>
								</div>
							</svelte:fragment>
						</LabelBase>

						{#if keepAlive !== null}
							<Input
								bind:value={keepAlive}
								size="md"
								placeholder={$i18n.t("e.g. '30s','10m'. Valid time units are 's', 'm', 'h'.")}
							/>
						{/if}
					</div>

					<div class="space-y-2">
						<LabelBase label={$i18n.t('Request Mode')} size="md">
							<svelte:fragment slot="right">
								<div class="flex items-center gap-1 w-[10rem]">
									<Button
										kind={requestFormat === null ? 'filled' : 'outlined'}
										size="sm"
										className="flex-1 justify-center"
										on:click={() => toggleRequestFormat(false)}
									>
										{$i18n.t('Default')}
									</Button>
									<Button
										kind={requestFormat !== null ? 'filled' : 'outlined'}
										size="sm"
										className="flex-1 justify-center"
										on:click={() => toggleRequestFormat(true)}
									>
										{$i18n.t('JSON')}
									</Button>
								</div>
							</svelte:fragment>
						</LabelBase>

						{#if requestFormat !== null}
							<Textarea
								bind:value={requestFormat}
								size="md"
								placeholder={$i18n.t('e.g. "json" or a JSON schema')}
							/>
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button
			kind="filled"
			size="md"
			on:click={() => {
				saveHandler();
			}}
		>
			{$i18n.t('Save')}
		</Button>
	</div>
</div>
