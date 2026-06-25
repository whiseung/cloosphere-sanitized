"""create_presentation — Presenton 기반 PPT 생성 툴 (편집 가능 PPTX).

별도 docker 로 뜬 Presenton 서비스의 REST API 를 호출해 디자인된 .pptx 를 만들고,
결과 파일을 Cloosphere Storage/Files 에 ingest 한 뒤 다운로드 링크를 반환한다.

설계 메모:
- REST 직접 호출 → Presenton 내장 MCP 서버의 60s 내부 타임아웃을 우회. MCP tool_connection
  방식과 달리 결과 파일을 save_to_files 로 Cloosphere Files 에 등록 → 채팅 네이티브 다운로드 칩.
- **async 도구**: 비동기 생성(`/generate/async`) + 상태 폴링(`/status/{id}`)으로 단계별 진행상황을
  event_emitter(Socket.IO)로 사용자에게 실시간 표시. event_emitter 가 없거나 async 미지원이면
  sync `/generate` 로 폴백 (asyncio.to_thread 로 이벤트루프 비차단).
- 타임아웃은 PRESENTON_TIMEOUT(설정값)을 전체 폴링 budget 으로 사용.
"""

import asyncio
import logging
import time
import uuid
from io import BytesIO
from typing import Optional

import httpx
from extension_modules.tools.document._common import (
    format_tool_response,
    save_to_files,
)
from extension_modules.tools.document.pptx_tool import PPTX_MIME
from langchain_core.tools import StructuredTool
from open_webui.config import (
    PRESENTON_BASE_URL,
    PRESENTON_DEFAULT_TEMPLATE,
    PRESENTON_TIMEOUT,
)
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT_S = 60.0
_POLL_HTTP_TIMEOUT_S = 15.0  # 개별 폴링/요청 타임아웃 (전체 budget 과 별개)
_POLL_INTERVAL_S = 2.0

# Presenton 비동기 생성 단계 메시지 → 사용자 표시용 한글 라벨. 미매핑 메시지는 원문 노출.
_STAGE_LABELS = {
    "Queued for generation": "생성 대기 중…",
    "Generating presentation outlines": "발표 개요 생성 중…",
    "Selecting layout for each slide": "슬라이드 레이아웃 선택 중…",
    "Generating slides": "슬라이드 생성 중…",
    "Fetching assets for slides": "이미지·자료 준비 중…",
    "Exporting presentation": "PPTX 내보내는 중…",
    "Presentation generation completed": "생성 완료",
}

_TEMPLATES = ("general", "modern", "standard", "swift")
_TONES = (
    "default",
    "casual",
    "professional",
    "funny",
    "educational",
    "sales_pitch",
)
_VERBOSITY = ("concise", "standard", "text-heavy")


class _AsyncUnavailable(Exception):
    """Presenton 이 /generate/async 를 지원하지 않을 때 (404/405) → sync 폴백 트리거."""


def _base_url() -> str:
    return (PRESENTON_BASE_URL.value or "http://localhost:5001").rstrip("/")


def _budget_s() -> float:
    """전체 생성 폴링 budget(초). PRESENTON_TIMEOUT 설정값, 가드 폴백 600."""
    try:
        v = int(PRESENTON_TIMEOUT.value)
        return float(v) if v > 0 else 600.0
    except (TypeError, ValueError):
        return 600.0


# 템플릿 목록 캐시 (id/name 은 자주 안 바뀜) — (fetched_at, [{"id","name"}]).
_TEMPLATE_CACHE: tuple[float, list[dict]] | None = None
_TEMPLATE_TTL_S = 120.0


