#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown>=3.7", "pygments>=2.18"]
# ///
"""
Cloosphere 가이드 → 정적 HTML 빌더 (한/영 이중 언어)
실행: uv run guide/build.py
출력: guide-output/ko/, guide-output/en/
"""

import re
import shutil
import urllib.request
from pathlib import Path

import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from pygments.formatters import HtmlFormatter

# ─── 설정 ─────────────────────────────────────────────────
GUIDE_DIR = Path(__file__).parent
OUTPUT_DIR = GUIDE_DIR.parent / "guide-output"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.0/dist/mermaid.min.js"

LANG_CONFIG = {
    "ko": {"site_name": "Cloosphere 사용자 가이드", "menu_label": "메뉴"},
    "en": {"site_name": "Cloosphere User Guide", "menu_label": "Menu"},
}

# ─── CSS ──────────────────────────────────────────────────
MAIN_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --theme:#3b82f6;--theme-d:#2563eb;
  --sidebar-w:272px;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --mono:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;
  --text:#2c3e50;--bg:#fff;--sidebar-bg:#f8f9fa;
  --border:#e9ecef;--muted:#6c757d;
}
html,body{margin:0;padding:0;height:100%}
body{font-family:var(--font);color:var(--text);background:var(--bg);display:flex;min-height:100vh}

