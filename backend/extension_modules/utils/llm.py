"""
공용 LLM 유틸리티 모듈.

다양한 extension_modules에서 LangChain 기반 LLM 호출에 사용.
React Agent, DbSphere 스키마 추출 등에서 공통으로 활용.
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# Models incompatible with json_mode (response_format: json_object).
# These models produce degraded output (single object instead of arrays,
# wrapped responses) when json_mode is forced via API parameter.
# Prompt-level JSON instructions work fine without the API flag.
MODELS_SKIP_JSON_MODE = {"gpt-oss"}

# 런타임 학습 캐시: temperature(및 top_p)를 거부하는 모델 id 집합.
# ainvoke_temperature_safe() 가 HTTP 400 temperature 에러를 한 번 만나면 여기
# 등록 → 이후 같은 모델 호출은 처음부터 temperature 를 생략한다.
# - 프로세스 메모리 (멀티워커는 워커별 독립 학습; 캐시 sync 불필요).
# - 재시작 시 모델당 최초 1회만 재학습 (비용 무시 가능).
# - 이름 추론과 달리 gpt-5/gpt-6/claude-thinking/커스텀 배포명 모두 자동 대응.
_FIXED_TEMP_MODELS: set = set()


def _only_default_temperature(model_id: Optional[str]) -> bool:
    """확실하게 temperature=1 만 허용하는 모델인지 이름으로 빠르게 판별.

    OpenAI o-series(o1/o3/o4...)는 추론 전용이라 항상 temperature≠1 을 거부한다
    — 이름만으로 안전하게 단정 가능(오탐/과잉제거 없음)하므로 첫 호출부터
    temperature 를 생략해 불필요한 400 1회를 아낀다.

    gpt-5 계열은 reasoning on/off 에 따라 temperature 허용 여부가 달라지고
    (#35423), gpt-6 등 미래 모델은 이름으로 알 수 없으므로 여기서 판별하지
    않는다 — 그런 모델은 _FIXED_TEMP_MODELS 런타임 학습이 처리한다.
    """
    name = (model_id or "").lower()
    if "/" in name:  # "openai/o3" 같은 provider prefix 제거
        name = name.rsplit("/", 1)[-1]
    # o1, o1-mini, o3, o3-mini, o4-mini 등 (o + 숫자 + 경계)
    return bool(re.match(r"^o[1-9]\d*(?:[-_.]|$)", name))


def _should_omit_temperature(model_id: Optional[str]) -> bool:
    """이름 fast-path(o-series) 또는 런타임 학습 캐시에 걸리면 True."""
    return _only_default_temperature(model_id) or (model_id in _FIXED_TEMP_MODELS)


def _is_temperature_error(exc: Exception) -> bool:
    """HTTP 400 이 temperature(또는 top_p) 미지원 때문인지 판별.

    다른 400(잘못된 max_tokens, content filter 등)과 구분하기 위해 보수적으로
    확인한다 — temperature 라고 확신될 때만 strip+재시도해야 다른 에러를
    무한 재시도로 마스킹하지 않는다.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    # status 가 노출 안 되는 래핑 케이스도 있어 메시지로도 검사하므로 강제 안 함.
    if status not in (400, None):
        return False

    # 1순위: openai SDK 가 구조화한 param
    if getattr(exc, "param", None) in ("temperature", "top_p"):
        return True
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        if isinstance(err, dict) and err.get("param") in ("temperature", "top_p"):
            return True

    # 2순위: 메시지 substring (param 누락한 프록시/Azure/Claude 변형 안전망)
    msg = str(exc).lower()
    if "temperature" not in msg and "top_p" not in msg:
        return False
    return any(
        s in msg
        for s in (
            "does not support",
            "only the default",
            "unsupported value",
            "only be set to 1",  # Claude thinking 변형
        )
    )


def _strip_temperature(llm: BaseChatModel) -> None:
    """이미 생성된 chat model 인스턴스에서 temperature/top_p 를 제거(None).

    langchain ChatOpenAI 는 None 이면 요청에서 해당 파라미터를 생략하므로,
    재빌드 없이 같은 인스턴스로 재시도할 수 있다.
    """
    for attr in ("temperature", "top_p"):
        if getattr(llm, attr, None) is not None:
            try:
                setattr(llm, attr, None)
            except Exception:
                pass


def _is_retryable_error(exc: Exception) -> bool:
    """일시적(transient) 에러인지 — 재시도하면 성공할 가능성이 있는 것.

    429(rate limit), 5xx, 타임아웃, 연결 오류가 해당. 401/403(인증),
    400(temperature 제외 — 그건 별도 처리)은 재시도해도 같은 결과라 제외.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in (429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__
    if name in (
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "TimeoutError",
    ):
        return True
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "rate limit",
            "429",
            "timeout",
            "timed out",
            "temporarily",
            "overloaded",
            "503",
            "try again",
        )
    )


def _retry_delay(
    exc: Exception, attempt: int, base_delay: float, max_wait: float
) -> float:
    """다음 재시도까지 대기(초).

    서버가 ``Retry-After`` 를 주면 그 값을(``max_wait`` 상한) 우선 존중하고,
    없으면 지수 백오프(``base_delay`` × 2^attempt, ``max_wait`` 상한) + jitter.

    Retry-After 파싱은 임베딩 경로(PR #244)의 공유 헬퍼를 재사용한다 —
    search_engine/embedding.py 와 동일하게 lazy import 로 모듈 로드 순서 의존을
    피한다. 헬퍼를 못 불러와도 backoff 로 안전하게 폴백한다.
    """
    try:
        from open_webui.retrieval.embedding_retry import retry_after_seconds
    except Exception:
        retry_after_seconds = None  # 헬퍼 로드 실패 시 backoff 로 폴백
    if retry_after_seconds is not None:
        after = retry_after_seconds(exc)
        if after is not None:
            return min(after, max_wait)
    backoff = min(base_delay * (2**attempt), max_wait)
    return backoff + random.uniform(0, base_delay)


async def ainvoke_temperature_safe(
    llm: BaseChatModel,
    messages,
    *,
    max_retries: int = 0,
    base_delay: float = 1.0,
    max_wait: float = 30.0,
    **kwargs,
):
    """llm.ainvoke 래퍼 — temperature 미지원 우회 + 일시적 에러 재시도.

    1. 학습 캐시에 있는 모델이면 호출 전에 temperature 제거.
    2. temperature 400 → 모델을 캐시에 등록하고 제거 후 즉시 재시도
       (재시도 횟수에 포함 안 됨 — 1회성 보정).
    3. 일시적 에러(429/5xx/타임아웃) → max_retries 회 재시도. 서버가
       ``Retry-After`` 를 주면 그 값을(``max_wait`` 상한) 우선 존중하고, 없으면
       지수 백오프 + jitter 를 적용한다. 그 외 에러는 그대로 전파.

    plain ainvoke 경로용. 체인(.with_structured_output / prompt|llm) 은 베이스
    llm 을 만들 때 _should_omit_temperature 로 사전 제거하거나 별도 처리.

    Args:
        max_retries: 일시적 에러 재시도 횟수 (기본 0 = 재시도 없음, 기존 동작 유지).
        base_delay: Retry-After 부재 시 backoff 기준 (초).
        max_wait: 한 번의 대기 상한 (초). Retry-After/backoff 모두에 적용.
    """
    model_id = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    if model_id in _FIXED_TEMP_MODELS:
        _strip_temperature(llm)

    attempt = 0
    while True:
        try:
            return await llm.ainvoke(messages, **kwargs)
        except Exception as exc:
            # temperature 우회 (1회성, 재시도 카운트 미소모)
            if _is_temperature_error(exc) and model_id not in _FIXED_TEMP_MODELS:
                logger.warning(
                    "[llm] %s 가 temperature 를 거부 — 캐시 등록 후 재시도", model_id
                )
                if model_id:
                    _FIXED_TEMP_MODELS.add(model_id)
                _strip_temperature(llm)
                continue
            # 일시적 에러 재시도 (Retry-After 우선, 없으면 지수 백오프 + jitter)
            if _is_retryable_error(exc) and attempt < max_retries:
                delay = _retry_delay(exc, attempt, base_delay, max_wait)
                logger.warning(
                    "[llm] 일시적 에러, %.1fs 후 재시도 %d/%d (model=%s): %s",
                    delay,
                    attempt + 1,
                    max_retries,
                    model_id,
                    str(exc)[:200],
                )
                await asyncio.sleep(delay)
                attempt += 1
                continue
            raise


@dataclass
class LLMConfig:
    """LLM 설정 데이터클래스."""

    model_id: str
    api_key: str
    base_url: Optional[str] = None
    provider_type: Optional[str] = (
        None  # "azure-openai", "openai", "ollama", "vertex-gemini"
    )
    # Azure OpenAI 전용
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    api_version: Optional[str] = None
    # 원본 api_config (vertex-gemini 등 프로바이더별 추가 설정 접근용)
    api_config: Optional[Dict[str, Any]] = None


def create_llm(
    config: Union[LLMConfig, Dict[str, Any]],
    *,
    streaming: bool = False,
    json_mode: bool = False,
    model_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> BaseChatModel:
    """
    LangChain Chat Model 생성.

    react_base.py의 _create_llm 패턴을 공용으로 추출.
    모든 프로바이더에 streaming, model_kwargs, json_mode 지원.

    Args:
        config: LLMConfig 또는 dict (api_config 포함 가능)
        streaming: 스트리밍 모드 활성화
        json_mode: JSON 응답 강제. 프로바이더별 자동 적용:
            - OpenAI/Azure: response_format={"type": "json_object"}
            - Gemini/Vertex: generation_config.response_mime_type="application/json"
            - Ollama: format="json"
        model_kwargs: 모델별 추가 파라미터 (temperature, top_p 등)
        **kwargs: 추가 모델 파라미터 (temperature, max_tokens 등)

    Returns:
        BaseChatModel: LangChain Chat Model 인스턴스

    Example:
        >>> config = get_model_config_from_app(app, "gpt-4o")
        >>> llm = create_llm(config, json_mode=True, temperature=0.1)
        >>> response = await llm.ainvoke([HumanMessage(content="Extract as JSON")])
    """
    from langchain_openai import AzureChatOpenAI, ChatOpenAI

    # Dict를 LLMConfig로 변환
    if isinstance(config, dict):
        api_config = config.get("api_config", {})
        config = LLMConfig(
            model_id=config.get("model_id", ""),
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url"),
            provider_type=api_config.get("provider_type"),
            azure_endpoint=api_config.get("azure_endpoint") or config.get("base_url"),
            azure_deployment=api_config.get("azure_deployment"),
            api_version=api_config.get("api_version"),
            api_config=api_config,
        )

    provider = config.provider_type or ""
    _model_kwargs = dict(model_kwargs or {})

    # temperature≠1 을 거부하는 모델(o-series 또는 학습캐시에 등록된 모델)에는
    # temperature/top_p 를 사전 제거한다. 그 외 모델은 그대로 두고, 혹시 거부하면
    # 호출부의 ainvoke_temperature_safe 가 런타임에 학습/우회한다.
    if _should_omit_temperature(config.model_id):
        for _src in (kwargs, _model_kwargs):
            for _param in ("temperature", "top_p"):
                if _param in _src:
                    logger.info(
                        "[create_llm] %s 는 temperature 미지원 — %s 제거 (model=%s)",
                        config.model_id,
                        _param,
                        _src.pop(_param),
                    )

    # JSON mode: 프로바이더별 자동 적용
    # Skip for models that produce degraded output with json_mode API flag
    model_name_lower = (config.model_id or "").lower()
    if json_mode and not any(m in model_name_lower for m in MODELS_SKIP_JSON_MODE):
        if provider in ("azure-openai", "azure-ai-foundry", ""):
            # OpenAI / Azure OpenAI / Azure AI Foundry
            _model_kwargs.setdefault("response_format", {"type": "json_object"})
        elif provider in ("vertex-gemini", "vertex-ai"):
            # Gemini / Vertex AI
            _model_kwargs.setdefault("generation_config", {})
            if isinstance(_model_kwargs.get("generation_config"), dict):
                _model_kwargs["generation_config"].setdefault(
                    "response_mime_type", "application/json"
                )

    if provider == "azure-openai":
        if streaming:
            _model_kwargs.setdefault("stream_options", {"include_usage": True})

        return AzureChatOpenAI(
            azure_endpoint=config.azure_endpoint,
            azure_deployment=config.azure_deployment or config.model_id,
            api_version=config.api_version,
            api_key=config.api_key,
            streaming=streaming,
            model_kwargs=_model_kwargs,
            **kwargs,
        )
    elif provider == "vertex-gemini":
        # Vertex AI Gemini 지원 (서비스 계정 인증)
        import json as _json

        from google.oauth2 import service_account
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_cfg = config.api_config or {}
        vertex_cfg = api_cfg.get("vertex_gemini", {})
        credentials_json = vertex_cfg.get("credentials_json")

        if streaming:
            _model_kwargs.setdefault("stream_options", {"include_usage": True})

        if credentials_json:
            cred_info = (
                _json.loads(credentials_json)
                if isinstance(credentials_json, str)
                else credentials_json
            )
            credentials = service_account.Credentials.from_service_account_info(
                cred_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return ChatGoogleGenerativeAI(
                model=config.model_id,
                credentials=credentials,
                streaming=streaming,
                model_kwargs=_model_kwargs,
                **kwargs,
            )
        else:
            # Fallback: API key 방식
            return ChatGoogleGenerativeAI(
                model=config.model_id,
                google_api_key=config.api_key,
                streaming=streaming,
                model_kwargs=_model_kwargs,
                **kwargs,
            )
    elif provider == "vertex-ai":
        # Vertex AI backend — ChatGoogleGenerativeAI with vertexai=True.
        # ChatVertexAI(langchain-google-vertexai) was deprecated in
        # LangChain 3.2.0 and rejects Gemini 3 preview models with
        # INVALID_ARGUMENT even on bare "hi" requests. The new google-genai
        # SDK speaks both Gemini Developer API and Vertex AI through the
        # same class, and is the only path that works for Gemini 3.
        import json as _json

        import google.auth
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_cfg = config.api_config or {}
        project_id = api_cfg.get("project_id")
        location = api_cfg.get("location", "us-central1")
        service_account_key = api_cfg.get("service_account_key")
        use_adc = bool(api_cfg.get("use_adc")) and not service_account_key

        if not project_id:
            raise ValueError("Vertex AI 설정이 올바르지 않습니다. (project_id 필요)")
        if not service_account_key and not use_adc:
            debug = api_cfg.get("_gcp_resolve_debug")
            if debug:
                use_global = debug.get("use_global_in_conn")
                global_set = debug.get("global_key_set")
                enabled = debug.get("gcp_enabled")

                # 현재 설정 상태 요약 (사용자가 UI 에서 본 그대로)
                state_lines = [
                    "  - 이 연결의 SA 키: 미입력",
                    f"  - 이 연결의 '전역 Google Cloud 키 사용': {'체크됨' if use_global else '미체크'}",
                    f"  - 글로벌 GCP 카드 등록: {'예' if enabled else '아니오'}",
                    f"  - 글로벌 SA 키: {'입력됨' if global_set else '비어 있음 (ADC 모드)'}",
                ]

                # 원인 + 조치
                if not use_global:
                    cause = (
                        "이 연결이 자체 SA 키도 없고 '전역 키 사용' 도 꺼져 있어 "
                        "사용할 자격증명이 없음"
                    )
                    action = (
                        "Vertex AI 연결 편집 모달에서 '전역 Google Cloud 키 사용' 체크 "
                        "후 Save (또는 연결에 서비스 계정 키 직접 입력)"
                    )
                elif not enabled:
                    cause = "글로벌 GCP 카드 자체가 등록되지 않음"
                    action = (
                        "관리자 설정 > Connections > Cloud Accounts 에서 "
                        "'+ Google Cloud' 추가 (서비스 계정 키 입력 또는 ADC 모드 사용)"
                    )
                elif global_set:
                    cause = (
                        "글로벌 SA 키가 입력돼 있는데도 주입 실패 — 코드 버그 또는 "
                        "캐시 동기화 이슈"
                    )
                    action = "백엔드 재시작 후 재시도. 같은 에러 반복 시 보고"
                else:
                    # ADC 모드인데 use_adc 주입 실패 — 로직상 일어나면 안 됨
                    cause = (
                        "글로벌 GCP 카드가 ADC 모드 (키 비어 있고 등록됨) 이지만 "
                        "ADC 플래그 주입이 안 됨 (로직 버그)"
                    )
                    action = "백엔드 로그 + 재시작 확인"

                diag = (
                    f"\n[현재 설정]\n{chr(10).join(state_lines)}"
                    f"\n\n[원인] {cause}"
                    f"\n[조치] {action}"
                )
            else:
                # 호출 경로 추적용 — 어느 에이전트/워커에서 create_llm 호출했는지
                import traceback

                frames = traceback.extract_stack()[:-1]  # 자신 제외
                project_frames = [
                    f
                    for f in frames
                    if "extension_modules" in f.filename or "open_webui" in f.filename
                ]
                # 프로젝트 프레임 우선, 없으면 최근 5단계 그대로
                target_frames = project_frames[-5:] if project_frames else frames[-5:]
                caller_chain = [
                    f"{f.filename.split('/')[-1]}:{f.lineno} in {f.name}"
                    for f in target_frames
                ]

                # api_cfg 의 키 목록 (sensitive 값은 마스킹)
                cfg_keys = sorted(api_cfg.keys())
                cfg_snapshot = {
                    k: (
                        "<set>"
                        if k
                        in (
                            "service_account_key",
                            "api_key",
                            "credentials_json",
                        )
                        and api_cfg.get(k)
                        else api_cfg.get(k)
                    )
                    for k in cfg_keys
                }

                diag = (
                    "\n[원인] 이 호출 경로가 _resolve_vertex_global_key 를 거치지 않음"
                    "\n       (각 에이전트가 자체 _create_llm 메서드로 직접 create_llm 호출하는 경로)"
                    "\n\n[현재 api_config]"
                    f"\n  {cfg_snapshot}"
                    "\n\n[호출 스택]"
                    "\n  " + "\n  → ".join(caller_chain) + "\n\n[조치]"
                    "\n  1. 백엔드 재시작 후 재시도 (PR #208 코드 반영 확인)"
                    "\n  2. 호출 스택의 에이전트가 _resolve_vertex_global_key 를 거치도록 수정 필요"
                )
            raise ValueError(f"Vertex AI 인증 실패{diag}")

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        if use_adc:
            try:
                credentials, _ = google.auth.default(scopes=scopes)
            except google.auth.exceptions.DefaultCredentialsError as e:
                raise ValueError(
                    "Vertex AI 인증 실패"
                    "\n[현재 설정]"
                    "\n  - 글로벌 GCP 카드: ADC 모드 (서비스 계정 키 미입력)"
                    "\n  - 이 연결: '전역 키 사용' 체크 + SA 키 미입력"
                    "\n\n[원인] 시스템에 Application Default Credentials 가 셋업돼 있지 않음"
                    f"\n       (google.auth 메시지: {str(e)[:150]})"
                    "\n\n[조치] 다음 중 하나 셋업 필요"
                    "\n  1. 운영(GCP): Workload Identity 또는 서비스 계정 마운트 확인"
                    "\n  2. 로컬: 환경변수 GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json"
                    "\n  3. 로컬 (대안): gcloud auth application-default login"
                    "\n  4. ADC 안 쓸 거면: 글로벌 GCP 카드 또는 연결에 SA 키 직접 입력"
                ) from e
        else:
            from google.oauth2 import service_account

            credentials_info = (
                _json.loads(service_account_key)
                if isinstance(service_account_key, str)
                else service_account_key
            )
            credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=scopes,
            )

        model_id = config.model_id
        # Remove google/ prefix if present
        if model_id.startswith("google/"):
            model_id = model_id[7:]

        # Gemini 3 preview models require global location
        if model_id.startswith("gemini-3"):
            location = "global"

        return ChatGoogleGenerativeAI(
            model=model_id,
            vertexai=True,
            project=project_id,
            location=location,
            credentials=credentials,
            streaming=streaming,
            model_kwargs=_model_kwargs,
            **kwargs,
        )
    elif provider == "ollama":
        # Ollama 지원
        try:
            from langchain_ollama import ChatOllama

            ollama_kwargs = {**kwargs}
            if json_mode:
                ollama_kwargs["format"] = "json"

            return ChatOllama(
                model=config.model_id,
                base_url=config.base_url,
                streaming=streaming,
                **ollama_kwargs,
            )
        except ImportError:
            logger.warning("langchain_ollama not installed, falling back to ChatOpenAI")
            if streaming:
                _model_kwargs.setdefault("stream_options", {"include_usage": True})

            # Ollama's OpenAI-compatible endpoint lives at {base_url}/v1.
            # ChatOpenAI calls {base_url}/chat/completions, so without the
            # /v1 suffix every request returns 404 immediately.
            ollama_base_url = None
            if config.base_url:
                stripped = config.base_url.rstrip("/")
                ollama_base_url = (
                    stripped if stripped.endswith("/v1") else f"{stripped}/v1"
                )

            return ChatOpenAI(
                model=config.model_id,
                api_key=config.api_key or "ollama",
                base_url=ollama_base_url,
                streaming=streaming,
                model_kwargs=_model_kwargs,
                **kwargs,
            )
    elif provider == "azure-ai-foundry":
        # Azure AI Foundry — OpenAI-compatible via /openai/v1
        if streaming:
            _model_kwargs.setdefault("stream_options", {"include_usage": True})

        base_url = config.base_url.rstrip("/") if config.base_url else ""
        return ChatOpenAI(
            model=config.model_id,
            api_key=config.api_key,
            base_url=f"{base_url}/openai/v1",
            streaming=streaming,
            model_kwargs=_model_kwargs,
            **kwargs,
        )
    else:
        # Default: OpenAI compatible
        if streaming:
            _model_kwargs.setdefault("stream_options", {"include_usage": True})

        return ChatOpenAI(
            model=config.model_id,
            api_key=config.api_key,
            base_url=config.base_url if config.base_url else None,
            streaming=streaming,
            model_kwargs=_model_kwargs,
            **kwargs,
        )


async def generate_text(
    config: Union[LLMConfig, Dict[str, Any]],
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs,
) -> str:
    """
    간단한 텍스트 생성.

    Args:
        config: LLM 설정
        prompt: 사용자 프롬프트
        system_prompt: 시스템 프롬프트 (선택)
        **kwargs: 추가 모델 파라미터

    Returns:
        str: 생성된 텍스트

    Example:
        >>> config = get_model_config_from_app(app, "gpt-4o")
        >>> result = await generate_text(
        ...     config,
        ...     prompt="Explain SQL joins",
        ...     system_prompt="You are a database expert.",
        ...     temperature=0.3
        ... )
    """
    llm = create_llm(config, **kwargs)

    messages: List[BaseMessage] = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=prompt))

    response = await ainvoke_temperature_safe(llm, messages)
    content = response.content
    # Gemini/Vertex AI may return list of content blocks
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return content


def _resolve_vertex_global_key(
    model_config: Optional[Dict[str, Any]], app
) -> Optional[Dict[str, Any]]:
    """Vertex AI 모델에서 service_account_key 가 비어있고 use_global_gcp_key=True 면
    app.state.config.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY 를 주입한다.

    글로벌 키도 비어 있고 GOOGLE_CLOUD_ENABLED=True 면 ADC 모드로 판단해
    api_config["use_adc"]=True 플래그를 세팅한다 (worker 가 app 없이도 ADC 분기 가능).

    채팅 엔드포인트(routers/openai.py:_resolve_vertex_ai_sa_key)와 동일한 fallback 을
    백그라운드 워커가 받는 pre_resolved 페이로드에 미리 적용한다 — Redis 큐로 넘긴
    뒤에는 app 컨텍스트가 없어서 worker 가 직접 resolve 못 하기 때문.

    Vertex 가 아닌 provider 면 그대로 반환 (no-op).
    """
    if not model_config:
        return model_config
    api_cfg = dict(model_config.get("api_config") or {})
    provider = api_cfg.get("provider_type", "")
    if provider not in ("vertex-ai", "vertex-gemini"):
        return model_config
    if api_cfg.get("service_account_key"):
        return model_config

    def _unwrap(attr_name: str):
        try:
            attr = getattr(app.state.config, attr_name, None)
        except Exception:
            return None
        return attr.value if hasattr(attr, "value") else attr

    # Capture gate state for diagnostic — used in create_llm error message when
    # all paths fail. Cleared/overwritten on successful resolution paths below.
    api_cfg["_gcp_resolve_debug"] = {
        "app_present": app is not None,
        "use_global_in_conn": bool(api_cfg.get("use_global_gcp_key")),
        "global_key_set": bool(_unwrap("GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY")),
        "gcp_enabled": bool(_unwrap("GOOGLE_CLOUD_ENABLED")),
    }

    if not api_cfg.get("use_global_gcp_key"):
        new_config = dict(model_config)
        new_config["api_config"] = api_cfg
        return new_config

    global_key = _unwrap("GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY")
    if global_key:
        api_cfg["service_account_key"] = global_key
        api_cfg.pop("_gcp_resolve_debug", None)
        new_config = dict(model_config)
        new_config["api_config"] = api_cfg
        return new_config

    # ADC fallback: global key 비어 있고 GCP integration 이 enabled 면 ADC 모드
    if _unwrap("GOOGLE_CLOUD_ENABLED"):
        api_cfg["use_adc"] = True
        api_cfg.pop("_gcp_resolve_debug", None)
        new_config = dict(model_config)
        new_config["api_config"] = api_cfg
        return new_config

    new_config = dict(model_config)
    new_config["api_config"] = api_cfg
    return new_config


def model_config_has_credentials(model_config: Optional[Dict[str, Any]]) -> bool:
    """모델 config 가 호출 가능한 자격 증명을 갖췄는지 검증.

    Provider 별:
    - openai/azure-openai/azure-ai-foundry/기타: api_key 필수
      (config.api_key 또는 api_config.api_key)
    - vertex-ai/vertex-gemini: service_account_key 또는 use_global_gcp_key 또는 use_adc
    - ollama: 키 없이 동작 가능 (항상 True)
    """
    if not model_config:
        return False
    api_cfg = model_config.get("api_config") or {}
    provider = api_cfg.get("provider_type", "")
    if provider in ("vertex-ai", "vertex-gemini"):
        return bool(
            api_cfg.get("service_account_key")
            or api_cfg.get("use_global_gcp_key")
            or api_cfg.get("use_adc")
        )
    if provider == "ollama":
        return True
    if model_config.get("api_key"):
        return True
    if api_cfg.get("api_key"):
        return True
    return False


def get_model_config_from_app(app, model_id: str) -> Optional[Dict[str, Any]]:
    """
    FastAPI app에서 모델 설정 추출.

    app.state.MODELS와 app.state.config에서 모델 정보를 가져와
    LLM 생성에 필요한 설정을 반환.

    Args:
        app: FastAPI application
        model_id: 모델 ID

    Returns:
        dict: model_config (model_id, api_config, base_url, api_key)
              모델을 찾을 수 없으면 None

    Example:
        >>> config = get_model_config_from_app(request.app, "gpt-4o")
        >>> if config:
        ...     llm = create_llm(config)
    """
    models = getattr(app.state, "MODELS", {})
    model_info = models.get(model_id)

    # model_id로 직접 매칭 안 되면, base_model_id로 resolve 시도
    # 예: 설정에 "gpt-5.2" 저장 → MODELS에는 "cloosphere---gpt-52"(base_model_id="gpt-5.2")
    if not model_info and models:
        for mid, minfo in models.items():
            # DB에서 base_model_id 확인
            pipe_info = minfo.get("info", {}) if isinstance(minfo, dict) else {}
            base_mid = pipe_info.get("base_model_id") or minfo.get("base_model_id")
            if base_mid == model_id:
                logger.info(
                    f"Resolved model '{model_id}' → proxy '{mid}' (base_model_id match)"
                )
                # 프록시 모델의 원본(base_model_id)으로 실제 호출해야 하므로
                # base_model_id를 다시 MODELS에서 찾아서 urlIdx를 가져옴
                base_info = models.get(base_mid)
                if base_info:
                    model_info = base_info
                    model_id = base_mid
                break

    config = app.state.config
    api_configs = getattr(config, "OPENAI_API_CONFIGS", {}) or {}
    base_urls = getattr(config, "OPENAI_API_BASE_URLS", []) or []
    api_keys = getattr(config, "OPENAI_API_KEYS", []) or []

    if not model_info:
        # Fallback: MODELS가 비어있을 때 (백그라운드 태스크 등)
        # api_configs를 순회하면서 model_id와 호환되는 연결을 찾음.
        #
        # 우선순위:
        #   1) 해당 프로바이더의 `model_ids` 허용목록에 model_id 가 명시된 경우
        #   2) prefix_id 를 떼어낸 뒤 `model_ids` 에 매치되는 경우
        #   3) 어떤 프로바이더도 명시하지 않은 경우에만 첫 비-vertex 프로바이더로
        #      폴백 (정말 예전 동작과 동일한 "best effort" 경로)
        # 1번 없이 3번만 있으면 첫 openai-호환 연결이 그 model_id를 *실제로는
        # 서빙하지 않더라도* 선택돼버려 런타임 401/404 가 나는 버그가 있었다.
        if not models:
            logger.info(
                f"MODELS empty, using fallback for {model_id} "
                f"(api_configs has {len(api_configs)} entries)"
            )
            vertex_providers = {"vertex-ai", "vertex-gemini"}
            is_vertex_model = model_id.startswith(("gemini", "google/"))

            def _entry_for(idx: int, api_cfg: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "model_id": model_id,
                    "api_config": api_cfg,
                    "base_url": base_urls[idx] if idx < len(base_urls) else "",
                    "api_key": api_keys[idx] if idx < len(api_keys) else "",
                }

            # Pass 1 — model_ids 허용목록에 명시된 프로바이더 매치 (정확 매치)
            for idx_str, api_cfg in api_configs.items():
                try:
                    idx = int(idx_str)
                except (TypeError, ValueError):
                    continue
                provider = api_cfg.get("provider_type", "")
                if is_vertex_model != (provider in vertex_providers):
                    continue
                allowed = api_cfg.get("model_ids") or []
                if not allowed:
                    continue
                prefix = api_cfg.get("prefix_id") or ""
                stripped_id = (
                    model_id[len(prefix) + 1 :]
                    if prefix and model_id.startswith(f"{prefix}.")
                    else model_id
                )
                if model_id in allowed or stripped_id in allowed:
                    entry = _entry_for(idx, api_cfg)
                    if is_vertex_model:
                        return _resolve_vertex_global_key(entry, app)
                    return entry

            # Pass 2 — 어느 프로바이더도 model_ids 를 명시하지 않은 경우의 폴백.
            # 하나라도 명시한 프로바이더가 있으면 여기까지 오면 안된다 (잘못된
            # 프로바이더에 보낼 위험). 모두 비명시일 때만 첫 번째를 쓴다.
            any_explicit = any(
                (cfg or {}).get("model_ids") for cfg in api_configs.values()
            )
            if not any_explicit:
                for idx_str, api_cfg in api_configs.items():
                    try:
                        idx = int(idx_str)
                    except (TypeError, ValueError):
                        continue
                    provider = api_cfg.get("provider_type", "")
                    entry = _entry_for(idx, api_cfg)
                    if is_vertex_model and provider in vertex_providers:
                        return _resolve_vertex_global_key(entry, app)
                    if not is_vertex_model and provider not in vertex_providers:
                        return entry

            logger.warning(
                f"No provider advertises model '{model_id}' in model_ids "
                f"(is_vertex={is_vertex_model}); refusing fallback"
            )
            return None
        logger.warning(f"Model not found: {model_id}")
        return None

    # Ollama 모델인 경우 OLLAMA_* 설정에서 가져옴
    if model_info.get("owned_by") == "ollama":
        ollama_base_urls = getattr(config, "OLLAMA_BASE_URLS", []) or []
        ollama_api_configs = getattr(config, "OLLAMA_API_CONFIGS", {}) or {}
        idx = model_info.get("urlIdx", 0)
        ollama_base_url = ollama_base_urls[idx] if idx < len(ollama_base_urls) else ""
        ollama_api_cfg = ollama_api_configs.get(
            str(idx), ollama_api_configs.get(ollama_base_url, {})
        )
        result = {
            "model_id": model_id,
            "api_config": {**ollama_api_cfg, "provider_type": "ollama"},
            "base_url": ollama_base_url,
            "api_key": ollama_api_cfg.get("key", ""),
        }
        logger.debug(
            f"[get_model_config_from_app] Ollama model_id={model_id}, idx={idx}, "
            f"base_url={result['base_url'][:50] if result['base_url'] else 'None'}"
        )
        return result

    idx = model_info.get("urlIdx", 0)

    result = {
        "model_id": model_id,
        "api_config": api_configs.get(str(idx), {}),
        "base_url": base_urls[idx] if idx < len(base_urls) else "",
        "api_key": api_keys[idx] if idx < len(api_keys) else "",
    }
    logger.debug(
        f"[get_model_config_from_app] model_id={model_id}, idx={idx}, "
        f"provider_type={result['api_config'].get('provider_type')}, "
        f"base_url={result['base_url'][:50] if result['base_url'] else 'None'}"
    )
    return _resolve_vertex_global_key(result, app)


def create_llm_from_app(
    app,
    model_id: str,
    **kwargs,
) -> Optional[BaseChatModel]:
    """
    FastAPI app에서 모델 설정을 추출하여 LLM 생성.

    get_model_config_from_app와 create_llm을 결합한 편의 함수.

    Args:
        app: FastAPI application
        model_id: 모델 ID
        **kwargs: 추가 모델 파라미터

    Returns:
        BaseChatModel: LangChain Chat Model 인스턴스, 모델을 찾을 수 없으면 None

    Example:
        >>> llm = create_llm_from_app(request.app, "gpt-4o", temperature=0.5)
        >>> if llm:
        ...     response = await llm.ainvoke([HumanMessage(content="Hello")])
    """
    config = get_model_config_from_app(app, model_id)
    if not config:
        return None
    return create_llm(config, **kwargs)


async def generate_text_from_app(
    app,
    model_id: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    **kwargs,
) -> Optional[str]:
    """
    FastAPI app에서 모델 설정을 추출하여 텍스트 생성.

    Args:
        app: FastAPI application
        model_id: 모델 ID
        prompt: 사용자 프롬프트
        system_prompt: 시스템 프롬프트 (선택)
        **kwargs: 추가 모델 파라미터

    Returns:
        str: 생성된 텍스트, 실패 시 None

    Example:
        >>> result = await generate_text_from_app(
        ...     request.app,
        ...     "gpt-4o",
        ...     prompt="Explain SQL joins",
        ...     temperature=0.3
        ... )
    """
    config = get_model_config_from_app(app, model_id)
    if not config:
        return None
    return await generate_text(config, prompt, system_prompt, **kwargs)
