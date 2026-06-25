"""
LLM Vision 기반 문서 추출기.

PDF/이미지 문서를 LLM Vision 모델에 보내 마크다운 텍스트로 추출한다.
3단계 처리: 1차 페이지별 추출 → 2차 페이지 경계 보정 → 3차 헤딩 레벨 정규화.

대용량 PDF 안정성:
- 페이지별 LLM 호출을 Semaphore(MAX_CONCURRENCY)로 상한 → connection pool /
  Azure 배포 동시연결·RPM 한도 초과 방지
- 페이지별 지수 백오프 재시도 + gather(return_exceptions=True) → transient 오류를
  흡수하고, 최종 실패한 페이지만 빈 텍스트로 두는 부분 성공 (1페이지 실패로 전체 폐기 X)
- PNG 렌더링을 세마포어 슬롯 진입 시점에 lazy 수행 → 메모리 상주 PNG ≤ MAX_CONCURRENCY
- per-call timeout + 페이지 수 기반 backstop timeout 을 로더가 내부적으로 관리
"""

import asyncio
import base64
import logging
import re
from typing import Optional

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["RAG"])

# 동시 LLM 호출 상한 (contextual_chunking.py / question_generator.py 와 동일 컨벤션).
# 근본 크래시 원인은 Azure 배포 동시연결/RPM 한도 초과이므로 동시성을 낮게 묶는다.
MAX_CONCURRENCY = 5
# 페이지별 추출 실패 시 재시도 횟수 (transient ConnectError/ReadError 흡수).
MAX_RETRIES = 3
# 재시도 지수 백오프 기본 지연(초): delay = RETRY_BASE_DELAY * 2 ** (attempt - 1)
RETRY_BASE_DELAY = 2.0
# 페이지당 LLM 호출 상한(초) — 단일 호출이 무한정 매달리는 것을 차단.
PER_CALL_TIMEOUT = 120
# 경계 보정 LLM 호출 상한(초).
BOUNDARY_CALL_TIMEOUT = 60
# 헤딩 정규화 LLM 호출 상한(초).
NORMALIZE_TIMEOUT = 120
# 전체 추출 backstop 상한(초) = max(MIN_OVERALL_TIMEOUT, page_count * OVERALL_TIMEOUT_PER_PAGE).
# 실제 제어는 per-call timeout 이 담당하고, 이 값은 비정상적으로 멈춘 작업을 끊기 위한
# 여유 있는 안전망일 뿐이다.
OVERALL_TIMEOUT_PER_PAGE = 20
MIN_OVERALL_TIMEOUT = 600
# 헤딩 정규화에 보낼 outline 의 최대 길이(chars). 초과하면 정규화를 건너뛴다.
MAX_OUTLINE_CHARS = 40000

_HEADING_RE = re.compile(r"^(#{1,6})\s")


def _is_structural_line(line: str) -> bool:
    """헤딩/표/리스트/blockquote/노트 등 구조적 마크다운 라인인지 여부.

    경계 보정(_fix_page_boundaries) 전용 헬퍼. 경계 보정은 '페이지 끝에서 잘린 산문
    문장' 만 이어붙여야 한다. 헤딩(#), 표(|), 리스트/노트(* - + •), 인용(>) 같은
    구조적 라인은 잘린 문장이 아니므로 병합 대상에서 제외해, 헤딩에 다음 페이지 노트가
    빨려 들어가는 오병합을 막는다.

    NOTE: 경계 보정은 현재 파이프라인에서 비활성 (aload 참조). 재활성화 대비 보존.
    """
    s = line.lstrip()
    if not s:
        return True
    return s[0] in "#|>*-+•"


