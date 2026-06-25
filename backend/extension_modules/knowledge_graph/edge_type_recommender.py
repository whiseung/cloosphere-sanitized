"""KG 링크 단위 엣지 타입 카탈로그 추천 — LLM 호출.

지정된 link(kg_knowledge_link 한 행)의 글로서리 + KB 만 컨텍스트로 모아서
LLM 에게 "이 도메인 link 에서 자주 등장할 엣지 타입"을 제안받는다. 추천
결과는 곧바로 DB 에 기록하지 않고 라우터에서 사용자에게 반환한다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from extension_modules.utils.llm import create_llm, get_model_config_from_app
from langchain_core.messages import HumanMessage, SystemMessage
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.glossary import Glossaries
from open_webui.models.knowledge import Knowledges
from open_webui.models.knowledge_graph import KnowledgeGraphs

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# ─── Limits ────────────────────────────────────────────────────────
_MAX_GLOSSARY_ENTRIES = 25
_MAX_KB_SAMPLE_CHUNKS = 15
_KB_CHUNK_CHAR_CAP = 500
_MAX_NODE_LABELS_PER_TYPE = 8


# ─── JSON extraction ───────────────────────────────────────────────
def _extract_json(text: str) -> Optional[dict]:
    """LLM 응답에서 JSON 객체 추출 — markdown 코드블록/잡설 허용."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


# ─── Resource summarizers ──────────────────────────────────────────
def _sample_glossary_entries(entries: list[dict], cap: int) -> list[dict]:
    """카테고리가 있으면 카테고리별 round-robin 으로 균등 샘플링.

    동일 글로서리에 여러 카테고리가 섞여 있을 때 앞쪽 카테고리만 잘려서
    LLM 컨텍스트에 들어가는 문제를 방지한다. 카테고리가 없는 항목은 별도
    버킷으로 둔다.
    """
    if not entries:
        return []
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for e in entries:
        cat = (e.get("category") or "(none)").strip() or "(none)"
        if cat not in buckets:
            buckets[cat] = []
            order.append(cat)
        buckets[cat].append(e)
    if len(order) <= 1:
        return entries[:cap]
    out: list[dict] = []
    idx = 0
    while len(out) < cap:
        progressed = False
        for cat in order:
            bucket = buckets[cat]
            if idx < len(bucket):
                out.append(bucket[idx])
                progressed = True
                if len(out) >= cap:
                    break
        if not progressed:
            break
        idx += 1
    return out


def _summarize_glossary(g) -> dict:
    data = g.data or {}
    all_entries = list(data.get("entries") or [])
    sampled = _sample_glossary_entries(all_entries, _MAX_GLOSSARY_ENTRIES)
    sample_terms = []
    # 카테고리 분포 (전체 기준 — LLM 에게 도메인 다양성 알림)
    cat_counts: dict[str, int] = {}
    for e in all_entries:
        cat = (e.get("category") or "").strip()
        if cat:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
    for e in sampled:
        term = (e.get("term") or "").strip()
        definition = (e.get("definition") or "").strip()
        category = (e.get("category") or "").strip()
        if not term:
            continue
        prefix = f"[{category}] " if category else ""
        if definition:
            sample_terms.append(f"- {prefix}{term}: {definition[:150]}")
        else:
            sample_terms.append(f"- {prefix}{term}")
    return {
        "id": g.id,
        "name": g.name or "",
        "description": g.description or "",
        "sample_terms": sample_terms,
        "category_counts": cat_counts,
        "total_entries": len(all_entries),
    }


async def _summarize_knowledge(app, kb) -> dict:
    """KB sample chunks."""
    sample_chunks: list[str] = []
    try:
        from open_webui.retrieval.knowledge_service import SearchEngineKnowledge

        service = SearchEngineKnowledge(app=app, collection_name=kb.id)
        docs = await service.query_by_metadata({}, limit=_MAX_KB_SAMPLE_CHUNKS)
        for d in docs[:_MAX_KB_SAMPLE_CHUNKS]:
            text = (getattr(d, "content", "") or "").strip().replace("\n", " ")
            if text:
                sample_chunks.append(text[:_KB_CHUNK_CHAR_CAP])
    except Exception as e:
        log.warning(
            f"[edge_type_recommender] KB sample fetch failed ({kb.id[:8]}): {e}"
        )

    return {
        "id": kb.id,
        "name": kb.name or "",
        "description": kb.description or "",
        "sample_chunks": sample_chunks,
    }


def _summarize_kg_nodes(kg_id: str) -> dict:
    """node_type 별 카운트 + 상위 라벨 (도메인 분위기 파악용 — KG 전체)."""
    summary: dict[str, dict] = {}
    for node_type in ("term", "concept", "table", "column", "doc_entity"):
        count = KnowledgeGraphs.count_nodes(kg_id=kg_id, node_type=node_type)
        if count == 0:
            continue
        nodes = KnowledgeGraphs.get_nodes(
            kg_id=kg_id, node_type=node_type, limit=_MAX_NODE_LABELS_PER_TYPE
        )
        summary[node_type] = {
            "count": count,
            "sample_labels": [n.label for n in nodes if n.label][
                :_MAX_NODE_LABELS_PER_TYPE
            ],
        }
    return summary


def _summarize_link_existing_catalog(link_id: str) -> dict:
    """링크의 기존 카탈로그 — 모든 항목을 보존 대상으로 LLM 에 알린다."""
    catalog = KnowledgeGraphs.get_link_edge_type_catalog(link_id)
    items = catalog.get("items") or []
    preserve = []
    for it in items:
        preserve.append(
            {
                "key": it["key"],
                "display_name": it.get("display_name") or it["key"],
                "description": it.get("description") or "",
                "source": it.get("source") or "manual",
            }
        )
    return {"preserve": preserve}


