# Guardrails (가드레일) 개요

`guardrails`는 모델 입출력에 대한 보안 필터링 및 콘텐츠 제어 시스템입니다. 규칙 기반 탐지(PII, 금지어, 정규식)와 LLM-as-a-Judge 방식을 모두 지원합니다.

## 주요 목적

- **PII(개인식별정보) 보호**: 이메일, 신용카드, IP 주소 등 민감 정보 탐지 및 처리
- **콘텐츠 필터링**: 금지어 및 사용자 정의 패턴 탐지
- **LLM 기반 검증**: AI 모델을 활용한 콘텐츠 적합성 검증
- **유연한 처리 전략**: 차단(block), 삭제(redact), 마스킹(mask), 해시(hash) 지원

## 주요 구성 요소

### 백엔드

- **`models/guardrails.py`**: SQLAlchemy DB 모델 및 Pydantic 스키마
- **`routers/guardrails.py`**: REST API 엔드포인트
- **`utils/guardrails.py`**: 가드레일 처리 엔진

### 프론트엔드

- **워크스페이스 관리**: `components/workspace/Guardrails/` - 생성, 편집, 목록
- **에이전트 연동**: `components/workspace/Agents/Guardrails/` - 에이전트에 가드레일 할당

## 핵심 기능

| 기능 | 설명 |
|------|------|
| PII 탐지 | 이메일, 신용카드, IP, MAC, URL, API 키 자동 탐지 |
| 처리 전략 | block, redact, mask, hash 중 선택 |
| 커스텀 패턴 | 정규식 기반 사용자 정의 패턴 |
| 금지어 | 특정 단어/문구 차단 |
| LLM Judge | AI 모델을 활용한 콘텐츠 심사 |
| 적용 범위 | 입력/출력 각각 개별 설정 가능 |

## 기술 스택

- **Framework**: FastAPI (Python), SvelteKit (Frontend)
- **Database**: SQLAlchemy (PostgreSQL/SQLite)
- **LLM**: Azure OpenAI / OpenAI (LLM Judge용)
- **패턴 매칭**: Python `re` 모듈
