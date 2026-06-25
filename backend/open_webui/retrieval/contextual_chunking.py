"""
Contextual Chunking — 각 청크에 문맥 요약 프리앰블을 추가.

Anthropic의 Contextual Retrieval 기법 구현.
전체 문서 텍스트를 참조하여 각 청크의 위치/맥락을 LLM이 요약하고,
요약을 청크 앞에 prepend하여 검색 정확도를 높인다.
"""

import asyncio
import logging
import os

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_PROMPT = """\
<document>
{document}
</document>

Here is the chunk we want to situate within the whole document:
<chunk>
{chunk}
</chunk>

Please give a short succinct context to situate this chunk within the \
overall document for the purposes of improving search retrieval of the chunk. \
Answer only with the succinct context and nothing else."""

# 동시 LLM 호출 제한
MAX_CONCURRENCY = 5
# 문서 텍스트 최대 길이 (chars)
MAX_DOCUMENT_LENGTH = 50000
# 일시적(429/5xx) 오류 재시도 횟수. Azure S0 tier 처럼 분당 replenish 되는 rate
# limit 을 Retry-After 존중 재시도로 흡수한다 (질의예시 생성과 동일 env 공유).
try:
    MAX_LLM_RETRIES = max(0, int(os.getenv("RAG_DOC_ENRICHMENT_LLM_MAX_RETRIES", "5")))
except (ValueError, TypeError):
    MAX_LLM_RETRIES = 5
# enrichment 전체 wall-clock 상한 (초). retry 가 semaphore 슬롯을 쥔 채 누적돼
# file-processing 타임아웃(FILE_PROCESSING_TIMEOUT, 기본 600s)을 잡아먹고 job 을
# 통째로 실패시키는 것을 막는다. 초과 시 best-effort 로 원본(미enrich) 청크 반환.
try:
    ENRICH_TIMEOUT = max(1, int(os.getenv("RAG_DOC_ENRICHMENT_TIMEOUT", "180")))
except (ValueError, TypeError):
    ENRICH_TIMEOUT = 180


async def apply_contextual_chunking(
    app,
    docs: list[Document],
    full_text: str,
    model_id: str,
) -> list[Document]:
    """
    각 청크에 문맥 요약 프리앰블을 추가한다.

    Args:
        app: FastAPI application
        docs: 청킹된 Document 리스트
        full_text: 전체 문서 텍스트
        model_id: LLM 모델 ID (기존 등록된 모델)

    Returns:
        문맥 프리앰블이 추가된 Document 리스트
    """
    from extension_modules.utils.llm import (
        ainvoke_temperature_safe,
        create_llm_from_app,
    )

    llm = create_llm_from_app(app, model_id)
    if not llm:
        log.warning(
            f"Contextual chunking model not found: {model_id}, "
            f"skipping contextual enrichment"
        )
        return docs

    # 문서 길이 제한
    truncated_text = full_text[:MAX_DOCUMENT_LENGTH]

    log.info(f"Contextual chunking: enriching {len(docs)} chunks with model {model_id}")

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def enrich_chunk(doc: Document) -> Document:
        async with semaphore:
            prompt = DEFAULT_CONTEXT_PROMPT.format(
                document=truncated_text,
                chunk=doc.page_content,
            )

            try:
                response = await ainvoke_temperature_safe(
                    llm,
                    [HumanMessage(content=prompt)],
                    max_retries=MAX_LLM_RETRIES,
                )
                context_text = (
                    response.content if hasattr(response, "content") else str(response)
                )

                new_content = f"[Context: {context_text.strip()}]\n\n{doc.page_content}"
                return Document(
                    page_content=new_content,
                    metadata={
                        **doc.metadata,
                        "has_context": True,
                    },
                )
            except Exception as e:
                log.warning(f"Contextual enrichment failed for chunk: {e}")
                return doc

    # 병렬 처리 — 전체 budget 초과 시 best-effort 로 원본 청크 반환.
    # enrichment 는 optional 후처리이므로, 지속 rate-limit 으로 retry 가 누적돼
    # file-processing 타임아웃을 넘기면 job 전체를 죽이는 대신 미enrich 로 진행한다.
    try:
        result_docs = await asyncio.wait_for(
            asyncio.gather(*[enrich_chunk(doc) for doc in docs]),
            timeout=ENRICH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.warning(
            "Contextual enrichment exceeded %ds budget (sustained rate-limit?); "
            "falling back to un-enriched chunks (%d docs)",
            ENRICH_TIMEOUT,
            len(docs),
        )
        return docs

    log.info(f"Contextual chunking completed: {len(result_docs)} chunks")
    return list(result_docs)
