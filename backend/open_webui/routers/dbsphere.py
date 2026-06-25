import asyncio
import logging
from typing import Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.dbsphere import (
    DbSphereForm,
    DbSphereResponse,
    DbSpheres,
    DbSphereUserResponse,
)
from open_webui.models.dbsphere_sql_file import (
    DbSphereSqlFileForm,
    DbSphereSqlFileUpdateForm,
)
from open_webui.models.models import Models
from open_webui.utils.access_control import (
    has_access,
    has_permission_min_level,
)
from open_webui.utils.auth import get_verified_user
from open_webui.utils.crypto import (
    decrypt_value,
    encrypt_value,
    is_encrypted,
    is_masked,
    mask_sensitive_value,
)
from open_webui.utils.license import require_feature
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("dbsphere"))])

# Keep references to background tasks to prevent garbage collection
_background_tasks: Set[asyncio.Task] = set()

############################
# Connection Test Form
############################


class ConnectionTestForm(BaseModel):
    db_type: str
    host: str
    port: int = 0
    database: str = ""
    username: str = ""
    password: str = ""
    # Optional fields for specific databases
    schema_name: Optional[str] = None
    service_name: Optional[str] = None  # Oracle (alternative to SID/database)
    warehouse: Optional[str] = None  # For Snowflake
    account: Optional[str] = None  # For Snowflake
    role: Optional[str] = None  # For Snowflake
    # Databricks specific
    http_path: Optional[str] = None
    catalog: Optional[str] = None
    access_token: Optional[str] = None
    # Azure AD (Synapse, Fabric)
    tenant_id: Optional[str] = None
    # For resolving masked credentials against stored dbsphere
    dbsphere_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    # BigQuery specific
    project_id: Optional[str] = None
    dataset_id: Optional[str] = None
    credentials_json: Optional[str] = None
    use_adc: Optional[bool] = None


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None


class TableInfo(BaseModel):
    name: str
    type: str  # 'TABLE' or 'VIEW'
    schema_name: Optional[str] = None


class TablesListResponse(BaseModel):
    success: bool
    message: str
    tables: list[TableInfo] = []


############################
# Password Encryption Helpers
############################


def encrypt_connection_password(data: Optional[dict]) -> Optional[dict]:
    """Encrypt password in connection data before saving to database."""
    if not data or "connection" not in data:
        return data

    connection = data.get("connection", {})
    if connection and "password" in connection and connection["password"]:
        password = connection["password"]
        # Only encrypt if not already encrypted
        if not is_encrypted(password):
            connection["password"] = encrypt_value(password)
            data["connection"] = connection

    # Encrypt other sensitive fields
    for field in ("access_token", "client_secret", "credentials_json"):
        if connection and field in connection and connection[field]:
            val = connection[field]
            if isinstance(val, str) and not is_encrypted(val):
                connection[field] = encrypt_value(val)
                data["connection"] = connection

    return data


def _strip_adc_service_account(data: Optional[dict]) -> Optional[dict]:
    """When BigQuery ADC is enabled, never persist a service account key.

    Connection data is merged client-side, so an old credentials_json can ride
    along even after the user switches to ADC. Clear it before encryption/save.
    """
    if not data or "connection" not in data:
        return data
    connection = data.get("connection", {})
    if connection.get("use_adc"):
        connection["credentials_json"] = ""
        data["connection"] = connection
    return data


def decrypt_connection_password(data: Optional[dict]) -> Optional[dict]:
    """Decrypt password in connection data for use (internal only, not for API response)."""
    if not data or "connection" not in data:
        return data

    connection = data.get("connection", {})
    if connection and "password" in connection and connection["password"]:
        password = connection["password"]
        # Only decrypt if encrypted
        if is_encrypted(password):
            try:
                connection["password"] = decrypt_value(password)
                data["connection"] = connection
            except ValueError:
                # If decryption fails, leave as is
                log.warning("Failed to decrypt connection password")

    # Decrypt other sensitive fields
    for field in ("access_token", "client_secret", "credentials_json"):
        if connection and field in connection and connection[field]:
            val = connection[field]
            if isinstance(val, str) and is_encrypted(val):
                try:
                    connection[field] = decrypt_value(val)
                    data["connection"] = connection
                except ValueError:
                    log.warning(f"Failed to decrypt connection {field}")

    return data


# Sensitive fields in connection data that should be masked in API responses
_CONNECTION_SENSITIVE_FIELDS = {
    "password",
    "access_token",
    "client_secret",
    "credentials_json",
}


def mask_connection_data(data: Optional[dict]) -> Optional[dict]:
    """Mask sensitive fields in connection data for API response."""
    import copy

    if not data or "connection" not in data:
        return data

    masked = copy.deepcopy(data)
    connection = masked.get("connection", {})
    for field in _CONNECTION_SENSITIVE_FIELDS:
        if field in connection and connection[field]:
            val = connection[field]
            # Decrypt first if still encrypted
            if isinstance(val, str) and is_encrypted(val):
                try:
                    val = decrypt_value(val)
                except ValueError:
                    pass
            if isinstance(val, str) and val:
                connection[field] = mask_sensitive_value(val)
    masked["connection"] = connection
    return masked


def resolve_connection_password(
    new_data: Optional[dict], current_data: Optional[dict]
) -> Optional[dict]:
    """If password in new_data is masked, keep the current (encrypted) value."""
    if not new_data or "connection" not in new_data:
        return new_data
    if not current_data or "connection" not in current_data:
        return new_data

    connection = new_data.get("connection", {})
    cur_connection = current_data.get("connection", {})
    for field in _CONNECTION_SENSITIVE_FIELDS:
        if (
            field in connection
            and isinstance(connection[field], str)
            and is_masked(connection[field])
        ):
            # Keep current value (may be encrypted in DB)
            connection[field] = cur_connection.get(field, "")
    new_data["connection"] = connection
    return new_data


############################
# getDbSpheres
############################


@router.get("/", response_model=list[DbSphereUserResponse])
async def get_dbspheres(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.databases",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    dbspheres = []

    if user.role == "admin":
        dbspheres = DbSpheres.get_dbspheres()
    else:
        dbspheres = DbSpheres.get_dbspheres_by_user_id(user.id, "read")

    return [DbSphereUserResponse(**dbsphere.model_dump()) for dbsphere in dbspheres]


@router.get("/list", response_model=list[DbSphereUserResponse])
async def get_dbsphere_list(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.databases",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    dbspheres = []

    if user.role == "admin":
        dbspheres = DbSpheres.get_dbspheres()
    else:
        dbspheres = DbSpheres.get_dbspheres_by_user_id(user.id, "write")

    return [DbSphereUserResponse(**dbsphere.model_dump()) for dbsphere in dbspheres]


############################
# TestConnection
############################


def _resolve_masked_connection_form(form_data: ConnectionTestForm):
    """Resolve masked credentials in ConnectionTestForm against stored dbsphere."""
    import copy

    if form_data.use_adc:
        # ADC: ignore any (possibly masked) service account key entirely.
        form_data.credentials_json = ""

    if not form_data.dbsphere_id:
        return
    dbsphere = DbSpheres.get_dbsphere_by_id(id=form_data.dbsphere_id)
    if not dbsphere or not dbsphere.data:
        return
    stored = decrypt_connection_password(copy.deepcopy(dbsphere.data))
    conn = stored.get("connection", {})
    if is_masked(form_data.password):
        form_data.password = conn.get("password", "")
    if form_data.access_token and is_masked(form_data.access_token):
        form_data.access_token = conn.get("access_token", "")
    if form_data.credentials_json and is_masked(form_data.credentials_json):
        form_data.credentials_json = conn.get("credentials_json", "")


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(
    form_data: ConnectionTestForm,
    user=Depends(get_verified_user),
):
    """Test database connection with provided credentials"""
    _resolve_masked_connection_form(form_data)

    db_type = form_data.db_type.upper()

    try:
        if db_type == "MYSQL":
            return await _test_mysql_connection(form_data)
        elif db_type == "MSSQL":
            return await _test_mssql_connection(form_data)
        elif db_type == "POSTGRESQL":
            return await _test_postgresql_connection(form_data)
        elif db_type == "SNOWFLAKE":
            return await _test_snowflake_connection(form_data)
        elif db_type == "ORACLE":
            return await _test_oracle_connection(form_data)
        elif db_type == "SQLITE":
            return await _test_sqlite_connection(form_data)
        elif db_type in ("BIGQUERY", "DATABRICKS", "SYNAPSE", "FABRIC"):
            return await _test_runner_connection(form_data, db_type)
        else:
            return ConnectionTestResponse(
                success=False,
                message=f"Unsupported database type: {db_type}",
            )
    except Exception as e:
        log.error(f"Connection test failed: {str(e)}")
        return ConnectionTestResponse(
            success=False,
            message=f"Connection failed: {str(e)}",
        )


@router.post("/{id}/test-connection", response_model=ConnectionTestResponse)
async def test_connection_by_id(
    id: str,
    user=Depends(get_verified_user),
):
    """저장된 DbSphere의 연결을 테스트."""
    import copy

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if not dbsphere.data or "connection" not in dbsphere.data:
        return ConnectionTestResponse(
            success=False,
            message="No connection info configured",
        )

    data = decrypt_connection_password(copy.deepcopy(dbsphere.data))
    conn = data.get("connection", {})

    form_data = ConnectionTestForm(
        db_type=conn.get("db_type", data.get("db_type", "")),
        host=conn.get("host", ""),
        port=conn.get("port", 0),
        database=conn.get("database", ""),
        username=conn.get("username", ""),
        password=conn.get("password", ""),
        schema_name=conn.get("schema_name"),
        warehouse=conn.get("warehouse"),
        account=conn.get("account"),
        role=conn.get("role"),
        http_path=conn.get("http_path"),
        catalog=conn.get("catalog"),
        access_token=conn.get("access_token"),
    )

    return await test_connection(form_data, user)


async def _test_mysql_connection(
    form_data: ConnectionTestForm,
) -> ConnectionTestResponse:
    try:
        import pymysql

        connection = pymysql.connect(
            host=form_data.host,
            port=form_data.port,
            user=form_data.username,
            password=form_data.password,
            database=form_data.database,
            connect_timeout=10,
        )

        cursor = connection.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]

        # Check schema access for extraction
        db_name = form_data.database
        warnings = []
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s",
                (db_name,),
            )
            table_count = cursor.fetchone()[0]
            if table_count == 0:
                warnings.append(f"No tables found in database '{db_name}'.")
        except Exception:
            warnings.append(
                "Cannot access INFORMATION_SCHEMA. Schema extraction may fail."
            )

        cursor.close()
        connection.close()

        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={
                "version": version,
                "db_type": "MySQL",
                "table_count": table_count if not warnings else 0,
                "warnings": warnings,
            },
        )
    except ImportError:
        return ConnectionTestResponse(
            success=False,
            message="MySQL driver (pymysql) is not installed",
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"MySQL connection failed: {str(e)}",
        )


async def _test_mssql_connection(
    form_data: ConnectionTestForm,
) -> ConnectionTestResponse:
    try:
        import pymssql

        connection = pymssql.connect(
            server=form_data.host,
            port=form_data.port,
            user=form_data.username,
            password=form_data.password,
            database=form_data.database,
            login_timeout=10,
        )

        cursor = connection.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]

        # Check schema access for extraction
        schema_name = form_data.schema_name or "dbo"
        warnings = []
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s",
                (schema_name,),
            )
            table_count = cursor.fetchone()[0]
            if table_count == 0:
                warnings.append(f"No tables found in schema '{schema_name}'.")
        except Exception:
            warnings.append(
                "Cannot access INFORMATION_SCHEMA. Schema extraction may fail."
            )

        cursor.close()
        connection.close()

        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={
                "version": version[:100] + "..." if len(version) > 100 else version,
                "db_type": "MSSQL",
                "table_count": table_count if not warnings else 0,
                "warnings": warnings,
            },
        )
    except ImportError:
        return ConnectionTestResponse(
            success=False,
            message="MSSQL driver (pymssql) is not installed",
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"MSSQL connection failed: {str(e)}",
        )


