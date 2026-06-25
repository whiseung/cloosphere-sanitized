"""Prompts for UnifiedAgent (DbSphere + KbSphere)."""

from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def _build_user_content_with_images(
    text: str, original_content: Any
) -> Union[str, List[Dict[str, Any]]]:
    """Build user message content preserving image blocks from the original.

    When the last user message contains images (multi-part content),
    the normalized_question only has the text portion. This function
    re-combines the text with the original image blocks so the LLM
    can see the images in the final answer prompt.

    Args:
        text: The normalized question text
        original_content: The original message content (str or list of blocks)

    Returns:
        str if no images, or list of content blocks with text + images
    """
    if not isinstance(original_content, list):
        return text

    # Extract non-text blocks (images, files, etc.)
    non_text_blocks = [
        block
        for block in original_content
        if isinstance(block, dict) and block.get("type") != "text"
    ]

    if not non_text_blocks:
        return text

    # Combine: text block + original image/file blocks
    return [{"type": "text", "text": text}, *non_text_blocks]


def get_unified_system_prompt(
    active_capabilities: List[str],
    task_prompt: str = "",
    unavailable_capabilities: Optional[List[str]] = None,
    current_datetime: str = "",
) -> str:
    """
    Build a concise system prompt for the unified agent.

    Tool-specific details (schema, SQL rules, search instructions) are in each
    tool's description — NOT repeated here. This prompt defines only the
    agent's role and completion signal.

    Args:
        active_capabilities: List of enabled capabilities. Recognized values:
            ``dbsphere``, ``kbsphere``, ``glossary``, ``knowledge_graph``,
            ``tool_connections``, ``web_search``, ``code_interpreter``,
            ``document_tools``, ``gmail``, ``calendar``, ``drive``. Each
            recognized value unlocks its dedicated hint block; unknown values
            are ignored.
        task_prompt: User-defined task prompt from agent settings (작업 프롬프트)
        unavailable_capabilities: Capabilities the agent has registered but
            which are NOT active this turn (e.g. user toggle off, OAuth not
            connected). LLM uses this to point the user at the exact action
            instead of hallucinating "no tool". Recognized values: ``gmail``,
            ``calendar``, ``drive``.

    Returns:
        System prompt string
    """
    if task_prompt and task_prompt.strip():
        base = task_prompt.strip()
    else:
        base = (
            "You are a data-gathering assistant. "
            "Use all available tools to collect relevant data and sources for the user's question. "
            "Do NOT write a final answer — just gather data."
        )

    # Current date/time anchor — without this the LLM cannot resolve relative
    # dates ("내일"/tomorrow, "다음 주 화요일") and silently guesses (e.g. books
    # "tomorrow" on today's date). Placed early so it applies to ALL time
    # reasoning, not just calendar tools.
    datetime_hint = ""
    if current_datetime and current_datetime.strip():
        datetime_hint = (
            f"\n\n**Current date and time**: {current_datetime.strip()}. "
            "Resolve every relative date/time in the user's request "
            "(today/tomorrow/yesterday/this week/next week, "
            "오늘/내일/어제/이번 주/다음 주, this afternoon, in N hours …) "
            "against THIS reference. When a calendar or scheduling tool needs a "
            "timezone, use the timezone shown here unless the user explicitly "
            "names another."
        )

    gmail_hint = ""
    if "gmail" in active_capabilities:
        gmail_hint = (
            "\n\n**Gmail tools** (`gmail_search`, `gmail_get`, `gmail_send`) are "
            "available. When the user asks about email — 메일, 이메일, mail, inbox, "
            "받은편지함, 보낸편지함 — use these tools instead of declining. "
            "`gmail_search` searches subject, body AND attachment text (e.g. "
            "`MPCI`, `from:alice@example.com`, `subject:invoice`, `has:attachment`, "
            "`newer_than:7d`). Use `gmail_get` with a result's `id` to fetch the full "
            "message body AND the extracted text of PDF/Office attachments "
            "(returned in `attachments[].content`). `gmail_send` is HITL-gated — the "
            "user must confirm before the email is actually sent, so the tool "
            "returning a confirmation marker means 'preview shown', not 'sent'.\n"
            "- Do NOT say 'no email tool available' or fabricate email content — the "
            "tool exists and you just called it (or should). If a Gmail tool returns "
            "an error (`google_reauth_required`, `gmail_api_error_403/429/...`), "
            "surface that error verbatim INCLUDING any actionable hint (re-auth URL, "
            "API enablement URL, retry timing) from the message. The user needs that "
            "hint to fix it — do not paraphrase it away.\n"
            "- **Composing/sending email → call `gmail_send`.** When the user wants "
            "to write, compose, draft, or send an email — 메일 작성/생성/초안/템플릿, "
            "공지 메일, 메일 뿌리기, 발송 — you MUST call the `gmail_send` tool to "
            "produce the editable send-confirmation preview, EVEN IF the user says "
            "'template'/'draft'/'템플릿'/'초안'. The preview IS the editable draft and "
            "the only way the user can actually send. **If you do NOT know the "
            "recipient address (e.g. the user said '거래처에' / 'to the client' "
            "without giving an email), STILL call `gmail_send` with an empty `to` "
            "list ([]) — the user fills in the recipient in the confirmation card. "
            "Never fall back to a plain-text draft just because the recipient is "
            "unspecified.** Do NOT just write the "
            "subject/body as plain text in your reply — that leaves the user with no "
            "Send button and defeats the integration. Write the email as plain text "
            "ONLY when the user explicitly says they do NOT want to send it (e.g. "
            "they just want wording to copy elsewhere).\n"
            "- **Replying to an email (답장/회신/reply):** the recipient is the "
            "ORIGINAL SENDER — the email's `From` (보낸사람).  Set `to` to that "
            "`From` address (extract the bare email, e.g. 'a@b.com' from "
            "'Name <a@b.com>'; it comes from gmail_get / gmail_search), and set "
            "`in_reply_to` to the email's `Message-Id`.  Do NOT leave `to` empty when "
            "replying, and do NOT use Reply-To or any other address — reply to the "
            "`From` sender."
        )

    unavailable_capabilities = unavailable_capabilities or []
    unavailable_hint = ""
    if unavailable_capabilities:
        # (short_name, icon, usage, topic_keywords) per capability.
        _cap_guide = {
            "gmail": (
                "Gmail",
                "📧",
                "메일 조회/발송",
                "메일, 이메일, mail, inbox, 받은편지함",
            ),
            "calendar": (
                "Google Calendar",
                "📅",
                "일정 조회/생성",
                "일정, 캘린더, calendar, 회의, 약속",
            ),
            "drive": (
                "Google Drive",
                "📁",
                "파일 조회/문서 생성",
                "파일, 문서, 드라이브, drive, document",
            ),
        }
        _ua = [_cap_guide[c] for c in unavailable_capabilities if c in _cap_guide]
        if _ua:
            bullet = "\n".join(
                f"  - **{short}** ({usage}): 입력창의 {icon} 토글 ON + Google 계정 연결 필요"
                for short, icon, usage, _kw in _ua
            )
            # 키워드/예시를 실제 미활성 capability 로만 한정한다. 활성화된 capability
            # 의 키워드가 섞이면 LLM 이 활성 기능을 미활성으로 오인하여 툴 호출을
            # 건너뛰거나 "미활성" 을 출력하는 회귀가 발생한다.
            _kw = ", ".join(kw for _s, _i, _u, kw in _ua)
            _names = "/".join(s for s, _i, _u, _k in _ua)
            _icons = "/".join(i for _s, i, _u, _k in _ua)
            unavailable_hint = (
                "\n\n**Capabilities configured but INACTIVE this turn** — the "
                "agent has the following capabilities registered, but the user "
                "has not enabled them for this conversation (chat-input toggle "
                "is OFF, or Google account is not yet connected):\n"
                f"{bullet}\n"
                f"- This applies ONLY to the capabilities listed above ({_names}). "
                "Any capability NOT listed here IS active this turn — call its tool "
                "normally and never claim it is unavailable.\n"
                f"- If the user asks specifically about these topics ({_kw}), DO NOT "
                "fall back to other tools to fake a result and DO NOT pretend "
                "the capability is missing. Instead, tell the user the EXACT "
                "action they need to take, in their language. Example response:\n"
                f'  > "이 에이전트는 {_names} 기능을 지원하지만 이번 '
                f"대화에서 활성화되지 않았습니다. 채팅 입력창의 {_icons} 토글을 "
                "켠 다음 다시 질문해 주세요. Google 계정이 아직 연결되지 "
                "않았다면 먼저 '설정 > 연결' 에서 Google 계정 연결이 "
                '필요합니다."\n'
                "- Do NOT fabricate email/event/file content from general "
                "knowledge — that would mislead the user about what is actually "
                "in their account."
            )

    calendar_hint = ""
    if "calendar" in active_capabilities:
        calendar_hint = (
            "\n\n**Calendar tools** (`calendar_list_events`, `calendar_find_free_slots`, "
            "`calendar_create_event`) are available. When the user asks about schedule, "
            "meetings, availability — 일정, 캘린더, 회의, 약속, 빈 시간, 일정 잡기 — "
            "use these tools. `calendar_list_events` reads events for a time range, "
            "`calendar_find_free_slots` finds open windows across attendees, "
            "`calendar_create_event` is HITL-gated and requires user confirmation "
            "before writing (the tool returning a confirmation marker means 'preview "
            "shown', not 'created').\n"
            "- All times use the user's IANA timezone — pass RFC3339 with offset "
            "(e.g. `2026-05-23T14:00:00+09:00`).\n"
            "- Do NOT fabricate events. If a Calendar tool returns an error, surface "
            "it verbatim with any actionable hint (re-auth URL, API enablement URL) "
            "from the message — do not paraphrase it away."
        )

    drive_hint = ""
    if "drive" in active_capabilities:
        drive_hint = (
            "\n\n**Google Drive tools** (`drive_search`, `drive_get_content`, "
            "`drive_create_doc`) are available. When the user asks about files, "
            "documents, folders — 드라이브, 파일, 문서, 폴더, drive, file, document, "
            "Google Doc — use these tools instead of declining. "
            "`drive_search` takes Drive's standard `q` query syntax. To find files "
            "by their CONTENT (e.g. an 'MPCI' keyword inside documents), use "
            "`fullText contains 'MPCI'` — searching by `name contains` alone misses "
            "files where the keyword is only in the body. Other operators: "
            "`mimeType='application/pdf'`, `'<folderId>' in parents`, "
            "`modifiedTime > '2026-01-01T00:00:00'`. "
            "Use `drive_get_content` with a result's `id` to read a file's text — "
            "Google Docs/Sheets/Slides, PDFs, and Office files (Word/Excel/PowerPoint) "
            "are extracted; images return metadata only. "
            "`drive_create_doc` is HITL-gated — the user must confirm before the "
            "Google Doc is actually created, so the tool returning a confirmation "
            "marker means 'preview shown', not 'created'.\n"
            "- Do NOT say 'no Drive tool available' or fabricate file content — the "
            "tool exists and you just called it (or should). If a Drive tool returns "
            "an error (`google_reauth_required`, `drive_api_error_403/429/...`), "
            "surface that error verbatim INCLUDING any actionable hint (re-auth URL, "
            "API enablement URL, retry timing) from the message — do not paraphrase "
            "it away."
            "\n- **Source picker (drive_select_files):** When the user asks you to "
            "compose an email or document FROM Drive materials AND a drive_search "
            "returned 2+ candidates, you MUST call `drive_select_files` with those "
            "candidates BEFORE reading — the user checks which files to include. "
            "Read ONLY the selected files (the selection returns as one or more "
            "`[file_id:<id>]` tokens — read them with drive_get_contents) and compose "
            "from only those. Do NOT read-and-synthesize all search results without "
            "this confirmation. Skip the picker only for plain Q&A (no compose)."
        )

    # Web search is an EXTERNAL / FALLBACK source. We do NOT assert that internal
    # tools are connected (this prompt serves general models AND multi-tool agents
    # alike) — the internal-preference clause is phrased conditionally ("if this
    # agent has connected sources"), so it self-applies only when relevant and is
    # harmlessly inert for a model with no tools. Triggers: (a) current/recent
    # info, (b) knowledge outside the model's training, (c) fallback when
    # connected tools can't answer. The private-data carve-out keeps "오늘 매출"
    # (the organization's OWN data) on the internal source rather than the web.
    web_search_hint = ""
    if "web_search" in active_capabilities:
        web_search_hint = (
            "\n\n**Web search tool** (`search_web`) gathers PUBLIC / EXTERNAL "
            "information from the open web. Use it when your own knowledge is not "
            "enough to answer reliably — specifically:\n"
            "- (a) **The question needs CURRENT or RECENT facts** that change over "
            "time or postdate your knowledge cutoff: today's weather (날씨), news/"
            "headlines (뉴스), public market prices (주가/환율/시세/코인), sports "
            "scores, product/version releases, recent public events.\n"
            "- (b) **The question needs EXTERNAL knowledge you were not trained on "
            "or do not reliably know** — niche, specialized, or domain-specific "
            "facts where answering from memory would just be guessing.\n"
            "- (c) **As a FALLBACK when connected tools cannot answer** — if this "
            "agent has connected internal sources (database / knowledge base / "
            "knowledge graph / glossary) and they returned nothing relevant or do "
            "not cover the question, widen to the web instead of giving up.\n"
            "PROACTIVELY search in these cases — do NOT wait for the user to say "
            "'웹에서 찾아봐' / 'search the web', and do NOT answer from memory or "
            "reply that you 'cannot access real-time data' / 'don't know'. Retry "
            "with refined or alternative terms if results are too few or stale.\n"
            "- BUT if this agent HAS connected internal sources and the answer is "
            "something they OWN — the organization's own sales, revenue, inventory, "
            "orders, customers, internal documents or policies, even when phrased "
            "with '오늘/이번 달/최신' — query the INTERNAL source FIRST; do not "
            "substitute a web search for the organization's private data."
        )

    # NOTE (W2): capability-specific tool guidance now lives in each tool's own
    # description (glossary/tool_connections/knowledge_graph/dbsphere SQL strategy/
    # document/code_interpreter), not in this prompt — see the respective tool
    # factories. Only cross-cutting behavioral guidance stays below.

    # ── 도구 호출 일반 원칙 (근거 수집 도구가 있을 때만) ──
    # 특정 도구나 도메인에 종속되지 않는 적응형 retry 가이드. 도구별
    # 상세 사용법은 각 tool description, capability-specific 시나리오는
    # 위의 hint 들에 둔다. 여기는 "결과가 부족할 때 어떻게 행동해야 하는가"
    # 의 행동 원칙만 담는다.
    #
    # retry / sufficiency-gate 가이드는 DB/KB/web/tool 등 "근거를 수집하는"
    # 도구가 있을 때만 의미가 있다. document_tools / code_interpreter 처럼
    # 산출물만 만드는 capability 만 켜진 (또는 도구 없는 일반) 모델에는
    # 불필요한 노이즈이며, "데이터에서 답을 못 찾으면 근거 부족" 이라는
    # 프레이밍이 일반 지식 질문조차 거부하게 만든다. 그래서 근거 수집형
    # capability 가 하나도 없으면 통째로 생략한다.
    _grounding_caps = {
        "dbsphere",
        "kbsphere",
        "glossary",
        "web_search",
        "tool_connections",
        "knowledge_graph",
        "gmail",
        "calendar",
        "drive",
    }
    tool_retry_hint = ""
    if any(c in _grounding_caps for c in active_capabilities):
        tool_retry_hint = (
            "\n\n**Tool-call retry strategy** (applies to all tools, all "
            "capabilities) — if a tool returns insufficient data, broaden "
            "parameters and retry BEFORE concluding:\n"
            "- Aggregation / list returned only 1 bucket (all rows mapped to "
            "a single category, NULL / 'unknown' / '미분류') → try a different "
            "GROUP BY column, or split COUNT NULL vs NOT NULL separately.\n"
            "- User asked for N items but fewer were found → retry with "
            "synonym, broader category, or drop a secondary filter one at a "
            "time.\n"
            "- WHERE / filter returned 0 rows → relax the predicate (LIKE → "
            "broader pattern, drop the most restrictive filter first, try an "
            "alternative column with similar semantics).\n"
            "- Multi-criteria query returned nothing → progressively drop "
            "filters from most restrictive to least.\n"
            "- Tool returned an error or empty result → fix the parameter "
            "shape and retry; do NOT silently fall back to general knowledge "
            "or fabricate values.\n"
            "Goal: deliver the most complete grounded answer the data "
            "supports — not the first answer that superficially matches the "
            "question. Stop retrying only when broader scope clearly exhausts "
            "the available data surface."
            "\n\n**Sufficiency gate (before submit_result).** A non-empty tool "
            "result is NOT proof that the answer is present. Before concluding, "
            "verify the gathered context actually contains the SPECIFIC fact the "
            "user asked for. If the results are non-empty but do NOT contain the "
            "answer:\n"
            "- Retry the SAME source with a different filter — drop or change the "
            "most restrictive predicate, or try an alternative metadata value.\n"
            "- Retry with ALL filters removed — run the query against the full "
            "scope, not a filtered subset.\n"
            "- Search a DIFFERENT knowledge base / tool that could hold the "
            "answer. If multiple knowledge sources are registered, do not rely on "
            "just one.\n"
            "- Re-query with broader or alternative terms — synonyms, a parent "
            "category, or removing date/ID specifics.\n"
            "Make at least one such alternative attempt before deciding the data "
            "does not cover the question. Conclude 'no answer' only after the "
            "relevant sources are genuinely exhausted — never after a single "
            "search that returned unrelated results."
        )

    gws_workflow_hint = ""
    if "gmail" in active_capabilities or "drive" in active_capabilities:
        gws_workflow_hint = (
            "\n\n**Multi-source gather → compose workflow** (Drive/Gmail): when the "
            "user asks to find materials across Drive and past email and then write "
            "an email or report from them, follow this order — (1) SEARCH first: "
            "`drive_search` with `fullText contains '<keyword>'` AND `gmail_search` "
            "'<keyword>' (both index file/attachment content). (2) READ the relevant "
            "hits to get the actual text (PDF/Office/attachments are extracted) — "
            "BUT when the goal is to COMPOSE from these and drive_search returned 2+ "
            "files, FIRST call `drive_select_files` so the user checks which files to "
            "include, then read ONLY the selected ones. "
            "When reading SEVERAL selected items, use the batch tools "
            "`drive_get_contents` / "
            "`gmail_get_batch` (one call for many ids) to conserve the tool-call "
            "budget instead of many single `drive_get_content` / `gmail_get` calls. "
            "Do NOT synthesize from search snippets alone — read the files first. "
            "(3) De-duplicate overlapping "
            "sources. (4) Only AFTER reading, compose: `gmail_send` (draft email, "
            "HITL) or `create_docx` (Word report)."
        )
    # ask_user guidance (call conditions, last-resort priority, choices rules)
    # now lives entirely in the ask_user tool description (ask_user_tool.py) and
    # the AskUserInput.choices field — removed from the prompt to avoid duplication.

    return (
        f"{base}{datetime_hint}{gmail_hint}{calendar_hint}{drive_hint}"
        f"{web_search_hint}{gws_workflow_hint}{unavailable_hint}{tool_retry_hint}\n\n"
        "When done, call submit_result to set the language and format for your final answer. "
        "The final answer is generated based on the submit_result parameters you provide."
    )


