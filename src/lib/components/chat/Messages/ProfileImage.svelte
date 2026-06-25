<script lang="ts">
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { brandingUrls } from '$lib/stores/branding';

	export let className = 'size-8';
	export let src = '';
	$: resolvedSrc = src || $brandingUrls.favicon;
</script>

<img
	crossorigin="anonymous"
	src={resolvedSrc === ''
		? $brandingUrls.favicon
		: resolvedSrc.startsWith(WEBUI_BASE_URL) ||
			  resolvedSrc.startsWith('https://www.gravatar.com/avatar/') ||
			  resolvedSrc.startsWith('data:') ||
			  resolvedSrc.startsWith('/')
			? resolvedSrc
			: `/user.png`}
	class=" {className} object-cover rounded-full -translate-y-[1px]"
	alt="profile"
	draggable="false"
/>
