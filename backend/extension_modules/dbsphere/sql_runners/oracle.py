"""Oracle database runner implementation for DBSphere V2."""

import asyncio
import re
from typing import Dict, List, Optional

import pandas as pd
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.base import (
    ColumnInfo,
    SqlRunnerBase,
    TableInfo,
    validate_sql_identifier,
)

# Oracle folds unquoted identifiers to uppercase. Tables/columns created with
# double quotes (.NET/EF style, e.g. "T_Codes") are case-sensitive and must be
# quoted to be referenced. Quote only when needed so all-uppercase identifiers
# stay readable (and so the DDL shown to the LLM teaches quoting only where
# required).
_ORACLE_RESERVED = {
    "ACCESS",
    "ADD",
    "ALL",
    "ALTER",
    "AND",
    "ANY",
    "AS",
    "ASC",
    "AUDIT",
    "BETWEEN",
    "BY",
    "CHAR",
    "CHECK",
    "CLUSTER",
    "COLUMN",
    "COMMENT",
    "COMPRESS",
    "CONNECT",
    "CREATE",
    "CURRENT",
    "DATE",
    "DECIMAL",
    "DEFAULT",
    "DELETE",
    "DESC",
    "DISTINCT",
    "DROP",
    "ELSE",
    "EXCLUSIVE",
    "EXISTS",
    "FILE",
    "FLOAT",
    "FOR",
    "FROM",
    "GRANT",
    "GROUP",
    "HAVING",
    "IN",
    "INDEX",
    "INSERT",
    "INTEGER",
    "INTERSECT",
    "INTO",
    "IS",
    "LEVEL",
    "LIKE",
    "LOCK",
    "LONG",
    "MODE",
    "MODIFY",
    "NOT",
    "NOWAIT",
    "NULL",
    "NUMBER",
    "OF",
    "ON",
    "OPTION",
    "OR",
    "ORDER",
    "PRIOR",
    "PUBLIC",
    "RAW",
    "RENAME",
    "RESOURCE",
    "REVOKE",
    "ROW",
    "ROWID",
    "ROWNUM",
    "ROWS",
    "SELECT",
    "SESSION",
    "SET",
    "SHARE",
    "SIZE",
    "START",
    "SYNONYM",
    "SYSDATE",
    "TABLE",
    "THEN",
    "TIME",
    "TIMESTAMP",
    "TO",
    "TRIGGER",
    "TYPE",
    "UID",
    "UNION",
    "UNIQUE",
    "UPDATE",
    "USER",
    "VALUES",
    "VARCHAR",
    "VARCHAR2",
    "VIEW",
    "WHERE",
    "WITH",
}


def _quote_ident(name: str) -> str:
    """Quote an Oracle identifier only when required (mixed-case/special/reserved)."""
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", name) and name.upper() not in _ORACLE_RESERVED:
        return name
    return '"' + name.replace('"', '""') + '"'


