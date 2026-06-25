---
name: hol
description: Cloosphere HOL(Hands-On Lab) 콘텐츠 작성. 관리자/개발자 실습 문서를 현재 시스템 코드 기반으로 생성 및 업데이트.
---

# HOL 콘텐츠 작성 워크플로우

Cloosphere의 실제 코드와 기능을 참조하여 `/cloosphere-docs/` 리포지토리에 HOL 문서를 작성합니다.

---

## 프로젝트 구조

```
/cloosphere-docs/
├── mkdocs.yml                    # MkDocs Material 설정
├── docs/
│   ├── index.md                  # 홈
│   ├── admin-hol/                # 관리자 실습 (Lab 1~7)
│   │   ├── index.md
│   │   ├── lab01-connections.md      # LLM 연결
│   │   ├── lab02-embedding-search.md # 임베딩/검색엔진
│   │   ├── lab03-users-groups.md     # 사용자/그룹
│   │   ├── lab04-organizations.md    # 조직
│   │   ├── lab05-general-branding.md # 일반/브랜딩
│   │   ├── lab06-guardrails.md       # 가드레일
│   │   └── lab07-monitoring.md       # 모니터링
│   └── developer-hol/            # 개발자 실습 (Lab 1~8)
│       ├── index.md
│       ├── lab01-agent-basic.md      # 에이전트 생성
│       ├── lab02-knowledge-base.md   # 지식 기반
│       ├── lab03-dbsphere.md         # DbSphere
│       ├── lab04-unified-agent.md    # 통합 에이전트
│       ├── lab05-glossary.md         # 용어집
│       ├── lab06-agent-flow.md       # Agent Flow
│       ├── lab07-projects.md         # 프로젝트
│       └── lab08-tool-connections.md # 외부 도구 연결 (MCP/OpenAPI)
```

## 역할 구분

| 역할 | 범위 |
|------|------|
| **관리자** | 관리자 페이지 설정 전반 + 워크스페이스 > 가드레일 |
| **개발자** | 워크스페이스: 에이전트, 지식 기반, 데이터베이스, 용어집, Flow, 프로젝트, 도구 연결 |

---

## Lab 문서 작성 규칙

### 파일 구조

```markdown
# Lab N: 제목

한 줄 설명.

**소요 시간**: NN분

## 학습 목표
- 목표 1
- 목표 2

## (사전 지식 — 필요 시)
개념 설명, 비교 표 등

## 실습

### Step 1: 제목
1. 구체적 클릭 경로
2. 입력 값 테이블
3. admonition (tip, warning, info) 활용

### Step N: ...

## 확인 사항
- [ ] 체크리스트

## 다음 단계
[Lab N+1: 제목 →](다음파일.md)
```

### 작성 원칙

1. **실제 코드 참조 필수**: 설정 항목, 필드명, 동작 방식은 반드시 소스 코드를 확인하고 작성
2. **구체적 클릭 경로**: "관리자 패널 > 설정 > 연결" 형태로 정확한 UI 경로 제시
3. **입력 값은 테이블**: 설정 항목과 예시 값을 표로 정리
4. **Admonition 활용**: tip, warning, info, note 박스로 주의사항/팁 강조
5. **스크린샷 위치**: `docs/assets/images/` 디렉토리, `![설명](../assets/images/파일명.png)` 형식
6. **한국어 작성**: 모든 콘텐츠 한국어, 코드/명령어만 영어

### 참조할 소스 코드 위치

| 기능 | 코드 위치 |
|------|----------|
| 관리자 설정 UI | `src/lib/components/admin/Settings/` |
| 사용자/그룹/조직 | `src/lib/components/admin/Users/` |
| 워크스페이스 UI | `src/lib/components/workspace/` |
| 에이전트 편집 | `src/lib/components/workspace/Agents/` |
| 지식 기반 | `src/lib/components/workspace/Knowledge/` |
| DbSphere | `src/lib/components/workspace/Database/` |
| 가드레일 | `src/lib/components/workspace/Guardrails/` |
| 용어집 | `src/lib/components/workspace/Glossary/` |
| Agent Flow | `src/lib/components/workspace/Flows/` |
| 프로젝트 | `src/lib/components/workspace/Projects/` |
| 도구 연결 UI | `src/lib/components/workspace/Tools/MCPConnectionForm.svelte`, `ToolDetail.svelte` |
| 도구 연결 선택 | `src/lib/components/workspace/Agents/ToolConnections/` |
| 도구 연결 API | `src/lib/apis/tool-connections/index.ts` |
| 모니터링 | `src/lib/components/admin/Monitoring/` |
| 백엔드 라우터 | `backend/open_webui/routers/` |
| 도구 연결 라우터 | `backend/open_webui/routers/tool_connections.py` |
| 도구 연결 모델 | `backend/open_webui/models/tool_connections.py` |
| MCP 클라이언트 | `backend/open_webui/utils/mcp_client.py` |
| MCP 커넥터 | `backend/extension_modules/server/mcp_connector.py` |
| OpenAPI 커넥터 | `backend/extension_modules/server/openapi_connector.py` |
| 백엔드 모델 | `backend/open_webui/models/` |
| 설정 변수 | `backend/open_webui/config.py` |