async def _test_postgresql_connection(
    form_data: ConnectionTestForm,
) -> ConnectionTestResponse:
    try:
        import psycopg2

        connection = psycopg2.connect(
            host=form_data.host,
            port=form_data.port,
            user=form_data.username,
            password=form_data.password,
            dbname=form_data.database,
            connect_timeout=10,
        )

        cursor = connection.cursor()
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]

        # Check schema access for extraction
        schema_name = form_data.schema_name or "public"
        warnings = []
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s",
                (schema_name,),
            )
            table_count = cursor.fetchone()[0]
            if table_count == 0:
                warnings.append(f"No tables found in schema '{schema_name}'.")
        except Exception:
            warnings.append(
                "Cannot access information_schema. Schema extraction may fail."
            )

        cursor.close()
        connection.close()

        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={
                "version": version,
                "db_type": "PostgreSQL",
                "table_count": table_count if not warnings else 0,
                "warnings": warnings,
            },
        )
    except ImportError:
        return ConnectionTestResponse(
            success=False,
            message="PostgreSQL driver (psycopg2) is not installed",
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"PostgreSQL connection failed: {str(e)}",
        )


async def _test_snowflake_connection(
    form_data: ConnectionTestForm,
) -> ConnectionTestResponse:
    try:
        import snowflake.connector

        connection = snowflake.connector.connect(
            account=form_data.account or form_data.host,
            user=form_data.username,
            password=form_data.password,
            database=form_data.database,
            warehouse=form_data.warehouse,
            role=form_data.role,
            schema=form_data.schema_name or "PUBLIC",
            login_timeout=10,
        )

        cursor = connection.cursor()
        cursor.execute("SELECT CURRENT_VERSION()")
        version = cursor.fetchone()[0]

        # Check schema access for extraction
        schema_name = form_data.schema_name or "PUBLIC"
        db_name = form_data.database
        warnings = []
        try:
            # db_name qualifies INFORMATION_SCHEMA (an identifier with no bind
            # channel) so it is allow-listed; schema_name is a bound value.
            from extension_modules.dbsphere.sql_runners.base import (
                validate_sql_identifier,
            )

            validate_sql_identifier(db_name, kind="database")
            cursor.execute(
                f"SELECT COUNT(*) FROM {db_name}.INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s",
                (schema_name,),
            )
            table_count = cursor.fetchone()[0]
            if table_count == 0:
                warnings.append(f"No tables found in {db_name}.{schema_name}.")
        except Exception:
            warnings.append(
                "Cannot access INFORMATION_SCHEMA. Schema extraction may fail."
            )

        cursor.close()
        connection.close()

        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={
                "version": version,
                "db_type": "Snowflake",
                "table_count": table_count if not warnings else 0,
                "warnings": warnings,
            },
        )
    except ImportError:
        return ConnectionTestResponse(
            success=False,
            message="Snowflake driver (snowflake-connector-python) is not installed",
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"Snowflake connection failed: {str(e)}",
        )


async def _test_oracle_connection(
    form_data: ConnectionTestForm,
) -> ConnectionTestResponse:
    try:
        import oracledb

        # Prefer service_name (PDB/RAC); fall back to SID via database field.
        target = form_data.service_name or form_data.database
        dsn = f"{form_data.host}:{form_data.port}/{target}"
        connection = oracledb.connect(
            user=form_data.username,
            password=form_data.password,
            dsn=dsn,
        )

        cursor = connection.cursor()
        cursor.execute("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1")
        version = cursor.fetchone()[0]

        # Check schema access for extraction
        schema_name = (form_data.schema_name or form_data.username).upper()
        warnings = []
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM ALL_TABLES WHERE OWNER = :owner",
                owner=schema_name,
            )
            table_count = cursor.fetchone()[0]
            if table_count == 0:
                warnings.append(
                    f"No tables found for schema '{schema_name}'. Check schema name or OWNER permissions."
                )
        except Exception:
            warnings.append(
                f"Cannot access ALL_TABLES for schema '{schema_name}'. Schema extraction may fail."
            )

        cursor.close()
        connection.close()

        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={
                "version": version,
                "db_type": "Oracle",
                "schema": schema_name,
                "table_count": table_count if not warnings else 0,
                "warnings": warnings,
            },
        )
    except ImportError:
        return ConnectionTestResponse(
            success=False,
            message="Oracle driver (oracledb) is not installed",
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"Oracle connection failed: {str(e)}",
        )


async def _test_sqlite_connection(
    form_data: ConnectionTestForm,
) -> ConnectionTestResponse:
    try:
        import sqlite3

        # For SQLite, the database field contains the file path
        connection = sqlite3.connect(form_data.database, timeout=10)

        cursor = connection.cursor()
        cursor.execute("SELECT sqlite_version()")
        version = cursor.fetchone()[0]

        cursor.close()
        connection.close()

        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={"version": version, "db_type": "SQLite"},
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"SQLite connection failed: {str(e)}",
        )


############################
# GetTables
############################


@router.post("/tables", response_model=TablesListResponse)
async def get_tables(
    form_data: ConnectionTestForm,
    user=Depends(get_verified_user),
):
    """Get list of tables and views from the database"""
    _resolve_masked_connection_form(form_data)
    db_type = form_data.db_type.upper()

    try:
        if db_type == "MYSQL":
            return await _get_mysql_tables(form_data)
        elif db_type == "MSSQL":
            return await _get_mssql_tables(form_data)
        elif db_type == "POSTGRESQL":
            return await _get_postgresql_tables(form_data)
        elif db_type == "SNOWFLAKE":
            return await _get_snowflake_tables(form_data)
        elif db_type == "ORACLE":
            return await _get_oracle_tables(form_data)
        elif db_type == "SQLITE":
            return await _get_sqlite_tables(form_data)
        elif db_type in ("BIGQUERY", "DATABRICKS", "SYNAPSE", "FABRIC"):
            return await _get_runner_tables(form_data, db_type)
        else:
            return TablesListResponse(
                success=False,
                message=f"Unsupported database type: {db_type}",
            )
    except Exception as e:
        log.error(f"Get tables failed: {str(e)}")
        return TablesListResponse(
            success=False,
            message=f"Failed to get tables: {str(e)}",
        )


async def _get_mysql_tables(form_data: ConnectionTestForm) -> TablesListResponse:
    try:
        import pymysql

        connection = pymysql.connect(
            host=form_data.host,
            port=form_data.port,
            user=form_data.username,
            password=form_data.password,
            database=form_data.database,
            connect_timeout=10,
        )

        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT TABLE_NAME, TABLE_TYPE
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_TYPE, TABLE_NAME
        """,
            (form_data.database,),
        )

        tables = []
        for row in cursor.fetchall():
            table_type = "VIEW" if row[1] == "VIEW" else "TABLE"
            tables.append(TableInfo(name=row[0], type=table_type))

        cursor.close()
        connection.close()

        return TablesListResponse(
            success=True,
            message=f"Found {len(tables)} tables/views",
            tables=tables,
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"MySQL error: {str(e)}",
        )


async def _get_mssql_tables(form_data: ConnectionTestForm) -> TablesListResponse:
    try:
        import pymssql

        connection = pymssql.connect(
            server=form_data.host,
            port=form_data.port,
            user=form_data.username,
            password=form_data.password,
            database=form_data.database,
            login_timeout=10,
        )

        cursor = connection.cursor()
        schema = form_data.schema_name or "dbo"
        cursor.execute(
            """
            SELECT TABLE_NAME, TABLE_TYPE
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_TYPE, TABLE_NAME
        """,
            (schema,),
        )

        tables = []
        for row in cursor.fetchall():
            table_type = "VIEW" if row[1] == "VIEW" else "TABLE"
            tables.append(TableInfo(name=row[0], type=table_type, schema_name=schema))

        cursor.close()
        connection.close()

        return TablesListResponse(
            success=True,
            message=f"Found {len(tables)} tables/views",
            tables=tables,
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"MSSQL error: {str(e)}",
        )


async def _get_postgresql_tables(form_data: ConnectionTestForm) -> TablesListResponse:
    try:
        import psycopg2

        connection = psycopg2.connect(
            host=form_data.host,
            port=form_data.port,
            user=form_data.username,
            password=form_data.password,
            dbname=form_data.database,
            connect_timeout=10,
        )

        cursor = connection.cursor()
        schema = form_data.schema_name or "public"
        cursor.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_type, table_name
        """,
            (schema,),
        )

        tables = []
        for row in cursor.fetchall():
            table_type = "VIEW" if row[1] == "VIEW" else "TABLE"
            tables.append(TableInfo(name=row[0], type=table_type, schema_name=schema))

        cursor.close()
        connection.close()

        return TablesListResponse(
            success=True,
            message=f"Found {len(tables)} tables/views",
            tables=tables,
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"PostgreSQL error: {str(e)}",
        )


async def _get_snowflake_tables(form_data: ConnectionTestForm) -> TablesListResponse:
    try:
        import snowflake.connector

        connection = snowflake.connector.connect(
            account=form_data.account or form_data.host,
            user=form_data.username,
            password=form_data.password,
            database=form_data.database,
            warehouse=form_data.warehouse,
            role=form_data.role,
            schema=form_data.schema_name or "PUBLIC",
            login_timeout=10,
        )

        cursor = connection.cursor()
        schema = form_data.schema_name or "PUBLIC"

        # SHOW ... IN SCHEMA takes bare identifiers (no bind channel), so the
        # database/schema names are allow-listed to block introspection injection.
        from extension_modules.dbsphere.sql_runners.base import (
            validate_sql_identifier,
        )

        validate_sql_identifier(form_data.database, kind="database")
        validate_sql_identifier(schema, kind="schema")

        # Get tables
        cursor.execute(f"SHOW TABLES IN SCHEMA {form_data.database}.{schema}")
        tables = []
        for row in cursor.fetchall():
            tables.append(TableInfo(name=row[1], type="TABLE", schema_name=schema))

        # Get views
        cursor.execute(f"SHOW VIEWS IN SCHEMA {form_data.database}.{schema}")
        for row in cursor.fetchall():
            tables.append(TableInfo(name=row[1], type="VIEW", schema_name=schema))

        cursor.close()
        connection.close()

        # Sort by type, then name
        tables.sort(key=lambda x: (x.type, x.name))

        return TablesListResponse(
            success=True,
            message=f"Found {len(tables)} tables/views",
            tables=tables,
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"Snowflake error: {str(e)}",
        )


