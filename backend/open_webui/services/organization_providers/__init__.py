"""
Organization Provider System

조직 데이터를 다양한 소스에서 가져올 수 있는 확장 가능한 Provider 시스템.

지원 Provider:
- json: JSON 데이터 직접 입력
- msgraph: Microsoft Graph API (Azure AD / Entra ID)
- keycloak: Keycloak Admin REST API
- (향후) okta: Okta Directory
- google: Google Workspace Directory
"""

from .base import OrganizationData, OrganizationProvider, OrgUnitData
from .google_provider import GoogleOrganizationProvider
from .json_provider import JsonOrganizationProvider
from .keycloak_provider import KeycloakOrganizationProvider
from .msgraph_provider import MSGraphOrganizationProvider

__all__ = [
    "OrganizationProvider",
    "OrganizationData",
    "OrgUnitData",
    "GoogleOrganizationProvider",
    "JsonOrganizationProvider",
    "KeycloakOrganizationProvider",
    "MSGraphOrganizationProvider",
    "get_provider",
]


def get_provider(provider_type: str, **kwargs) -> OrganizationProvider:
    """
    Provider 타입에 따라 적절한 Provider 인스턴스 반환

    Args:
        provider_type: 'json', 'msgraph', 'keycloak', 'google' 등
        **kwargs: Provider별 설정 (access_token, service_account_key 등)

    Returns:
        OrganizationProvider 인스턴스
    """
    providers = {
        "json": JsonOrganizationProvider,
        "msgraph": MSGraphOrganizationProvider,
        "keycloak": KeycloakOrganizationProvider,
        "google": GoogleOrganizationProvider,
    }

    provider_class = providers.get(provider_type)
    if not provider_class:
        raise ValueError(
            f"Unknown provider type: {provider_type}. Available: {list(providers.keys())}"
        )

    return provider_class(**kwargs)
