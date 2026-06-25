"""Knowledge Graph extension module.

Phase 0 슬라이스 — Glossary 동기화 + 기본 그래프 트래버설.

향후 슬라이스에서 추가될 것:
- DbSphere 스키마 동기화 (sync/dbsphere_sync.py)
- KB 문서 LLM 추출 (sync/kb_extract.py)
- LLM 도구 노출 (tools.py)
- 임베딩 기반 시맨틱 검색 (embedding.py)
"""

from extension_modules.knowledge_graph.index_service import KGNodeIndexService
from extension_modules.knowledge_graph.service import KGService
from extension_modules.knowledge_graph.sync.dbsphere_sync import sync_dbsphere_to_kg
from extension_modules.knowledge_graph.sync.glossary_sync import sync_glossary_to_kg
from extension_modules.knowledge_graph.sync.kb_sync import sync_kb_to_kg
from extension_modules.knowledge_graph.tools import KGToolManager

__all__ = [
    "KGNodeIndexService",
    "KGService",
    "KGToolManager",
    "sync_dbsphere_to_kg",
    "sync_glossary_to_kg",
    "sync_kb_to_kg",
]
