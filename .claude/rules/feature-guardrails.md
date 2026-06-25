---
paths:
  - "backend/open_webui/routers/guardrails.py"
  - "backend/open_webui/models/guardrails.py"
  - "backend/open_webui/utils/guardrails.py"
  - "backend/extension_modules/guardrail/**/*.py"
  - "src/lib/components/workspace/Guardrails/**/*.svelte"
---

# 가드레일/안전 규칙

## 라우터 (routers/guardrails.py)
- CRUD 표준 패턴 — `workspace.guardrails` 권한
- `/{id}/test`: POST 가드레일 테스트 → GuardrailTestResponse

## 모델 스키마
```python
class Guardrail(Base):
    __tablename__ = "guardrail"
    id, user_id, name, description
    apply_to_input(bool), apply_to_output(bool)
    pii_types(JSON, default=[])
    pii_strategy(Text, default="redact")
    custom_patterns(JSON, default=[])
    blocked_words(JSON, default=[])
    llm_judge_enabled(bool), llm_judge_model_id(Text)
    llm_judge_prompt(Text)
    llm_judge_pass_examples(JSON, default=[])
    llm_judge_block_examples(JSON, default=[])
    access_control(JSON), created_at, updated_at
```

## PII 감지 타입
- email, credit_card, ip, mac_address, url, api_key, phone, ssn 등

## 전략 (Strategy)
- `block`: 요청 차단
- `redact`: PII 제거
- `mask`: PII 마스킹 (****)
- `hash`: PII 해싱

## LLM Judge
- 모델 기반 2차 필터링
- pass/block 예시 기반 판단
- `llm_judge_model_id`로 사용할 모델 지정

## 적용 구분
- `apply_to_input`: 입력에 적용
- `apply_to_output`: 출력에 적용

## 테스트 응답
```python
class GuardrailTestResponse(BaseModel):
    processed_text: str
    violations: List[dict]
    blocked: bool
    message: Optional[str] = None
```

## 참조 파일
- `routers/guardrails.py`: CRUD + 테스트
- `models/guardrails.py`: 스키마 정의
- `utils/guardrails.py`: 가드레일 적용 로직
- `extension_modules/guardrail/`: PII 감지, 콘텐츠 필터
