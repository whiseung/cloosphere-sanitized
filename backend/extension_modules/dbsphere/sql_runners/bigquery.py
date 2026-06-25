"""BigQuery database runner implementation for DBSphere V2."""

import asyncio
import json
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


class BigQueryRunner(SqlRunnerBase):
    """BigQuery implementation of SqlRunnerBase using google-cloud-bigquery."""

    def __init__(self, config: DBConfig):
        super().__init__(config)
        self._client = None

    def _get_client_sync(self):
        """Get or create synchronous BigQuery client."""
        if self._client is None:
            try:
                from google.cloud import bigquery
            except ImportError:
                raise ImportError(
                    "google-cloud-bigquery is required for BigQuery support. "
                    "Install with: pip install google-cloud-bigquery"
                )

            if self.config.use_adc:
                # Application Default Credentials: GOOGLE_APPLICATION_CREDENTIALS,
                # `gcloud auth application-default login`, or the GCP metadata
                # server. Passing no credentials lets the client resolve ADC.
                project = self.config.project_id
                if not project:
                    raise ValueError(
                        "project_id is required for BigQuery ADC connection"
                    )
                try:
                    self._client = bigquery.Client(project=project)
                except Exception as e:
                    raise ValueError(
                        f"Failed to authenticate with Google Cloud via ADC: {e} "
                        "(ADC not configured — set GOOGLE_APPLICATION_CREDENTIALS, "
                        "run 'gcloud auth application-default login', or run on GCP "
                        "with a service account)"
                    )
            else:
                if not self.config.credentials_json:
                    raise ValueError(
                        "credentials_json is required for BigQuery connection"
                    )
                from google.oauth2 import service_account

                credentials_info = json.loads(self.config.credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info
                )
                project = self.config.project_id or credentials_info.get("project_id")
                if not project:
                    raise ValueError(
                        "project_id must be set or present in the service account JSON"
                    )
                self._client = bigquery.Client(project=project, credentials=credentials)
        return self._client

    @property
    def _dataset_id(self) -> str:
        return self.config.dataset_id or self.config.schema_name or ""

    @property
    def _project(self) -> str:
        client = self._get_client_sync()
        return client.project

    def _fully_qualified_table(self, table_name: str) -> str:
        """Return `dataset.table` (project is implicit from client)."""
        dataset = self._dataset_id
        if dataset and "." not in table_name:
            return f"`{dataset}`.`{table_name}`"
        return f"`{table_name}`"

    async def run_sql(self, sql: str) -> pd.DataFrame:
        def _execute():
            client = self._get_client_sync()
            query_job = client.query(sql)
            result = query_job.result()
            return result.to_dataframe()

        return await asyncio.to_thread(_execute)

    async def test_connection(self) -> bool:
        try:
            df = await self.run_sql("SELECT 1 AS test")
            return len(df) > 0
        except Exception:
            logger.exception("BigQuery test_connection failed")
            raise

    async def get_schema_info(self) -> str:
        dataset = self._dataset_id
        if not dataset:
            return "No dataset specified."

        query = f"""
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default
        FROM `{dataset}`.INFORMATION_SCHEMA.COLUMNS c
        JOIN `{dataset}`.INFORMATION_SCHEMA.TABLES t
            ON c.table_name = t.table_name
            AND c.table_schema = t.table_schema
        WHERE t.table_type = 'BASE TABLE'
        ORDER BY c.table_name, c.ordinal_position
        """

        df = await self.run_sql(query)
        if df.empty:
            return f"No tables found in dataset {dataset}."

        tables: Dict[str, List[str]] = {}
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

        ddl_parts = []
        for table_name, cols in tables.items():
            columns_str = ",\n".join(cols)
            ddl_parts.append(
                f"CREATE TABLE `{dataset}`.`{table_name}` (\n{columns_str}\n);"
            )

        return "\n\n".join(ddl_parts)

    async def get_all_tables(self) -> List[TableInfo]:
        dataset = self._dataset_id
        if not dataset:
            return []

        query = f"""
        SELECT
            table_name,
            table_schema,
            table_type
        FROM `{dataset}`.INFORMATION_SCHEMA.TABLES
        WHERE table_type = 'BASE TABLE'
        ORDER BY table_name
        """

        df = await self.run_sql(query)
        return [
            TableInfo(
                table_name=row["table_name"],
                schema_name=row["table_schema"],
                table_type=row["table_type"],
            )
            for _, row in df.iterrows()
        ]

    async def get_table_ddl(self, table_name: str) -> str:
        dataset = self._dataset_id
        if not dataset:
            return f"-- No dataset specified for table {table_name}"

        query = f"""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM `{dataset}`.INFORMATION_SCHEMA.COLUMNS
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
        """

        df = await self.run_sql(query)
        if df.empty:
            return f"-- Table `{dataset}`.`{table_name}` not found"

        col_defs = []
        for _, row in df.iterrows():
            col_def = f"  `{row['column_name']}` {row['data_type']}"
            if row["is_nullable"] == "NO":
                col_def += " NOT NULL"
            if pd.notna(row.get("column_default")):
                col_def += f" DEFAULT {row['column_default']}"
            col_defs.append(col_def)

        columns_str = ",\n".join(col_defs)
        return f"CREATE TABLE `{dataset}`.`{table_name}` (\n{columns_str}\n);"

    async def get_table_columns(self, table_name: str) -> List[ColumnInfo]:
        dataset = self._dataset_id
        if not dataset:
            return []

        query = f"""
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM `{dataset}`.INFORMATION_SCHEMA.COLUMNS
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
        """

        df = await self.run_sql(query)
        return [
            ColumnInfo(
                column_name=row["column_name"],
                data_type=row["data_type"],
                is_nullable=row["is_nullable"] == "YES",
                column_default=str(row["column_default"])
                if pd.notna(row.get("column_default"))
                else None,
                is_primary_key=False,
                is_foreign_key=False,
            )
            for _, row in df.iterrows()
        ]

    async def get_random_samples(
        self,
        table_name: str,
        limit: int = 5,
    ) -> pd.DataFrame:
        fq = self._fully_qualified_table(table_name)
        query = f"SELECT * FROM {fq} LIMIT {limit}"
        return await self.run_sql(query)

    async def get_foreign_key_relationships(
        self,
        table_name: Optional[str] = None,
    ) -> List[Dict]:
        # BigQuery does not enforce foreign key constraints
        return []

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None
