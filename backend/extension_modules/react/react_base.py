import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
)

from extension_modules.utils.media_handler import upload_base64_to_blob
from langchain.agents import AgentState
from langchain.tools import ToolRuntime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.types import Command
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.utils.misc import openai_chat_chunk_message_template
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from open_webui.models.agent_config import AgentConfig


class AgentOutputBase(BaseModel):
    answerable: bool = Field(
        default=False,
        description="검색 결과가 질의에 대한 답변이 가능한 근거인지 판단하고 결과를 반환합니다.",
    )


class AgentStateBase(AgentState):
    normalized_question: str = ""
    language: str = ""
    eval_score: int = 0
    eval_reason: str = ""
    answerable: bool = False
    attached_files: List[str] = []


class ReactAgentBase(ABC):
    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        **kwargs,
    ):
        self.api_config = api_config
        self.base_url = base_url
        self.api_key = api_key
        self.metadata = metadata
        self._agent_config: Optional["AgentConfig"] = None

    @property
    def agent_config(self) -> Optional["AgentConfig"]:
        """
        Get agent configuration from metadata.

        Returns:
            AgentConfig instance if available, None otherwise.
        """
        if self._agent_config is not None:
            return self._agent_config

        config = self.metadata.get("agent_config")
        if config is None:
            return None

        # If it's already an AgentConfig instance, use it directly
        from open_webui.models.agent_config import AgentConfig

        if isinstance(config, AgentConfig):
            self._agent_config = config
            return self._agent_config

        # If it's a dict (e.g., from JSON serialization), parse it
        if isinstance(config, dict):
            self._agent_config = AgentConfig(**config)
            return self._agent_config

        return None

    @abstractmethod
    def run(self, question: str) -> str:
        """
        Run the agent and return the result.
        """
        pass

    def rewrite_question(
        self, question: str, runtime: ToolRuntime[None, AgentStateBase]
    ) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Successfully re-write question",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "normalized_question": question,
            }
        )

    def _extract_tool_messages_after_last_human(
        self, messages: List[Any]
    ) -> List[ToolMessage]:
        """
        messages에서 '가장 마지막 HumanMessage' 이후에 나온 모든 ToolMessage들을 반환한다.
        - ReAct가 여러 tool을 연속 호출한 경우, 마지막 사용자 발화 이후 tool 결과를 모두 평가/병합할 때 사용.
        """
        if not isinstance(messages, list) or not messages:
            return []

        last_human_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break

        start = last_human_idx + 1 if last_human_idx >= 0 else 0
        out: List[ToolMessage] = []
        for m in messages[start:]:
            if isinstance(m, ToolMessage):
                out.append(m)
        return out

    async def _run_final_stream(
        self, payload, system_prompt, display_message: str = None
    ):
        """
        StreamResponse 시 OWUI의 openai_chat_chunk_message_template 형식으로 변환하여 SSE
        최종 완료 이벤트 전송
        """
        import uuid

        from open_webui.models.message_trace import (
            MessageTraceCreateForm,
            MessageTraces,
            RunStatus,
            RunType,
        )

        model_name = payload.get("model")
        payload["stream_options"] = {"include_usage": True}

        # Tracing 설정
        tracing_enabled = False
        trace_run_id = None
        try:
            from open_webui.config import ENABLE_MESSAGE_TRACING

            tracing_enabled = ENABLE_MESSAGE_TRACING.value
        except Exception:
            pass

        # Start trace for final stream LLM call
        if tracing_enabled:
            trace_id = str(uuid.uuid4())
            form_data = MessageTraceCreateForm(
                trace_id=trace_id,
                parent_run_id=None,
                dotted_order="1",
                chat_id=self.metadata.get("chat_id"),
                message_id=self.metadata.get("message_id"),
                user_id=self.metadata.get("user_id"),
                run_type=RunType.LLM.value,
                name=f"{model_name} (final_answer)",
                status=RunStatus.RUNNING.value,
                inputs={
                    "type": "final_answer_generation",
                    "stream": True,
                },
                model_id=model_name,
            )
            trace = MessageTraces.create_trace(form_data)
            if trace:
                trace_run_id = trace.id

        final_usage = None
        output_parts = []
        _MAX_PREVIEW = 1000

        # Extract user question for conversation log preview
        _input_preview = ""
        messages = payload.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    content = " ".join(text_parts)
                _input_preview = content[:500] if isinstance(content, str) else ""
                break

        async def insert_usage(usage: dict):
            nonlocal final_usage
            final_usage = usage
            # 에이전트인 경우에만 agent_id 설정 (base_model_id가 있으면 에이전트)
            model_info = self.metadata.get("model", {})
            base_model_id = model_info.get("info", {}).get("base_model_id")
            agent_id = model_info.get("id") if base_model_id else None

            # Enrich with conversation preview for conversation logs
            enriched = dict(usage) if usage else {}
            if _input_preview:
                enriched["request_summary"] = {
                    "input_preview": _input_preview,
                    "message_count": len(messages),
                }
            output_text = "".join(output_parts)
            if output_text:
                enriched["output_preview"] = output_text[:_MAX_PREVIEW]
            if self.metadata.get("client_type"):
                enriched["client_type"] = self.metadata["client_type"]

            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: Usages.insert_new_usage(
                    user_id=self.metadata.get("user_id"),
                    chat_id=self.metadata.get("chat_id"),
                    agent_id=agent_id,
                    model_id=model_name,
                    message_id=self.metadata.get("message_id"),
                    message_type=UsageMessageType.GENERATION,
                    total_tokens=usage.get("total_tokens"),
                    usage=enriched,
                ),
            )

        error_msg = None
        try:
            async for chunk in self._create_llm(payload, stream=True).astream(
                system_prompt
            ):
                if chunk.usage_metadata:
                    await insert_usage(chunk.usage_metadata)
                piece = self._extract_text_from_chunk(chunk)
                if piece:
                    if len("".join(output_parts)) < _MAX_PREVIEW:
                        output_parts.append(piece)
                    payload = openai_chat_chunk_message_template(
                        model_name, content=piece
                    )
                    yield self._sse(payload)
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            # Complete trace
            if trace_run_id and tracing_enabled:
                MessageTraces.complete_trace(
                    trace_id=trace_run_id,
                    outputs={"type": "final_answer"},
                    token_usage=final_usage,
                    error=error_msg,
                )

        await self.event_emitter(
            {
                "type": "status",
                "data": {
                    "description": display_message or "Task completed!",
                    "done": True,
                    "detail": display_message or "Task completed!",
                },
            }
        )

    def _extract_text_from_chunk(self, chunk) -> str:
        content = getattr(chunk, "content", "")
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        texts.append(item.get("text", ""))
                    # thinking은 프론트에 안 보내려면 무시
                    # elif item.get("type") == "thinking":
                    #     pass
            return "".join(texts)

        return ""

    def _collect_sources_from_result(
        self, result: AgentStateBase
    ) -> List[Dict[str, Any]]:
        """ToolMessage 들에서 raw source dict 리스트를 추출한다 (grouping 이전 단계).

        레거시 filename grouping(build_aggregated_sources_by_filename)과 provenance
        grouping(build_source_bundles)이 공유하는 추출 단계. 평가용 raw source 를
        self._raw_sources 에 저장하는 부수효과 포함. (PR2)
        """

        def extract_sources_from_payload(payload):
            if isinstance(payload, dict):
                yield from payload.get("sources", [])

        def _sanitize_redacted_markers(text: str) -> str:
            """Remove [REDACTED_*] markers that break JSON parsing.

            Guardrail PII detection can replace numeric values (e.g., distances like
            2.329124689102173) with markers like [REDACTED_CREDIT_CARD], corrupting
            the JSON structure. This sanitizes the string so json.loads can succeed.
            """
            # Numeric-context: "2.[REDACTED_CREDIT_CARD]" → "0"
            text = re.sub(r"\d+\.?\[REDACTED_[A-Z_]+\]", "0", text)
            # String-context: "[REDACTED_EMAIL]" → "__redacted__"
            text = re.sub(r"\[REDACTED_[A-Z_]+\]", "__redacted__", text)
            return text

        def _parse_content(content_str: str):
            """Parse content string to dict/list. Handles both JSON and Python repr."""
            # 1. Try JSON (double quotes)
            try:
                return json.loads(content_str)
            except (json.JSONDecodeError, ValueError):
                pass
            # 2. If guardrail redacted markers broke JSON, sanitize and retry
            if "[REDACTED_" in content_str:
                sanitized = _sanitize_redacted_markers(content_str)
                try:
                    return json.loads(sanitized)
                except (json.JSONDecodeError, ValueError):
                    logger.warning(
                        "[_parse_content] JSON parse failed even after sanitizing "
                        "REDACTED markers"
                    )
            # 3. Try Python literal (single quotes from str(dict))
            try:
                import ast

                parsed = ast.literal_eval(content_str)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except (ValueError, SyntaxError):
                pass
            return None

        def extract_sources_from_messages(messages):
            for m in messages:
                content = getattr(m, "content", None)
                if content is None:
                    continue

                # content가 dict/list일 수 있음 (LangGraph ToolMessage)
                if isinstance(content, dict):
                    yield from content.get("sources", [])
                    continue
                elif isinstance(content, list):
                    for p in content:
                        yield from extract_sources_from_payload(p)
                    continue
                elif not isinstance(content, str):
                    continue

                payload = _parse_content(content)
                if payload is None:
                    continue

                if isinstance(payload, dict):
                    yield from payload.get("sources", [])
                elif isinstance(payload, list):
                    for p in payload:
                        yield from extract_sources_from_payload(p)

        all_messages = result.get("messages", [])

        # Primary: extract ToolMessages after last HumanMessage
        tool_msgs_primary = self._extract_tool_messages_after_last_human(all_messages)

        sources = []

        for s in extract_sources_from_messages(tool_msgs_primary):
            if not isinstance(s, dict):
                continue
            sources.append(s)

        # Fallback: if no sources found, scan ALL ToolMessages in the result.
        if not sources:
            all_tool_msgs = [m for m in all_messages if isinstance(m, ToolMessage)]
            if all_tool_msgs:
                for s in extract_sources_from_messages(all_tool_msgs):
                    if not isinstance(s, dict):
                        continue
                    sources.append(s)
        # --- 입력 정규화 ---
        if isinstance(sources, dict):
            sources = list(sources.values())

        # Store raw (pre-grouping) sources for evaluation use
        self._raw_sources = list(sources)
        return list(sources)

    def build_aggregated_sources_by_filename(
        self, result: AgentStateBase
    ) -> Dict[str, Dict[str, Any]]:
        """레거시 filename-기준 source 집계. 같은 파일명의 chat upload 와 KB 문서가
        한 bucket 으로 합쳐지는 기존 동작을 보존한다 (PR3 전까지 소비처 호환).
        신규 코드는 build_source_bundles(provenance grouping)를 사용할 것. (PR2)
        """
        sources = self._collect_sources_from_result(result)

        grouped = defaultdict(list)

        # --- 1. source.name 기준 grouping ---
        for s in sources:
            if not isinstance(s, dict):
                continue
            name = s.get("source", {}).get("name")
            if isinstance(name, str) and name.strip():
                grouped[name].append(s)

        aggregated_sources: Dict[str, Dict[str, Any]] = {}

        # --- 2. 그룹별 병합 ---
        for group in grouped.values():
            if not group:
                continue

            base = group[0]

            merged = {
                "source": base.get("source"),
                "document": [],
                "metadata": [],
                "distances": [],
            }

            for s in group:
                merged["document"].extend(
                    d for d in (s.get("document") or []) if isinstance(d, str)
                )
                merged["metadata"].extend(
                    m for m in (s.get("metadata") or []) if isinstance(m, dict)
                )
                merged["distances"].extend(
                    d for d in (s.get("distances") or []) if isinstance(d, (int, float))
                )

            # --- 3. key 결정 ---
            meta0 = (merged.get("metadata") or [{}])[0]
            key = None
            if isinstance(meta0, dict):
                key = meta0.get("source")

            if key is None:
                key = (
                    merged.get("source", {}).get("id")
                    or merged.get("source", {}).get("name")
                    or "N/A"
                )

            aggregated_sources[str(key)] = merged

        return aggregated_sources

    @staticmethod
    def _bundle_sources_by_provenance(
        sources: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """source 를 provenance identity 기준으로 묶는다 — filename 이 아니라
        (source_type, collection_id|file_id|source.id) 로 grouping 하여 같은 파일명의
        chat upload 와 KB 문서가 섞이는 collision(§3.3)을 차단한다.

        반환: {source_type: [bundle, ...]}. bundle 은 레거시 merged source 의
        상위집합(source/document/metadata/distances) + display_name/source_type/
        citation_policy/identity 를 포함하여 PR3 prompt split 이 그대로 소비한다.
        """
        grouped = defaultdict(list)
        for s in sources:
            if not isinstance(s, dict):
                continue
            meta_list = s.get("metadata") or []
            meta0 = meta_list[0] if meta_list and isinstance(meta_list[0], dict) else {}
            src_obj = s.get("source") or {}
            source_type = meta0.get("source_type") or src_obj.get("type") or "unknown"
            identity = (
                meta0.get("collection_id")
                or meta0.get("file_id")
                or src_obj.get("id")
                or src_obj.get("name")
                or "N/A"
            )
            grouped[(source_type, str(identity))].append(s)

        bundles = defaultdict(list)
        for (source_type, identity), group in grouped.items():
            base = group[0]
            documents: List[str] = []
            metadata: List[Dict[str, Any]] = []
            distances: List[Any] = []
            for s in group:
                documents.extend(
                    d for d in (s.get("document") or []) if isinstance(d, str)
                )
                metadata.extend(
                    m for m in (s.get("metadata") or []) if isinstance(m, dict)
                )
                distances.extend(
                    d for d in (s.get("distances") or []) if isinstance(d, (int, float))
                )
            meta0 = metadata[0] if metadata else {}
            src_obj = base.get("source") or {}
            bundles[source_type].append(
                {
                    "source": base.get("source"),
                    "display_name": (
                        src_obj.get("name") or src_obj.get("id") or identity
                    ),
                    "document": documents,
                    "metadata": metadata,
                    "distances": distances,
                    "source_type": source_type,
                    "citation_policy": meta0.get("citation_policy", "required"),
                    "identity": identity,
                }
            )
        return dict(bundles)

    def build_source_bundles(
        self, result: AgentStateBase
    ) -> Dict[str, List[Dict[str, Any]]]:
        """result 의 ToolMessage source 를 provenance 기준 typed bundle 로 묶는다. (PR2)

        build_aggregated_sources_by_filename(레거시)와 동일한 추출 단계를 공유하되
        filename collision 없는 grouping 을 제공한다. PR3 final-prompt split 의 입력.
        """
        sources = self._collect_sources_from_result(result)
        return self._bundle_sources_by_provenance(sources)

    def _to_langchain_messages(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str],
    ) -> List[BaseMessage]:
        lc_messages: List[BaseMessage] = []

        if system_prompt:
            lc_messages.append(SystemMessage(content=system_prompt))

        for m in messages:
            role = m.get("role")
            content = m.get("content")

            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))

        return lc_messages

    # Regex for markdown image syntax: ![alt](url)
    _IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\((/api/v1/files/([^/)]+)/content)\)")

    def _normalize_langchain_content_blocks(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        OpenAI-style content blocks → LangChain 1.0 content blocks

        1) image_url 블록의 base64 데이터를 Azure Blob Storage에 업로드하고
           URL로 치환. Blob 미설정 시 원본 base64 유지.
        2) 문자열 content에 포함된 이미지 마크다운(![...](/api/v1/files/{id}/content))을
           image_url content block으로 변환하여 LLM이 실제 이미지를 볼 수 있도록 함.
        """
        normalized = []

        for msg in messages:
            content = msg.get("content")

            # string content → 이미지 마크다운이 있으면 multipart로 변환
            if isinstance(content, str):
                converted = self._convert_image_markdown_to_blocks(content)
                if converted is not None:
                    normalized.append({**msg, "content": converted})
                else:
                    normalized.append(msg)
                continue

            # content가 list가 아니면 그대로
            if not isinstance(content, list):
                normalized.append(msg)
                continue

            new_blocks = []
            for block in content:
                if not isinstance(block, dict):
                    continue

                if block.get("type") == "image_url":
                    img_url = block.get("image_url", {}).get("url", "")

                    if img_url.startswith("data:"):
                        # base64 데이터 → Azure Blob에 업로드 시도
                        try:
                            result = upload_base64_to_blob(data=img_url)
                            final_url = result.get("blob_url")
                        except Exception:
                            # Azure Blob Storage 미설정 시 원본 base64 유지
                            final_url = img_url
                    else:
                        # HTTP URL (이미 클라우드 스토리지에 업로드됨) → 그대로 사용
                        final_url = img_url

                    new_blocks.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": final_url},
                        }
                    )
                else:
                    # text 등은 그대로
                    new_blocks.append(block)

            normalized.append(
                {
                    **msg,
                    "content": new_blocks,
                }
            )

        return normalized

    def _convert_image_markdown_to_blocks(
        self, content: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert image markdown in string content to multipart content blocks.

        Finds ![alt](/api/v1/files/{id}/content) patterns, reads the file,
        converts to base64, and returns multipart content blocks.
        Returns None if no image markdown found.
        """
        matches = list(self._IMAGE_MD_RE.finditer(content))
        if not matches:
            return None

        blocks = []
        last_end = 0

        for match in matches:
            # Text before this image
            text_before = content[last_end : match.start()].strip()
            if text_before:
                blocks.append({"type": "text", "text": text_before})

            # Convert file to base64 image_url block
            file_id = match.group(3)
            image_block = self._file_id_to_image_block(file_id)
            if image_block:
                blocks.append(image_block)
            else:
                # Fallback: keep markdown as text
                blocks.append({"type": "text", "text": match.group(0)})

            last_end = match.end()

        # Remaining text after last image
        text_after = content[last_end:].strip()
        if text_after:
            blocks.append({"type": "text", "text": text_after})

        return blocks if blocks else None

    @staticmethod
    def _file_id_to_image_block(file_id: str) -> Optional[Dict[str, Any]]:
        """Read a file by ID and convert to base64 image_url block."""
        try:
            import base64
            from pathlib import Path

            from open_webui.models.files import Files
            from open_webui.storage.provider import Storage

            file = Files.get_file_by_id(file_id)
            if not file:
                return None

            content_type = file.meta.get("content_type", "image/png")
            if not content_type.startswith("image/"):
                return None

            file_path = Storage.get_file(file.path)
            file_path = Path(file_path)

            if not file_path.is_file():
                return None

            with open(file_path, "rb") as f:
                image_data = f.read()

            b64 = base64.b64encode(image_data).decode("utf-8")
            data_url = f"data:{content_type};base64,{b64}"

            # Azure Blob 업로드 시도 (base64 → URL 변환)
            try:
                result = upload_base64_to_blob(data=data_url)
                final_url = result.get("blob_url")
            except Exception:
                final_url = data_url

            return {
                "type": "image_url",
                "image_url": {"url": final_url},
            }
        except Exception as e:
            logger.warning(
                f"[ReactBase] Failed to convert file {file_id} to image block: {e}"
            )
            return None

    def _extract_messages_and_prompt(
        self, payload: Dict[str, Any]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        system_messages: List[str] = []
        prompt = self.api_config.get("system_prompt")

        raw_messages: Iterable[Dict[str, Any]] = payload.get("messages") or []
        cleaned_messages: List[Dict[str, Any]] = []
        for message in raw_messages:
            if message.get("role") == "system":
                if message.get("content"):
                    system_messages.append(str(message["content"]))
                continue
            cleaned_messages.append(message)

        if system_messages:
            system_prompt = "\n".join(system_messages)
        else:
            system_prompt = prompt

        return self._normalize_langchain_content_blocks(cleaned_messages), system_prompt

    def _create_llm(self, payload: Dict[str, Any], *, stream: bool) -> BaseChatModel:
        from extension_modules.utils.llm import create_llm

        model_kwargs = self._collect_model_kwargs(payload)
        return create_llm(
            {
                "model_id": payload.get("model"),
                "api_key": self.api_key,
                "base_url": self.base_url,
                "api_config": self.api_config,
            },
            streaming=stream,
            model_kwargs=model_kwargs,
        )

    def _collect_model_kwargs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_params = {
            "temperature",
            "top_p",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "seed",
        }

        return {
            key: payload[key]
            for key in allowed_params
            if key in payload and payload[key] is not None
        }

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
