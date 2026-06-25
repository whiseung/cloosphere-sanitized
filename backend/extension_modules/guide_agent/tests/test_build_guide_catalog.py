"""build_guide_catalog 단위 테스트 — 임시 트리에 가짜 docs.json + .mdx 생성."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.build_guide_catalog import _classify_audience, build_catalog


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


@pytest.fixture
def fake_docs_root(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    docs_json = {
        "navigation": {
            "languages": [
                {
                    "language": "ko",
                    "tabs": [
                        {
                            "tab": "시작하기",
                            "groups": [
                                {
                                    "group": "기본",
                                    "pages": [
                                        "ko/getting-started/overview",
                                        "ko/admin/users",
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "language": "en",
                    "tabs": [
                        {
                            "tab": "Getting Started",
                            "groups": [
                                {
                                    "group": "Basics",
                                    "pages": [
                                        "en/getting-started/overview",
                                        "en/admin/users",
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    }
    _write(root / "docs.json", json.dumps(docs_json))
    _write(
        root / "ko" / "getting-started" / "overview.mdx",
        '---\ntitle: "개요"\ndescription: "ko desc"\n---\n\n본문',
    )
    _write(
        root / "en" / "getting-started" / "overview.mdx",
        '---\ntitle: "Overview"\ndescription: "en desc"\n---\n\nbody',
    )
    _write(
        root / "ko" / "admin" / "users.mdx",
        '---\ntitle: "사용자"\ndescription: "관리자용"\n---\n\n본문',
    )
    _write(
        root / "en" / "admin" / "users.mdx",
        '---\ntitle: "Users"\ndescription: "admin only"\n---\n\nbody',
    )
    # Filesystem-only page (not in nav)
    _write(
        root / "ko" / "whats-new.mdx",
        '---\ntitle: "변경사항"\ndescription: "릴리즈 노트"\n---\n\n본문',
    )
    _write(
        root / "en" / "whats-new.mdx",
        '---\ntitle: "Changelog"\ndescription: "release notes"\n---\n\nbody',
    )
    return root


def test_classify_audience_admin_prefix():
    assert _classify_audience("admin/users") == "admin"
    assert _classify_audience("admin/settings/general") == "admin"


def test_classify_audience_monitoring_prefix():
    assert _classify_audience("monitoring/audit-logs") == "admin"


def test_classify_audience_user_default():
    assert _classify_audience("getting-started/overview") == "user"
    assert _classify_audience("workspace/agents") == "user"
    assert _classify_audience("index") == "user"


def test_build_catalog_contains_nav_pages(fake_docs_root: Path):
    catalog = build_catalog(
        docs_root=fake_docs_root, docs_json=fake_docs_root / "docs.json"
    )
    ids = {c["id"] for c in catalog["categories"]}
    assert "getting-started/overview" in ids
    assert "admin/users" in ids


def test_build_catalog_picks_up_filesystem_only_pages(fake_docs_root: Path):
    catalog = build_catalog(
        docs_root=fake_docs_root, docs_json=fake_docs_root / "docs.json"
    )
    by_id = {c["id"]: c for c in catalog["categories"]}
    assert "whats-new" in by_id
    assert by_id["whats-new"]["in_nav"] is False
    assert by_id["whats-new"]["title_ko"] == "변경사항"
    assert by_id["whats-new"]["title_en"] == "Changelog"


def test_build_catalog_classifies_audience_correctly(fake_docs_root: Path):
    catalog = build_catalog(
        docs_root=fake_docs_root, docs_json=fake_docs_root / "docs.json"
    )
    by_id = {c["id"]: c for c in catalog["categories"]}
    assert by_id["admin/users"]["audience"] == "admin"
    assert by_id["getting-started/overview"]["audience"] == "user"


def test_build_catalog_extracts_titles_and_descriptions(fake_docs_root: Path):
    catalog = build_catalog(
        docs_root=fake_docs_root, docs_json=fake_docs_root / "docs.json"
    )
    by_id = {c["id"]: c for c in catalog["categories"]}
    entry = by_id["getting-started/overview"]
    assert entry["title_ko"] == "개요"
    assert entry["title_en"] == "Overview"
    assert entry["description_ko"] == "ko desc"
    assert entry["description_en"] == "en desc"
    assert entry["tab_ko"] == "시작하기"
    assert entry["tab_en"] == "Getting Started"
    assert entry["group_ko"] == "기본"
    assert entry["group_en"] == "Basics"


def test_build_catalog_audience_counts(fake_docs_root: Path):
    catalog = build_catalog(
        docs_root=fake_docs_root, docs_json=fake_docs_root / "docs.json"
    )
    # admin/users → admin; getting-started/overview, whats-new → user
    assert catalog["audience_counts"]["admin"] == 1
    assert catalog["audience_counts"]["user"] == 2
