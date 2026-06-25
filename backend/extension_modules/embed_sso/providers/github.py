"""GitHub OAuth 2.0 SSO provider.

GitHub은 OIDC를 지원하지 않으므로 access_token으로 GitHub API를 직접 호출한다.
이메일이 비공개로 설정된 사용자의 경우 `/user/emails`를 호출해 primary verified
이메일을 가져온다.
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import SSOExchangeRequest, SSOUserClaims
from .base import BaseSSOProvider

log = logging.getLogger(__name__)


class GitHubSSOProvider(BaseSSOProvider):
    name = "github"

    async def verify(self, request: SSOExchangeRequest) -> SSOUserClaims:
        if not request.access_token:
            raise ValueError("GitHub provider requires access_token")

        headers = {
            "Authorization": f"Bearer {request.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        user = await self._http_get_json("https://api.github.com/user", headers=headers)
        email = user.get("email")

        if not email:
            # 이메일이 비공개인 경우 별도 endpoint 호출
            try:
                emails: list[dict[str, Any]] = await self._http_get_json(
                    "https://api.github.com/user/emails", headers=headers
                )
                primary = next(
                    (e for e in emails if e.get("primary") and e.get("verified")),
                    None,
                )
                if primary:
                    email = primary.get("email")
            except Exception as e:
                log.warning(f"GitHub /user/emails call failed: {e}")

        if not email:
            raise ValueError(
                "GitHub user has no public/primary email. "
                "Grant 'user:email' scope or set a public email."
            )

        sub = user.get("id") or user.get("node_id")
        if sub is None:
            raise ValueError("GitHub user response missing id")

        return SSOUserClaims(
            sub=str(sub),
            email=email.lower(),
            email_verified=True,  # GitHub의 verified email만 사용
            name=user.get("name") or user.get("login"),
            picture=user.get("avatar_url"),
            raw=user,
        )
