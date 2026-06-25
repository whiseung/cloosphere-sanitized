<script lang="ts">
	import { getBackendConfig } from '$lib/apis';
	import { setDefaultPromptSuggestions } from '$lib/apis/configs';
	import { config, models, settings, user } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import { updateUserInfo } from '$lib/apis/users';
	import { getUserPosition } from '$lib/utils';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	let backgroundImageUrl = null;
	let inputFiles = null;
	let filesInputElement;

	// Addons
	let titleAutoGenerate = true;
	let autoTags = true;

	let responseAutoCopy = false;
	let widescreenMode = false;
	let splitLargeChunks = false;
	let scrollOnBranchChange = true;
	let userLocation = false;

	// Interface
	let defaultModelId = '';
	let showUsername = false;
	let notificationSound = true;

	let detectArtifacts = true;

	let richTextInput = true;
	let promptAutocomplete = false;

	let largeTextAsFile = false;

	let chatBubble = true;
	let chatDirection: 'LTR' | 'RTL' | 'auto' = 'auto';
	let ctrlEnterToSend = false;
	let copyFormatted = false;

	let collapseCodeBlocks = false;
	let expandDetails = false;

	let imageCompression = false;
	let imageCompressionSize = {
		width: '',
		height: ''
	};

	// Admin - Show Update Available Toast
	let showUpdateToast = true;
	let showChangelog = true;

	let showEmojiInCall = false;
	let voiceInterruption = false;
	let hapticFeedback = false;

	let webSearch = null;

	let iframeSandboxAllowSameOrigin = false;
	let iframeSandboxAllowForms = false;

	const toggleExpandDetails = () => {
		expandDetails = !expandDetails;
		saveSettings({ expandDetails });
	};

	const toggleCollapseCodeBlocks = () => {
		collapseCodeBlocks = !collapseCodeBlocks;
		saveSettings({ collapseCodeBlocks });
	};

	const toggleSplitLargeChunks = async () => {
		splitLargeChunks = !splitLargeChunks;
		saveSettings({ splitLargeChunks: splitLargeChunks });
	};

	const togglePromptAutocomplete = async () => {
		promptAutocomplete = !promptAutocomplete;
		saveSettings({ promptAutocomplete: promptAutocomplete });
	};

	const togglesScrollOnBranchChange = async () => {
		scrollOnBranchChange = !scrollOnBranchChange;
		saveSettings({ scrollOnBranchChange: scrollOnBranchChange });
	};

	const toggleWidescreenMode = async () => {
		widescreenMode = !widescreenMode;
		saveSettings({ widescreenMode: widescreenMode });
	};

	const toggleChatBubble = async () => {
		chatBubble = !chatBubble;
		saveSettings({ chatBubble: chatBubble });
	};

	const toggleShowUpdateToast = async () => {
		showUpdateToast = !showUpdateToast;
		saveSettings({ showUpdateToast: showUpdateToast });
	};

	const toggleNotificationSound = async () => {
		notificationSound = !notificationSound;
		saveSettings({ notificationSound: notificationSound });
	};

	const toggleShowChangelog = async () => {
		showChangelog = !showChangelog;
		saveSettings({ showChangelog: showChangelog });
	};

	const toggleShowUsername = async () => {
		showUsername = !showUsername;
		saveSettings({ showUsername: showUsername });
	};

	const toggleEmojiInCall = async () => {
		showEmojiInCall = !showEmojiInCall;
		saveSettings({ showEmojiInCall: showEmojiInCall });
	};

	const toggleVoiceInterruption = async () => {
		voiceInterruption = !voiceInterruption;
		saveSettings({ voiceInterruption: voiceInterruption });
	};

	const toggleImageCompression = async () => {
		imageCompression = !imageCompression;
		saveSettings({ imageCompression });
	};

	const toggleHapticFeedback = async () => {
		hapticFeedback = !hapticFeedback;
		saveSettings({ hapticFeedback: hapticFeedback });
	};

	const toggleUserLocation = async () => {
		userLocation = !userLocation;

		if (userLocation) {
			const position = await getUserPosition().catch((error) => {
				toast.error(error.message);
				return null;
			});

			if (position) {
				await updateUserInfo(localStorage.token, { location: position });
				toast.success($i18n.t('User location successfully retrieved.'));
			} else {
				userLocation = false;
			}
		}

		saveSettings({ userLocation });
	};

	const toggleTitleAutoGenerate = async () => {
		titleAutoGenerate = !titleAutoGenerate;
		saveSettings({
			title: {
				...$settings.title,
				auto: titleAutoGenerate
			}
		});
	};

	const toggleAutoTags = async () => {
		autoTags = !autoTags;
		saveSettings({ autoTags });
	};

	const toggleDetectArtifacts = async () => {
		detectArtifacts = !detectArtifacts;
		saveSettings({ detectArtifacts });
	};

	const toggleRichTextInput = async () => {
		richTextInput = !richTextInput;
		saveSettings({ richTextInput });
	};

	const toggleLargeTextAsFile = async () => {
		largeTextAsFile = !largeTextAsFile;
		saveSettings({ largeTextAsFile });
	};

	const toggleResponseAutoCopy = async () => {
		const permission = await navigator.clipboard
			.readText()
			.then(() => {
				return 'granted';
			})
			.catch(() => {
				return '';
			});

		console.log(permission);

		if (permission === 'granted') {
			responseAutoCopy = !responseAutoCopy;
			saveSettings({ responseAutoCopy: responseAutoCopy });
		} else {
			toast.error(
				$i18n.t(
					'Clipboard write permission denied. Please check your browser settings to grant the necessary access.'
				)
			);
		}
	};

	const toggleCopyFormatted = async () => {
		copyFormatted = !copyFormatted;
		saveSettings({ copyFormatted });
	};

	const toggleChangeChatDirection = async () => {
		if (chatDirection === 'auto') {
			chatDirection = 'LTR';
		} else if (chatDirection === 'LTR') {
			chatDirection = 'RTL';
		} else if (chatDirection === 'RTL') {
			chatDirection = 'auto';
		}
		saveSettings({ chatDirection });
	};

	const togglectrlEnterToSend = async () => {
		ctrlEnterToSend = !ctrlEnterToSend;
		saveSettings({ ctrlEnterToSend });
	};

	const updateInterfaceHandler = async () => {
		saveSettings({
			models: [defaultModelId],
			imageCompressionSize: imageCompressionSize
		});
	};

	const toggleWebSearch = async () => {
		webSearch = webSearch === null ? 'always' : null;
		saveSettings({ webSearch: webSearch });
	};

	const toggleIframeSandboxAllowSameOrigin = async () => {
		iframeSandboxAllowSameOrigin = !iframeSandboxAllowSameOrigin;
		saveSettings({ iframeSandboxAllowSameOrigin });
	};

	const toggleIframeSandboxAllowForms = async () => {
		iframeSandboxAllowForms = !iframeSandboxAllowForms;
		saveSettings({ iframeSandboxAllowForms });
	};

	onMount(async () => {
		titleAutoGenerate = $settings?.title?.auto ?? true;
		autoTags = $settings.autoTags ?? true;

		detectArtifacts = $settings.detectArtifacts ?? true;
		responseAutoCopy = $settings.responseAutoCopy ?? false;

		showUsername = $settings.showUsername ?? false;
		showUpdateToast = $settings.showUpdateToast ?? true;
		showChangelog = $settings.showChangelog ?? true;

		showEmojiInCall = $settings.showEmojiInCall ?? false;
		voiceInterruption = $settings.voiceInterruption ?? false;

		richTextInput = $settings.richTextInput ?? true;
		promptAutocomplete = $settings.promptAutocomplete ?? false;
		largeTextAsFile = $settings.largeTextAsFile ?? false;
		copyFormatted = $settings.copyFormatted ?? false;

		collapseCodeBlocks = $settings.collapseCodeBlocks ?? false;
		expandDetails = $settings.expandDetails ?? false;

		chatBubble = $settings.chatBubble ?? true;
		widescreenMode = $settings.widescreenMode ?? false;
		splitLargeChunks = $settings.splitLargeChunks ?? false;
		scrollOnBranchChange = $settings.scrollOnBranchChange ?? true;
		chatDirection = $settings.chatDirection ?? 'auto';
		userLocation = $settings.userLocation ?? false;

		notificationSound = $settings.notificationSound ?? true;

		hapticFeedback = $settings.hapticFeedback ?? false;
		ctrlEnterToSend = $settings.ctrlEnterToSend ?? false;

		imageCompression = $settings.imageCompression ?? false;
		imageCompressionSize = $settings.imageCompressionSize ?? { width: '', height: '' };

		defaultModelId = $settings?.models?.at(0) ?? '';
		if ($config?.default_models) {
			defaultModelId = $config.default_models.split(',')[0];
		}

		backgroundImageUrl = $settings.backgroundImageUrl ?? null;
		webSearch = $settings.webSearch ?? null;
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		updateInterfaceHandler();
		dispatch('save');
	}}
