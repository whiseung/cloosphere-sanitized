<script>
	import { onDestroy, onMount, tick, getContext, createEventDispatcher } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import Markdown from './Markdown.svelte';
	import GmailConfirmation from './GmailConfirmation.svelte';
	import CalendarConfirmation from './CalendarConfirmation.svelte';
	import DriveConfirmation from './DriveConfirmation.svelte';
	import { chatId, mobile, settings, showArtifacts, showControls, showOverview } from '$lib/stores';
	import FloatingButtons from '../ContentRenderer/FloatingButtons.svelte';
	import { createMessagesList } from '$lib/utils';

	export let id;
	export let content;
	export let history;
	export let model = null;
	export let sources = null;

	export let save = false;
	export let floatingButtons = true;

	export let onSourceClick = () => {};
	export let onTaskClick = () => {};

	export let onAddMessages = () => {};

	// ----- Gmail / Calendar / Drive HITL marker 검출 -----
	// backend 의 ``[gmail_confirmation_required]`` / ``[calendar_confirmation_required]``
	// / ``[drive_confirmation_required]`` + ```json {...} ``` 블록을 인식해
	// Gmail/Calendar/Drive Confirmation 컴포넌트로 렌더한다.
	// marker 가 없는 콘텐츠는 그대로 Markdown 으로.
	//
	// 한 응답 안에 여러 marker 가 있을 수 있으므로 ``segments`` 로 split:
	// [{ kind: 'markdown', text }, { kind: 'gmail-confirm', payload }, ...]
	const HITL_RE =
		/\[(gmail_confirmation_required|calendar_confirmation_required|drive_confirmation_required)\]\s*```json\s*([\s\S]*?)```/g;

	$: segments = parseSegments(content);

	function parseSegments(raw) {
		const out = [];
		if (!raw) return out;
		let lastIndex = 0;
		HITL_RE.lastIndex = 0;
		let m;
		while ((m = HITL_RE.exec(raw)) !== null) {
			const [full, markerKind, jsonStr] = m;
			if (m.index > lastIndex) {
				out.push({ kind: 'markdown', text: raw.slice(lastIndex, m.index) });
			}
			let payload = null;
			try {
				payload = JSON.parse(jsonStr.trim());
			} catch (e) {
				// JSON 파싱 실패 — fallback 으로 원본을 markdown 으로 노출.
				console.warn('HITL payload parse failed', e);
				out.push({ kind: 'markdown', text: full });
				lastIndex = m.index + full.length;
				continue;
			}
			const KIND_BY_MARKER = {
				gmail_confirmation_required: 'gmail-confirm',
				calendar_confirmation_required: 'calendar-confirm',
				drive_confirmation_required: 'drive-confirm'
			};
			out.push({
				kind: KIND_BY_MARKER[markerKind],
				payload,
				raw: full
			});
			lastIndex = m.index + full.length;
		}
		if (lastIndex < raw.length) {
			out.push({ kind: 'markdown', text: raw.slice(lastIndex) });
		}
		return out;
	}

	function handleHitlConfirmed(kind, seg, result) {
		// 성공(created/already_created/sent/already_sent)일 때만 마커를 완료 텍스트로 영속 치환.
		if (!result) return;
		const successStatuses = ['created', 'already_created', 'sent', 'already_sent'];
		if (!successStatuses.includes(result.status)) return;
		const d = seg.payload?.draft || {};
		const link = result.html_link || result.web_link || '';
		let label = '';
		if (kind === 'calendar-confirm') {
			const title = d.title || $i18n.t('Event');
			label = link
				? `✅ ${$i18n.t('Event registered')}: [${title}](${link})`
				: `✅ ${$i18n.t('Event registered')}: ${title}`;
		} else if (kind === 'gmail-confirm') {
			label = `✅ ${$i18n.t('Email sent')}`;
		} else if (kind === 'drive-confirm') {
			const name = d.name || $i18n.t('Document');
			label = link
				? `✅ ${$i18n.t('Document created')}: [${name}](${link})`
				: `✅ ${$i18n.t('Document created')}: ${name}`;
		}
		if (!label || !seg.raw) return;
		dispatch('update', { raw: seg.raw, oldContent: seg.raw, newContent: label });
	}

	let contentContainerElement;

	let floatingButtonsElement;

	const updateButtonPosition = (event) => {
		const buttonsContainerElement = document.getElementById(`floating-buttons-${id}`);
		if (
			!contentContainerElement?.contains(event.target) &&
			!buttonsContainerElement?.contains(event.target)
		) {
			closeFloatingButtons();
			return;
		}

		setTimeout(async () => {
			await tick();

			if (!contentContainerElement?.contains(event.target)) return;

			let selection = window.getSelection();

			if (selection.toString().trim().length > 0) {
				const range = selection.getRangeAt(0);
				const rect = range.getBoundingClientRect();

				const parentRect = contentContainerElement.getBoundingClientRect();

				// Adjust based on parent rect
				const top = rect.bottom - parentRect.top;
				const left = rect.left - parentRect.left;

				if (buttonsContainerElement) {
					buttonsContainerElement.style.display = 'block';

					// Calculate space available on the right
					const spaceOnRight = parentRect.width - left;
					let halfScreenWidth = $mobile ? window.innerWidth / 2 : window.innerWidth / 3;

					if (spaceOnRight < halfScreenWidth) {
						const right = parentRect.right - rect.right;
						buttonsContainerElement.style.right = `${right}px`;
						buttonsContainerElement.style.left = 'auto'; // Reset left
					} else {
						// Enough space, position using 'left'
						buttonsContainerElement.style.left = `${left}px`;
						buttonsContainerElement.style.right = 'auto'; // Reset right
					}
					buttonsContainerElement.style.top = `${top + 5}px`; // +5 to add some spacing
				}
			} else {
				closeFloatingButtons();
			}
		}, 0);
	};

	const closeFloatingButtons = () => {
		const buttonsContainerElement = document.getElementById(`floating-buttons-${id}`);
		if (buttonsContainerElement) {
			buttonsContainerElement.style.display = 'none';
		}

		if (floatingButtonsElement) {
			// check if closeHandler is defined

			if (typeof floatingButtonsElement?.closeHandler === 'function') {
				// call the closeHandler function
				floatingButtonsElement?.closeHandler();
			}
		}
	};

	const keydownHandler = (e) => {
		if (e.key === 'Escape') {
			closeFloatingButtons();
		}
	};

	onMount(() => {
		if (floatingButtons) {
			contentContainerElement?.addEventListener('mouseup', updateButtonPosition);
			document.addEventListener('mouseup', updateButtonPosition);
			document.addEventListener('keydown', keydownHandler);
		}
	});

	onDestroy(() => {
		if (floatingButtons) {
			contentContainerElement?.removeEventListener('mouseup', updateButtonPosition);
			document.removeEventListener('mouseup', updateButtonPosition);
			document.removeEventListener('keydown', keydownHandler);
		}
	});