/* ── Sidebar ─────────────────────────── */
.sidebar{
  width:var(--sidebar-w);min-height:100vh;background:var(--sidebar-bg);
  border-right:1px solid var(--border);display:flex;flex-direction:column;
  position:fixed;top:0;left:0;bottom:0;overflow-y:auto;z-index:100;transition:transform .25s
}
.sidebar-header{
  display:flex;align-items:center;gap:10px;padding:20px 20px 16px;
  border-bottom:1px solid var(--border);font-weight:700;font-size:1rem;
  color:var(--text);text-decoration:none
}
.sidebar-header img{width:28px;height:28px;object-fit:contain}
.sidebar-nav{padding:10px 0 24px}
.nav-section{
  padding:14px 20px 5px;font-size:.7rem;font-weight:700;
  text-transform:uppercase;letter-spacing:.08em;color:var(--muted)
}
.nav-link{
  display:block;padding:6px 20px;font-size:.9rem;color:var(--text);
  text-decoration:none;border-left:3px solid transparent;transition:all .15s
}
.nav-link:hover{color:var(--theme);background:#eef2ff}
.nav-link.active{color:var(--theme);font-weight:600;border-left-color:var(--theme);background:#eef2ff}

/* ── Lang switch ────────────────────── */
.lang-switch{
  display:flex;align-items:center;gap:6px;padding:8px 16px;margin:8px 12px;
  border:1px solid var(--border);border-radius:6px;background:#fff;
  cursor:pointer;font-size:.8rem;font-weight:600;color:var(--muted);
  text-decoration:none;transition:all .15s
}
.lang-switch:hover{background:#eef2ff;border-color:var(--theme);color:var(--theme)}

/* ── Main ────────────────────────────── */
.main{margin-left:var(--sidebar-w);flex:1;min-height:100vh}
.markdown-section{max-width:880px;margin:0 auto;padding:48px 40px 80px}

/* ── Mobile toggle ───────────────────── */
.menu-toggle{
  display:none;position:fixed;top:12px;left:12px;z-index:200;
  background:var(--theme);color:#fff;border:none;border-radius:6px;
  width:36px;height:36px;font-size:1.1rem;cursor:pointer;
  align-items:center;justify-content:center
}

/* ── Typography ──────────────────────── */
.markdown-section h1{font-size:2rem;border-bottom:2px solid var(--theme);padding-bottom:12px;margin:0 0 28px}
.markdown-section h2{font-size:1.45rem;margin:40px 0 14px;padding-bottom:6px;border-bottom:1px solid var(--border)}
.markdown-section h3{font-size:1.15rem;margin:28px 0 10px}
.markdown-section h4{font-size:1rem;margin:20px 0 8px;color:var(--muted)}
.markdown-section p{line-height:1.8;margin:0 0 14px}
.markdown-section ul,.markdown-section ol{padding-left:24px;line-height:1.8;margin:0 0 14px}
.markdown-section li{margin:3px 0}
.markdown-section a{color:var(--theme);text-decoration:none}
.markdown-section a:hover{text-decoration:underline}
.markdown-section blockquote{
  margin:16px 0;padding:12px 20px;background:#eff6ff;
  border-left:4px solid var(--theme);border-radius:0 6px 6px 0;color:#374151
}
.markdown-section blockquote p{margin:0}
.markdown-section hr{border:none;border-top:1px solid var(--border);margin:32px 0}
.markdown-section img{max-width:100%;border-radius:8px;border:1px solid var(--border)}

/* ── Inline code ─────────────────────── */
.markdown-section code{
  font-family:var(--mono);font-size:.875em;background:#f1f5f9;
  color:#be123c;padding:2px 6px;border-radius:4px
}

/* ── Code blocks ─────────────────────── */
.markdown-section .highlight{
  background:#f8fafc;border:1px solid var(--border);border-radius:8px;
  overflow:auto;margin:16px 0
}
.markdown-section .highlight pre{
  margin:0;padding:16px 20px;font-family:var(--mono);
  font-size:.875rem;line-height:1.6;overflow-x:auto
}
.markdown-section .highlight code{background:none;color:inherit;padding:0;border-radius:0}

/* ── Tables ──────────────────────────── */
.markdown-section table{
  width:100%;border-collapse:collapse;margin:16px 0;font-size:.9rem;
  border:1px solid var(--border);border-radius:8px;overflow:hidden
}
.markdown-section th{
  background:#eff6ff;color:#1e40af;font-weight:600;
  padding:10px 16px;text-align:left;border-bottom:2px solid #bfdbfe
}
.markdown-section td{padding:10px 16px;border-bottom:1px solid var(--border)}
.markdown-section tr:last-child td{border-bottom:none}
.markdown-section tr:nth-child(even) td{background:#f9fafb}

/* ── Mermaid ─────────────────────────── */
.mermaid{text-align:center;margin:24px 0;overflow-x:auto}
.mermaid svg{max-width:100%}

/* ── Mobile ──────────────────────────── */
@media(max-width:768px){
  .menu-toggle{display:flex}
  .sidebar{transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0);box-shadow:4px 0 20px rgba(0,0,0,.15)}
  .main{margin-left:0}
  .markdown-section{padding:56px 18px 48px}
}
"""


def get_style() -> str:
    pygments_css = HtmlFormatter(style="friendly").get_style_defs(".highlight")
    return MAIN_CSS + "\n" + pygments_css


# ─── HTML 템플릿 ───────────────────────────────────────────
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
{style}
  </style>
</head>
<body>
  <button class="menu-toggle" onclick="toggleSidebar()" title="{menu_label}">&#9776;</button>
  <nav class="sidebar" id="sidebar">
    <a class="sidebar-header" href="{prefix}index.html">
      <img src="{prefix}images/favicon-96x96.png" alt="logo"
           onerror="this.style.display='none'">
      <span>ClooSphere</span>
    </a>
    <div class="sidebar-nav">
      <a class="lang-switch" href="{other_lang_prefix}index.html">{lang_switch_label}</a>
{sidebar}
    </div>
  </nav>
  <div class="main" id="main">
    <article class="markdown-section">
{content}
    </article>
  </div>
  <script src="{prefix}assets/mermaid.min.js"></script>
  <script>
    mermaid.initialize({{ startOnLoad: true, theme: 'default', securityLevel: 'loose' }});
    function toggleSidebar() {{
      document.getElementById('sidebar').classList.toggle('open');
    }}
    document.getElementById('main').addEventListener('click', function() {{
      if (window.innerWidth <= 768)
        document.getElementById('sidebar').classList.remove('open');
    }});
  </script>
</body>
</html>
"""


# ─── 사이드바 파서 ─────────────────────────────────────────
def parse_sidebar(lang_dir: Path) -> list[dict]:
    """_sidebar.md → [{type, text, url}] 파싱."""
    path = lang_dir / "_sidebar.md"
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # 섹션 헤더: "- **텍스트**"
        m = re.match(r"^-\s+\*\*(.+?)\*\*$", stripped)
        if m:
            items.append({"type": "section", "text": m.group(1)})
            continue
        # 링크: "  - [텍스트](url)"
        m = re.match(r"^\s*-\s+\[(.+?)\]\((.+?)\)$", line)
        if m:
            text, url = m.group(1), m.group(2)
            url = "index.html" if url == "/" else url.replace(".md", ".html")
            items.append({"type": "link", "text": text, "url": url})
    return items


def render_sidebar(items: list[dict], current_html: str) -> str:
    """현재 파일 기준 상대 경로 사이드바 HTML 생성."""
    depth = current_html.count("/")
    prefix = "../" * depth
    parts: list[str] = []
    for item in items:
        if item["type"] == "section":
            parts.append(f'      <div class="nav-section">{item["text"]}</div>')
        else:
            href = prefix + item["url"]
            active = " active" if item["url"] == current_html else ""
            parts.append(
                f'      <a href="{href}" class="nav-link{active}">{item["text"]}</a>'
            )
    return "\n".join(parts)


# ─── 마크다운 변환 ─────────────────────────────────────────
def preprocess_mermaid(text: str) -> str:
    """mermaid 코드 블록 → <div class="mermaid"> 변환."""
    return re.sub(
        r"```mermaid\n(.*?)\n```",
        lambda m: f'\n<div class="mermaid">\n{m.group(1)}\n</div>\n',
        text,
        flags=re.DOTALL,
    )


def fix_links(html: str, current_html: str) -> str:
    """.md → .html, 루트 링크 수정."""
    depth = current_html.count("/")

    def repl(m: re.Match) -> str:
        href = m.group(1)
        # .md 확장자 → .html
        href = re.sub(r"\.md(#[^\"]*)?$", lambda x: ".html" + (x.group(1) or ""), href)
        # 루트 링크 "/"
        if href == "/":
            href = "../" * depth + "index.html"
        return f'href="{href}"'

    return re.sub(r'href="([^"]*?)"', repl, html)


def fix_images(html: str, current_html: str) -> str:
    """이미지 경로를 현재 파일 깊이 기준으로 수정. lang 폴더에서 상위 images/ 참조."""
    depth = current_html.count("/")
    # lang 폴더(ko/ or en/) 기준이므로 한 단계 더 올라가야 함
    up = "../" * (depth + 1)

    def repl(m: re.Match) -> str:
        src = m.group(1)
        if src.startswith("/guide/images/"):
            # 절대경로 /guide/images/ → 빌드 출력의 상위 images/ (상대경로로 변환)
            src = up + "images/" + src[len("/guide/images/") :]
        elif src.startswith("../images/"):
            # legacy: ko/ 파일의 ../images/ → 빌드 출력의 상위 images/
            src = up + "images/" + src[len("../images/") :]
        elif src.startswith("./images/"):
            src = up + "images/" + src[len("./images/") :]
        elif src.startswith("images/") and not src.startswith("http"):
            src = up + src
        return f'src="{src}"'

    return re.sub(r'src="([^"]*?)"', repl, html)


def convert_md(md_text: str, current_html: str) -> str:
    """Markdown → HTML (mermaid, 링크, 이미지 처리 포함)."""
    md_text = preprocess_mermaid(md_text)
    md = markdown.Markdown(
        extensions=[
            FencedCodeExtension(),
            CodeHiliteExtension(guess_lang=False, css_class="highlight"),
            TableExtension(),
            "markdown.extensions.sane_lists",
        ]
    )
    html = md.convert(md_text)
    html = fix_links(html, current_html)
    html = fix_images(html, current_html)
    return html


# ─── 페이지 렌더 ───────────────────────────────────────────
def extract_title(html: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def render_page(
    content: str,
    sidebar: str,
    current_html: str,
    style: str,
    lang: str,
) -> str:
    cfg = LANG_CONFIG[lang]
    site_name = cfg["site_name"]
    menu_label = cfg["menu_label"]
    depth = current_html.count("/")
    prefix = "../" * (depth + 1)
    page_title = extract_title(content)
    full_title = f"{page_title} | {site_name}" if page_title else site_name

    other_lang = "en" if lang == "ko" else "ko"
    other_lang_prefix = prefix + other_lang + "/"
    lang_switch_label = "🌐 English" if lang == "ko" else "🌐 한국어"

    return HTML_TEMPLATE.format(
        lang=lang,
        title=full_title,
        style=style,
        sidebar=sidebar,
        content=content,
        prefix=prefix,
        menu_label=menu_label,
        other_lang_prefix=other_lang_prefix,
        lang_switch_label=lang_switch_label,
    )


# ─── 빌드 ─────────────────────────────────────────────────
def sidebar_url_to_md(url: str) -> str:
    if url == "index.html":
        return "README.md"
    return url.replace(".html", ".md")


def build_lang(lang: str, style: str) -> int:
    """단일 언어 빌드. 처리된 파일 수 반환."""
    lang_dir = GUIDE_DIR / lang
    lang_output = OUTPUT_DIR / lang

    if not lang_dir.exists():
        print(f"  ⏭️  {lang}/ 디렉토리 없음, 건너뜀")
        return 0

    lang_output.mkdir(parents=True, exist_ok=True)
    (lang_output / "workspace").mkdir(exist_ok=True)
    (lang_output / "admin").mkdir(exist_ok=True)

    sidebar_items = parse_sidebar(lang_dir)

    processed = 0
    for item in sidebar_items:
        if item["type"] != "link":
            continue

        html_rel = item["url"]
        md_rel = sidebar_url_to_md(html_rel)
        md_path = lang_dir / md_rel
        html_path = lang_output / html_rel

        if not md_path.exists():
            print(f"  ⏭️  건너뜀 (파일 없음): {lang}/{md_rel}")
            continue

        md_text = md_path.read_text(encoding="utf-8")
        content_html = convert_md(md_text, html_rel)
        sidebar_html = render_sidebar(sidebar_items, html_rel)
        page_html = render_page(content_html, sidebar_html, html_rel, style, lang)

        html_path.write_text(page_html, encoding="utf-8")
        print(f"  ✓ {lang}/{html_rel}")
        processed += 1

    return processed


def build() -> None:
    print(f"📁 출력 경로: {OUTPUT_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "assets").mkdir(exist_ok=True)

    # 이미지 복사 (공유)
    img_src = GUIDE_DIR / "images"
    img_dst = OUTPUT_DIR / "images"
    if img_src.exists():
        shutil.copytree(img_src, img_dst, dirs_exist_ok=True)
        count = len(list(img_src.rglob("*.*")))
        print(f"🖼️  이미지 복사: {count}개")

    # mermaid.min.js 다운로드
    mermaid_path = OUTPUT_DIR / "assets" / "mermaid.min.js"
    if not mermaid_path.exists():
        print("⬇️  mermaid.min.js 다운로드 중...", end="", flush=True)
        try:
            urllib.request.urlretrieve(MERMAID_URL, mermaid_path)
            size_kb = mermaid_path.stat().st_size // 1024
            print(f" 완료 ({size_kb}KB)")
        except Exception as e:
            print(f" 실패 ({e})\n   ⚠️  다이어그램이 표시되지 않을 수 있습니다.")
            mermaid_path.write_text("/* mermaid.min.js 다운로드 실패 */")
    else:
        print("✅ mermaid.min.js 이미 존재")

    style = get_style()
    total = 0

    for lang in LANG_CONFIG:
        print(f"\n🌐 [{lang.upper()}] 빌드 시작...")
        count = build_lang(lang, style)
        total += count
        print(f"  → {count}개 파일 처리")

    print(f"\n✅ 완료! 총 {total}개 HTML 파일 생성됨")
    print(f"   한국어: {OUTPUT_DIR / 'ko' / 'index.html'}")
    print(f"   English: {OUTPUT_DIR / 'en' / 'index.html'}")


if __name__ == "__main__":
    build()
