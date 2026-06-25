<script>
	import { page } from '$app/stores';
	import Evaluations from '$lib/components/admin/Evaluations.svelte';

	// URL 파라미터에서 초기값 읽기
	$: initialTab = $page.url.searchParams.get('tab') || '';
	$: initialChatId = $page.url.searchParams.get('chat_id') || '';
	$: initialMessageId = $page.url.searchParams.get('message_id') || '';
</script>

<Evaluations {initialTab} {initialChatId} {initialMessageId} />