DEFAULT_EXTRACTION_PROMPT = """\
Extract all text content from this document page as markdown.
Preserve the structure: headings, lists, tables, paragraphs.
For tables, use markdown table format.
For any informative image, diagram, technical drawing, chart, or figure on the page, write a concise description of what it shows in place, where it appears in the reading order. Prefix each such description with "[Figure] " and write it in the same language as the document. Describe the key components, labels, axes, values, and relationships; do NOT skip an informative figure just because it contains little or no text. Do NOT emit a [Figure] line for logos, decorative rules, watermarks, or other page furniture, and emit no [Figure] line when the page has no such figure.
Do NOT add any HTML comments (<!-- -->) such as PageBreak, PageNumber, PageHeader, or similar markers.
Do NOT add page numbers or headers/footers that appear as decorative elements.
Output ONLY the extracted text, no commentary."""

BOUNDARY_FIX_PROMPT = """\
Below are the end of page {n} and the start of page {n1}.
If a sentence is cut off at the page boundary, merge them into one continuous sentence.
If they are independent, return them as-is.
Return ONLY the corrected boundary text (the merged ending and beginning), nothing else.

--- END OF PAGE {n} ---
{end_text}

--- START OF PAGE {n1} ---
{start_text}"""

HEADING_NORMALIZE_PROMPT = """\
The following is the heading outline of a multi-page document. Each page was \
extracted independently, so the heading levels (number of leading # marks) may be \
inconsistent across pages. Re-assign a single, coherent hierarchical level (an \
integer 1-6) to every heading so the document has a consistent outline.

Rules:
- Do NOT change, translate, or rephrase the heading text.
- Do NOT add or remove headings.
- Output exactly one line per heading, in the same order, in the format "<id>\t<level>"
  where <id> is the integer id shown in brackets and <level> is an integer 1-6.
- Output ONLY those lines, nothing else.

Outline:
{outline}"""