def get_unified_dynamic_prompt(state: Dict[str, Any]) -> str:
    """Build dynamic system prompt from state for middleware.

    Currently unused — the system prompt is static.
    Kept for future use with _create_dynamic_prompt_with_trace().
    """
    return get_unified_system_prompt(
        active_capabilities=state.get("active_capabilities", []),
        task_prompt=state.get("task_prompt", ""),
    )


def resolve_citation_mode(
    *,
    has_uploaded: bool,
    has_citation_sources: bool,
    use_structured: bool,
) -> str:
    """Deterministic 2-state citation policy (PR3).

    - structured output(json_schema) → 'none' (citation markers corrupt schema)
    - KB/web 등 citation-worthy source 존재 → 'required' (legacy 인용 on)
    - chat upload 단독 → 'optional' (인용 off — 깔끔한 요약/재구성)
    - source 없음 → 'none'

    'mixed' 상태는 의도적으로 없음(hallucinated citation 유발). KB 와 upload 가
    공존하면 'required' 이고 인용은 KB(Document Sources) 섹션에만 적용된다.
    """
    if use_structured:
        return "none"
    if has_citation_sources:
        return "required"
    if has_uploaded:
        return "optional"
    return "none"


def split_source_contexts(
    source_bundles: Optional[Dict[str, List[Dict[str, Any]]]],
) -> Tuple[str, str, List[Dict[str, Any]], bool, bool]:
    """typed source bundle 를 final-answer prompt 용 context 로 분할한다 (PR3).

    chat_upload 은 [i] 인덱스 없는 uploaded context 로, 그 외(KB/web/unknown)는
    번호 매긴 citation context 로 분리한다. citation source event 목록도 함께 반환해
    emit 순서가 [i] 번호와 위치 정합되도록 한다(FE Source.svelte: [i]→citation[i-1]).

    Returns:
        (sources_context, uploaded_files_context, citation_events,
         has_citation_sources, has_uploaded)
        citation_events: emit 할 {source,document,metadata,distances} dict 의 순서
        있는 리스트 — i 번째가 [i+1] citation 에 대응(단일 진실 공급원).
    """
    source_lines: List[str] = []
    uploaded_lines: List[str] = []
    citation_events: List[Dict[str, Any]] = []
    idx = 1
    has_citation_sources = False
    has_uploaded = False

    for source_type, bundles in (source_bundles or {}).items():
        for bundle in bundles:
            docs = [
                d.strip()
                for d in (bundle.get("document") or [])
                if isinstance(d, str) and d.strip()
            ]
            if not docs:
                continue
            name = bundle.get("display_name") or "N/A"
            if source_type == "chat_upload":
                has_uploaded = True
                uploaded_lines += [f"### {name}", *docs, ""]
            else:
                has_citation_sources = True
                citation_events.append(
                    {
                        "source": bundle.get("source"),
                        "document": bundle.get("document") or [],
                        "metadata": bundle.get("metadata") or [],
                        "distances": bundle.get("distances") or [],
                    }
                )
                source_lines += [f"[{idx}] {name}", *[f"- {d}" for d in docs], ""]
                idx += 1

    return (
        "\n".join(source_lines).strip(),
        "\n".join(uploaded_lines).strip(),
        citation_events,
        has_citation_sources,
        has_uploaded,
    )


