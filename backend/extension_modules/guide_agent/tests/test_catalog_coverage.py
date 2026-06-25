"""실제 guide_catalog.yaml 의 커버리지/일관성 검증.

오프라인(LLM 호출 없음). regression_questions.yaml 의 expected_categories 가
실제 카탈로그에 존재하는지, audience 분류가 일관적인지를 빠르게 점검한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3].parent
CATALOG = ROOT / "backend" / "extension_modules" / "guide_agent" / "guide_catalog.yaml"
QUESTIONS = (
    ROOT
    / "backend"
    / "extension_modules"
    / "guide_agent"
    / "tests"
    / "regression_questions.yaml"
)


@pytest.fixture(scope="module")
def catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]


def test_catalog_exists_and_has_64_categories(catalog):
    assert catalog["categories"], "Catalog is empty"
    assert len(catalog["categories"]) == 64, (
        f"Expected 64 categories, got {len(catalog['categories'])}"
    )


def test_catalog_audience_split(catalog):
    counts = catalog["audience_counts"]
    assert counts["admin"] >= 22  # admin/* + monitoring/*
    assert counts["user"] >= 30


def test_all_categories_have_files(catalog):
    missing = [
        c["id"] for c in catalog["categories"] if not c["file_ko"] or not c["file_en"]
    ]
    assert missing == [], f"Categories missing ko/en files: {missing}"


def test_all_categories_have_titles(catalog):
    missing = [
        c["id"] for c in catalog["categories"] if not c["title_ko"] or not c["title_en"]
    ]
    assert missing == [], f"Categories missing titles: {missing}"


def test_regression_set_has_at_least_80_questions(questions):
    assert len(questions) >= 80, (
        f"Need >= 80 regression questions, got {len(questions)}"
    )


def test_all_expected_categories_exist_in_catalog(catalog, questions):
    catalog_ids = {c["id"] for c in catalog["categories"]}
    unknown = []
    for q in questions:
        for expected in q.get("expected_categories", []):
            if expected not in catalog_ids:
                unknown.append((q["question"], expected))
    assert unknown == [], f"Regression refs unknown categories: {unknown[:5]}..."


def test_admin_only_questions_target_admin_categories(catalog, questions):
    """role=admin 인 질문의 expected_categories 는 admin audience 여야 한다."""
    by_id = {c["id"]: c for c in catalog["categories"]}
    mismatches = []
    for q in questions:
        if q.get("role") != "admin":
            continue
        for expected in q.get("expected_categories", []):
            entry = by_id.get(expected)
            if entry and entry["audience"] != "admin":
                mismatches.append((q["question"], expected, entry["audience"]))
    assert mismatches == [], (
        f"Admin-role questions targeting user categories: {mismatches}"
    )


def test_admin_blocked_questions_have_empty_expected(questions):
    blocked = [q for q in questions if q.get("tag") == "admin-blocked"]
    for q in blocked:
        assert q["expected_categories"] == [], (
            f"admin-blocked question must have empty expected_categories: {q['question']}"
        )
