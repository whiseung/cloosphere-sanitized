"""용어집 DB 값 → LLM 동의어/설명/예문 일괄 생성.

`extract_worker`가 SQL로 추출한 값 목록을 받아 LLM으로 entry 정보를 생성한다.
배치 단위 병렬/순차 처리, 진행률 콜백, 취소 체크, 통계 출력 지원.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from extension_modules.utils.llm import ainvoke_temperature_safe, create_llm
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def _extract_json(text: str) -> Optional[dict]:
    """LLM 응답에서 JSON 추출 (markdown 코드 블록 등 처리)."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


_VALUE_ENRICH_SYSTEM_PROMPT = """\
당신은 데이터 카탈로그 어시스턴트입니다. 데이터베이스 컬럼에서 추출된 값들을 받아, \
해당 값을 용어집(glossary)에 등록할 정보를 생성합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 배경: 이 데이터가 실제로 어떻게 쓰이는가 (중요)

당신이 생성하는 각 entry는 시스템 전반에서 다음과 같이 사용됩니다.

### 공통 저장 방식
entry 전체(`term + synonyms + description + example`)가 하나의 텍스트로 \
합쳐져 **벡터 임베딩**됩니다. 이후 모든 조회는 의미 유사도 기반의 벡터 \
검색으로 이루어집니다.

### 주요 사용 경로
1. **에이전트 도구 `lookup_glossary_term`**: 사용자가 에이전트와 자연어로 \
   대화할 때, LLM 에이전트가 질문에 나온 약어·전문용어·업무용어를 해석하기 \
   위해 이 도구를 호출합니다. 질의 문자열로 벡터 검색을 돌려 가장 관련 있는 \
   entry들을 찾고, `term + synonyms + description + example`이 에이전트 \
   후속 추론의 컨텍스트로 주입됩니다. 이 정보로 에이전트가 SQL을 작성하거나 \
   RAG 검색어를 다듬거나 답변을 생성합니다.
2. **에이전트 미들웨어 자동 주입**: 에이전트에 연결된 용어집에서 사용자 \
   질문과 관련된 용어를 자동으로 찾아 프롬프트에 주입하기도 합니다.
3. **지식 그래프 용어 해석**: 지식 그래프 도구가 사용자 질문 속 표기를 \
   정식 entity로 매핑할 때도 같은 용어집을 조회합니다.

즉 이 용어집은 **한 번 작성되어 여러 LLM 파이프라인에서 공용**으로 사용되는 \
자산입니다. 품질 문제는 도구 호출 한 번이 아니라 모든 에이전트 동작에 \
영향을 줍니다.

### synonyms의 진짜 역할
synonyms는 **벡터 검색의 recall(재현율)을 높이는 앵커 텍스트**입니다. \
사용자가 공식 term 대신 다른 표기로 질문할 때도 같은 entry가 매칭되도록 \
"이 항목을 부르는 다른 방식"을 미리 적어두는 것입니다.

이 사용 방식 때문에 두 가지가 동시에 중요합니다:

- **포함의 기준 (recall)**: 사용자가 실제로 타이핑·질문할 법한 자연스러운 \
  변형이면 포함 가치가 큽니다. 예: "MacBook Pro 16"을 사람들이 흔히 "맥북 프로"로 \
  줄여 부른다면 반드시 포함. 그렇지 않으면 사용자가 "맥북 프로 재고"라고 물었을 \
  때 이 entry가 검색되지 않습니다.
- **제외의 기준 (precision)**: 여러 항목에 공통으로 쓰이는 일반명(성분·\
  카테고리·모기업 등)을 넣으면, 사용자가 그 표기로 질문할 때 **엉뚱한 entry가 \
  과도하게 매칭**되어 에이전트가 잘못된 항목에 대해 답하게 됩니다. 예: \
  "카페인"을 "코카콜라 제로"의 동의어로 넣어 버리면, 사용자가 "카페인 \
  판매량"을 물을 때 이 특정 제품이 잘못 집혀서 답변이 오염됩니다.

판단이 어려울 때는 "사용자가 이 표기로 에이전트에게 질문할 때 이 항목만 \
나오는 게 자연스러운가?"를 떠올리세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

각 값에 대해 다음 세 필드를 생성하세요: `synonyms`, `description`, `example`.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## synonyms (동의어)

### 리트머스 테스트 (판단 기준)
"사용자가 이 표기로 질의했을 때, 다른 것과 혼동 없이 이 항목만을 가리킬 수 있는가?"
  • YES → 동의어로 포함
  • NO (여러 항목을 가리킴) → 제외

동의어가 있는데 빠뜨리는 것은, 잘못된 동의어를 넣는 것만큼 문제입니다. \
적극적으로 찾되, 반드시 리트머스 테스트를 통과한 것만 넣으세요.

### 포함해야 할 세 가지 변형 패턴

**패턴 1) 언어·문자 변형**
같은 대상의 다른 언어 표기, 한자/영문/한글 표기, 로마자 표기.
  ✓ "USA" → ["미국", "United States", "United States of America"]
  ✓ "아이폰 15" → ["iPhone 15"]
  ✓ "삼성전자" → ["Samsung Electronics"]

**패턴 2) 표준 약어·줄임말**
널리 통용되는 약어, 공식 약칭, 코드↔이름 매핑.
  ✓ "인공지능" → ["AI"]
  ✓ "Microsoft SQL Server" → ["MSSQL", "SQL Server"]
  ✓ "4분기 2024" → ["Q4 2024", "2024 Q4", "2024년 4분기"]

**패턴 3) 부가 정보(modifier) 제거 후의 고유 명칭**
사람들은 긴 공식 명칭을 부를 때 거의 항상 **부가 정보를 떼어낸 짧은 형태**를 \
사용합니다. 이것이 synonyms에서 가장 자주 빠뜨리는 영역이므로, 모든 값에 대해 \
아래 체크리스트를 **반드시** 순서대로 적용하세요.

### 값 분해 체크리스트 (도메인 무관)

값을 `[고유 식별부] + [부가 정보(modifier)]` 구조로 본 뒤, 식별부가 여전히 \
이 항목을 고유하게 가리킬 수 있는 한 부가 정보를 단계적으로 떼어내세요.

**떼어낼 수 있는 부가 정보 종류 (도메인 무관):**

| 종류 | 설명 | 예 |
|---|---|---|
| **괄호 내용** | 성분·규격·번역·부가설명 | `(엔테로코쿠스...)`, `(Seoul Station)` |
| **형태/제형/포장** | 같은 항목의 물리적 형태·용기·단위 | 병, 팩, 캔, 박스, 봉, 컵, 세트, 패키지 |
| **용량/사이즈/스펙** | 수치 + 단위, 크기, 용량, 저장소 | 500mg, 100ml, 16인치, 256GB, 55인치, 1.5L |
| **수량/입수** | 개수·묶음 | 10정들이, 30개입, 5팩, 2병 |
| **모델/SKU 접미사** | 기종 코드, 색상 코드, 시리얼 꼬리표 | M3 Max, MLJU3KH/A, -BLK |
| **회사 법적 형태** | 주식회사 표기·약자 | (주), 주식회사, Co., Ltd., Inc. |

### 판단 기준 (떼어낸 뒤의 이름이 **모두** 만족해야 함)
  (a) 성분명·재료명·카테고리·일반명사·모기업명이 아닐 것
  (b) 그 이름만으로 이 항목(또는 이 항목이 속한 고유 제품군)을 식별할 수 있을 것
  (c) 사용자가 실제로 그 짧은 형태로 부를 만할 것

### 형태/제형 접미사는 **거의 항상** 떼어낼 수 있다 (중요)
형태 접미사(병, 팩, 캔, 컵, 박스 등)는 "같은 제품의 물리적 포장·용기"를 \
나타낼 뿐 **제품의 정체성을 바꾸지 않습니다**. 사용자는 "코카콜라 제로 캔"을 \
거의 항상 "코카콜라 제로"라고 부르고, "신라면 컵"을 "신라면"이라고 부릅니다. \
따라서 값 끝이 이런 형태 접미사로 끝나면 **거의 무조건** 떼어낸 형태를 \
synonyms에 포함해야 합니다 (단, 떼어낸 결과가 위 (a)(b)(c) 조건을 지킬 때).

단, 형태 접미사와 **카테고리 접미사**는 구별해야 합니다:
  - 형태 (OK, 떼어냄): 병, 팩, 캔, 컵, 박스, 봉, 세트 — "물리적 형태/용기"
  - 카테고리 (NOT OK, 떼어내면 더 짧아지지 않음): 음료, 노트북, 스마트폰, \
    라면 — "무엇인지(what)를 설명하는 분류"

예시 (도메인 무관):
  ✓ "맥북 프로 16인치 M3 Max" → ["맥북 프로 16", "맥북 프로", "MacBook Pro 16"]
     └ M3 Max(스펙) + 16인치(사이즈) 단계적 제거.
  ✓ "코카콜라 제로 500ml 페트" → ["코카콜라 제로 500ml", "코카콜라 제로"]
     └ 페트(용기) + 500ml(용량) 제거. "코카콜라 제로"는 고유 SKU 라인.
  ✓ "신라면 멀티팩 (5개입)" → ["신라면 멀티팩", "신라면"]
     └ (5개입)(입수) + "멀티팩"(포장) 제거. "신라면"은 고유 브랜드.
  ✓ "갤럭시 S24 Ultra 256GB 티타늄 블랙" → ["갤럭시 S24 Ultra", "Galaxy S24 Ultra"]
     └ 색상/저장용량 스펙 제거. "갤럭시 S24 Ultra"는 고유 모델명.
  ✓ "삼성전자(주)" → ["삼성전자", "Samsung Electronics"]
     └ (주)(법적 형태) 제거.
  ✓ "서울역(Seoul Station)" → ["Seoul Station"]
     └ 괄호 내 번역어 — 언어 변형.

반례 (떼어낸 결과가 부적격한 경우):
  ✗ "코카콜라 제로 500ml" → "카페인"
     └ "500ml"·"제로"를 단계적으로 떼어내다 **성분명**(카페인)까지 \
       도달하면 조건 (a) 위반. 수많은 다른 음료에도 공통으로 들어감.
  ✗ "삼성전자서비스" → "삼성"
     └ "전자서비스"를 떼면 "삼성"이 되지만, 삼성은 **모기업 그룹**이라 \
       조건 (a)·(b) 위반. 삼성전자·삼성생명 등 다른 항목도 가리킴.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
### 절대 포함하면 안 되는 것 (제외 규칙)

다음은 리트머스 테스트를 통과하지 못합니다. synonyms에 넣지 마세요.

**제외 A) 성분·재료·구성요소**
제품의 성분은 그 제품만의 이름이 아니라, 수많은 다른 제품에도 들어가는 일반명입니다.
  ✗ "코카콜라 제로" → "카페인", "아스파탐"  (성분은 음료 전반에 공통)
  ✗ "맥북 프로 16 M3 Max" → "M3"  (칩은 여러 제품에 공통 탑재)

**제외 B) 상위 카테고리·분류·유형**
카테고리 이름은 그 카테고리에 속한 모든 항목을 동시에 가리킵니다.
  ✗ "iPhone 15 Pro" → "스마트폰", "휴대폰"
  ✗ "맥북 프로 16" → "노트북", "랩탑"
  ✗ "코카콜라 제로" → "탄산음료", "음료"

**제외 C) 모기업·브랜드 그룹·상위 조직**
상위 조직명은 하위의 여러 조직·제품을 모두 가리킵니다. 하위 항목의 동의어가 될 수 없습니다.
  ✗ "삼성전자서비스" → "삼성"  (삼성은 그룹 전체)
  ✗ "네이버 파이낸셜" → "네이버"
  ✗ "현대자동차 울산공장" → "현대"

**제외 D) 일반 명사·추상 단어**
  ✗ "서울중앙지방법원" → "법원", "서울"
  ✗ "현대자동차 울산공장" → "공장"

**제외 E) 단순 형식 변형**
띄어쓰기만 다른 것, 대소문자만 다른 것, 조사가 붙은 것 등은 시스템이 자동으로 \
정규화합니다. synonyms에 넣지 마세요.
  ✗ "iPhone 15" → "iPhone15", "iphone 15"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## description (설명)
이 값이 무엇인지 **사실에 기반해** 1–2문장으로 설명합니다.
  • 확실하지 않으면 짧게. 추측·과장·허위 금지.
  • 같은 행의 context가 있으면 그것을 활용해 정확도를 높이세요.

## example (예문)
이 값이 업무 질의·대화에 등장할 법한 자연스러운 한국어 예문 1개.
  ✓ "iPhone 15 Pro 에 대한 최근 6개월 판매량을 보여줘"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## context 사용법
각 입력 항목에는 동일 행의 다른 컬럼에서 가져온 `context`가 함께 제공될 수 있습니다. \
context는 **값의 정체를 파악하기 위한 참고 자료**일 뿐입니다.
  • context 텍스트를 그대로 synonyms로 복사하지 마세요.
  • context를 활용해 "이 값이 무엇인지" 파악한 뒤, 그 정체에 맞는 동의어를 생성하세요.
  • 예: context에 `{{"제조사": "Apple", "카테고리": "스마트폰"}}`가 있으면 \
"이 값은 Apple 이 만드는 스마트폰이구나"라고 이해만 하세요 — "Apple"이나 \
"스마트폰"을 동의어로 넣으면 안 됩니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 최종 지침
- 명백한 동의어는 반드시 찾아내되, 리트머스 테스트를 통과한 것만 포함합니다.
- 판단이 애매하면 제외합니다.
- 반드시 아래 JSON 스키마로만 응답하세요. 추가 설명 텍스트 금지.

컨텍스트(컬럼/도메인 정보):
{context}

JSON 형식:
{{
  "값1": {{"synonyms": ["..."], "description": "...", "example": "..."}},
  "값2": {{"synonyms": [], "description": "...", "example": "..."}}
}}
"""

