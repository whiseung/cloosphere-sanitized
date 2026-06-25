<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { getAudioPublicConfig, getAvatarToken } from '$lib/apis/audio';

	const dispatch = createEventDispatcher();

	export let sessionToken: string = '';

	let avatarSynthesizer: any = null;
	let peerConnection: RTCPeerConnection | null = null;
	let sdkLoaded = false;
	let isReady = false;
	let initError: string | null = null;
	
	// Export speak function for parent component
	export function speakText(text: string): Promise<void> {
		return new Promise((resolve, reject) => {
			if (!avatarSynthesizer || !isReady) {
				console.warn('[Avatar] Synthesizer not ready, cannot speak');
				reject(new Error('Avatar not ready'));
				return;
			}
			
			console.log('[Avatar] Speaking text:', text);
			avatarSynthesizer.speakTextAsync(text).then(
				(result: any) => {
					console.log('[Avatar] Speech finished:', result);
					resolve();
				},
				(error: any) => {
					console.error('[Avatar] Speech error:', error);
					reject(error);
				}
			);
		});
	}

	async function loadAzureSpeechSDK() {
		if ((window as any).SpeechSDK) {
			sdkLoaded = true;
			return;
		}

		return new Promise((resolve, reject) => {
			const script = document.createElement('script');
			script.src = 'https://aka.ms/csspeech/jsbrowserpackageraw';
			script.onload = () => {
				sdkLoaded = true;
				console.log('[Avatar] Azure Speech SDK loaded');
				resolve(true);
			};
			script.onerror = (e) => {
				console.error('[Avatar] Failed to load Azure Speech SDK:', e);
				reject(e);
			};
			document.head.appendChild(script);
		});
	}

	async function initializeAvatar() {
		try {
			console.log('[Avatar] Initializing...');

			// 1. Load SDK
			await loadAzureSpeechSDK();

		// 2. Get public config (avatar engine, voice, region, character, style)
		const config = await getAudioPublicConfig();
		if (!config || !config.tts) {
			console.error('[Avatar] Failed to get audio config');
			return;
		}

		const { 
			VOICE, 
			AZURE_AVATAR_ENGINE, 
			AZURE_AVATAR_REGION,
			AZURE_AVATAR_CHARACTER, 
			AZURE_AVATAR_STYLE 
		} = config.tts;

		// Skip if avatar engine is not set to Azure
		const avatarEngine = AZURE_AVATAR_ENGINE?.toLowerCase() || '';
		if (avatarEngine !== 'azure') {
			console.log('[Avatar] Skipping: Avatar engine is not Azure (engine:', avatarEngine, ')');
			return;
		}

		console.log('[Avatar] Config:', {
			engine: avatarEngine,
			voice: VOICE,
			region: AZURE_AVATAR_REGION,
			character: AZURE_AVATAR_CHARACTER,
			style: AZURE_AVATAR_STYLE
		});

			// 3. Get avatar token
			const tokenResponse = await getAvatarToken(sessionToken);
			if (!tokenResponse || !tokenResponse.token) {
				const error = 'Failed to get avatar token';
				console.error('[Avatar]', error);
				initError = error;
				dispatch('error', { error });
				return;
			}

			const { token, region } = tokenResponse;
			console.log('[Avatar] Token received, region:', region);

			// 4. Create Speech SDK config
			const SpeechSDK = (window as any).SpeechSDK;
			const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(token, region);
			speechConfig.speechSynthesisVoiceName = VOICE;

			// 5. Create Avatar Config
			const character = AZURE_AVATAR_CHARACTER || 'lisa';
			const style = AZURE_AVATAR_STYLE || 'casual-sitting';
			
			const avatarConfig = new SpeechSDK.AvatarConfig(character, style);
			console.log('[Avatar] Avatar config:', { character, style });

			// 6. Create PeerConnection
			peerConnection = new RTCPeerConnection({
				iceServers: [{ urls: ['stun:stun.l.google.com:19302'] }]
			});

			console.log('[Avatar] PeerConnection created');

			// 7. Setup stream receiver
			peerConnection.ontrack = (event) => {
				console.log('[Avatar] Track received:', event.track.kind);
				if (event.streams && event.streams[0]) {
					console.log('[Avatar] Stream received');
					dispatch('stream', { stream: event.streams[0] });
				}
			};

			// 8. Add recvonly transceiver (important for avatar)
			peerConnection.addTransceiver('video', { direction: 'recvonly' });
			peerConnection.addTransceiver('audio', { direction: 'recvonly' });

			// 9. Create Avatar Synthesizer
			avatarSynthesizer = new SpeechSDK.AvatarSynthesizer(speechConfig, avatarConfig);
			console.log('[Avatar] Synthesizer created');

			// 10. Start avatar
			console.log('[Avatar] Starting avatar...');
			avatarSynthesizer.startAvatarAsync(peerConnection).then(
				(r: any) => {
					console.log('[Avatar] Started successfully:', r);
					isReady = true;
					dispatch('ready');
				},
				(error: any) => {
					console.error('[Avatar] Start failed:', error);
					isReady = false;
				}
			);
		} catch (error) {
			console.error('[Avatar] Initialization error:', error);
		}
	}

	onMount(() => {
		initializeAvatar();

		return () => {
			// Cleanup
			if (avatarSynthesizer) {
				avatarSynthesizer.close();
			}
			if (peerConnection) {
				peerConnection.close();
			}
		};
	});
</script>
