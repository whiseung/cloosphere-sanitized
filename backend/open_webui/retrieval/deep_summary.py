"""Deep document summary via windowed map-reduce (full-text, tree-reduce).

문서 "전문(full text)"을 토큰 윈도로 나눠 MAP(윈도별 병렬 요약) → tree REDUCE 한다.
검색(top-k)이 아니라 문서 전체를 빠짐없이 반영하며, 한 번에 한 윈도만 LLM 에 넣으므로
수백 페이지 문서도 통째로 컨텍스트에 투입하지 않는다.

기존 _generate_file_summary_sync(앞/중/뒤 샘플링 = lossy)의 한계를 넘는 무손실 경로.
인제스트 시점(전체 text_content 보유) 또는 질의 시점(청크 복원) 양쪽에서 사용한다.
"""

import asyncio
import logging
from typing import List, Optional

log = logging.getLogger(__name__)

# 기본값 (합의)
DEFAULT_WINDOW_TOKENS = 6000  # MAP 윈도 크기 (tiktoken 토큰 기준)
DEFAULT_REDUCE_BATCH = 40  # tree REDUCE 한 배치당 요약 수
DEFAULT_CONCURRENCY = 8  # 동시 LLM 호출 상한 (rate-limit 보호)
DEFAULT_WINDOW_CEILING = 500  # 윈도 수 상한 (초과분은 로그 후 절단)
DEFAULT_TIMEOUT = 120  # per-call 타임아웃(초)


def _resolve_task_model_id(app, model_override: Optional[str] = None) -> Optional[str]:
    """요약용 Task Model id 결정 (_generate_file_summary_sync 와 동일 정책).

    app.state.MODELS 는 백그라운드 처리 시점에 비어있을 수 있으므로 'in models'
    로 강제 게이트하지 않고 설정값 존재만 확인한다.
    """
    models = getattr(app.state, "MODELS", {})
    if model_override and (not models or model_override in models):
        return model_override
    task_model = app.state.config.TASK_MODEL
    task_model_external = app.state.config.TASK_MODEL_EXTERNAL
    if task_model_external and (not models or task_model_external in models):
        return task_model_external
    if task_model and (not models or task_model in models):
        return task_model
    return None


def _get_encoder(app):
    """tiktoken 인코더 반환. 실패 시 None (호출부가 문자 기준 fallback)."""
    try:
        import tiktoken

        name = getattr(app.state.config, "TIKTOKEN_ENCODING_NAME", "cl100k_base")
        return tiktoken.get_encoding(str(name))
    except Exception:
        try:
            import tiktoken

            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None


def _split_into_token_windows(text: str, encoder, window_tokens: int) -> List[str]:
    """텍스트를 토큰 기준 윈도로 분할. encoder 없으면 문자 기준 근사(1토큰≈2자)."""
    if not text:
        return []
    if encoder is None:
        approx = max(1, window_tokens * 2)
        return [text[i : i + approx] for i in range(0, len(text), approx)]
    tokens = encoder.encode(text)
    windows = []
    for i in range(0, len(tokens), window_tokens):
        windows.append(encoder.decode(tokens[i : i + window_tokens]))
    return windows


