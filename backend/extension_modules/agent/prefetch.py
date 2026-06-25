"""Deterministic uploaded-file prefetch helpers (PR4).

UnifiedAgent 가 현재 턴 업로드 파일을 모델의 get_file_contents tool-call 확률성에
의존하지 않고 코드로 결정적 주입(decision a)하기 위한 순수 헬퍼 모음.
size gate(decision f) · input PII redaction(decision e) · 빈 파일 안내를 담당한다.

무거운 UnifiedAgent import 없이 단위 테스트 가능하도록 별도 모듈로 분리.
주입 자체는 `UnifiedAgent._prefetch_uploaded_files`(_run_stream bundle merge, option A).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Size gate 임계값 — reasoning LLM 토큰 기준 근사 (Nate decision f: 넉넉).
PREFETCH_PER_FILE_TOKEN_CAP = 20_000
PREFETCH_TOTAL_TOKEN_CAP = 40_000

# tiktoken 미가용 시 char→token 근사 비율 (혼합 한/영 보수적).
_CHARS_PER_TOKEN = 3

_ENC: Any = None
_ENC_TRIED = False


def _get_encoder() -> Any:
    """cl100k_base 인코더를 lazy 로 1회 로드. 실패 시 None (char fallback)."""
    global _ENC, _ENC_TRIED
    if _ENC_TRIED:
        return _ENC
    _ENC_TRIED = True
    try:
        import tiktoken

        _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # pragma: no cover - 환경 의존
        logger.warning("[prefetch] tiktoken unavailable, using char fallback: %s", e)
        _ENC = None
    return _ENC


def build_prefetch_tool_messages(
    sources: List[Dict[str, Any]], tool_call_id: str = "prefetch_files"
) -> List[Dict[str, Any]]:
    """합성 AIMessage(get_file_contents tool_call) + ToolMessage(파일 본문) 쌍 생성 (PR4 option B).

    추론 루프가 '이미 get_file_contents 를 호출해 본문을 받았다'고 인식하게 만들어,
    모델 tool-call 확률성을 제거하고 파일 기반 추론을 유도한다. ToolMessage 의 content 는
    실제 get_file_contents 반환과 동일한 {"sources":[...]} JSON 이라 build_source_bundles
    가 그대로 chat_upload bundle 로 수집한다.
    """
    ai_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": "get_file_contents", "arguments": "{}"},
            }
        ],
    }
    tool_msg = {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps({"sources": sources}, ensure_ascii=False),
    }
    return [ai_msg, tool_msg]


def compute_missing_file_ids(
    attached_files: Optional[List[str]],
    source_bundles: Optional[Dict[str, List[Dict[str, Any]]]],
) -> List[str]:
    """모델이 이미 get_file_contents 로 가져온 파일을 제외한 미주입 file_id 목록.

    chat_upload bundle 의 file_id(없으면 identity)로 dedup. KB 등 다른 source_type
    bundle 은 업로드 dedup 에 영향 주지 않는다.
    """
    already: set = set()
    for b in (source_bundles or {}).get("chat_upload", []):
        meta_list = b.get("metadata") or []
        meta0 = meta_list[0] if meta_list and isinstance(meta_list[0], dict) else {}
        fid = meta0.get("file_id") or b.get("identity")
        if fid:
            already.add(fid)
    return [fid for fid in (attached_files or []) if fid not in already]


def merge_prefetched_bundles(
    source_bundles: Dict[str, List[Dict[str, Any]]],
    prefetched_bundles: Optional[Dict[str, List[Dict[str, Any]]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """prefetch bundle 을 기존 source_bundles 에 source_type 별로 append (in-place)."""
    for stype, bundles in (prefetched_bundles or {}).items():
        source_bundles.setdefault(stype, []).extend(bundles)
    return source_bundles


def truncate_to_tokens(
    text: str, budget_tokens: int, enc: Any = None
) -> Tuple[str, int]:
    """본문을 token budget 으로 절단한다. 초과 시 head 70% + tail 30% + 생략 마커.

    Returns: (잘린 텍스트, 실제 사용 토큰 수). budget<=0 이면 생략 안내 + 0 토큰.
    """
    if not text:
        return text, 0
    if budget_tokens <= 0:
        return "[첨부 파일 본문이 컨텍스트 예산을 초과하여 생략되었습니다]", 0

    if enc is None:
        enc = _get_encoder()

    if enc is None:
        # char fallback
        cap = budget_tokens * _CHARS_PER_TOKEN
        if len(text) <= cap:
            return text, max(1, len(text) // _CHARS_PER_TOKEN)
        head_len = int(cap * 0.7)
        tail_len = cap - head_len
        head, tail = text[:head_len], text[len(text) - tail_len :]
        omitted = len(text) - head_len - tail_len
        return (
            f"{head}\n\n[... 중간 약 {omitted}자 생략 (size gate) ...]\n\n{tail}",
            budget_tokens,
        )

    tokens = enc.encode(text)
    if len(tokens) <= budget_tokens:
        return text, len(tokens)
    head_n = int(budget_tokens * 0.7)
    tail_n = budget_tokens - head_n
    head = enc.decode(tokens[:head_n])
    tail = enc.decode(tokens[len(tokens) - tail_n :])
    omitted = len(tokens) - head_n - tail_n
    return (
        f"{head}\n\n[... 중간 약 {omitted} 토큰 생략 (size gate) ...]\n\n{tail}",
        budget_tokens,
    )


def apply_size_gate(
    sources: List[Dict[str, Any]],
    per_file_cap: int = PREFETCH_PER_FILE_TOKEN_CAP,
    total_cap: int = PREFETCH_TOTAL_TOKEN_CAP,
) -> List[Dict[str, Any]]:
    """sources 의 document 본문을 per-file + 전체 token budget 으로 절단(OOM/비용 방지).

    sources 를 in-place 변형 — get_file_contents 가 매 호출 새로 만든 dict 전제.
    """
    enc = _get_encoder()
    total = 0
    for src in sources:
        if not isinstance(src, dict):
            continue
        new_docs = []
        for d in src.get("document") or []:
            if not isinstance(d, str) or not d:
                new_docs.append(d)
                continue
            budget = min(per_file_cap, max(0, total_cap - total))
            truncated, used = truncate_to_tokens(d, budget, enc)
            total += used
            new_docs.append(truncated)
        src["document"] = new_docs
    return sources


def mark_empty_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """본문 추출 실패(빈/공백) 파일에 안내 문구를 채워 silent omission 을 방지한다.

    split_source_contexts 는 빈 document bundle 을 건너뛰므로, 안내 없이 두면
    사용자는 "파일을 못 읽었다"는 피드백 없이 답변이 비게 된다. sources 를 in-place 변형.
    """
    for src in sources:
        if not isinstance(src, dict):
            continue
        docs = src.get("document") or []
        if not any(isinstance(d, str) and d.strip() for d in docs):
            name = (src.get("source") or {}).get("name") or "첨부 파일"
            src["document"] = [
                f"[{name}: 텍스트를 추출하지 못했습니다 — 스캔/이미지 문서일 수 있습니다]"
            ]
    return sources


def redact_pii(
    sources: List[Dict[str, Any]], engines: Optional[List[Any]]
) -> List[Dict[str, Any]]:
    """prefetch 본문을 input PII 경로로 명시 통과시킨다 (decision e). sources 를 in-place 변형.

    ToolMessage 는 guardrail 미스캔이라, 코드 주입 본문은 input PII redaction 을
    우회한다. 에이전트의 input PII 엔진(process_text(text, is_input=True) →
    (processed, violations, blocked))을 직접 태워 redact/mask/hash 를 적용한다.
    **fail-closed**: block 전략이거나 엔진 오류 시 본문을 제외하고 안내로 대체한다
    (un-redacted PII 유출 방지 — ACME redact 고객 안전).
    """
    if not engines:
        return sources
    for src in sources:
        if not isinstance(src, dict):
            continue
        name = (src.get("source") or {}).get("name") or "첨부 파일"
        new_docs = []
        for d in src.get("document") or []:
            if not isinstance(d, str) or not d:
                new_docs.append(d)
                continue
            text = d
            excluded = False
            for engine in engines:
                try:
                    processed, _violations, blocked = engine.process_text(
                        text, is_input=True
                    )
                    text = processed
                    if blocked:
                        excluded = True
                        break
                except Exception as e:
                    # fail-closed: 엔진 오류 시 un-redacted 본문을 흘려보내지 않는다.
                    logger.error(
                        "[prefetch] PII redaction engine error (fail-closed): %s", e
                    )
                    excluded = True
                    break
            if excluded:
                logger.warning(
                    "[prefetch] uploaded file '%s' body excluded (PII policy/engine error)",
                    name,
                )
                text = f"[{name}: 민감정보 처리 정책에 의해 본문이 제외되었습니다]"
            new_docs.append(text)
        src["document"] = new_docs
    return sources
