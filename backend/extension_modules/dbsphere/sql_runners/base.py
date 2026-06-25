"""Base SQL runner abstraction for DBSphere V2."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd
from extension_modules.dbsphere.dbsphere_state import DBConfig

# Schema/table names are SQL *identifiers*, not values — they flow into
# introspection queries (some via run_sql, which has no bind-parameter channel),
# so per OWASP we allow-list them rather than parameterize. The allow-list is
# Unicode-aware word characters plus "$" — so Korean/CJK table & column names
# (common in this product) are accepted — while quotes, whitespace, ";", "--",
# ".", "(", ... are rejected, blocking SQL injection through introspection.
_SQL_IDENTIFIER_RE = re.compile(r"[\w$]+", re.UNICODE)


def validate_sql_identifier(name: str, *, kind: str = "identifier") -> str:
    """Return ``name`` unchanged if it is a safe SQL identifier, else raise.

    Allows Unicode letters/digits, ``_`` and ``$`` (full-match, so an embedded
    newline is rejected too). Raises ValueError on anything else or a non-str.
    """
    if not isinstance(name, str) or not _SQL_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Invalid SQL {kind}: {name!r}")
    return name


@dataclass
class TableInfo:
    """Information about a database table."""

    table_name: str
    schema_name: Optional[str] = None
    table_type: str = "BASE TABLE"


@dataclass
class ColumnInfo:
    """Information about a database column."""

    column_name: str
    data_type: str
    is_nullable: bool = True
    column_default: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_table: Optional[str] = None
    foreign_column: Optional[str] = None


class SqlRunnerBase(ABC):
    """
    Abstract base class for SQL execution.

    All database-specific implementations should inherit from this class
    and implement the abstract methods.
    """

    # True 면 쿼리마다 독립 커넥션을 주는 연결 풀 기반(동시 호출 안전)이라 병렬
    # 추출 시 인스턴스를 공유해도 된다. False(기본)인 단일 커넥션 runner 는 동시
    # 접근이 깨지므로 task 마다 전용 인스턴스를 만들어야 한다.
    is_pool_based: bool = False

    def __init__(self, config: DBConfig):
        """
        Initialize the SQL runner with database configuration.

        Args:
            config: Database connection configuration

        Raises:
            ValueError: if the connection-supplied schema name is not a safe SQL
                identifier (blocks SQL injection through introspection queries).
        """
        self.config = config
        # The connection-supplied schema name flows into introspection queries
        # across every runner — allow-list it once here. Per-method table names
        # are validated at their call sites.
        if config.schema_name:
            validate_sql_identifier(config.schema_name, kind="schema")

    @abstractmethod
    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute a SQL query and return results as a DataFrame.

        Args:
            sql: The SQL query to execute

        Returns:
            pd.DataFrame: Query results as a pandas DataFrame

        Raises:
            Exception: If query execution fails
        """
        pass

    @abstractmethod
    async def get_schema_info(self) -> str:
        """
        Get database schema information as DDL statements.

        Returns:
            str: Schema information in DDL format
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Test the database connection.

        Returns:
            bool: True if connection is successful, False otherwise
        """
        pass

    def _get_connection_string(self) -> str:
        """
        Build connection string from config.

        Returns:
            str: Database connection string
        """
        pass

    # =========================================================================
    # New methods for schema extraction
    # =========================================================================

    async def get_all_tables(self) -> List[TableInfo]:
        """
        Get list of all tables in the database.

        Returns:
            List[TableInfo]: List of table information
        """
        raise NotImplementedError(
            "get_all_tables is not implemented for this database type"
        )

    async def get_table_ddl(self, table_name: str) -> str:
        """
        Get DDL statement for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            str: DDL CREATE TABLE statement
        """
        raise NotImplementedError(
            "get_table_ddl is not implemented for this database type"
        )

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """
        Get column information for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            List[ColumnInfo]: List of column information
        """
        raise NotImplementedError(
            "get_table_columns is not implemented for this database type"
        )

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """
        Get random sample rows from a table.

        Args:
            table_name: Name of the table
            limit: Number of rows to return

        Returns:
            pd.DataFrame: Sample data
        """
        raise NotImplementedError(
            "get_random_samples is not implemented for this database type"
        )

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get foreign key relationships.

        Args:
            table_name: Optional table name to filter by

        Returns:
            List of foreign key relationship dictionaries
        """
        raise NotImplementedError(
            "get_foreign_key_relationships is not implemented for this database type"
        )

    def apply_row_limit(self, sql: str, limit: int = 1) -> str:
        """Cap a query's result size using a dialect-appropriate row limit.

        Used when validating generated sample queries so validation does not
        pull large result sets. The base implementation targets LIMIT-capable
        dialects (PostgreSQL, MySQL, Snowflake, Databricks, BigQuery). Dialects
        without a LIMIT clause (Oracle, T-SQL family) override this method.
        """
        stripped = sql.strip().rstrip(";")
        if re.search(r"\blimit\b", stripped, re.IGNORECASE):
            return stripped
        return f"{stripped} LIMIT {limit}"
