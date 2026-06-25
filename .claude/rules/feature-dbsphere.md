---
paths:
  - "backend/open_webui/routers/dbsphere.py"
  - "backend/open_webui/models/dbsphere.py"
  - "backend/extension_modules/dbsphere/**/*.py"
  - "src/lib/components/workspace/Database/**/*.svelte"
  - "src/lib/apis/dbsphere/**/*.ts"
---

# DbSphere NL-to-SQL 규칙

## 라우터 (routers/dbsphere.py)
- CRUD 표준 + DB 연결 관리
- `/{id}/test`: POST 연결 테스트
- `/{id}/schema/extract`: POST 스키마 추출 (LLM 설명 생성)
- `/{id}/query`: POST SQL 쿼리 실행
- `/{id}/memory/`: 메모리 CRUD
- `/{id}/chart`: POST 차트 생성

## 모델 스키마
```python
class DbSphere(Base):
    __tablename__ = "dbsphere"
    id, user_id, name, description
    data(JSON), meta(JSON), access_control(JSON)
    created_at, updated_at
```
- `data`: DB 연결 정보, 추출된 스키마 등

## SQL Runner — 8종 DB 지원
- Postgres, MySQL, MSSQL, Oracle, Snowflake, Databricks, Synapse, Fabric
- `extension_modules/dbsphere/sql_runners/` 디렉토리 (base.py + DB별 구현)

## 메모리 시스템 (extension_modules/dbsphere/memory/)
- 단일 인덱스: `dbsphere_memory` + `dbsphere_id` 필터
- `entity_type`으로 구분:
  - `sql_memory`: Question-SQL 쌍
  - `ddl_schema`: 테이블/컬럼 정의 + LLM 설명
  - `documentation`: 비즈니스 규칙, 용어
  - `sql_example`: 설명 포함 SQL 예제

## 스키마 추출
- LLM으로 테이블/컬럼 설명 자동 생성
- `schema_extractor.py`: create_llm() + 프롬프트 기반

## 차트 생성
- Plotly 기반 시각화: `extension_modules/dbsphere/chart/plotly_generator.py`
- SQL 결과 → 차트 데이터 변환

## Dashboard Builder Agent
- 파일: `extension_modules/dbsphere/dashboard_builder_agent.py`
- 여러 SQL 쿼리 결과를 조합해 BI 대시보드 생성

## Tools (LangChain StructuredTool)
- `extension_modules/dbsphere/tools/`: dbsphere_info, get_table_details, run_sql, visualize_data
- UnifiedAgent가 필요 시 로드하여 에이전트 도구로 등록

## 참조 파일
- `routers/dbsphere.py`: CRUD + 쿼리/메모리/스키마
- `extension_modules/dbsphere/`: NL-to-SQL 에이전트 (LangGraph)
- `extension_modules/dbsphere/dbsphere_agent.py` / `dbsphere_state.py`: 에이전트 본체
- `extension_modules/dbsphere/memory/`: SearchEngineDbSphereMemory
- `extension_modules/dbsphere/sql_runners/`: DB별 실행기
- `extension_modules/dbsphere/chart/`: Plotly 생성기
- `extension_modules/dbsphere/tools/`: LangChain 도구 팩토리