async def _get_oracle_tables(form_data: ConnectionTestForm) -> TablesListResponse:
    try:
        import oracledb

        # Prefer service_name (PDB/RAC); fall back to SID via database field.
        target = form_data.service_name or form_data.database
        dsn = f"{form_data.host}:{form_data.port}/{target}"
        connection = oracledb.connect(
            user=form_data.username,
            password=form_data.password,
            dsn=dsn,
        )

        # Owner schema may differ from the connecting user when the account only
        # holds SELECT grants on another schema (e.g. read-only proxy account).
        # ALL_TABLES / ALL_VIEWS expose every object the user can see; user_objects
        # would hide cross-schema grants entirely.
        owner = (form_data.schema_name or form_data.username).upper()

        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT TABLE_NAME, 'TABLE' AS OBJECT_TYPE
              FROM ALL_TABLES
             WHERE OWNER = :owner
            UNION ALL
            SELECT VIEW_NAME, 'VIEW' AS OBJECT_TYPE
              FROM ALL_VIEWS
             WHERE OWNER = :owner
            ORDER BY 2, 1
            """,
            owner=owner,
        )

        tables = [
            TableInfo(name=row[0], type=row[1], schema_name=owner)
            for row in cursor.fetchall()
        ]

        cursor.close()
        connection.close()

        return TablesListResponse(
            success=True,
            message=f"Found {len(tables)} tables/views in schema '{owner}'",
            tables=tables,
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"Oracle error: {str(e)}",
        )


async def _get_sqlite_tables(form_data: ConnectionTestForm) -> TablesListResponse:
    try:
        import sqlite3

        connection = sqlite3.connect(form_data.database, timeout=10)

        cursor = connection.cursor()
        cursor.execute("""
            SELECT name, type
            FROM sqlite_master
            WHERE type IN ('table', 'view')
            AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
        """)

        tables = []
        for row in cursor.fetchall():
            tables.append(TableInfo(name=row[0], type=row[1].upper()))

        cursor.close()
        connection.close()

        return TablesListResponse(
            success=True,
            message=f"Found {len(tables)} tables/views",
            tables=tables,
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"SQLite error: {str(e)}",
        )


def _form_to_dbconfig(form_data: ConnectionTestForm, db_type: str):
    """Convert ConnectionTestForm to DBConfig for runner-based DB types."""
    from extension_modules.dbsphere.dbsphere_state import DBConfig

    use_adc = bool(form_data.use_adc)
    return DBConfig(
        db_type=db_type.lower(),
        host=form_data.host or "",
        port=form_data.port or 0,
        database=form_data.database or "",
        username=form_data.username or "",
        password=form_data.password or "",
        schema_name=form_data.schema_name,
        warehouse=form_data.warehouse,
        account=form_data.account,
        role=form_data.role,
        http_path=form_data.http_path,
        catalog=form_data.catalog,
        access_token=form_data.access_token,
        tenant_id=form_data.tenant_id,
        client_id=form_data.client_id,
        client_secret=form_data.client_secret,
        project_id=form_data.project_id,
        dataset_id=form_data.dataset_id,
        credentials_json="" if use_adc else form_data.credentials_json,
        use_adc=use_adc,
    )


def _get_runner_for_type(db_config, db_type: str):
    """Get the appropriate SQL runner for a DB type."""
    from extension_modules.dbsphere.sql_runners import (
        BigQueryRunner,
        DatabricksRunner,
        FabricRunner,
        SynapseRunner,
    )

    runners = {
        "BIGQUERY": BigQueryRunner,
        "DATABRICKS": DatabricksRunner,
        "SYNAPSE": SynapseRunner,
        "FABRIC": FabricRunner,
    }
    runner_cls = runners.get(db_type)
    if not runner_cls:
        raise ValueError(f"No runner for: {db_type}")
    return runner_cls(db_config)


async def _test_runner_connection(
    form_data: ConnectionTestForm, db_type: str
) -> ConnectionTestResponse:
    """Test connection using SQL runner (Databricks, Synapse, Fabric)."""
    try:
        db_config = _form_to_dbconfig(form_data, db_type)
        runner = _get_runner_for_type(db_config, db_type)
        try:
            result = await runner.test_connection()
            if result:
                # Check schema access for extraction
                warnings = []
                try:
                    tables = await runner.get_all_tables()
                    table_count = len(tables)
                    if table_count == 0:
                        warnings.append(
                            "No tables found. Check schema/catalog permissions."
                        )
                except Exception:
                    table_count = 0
                    warnings.append("Cannot list tables. Schema extraction may fail.")

                return ConnectionTestResponse(
                    success=True,
                    message="Connection successful",
                    details={
                        "db_type": db_type,
                        "table_count": table_count,
                        "warnings": warnings,
                    },
                )
            return ConnectionTestResponse(
                success=False,
                message=f"{db_type} connection test failed. Check credentials and network access.",
            )
        except Exception as e:
            return ConnectionTestResponse(
                success=False,
                message=f"{db_type} connection error: {str(e)}",
            )
        finally:
            await runner.close()
    except ImportError as e:
        return ConnectionTestResponse(
            success=False,
            message=f"{db_type} driver not installed: {str(e)}",
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"{db_type} connection failed: {str(e)}",
        )


async def _get_runner_tables(
    form_data: ConnectionTestForm, db_type: str
) -> TablesListResponse:
    """Get tables using SQL runner (Databricks, Synapse, Fabric)."""
    try:
        db_config = _form_to_dbconfig(form_data, db_type)
        runner = _get_runner_for_type(db_config, db_type)
        try:
            table_infos = await runner.get_all_tables()
            # Normalize runner table types to the TableInfo contract ('TABLE'/'VIEW').
            # BigQuery INFORMATION_SCHEMA reports 'BASE TABLE', which the frontend's
            # `type === 'TABLE'` filter would otherwise drop.
            tables = [
                TableInfo(
                    name=t.table_name,
                    type="VIEW"
                    if str(getattr(t, "table_type", "")).upper() == "VIEW"
                    else "TABLE",
                )
                for t in table_infos
            ]
            return TablesListResponse(
                success=True,
                message=f"Found {len(tables)} tables/views",
                tables=tables,
            )
        finally:
            await runner.close()
    except ImportError as e:
        return TablesListResponse(
            success=False,
            message=f"{db_type} driver not installed: {str(e)}",
        )
    except Exception as e:
        return TablesListResponse(
            success=False,
            message=f"{db_type} error: {str(e)}",
        )


############################
# CreateNewDbSphere
############################


@router.post("/create", response_model=Optional[DbSphereResponse])
async def create_new_dbsphere(
    request: Request, form_data: DbSphereForm, user=Depends(get_verified_user)
):
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.databases",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )

    if DbSpheres.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    # Encrypt password if present in data
    if form_data.data:
        form_data.data = _strip_adc_service_account(form_data.data)
        form_data.data = encrypt_connection_password(form_data.data)

    dbsphere = DbSpheres.insert_new_dbsphere(user.id, form_data)

    if dbsphere:
        return dbsphere
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create database"),
        )


############################
# GetDbSphereById
############################


@router.get("/{id}", response_model=Optional[DbSphereResponse])
async def get_dbsphere_by_id(id: str, user=Depends(get_verified_user)):
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)

    if dbsphere:
        if (
            user.role == "admin"
            or dbsphere.user_id == user.id
            or has_access(user.id, "read", dbsphere.access_control)
        ):
            # Mask password in response
            response_data = dbsphere.model_dump()
            response_data["data"] = mask_connection_data(response_data.get("data"))
            return DbSphereResponse(**response_data)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# UpdateDbSphereById
############################


@router.post("/{id}/update", response_model=Optional[DbSphereResponse])
async def update_dbsphere_by_id(
    id: str,
    form_data: DbSphereForm,
    user=Depends(get_verified_user),
):
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if DbSpheres.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    # Resolve masked passwords (keep existing encrypted value if masked)
    if form_data.data:
        current_data = dbsphere.data if dbsphere.data else {}
        form_data.data = resolve_connection_password(form_data.data, current_data)
        # Encrypt password before saving
        form_data.data = _strip_adc_service_account(form_data.data)
        form_data.data = encrypt_connection_password(form_data.data)

    dbsphere = DbSpheres.update_dbsphere_by_id(id=id, form_data=form_data)
    if dbsphere:
        # Mask password in response
        response_data = dbsphere.model_dump()
        response_data["data"] = mask_connection_data(response_data.get("data"))
        return DbSphereResponse(**response_data)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to update database"),
        )


############################
# DeleteDbSphereById
############################


@router.get("/{id}/linked-agents")
async def get_linked_agents_by_dbsphere_id(id: str, _user=Depends(get_verified_user)):
    """Return agents (models) that have this dbsphere connected."""
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    models = Models.get_all_models()
    linked = []
    for model in models:
        if not model.meta:
            continue
        meta = model.meta.model_dump() if hasattr(model.meta, "model_dump") else {}
        dbspheres = meta.get("dbspheres", []) or []
        # support both list and single string
        if isinstance(dbspheres, str):
            dbspheres = [dbspheres]
        for db in dbspheres:
            if isinstance(db, dict) and db.get("id") == id:
                linked.append({"id": model.id, "name": model.name})
                break
            elif isinstance(db, str) and db == id:
                linked.append({"id": model.id, "name": model.name})
                break
    return linked


@router.delete("/{id}/delete", response_model=bool)
async def delete_dbsphere_by_id(id: str, user=Depends(get_verified_user)):
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    log.info(f"Deleting database: {id} (name: {dbsphere.name})")

    result = DbSpheres.delete_dbsphere_by_id(id=id)
    return result


############################
# ExtractSchema
############################


class ExtractSchemaForm(BaseModel):
    model_id: Optional[str] = None  # LLM model for generating descriptions
    sample_row_count: int = 5  # Number of sample rows per table
    table_names: Optional[list[str]] = None  # Specific tables to extract (None = all)
    generate_sample_qa: bool = True  # Whether to generate sample Q&A pairs
    clear_existing: bool = True  # Whether to clear existing memory before extraction
    background: bool = (
        True  # Run extraction in background (recommended for large schemas)
    )
    force: bool = False  # Force restart even if extraction is already running


class ExtractionJobStatus(BaseModel):
    """Status of a background extraction job."""

    # "none" | "pending" | "running" | "cancelling" | "cancelled" | "completed" | "failed"
    status: str
    # User pressed Stop — the background loop reads this flag (via DB) at three
    # cooperative checkpoints and aborts. Stored separately from `status` so
    # per-table progress updates never clobber it (and vice versa).
    cancel_requested: bool = False
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    current_table: Optional[str] = None
    # Raw phase key ("extracting" | "saving_ddl" | "generating_qa" | "saving_qa")
    # — UI translates this so the message respects the user's locale.
    current_phase: Optional[str] = None
    tables_total: int = 0
    tables_processed: int = 0
    # Number of tables currently being processed in parallel — exposes the
    # asyncio.gather concurrency so the UI doesn't look "frozen" while the
    # first wave of N tables works in parallel before any completes.
    tables_in_progress: int = 0
    tables_saved: int = 0
    qa_saved: int = 0
    error: Optional[str] = None


class ExtractSchemaResponse(BaseModel):
    success: bool
    # `message` is an English i18n key (with {{var}} placeholders). Frontend
    # passes it through `$i18n.t(message, message_vars)` so the localized
    # text appears with values interpolated. The English text is also the
    # natural fallback when no translation exists.
    message: str
    message_vars: Optional[dict] = None
    tables_processed: int = 0
    tables_saved: int = 0
    qa_saved: int = 0
    deleted_counts: Optional[dict] = None  # Counts of deleted memories by type
    # Background job info
    background: bool = False
    job_status: Optional[ExtractionJobStatus] = None


async def _run_schema_extraction_background(
    app,
    dbsphere_id: str,
    user_id: str,
    form_data: ExtractSchemaForm,
    db_config,
    db_type_name: str,
    embedding_config,
    model_config=None,
):
    """
    Background task for schema extraction.

    Updates extraction_job status in dbsphere.data as it progresses.
    """
    import time

    from extension_modules.dbsphere.memory import (
        MemoryType,
        SchemaExtractor,
        SearchEngineDbSphereMemory,
    )
    from extension_modules.dbsphere.sql_runners import (
        BigQueryRunner,
        DatabricksRunner,
        FabricRunner,
        MSSQLRunner,
        MySQLRunner,
        OracleRunner,
        PostgresRunner,
        SnowflakeRunner,
        SynapseRunner,
    )
    from extension_modules.search_engine.embedding import generate_embedding_async

    def update_job_status(status_update: dict):
        """Update extraction job status in dbsphere.data using atomic operation."""
        try:
            DbSpheres.update_extraction_job_atomic(
                id=dbsphere_id, status_update=status_update
            )
        except Exception as e:
            log.error(f"Failed to update job status: {e}")

    # Cooperative cancellation: the cancel endpoint sets `cancel_requested` in
    # the DB (multi-worker safe — the flag is shared state, unlike an in-memory
    # asyncio task handle). The extractor polls this between tables. Cache the
    # read for ~2s so a many-table run doesn't hammer the DB on every check.
    _cancel_cache = {"value": False, "checked_at": 0.0}

    def should_cancel() -> bool:
        now = time.monotonic()
        if now - _cancel_cache["checked_at"] < 2.0:
            return _cancel_cache["value"]
        try:
            current = DbSpheres.get_dbsphere_by_id(id=dbsphere_id)
            requested = bool(
                ((current.data or {}).get("extraction_job", {}) or {}).get(
                    "cancel_requested"
                )
                if current
                else False
            )
        except Exception as e:
            log.warning(f"Failed to read cancel flag for {dbsphere_id}: {e}")
            requested = _cancel_cache["value"]
        _cancel_cache["value"] = requested
        _cancel_cache["checked_at"] = now
        return requested

    try:
        # Create SQL runner
        from extension_modules.dbsphere.dbsphere_state import DBType

        db_type = db_config.get_db_type_enum()
        runner_map = {
            DBType.POSTGRES: PostgresRunner,
            DBType.MYSQL: MySQLRunner,
            DBType.MSSQL: MSSQLRunner,
            DBType.ORACLE: OracleRunner,
            DBType.SNOWFLAKE: SnowflakeRunner,
            DBType.DATABRICKS: DatabricksRunner,
            DBType.SYNAPSE: SynapseRunner,
            DBType.FABRIC: FabricRunner,
            DBType.BIGQUERY: BigQueryRunner,
        }
        runner_cls = runner_map.get(db_type)

        if runner_cls:
            sql_runner = runner_cls(db_config)
        else:
            update_job_status(
                {
                    "status": "failed",
                    "error": f"Unsupported database type: {db_config.db_type}",
                    "completed_at": int(time.time()),
                }
            )
            return

        # Cancel may arrive in the brief pending→running window. Short-circuit
        # before fetching tables / flipping status to "running" so the UI
        # doesn't flicker "Extracting" back on after the user pressed Stop.
        if should_cancel():
            update_job_status(
                {
                    "status": "cancelled",
                    "cancel_requested": False,
                    "completed_at": int(time.time()),
                }
            )
            log.info(f"Schema extraction cancelled before start for {dbsphere_id}")
            return

        # Get table list
        tables = await sql_runner.get_all_tables()
        table_names = form_data.table_names or [t.table_name for t in tables]
        total_tables = len(table_names)

        update_job_status(
            {
                "status": "running",
                "tables_total": total_tables,
                "tables_processed": 0,
            }
        )

        # Create embedding function
        async def create_embedding(text: str):
            try:
                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=user_id,
                )
            except Exception as e:
                log.error(f"Failed to create embedding: {e}")
                return None

        memory = SearchEngineDbSphereMemory(
            app=app,
            dbsphere_id=dbsphere_id,
            user_id=user_id,
            embedding_func=create_embedding,
        )

        # Clear existing memories if requested.
        # PARTIAL EXTRACT: when the user specified table_names, we only purge
        # memories for THOSE tables — other tables' DDL / Q&A / docs are
        # preserved. Previously this branch deleted everything regardless,
        # which silently wiped prior extractions when the user came back to
        # extract a different table set.
        # FULL EXTRACT (no table_names): purge everything as before.
        if form_data.clear_existing:
            try:
                if form_data.table_names:
                    for name in form_data.table_names:
                        await memory.delete_memories_by_table_name(name)
                    log.info(
                        f"Cleared memories for {len(form_data.table_names)} tables "
                        f"in dbsphere {dbsphere_id}: {form_data.table_names}"
                    )
                else:
                    await memory.delete_all_memories(
                        include_types=[
                            MemoryType.DDL_SCHEMA,
                            MemoryType.SQL_MEMORY,
                            MemoryType.DOCUMENTATION,
                        ]
                    )
                    log.info(f"Cleared all memories for dbsphere {dbsphere_id}")
            except Exception as e:
                log.warning(f"Failed to clear existing memories: {e}")

        # Create extractor (model_config pre-resolved from request context)
        extractor = SchemaExtractor(
            sql_runner=sql_runner,
            model_config=model_config,
            sample_row_count=form_data.sample_row_count,
            user_id=user_id,
        )

        # Progress callback with extended signature.
        # Sends raw `table_name` + `phase` so the frontend can apply
        # i18n on the user's selected locale. (Previously this string was
        # hardcoded Korean which leaked into English UI.)
        def progress_callback(
            table_name: str,
            current: int,
            total: int,
            phase: str = "extracting",
            ddl_saved: int = 0,
            qa_saved: int = 0,
            in_progress: int = 0,
        ):
            update_job_status(
                {
                    "current_table": table_name,
                    "current_phase": phase,
                    "tables_processed": current,
                    "tables_in_progress": in_progress,
                    "tables_saved": ddl_saved,
                    "qa_saved": qa_saved,
                }
            )

        # Extract and save
        extraction_result = await extractor.extract_and_save_to_memory(
            memory=memory,
            table_names=table_names,
            metadata={"user_id": user_id},
            generate_sample_qa=form_data.generate_sample_qa,
            db_type=db_type_name,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

        # Cancelled mid-run: mark terminal state and skip the success writeback
        # (last_extracted_at / schema_summary). Partial DDL that was already
        # saved stays, but the extraction must not masquerade as a full success.
        if isinstance(extraction_result, dict) and extraction_result.get("cancelled"):
            update_job_status(
                {
                    "status": "cancelled",
                    "cancel_requested": False,
                    "completed_at": int(time.time()),
                    "current_table": None,
                    "current_phase": None,
                    "tables_in_progress": 0,
                    "tables_saved": extraction_result.get("ddl_saved", 0),
                    "qa_saved": extraction_result.get("qa_saved", 0),
                }
            )
            log.info(f"Schema extraction cancelled for {dbsphere_id}")
            try:
                from open_webui.socket.main import send_notification_to_user

                cancelled_db = DbSpheres.get_dbsphere_by_id(id=dbsphere_id)
                cancelled_name = cancelled_db.name if cancelled_db else "Unknown"
                await send_notification_to_user(
                    user_id=user_id,
                    event_type="schema-extraction-cancelled",
                    data={
                        "dbsphere_id": dbsphere_id,
                        "dbsphere_name": cancelled_name,
                        "tables_saved": extraction_result.get("ddl_saved", 0),
                        "message": f"Schema extraction for '{cancelled_name}' was cancelled.",
                    },
                )
            except Exception as e:
                log.warning(f"Failed to send cancellation notification: {e}")
            return

        # Handle result
        if isinstance(extraction_result, dict):
            tables_saved = extraction_result.get("ddl_saved", 0)
            qa_saved = extraction_result.get("qa_saved", 0)
        else:
            tables_saved = extraction_result
            qa_saved = 0

        # Generate schema summary and table overview over the FULL extraction set
        # S. The join_graph recompute already reloaded the whole DDL set and merged
        # this batch into full_table_details, so summary/overview describe the
        # entire dbsphere (not just this — possibly partial — batch). join_graph
        # itself was already rendered by the recompute orchestrator.
        schema_summary = None
        table_overview = None
        if isinstance(extraction_result, dict):
            table_details = extraction_result.get(
                "full_table_details"
            ) or extraction_result.get("table_details", [])
            join_graph = extraction_result.get("join_graph")
            join_graph_truncated = extraction_result.get("join_graph_truncated", False)
        else:
            table_details = []
            join_graph = None
            join_graph_truncated = False
        if table_details:
            table_overview = extractor.generate_table_overview(table_details)
            if form_data.model_id:
                update_job_status({"current_table": "데이터베이스 요약 생성 중"})
                try:
                    schema_summary = await extractor.generate_schema_summary(
                        table_details
                    )
                    if schema_summary:
                        log.info(
                            f"Generated schema summary for dbsphere {dbsphere_id} ({len(schema_summary)} chars)"
                        )
                except Exception as e:
                    log.warning(f"Failed to generate schema summary: {e}")

        # Update final status
        update_job_status(
            {
                "status": "completed",
                "completed_at": int(time.time()),
                "tables_processed": total_tables,
                "tables_saved": tables_saved,
                "qa_saved": qa_saved,
                "current_table": None,
            }
        )

        # Persist last_extracted_at + full-S schema_summary/table_overview/join_graph
        # via an atomic top-level merge (P-M2: race-safe vs concurrent
        # extraction_job/CRUD writes; preserves extraction_job — already set
        # "completed" above through update_extraction_job_atomic — and connection).
        # Replaces the old whole-replace + extraction_job status fix-up, which is
        # unnecessary now that the merge never touches extraction_job.
        dbsphere = DbSpheres.get_dbsphere_by_id(id=dbsphere_id)
        dbsphere_name = dbsphere.name if dbsphere else "Unknown"
        if dbsphere:
            DbSpheres.update_dbsphere_data_atomic(
                id=dbsphere_id,
                partial={
                    "last_extracted_at": int(time.time()),
                    "schema_summary": schema_summary,
                    "table_overview": table_overview,
                    "join_graph": join_graph,
                    "join_graph_truncated": join_graph_truncated,
                },
            )

        log.info(
            f"Background schema extraction completed for {dbsphere_id}: "
            f"{tables_saved} DDL, {qa_saved} Q&A"
        )

        # Send completion notification via Socket.IO
        from open_webui.socket.main import send_notification_to_user

        await send_notification_to_user(
            user_id=user_id,
            event_type="schema-extraction-completed",
            data={
                "dbsphere_id": dbsphere_id,
                "dbsphere_name": dbsphere_name,
                "tables_saved": tables_saved,
                "qa_saved": qa_saved,
                "message": f"Schema extraction for '{dbsphere_name}' completed. ({tables_saved} tables)",
            },
        )

    except Exception as e:
        log.error(f"Background schema extraction failed: {e}")
        update_job_status(
            {
                "status": "failed",
                "error": str(e),
                "completed_at": int(time.time()),
            }
        )

        # Send failure notification via Socket.IO
        try:
            from open_webui.socket.main import send_notification_to_user

            dbsphere = DbSpheres.get_dbsphere_by_id(id=dbsphere_id)
            dbsphere_name = dbsphere.name if dbsphere else "Unknown"

            await send_notification_to_user(
                user_id=user_id,
                event_type="schema-extraction-failed",
                data={
                    "dbsphere_id": dbsphere_id,
                    "dbsphere_name": dbsphere_name,
                    "error": str(e),
                    "message": f"Schema extraction for '{dbsphere_name}' failed: {str(e)}",
                },
            )
        except Exception as notify_error:
            log.error(f"Failed to send failure notification: {notify_error}")

    finally:
        # Cleanup SQL runner connection
        try:
            if sql_runner:
                await sql_runner.close()
        except Exception:
            pass


@router.post("/{id}/extract-schema", response_model=ExtractSchemaResponse)
async def extract_schema(
    request: Request,
    id: str,
    form_data: ExtractSchemaForm,
    user=Depends(get_verified_user),
):
    """
    Extract schema information and save to memory.

    If model_id is provided, uses LLM to generate table/column descriptions
    and sample Q&A pairs for few-shot learning.
    Otherwise, saves basic DDL without descriptions.

    If background is True (default), runs extraction in background and returns immediately.
    Use GET /{id}/extraction-status to check progress.
    """
    import asyncio
    import time

    from extension_modules.dbsphere.dbsphere_state import DBConfig, DBType

    # Get DbSphere
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Check access
    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Get connection config
    data = dbsphere.data
    if not data or "connection" not in data:
        return ExtractSchemaResponse(
            success=False,
            message="Database connection not configured",
        )

    data = decrypt_connection_password(data)
    db_config = DBConfig.from_dbsphere_data(data)

    # Validate DB type
    db_type = db_config.get_db_type_enum()
    db_type_name_map = {
        DBType.POSTGRES: "PostgreSQL",
        DBType.MYSQL: "MySQL",
        DBType.MSSQL: "MSSQL",
        DBType.ORACLE: "Oracle",
        DBType.SNOWFLAKE: "Snowflake",
        DBType.DATABRICKS: "Databricks",
        DBType.SYNAPSE: "Synapse",
        DBType.FABRIC: "Fabric",
        DBType.BIGQUERY: "BigQuery",
    }
    db_type_name = db_type_name_map.get(db_type)
    if not db_type_name:
        return ExtractSchemaResponse(
            success=False,
            message=f"Unsupported database type: {db_config.db_type}",
        )

    # Get embedding config
    from extension_modules.search_engine.embedding import get_embedding_config_from_app

    embedding_config = get_embedding_config_from_app(request.app)

    # Check if extraction is already running
    current_job = (dbsphere.data or {}).get("extraction_job", {})
    if current_job.get("status") == "running":
        started_at = current_job.get("started_at", 0)
        elapsed = int(time.time()) - started_at if started_at else 0

        if form_data.force:
            # 강제 리셋
            log.warning(f"Force resetting extraction job for {id} (elapsed {elapsed}s)")
            DbSpheres.update_extraction_job_atomic(
                id=id,
                status_update={
                    "status": "failed",
                    "error": "강제 리셋됨",
                    "completed_at": int(time.time()),
                },
            )
        elif elapsed > max(600, current_job.get("tables_total", 0) * 120):
            # 최소 10분 + 테이블당 2분 (DDL 추출 + Q&A 생성, 예: 50테이블 → 100분)
            log.warning(
                f"Stale extraction job detected for {id} "
                f"(started {elapsed}s ago), resetting"
            )
            DbSpheres.update_extraction_job_atomic(
                id=id,
                status_update={
                    "status": "failed",
                    "error": "Job timed out after 5 minutes",
                    "completed_at": int(time.time()),
                },
            )
        else:
            return ExtractSchemaResponse(
                success=False,
                message="Schema extraction is already running ({{elapsed}}s elapsed). Try again to force restart.",
                message_vars={"elapsed": elapsed},
                background=True,
                job_status=ExtractionJobStatus(**current_job),
            )

    if form_data.background:
        # Initialize job status
        # table_names가 지정된 경우 선택된 테이블 수를 미리 설정
        initial_tables_total = (
            len(form_data.table_names) if form_data.table_names else 0
        )
        job_status = {
            "status": "pending",
            "cancel_requested": False,
            "started_at": int(time.time()),
            "completed_at": None,
            "current_table": None,
            "tables_total": initial_tables_total,
            "tables_processed": 0,
            "tables_saved": 0,
            "qa_saved": 0,
            "error": None,
        }

        # Save initial status
        DbSpheres.update_dbsphere_data_by_id(
            id=id,
            data={
                **(dbsphere.data or {}),
                "extraction_job": job_status,
            },
        )

        # Pre-resolve model config (MODELS may be empty in background)
        pre_resolved_model_config = None
        if form_data.model_id:
            from extension_modules.utils.llm import (
                get_model_config_from_app,
                model_config_has_credentials,
            )

            pre_resolved_model_config = get_model_config_from_app(
                request.app, form_data.model_id
            )
            # Vertex AI 모델은 top-level api_key 가 없고 ADC/service_account_key/
            # use_global_gcp_key 로 인증한다. api_key 만 보면 Vertex 모델이 전부
            # 막히므로 provider 별 검증 헬퍼를 사용한다.
            if pre_resolved_model_config and not model_config_has_credentials(
                pre_resolved_model_config
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The selected model has no usable credentials configured. Set an API key or Vertex AI credentials in Admin Settings > Connections.",
                )

        # Start background task (keep reference to prevent GC)
        task = asyncio.create_task(
            _run_schema_extraction_background(
                app=request.app,
                dbsphere_id=id,
                user_id=user.id,
                form_data=form_data,
                db_config=db_config,
                db_type_name=db_type_name,
                embedding_config=embedding_config,
                model_config=pre_resolved_model_config,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return ExtractSchemaResponse(
            success=True,
            message="Schema extraction started in the background. Check progress at the top of the page.",
            tables_processed=initial_tables_total,
            background=True,
            job_status=ExtractionJobStatus(**job_status),
        )

    # Synchronous execution (background=False)
    from extension_modules.dbsphere.memory import (
        MemoryType,
        SchemaExtractor,
        SearchEngineDbSphereMemory,
    )
    from extension_modules.dbsphere.sql_runners import (
        BigQueryRunner,
        DatabricksRunner,
        FabricRunner,
        MSSQLRunner,
        MySQLRunner,
        OracleRunner,
        PostgresRunner,
        SnowflakeRunner,
        SynapseRunner,
    )
    from extension_modules.search_engine.embedding import generate_embedding_async

    # Create SQL runner
    runner_map = {
        DBType.POSTGRES: PostgresRunner,
        DBType.MYSQL: MySQLRunner,
        DBType.MSSQL: MSSQLRunner,
        DBType.ORACLE: OracleRunner,
        DBType.SNOWFLAKE: SnowflakeRunner,
        DBType.DATABRICKS: DatabricksRunner,
        DBType.SYNAPSE: SynapseRunner,
        DBType.FABRIC: FabricRunner,
        DBType.BIGQUERY: BigQueryRunner,
    }
    runner_cls = runner_map.get(db_type)
    if not runner_cls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported database type: {db_config.db_type}",
        )
    sql_runner = runner_cls(db_config)

    async def create_embedding(text: str):
        try:
            return await generate_embedding_async(
                text=text,
                config=embedding_config,
                user_id=user.id,
            )
        except Exception as e:
            log.error(f"Failed to create embedding: {e}")
            return None

    memory = SearchEngineDbSphereMemory(
        app=request.app,
        dbsphere_id=id,
        user_id=user.id,
        embedding_func=create_embedding,
    )

    # Clear existing memories if requested.
    # PARTIAL EXTRACT: when the user specified table_names, only purge memories
    # for THOSE tables (preserves prior extractions of other tables). The bug
    # this guards against: user extracts table A, returns later to extract
    # table B only, and silently loses A's memory.
    deleted_counts: Optional[dict] = None
    if form_data.clear_existing:
        try:
            if form_data.table_names:
                aggregated: dict = {}
                for name in form_data.table_names:
                    per_table = await memory.delete_memories_by_table_name(name)
                    for k, v in (per_table or {}).items():
                        aggregated[k] = aggregated.get(k, 0) + v
                deleted_counts = aggregated
                log.info(
                    f"Cleared memories for {len(form_data.table_names)} tables "
                    f"in dbsphere {id}: {deleted_counts}"
                )
            else:
                deleted_counts = await memory.delete_all_memories(
                    include_types=[
                        MemoryType.DDL_SCHEMA,
                        MemoryType.SQL_MEMORY,
                        MemoryType.DOCUMENTATION,
                    ]
                )
                log.info(f"Cleared all memories for dbsphere {id}: {deleted_counts}")
        except Exception as e:
            log.warning(f"Failed to clear existing memories: {e}")

    # Get model config if model_id provided
    model_config = None
    if form_data.model_id:
        from extension_modules.utils.llm import (
            get_model_config_from_app,
            model_config_has_credentials,
        )

        model_config = get_model_config_from_app(request.app, form_data.model_id)
        if not model_config:
            log.warning(
                f"Model not found: {form_data.model_id}, proceeding without LLM"
            )
        elif not model_config_has_credentials(model_config):
            # Vertex AI 모델은 api_key 가 없고 ADC/service_account_key 로 인증하므로
            # provider 별 검증 헬퍼로 판정한다.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="선택한 모델에 사용 가능한 자격 증명이 없습니다. 관리자 설정 > 연결에서 API 키 또는 Vertex AI 자격 증명을 설정해주세요.",
            )

    extractor = SchemaExtractor(
        sql_runner=sql_runner,
        model_config=model_config,
        sample_row_count=form_data.sample_row_count,
        user_id=user.id,
    )

    try:
        extraction_result = await extractor.extract_and_save_to_memory(
            memory=memory,
            table_names=form_data.table_names,
            metadata={"user_id": user.id},
            generate_sample_qa=form_data.generate_sample_qa,
            db_type=db_type_name,
        )

        if isinstance(extraction_result, dict):
            tables_saved = extraction_result.get("ddl_saved", 0)
            qa_saved = extraction_result.get("qa_saved", 0)
        else:
            tables_saved = extraction_result
            qa_saved = 0

        # Generate schema summary and table overview
        schema_summary = None
        table_overview = None
        # Full-S summary/overview (see background path) + join_graph from recompute.
        if isinstance(extraction_result, dict):
            table_details = extraction_result.get(
                "full_table_details"
            ) or extraction_result.get("table_details", [])
            join_graph = extraction_result.get("join_graph")
            join_graph_truncated = extraction_result.get("join_graph_truncated", False)
        else:
            table_details = []
            join_graph = None
            join_graph_truncated = False
        if table_details:
            table_overview = extractor.generate_table_overview(table_details)
            if form_data.model_id:
                try:
                    schema_summary = await extractor.generate_schema_summary(
                        table_details
                    )
                except Exception as e:
                    log.warning(f"Failed to generate schema summary: {e}")

        # Atomic top-level merge (race-safe; preserves extraction_job/connection).
        DbSpheres.update_dbsphere_data_atomic(
            id=id,
            partial={
                "last_extracted_at": int(time.time()),
                "schema_summary": schema_summary,
                "table_overview": table_overview,
                "join_graph": join_graph,
                "join_graph_truncated": join_graph_truncated,
            },
        )

        tables = await sql_runner.get_all_tables()
        tables_processed = (
            len(form_data.table_names) if form_data.table_names else len(tables)
        )

        message_parts = [f"Successfully extracted schema for {tables_saved} tables"]
        if qa_saved > 0:
            message_parts.append(f"{qa_saved} sample Q&A pairs generated")

        return ExtractSchemaResponse(
            success=True,
            message=", ".join(message_parts),
            tables_processed=tables_processed,
            tables_saved=tables_saved,
            qa_saved=qa_saved,
            deleted_counts=deleted_counts,
            background=False,
        )

    except Exception as e:
        log.error(f"Schema extraction failed: {e}")
        return ExtractSchemaResponse(
            success=False,
            message=f"Schema extraction failed: {str(e)}",
        )

    finally:
        # Cleanup SQL runner connection
        try:
            if sql_runner:
                await sql_runner.close()
        except Exception:
            pass


############################
# GetExtractionStatus
############################


@router.get("/{id}/extraction-status", response_model=ExtractionJobStatus)
async def get_extraction_status(
    id: str,
    user=Depends(get_verified_user),
):
    """Get the status of schema extraction job."""
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Check access
    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    job_status = (dbsphere.data or {}).get("extraction_job", {})
    if not job_status:
        return ExtractionJobStatus(status="none")

    return ExtractionJobStatus(**job_status)


@router.post("/{id}/extract-schema/cancel", response_model=ExtractionJobStatus)
async def cancel_extraction(
    id: str,
    user=Depends(get_verified_user),
):
    """Request cancellation of a running schema extraction.

    Sets a `cancel_requested` flag on the job status (atomic, row-locked). The
    background task reads this flag at cooperative checkpoints and aborts. The
    flag does not interrupt an in-flight LLM call, so cancellation confirms once
    the currently-processing tables finish their current step.
    """
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Cancelling mutates the job → require write access (matches extract-schema).
    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    job_status = (dbsphere.data or {}).get("extraction_job", {})
    if job_status.get("status") not in ("pending", "running", "cancelling"):
        # Nothing to cancel — return current status unchanged.
        return (
            ExtractionJobStatus(**job_status)
            if job_status
            else ExtractionJobStatus(status="none")
        )

    updated = DbSpheres.update_extraction_job_atomic(
        id=id,
        status_update={"cancel_requested": True, "status": "cancelling"},
    )
    log.info(f"Cancellation requested for extraction job {id} by user {user.id}")

    updated_job = (
        (updated.data or {}).get("extraction_job", {}) if updated else job_status
    )
    return ExtractionJobStatus(**updated_job)


############################
# GetExtractedTables
############################


class ExtractedTableInfo(BaseModel):
    """Information about an extracted table."""

    table_name: str
    schema_name: Optional[str] = None
    description: Optional[str] = None
    column_count: int = 0
    has_relationships: bool = False
    extracted_at: Optional[str] = None


class ExtractedTablesResponse(BaseModel):
    """Response containing list of extracted tables."""

    success: bool
    tables: list[ExtractedTableInfo] = []
    total_count: int = 0
    last_extracted_at: Optional[int] = None


@router.get("/{id}/extracted-tables", response_model=ExtractedTablesResponse)
async def get_extracted_tables(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
):
    """Get list of tables that have been extracted to memory."""
    from extension_modules.dbsphere.memory import (
        SearchEngineDbSphereMemory,
    )

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Check access
    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        # Create memory instance (no embedding needed for read)
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        # Get all DDL schemas from memory
        ddl_memories = await memory.get_table_schemas()

        tables = []
        for ddl in ddl_memories:
            tables.append(
                ExtractedTableInfo(
                    table_name=ddl.table_name,
                    schema_name=ddl.schema_name,
                    description=ddl.table_description,
                    column_count=len(ddl.columns) if ddl.columns else 0,
                    has_relationships=bool(ddl.relationships),
                    extracted_at=ddl.timestamp,
                )
            )

        # Sort by table name
        tables.sort(key=lambda x: x.table_name)

        return ExtractedTablesResponse(
            success=True,
            tables=tables,
            total_count=len(tables),
            last_extracted_at=(dbsphere.data or {}).get("last_extracted_at"),
        )

    except Exception as e:
        log.error(f"Failed to get extracted tables: {e}")
        return ExtractedTablesResponse(
            success=False,
            tables=[],
            total_count=0,
        )


############################
# GetJoinGraph (relationship panel #4/#5)
############################


class JoinGraphColumn(BaseModel):
    name: str
    data_type: Optional[str] = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_table: Optional[str] = None
    foreign_column: Optional[str] = None
    is_nullable: bool = True


class JoinGraphNode(BaseModel):
    table: str
    schema_name: Optional[str] = None
    column_count: int = 0
    columns: list[JoinGraphColumn] = []
    role: str = "unclassified"
    role_confidence: Optional[str] = None  # 'high' (verified) | 'likely' (inferred)
    as_target: int = 0
    as_source: int = 0
    self_ref: bool = False


class JoinGraphEdge(BaseModel):
    source_table: str
    source_columns: list[str] = []
    target_table: str
    target_columns: list[str] = []
    relationship_type: str  # 'verified_fk' | 'inferred_name'
    confidence: float = 0.0


class RelationshipGraphResponse(BaseModel):
    """Relationship graph for the connection's extracted schema."""

    success: bool
    nodes: list[JoinGraphNode] = []
    edges: list[JoinGraphEdge] = []
    truncated: bool = False  # schema fetch cap hit (graph + roles incomplete)
    extracted: bool = (
        False  # False = never extracted (vs extracted-but-no-relationships)
    )


