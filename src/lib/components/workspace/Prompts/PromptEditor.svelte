<script lang="ts">
	import { onMount, tick, getContext } from 'svelte';

	import Textarea from '$lib/components/common/Textarea.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { toast } from 'svelte-sonner';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import AccessControl from '../common/AccessControl.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import WorkspaceDetailHeader from '../common/WorkspaceDetailHeader.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import { user } from '$lib/stores';
	import { goto } from '$app/navigation';
	import { getGroups } from '$lib/apis/groups';

	export let onSubmit: Function;
	export let edit = false;
	export let prompt = null;

	const i18n = getContext('i18n');

	let loading = false;
	let tagSelector: any;

	let title = '';
	let command = '';
	let content = '';

	let accessControl: any = {
		read: {
			group_ids: [],
			user_ids: [$user?.id]
		},
		write: {
			group_ids: [],
			user_ids: [$user?.id]
		}
	};

	let showAccessControlModal = false;
	let group_ids: string[] = [];

	$: isOwnerOrAdmin = $user?.role === 'admin' || prompt?.user_id === $user?.id;

	$: canWrite = $user?.role === 'admin' || (
		$user?.permissions?.workspace?.prompts === 'write' && (
			!edit
			|| prompt?.user_id === $user?.id
			|| accessControl?.write?.user_ids?.includes($user?.id)
			|| accessControl?.write?.group_ids?.some((gid: string) => group_ids.includes(gid))
		)
	);

	$: if (!edit) {
		command = title !== '' ? `${title.replace(/\s+/g, '-').toLowerCase()}` : '';
	}

	const submitHandler = async () => {
		loading = true;

		if (validateCommandString(command)) {
			// 태그 변경사항 커밋 (onSubmit이 페이지 이동할 수 있으므로 먼저 실행)
			if (tagSelector?.commitChanges) {
				try {
					await tagSelector.commitChanges();
				} catch (e) {
					console.error('Failed to commit tag changes:', e);
				}
			}

			await onSubmit({
				title,
				command,
				content,
				access_control: accessControl
			});
		} else {
			toast.error(
				$i18n.t('Only alphanumeric characters and hyphens are allowed in the command string.')
			);
		}

		loading = false;
	};

	const validateCommandString = (inputString) => {
		// Regular expression to match only alphanumeric characters and hyphen
		const regex = /^[a-zA-Z0-9-]+$/;

		// Test the input string against the regular expression
		return regex.test(inputString);
	};

	onMount(async () => {
		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		if (prompt) {
			title = prompt.title;
			await tick();

			command = prompt.command.at(0) === '/' ? prompt.command.slice(1) : prompt.command;
			content = prompt.content;

			accessControl = prompt?.access_control ?? null;
		}
	});
</script>

<AccessControlModal
	bind:show={showAccessControlModal}
	bind:accessControl
	accessRoles={['read', 'write']}
	allowPublic={$user?.permissions?.sharing?.public_prompts || $user?.role === 'admin'}
/>

<div class="flex flex-col w-full h-full translate-y-1">
	<form
		class="flex flex-col w-full mb-10"
		on:submit|preventDefault={() => {
			submitHandler();
		}}
	>
			<WorkspaceDetailHeader
				backHref="/workspace/prompts"
				badgeContent={$i18n.t('Prompt')}
				bind:name={title}
				namePlaceholder={$i18n.t('Title')}
				nameRequired
				showDescription={false}
				resourceType={edit && command ? 'prompt' : ''}
				resourceId={edit && command ? command : ''}
				bind:tagSelector
				showAccess={(!edit || isOwnerOrAdmin) && canWrite}
				canWrite={canWrite && !loading}
				saving={loading}
				saveType="submit"
				saveLabel={edit ? $i18n.t('Save & Update') : $i18n.t('Save & Create')}
				on:access={() => (showAccessControlModal = true)}
			>
				<svelte:fragment slot="actions-prefix">
					<slot name="header-actions" />
				</svelte:fragment>

				<svelte:fragment slot="below">
					<Tooltip
						content={`${$i18n.t('Only alphanumeric characters and hyphens are allowed')} - ${$i18n.t(
							'Activate this command by typing "/{{COMMAND}}" to chat input.',
							{ COMMAND: command }
						)}`}
						placement="bottom-start"
					>
						<div class="flex gap-0.5 items-center pl-10 pr-1">
							<div class="text-xs text-gray-500 dark:text-gray-400">/</div>
							<input
								class="w-full text-xs text-gray-500 dark:text-gray-400 bg-transparent outline-hidden"
								placeholder={$i18n.t('Command')}
								bind:value={command}
								required
								disabled={edit}
							/>
						</div>
					</Tooltip>
				</svelte:fragment>
			</WorkspaceDetailHeader>

		<div class="my-2">
			<div class="flex w-full justify-between">
				<div class=" self-center text-sm font-semibold">{$i18n.t('Prompt Content')}</div>
			</div>

			<div class="mt-2">
				<div>
					<Textarea
						className="text-sm w-full bg-transparent outline-hidden overflow-y-hidden resize-none"
						placeholder={$i18n.t('Write a summary in 50 words that summarizes [topic or keyword].')}
						bind:value={content}
						rows={6}
						required
					/>
				</div>

				<div class="text-xs text-gray-400 dark:text-gray-500">
					ⓘ {$i18n.t('Format your variables using brackets like this:')}&nbsp;<span
						class=" text-gray-600 dark:text-gray-300 font-medium"
						>{'{{'}{$i18n.t('variable')}{'}}'}</span
					>.
					{$i18n.t('Make sure to enclose them with')}
					<span class=" text-gray-600 dark:text-gray-300 font-medium">{'{{'}</span>
					{$i18n.t('and')}
					<span class=" text-gray-600 dark:text-gray-300 font-medium">{'}}'}</span>.
				</div>

				<div class="text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Utilize')}<span class=" text-gray-600 dark:text-gray-300 font-medium">
						{` {{CLIPBOARD}}`}</span
					>
					{$i18n.t('variable to have them replaced with clipboard content.')}
				</div>
			</div>
		</div>

		<div class="my-4 pb-20">
		</div>
	</form>
</div>