async def _build_link_recommendation_context(app, kg_id: str, link_id: str) -> dict:
    """링크 컨텍스트 수집 — 그 링크의 글로서리 + KB 만 사용."""
    kg = KnowledgeGraphs.get_kg_by_id(kg_id)
    if not kg:
        raise ValueError(f"KG not found: {kg_id}")

    link = KnowledgeGraphs.get_knowledge_link_by_id(link_id)
    if not link or link.kg_id != kg_id:
        raise ValueError(f"Link not found: {link_id}")

    glossary = None
    if link.glossary_id:
        g = Glossaries.get_glossary_by_id(link.glossary_id)
        if g:
            glossary = _summarize_glossary(g)

    knowledges: list[dict] = []
    for kid in link.knowledge_ids or []:
        kb = Knowledges.get_knowledge_by_id(kid)
        if kb:
            knowledges.append(await _summarize_knowledge(app, kb))

    return {
        "kg": {
            "name": kg.name or "",
            "description": kg.description or "",
        },
        "glossary": glossary,
        "knowledges": knowledges,
        "kg_nodes": _summarize_kg_nodes(kg_id),
        "existing_catalog": _summarize_link_existing_catalog(link_id),
    }


# ─── Prompt rendering ──────────────────────────────────────────────
def _render_link_context_block(ctx: dict) -> str:
    lines: list[str] = []
    lines.append(f"## KG\n- 이름: {ctx['kg']['name']}")
    if ctx["kg"]["description"]:
        lines.append(f"- 설명: {ctx['kg']['description']}")

    g = ctx.get("glossary")
    if g:
        lines.append("\n## 이 링크의 용어집 (앵커 어휘)")
        lines.append(f"- 이름: {g['name']}")
        if g.get("description"):
            lines.append(f"- 설명: {g['description']}")
        if g.get("category_counts"):
            cat_str = ", ".join(f"{c}({n})" for c, n in g["category_counts"].items())
            lines.append(
                f"- 카테고리 분포 (전체 {g.get('total_entries', 0)}개): {cat_str}"
            )
            lines.append(
                "  ※ 위 모든 카테고리에 대해 적절한 엣지 타입을 제안하세요. "
                "샘플 용어는 카테고리별 round-robin 이라 일부만 보일 수 있습니다."
            )
        if g.get("sample_terms"):
            lines.append("- 샘플 용어:")
            for t in g["sample_terms"]:
                lines.append(f"  {t}")

    if ctx.get("knowledges"):
        lines.append("\n## 이 링크의 지식기반 (KB)")
        for k in ctx["knowledges"]:
            lines.append(f"\n### {k['name']}")
            if k.get("description"):
                lines.append(f"설명: {k['description']}")
            if k.get("sample_chunks"):
                lines.append("샘플 문서 청크:")
                for ch in k["sample_chunks"]:
                    lines.append(f"- {ch}")

    if ctx.get("kg_nodes"):
        lines.append("\n## KG 전체 노드 통계 (참고용)")
        for nt, info in ctx["kg_nodes"].items():
            sample = ", ".join(info["sample_labels"][:5])
            lines.append(f"- {nt} ({info['count']}개): {sample}")

    existing = ctx.get("existing_catalog") or {}
    if existing.get("preserve"):
        lines.append("\n## 이미 정의된 엣지 타입 (보존 필요, 다시 제안 금지)")
        for it in existing["preserve"]:
            lines.append(f"- {it['key']} ({it['display_name']}): {it['description']}")

    return "\n".join(lines)


_BASE_OUTPUT_RULES = """## 출력 규칙
- JSON 객체 하나만 반환. 마크다운/주석/설명문 금지.
- 정확히 다음 스키마를 따른다:

{{
  "candidates": [
    {{
      "key": "snake_case_ascii",
      "display_name": "한국어 이름",
      "description": "1~2 문장 설명",
      "recommendation_reason": "이 자료에서 어떤 패턴을 보았기에 이 타입을 제안하는지 구체적으로",
      "category": "...",
      "src_category": "...",
      "dst_category": "..."
    }}
  ]
}}

## 작성 규칙
- key 는 ASCII snake_case, 동사형/관계형 권장 (예: synonym_of, part_of, measures).
- display_name 은 한국어로 짧게 (10자 이내 권장).
- description 은 "A는 B의 ___" 처럼 src→dst 방향성이 드러나게 쓴다.
- recommendation_reason 은 반드시 채운다. 어느 자료(용어집/KB 의 어떤 패턴)에서 단서를 보고
  제안했는지 구체적으로 한국어로 1~2 문장. 도메인별 문구를 복사하지 말고 일반화해서 표현.
- **category / src_category / dst_category 중 하나만** 사용:
  - `category`: 한 카테고리 내부 속성. 한 엔티티 카테고리의 속성을 나타낼 때.
  - `src_category` + `dst_category`: 서로 다른 두 카테고리를 잇는 관계.
  - 셋 다 비움: 범용 (드물게 — 여러 카테고리에 공통으로 적용되는 진짜 범용 관계만).
  - **대부분의 intra 엣지는 반드시 `category` 를 채우세요.** 비워두면 모든 카테고리에 오염됩니다.
- 값은 카테고리 분포에 나열된 카테고리 이름 그대로.
- 이미 정의된 엣지 타입(보존 목록)은 절대 다시 제안하지 말 것.
- 최대 {max_candidates} 개까지.
"""


_SYSTEM_PROMPT_SINGLE = (
    """당신은 도메인 지식그래프(KG) 설계 전문가입니다.

이 KG 의 한 "지식 연결(link)" 에 대해, 그 링크에 포함된 용어집과 지식기반(KB) 의
도메인을 분석해서 그 링크에서 자주 등장할 만한 **엣지 타입(관계 유형) 카탈로그**를
제안하세요.

엣지 타입은 KG 노드 사이의 관계를 일반화한 라벨이며, 추후 LLM 추출이 이 카탈로그
안에서만 슬롯을 고를 수 있도록 강제됩니다. 따라서 너무 좁은(인스턴스 같은) 타입이나
너무 일반적인(has_feature 같은) 타입은 피해야 합니다. 이 링크의 도메인에 특화된
관계 위주로 제안하되, 같은 도메인 안에서 재사용 가능해야 합니다.

"""
    + _BASE_OUTPUT_RULES
)


