## 📝 요약

Cloosphere v2 엔터프라이즈 기능 대규모 업데이트

---

## 📄 주요 변경 내용

### 1. 조직(Organization) 관리
- Microsoft Entra ID 연동 조직 구조 동기화
- 조직 단위(OU) 기반 접근 제어

### 2. 모니터링 (Usage & Audit)
- LLM 사용량 추적 (agent_id/model_id 분리)
- 임베딩/백그라운드 태스크 추적
- Audit Logging (사용자 활동 기록)

### 3. 워크스페이스 확장
- Models → Agents 리네이밍
- Glossary (용어집) 기능
- DbSphere 개선

### 4. 검색 엔진 추상화
- Azure AI Search, pgvector, Milvus, Elasticsearch 지원
- 통합 인터페이스 (`SearchEngine` 베이스 클래스)

### 5. 도구 서버 연결
- MCP/OpenAPI 커넥터 추가
- LangChain Tool 어댑터

### 6. 관리자 권한 분리
- 탭별 세분화된 접근 제어
- Developer Mode 추가

### 7. 기타
- SharePoint 연동 개선
- 다국어 번역 업데이트
- 엔지니어 문서 추가

---

## ✅ 체크리스트

- [x] 린트 통과
- [x] 포맷 확인
- [x] 새 기능 / 문서 수정 / 설정 변경

---

## 📊 변경 통계

| 항목 | 수치 |
|------|------|
| 커밋 수 | 40+ |
| 변경 파일 | 395개 |

---

## 💬 리뷰어 참고

**상세 문서:** [PR_ENTERPRISE_FEATURES_DETAIL.md](docs/pr/PR_ENTERPRISE_FEATURES_DETAIL.md)

**환경 변수 추가 필요:**
```env
SEARCH_ENGINE_TYPE=azure_search
ENABLE_OAUTH_ORG_UNIT_MANAGEMENT=true
ENABLE_USAGE_TRACKING=true
```

**마이그레이션:** `alembic upgrade head`
