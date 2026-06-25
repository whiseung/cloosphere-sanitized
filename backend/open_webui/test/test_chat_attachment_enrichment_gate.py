"""채팅 첨부 파일이 LLM enrichment(contextual chunking + 질의예시)를 건너뛰는지 검증.

배경: contextual chunking / 질의예시 생성은 청크마다 chat LLM 을 fan-out 호출하는
무거운 enrichment 다. 큐레이션된 KB 인제스트용 기능인데, 휘발성 채팅 첨부
(``file-{id}`` 임시 컬렉션)에까지 동기 처리 경로(``upload_file`` → ``process_file``)
로 적용되면서 Azure 429 storm + 2~4분 동기 업로드 → 프론트/프록시 타임아웃 →
채팅창에서 파일 소실을 유발했다.

``save_docs_to_vector_db(enable_enrichment=...)`` 게이트의 의사결정 규칙
(``_collection_is_persistent_kb``)을 핀으로 고정한다: 실제 KB 컬렉션만
enrichment 비용(청크당 chat 호출)을 지불하고, 채팅/임시 첨부는 embed-only 로
빠르게 처리되어 동기 업로드가 타임아웃 없이 끝나야 한다.

채팅 임시 컬렉션 네이밍 규칙(``file-{file_id}``)은 라우터 전반(``process_file`` 의
``_sync_knowledge_id`` 계산, KB chunk 정리 분기 등)에서 이미 "실제 KB vs 휘발성
첨부"를 가르는 데 쓰는 기존 컨벤션이며, helper 는 이를 형식화한 것이다.
"""

from open_webui.routers.retrieval import _collection_is_persistent_kb


def test_chat_attachment_no_collection_is_ephemeral():
    # 채팅 첨부: collection_name 미지정 → process_file 이 file-{id} 로 처리 → enrichment 금지
    assert _collection_is_persistent_kb(None) is False


def test_empty_collection_is_ephemeral():
    assert _collection_is_persistent_kb("") is False


def test_file_prefixed_collection_is_ephemeral():
    # 채팅 첨부 임시 컬렉션은 항상 f"file-{file.id}" 형태
    assert (
        _collection_is_persistent_kb("file-4c2ebac1-dc23-4058-b6a9-cdaac71532bd")
        is False
    )


def test_real_knowledge_base_is_persistent():
    # 워크스페이스 KB 인제스트 → 실제 knowledge_id(UUID) → enrichment 허용
    assert _collection_is_persistent_kb("a1b2c3d4-1234-5678-9abc-def012345678") is True


def test_knowledge_id_not_starting_with_file_is_persistent():
    assert _collection_is_persistent_kb("kb-shipping-terms") is True


def test_substring_file_not_prefix_is_persistent():
    # 'file' 이 접두가 아니라 중간/끝에 있으면 KB 로 취급 (접두 매칭만)
    assert _collection_is_persistent_kb("my-file-collection") is True