_SYSTEM_PROMPT_INTRA = (
    """당신은 도메인 지식그래프(KG) 설계 전문가입니다.

이 KG 의 한 "지식 연결(link)" 안에서, **'{focus_category}' 카테고리에 속한 용어들 끼리** 또는
'{focus_category}' 카테고리의 용어가 KB 청크에서 갖는 속성/관계만 찾아서 엣지 타입을
제안하세요.

다른 카테고리({other_categories})와의 관계는 **이 콜에서는 절대 제안하지 마세요** —
별도 머지 단계에서 처리됩니다. '{focus_category}' 의 내부 구조에만 집중합니다.

## 시스템이 이미 처리하는 구조 (절대 엣지로 제안 금지)

KG 파이프라인이 자동 생성하는 구조가 이미 있으므로, 같은 의미를 가진 엣지 타입은
**중복이며 제안하면 안 됩니다**:

1. **엔티티의 식별 이름은 term 노드의 label 자체**
   용어집 term 노드의 label 이 곧 엔티티의 이름/식별자입니다. 문서 헤더나 메타
   블록에 "<라벨>: <term 이름>" 형태로 반복되더라도, 그 값이 term 자체(= 현재
   카테고리에서 등록된 용어) 면 이미 표현된 정보입니다. `has_name` / `has_label` /
   `product_name` / `entity_id` 류의 "term 이름을 가리키는 엣지" 는 제안 금지.

2. **용어 간 계층/동의어 관계는 glossary sync 전용**
   `synonym_of`, `broader_than`, `narrower_than` 는 이미 glossary sync 가 자동
   생성합니다. 같은 의미의 `is_variant_of` / `is_alias_of` / `is_subtype_of` /
   `is_a` 같은 관계는 제안 금지.

## 검토 절차 — broad 축 먼저, 세부 측면은 그 다음

세부 속성을 바로 찾기 전에, **이 카테고리 엔티티가 일반적으로 가지는 가장 기본적인
속성 축** 을 먼저 식별하세요. 도메인이 무엇이든 다음 추상 축이 거의 항상 존재합니다:

- 엔티티의 **핵심 정의 / 본질 / 분류** 정보
- 엔티티의 **목적 / 용도 / 기능**
- 엔티티의 **사용 / 적용 / 실행 방법**
- 엔티티에 적용되는 **제약 / 주의 / 조건**
- 엔티티의 **구성 요소 / 부분 / 관련 엔티티**
- 엔티티의 **관리 / 보관 / 처리 / 유지** 정보 (해당될 때)
- 엔티티의 **정량 측정 / 한계 / 범위** 정보 (해당될 때)

샘플에 위 추상 축 중 하나에 해당하는 패턴이 한 번이라도 보이면, **그 축을 대표하는
broad 엣지 타입을 1 개씩 우선 제안**하세요. 같은 축의 세부 변형 여러 개보다 그
**축 자체 1 개**를 선택합니다 — 세부는 값/property 로 표현 가능합니다.

이 절차를 거친 후, 위 축에 들어가지 않는 추가적인 도메인 특수 패턴이 있으면
보충 후보로 제안하세요.

## 무엇을 찾나요 (구체 패턴)

1. **반복되는 구조화 필드**: 샘플 청크에 `필드명: 값`, `<필드명>값</필드명>`,
   `- 필드명: 값` 같은 패턴으로 **여러 청크에 반복 등장**하는 라벨. 단, 값이
   현재 카테고리의 term 이름이거나 위 "시스템이 이미 처리하는 구조" 에 해당하면 제외.
2. **반복되는 서술형 속성**: 문장 안에 나타나지만 여러 청크/엔티티에 일관된 형태로
   반복되는 속성 (정량값/리스트/설명 블록 등).
3. **카테고리 내 관계**: 동의어/상위개념/하위개념 외의 용어 간 관계만 (위 3번 규칙).

## 어떻게 찾나요

- 샘플 청크를 **모두 훑어** 반복 패턴을 센다. 한 번만 등장하는 건 제외.
- 3개 이상 청크 혹은 여러 엔티티에 등장하는 패턴만 신뢰 (그 이하는 노이즈 가능).
- **개념 단위로 묶어서** 제안. 같은 속성을 세부 분류(전반 / 금지 / 예외 / 추가정보,
  또는 대표 / 빈도 / 세부 케이스) 로 쪼개서 별개 엣지 타입으로 만들면 추출 단계에서
  일관성이 깨진다. 의미가 같은 개념이면 가장 포괄적인 라벨 하나로 통합해서 제안.
- 서로 다른 표현 변형(라벨의 번역/약어/띄어쓰기 차이)은 하나로 통합.

## 이상적인 카탈로그 크기
- intra-category 하나당 **3~6 개 관계가 이상적**.
- 8 개를 넘는 순간 거의 확실히 **과세분화** — 상위 개념으로 더 묶어서 제출.
- 의심스러우면 **항상 상위 개념을 선택**.

## 카테고리 범주 엄수
- 이 콜은 '{focus_category}' 내부 관계만 다룹니다.
- 엔티티 두 쪽의 카테고리가 서로 다른 관계 (예: src 는 A 인데 dst 는 B)는
  **절대 여기서 제안하지 마세요** — cross-category 콜 전담.
- 방향을 돌려 본 표현(예: "X 는 Y 의 ___이다") 도 마찬가지 — 방향이 바뀌어도 양쪽
  카테고리가 다르면 cross 전용.

## 도메인 바이어스 금지

- **특정 도메인의 용어나 예시를 프롬프트가 가정하는 것으로 착각하지 마세요.**
  실제 샘플에서 관찰된 패턴만 근거로 사용.
- description 과 recommendation_reason 은 범용 언어로 쓰되, 관찰된 실제 라벨/패턴을
  구체적으로 인용해 근거를 남긴다.

"""
    + _BASE_OUTPUT_RULES
)