def _fetch_templates() -> list[dict]:
    """Presenton 의 사용 가능한 템플릿(내장+커스텀) 목록. 실패 시 빈 list.

    내장(general/modern/standard/swift)은 id==name, 커스텀은 uuid id + 사람이 정한 name.
    """
    global _TEMPLATE_CACHE
    now = time.monotonic()
    if _TEMPLATE_CACHE and now - _TEMPLATE_CACHE[0] < _TEMPLATE_TTL_S:
        return _TEMPLATE_CACHE[1]
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{_base_url()}/api/v1/ppt/template/all")
        items = resp.json() if resp.status_code == 200 else []
        templates = [
            {"id": str(t.get("id")), "name": str(t.get("name") or t.get("id"))}
            for t in items
            if isinstance(t, dict) and t.get("id")
        ]
    except Exception as e:  # noqa: BLE001 — 네트워크/파싱 실패는 빈 목록으로
        log.warning("Presenton 템플릿 목록 조회 실패: %s", e)
        templates = []
    _TEMPLATE_CACHE = (now, templates)
    return templates


def _resolve_template(value: Optional[str]) -> str:
    """사용자/LLM 이 준 template 값을 Presenton 이 기대하는 형태로 변환.

    - 미지정 → PRESENTON_DEFAULT_TEMPLATE 설정값 (없으면 'general')
    - 내장 이름(general 등) / 'custom-<id>' → 그대로
    - 커스텀 템플릿의 name 또는 id → 그 id (이미 'custom-<uuid>' 형태라 접두 중복 금지)
    - 매칭 실패 → 'general'
    """
    if not value:
        value = PRESENTON_DEFAULT_TEMPLATE.value or "general"
    v = str(value).strip()
    if v in _TEMPLATES or v.startswith("custom-"):
        return v
    for t in _fetch_templates():
        if v == t["id"] or v.lower() == t["name"].lower():
            return t["id"]
    return "general"


def _templates_hint() -> str:
    """tool description 에 붙일 사용 가능 템플릿 안내."""
    customs = [t for t in _fetch_templates() if t["id"] not in _TEMPLATES]
    if not customs:
        return ""
    listed = "; ".join(f"'{t['name']}' ({t['id']})" for t in customs[:12])
    return (
        " Custom templates extracted from real decks are also available — pass the "
        f"template name to match a company/brand style: {listed}."
    )


class PresentationContent(BaseModel):
    content: str = Field(
        ...,
        description=(
            "발표자료에 담을 핵심 내용/주제. 지식기반·DB 등에서 모은 사실을 충분히 풀어서 "
            "넣을수록 슬라이드 품질이 올라간다."
        ),
    )
    filename: str = Field(
        "presentation",
        description="확장자 제외 파일명 (한글/영문 가능).",
    )
    instructions: Optional[str] = Field(
        None,
        description="구성·강조점 등 추가 지시 (예: '첫 장은 핵심 요약, 마지막은 결론').",
    )
    n_slides: Optional[int] = Field(
        None, ge=1, le=30, description="슬라이드 수. 생략 시 모델이 자동 결정."
    )
    language: Optional[str] = Field(
        "Korean", description="발표자료 언어 (예: Korean, English)."
    )
    template: Optional[str] = Field(
        None,
        description=(
            f"디자인 템플릿. 택1: {', '.join(_TEMPLATES)} (또는 custom-<id> / 커스텀 템플릿 이름). "
            "생략 시 관리자 기본 템플릿 사용."
        ),
    )
    use_attached_template: bool = Field(
        False,
        description=(
            "사용자가 채팅에 .pptx 파일을 첨부하고 '이 PPT 디자인으로/이 템플릿으로 만들어줘' "
            "처럼 첨부 파일을 디자인 템플릿으로 쓰라고 명시한 경우에만 True. "
            "True 면 첨부 .pptx 의 마스터/레이아웃을 on-the-fly 로 Presenton 커스텀 템플릿으로 "
            "추출해 사용한다 (추출 1-3분 추가). True 시 `template` 필드는 무시된다."
        ),
    )
    tone: str = Field(
        "professional",
        description=f"문체 톤. 택1: {', '.join(_TONES)}.",
    )
    verbosity: str = Field(
        "standard",
        description=f"분량. 택1: {', '.join(_VERBOSITY)}.",
    )


def _build_payload(c: PresentationContent) -> dict:
    payload: dict = {
        "content": c.content,
        "template": _resolve_template(c.template),
        "tone": c.tone if c.tone in _TONES else "professional",
        "verbosity": c.verbosity if c.verbosity in _VERBOSITY else "standard",
        "export_as": "pptx",
        "include_title_slide": True,
    }
    if c.instructions:
        payload["instructions"] = c.instructions
    if c.n_slides:
        payload["n_slides"] = c.n_slides
    if c.language:
        payload["language"] = c.language
    return payload


