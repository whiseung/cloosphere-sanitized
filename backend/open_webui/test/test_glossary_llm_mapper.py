"""Unit tests for LLM-aided conversion rule apply + validate.

LLM 호출 자체는 외부 의존성이라 mock 또는 e2e. 여기서는 deterministic 부분만 검증.
"""

import pytest

from open_webui.utils import glossary_llm_mapper as mapper

# ============================================================
# apply_rule — 포트코드 시나리오 (실제 ACME 자료)
# ============================================================


PORT_CODE_RULE = {
    "mapping": {
        "term": {
            "kind": "column",
            "source": "Place Name(English)",
            "transform": "title_case",
        },
        "synonyms": {
            "kind": "concat_list",
            "sources": [
                {"kind": "template", "template": "{CN}{Place}"},
                {"kind": "column", "source": "Place"},
                {"kind": "column", "source": "Place Name(English)"},
            ],
        },
        "description": {
            "kind": "template",
            "template": "UN/LOCODE: {CN}{Place} (국가: {CN}, 코드: {Place}, 영문: {Place Name(English)})",
        },
        "example": {"kind": "constant", "value": ""},
        "category": {"kind": "constant", "value": "포트코드"},
    },
    "rationale": "포트코드 표 — CN + Place 합쳐서 UN/LOCODE",
}


def test_apply_rule_port_code_row():
    row = {
        "CN": "AE",
        "Place": "AJM",
        "Class": "PORT",
        "Place Name(Local)": "AJMAN, UNITED ARAB EMIRATES",
        "Place Name(English)": "AJMAN, UNITED ARAB EMIRATES",
    }
    entry = mapper.apply_rule(PORT_CODE_RULE, row)
    # title_case 변환
    assert entry["term"] == "Ajman, United Arab Emirates"
    # synonyms — AEAJM (concat) + AJM + 원본 (title 적용된 term 과 중복되니 제거 가능하지만
    # title_case 가 col level 이라 synonyms 원본 그대로 — primary term 과 다르므로 유지)
    syns = entry["synonyms"]
    assert "AEAJM" in syns
    assert "AJM" in syns
    # description 합성
    assert "AEAJM" in entry["description"]
    assert "AE" in entry["description"]
    # 카테고리 일괄 부여
    assert entry["category"] == "포트코드"


def test_apply_rule_skip_empty_term():
    row = {"CN": "", "Place Name(English)": ""}
    entry = mapper.apply_rule(PORT_CODE_RULE, row)
    assert entry["term"] == ""  # 빈 term — 호출자가 skip


def test_apply_rule_synonyms_dedupe_against_term():
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [
                    {"kind": "column", "source": "name"},
                    {"kind": "column", "source": "alt"},
                ],
            },
        },
    }
    entry = mapper.apply_rule(rule, {"name": "B/L", "alt": "Bill of Lading"})
    assert entry["term"] == "B/L"
    # synonyms 에서 primary term 'B/L' 제거됨
    assert "B/L" not in entry["synonyms"]
    assert "Bill of Lading" in entry["synonyms"]


def test_apply_rule_constant_only_no_term_raises_silently():
    rule = {
        "mapping": {
            "category": {"kind": "constant", "value": "x"},
        },
    }
    entry = mapper.apply_rule(rule, {})
    assert entry["term"] == ""


def test_apply_rule_template_with_missing_columns():
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {
                "kind": "template",
                "template": "{missing_col} - {name}",
            },
        },
    }
    entry = mapper.apply_rule(rule, {"name": "A"})
    # missing_col → '' substitution. strip 이후 leading space 제거.
    assert entry["description"] == "- A"


def test_apply_rule_skip_kind():
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {"kind": "skip"},
        },
    }
    entry = mapper.apply_rule(rule, {"name": "A"})
    assert entry["term"] == "A"
    assert entry["description"] == ""


def test_apply_rule_transforms():
    row = {"x": "hello world", "y": "  trim me  "}
    cases = [
        ({"kind": "column", "source": "x", "transform": "upper"}, "HELLO WORLD"),
        ({"kind": "column", "source": "x", "transform": "lower"}, "hello world"),
        ({"kind": "column", "source": "y", "transform": "trim"}, "trim me"),
    ]
    for spec, expected in cases:
        rule = {"mapping": {"term": spec}}
        entry = mapper.apply_rule(rule, row)
        assert entry["term"] == expected