_SYSTEM_PROMPT_MERGE = (
    """당신은 도메인 지식그래프(KG) 설계 전문가입니다.

여러 카테고리({all_categories}) 각각에 대해 독립적으로 LLM 이 제안한 엣지 타입 후보 목록이
아래에 있습니다. 각 카테고리 콜은 서로의 결과를 모르고 작성되었고, 한 카테고리 안에서도
LLM 이 같은 개념을 세부 분류로 쪼개 제안했을 수 있어 **중복/과세분화** 가 존재합니다.

## 당신의 임무 — 적극적인 개념 통합

엣지 타입은 추후 LLM 이 값(슬롯) 을 채울 때 사용됩니다. 타입이 많고 경계가 모호할수록
추출이 불일치하고 같은 의미가 여러 key 로 흩뿌려집니다. 따라서 **가능한 한 넓은 상위
개념으로 묶어서** 카탈로그를 단순하게 유지해야 합니다.

### 통합해야 할 두 가지 패턴

**(1) 표현 변형** — key/display_name 만 다르고 같은 관계
(능동/수동, 영한 변형, 동사 시제/의미 중복 동의어 등)

**(2) 개념적 포함(semantic subsumption)** — 한 후보가 다른 후보의 *특수 케이스* 나
*하위 분류* 인 경우. 상위/포괄적 후보가 하위/세부 후보를 흡수해야 합니다.
- 판단 기준: 각 후보의 `description` 과 `recommendation_reason` 을 읽었을 때, 세부
  후보가 다루는 내용이 포괄 후보의 description 안에 자연스럽게 들어가는가?
  - 들어간다면 → 하위는 drop, 상위는 유지. 상위의 description 에 하위가 포함됨을 한 줄 추가.
  - 안 들어간다면 → 서로 독립, 둘 다 유지.
- 같은 "맥락" 을 서로 다른 granularity 로 다루는 후보들은 거의 항상 통합 대상.
  사용자는 추후 값(슬롯) 의 내용이나 property 로 세부 구분할 수 있으므로, 엣지 타입
  레벨에서 미리 쪼갤 필요가 없다.

### 통합 절차
1. 후보 목록의 description + recommendation_reason 을 읽어 **동일 맥락 클러스터**
   식별.
2. 각 클러스터에서 가장 넓고 재사용 가능한 하나를 대표로 선택.
3. 대표의 description 은 클러스터 전체를 아우르도록 약간 일반화.
4. recommendation_reason 은 클러스터의 모든 근거를 1~2 문장으로 요약.
5. 의미가 분명히 독립적인 후보는 그대로 유지.

### Broad 축 coverage 자기 점검 (생략 금지)

각 카테고리의 결과를 모은 뒤, **아래 broad 축 중 어떤 것이 다뤄지고 있는지** 자문:

- 핵심 정의 / 본질 / 분류
- 목적 / 용도 / 기능
- 사용 / 적용 / 실행 방법
- 제약 / 주의 / 조건
- 구성 요소 / 부분 / 관련 엔티티
- 관리 / 보관 / 처리 / 유지
- 정량 측정 / 한계 / 범위

만약 한 카테고리의 후보들이 위 축 중 좁은 1~2 개에만 몰려 있고 다른 축에 명백히
해당할 만한 입력 후보가 있는데도 좁은 표현으로만 잡혀 있다면, **가장 가까운 입력
후보의 description 을 일반화해서 그 broad 축을 커버**하도록 확장하세요. (입력에
전혀 없으면 새로 만들지 말고 생략 — 머지 콜은 새 항목 추가 금지.)

이 자기 점검은 niche 한 후보 8 개만 남고 broad 한 축이 전부 누락되는 사고를
방지하기 위함입니다.

## 이상적 카탈로그 크기 — 강제 통합의 기준
- **카테고리당 3~6개**, 범용 / cross 포함한 전체 카탈로그 **10~15개** 가 이상적.
- 어느 카테고리가 8 개를 넘거나 전체가 15 개를 넘으면 **거의 확실히 과세분화**.
  이 경우 description/recommendation_reason 을 더 넓게 해석해서 병합하세요.
- 의심스러우면 **항상 상위 개념을 선택** — 세부 구분은 추후 값(슬롯) property 로
  다시 얻을 수 있지만, 한번 쪼개진 엣지 타입은 추출 단계에서 일관성을 잃는다.

## 시스템이 이미 처리하는 구조 (발견 시 drop)

입력 후보에 다음 패턴이 있으면 **파이프라인이 이미 처리하는 구조** 이므로 통합이
아니라 **완전히 제거** 하세요:

1. **엔티티 이름/식별자를 가리키는 엣지** — term 노드의 label 자체가 엔티티 이름.
   `has_name` / `has_label` / `product_name` / `entity_id` 같은 "이름을 값으로 하는"
   엣지는 drop.
2. **glossary 계층/동의어 엣지** — `synonym_of` / `broader_than` / `narrower_than`
   은 glossary sync 가 자동 생성. `is_variant_of` / `is_alias_of` / `is_subtype_of` /
   `is_a` 같은 중복 관계는 drop.

## 절대 규칙 — 카테고리 필드 처리 금지

이 콜은 **의미 통합만** 수행하고, 카테고리 배정은 코드가 책임집니다.

- **출력의 모든 후보에서 `category` / `src_category` / `dst_category` 필드는
  반드시 비워두세요** (`null` 또는 빈 문자열 또는 필드 자체 생략).
- 카테고리를 LLM 이 직접 채우지 마세요 — 코드가 입력 후보의 key 를 따라
  카테고리를 자동 매핑합니다.
- 입력에 `category=...` 가 표시되어 있어도 그것은 코드 매핑용 정보일 뿐,
  당신은 거기에 대해 어떤 출력도 하지 마세요.

## 절대 규칙 — key 는 입력에서만 선택

- 출력 후보의 `key` 는 **반드시 입력 후보 중 하나의 key 와 동일** 해야 합니다.
- 두 후보를 통합할 때는 그 중 더 적합한 input key 하나를 골라서 대표로 사용.
- **새로운 key 를 만들거나 변형 (대소문자/철자 변경 등) 하지 마세요** — 코드가
  새 key 를 매핑할 수 없어 drop 합니다.
- 입력에 없는 새 엣지 타입을 추가하지 마세요.

## 절대 금지
- **카테고리 간 관계(`src_category`/`dst_category` 가 있는 항목)를 새로 만들지 마세요.**
  카테고리 간 관계는 별도 cross-category 전용 콜에서 처리되므로, 이 콜에서는
  **카테고리 내부 관계만** 다룹니다. 입력 후보에 cross-category 항목이 섞여 있어도
  drop 하세요.
- 특정 도메인의 용어를 가정하지 말고, 입력된 description 과 recommendation_reason
  만 근거로 판단하세요.

## 입력
{candidate_blocks}

이미 정의된 엣지 타입(절대 제안 금지):
{preserve_block}

"""
    + _BASE_OUTPUT_RULES
)


