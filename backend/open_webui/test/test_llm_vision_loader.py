"""Unit tests for ``LLMVisionLoader`` 대용량 PDF 안정화 로직.

검증 대상 (실제 Azure LLM 불필요 — fake llm 으로 오케스트레이션만 검증):
- 페이지별 지수 백오프 재시도 (transient 오류 흡수)
- 부분 성공: 일부 페이지 영구 실패 시 빈 텍스트로 두고 나머지는 보존 (전체 폐기 X)
- 동시 LLM 호출이 MAX_CONCURRENCY 를 넘지 않음
- 헤딩 레벨 정규화 apply-back (정상 / 파싱 실패 / 누락 id / 텍스트 보존 / 호출 실패)
- lazy 렌더링 경로 smoke (PyMuPDF 설치 시)
"""

import asyncio

import pytest

from open_webui.retrieval.loaders import llm_vision
from open_webui.retrieval.loaders.llm_vision import LLMVisionLoader


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """ainvoke 가 호출별로 사용자 정의 동작(반환/예외)을 수행하는 fake."""

    def __init__(self, handler):
        # handler: callable(call_index, messages) -> content(str) | raises
        self._handler = handler
        self.calls = 0

    async def ainvoke(self, messages):
        idx = self.calls
        self.calls += 1
        result = self._handler(idx, messages)
        return FakeResponse(result)


def _loader():
    return LLMVisionLoader(app=None, model_id="fake-model")


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """재시도 백오프 sleep 을 0 으로 만들어 테스트를 빠르게."""
    monkeypatch.setattr(llm_vision, "RETRY_BASE_DELAY", 0.0)


# --------------------------------------------------------------------------- #
# 재시도
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_retry_succeeds_after_transient_failure():
    def handler(idx, _messages):
        if idx == 0:
            raise ConnectionError("All connection attempts failed")
        return "page text"

    llm = FakeLLM(handler)
    loader = _loader()

    text = await loader._extract_page_with_retry(llm, b"img", page_num=1)

    assert text == "page text"
    assert llm.calls == 2  # 1차 실패 + 2차 성공


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_runtime_error():
    def handler(_idx, _messages):
        raise ConnectionError("boom")

    llm = FakeLLM(handler)
    loader = _loader()

    with pytest.raises(RuntimeError):
        await loader._extract_page_with_retry(llm, b"img", page_num=3)

    assert llm.calls == llm_vision.MAX_RETRIES


# --------------------------------------------------------------------------- #
# 부분 성공
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_partial_success_keeps_other_pages(monkeypatch):
    loader = _loader()
    # 렌더링은 더미로 대체 (fitz 불필요)
    monkeypatch.setattr(loader, "_render_page", lambda doc, idx: b"x")

    async def fake_extract_page(_llm, _img, page_num):
        if page_num == 2:
            raise ConnectionError("page 2 always fails")
        return f"page{page_num}"

    monkeypatch.setattr(loader, "_extract_page", fake_extract_page)

    pages = await loader._extract_all_pages(llm=object(), doc=None, page_count=4)

    # 2페이지만 빈 문자열, 나머지는 보존, 예외는 전파되지 않음
    assert pages == ["page1", "", "page3", "page4"]


# --------------------------------------------------------------------------- #
# 동시성 상한
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_concurrency_capped_at_max(monkeypatch):
    loader = _loader()
    monkeypatch.setattr(loader, "_render_page", lambda doc, idx: b"x")

    state = {"current": 0, "max": 0}

    async def fake_extract_page(_llm, _img, _page_num):
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(0.01)
        state["current"] -= 1
        return "ok"

    monkeypatch.setattr(loader, "_extract_page", fake_extract_page)

    pages = await loader._extract_all_pages(llm=object(), doc=None, page_count=20)

    assert len(pages) == 20
    assert all(p == "ok" for p in pages)
    assert state["max"] <= llm_vision.MAX_CONCURRENCY


# --------------------------------------------------------------------------- #
# 헤딩 레벨 정규화
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_normalize_headings_applies_levels():
    # id0 = "# Title"(level1), id1 = "## Section"(level2)
    pages = ["# Title\nbody one", "## Section\nbody two"]

    # 응답: id1 을 level 3 으로 승격, 텍스트는 그대로
    llm = FakeLLM(lambda idx, msgs: "0\t1\n1\t3")
    loader = _loader()

    result = await loader._normalize_heading_levels(llm, pages)

    assert result[0] == "# Title\nbody one"  # 변화 없음
    assert result[1] == "### Section\nbody two"  # ## → ###, 텍스트 보존


