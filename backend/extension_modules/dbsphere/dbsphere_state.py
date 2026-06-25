"""State definitions for DBSphere V2 agent."""

from enum import Enum
from typing import Any, Dict, List, Optional

from extension_modules.react.react_base import AgentStateBase
from pydantic import BaseModel, Field


class DBType(str, Enum):
    """Supported database types."""

    POSTGRES = "postgresql"
    MYSQL = "mysql"
    MSSQL = "mssql"
    SNOWFLAKE = "snowflake"
    ORACLE = "oracle"
    SQLITE = "sqlite"
    DATABRICKS = "databricks"
    SYNAPSE = "synapse"
    FABRIC = "fabric"
    BIGQUERY = "bigquery"


class DBConfig(BaseModel):
    """
    Database connection configuration.

    Compatible with DbSphere.data.connection structure from the database model.
    """

    db_type: str  # mysql, mssql, postgresql, snowflake, oracle, sqlite
    host: str
    port: int
    database: str
    username: str
    password: str
    # Optional fields for specific databases
    schema_name: Optional[str] = None
    warehouse: Optional[str] = None  # For Snowflake
    account: Optional[str] = None  # For Snowflake
    role: Optional[str] = None  # For Snowflake

    # Oracle specific
    service_name: Optional[str] = None  # For Oracle (alternative to database/SID)
    dsn: Optional[str] = None  # For Oracle (full DSN string)

    # Databricks specific
    http_path: Optional[str] = None  # For Databricks SQL warehouse
    catalog: Optional[str] = None  # For Databricks Unity Catalog
    access_token: Optional[str] = None  # For Databricks PAT

    # Azure AD authentication (Synapse, Fabric)
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    use_managed_identity: bool = False

    # BigQuery specific
    project_id: Optional[str] = None
    dataset_id: Optional[str] = None
    credentials_json: Optional[str] = None  # Service account JSON key
    use_adc: bool = (
        False  # BigQuery: use Application Default Credentials instead of a key
    )

    @classmethod
    def from_dbsphere_data(cls, data: Dict[str, Any]) -> "DBConfig":
        """
        Create DBConfig from DbSphere.data structure.

        Args:
            data: DbSphere.data dict containing 'connection' key

        Returns:
            DBConfig instance
        """
        connection = data.get("connection", {})
        return cls(
            db_type=connection.get("db_type", "postgresql").lower(),
            host=connection.get("host", "localhost"),
            port=int(connection.get("port", 5432)),
            database=connection.get("database", ""),
            username=connection.get("username", ""),
            password=connection.get("password", ""),
            schema_name=connection.get("schema_name"),
            warehouse=connection.get("warehouse"),
            account=connection.get("account"),
            role=connection.get("role"),
            # Oracle
            service_name=connection.get("service_name"),
            dsn=connection.get("dsn"),
            # Databricks
            http_path=connection.get("http_path"),
            catalog=connection.get("catalog"),
            access_token=connection.get("access_token"),
            # Azure AD
            tenant_id=connection.get("tenant_id"),
            client_id=connection.get("client_id"),
            client_secret=connection.get("client_secret"),
            use_managed_identity=connection.get("use_managed_identity", False),
            # BigQuery
            project_id=connection.get("project_id"),
            dataset_id=connection.get("dataset_id"),
            credentials_json=connection.get("credentials_json"),
            use_adc=connection.get("use_adc", False),
        )

    def get_db_type_enum(self) -> DBType:
        """Get DBType enum from string db_type."""
        type_map = {
            "mysql": DBType.MYSQL,
            "mssql": DBType.MSSQL,
            "postgresql": DBType.POSTGRES,
            "postgres": DBType.POSTGRES,
            "snowflake": DBType.SNOWFLAKE,
            "oracle": DBType.ORACLE,
            "sqlite": DBType.SQLITE,
            "databricks": DBType.DATABRICKS,
            "synapse": DBType.SYNAPSE,
            "fabric": DBType.FABRIC,
            "bigquery": DBType.BIGQUERY,
        }
        return type_map.get(self.db_type.lower(), DBType.POSTGRES)


class DBSphereAgentState(AgentStateBase):
    """
    Extended agent state for DBSphere V2.

    Inherits from AgentStateBase which includes:
    - messages: List of conversation messages
    - normalized_question: str
    - language: str
    - eval_score: int
    - eval_reason: str
    - answerable: bool
    - attached_files: List[str]

    DBSphere-specific fields:
    - executed_sql: The SQL query that was executed
    - query_result_file: Path to the CSV file containing query results
    - chart_data_list: Chart generation result data (list, supports multiple charts)
    - schema_info: Database schema information (DDL)
    - similar_queries: Similar queries from memory search
    """

    # SQL execution state
    executed_sql: str = ""
    query_result_file: str = ""

    # Chart generation state (accumulates across multiple visualize_data calls)
    chart_data_list: List[Dict[str, Any]] = Field(default_factory=list)

    # Context for SQL generation
    schema_info: str = ""
    similar_queries: List[Dict[str, Any]] = Field(default_factory=list)

    # Query history for this session (used for final response)
    query_history: List[str] = Field(default_factory=list)


class ChartResult(BaseModel):
    """Result from chart generation."""

    chart_result: Dict[str, Any]
    status: str  # "auto_success", "explicit_success", "fallback_auto", "error"
    requested_chart_type: str
    used_chart_type: str
    error_reason: Optional[str] = None