_SYSTEM_PROMPT_CROSS = (
    """당신은 도메인 지식그래프(KG) 설계 전문가입니다.

이 KG 의 한 "지식 연결(link)" 안에서 **여러 카테고리 사이를 잇는 관계(cross-category
edge)만** 제안하세요. 한 카테고리 안에서 닫히는 관계(동의어/계층/속성)는 **절대
제안하지 마세요** — 별도 콜에서 처리됩니다.

## 카테고리 목록
{all_categories}

## 임무
위 카테고리들을 참고해, 두 개 이상의 카테고리를 잇는 관계를 **적극적으로** 찾아서
제안하세요. 이런 관계는 사용자가 DB 기반 자동 파생(JOIN) 의 대상으로 사용하므로
**재현율이 최우선**입니다. 가능한 모든 카테고리 쌍에 대해 샘플 데이터에서 관찰된
의미 있는 관계가 있으면 반드시 제안하세요.

특정 도메인의 관계를 미리 가정하지 말고, 실제 입력된 용어집과 KB 샘플에서 관찰되는
패턴만 근거로 판단하세요.

## 시스템이 이미 처리하는 구조 (절대 엣지로 제안 금지)

파이프라인이 자동 생성하는 구조가 이미 있으므로, 같은 의미의 cross-category 엣지는
중복이며 제안하면 안 됩니다:

1. **엔티티의 이름/식별자는 term 노드 label 자체**
   한 카테고리 엔티티의 이름을 다른 카테고리 값으로 가리키는 엣지 (`has_name` 류)는
   만들지 마세요 — term 노드가 이미 이름을 표현.
2. **glossary 관계 (synonym / hierarchy) 는 glossary sync 전담**
   카테고리 간 동의어 / 계층 관계를 굳이 cross 엣지로 만들지 마세요.

## 출력 규칙 — 필수
- **모든 항목에 `src_category`, `dst_category` 필드를 반드시 채우세요.**
  값은 "카테고리 목록"에 나열된 이름 그대로. 두 값이 달라야 함.
- 한 관계는 한 방향만 선언. 역방향(inverse) 중복 금지.
  같은 의미를 반대 방향 라벨로 두 번 넣지 마세요.
- **방향 선택 기준 — RDBMS 1:N / M:N 규칙:**
  1. **1:N 관계** (부모 1개 → 자식 여러 개, RDBMS 에서 child 에 FK 가 있는 형태):
     **"1" 쪽(부모) → "N" 쪽(자식)** 방향 (FK 의 반대 방향).
  2. **M:N junction 관계** (fact 테이블로 연결되는 다대다):
     **전체/컨테이너 → 부분/멤버** 방향.
  3. **계층/self-relation**:
     **상위 → 하위**.

  FK 는 구현 디테일이라 무시하고 **의미의 자연스러움** 에 따라 방향을 정하세요.

## 개념 통합
같은 맥락의 관계를 세부 분류로 쪼개지 마세요. description 과 recommendation_reason 을
읽었을 때 한 후보가 다른 후보의 특수 케이스로 보이면 **상위 개념 하나로 통합**하세요.

## 입력 컨텍스트
(아래 user message 에 용어집/KB 샘플이 포함됩니다)

"""
    + _BASE_OUTPUT_RULES
)


_MAX_INTRA_CATEGORIES = 5  # 카테고리가 너무 많으면 비용 폭발 방지


def _resolve_model_config(app, kg_id: str, model_id: Optional[str]):
    """모델 결정: 인자 > kg.data.options.* > 첫 번째 사용 가능 모델."""
    kg = KnowledgeGraphs.get_kg_by_id(kg_id)
    options = ((kg.data or {}) if kg else {}).get("options") or {}
    chosen_model_id = (
        model_id
        or options.get("tool_description_model_id")
        or options.get("llm_model_id")
        or None
    )
    llm_config = (
        get_model_config_from_app(app, chosen_model_id) if chosen_model_id else None
    )
    if not llm_config:
        try:
            available = list(getattr(app.state, "MODELS", {}).values())
            for m in available:
                mid = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
                if mid:
                    llm_config = get_model_config_from_app(app, mid)
                    if llm_config:
                        chosen_model_id = mid
                        break
        except Exception:
            pass
    if not llm_config:
        raise RuntimeError("사용 가능한 LLM 모델을 찾을 수 없습니다.")
    return llm_config, chosen_model_id


