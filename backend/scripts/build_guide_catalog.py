"""docs.json → guide_catalog.yaml 자동 생성기.

색인 가능한 카테고리(canonical id) 목록을 만들어 chunker·tools.py 가 사용하도록 한다.
canonical id = `<category>/<page>` (lang prefix 제거).

Audience:
- `admin/*` 또는 `monitoring/*` → admin
- 그 외 → user

사용법:
    uv run python -m backend.scripts.build_guide_catalog
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from extension_modules.guide_agent.mdx_cleaner import clean_mdx

log = logging.getLogger("build_guide_catalog")

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = (REPO_ROOT / "guide" / "docs").resolve()
DOCS_JSON = DOCS_ROOT / "docs.json"
OUTPUT_PATH = (
    REPO_ROOT / "backend" / "extension_modules" / "guide_agent" / "guide_catalog.yaml"
)

ADMIN_PREFIXES = ("admin/", "monitoring/")

CATALOG_ENTRY_LANG_FIELDS = (
    "tab_ko",
    "tab_en",
    "group_ko",
    "group_en",
    "title_ko",
    "title_en",
    "description_ko",
    "description_en",
    "file_ko",
    "file_en",
)


def _empty_entry(canonical: str, *, in_nav: bool) -> dict[str, Any]:
    """카탈로그 entry 의 기본 스켈레톤. 키 추가 시 한 곳만 수정."""
    return {
        "id": canonical,
        "audience": _classify_audience(canonical),
        **{k: "" for k in CATALOG_ENTRY_LANG_FIELDS},
        "in_nav": in_nav,
    }


def _relpath(
    path: Path, *, docs_root: Path = DOCS_ROOT, repo_root: Path = REPO_ROOT
) -> str:
    """Path → repo_root 상대경로. docs_root 외부면 ValueError (path traversal 방어).

    docs_root/repo_root 인자는 테스트가 임시 디렉토리를 주입할 수 있도록 분리.
    """
    resolved = path.resolve()
    docs_resolved = docs_root.resolve()
    try:
        resolved.relative_to(docs_resolved)
    except ValueError as e:
        raise ValueError(f"Path outside docs root ({docs_resolved}): {path}") from e
    try:
        return str(resolved.relative_to(repo_root.resolve()))
    except ValueError:
        return str(resolved)


def _flatten_pages(tabs: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for tab in tabs:
        tab_name = tab.get("tab", "")
        for grp in tab.get("groups", []):
            group_name = grp.get("group", "")
            for page in grp.get("pages", []):
                if isinstance(page, str):
                    out.append({"page": page, "tab": tab_name, "group": group_name})
                elif isinstance(page, dict):
                    sub_group = page.get("group", group_name)
                    for sub in page.get("pages", []):
                        if isinstance(sub, str):
                            out.append(
                                {"page": sub, "tab": tab_name, "group": sub_group}
                            )
    return out


def _classify_audience(canonical: str) -> str:
    return "admin" if canonical.startswith(ADMIN_PREFIXES) else "user"


def _read_frontmatter(path: Path) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "", ""
    result = clean_mdx(text, source=str(path), strict=False)
    return result.title, result.description


def build_catalog(
    docs_root: Path = DOCS_ROOT, docs_json: Path = DOCS_JSON
) -> dict[str, Any]:
    if not docs_json.exists():
        raise FileNotFoundError(f"docs.json not found: {docs_json}")
    docs = json.loads(docs_json.read_text(encoding="utf-8"))

    languages = docs.get("navigation", {}).get("languages", [])
    if not languages:
        raise ValueError("docs.json navigation.languages is empty")

    by_canonical: dict[str, dict[str, Any]] = {}
    nav_pages_per_lang: dict[str, set[str]] = {}

    for lang_block in languages:
        lang = lang_block["language"]
        nav_pages_per_lang[lang] = set()
        for page in _flatten_pages(lang_block.get("tabs", [])):
            page_path = page["page"]
            if not page_path.startswith(f"{lang}/"):
                log.warning(
                    "Skipping page with mismatched lang prefix: %s (lang=%s)",
                    page_path,
                    lang,
                )
                continue
            canonical = page_path[len(lang) + 1 :]
            nav_pages_per_lang[lang].add(canonical)
            entry = by_canonical.setdefault(
                canonical, _empty_entry(canonical, in_nav=True)
            )
            entry[f"tab_{lang}"] = page["tab"]
            entry[f"group_{lang}"] = page["group"]
            file_path = docs_root / lang / f"{canonical}.mdx"
            entry[f"file_{lang}"] = _relpath(file_path, docs_root=docs_root)
            title, description = _read_frontmatter(file_path)
            entry[f"title_{lang}"] = title
            entry[f"description_{lang}"] = description

    # Filesystem-only pages (not in docs.json) — e.g., whats-new
    for lang_dir in docs_root.iterdir():
        if not lang_dir.is_dir() or lang_dir.name not in {"ko", "en"}:
            continue
        lang = lang_dir.name
        for mdx in lang_dir.rglob("*.mdx"):
            canonical = mdx.relative_to(lang_dir).with_suffix("").as_posix()
            if canonical in nav_pages_per_lang[lang]:
                continue
            entry = by_canonical.setdefault(
                canonical, _empty_entry(canonical, in_nav=False)
            )
            entry[f"file_{lang}"] = _relpath(mdx, docs_root=docs_root)
            title, description = _read_frontmatter(mdx)
            entry[f"title_{lang}"] = title
            entry[f"description_{lang}"] = description

    categories = sorted(by_canonical.values(), key=lambda e: e["id"])
    audience_counts = {
        "user": sum(1 for c in categories if c["audience"] == "user"),
        "admin": sum(1 for c in categories if c["audience"] == "admin"),
    }
    return {
        "version": 1,
        "source": "guide/docs/docs.json + guide/docs/{ko,en}/**/*.mdx",
        "audience_counts": audience_counts,
        "categories": categories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build guide_catalog.yaml from docs.json"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output YAML path (default: {OUTPUT_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print catalog summary without writing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    catalog = build_catalog()
    summary = (
        f"categories={len(catalog['categories'])} "
        f"user={catalog['audience_counts']['user']} "
        f"admin={catalog['audience_counts']['admin']}"
    )
    log.info("Catalog: %s", summary)

    missing_files = [
        c["id"] for c in catalog["categories"] if not c["file_ko"] or not c["file_en"]
    ]
    if missing_files:
        log.warning(
            "Categories missing one or both language files (%d): %s",
            len(missing_files),
            missing_files,
        )

    if args.dry_run:
        yaml.safe_dump(catalog, sys.stdout, allow_unicode=True, sort_keys=False)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(catalog, f, allow_unicode=True, sort_keys=False)
    log.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
