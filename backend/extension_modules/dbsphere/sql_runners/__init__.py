"""SQL Runner implementations for different database types.

`RUNNER_REGISTRY` is the single source of truth mapping each `DBType` to its
runner class AND its prompt dialect name. DBSphereAgent, DashboardBuilder and
UnifiedAgent all delegate here via `create_sql_runner()` / `get_dialect_name()`
instead of keeping their own copies — adding a new DB type means editing this
one map. Binding runner + dialect in a single entry makes it structurally
impossible for them to drift apart (the bug that left BigQuery with a runner
but no dialect rules across the duplicated copies).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Optional

from extension_modules.dbsphere.dbsphere_state import DBType
from extension_modules.dbsphere.sql_runners.base import SqlRunnerBase
from extension_modules.dbsphere.sql_runners.bigquery import BigQueryRunner
from extension_modules.dbsphere.sql_runners.databricks import DatabricksRunner
from extension_modules.dbsphere.sql_runners.fabric import FabricRunner
from extension_modules.dbsphere.sql_runners.mssql import MSSQLRunner
from extension_modules.dbsphere.sql_runners.mysql import MySQLRunner
from extension_modules.dbsphere.sql_runners.oracle import OracleRunner
from extension_modules.dbsphere.sql_runners.postgres import PostgresRunner
from extension_modules.dbsphere.sql_runners.snowflake import SnowflakeRunner
from extension_modules.dbsphere.sql_runners.synapse import SynapseRunner

if TYPE_CHECKING:
    from extension_modules.dbsphere.dbsphere_state import DBConfig

__all__ = [
    "SqlRunnerBase",
    "PostgresRunner",
    "MySQLRunner",
    "MSSQLRunner",
    "OracleRunner",
    "SnowflakeRunner",
    "DatabricksRunner",
    "SynapseRunner",
    "FabricRunner",
    "BigQueryRunner",
    "RunnerRegistryEntry",
    "RUNNER_REGISTRY",
    "create_sql_runner",
    "get_dialect_name",
]


@dataclass(frozen=True)
class RunnerRegistryEntry:
    """Canonical binding of a DBType to its runner and prompt dialect.

    Attributes:
        runner_cls: SQL runner class, or None for a DBType that is recognised
            (and may have dialect rules) but has no runner implementation
            (e.g. SQLite).
        dialect_name: Human-readable dialect name fed to
            ``prompts._build_dialect_rules()``, which substring-matches it
            case-insensitively to select the dialect-specific rule block.
    """

    runner_cls: Optional[type[SqlRunnerBase]]
    dialect_name: str


# Single source of truth. Add a new DB type HERE ONLY.
_RUNNER_REGISTRY: dict[DBType, RunnerRegistryEntry] = {
    DBType.POSTGRES: RunnerRegistryEntry(PostgresRunner, "PostgreSQL"),
    DBType.MYSQL: RunnerRegistryEntry(MySQLRunner, "MySQL"),
    DBType.MSSQL: RunnerRegistryEntry(MSSQLRunner, "Microsoft SQL Server"),
    DBType.ORACLE: RunnerRegistryEntry(OracleRunner, "Oracle"),
    DBType.SNOWFLAKE: RunnerRegistryEntry(SnowflakeRunner, "Snowflake"),
    DBType.DATABRICKS: RunnerRegistryEntry(DatabricksRunner, "Databricks SQL"),
    DBType.SYNAPSE: RunnerRegistryEntry(SynapseRunner, "Azure Synapse Analytics"),
    DBType.FABRIC: RunnerRegistryEntry(FabricRunner, "Microsoft Fabric"),
    DBType.BIGQUERY: RunnerRegistryEntry(BigQueryRunner, "BigQuery"),
    # In the enum + has a dialect block in prompts.py, but no runner impl.
    DBType.SQLITE: RunnerRegistryEntry(None, "SQLite"),
}

# Read-only view: entries are frozen and the container is sealed, so the single
# source of truth cannot be mutated at runtime (multi-worker hygiene).
RUNNER_REGISTRY: Mapping[DBType, RunnerRegistryEntry] = MappingProxyType(
    _RUNNER_REGISTRY
)


def create_sql_runner(db_config: "DBConfig") -> Optional[SqlRunnerBase]:
    """DBConfig로부터 적합한 SQL runner를 생성하는 팩토리 (단일 진실원).

    새 DB 타입 추가 시 ``RUNNER_REGISTRY`` 한 곳만 수정하면 DBSphereAgent ·
    DashboardBuilder · UnifiedAgent · KGToolManager 전부에 반영된다.
    """
    entry = RUNNER_REGISTRY.get(db_config.get_db_type_enum())
    if entry is None or entry.runner_cls is None:
        return None
    return entry.runner_cls(db_config)


def get_dialect_name(db_type: DBType) -> str:
    """DBType → 프롬프트용 dialect 이름 (``prompts._build_dialect_rules`` 매칭).

    알 수 없는 타입은 generic ``"SQL"`` 로 폴백한다.
    """
    entry = RUNNER_REGISTRY.get(db_type)
    return entry.dialect_name if entry else "SQL"