</script>

<div bind:this={contentContainerElement}>
	{#each segments as seg, i (i)}
		{#if seg.kind === 'markdown'}
			<Markdown
				id={`${id}-md-${i}`}
				content={seg.text}
				{model}
				{save}
				sourceIds={(sources ?? []).reduce((acc, s) => {
					let ids = [];
					if (!Array.isArray(s?.document)) {
						return acc;
					}
					s.document.forEach((document, index) => {
						const metadata = s.metadata?.[index];
						const id = metadata?.source ?? 'N/A';

						if (metadata?.name) {
							ids.push(metadata.name);
							return ids;
						}

						if (id.startsWith('http://') || id.startsWith('https://')) {
							ids.push(id);
						} else {
							ids.push(s?.source?.name ?? id);
						}

						return ids;
					});

					acc = [...acc, ...ids];

					// remove duplicates
					return acc.filter((item, index) => acc.indexOf(item) === index);
				}, [])}
				{onSourceClick}
				{onTaskClick}
				on:update={(e) => {
					dispatch('update', e.detail);
				}}
				on:code={(e) => {
					const { lang, code } = e.detail;

					if (
						($settings?.detectArtifacts ?? true) &&
						(['html', 'svg'].includes(lang) || (lang === 'xml' && code.includes('svg'))) &&
						!$mobile &&
						$chatId
					) {
						showArtifacts.set(true);
						showControls.set(true);
					}
				}}
			/>
		{:else if seg.kind === 'gmail-confirm'}
			<GmailConfirmation
				payload={seg.payload}
				conversationId={$chatId}
				on:confirmed={(e) => handleHitlConfirmed('gmail-confirm', seg, e.detail)}
			/>
		{:else if seg.kind === 'calendar-confirm'}
			<CalendarConfirmation
				payload={seg.payload}
				conversationId={$chatId}
				on:confirmed={(e) => handleHitlConfirmed('calendar-confirm', seg, e.detail)}
			/>
		{:else if seg.kind === 'drive-confirm'}
			<DriveConfirmation
				payload={seg.payload}
				conversationId={$chatId}
				on:confirmed={(e) => handleHitlConfirmed('drive-confirm', seg, e.detail)}
			/>
		{/if}
	{/each}
</div>

{#if floatingButtons && model}
	<FloatingButtons
		bind:this={floatingButtonsElement}
		{id}
		model={model?.id}
		messages={createMessagesList(history, id)}
		onAdd={({ modelId, parentId, messages }) => {
			console.log(modelId, parentId, messages);
			onAddMessages({ modelId, parentId, messages });
			closeFloatingButtons();
		}}
	/>
{/if}
