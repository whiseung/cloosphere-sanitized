# Guide Q&A Agent

Cloosphere 사용자 도움말을 BM25 in-memory 검색 + LangChain ReAct 로 답변하는 에이전트.

**임베딩·벡터 DB·관리자 재빌드 버튼 없음** — 고객사 운영 부담 0, 추가 인프라 0.

## 아키텍처

```
guide/docs/{ko,en}/**/*.mdx  ──┐
guide/docs/docs.json           │
                               ▼
            ┌─────────────────────────────────┐
            │ build_guide_catalog.py (수동)   │  → guide_catalog.yaml (64 카테고리)
            └─────────────────────────────────┘
                               │
                               ▼ (lifespan startup)
            ┌─────────────────────────────────┐
            │ bm25_retriever.warmup()         │
            │  1. mdx_cleaner   (Q1)          │
            │  2. chunker       (Q3)          │  H2/H3 1500 token (1237 청크)
            │  3. tokenize      (Q4)          │  영문 word + 한글 char-bigram
            │  4. BM25Okapi (lang 별 분리)    │  메모리 ~5MB
            └─────────────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────────┐
                  │ POST /api/v1/guide/chat      │
                  │  → GuideQAAgent (ReAct)      │
                  │     • search_guides          │ Q2 BM25 + role/lang/MMR 필터
                  │     • get_guide_section      │ Q5 audience-aware
                  │     • list_guide_categories  │ Q5 audience-aware
                  │  → 답변 + 출처 인용          │
                  └──────────────────────────────┘
```

콘텐츠 hash (`guide_catalog.yaml` + 모든 .mdx) 변경 시 자동 재빌드 — admin 개입 불필요.

## 주요 모듈

| 파일 | 역할 |
|---|---|
| `mdx_cleaner.py` | Mintlify MDX → 평문 (16종 컴포넌트 화이트리스트, 코드 펜스 보존, unknown 태그 임계 fail-fast) |
| `chunker.py` | H2 단위 1500 token 청크, H3 fallback, code-fence 인식 |
| `guide_catalog.yaml` | 64 카테고리 메타 (자동 생성, 직접 편집 금지) |
| `bm25_retriever.py` | startup 시 메모리에 BM25 인덱스 빌드 + 콘텐츠 hash 자동 감지 |
| `tools.py` | LangChain 도구 3종 |
| `guide_agent.py` | ReAct 에이전트 + 시스템 프롬프트 |

## 답변 품질 장치 (Q1~Q6)

| # | 이름 | 구현 |
|---|---|---|
| Q1 | MDX 정제 | `mdx_cleaner.py` 16종 화이트리스트 + 코드 펜스 보존 |
| Q2 | 검색 | BM25 in-memory (lang 별 인덱스 분리) |
| Q3 | Heading 청크 + 인용 | `chunker.py` H2/H3 + `heading_path` 메타 → 답변 출처 표기 |
| Q4 | 다국어 자동 감지 | `langdetect` (ko/en), 한글은 char-bigram 토크나이저 |
| Q5 | Audience 권한 필터 | 사용자 role 별 admin/monitoring 차단 (메뉴 + 검색 결과) |
| Q6 | 카테고리 다양성 | top_k=8, 카테고리당 최대 3개 (다양성 컷오프) |

## 콘텐츠 편집 흐름

신규 가이드를 작성/수정하려면 본 리포 `guide/docs/{ko,en}/**/*.mdx` 를 직접 편집한다.

```bash
# 1. 콘텐츠 편집
vim guide/docs/ko/workspace/agents.mdx

# 2. 카탈로그 재생성 (frontmatter title/description 또는 페이지 추가/삭제 시)
PYTHONPATH=backend uv run python -m scripts.build_guide_catalog

# 3. 그게 다임 — 다음 백엔드 startup 시 BM25 인덱스 자동 재빌드
#    (콘텐츠 hash 변경 자동 감지)
```

별도 admin UI 버튼/CLI 명령 불필요. 변경된 콘텐츠는 다음 쿼리 시 즉시 반영된다.

## 권한 모델

| 도구 | user role | admin role |
|---|---|---|
| `list_guide_categories` | 34 카테고리 (admin/* + monitoring/* 제외) | 64 카테고리 |
| `get_guide_section` | admin/* + monitoring/* 카테고리 차단 | 모두 허용 |
| `search_guides` | 검색 결과에서 admin/* + monitoring/* 카테고리 메타 차단 | 모두 허용 |

## 운영 비용

| 항목 | 비용 |
|---|---|
| 임베딩 모델 호출 | **0** |
| 벡터 DB 스토리지 | **0** |
| 인덱스 빌드 시간 | startup 1회 < 1초 (1237 청크) |
| 메모리 | ~5MB |
| 쿼리 latency | < 10ms (BM25) + LLM 호출 |
| LLM 호출 | 질문당 평균 1~2회 |

## 롤백 절차

신규 가이드가 문제가 있을 때:

```bash
# A. 콘텐츠 일부만 되돌리기
vim guide/docs/...mdx     # 수정
# → 다음 startup 시 자동 반영

# B. 전체 롤백 (커밋 단위)
git revert <commit_sha>   # feat/guide-docs-refresh PR
```

벡터 DB 정리 같은 별도 작업 불필요.

## 회귀 검증

테스트 90+개 회귀 질문은 `tests/regression_questions.yaml` 에 정의되어 있다.

```bash
# 정합성 + 카탈로그 커버리지 (LLM 호출 없음)
uv run python -m pytest backend/extension_modules/guide_agent/tests/
```

acceptance:
- 단위 테스트: mdx_cleaner 16, chunker 9, catalog builder 8, BM25 retriever 검증 → 모두 통과
- top-3 정답률 ≥ 70% (수동 검증 권장)
- admin-blocked 누수 0건