def test_title_case_stopwords_lowercased():
    row = {"name": "REPUBLIC OF KOREA"}
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name", "transform": "title_case"},
        },
    }
    entry = mapper.apply_rule(rule, row)
    assert entry["term"] == "Republic of Korea"


def test_concat_list_dedupes_preserves_order():
    rule = {
        "mapping": {
            "term": {"kind": "constant", "value": "x"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [
                    {"kind": "constant", "value": "a"},
                    {"kind": "constant", "value": "b"},
                    {"kind": "constant", "value": "a"},  # duplicate
                ],
            },
        },
    }
    entry = mapper.apply_rule(rule, {})
    assert entry["synonyms"] == ["a", "b"]


# ============================================================
# validate_rule — sanitize LLM output
# ============================================================


def test_validate_rule_minimal_ok():
    out = mapper.validate_rule(
        {
            "mapping": {
                "term": {"kind": "column", "source": "x"},
            },
        }
    )
    assert out["mapping"]["term"]["kind"] == "column"
    assert out["mapping"]["term"]["source"] == "x"


def test_validate_rule_rejects_missing_term():
    with pytest.raises(mapper.RuleValidationError, match="term"):
        mapper.validate_rule(
            {"mapping": {"category": {"kind": "constant", "value": "x"}}}
        )


def test_validate_rule_rejects_invalid_kind():
    with pytest.raises(mapper.RuleValidationError, match="kind"):
        mapper.validate_rule(
            {
                "mapping": {
                    "term": {"kind": "eval", "expr": "__import__('os').system('rm')"},
                },
            }
        )


def test_validate_rule_strips_unknown_fields():
    out = mapper.validate_rule(
        {
            "mapping": {
                "term": {"kind": "column", "source": "x"},
                "unknown_field": {"kind": "constant", "value": "y"},
            },
        }
    )
    assert "unknown_field" not in out["mapping"]


def test_validate_rule_invalid_transform_falls_back_to_none():
    out = mapper.validate_rule(
        {
            "mapping": {
                "term": {"kind": "column", "source": "x", "transform": "EVAL"},
            },
        }
    )
    assert out["mapping"]["term"]["transform"] == "none"


def test_validate_rule_concat_depth_limited():
    """깊은 중첩 spec 거절."""
    spec = {"kind": "column", "source": "x"}
    nested = spec
    for _ in range(10):
        nested = {"kind": "concat", "sources": [nested], "join": ""}
    with pytest.raises(mapper.RuleValidationError, match="depth"):
        mapper.validate_rule({"mapping": {"term": nested}})


def test_validate_rule_template_length_capped():
    out = mapper.validate_rule(
        {
            "mapping": {
                "term": {"kind": "template", "template": "x" * 5000},
            },
        }
    )
    assert len(out["mapping"]["term"]["template"]) == 1000


def test_validate_rule_rationale_capped():
    out = mapper.validate_rule(
        {
            "mapping": {"term": {"kind": "column", "source": "x"}},
            "rationale": "x" * 1000,
        }
    )
    assert len(out["rationale"]) == 500


# ============================================================
# build_messages — prompt 안정성
# ============================================================


def test_build_messages_with_korean_headers():
    msgs = mapper.build_messages(
        ["국가", "코드"],
        [{"국가": "한국", "코드": "KR"}],
    )
    assert len(msgs) == 2
    # System + User
    assert "헤더" in msgs[1].content
    assert "국가" in msgs[1].content


# ============================================================
# split kind — 콤마/세미콜론 구분 다중 동의어 (T10)
# ============================================================


