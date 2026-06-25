"""Microsoft Fabric runner implementation for DBSphere V2."""

from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.synapse import SynapseRunner


class FabricRunner(SynapseRunner):
    """
    Microsoft Fabric implementation of SqlRunnerBase.

    Inherits from SynapseRunner as Fabric uses the same T-SQL interface
    and ODBC connectivity. The main differences are:
    - Endpoint format: *.datawarehouse.fabric.microsoft.com
    - Authentication: Entra ID (Azure AD) required, no SQL auth
    """

    def __init__(self, config: DBConfig):
        """
        Initialize Fabric runner.

        Args:
            config: Database connection configuration
        """
        super().__init__(config)

    def _get_connection_sync(self):
        """Fail fast with a clear, actionable error.

        Fabric inherits SynapseRunner, whose ``_get_connection_sync`` opens a
        ``pymssql`` connection using SQL Server authentication. Microsoft Fabric
        warehouses reject SQL auth — they require Entra ID (Azure AD) over the
        ODBC 18 driver (see ``_build_connection_string``), which is not wired up
        yet. Without this guard, every query/test surfaces an opaque pymssql
        login failure that looks like a credentials problem rather than an
        unsupported-connector one. Raising here turns ``test_connection`` and
        every extraction/query call into a single, diagnosable message.
        """
        raise NotImplementedError(
            "Microsoft Fabric warehouse connections are not supported yet. "
            "Fabric requires Entra ID (Azure AD) authentication over the "
            "ODBC 18 driver; SQL Server authentication (pymssql) is rejected by "
            "Fabric. Use a supported connector (Synapse/MSSQL/PostgreSQL/etc.) "
            "until Fabric Azure AD connectivity is implemented."
        )

    def _build_connection_string(self) -> str:
        """
        Build ODBC connection string for Microsoft Fabric.

        Microsoft Fabric requires Azure AD authentication.
        SQL Server authentication is not supported.
        """
        # Base connection parameters
        conn_parts = [
            "DRIVER={ODBC Driver 18 for SQL Server}",
            f"SERVER={self.config.host}",
            f"DATABASE={self.config.database}",
        ]

        # Authentication method selection (Azure AD only for Fabric)
        if self.config.use_managed_identity:
            # Azure Managed Identity authentication
            conn_parts.append("Authentication=ActiveDirectoryMsi")
        elif self.config.client_id and self.config.client_secret:
            # Service Principal authentication
            conn_parts.extend(
                [
                    "Authentication=ActiveDirectoryServicePrincipal",
                    f"UID={self.config.client_id}",
                    f"PWD={self.config.client_secret}",
                ]
            )
            if self.config.tenant_id:
                conn_parts.append(f"TenantId={self.config.tenant_id}")
        elif self.config.access_token:
            # Access token authentication (if supported by driver)
            conn_parts.extend(
                [
                    "Authentication=ActiveDirectoryAccessToken",
                    f"AccessToken={self.config.access_token}",
                ]
            )
        else:
            # Fallback to interactive Azure AD (for development)
            # Note: This may not work in headless environments
            conn_parts.append("Authentication=ActiveDirectoryInteractive")
            if self.config.username:
                conn_parts.append(f"UID={self.config.username}")

        # Additional connection options for Azure
        conn_parts.extend(
            [
                "Encrypt=yes",
                "TrustServerCertificate=no",
                "Connection Timeout=30",
            ]
        )

        return ";".join(conn_parts)
