"""Unit tests for glossary file parser (XLSX / CSV / MD)."""

import io

import openpyxl
import pytest

from open_webui.utils import glossary_file_parser as gfp

# ============================================================
# Helpers — create in-memory test files
# ============================================================


def _make_xlsx(rows: list[list]) -> bytes:
    """rows: 첫 row 가 header. 나머지가 data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


# ============================================================
# parse_xlsx
# ============================================================


def test_parse_xlsx_basic():
    data = _make_xlsx(
        [
            ["term", "synonyms", "description", "example", "category"],
            [
                "B/L",
                "Bill of Lading, 선하증권",
                "운송 계약 증서",
                "B/L 발급",
                "운송 서류",
            ],
            ["A/R", "외상매출금", "매출채권", "A/R 정산", "재무/결제"],
        ]
    )
    out = gfp.parse_xlsx(data)
    assert out["format"] == "xlsx"
    assert out["headers"] == ["term", "synonyms", "description", "example", "category"]
    assert len(out["rows"]) == 2
    assert out["rows"][0]["term"] == "B/L"
    assert out["rows"][0]["synonyms"] == "Bill of Lading, 선하증권"


def test_parse_xlsx_empty_rows_skipped():
    data = _make_xlsx(
        [
            ["term", "category"],
            ["A", "x"],
            [None, None],
            ["", ""],
            ["B", "y"],
        ]
    )
    out = gfp.parse_xlsx(data)
    assert len(out["rows"]) == 2
    assert [r["term"] for r in out["rows"]] == ["A", "B"]


def test_parse_xlsx_no_header_raises():
    data = _make_xlsx([[None, None], ["A", "B"]])
    with pytest.raises(gfp.GlossaryParseError, match="비어 있"):
        gfp.parse_xlsx(data)


def test_parse_xlsx_max_rows_enforced():
    rows = [["term"]] + [[f"t{i}"] for i in range(5)]
    data = _make_xlsx(rows)
    with pytest.raises(gfp.GlossaryParseError, match="row 수"):
        gfp.parse_xlsx(data, max_rows=3)


# ============================================================
# parse_csv
# ============================================================


def test_parse_csv_utf8():
    data = _make_csv("term,description\nA,설명1\nB,설명2\n", "utf-8")
    out = gfp.parse_csv(data)
    assert out["format"] == "csv"
    assert out["encoding"] == "utf-8-sig" or out["encoding"] == "utf-8"
    assert len(out["rows"]) == 2
    assert out["rows"][0]["term"] == "A"


def test_parse_csv_utf8_bom():
    data = "﻿" + "term,description\nA,설명\n"
    out = gfp.parse_csv(data.encode("utf-8"))
    # utf-8-sig 가 BOM 제거 — 첫 헤더가 'term' 그대로
    assert out["rows"][0]["term"] == "A"


def test_parse_csv_cp949_fallback():
    data = _make_csv("term,description\nA,한글설명\n", "cp949")
    out = gfp.parse_csv(data)
    assert out["encoding"] == "cp949"
    assert out["rows"][0]["description"] == "한글설명"


def test_parse_csv_tab_delimiter():
    data = _make_csv("term\tdescription\nA\t설명\n", "utf-8")
    out = gfp.parse_csv(data)
    assert out["headers"] == ["term", "description"]
    assert out["rows"][0]["term"] == "A"


def test_parse_csv_empty_raises():
    with pytest.raises(gfp.GlossaryParseError, match="비어"):
        gfp.parse_csv(b"")


# ============================================================
# parse_md
# ============================================================


def test_parse_md_table():
    text = """
| term | synonyms | description |
|------|----------|-------------|
| B/L  | Bill of Lading | 운송 |
| A/R  | 외상매출금     | 매출 |
""".strip()
    out = gfp.parse_md(text.encode("utf-8"))
    assert out["format"] == "md"
    assert out["md_pattern"] == "table"
    assert len(out["rows"]) == 2
    assert out["rows"][0]["term"] == "B/L"
    assert out["rows"][1]["synonyms"] == "외상매출금"


def test_parse_md_sectioned():
    text = """
[1] B/L 용어: B/L, Bill of Lading 뜻: 선하증권 실무 예시: 발급 시 해설: □ 항목1 □ 항목2