class LLMVisionLoader:
    """LLM Vision 기반 문서 추출기 (3단계 처리)."""

    def __init__(
        self,
        app,
        model_id: str,
        prompt: str = "",
        normalize_headings: bool = True,
    ):
        self.app = app
        self.model_id = model_id
        self.prompt = prompt or DEFAULT_EXTRACTION_PROMPT
        self.normalize_headings = normalize_headings

    async def aload(
        self,
        filename: str,
        file_content_type: Optional[str],
        file_path: str,
    ) -> list[Document]:
        """PDF/이미지 파일에서 텍스트 추출 (async)."""
        from extension_modules.utils.llm import create_llm_from_app

        llm = create_llm_from_app(self.app, self.model_id)
        if not llm:
            raise ValueError(f"LLM Vision model not found: {self.model_id}")

        # 이미지 파일인 경우 단일 이미지로 처리 (단일 호출은 all-or-nothing 이 자연스러움)
        if file_content_type and file_content_type.startswith("image/"):
            text = await self._extract_single_image(llm, file_path)
            return [
                Document(
                    page_content=text,
                    metadata={
                        "source": filename,
                        "page": 0,
                    },
                )
            ]

        # PDF: 페이지 수만 먼저 확인하고, 이미지는 추출 시점에 페이지별 lazy 렌더링
        doc = self._open_pdf(file_path)
        try:
            page_count = doc.page_count
            if page_count == 0:
                raise ValueError(f"Failed to convert file to images: {filename}")

            log.info(f"LLM Vision: extracting {page_count} pages from {filename}")

            # per-call timeout 이 실제 제어, overall 은 비정상 hang 을 끊기 위한 안전망
            overall_timeout = max(
                MIN_OVERALL_TIMEOUT, page_count * OVERALL_TIMEOUT_PER_PAGE
            )
            pages = await asyncio.wait_for(
                self._extract_all_pages(llm, doc, page_count),
                timeout=overall_timeout,
            )
        finally:
            doc.close()

        # 2차: 페이지 경계 보정 — 2026-05-22 비활성화 (메서드 _fix_page_boundaries 에 보존)
        #
        # 인접 페이지의 끊긴 문장을 LLM 으로 이어붙이는 단계였으나 비용 대비 효과가 낮아 제거:
        #   - 청크는 페이지별(split_documents)로 생성되어 경계 보정이 검색 단위(청크)를
        #     바꾸지 않음. 경계 문맥은 CHUNK_OVERLAP 으로 이미 일부 커버된다.
        #   - 페이지 수 - 1 번의 순차 LLM 호출이라 대용량 PDF 처리 시간의 큰 부분을 차지하고
        #     (218p ≈ 217 콜) task_queue timeout 을 유발했다.
        #   - 헤딩/표/노트를 잘린 문장으로 오인해 병합하는 사고도 있었다 (_is_structural_line
        #     가드로 완화했으나 근본적으로 구조 손상 위험).
        # 서술형(표/헤딩이 적은) 문서에서 필요하면 _fix_page_boundaries 를 다시 호출하면 된다.
        # if len(pages) > 1:
        #     pages = await self._fix_page_boundaries(llm, pages)

        # 3차: 헤딩 레벨 정규화 (페이지별 독립 추출로 인한 ##/### 불일치 보정)
        if self.normalize_headings and len(pages) > 1:
            pages = await self._normalize_heading_levels(llm, pages)

        # Document 리스트 생성
        docs = []
        for i, text in enumerate(pages):
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": filename,
                        "page": i,
                    },
                )
            )
        return docs

    def _open_pdf(self, file_path: str):
        """PDF 파일을 PyMuPDF Document 로 연다 (페이지는 lazy 렌더링)."""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError(
                "PyMuPDF (fitz) is required for LLM Vision PDF extraction"
            )
        return fitz.open(file_path)

    def _render_page(self, doc, page_index: int) -> bytes:
        """단일 페이지 → PNG bytes (PyMuPDF, CPU-bound). to_thread 로 호출됨.

        fitz Document 는 thread-safe 하지 않으므로 호출자가 lock 으로 직렬 접근을 보장한다.
        """
        import fitz

        page = doc[page_index]
        # 2x 해상도로 렌더링 (~144 DPI 수준)
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")

    async def _extract_all_pages(self, llm, doc, page_count: int) -> list[str]:
        """모든 페이지를 동시성 상한 하에 추출 (lazy 렌더링 + 재시도 + 부분 성공)."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        render_lock = asyncio.Lock()  # fitz Document 는 thread-safe 하지 않음

        async def extract_one(page_index: int) -> str:
            async with semaphore:
                # PNG 를 이 시점에 렌더링 → 동시에 최대 MAX_CONCURRENCY 개만 메모리 상주.
                # 렌더링은 CPU-bound 이므로 to_thread 로 이벤트 루프를 막지 않고,
                # doc 접근은 lock 으로 직렬화한다.
                async with render_lock:
                    img_bytes = await asyncio.to_thread(
                        self._render_page, doc, page_index
                    )
                return await self._extract_page_with_retry(
                    llm, img_bytes, page_index + 1
                )

        results = await asyncio.gather(
            *[extract_one(i) for i in range(page_count)],
            return_exceptions=True,
        )

        pages: list[str] = []
        failed_pages: list[int] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_pages.append(i + 1)
                pages.append("")  # 부분 성공: 실패 페이지는 빈 텍스트로 둔다
            else:
                pages.append(result)

        if failed_pages:
            log.warning(
                f"LLM Vision: {len(failed_pages)}/{page_count} pages failed after "
                f"{MAX_RETRIES} retries (model={self.model_id}): pages {failed_pages}"
            )
        log.info(
            f"LLM Vision: {page_count - len(failed_pages)}/{page_count} pages extracted"
        )
        return pages

    def _image_to_base64_url(self, image_bytes: bytes) -> str:
        """이미지 bytes → data URL."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    async def _extract_single_image(self, llm, file_path: str) -> str:
        """단일 이미지 파일에서 텍스트 추출 (재시도 포함, 최종 실패 시 raise)."""
        with open(file_path, "rb") as f:
            image_bytes = f.read()
        return await self._extract_page_with_retry(llm, image_bytes, 1)

    async def _extract_page(self, llm, image_bytes: bytes, page_num: int) -> str:
        """1차: 단일 페이지 이미지 → LLM → 마크다운 텍스트 (1회 시도).

        실패 시 예외를 propagate 한다. 재시도/부분 성공은 호출자가 처리한다.
        """
        data_url = self._image_to_base64_url(image_bytes)

        message = HumanMessage(
            content=[
                {"type": "text", "text": self.prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                },
            ]
        )

        response = await asyncio.wait_for(
            llm.ainvoke([message]), timeout=PER_CALL_TIMEOUT
        )

        content = response.content if hasattr(response, "content") else str(response)
        # Some providers return list of content blocks (Gemini/Vertex)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        return content or ""

    async def _extract_page_with_retry(
        self, llm, image_bytes: bytes, page_num: int
    ) -> str:
        """페이지 추출 + transient 오류 재시도 (지수 백오프). 모든 재시도 소진 시 예외."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await self._extract_page(llm, image_bytes, page_num)
            except asyncio.CancelledError:
                raise  # 취소는 재시도하지 않고 그대로 전파
            except Exception as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    log.warning(
                        f"LLM Vision page {page_num} attempt {attempt}/{MAX_RETRIES} "
                        f"failed (model={self.model_id}), retrying in {delay:.0f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    log.error(
                        f"LLM Vision page {page_num} failed after {MAX_RETRIES} "
                        f"attempts (model={self.model_id}): {e}",
                        exc_info=True,
                    )
        raise RuntimeError(
            f"LLM Vision page {page_num} extraction failed after {MAX_RETRIES} "
            f"attempts (model={self.model_id}): {last_exc}"
        ) from last_exc

    async def _fix_page_boundaries(self, llm, pages: list[str]) -> list[str]:
        """2차: 인접 페이지 경계의 끊긴 문장 감지 및 보정.

        NOTE: 2026-05-22 부터 aload 파이프라인에서 호출하지 않는다 (비용 대비 효과 +
        대용량 PDF timeout 문제 — aload 의 비활성화 주석 참조). 메서드는 재활성화 및
        단위 테스트 대상으로 보존한다. 호출 시 페이지 수 - 1 번의 순차 LLM 호출이 발생한다.
        """
        result = list(pages)
        num_lines = 3  # 경계 확인에 사용할 줄 수

        for i in range(len(pages) - 1):
            end_lines = pages[i].strip().split("\n")
            start_lines = pages[i + 1].strip().split("\n")

            end_text = "\n".join(end_lines[-num_lines:])
            start_text = "\n".join(start_lines[:num_lines])

            # 경계가 비어있으면 건너뜀
            if not end_text.strip() or not start_text.strip():
                continue

            # 경계에 인접한 라인(앞 페이지 마지막 / 뒤 페이지 첫 줄)이 헤딩·표·리스트
            # 등 구조적 요소이면 '잘린 문장' 이 아니므로 병합하지 않는다 (오병합 방지).
            if _is_structural_line(end_lines[-1]) or _is_structural_line(
                start_lines[0]
            ):
                continue

            prompt = BOUNDARY_FIX_PROMPT.format(
                n=i + 1,
                n1=i + 2,
                end_text=end_text,
                start_text=start_text,
            )

            try:
                response = await asyncio.wait_for(
                    llm.ainvoke([HumanMessage(content=prompt)]),
                    timeout=BOUNDARY_CALL_TIMEOUT,
                )
                fixed = (
                    response.content if hasattr(response, "content") else str(response)
                )

                # 보정된 텍스트를 원본에 반영
                # 끝 페이지의 마지막 줄들을 교체하고, 시작 페이지의 첫 줄들을 교체
                fixed_parts = fixed.strip().split("\n")
                if len(fixed_parts) >= 2:
                    # 경계 영역만 교체
                    mid = len(fixed_parts) // 2
                    new_end = fixed_parts[:mid]
                    new_start = fixed_parts[mid:]

                    # 원본의 앞부분 유지 + 수정된 끝부분
                    result[i] = "\n".join(end_lines[:-num_lines] + new_end)
                    # 수정된 시작부분 + 원본의 뒷부분 유지
                    result[i + 1] = "\n".join(new_start + start_lines[num_lines:])
            except Exception as e:
                log.warning(
                    f"Page boundary fix failed between page {i + 1} and {i + 2}: {e}"
                )
                # 보정 실패 시 원본 유지

        return result

    async def _normalize_heading_levels(self, llm, pages: list[str]) -> list[str]:
        """3차: 페이지별 독립 추출로 인한 헤딩 레벨(##, ###) 불일치를 LLM 으로 정규화.

        전체 텍스트 대신 헤딩 outline 만 LLM 에 보내고, 응답으로 받은 level 만
        각 헤딩 라인에 방어적으로 반영한다 (텍스트는 보존). 실패 시 원본을 그대로 둔다.
        """
        # (page_index, line_index, level, text) 형태로 모든 헤딩 수집
        headings: list[tuple[int, int, int, str]] = []
        page_lines: list[list[str]] = []
        for p_idx, page in enumerate(pages):
            lines = page.split("\n")
            page_lines.append(lines)
            for l_idx, line in enumerate(lines):
                m = _HEADING_RE.match(line)
                if m:
                    level = len(m.group(1))
                    text = line[m.end() :].strip()
                    headings.append((p_idx, l_idx, level, text))

        # 헤딩이 거의 없으면 정규화할 게 없음
        if len(headings) < 2:
            return pages

        outline_lines = [
            f"[{hid}] {'#' * level} {text}"
            for hid, (_, _, level, text) in enumerate(headings)
        ]
        outline = "\n".join(outline_lines)
        if len(outline) > MAX_OUTLINE_CHARS:
            log.info(
                f"LLM Vision: heading outline too large "
                f"({len(outline)} chars > {MAX_OUTLINE_CHARS}), skipping normalization"
            )
            return pages

        try:
            response = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        HumanMessage(
                            content=HEADING_NORMALIZE_PROMPT.format(outline=outline)
                        )
                    ]
                ),
                timeout=NORMALIZE_TIMEOUT,
            )
            raw = response.content if hasattr(response, "content") else str(response)
            if isinstance(raw, list):
                raw = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw
                )
        except Exception as e:
            log.warning(f"LLM Vision heading normalization call failed: {e}")
            return pages

        # 응답 파싱: "<id>\t<level>" 라인 → {id: level}
        new_levels: dict[int, int] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"[\t\s]+", line, maxsplit=1)
            if len(parts) != 2:
                continue
            try:
                hid = int(parts[0].strip().lstrip("[").rstrip("]"))
                level = int(parts[1].strip())
            except ValueError:
                continue
            if 1 <= level <= 6:
                new_levels[hid] = level

        if not new_levels:
            log.warning(
                "LLM Vision heading normalization: no parseable levels in response"
            )
            return pages

        # 방어적 apply-back: 헤딩 라인의 # 개수만 새 level 로 치환, 텍스트는 보존.
        # 매핑이 없는 헤딩은 원본 level 유지.
        applied = 0
        for hid, (p_idx, l_idx, old_level, _) in enumerate(headings):
            new_level = new_levels.get(hid)
            if new_level is None or new_level == old_level:
                continue
            line = page_lines[p_idx][l_idx]
            m = _HEADING_RE.match(line)
            if not m:
                continue  # 안전장치: 라인이 예상과 다르면 건드리지 않음
            rest = line[m.end() - 1 :]  # 헤딩 마커 뒤(공백 포함) 텍스트 보존
            page_lines[p_idx][l_idx] = ("#" * new_level) + rest
            applied += 1

        if applied:
            log.info(f"LLM Vision: normalized {applied}/{len(headings)} heading levels")
        return ["\n".join(lines) for lines in page_lines]
