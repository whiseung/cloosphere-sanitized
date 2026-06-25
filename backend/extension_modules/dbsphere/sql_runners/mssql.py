"""MSSQL (SQL Server) runner implementation for DBSphere V2."""

import asyncio
from typing import Dict, List, Optional

import pandas as pd
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.base import (
    ColumnInfo,
    SqlRunnerBase,
    TableInfo,
)


class MSSQLRunner(SqlRunnerBase):
    """Microsoft SQL Server implementation of SqlRunnerBase using pymssql."""

    def __init__(self, config: DBConfig):
        """
        Initialize MSSQL runner.

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
                    "pymssql is required for MSSQL support. "
                    "Install with: pip install pymssql"
                )

            self._connection = pymssql.connect(
                server=self.config.host,
                port=self.config.port,
                user=self.config.username,
                password=self.config.password,
                database=self.config.database,
                charset="utf8",
                login_timeout=10,
                as_dict=False,
            )
        return self._connection

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against MSSQL database.

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
        Get MSSQL schema information.

        Returns:
            str: Schema DDL statements
        """
        # Use configured schema or default to 'dbo'
        schema_name = self.config.schema_name or "dbo"

        # Query to get table and column information
        schema_query = f"""
        SELECT
            t.TABLE_NAME as table_name,
            c.COLUMN_NAME as column_name,
            c.DATA_TYPE as data_type,
            c.CHARACTER_MAXIMUM_LENGTH as max_length,
            c.IS_NULLABLE as is_nullable,
            c.COLUMN_DEFAULT as column_default,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END as is_primary_key
        FROM INFORMATION_SCHEMA.TABLES t
        JOIN INFORMATION_SCHEMA.COLUMNS c
            ON t.TABLE_NAME = c.TABLE_NAME
            AND t.TABLE_SCHEMA = c.TABLE_SCHEMA
        LEFT JOIN (
            SELECT ku.TABLE_NAME, ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
        ) pk ON c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
        WHERE t.TABLE_TYPE = 'BASE TABLE'
            AND t.TABLE_SCHEMA = '{schema_name}'
        ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION;
        """

        df = await self.run_sql(schema_query)

        if df.empty:
            return "No tables found in dbo schema."

        # Build DDL-like schema description
        tables = {}
        for _, row in df.iterrows():
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = []

            # Build data type with length if applicable
            data_type = row["data_type"]
            if row["max_length"] and data_type in (
                "varchar",
                "nvarchar",
                "char",
                "nchar",
            ):
                if row["max_length"] == -1:
                    data_type += "(MAX)"
                else:
                    data_type += f"({row['max_length']})"

            col_def = f"  {row['column_name']} {data_type}"
            if row["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if row["is_primary_key"] == "YES":
                col_def += " PRIMARY KEY"
            if row["column_default"]:
                col_def += f" DEFAULT {row['column_default']}"

            tables[table_name].append(col_def)

        # Format as DDL
        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")

        return "\n\n".join(ddl_parts)

    async def test_connection(self) -> bool:
        """
        Test MSSQL connection.

        Returns:
            bool: True if connection successful
        """
        try:
            df = await self.run_sql("SELECT 1")
            return len(df) > 0
        except Exception:
            return False

    async def close(self):
        """Close the connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

    # =========================================================================
    # Schema extraction methods
    # =========================================================================

    async def get_all_tables(self) -> List[TableInfo]:
        """Get list of all tables in the database."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT TABLE_NAME, TABLE_SCHEMA, TABLE_TYPE
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
            AND TABLE_SCHEMA = '{schema_name}'
        ORDER BY TABLE_NAME
        """
        df = await self.run_sql(query)
        return [
            TableInfo(
                table_name=row["TABLE_NAME"],
                schema_name=row["TABLE_SCHEMA"],
                table_type=row["TABLE_TYPE"],
            )
            for _, row in df.iterrows()
        ]

    async def get_table_ddl(self, table_name: str) -> str:
        """Get DDL statement for a specific MSSQL table."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.NUMERIC_PRECISION,
            c.NUMERIC_SCALE,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END as IS_PK
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN (
            SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
        ) pk ON c.TABLE_SCHEMA = pk.TABLE_SCHEMA
            AND c.TABLE_NAME = pk.TABLE_NAME
            AND c.COLUMN_NAME = pk.COLUMN_NAME
        WHERE c.TABLE_SCHEMA = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """
        df = await self.run_sql(query)
        if df.empty:
            return f"-- Table [{schema_name}].[{table_name}] not found"

        col_defs = []
        for _, row in df.iterrows():
            data_type = row["DATA_TYPE"]
            max_len = row["CHARACTER_MAXIMUM_LENGTH"]
            if max_len is not None and pd.notna(max_len):
                max_len = int(max_len)
                if data_type in ("varchar", "nvarchar", "char", "nchar"):
                    data_type += "(MAX)" if max_len == -1 else f"({max_len})"
                elif data_type == "varbinary":
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
                if data_type == "decimal" or data_type == "numeric":
                    data_type = f"{data_type}({precision},{scale})"

            col_def = f"  [{row['COLUMN_NAME']}] {data_type}"
            if row["IS_NULLABLE"] == "NO":
                col_def += " NOT NULL"
            if row["IS_PK"] == "YES":
                col_def += " PRIMARY KEY"
            if row["COLUMN_DEFAULT"] is not None and pd.notna(row["COLUMN_DEFAULT"]):
                col_def += f" DEFAULT {row['COLUMN_DEFAULT']}"
            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return f"CREATE TABLE [{schema_name}].[{table_name}] (\n{columns_str}\n);"

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """Get column information for a specific MSSQL table."""
        schema_name = self.config.schema_name or "dbo"

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END as IS_PK,
            fk.REFERENCED_TABLE_NAME as FK_TABLE,
            fk.REFERENCED_COLUMN_NAME as FK_COLUMN
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN (
            SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
        ) pk ON c.TABLE_SCHEMA = pk.TABLE_SCHEMA
            AND c.TABLE_NAME = pk.TABLE_NAME
            AND c.COLUMN_NAME = pk.COLUMN_NAME
        LEFT JOIN (
            SELECT
                OBJECT_SCHEMA_NAME(fkc.parent_object_id) as TABLE_SCHEMA,
                OBJECT_NAME(fkc.parent_object_id) as TABLE_NAME,
                COL_NAME(fkc.parent_object_id, fkc.parent_column_id) as COLUMN_NAME,
                OBJECT_NAME(fkc.referenced_object_id) as REFERENCED_TABLE_NAME,
                COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) as REFERENCED_COLUMN_NAME
            FROM sys.foreign_key_columns fkc
        ) fk ON c.TABLE_SCHEMA = fk.TABLE_SCHEMA
            AND c.TABLE_NAME = fk.TABLE_NAME
            AND c.COLUMN_NAME = fk.COLUMN_NAME
        WHERE c.TABLE_SCHEMA = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """
        df = await self.run_sql(query)

        columns = []
        for _, row in df.iterrows():
            data_type = row["DATA_TYPE"]
            max_len = row["CHARACTER_MAXIMUM_LENGTH"]
            if max_len is not None and pd.notna(max_len):
                max_len = int(max_len)
                if data_type in ("varchar", "nvarchar", "char", "nchar"):
                    data_type += "(MAX)" if max_len == -1 else f"({max_len})"

            columns.append(
                ColumnInfo(
                    column_name=row["COLUMN_NAME"],
                    data_type=data_type,
                    is_nullable=row["IS_NULLABLE"] == "YES",
                    column_default=str(row["COLUMN_DEFAULT"])
                    if row["COLUMN_DEFAULT"] is not None
                    and pd.notna(row["COLUMN_DEFAULT"])
                    else None,
                    is_primary_key=row["IS_PK"] == "YES",
                    is_foreign_key=row["FK_TABLE"] is not None
                    and pd.notna(row.get("FK_TABLE")),
                    foreign_table=row["FK_TABLE"]
                    if pd.notna(row.get("FK_TABLE"))
                    else None,
                    foreign_column=row["FK_COLUMN"]
                    if pd.notna(row.get("FK_COLUMN"))
                    else None,
                )
            )
        return columns

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Get random sample rows from a MSSQL table."""
        schema_name = self.config.schema_name or "dbo"
        query = (
            f"SELECT TOP {limit} * FROM [{schema_name}].[{table_name}] ORDER BY NEWID()"
        )
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """Get foreign key relationships."""
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

        df = await self.run_sql(query)
        return df.to_dict("records")