---

## 새 Lab 추가 워크플로우

### 1단계: 기능 코드 분석
- 해당 기능의 프론트엔드 컴포넌트와 백엔드 라우터를 읽어 UI 흐름과 설정 항목 파악
- 설정 필드명, 옵션 값, 기본값 확인

### 2단계: Lab 문서 작성
- 위의 파일 구조와 작성 원칙에 따라 작성
- `/cloosphere-docs/docs/{admin-hol|developer-hol}/` 에 파일 생성

### 3단계: mkdocs.yml 업데이트
- `nav` 섹션에 새 Lab 항목 추가

### 4단계: 전후 Lab 링크 업데이트
- 이전 Lab의 "다음 단계" 링크 수정
- index.md 테이블에 새 Lab 추가

---

## 기존 Lab 업데이트 워크플로우

### 1단계: 변경된 기능 확인
- 관련 소스 코드의 변경 사항 확인 (git diff, git log)

### 2단계: 문서 수정
- 변경된 UI 경로, 설정 항목, 동작 방식 반영
- 스크린샷 업데이트 필요 시 표시

---

## 변경 감지 및 자동 업데이트

기능 변경 시 영향받는 Lab을 자동으로 파악하고 업데이트합니다.

### 변경 감지 방법

```bash
# 1. 최근 변경된 백엔드/프론트엔드 파일 확인
git diff --name-only HEAD~10 -- backend/open_webui/routers/ backend/open_webui/models/ src/lib/components/

# 2. 새로 추가된 라우터나 컴포넌트 확인
git diff --name-only --diff-filter=A HEAD~10

# 3. 특정 기능 영역의 변경 확인
git log --oneline -10 -- <기능경로>
```

### 기능 → Lab 매핑

| 변경된 코드 경로 | 영향받는 Lab |
|-----------------|-------------|
| `routers/openai.py`, `config.py` (LLM 관련) | 관리자 Lab 1 |
| `config.py` (RAG/임베딩), `search_engine/` | 관리자 Lab 2 |
| `routers/users.py`, `routers/groups.py`, `models/groups.py` | 관리자 Lab 3 |
| `routers/organizations.py`, `models/organizations.py` | 관리자 Lab 4 |
| `routers/configs.py`, `routers/branding.py` | 관리자 Lab 5 |
| `routers/guardrails.py`, `extension_modules/guardrail/` | 관리자 Lab 6 |
| `routers/usage.py`, `routers/audit_logs.py`, `routers/traces.py` | 관리자 Lab 7 |
| `components/workspace/Agents/`, `routers/models.py` | 개발자 Lab 1 |
| `components/workspace/Knowledge/`, `routers/knowledge.py` | 개발자 Lab 2 |
| `components/workspace/Database/`, `routers/dbsphere.py`, `extension_modules/dbsphere/` | 개발자 Lab 3 |
| 개발자 Lab 1~3 관련 코드 동시 변경 | 개발자 Lab 4 |
| `components/workspace/Glossary/`, `routers/glossary.py` | 개발자 Lab 5 |
| `components/workspace/Flows/`, `routers/agent_flows.py`, `extension_modules/agent_flow/` | 개발자 Lab 6 |
| `components/workspace/Projects/`, `routers/projects.py` | 개발자 Lab 7 |
| `components/workspace/Tools/`, `routers/tool_connections.py`, `utils/mcp_client.py`, `extension_modules/server/` | 개발자 Lab 8 |

### 업데이트 워크플로우

1. **변경 감지**: 위 매핑 테이블로 영향받는 Lab 식별
2. **코드 분석**: 변경된 소스 코드를 읽어 UI/설정/동작 변경 파악
3. **문서 업데이트**: 변경된 내용을 해당 Lab 문서에 반영
   - 새 설정 항목 → Step에 테이블 행 추가
   - UI 경로 변경 → 클릭 경로 수정
   - 새 기능 추가 → Step 추가 또는 새 Lab 생성
   - 기능 삭제 → 해당 Step 제거
4. **연관 문서 확인**: index.md, mkdocs.yml, 전후 Lab 링크 일관성 확인

### 새 기능 → 새 Lab 판단 기준

- 새 라우터(`routers/`) + 새 모델(`models/`) + 새 프론트엔드 컴포넌트가 모두 추가된 경우 → 새 Lab 후보
- 기존 기능의 하위 설정 추가 → 기존 Lab에 Step 추가
- 관리자 페이지 기능 → admin-hol, 워크스페이스 기능 → developer-hol

---

## MkDocs 로컬 미리보기

```bash
cd /cloosphere-docs
pip install -r requirements.txt
mkdocs serve -a 0.0.0.0:8000
```

## Markdown 확장 사용법

```markdown
# Admonition
!!! tip "제목"
    내용

!!! warning "주의"
    내용

# 탭
=== "Azure OpenAI"
    설정 내용

=== "Vertex AI"
    설정 내용

# 코드 복사
```bash
명령어
```
```
