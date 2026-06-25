/**
 * 메뉴 숨김 설정 (간단 버전)
 *
 * 기본: 모든 메뉴가 보임
 * 숨기고 싶은 것만 여기에 추가
 */

// ============================================================================
// 개발 호스트 판단
// ============================================================================
// 두 가지 기준이 있음:
//   - isDevHost(): 환경변수(VITE_SHOW_DEV_FEATURES) + hostname 둘 다 만족해야 true (AND)
//     → /admin/developer 같이 완전히 내부용 메뉴에 사용
//   - isDevHostname(): hostname만 검사 (env 무관)
//     → 플로우/지식 그래프처럼 개발 호스트에서는 항상 미리보기로 노출할 메뉴에 사용
// 프로덕션 호스트에서는 둘 다 false 이므로 실수 노출이 차단됨.
const DEV_HOSTNAMES = ['localhost', '127.0.0.1', 'cloosphere.azurewebsites.net'];

export function isDevHostname(): boolean {
	if (typeof window === 'undefined') return false;
	return DEV_HOSTNAMES.includes(window.location.hostname);
}

export function isDevHost(): boolean {
	if (import.meta.env.VITE_SHOW_DEV_FEATURES !== 'true') return false;
	return isDevHostname();
}

// ============================================================================
// 숨길 메뉴 ID 목록
// ============================================================================
export const hiddenMenus: string[] = [
	'functions',  // /admin/functions - Functions 기능 임시 비활성화

	// === Admin 메뉴 ===
	// 'users',        // /admin - 사용자 관리
	// 'evaluations',  // /admin/evaluations - 평가
	// 'settings',     // /admin/settings - 설정
	// 'monitoring',   // /admin/monitoring - 모니터링
	// 'developer',    // /admin/developer - 개발자 모드

	// === Workspace 메뉴 ===
	// 'agents',       // /workspace/agents - 에이전트
	// 'flows',        // /workspace/flows - 플로우
	// 'knowledge',    // /workspace/knowledge - 지식베이스
	// 'database',     // /workspace/database - 데이터베이스
	// 'glossary',     // /workspace/glossary - 용어집
	// 'guardrails',   // /workspace/guardrails - 가드레일
	// 'prompts',      // /workspace/prompts - 프롬프트
	// 'tools',        // /workspace/tools - 도구

	// === Settings 하위 탭 ===
	// 'general',       // 일반
	// 'connections',   // 연결
	// 'models',        // 모델
	// 'documents',     // 문서
	// 'search-engine', // 검색 엔진
	// 'web',           // 웹 검색
	// 'code-execution',// 코드 실행
	// 'interface',     // 인터페이스
	// 'audio',         // 오디오
	// 'images',        // 이미지
	// 'storage',       // 스토리지
	// 'pipelines',     // 파이프라인
	// 'notifications', // 알림
	// 'db',            // 데이터베이스

	// === Monitoring 하위 탭 ===
	// 'audit-logs',    // 감사 로그
	// 'guardrail-logs', // 가드레일 로그
	// 'conversation-logs', // 대화 로그
	// 'usage',         // 사용량

	// === Evaluations 하위 탭 ===
	// 'leaderboard',   // 리더보드
	// 'feedbacks',     // 피드백
	// 'auto',          // 자동 평가
];

// ============================================================================
// 개발 모드에서만 보이는 메뉴 ID 목록
// ============================================================================
// devOnlyMenus: isDevHost() (env + hostname AND) 를 충족해야 노출
// devHostOnlyMenus: isDevHostname() (hostname 만) 으로 노출 — 개발 호스트에서 항상 미리보기
export const devOnlyMenus: string[] = [
	// === Admin 메뉴 ===
	'developer',    // /admin/developer - 개발자 모드

	// === Workspace 메뉴 ===
	'marketplace',  // /workspace/marketplace - 마켓플레이스 (개발중, 로컬 전용 — 개발자 모드와 동일 게이팅)

	// === Settings 하위 탭 ===
	// 'pipelines',    // 파이프라인 (개발중)
];

export const devHostOnlyMenus: string[] = [
	// === Workspace 메뉴 ===
	'flows',          // /workspace/flows - 플로우 (미리보기)
	'knowledge-graph', // /workspace/knowledge-graph - 지식 그래프 (미리보기)
];

// ============================================================================
// 헬퍼 함수
// ============================================================================

/**
 * 메뉴가 보여야 하는지 확인
 */
export function isMenuVisible(id: string): boolean {
	// 숨김 목록에 있으면 안 보임
	if (hiddenMenus.includes(id)) return false;
	// devOnly 목록: env + hostname 둘 다 필요
	if (devOnlyMenus.includes(id) && !isDevHost()) return false;
	// devHostOnly 목록: hostname 만 맞아도 노출 (env 불필요)
	if (devHostOnlyMenus.includes(id) && !isDevHostname()) return false;
	return true;
}