def get_unified_final_answer_prompt(
    # KbSphere data
    sources_context: str = "",
    # Chat-uploaded files (current conversation) — separate from persistent KB.
    uploaded_files_context: str = "",
    # Deterministic citation policy: 'required' | 'optional' | 'none' (PR3)
    citation_mode: str = "required",
    # DbSphere data
    llm_response: str = "",
    sql_results: str = "",
    chart_status_message: str = "",
    # Image generation
    image_generation_content: str = "",
    # Document generation (create_pptx/docx/xlsx 가 이번 턴에 만든 파일 링크 목록)
    document_tool_links: Optional[List[str]] = None,
    # Common
    normalized_question: str = "",
    language: str = "Korean",
    messages: Optional[List[Any]] = None,
    active_capabilities: List[str] = None,
    format_prompt: str = "",
    guardrail_context: str = "",
    # Glossary data
    glossary_context: str = "",
    # Tool connections data
    tool_connections_context: str = "",
    # UI action tool results (fill_form_field 등 — host page dashboard bridge 가 반환한 JSON)
    ui_action_context: str = "",
    # User memory context (pre-fetched long-term + retrieved history)
    user_memory_context: str = "",
    # Conversation summary (adaptive compression of old messages)
    conversation_summary: str = "",
    # Code interpreter execution results
    code_interpreter_context: str = "",
    # Knowledge graph context (from KG tool results)
    kg_context: str = "",
    # Tool error aggregation — JSON error payloads returned by tools
    # (e.g. Gmail 403 with API enablement URL, google_reauth_required, ...).
    # Surfaced as a dedicated ## Tool Errors section so the LLM cannot
    # mis-classify them as "no data".
    tool_errors_context: str = "",
    # Google Workspace tool SUCCESS results (gmail_/calendar_/drive_) — JSON
    # payloads of fetched mail/events/files. These have no other context slot,
    # so without this the final-answer LLM never sees them and says "no data".
    google_results_context: str = "",
    # Capabilities the agent has registered but which were INACTIVE this turn
    # (toggle off / OAuth not connected). Rendered as a ## Unavailable
    # Capabilities section so the final-answer LLM gives the actionable guidance
    # instead of "no email tool" hallucination.
    unavailable_capabilities: Optional[List[str]] = None,
    # Image passthrough: include image blocks in the last user message
    # (for no-tools path where agent phase is skipped)
    include_images: bool = False,
    # 엄격 근거 준수(grounding) 모드. **디폴트 True (기존 동작)**.
    #   True  → 수집한 데이터에만 근거해 답하고, 없으면 "자료 없음" 명시(환각 방지).
    #   False → 연결 소스를 우선하되 부족 시 일반 지식으로 보완(거부 안 함). 단,
    #           사용자의 PRIVATE 데이터(문서/DB/메일 등) 날조는 여전히 금지.
    # 에이전트 capabilities.grounding 토글(AgentConfig.is_grounding_enabled())에서 전달.
    grounding_enabled: bool = True,
) -> Any:
    """
    Build the final answer prompt for unified response.

    Args:
        sources_context: Aggregated sources from KbSphere (formatted string)
        llm_response: LLM analysis from DbSphere agent
        sql_results: SQL query execution results (data preview from run_sql tool)
        chart_status_message: Chart generation status message
        normalized_question: User's normalized question
        language: Response language
        messages: Conversation history
        active_capabilities: List of active capabilities
        format_prompt: User-defined response format prompt from agent settings
        tool_errors_context: Aggregated `[tool_name] {error_json}` lines from
            ToolMessages whose payload contained an ``error`` field. Rendered
            as a dedicated ``## Tool Errors`` section so the final-answer LLM
            cannot mis-classify them as "no data".

    Returns:
        List of messages for final answer generation
    """
    active_capabilities = active_capabilities or []
    unavailable_capabilities = unavailable_capabilities or []
    messages = messages or []

    # Check if agent gathered any data
    has_data = any(
        [
            sources_context and sources_context.strip(),
            uploaded_files_context and uploaded_files_context.strip(),
            sql_results and sql_results.strip(),
            llm_response and llm_response.strip(),
            chart_status_message and chart_status_message.strip(),
            image_generation_content and image_generation_content.strip(),
            glossary_context and glossary_context.strip(),
            tool_connections_context and tool_connections_context.strip(),
            # tool_errors_context is data — surfacing the error IS the answer.
            tool_errors_context and tool_errors_context.strip(),
            # unavailable_capabilities is also "data" — pointing the user to the
            # enable path IS the answer when they asked about email/calendar.
            bool(unavailable_capabilities),
            ui_action_context and ui_action_context.strip(),
            user_memory_context and user_memory_context.strip(),
            code_interpreter_context and code_interpreter_context.strip(),
            kg_context and kg_context.strip(),
        ]
    )

    # Fallback: if normalized_question is empty, extract from last user message
    if not normalized_question or (
        isinstance(normalized_question, str) and not normalized_question.strip()
    ):
        for msg in reversed(messages or []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                # Extract text only (content may be multi-part list with images)
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, str):
                            text_parts.append(block)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    normalized_question = " ".join(text_parts)
                else:
                    normalized_question = content
                break

    # Capabilities that GATHER grounding data. When one of these is active we keep
    # the strict grounding prompt even if this turn gathered nothing — the agent
    # was meant to ground its answer in that source, so it must say "the data does
    # not cover this" rather than answer from general knowledge.
    #
    # Pure output/utility capabilities (document_tools, code_interpreter) only
    # PRODUCE artifacts; they make no grounding promise. When they are the ONLY
    # active capabilities and nothing was gathered/created, the user just asked a
    # general question (e.g. "각 나라별 언어를 알려줘") and must get a normal
    # general-knowledge answer — NOT a "근거 자료가 없습니다" refusal. A plain
    # model with document_tools defaulted on must still behave like a chat model.
    grounding_capabilities = {
        "dbsphere",
        "kbsphere",
        "glossary",
        "web_search",
        "tool_connections",
        "knowledge_graph",
        "gmail",
        "calendar",
        "drive",
    }
    grounding_active = [c for c in active_capabilities if c in grounding_capabilities]

    # No agent data AND no grounding-capable tool active: lightweight prompt for
    # casual conversation. document_tool_links is guarded separately so a file
    # actually created this turn still routes through the full prompt (renders the
    # "Document Generation Notes" section — otherwise the LLM denies its own file).
    if (
        not has_data
        and not document_tool_links
        and not guardrail_context
        and not grounding_active
    ):
        lang_instruction = (
            f" Respond in {language}."
            if language
            else " Respond in the same language the user is using."
        )
        base_prompt = f"You are a helpful assistant.{lang_instruction}"
        if format_prompt and format_prompt.strip():
            base_prompt += f"\n\n{format_prompt.strip()}"

        result = [SystemMessage(content=base_prompt)]
        # Add conversation history, excluding the last user message (added separately below)
        last_user_idx = None
        last_user_content = None
        for i, msg in enumerate(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user_idx = i
                last_user_content = msg.get("content", "")
        for i, message in enumerate(messages):
            if isinstance(message, dict):
                role = message.get("role")
                content = message.get("content", "")
                if role == "system":
                    continue
                if i == last_user_idx:
                    continue  # skip last user msg, will be added as normalized_question
                elif role == "user":
                    result.append(HumanMessage(content=content))
                elif role == "assistant":
                    result.append(AIMessage(content=content))

        # Build the last user message: use normalized_question for text.
        # Only include image blocks when include_images=True (no-tools path
        # where agent phase is skipped and LLM needs to see the image directly).
        if include_images:
            final_user_content = _build_user_content_with_images(
                normalized_question, last_user_content
            )
        else:
            final_user_content = normalized_question
        result.append(HumanMessage(content=final_user_content))
        return result

    # Relax the strict "answer ONLY from gathered data" contract in two cases:
    #   1) web_search active — the model owner enabled external/world knowledge.
    #      Strict grounding is then self-contradictory: it makes the agent REFUSE
    #      general-knowledge questions ("각 나라별 언어를 알려줘") it could answer.
    #   2) grounding toggle OFF — the operator explicitly opted this agent out of
    #      strict grounding (capabilities.grounding = "off") so it behaves like a
    #      general assistant that prefers connected sources but falls back to its
    #      own knowledge instead of replying "the data does not cover this".
    # In BOTH relaxed modes we STILL never fabricate the user's PRIVATE data (KB
    # doc contents, DB rows, mail/calendar/file contents). With grounding ON and
    # no web_search (pure KB/DB grounding) we keep the strict contract so an
    # enterprise document/data bot still says "the data does not cover this".
    allow_general_knowledge = (
        "web_search" in active_capabilities or not grounding_enabled
    )

    if allow_general_knowledge:
        grounding_rules = (
            "- Prefer the gathered data shown below. When it answers the "
            "question, base your answer on it and cite the connected sources "
            "(KB / DB / web) — they take priority over memory.\n"
            "- If the gathered data is empty or does NOT cover the question, "
            "answer from your own general knowledge instead of refusing. Be "
            'direct and helpful; do NOT say "the available tools and data do '
            'not cover this". You may briefly note when an answer is general '
            "knowledge rather than from the connected sources."
        )
        no_fabricate_rule = (
            "- Never fabricate the user's PRIVATE data — specific KB document "
            "contents, database rows/values/counts, email/calendar/file "
            "contents, IDs, URLs, or quotes that do not appear in the gathered "
            "data. (General, widely-known world knowledge is fine; inventing "
            "specifics about the connected sources is not.)"
        )
    else:
        grounding_rules = (
            "- Your answer MUST be grounded in the gathered data shown below. "
            "Do not use external or general knowledge to fill gaps.\n"
            "- If the gathered data is genuinely empty (no relevant rows, no "
            "matching documents, no tool calls were made, or tool outputs "
            "returned zero results AND there is no `## Tool Errors` / "
            "`## Unavailable Capabilities` section), state explicitly and "
            "concisely that the available tools and data do not cover the "
            "question. Then offer to refine the query or suggest what "
            "additional resource would be needed."
        )
        no_fabricate_rule = (
            "- Never fabricate entity names, values, counts, dates, IDs, URLs, "
            "quotes, or any content that does not appear in the gathered data."
        )

    # Build system prompt sections (agent gathered data)
    base_prompt = f"""You are a helpful assistant providing a comprehensive answer based on the gathered information.

## Grounding Rules (apply to every response)
{grounding_rules}
- **Tool errors are NOT "no data".** If a `## Tool Errors` section appears below, a tool reached the service and the service returned an explicit failure with actionable instructions. You MUST surface those errors to the user: quote the `message` / `hint` field verbatim (especially URLs, re-auth links, and "Enable it by visiting ..." style instructions) and state the concrete action the user needs to take (enable an API, re-authenticate, wait N minutes for retry). Do NOT say "the tool is unavailable", "I cannot do X", or "there is no email/calendar tool" — the tool IS available; it returned a specific fixable error and the user needs to see the actual message to fix it.
- **Inactive capabilities are NOT "no data" either.** If a `## Unavailable Capabilities` section appears below, the agent has the capability configured but the user has not activated it this turn (toggle off / OAuth not connected). Tell the user the EXACT activation steps from that section verbatim. Do NOT fabricate email/event content from general knowledge — that would mislead them about their actual account.
{no_fabricate_rule}"""

    # PR3 회귀 구멍: citation marker rule 은 citation 이 켜졌을 때만 주입한다.
    # 무조건 주입하면 chat-upload-only 답변에도 [1] 인용을 재점화시킨다.
    # (merge: GWS 의 무조건 citation 규칙 대신 PR3 의 조건부 버전 유지.)
    if citation_mode == "required":
        base_prompt += "\n- Never attach citation markers like [1], [2] to statements that are not directly supported by the Document Sources section. Citation markers must map to real items in that section."

    sections = []

    # Uploaded files section (chat-time uploads) — current task material, NOT a
    # persistent grounding source. No [1][2] citation by default (PR3).
    if uploaded_files_context and uploaded_files_context.strip():
        sections.append(f"""
## Uploaded Files (current conversation)
The user uploaded the following file(s) in this chat. Treat them as the primary
material for the current request.

{uploaded_files_context}

### How to use uploaded files
- When the user asks to summarize, rewrite, reorganize, translate, or convert these files, produce a clean, well-structured answer in your own organized form — do NOT dump raw excerpts and do NOT attach [1], [2] citation markers.
- Preserve meaningful structure (headings, tables, lists) faithfully.
- Add exact quotes or references ONLY if the user explicitly asks for quotes, page numbers, or evidence.
""")

    # Tool errors section — placed FIRST so the LLM can't overlook it.
    # Each entry is "[tool_name] {json}" from a ToolMessage whose JSON payload
    # contained an `error` field.  These are explicit service failures with
    # actionable hints (URLs, re-auth instructions) — NOT empty results.
    if tool_errors_context and tool_errors_context.strip():
        sections.append(f"""
## Tool Errors
The following tool calls returned errors during this turn. These are explicit failures with actionable instructions — they are NOT empty results.

{tool_errors_context}

### How to surface these to the user
- Quote the `message`, `hint`, and any URL verbatim in your response — the user needs the exact link / instruction to fix this.
- Tell the user the concrete action: "Gmail API 활성화가 필요합니다. 다음 링크에서 활성화 후 1~2분 후 다시 시도해 주세요: <URL>" / "Google 계정 재인증이 필요합니다: 설정 > 연결에서 다시 연결해 주세요." 같이.
- Do NOT paraphrase the error as "the tool is not available" or "I cannot retrieve emails" — the tool is available and the user can fix this specific failure.
""")

    # Google Workspace results section — SUCCESS payloads from gmail_/calendar_/
    # drive_ tools. Placed before the Unavailable Capabilities guidance so REAL
    # fetched data takes priority: the tool ran and returned the user's actual
    # mail/events/files, and the LLM MUST answer from it instead of falling back
    # to "no data" / "not activated".
    if google_results_context and google_results_context.strip():
        sections.append(f"""
## Gathered Data (Google Workspace)
The following results were returned by Google Workspace tools (Gmail / Calendar / Drive) during this turn. This is REAL data fetched from the user's own account — each line is `[tool_name] {{json_payload}}`.

{google_results_context}

### How to use this data
- Answer the user's question DIRECTLY from this data (e.g. for `gmail_search`, list each message's `headers.Subject` and `headers.From`; for calendar, the event summaries/times; for drive, file names).
- Preserve exact subjects / senders / dates / values — do NOT invent, omit, or summarize away specifics.
- The tool already ran successfully, so NEVER say "no data was provided", "I cannot access your mail", or "the feature is not activated". The data is right above.
""")

    # Unavailable capabilities section — agent has these registered but user
    # didn't activate them this turn (toggle off / OAuth missing). Mirror of
    # the Tool Errors section semantically: there IS an action the user can
    # take; the LLM must surface it verbatim instead of hallucinating "no tool".
    if unavailable_capabilities:
        # (short_name, icon, usage, topic_keywords) per capability.
        _cap_guide = {
            "gmail": (
                "Gmail",
                "📧",
                "메일 조회/발송",
                "메일, 이메일, mail, inbox, 받은편지함",
            ),
            "calendar": (
                "Google Calendar",
                "📅",
                "일정 조회/생성",
                "일정, 캘린더, calendar, 회의, 약속",
            ),
            "drive": (
                "Google Drive",
                "📁",
                "파일 조회/문서 생성",
                "파일, 문서, 드라이브, drive, document",
            ),
        }
        _ua = [_cap_guide[c] for c in unavailable_capabilities if c in _cap_guide]
        if _ua:
            _ua_bullet = "\n".join(
                f"- **{short}** ({usage}): 입력창의 {icon} 토글 ON + Google 계정 연결 필요"
                for short, icon, usage, _kw in _ua
            )
            # 키워드/예시를 실제 미활성 capability 로만 한정한다. 활성화된 capability
            # (예: Gmail 켜짐 + Calendar/Drive 꺼짐) 의 키워드/예시가 섞여 들어가면
            # LLM 이 "메일" 질문을 미활성 안내로 오인해, 이미 가져온 gmail_search
            # 데이터를 버리고 "Gmail 미활성" 을 출력하는 회귀가 발생한다.
            _ua_keywords = ", ".join(kw for _s, _i, _u, kw in _ua)
            _ua_names = "/".join(s for s, _i, _u, _k in _ua)
            _ua_icons = "/".join(i for _s, i, _u, _k in _ua)
            sections.append(f"""
## Unavailable Capabilities
The agent is configured with the following capabilities, but the user has NOT activated them this turn (chat-input toggle is OFF, or Google account is not yet connected):

{_ua_bullet}

### How to surface these to the user
**Scope**: This section applies ONLY to the capabilities listed above ({_ua_names}). Any capability NOT listed here IS active this turn — if its tool already returned data (e.g. a `gmail_search` / `calendar_*` / `drive_*` result in the gathered data), use that data normally and NEVER claim it is unavailable.

If the user's question is about these specific topics ({_ua_keywords}), respond with the EXACT activation steps in their language. Example:

> 이 에이전트는 {_ua_names} 기능을 지원하지만 이번 대화에서 활성화되지 않았습니다.
>
> 1. 채팅 입력창 좌측의 {_ua_icons} 토글을 ON 으로 변경
> 2. 토글이 회색으로 비활성화되어 있다면 '설정 > 연결' 에서 먼저 Google 계정 연결
> 3. 그 다음 질문을 다시 입력

- Do NOT pretend the capability does not exist — it IS configured; only the user's per-conversation activation is missing.
- Do NOT fabricate email/event/file content from general knowledge — that would mislead them about their actual account.
- If the user's question is NOT about the topics listed above, ignore this section entirely.
""")

    # KbSphere sources section
    if sources_context and sources_context.strip():
        doc_section = f"""
## Document Sources
The following information was retrieved from documents and knowledge bases:

{sources_context}
"""
        # Citation Rules 는 citation 이 켜졌을 때만 — structured/upload-only 답변엔 생략.
        if citation_mode == "required":
            doc_section += """
### Citation Rules
- Reference document sources using [1], [2] format at the end of relevant statements
- Citations apply ONLY to document sources above — do NOT cite glossary terms, SQL results, or other non-document data
- Prefer internal documents over web search results
"""
        sections.append(doc_section)

    # Glossary section
    if glossary_context and glossary_context.strip():
        sections.append(f"""
## Glossary Terms
The following term definitions were found in the glossary (용어집):

{glossary_context}

Use these definitions to answer the user's question accurately.
- Do NOT add citation references like [1], [2] for glossary terms — citations are only for document sources
""")

    # Knowledge graph context section
    if kg_context and kg_context.strip():
        sections.append(f"""
## Knowledge Graph Results
The following information was retrieved from the knowledge graph (지식 그래프).
This contains business term definitions, database table/column mappings, entity relationships, and KB filter-derived document attribute nodes (the specific filter slots and values are domain-specific and visible in the results below).

{kg_context}

- Use these results as the PRIMARY source for answering about tables, columns, terms, and relationships
- Do NOT guess or use general knowledge when KG results provide specific information
- Do NOT add citation references like [1], [2] for KG results — citations are only for document sources
""")

    # Conversation summary (adaptive compression of old messages)
    if conversation_summary and conversation_summary.strip():
        sections.append(f"""
## Previous Conversation Summary
The following is a summary of earlier parts of this conversation that are no longer in the message history.
Use this to maintain continuity and avoid repeating already-discussed topics.

{conversation_summary}
""")

    # User memory section (long-term memory + retrieved conversation history)
    if user_memory_context and user_memory_context.strip():
        sections.append(f"""
## User Memory
The following is known about this user from previous conversations and earlier in this chat.
The "Profile" subsection (if present) is an auto-generated summary of the user; "Relevant Context" contains specific facts related to the current query.

{user_memory_context}

Use this context to provide personalized, consistent responses.
- Do NOT add citation references like [1], [2] for user memory — citations are only for document sources
""")

    # Tool connections results section
    if tool_connections_context and tool_connections_context.strip():
        sections.append(f"""
## External Tool Results
The following data was retrieved from external tool servers (MCP/OpenAPI):

{tool_connections_context}

- Use these results to answer the user's question
- Do NOT add citation references like [1], [2] for tool results — citations are only for document sources
""")

    # UI action tool results section
    # 호스트 페이지의 UI 액션 도구(fill_form_field, click_element, read_form 등)가 반환한 payload.
    # 도메인 무관한 범용 표현 — 임베드 위젯이 사용되는 어떤 호스트 페이지든 그대로 적용됨.
    if ui_action_context and ui_action_context.strip():
        sections.append(f"""
## UI Action Tool Results
The following payload was returned by host-page UI action tools (e.g. fill_form_field, click_element, read_form):

{ui_action_context}

- This payload reflects the CURRENT state of the host page as reported by the bridge.
- **Treat this as an authoritative source** when answering questions about the page or its data.
- Cite **only values that literally appear in this payload**. Do NOT fabricate, extrapolate, or draw from prior knowledge any values not explicitly present.
- If a field is empty / null / zero, state that clearly; do NOT substitute plausible-sounding values.
- Do NOT add citation references like [1], [2] — those apply only to document sources.
""")

    # DbSphere SQL results section (executed queries + their results from run_sql tool)
    if sql_results and sql_results.strip():
        sections.append(f"""
## SQL Query Results
The following SQL queries were executed against the database (in execution order), each shown with its result:

{sql_results}

GROUNDING RULES — read before describing any numbers:
- Your analysis scope (region, time period, product/granularity, and every filter) MUST match what the SQL actually did: the WHERE clause, GROUP BY, and selected columns above. Describe the data the SQL returned — not what the question seemed to ask for.
- If the user's wording maps ambiguously to the SQL (an abbreviation, a code, or a value that could exist in more than one column), do NOT silently pick a label. EXPLICITLY state which column and value the SQL filtered on (e.g. "filtered on subsidiary = 'SEA'") and flag the possible mismatch so the user can confirm.
- Do NOT relabel or "translate" the scope using glossary terms or prior knowledge when they contradict the actual SQL filter. The SQL's WHERE/GROUP BY is the source of truth for scope; a glossary definition never overrides it.
- If the executed SQL does not actually answer the user's question (wrong column, wrong value, or empty result), say so plainly instead of presenting unrelated numbers as the answer.
- Do NOT add citation references like [1], [2] for SQL results — citations are only for document sources.
""")

    # Code interpreter execution results
    if code_interpreter_context and code_interpreter_context.strip():
        # Strip any remaining Plotly JSON markers from text context
        if code_interpreter_context:
            clean_lines = [
                line
                for line in code_interpreter_context.split("\n")
                if not line.startswith("__PLOTLY_JSON__")
            ]
            code_interpreter_context = "\n".join(clean_lines).strip()

        sections.append(f"""
## Code Execution Results
The following results were produced by executing Python code on the uploaded data files:

{code_interpreter_context}

- Present these results clearly to the user using markdown tables (users can download as CSV)
- Explain the results in the user's language
- If the data contains tabular output, format it as a markdown table
- The interactive chart will be displayed separately below your answer
- Do NOT generate any charts in your text (no ASCII art, no text bar charts, no mermaid, no matplotlib code blocks)
- Do NOT say charts are missing or unavailable — they are rendered separately
- Do NOT include code examples in your answer — the code has already been executed
""")

    # DbSphere analysis section (agent's interpretation)
    if llm_response and llm_response.strip():
        sections.append(f"""
## Agent Analysis
{llm_response}
""")

    # Chart status
    if chart_status_message and chart_status_message.strip():
        sections.append(f"""
## Chart Generation Notes
{chart_status_message}
""")

    # Image generation
    if image_generation_content and image_generation_content.strip():
        sections.append("""
## Image Generation Notes
The user's image request has been SUCCESSFULLY completed. The image is already displayed above.
- NEVER output image markdown syntax like ![...](...) — the image is already shown
- NEVER invent or hallucinate image URLs
- Do NOT say you cannot generate or edit images — the tool already did it
- Respond with ONLY a brief text (1-2 sentences) acknowledging the result
""")

    # Document generation (PPT/Word/Excel via create_pptx/docx/xlsx)
    # 이번 턴에 실제로 만들어진 파일이 있으면 (document_tool_links 비어있지 않음),
    # final answer 가 그 사실을 부정 못 하도록 명시적 컨텍스트 + 강한 directive 주입.
    if document_tool_links:
        links_block = "\n".join(f"- {link}" for link in document_tool_links)
        sections.append(f"""
## Document Generation Notes — TOOL EXECUTION SUCCESSFUL
The user's document generation request has been **SUCCESSFULLY COMPLETED**. The
following file(s) have been created and saved. The download link(s) below are
already shown to the user above (streamed before this final answer):

{links_block}

STRICT RULES:
- The file EXISTS. Do NOT say "현재 제공된 도구 결과에는 파일을 생성할 수 있는 도구
  실행 결과가 없습니다" or any variant. That is FALSE — the tool returned successfully.
- Do NOT regenerate the data as CSV / TSV / 마크다운 표 / "복사해서 저장" guidance.
  The actual file is already created.
- Respond with ONLY a brief 1-2 sentence acknowledgment in the user's language
  (e.g., "요청하신 데이터를 첨부 파일로 생성했습니다. 위 링크에서 다운로드하세요.").
- Do NOT repeat the markdown link text — it is already shown above.
""")

    # Guardrail context
    if guardrail_context:
        sections.append(f"""
## Guardrail Notice
The user's message contained sensitive information that has been processed: {guardrail_context}
- IMPORTANT: At the beginning of your response, write ONE short sentence informing the user which specific type(s) of sensitive information were detected (use the exact types listed above, e.g. "이메일", "주민등록번호") and that they were redacted/masked
- Do NOT use generic phrases like "sensitive information" or "personal data" — always mention the SPECIFIC detected type(s)
- Do NOT attempt to guess, reconstruct, or reveal the original content behind redacted/masked/hashed markers
- After the ONE sentence notice, continue answering the question using only the visible, non-redacted information
""")

    # Response guidelines
    guideline_items = [
        "Provide a clear, helpful answer to the user's question",
    ]
    if language:
        guideline_items.append(f"Respond in {language}")
    else:
        guideline_items.append("Respond in the same language the user is using")

    # PR3 회귀 구멍: citation 이 켜졌을 때만 인용 가이드라인 주입.
    if (
        citation_mode == "required"
        and "kbsphere" in active_capabilities
        and sources_context
        and sources_context.strip()
    ):
        guideline_items.append("Cite sources using [1], [2] format")

    if "dbsphere" in active_capabilities:
        guideline_items.extend(
            [
                "Explain SQL results in easy-to-understand terms",
                "Format numbers appropriately (thousands separator, percentages)",
                "If a chart was generated, briefly describe what it shows",
            ]
        )

    guidelines = "\n".join(f"- {item}" for item in guideline_items)

    # User-defined format prompt takes priority over default guidelines
    if format_prompt and format_prompt.strip():
        sections.append(f"""
## Response Format Instructions
{format_prompt.strip()}
""")
    else:
        sections.append(f"""
## Response Guidelines
{guidelines}
""")

    combined_prompt = base_prompt + "\n".join(sections)

    # Build message list
    result = [SystemMessage(content=combined_prompt)]

    # Add conversation history, excluding the last user message (added separately below)
    last_user_idx = None
    last_user_content = None
    for i, msg in enumerate(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            last_user_idx = i
            last_user_content = msg.get("content", "")
    for i, message in enumerate(messages):
        if isinstance(message, dict):
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                continue
            if i == last_user_idx:
                continue
            elif role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))

    # Build final question — preserve image attachments from the last user message
    # so the LLM can see what the user is referring to (e.g., "remove the background")
    image_parts = []
    if isinstance(last_user_content, list):
        image_parts = [
            part
            for part in last_user_content
            if isinstance(part, dict) and part.get("type") == "image_url"
        ]

    if image_parts:
        # Multipart: text question + original image attachments
        final_content = [
            {"type": "text", "text": normalized_question},
            *image_parts,
        ]
        result.append(HumanMessage(content=final_content))
    else:
        result.append(HumanMessage(content=normalized_question))

    return result
