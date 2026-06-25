# Guardrails 아키텍처

## 1. 데이터베이스 모델

### Guardrail 테이블

```python
# backend/open_webui/models/guardrails.py

class Guardrail(Base):
    __tablename__ = "guardrail"

    id = Column(Text, primary_key=True)           # UUID
    user_id = Column(Text)                         # 소유자 ID
    name = Column(Text)                            # 가드레일 이름
    description = Column(Text, nullable=True)      # 설명

    # 규칙 기반 설정
    pii_types = Column(JSON, default=[])           # PII 탐지 유형
    pii_strategy = Column(Text, default="redact")  # 처리 전략
    custom_patterns = Column(JSON, default=[])     # 사용자 정의 패턴
    blocked_words = Column(JSON, default=[])       # 금지어 목록

    # 적용 범위
    apply_to_input = Column(Boolean, default=True)   # 입력에 적용
    apply_to_output = Column(Boolean, default=False) # 출력에 적용

    # LLM Judge 설정
    llm_judge_enabled = Column(Boolean, default=False)
    llm_judge_model = Column(Text, nullable=True)
    llm_judge_prompt = Column(Text, nullable=True)
    llm_judge_pass_examples = Column(JSON, default=[])
    llm_judge_block_examples = Column(JSON, default=[])
    llm_judge_apply_to_input = Column(Boolean, default=True)
    llm_judge_apply_to_output = Column(Boolean, default=False)

    # 접근 제어
    access_control = Column(JSON, nullable=True)

    # 메타데이터
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)
```

## 2. PII 탐지 패턴

### 지원하는 PII 유형

```python
# backend/open_webui/utils/guardrails.py

PII_PATTERNS = {
    "email": {
        "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "description": "이메일 주소 (예: user@domain.com)",
        "mask_func": lambda m: f"{m[0]}***@***{domain[-4:]}",
    },
    "credit_card": {
        "pattern": r"\b(?:\d{4}[- ]?){3}\d{4}\b",
        "description": "신용카드 번호 (Luhn 알고리즘 검증)",
        "mask_func": lambda m: f"****-****-****-{last4}",
        "validator": luhn_check,  # 실제 카드번호만 탐지
    },
    "ip": {
        "pattern": r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}...\b",
        "description": "IPv4 주소 (예: 192.168.1.1)",
    },
    "mac": {
        "pattern": r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})",
        "description": "MAC 주소 (예: 00:1A:2B:3C:4D:5E)",
    },
    "url": {
        "pattern": r"https?://[^\s<>\"']+",
        "description": "HTTP/HTTPS URL",
    },
    "api_key": {
        "pattern": r"sk-[a-zA-Z0-9]{20,}",
        "description": "API 키 (sk-xxx 패턴)",
    },
}
```

## 3. 처리 전략

| 전략 | 설명 | 예시 |
|------|------|------|
| `block` | 콘텐츠 전체 차단 | 요청 거부 |
| `redact` | 탐지된 부분 삭제 | `[REDACTED_EMAIL]` |
| `mask` | 부분 마스킹 | `j***@***com` |
| `hash` | 해시값으로 대체 | `<email_hash:a1b2c3d4>` |

## 4. 처리 흐름

```
                    ┌─────────────────┐
                    │   사용자 입력   │
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │     규칙 기반 처리          │
              │  - PII 탐지                 │
              │  - 커스텀 패턴              │
              │  - 금지어 탐지              │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │   위반 발견?    │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
     ┌─────▼─────┐    ┌──────▼──────┐   ┌─────▼─────┐
     │  block    │    │redact/mask/ │   │위반 없음  │
     │  전략     │    │   hash      │   │           │
     └─────┬─────┘    └──────┬──────┘   └─────┬─────┘
           │                 │                 │
    ┌──────▼──────┐   ┌──────▼──────┐         │
    │ 요청 거부   │   │ 처리된 텍스트│         │
    └─────────────┘   └──────┬──────┘         │
                             │                 │
              ┌──────────────┴─────────────────┘
              │
     ┌────────▼────────┐
     │ LLM Judge 활성? │
     └────────┬────────┘
              │ Yes
     ┌────────▼────────┐
     │ LLM 콘텐츠 심사 │
     └────────┬────────┘
              │
     ┌────────▼────────┐
     │  PASS / BLOCK   │
     └─────────────────┘
```

## 5. GuardrailEngine 클래스

```python
class GuardrailEngine:
    def __init__(self, config: dict):
        self.pii_types = config.get("pii_types", [])
        self.pii_strategy = config.get("pii_strategy", "redact")
        self.custom_patterns = config.get("custom_patterns", [])
        self.blocked_words = config.get("blocked_words", [])
        # LLM Judge 설정
        self.llm_judge_enabled = config.get("llm_judge_enabled", False)
        self.llm_judge_model = config.get("llm_judge_model")
        self.llm_judge_prompt = config.get("llm_judge_prompt")

    def process_text(
        self,
        text: str,
        is_input: bool = True
    ) -> Tuple[str, List[dict], bool]:
        """
        텍스트 처리

        Returns:
            (processed_text, violations, blocked)
        """
        violations = []
        processed_text = text

        # 1. PII 탐지
        for pii_type in self.pii_types:
            matches = find_pii_matches(pii_type, text)
            violations.extend(matches)

        # 2. 커스텀 패턴 탐지
        for pattern in self.custom_patterns:
            matches = re.finditer(pattern["pattern"], text)
            violations.extend(matches)

        # 3. 금지어 탐지
        for word in self.blocked_words:
            if word.lower() in text.lower():
                violations.append({"type": "blocked_word", "word": word})

        # 4. 전략 적용
        if violations:
            if self.pii_strategy == "block":
                return text, violations, True
            else:
                processed_text = self._apply_strategy(text, violations)

        return processed_text, violations, False

    async def llm_judge(
        self,
        text: str,
        generate_func: callable
    ) -> Tuple[bool, str]:
        """
        LLM을 사용한 콘텐츠 심사

        Returns:
            (passed, reason)
        """
        prompt = self._build_judge_prompt(text)
        response = await generate_func(
            model=self.llm_judge_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0
        )

        # PASS 또는 BLOCK 파싱
        response_text = response["choices"][0]["message"]["content"]
        if "block" in response_text.lower():
            return False, "Content blocked by LLM judge"
        return True, "Content approved"
```