def _find_attached_pptx(attached_files: list[str]) -> Optional[tuple[bytes, str]]:
    """attached_files(file_id 목록) 중 첫 .pptx 를 찾아 (bytes, filename) 반환.

    없으면 None. 파일 행/스토리지 접근 실패는 None 으로 흡수 (LLM 에 친화적 메시지).
    """
    if not attached_files:
        return None
    try:
        from open_webui.models.files import Files
        from open_webui.storage.provider import Storage
    except Exception as e:  # noqa: BLE001
        log.warning("Files/Storage import 실패: %s", e)
        return None

    for fid in attached_files:
        try:
            f = Files.get_file_by_id(fid)
        except Exception as e:  # noqa: BLE001
            log.warning("file_id=%s 조회 실패: %s", fid, e)
            continue
        if not f or not f.filename or not f.path:
            continue
        if not f.filename.lower().endswith(".pptx"):
            continue
        try:
            local = Storage.get_file(f.path)
            with open(local, "rb") as fh:
                return fh.read(), f.filename
        except Exception as e:  # noqa: BLE001
            log.warning("file_id=%s 읽기 실패: %s", fid, e)
            continue
    return None


async def _extract_attached_as_template(
    pptx_bytes: bytes, filename: str, event_emitter
) -> str:
    """첨부 .pptx → Presenton 커스텀 템플릿 추출 후 template_id 반환.

    document_templates 라우터의 `_build_presenton_template` 를 재사용.
    추출 1-3분 소요 → 단계별 progress emit.
    """
    # 라우터 모듈 import (Presenton 추출 코어 로직 재사용)
    from open_webui.routers.document_templates import (
        _PRESENTON_JOBS,
        _build_presenton_template,
    )

    base = _base_url()
    job_id = str(uuid.uuid4())
    _PRESENTON_JOBS[job_id] = {
        "status": "pending",
        "message": "대기 중…",
        "template_id": None,
        "error": None,
    }
    # 첨부 PPT 의 처음 5장에서 레이아웃 추출 (기본 indices).
    indices = [0, 1, 2, 3, 4]
    # 이름은 파일명 기반 (확장자 제외, 충돌 회피 위해 짧은 접미사).
    name = filename.rsplit(".", 1)[0][:64]

    await _emit_status(
        event_emitter,
        "첨부 PPT 를 템플릿으로 추출 중…",
        f"extract_start:{filename}",
    )

    # 폴링 task 와 추출 task 를 병렬로 — 폴링은 job["message"] 변화를 emit
    extract_task = asyncio.create_task(
        _build_presenton_template(base, pptx_bytes, filename, name, indices, job_id)
    )

    last_msg = None
    while not extract_task.done():
        msg = _PRESENTON_JOBS[job_id].get("message")
        if msg and msg != last_msg:
            last_msg = msg
            await _emit_status(event_emitter, msg, f"extract:{msg}")
        await asyncio.sleep(1.0)
    await extract_task  # propagate exceptions

    job = _PRESENTON_JOBS[job_id]
    if job.get("status") != "completed" or not job.get("template_id"):
        err = job.get("error") or "템플릿 추출 실패"
        raise RuntimeError(f"첨부 PPT 템플릿 추출 실패: {err}")

    template_id = str(job["template_id"])
    # 템플릿 캐시 무효화 (방금 만든 템플릿이 다음 조회에 보이도록)
    global _TEMPLATE_CACHE
    _TEMPLATE_CACHE = None
    log.info("첨부 PPT 템플릿 추출 완료: %s → template_id=%s", filename, template_id)
    await _emit_status(
        event_emitter, "템플릿 추출 완료, 발표자료 생성 시작…", "extract_done"
    )
    return template_id


