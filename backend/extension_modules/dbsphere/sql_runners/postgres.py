"""PostgreSQL runner implementation for DBSphere V2."""

from typing import Dict, List, Optional

import pandas as pd
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.base import (
    ColumnInfo,
    SqlRunnerBase,
    TableInfo,
)


class PostgresRunner(SqlRunnerBase):
    """PostgreSQL implementation of SqlRunnerBase."""

    is_pool_based = True  # asyncpg pool — 쿼리마다 acquire() 로 독립 커넥션

    def __init__(self, config: DBConfig):
        """
        Initialize PostgreSQL runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)
        self._pool = None

    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            try:
                import asyncpg
            except ImportError:
                raise ImportError(
                    "asyncpg is required for PostgreSQL support. "
                    "Install with: pip install asyncpg"
                )

            self._pool = await asyncpg.create_pool(
                host=self.config.host,
                port=self.config.port,
                user=self.config.username,
                password=self.config.password,
                database=self.config.database,
                min_size=1,
                max_size=5,
            )
        return self._pool

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against PostgreSQL database.

        Args:
            sql: SQL query to execute

        Returns:
            pd.DataFrame: Query results
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Execute query and fetch results
            rows = await conn.fetch(sql)

            if not rows:
                return pd.DataFrame()

            # Convert to DataFrame
            columns = list(rows[0].keys())
            data = [dict(row) for row in rows]
            return pd.DataFrame(data, columns=columns)

    async def get_schema_info(self) -> str:
        """
        Get PostgreSQL schema information.

        Returns:
            str: Schema DDL statements
        """
        pool = await self._get_pool()

        # Use configured schema or default to 'public'
        schema_name = self.config.schema_name or "public"

        # Query to get table and column information
        schema_query = f"""
        SELECT
            t.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            tc.constraint_type,
            kcu.column_name as key_column
        FROM information_schema.tables t
        JOIN information_schema.columns c
            ON t.table_name = c.table_name
            AND t.table_schema = c.table_schema
        LEFT JOIN information_schema.table_constraints tc
            ON t.table_name = tc.table_name
            AND t.table_schema = tc.table_schema
            AND tc.constraint_type = 'PRIMARY KEY'
        LEFT JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
            AND c.column_name = kcu.column_name
        WHERE t.table_schema = '{schema_name}'
            AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name, c.ordinal_position;
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(schema_query)

        # Build DDL-like schema description
        if not rows:
            return "No tables found in public schema."

        tables = {}
        for row in rows:
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = []

            col_def = f"  {row['column_name']} {row['data_type']}"
            if row["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if row["key_column"]:
                col_def += " PRIMARY KEY"
            if row["column_default"]:
                col_def += f" DEFAULT {row['column_default']}"

            tables[table_name].append(col_def)

        # Format as DDL
        ddl_parts = []
        for table_name, columns in tables.items():
            columns_str = ",\n".join(columns)
            ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")

        return "\n\n".join(ddl_parts)

    async def test_connection(self) -> bool:
        """
        Test PostgreSQL connection.

        Returns:
            bool: True if connection successful
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # =========================================================================
    # Schema extraction methods
    # =========================================================================

    async def get_all_tables(self) -> List[TableInfo]:
        """
        Get list of all tables in the database.

        Returns:
            List[TableInfo]: List of table information
        """
        pool = await self._get_pool()
        schema_name = self.config.schema_name or "public"

        query = f"""
        SELECT table_name, table_schema, table_type
        FROM information_schema.tables
        WHERE table_schema = '{schema_name}'
            AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query)

        return [
            TableInfo(
                table_name=row["table_name"],
                schema_name=row["table_schema"],
                table_type=row["table_type"],
            )
            for row in rows
        ]

    async def get_table_ddl(self, table_name: str) -> str:
        """
        Get DDL statement for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            str: DDL CREATE TABLE statement
        """
        pool = await self._get_pool()
        schema_name = self.config.schema_name or "public"

        # Get column information
        column_query = f"""
        SELECT
            c.column_name,
            c.data_type,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            c.is_nullable,
            c.column_default
        FROM information_schema.columns c
        WHERE c.table_schema = '{schema_name}'
            AND c.table_name = '{table_name}'
        ORDER BY c.ordinal_position;
        """

        # Get primary key columns
        pk_query = f"""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = '{schema_name}'
            AND tc.table_name = '{table_name}'
            AND tc.constraint_type = 'PRIMARY KEY';
        """

        async with pool.acquire() as conn:
            columns = await conn.fetch(column_query)
            pk_rows = await conn.fetch(pk_query)

        pk_columns = {row["column_name"] for row in pk_rows}

        # Build DDL
        col_defs = []
        for col in columns:
            data_type = col["data_type"]
            if col["character_maximum_length"]:
                data_type = f"{data_type}({col['character_maximum_length']})"
            elif col["numeric_precision"] and col["numeric_scale"]:
                data_type = (
                    f"{data_type}({col['numeric_precision']},{col['numeric_scale']})"
                )

            col_def = f"  {col['column_name']} {data_type}"
            if col["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if col["column_name"] in pk_columns:
                col_def += " PRIMARY KEY"
            if col["column_default"]:
                col_def += f" DEFAULT {col['column_default']}"

            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return f"CREATE TABLE {schema_name}.{table_name} (\n{columns_str}\n);"

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """
        Get column information for a specific table.

        Args:
            table_name: Name of the table

        Returns:
            List[ColumnInfo]: List of column information
        """
        pool = await self._get_pool()
        schema_name = self.config.schema_name or "public"

        query = f"""
        SELECT
            c.column_name,
            c.data_type,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            c.is_nullable,
            c.column_default,
            CASE WHEN pk.column_name IS NOT NULL THEN TRUE ELSE FALSE END as is_primary_key,
            CASE WHEN fk.column_name IS NOT NULL THEN TRUE ELSE FALSE END as is_foreign_key,
            fk.foreign_table_name,
            fk.foreign_column_name
        FROM information_schema.columns c
        LEFT JOIN (
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = '{schema_name}'
                AND tc.table_name = '{table_name}'
                AND tc.constraint_type = 'PRIMARY KEY'
        ) pk ON c.column_name = pk.column_name
        LEFT JOIN (
            SELECT
                kcu.column_name,
                ccu.table_name as foreign_table_name,
                ccu.column_name as foreign_column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.table_schema = '{schema_name}'
                AND tc.table_name = '{table_name}'
                AND tc.constraint_type = 'FOREIGN KEY'
        ) fk ON c.column_name = fk.column_name
        WHERE c.table_schema = '{schema_name}'
            AND c.table_name = '{table_name}'
        ORDER BY c.ordinal_position;
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query)

        columns = []
        for row in rows:
            data_type = row["data_type"]
            if row["character_maximum_length"]:
                data_type = f"{data_type}({row['character_maximum_length']})"
            elif row["numeric_precision"] and row["numeric_scale"]:
                data_type = (
                    f"{data_type}({row['numeric_precision']},{row['numeric_scale']})"
                )

            columns.append(
                ColumnInfo(
                    column_name=row["column_name"],
                    data_type=data_type,
                    is_nullable=row["is_nullable"] == "YES",
                    column_default=row["column_default"],
                    is_primary_key=row["is_primary_key"],
                    is_foreign_key=row["is_foreign_key"],
                    foreign_table=row["foreign_table_name"],
                    foreign_column=row["foreign_column_name"],
                )
            )

        return columns

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
        schema_name = self.config.schema_name or "public"

        # Use TABLESAMPLE for efficient random sampling on large tables
        # Fall back to ORDER BY RANDOM() for smaller tables or if TABLESAMPLE not available
        query = f"""
        SELECT * FROM {schema_name}.{table_name}
        ORDER BY RANDOM()
        LIMIT {limit};
        """

        return await self.run_sql(query)

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
        pool = await self._get_pool()
        schema_name = self.config.schema_name or "public"

        table_filter = ""
        if table_name:
            table_filter = f"AND tc.table_name = '{table_name}'"

        query = f"""
        SELECT
            tc.table_name as source_table,
            kcu.column_name as source_column,
            ccu.table_name as target_table,
            ccu.column_name as target_column,
            tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
            AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = '{schema_name}'
            AND tc.constraint_type = 'FOREIGN KEY'
            {table_filter}
        ORDER BY tc.table_name, kcu.column_name;
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query)

        return [
            {
                "source_table": row["source_table"],
                "source_column": row["source_column"],
                "target_table": row["target_table"],
                "target_column": row["target_column"],
                "constraint_name": row["constraint_name"],
            }
            for row in rows
        ]
