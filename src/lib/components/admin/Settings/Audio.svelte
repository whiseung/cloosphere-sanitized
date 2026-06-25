<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	const dispatch = createEventDispatcher();

	import { getBackendConfig } from '$lib/apis';
	import {
		getAudioConfig,
		updateAudioConfig,
		getModels as _getModels,
		getVoices as _getVoices,
		getAvatars as _getAvatars
	} from '$lib/apis/audio';
	import { config, settings } from '$lib/stores';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SensitiveTextarea from '$lib/components/common/SensitiveTextarea.svelte';

	import { TTS_RESPONSE_SPLIT } from '$lib/types';

	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let saveHandler: () => void;

	// Audio
	let TTS_OPENAI_API_BASE_URL = '';
	let TTS_OPENAI_API_KEY = '';
	let TTS_API_KEY = '';
	let TTS_ENGINE = '';
	let TTS_MODEL = '';
	let TTS_VOICE = '';
	let TTS_SPLIT_ON: TTS_RESPONSE_SPLIT = TTS_RESPONSE_SPLIT.PUNCTUATION;
	let TTS_AZURE_SPEECH_REGION = '';
	let TTS_AZURE_SPEECH_OUTPUT_FORMAT = '';

	let STT_OPENAI_API_BASE_URL = '';
	let STT_OPENAI_API_KEY = '';
	let STT_ENGINE = '';
	let STT_MODEL = '';
	let STT_WHISPER_MODEL = '';
	let STT_AZURE_API_KEY = '';
	let STT_AZURE_REGION = '';
	let STT_AZURE_LOCALES = '';
	let STT_DEEPGRAM_API_KEY = '';

	let STT_GOOGLE_PROJECT_ID = '';
	let STT_GOOGLE_LOCATION = 'global';
	let STT_GOOGLE_LANGUAGE_CODES = 'auto';
	let STT_GOOGLE_SERVICE_ACCOUNT_KEY = '';

	let TTS_GOOGLE_LANGUAGE_CODE = '';
	let TTS_GOOGLE_SERVICE_ACCOUNT_KEY = '';

	let TTS_GEMINI_MODEL = 'gemini-2.5-flash-preview-tts';
	let TTS_GEMINI_LOCATION = 'us-central1';
	let TTS_GEMINI_SERVICE_ACCOUNT_KEY = '';

	let STT_WHISPER_MODEL_LOADING = false;

	// Avatar
	let AVATAR_ENGINE = '';
	let AVATAR_API_KEY = '';
	let AVATAR_REGION = '';
	let AVATAR_CHARACTER = '';
	let AVATAR_STYLE = '';
	let AVATAR_GREETING = '';

	let avatars: any[] = [];
	let selectedAvatarStyles: any[] = [];

	// eslint-disable-next-line no-undef
	let voices: SpeechSynthesisVoice[] = [];
	let models: Awaited<ReturnType<typeof _getModels>>['models'] = [];

	$: sttEngineOptions = [
		{ value: '', label: $i18n.t('Whisper (Local)') },
		{ value: 'openai', label: 'OpenAI' },
		{ value: 'web', label: $i18n.t('Web API') },
		{ value: 'deepgram', label: 'Deepgram' },
		{ value: 'azure', label: 'Azure AI Speech' },
		{ value: 'google', label: $i18n.t('Google Cloud Speech') }
	];

	$: ttsEngineOptions = [
		{ value: '', label: $i18n.t('Web API') },
		{ value: 'transformers', label: `${$i18n.t('Transformers')} (${$i18n.t('Local')})` },
		{ value: 'openai', label: $i18n.t('OpenAI') },
		{ value: 'elevenlabs', label: $i18n.t('ElevenLabs') },
		{ value: 'azure', label: $i18n.t('Azure AI Speech') },
		{ value: 'google', label: $i18n.t('Google Cloud TTS') },
		{ value: 'gemini', label: $i18n.t('Gemini TTS') }
	];

	$: splitOptions = Object.values(TTS_RESPONSE_SPLIT).map((split) => ({
		value: split,
		label: $i18n.t(split.charAt(0).toUpperCase() + split.slice(1))
	}));

	$: avatarEngineOptions = [
		{ value: '', label: $i18n.t('Default (None)') },
		{ value: 'azure', label: 'Azure AI Speech' }
	];

	$: avatarCharacterOptions = [
		{ value: '', label: $i18n.t('Select character') },
		...avatars.map((a) => ({ value: a.id, label: `${a.name} - ${a.description}` }))
	];

	$: avatarStyleOptions = [
		{ value: '', label: $i18n.t('Select style') },
		...selectedAvatarStyles.map((s) => ({ value: s.id, label: s.name }))
	];

	$: webVoiceOptions = [
		{ value: '', label: $i18n.t('Default') },
		...voices.map((v: any) => ({ value: v.voiceURI ?? v.id, label: v.name }))
	];

	$: geminiVoiceOptions = voices.map((v: any) => ({ value: v.id, label: v.name }));
	$: geminiModelOptions = models.map((m) => ({ value: m.id, label: m.name }));

	const getModels = async () => {
		if (TTS_ENGINE === '') {
			models = [];
		} else {
			const res = await _getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			).catch((e) => {
				toast.error($i18n.t(`${e}`));
			});

			if (res) {
				console.log(res);
				models = res.models;
			}
		}
	};

	const getVoices = async () => {
		if (TTS_ENGINE === '') {
			const getVoicesLoop = setInterval(() => {
				voices = speechSynthesis.getVoices();

				// do your loop
				if (voices.length > 0) {
					clearInterval(getVoicesLoop);
					voices.sort((a, b) => a.name.localeCompare(b.name, $i18n.resolvedLanguage));
				}
			}, 100);
		} else {
			const res = await _getVoices(localStorage.token).catch((e) => {
				toast.error($i18n.t(`${e}`));
			});

			if (res) {
				console.log(res);
				voices = res.voices;
				voices.sort((a, b) => a.name.localeCompare(b.name, $i18n.resolvedLanguage));
			}
		}
	};

	const getAvatars = async () => {
		if (AVATAR_ENGINE === 'azure') {
			const res = await _getAvatars(localStorage.token).catch((e) => {
				toast.error($i18n.t(`${e}`));
			});

			if (res) {
				console.log('[Avatar] Loaded avatars:', res);
				avatars = res.avatars;
				// After loading avatars, update styles if character is already selected
				if (AVATAR_CHARACTER) {
					updateAvatarStyles();
				}
			}
		} else {
			// Clear avatars if engine is not Azure
			avatars = [];
			selectedAvatarStyles = [];
		}
	};

	const updateAvatarStyles = () => {
		console.log('[Avatar] Updating styles for character:', AVATAR_CHARACTER);
		console.log('[Avatar] Available avatars:', avatars.length);

		if (!avatars || avatars.length === 0) {
			console.log('[Avatar] No avatars loaded yet');
			selectedAvatarStyles = [];
			return;
		}

		const avatar = avatars.find((a) => a.id === AVATAR_CHARACTER);
		if (avatar) {
			console.log('[Avatar] Found avatar:', avatar);
			selectedAvatarStyles = avatar.styles;
			// If current style is not available in new character, reset it
			if (!selectedAvatarStyles.find((s) => s.id === AVATAR_STYLE)) {
				AVATAR_STYLE = selectedAvatarStyles[0]?.id || '';
			}
		} else {
			console.log('[Avatar] Avatar not found for character:', AVATAR_CHARACTER);
			selectedAvatarStyles = [];
		}
	};

	// Watch for AVATAR_CHARACTER changes (when avatars are already loaded)
	$: if (AVATAR_CHARACTER && avatars.length > 0) {
		updateAvatarStyles();
	}

	// Watch for AVATAR_ENGINE changes
	$: if (AVATAR_ENGINE) {
		getAvatars();
	}

	const updateConfigHandler = async () => {
		const res = await updateAudioConfig(localStorage.token, {
			tts: {
				OPENAI_API_BASE_URL: TTS_OPENAI_API_BASE_URL,
				OPENAI_API_KEY: TTS_OPENAI_API_KEY,
				API_KEY: TTS_API_KEY,
				ENGINE: TTS_ENGINE,
				MODEL: TTS_MODEL,
				VOICE: TTS_VOICE,
				SPLIT_ON: TTS_SPLIT_ON,
				AZURE_SPEECH_REGION: TTS_AZURE_SPEECH_REGION,
				AZURE_SPEECH_OUTPUT_FORMAT: TTS_AZURE_SPEECH_OUTPUT_FORMAT,
				GOOGLE_LANGUAGE_CODE: TTS_GOOGLE_LANGUAGE_CODE,
				GOOGLE_SERVICE_ACCOUNT_KEY: TTS_GOOGLE_SERVICE_ACCOUNT_KEY,
				GEMINI_MODEL: TTS_GEMINI_MODEL,
				GEMINI_LOCATION: TTS_GEMINI_LOCATION,
				GEMINI_SERVICE_ACCOUNT_KEY: TTS_GEMINI_SERVICE_ACCOUNT_KEY
			},
			stt: {
				OPENAI_API_BASE_URL: STT_OPENAI_API_BASE_URL,
				OPENAI_API_KEY: STT_OPENAI_API_KEY,
				ENGINE: STT_ENGINE,
				MODEL: STT_MODEL,
				WHISPER_MODEL: STT_WHISPER_MODEL,
				DEEPGRAM_API_KEY: STT_DEEPGRAM_API_KEY,
				AZURE_API_KEY: STT_AZURE_API_KEY,
				AZURE_REGION: STT_AZURE_REGION,
				AZURE_LOCALES: STT_AZURE_LOCALES,
				GOOGLE_PROJECT_ID: STT_GOOGLE_PROJECT_ID,
				GOOGLE_LOCATION: STT_GOOGLE_LOCATION,
				GOOGLE_LANGUAGE_CODES: STT_GOOGLE_LANGUAGE_CODES,
				GOOGLE_SERVICE_ACCOUNT_KEY: STT_GOOGLE_SERVICE_ACCOUNT_KEY
			},
			avatar: {
				ENGINE: AVATAR_ENGINE,
				API_KEY: AVATAR_API_KEY,
				REGION: AVATAR_REGION,
				CHARACTER: AVATAR_CHARACTER,
				STYLE: AVATAR_STYLE,
				GREETING: AVATAR_GREETING
			}
		});

		if (res) {
			saveHandler();
			config.set(await getBackendConfig());
		}
	};

	const sttModelUpdateHandler = async () => {
		STT_WHISPER_MODEL_LOADING = true;
		await updateConfigHandler();
		STT_WHISPER_MODEL_LOADING = false;
	};

	const onSplitOnChange = (value: string) => {
		TTS_SPLIT_ON = value as TTS_RESPONSE_SPLIT;
	};

	const onTtsEngineChange = async (newEngine: string) => {
		// Update state first so downstream handlers see the new value.
		TTS_ENGINE = newEngine;

		await updateConfigHandler();
		await getVoices();
		await getModels();

		if (newEngine === 'openai') {
			TTS_VOICE = 'alloy';
			TTS_MODEL = 'tts-1';
		} else if (newEngine === 'gemini') {
			TTS_VOICE = 'Kore';
			TTS_MODEL = 'gemini-2.5-flash-preview-tts';
		} else {
			TTS_VOICE = '';
			TTS_MODEL = '';
		}
	};

	onMount(async () => {
		const res = await getAudioConfig(localStorage.token);

		if (res) {
			console.log(res);
			TTS_OPENAI_API_BASE_URL = res.tts.OPENAI_API_BASE_URL;
			TTS_OPENAI_API_KEY = res.tts.OPENAI_API_KEY;
			TTS_API_KEY = res.tts.API_KEY;

			TTS_ENGINE = res.tts.ENGINE;
			TTS_MODEL = res.tts.MODEL;
			TTS_VOICE = res.tts.VOICE;

			TTS_SPLIT_ON = res.tts.SPLIT_ON || TTS_RESPONSE_SPLIT.PUNCTUATION;

			TTS_AZURE_SPEECH_OUTPUT_FORMAT = res.tts.AZURE_SPEECH_OUTPUT_FORMAT;
			TTS_AZURE_SPEECH_REGION = res.tts.AZURE_SPEECH_REGION;

			// Avatar configuration
			if (res.avatar) {
				AVATAR_ENGINE = res.avatar.ENGINE || '';
				AVATAR_API_KEY = res.avatar.API_KEY || '';
				AVATAR_REGION = res.avatar.REGION || '';
				AVATAR_CHARACTER = res.avatar.CHARACTER || '';
				AVATAR_STYLE = res.avatar.STYLE || '';
				AVATAR_GREETING = res.avatar.GREETING || '';
			}

			console.log('[Avatar] Loaded config:', {
				AVATAR_ENGINE,
				AVATAR_API_KEY: AVATAR_API_KEY ? '***' : '',
				AVATAR_REGION,
				AVATAR_CHARACTER,
				AVATAR_STYLE,
				AVATAR_GREETING
			});

			STT_OPENAI_API_BASE_URL = res.stt.OPENAI_API_BASE_URL;
			STT_OPENAI_API_KEY = res.stt.OPENAI_API_KEY;

			STT_ENGINE = res.stt.ENGINE;
			STT_MODEL = res.stt.MODEL;
			STT_WHISPER_MODEL = res.stt.WHISPER_MODEL;
			STT_AZURE_API_KEY = res.stt.AZURE_API_KEY;
			STT_AZURE_REGION = res.stt.AZURE_REGION;
			STT_AZURE_LOCALES = res.stt.AZURE_LOCALES;
			STT_DEEPGRAM_API_KEY = res.stt.DEEPGRAM_API_KEY;

			STT_GOOGLE_PROJECT_ID = res.stt.GOOGLE_PROJECT_ID || '';
			STT_GOOGLE_LOCATION = res.stt.GOOGLE_LOCATION || 'global';
			STT_GOOGLE_LANGUAGE_CODES = res.stt.GOOGLE_LANGUAGE_CODES || 'auto';
			STT_GOOGLE_SERVICE_ACCOUNT_KEY = res.stt.GOOGLE_SERVICE_ACCOUNT_KEY || '';

			TTS_GOOGLE_LANGUAGE_CODE = res.tts.GOOGLE_LANGUAGE_CODE || '';
			TTS_GOOGLE_SERVICE_ACCOUNT_KEY = res.tts.GOOGLE_SERVICE_ACCOUNT_KEY || '';

			TTS_GEMINI_MODEL = res.tts.GEMINI_MODEL || 'gemini-2.5-flash-preview-tts';
			TTS_GEMINI_LOCATION = res.tts.GEMINI_LOCATION || 'us-central1';
			TTS_GEMINI_SERVICE_ACCOUNT_KEY = res.tts.GEMINI_SERVICE_ACCOUNT_KEY || '';
		}

		await getVoices();
		await getModels();

		// Load avatars if engine is set
		if (AVATAR_ENGINE) {
			await getAvatars();
		}
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		await updateConfigHandler();
		dispatch('save');
	}}
