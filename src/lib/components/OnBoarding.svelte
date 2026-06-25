<script lang="ts">
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { brandingUrls } from '$lib/stores/branding';
	import ArrowRightCircle from './icons/ArrowRightCircle.svelte';
	import { changeLanguage } from '$lib/i18n';

	export let show = true;
	export let getStartedHandler = () => {};

	let currentLang = localStorage.getItem('locale') || 'ko-KR';

	function setLang(lang: string) {
		currentLang = lang;
		localStorage.setItem('locale', lang);
		changeLanguage(lang);
	}

	let scrollEl: HTMLDivElement;
	let isLastSection = false;
	const SECTION_COUNT = 4;

	function scrollToNext() {
		if (!scrollEl) return;
		const sectionHeight = scrollEl.clientHeight;
		const currentIndex = Math.round(scrollEl.scrollTop / sectionHeight);
		const nextIndex = Math.min(currentIndex + 1, SECTION_COUNT - 1);
		scrollEl.scrollTo({ top: nextIndex * sectionHeight, behavior: 'smooth' });
	}

	function handleScroll() {
		if (!scrollEl) return;
		const sectionHeight = scrollEl.clientHeight;
		const currentIndex = Math.round(scrollEl.scrollTop / sectionHeight);
		isLastSection = currentIndex >= SECTION_COUNT - 1;
	}
</script>