class OracleRunner(SqlRunnerBase):
    """Oracle Database implementation of SqlRunnerBase using oracledb."""

    def __init__(self, config: DBConfig):
        """
        Initialize Oracle runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)
        self._connection = None
        # Oracle uses the username as the schema when schema_name is unset; that
        # value also flows into introspection queries, so allow-list it too.
        if not config.schema_name and config.username:
            validate_sql_identifier(config.username.upper(), kind="schema")

    def _get_connection_sync(self):
        """Get or create synchronous connection."""
        if self._connection is None:
            try:
                import oracledb
            except ImportError:
                raise ImportError(
                    "oracledb is required for Oracle support. "
                    "Install with: pip install oracledb"
                )

            # Build connection parameters
            if self.config.dsn:
                # Use full DSN if provided
                dsn = self.config.dsn
            elif self.config.service_name:
                # Use service_name
                dsn = oracledb.makedsn(
                    self.config.host,
                    self.config.port,
                    service_name=self.config.service_name,
                )
            else:
                # Use SID (database name)
                dsn = oracledb.makedsn(
                    self.config.host,
                    self.config.port,
                    sid=self.config.database,
                )

            self._connection = oracledb.connect(
                user=self.config.username,
                password=self.config.password,
                dsn=dsn,
            )
        return self._connection

    async def run_sql(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL query against Oracle database.

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
        Get Oracle schema information.

        Returns:
            str: Schema DDL statements
        """
        # Use configured schema or current user's schema
        schema_name = self.config.schema_name or self.config.username.upper()

        schema_query = f"""
        SELECT
            t.TABLE_NAME as table_name,
            c.COLUMN_NAME as column_name,
            c.DATA_TYPE as data_type,
            c.DATA_LENGTH as data_length,
            c.DATA_PRECISION as data_precision,
            c.DATA_SCALE as data_scale,
            c.NULLABLE as is_nullable,
            c.DATA_DEFAULT as column_default,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END as is_primary_key
        FROM ALL_TABLES t
        JOIN ALL_TAB_COLUMNS c
            ON t.OWNER = c.OWNER AND t.TABLE_NAME = c.TABLE_NAME
        LEFT JOIN (
            SELECT acc.OWNER, acc.TABLE_NAME, acc.COLUMN_NAME
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
                ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
                AND ac.OWNER = acc.OWNER
            WHERE ac.CONSTRAINT_TYPE = 'P'
        ) pk ON c.OWNER = pk.OWNER AND c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
        WHERE t.OWNER = '{schema_name}'
        ORDER BY t.TABLE_NAME, c.COLUMN_ID
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

            # Build data type with precision/scale
            data_type = row["DATA_TYPE"]
            if data_type in ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR", "RAW"):
                data_type = f"{data_type}({int(row['DATA_LENGTH'])})"
            elif data_type == "NUMBER":
                if pd.notna(row["DATA_PRECISION"]):
                    precision = int(row["DATA_PRECISION"])
                    scale = int(row["DATA_SCALE"]) if pd.notna(row["DATA_SCALE"]) else 0
                    if scale > 0:
                        data_type = f"NUMBER({precision},{scale})"
                    else:
                        data_type = f"NUMBER({precision})"

            col_def = f"  {_quote_ident(row['COLUMN_NAME'])} {data_type}"
            if row["IS_NULLABLE"] == "N":
                col_def += " NOT NULL"
            if row["IS_PRIMARY_KEY"] == "Y":
                col_def += " PRIMARY KEY"
            if pd.notna(row["COLUMN_DEFAULT"]):
                col_def += f" DEFAULT {row['COLUMN_DEFAULT']}"

            tables[table_name].append(col_def)

        # Format as DDL
        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(
                f"CREATE TABLE {_quote_ident(table_name)} (\n{columns_str}\n);"
            )

        return "\n\n".join(ddl_parts)

    async def test_connection(self) -> bool:
        """
        Test Oracle connection.

        Returns:
            bool: True if connection successful
        """
        try:
            df = await self.run_sql("SELECT 1 FROM DUAL")
            return len(df) > 0
        except Exception:
            return False

    async def get_all_tables(self) -> List[TableInfo]:
        """Get list of all tables in the database."""
        schema_name = self.config.schema_name or self.config.username.upper()

        query = f"""
        SELECT TABLE_NAME, OWNER as SCHEMA_NAME, 'BASE TABLE' as TABLE_TYPE
        FROM ALL_TABLES
        WHERE OWNER = '{schema_name}'
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
        """Get DDL statement for a specific Oracle table."""
        schema_name = self.config.schema_name or self.config.username.upper()

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.DATA_LENGTH,
            c.DATA_PRECISION,
            c.DATA_SCALE,
            c.NULLABLE,
            c.DATA_DEFAULT,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END as IS_PK
        FROM ALL_TAB_COLUMNS c
        LEFT JOIN (
            SELECT acc.OWNER, acc.TABLE_NAME, acc.COLUMN_NAME
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
                ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
                AND ac.OWNER = acc.OWNER
            WHERE ac.CONSTRAINT_TYPE = 'P'
        ) pk ON c.OWNER = pk.OWNER
            AND c.TABLE_NAME = pk.TABLE_NAME
            AND c.COLUMN_NAME = pk.COLUMN_NAME
        WHERE c.OWNER = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.COLUMN_ID
        """

        df = await self.run_sql(query)
        if df.empty:
            return f"-- Table {schema_name}.{table_name} not found"

        col_defs = []
        for _, row in df.iterrows():
            data_type = row["DATA_TYPE"]
            if data_type in ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR", "RAW"):
                data_type = f"{data_type}({int(row['DATA_LENGTH'])})"
            elif data_type == "NUMBER":
                if pd.notna(row["DATA_PRECISION"]):
                    precision = int(row["DATA_PRECISION"])
                    scale = int(row["DATA_SCALE"]) if pd.notna(row["DATA_SCALE"]) else 0
                    if scale > 0:
                        data_type = f"NUMBER({precision},{scale})"
                    else:
                        data_type = f"NUMBER({precision})"

            col_def = f"  {_quote_ident(row['COLUMN_NAME'])} {data_type}"
            if row["NULLABLE"] == "N":
                col_def += " NOT NULL"
            if row["IS_PK"] == "Y":
                col_def += " PRIMARY KEY"
            if pd.notna(row["DATA_DEFAULT"]):
                col_def += f" DEFAULT {str(row['DATA_DEFAULT']).strip()}"

            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return (
            f"CREATE TABLE {_quote_ident(schema_name)}.{_quote_ident(table_name)} "
            f"(\n{columns_str}\n);"
        )

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        """Get column information for a specific table."""
        schema_name = self.config.schema_name or self.config.username.upper()

        query = f"""
        SELECT
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.NULLABLE,
            c.DATA_DEFAULT,
            CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END as IS_PK,
            CASE WHEN fk.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END as IS_FK,
            fk.R_TABLE_NAME as FK_TABLE,
            fk.R_COLUMN_NAME as FK_COLUMN
        FROM ALL_TAB_COLUMNS c
        LEFT JOIN (
            SELECT acc.OWNER, acc.TABLE_NAME, acc.COLUMN_NAME
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
                ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME AND ac.OWNER = acc.OWNER
            WHERE ac.CONSTRAINT_TYPE = 'P'
        ) pk ON c.OWNER = pk.OWNER AND c.TABLE_NAME = pk.TABLE_NAME AND c.COLUMN_NAME = pk.COLUMN_NAME
        LEFT JOIN (
            SELECT
                acc.OWNER, acc.TABLE_NAME, acc.COLUMN_NAME,
                rac.TABLE_NAME as R_TABLE_NAME, racc.COLUMN_NAME as R_COLUMN_NAME
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
                ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME AND ac.OWNER = acc.OWNER
            JOIN ALL_CONSTRAINTS rac
                ON ac.R_CONSTRAINT_NAME = rac.CONSTRAINT_NAME AND ac.R_OWNER = rac.OWNER
            JOIN ALL_CONS_COLUMNS racc
                ON rac.CONSTRAINT_NAME = racc.CONSTRAINT_NAME AND rac.OWNER = racc.OWNER
            WHERE ac.CONSTRAINT_TYPE = 'R'
        ) fk ON c.OWNER = fk.OWNER AND c.TABLE_NAME = fk.TABLE_NAME AND c.COLUMN_NAME = fk.COLUMN_NAME
        WHERE c.OWNER = '{schema_name}' AND c.TABLE_NAME = '{table_name}'
        ORDER BY c.COLUMN_ID
        """

        df = await self.run_sql(query)
        return [
            ColumnInfo(
                column_name=row["COLUMN_NAME"],
                data_type=row["DATA_TYPE"],
                is_nullable=row["NULLABLE"] == "Y",
                column_default=str(row["DATA_DEFAULT"])
                if pd.notna(row["DATA_DEFAULT"])
                else None,
                is_primary_key=row["IS_PK"] == "Y",
                is_foreign_key=row["IS_FK"] == "Y",
                foreign_table=row["FK_TABLE"] if pd.notna(row["FK_TABLE"]) else None,
                foreign_column=row["FK_COLUMN"] if pd.notna(row["FK_COLUMN"]) else None,
            )
            for _, row in df.iterrows()
        ]

    def apply_row_limit(self, sql: str, limit: int = 1) -> str:
        """Oracle has no LIMIT clause — cap rows with a ROWNUM-wrapped subquery."""
        stripped = sql.strip().rstrip(";")
        return f"SELECT * FROM (\n{stripped}\n) WHERE ROWNUM <= {limit}"

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Get random sample rows from a table."""
        schema_name = self.config.schema_name or self.config.username.upper()
        full_table_name = f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"

        # ROWNUM must be applied AFTER the random ordering (inner subquery),
        # otherwise it grabs the first N rows by storage order and only shuffles
        # those — not a true random sample.
        query = f"""
        SELECT * FROM (
            SELECT * FROM {full_table_name}
            ORDER BY DBMS_RANDOM.VALUE
        )
        WHERE ROWNUM <= {limit}
        """
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        """Get foreign key relationships."""
        schema_name = self.config.schema_name or self.config.username.upper()

        query = f"""
        SELECT
            ac.TABLE_NAME as SOURCE_TABLE,
            acc.COLUMN_NAME as SOURCE_COLUMN,
            rac.TABLE_NAME as TARGET_TABLE,
            racc.COLUMN_NAME as TARGET_COLUMN,
            ac.CONSTRAINT_NAME
        FROM ALL_CONSTRAINTS ac
        JOIN ALL_CONS_COLUMNS acc
            ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME AND ac.OWNER = acc.OWNER
        JOIN ALL_CONSTRAINTS rac
            ON ac.R_CONSTRAINT_NAME = rac.CONSTRAINT_NAME AND ac.R_OWNER = rac.OWNER
        JOIN ALL_CONS_COLUMNS racc
            ON rac.CONSTRAINT_NAME = racc.CONSTRAINT_NAME AND rac.OWNER = racc.OWNER
            AND acc.POSITION = racc.POSITION
        WHERE ac.CONSTRAINT_TYPE = 'R' AND ac.OWNER = '{schema_name}'
        """

        if table_name:
            query += f" AND ac.TABLE_NAME = '{table_name}'"

        df = await self.run_sql(query)
        return df.to_dict("records")

    async def close(self):
        """Close the connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