>
	<div class=" space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		<div class="flex flex-col gap-3">
			<!-- STT Settings -->
			<div>
				<div class=" mb-1 text-sm font-medium">{$i18n.t('STT Settings')}</div>

				<LabelBase label={$i18n.t('Speech-to-Text Engine')} size="md">
					<svelte:fragment slot="right">
						<div class="min-w-[16rem]">
							<Selector
								value={STT_ENGINE ?? ''}
								items={sttEngineOptions}
								size="sm"
								searchEnabled={false}
								on:change={(event) => {
									STT_ENGINE = event.detail.value;
								}}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>

				{#if STT_ENGINE === 'openai'}
					<div class="mt-2 flex gap-2 mb-1">
						<div class="flex-1">
							<Input
								bind:value={STT_OPENAI_API_BASE_URL}
								placeholder={$i18n.t('API Base URL')}
								size="md"
							/>
						</div>
						<div class="flex-1">
							<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={STT_OPENAI_API_KEY} />
						</div>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div>
						<div class=" mb-1.5 text-sm font-medium">{$i18n.t('STT Model')}</div>
						<input
							list="model-list"
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={STT_MODEL}
							placeholder="Select a model"
						/>
						<datalist id="model-list">
							<option value="whisper-1" />
						</datalist>
					</div>
				{:else if STT_ENGINE === 'deepgram'}
					<div class="mt-2 mb-1">
						<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={STT_DEEPGRAM_API_KEY} />
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<Input
						bind:value={STT_MODEL}
						label={$i18n.t('STT Model')}
						caption={$i18n.t('Leave model field empty to use the default model.')}
						placeholder="Select a model (optional)"
						size="md"
					/>
					<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
						<a
							class=" hover:underline dark:text-gray-200 text-gray-800"
							href="https://developers.deepgram.com/docs/models"
							target="_blank"
						>
							{$i18n.t('Click here to see available models.')}
						</a>
					</div>
				{:else if STT_ENGINE === 'azure'}
					<div class="mt-2 flex gap-2 mb-1">
						<div class="flex-1">
							<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={STT_AZURE_API_KEY} />
						</div>
						<div class="flex-1">
							<Input
								bind:value={STT_AZURE_REGION}
								placeholder={$i18n.t('Azure Region')}
								size="md"
							/>
						</div>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<Input
						bind:value={STT_AZURE_LOCALES}
						label={$i18n.t('Language Locales')}
						placeholder={$i18n.t('e.g., en-US,ja-JP (leave blank for auto-detect)')}
						size="md"
					/>
				{:else if STT_ENGINE === 'google'}
					<div class="mt-2 flex gap-2 mb-1">
						<div class="flex-1">
							<Input
								bind:value={STT_GOOGLE_PROJECT_ID}
								placeholder={$i18n.t('GCP Project ID')}
								size="md"
							/>
						</div>
						<div class="flex-1">
							<Input
								bind:value={STT_GOOGLE_LOCATION}
								placeholder={$i18n.t('Location (e.g. global, us-central1)')}
								size="md"
							/>
						</div>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<Input
						bind:value={STT_MODEL}
						label={$i18n.t('STT Model')}
						placeholder="chirp_2, chirp_3, short, long"
						size="md"
					/>
					<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
						{$i18n.t('Enter a Cloud Speech-to-Text V2 model name.')}
						<a
							class=" hover:underline dark:text-gray-200 text-gray-800"
							href="https://cloud.google.com/speech-to-text/v2/docs/speech-to-text-supported-languages"
							target="_blank"
						>
							{$i18n.t('Click here to see available models.')}
						</a>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<Input
						bind:value={STT_GOOGLE_LANGUAGE_CODES}
						label={$i18n.t('Language Codes')}
						placeholder="auto, ko-KR, en-US"
						size="md"
					/>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div>
						<LabelBase label={$i18n.t('Service Account Key (Optional)')} size="md" />
						<SensitiveTextarea
							placeholder={$i18n.t('Leave empty to use Application Default Credentials.')}
							bind:value={STT_GOOGLE_SERVICE_ACCOUNT_KEY}
						/>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t('Use Global Google Cloud Key')}
						</div>
					</div>
				{:else if STT_ENGINE === ''}
					<div class="mt-2">
						<div class=" mb-1.5 text-sm font-medium">{$i18n.t('STT Model')}</div>

						<div class="flex w-full">
							<div class="flex-1 mr-2">
								<input
									class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
									placeholder={$i18n.t('Set whisper model')}
									bind:value={STT_WHISPER_MODEL}
								/>
							</div>

							<button
								class="px-2.5 bg-gray-50 hover:bg-gray-200 text-gray-800 dark:bg-gray-850 dark:hover:bg-gray-800 dark:text-gray-100 rounded-lg transition"
								type="button"
								on:click={() => {
									sttModelUpdateHandler();
								}}
								disabled={STT_WHISPER_MODEL_LOADING}
							>
								{#if STT_WHISPER_MODEL_LOADING}
									<div class="self-center">
										<svg
											class=" w-4 h-4"
											viewBox="0 0 24 24"
											fill="currentColor"
											xmlns="http://www.w3.org/2000/svg"
										>
											<style>
												.spinner_ajPY {
													transform-origin: center;
													animation: spinner_AtaB 0.75s infinite linear;
												}

												@keyframes spinner_AtaB {
													100% {
														transform: rotate(360deg);
													}
												}
											</style>
											<path
												d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
												opacity=".25"
											/>
											<path
												d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
												class="spinner_ajPY"
											/>
										</svg>
									</div>
								{:else}
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 16 16"
										fill="currentColor"
										class="w-4 h-4"
									>
										<path
											d="M8.75 2.75a.75.75 0 0 0-1.5 0v5.69L5.03 6.22a.75.75 0 0 0-1.06 1.06l3.5 3.5a.75.75 0 0 0 1.06 0l3.5-3.5a.75.75 0 0 0-1.06-1.06L8.75 8.44V2.75Z"
										/>
										<path
											d="M3.5 9.75a.75.75 0 0 0-1.5 0v1.5A2.75 2.75 0 0 0 4.75 14h6.5A2.75 2.75 0 0 0 14 11.25v-1.5a.75.75 0 0 0-1.5 0v1.5c0 .69-.56 1.25-1.25 1.25h-6.5c-.69 0-1.25-.56-1.25-1.25v-1.5Z"
										/>
									</svg>
								{/if}
							</button>
						</div>

						<div class="mt-2 mb-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t(`Open WebUI uses faster-whisper internally.`)}

							<a
								class=" hover:underline dark:text-gray-200 text-gray-800"
								href="https://github.com/SYSTRAN/faster-whisper"
								target="_blank"
							>
								{$i18n.t(
									`Click here to learn more about faster-whisper and see the available models.`
								)}
							</a>
						</div>
					</div>
				{/if}
			</div>

			<hr class="border-gray-100 dark:border-gray-850" />

			<!-- TTS Settings -->
			<div>
				<div class=" mb-1 text-sm font-medium">{$i18n.t('TTS Settings')}</div>

				<LabelBase label={$i18n.t('Text-to-Speech Engine')} size="md">
					<svelte:fragment slot="right">
						<div class="min-w-[16rem]">
							<Selector
								value={TTS_ENGINE ?? ''}
								items={ttsEngineOptions}
								size="sm"
								searchEnabled={false}
								on:change={(event) => onTtsEngineChange(event.detail.value)}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>

				{#if TTS_ENGINE === 'openai'}
					<div class="mt-2 flex gap-2 mb-1">
						<div class="flex-1">
							<Input
								bind:value={TTS_OPENAI_API_BASE_URL}
								placeholder={$i18n.t('API Base URL')}
								size="md"
							/>
						</div>
						<div class="flex-1">
							<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={TTS_OPENAI_API_KEY} />
						</div>
					</div>
				{:else if TTS_ENGINE === 'elevenlabs'}
					<div class="mt-2 mb-1">
						<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={TTS_API_KEY} />
					</div>
				{:else if TTS_ENGINE === 'azure'}
					<div class="mt-2 flex gap-2 mb-1">
						<div class="flex-1">
							<SensitiveInput placeholder={$i18n.t('API Key')} bind:value={TTS_API_KEY} />
						</div>
						<div class="flex-1">
							<Input
								bind:value={TTS_AZURE_SPEECH_REGION}
								placeholder={$i18n.t('Azure Region')}
								size="md"
							/>
						</div>
					</div>
				{:else if TTS_ENGINE === 'google'}
					<div class="mt-2 mb-1">
						<Input
							bind:value={TTS_GOOGLE_LANGUAGE_CODE}
							label={$i18n.t('Language Filter (Optional)')}
							placeholder="ko-KR, en-US"
							size="md"
						/>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div>
						<LabelBase label={$i18n.t('Service Account Key (Optional)')} size="md" />
						<SensitiveTextarea
							placeholder={$i18n.t('Leave empty to use Application Default Credentials.')}
							bind:value={TTS_GOOGLE_SERVICE_ACCOUNT_KEY}
						/>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t('Use Global Google Cloud Key')}
						</div>
					</div>
				{:else if TTS_ENGINE === 'gemini'}
					<div class="mt-2 mb-1">
						<Input
							bind:value={TTS_GEMINI_LOCATION}
							placeholder={$i18n.t('Location (e.g. us-central1)')}
							size="md"
						/>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div>
						<LabelBase label={$i18n.t('Service Account Key (Optional)')} size="md" />
						<SensitiveTextarea
							placeholder={$i18n.t('Leave empty to use Application Default Credentials.')}
							bind:value={TTS_GEMINI_SERVICE_ACCOUNT_KEY}
						/>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t('Use Global Google Cloud Key')}
						</div>
					</div>
				{/if}

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				{#if TTS_ENGINE === ''}
					<div>
						<LabelBase label={$i18n.t('TTS Voice')} size="md" />
						<Selector
							value={TTS_VOICE ?? ''}
							items={webVoiceOptions}
							size="sm"
							searchEnabled={voices.length > 10}
							on:change={(event) => {
								TTS_VOICE = event.detail.value;
							}}
						/>
					</div>
				{:else if TTS_ENGINE === 'transformers'}
					<div>
						<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Model')}</div>
						<input
							list="tts-model-list"
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={TTS_MODEL}
							placeholder="CMU ARCTIC speaker embedding name"
						/>
						<datalist id="tts-model-list">
							<option value="tts-1" />
						</datalist>
						<div class="mt-2 mb-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t(`Open WebUI uses SpeechT5 and CMU Arctic speaker embeddings.`)}

							To learn more about SpeechT5,

							<a
								class=" hover:underline dark:text-gray-200 text-gray-800"
								href="https://github.com/microsoft/SpeechT5"
								target="_blank"
							>
								{$i18n.t(`click here`, {
									name: 'SpeechT5'
								})}.
							</a>
							To see the available CMU Arctic speaker embeddings,
							<a
								class=" hover:underline dark:text-gray-200 text-gray-800"
								href="https://huggingface.co/datasets/Matthijs/cmu-arctic-xvectors"
								target="_blank"
							>
								{$i18n.t(`click here`)}.
							</a>
						</div>
					</div>
				{:else if TTS_ENGINE === 'openai'}
					<div class="flex gap-2">
						<div class="w-full">
							<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Voice')}</div>
							<input
								list="voice-list"
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={TTS_VOICE}
								placeholder="Select a voice"
							/>
							<datalist id="voice-list">
								{#each voices as voice}
									<option value={voice.id}>{voice.name}</option>
								{/each}
							</datalist>
						</div>
						<div class="w-full">
							<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Model')}</div>
							<input
								list="tts-model-list"
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={TTS_MODEL}
								placeholder="Select a model"
							/>
							<datalist id="tts-model-list">
								{#each models as model}
									<option value={model.id} class="bg-gray-50 dark:bg-gray-700" />
								{/each}
							</datalist>
						</div>
					</div>
				{:else if TTS_ENGINE === 'elevenlabs'}
					<div class="flex gap-2">
						<div class="w-full">
							<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Voice')}</div>
							<input
								list="voice-list"
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={TTS_VOICE}
								placeholder="Select a voice"
							/>
							<datalist id="voice-list">
								{#each voices as voice}
									<option value={voice.id}>{voice.name}</option>
								{/each}
							</datalist>
						</div>
						<div class="w-full">
							<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Model')}</div>
							<input
								list="tts-model-list"
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={TTS_MODEL}
								placeholder="Select a model"
							/>
							<datalist id="tts-model-list">
								{#each models as model}
									<option value={model.id} class="bg-gray-50 dark:bg-gray-700" />
								{/each}
							</datalist>
						</div>
					</div>
				{:else if TTS_ENGINE === 'azure'}
					<div class="flex gap-2">
						<div class="w-full">
							<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Voice')}</div>
							<input
								list="voice-list"
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={TTS_VOICE}
								placeholder="Select a voice"
							/>
							<datalist id="voice-list">
								{#each voices as voice}
									<option value={voice.id}>{voice.name}</option>
								{/each}
							</datalist>
						</div>
						<div class="w-full">
							<div class=" mb-1.5 text-sm font-medium">
								{$i18n.t('Output format')}
								<a
									href="https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech?tabs=streaming#audio-outputs"
									target="_blank"
								>
									<small>{$i18n.t('Available list')}</small>
								</a>
							</div>
							<input
								list="tts-model-list"
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={TTS_AZURE_SPEECH_OUTPUT_FORMAT}
								placeholder="Select a output format"
							/>
						</div>
					</div>
				{:else if TTS_ENGINE === 'google'}
					<div>
						<div class=" mb-1.5 text-sm font-medium">{$i18n.t('TTS Voice')}</div>
						<input
							list="voice-list"
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={TTS_VOICE}
							placeholder="Select a voice"
						/>
						<datalist id="voice-list">
							{#each voices as voice}
								<option value={voice.id}>{voice.name}</option>
							{/each}
						</datalist>
					</div>
				{:else if TTS_ENGINE === 'gemini'}
					<div class="flex gap-2">
						<div class="w-full">
							<LabelBase label={$i18n.t('TTS Voice')} size="md" />
							<Selector
								value={TTS_VOICE ?? ''}
								items={geminiVoiceOptions}
								size="sm"
								on:change={(event) => {
									TTS_VOICE = event.detail.value;
								}}
							/>
						</div>
						<div class="w-full">
							<LabelBase label={$i18n.t('TTS Model')} size="md" />
							<Selector
								value={TTS_GEMINI_MODEL ?? ''}
								items={geminiModelOptions}
								size="sm"
								on:change={(event) => {
									TTS_GEMINI_MODEL = event.detail.value;
								}}
							/>
						</div>
					</div>
				{/if}

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<LabelBase
					label={$i18n.t('Response splitting')}
					caption={$i18n.t(
						"Control how message text is split for TTS requests. 'Punctuation' splits into sentences, 'paragraphs' splits into paragraphs, and 'none' keeps the message as a single string."
					)}
					size="md"
				>
					<svelte:fragment slot="right">
						<div class="min-w-[16rem]">
							<Selector
								value={TTS_SPLIT_ON ?? ''}
								items={splitOptions}
								size="sm"
								searchEnabled={false}
								on:change={(event) => onSplitOnChange(event.detail.value)}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>

				<hr class="border-gray-100 dark:border-gray-850 my-3" />

				<!-- AVATAR Section -->
				<div class="flex mb-2 gap-2 items-center">
					<div class="flex-1 text-xs font-medium uppercase">{$i18n.t('Avatar')}</div>
				</div>

				<div class="space-y-3">
					<LabelBase label={$i18n.t('Avatar Engine')} size="md">
						<svelte:fragment slot="right">
							<div class="min-w-[16rem]">
								<Selector
									value={AVATAR_ENGINE ?? ''}
									items={avatarEngineOptions}
									size="sm"
									searchEnabled={false}
									on:change={(event) => {
										AVATAR_ENGINE = event.detail.value;
									}}
								/>
							</div>
						</svelte:fragment>
					</LabelBase>

					{#if AVATAR_ENGINE === 'azure'}
						<div>
							<LabelBase label={$i18n.t('API Key')} size="md" />
							<SensitiveInput placeholder="Enter API Key" bind:value={AVATAR_API_KEY} />
						</div>

						<Input
							bind:value={AVATAR_REGION}
							label={$i18n.t('Azure Region')}
							placeholder="e.g. eastus, koreacentral"
							size="md"
						/>

						<LabelBase label={$i18n.t('Avatar Character')} size="md">
							<svelte:fragment slot="right">
								<div class="min-w-[16rem]">
									<Selector
										value={AVATAR_CHARACTER ?? ''}
										items={avatarCharacterOptions}
										size="sm"
										searchEnabled={avatars.length > 10}
										on:change={(event) => {
											AVATAR_CHARACTER = event.detail.value;
										}}
									/>
								</div>
							</svelte:fragment>
						</LabelBase>

						{#if AVATAR_CHARACTER && selectedAvatarStyles.length > 0}
							<LabelBase label={$i18n.t('Avatar Style')} size="md">
								<svelte:fragment slot="right">
									<div class="min-w-[16rem]">
										<Selector
											value={AVATAR_STYLE ?? ''}
											items={avatarStyleOptions}
											size="sm"
											searchEnabled={false}
											on:change={(event) => {
												AVATAR_STYLE = event.detail.value;
											}}
										/>
									</div>
								</svelte:fragment>
							</LabelBase>
						{/if}

						<Input
							bind:value={AVATAR_GREETING}
							label={$i18n.t('Greeting Message')}
							caption={$i18n.t(
								'Initial greeting message when avatar appears. Leave empty for default.'
							)}
							placeholder={$i18n.t('e.g. Hello, 안녕하세요')}
							size="md"
						/>
					{/if}
				</div>
			</div>
		</div>
	</div>

	<div class="flex justify-end text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
