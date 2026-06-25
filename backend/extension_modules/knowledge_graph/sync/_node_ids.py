"""KG Phase 2 계층 노드 ID 헬퍼.

기존 term/concept/table/column ID 는 각 sync 모듈 안에 있는 로컬 헬퍼를 그대로
쓴다. 이 파일은 컨테이너 / 문서 / 문서유형 노드 ID 를 두 군데 이상에서
참조하므로 공용 모듈로 분리한다.

ID 패턴은 기존 make_node_id 관례를 따른다:
    {kg_id}__{source_kind}__{resource_id}__{node_kind}[__{leaf_id}]
"""

from open_webui.models.knowledge_graph import make_node_id


def database_node_id(kg_id: str, dbsphere_id: str) -> str:
    """DbSphere 인스턴스 컨테이너 노드 ID."""
    return make_node_id(kg_id, "dbsphere", dbsphere_id, "database")


def glossary_container_node_id(kg_id: str, glossary_id: str) -> str:
    """Glossary 인스턴스 컨테이너 노드 ID."""
    return make_node_id(kg_id, "glossary", glossary_id, "glossary")


def knowledge_base_node_id(kg_id: str, knowledge_id: str) -> str:
    """KnowledgeBase 인스턴스 컨테이너 노드 ID."""
    return make_node_id(kg_id, "kb", knowledge_id, "kb")


def document_node_id(kg_id: str, knowledge_id: str, file_id: str) -> str:
    """KB 파일(문서) 노드 ID."""
    return make_node_id(kg_id, "kb", knowledge_id, "doc", file_id)
