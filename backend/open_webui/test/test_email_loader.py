"""Unit tests for .eml/.msg 이메일 인제스트 (통합 문서 Loader).

검증 대상:
- .eml/.msg 가 UnstructuredEmailLoader 로 라우팅됨 — .msg 는 oxmsg 로 파싱되어
  extract_msg(미설치, bs4 핀과 충돌) 불필요. 원래 버그(extract_msg ImportError →
  업로드 에러)의 회귀 가드.
- process_attachments=False → 본문만 추출, 첨부 내용 미유출. (이전 기본 경로는
  .eml 을 TextLoader 로 raw MIME 덤프해 첨부를 노출했으므로 이 분기가 보안 개선.)
- 파싱 실패 시 in-loader 폴백을 두지 않는다 → 정상 전파(파일별 깨끗한 실패).
  TextLoader / 직접 MIME 파싱 폴백은 모두 첨부 유출·OLE mojibake 를 재유발하므로
  채택하지 않음. .msg 의 깨진 입력도 폴백 없이 전파(mojibake 미색인).
- 비-이메일(.pdf 등) 실패는 정상 전파.
- 한국어 본문 인코딩 round-trip.

커버리지 노트: .msg 성공(oxmsg 본문 추출) 경로는 라우팅 수준까지만 검증한다 —
순수 Python 으로 유효한 Outlook .msg(OLE/MAPI) 바이너리를 생성할 방법이 없어
(oxmsg 는 read-only) 실제 .msg fixture 가 필요하다. 성공 경로 e2e 는 실제
.msg 샘플로 수동 검증한다.
"""

import email.message
import email.policy

import pytest
from langchain_community.document_loaders import UnstructuredEmailLoader

from open_webui.retrieval.loaders import main as loader_main
from open_webui.retrieval.loaders.main import Loader


def _write_eml(path, body, *, charset="utf-8", attachment=None):
    msg = email.message.EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bob@example.com"
    msg["Subject"] = "Subject line"
    msg.set_content(body, charset=charset)
    if attachment is not None:
        msg.add_attachment(
            attachment.encode("utf-8"),
            maintype="text",
            subtype="plain",
            filename="note.txt",
        )
    path.write_bytes(msg.as_bytes(policy=email.policy.SMTP))
    return str(path)


def _text(docs):
    return "\n".join(d.page_content for d in docs)


# --------------------------------------------------------------------------- #
# 라우팅 (파일 I/O 없음 — _get_loader 는 로더만 생성)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,content_type",
    [("mail.msg", "application/octet-stream"), ("mail.eml", "message/rfc822")],
)
def test_email_exts_route_to_unstructured_email_loader(tmp_path, name, content_type):
    p = tmp_path / name
    p.write_bytes(b"\x00")  # _get_loader 는 내용을 읽지 않음 (lazy)
    loader = Loader()._get_loader(name, content_type, str(p))
    # .msg 가 OutlookMessageLoader(=extract_msg) 가 아니라 oxmsg 기반 경로로 감
    assert isinstance(loader, UnstructuredEmailLoader)
    # 첨부 파싱 비활성 강제 (본문만)
    assert loader.unstructured_kwargs.get("process_attachments") is False


# --------------------------------------------------------------------------- #
# 본문 추출 (성공 경로, end-to-end)
# --------------------------------------------------------------------------- #
def test_eml_plain_body_extracted(tmp_path):
    path = _write_eml(tmp_path / "m.eml", "Hello Bob, revenue grew 12% QoQ.")
    docs = Loader().load("m.eml", "message/rfc822", path)
    assert "revenue grew 12% QoQ" in _text(docs)


def test_eml_korean_body_roundtrips(tmp_path):
    path = _write_eml(
        tmp_path / "k.eml", "안녕하세요. 매출이 전분기 대비 12% 증가했습니다."
    )
    docs = Loader().load("k.eml", "message/rfc822", path)
    assert "매출이 전분기 대비 12% 증가" in _text(docs)


def test_eml_attachment_content_not_extracted(tmp_path):
    """본문만 색인되고 첨부 내용은 유출되지 않는다 (process_attachments=False)."""
    path = _write_eml(
        tmp_path / "a.eml",
        "Body visible text.",
        attachment="LEAKED_ATTACHMENT_CONTENT",
    )
    text = _text(Loader().load("a.eml", "message/rfc822", path))
    assert "Body visible text" in text
    assert "LEAKED_ATTACHMENT_CONTENT" not in text


# --------------------------------------------------------------------------- #
# 파싱 실패 — 폴백 없이 전파 (첨부 유출 / mojibake 재유발 방지)
# --------------------------------------------------------------------------- #
def test_eml_parse_failure_propagates_no_fallback(tmp_path, monkeypatch):
    """1차 파서가 실패해도 raw 폴백을 두지 않고 정상 전파한다.
    (TextLoader/직접 MIME 파싱 폴백은 첨부 base64·파일명을 KB 에 색인하는 유출을
    재유발하므로 채택하지 않음 — 회귀 가드.)"""
    path = _write_eml(
        tmp_path / "f.eml", "body", attachment="LEAKED_ATTACHMENT_CONTENT"
    )

    class FailingLoader:
        def __init__(self, *args, **kwargs):
            pass

        def load(self):
            raise RuntimeError("unstructured email parse blew up")

    monkeypatch.setattr(loader_main, "UnstructuredEmailLoader", FailingLoader)
    with pytest.raises(RuntimeError):
        Loader().load("f.eml", "message/rfc822", path)


def test_corrupt_msg_no_silent_mojibake(tmp_path):
    """깨진 .msg 는 폴백 없이 전파(또는 빈 결과) — non-empty mojibake 를
    조용히 색인하지 않는다 (OLE 바이너리를 raw 텍스트로 덤프하던 결함 방지)."""
    path = tmp_path / "corrupt.msg"
    path.write_bytes(b"\x00\x01 not a real outlook msg \xff\xfe garbage")
    try:
        docs = Loader().load("corrupt.msg", "application/octet-stream", str(path))
    except Exception:
        return  # 깨끗한 실패 — 허용 (garbage 미색인)
    # 예외가 없었다면 비어 있어야 한다 (non-empty mojibake 금지)
    assert all(not d.page_content.strip() for d in docs)


def test_non_email_failure_propagates(tmp_path, monkeypatch):
    """비-이메일(.pdf) 로더의 .load() 실패는 정상 전파한다
    (PDF/office 실패가 조용히 묻히지 않도록)."""

    class BoomLoader:
        def load(self):
            raise RuntimeError("pdf parse exploded")

    monkeypatch.setattr(Loader, "_get_loader", lambda self, *a, **k: BoomLoader())
    with pytest.raises(RuntimeError):
        Loader().load("doc.pdf", "application/pdf", str(tmp_path / "doc.pdf"))