[2] A/R 용어: A/R, 외상매출금 뜻: 매출채권 실무 예시: 정산 시 해설: □ 항목A
""".strip()
    out = gfp.parse_md(text.encode("utf-8"))
    assert out["md_pattern"] == "sectioned"
    assert len(out["rows"]) == 2
    assert out["rows"][0]["term"] == "B/L"
    # synonyms 는 원본 그대로 (normalize 단계에서 split)
    assert "Bill of Lading" in out["rows"][0]["synonyms"]
    # description 에 [해설] 섹션 + bullet 변환
    assert "[해설]" in out["rows"][0]["description"]
    assert "• 항목1" in out["rows"][0]["description"]


def test_parse_md_h2_dl():
    text = """
## B/L
- Synonyms: Bill of Lading, 선하증권
- Description: 운송 계약 증서
- Category: 운송 서류

## A/R
- 동의어: 외상매출금
- 뜻: 매출채권
- 분류: 재무/결제
""".strip()
    out = gfp.parse_md(text.encode("utf-8"))
    assert out["md_pattern"] == "h2-dl"
    assert len(out["rows"]) == 2
    assert out["rows"][0]["term"] == "B/L"
    assert out["rows"][0]["synonyms"] == "Bill of Lading, 선하증권"
    assert out["rows"][1]["category"] == "재무/결제"


def test_parse_md_unknown_pattern_raises():
    text = "Just some plain text, no markdown structure at all."
    with pytest.raises(gfp.GlossaryParseError, match="패턴"):
        gfp.parse_md(text.encode("utf-8"))


# ============================================================
# infer_header_mapping
# ============================================================


def test_infer_header_mapping_english():
    m = gfp.infer_header_mapping(
        ["Term", "Synonyms", "Description", "Example", "Category"]
    )
    assert m["Term"] == "term"
    assert m["Synonyms"] == "synonyms"
    assert m["Description"] == "description"
    assert m["Example"] == "example"
    assert m["Category"] == "category"


def test_infer_header_mapping_korean():
    m = gfp.infer_header_mapping(["제목", "용어", "뜻", "용도(예)", "해설"])
    assert m["제목"] == "term"
    # "용어" 는 컨텍스트 의존: 제목 (term) 이미 매칭됐으므로 synonyms 로 fallback
    assert m["용어"] == "synonyms"
    assert m["뜻"] == "description"
    assert m["용도(예)"] == "example"
    # description 이미 "뜻" 에 의해 채워졌으므로 "해설" 은 skip
    assert m["해설"] == "skip"


def test_infer_header_mapping_term_fallback_from_yongeo():
    """제목 없을 때 '용어' 가 term 으로 fallback."""
    m = gfp.infer_header_mapping(["용어", "뜻"])
    assert m["용어"] == "term"
    assert m["뜻"] == "description"


def test_infer_header_mapping_skip_for_unknown():
    m = gfp.infer_header_mapping(["term", "unknown_col", "memo"])
    assert m["term"] == "term"
    # unknown_col 은 키워드 매칭 없음 → skip
    assert m["unknown_col"] == "skip"
    assert m["memo"] == "skip"


def test_infer_header_mapping_first_match_wins():
    """동일 field 로 매칭되는 헤더 여러 개 → 첫 번째만 채택."""
    m = gfp.infer_header_mapping(["definition", "description"])
    # 둘 다 description 매칭. 첫 번째만 'description' 으로.
    assert sum(1 for v in m.values() if v == "description") == 1


# ============================================================
# normalize_entries
# ============================================================


def test_normalize_basic():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "synonyms", "description", "example", "category"],
        rows=[
            {
                "term": "B/L",
                "synonyms": "Bill of Lading, 선하증권",
                "description": "운송",
                "example": "B/L 발급",
                "category": "운송 서류",
            }
        ],
        encoding="utf-8",
        md_pattern=None,
    )
    mapping = {
        "term": "term",
        "synonyms": "synonyms",
        "description": "description",
        "example": "example",
        "category": "category",
    }
    entries, stats = gfp.normalize_entries(parsed, mapping)
    assert stats["parsed"] == 1
    assert entries[0]["term"] == "B/L"
    assert entries[0]["synonyms"] == ["Bill of Lading", "선하증권"]
    assert entries[0]["category"] == "운송 서류"


def test_normalize_slash_preserved_in_synonyms():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "synonyms"],
        rows=[{"term": "Outstanding", "synonyms": "A/R, A/P"}],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, _ = gfp.normalize_entries(parsed, {"term": "term", "synonyms": "synonyms"})
    # / 는 split 안 됨 — comma 만
    assert entries[0]["synonyms"] == ["A/R", "A/P"]


def test_normalize_primary_term_removed_from_synonyms():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "synonyms"],
        rows=[{"term": "B/L", "synonyms": "B/L, Bill of Lading"}],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, _ = gfp.normalize_entries(parsed, {"term": "term", "synonyms": "synonyms"})
    assert entries[0]["synonyms"] == ["Bill of Lading"]


def test_normalize_first_wins_for_duplicate_terms():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "description"],
        rows=[
            {"term": "B/L", "description": "first"},
            {"term": "b/l", "description": "second"},  # case-insensitive 중복
            {"term": "A/R", "description": "third"},
        ],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, stats = gfp.normalize_entries(
        parsed, {"term": "term", "description": "description"}
    )
    assert stats["parsed"] == 2
    assert stats["skipped"] == 1
    assert entries[0]["description"] == "first"


def test_normalize_empty_term_skipped():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "description"],
        rows=[
            {"term": "", "description": "x"},
            {"term": "   ", "description": "y"},
            {"term": "A", "description": "z"},
        ],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, stats = gfp.normalize_entries(
        parsed, {"term": "term", "description": "description"}
    )
    assert stats["parsed"] == 1
    assert stats["skipped"] == 2
    assert entries[0]["term"] == "A"


def test_normalize_skip_field_ignored():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "memo"],
        rows=[{"term": "B/L", "memo": "should be ignored"}],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, _ = gfp.normalize_entries(parsed, {"term": "term", "memo": "skip"})
    assert entries[0] == {
        "term": "B/L",
        "synonyms": [],
        "description": "",
        "example": "",
    }


def test_normalize_bullet_conversion_in_description():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "description"],
        rows=[{"term": "A", "description": "intro □ item1 □ item2"}],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, _ = gfp.normalize_entries(
        parsed, {"term": "term", "description": "description"}
    )
    assert "□" not in entries[0]["description"]
    assert "• item1" in entries[0]["description"]


def test_normalize_auto_classify_when_category_missing():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "synonyms"],
        rows=[
            {"term": "B/L", "synonyms": "Bill of Lading"},
            {"term": "Container", "synonyms": ""},
        ],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, _ = gfp.normalize_entries(
        parsed, {"term": "term", "synonyms": "synonyms"}, auto_classify=True
    )
    assert entries[0].get("category") == "운송 서류"
    assert entries[1].get("category") == "컨테이너"


def test_normalize_auto_classify_does_not_overwrite_existing_category():
    parsed = gfp.ParsedFile(
        format="csv",
        headers=["term", "category"],
        rows=[{"term": "Container", "category": "사용자지정"}],
        encoding="utf-8",
        md_pattern=None,
    )
    entries, _ = gfp.normalize_entries(
        parsed,
        {"term": "term", "category": "category"},
        auto_classify=True,
    )
    # 입력 그대로
    assert entries[0]["category"] == "사용자지정"


# ============================================================
# auto_classify_category — word boundary
# ============================================================


def test_auto_classify_bl_matches_in_term():
    assert gfp.auto_classify_category("B/L", []) == "운송 서류"


def test_auto_classify_bl_not_in_receivable():
    """짧은 약어 'BL' 가 'receivABLe' 같은 일반 단어에서 매칭되면 안 됨."""
    result = gfp.auto_classify_category(
        "Receivable", [], "Account receivable description"
    )
    # 운송 서류 (B/L) 로 잘못 매칭되면 안 됨 — 핵심 검증
    assert result != "운송 서류"


def test_auto_classify_no_match():
    assert gfp.auto_classify_category("RandomWord", [], "nothing meaningful") is None


# ============================================================
# parse_file dispatcher
# ============================================================


def test_parse_file_dispatcher_xlsx():
    data = _make_xlsx([["term"], ["A"]])
    out = gfp.parse_file("glossary.xlsx", data)
    assert out["format"] == "xlsx"


def test_parse_file_dispatcher_csv():
    out = gfp.parse_file("glossary.CSV", b"term\nA\n")
    assert out["format"] == "csv"


def test_parse_file_dispatcher_md():
    text = "## A\n- description: x"
    out = gfp.parse_file("glossary.md", text.encode("utf-8"))
    assert out["format"] == "md"


def test_parse_file_dispatcher_unsupported():
    with pytest.raises(gfp.GlossaryParseError, match="지원하지 않는"):
        gfp.parse_file("glossary.docx", b"x")


def test_parse_file_dispatcher_empty_filename():
    with pytest.raises(gfp.GlossaryParseError, match="파일명"):
        gfp.parse_file("", b"x")