>
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

				backgroundImageUrl = originalImageUrl;
				saveSettings({ backgroundImageUrl });
			};

			if (
				inputFiles &&
				inputFiles.length > 0 &&
				['image/gif', 'image/webp', 'image/jpeg', 'image/png'].includes(inputFiles[0]['type'])
			) {
				reader.readAsDataURL(inputFiles[0]);
			} else {
				console.log(`Unsupported File Type '${inputFiles[0]['type']}'.`);
				inputFiles = null;
			}
		}}
	/>

	<div class=" space-y-3 overflow-y-scroll max-h-[28rem] lg:max-h-full">
		<div class="space-y-2">
			<div class=" mb-1.5 text-base font-semibold">{$i18n.t('UI')}</div>

			<LabelBase label={$i18n.t('Chat Bubble UI')} size="md">
				<svelte:fragment slot="right">
					<Switch state={chatBubble} on:change={() => toggleChatBubble()} />
				</svelte:fragment>
			</LabelBase>

			{#if !$settings.chatBubble}
				<LabelBase label={$i18n.t('Display the username instead of You in the Chat')} size="md">
				<svelte:fragment slot="right">
					<Switch state={showUsername} on:change={() => toggleShowUsername()} />
				</svelte:fragment>
			</LabelBase>
			{/if}

			<LabelBase label={$i18n.t('Widescreen Mode')} size="md">
				<svelte:fragment slot="right">
					<Switch state={widescreenMode} on:change={() => toggleWidescreenMode()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Notification Sound')} size="md">
				<svelte:fragment slot="right">
					<Switch state={notificationSound} on:change={() => toggleNotificationSound()} />
				</svelte:fragment>
			</LabelBase>

			{#if $user?.role === 'admin'}
				<LabelBase label={$i18n.t('Toast notifications for new updates')} size="md">
				<svelte:fragment slot="right">
					<Switch state={showUpdateToast} on:change={() => toggleShowUpdateToast()} />
				</svelte:fragment>
			</LabelBase>

				<LabelBase label={$i18n.t(`Show "What's New" modal on login`)} size="md">
				<svelte:fragment slot="right">
					<Switch state={showChangelog} on:change={() => toggleShowChangelog()} />
				</svelte:fragment>
			</LabelBase>
			{/if}

			<LabelBase label={$i18n.t('Chat direction')} size="md">
				<svelte:fragment slot="right">
					<div class="min-w-[9.25rem]">
						<Selector
							value={chatDirection}
							items={[
								{ value: 'auto', label: $i18n.t('Auto') },
								{ value: 'LTR', label: $i18n.t('LTR') },
								{ value: 'RTL', label: $i18n.t('RTL') }
							]}
							size="sm"
							searchEnabled={false}
							portal="body"
							contentClassName="z-[10000]"
							on:change={(e) => { chatDirection = e.detail.value; saveSettings({ chatDirection }); }}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<hr class="border-gray-50 dark:border-gray-850 my-3" />

			<div class=" mb-1.5 text-base font-semibold">{$i18n.t('Chat')}</div>

			<LabelBase label={$i18n.t('Title Auto-Generation')} size="md">
				<svelte:fragment slot="right">
					<Switch state={titleAutoGenerate} on:change={() => toggleTitleAutoGenerate()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Chat Tags Auto-Generation')} size="md">
				<svelte:fragment slot="right">
					<Switch state={autoTags} on:change={() => toggleAutoTags()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Detect Artifacts Automatically')} size="md">
				<svelte:fragment slot="right">
					<Switch state={detectArtifacts} on:change={() => toggleDetectArtifacts()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Auto-Copy Response to Clipboard')} size="md">
				<svelte:fragment slot="right">
					<Switch state={responseAutoCopy} on:change={() => toggleResponseAutoCopy()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Rich Text Input for Chat')} size="md">
				<svelte:fragment slot="right">
					<Switch state={richTextInput} on:change={() => toggleRichTextInput()} />
				</svelte:fragment>
			</LabelBase>

			{#if $config?.features?.enable_autocomplete_generation && richTextInput}
				<LabelBase label={$i18n.t('Prompt Autocompletion')} size="md">
				<svelte:fragment slot="right">
					<Switch state={promptAutocomplete} on:change={() => togglePromptAutocomplete()} />
				</svelte:fragment>
			</LabelBase>
			{/if}

			<LabelBase label={$i18n.t('Paste Large Text as File')} size="md">
				<svelte:fragment slot="right">
					<Switch state={largeTextAsFile} on:change={() => toggleLargeTextAsFile()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Copy Formatted Text')} size="md">
				<svelte:fragment slot="right">
					<Switch state={copyFormatted} on:change={() => toggleCopyFormatted()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Always Collapse Code Blocks')} size="md">
				<svelte:fragment slot="right">
					<Switch state={collapseCodeBlocks} on:change={() => toggleCollapseCodeBlocks()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Always Expand Details')} size="md">
				<svelte:fragment slot="right">
					<Switch state={expandDetails} on:change={() => toggleExpandDetails()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Chat Background Image')} size="md">
				<svelte:fragment slot="right">
					<Button
						kind="outlined"
						size="sm"
						className="min-w-[4.5rem] justify-center"
						on:click={() => {
							if (backgroundImageUrl !== null) {
								backgroundImageUrl = null;
								saveSettings({ backgroundImageUrl });
							} else {
								filesInputElement.click();
							}
						}}
					>{backgroundImageUrl !== null ? $i18n.t('Reset') : $i18n.t('Upload')}</Button>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Allow User Location')} size="md">
				<svelte:fragment slot="right">
					<Switch state={userLocation} on:change={() => toggleUserLocation()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={`${$i18n.t('Haptic Feedback')} (${$i18n.t('Android')})`} size="md">
				<svelte:fragment slot="right">
					<Switch state={hapticFeedback} on:change={() => toggleHapticFeedback()} />
				</svelte:fragment>
			</LabelBase>

			<!-- <LabelBase label={$i18n.t('Fluidly stream large external response chunks')} size="md">
				<svelte:fragment slot="right">
					<Switch state={splitLargeChunks} on:change={() => toggleSplitLargeChunks()} />
				</svelte:fragment>
			</LabelBase> -->

			<LabelBase label={$i18n.t('Scroll to bottom when switching between branches')} size="md">
				<svelte:fragment slot="right">
					<Switch state={scrollOnBranchChange} on:change={() => togglesScrollOnBranchChange()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('iframe Sandbox Allow Same Origin')} size="md">
				<svelte:fragment slot="right">
					<Switch state={iframeSandboxAllowSameOrigin} on:change={() => toggleIframeSandboxAllowSameOrigin()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('iframe Sandbox Allow Forms')} size="md">
				<svelte:fragment slot="right">
					<Switch state={iframeSandboxAllowForms} on:change={() => toggleIframeSandboxAllowForms()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Enter Key Behavior')} size="md">
				<svelte:fragment slot="right">
					<div class="flex items-center gap-1">
						<Button
							kind={!ctrlEnterToSend ? 'filled' : 'outlined'}
							size="sm"
							className="min-w-[4.5rem] justify-center"
							on:click={() => { if (ctrlEnterToSend) togglectrlEnterToSend(); }}
						>{$i18n.t('Enter')}</Button>
						<Button
							kind={ctrlEnterToSend ? 'filled' : 'outlined'}
							size="sm"
							className="min-w-[4.5rem] justify-center"
							on:click={() => { if (!ctrlEnterToSend) togglectrlEnterToSend(); }}
						>{$i18n.t('Ctrl+Enter')}</Button>
					</div>
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Web Search in Chat')} size="md">
				<svelte:fragment slot="right">
					<div class="flex items-center gap-1">
						<Button
							kind={webSearch === null ? 'filled' : 'outlined'}
							size="sm"
							className="min-w-[4.5rem] justify-center"
							on:click={() => { if (webSearch !== null) toggleWebSearch(); }}
						>{$i18n.t('Default')}</Button>
						<Button
							kind={webSearch === 'always' ? 'filled' : 'outlined'}
							size="sm"
							className="min-w-[4.5rem] justify-center"
							on:click={() => { if (webSearch === null) toggleWebSearch(); }}
						>{$i18n.t('Always')}</Button>
					</div>
				</svelte:fragment>
			</LabelBase>

			<hr class="border-gray-50 dark:border-gray-850 my-3" />

			<div class=" mb-1.5 text-base font-semibold">{$i18n.t('Voice')}</div>

			<LabelBase label={$i18n.t('Allow Voice Interruption in Call')} size="md">
				<svelte:fragment slot="right">
					<Switch state={voiceInterruption} on:change={() => toggleVoiceInterruption()} />
				</svelte:fragment>
			</LabelBase>

			<LabelBase label={$i18n.t('Display Emoji in Call')} size="md">
				<svelte:fragment slot="right">
					<Switch state={showEmojiInCall} on:change={() => toggleEmojiInCall()} />
				</svelte:fragment>
			</LabelBase>

			<hr class="border-gray-50 dark:border-gray-850 my-3" />

			<div class=" mb-1.5 text-base font-semibold">{$i18n.t('File')}</div>

			<LabelBase label={$i18n.t('Image Compression')} size="md">
				<svelte:fragment slot="right">
					<Switch state={imageCompression} on:change={() => toggleImageCompression()} />
				</svelte:fragment>
			</LabelBase>

			{#if imageCompression}
				<LabelBase label={$i18n.t('Image Max Compression Size')} size="md">
					<svelte:fragment slot="right">
						<div class="flex items-center gap-2">
							<div class="w-20">
								<Input
									type="number"
									bind:value={imageCompressionSize.width}
									placeholder={$i18n.t('Width')}
									size="sm"
								/>
							</div>
							<span class="text-xs text-[var(--cloo-text-muted)]">×</span>
							<div class="w-20">
								<Input
									type="number"
									bind:value={imageCompressionSize.height}
									placeholder={$i18n.t('Height')}
									size="sm"
								/>
							</div>
						</div>
					</svelte:fragment>
				</LabelBase>
			{/if}
		</div>
	</div>

	<div class="flex justify-end text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
