"""
Cookie-based user resolver.

The built-in Vanna web UI demo stores the chosen email in a cookie named
`vanna_email`. This resolver turns that cookie into a User object.
"""

from __future__ import annotations

from dataclasses import dataclass

from vanna.core.user.models import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver


@dataclass(frozen=True)
class CookieEmailUserResolver(UserResolver):
    """
    Resolve user identity from a single cookie containing an email address.

    If the cookie is missing/empty and allow_anonymous=True, this returns an
    anonymous user instead of raising.
    """

    cookie_name: str = "vanna_email"
    allow_anonymous: bool = True
    anonymous_user_id: str = "anonymous"
    default_user_group: str = "user"
    admin_group: str = "admin"
    admin_emails: tuple[str, ...] = ("admin@example.com",)

    async def resolve_user(self, request_context: RequestContext) -> User:
        email = (request_context.cookies or {}).get(self.cookie_name)
        email = (email or "").strip()

        if not email:
            if self.allow_anonymous:
                # In dev/demo mode it’s convenient to let anonymous users still access
                # “user”-level tools (otherwise the UI looks like it’s doing nothing).
                return User(
                    id=self.anonymous_user_id,
                    username=self.anonymous_user_id,
                    email=None,
                    group_memberships=[self.default_user_group],
                )
            raise ValueError(f"Missing auth cookie: {self.cookie_name}")

        username = self._username_from_email(email)
        groups = [self.default_user_group]
        if email in self.admin_emails:
            groups.append(self.admin_group)

        # Use email as stable user id for demo purposes
        return User(id=email, username=username, email=email, group_memberships=groups)

    @staticmethod
    def _username_from_email(email: str) -> str:
        # Very small helper for demo UX (e.g. "alice@example.com" -> "alice")
        if "@" in email:
            left = email.split("@", 1)[0].strip()
            return left or email
        return email
