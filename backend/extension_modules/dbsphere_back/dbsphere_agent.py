import json
import os
import re
from typing import Any, Dict, List, Optional

from extension_modules.dbsphere_back.dbsphere_base import DBSphereAgentState
from extension_modules.dbsphere_back.prompt import DBSpherePromptBuilder
from extension_modules.dbsphere_back.tools.agent_memory import AzureAISearchAgentMemory
from extension_modules.dbsphere_back.tools.cookie_email_user_resolver import (
    CookieEmailUserResolver,
)
from extension_modules.dbsphere_back.tools.run_sql import RunSqlTool
from extension_modules.dbsphere_back.tools.visualize_data import VisualizeDataTool
from extension_modules.react.react_base import ReactAgentBase
from fastapi import Request
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
)
from open_webui.utils.misc import (
    openai_chat_chunk_message_template,
)
from starlette.responses import StreamingResponse
from vanna.components import ComponentType
from vanna.core.agent import Agent, AgentConfig
from vanna.core.lifecycle import LifecycleHook
from vanna.core.registry import ToolRegistry
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.integrations.azureopenai import AzureOpenAILlmService
from vanna.integrations.local import LocalFileSystem
from vanna.integrations.mysql import MySQLRunner
from vanna.integrations.postgres import PostgresRunner
from vanna.tools.agent_memory import (
    SaveQuestionToolArgsTool,
    SaveTextMemoryTool,
    SearchSavedCorrectToolUsesTool,
)


class DBSphereLifecycleHook(LifecycleHook):
    def __init__(self, event_emitter, event_call, agent_state: DBSphereAgentState):
        self.event_emitter = event_emitter
        self.event_call = event_call
        self.agent_state = agent_state

        self.event_message = ""

    async def before_message(self, user: User, message: str) -> Optional[str]:
        return message

    async def after_message(self, result: Any) -> None:
        pass

    async def before_tool(self, tool: Tool, context: ToolContext) -> None:
        event_message = f"{tool.name} : {tool.description}..."
        if tool.name == "run_sql":
            if self.event_message != event_message:
                self.event_message = event_message
                await self.event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": self.event_message,
                            "done": False,
                            "detail": tool.description,
                        },
                    }
                )
        elif tool.name == "visualize_data":
            if self.event_message != event_message:
                self.event_message = event_message
                await self.event_emitter(
                    {
                        "type": "status",
                        "data": {
                            "description": f"{tool.name} : {tool.description}...",
                            "done": False,
                            "detail": tool.description,
                        },
                    }
                )

        return None

    async def after_tool(self, result: ToolResult) -> None:
        metadata = result.metadata or {}
        chart_data = metadata.get("chart", {})
        if chart_data:
            self._get_chart_data(chart_data)

        run_sql_data = metadata.get("query", "")
        if run_sql_data and result.success:
            self.agent_state.query_data.append(run_sql_data)

    def _get_chart_data(self, data: dict) -> dict:
        # chart_result는 이미 chart_generator에서 DataFrame JSON으로 변환됨
        chart_result = data.get("chart_result")

        # dict를 JSON 문자열로 변환
        if isinstance(chart_result, dict):
            data["chart_result"] = json.dumps(chart_result)
        else:
            data["chart_result"] = json.dumps(chart_result) if chart_result else "{}"

        self.agent_state.chart_data = data


