"""Snowflake database runner implementation for DBSphere V2."""

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


class SnowflakeRunner(SqlRunnerBase):
    """Snowflake implementation of SqlRunnerBase using snowflake-connector-python."""

    def __init__(self, config: DBConfig):
        """
        Initialize Snowflake runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)
        self._connection = None

    def _get_connection_sync(self):
        """Get or create synchronous connection."""
        if self._connection is None:
            try:
                import snowflake.connector
            except ImportError:
                raise ImportError(
                    "snowflake-connector-python is required for Snowflake support. "
                    "Install with: pip install snowflake-connector-python"
                )

            conn_params = {
                "account": self.config.account,
                "user": self.config.username,
                "password": self.config.password,
                "database": self.config.database,
            }

            # Optional parameters
            if self.config.warehouse:
                conn_params["warehouse"] = self.config.warehouse
            if self.config.schema_name:
                conn_params["schema"] = self.config.schema_name
            if self.config.role:
                conn_params["role"] = self.config.role

            self._connection = snowflake.connector.connect(**conn_params)
        return self._connection

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against Snowflake database.

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

    async def _run_show_command(self, command: str) -> pd.DataFrame:
        """Execute a SHOW command and return results as DataFrame."""

        def _execute():
            conn = self._get_connection_sync()
            cursor = conn.cursor()
            try:
                cursor.execute(command)
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

    async def _get_primary_keys(self, table_name: str) -> set:
        """Get primary key column names using SHOW command."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database
        try:
            df = await self._run_show_command(
                f'SHOW PRIMARY KEYS IN TABLE {database}.{schema_name}."{table_name}"'
            )
            if not df.empty and "column_name" in df.columns:
                return set(df["column_name"].tolist())
        except Exception as e:
            logger.debug(f"No primary keys for {table_name}: {e}")
        return set()

    async def _get_imported_keys(self, table_name: str) -> Dict[str, Dict]:
        """Get foreign key info using SHOW command. Returns {column_name: {fk_table, fk_column}}."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database
        fk_map = {}
        try:
            df = await self._run_show_command(
                f'SHOW IMPORTED KEYS IN TABLE {database}.{schema_name}."{table_name}"'
            )
            if not df.empty:
                for _, row in df.iterrows():
                    fk_col = row.get("fk_column_name", "")
                    pk_table = row.get("pk_table_name", "")
                    pk_col = row.get("pk_column_name", "")
                    if fk_col:
                        fk_map[fk_col] = {
                            "fk_table": pk_table,
                            "fk_column": pk_col,
                        }
        except Exception as e:
            logger.debug(f"No foreign keys for {table_name}: {e}")
        return fk_map

    async def get_schema_info(self) -> str:
        """
        Get Snowflake schema information.

        Returns:
            str: Schema DDL statements
        """
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database

        schema_query = f"""
        SELECT
            c.TABLE_NAME as table_name,
            c.COLUMN_NAME as column_name,
            c.DATA_TYPE as data_type,
            c.CHARACTER_MAXIMUM_LENGTH as max_length,
            c.NUMERIC_PRECISION as numeric_precision,
            c.NUMERIC_SCALE as numeric_scale,
            c.IS_NULLABLE as is_nullable,
            c.COLUMN_DEFAULT as column_default
        FROM {database}.INFORMATION_SCHEMA.COLUMNS c
        JOIN {database}.INFORMATION_SCHEMA.TABLES t
            ON c.TABLE_NAME = t.TABLE_NAME
            AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
            AND c.TABLE_CATALOG = t.TABLE_CATALOG
        WHERE t.TABLE_TYPE = 'BASE TABLE'
            AND c.TABLE_SCHEMA = '{schema_name}'
        ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
        """

        df = await self.run_sql(schema_query)

        if df.empty:
            return f"No tables found in schema {schema_name}."

        # Build DDL-like schema description
        tables = {}
        for _, row in df.iterrows():
            table_name = row["TABLE_NAME"]
            if table_name not in tables:
                tables[table_name] = []

            # Build data type with length/precision
            data_type = row["DATA_TYPE"]
            if data_type in ("VARCHAR", "CHAR", "STRING", "TEXT"):
                if pd.notna(row["MAX_LENGTH"]):
                    data_type = f"{data_type}({int(row['MAX_LENGTH'])})"
            elif data_type in ("NUMBER", "DECIMAL", "NUMERIC"):
                if pd.notna(row["NUMERIC_PRECISION"]):
                    precision = int(row["NUMERIC_PRECISION"])
                    scale = (
                        int(row["NUMERIC_SCALE"])
                        if pd.notna(row["NUMERIC_SCALE"])
                        else 0
                    )
                    if scale > 0:
                        data_type = f"{data_type}({precision},{scale})"
                    else:
                        data_type = f"{data_type}({precision})"

            col_def = f"  {row['COLUMN_NAME']} {data_type}"
            if row["IS_NULLABLE"] == "NO":
                col_def += " NOT NULL"
            if pd.notna(row["COLUMN_DEFAULT"]):
                col_def += f" DEFAULT {row['COLUMN_DEFAULT']}"

            tables[table_name].append(col_def)

        # Format as DDL
        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")

        return "\n\n".join(ddl_parts)

    async def test_connection(self) -> bool:
        """
        Test Snowflake connection.

        Returns:
            bool: True if connection successful
        """
        try:
            df = await self.run_sql("SELECT 1")
            return len(df) > 0
        except Exception:
            return False

    async def get_all_tables(self) -> List[TableInfo]:
        """Get list of all tables in the database."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database

        query = f"""
        SELECT
            TABLE_NAME,
            TABLE_SCHEMA as SCHEMA_NAME,
            TABLE_TYPE
        FROM {database}.INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '{schema_name}'
            AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
        """

        df = await self.run_sql(query)
        return [
            TableInfo(
                table_name=row["TABLE_NAME"],
                schema_name=row["SCHEMA_NAME"],
                table_type=row["TABLE_TYPE"],
            )
            for _, row in df.iterrows()
        ]

    async def get_table_ddl(self, table_name: str) -> str:
        """Get DDL statement for a specific Snowflake table."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.NUMERIC_PRECISION,
            c.NUMERIC_SCALE,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT
        FROM {database}.INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """

        df = await self.run_sql(query)
        if df.empty:
            return f"-- Table {database}.{schema_name}.{table_name} not found"

        # Get PK info via SHOW command
        pk_columns = await self._get_primary_keys(table_name)

        col_defs = []
        for _, row in df.iterrows():
            data_type = row["DATA_TYPE"]
            if data_type in ("VARCHAR", "CHAR", "STRING", "TEXT"):
                if pd.notna(row["CHARACTER_MAXIMUM_LENGTH"]):
                    data_type = f"{data_type}({int(row['CHARACTER_MAXIMUM_LENGTH'])})"
            elif data_type in ("NUMBER", "DECIMAL", "NUMERIC"):
                if pd.notna(row["NUMERIC_PRECISION"]):
                    precision = int(row["NUMERIC_PRECISION"])
                    scale = (
                        int(row["NUMERIC_SCALE"])
                        if pd.notna(row["NUMERIC_SCALE"])
                        else 0
                    )
                    if scale > 0:
                        data_type = f"{data_type}({precision},{scale})"
                    else:
                        data_type = f"{data_type}({precision})"

            col_def = f"  {row['COLUMN_NAME']} {data_type}"
            if row["IS_NULLABLE"] == "NO":
                col_def += " NOT NULL"
            if row["COLUMN_NAME"] in pk_columns:
                col_def += " PRIMARY KEY"
            if pd.notna(row["COLUMN_DEFAULT"]):
                col_def += f" DEFAULT {row['COLUMN_DEFAULT']}"
            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return (
            f"CREATE TABLE {database}.{schema_name}.{table_name} (\n{columns_str}\n);"
        )

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """Get column information for a specific table."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT
        FROM {database}.INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """

        df = await self.run_sql(query)

        # Get PK/FK info via SHOW commands
        pk_columns = await self._get_primary_keys(table_name)
        fk_map = await self._get_imported_keys(table_name)

        return [
            ColumnInfo(
                column_name=row["COLUMN_NAME"],
                data_type=row["DATA_TYPE"],
                is_nullable=row["IS_NULLABLE"] == "YES",
                column_default=str(row["COLUMN_DEFAULT"])
                if pd.notna(row["COLUMN_DEFAULT"])
                else None,
                is_primary_key=row["COLUMN_NAME"] in pk_columns,
                is_foreign_key=row["COLUMN_NAME"] in fk_map,
                foreign_table=fk_map.get(row["COLUMN_NAME"], {}).get("fk_table"),
                foreign_column=fk_map.get(row["COLUMN_NAME"], {}).get("fk_column"),
            )
            for _, row in df.iterrows()
        ]

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Get random sample rows from a table."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database
        full_table_name = f"{database}.{schema_name}.{table_name}"

        query = f"""
        SELECT * FROM {full_table_name}
        SAMPLE ({limit} ROWS)
        """
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """Get foreign key relationships using SHOW commands."""
        schema_name = self.config.schema_name or "PUBLIC"
        database = self.config.database

        if table_name:
            # Single table
            fk_map = await self._get_imported_keys(table_name)
            results = []
            for col_name, fk_info in fk_map.items():
                results.append(
                    {
                        "SOURCE_TABLE": table_name,
                        "SOURCE_COLUMN": col_name,
                        "TARGET_TABLE": fk_info["fk_table"],
                        "TARGET_COLUMN": fk_info["fk_column"],
                    }
                )
            return results

        # All tables - get table list first, then FK for each
        tables = await self.get_all_tables()
        results = []
        for t in tables:
            fk_map = await self._get_imported_keys(t.table_name)
            for col_name, fk_info in fk_map.items():
                results.append(
                    {
                        "SOURCE_TABLE": t.table_name,
                        "SOURCE_COLUMN": col_name,
                        "TARGET_TABLE": fk_info["fk_table"],
                        "TARGET_COLUMN": fk_info["fk_column"],
                    }
                )
        return results

    async def close(self):
        """Close the connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
