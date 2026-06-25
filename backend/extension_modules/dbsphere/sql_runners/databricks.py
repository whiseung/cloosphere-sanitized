"""Databricks SQL runner implementation for DBSphere V2."""

import asyncio
import logging
from typing import Dict, List, Optional

import pandas as pd
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.base import (
    ColumnInfo,
    SqlRunnerBase,
    TableInfo,
)

logger = logging.getLogger(__name__)


class DatabricksRunner(SqlRunnerBase):
    """Databricks implementation of SqlRunnerBase using databricks-sql-connector."""

    def __init__(self, config: DBConfig):
        """
        Initialize Databricks runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)
        self._connection = None

    def _catalog_prefix(self) -> str:
        """Return 'catalog.' prefix if catalog is set, empty string otherwise."""
        return f"{self.config.catalog}." if self.config.catalog else ""

    def _schema_name(self) -> str:
        """Return schema name, defaulting to 'default'."""
        return self.config.schema_name or "default"

    def _full_table_name(self, table_name: str) -> str:
        """Return fully qualified table name."""
        prefix = self._catalog_prefix()
        return f"{prefix}{self._schema_name()}.{table_name}"

    def _schema_path(self) -> str:
        """Return catalog.schema or just schema path."""
        prefix = self._catalog_prefix()
        return f"{prefix}{self._schema_name()}"

    def _get_connection_sync(self):
        """Get or create synchronous connection."""
        if self._connection is None:
            try:
                from databricks import sql
            except ImportError:
                raise ImportError(
                    "databricks-sql-connector is required for Databricks support. "
                    "Install with: pip install databricks-sql-connector"
                )

            conn_params = {
                "server_hostname": self.config.host,
                "http_path": self.config.http_path,
                "access_token": self.config.access_token,
            }
            if self.config.catalog:
                conn_params["catalog"] = self.config.catalog
            if self.config.schema_name:
                conn_params["schema"] = self.config.schema_name

            self._connection = sql.connect(**conn_params)
        return self._connection

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against Databricks database.

        Args:
            sql: SQL query to execute

        Returns:
            pd.DataFrame: Query results
        """

        def _execute():
            conn = self._get_connection_sync()
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )
                rows = cursor.fetchall()

                if not rows:
                    return pd.DataFrame(columns=columns)

                return pd.DataFrame.from_records(rows, columns=columns)
            finally:
                cursor.close()

        return await asyncio.to_thread(_execute)

    async def get_schema_info(self) -> str:
        """
        Get Databricks schema information using Unity Catalog.

        Returns:
            str: Schema DDL statements
        """
        prefix = self._catalog_prefix()
        schema_name = self._schema_name()

        schema_query = f"""
        SELECT
            t.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default
        FROM {prefix}information_schema.tables t
        JOIN {prefix}information_schema.columns c
            ON t.table_catalog = c.table_catalog
            AND t.table_schema = c.table_schema
            AND t.table_name = c.table_name
        WHERE t.table_schema = '{schema_name}'
            AND t.table_type IN ('MANAGED', 'EXTERNAL', 'TABLE')
        ORDER BY t.table_name, c.ordinal_position
        """

        try:
            df = await self.run_sql(schema_query)
        except Exception:
            # Fallback: use SHOW and DESCRIBE commands
            return await self._get_schema_info_fallback()

        if df.empty:
            return f"No tables found in schema {self._schema_path()}."

        # Build DDL-like schema description
        tables = {}
        for _, row in df.iterrows():
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = []

            col_def = f"  {row['column_name']} {row['data_type']}"
            if row["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if pd.notna(row.get("column_default")):
                col_def += f" DEFAULT {row['column_default']}"

            tables[table_name].append(col_def)

        # Format as DDL
        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")

        return "\n\n".join(ddl_parts)

    async def _get_schema_info_fallback(self) -> str:
        """
        Get schema info using SHOW TABLES and DESCRIBE commands.

        Returns:
            str: Schema DDL statements
        """
        schema_path = self._schema_path()

        # Get list of tables
        tables_df = await self.run_sql(f"SHOW TABLES IN {schema_path}")

        if tables_df.empty:
            return f"No tables found in schema {schema_path}."

        ddl_parts = []
        for _, row in tables_df.iterrows():
            table_name = row.get("tableName") or row.get("TABLE_NAME") or row.iloc[1]

            # Get columns for each table
            try:
                cols_df = await self.run_sql(
                    f"DESCRIBE TABLE {self._full_table_name(table_name)}"
                )
                cols = []
                for _, col_row in cols_df.iterrows():
                    col_name = (
                        col_row.get("col_name")
                        or col_row.get("COLUMN_NAME")
                        or col_row.iloc[0]
                    )
                    col_type = (
                        col_row.get("data_type")
                        or col_row.get("DATA_TYPE")
                        or col_row.iloc[1]
                    )
                    # Skip partition/comment rows
                    if col_name and not col_name.startswith("#"):
                        cols.append(f"  {col_name} {col_type}")

                if cols:
                    columns_str = ",\n".join(cols)
                    ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")
            except Exception:
                continue

        return (
            "\n\n".join(ddl_parts)
            if ddl_parts
            else f"No accessible tables in {schema_path}."
        )

    async def test_connection(self) -> bool:
        """
        Test Databricks connection.

        Returns:
            bool: True if connection successful

        Raises:
            Exception: Connection error with details for diagnostics
        """
        df = await self.run_sql("SELECT 1")
        return len(df) > 0

    async def get_all_tables(self) -> List[TableInfo]:
        """Get list of all tables in the database."""
        prefix = self._catalog_prefix()
        schema_name = self._schema_name()

        try:
            query = f"""
            SELECT
                table_name,
                table_schema as schema_name,
                table_type
            FROM {prefix}information_schema.tables
            WHERE table_schema = '{schema_name}'
            ORDER BY table_name
            """
            df = await self.run_sql(query)
        except Exception:
            # Fallback to SHOW TABLES
            df = await self.run_sql(f"SHOW TABLES IN {self._schema_path()}")
            return [
                TableInfo(
                    table_name=row.get("tableName")
                    or row.get("TABLE_NAME")
                    or row.iloc[1],
                    schema_name=schema_name,
                    table_type="BASE TABLE",
                )
                for _, row in df.iterrows()
            ]

        return [
            TableInfo(
                table_name=row["table_name"],
                schema_name=row["schema_name"],
                table_type=row["table_type"],
            )
            for _, row in df.iterrows()
        ]

    async def get_table_ddl(self, table_name: str) -> str:
        """Get DDL statement for a specific Databricks table."""
        prefix = self._catalog_prefix()
        schema_name = self._schema_name()
        full_name = self._full_table_name(table_name)

        try:
            # Try information_schema first
            query = f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM {prefix}information_schema.columns
            WHERE table_schema = '{schema_name}' AND table_name = '{table_name}'
            ORDER BY ordinal_position
            """
            df = await self.run_sql(query)
        except Exception:
            # Fallback to DESCRIBE
            df = await self.run_sql(f"DESCRIBE TABLE {full_name}")
            if df.empty:
                return f"-- Table {full_name} not found"

            col_defs = []
            for _, row in df.iterrows():
                col_name = row.get("col_name") or row.iloc[0]
                col_type = row.get("data_type") or row.iloc[1]
                if col_name and not str(col_name).startswith("#"):
                    col_defs.append(f"  {col_name} {col_type}")

            columns_str = ",\n".join(col_defs)
            return f"CREATE TABLE {full_name} (\n{columns_str}\n);"

        if df.empty:
            return f"-- Table {full_name} not found"

        col_defs = []
        for _, row in df.iterrows():
            col_def = f"  {row['column_name']} {row['data_type']}"
            if row["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if pd.notna(row.get("column_default")):
                col_def += f" DEFAULT {row['column_default']}"
            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return f"CREATE TABLE {full_name} (\n{columns_str}\n);"

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """Get column information for a specific table."""
        prefix = self._catalog_prefix()
        schema_name = self._schema_name()

        try:
            query = f"""
            SELECT
                column_name,
                data_type,
                is_nullable
            FROM {prefix}information_schema.columns
            WHERE table_schema = '{schema_name}' AND table_name = '{table_name}'
            ORDER BY ordinal_position
            """
            df = await self.run_sql(query)
        except Exception:
            # Fallback to DESCRIBE
            full_name = self._full_table_name(table_name)
            df = await self.run_sql(f"DESCRIBE TABLE {full_name}")
            return [
                ColumnInfo(
                    column_name=row.get("col_name") or row.iloc[0],
                    data_type=row.get("data_type") or row.iloc[1],
                    is_nullable=True,
                )
                for _, row in df.iterrows()
                if (row.get("col_name") or row.iloc[0])
                and not str(row.get("col_name") or row.iloc[0]).startswith("#")
            ]

        return [
            ColumnInfo(
                column_name=row["column_name"],
                data_type=row["data_type"],
                is_nullable=row["is_nullable"] == "YES",
            )
            for _, row in df.iterrows()
        ]

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Get random sample rows from a table."""
        full_table_name = self._full_table_name(table_name)

        query = f"""
        SELECT * FROM {full_table_name}
        ORDER BY RAND()
        LIMIT {limit}
        """
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """Get **declared/enforced** foreign key relationships from Unity Catalog.

        Unity Catalog exposes informational PK/FK constraints (added via
        ``ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY``) through the ANSI
        ``information_schema`` views. We read only those declared constraints —
        no name-pattern or LLM inference — so the verified-FK tier of the
        join_graph stays verified-FK-only (see ``_collect_verified_fks``). A schema with
        no declared FKs returns ``[]`` (by-design empty, not an error).

        ``position_in_unique_constraint`` aligns each FK column with its
        referenced column so composite keys map 1:1 instead of cartesian.
        Older Unity Catalog metastores may not expose these views; on any query
        failure we degrade to ``[]`` rather than raising.
        """
        prefix = self._catalog_prefix()
        schema_name = self._schema_name()

        query = f"""
        SELECT
            kcu_fk.constraint_name AS constraint_name,
            kcu_fk.table_name AS source_table,
            kcu_fk.column_name AS source_column,
            kcu_pk.table_name AS target_table,
            kcu_pk.column_name AS target_column
        FROM {prefix}information_schema.referential_constraints rc
        JOIN {prefix}information_schema.key_column_usage kcu_fk
            ON rc.constraint_catalog = kcu_fk.constraint_catalog
            AND rc.constraint_schema = kcu_fk.constraint_schema
            AND rc.constraint_name = kcu_fk.constraint_name
        JOIN {prefix}information_schema.key_column_usage kcu_pk
            ON rc.unique_constraint_catalog = kcu_pk.constraint_catalog
            AND rc.unique_constraint_schema = kcu_pk.constraint_schema
            AND rc.unique_constraint_name = kcu_pk.constraint_name
            AND kcu_fk.position_in_unique_constraint = kcu_pk.ordinal_position
        WHERE kcu_fk.table_schema = '{schema_name}'
        """
        if table_name:
            query += f"    AND kcu_fk.table_name = '{table_name}'\n"
        query += "        ORDER BY source_table, source_column"

        try:
            df = await self.run_sql(query)
        except Exception as e:
            # Older Unity Catalog / metastore without information_schema FK
            # views, or insufficient privileges — degrade to no declared FKs.
            logger.debug(f"Databricks FK introspection unavailable: {e}")
            return []

        return df.to_dict("records")

    async def close(self):
        """Close the connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