def test_apply_rule_split_in_concat_list_terminology():
    """terminology.xlsx 의 '용어' 컬럼 = 'A/R, 외상매출금' → split 으로 2개 동의어."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "제목"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [
                    {
                        "kind": "split",
                        "source": "용어",
                        "separator": ",",
                        "transform": "trim",
                    }
                ],
            },
        },
    }
    row = {"제목": "Account Receivable", "용어": "A/R, 외상매출금"}
    entry = mapper.apply_rule(rule, row)
    assert entry["term"] == "Account Receivable"
    # 콤마로 분리되어 양쪽 다 검색 hit 가능
    assert "A/R" in entry["synonyms"]
    assert "외상매출금" in entry["synonyms"]


def test_apply_rule_split_empty_value_returns_empty_list():
    rule = {
        "mapping": {
            "term": {"kind": "constant", "value": "x"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [{"kind": "split", "source": "missing", "separator": ","}],
            },
        },
    }
    entry = mapper.apply_rule(rule, {})
    assert entry["synonyms"] == []


def test_apply_rule_split_semicolon_separator():
    rule = {
        "mapping": {
            "term": {"kind": "constant", "value": "x"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [
                    {
                        "kind": "split",
                        "source": "aliases",
                        "separator": ";",
                        "transform": "trim",
                    }
                ],
            },
        },
    }
    entry = mapper.apply_rule(rule, {"aliases": "B/L ; 선하증권 ; Bill of Lading"})
    # term 'x' 가 synonyms 와 다르므로 dedupe 영향 없음
    assert entry["synonyms"] == ["B/L", "선하증권", "Bill of Lading"]


def test_validate_split_rejects_nested_source():
    """split.source 는 column 이름 (str) 만. nested spec 거절 (depth attack 방어)."""
    with pytest.raises(mapper.RuleValidationError, match="split.source"):
        mapper.validate_rule(
            {
                "mapping": {
                    "term": {"kind": "constant", "value": "x"},
                    "synonyms": {
                        "kind": "concat_list",
                        "sources": [
                            {
                                "kind": "split",
                                "source": {"kind": "column", "source": "x"},
                                "separator": ",",
                            }
                        ],
                    },
                },
            }
        )


def test_validate_split_separator_capped_and_defaulted():
    out = mapper.validate_rule(
        {
            "mapping": {
                "term": {"kind": "constant", "value": "x"},
                "synonyms": {
                    "kind": "concat_list",
                    "sources": [
                        {
                            "kind": "split",
                            "source": "용어",
                            "separator": "######longseparator",  # >5 → capped
                        }
                    ],
                },
            },
        }
    )
    sep = out["mapping"]["synonyms"]["sources"][0]["separator"]
    assert len(sep) <= 5


def test_validate_split_blank_separator_defaults_to_comma():
    out = mapper.validate_rule(
        {
            "mapping": {
                "term": {"kind": "constant", "value": "x"},
                "synonyms": {
                    "kind": "concat_list",
                    "sources": [
                        {"kind": "split", "source": "용어", "separator": "   "}
                    ],
                },
            },
        }
    )
    assert out["mapping"]["synonyms"]["sources"][0]["separator"] == ","


def test_validate_split_missing_source_raises():
    with pytest.raises(mapper.RuleValidationError, match="split.source"):
        mapper.validate_rule(
            {
                "mapping": {
                    "term": {"kind": "constant", "value": "x"},
                    "synonyms": {
                        "kind": "concat_list",
                        "sources": [{"kind": "split", "separator": ","}],
                    },
                },
            }
        )


# ============================================================
# apply_rule_with_segments — Hallucination 시각 표시 (T11)
# ============================================================


def test_segments_template_separates_literal_and_data():
    """template 의 placeholder = data, 사이 wording = literal."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {
                "kind": "template",
                "template": "{name}는 좋은 항목이며, 코드 {code}로 식별된다.",
            },
        },
    }
    result = mapper.apply_rule_with_segments(rule, {"name": "AJMAN", "code": "AJM"})
    segs = result["segments"]["description"]
    # 순서: [data:AJMAN, literal:"는 좋은 ...", data:AJM, literal:"로 식별된다."]
    kinds = [s["kind"] for s in segs]
    texts = [s["text"] for s in segs]
    assert kinds[0] == "data"
    assert texts[0] == "AJMAN"
    # 어딘가에 literal "는 좋은 항목이며, 코드 " 같은 wording
    assert any(s["kind"] == "literal" and "좋은" in s["text"] for s in segs)
    # AJM 도 data segment 로
    assert any(s["kind"] == "data" and s["text"] == "AJM" for s in segs)


def test_segments_column_all_data():
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name", "transform": "title_case"},
            "description": {"kind": "column", "source": "desc"},
        },
    }
    result = mapper.apply_rule_with_segments(
        rule, {"name": "hello", "desc": "실무 정의"}
    )
    desc_segs = result["segments"]["description"]
    assert len(desc_segs) == 1
    assert desc_segs[0] == {"kind": "data", "text": "실무 정의"}
    # term 도 data (transform 적용된 값)
    term_segs = result["segments"]["term"]
    assert term_segs == [{"kind": "data", "text": "Hello"}]