@pytest.mark.asyncio
async def test_normalize_headings_missing_id_keeps_original():
    pages = ["# Title\nx", "## Section\ny"]
    # id1 매핑 누락 → id1 은 원본 유지, id0 만 변경
    llm = FakeLLM(lambda idx, msgs: "0\t2")
    loader = _loader()

    result = await loader._normalize_heading_levels(llm, pages)

    assert result[0] == "## Title\nx"  # # → ##
    assert result[1] == "## Section\ny"  # 누락 → 원본 유지


@pytest.mark.asyncio
async def test_normalize_headings_unparseable_returns_original():
    pages = ["# Title\nx", "## Section\ny"]
    llm = FakeLLM(lambda idx, msgs: "그냥 잡담, 숫자 없음")
    loader = _loader()

    result = await loader._normalize_heading_levels(llm, pages)

    assert result == pages  # 파싱 실패 → 원본 그대로


@pytest.mark.asyncio
async def test_normalize_headings_skips_when_too_few_headings():
    pages = [
        "only one # is inline not a heading\n## just one heading",
        "no heading here",
    ]
    # 헤딩이 1개뿐(라인 시작 ## 하나) → LLM 호출 없이 원본 반환
    called = {"n": 0}

    def handler(idx, msgs):
        called["n"] += 1
        return "0\t1"

    llm = FakeLLM(handler)
    loader = _loader()

    result = await loader._normalize_heading_levels(llm, pages)

    assert result == pages
    assert called["n"] == 0  # LLM 미호출


@pytest.mark.asyncio
async def test_normalize_headings_call_failure_returns_original():
    pages = ["# A\nx", "## B\ny"]

    def handler(idx, msgs):
        raise TimeoutError("normalize call timed out")

    llm = FakeLLM(handler)
    loader = _loader()

    result = await loader._normalize_heading_levels(llm, pages)

    assert result == pages  # 호출 실패 → graceful degrade


# --------------------------------------------------------------------------- #
# lazy 렌더링 경로 smoke (PyMuPDF 설치 시에만)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_render_and_extract_lazy_path(monkeypatch, tmp_path):
    fitz = pytest.importorskip("fitz")

    # 2페이지 PDF 생성
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Hello page {i + 1}")
    doc.save(str(pdf_path))
    doc.close()

    loader = _loader()

    # 실제 렌더링은 수행하되 LLM 호출만 더미로 (page_num 마커 반환)
    async def fake_extract_page(_llm, img_bytes, page_num):
        assert isinstance(img_bytes, (bytes, bytearray)) and len(img_bytes) > 0
        return f"PAGE-{page_num}"

    monkeypatch.setattr(loader, "_extract_page", fake_extract_page)

    opened = loader._open_pdf(str(pdf_path))
    try:
        pages = await loader._extract_all_pages(
            llm=object(), doc=opened, page_count=opened.page_count
        )
    finally:
        opened.close()

    assert pages == ["PAGE-1", "PAGE-2"]


# --------------------------------------------------------------------------- #
# 경계 보정 가드 (구조적 라인은 병합하지 않음)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_boundary_fix_skips_structural_lines():
    # 앞 페이지가 헤딩으로 끝나고 뒤 페이지가 노트(*)로 시작 → 병합 안 함, LLM 미호출
    pages = [
        "body text\n### 11.10 Delivery Schedule",
        "*Supply condition is DDP\n\n| a | b |",
    ]
    called = {"n": 0}

    def handler(idx, msgs):
        called["n"] += 1
        return "merged"

    llm = FakeLLM(handler)
    loader = _loader()

    result = await loader._fix_page_boundaries(llm, pages)

    assert result == pages  # 구조적 경계 → 원본 유지
    assert called["n"] == 0  # LLM 미호출


@pytest.mark.asyncio
async def test_boundary_fix_merges_prose():
    # 산문 문장이 페이지 경계에서 잘림 → 병합 시도 (LLM 호출)
    pages = ["The delivery shall be made in", "accordance with the schedule."]
    called = {"n": 0}

    def handler(idx, msgs):
        called["n"] += 1
        return "The delivery shall be made in\naccordance with the schedule."

    llm = FakeLLM(handler)
    loader = _loader()

    await loader._fix_page_boundaries(llm, pages)

    assert called["n"] == 1  # 산문 경계 → LLM 호출됨