class DBSphereAgent(ReactAgentBase):
    # def __init__(self, event_emitter, event_call,metadata: Dict[str, Any]):
    def __init__(
        self,
        api_config: Dict[str, Any],
        base_url: str,
        api_key: str,
        metadata: Dict[str, Any],
        request: Request,
    ):
        """
        todo : 향후 요건에 따라 DB 정보 등 받아야 함
        """

        super().__init__(api_config, base_url, api_key, metadata)

        self.request = request
        self.db_host = os.getenv("DATABASE_HOST")
        self.db_name = os.getenv("DATABASE_NAME")
        self.db_user = os.getenv("DATABASE_USER")
        self.db_password = os.getenv("DATABASE_PASSWORD")
        self.db_port = int(os.getenv("DATABASE_PORT"))
        self.metadata = metadata

    def _create_sql_runner(self, db_type: str):
        if db_type == "postgres":
            return PostgresRunner(
                host=self.db_host,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                port=self.db_port,
            )
        elif db_type == "mysql":
            return MySQLRunner(
                host=self.db_host,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                port=self.db_port,
            )

    def _create_agent_memory(self, memory_type: str = "azure_search"):
        """
        관리자 설정 기반 Agent Memory 생성.

        검색 엔진 설정: app.state.config.SEARCH_ENGINE_*
        임베딩 설정: app.state.config.RAG_AZURE_OPENAI_* (Azure OpenAI 임베딩 사용 시)
        """
        config = self.request.app.state.config
        engine_type = getattr(config, "SEARCH_ENGINE_TYPE", "")

        if memory_type == "azure_search" or engine_type == "azure_search":
            # 검색 엔진 연결 정보 (관리자 설정 > 검색 엔진)
            endpoint = getattr(config, "SEARCH_ENGINE_AZURE_ENDPOINT", "") or os.getenv(
                "AZURE_SEARCH_ENDPOINT", ""
            )
            api_key = getattr(config, "SEARCH_ENGINE_AZURE_API_KEY", "") or os.getenv(
                "AZURE_SEARCH_API_KEY", ""
            )
            index_name = os.getenv(
                "AZURE_SEARCH_DBSPHERE_INDEX_NAME", "dbsphere-memory"
            )

            # 임베딩 설정 (관리자 설정 > 문서 > RAG 임베딩)
            embedding_endpoint = getattr(
                config, "RAG_AZURE_OPENAI_API_BASE_URL", ""
            ) or os.getenv("AZURE_OPENAI_ENDPOINT", "")
            embedding_api_key = getattr(
                config, "RAG_AZURE_OPENAI_API_KEY", ""
            ) or os.getenv("AZURE_OPENAI_API_KEY", "")
            embedding_model = getattr(config, "RAG_EMBEDDING_MODEL", "") or os.getenv(
                "AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"
            )
            embedding_api_version = getattr(
                config, "RAG_AZURE_OPENAI_API_VERSION", ""
            ) or os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

            return AzureAISearchAgentMemory(
                endpoint=endpoint,
                api_key=api_key,
                index_name=index_name,
                dimension=3072,
                embedding_endpoint=embedding_endpoint,
                embedding_api_key=embedding_api_key,
                embedding_deployment=embedding_model,
                embedding_api_version=embedding_api_version,
            )

        # 다른 검색 엔진 타입 지원 시 여기에 추가
        return None

    def _create_llm_service(self, llm_type: str = "azure_openai"):
        if llm_type == "azure_openai":
            return AzureOpenAILlmService(
                azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
                # include_usage=True,
            )

    def _create_agent(self):
        llm_service = self._create_llm_service(llm_type="azure_openai")
        sql_runner = self._create_sql_runner(db_type="postgres")
        file_system = LocalFileSystem(working_directory="data/cache/dbsphere")

        agent_memory = self._create_agent_memory(memory_type="azure_search")

        tools = ToolRegistry()
        tools.register_local_tool(
            RunSqlTool(sql_runner=sql_runner, file_system=file_system),
            access_groups=["admin", "user"],
        )
        tools.register_local_tool(
            SaveQuestionToolArgsTool(), access_groups=["admin", "user"]
        )
        tools.register_local_tool(
            SearchSavedCorrectToolUsesTool(), access_groups=["admin", "user"]
        )
        tools.register_local_tool(SaveTextMemoryTool(), access_groups=["admin", "user"])
        tools.register_local_tool(
            VisualizeDataTool(file_system=file_system), access_groups=["admin", "user"]
        )

        user_resolver = CookieEmailUserResolver(
            cookie_name="vanna_email", allow_anonymous=True
        )

        return Agent(
            llm_service=llm_service,
            tool_registry=tools,
            user_resolver=user_resolver,
            agent_memory=agent_memory,
            config=AgentConfig(
                stream_responses=True, include_thinking_indicators=False
            ),
            system_prompt_builder=DBSpherePromptBuilder(),
            # llm_context_enhancer=DBSphereLlmContextEnhancer(sql_runner),
            # lifecycle_hooks=[DBSphereLifecycleHook()],
        )

    async def run(
        self,
        *,
        request,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        user,
    ):
        self.event_emitter = get_event_emitter(metadata)
        self.event_call = get_event_call(metadata)

        llm = self._create_llm(payload, stream=False)
        messages, system_prompt = self._extract_messages_and_prompt(payload)
        normalized_message = await self._normalize_message(messages, llm)
        result = await self._run_agent(normalized_message)

        return await self._run_stream(result, payload)

    async def _normalize_message(
        self,
        messages: List[Dict[str, Any]],
        llm: BaseChatModel,
    ) -> str:
        system_prompt = """
                당신은 '대화 맥락을 완벽히 이해하는 질의 재작성(Query Rewriter) 전문가'입니다.
                사용자의 채팅 히스토리를 분석하여, 사용자의 **마지막 발화**를 제3자가 봐도 완벽히 이해할 수 있는 **하나의 독립된 문장(Standalone Query)**으로 변환하는 것이 당신의 임무입니다.

                ### [목표]
                채팅 히스토리(Context)를 참고하여, 사용자의 **마지막 메시지**에 생략된 정보(주어, 목적어, 구체적인 대상)를 복원하고 명확한 문장으로 다시 쓰십시오.

                ### [핵심 원칙]
                1. **대명사 해결 (가장 중요):** '그것', '이거', '저번 것', '아까 말한 곳' 등 지시 대명사가 가리키는 실제 대상을 이전 대화에서 찾아 구체적인 명사로 교체하십시오.
                2. **문맥 통합:** 마지막 질문이 "가격은?", "거기는 어때?"처럼 앞선 대화에 의존하는 경우, 앞의 주제를 포함하여 완전한 문장으로 만드십시오. (예: "가격은?" -> "아이폰 15의 가격은 얼마입니까?")
                3. **의도 유지:** 사용자의 원래 의도나 질문의 뉘앙스(정중함, 급박함 등)를 훼손하거나 왜곡하지 마십시오.
                4. **불필요한 요소 제거:** 인사말("안녕하세요"), 감탄사("아 진짜요?"), 단순 호응("네 알겠습니다") 등 질문과 관계없는 텍스트는 제거하고 핵심 요청사항만 남기십시오.
                5. **언어:** 결과물은 반드시 자연스러운 **한국어**여야 합니다.

                ### [예시 데이터]
                **Case 1: 지시어 해결**
                - 히스토리: ["강남역 맛집 추천해줘", "파스타 파는 곳으로"]
                - 마지막 메시지: "거기 주차는 돼?"
                - 정규화 결과: "강남역에 있는 파스타 맛집들은 주차가 가능합니까?"

                **Case 2: 조건 변경**
                - 히스토리: ["2박 3일 제주도 여행 코스 짜줘"]
                - 마지막 메시지: "부산으로 변경해서 다시 알려줘"
                - 정규화 결과: "2박 3일 부산 여행 코스를 짜주세요."

                **Case 3: 단순 오타 및 불완전 문장**
                - 히스토리: ["맥북 프로 M3 스펙 알려줘"]
                - 마지막 메시지: "가격은 어떰?"
                - 정규화 결과: "맥북 프로 M3의 가격은 어떻습니까?"

                ### [출력 형식]
                반드시 아래 JSON 포맷으로만 출력하십시오. 코드 블록(```json)이나 부가 설명은 포함하지 마십시오.
                {
                    "normalized": "완성된 하나의 질문 문장"
                }
            """

        recent_messages = messages[-10:]

        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in recent_messages
        )

        user_prompt = f"""
                CONVERSATION HISTORY:
                {conversation_text}

                Extract and normalize the database question now.
                """

        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

        try:
            raw_content = response.content
            # Gemini/Vertex AI may return list of content blocks
            if isinstance(raw_content, list):
                raw_content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in raw_content
                )
            data = json.loads(raw_content)
            normalized_message = data["normalized"]
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "description": f"Normalized question : {normalized_message}",
                        "done": True,
                        "detail": f"Normalized question : {normalized_message}",
                    },
                }
            )
            return normalized_message
        except Exception:
            # fallback: 마지막 user 메시지
            return recent_messages[-1]["content"]

    async def _run_stream(
        self, agent_result: DBSphereAgentState, payload: Dict[str, Any]
    ):
        def _check_chart_data(chart_data: dict) -> str:
            if not chart_data:
                return ""

            status: Optional[str] = chart_data.get("status")
            error_reason: Optional[str] = chart_data.get("error_reason")
            requested: Optional[str] = chart_data.get("requested_chart_type")
            used: Optional[str] = chart_data.get("used_chart_type")

            if status in ("explicit_success", "auto_success") and requested == used:
                return ""

            # if status == "auto_success" and requested == "auto":
            #     return (
            #         "차트 유형은 데이터 구조를 기반으로 자동 선택되었습니다. "
            #         "데이터 특성을 가장 잘 표현할 수 있는 시각화 방식이 적용되었습니다."
            #     )

            if status == "fallback_auto":
                # If we ended up using the requested type, don't claim it was impossible
                if requested and used and requested == used:
                    return ""

                reason_text = (
                    f"요청한 차트 유형('{requested}')은 데이터 구조상 생성할 수 없었습니다."
                    if requested
                    else "요청한 차트 유형은 데이터 구조상 생성할 수 없었습니다."
                )

                if error_reason:
                    reason_text += f" 실패 사유: {error_reason}."

                if used:
                    reason_text += f" 대신 데이터를 가장 잘 표현할 수 있는 '{used}' 차트로 시각화했습니다."

                return reason_text

            if status == "error":
                base = "데이터를 시각화할 수 있는 차트를 생성하지 못했습니다."
                if error_reason:
                    base += f" 사유: {error_reason}."
                return base

            return ""

        system_prompt = f"""
            사용자는 데이터베이스를 자연어로 질의하여 아래와 같은 응답을 받았습니다.
            아래 내용을 참고하여 사용자에게 답변을 생성 합니다.

            기존 LLM의 응답 내용
            {agent_result.llm_response}
        """

        check_chart_data = _check_chart_data(agent_result.chart_data)

        if check_chart_data:
            system_prompt += f"""
                다음은 차트 생성시 발견된 이슈이며 이를 참고하여 최종 답변을 생성 합니다.

                {_check_chart_data(agent_result.chart_data)}"""

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            self._run_final_stream(payload, system_prompt, agent_result),
            media_type="text/event-stream",
            headers=headers,
        )

    async def _run_agent(self, message: str):
        dbsphere_agent_state = DBSphereAgentState()

        agent = self._create_agent()

        lifecycle_hooks = DBSphereLifecycleHook(
            self.event_emitter, self.event_call, dbsphere_agent_state
        )
        agent.lifecycle_hooks = [lifecycle_hooks]

        request_context = RequestContext(cookies={}, headers={})

        async for component in agent.send_message(
            request_context=request_context, message=message
        ):
            type = component.rich_component.type

            if type == ComponentType.TEXT:
                dbsphere_agent_state.llm_response = component.rich_component.content

        return dbsphere_agent_state

    async def _run_final_stream(
        self,
        payload,
        system_prompt,
        agent_result: DBSphereAgentState,
        display_message: str = None,
    ):
        """
        StreamResponse 시 OWUI의 openai_chat_chunk_message_template 형식으로 변환하여 SSE
        최종 완료 이벤트 전송
        """
        model_name = payload.get("model")
        payload["stream_options"] = {"include_usage": True}
        usage = None

        if agent_result.query_data:
            query_data = "\n".join(agent_result.query_data)
            query_data = f"```sql\n{query_data}\n```\n\n"

            yield self._sse(
                openai_chat_chunk_message_template(model_name, content=query_data)
            )

        def insert_usage(usage: dict):
            # 에이전트인 경우에만 agent_id 설정 (base_model_id가 있으면 에이전트)
            model_info = self.metadata.get("model", {})
            base_model_id = model_info.get("info", {}).get("base_model_id")
            agent_id = model_info.get("id") if base_model_id else None

            Usages.insert_new_usage(
                user_id=self.metadata.get("user_id"),
                chat_id=self.metadata.get("chat_id"),
                agent_id=agent_id,
                model_id=model_name,  # 실제 LLM 모델 ID
                message_id=self.metadata.get("message_id"),
                message_type=UsageMessageType.GENERATION,
                total_tokens=usage.get("total_tokens"),
                usage=usage,
            )

        async for chunk in self._create_llm(payload, stream=True).astream(
            system_prompt
        ):
            if chunk.usage_metadata:
                insert_usage(chunk.usage_metadata)
            piece = getattr(chunk, "content", "")
            # Gemini/Vertex AI returns list of content blocks
            if isinstance(piece, list):
                piece = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in piece
                )
            if isinstance(piece, str) and piece:
                payload = openai_chat_chunk_message_template(model_name, content=piece)
                yield self._sse(payload)

        if agent_result.chart_data:
            chart_json = agent_result.chart_data.get("chart_result") or ""

            # JSON 형식으로 전송
            chart_data = f"\n\n[[dbsphere:chart]]\n```json\n{chart_json}\n```\n\n"
            yield self._sse(
                openai_chat_chunk_message_template(model_name, content=chart_data)
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

    @staticmethod
    def _split_plotly_html(html: str) -> tuple[str, str]:
        """
        Split Plotly HTML into HTML and JS code blocks for OpenWebUI artifact rendering.
        HTML block contains divs; JS block contains script content and ensures Plotly loads.
        """
        if not html:
            return "", ""

        script_srcs = re.findall(
            r"<script[^>]*src=[\"']([^\"']+)[\"'][^>]*></script>",
            html,
            flags=re.IGNORECASE,
        )
        inline_scripts = re.findall(
            r"<script[^>]*>([\s\S]*?)</script>", html, flags=re.IGNORECASE
        )

        # Remove all script tags from HTML, keep divs and other markup.
        html_block = re.sub(
            r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE
        ).strip()

        js_lines = []
        if script_srcs:
            js_lines.append("(async () => {")
            for src in script_srcs:
                js_lines.append(
                    "await new Promise((resolve, reject) => {"
                    "const s = document.createElement('script');"
                    f"s.src = '{src}';"
                    "s.onload = resolve;"
                    "s.onerror = reject;"
                    "document.head.appendChild(s);"
                    "});"
                )
            for script in inline_scripts:
                script = script.strip()
                if script:
                    js_lines.append(script)
            js_lines.append("})();")
        else:
            for script in inline_scripts:
                script = script.strip()
                if script:
                    js_lines.append(script)

        js_block = "\n".join(js_lines).strip()
        return html_block, js_block
