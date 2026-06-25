<script lang="ts">
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	// General nodes
	$: generalNodes = [
		{
			type: 'flowInput',
			label: $i18n.t('Start'),
			description: $i18n.t('Flow entry point'),
			icon: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
			color: 'green'
		},
		{
			type: 'flowOutput',
			label: $i18n.t('Output'),
			description: $i18n.t('Final response'),
			icon: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
			color: 'emerald'
		}
	];

	// AI nodes
	$: aiNodes = [
		{
			type: 'agent',
			label: $i18n.t('Agent'),
			description: $i18n.t('Execute agent task'),
			icon: 'M12 8V4H8M4 8h16v12H4zM2 14h2M20 14h2M15 13v2M9 13v2',
			color: 'blue'
		},
		{
			type: 'model',
			label: $i18n.t('Model'),
			description: $i18n.t('LLM call'),
			icon: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
			color: 'indigo'
		}
	];

	// Logic & Data nodes
	$: logicNodes = [
		{
			type: 'condition',
			label: $i18n.t('Condition'),
			description: $i18n.t('True / False branch'),
			icon: 'm16 3 4 4-4 4M20 7H4m4 14-4-4 4-4M4 17h16',
			color: 'amber'
		},
		{
			type: 'router',
			label: $i18n.t('Router'),
			description: $i18n.t('N-way routing'),
			icon: 'M13 5l7 7-7 7M5 5l7 7-7 7',
			color: 'violet'
		},
		{
			type: 'merge',
			label: $i18n.t('Merge'),
			description: $i18n.t('Combine outputs'),
			icon: 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10',
			color: 'teal'
		},
		{
			type: 'transform',
			label: $i18n.t('Transform'),
			description: $i18n.t('Data transformation'),
			icon: 'M12 3v12m-4-4 4 4 4-4M8 5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4',
			color: 'cyan'
		}
	];

	// Workspace resource nodes
	$: workspaceNodes = [
		{
			type: 'guardrail',
			label: $i18n.t('Guardrail'),
			description: $i18n.t('Safety filter'),
			icon: 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
			color: 'rose'
		},
		{
			type: 'glossary',
			label: $i18n.t('Glossary'),
			description: $i18n.t('Term lookup'),
			icon: 'M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253',
			color: 'purple'
		}
	];

	$: nodeCategories = [
		{ name: $i18n.t('General'), nodes: generalNodes },
		{ name: $i18n.t('AI'), nodes: aiNodes },
		{ name: $i18n.t('Logic & Data'), nodes: logicNodes },
		{ name: $i18n.t('Workspace'), nodes: workspaceNodes }
	];

	function handleDragStart(event: DragEvent, type: string) {
		event.dataTransfer?.setData('application/reactflow', type);
		event.dataTransfer!.effectAllowed = 'move';
	}

	function getColorClasses(color: string) {
		const colors: Record<string, string> = {
			green: 'bg-green-100 dark:bg-green-900/30 border-green-300 dark:border-green-700 hover:border-green-500',
			red: 'bg-red-100 dark:bg-red-900/30 border-red-300 dark:border-red-700 hover:border-red-500',
			blue: 'bg-blue-100 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700 hover:border-blue-500',
			purple: 'bg-purple-100 dark:bg-purple-900/30 border-purple-300 dark:border-purple-700 hover:border-purple-500',
			amber: 'bg-amber-100 dark:bg-amber-900/30 border-amber-300 dark:border-amber-700 hover:border-amber-500',
			cyan: 'bg-cyan-100 dark:bg-cyan-900/30 border-cyan-300 dark:border-cyan-700 hover:border-cyan-500',
			orange: 'bg-orange-100 dark:bg-orange-900/30 border-orange-300 dark:border-orange-700 hover:border-orange-500',
			pink: 'bg-pink-100 dark:bg-pink-900/30 border-pink-300 dark:border-pink-700 hover:border-pink-500',
			yellow: 'bg-yellow-100 dark:bg-yellow-900/30 border-yellow-300 dark:border-yellow-700 hover:border-yellow-500',
			violet: 'bg-violet-100 dark:bg-violet-900/30 border-violet-300 dark:border-violet-700 hover:border-violet-500',
			lime: 'bg-lime-100 dark:bg-lime-900/30 border-lime-300 dark:border-lime-700 hover:border-lime-500',
			indigo: 'bg-indigo-100 dark:bg-indigo-900/30 border-indigo-300 dark:border-indigo-700 hover:border-indigo-500',
			teal: 'bg-teal-100 dark:bg-teal-900/30 border-teal-300 dark:border-teal-700 hover:border-teal-500',
			fuchsia: 'bg-fuchsia-100 dark:bg-fuchsia-900/30 border-fuchsia-300 dark:border-fuchsia-700 hover:border-fuchsia-500',
			rose: 'bg-rose-100 dark:bg-rose-900/30 border-rose-300 dark:border-rose-700 hover:border-rose-500',
			sky: 'bg-sky-100 dark:bg-sky-900/30 border-sky-300 dark:border-sky-700 hover:border-sky-500',
			emerald: 'bg-emerald-100 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-700 hover:border-emerald-500'
		};
		return colors[color] || colors.blue;
	}

	function getIconColorClasses(color: string) {
		const colors: Record<string, string> = {
			green: 'bg-green-500',
			red: 'bg-red-500',
			blue: 'bg-blue-500',
			purple: 'bg-purple-500',
			amber: 'bg-amber-500',
			cyan: 'bg-cyan-500',
			orange: 'bg-orange-500',
			pink: 'bg-pink-500',
			yellow: 'bg-yellow-500',
			violet: 'bg-violet-500',
			lime: 'bg-lime-500',
			indigo: 'bg-indigo-500',
			teal: 'bg-teal-500',
			fuchsia: 'bg-fuchsia-500',
			rose: 'bg-rose-500',
			sky: 'bg-sky-500',
			emerald: 'bg-emerald-500'
		};
		return colors[color] || colors.blue;
	}
</script>

<div class="p-4 h-full overflow-y-auto">
	<h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">
		{$i18n.t('Nodes')}
	</h3>
	<p class="text-xs text-gray-500 dark:text-gray-400 mb-4">
		{$i18n.t('Drag nodes to the canvas')}
	</p>

	{#each nodeCategories as category}
		<div class="mb-4">
			<h4 class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wider">
				{category.name}
			</h4>
			<div class="space-y-1.5">
				{#each category.nodes as node}
					<div
						class="palette-node p-2.5 rounded-lg border cursor-grab active:cursor-grabbing transition-all {getColorClasses(
							node.color
						)}"
						draggable="true"
						on:dragstart={(e) => handleDragStart(e, node.type)}
						role="button"
						tabindex="0"
					>
						<div class="flex items-center gap-2">
							<div class="w-6 h-6 rounded-full {getIconColorClasses(node.color)} flex items-center justify-center flex-shrink-0">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="w-3 h-3 text-white"
								>
									<path d={node.icon} />
								</svg>
							</div>
							<div class="flex-1 min-w-0">
								<div class="text-xs font-medium text-gray-800 dark:text-gray-200">
									{node.label}
								</div>
								<div class="text-[10px] text-gray-500 dark:text-gray-400 truncate">
									{node.description}
								</div>
							</div>
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/each}
</div>

<style>
	.palette-node {
		user-select: none;
	}
	.palette-node:hover {
		transform: translateX(2px);
	}
	.palette-node:active {
		transform: scale(0.98);
	}
</style>