@router.get("/{id}/join-graph", response_model=RelationshipGraphResponse)
async def get_join_graph(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
):
    """Relationship graph for a DB connection (read-only, side-effect-free).

    Edges are parsed from the persisted ``data.join_graph`` markdown — the exact
    view the agent is injected with, so the panel and the agent never disagree.
    Nodes (tables + columns + PK/FK) come from DDL memory, and a soft
    fact/dimension/bridge role is inferred from join directionality. This GET
    deliberately does NOT call ``_recompute_join_graph`` (that purges the legacy
    relationship doc — a write side-effect); it only reads.
    """
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory
    from extension_modules.dbsphere.memory.schema_extractor import (
        _infer_table_roles,
        build_join_graph_struct,
        parse_join_graph,
        reconstruct_table_details,
    )
    from extension_modules.dbsphere.memory.search_memory import DDL_SCHEMA_FETCH_LIMIT

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Row-level read access — matches the get_extracted_tables sibling
    # (owner / access_control read / admin). Per-resource reads are row-level
    # only by convention; the workspace.databases feature gate is applied on the
    # collection list endpoints, not here.
    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )
        ddl_memories = await memory.get_table_schemas()
        truncated = len(ddl_memories) >= DDL_SCHEMA_FETCH_LIMIT
        full_details = reconstruct_table_details(ddl_memories)

        if not full_details:
            # Never extracted (no DDL memory). Distinct from "extracted but no
            # relationships found" (extracted=True, empty edges) so the FE can
            # show the right empty-state copy.
            return RelationshipGraphResponse(
                success=True, nodes=[], edges=[], truncated=False, extracted=False
            )

        edges = parse_join_graph((dbsphere.data or {}).get("join_graph"))
        roles = _infer_table_roles(edges, full_details, truncated=truncated)
        schema_map = {ddl.table_name.lower(): ddl.schema_name for ddl in ddl_memories}
        struct = build_join_graph_struct(
            edges, full_details, roles, schema_map=schema_map
        )

        return RelationshipGraphResponse(
            success=True,
            nodes=struct["nodes"],
            edges=struct["edges"],
            truncated=truncated,
            extracted=True,
        )
    except Exception as e:
        log.error(f"Failed to build join graph for {id}: {e}")
        return RelationshipGraphResponse(
            success=False, nodes=[], edges=[], truncated=False, extracted=False
        )


