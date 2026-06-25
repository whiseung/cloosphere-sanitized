<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { KokoroTTS } from 'kokoro-js';

	import { user, settings, config } from '$lib/stores';
	import { getVoices as _getVoices } from '$lib/apis/audio';

	import Switch from '$lib/components/common/Switch.svelte';
	import { round } from '@huggingface/transformers';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	// Audio
	let conversationMode = false;
	let speechAutoSend = false;
	let responseAutoPlayback = false;
	let nonLocalVoices = false;

	let STTEngine = '';

	let TTSEngine = '';
	let TTSEngineConfig = {};

	let TTSModel = null;
	let TTSModelProgress = null;
	let TTSModelLoading = false;

	let voices = [];
	let voice = '';

	// Audio speed control
	let playbackRate = 1;
	const speedOptions = [2, 1.75, 1.5, 1.25, 1, 0.75, 0.5];

	const getVoices = async () => {
		if (TTSEngine === 'browser-kokoro') {
			if (!TTSModel) {
				await loadKokoro();
			}

			voices = Object.entries(TTSModel.voices).map(([key, value]) => {
				return {
					id: key,
					name: value.name,
					localService: false
				};
			});
		} else {
			if ($config.audio.tts.engine === '') {
				const getVoicesLoop = setInterval(async () => {
					voices = await speechSynthesis.getVoices();

					// do your loop
					if (voices.length > 0) {
						clearInterval(getVoicesLoop);
					}
				}, 100);
			} else {
				const res = await _getVoices(localStorage.token).catch((e) => {
					toast.error($i18n.t(`${e}`));
				});

				if (res) {
					console.log(res);
					voices = res.voices;
				}
			}
		}
	};

	const toggleResponseAutoPlayback = async () => {
		responseAutoPlayback = !responseAutoPlayback;
		saveSettings({ responseAutoPlayback: responseAutoPlayback });
	};

	const toggleSpeechAutoSend = async () => {
		speechAutoSend = !speechAutoSend;
		saveSettings({ speechAutoSend: speechAutoSend });
	};

	onMount(async () => {
		playbackRate = $settings.audio?.tts?.playbackRate ?? 1;
		conversationMode = $settings.conversationMode ?? false;
		speechAutoSend = $settings.speechAutoSend ?? false;
		responseAutoPlayback = $settings.responseAutoPlayback ?? false;

		STTEngine = $settings?.audio?.stt?.engine ?? '';

		TTSEngine = $settings?.audio?.tts?.engine ?? '';
		TTSEngineConfig = $settings?.audio?.tts?.engineConfig ?? {};

		if ($settings?.audio?.tts?.defaultVoice === $config.audio.tts.voice) {
			voice = $settings?.audio?.tts?.voice ?? $config.audio.tts.voice ?? '';
		} else {
			voice = $config.audio.tts.voice ?? '';
		}

		nonLocalVoices = $settings.audio?.tts?.nonLocalVoices ?? false;

		await getVoices();
	});

	$: if (TTSEngine && TTSEngineConfig) {
		onTTSEngineChange();
	}

	const onTTSEngineChange = async () => {
		if (TTSEngine === 'browser-kokoro') {
			await loadKokoro();
		}
	};

	// Selector items
	$: sttEngineItems = [
		{ value: '', label: $i18n.t('Default') },
		{ value: 'web', label: $i18n.t('Web API') }
	];
	$: ttsEngineItems = [
		{ value: '', label: $i18n.t('Default') },
		{ value: 'browser-kokoro', label: $i18n.t('Kokoro.js (Browser)') }
	];
	const kokoroDtypeItems = [
		{ value: 'fp32', label: 'fp32' },
		{ value: 'fp16', label: 'fp16' },
		{ value: 'q8', label: 'q8' },
		{ value: 'q4', label: 'q4' }
	];
	$: playbackRateItems = speedOptions.map((opt) => ({ value: String(opt), label: `${opt}x` }));
	$: voiceItems = [
		{ value: '', label: $i18n.t('Default') },
		...voices
			.filter((v) => nonLocalVoices || v.localService === true)
			.map((v) => ({ value: v.name, label: v.name }))
	];

	const handleSpeechAutoSendChange = (next: boolean) => {
		speechAutoSend = next;
		saveSettings({ speechAutoSend: next });
	};
	const handleResponseAutoPlaybackChange = (next: boolean) => {
		responseAutoPlayback = next;
		saveSettings({ responseAutoPlayback: next });
	};
	const handlePlaybackRateChange = (value: string) => {
		playbackRate = Number(value);
	};

	const loadKokoro = async () => {
		if (TTSEngine === 'browser-kokoro') {
			voices = [];

			if (TTSEngineConfig?.dtype) {
				TTSModel = null;
				TTSModelProgress = null;
				TTSModelLoading = true;

				const model_id = 'onnx-community/Kokoro-82M-v1.0-ONNX';

				TTSModel = await KokoroTTS.from_pretrained(model_id, {
					dtype: TTSEngineConfig.dtype, // Options: "fp32", "fp16", "q8", "q4", "q4f16"
					device: navigator?.gpu ? 'webgpu' : 'wasm', // Detect WebGPU
					progress_callback: (e) => {
						TTSModelProgress = e;
						console.log(e);
					}
				});

				await getVoices();

				// const rawAudio = await tts.generate(inputText, {
				// 	// Use `tts.list_voices()` to list all available voices
				// 	voice: voice
				// });

				// const blobUrl = URL.createObjectURL(await rawAudio.toBlob());
				// const audio = new Audio(blobUrl);

				// audio.play();
			}
		}
	};
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		saveSettings({
			audio: {
				stt: {
					engine: STTEngine !== '' ? STTEngine : undefined
				},
				tts: {
					engine: TTSEngine !== '' ? TTSEngine : undefined,
					engineConfig: TTSEngineConfig,
					playbackRate: playbackRate,
					voice: voice !== '' ? voice : undefined,
					defaultVoice: $config?.audio?.tts?.voice ?? '',
					nonLocalVoices: $config.audio.tts.engine === '' ? nonLocalVoices : undefined
				}
			}
		});
		dispatch('save');
	}}
