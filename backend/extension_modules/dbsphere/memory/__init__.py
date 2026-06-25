"""Memory implementations for DBSphere V2."""

from extension_modules.dbsphere.memory.models import (
    ColumnDetail,
    DDLMemory,
    DDLMemorySearchResult,
    DocumentationMemory,
    DocumentationSearchResult,
    DocumentationType,
    MemoryType,
    SqlExampleMemory,
    SqlExampleSearchResult,
    SqlMemory,
    SqlMemorySearchResult,
    TableDetails,
    UnifiedSearchResult,
)
from extension_modules.dbsphere.memory.schema_extractor import (
    SampleQA,
    SchemaExtractor,
    create_schema_extractor,
    create_schema_extractor_with_config,
)
from extension_modules.dbsphere.memory.search_memory import (
    SearchEngineDbSphereMemory,
    SearchEngineSqlMemory,  # Backward compatibility alias
    create_dbsphere_memory_index_config,
    create_sql_memory_config,
)

__all__ = [
    # Memory Service
    "SearchEngineDbSphereMemory",
    "SearchEngineSqlMemory",  # Backward compatibility alias
    "create_dbsphere_memory_index_config",
    "create_sql_memory_config",
    # Memory Types
    "MemoryType",
    "DocumentationType",
    # SQL Memory
    "SqlMemory",
    "SqlMemorySearchResult",
    # DDL Memory
    "DDLMemory",
    "DDLMemorySearchResult",
    "ColumnDetail",
    "TableDetails",
    # Documentation Memory
    "DocumentationMemory",
    "DocumentationSearchResult",
    # SQL Example Memory
    "SqlExampleMemory",
    "SqlExampleSearchResult",
    # Unified Search
    "UnifiedSearchResult",
    # Schema Extractor
    "SchemaExtractor",
    "SampleQA",
    "create_schema_extractor",
    "create_schema_extractor_with_config",
]
