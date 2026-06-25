#!/usr/bin/env python3
"""기존 PPTX 를 Presenton 커스텀 템플릿으로 등록 (디자인/톤 추출 자동화).

업로드 → 슬라이드 프리뷰 → init → 슬라이드별 레이아웃 추출(vision-LLM) → 저장 전 과정을
한 번에 수행한다. 결과로 'custom-<id>' 를 출력 — Cloosphere 의 create_presentation 도구에서
template 값(또는 템플릿 이름)으로 쓰면 그 덱의 톤앤매너로 새 자료가 생성된다.

전제: docker-compose 의 prompts.py 패치가 적용돼 있어야 추출 레이아웃이 자동으로
      (고정높이 대신 min-h + 인라인 마크다운 볼드) 정상화된다. (services/Presenton/README.md)

사용 예:
  python register_template.py --pptx "회사덱.pptx" --name "회사 표준" --indices 0,2,5
  # 표지(0) + 본문 카드(2) + 다른 본문(5) 슬라이드를 레이아웃으로 추출

옵션:
  --indices  레이아웃으로 만들 슬라이드 인덱스(0-based, 쉼표구분). 적을수록 빠름.
             슬라이드당 vision-LLM ~60-90s 소요. 다양한 본문 타입을 2~5개 고르면 충분.
  --url      Presenton base URL (기본: 환경변수 PRESENTON_BASE_URL 또는 http://localhost:5001)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import uuid


def _post_json(url: str, body: dict, timeout: float = 600.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())


def _upload_pptx(base: str, pptx_path: str) -> dict:
    """multipart/form-data 로 pptx 업로드 → 프리뷰 이미지 + 폰트."""
    boundary = "----presenton" + uuid.uuid4().hex
    fname = os.path.basename(pptx_path)
    with open(pptx_path, "rb") as f:
        file_data = f.read()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="pptx_file"; '
                f'filename="{fname}"\r\n'
            ).encode(),
            b"Content-Type: application/vnd.openxmlformats-officedocument."
            b"presentationml.presentation\r\n\r\n",
            file_data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        f"{base}/api/v1/ppt/template/fonts-upload-and-slides-preview",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=600).read().decode())


def _extract(pattern: str, text: str, default: str) -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else default


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Register a PPTX as a Presenton custom template"
    )
    ap.add_argument("--pptx", required=True, help="소스 .pptx 경로")
    ap.add_argument("--name", required=True, help="템플릿 이름")
    ap.add_argument(
        "--indices", default="0,1,2", help="레이아웃화할 슬라이드 인덱스(0-based, 쉼표)"
    )
    ap.add_argument(
        "--url",
        default=os.environ.get("PRESENTON_BASE_URL", "http://localhost:5001"),
        help="Presenton base URL",
    )
    args = ap.parse_args()
    base = args.url.rstrip("/")
    indices = [int(x) for x in args.indices.split(",") if x.strip()]

    if not os.path.isfile(args.pptx):
        sys.exit(f"파일 없음: {args.pptx}")

    print(f"[1/4] 업로드 + 프리뷰: {args.pptx}")
    prev = _upload_pptx(base, args.pptx)
    n = len(prev.get("slide_image_urls", []))
    print(f"      슬라이드 {n}장 · 폰트 {list((prev.get('fonts') or {}).keys())}")
    indices = [i for i in indices if 0 <= i < n]
    if not indices:
        sys.exit("유효한 슬라이드 인덱스가 없습니다.")

    print("[2/4] init (pptx → HTML)")
    tcid = str(
        _post_json(
            f"{base}/api/v1/ppt/template/create/init",
            {
                "slide_image_urls": prev["slide_image_urls"],
                "pptx_url": prev["pptx_url"],
                "fonts": prev.get("fonts"),
            },
            timeout=300,
        )
    ).strip('"')

    print(f"[3/4] 레이아웃 추출 (인덱스 {indices}) — 슬라이드당 ~60-90s")
    layouts = []
    for idx in indices:
        t0 = time.time()
        rc = _post_json(
            f"{base}/api/v1/ppt/template/slide-layout/create",
            {"id": tcid, "index": idx},
            timeout=300,
        ).get("react_component", "")
        lid = _extract(r'const layoutId\s*=\s*"([^"]+)"', rc, f"layout-{idx}")
        lname = _extract(r'const layoutName\s*=\s*"([^"]+)"', rc, f"Layout {idx}")
        layouts.append({"layout_id": lid, "layout_name": lname, "layout_code": rc})
        print(f"      index {idx}: {lname}  ({time.time() - t0:.0f}s)")

    print("[4/4] 템플릿 저장")
    res = _post_json(
        f"{base}/api/v1/ppt/template/save",
        {
            "template_info_id": tcid,
            "name": args.name,
            "description": f"Extracted from {os.path.basename(args.pptx)}",
            "layouts": layouts,
        },
        timeout=120,
    )
    tid = res.get("id")
    print(f"\n✅ 완료 — 템플릿 '{args.name}' 등록됨")
    print("   Cloosphere create_presentation 의 template 값으로 사용:")
    print(f"     custom-{tid}")
    print(f"   또는 도구에서 템플릿 이름 '{args.name}' 으로 지정해도 자동 매핑됩니다.")


if __name__ == "__main__":
    main()
