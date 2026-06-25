"""Unit tests for snapshot-copy 기반 KB clone — vector / chunk metadata 변환,
Storage server-side copy interface contract.

Snapshot copy 모델 (commit 후속) 의 핵심 로직:
- ``SearchEngineKnowledge.copy_chunks_to`` 가 chunk 의 vector / content /
  secondary_vector 를 보존하고 id, collection, metadata.file_id 만 갱신
- ``Storage.copy_file`` 추상이 server-side (download/upload hop 없음) copy
  를 요구하는 contract

DB / 실제 vector engine 의존성 없이 변환 로직만 검증.
"""

import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# DocumentItem 인라인 사본 (extension_modules.search_engine.DocumentItem 의 핵심 필드)
# ---------------------------------------------------------------------------


@dataclass
class FakeDocumentItem:
    """Production ``DocumentItem`` 의 contract-relevant 필드만."""

    id: str
    content: str
    vector: List[float]
    collection: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    secondary_vector: Optional[List[float]] = None


def _transform_for_copy(
    docs: List[FakeDocumentItem],
    dst_collection: str,
    dst_file_id: str,
) -> List[FakeDocumentItem]:
    """``copy_chunks_to`` 의 핵심 변환 인라인 재현 — id 새로 발급, collection
    / metadata.file_id 새 값, vector 등 나머지는 보존."""
    import uuid

    new_docs = []
    for doc in docs:
        new_meta = dict(doc.metadata or {})
        new_meta["file_id"] = dst_file_id
        new_docs.append(
            FakeDocumentItem(
                id=str(uuid.uuid4()),
                content=doc.content,
                vector=doc.vector,
                collection=dst_collection,
                metadata=new_meta,
                secondary_vector=doc.secondary_vector,
            )
        )
    return new_docs


# ---------------------------------------------------------------------------
# vector / content / secondary_vector 보존 — 임베딩 재계산 0 의 핵심
# ---------------------------------------------------------------------------


def test_copy_preserves_vector():
    """벡터 그대로 복제 — bit-identical (재계산 X)."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="chunk text 1",
            vector=[0.1, 0.2, 0.3],
            collection="src-kb",
            metadata={"file_id": "src-f"},
        )
    ]
    out = _transform_for_copy(src, "dst-kb", "dst-f")
    assert out[0].vector == [0.1, 0.2, 0.3]
    assert out[0].vector is src[0].vector or out[0].vector == src[0].vector


def test_copy_preserves_content():
    """content (chunk 텍스트) 도 그대로."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="원본 청크 내용",
            vector=[0.0],
            collection="src",
            metadata={},
        )
    ]
    out = _transform_for_copy(src, "dst", "dst-f")
    assert out[0].content == "원본 청크 내용"


def test_copy_preserves_secondary_vector():
    """multi-vector 검색용 secondary_vector (sample question 임베딩) 도 보존."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="x",
            vector=[0.1],
            collection="src",
            metadata={},
            secondary_vector=[0.9, 0.8],
        )
    ]
    out = _transform_for_copy(src, "dst", "dst-f")
    assert out[0].secondary_vector == [0.9, 0.8]


def test_copy_handles_no_secondary_vector():
    """secondary_vector 가 None 인 일반 chunk 도 안전 처리."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="x",
            vector=[0.1],
            collection="src",
            metadata={},
            secondary_vector=None,
        )
    ]
    out = _transform_for_copy(src, "dst", "dst-f")
    assert out[0].secondary_vector is None


# ---------------------------------------------------------------------------
# id / collection / file_id 갱신 — 검색 분리 보장
# ---------------------------------------------------------------------------


def test_copy_assigns_new_ids():
    """id 는 항상 새 uuid — source chunk 와 1:1 매핑이지만 id 충돌 X."""
    src = [
        FakeDocumentItem(
            id=f"d{i}", content="x", vector=[0.0], collection="src", metadata={}
        )
        for i in range(3)
    ]
    out = _transform_for_copy(src, "dst", "dst-f")
    src_ids = {d.id for d in src}
    out_ids = {d.id for d in out}
    assert src_ids.isdisjoint(out_ids)  # 겹치는 id 없음
    assert len(out_ids) == 3  # 새 id 도 unique


def test_copy_sets_dst_collection():
    """collection 필드 → dst_collection (cloned KB 검색 분리 핵심)."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="x",
            vector=[0.0],
            collection="old-kb",
            metadata={"file_id": "src-f"},
        )
    ]
    out = _transform_for_copy(src, "new-kb", "new-f")
    assert out[0].collection == "new-kb"


def test_copy_sets_dst_file_id_in_metadata():
    """metadata.file_id 갱신 — 검색에서 file 단위 그루핑 가능."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="x",
            vector=[0.0],
            collection="src",
            metadata={"file_id": "src-f", "page": 1},
        )
    ]
    out = _transform_for_copy(src, "dst", "new-f")
    assert out[0].metadata["file_id"] == "new-f"
    # 다른 metadata 키는 보존
    assert out[0].metadata["page"] == 1