############################
# DeleteAllExtractedTables / DeleteExtractedTable
############################


class DeleteExtractedTableResponse(BaseModel):
    success: bool
    message: str
    deleted_counts: Optional[dict] = None


@router.delete("/{id}/extracted-tables", response_model=DeleteExtractedTableResponse)
async def delete_all_extracted_tables(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
):
    """Delete all extracted memories (DDL, SQL examples, etc.) for a dbsphere."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        deleted_counts = await memory.delete_all_memories()
        total_deleted = sum(deleted_counts.values())

        # Clear schema_summary + join_graph (Option C invariant: relationships are
        # a pure function of the current extraction set S — on full clear S=∅, so
        # no stale edges may survive). Atomic top-level merge (row-locked) — matches
        # the extract paths and avoids clobbering a concurrent extract's
        # extraction_job/connection/join_graph with a stale whole-replace snapshot.
        DbSpheres.update_dbsphere_data_atomic(
            id=id,
            partial={
                "schema_summary": None,
                "join_graph": None,
                "join_graph_truncated": None,
            },
        )

        return DeleteExtractedTableResponse(
            success=True,
            message=f"Deleted {total_deleted} memories for dbsphere '{id}'",
            deleted_counts=deleted_counts,
        )

    except Exception as e:
        log.error(f"Failed to delete all extracted tables for dbsphere {id}: {e}")
        return DeleteExtractedTableResponse(
            success=False,
            message=f"Failed to delete all: {str(e)}",
        )


@router.delete(
    "/{id}/extracted-tables/{table_name}", response_model=DeleteExtractedTableResponse
)
async def delete_extracted_table(
    request: Request,
    id: str,
    table_name: str,
    user=Depends(get_verified_user),
):
    """Delete a specific table's memories (DDL schema and related sample Q&A)."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        deleted_counts = await memory.delete_memories_by_table_name(table_name)
        total_deleted = sum(deleted_counts.values())

        # E1: delete_memories_by_table_name skips DOCUMENTATION, so purge the
        # legacy fixed-id relationship doc explicitly (idempotent, Option C). The
        # full clear path (delete_all_memories) already covers DOCUMENTATION.
        await memory.delete_relationship_graph_doc()

        if total_deleted > 0:
            # Invalidate schema_summary + join_graph since the table set S changed
            # (both rebuilt on the next extract). Atomic top-level merge (row-locked)
            # — matches the extract paths and avoids clobbering a concurrent extract's
            # extraction_job/connection/join_graph with a stale whole-replace snapshot.
            DbSpheres.update_dbsphere_data_atomic(
                id=id,
                partial={
                    "schema_summary": None,
                    "join_graph": None,
                    "join_graph_truncated": None,
                },
            )

        return DeleteExtractedTableResponse(
            success=True,
            message=f"Deleted {total_deleted} memories for table '{table_name}'",
            deleted_counts=deleted_counts,
        )

    except Exception as e:
        log.error(f"Failed to delete extracted table {table_name}: {e}")
        return DeleteExtractedTableResponse(
            success=False,
            message=f"Failed to delete table: {str(e)}",
        )


