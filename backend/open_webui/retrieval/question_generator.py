"""
Knowledge Base 청크 질의예시 생성 모듈.

문서 청크에서 LLM을 사용하여 해당 청크 내용으로 답변 가능한 질문들을 생성합니다.
이 질의예시는 멀티 벡터 검색에서 검색 정확도를 높이는 데 활용됩니다.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage

log = logging.getLogger(__name__)

# 일시적(429/5xx) 오류 재시도 횟수. Azure S0 tier 처럼 분당 replenish 되는 rate
# limit 을 Retry-After 존중 재시도로 흡수한다 (contextual chunking 과 동일 env 공유).
try:
    MAX_LLM_RETRIES = max(0, int(os.getenv("RAG_DOC_ENRICHMENT_LLM_MAX_RETRIES", "5")))
except (ValueError, TypeError):
    MAX_LLM_RETRIES = 5
# enrichment 전체 wall-clock 상한 (초). retry 누적이 file-processing 타임아웃
# (FILE_PROCESSING_TIMEOUT, 기본 600s)을 잡아먹어 job 전체가 실패하는 것을 막는다
# (contextual chunking 과 동일 env 공유). 초과 시 빈 질의예시로 best-effort 폴백.
try:
    ENRICH_TIMEOUT = max(1, int(os.getenv("RAG_DOC_ENRICHMENT_TIMEOUT", "180")))
except (ValueError, TypeError):
    ENRICH_TIMEOUT = 180


# 질의예시 생성 프롬프트 템플릿
CHUNK_QUESTION_PROMPT = """다음 문서 청크를 읽고, 이 청크 내용만으로 답변 가능한 질문을 최대한 많이 추출해주세요.

파일명: {filename}

--- 청크 내용 ---
{chunk_content}
--- 끝 ---

요구사항:
1. **반드시 이 청크 내용만으로 답변 가능한 질문만** 생성 (외부 정보 필요 없이)
2. 실제 사용자가 검색할 법한 자연스러운 한국어 질문
3. 너무 일반적이지 않고 이 청크에 특화된 구체적인 질문
4. 가능한 많은 질문 추출 (최대 {max_count}개)
5. 중복되지 않는 다양한 관점의 질문 (사실, 정의, 비교, 방법 등)

JSON 배열로만 응답:
["질문1", "질문2", ...]
"""

CHUNK_QUESTION_PROMPT_EN = """Read the following document chunk and extract as many questions as possible that can be answered solely using this chunk's content.

Filename: {filename}

--- Chunk Content ---
{chunk_content}
--- End ---

Requirements:
1. **Only generate questions that can be answered using this chunk's content alone** (no external information needed)
2. Natural questions that users would realistically search for
3. Specific questions tailored to this chunk, not overly generic
4. Extract as many questions as possible (maximum {max_count})
5. Diverse perspectives without duplication (facts, definitions, comparisons, methods, etc.)