>
	<div class=" space-y-3 overflow-y-scroll max-h-[28rem] lg:max-h-full">
		<div>
			<div class=" mb-1 text-sm font-medium">{$i18n.t('STT Settings')}</div>

			{#if $config.audio.stt.engine !== 'web'}
				<div class="py-0.5">
					<LabelBase label={$i18n.t('Speech-to-Text Engine')} size="md">
						<svelte:fragment slot="right">
							<div class="min-w-[12rem]">
								<Selector
									value={STTEngine}
									items={sttEngineItems}
									size="sm"
									on:change={(e) => {
										STTEngine = e.detail.value;
									}}
								/>
							</div>
						</svelte:fragment>
					</LabelBase>
				</div>
			{/if}

			<div class="py-0.5">
				<LabelBase
					label={$i18n.t('Instant Auto-Send After Voice Transcription')}
					size="md"
				>
					<svelte:fragment slot="right">
						<Switch
							bind:state={speechAutoSend}
							on:change={(e) => handleSpeechAutoSendChange(e.detail)}
						/>
					</svelte:fragment>
				</LabelBase>
			</div>
		</div>

		<div>
			<div class=" mb-1 text-sm font-medium">{$i18n.t('TTS Settings')}</div>

			<div class="py-0.5">
				<LabelBase label={$i18n.t('Text-to-Speech Engine')} size="md">
					<svelte:fragment slot="right">
						<div class="min-w-[12rem]">
							<Selector
								value={TTSEngine}
								items={ttsEngineItems}
								size="sm"
								on:change={(e) => {
									TTSEngine = e.detail.value;
								}}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			</div>

			{#if TTSEngine === 'browser-kokoro'}
				<div class="py-0.5">
					<LabelBase label={$i18n.t('Kokoro.js Dtype')} size="md">
						<svelte:fragment slot="right">
							<div class="min-w-[12rem]">
								<Selector
									value={TTSEngineConfig.dtype ?? ''}
									items={kokoroDtypeItems}
									placeholder={$i18n.t('Select dtype')}
									size="sm"
									on:change={(e) => {
										TTSEngineConfig = { ...TTSEngineConfig, dtype: e.detail.value };
									}}
								/>
							</div>
						</svelte:fragment>
					</LabelBase>
				</div>
			{/if}

			<div class="py-0.5">
				<LabelBase label={$i18n.t('Speech Playback Speed')} size="md">
					<svelte:fragment slot="right">
						<div class="min-w-[12rem]">
							<Selector
								value={String(playbackRate)}
								items={playbackRateItems}
								size="sm"
								searchEnabled={false}
								on:change={(e) => handlePlaybackRateChange(e.detail.value)}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			</div>

			<div class="py-0.5">
				<LabelBase label={$i18n.t('Auto-playback response')} size="md">
					<svelte:fragment slot="right">
						<Switch
							bind:state={responseAutoPlayback}
							on:change={(e) => handleResponseAutoPlaybackChange(e.detail)}
						/>
					</svelte:fragment>
				</LabelBase>
			</div>
		</div>

		<hr class=" border-gray-100 dark:border-gray-850" />

		{#if TTSEngine === 'browser-kokoro'}
			{#if TTSModel}
				<div>
					<div class=" mb-2.5 text-sm font-medium">{$i18n.t('Set Voice')}</div>
					<div class="flex w-full">
						<div class="flex-1">
							<input
								list="voice-list"
								class="w-full text-sm bg-white dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								bind:value={voice}
								placeholder="Select a voice"
							/>

							<datalist id="voice-list">
								{#each voices as voice}
									<option value={voice.id}>{voice.name}</option>
								{/each}
							</datalist>
						</div>
					</div>
				</div>
			{:else}
				<div>
					<div class=" mb-2.5 text-sm font-medium flex gap-2 items-center">
						<Spinner className="size-4" />

						<div class=" text-sm font-medium shimmer">
							{$i18n.t('Loading Kokoro.js...')}
							{TTSModelProgress && TTSModelProgress.status === 'progress'
								? `(${Math.round(TTSModelProgress.progress * 10) / 10}%)`
								: ''}
						</div>
					</div>

					<div class="text-xs text-gray-500">
						{$i18n.t('Please do not close the settings page while loading the model.')}
					</div>
				</div>
			{/if}
		{:else if $config.audio.tts.engine === ''}
			<div>
				<div class=" mb-2.5 text-sm font-medium">{$i18n.t('Set Voice')}</div>
				<Selector
					value={voice}
					items={voiceItems}
					size="sm"
					on:change={(e) => {
						voice = e.detail.value;
					}}
				/>
				<div class="mt-1.5">
					<LabelBase label={$i18n.t('Allow non-local voices')} size="md">
						<svelte:fragment slot="right">
							<Switch bind:state={nonLocalVoices} />
						</svelte:fragment>
					</LabelBase>
				</div>
			</div>
		{:else if $config.audio.tts.engine !== ''}
			<div>
				<div class=" mb-2.5 text-sm font-medium">{$i18n.t('Set Voice')}</div>
				<div class="flex w-full">
					<div class="flex-1">
						<input
							list="voice-list"
							class="w-full text-sm bg-white dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={voice}
							placeholder="Select a voice"
						/>

						<datalist id="voice-list">
							{#each voices as voice}
								<option value={voice.id}>{voice.name}</option>
							{/each}
						</datalist>
					</div>
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