############################
# Memory Management
############################


class MemoryItem(BaseModel):
    memory_id: str
    entity_type: str
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: Optional[str] = None
    # 참조(주입) 통계 — sql_memory 에만 채워진다. use_count 는 "주입 이벤트 수"이지
    # LLM 실사용/품질 지표가 아니다(다중 주입 경로로 inflation, 오염은 high-use 위장).
    use_count: Optional[int] = None
    last_used_at: Optional[int] = None
    # 생성자 이메일 — metadata.user_id 를 해석. 자동저장 few-shot 의 경우 채팅 질문을 한
    # 사용자의 이메일이다(legacy 도 user_id 가 있어 표시 가능).
    user_email: Optional[str] = None
    # 생성자 표시값 — schema_extraction/ddl_schema 출신은 "system", 그 외는 이메일.
    creator: Optional[str] = None
    # 최종수정자(이메일)·최종수정일(ISO) — 수정 이력 없으면 None.
    last_modified_by: Optional[str] = None
    last_modified_at: Optional[str] = None


class MemoryListResponse(BaseModel):
    success: bool
    memories: list[MemoryItem] = []
    total_count: int = 0
    has_more: bool = False


class UnusedMemoryItem(BaseModel):
    memory_id: str
    content: str
    sql: Optional[str] = None
    origin: Optional[str] = None
    created_at: Optional[str] = None


class UnusedMemoryResponse(BaseModel):
    success: bool
    memories: list[UnusedMemoryItem] = []
    total_count: int = 0
    # trust-window 충족 여부 — False 면 "아직 참조 데이터가 충분히 쌓이지 않음"(거짓 flag 차단).
    logging_ready: bool = False
    grace_days: int = 180


class BulkDeleteForm(BaseModel):
    memory_ids: list[str]


class BulkDeleteResponse(BaseModel):
    success: bool
    deleted: int = 0
    failed: list[str] = Field(default_factory=list)


class MemoryCreateForm(BaseModel):
    entity_type: str  # sql_memory | documentation | sql_example
    question: Optional[str] = None  # sql_memory
    sql: Optional[str] = None  # sql_memory, sql_example
    content: Optional[str] = None  # documentation
    doc_type: Optional[str] = "context"  # documentation
    title: Optional[str] = None  # documentation
    description: Optional[str] = None  # sql_example
    related_tables: Optional[list[str]] = None
    related_columns: Optional[list[str]] = None
    use_case: Optional[str] = None
    tags: Optional[list[str]] = None


class MemoryUpdateForm(BaseModel):
    content: Optional[str] = None
    metadata: Optional[dict] = None


class MemoryStatsResponse(BaseModel):
    success: bool
    counts: dict = Field(default_factory=dict)
    total: int = 0
    schema_summary: Optional[str] = None
    table_overview: Optional[str] = None


class SummaryUpdateForm(BaseModel):
    schema_summary: Optional[str] = None
    table_overview: Optional[str] = None


def _doc_to_memory_item(doc) -> MemoryItem:
    """Convert a DocumentItem to a MemoryItem response."""
    metadata = doc.metadata or {}
    return MemoryItem(
        memory_id=doc.id,
        entity_type=metadata.get("entity_type", ""),
        content=doc.content or "",
        metadata=metadata,
        created_at=metadata.get("created_at"),
    )


def _iso_to_epoch(value) -> Optional[int]:
    """ISO8601 문자열 → epoch(int). 파싱 불가/None 이면 None.

    few-shot 의 created_at 은 datetime.now(timezone.utc).isoformat() 형식.
    """
    if not value:
        return None
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(value).timestamp())
    except (ValueError, TypeError):
        return None


def _compute_unused_candidates(
    docs,
    used_ids: set,
    logging_active_since: Optional[int],
    now: int,
    grace_days: int,
) -> tuple[bool, list["UnusedMemoryItem"]]:
    """미사용 few-shot 후보 계산 (순수 함수 — 단위테스트 대상).

    - trust-window 게이트: 로깅 누적이 grace 미만이면 (False, []) — 거짓 flag 차단.
    - 후보 = 벡터인덱스 docs 중 used_ids 에 없고(anti-join) created_at < (now-grace) 인 것.
    - created_at 파싱 불가/누락이면 나이를 확정 못하므로 제외(보수적).
    """
    grace = max(0, grace_days) * 86400
    logging_ready = (
        logging_active_since is not None and (now - logging_active_since) >= grace
    )
    if not logging_ready:
        return False, []

    cutoff = now - grace
    out: list[UnusedMemoryItem] = []
    for doc in docs:
        if doc.id in used_ids:
            continue
        meta = doc.metadata or {}
        created_raw = meta.get("created_at")
        created_ts = _iso_to_epoch(created_raw)
        if created_ts is None or created_ts >= cutoff:
            continue
        out.append(
            UnusedMemoryItem(
                memory_id=doc.id,
                content=doc.content or "",
                sql=meta.get("sql_query"),
                origin=meta.get("origin"),
                created_at=created_raw,
            )
        )
    return True, out


