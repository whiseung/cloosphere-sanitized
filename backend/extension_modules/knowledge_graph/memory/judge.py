"""LLM judge — 생성·실행한 Cypher 가 사용자 질문에 답이 됐는지 판단.

`cypher_example` 메모리 저장의 게이트. 단순 result-non-empty 만으로는
`MATCH (n) RETURN n LIMIT 5` 같은 무관 쿼리가 누적되어 retrieval 노이즈가
커지므로, 별도 LLM 호출로 (question, cypher, result preview) 를 본 다음
`{answers_question, confidence, reason}` JSON 을 받아 confidence ≥ 0.7
일 때만 저장한다.

호출 비용은 cypher 1건당 ~200 token 의 짧은 호출 한 번. KG `options.llm_model_id`
재사용.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from extension_modules.utils.llm import generate_text, get_model_config_from_app

logger = logging.getLogger(__name__)


JUDGE_PROMPT = """당신은 데이터베이스 결과 품질 검증자입니다.
주어진 사용자 질문 / Cypher / 결과를 보고, 이 결과가 질문에 답이 되는지 판단하세요.

## 사용자 질문
{question}

## 실행된 Cypher
```cypher
{cypher}
```

## 결과 미리보기 (상위 {row_count}/{total_rows} 행)
{result_preview}

## 판단 기준
- "answers_question": 결과가 질문이 묻는 정보를 어느 정도 포함하는가? (boolean)
- "confidence": 0~1 사이. 결과가 질문의 핵심 정보(엔티티/속성)를 명시적으로 포함하면 0.8 이상,
   부분적이거나 모호하면 0.4~0.7, 거의 무관하거나 빈 결과면 0~0.3
- "reason": 1문장 한국어 설명

## 응답 형식 (JSON 한 객체만, 코드 블록 없이)
{{
  "answers_question": true,
  "confidence": 0.85,
  "reason": "..."
}}
"""


@dataclass
class JudgeVerdict:
    answers_question: bool
    confidence: float  # 0..1
    reason: str
    raw: Optional[str] = None  # LLM 원본 응답 (디버깅)


def _format_result_preview(
    rows: List[List[Any]], max_rows: int = 5, max_chars: int = 800
) -> str:
    """결과 행을 사람/LLM 이 읽기 좋은 짧은 텍스트로."""
    if not rows:
        return "(no rows)"
    preview = rows[:max_rows]
    try:
        text = json.dumps(preview, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = str(preview)
    if len(text) > max_chars:
        text = text[:max_chars] + " ... (truncated)"
    return text


def _parse_verdict(raw: str) -> Optional[JudgeVerdict]:
    if not raw:
        return None
    s = raw.strip()
    # 코드 블록 strip
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s
        s = s.split("\n", 1)[-1]
        if s.endswith("```"):
            s = s[:-3]
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(s[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        return JudgeVerdict(
            answers_question=bool(data.get("answers_question", False)),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
            reason=str(data.get("reason", "")),
            raw=raw,
        )
    except (TypeError, ValueError):
        return None


async def judge_cypher_result(
    app,
    *,
    question: str,
    cypher: str,
    rows: List[List[Any]],
    total_rows: int,
    llm_model_id: str,
    confidence_threshold: float = 0.7,
) -> Optional[JudgeVerdict]:
    """LLM judge 호출. 모델 미설정/응답 파싱 실패 시 None 반환.

    호출자는 None 또는 confidence<threshold 일 때 메모리 저장 skip 한다.
    """
    cfg = get_model_config_from_app(app, llm_model_id)
    if not cfg:
        logger.warning(f"[kg_judge] llm model `{llm_model_id}` not configured")
        return None

    prompt = JUDGE_PROMPT.format(
        question=question.strip(),
        cypher=cypher.strip(),
        row_count=min(len(rows), 5),
        total_rows=total_rows,
        result_preview=_format_result_preview(rows),
    )
    try:
        raw = await generate_text(cfg, prompt, system_prompt=None, temperature=0.0)
    except Exception as e:
        logger.warning(f"[kg_judge] llm call failed: {e}")
        return None

    verdict = _parse_verdict(raw)
    if not verdict:
        logger.warning(
            f"[kg_judge] failed to parse verdict from: {raw[:200] if raw else '<empty>'}"
        )
        return None
    return verdict


__all__ = ["JudgeVerdict", "judge_cypher_result"]