def test_segments_constant_all_literal():
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "category": {"kind": "constant", "value": "포트코드"},
        },
    }
    result = mapper.apply_rule_with_segments(rule, {"name": "x"})
    assert result["segments"]["category"] == [{"kind": "literal", "text": "포트코드"}]


def test_segments_entry_matches_apply_rule():
    """segments 함수가 apply_rule 과 동일한 entry 반환."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name", "transform": "title_case"},
            "description": {
                "kind": "template",
                "template": "{name} - {code}",
            },
        },
    }
    row = {"name": "hello world", "code": "HW1"}
    result = mapper.apply_rule_with_segments(rule, row)
    plain = mapper.apply_rule(rule, row)
    assert result["entry"] == plain


def test_segments_empty_term_returns_empty_segments():
    rule = {"mapping": {"term": {"kind": "column", "source": "name"}}}
    result = mapper.apply_rule_with_segments(rule, {"name": ""})
    assert result["segments"] == {}


def test_segments_skip_synonyms_list_field():
    """synonyms (list field) 는 segment 분해 X — 사용자가 list 로 이미 인지."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [{"kind": "column", "source": "alt"}],
            },
        },
    }
    result = mapper.apply_rule_with_segments(rule, {"name": "B/L", "alt": "선하증권"})
    # synonyms 는 segments 에 포함 안 됨
    assert "synonyms" not in result["segments"]
    # term 만 분해
    assert "term" in result["segments"]


# ============================================================
# 보수 모드 (Hallucination 방어 B) — T12
# ============================================================


def test_conservative_description_downgrades_template():
    """description 이 template 이면 conservative 모드에서 skip 으로 강등."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {
                "kind": "template",
                "template": "이것은 {name}의 상세 설명이며 AI 가 만든 wording...",
            },
        },
    }
    out = mapper._enforce_conservative_description(rule)
    assert out["mapping"]["description"] == {"kind": "skip"}


def test_conservative_description_keeps_column():
    """description 이 column 이면 그대로 유지."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {"kind": "column", "source": "desc"},
        },
    }
    out = mapper._enforce_conservative_description(rule)
    assert out["mapping"]["description"]["kind"] == "column"
    assert out["mapping"]["description"]["source"] == "desc"


def test_conservative_description_downgrades_constant():
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {"kind": "constant", "value": "고정 설명"},
        },
    }
    out = mapper._enforce_conservative_description(rule)
    assert out["mapping"]["description"] == {"kind": "skip"}


def test_conservative_description_concat_with_nested_template_downgraded():
    """concat 안에 template 이 끼어있으면 description 전체 skip."""
    rule = {
        "mapping": {
            "term": {"kind": "column", "source": "name"},
            "description": {
                "kind": "concat",
                "sources": [
                    {"kind": "column", "source": "desc"},
                    {"kind": "template", "template": "추가 설명"},
                ],
                "join": " ",
            },
        },
    }
    out = mapper._enforce_conservative_description(rule)
    assert out["mapping"]["description"] == {"kind": "skip"}


def test_build_messages_includes_conservative_rule():
    msgs = mapper.build_messages(
        ["name", "desc"],
        [{"name": "A", "desc": "B"}],
        conservative_description=True,
    )
    assert "보수 모드" in msgs[0].content
    assert "template" in msgs[0].content


def test_build_messages_default_excludes_conservative_rule():
    msgs = mapper.build_messages(["name"], [{"name": "A"}])
    assert "보수 모드" not in msgs[0].content


def test_apply_rule_split_literal_not_regex():
    """separator 는 literal split — '.' / '|' 같은 정규식 메타문자 그대로 처리."""
    rule = {
        "mapping": {
            "term": {"kind": "constant", "value": "x"},
            "synonyms": {
                "kind": "concat_list",
                "sources": [{"kind": "split", "source": "v", "separator": "."}],
            },
        },
    }
    entry = mapper.apply_rule(rule, {"v": "a.b.c"})
    # 정규식이면 "a","b","c" 가 아닌 다른 결과. literal split → 3개
    assert entry["synonyms"] == ["a", "b", "c"]