@router.get("/{id}/memories", response_model=MemoryListResponse)
async def get_memories(
    request: Request,
    id: str,
    type: Optional[str] = None,
    limit: int = 200,
    user=Depends(get_verified_user),
):
    """Get memories for a dbsphere, optionally filtered by type."""
    from extension_modules.dbsphere.memory import MemoryType, SearchEngineDbSphereMemory

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        memory_type = None
        if type:
            try:
                memory_type = MemoryType(type)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid memory type: {type}",
                )

        docs = await memory.list_memories_by_type(
            memory_type=memory_type,
            limit=limit + 1,  # Fetch one extra to check has_more
        )

        has_more = len(docs) > limit
        items = [_doc_to_memory_item(doc) for doc in docs[:limit]]

        # sql_memory 항목에 참조(주입) 횟수·마지막참조 부착 (dbsphere 스코핑).
        sql_ids = [
            it.memory_id
            for it in items
            if it.entity_type == MemoryType.SQL_MEMORY.value
        ]
        if sql_ids:
            from open_webui.models.dbsphere_memory_usage import DbsphereMemoryUsages

            usage = DbsphereMemoryUsages.get_usage_counts(id, memory_ids=sql_ids)
            for it in items:
                if it.entity_type == MemoryType.SQL_MEMORY.value:
                    u = usage.get(it.memory_id)
                    it.use_count = u["use_count"] if u else 0
                    it.last_used_at = u["last_used_at"] if u else None

        # 생성자/최종수정자 이메일 부착 + creator(system/email) 계산.
        # user_id(생성자)와 updated_by(수정자)를 unique 단위로 한 번씩만 해석(배치).
        uids: set = set()
        for it in items:
            if it.metadata.get("user_id"):
                uids.add(it.metadata["user_id"])
            if it.metadata.get("updated_by"):
                uids.add(it.metadata["updated_by"])
        email_map: dict[str, str] = {}
        if uids:
            from open_webui.models.users import Users

            # 단일 IN 쿼리로 일괄 해석 (목록 1회 로드당 DB 왕복 1회).
            for u in Users.get_users_by_user_ids(list(uids)):
                if u.email:
                    email_map[u.id] = u.email

        # ddl_schema 와 schema_extraction 출신은 시스템 생성물 → "system".
        SYSTEM_ORIGINS = {"schema_extraction"}
        for it in items:
            md = it.metadata or {}
            uid = md.get("user_id")
            it.user_email = email_map.get(uid) if uid else None
            if (
                it.entity_type == MemoryType.DDL_SCHEMA.value
                or md.get("origin") in SYSTEM_ORIGINS
                or md.get("source") in SYSTEM_ORIGINS
            ):
                it.creator = "system"
            else:
                it.creator = it.user_email
            ub = md.get("updated_by")
            it.last_modified_by = email_map.get(ub) if ub else None
            it.last_modified_at = md.get("updated_at")

        return MemoryListResponse(
            success=True,
            memories=items,
            total_count=len(items),
            has_more=has_more,
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get memories: {e}")
        return MemoryListResponse(success=False)


@router.get("/{id}/memories/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
):
    """Get memory statistics for a dbsphere."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        mem = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        counts = await mem.count_memories_by_type()
        total = sum(counts.values())

        data = dbsphere.data or {}
        return MemoryStatsResponse(
            success=True,
            counts=counts,
            total=total,
            schema_summary=data.get("schema_summary"),
            table_overview=data.get("table_overview"),
        )

    except Exception as e:
        log.error(f"Failed to get memory stats: {e}")
        return MemoryStatsResponse(success=False)


@router.get("/{id}/memories/unused", response_model=UnusedMemoryResponse)
async def get_unused_memories(
    request: Request,
    id: str,
    grace_days: int = 180,
    user=Depends(get_verified_user),
):
    """한 번도 참조(주입)되지 않은 sql_memory few-shot 후보 목록 (수동 정리용).

    판정(false-positive 방어):
    - 후보 집합은 벡터인덱스의 전체 sql_memory 에서 열거하고, usage 테이블의 distinct
      memory_id 에 left-anti-join (usage 는 미사용 row 가 구조적으로 부재).
    - trust-window: 로깅이 grace 기간 미만으로 쌓였으면 신호를 신뢰하지 않고 빈 목록을
      반환(logging_ready=False) — 배포 직후/저활동 dbsphere 의 거짓 flag 차단.
    - grace: 갓 등록된 few-shot 은 아직 매칭 질문이 안 들어왔을 수 있어 created_at 컷오프.
    절대 자동삭제하지 않는다 — 호출자(UI)가 검토 후 bulk-delete 한다.

    스코핑: 후보는 list_memories_by_type 의 tenant 격리(_sql_memory_row_visible)를 따른다.
    즉 비-admin 은 본인 소유(+schema_extraction) few-shot 만 미사용 후보로 본다. dbsphere
    전체 정리는 admin/owner 가 수행. (used_ids 는 전 사용자 기준이라 오삭제 위험은 없음.)
    """
    import time

    from extension_modules.dbsphere.memory import MemoryType, SearchEngineDbSphereMemory
    from open_webui.models.dbsphere_memory_usage import DbsphereMemoryUsages

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    grace_days = max(0, grace_days)
    now = int(time.time())

    try:
        logging_active_since = DbsphereMemoryUsages.get_logging_active_since(id)
        # trust-window 미충족이면 검색 엔진 조회도 생략(빈 목록).
        grace = grace_days * 86400
        if logging_active_since is None or (now - logging_active_since) < grace:
            return UnusedMemoryResponse(
                success=True,
                memories=[],
                total_count=0,
                logging_ready=False,
                grace_days=grace_days,
            )

        memory = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )
        docs = await memory.list_memories_by_type(
            memory_type=MemoryType.SQL_MEMORY,
            limit=1000,
        )
        used_ids = DbsphereMemoryUsages.get_used_memory_ids(id)

        logging_ready, candidates = _compute_unused_candidates(
            docs, used_ids, logging_active_since, now, grace_days
        )

        return UnusedMemoryResponse(
            success=True,
            memories=candidates,
            total_count=len(candidates),
            logging_ready=logging_ready,
            grace_days=grace_days,
        )

    except Exception as e:
        log.error(f"Failed to get unused memories: {e}")
        return UnusedMemoryResponse(success=False, grace_days=grace_days)


@router.get("/{id}/memories/{memory_id}")
async def get_memory_by_id(
    request: Request,
    id: str,
    memory_id: str,
    user=Depends(get_verified_user),
):
    """Get a single memory by ID."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        mem = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        doc = await mem.get_memory_by_id(memory_id)
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )

        return _doc_to_memory_item(doc)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{id}/memories/create", response_model=MemoryItem)
async def create_memory(
    request: Request,
    id: str,
    form_data: MemoryCreateForm,
    user=Depends(get_verified_user),
):
    """Manually create a memory item."""
    from extension_modules.dbsphere.memory import MemoryType, SearchEngineDbSphereMemory
    from extension_modules.search_engine.embedding import (
        generate_embedding_async,
        get_embedding_config_from_app,
    )

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Validate entity_type
    allowed_types = [
        MemoryType.SQL_MEMORY.value,
        MemoryType.DOCUMENTATION.value,
        MemoryType.SQL_EXAMPLE.value,
    ]
    if form_data.entity_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {', '.join(allowed_types)} can be manually created",
        )

    try:
        embedding_config = get_embedding_config_from_app(request.app)

        async def create_embedding(text: str):
            try:
                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=user.id,
                )
            except Exception as e:
                log.error(f"Failed to create embedding: {e}")
                return None

        mem = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
            embedding_func=create_embedding,
        )

        result = None
        if form_data.entity_type == MemoryType.SQL_MEMORY.value:
            if not form_data.question or not form_data.sql:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="question and sql are required for sql_memory",
                )
            result = await mem.save_sql_memory(
                question=form_data.question,
                sql=form_data.sql,
                metadata={"user_id": user.id, "origin": "user_manual"},
            )
            if result:
                return MemoryItem(
                    memory_id=result.memory_id,
                    entity_type=MemoryType.SQL_MEMORY.value,
                    content=result.question,
                    metadata={
                        "entity_type": MemoryType.SQL_MEMORY.value,
                        "sql_query": result.sql,
                        "created_at": result.timestamp,
                        "user_id": user.id,
                        # 생성 직후 낙관적 UI 갱신에서도 배지가 뜨도록 응답에 포함(M-S2-2).
                        "origin": "user_manual",
                    },
                    created_at=result.timestamp,
                )

        elif form_data.entity_type == MemoryType.DOCUMENTATION.value:
            if not form_data.content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="content is required for documentation",
                )
            result = await mem.save_documentation(
                content=form_data.content,
                doc_type=form_data.doc_type or "context",
                title=form_data.title,
                related_tables=form_data.related_tables,
                related_columns=form_data.related_columns,
                metadata={"user_id": user.id, "origin": "user_manual"},
            )
            if result:
                return MemoryItem(
                    memory_id=result.memory_id,
                    entity_type=MemoryType.DOCUMENTATION.value,
                    content=result.content,
                    metadata={
                        "entity_type": MemoryType.DOCUMENTATION.value,
                        "doc_type": result.doc_type,
                        "title": result.title,
                        "created_at": result.timestamp,
                        "user_id": user.id,
                        "origin": "user_manual",
                    },
                    created_at=result.timestamp,
                )

        elif form_data.entity_type == MemoryType.SQL_EXAMPLE.value:
            if not form_data.sql or not form_data.description:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="sql and description are required for sql_example",
                )
            result = await mem.save_sql_example(
                sql=form_data.sql,
                description=form_data.description,
                use_case=form_data.use_case,
                related_tables=form_data.related_tables,
                tags=form_data.tags,
                metadata={"user_id": user.id},
            )
            if result:
                return MemoryItem(
                    memory_id=result.memory_id,
                    entity_type=MemoryType.SQL_EXAMPLE.value,
                    content=result.description,
                    metadata={
                        "entity_type": MemoryType.SQL_EXAMPLE.value,
                        "sql_query": result.sql,
                        "description": result.description,
                        "use_case": result.use_case,
                        "created_at": result.timestamp,
                        "user_id": user.id,
                    },
                    created_at=result.timestamp,
                )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create memory",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to create memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{id}/memories/{memory_id}/update")
async def update_memory(
    request: Request,
    id: str,
    memory_id: str,
    form_data: MemoryUpdateForm,
    user=Depends(get_verified_user),
):
    """Update a memory's content and/or metadata."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory
    from extension_modules.search_engine.embedding import (
        generate_embedding_async,
        get_embedding_config_from_app,
    )

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        embedding_config = get_embedding_config_from_app(request.app)

        async def create_embedding(text: str):
            try:
                return await generate_embedding_async(
                    text=text,
                    config=embedding_config,
                    user_id=user.id,
                )
            except Exception as e:
                log.error(f"Failed to create embedding: {e}")
                return None

        mem = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
            embedding_func=create_embedding,
        )

        # 최종수정자/최종수정일 스탬프 — 이름은 가변이라 user_id(이메일 해석용)로 기록.
        from datetime import datetime, timezone

        meta_updates = dict(form_data.metadata or {})
        meta_updates["updated_by"] = user.id
        meta_updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        success = await mem.update_memory(
            memory_id=memory_id,
            content=form_data.content,
            metadata_updates=meta_updates,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory not found or update failed",
            )

        # Return updated memory
        doc = await mem.get_memory_by_id(memory_id)
        if doc:
            return _doc_to_memory_item(doc)

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to update memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{id}/memories/{memory_id}")
async def delete_memory_by_id(
    request: Request,
    id: str,
    memory_id: str,
    user=Depends(get_verified_user),
):
    """Delete a single memory by ID."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        mem = SearchEngineDbSphereMemory(
            app=request.app,
            dbsphere_id=id,
            user_id=user.id,
        )

        success = await mem.delete_memory(memory_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Memory not found",
            )

        # 삭제된 메모리의 참조 로그도 정리(고아 행 방지). best-effort.
        try:
            from open_webui.models.dbsphere_memory_usage import DbsphereMemoryUsages

            DbsphereMemoryUsages.delete_by_memory_ids(id, [memory_id])
        except Exception as e:
            log.warning(f"usage rows cleanup failed: {e}")

        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete memory: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{id}/memories/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_memories(
    request: Request,
    id: str,
    form_data: BulkDeleteForm,
    user=Depends(get_verified_user),
):
    """memory_id 목록을 일괄 삭제 (미사용 정리 UI 의 검토 후 삭제용). 쓰기 권한."""
    from extension_modules.dbsphere.memory import SearchEngineDbSphereMemory
    from open_webui.models.dbsphere_memory_usage import DbsphereMemoryUsages

    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # 직접 호출 시 대량 입력으로 인덱스를 장시간 점유하지 않도록 상한. 정상 UI 흐름은
    # unused 후보(limit=1000)로 이미 바운드됨.
    memory_ids = [m for m in (form_data.memory_ids or []) if m][:1000]
    if not memory_ids:
        return BulkDeleteResponse(success=True, deleted=0)

    mem = SearchEngineDbSphereMemory(
        app=request.app,
        dbsphere_id=id,
        user_id=user.id,
    )

    deleted_ids: list[str] = []
    failed: list[str] = []
    for mid in memory_ids:
        try:
            if await mem.delete_memory(mid):
                deleted_ids.append(mid)
            else:
                failed.append(mid)
        except Exception as e:
            log.warning(f"bulk-delete failed for {mid}: {e}")
            failed.append(mid)

    # 삭제 성공분의 참조 로그 정리.
    if deleted_ids:
        try:
            DbsphereMemoryUsages.delete_by_memory_ids(id, deleted_ids)
        except Exception as e:
            log.warning(f"usage rows cleanup failed (bulk): {e}")

    return BulkDeleteResponse(
        success=True,
        deleted=len(deleted_ids),
        failed=failed,
    )