def _focus_glossary_on_category(ctx: dict, focus_cat: str) -> dict:
    """ctx 를 복사하면서 glossary.sample_terms 를 focus_cat 카테고리만 남기도록 재구성.

    원본 ctx 의 sample_terms 는 round-robin 이라 카테고리가 섞여 있으므로,
    여기서 focus 카테고리 항목만 우선 추출. 부족하면 원본에서 더 채운다.
    """
    new_ctx = dict(ctx)
    g = ctx.get("glossary")
    if not g:
        return new_ctx
    new_g = dict(g)
    cat_counts = g.get("category_counts") or {}
    # round-robin 결과에서 focus 카테고리 prefix `[focus_cat]` 만 추출
    focus_terms = [
        t for t in (g.get("sample_terms") or []) if t.startswith(f"- [{focus_cat}]")
    ]
    new_g["sample_terms"] = focus_terms
    new_g["focus_category"] = focus_cat
    new_g["focus_category_count"] = cat_counts.get(focus_cat, 0)
    new_g["other_categories"] = [c for c in cat_counts.keys() if c != focus_cat]
    new_ctx["glossary"] = new_g
    return new_ctx


def _render_intra_context_block(ctx: dict, focus_cat: str) -> str:
    """카테고리 집중 모드용 컨텍스트 — focus 카테고리만 sample 로 보이고 다른 건 카운트만."""
    g = ctx.get("glossary") or {}
    other = g.get("other_categories") or []
    lines: list[str] = []
    lines.append(f"## KG\n- 이름: {ctx['kg']['name']}")
    if ctx["kg"]["description"]:
        lines.append(f"- 설명: {ctx['kg']['description']}")

    if g:
        lines.append("\n## 이 링크의 용어집")
        lines.append(f"- 이름: {g.get('name', '')}")
        if g.get("description"):
            lines.append(f"- 설명: {g['description']}")
        lines.append(
            f"- 집중 카테고리: '{focus_cat}' ({g.get('focus_category_count', 0)}개)"
        )
        if other:
            lines.append(f"- 다른 카테고리(이번엔 무시): {', '.join(other)}")
        if g.get("sample_terms"):
            lines.append(f"- '{focus_cat}' 샘플 용어:")
            for t in g["sample_terms"]:
                lines.append(f"  {t}")

    if ctx.get("knowledges"):
        lines.append("\n## 이 링크의 지식기반 (KB)")
        for k in ctx["knowledges"]:
            lines.append(f"\n### {k['name']}")
            if k.get("description"):
                lines.append(f"설명: {k['description']}")
            if k.get("sample_chunks"):
                lines.append("샘플 문서 청크:")
                for ch in k["sample_chunks"]:
                    lines.append(f"- {ch}")

    existing = ctx.get("existing_catalog") or {}
    if existing.get("preserve"):
        lines.append("\n## 이미 정의된 엣지 타입 (보존 필요, 다시 제안 금지)")
        for it in existing["preserve"]:
            lines.append(f"- {it['key']} ({it['display_name']}): {it['description']}")

    return "\n".join(lines)


async def _call_llm_for_candidates(
    llm,
    system_prompt: str,
    user_prompt: str,
    preserve_keys: set[str],
    seen_keys: set[str],
    cap: int,
) -> list[dict]:
    """단일 LLM 콜 후 JSON 파싱 + 정규화 + dedupe 적용."""
    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    raw_content = response.content
    if isinstance(raw_content, str):
        raw = raw_content
    elif isinstance(raw_content, list):
        # Anthropic 등 일부 모델이 [{"type":"text","text":"..."}] 형태로 반환
        parts = []
        for blk in raw_content:
            if isinstance(blk, dict):
                parts.append(blk.get("text") or blk.get("content") or "")
            elif isinstance(blk, str):
                parts.append(blk)
        raw = "".join(parts)
    else:
        raw = str(raw_content)
    parsed = _extract_json(raw)
    if not parsed or "candidates" not in parsed:
        log.warning(
            f"[edge_type_recommender] invalid LLM response (no candidates): {raw[:300]}"
        )
        return []

    out: list[dict] = []
    for c in parsed.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        key = (c.get("key") or "").strip().lower()
        key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_")
        if not key or key in seen_keys or key in preserve_keys:
            continue
        seen_keys.add(key)
        cat = (c.get("category") or "").strip() or None
        src_cat = (c.get("src_category") or "").strip() or None
        dst_cat = (c.get("dst_category") or "").strip() or None
        out.append(
            {
                "key": key,
                "display_name": (c.get("display_name") or key).strip(),
                "description": (c.get("description") or "").strip(),
                "recommendation_reason": (c.get("recommendation_reason") or "").strip()
                or None,
                "category": cat,
                "src_category": src_cat,
                "dst_category": dst_cat,
            }
        )
        if len(out) >= cap:
            break
    return out


def _escape_braces(s: str) -> str:
    """str.format() 안전 처리 — `{` `}` 를 `{{` `}}` 로 escape."""
    return s.replace("{", "{{").replace("}", "}}")


def _format_candidates_for_merge(grouped: list[tuple[str, list[dict]]]) -> str:
    """카테고리별 후보 리스트를 머지 LLM 에 보낼 텍스트 블록으로 변환."""
    lines: list[str] = []
    for cat, cands in grouped:
        lines.append(f"\n### 카테고리: {cat} ({len(cands)}개)")
        for c in cands:
            lines.append(
                f"- key={c['key']} | category={cat} | name={c['display_name']} "
                f"| desc={c['description']}"
            )
            if c.get("recommendation_reason"):
                lines.append(f"  reason: {c['recommendation_reason']}")
    return _escape_braces("\n".join(lines)) if lines else "(none)"


def _format_preserve_for_merge(preserve: list[dict]) -> str:
    if not preserve:
        return "(none)"
    return _escape_braces(
        "\n".join(
            f"- {it['key']} ({it.get('display_name') or it['key']}): {it.get('description', '')}"
            for it in preserve
        )
    )


