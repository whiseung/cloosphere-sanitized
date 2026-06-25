/**
 * Global AI generation task tracker.
 *
 * API 호출을 모듈 레벨에서 추적하여, 컴포넌트가 파괴되어도
 * 완료 시 toast 알림이 표시되도록 합니다.
 */
import { writable, get } from 'svelte/store';
import { toast } from 'svelte-sonner';

export type AITaskType = 'dashboard' | 'flow';
export type AITaskStatus = 'running' | 'completed' | 'failed';

export interface AITask {
	id: string;
	type: AITaskType;
	label: string;
	status: AITaskStatus;
	result?: any;
	error?: string;
}

export const aiTasks = writable<AITask[]>([]);

/**
 * AI 생성 작업을 글로벌로 추적합니다.
 *
 * promise가 resolve/reject되면 toast를 표시하고 task를 자동 정리합니다.
 * 컴포넌트가 파괴되어도 promise.then()은 모듈 스코프에서 실행됩니다.
 *
 * @returns taskId — 컴포넌트에서 결과를 확인할 때 사용
 */
export function trackAIGeneration(
	type: AITaskType,
	label: string,
	promise: Promise<any>,
	messages: { success: string; error: string }
): string {
	const id = crypto.randomUUID();

	aiTasks.update((tasks) => [
		...tasks,
		{ id, type, label, status: 'running' }
	]);

	promise
		.then((result) => {
			aiTasks.update((tasks) =>
				tasks.map((t) =>
					t.id === id
						? { ...t, status: 'completed' as const, result }
						: t
				)
			);
			toast.success(messages.success);

			// 자동 정리 (컴포넌트가 파괴되어 clearAITask를 못 부를 경우 대비)
			setTimeout(() => clearAITask(id), 5000);
		})
		.catch((err) => {
			aiTasks.update((tasks) =>
				tasks.map((t) =>
					t.id === id
						? { ...t, status: 'failed' as const, error: String(err?.detail || err) }
						: t
				)
			);
			toast.error(messages.error);
			setTimeout(() => clearAITask(id), 5000);
		});

	return id;
}

/** 완료/실패한 task를 정리합니다. */
export function clearAITask(id: string) {
	aiTasks.update((tasks) => tasks.filter((t) => t.id !== id));
}

/** 특정 타입의 running task가 있는지 확인합니다. */
export function hasRunningTask(type: AITaskType): boolean {
	return get(aiTasks).some((t) => t.type === type && t.status === 'running');
}