@router.post("/{id}/memories/summary/update")
async def update_summary(
    id: str,
    form_data: SummaryUpdateForm,
    user=Depends(get_verified_user),
):
    """Update schema_summary and/or table_overview."""
    dbsphere = DbSpheres.get_dbsphere_by_id(id=id)
    if not dbsphere:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        updated_data = {**(dbsphere.data or {})}
        if form_data.schema_summary is not None:
            updated_data["schema_summary"] = form_data.schema_summary
        if form_data.table_overview is not None:
            updated_data["table_overview"] = form_data.table_overview

        DbSpheres.update_dbsphere_data_by_id(id=id, data=updated_data)
        return {"success": True}

    except Exception as e:
        log.error(f"Failed to update summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


############################
# SQL Editor — direct execute + .sql files (PR1 backend)
############################
#
# 신규 namespace `/{id}/sql/...` — 기존 `/{id}/...` 엔드포인트와 충돌 없음 (B0.5
# 확인 완료). 모든 엔드포인트는 router prefix `/api/v1/dbsphere` 아래.
#
# 권한 모델 (resolution Q6 + H2):
# - 진입 (READ 실행, file CRUD): `workspace.databases` read + dbsphere row read access
# - WRITE 실행: dbsphere row write access AND `data.allow_data_modifications=True`
# - admin: ACL 만 bypass — 안전 토글 (allow_data_modifications) 은 honor
#
# 사용 컴포넌트: services/dbsphere_executor.py (B5), utils/dbsphere_approval.py (B3),
# extension_modules/dbsphere/sql_classifier.py (B4), models/dbsphere_sql_file.py (B2).


class SqlExecuteForm(BaseModel):
    sql: str = Field(min_length=1)


class SqlExecuteResponse(BaseModel):
    """Union 응답 — READ 면 result, WRITE 면 pending. 둘 중 하나만 채워짐."""

    op: str  # 'READ' / 'WRITE'
    # READ 결과 (op='READ' 일 때)
    result_id: Optional[str] = None
    columns: Optional[list[str]] = None
    rows: Optional[list[list]] = None
    row_count: Optional[int] = None
    total_row_count: Optional[int] = None
    truncated: Optional[bool] = None
    exec_ms: Optional[int] = None
    affected_rows: Optional[int] = None
    message: Optional[str] = None
    # WRITE pending (op='WRITE' 일 때)
    pending: Optional[dict] = None  # {result_id, sql, expires_in_s, affected_preview}


def _check_dbsphere_read_access(dbsphere, user, request: Request) -> None:
    """진입 권한: feature read + (admin || owner || row read access)."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.databases",
        "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    if (
        user.role != "admin"
        and dbsphere.user_id != user.id
        and not has_access(user.id, "read", dbsphere.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _check_dbsphere_write_access(dbsphere, user, request: Request) -> None:
    """WRITE 권한: feature write + (admin || owner || row write access)."""
    if user.role != "admin" and not has_permission_min_level(
        user.id,
        "workspace.databases",
        "write",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    if (
        user.role != "admin"
        and dbsphere.user_id != user.id
        and not has_access(user.id, "write", dbsphere.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


def _get_dbsphere_or_404(id: str):
    dbsphere = DbSpheres.get_dbsphere_by_id(id)
    if dbsphere is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    return dbsphere


def _result_to_response(result, op: str) -> dict:
    return {
        "op": op,
        "result_id": result.result_id,
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "total_row_count": result.total_row_count,
        "truncated": result.truncated,
        "exec_ms": result.exec_ms,
        "affected_rows": result.affected_rows,
        "message": result.message,
        "pending": None,
    }


def _pending_to_response(pending) -> dict:
    return {
        "op": "WRITE",
        "result_id": None,
        "columns": None,
        "rows": None,
        "row_count": None,
        "total_row_count": None,
        "truncated": None,
        "exec_ms": None,
        "affected_rows": None,
        "message": None,
        "pending": {
            "result_id": pending.result_id,
            "sql": pending.sql,
            "affected_preview": pending.affected_preview,
            "expires_in_s": pending.expires_in_s,
        },
    }


@router.post("/{id}/sql/execute", response_model=SqlExecuteResponse)
async def execute_sql(
    id: str,
    form_data: SqlExecuteForm,
    request: Request,
    user=Depends(get_verified_user),
):
    """단일 SQL statement 실행. READ 는 즉시 결과, WRITE 는 pending 후 confirm 필요."""
    from extension_modules.dbsphere.sql_classifier import (
        StmtClass,
        classify_statement,
    )
    from open_webui.services.dbsphere_executor import (
        ExecutorError,
        execute_sql_for_user,
    )

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_read_access(dbsphere, user, request)

    # ACL gate must precede the executor — otherwise a WRITE classify would
    # register a pending key in Redis before the 401 fires, leaving an orphan
    # entry until TTL expiry. Pre-classify here and reject WRITE without
    # write-access before any state mutation.
    if classify_statement(form_data.sql) is not StmtClass.READ:
        _check_dbsphere_write_access(dbsphere, user, request)

    try:
        result, pending = await execute_sql_for_user(
            dbsphere, form_data.sql, user.id, is_admin=(user.role == "admin")
        )
    except ExecutorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    if result is not None:
        return _result_to_response(result, op="READ")
    if pending is not None:
        return _pending_to_response(pending)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Executor returned neither result nor pending",
    )


@router.post("/{id}/sql/execute/{result_id}/confirm", response_model=SqlExecuteResponse)
async def confirm_sql_execution(
    id: str,
    result_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """DML/DDL 사용자 승인 → 실제 실행. 410 시 prior result 조회 후 200 반환 (C2)."""
    from open_webui.services.dbsphere_executor import (
        ExecutorError,
        commit_pending,
        find_prior_result,
    )

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_write_access(dbsphere, user, request)

    try:
        result = await commit_pending(dbsphere, result_id, user.id)
    except ExecutorError as e:
        if e.code == "pending_gone":
            # C2: 더블클릭 / 만료 — audit_log 에서 prior 조회. 있으면 200 + 결과 메타, 없으면 410.
            prior = find_prior_result(dbsphere.id, user.id, result_id)
            if prior is not None:
                return {
                    "op": "WRITE",
                    "result_id": result_id,
                    "columns": None,
                    "rows": None,
                    "row_count": None,
                    "total_row_count": None,
                    "truncated": None,
                    "exec_ms": prior.get("exec_ms"),
                    "affected_rows": prior.get("affected_rows"),
                    "message": "Already executed.",
                    "pending": None,
                }
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return _result_to_response(result, op="WRITE")


class RejectResponse(BaseModel):
    success: bool


@router.post("/{id}/sql/execute/{result_id}/reject", response_model=RejectResponse)
async def reject_sql_execution(
    id: str,
    result_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """DML/DDL 사용자 거부 — Redis pending 삭제 + audit_log SQL_REJECTED."""
    from open_webui.services.dbsphere_executor import ExecutorError, reject_pending

    dbsphere = _get_dbsphere_or_404(id)
    # Reject 도 write 권한 가진 사용자만 (자신이 등록한 pending 만 취소).
    _check_dbsphere_write_access(dbsphere, user, request)

    try:
        reject_pending(dbsphere, result_id, user.id)
    except ExecutorError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"success": True}


############################
# SQL Editor — .sql files (multi-tab persistence)
############################


@router.get("/{id}/sql/files", response_model=list)
async def list_sql_files(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """사용자가 이 DbSphere 에 저장한 .sql 파일 목록. user_id 소유 (공유 X)."""
    from open_webui.models.dbsphere_sql_file import DbSphereSqlFiles

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_read_access(dbsphere, user, request)
    files = DbSphereSqlFiles.get_sql_files_by_dbsphere_and_user(dbsphere.id, user.id)
    return [f.model_dump() for f in files]


@router.post("/{id}/sql/files")
async def create_sql_file(
    id: str,
    request: Request,
    form_data: DbSphereSqlFileForm,
    user=Depends(get_verified_user),
):
    """새 .sql 파일 생성. 256KB 본문 cap 은 Pydantic validator 가 강제."""
    from open_webui.models.dbsphere_sql_file import DbSphereSqlFiles

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_read_access(dbsphere, user, request)
    created = DbSphereSqlFiles.insert_new_sql_file(dbsphere.id, user.id, form_data)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create SQL file"),
        )
    return created.model_dump()


@router.get("/{id}/sql/files/{file_id}")
async def get_sql_file(
    id: str,
    file_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    from open_webui.models.dbsphere_sql_file import DbSphereSqlFiles

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_read_access(dbsphere, user, request)
    f = DbSphereSqlFiles.get_sql_file_by_id(file_id)
    if not f or f.dbsphere_id != dbsphere.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if f.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return f.model_dump()


@router.patch("/{id}/sql/files/{file_id}")
async def update_sql_file(
    id: str,
    file_id: str,
    request: Request,
    form_data: DbSphereSqlFileUpdateForm,
    user=Depends(get_verified_user),
):
    """이름/본문 부분 갱신. `expected_updated_at` 매치 안 하면 409 + 서버 copy."""
    from open_webui.models.dbsphere_sql_file import DbSphereSqlFiles

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_read_access(dbsphere, user, request)

    updated, err = DbSphereSqlFiles.update_sql_file_by_id(file_id, user.id, form_data)
    if err == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if err == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if err == "conflict":
        # 409 with server copy — UI 가 비교/머지 결정.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "message": "This file was modified elsewhere",
                "server": updated.model_dump() if updated else None,
            },
        )
    return updated.model_dump() if updated else None


@router.delete("/{id}/sql/files/{file_id}", response_model=bool)
async def delete_sql_file(
    id: str,
    file_id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    from open_webui.models.dbsphere_sql_file import DbSphereSqlFiles

    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_read_access(dbsphere, user, request)
    deleted, err = DbSphereSqlFiles.delete_sql_file_by_id(file_id, user.id)
    if err == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND
        )
    if err == "forbidden":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    return bool(deleted)


############################
# SQL Editor — allow_data_modifications toggle (P-H5 atomic merge)
############################


class AllowModificationsForm(BaseModel):
    allow: bool


@router.post("/{id}/sql/allow-modifications", response_model=DbSphereResponse)
async def set_allow_data_modifications(
    id: str,
    form_data: AllowModificationsForm,
    request: Request,
    user=Depends(get_verified_user),
):
    """`data.allow_data_modifications` 토글을 atomic merge 로 변경.

    write 권한 필요 (admin 도 ACL bypass 만, feature gate 는 honor).
    """
    dbsphere = _get_dbsphere_or_404(id)
    _check_dbsphere_write_access(dbsphere, user, request)
    updated = DbSpheres.update_dbsphere_data_atomic(
        id, {"allow_data_modifications": bool(form_data.allow)}
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to update toggle"),
        )
    return updated


# NOTE: Tool Description AI generate 는 신규 endpoint 추가 X.
# 기존 흐름 그대로 재사용 — `ToolDescriptionSection.svelte` 의 ✦ AI 버튼 →
# `DbSphereDetail.svelte::aiGenerateToolDescription` → `POST /api/v1/tasks/generate`
# (범용 LLM 생성 endpoint). 응답을 `meta.tool_description` 에 저장.
#
# 같은 패턴이 KB/Tools/Glossary/KG/DbSphere 5리소스에 일관 적용 — 별 endpoint 만들면
# 컨벤션 위반 (critique P-C1). 프롬프트 server-side 이동 / 쿨다운 / token logging 같은
# "보강"은 별 follow-up PR 에서 5리소스 공통으로 처리.


############################
# SQL Editor — admin audit reconciliation (B10)
############################
#
# SQL_PENDING audit row 를 작성한 워커가 final row 작성 전에 죽으면 audit 갭이
# 생긴다 (Redis 키는 이미 사라져 재실행도 불가). admin 이 on-demand 로 호출해
# orphan 을 가시화 + SQL_UNKNOWN 으로 명시 마킹.
#
# 1차는 scheduled janitor 대신 admin endpoint. 실제 orphan 이 운영에서 누적되면
# 2차에 task_queue / APScheduler 기반 자동 reconcile 추가 검토.


class OrphanPendingItem(BaseModel):
    result_id: str
    dbsphere_id: Optional[str] = None
    user_id: Optional[str] = None
    sql_preview: str = ""
    op: str = "WRITE"
    created_at: int
    age_s: int


class OrphanPendingResponse(BaseModel):
    items: list[OrphanPendingItem]
    threshold_s: int


@router.get("/sql/admin/orphan-pending", response_model=OrphanPendingResponse)
async def get_orphan_pending(
    request: Request,
    older_than_seconds: int = 60,
    limit: int = 200,
    user=Depends(get_verified_user),
):
    """SQL_PENDING audit row 중 final (COMMITTED/FAILED/REJECTED/UNKNOWN) 매칭 없는
    orphan 목록을 반환. admin 전용 — 운영 감사용."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    from open_webui.services.dbsphere_executor import find_orphan_pending

    items = find_orphan_pending(
        older_than_seconds=max(0, older_than_seconds), limit=max(1, min(limit, 500))
    )
    return {"items": items, "threshold_s": older_than_seconds}


class ReconcileOrphanForm(BaseModel):
    result_id: str
    dbsphere_id: str
    reason: str = "orphan"


@router.post("/sql/admin/reconcile-orphan", response_model=bool)
async def reconcile_orphan_pending(
    form_data: ReconcileOrphanForm,
    request: Request,
    user=Depends(get_verified_user),
):
    """Orphan SQL_PENDING 을 SQL_UNKNOWN append 로 마킹. admin 전용."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )
    from open_webui.services.dbsphere_executor import mark_orphan_unknown

    ok = mark_orphan_unknown(
        dbsphere_id=form_data.dbsphere_id,
        user_id=user.id,
        result_id=form_data.result_id,
        reason=form_data.reason,
    )
    return bool(ok)
