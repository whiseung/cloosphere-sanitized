<script lang="ts">
	import { onMount, getContext } from 'svelte';

	const i18n = getContext('i18n');

	export let avatarStream: MediaStream | null = null;
	export let avatarReady = false;

	let videoElement: HTMLVideoElement;

	$: if (videoElement && avatarStream) {
		videoElement.srcObject = avatarStream;
		videoElement.muted = false; // Use avatar audio for perfect lip-sync
		videoElement.play().catch((e) => {
			console.error('Failed to play avatar video:', e);
		});
	}
</script>

<div class="avatar-container">
	{#if avatarStream}
		<!-- Avatar video always shown once stream exists -->
		<video
			bind:this={videoElement}
			autoplay
			playsinline
			class="avatar-video"
		></video>
	{:else}
		<!-- Loading state / placeholder -->
		<div class="avatar-placeholder">
			<div class="avatar-loading">
				<div class="spinner"></div>
				{#if avatarReady}
					<p class="loading-text">{$i18n.t('avatar.connecting_stream')}</p>
					<p class="loading-subtext">{$i18n.t('avatar.please_wait')}</p>
				{:else}
					<p class="loading-text">{$i18n.t('avatar.initializing')}</p>
					<p class="loading-subtext">{$i18n.t('avatar.setup')}</p>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.avatar-container {
		width: 100%;
		height: 100%;
		position: relative;
		overflow: hidden; 
		background: #0f0f14; 
	}

	.avatar-video {
		width: 100%;
		height: 100%;
		object-fit: cover;   
		transform: none;    
	}

	.avatar-placeholder {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
	}

	.avatar-loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.5rem;
		color: #e0e0e0;
		padding: 2rem;
	}

	.loading-text {
		font-size: 1.1rem;
		font-weight: 600;
		opacity: 0.95;
		margin: 0;
		animation: pulse 2s ease-in-out infinite;
	}

	.loading-subtext {
		font-size: 0.85rem;
		opacity: 0.7;
		margin: 0;
		margin-top: -0.5rem;
	}

	.spinner {
		width: 48px;
		height: 48px;
		border: 4px solid rgba(255, 255, 255, 0.1);
		border-top-color: #667eea;
		border-radius: 50%;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	@keyframes pulse {
		0%, 100% {
			opacity: 0.6;
		}
		50% {
			opacity: 1;
		}
	}
</style>