{#if show}
	<div
		class="w-full bg-[#08080f] text-white overflow-y-auto h-screen max-h-[100dvh] scroll-container"
		bind:this={scrollEl}
		on:scroll={handleScroll}
	>
		<!-- Fixed bottom buttons -->
		<div class="fixed bottom-8 left-0 right-0 z-50 flex flex-col items-center gap-3 pointer-events-none">
			{#if !isLastSection}
				<button
					type="button"
					class="flex items-center justify-center size-10 rounded-full pointer-events-auto
						bg-white/10 hover:bg-white/20 border border-white/15 hover:border-white/25
						backdrop-blur-md shadow-lg shadow-black/20 transition-all"
					on:click={scrollToNext}
				>
					<svg class="size-5 text-white/70" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
					</svg>
				</button>
			{/if}
			<button
				type="button"
				class="flex items-center gap-2 px-7 py-3 text-sm font-medium rounded-full pointer-events-auto
					bg-white/10 hover:bg-white/20 border border-white/15 hover:border-white/25
					backdrop-blur-md shadow-lg shadow-black/20 transition-all"
				on:click={() => getStartedHandler()}
			>
				<span>{$i18n.t('Get started')}</span>
				<ArrowRightCircle className="size-4" />
			</button>
		</div>

		<!-- Section 0: Hero -->
		<section class="relative w-full min-h-screen flex flex-col overflow-hidden">
			<div
				class="absolute inset-0"
				style:background="radial-gradient(ellipse at 50% 40%, rgba(88, 28, 135, 0.4) 0%, rgba(30, 10, 60, 0.1) 50%, transparent 70%)"
			></div>

			<div class="relative z-10 flex-none pt-8 lg:pt-10 px-8 lg:px-12 flex items-center justify-between">
				<img
					src={$brandingUrls.splashDark}
					class="h-7 lg:h-8"
					alt="ClooSphere"
					on:error={(e) => { e.currentTarget.src = '/static/splash-dark.png'; }}
				/>
				<div class="flex items-center rounded-full border border-white/10 overflow-hidden">
					<button
						type="button"
						class="px-3 py-1.5 text-xs font-medium transition-all
							{currentLang === 'ko-KR' ? 'bg-white/15 text-white' : 'text-gray-500 hover:text-gray-300'}"
						on:click={() => setLang('ko-KR')}
					>
						한국어
					</button>
					<button
						type="button"
						class="px-3 py-1.5 text-xs font-medium transition-all
							{currentLang === 'en-US' ? 'bg-white/15 text-white' : 'text-gray-500 hover:text-gray-300'}"
						on:click={() => setLang('en-US')}
					>
						English
					</button>
				</div>
			</div>

			<div class="relative z-10 flex-1 flex items-center justify-center px-6 lg:px-8">
				<div class="w-full max-w-2xl mx-auto text-center">
					<div
						class="inline-block px-3 py-1 text-[11px] font-semibold tracking-[0.15em] uppercase rounded-full
							bg-purple-500/15 text-purple-300 border border-purple-500/20 mb-6"
					>
						Enterprise AI Platform
					</div>
					<h1 class="text-3xl sm:text-4xl lg:text-5xl font-bold leading-tight mb-6">
						{$i18n.t('Start your enterprise AI innovation with ClooSphere')}
					</h1>
					<p class="text-base lg:text-lg text-gray-400 leading-relaxed max-w-xl mx-auto">
						{$i18n.t('From AI chat to agents, flows, and evaluation. An enterprise AI platform with hallucination control, quality management, and security governance.')}
					</p>
				</div>
			</div>

			<div class="relative z-10 flex-none pb-10"></div>
		</section>

		<!-- Section 1: Core Features -->
		<section class="relative w-full min-h-screen flex items-center justify-center overflow-hidden">
			<div
				class="absolute inset-0"
				style:background="radial-gradient(ellipse at 30% 55%, rgba(109, 40, 217, 0.35) 0%, rgba(60, 20, 120, 0.1) 50%, transparent 65%)"
			></div>

			<div class="relative z-10 w-full max-w-3xl mx-auto text-center px-6 lg:px-8 py-16">
				<div
					class="inline-block px-3 py-1 text-[11px] font-semibold tracking-[0.15em] uppercase rounded-full
						bg-violet-500/15 text-violet-300 border border-violet-500/20 mb-6"
				>
					{$i18n.t('Core Features')}
				</div>
				<h2 class="text-3xl sm:text-4xl lg:text-5xl font-bold mb-3">
					{$i18n.t('AI Workspace')}
				</h2>
				<p class="text-base lg:text-lg text-gray-400 mb-10">
					{$i18n.t('All the tools you need, in one platform')}
				</p>
				<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5 lg:gap-3 max-w-2xl mx-auto">
					{#each [
						['\u{1F916}', 'Agents'],
						['\u{1F504}', 'Flows'],
						['\u{1F4DA}', 'Knowledge'],
						['\u{1F5C4}\u{FE0F}', 'Database'],
						['\u{1F4D6}', 'Glossary'],
						['\u{1F517}', 'Tools'],
						['\u{1F4AC}', 'AI Chat'],
						['\u{1F399}\u{FE0F}', 'Voice & Image'],
						['\u{270D}\u{FE0F}', 'Prompts'],
						['\u{1F4E2}', 'Channels'],
						['\u{23F0}', 'Scheduled Tasks'],
						['\u{1F4C1}', 'Projects']
					] as [emoji, label]}
						<span
							class="flex flex-col items-center justify-center gap-1.5 px-3 py-3.5 lg:py-4 text-sm lg:text-base
								rounded-xl bg-white/[0.05] border border-white/[0.08] text-gray-300"
						>
							<span class="text-xl lg:text-2xl">{emoji}</span>
							<span class="text-xs lg:text-sm">{$i18n.t(label)}</span>
						</span>
					{/each}
				</div>
			</div>
		</section>

		<!-- Section 2: AI Evaluation -->
		<section class="relative w-full min-h-screen flex items-center justify-center overflow-hidden">
			<div
				class="absolute inset-0"
				style:background="radial-gradient(ellipse at 70% 40%, rgba(5, 150, 105, 0.3) 0%, rgba(10, 60, 50, 0.1) 50%, transparent 65%)"
			></div>

			<div class="relative z-10 w-full max-w-3xl mx-auto text-center px-6 lg:px-8 py-16">
				<div
					class="inline-block px-3 py-1 text-[11px] font-semibold tracking-[0.15em] uppercase rounded-full
						bg-emerald-500/15 text-emerald-300 border border-emerald-500/20 mb-6"
				>
					{$i18n.t('AI Evaluation')}
				</div>
				<h2 class="text-3xl sm:text-4xl lg:text-5xl font-bold mb-10">
					{$i18n.t('Measure, track, and improve')}
				</h2>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto">
					{#each [
						['\u{1F4CA}', 'Usage Monitoring', 'Real-time metrics dashboard'],
						['\u{1F44D}', 'Feedback & Arena', 'Elo rating model comparison'],
						['\u{2705}', 'Auto Quality Evaluation', 'Automated quality scoring'],
						['\u{1F50D}', 'Execution Diagnostics', 'Full-path tracing and analysis']
					] as [emoji, title, desc]}
						<div
							class="flex items-center gap-4 p-5 rounded-2xl bg-white/[0.04] border border-white/[0.08] text-left"
						>
							<span class="text-2xl flex-none leading-none">{emoji}</span>
							<div>
								<div class="text-base font-medium text-gray-200">
									{$i18n.t(title)}
								</div>
								<div class="text-sm text-gray-500 mt-1">
									{$i18n.t(desc)}
								</div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		</section>

		<!-- Section 3: Governance -->
		<section class="relative w-full min-h-screen flex items-center justify-center overflow-hidden">
			<div
				class="absolute inset-0"
				style:background="radial-gradient(ellipse at 40% 55%, rgba(180, 83, 9, 0.3) 0%, rgba(80, 40, 10, 0.1) 50%, transparent 65%)"
			></div>

			<div class="relative z-10 w-full max-w-3xl mx-auto text-center px-6 lg:px-8 py-16">
				<div
					class="inline-block px-3 py-1 text-[11px] font-semibold tracking-[0.15em] uppercase rounded-full
						bg-amber-500/15 text-amber-300 border border-amber-500/20 mb-6"
				>
					{$i18n.t('Governance')}
				</div>
				<h2 class="text-3xl sm:text-4xl lg:text-5xl font-bold mb-10">
					{$i18n.t('Safe and transparent AI operations')}
				</h2>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto">
					{#each [
						['\u{1F6E1}\u{FE0F}', 'Guardrails', 'PII detection and dual protection'],
						['\u{2699}\u{FE0F}', 'Model Management', 'Centralized registration and deployment'],
						['\u{1F4CB}', 'Audit Logs', 'Full action tracking and compliance'],
						['\u{1F510}', 'Access Control', 'Four-level granular permissions']
					] as [emoji, title, desc]}
						<div
							class="flex items-center gap-4 p-5 rounded-2xl bg-white/[0.04] border border-white/[0.08] text-left"
						>
							<span class="text-2xl flex-none leading-none">{emoji}</span>
							<div>
								<div class="text-base font-medium text-gray-200">
									{$i18n.t(title)}
								</div>
								<div class="text-sm text-gray-500 mt-1">
									{$i18n.t(desc)}
								</div>
							</div>
						</div>
					{/each}
				</div>
			</div>
		</section>
	</div>
{/if}

<style>
	.scroll-container {
		scroll-snap-type: y mandatory;
		scrollbar-width: none;
	}

	.scroll-container::-webkit-scrollbar {
		display: none;
	}

	section {
		scroll-snap-align: start;
	}
</style>
