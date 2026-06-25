"""MySQL runner implementation for DBSphere V2."""

from typing import Dict, List, Optional

import pandas as pd
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.base import (
    ColumnInfo,
    SqlRunnerBase,
    TableInfo,
)


class MySQLRunner(SqlRunnerBase):
    """MySQL implementation of SqlRunnerBase."""

    is_pool_based = True  # aiomysql pool — 쿼리마다 acquire() 로 독립 커넥션

    def __init__(self, config: DBConfig):
        """
        Initialize MySQL runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)
        self._pool = None

    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            try:
                import aiomysql
            except ImportError:
                raise ImportError(
                    "aiomysql is required for MySQL support. "
                    "Install with: pip install aiomysql"
                )

            self._pool = await aiomysql.create_pool(
                host=self.config.host,
                port=self.config.port,
                user=self.config.username,
                password=self.config.password,
                db=self.config.database,
                charset="utf8mb4",
                minsize=1,
                maxsize=5,
                autocommit=True,
            )
        return self._pool

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against MySQL database.

        Args:
            sql: SQL query to execute

        Returns:
            pd.DataFrame: Query results
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                columns = (
                    [desc[0] for desc in cursor.description]
                    if cursor.description
                    else []
                )

                if not rows:
                    return pd.DataFrame(columns=columns)

                return pd.DataFrame(rows, columns=columns)

    async def get_schema_info(self) -> str:
        """
        Get MySQL schema information.

        Returns:
            str: Schema DDL statements
        """
        pool = await self._get_pool()

        # Query to get table and column information
        schema_query = """
        SELECT
            t.TABLE_NAME as table_name,
            c.COLUMN_NAME as column_name,
            c.COLUMN_TYPE as data_type,
            c.IS_NULLABLE as is_nullable,
            c.COLUMN_DEFAULT as column_default,
            c.COLUMN_KEY as column_key,
            c.EXTRA as extra
        FROM information_schema.TABLES t
        JOIN information_schema.COLUMNS c
            ON t.TABLE_NAME = c.TABLE_NAME
            AND t.TABLE_SCHEMA = c.TABLE_SCHEMA
        WHERE t.TABLE_SCHEMA = DATABASE()
            AND t.TABLE_TYPE = 'BASE TABLE'
        ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION;
        """

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(schema_query)
                rows = await cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

        if not rows:
            return "No tables found in database."

        # Build DDL-like schema description
        tables = {}
        for row in rows:
            row_dict = dict(zip(columns, row))
            table_name = row_dict["table_name"]
            if table_name not in tables:
                tables[table_name] = []

            col_def = f"  {row_dict['column_name']} {row_dict['data_type']}"
            if row_dict["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if row_dict["column_key"] == "PRI":
                col_def += " PRIMARY KEY"
            if row_dict["extra"]:
                col_def += f" {row_dict['extra']}"
            if row_dict["column_default"] is not None:
                col_def += f" DEFAULT {row_dict['column_default']}"

            tables[table_name].append(col_def)

        # Format as DDL
        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(f"CREATE TABLE {table_name} (\n{columns_str}\n);")

        return "\n\n".join(ddl_parts)

    async def test_connection(self) -> bool:
        """
        Test MySQL connection.

        Returns:
            bool: True if connection successful
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    # =========================================================================
    # Schema extraction methods
    # =========================================================================

    async def get_all_tables(self) -> List[TableInfo]:
        """Get list of all tables in the database."""
        query = """
        SELECT TABLE_NAME, TABLE_SCHEMA, TABLE_TYPE
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
            AND TABLE_TYPE = 'BASE TABLE'
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
        """Get DDL statement for a specific MySQL table."""
        query = f"""
        SELECT
            COLUMN_NAME,
            COLUMN_TYPE,
            IS_NULLABLE,
            COLUMN_DEFAULT,
            COLUMN_KEY,
            EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table_name}'
        ORDER BY ORDINAL_POSITION
        """
        df = await self.run_sql(query)
        if df.empty:
            return f"-- Table {table_name} not found"

        col_defs = []
        for _, row in df.iterrows():
            col_def = f"  {row['COLUMN_NAME']} {row['COLUMN_TYPE']}"
            if row["IS_NULLABLE"] == "NO":
                col_def += " NOT NULL"
            if row["COLUMN_KEY"] == "PRI":
                col_def += " PRIMARY KEY"
            if row["EXTRA"]:
                col_def += f" {row['EXTRA']}"
            if row["COLUMN_DEFAULT"] is not None and pd.notna(row["COLUMN_DEFAULT"]):
                col_def += f" DEFAULT {row['COLUMN_DEFAULT']}"
            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return f"CREATE TABLE {table_name} (\n{columns_str}\n);"

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """Get column information for a specific MySQL table."""
        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.COLUMN_TYPE,
            c.IS_NULLABLE,
            c.COLUMN_DEFAULT,
            c.COLUMN_KEY,
            k.REFERENCED_TABLE_NAME,
            k.REFERENCED_COLUMN_NAME
        FROM information_schema.COLUMNS c
        LEFT JOIN information_schema.KEY_COLUMN_USAGE k
            ON c.TABLE_SCHEMA = k.TABLE_SCHEMA
            AND c.TABLE_NAME = k.TABLE_NAME
            AND c.COLUMN_NAME = k.COLUMN_NAME
            AND k.REFERENCED_TABLE_NAME IS NOT NULL
        WHERE c.TABLE_SCHEMA = DATABASE() AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.ORDINAL_POSITION
        """
        df = await self.run_sql(query)
        return [
            ColumnInfo(
                column_name=row["COLUMN_NAME"],
                data_type=row["COLUMN_TYPE"],
                is_nullable=row["IS_NULLABLE"] == "YES",
                column_default=str(row["COLUMN_DEFAULT"])
                if row["COLUMN_DEFAULT"] is not None and pd.notna(row["COLUMN_DEFAULT"])
                else None,
                is_primary_key=row["COLUMN_KEY"] == "PRI",
                is_foreign_key=row["REFERENCED_TABLE_NAME"] is not None
                and pd.notna(row["REFERENCED_TABLE_NAME"]),
                foreign_table=row["REFERENCED_TABLE_NAME"]
                if pd.notna(row.get("REFERENCED_TABLE_NAME"))
                else None,
                foreign_column=row["REFERENCED_COLUMN_NAME"]
                if pd.notna(row.get("REFERENCED_COLUMN_NAME"))
                else None,
            )
            for _, row in df.iterrows()
        ]

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Get random sample rows from a MySQL table."""
        query = f"SELECT * FROM {table_name} ORDER BY RAND() LIMIT {limit}"
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """Get foreign key relationships."""
        query = """
        SELECT
            TABLE_NAME as source_table,
            COLUMN_NAME as source_column,
            REFERENCED_TABLE_NAME as target_table,
            REFERENCED_COLUMN_NAME as target_column,
            CONSTRAINT_NAME as constraint_name
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
            AND REFERENCED_TABLE_NAME IS NOT NULL
        """
        if table_name:
            query += f" AND TABLE_NAME = '{table_name}'"
        query += " ORDER BY TABLE_NAME, COLUMN_NAME"

        df = await self.run_sql(query)
        return df.to_dict("records")