# ─── Public entrypoint ─────────────────────────────────────────────
async def recommend_edge_types_for_link(
    request,
    kg_id: str,
    link_id: str,
    user_id: str,
    model_id: Optional[str] = None,
    max_candidates: int = 12,
    extra_preserve: Optional[list[dict]] = None,
) -> list[dict]:
    """링크 컨텍스트(글로서리 + KB)로 LLM 에게 엣지 타입 카탈로그 후보를 받는다.

    Map-reduce 전략: 글로서리 카테고리가 2개 이상이면
      1. 각 카테고리별 intra-call (병렬, 카테고리 내부 관계만)
      2. 머지 콜 1개: 모든 intra 결과를 받아 의미상 중복 통합 + 카테고리 간 관계 추가
    카테고리가 1개 이하면 단일 콜로 fallback.

    ``extra_preserve`` 는 현재 카탈로그에 없더라도 "이미 존재한다고 가정하고
    의미 변형 제안을 금지" 할 항목들. 프론트 seed(기본 엣지 타입)를 여기로 전달.
    각 원소: ``{key, display_name?, description?}``

    DB 는 건드리지 않는다. 추천 결과 list 만 반환.
    각 원소: ``{key, display_name, description, recommendation_reason}``
    """
    import asyncio

    app = request.app
    ctx = await _build_link_recommendation_context(app, kg_id, link_id)

    llm_config, chosen_model_id = _resolve_model_config(app, kg_id, model_id)
    llm = create_llm(llm_config, streaming=False, model_kwargs={"temperature": 0.1})

    preserve_keys = {
        it["key"] for it in (ctx["existing_catalog"].get("preserve") or [])
    }
    preserve_items = list(ctx["existing_catalog"].get("preserve") or [])

    # extra_preserve 머지 — 프론트 seed 항목을 preserve 에 추가해서 LLM 이
    # 의미상 변형도 제안하지 않도록.
    if extra_preserve:
        for ep in extra_preserve:
            if not isinstance(ep, dict):
                continue
            ek = (ep.get("key") or "").strip()
            if not ek or ek in preserve_keys:
                continue
            preserve_keys.add(ek)
            preserve_items.append(
                {
                    "key": ek,
                    "display_name": ep.get("display_name") or ek,
                    "description": ep.get("description") or "",
                    "source": "default",
                }
            )

    g = ctx.get("glossary") or {}
    cats = list((g.get("category_counts") or {}).keys())
    cats = [c for c in cats if c]  # drop empty

    if len(cats) < 2:
        # 단일 콜 (카테고리 0 또는 1개)
        log.info(
            f"[edge_type_recommender] SINGLE kg={kg_id[:8]} link={link_id[:8]} "
            f"model={chosen_model_id} kbs={len(ctx['knowledges'])}"
        )
        sys_prompt = _SYSTEM_PROMPT_SINGLE.format(max_candidates=max_candidates)
        user_prompt = _render_link_context_block(ctx)
        try:
            return await _call_llm_for_candidates(
                llm,
                sys_prompt,
                user_prompt,
                preserve_keys,
                set(),
                max_candidates,
            )
        except Exception as e:
            log.exception(f"[edge_type_recommender] single call failed: {e}")
            return []

    # ── Map-reduce + dedicated cross call (parallel) ──
    cats_to_run = cats[:_MAX_INTRA_CATEGORIES]
    # intra_cap: 카테고리당 충분한 슬롯을 주어 반복 구조 메타데이터를 놓치지
    # 않도록 하한 12. max_candidates 는 어디까지나 soft 힌트.
    intra_cap = max(12, max_candidates // len(cats_to_run))
    cross_cap = max(6, max_candidates)

    log.info(
        f"[edge_type_recommender] MAP-REDUCE kg={kg_id[:8]} link={link_id[:8]} "
        f"model={chosen_model_id} categories={cats_to_run} "
        f"intra_cap={intra_cap} cross_cap={cross_cap}"
    )

    async def _run_intra(cat: str) -> tuple[str, list[dict]]:
        sub_ctx = _focus_glossary_on_category(ctx, cat)
        other_cats = [c for c in cats_to_run if c != cat]
        sys_prompt = _SYSTEM_PROMPT_INTRA.format(
            focus_category=cat,
            other_categories=", ".join(other_cats) or "(none)",
            max_candidates=intra_cap,
        )
        user_prompt = _render_intra_context_block(sub_ctx, cat)
        log.info(
            f"[edge_type_recommender] intra category={cat} "
            f"prompt_chars={len(user_prompt)}"
        )
        try:
            cands = await _call_llm_for_candidates(
                llm,
                sys_prompt,
                user_prompt,
                preserve_keys,
                set(),  # intra 는 자기들끼리만 dedupe (key 충돌은 머지에서 정리)
                intra_cap,
            )
            # intra 콜 결과는 무조건 해당 카테고리로 scope 재설정.
            # LLM 이 스키마 예시의 src/dst_category 필드를 습관적으로 채워서
            # 반환하더라도 강제로 clear 하고 category 만 주입.
            for c in cands:
                c["src_category"] = None
                c["dst_category"] = None
                c["category"] = cat
            return cat, cands
        except Exception as e:
            log.warning(f"[edge_type_recommender] intra call failed ({cat}): {e}")
            return cat, []

    async def _run_cross() -> list[dict]:
        sys_prompt = _SYSTEM_PROMPT_CROSS.format(
            all_categories=", ".join(cats_to_run),
            max_candidates=cross_cap,
        )
        user_prompt = _render_link_context_block(ctx)
        log.info(
            f"[edge_type_recommender] cross call categories={cats_to_run} "
            f"prompt_chars={len(user_prompt)}"
        )
        try:
            return await _call_llm_for_candidates(
                llm,
                sys_prompt,
                user_prompt,
                preserve_keys,
                set(),
                cross_cap,
            )
        except Exception as e:
            log.warning(f"[edge_type_recommender] cross call failed: {e}")
            return []

    # 1) Map + Cross: 모든 intra 콜 + 전용 cross 콜 병렬
    gather_results = await asyncio.gather(
        *[_run_intra(cat) for cat in cats_to_run],
        _run_cross(),
    )
    intra_results: list[tuple[str, list[dict]]] = gather_results[:-1]
    cross_raw: list[dict] = gather_results[-1]

    total_intra = sum(len(cands) for _, cands in intra_results)
    log.info(
        f"[edge_type_recommender] map done: intra={total_intra} across "
        f"{len(intra_results)} cats, cross={len(cross_raw)}"
    )

    # cross 필터링 — src/dst_category 가 모두 유효하고 다른 것만 유지.
    # 같은 pair 의 역방향 중복은 frozenset 으로 제거.
    cross_clean: list[dict] = []
    seen_cross_keys: set[str] = set()
    seen_pairs: set[frozenset[str]] = set()
    for c in cross_raw:
        src_cat = c.get("src_category")
        dst_cat = c.get("dst_category")
        if not src_cat or not dst_cat or src_cat == dst_cat:
            log.info(
                f"[edge_type_recommender] drop cross candidate {c.get('key')} — "
                f"missing or equal category"
            )
            continue
        pair = frozenset((src_cat, dst_cat))
        if pair in seen_pairs:
            log.info(
                f"[edge_type_recommender] drop inverse duplicate {c.get('key')} "
                f"({src_cat}→{dst_cat}) — pair already covered"
            )
            continue
        seen_pairs.add(pair)
        if c["key"] in seen_cross_keys:
            continue
        seen_cross_keys.add(c["key"])
        cross_clean.append(c)

    if total_intra == 0 and not cross_clean:
        return []

    # 2) Reduce: intra 전용 머지 콜 — 중복 통합만
    merged_intra: list[dict] = []
    if total_intra > 0:
        # merge 는 dedupe 만 수행하므로 입력 개수만큼 출력 여유가 필요.
        # 각 intra 의 합계에 소폭 여유를 주어 legitimate intra 가 잘리지 않도록.
        merge_cap = max(total_intra, max_candidates)
        sys_prompt = _SYSTEM_PROMPT_MERGE.format(
            all_categories=", ".join(cats_to_run),
            candidate_blocks=_format_candidates_for_merge(intra_results),
            preserve_block=_format_preserve_for_merge(preserve_items),
            max_candidates=merge_cap,
        )
        cat_dist = ", ".join(
            f"{c}({(g.get('category_counts') or {}).get(c, 0)})" for c in cats_to_run
        )
        user_prompt = (
            f"카테고리 분포: {cat_dist}\n"
            "(위 후보 목록에서 의미 중복만 통합하세요. 새 엣지 타입은 추가하지 마세요.)"
        )
        try:
            merged_intra = await _call_llm_for_candidates(
                llm,
                sys_prompt,
                user_prompt,
                preserve_keys | seen_cross_keys,
                set(),
                merge_cap,
            )
        except Exception as e:
            log.exception(f"[edge_type_recommender] merge call failed: {e}")
            # fallback: intra 결과를 단순 dedup
            seen: set[str] = set()
            for _, cands in intra_results:
                for c in cands:
                    if c["key"] in seen:
                        continue
                    seen.add(c["key"])
                    merged_intra.append(c)
            merged_intra = merged_intra[:max_candidates]

    # merge 콜 결과에서 카테고리 간 항목이 섞여 들어온 경우 drop
    # (merge 프롬프트가 금지했지만 LLM 가끔 무시)
    merged_intra = [
        c
        for c in merged_intra
        if not (
            c.get("src_category")
            and c.get("dst_category")
            and c.get("src_category") != c.get("dst_category")
        )
    ]

    # category 강제 매핑 — MERGE 콜은 카테고리를 출력하지 않도록 지시했고,
    # key 도 입력에서만 선택하도록 강제했다. 코드는 input intra_results 로부터
    # key → category 매핑을 만들어 출력에 일괄 주입한다. 입력에 없는 key 는
    # 매핑 불가이므로 drop (LLM 이 새 key 를 만든 경우 — 드물어야 함).
    key_to_cats: dict[str, set[str]] = {}
    for cat_name, cands in intra_results:
        for c in cands:
            key_to_cats.setdefault(c["key"], set()).add(cat_name)

    mapped: list[dict] = []
    dropped_unknown_key = 0
    for c in merged_intra:
        cats_for_key = key_to_cats.get(c["key"])
        if not cats_for_key:
            # 입력에 없는 key — MERGE 콜이 새 key 를 만든 경우.
            # 카테고리 매핑 불가 + 데이터 일관성 보장 X → drop.
            dropped_unknown_key += 1
            continue
        # 코드가 카테고리 강제 주입 (LLM 출력은 무시)
        c["src_category"] = None
        c["dst_category"] = None
        if len(cats_for_key) == 1:
            c["category"] = next(iter(cats_for_key))
        else:
            # broad 개념이 여러 카테고리에 공통 등장한 경우 — sorted 첫 카테고리로
            # 강제 매핑. None 으로 두면 UI 에서 카테고리 누락처럼 보여 사용자 혼란.
            # 한 카테고리에 우선 표시하되 사용자가 필요시 수동으로 카탈로그에서
            # 다른 카테고리에도 추가 가능.
            c["category"] = sorted(cats_for_key)[0]
        mapped.append(c)
    merged_intra = mapped
    if dropped_unknown_key:
        log.info(
            f"[edge_type_recommender] dropped {dropped_unknown_key} merged_intra "
            f"items with unknown key (LLM invented new key)"
        )

    # 3) 합치기: cross 먼저 → intra. 키 충돌 시 cross 유지.
    cross_keys = {c["key"] for c in cross_clean}
    final: list[dict] = list(cross_clean) + [
        c for c in merged_intra if c["key"] not in cross_keys
    ]

    log.info(
        f"[edge_type_recommender] done: {len(final)} final candidates "
        f"(cross={len(cross_clean)}, intra={len(merged_intra)})"
    )
    return final