Respond with JSON array only:
["Question 1", "Question 2", ...]
"""


class ChunkQuestionGenerator:
    """문서 청크에서 질의예시를 생성하는 클래스."""

    def __init__(
        self,
        llm: Any,
        max_questions: int = 10,
        language: str = "ko",
        max_chunk_chars: int = 3000,
    ):
        """
        Args:
            llm: LangChain BaseChatModel 인스턴스
            max_questions: 청크당 최대 질문 수 (기본 10개)
            language: 프롬프트 언어 ("ko" or "en")
            max_chunk_chars: 프롬프트에 포함할 청크 최대 문자 수
        """
        self.llm = llm
        self.max_questions = max_questions
        self.language = language
        self.max_chunk_chars = max_chunk_chars
        self._prompt_template = (
            CHUNK_QUESTION_PROMPT if language == "ko" else CHUNK_QUESTION_PROMPT_EN
        )

    def _parse_response(self, response_text: str) -> List[str]:
        """LLM 응답에서 질문 리스트 파싱."""
        try:
            # JSON 배열 추출 시도
            # 응답에 마크다운 코드블록이 있을 수 있음
            text = response_text.strip()

            # ```json ... ``` 또는 ``` ... ``` 제거
            if "```" in text:
                match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
                if match:
                    text = match.group(1).strip()

            # JSON 배열 파싱
            questions = json.loads(text)

            if isinstance(questions, list):
                # 문자열만 필터링하고 빈 문자열 제거
                return [
                    q.strip() for q in questions if isinstance(q, str) and q.strip()
                ]

            return []
        except json.JSONDecodeError:
            # JSON 파싱 실패 시 줄 단위로 분리 시도
            log.warning(
                "Failed to parse JSON response, attempting line-by-line parsing"
            )
            lines = response_text.strip().split("\n")
            questions = []
            for line in lines:
                line = line.strip()
                # 번호 제거 (1. 질문, - 질문 등)
                line = re.sub(r"^[\d\.\-\*\)\]]+\s*", "", line)
                # 따옴표 제거
                line = line.strip("\"'")
                if line and len(line) > 5:  # 최소 길이 필터
                    questions.append(line)
            return questions[: self.max_questions]

    async def generate(
        self,
        chunk_text: str,
        filename: str = "",
    ) -> str:
        """
        단일 청크에 대한 질의예시 생성.

        Args:
            chunk_text: 청크 텍스트
            filename: 파일명 (컨텍스트용)

        Returns:
            str: 개행으로 구분된 질의예시 문자열
        """
        # 청크 텍스트 길이 제한
        truncated_chunk = chunk_text[: self.max_chunk_chars]
        if len(chunk_text) > self.max_chunk_chars:
            truncated_chunk += "\n... (truncated)"

        prompt = self._prompt_template.format(
            chunk_content=truncated_chunk,
            filename=filename or "Unknown",
            max_count=self.max_questions,
        )

        try:
            from extension_modules.utils.llm import ainvoke_temperature_safe

            response = await ainvoke_temperature_safe(
                self.llm,
                [HumanMessage(content=prompt)],
                max_retries=MAX_LLM_RETRIES,
            )
            questions = self._parse_response(response.content)

            # 최대 개수 제한
            questions = questions[: self.max_questions]

            log.debug(f"Generated {len(questions)} questions for chunk")
            return "\n".join(questions)
        except Exception as e:
            log.exception(f"Error generating questions: {e}")
            return ""

    async def generate_batch(
        self,
        chunks: List[str],
        filename: str = "",
        concurrency: int = 5,
    ) -> List[str]:
        """
        여러 청크에 대한 질의예시 배치 생성.

        Args:
            chunks: 청크 텍스트 리스트
            filename: 파일명
            concurrency: 동시 처리 수

        Returns:
            List[str]: 각 청크에 대한 질의예시 문자열 리스트
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def generate_with_semaphore(chunk: str) -> str:
            async with semaphore:
                return await self.generate(chunk, filename)

        tasks = [generate_with_semaphore(chunk) for chunk in chunks]
        # 전체 budget 초과 시 best-effort 로 빈 질의예시 반환. enrichment 는 optional
        # 이므로 retry 누적이 job 전체 timeout 을 유발해 청크 저장까지 막지 않게 한다.
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=ENRICH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning(
                "Question generation exceeded %ds budget (sustained rate-limit?); "
                "falling back to empty questions (%d chunks)",
                ENRICH_TIMEOUT,
                len(chunks),
            )
            return [""] * len(chunks)

        # 예외를 빈 문자열로 변환
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.error(f"Error generating questions for chunk {i}: {result}")
                processed_results.append("")
            else:
                processed_results.append(result)

        return processed_results


async def generate_chunk_questions(
    app,
    chunks: List[str],
    filename: str = "",
    model_id: Optional[str] = None,
    max_questions: Optional[int] = None,
    skip_enabled_check: bool = False,
) -> List[str]:
    """
    FastAPI app 설정을 사용하여 청크 질의예시 생성.

    Args:
        app: FastAPI application
        chunks: 청크 텍스트 리스트
        filename: 파일명
        model_id: 사용할 모델 ID (None이면 설정에서 가져옴)
        max_questions: 청크당 최대 질문 수 (None이면 설정에서 가져옴)
        skip_enabled_check: True면 전역 활성화 플래그 체크를 건너뜀 (per-KB 오버라이드 시)

    Returns:
        List[str]: 각 청크에 대한 질의예시 문자열 리스트
    """
    from extension_modules.utils.llm import create_llm_from_app

    config = app.state.config

    # 기능 활성화 확인 (per-KB 오버라이드 시 skip)
    if not skip_enabled_check and not getattr(
        config, "KB_QUESTION_GENERATION_ENABLED", False
    ):
        log.info("KB question generation is disabled")
        return [""] * len(chunks)

    # 모델 ID 결정
    if not model_id:
        model_id = getattr(config, "KB_QUESTION_GENERATION_MODEL", "")
        if not model_id:
            log.warning("KB_QUESTION_GENERATION_MODEL not configured")
            return [""] * len(chunks)

    # 최대 질문 수
    if max_questions is None:
        max_questions = getattr(config, "KB_MAX_QUESTIONS_PER_CHUNK", 10)

    # LLM 생성
    llm = create_llm_from_app(app, model_id, temperature=0.3)
    if not llm:
        log.error(f"Failed to create LLM for model: {model_id}")
        return [""] * len(chunks)

    # 질의예시 생성기 생성
    generator = ChunkQuestionGenerator(
        llm=llm,
        max_questions=max_questions,
    )

    # 배치 생성
    return await generator.generate_batch(chunks, filename)


def get_question_generator(
    app,
    model_id: Optional[str] = None,
) -> Optional[ChunkQuestionGenerator]:
    """
    FastAPI app에서 ChunkQuestionGenerator 인스턴스 생성.

    Args:
        app: FastAPI application
        model_id: 사용할 모델 ID

    Returns:
        ChunkQuestionGenerator 또는 None
    """
    from extension_modules.utils.llm import create_llm_from_app

    config = app.state.config

    if not model_id:
        model_id = getattr(config, "KB_QUESTION_GENERATION_MODEL", "")
        if not model_id:
            return None

    max_questions = getattr(config, "KB_MAX_QUESTIONS_PER_CHUNK", 10)

    llm = create_llm_from_app(app, model_id, temperature=0.3)
    if not llm:
        return None

    return ChunkQuestionGenerator(
        llm=llm,
        max_questions=max_questions,
    )
