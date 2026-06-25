"""Azure Synapse Analytics runner implementation for DBSphere V2."""

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


class SynapseRunner(SqlRunnerBase):
    """Azure Synapse Analytics implementation of SqlRunnerBase using pymssql."""

    def __init__(self, config: DBConfig):
        """
        Initialize Synapse runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)
        self._connection = None

    def apply_row_limit(self, sql: str, limit: int = 1) -> str:
        """T-SQL has no LIMIT clause — cap rows with a TOP-wrapped subquery."""
        stripped = sql.strip().rstrip(";")
        return f"SELECT TOP {limit} * FROM (\n{stripped}\n) AS _vlim"

    def _get_connection_sync(self):
        """Get or create synchronous connection."""
        if self._connection is None:
            try:
                import pymssql
            except ImportError:
                raise ImportError(
                    "pymssql is required for Azure Synapse support. "
                    "Install with: pip install pymssql"
                )

            self._connection = pymssql.connect(
                server=self.config.host,
                port=self.config.port or 1433,
                user=self.config.username,
                password=self.config.password,
                database=self.config.database,
                charset="utf8",
                login_timeout=30,
                as_dict=False,
            )
        return self._connection

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against Azure Synapse database.

        Args:
            sql: SQL query to execute

        Returns:
            pd.DataFrame: Query results
        """

        def _execute():
            conn = self._get_connection_sync()
            with conn.cursor() as cursor:
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

        return await asyncio.to_thread(_execute)

    async def get_schema_info(self) -> str:
        """
        Get Azure Synapse schema information.

        Returns:
            str: Schema DDL statements
        """
        schema_name = self.config.schema_name or "dbo"

        schema_query = f"""
        SELECT
            t.TABLE_NAME as table_name,
            c.COLUMN_NAME as column_name,
            c.DATA_TYPE as data_type,
            c.CHARACTER_MAXIMUM_LENGTH as max_length,
            c.NUMERIC_PRECISION as numeric_precision,
            c.NUMERIC_SCALE as numeric_scale,
            c.IS_NULLABLE as is_nullable,
            c.COLUMN_DEFAULT as column_default
        FROM INFORMATION_SCHEMA.TABLES t
        JOIN INFORMATION_SCHEMA.COLUMNS c
            ON t.TABLE_NAME = c.TABLE_NAME
            AND t.TABLE_SCHEMA = c.TABLE_SCHEMA
        WHERE t.TABLE_TYPE = 'BASE TABLE'
            AND t.TABLE_SCHEMA = '{schema_name}'
        ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
        """

        df = await self.run_sql(schema_query)

        if df.empty:
            return f"No tables found in schema {schema_name}."

        tables = {}
        for _, row in df.iterrows():
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = []

            data_type = row["data_type"]
            if data_type in ("varchar", "nvarchar", "char", "nchar", "varbinary"):
                if row["max_length"] and row["max_length"] != -1:
                    data_type = f"{data_type}({int(row['max_length'])})"
                elif row["max_length"] == -1:
                    data_type = f"{data_type}(MAX)"
            elif data_type in ("decimal", "numeric"):
                if pd.notna(row["numeric_precision"]):
                    precision = int(row["numeric_precision"])
                    scale = (
                        int(row["numeric_scale"])
                        if pd.notna(row["numeric_scale"])
                        else 0
                    )
                    data_type = f"{data_type}({precision},{scale})"

            col_def = f"  {row['column_name']} {data_type}"
            if row["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if pd.notna(row["column_default"]):
                col_def += f" DEFAULT {row['column_default']}"

            tables[table_name].append(col_def)

        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")

        return "\n\n".join(ddl_parts)

    async def test_connection(self) -> bool:
        """
        Test Azure Synapse connection.

        Returns:
            bool: True if connection successful

        Raises:
            Exception: Connection error with details for diagnostics
        """
        df = await self.run_sql("SELECT 1")
        return len(df) > 0

    async def get_all_tables(self) -> List[TableInfo]:
        """Get list of all tables in the database."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT
            TABLE_NAME,
            TABLE_SCHEMA as SCHEMA_NAME,
            TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
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
        """Get DDL statement for a specific Synapse table."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.NUMERIC_PRECISION,
            c.NUMERIC_SCALE,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """
        df = await self.run_sql(query)
        if df.empty:
            return f"-- Table [{schema_name}].[{table_name}] not found"

        # Get PK info via sys views
        pk_columns = await self._get_primary_keys(schema_name, table_name)

        col_defs = []
        for _, row in df.iterrows():
            data_type = row["DATA_TYPE"]
            max_len = row["CHARACTER_MAXIMUM_LENGTH"]
            if max_len is not None and pd.notna(max_len):
                max_len = int(max_len)
                if data_type in ("varchar", "nvarchar", "char", "nchar", "varbinary"):
                    data_type += "(MAX)" if max_len == -1 else f"({max_len})"
            elif row["NUMERIC_PRECISION"] is not None and pd.notna(
                row["NUMERIC_PRECISION"]
            ):
                precision = int(row["NUMERIC_PRECISION"])
                scale = (
                    int(row["NUMERIC_SCALE"])
                    if row["NUMERIC_SCALE"] is not None
                    and pd.notna(row["NUMERIC_SCALE"])
                    else 0
                )
                if data_type in ("decimal", "numeric"):
                    data_type = f"{data_type}({precision},{scale})"

            col_def = f"  [{row['COLUMN_NAME']}] {data_type}"
            if row["IS_NULLABLE"] == "NO":
                col_def += " NOT NULL"
            if row["COLUMN_NAME"] in pk_columns:
                col_def += " PRIMARY KEY"
            if row["COLUMN_DEFAULT"] is not None and pd.notna(row["COLUMN_DEFAULT"]):
                col_def += f" DEFAULT {row['COLUMN_DEFAULT']}"
            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return f"CREATE TABLE [{schema_name}].[{table_name}] (\n{columns_str}\n);"

    async def _get_primary_keys(self, schema_name: str, table_name: str) -> set:
        """Get primary key column names using sys views."""
        try:
            query = f"""
            SELECT COL_NAME(ic.object_id, ic.column_id) as column_name
            FROM sys.indexes i
            JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            WHERE i.is_primary_key = 1
                AND i.object_id = OBJECT_ID('{schema_name}.{table_name}')
            """
            df = await self.run_sql(query)
            if not df.empty:
                return set(df["column_name"].tolist())
        except Exception as e:
            logger.debug(f"No primary keys for {table_name}: {e}")
        return set()

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """Get column information for a specific table."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """
        df = await self.run_sql(query)

        # Get PK/FK info via sys views
        pk_columns = await self._get_primary_keys(schema_name, table_name)
        fk_map = await self._get_foreign_keys_for_table(schema_name, table_name)

        columns = []
        for _, row in df.iterrows():
            data_type = row["DATA_TYPE"]
            max_len = row["CHARACTER_MAXIMUM_LENGTH"]
            if max_len is not None and pd.notna(max_len):
                max_len = int(max_len)
                if data_type in ("varchar", "nvarchar", "char", "nchar"):
                    data_type += "(MAX)" if max_len == -1 else f"({max_len})"

            col_name = row["COLUMN_NAME"]
            fk_info = fk_map.get(col_name, {})

            columns.append(
                ColumnInfo(
                    column_name=col_name,
                    data_type=data_type,
                    is_nullable=row["IS_NULLABLE"] == "YES",
                    column_default=str(row["COLUMN_DEFAULT"])
                    if row["COLUMN_DEFAULT"] is not None
                    and pd.notna(row["COLUMN_DEFAULT"])
                    else None,
                    is_primary_key=col_name in pk_columns,
                    is_foreign_key=bool(fk_info),
                    foreign_table=fk_info.get("fk_table"),
                    foreign_column=fk_info.get("fk_column"),
                )
            )
        return columns

    async def _get_foreign_keys_for_table(
        self, schema_name: str, table_name: str
    ) -> Dict[str, Dict]:
        """Get FK info for a table using sys views."""
        try:
            query = f"""
            SELECT
                COL_NAME(fkc.parent_object_id, fkc.parent_column_id) as source_column,
                OBJECT_NAME(fkc.referenced_object_id) as target_table,
                COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) as target_column
            FROM sys.foreign_key_columns fkc
            WHERE fkc.parent_object_id = OBJECT_ID('{schema_name}.{table_name}')
            """
            df = await self.run_sql(query)
            fk_map = {}
            for _, row in df.iterrows():
                fk_map[row["source_column"]] = {
                    "fk_table": row["target_table"],
                    "fk_column": row["target_column"],
                }
            return fk_map
        except Exception as e:
            logger.debug(f"No foreign keys for {table_name}: {e}")
            return {}

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Get random sample rows from a table."""
        schema_name = self.config.schema_name or "dbo"
        full_table_name = f"[{schema_name}].[{table_name}]"

        query = f"""
        SELECT TOP {limit} * FROM {full_table_name}
        ORDER BY NEWID()
        """
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """Get foreign key relationships using sys views."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT
            OBJECT_NAME(fkc.parent_object_id) as source_table,
            COL_NAME(fkc.parent_object_id, fkc.parent_column_id) as source_column,
            OBJECT_NAME(fkc.referenced_object_id) as target_table,
            COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) as target_column,
            fk.name as constraint_name
        FROM sys.foreign_key_columns fkc
        JOIN sys.foreign_keys fk ON fkc.constraint_object_id = fk.object_id
        WHERE OBJECT_SCHEMA_NAME(fkc.parent_object_id) = '{schema_name}'
        """
        if table_name:
            query += f" AND OBJECT_NAME(fkc.parent_object_id) = '{table_name}'"
        query += " ORDER BY source_table, source_column"

        try:
            df = await self.run_sql(query)
            return df.to_dict("records")
        except Exception as e:
            logger.debug(f"Failed to get FK relationships: {e}")
            return []

    async def close(self):
        """Close the connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