async def generate_deep_summary(
    app,
    text: str,
    filename: str,
    model_override: Optional[str] = None,
    focus: Optional[str] = None,
    *,
    window_tokens: int = DEFAULT_WINDOW_TOKENS,
    reduce_batch: int = DEFAULT_REDUCE_BATCH,
    concurrency: int = DEFAULT_CONCURRENCY,
    window_ceiling: int = DEFAULT_WINDOW_CEILING,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """문서 전문을 windowed map-reduce 로 심층 요약한다.

    Args:
        text: 문서 전문 (청킹 전 원본 또는 청크 복원 텍스트)
        filename: 문서명 (프롬프트 컨텍스트)
        model_override: KB별 요약 모델 (없으면 Task Model)
        focus: 선택적 초점 관점 (예: "리스크", "유지보수"). 지정 시 그 관점 중심 요약.
    Returns:
        심층 요약 문자열, 실패/모델없음/빈텍스트면 None.
    """
    from extension_modules.utils.llm import create_llm_from_app
    from langchain_core.messages import HumanMessage

    if not text or not text.strip():
        return None

    model_id = _resolve_task_model_id(app, model_override)
    if not model_id:
        log.info("[deep_summary] Task model not configured — skipping")
        return None

    llm = create_llm_from_app(app, model_id, temperature=0.3)
    if not llm:
        return None

    encoder = _get_encoder(app)
    windows = _split_into_token_windows(text, encoder, window_tokens)
    if not windows:
        return None

    truncated = False
    if len(windows) > window_ceiling:
        log.warning(
            "[deep_summary] %s: %d windows exceeds ceiling %d — 앞 %d 윈도까지만 반영",
            filename,
            len(windows),
            window_ceiling,
            window_ceiling,
        )
        windows = windows[:window_ceiling]
        truncated = True

    focus_clause = f"\n특히 다음 관점에 초점을 맞추세요: {focus}\n" if focus else "\n"
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _ainvoke(prompt: str) -> str:
        async with sem:
            try:
                resp = await asyncio.wait_for(
                    llm.ainvoke([HumanMessage(content=prompt)]), timeout=timeout
                )
                return (resp.content or "").strip()
            except Exception as e:
                log.warning("[deep_summary] LLM call failed: %s", e)
                return ""

    # ── MAP: 윈도별 요약 (병렬) ───────────────────────────────────────────
    total = len(windows)

    async def _map_window(idx: int, w: str) -> str:
        prompt = (
            f"다음은 '{filename}' 문서의 일부(섹션 {idx + 1}/{total})입니다.{focus_clause}"
            f"---\n{w}\n---\n"
            "이 섹션의 핵심 내용(수치·항목·결론 포함)을 한국어로 간결히 요약하세요. "
            "요약만 출력하고 다른 텍스트는 넣지 마세요."
        )
        return await _ainvoke(prompt)

    window_summaries = await asyncio.gather(
        *(_map_window(i, w) for i, w in enumerate(windows))
    )
    window_summaries = [s for s in window_summaries if s]
    if not window_summaries:
        return None

    # 윈도가 1개뿐이면 그 요약이 곧 문서 요약
    if len(window_summaries) == 1:
        final = window_summaries[0]
        return _append_truncation_note(final, truncated, window_ceiling)

    # ── REDUCE: tree 방식 (배치별 합성 → 수렴) ────────────────────────────
    async def _reduce(summaries: List[str]) -> str:
        joined = "\n\n".join(f"- {s}" for s in summaries)
        prompt = (
            f"다음은 '{filename}' 문서를 여러 섹션으로 나눠 요약한 것입니다.{focus_clause}"
            f"{joined}\n\n"
            "위 섹션 요약들을 종합하여 문서 전체의 핵심을 한국어로 체계적으로 정리하세요. "
            "중복은 합치고 논리적 순서로 구성하며, 중요한 수치·항목은 보존하세요. "
            "요약만 출력하세요."
        )
        return await _ainvoke(prompt)

    level = window_summaries
    # 한 reduce 에 다 안 들어가면 배치로 나눠 단계적으로 수렴
    while len(level) > reduce_batch:
        batches = [
            level[i : i + reduce_batch] for i in range(0, len(level), reduce_batch)
        ]
        reduced = await asyncio.gather(*(_reduce(b) for b in batches))
        level = [s for s in reduced if s]
        if not level:
            return None

    final = level[0] if len(level) == 1 else await _reduce(level)
    return _append_truncation_note(final, truncated, window_ceiling)


def _append_truncation_note(
    summary: Optional[str], truncated: bool, ceiling: int
) -> Optional[str]:
    if summary and truncated:
        return (
            f"{summary}\n\n"
            f"(참고: 문서가 매우 길어 앞부분 {ceiling}개 구간까지만 반영된 요약입니다.)"
        )
    return summary


def stitch_document_text(docs) -> str:
    """청크(DocumentItem 류) 리스트를 원본 전문으로 복원.

    각 청크 metadata 의 start_index(원문 문자 오프셋)가 전부 있으면 오버랩을
    정확히 제거해 무손실 복원하고, 없으면 chunk_index 순으로 단순 연결한다
    (오버랩 중복은 요약에 무해). token/character 청킹 무관하게 동작.
    """
    if not docs:
        return ""

    def _ci(d):
        return (getattr(d, "metadata", None) or {}).get("chunk_index", 0)

    ordered = sorted(docs, key=_ci)
    all_si = all(
        (getattr(d, "metadata", None) or {}).get("start_index") is not None
        for d in ordered
    )

    if all_si:
        out = ""
        for d in ordered:
            si = (d.metadata or {}).get("start_index")
            content = d.content or ""
            if si <= len(out):
                # 이전까지 복원된 길이와 겹치는 부분 제거
                out += content[len(out) - si :]
            else:
                # 비정상 gap — 그냥 이어붙임
                out += content
        return out

    return "\n".join((d.content or "") for d in ordered)
