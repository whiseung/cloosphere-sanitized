// 백엔드 구조화 에러를 i18n 메시지로 포맷.
// 백엔드가 detail = { code, ...params, message } 형태로 보내주면 code 별 i18n 키 매핑.
// 일반 문자열/객체는 기존 동작 유지.

type I18n = { t: (key: string, opts?: Record<string, unknown>) => string };

export function formatBackendError(err: unknown, i18n: I18n): string {
	// detail 이 객체로 통째로 들어온 경우
	const detail =
		err && typeof err === 'object' && 'detail' in err && (err as any).detail !== undefined
			? (err as any).detail
			: err;

	// FastAPI 422 validation 에러: detail 이 [{ type, loc, msg, ... }] 배열.
	// 배열을 toast.error 등에 그대로 넘기면 svelte-sonner 가 컴포넌트로 마운트하려다 throw.
	if (Array.isArray(detail)) {
		return detail
			.map((d) => (d && typeof d === 'object' ? ((d as { msg?: string }).msg ?? '') : String(d)))
			.filter(Boolean)
			.join(', ');
	}

	if (detail && typeof detail === 'object' && 'code' in detail) {
		const d = detail as Record<string, any>;
		switch (d.code) {
			case 'USAGE_LIMIT_EXCEEDED':
				return i18n.t(
					"Daily token usage limit exceeded for model '{{model}}' ({{used}}/{{limit}} tokens, {{pct}}%). Source: {{source}}",
					{
						model: d.model_id ?? '',
						used: Number(d.daily_used ?? 0).toLocaleString(),
						limit: Number(d.daily_limit ?? 0).toLocaleString(),
						pct: d.pct ?? 0,
						source: d.source ?? ''
					}
				);
			default:
				return d.message ?? JSON.stringify(d);
		}
	}

	if (typeof detail === 'string') return detail;
	if (detail && typeof detail === 'object' && 'message' in detail) {
		return (detail as any).message;
	}
	return String(err);
}