async def _emit_status(event_emitter, korean: str, raw: str) -> None:
    """진행상황 status 이벤트 발행. 클라이언트 끊김 등 실패는 무시."""
    if not event_emitter:
        return
    try:
        await event_emitter(
            {
                "type": "status",
                "data": {"description": korean, "done": False, "detail": raw},
            }
        )
    except Exception as e:  # noqa: BLE001 — emit 실패해도 생성은 계속
        log.debug("presenton status emit 실패: %s", e)


async def _download_async(
    client: httpx.AsyncClient, base: str, path: str
) -> tuple[BytesIO, str]:
    url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    try:
        r = await client.get(url, timeout=_DOWNLOAD_TIMEOUT_S)
    except httpx.RequestError as e:
        raise RuntimeError(f"생성물 다운로드 실패: {e}") from e
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"생성물 다운로드 실패 (HTTP {r.status_code}) url={url}")
    return BytesIO(r.content), path.rsplit("/", 1)[-1]


async def _generate_via_presenton_async(
    content: PresentationContent, event_emitter, base: str, budget_s: float
) -> tuple[BytesIO, str]:
    """비동기 생성 + 상태 폴링 + 단계별 진행 emit. 파일 bytes + 이름 반환.

    예외: _AsyncUnavailable(async 미지원→sync 폴백), RuntimeError(실패/타임아웃).
    """
    payload = _build_payload(content)
    deadline = time.monotonic() + budget_s
    t0 = time.monotonic()

    async with httpx.AsyncClient(timeout=_POLL_HTTP_TIMEOUT_S) as client:
        try:
            resp = await client.post(
                f"{base}/api/v1/ppt/presentation/generate/async", json=payload
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Presenton 연결 실패 ({base}): {e}") from e
        if resp.status_code in (404, 405):
            raise _AsyncUnavailable()
        if resp.status_code != 200:
            raise RuntimeError(
                f"Presenton 생성 시작 실패 (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        task_id = (resp.json() or {}).get("id")
        if not task_id:
            raise RuntimeError(f"Presenton async 응답에 id 없음: {resp.text[:200]}")

        last_msg = None
        await _emit_status(event_emitter, "발표자료 생성 시작…", "started")
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"발표자료 생성이 제한시간({int(budget_s)}초)을 초과했습니다. "
                    "슬라이드 수를 줄이거나 잠시 후 다시 시도하세요."
                )
            try:
                s = await client.get(f"{base}/api/v1/ppt/presentation/status/{task_id}")
                sd = s.json()
            except (httpx.RequestError, ValueError):
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            status = sd.get("status")
            msg = sd.get("message")
            if msg and msg != last_msg:
                last_msg = msg
                await _emit_status(event_emitter, _STAGE_LABELS.get(msg, msg), msg)

            if status == "completed":
                path = (sd.get("data") or {}).get("path")
                if not path:
                    raise RuntimeError(f"생성 완료지만 path 없음: {str(sd)[:200]}")
                buf, name = await _download_async(client, base, path)
                log.info(
                    "Presenton 비동기 생성 완료: %.1fs, %d bytes, path=%s",
                    time.monotonic() - t0,
                    buf.getbuffer().nbytes,
                    path,
                )
                return buf, name
            if status == "failed":
                reason = sd.get("error") or sd.get("message") or "unknown"
                raise RuntimeError(f"발표자료 생성 실패: {reason}")

            await asyncio.sleep(_POLL_INTERVAL_S)


def _generate_via_presenton(
    content: PresentationContent, budget_s: float
) -> tuple[BytesIO, str]:
    """동기 생성(폴백) → 파일 bytes + 이름. 실패 시 RuntimeError.

    event_emitter 없거나 Presenton 이 async 미지원일 때만 사용. asyncio.to_thread 로 호출돼
    이벤트루프를 막지 않는다.
    """
    base = _base_url()
    payload = _build_payload(content)
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=budget_s) as client:
            resp = client.post(f"{base}/api/v1/ppt/presentation/generate", json=payload)
    except httpx.RequestError as e:
        raise RuntimeError(f"Presenton 연결 실패 ({base}): {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(
            f"발표자료 생성 실패 (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json()
    path = data.get("path")
    if not path:
        raise RuntimeError(f"Presenton 응답에 path 없음: {str(data)[:300]}")

    download_url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
    try:
        with httpx.Client(timeout=_DOWNLOAD_TIMEOUT_S) as client:
            file_resp = client.get(download_url)
    except httpx.RequestError as e:
        raise RuntimeError(f"생성물 다운로드 실패: {e}") from e
    if file_resp.status_code != 200 or not file_resp.content:
        raise RuntimeError(
            f"생성물 다운로드 실패 (HTTP {file_resp.status_code}) url={download_url}"
        )

    log.info(
        "Presenton 동기 생성 완료: %.1fs, %d bytes, path=%s",
        time.monotonic() - t0,
        len(file_resp.content),
        path,
    )
    return BytesIO(file_resp.content), path.rsplit("/", 1)[-1]


def make_create_presentation(
    user_id: str,
    event_emitter=None,
    attached_files: list[str] | None = None,
) -> StructuredTool:
    """user_id 에 바인딩된 async create_presentation 툴 생성 (Presenton 백엔드).

    event_emitter 가 주어지면 비동기 생성 + 단계별 진행상황을 사용자에게 표시한다.
    attached_files: 채팅 첨부 파일 ID 목록. use_attached_template=True 일 때 첫 .pptx
    를 on-the-fly 추출해 디자인 템플릿으로 사용.
    """
    attached_files = attached_files or []

    async def _create_presentation_async(**kwargs) -> str:
        content = PresentationContent(**kwargs)

        # 첨부 PPT 를 템플릿으로 사용 — 추출 후 그 template_id 로 덮어쓴다.
        if content.use_attached_template:
            found = _find_attached_pptx(attached_files)
            if not found:
                raise RuntimeError(
                    "use_attached_template=True 지만 채팅에 .pptx 첨부가 없습니다. "
                    "사용자에게 PPT 파일을 첨부해달라고 요청하거나, "
                    "기존 등록 템플릿(template 인자)을 사용하세요."
                )
            pptx_bytes, fname = found
            tid = await _extract_attached_as_template(pptx_bytes, fname, event_emitter)
            content.template = tid

        base = _base_url()
        budget = _budget_s()
        log.info(
            "create_presentation: user=%s template=%s tone=%s n_slides=%s budget=%ss",
            user_id,
            _resolve_template(content.template),
            content.tone,
            content.n_slides,
            int(budget),
        )

        if event_emitter is not None:
            try:
                buf, _name = await _generate_via_presenton_async(
                    content, event_emitter, base, budget
                )
            except _AsyncUnavailable:
                log.info("Presenton async 미지원 → sync 폴백")
                buf, _name = await asyncio.to_thread(
                    _generate_via_presenton, content, budget
                )
        else:
            buf, _name = await asyncio.to_thread(
                _generate_via_presenton, content, budget
            )

        # save_to_files 는 Storage 업로드(느릴 수 있음) → to_thread 로 비차단.
        result = await asyncio.to_thread(
            save_to_files,
            user_id,
            f"{content.filename}.pptx",
            buf,
            PPTX_MIME,
        )
        return format_tool_response(result)

    description = (
        "Generate a polished, design-rich PowerPoint (.pptx) via the Presenton "
        "engine. 발표자료/슬라이드/프레젠테이션/PPT 요청 시 사용. "
        "Supports `template` (general/modern/standard/swift or a custom template name), "
        "`tone`, and `verbosity`. If the user attached a .pptx in chat and asked to "
        "use it as the design template ('이 PPT 디자인으로', 'use this template'), "
        "set `use_attached_template=True` (the attached deck's master/layout is "
        "extracted into a Presenton template on the fly). Progress is streamed to the "
        "user while it runs. The file is saved and a markdown download link is returned. "
        "IMPORTANT: call this tool EXACTLY ONCE and wait (generation can take a few "
        "minutes); do NOT retry or call it in parallel. You MUST include the returned "
        "markdown link verbatim in your answer."
    ) + _templates_hint()

    return StructuredTool.from_function(
        coroutine=_create_presentation_async,
        name="create_presentation",
        description=description,
        args_schema=PresentationContent,
    )
