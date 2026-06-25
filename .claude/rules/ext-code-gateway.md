---
paths:
  - "backend/open_webui/routers/code_gateway.py"
---

# Code Gateway 규칙

## 개요
AI 코딩 도구(Cursor, GitHub Copilot 등)용 LLM API 프록시 게이트웨이.
여러 프로바이더를 통합 관리하며, 가드레일/사용량 추적/레이트 리밋 적용.

## 백엔드 라우터 (`/api/v1/code-gateway`)
| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/config` | admin (read) | 게이트웨이 설정 조회 |
| POST | `/config` | admin (write) | 설정 업데이트 |
| GET/POST | `/{provider_id}/{path:path}` | 인증됨 + features 권한 | 프로바이더 프록시 |

## 프록시 흐름
1. `_check_gateway_access()` — 기능 권한 체크
2. `_get_provider_config()` — 프로바이더 활성화/설정 검증
3. `_check_rate_limit()` — 인메모리 per-user 레이트 리밋 (60초 윈도우)
4. 모델 추출 → `_check_model_allowed()` + `_check_provider_model_allowed()`
5. `_apply_guardrails()` — PII/콘텐츠 필터 (guardrail_ids 설정 시)
6. 스트리밍 감지 → stream_options 주입 (OpenAI/Azure)
7. `_build_upstream_url()` + `_build_auth_headers()` — 프로바이더별 URL/인증
8. httpx 프록시 (스트리밍/논스트리밍)
9. `_record_usage()` — UsageMessageType.CODE_GATEWAY로 사용량 기록

## 지원 프로바이더
| 타입 | URL 패턴 | 인증 |
|------|----------|------|
| openai | `{api_url}/{path}` | Bearer token |
| anthropic | `{api_url}/{path}` | x-api-key |
| gemini | `{api_url}/{path}` | x-goog-api-key |
| azure_openai | `{api_url}/openai/{path}?api-version=...` | api-key |
| azure_ai_foundry | `{api_url}/{path}` | Bearer token |
| vertex_ai | `{base}/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:...` | GCP OAuth2 |

## Config (PersistentConfig)
```python
ENABLE_CODE_GATEWAY: bool
CODE_GATEWAY_PROVIDERS: dict[str, dict]  # provider_id → 설정
CODE_GATEWAY_ALLOWED_MODELS: list[str]   # 전역 허용 모델 (빈=전체)
CODE_GATEWAY_GUARDRAIL_IDS: list[str]    # 가드레일 ID
CODE_GATEWAY_RATE_LIMIT: int             # 요청/분 per user
```

## 프로바이더 설정 구조
```python
{
    "enable": bool,
    "type": "openai"|"anthropic"|"gemini"|"azure_openai"|"azure_ai_foundry"|"vertex_ai",
    "api_url": str,
    "api_key": str,
    "api_version": str,        # Azure only
    "model_ids": list[str],    # 프로바이더별 허용 모델
    "project_id": str,         # Vertex AI
    "service_account_key": str, # Vertex AI
    "location": str,           # Vertex AI (기본: us-central1)
    "use_global_gcp_key": bool  # Vertex AI 글로벌 키 폴백
}
```

## 사용량 추적
- `Usages.insert_new_usage()` — `message_type=CODE_GATEWAY`, `message_id="cg:..."`
- 스트리밍: SSE 청크 파싱으로 usage 누적
- 논스트리밍: 응답 body에서 usage 추출
- 프로바이더별 usage 필드 위치 다름 (usageMetadata, usage 등)

## 주의사항
- 프론트엔드 UI 없음 (백엔드 API only, 관리자 설정에서만 구성)
- 레이트 리밋: 인메모리 → 서버 재시작 시 리셋
- Vertex AI: GCP 서비스 계정 키 또는 글로벌 키 필요