def test_copy_preserves_other_metadata():
    """sample_questions, hash, created_at 같은 부수 metadata 모두 보존."""
    src = [
        FakeDocumentItem(
            id="d1",
            content="x",
            vector=[0.0],
            collection="src",
            metadata={
                "file_id": "src-f",
                "sample_questions": "Q1\nQ2",
                "hash": "abc123",
                "created_at": "2026-01-01T00:00:00Z",
                "f_str_1": "팀A",  # filter slot 도 함께 복제
                "f_int_1": 2024,
            },
        )
    ]
    out = _transform_for_copy(src, "dst", "new-f")
    assert out[0].metadata["sample_questions"] == "Q1\nQ2"
    assert out[0].metadata["hash"] == "abc123"
    assert out[0].metadata["created_at"] == "2026-01-01T00:00:00Z"
    assert out[0].metadata["f_str_1"] == "팀A"
    assert out[0].metadata["f_int_1"] == 2024


def test_copy_does_not_mutate_source_metadata():
    """source metadata dict 가 수정되면 안 됨 (원본 chunk 의 file_id 보호)."""
    src_meta = {"file_id": "src-f", "page": 1}
    src = [
        FakeDocumentItem(
            id="d1", content="x", vector=[0.0], collection="src", metadata=src_meta
        )
    ]
    out = _transform_for_copy(src, "dst", "new-f")
    assert src_meta["file_id"] == "src-f"  # source 원본 보존
    assert out[0].metadata is not src_meta  # 새 dict


def test_copy_handles_empty_source():
    """source chunk 0개 → 빈 list 반환, 예외 없음."""
    out = _transform_for_copy([], "dst", "new-f")
    assert out == []


# ---------------------------------------------------------------------------
# Storage.copy_file (Local) — server-side 의 가장 간단한 구현 검증
# ---------------------------------------------------------------------------


def test_local_copy_file_creates_dst_with_same_content(tmp_path):
    """Local provider 의 copy_file 은 OS 레벨 copy — content 동일.

    Production ``LocalStorageProvider.copy_file`` 의 contract 인라인 재현.
    """
    src = tmp_path / "src.txt"
    src.write_bytes(b"original content")
    dst_dir = tmp_path / "uploads"
    dst_dir.mkdir()

    # Production 함수와 동일한 분기 — shutil.copy2.
    dst_filename = "dst.txt"
    dst_path = dst_dir / dst_filename
    shutil.copy2(str(src), str(dst_path))

    assert dst_path.exists()
    assert dst_path.read_bytes() == b"original content"
    # source 파일은 변경되지 않음 (copy, not move)
    assert src.read_bytes() == b"original content"


def test_local_copy_file_independent_after_copy(tmp_path):
    """copy 후 src/dst 가 독립적이어야 — 한쪽 수정 다른쪽 영향 X."""
    src = tmp_path / "src.txt"
    src.write_bytes(b"v1")
    dst = tmp_path / "dst.txt"
    shutil.copy2(str(src), str(dst))

    # dst 수정 → src 영향 없음
    dst.write_bytes(b"v2")
    assert src.read_bytes() == b"v1"
    assert dst.read_bytes() == b"v2"


def test_local_copy_file_raises_on_missing_source(tmp_path):
    """존재하지 않는 src 는 에러 — production 도 동일 동작."""
    import os

    src = str(tmp_path / "ghost.txt")
    dst_dir = tmp_path / "uploads"
    dst_dir.mkdir()
    dst = str(dst_dir / "dst.txt")

    raised = False
    try:
        shutil.copy2(src, dst)
    except (FileNotFoundError, OSError):
        raised = True
    assert raised
    assert not os.path.exists(dst)


# ---------------------------------------------------------------------------
# StorageProvider.copy_file ABC default fallback — get_file → upload_file hop
# ---------------------------------------------------------------------------


def test_abc_default_falls_back_to_get_then_upload(tmp_path):
    """ABC 기본 구현이 get_file 후 upload_file hop 으로 동작 (provider 가
    server-side copy 미구현 시 의미적으로는 동작) — contract 검증."""
    # Fake provider — get_file 은 src 그대로, upload_file 은 stem 에 prefix 붙여 저장.
    saved: dict = {}

    class FakeProv:
        def get_file(self, p):
            return p

        def upload_file(self, fh, name):
            data = fh.read()
            saved[name] = data
            return data, f"fake://{name}"

        # ABC default copy_file 인라인 재현
        def copy_file(self, src_path, dst_filename):
            local_path = self.get_file(src_path)
            with open(local_path, "rb") as fh:
                _, new_path = self.upload_file(fh, dst_filename)
            return new_path

    src = tmp_path / "x.txt"
    src.write_bytes(b"hello")
    p = FakeProv()
    new_path = p.copy_file(str(src), "y.txt")
    assert new_path == "fake://y.txt"
    assert saved["y.txt"] == b"hello"
