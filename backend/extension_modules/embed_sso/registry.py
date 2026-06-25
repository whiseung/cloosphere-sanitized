"""SSO provider registry.

위젯 SSO config에서 받은 옵션으로 provider 인스턴스를 빌드한다.
호출자는 `get_sso_provider(name, options)`만 알면 된다.
"""

from __future__ import annotations

from typing import Any, Optional

from .providers.base import BaseSSOProvider
from .providers.github import GitHubSSOProvider
from .providers.google import GoogleSSOProvider
from .providers.microsoft import MicrosoftSSOProvider
from .providers.oidc import GenericOIDCProvider

SSO_PROVIDERS: dict[str, type[BaseSSOProvider]] = {
    "microsoft": MicrosoftSSOProvider,
    "google": GoogleSSOProvider,
    "github": GitHubSSOProvider,
    "oidc": GenericOIDCProvider,
}


def get_sso_provider(
    name: str, options: Optional[dict[str, Any]] = None
) -> BaseSSOProvider:
    """Build a provider instance with widget-config supplied options.

    Args:
        name: provider 키 ('microsoft', 'google', 'github', 'oidc')
        options: 위젯 sso config의 provider별 옵션 (tenant_id, trusted_audiences 등)

    Raises:
        ValueError: 알 수 없는 provider 이름
    """
    cls = SSO_PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown SSO provider: {name}")

    options = options or {}
    if name == "microsoft":
        return MicrosoftSSOProvider(
            tenant_id=options.get("tenant_id"),
            trusted_audiences=options.get("trusted_audiences"),
        )
    if name == "google":
        return GoogleSSOProvider(
            trusted_audiences=options.get("trusted_audiences"),
        )
    if name == "github":
        return GitHubSSOProvider()
    if name == "oidc":
        return GenericOIDCProvider(
            trusted_issuers=options.get("trusted_issuers"),
            trusted_audiences=options.get("trusted_audiences"),
        )

    # Should be unreachable due to the check above
    raise ValueError(f"No factory for provider: {name}")
