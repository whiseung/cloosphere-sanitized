# doc_create

엔지니어를 위한 기술 문서를 `docs/engineers/{module_name}/` 폴더에 작성합니다.
새로운 기능 모듈 개발 완료 후, 다른 엔지니어들이 이해하고 유지보수할 수 있도록 문서화합니다.

## 문서 구조

기존 문서(dbsphere, setup 등)의 형식을 따르며, 일반적으로 다음 4개 파일로 구성합니다:

```
docs/engineers/{module_name}/
├── 01_overview.md          # 개요, 목적, 구성요소, 기술 스택
├── 02_setup.md             # 설정 방법, 환경변수, 외부 서비스 연동
├── 03_architecture.md      # 코드 구조, 상세 구현, 다이어그램
└── 04_frontend_integration.md  # (프론트엔드 있는 경우) 컴포넌트 사용법, 확장 가이드
```

### 파일별 내용

| 파일 | 필수 포함 내용 |
|------|---------------|
| **01_overview** | 주요 목적, 핵심 기능, 구성요소 목록, 기술 스택, 데이터 흐름 |
| **02_setup** | 환경변수 목록 및 설명, 외부 서비스 설정 (API 키 등), 트러블슈팅 |
| **03_architecture** | 파일 구조, 주요 함수/클래스 설명, API 엔드포인트, 시퀀스 다이어그램 |
| **04_frontend_integration** | 컴포넌트 사용 예제, 이벤트/Props, 스타일링, 다국어, 확장 방법 |

## 작업 순서

1. **기존 문서 참고**
   - `docs/engineers/dbsphere/` 또는 유사 모듈 문서 구조 확인
   - 동일한 스타일과 깊이로 작성

2. **01_overview.md 작성**
   - 모듈의 목적과 가치를 명확히 설명
   - 주요 구성요소 나열
   - 기술 스택 테이블

3. **02_setup.md 작성**
   - 환경변수를 표 형식으로 정리
   - 외부 서비스 설정 단계별 가이드
   - 흔한 오류와 해결 방법

4. **03_architecture.md 작성**
   - 파일 구조를 트리 형태로 표시
   - 주요 코드 블록과 설명
   - API 엔드포인트 테이블
   - 필요시 ASCII 다이어그램

5. **04_frontend_integration.md 작성** (해당되는 경우)
   - 컴포넌트 import 및 사용 예제
   - Props, Events 타입 정의
   - 다국어 키 목록
   - 테스트 체크리스트

## 작성 규칙

### ✅ 해야 할 것
- 한국어로 작성
- 코드 블록에 언어 명시 (```python, ```typescript, ```svelte)
- 환경변수, API 엔드포인트는 표 형식 사용
- 복잡한 흐름은 ASCII 다이어그램으로 시각화
- 실제 코드 예제 포함
- 트러블슈팅 섹션 포함

### ❌ 하지 말아야 할 것
- 영어로 작성하지 않음 (코드/기술 용어 제외)
- 구현되지 않은 기능을 문서화하지 않음
- 민감한 정보 (실제 API 키, 비밀번호) 포함 금지
- 너무 세부적인 코드 전체 복사 금지 (핵심 부분만)

## 마크다운 형식 예시

### 환경변수 표
```markdown
| 변수명 | 설명 | 필수 | 기본값 |
|--------|------|------|--------|
| `MODULE_ENABLED` | 기능 활성화 | Yes | `false` |
| `MODULE_API_KEY` | API 키 | Yes | - |
```

### 파일 구조
```markdown
```
src/lib/
├── utils/
│   └── module-client.ts
├── components/
│   └── ModuleBrowser.svelte
└── stores/
    └── index.ts
```
```

### 시퀀스 다이어그램
```markdown
```
┌────────┐    ┌────────┐    ┌────────┐
│ Client │───▶│ Server │───▶│ API    │
└────────┘    └────────┘    └────────┘
```
```

## 체크리스트

- [ ] 폴더 생성: `docs/engineers/{module_name}/`
- [ ] 01_overview.md - 개요, 목적, 구성요소
- [ ] 02_setup.md - 환경변수, 설정 가이드
- [ ] 03_architecture.md - 코드 구조, API 상세
- [ ] 04_frontend_integration.md - 컴포넌트 사용법 (해당시)
- [ ] 코드 블록 언어 명시 확인
- [ ] 환경변수/API 테이블 형식 확인
- [ ] 트러블슈팅 섹션 포함 확인