_EMPTY_ENTRY = {"synonyms": [], "description": "", "example": ""}


async def generate_entries_batch(
    app,
    values: list[str],
    context: str,
    pre_resolved_model_config: dict,
    batch_size: int = 10,
    value_contexts: Optional[dict[str, dict]] = None,
    progress_cb=None,
    cancel_check=None,
    stats_out: Optional[dict] = None,
    custom_instructions: Optional[str] = None,
    concurrency: int = 8,
) -> dict[str, dict]:
    """값 목록에 대해 LLM으로 용어집 항목 정보를 일괄 생성한다.

    Args:
        value_contexts: 값별 추가 컬럼 컨텍스트 ({값: {컬럼명: 값}}). LLM에
            힌트로만 전달되며 동의어 후보로는 사용되지 않는다.
        progress_cb: 각 배치 완료 시 호출되는 동기/비동기 콜백.
            signature: (done: int, total: int) -> None | Awaitable[None]
        cancel_check: 각 배치 시작 전 호출되어 True를 반환하면 중단.
            동기/비동기 모두 지원. 중단 시 ``CancelledError``를 raise한다.
        stats_out: 전달되면 아래 키로 실행 통계를 채워 반환한다.
            - total_batches (int)
            - failed_batches (int): LLM 호출/파싱이 실패해 빈 entry 가 된 배치 수
            - mapped_values (int): 실제로 LLM 응답이 매핑된 값 개수
            - first_error (str|None): 첫 예외 메시지
            - first_bad_response (str|None): 첫 파싱 실패 응답 snippet

    Returns:
        {값: {"synonyms": [str], "description": str, "example": str}}
    """
    import asyncio
    import inspect

    llm = create_llm(pre_resolved_model_config, temperature=0.2)
    result: dict[str, dict] = {}

    # 통계 추적 (클로저로 공유)
    total_batches = 0
    failed_batches = 0
    mapped_values = 0
    first_error: Optional[str] = None
    first_bad_response: Optional[str] = None

    async def _maybe_call(fn, *args):
        if fn is None:
            return None
        out = fn(*args)
        if inspect.isawaitable(out):
            return await out
        return out

    async def _process_batch(batch: list[str]) -> dict[str, dict]:
        nonlocal total_batches, failed_batches, mapped_values
        nonlocal first_error, first_bad_response
        total_batches += 1
        prompt = _VALUE_ENRICH_SYSTEM_PROMPT.format(context=context)
        if custom_instructions:
            prompt += (
                "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "## 사용자 추가 지시사항 (반드시 준수)\n"
                f"{custom_instructions}\n"
            )
        if value_contexts:
            payload = [
                {"value": v, "context": value_contexts.get(v, {})} for v in batch
            ]
        else:
            payload = batch
        user_msg = json.dumps(payload, ensure_ascii=False)
        batch_result: dict[str, dict] = {}
        try:
            response = await ainvoke_temperature_safe(
                llm,
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=user_msg),
                ],
                # 일시적 에러(429 rate limit / 5xx / 타임아웃)에 대비한 배치 단위
                # 재시도 — 5000개 대량 처리 중 일부 배치만 일시 실패해도 빈 항목으로
                # 떨어지지 않고 백오프 후 재시도.
                max_retries=3,
                base_delay=2.0,
            )
            raw = response.content if hasattr(response, "content") else str(response)
            if isinstance(raw, list):
                parts: list[str] = []
                for blk in raw:
                    if isinstance(blk, dict):
                        t = blk.get("text") or blk.get("content")
                        if isinstance(t, str):
                            parts.append(t)
                    elif isinstance(blk, str):
                        parts.append(blk)
                content = "".join(parts)
            else:
                content = raw if isinstance(raw, str) else str(raw)
            parsed = _extract_json(content)
            this_batch_mapped = 0
            if parsed and isinstance(parsed, dict):
                for val, info in parsed.items():
                    if isinstance(info, dict):
                        batch_result[val] = {
                            "synonyms": [
                                s
                                for s in info.get("synonyms", [])
                                if isinstance(s, str) and s.strip()
                            ],
                            "description": info.get("description", ""),
                            "example": info.get("example", ""),
                        }
                        this_batch_mapped += 1
                    else:
                        batch_result[val] = dict(_EMPTY_ENTRY)
            if this_batch_mapped == 0:
                failed_batches += 1
                if first_bad_response is None:
                    snippet = (content or "")[:500]
                    first_bad_response = snippet
                    log.warning(
                        f"[generate_entries_batch] no values mapped in batch "
                        f"(size={len(batch)}); response snippet: {snippet!r}"
                    )
            else:
                mapped_values += this_batch_mapped
            for val in batch:
                batch_result.setdefault(val, dict(_EMPTY_ENTRY))
        except Exception as e:
            failed_batches += 1
            if first_error is None:
                first_error = f"{type(e).__name__}: {str(e)[:300]}"
            log.warning(f"[generate_entries_batch] LLM error: {e}")
            for val in batch:
                batch_result.setdefault(val, dict(_EMPTY_ENTRY))
        return batch_result

    batches = [values[i : i + batch_size] for i in range(0, len(values), batch_size)]
    total = len(values)
    done = 0

    # Semaphore 로 제한된 동시 실행 — LLM I/O 바운드라 한 워커에서 N개 동시
    # 호출이 순차 대비 N배 빠르다. progress/cancel 을 유지하면서 동시성을
    # 적용한다. concurrency 는 LLM 엔드포인트 TPM 에 맞춰 조정(기본 8).
    sem = asyncio.Semaphore(max(1, concurrency))
    cancelled = False

    async def _run_one(idx: int, batch: list[str]) -> None:
        nonlocal done, failed_batches, first_error, cancelled
        async with sem:
            # 협조적 취소: 이미 취소 신호면 새 작업 시작 안 함.
            if cancelled:
                return
            if cancel_check is not None and await _maybe_call(cancel_check):
                cancelled = True
                return
            try:
                br = await _process_batch(batch)
            except Exception as e:
                failed_batches += 1
                if first_error is None:
                    first_error = f"{type(e).__name__}: {str(e)[:300]}"
                log.warning(f"[generate_entries_batch] batch {idx} failed: {e}")
                br = {val: dict(_EMPTY_ENTRY) for val in batch}
            # asyncio 단일 스레드라 dict update / 카운터 갱신은 락 불필요.
            result.update(br)
            done += len(batch)
            if progress_cb is not None:
                await _maybe_call(progress_cb, done, total)

    await asyncio.gather(*[_run_one(i, b) for i, b in enumerate(batches)])

    if cancelled:
        raise asyncio.CancelledError("generate_entries_batch cancelled by caller")

    # 동시 실행 중 set 안 된 값은 빈 항목으로 보정.
    for batch in batches:
        for val in batch:
            result.setdefault(val, dict(_EMPTY_ENTRY))

    if stats_out is not None:
        stats_out["total_batches"] = total_batches
        stats_out["failed_batches"] = failed_batches
        stats_out["mapped_values"] = mapped_values
        stats_out["first_error"] = first_error
        stats_out["first_bad_response"] = first_bad_response

    log.info(
        f"[generate_entries_batch] done: total_values={total}, "
        f"mapped={mapped_values}, batches={total_batches}, failed={failed_batches}"
    )

    return result
