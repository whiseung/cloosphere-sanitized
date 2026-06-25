import base64
import logging
import mimetypes
import sys
import time
import uuid
from typing import Optional

import aiohttp
from authlib.integrations.starlette_client import OAuth
from authlib.oidc.core import UserInfo
from fastapi import (
    HTTPException,
    status,
)
from open_webui.config import (
    DEFAULT_USER_ROLE,
    ENABLE_EMAIL_DEIDENTIFY,
    ENABLE_GOOGLE_ADMIN_SYNC,
    ENABLE_OAUTH_GROUP_MANAGEMENT,
    ENABLE_OAUTH_ORG_UNIT_MANAGEMENT,
    ENABLE_OAUTH_ROLE_MANAGEMENT,
    ENABLE_OAUTH_SIGNUP,
    GOOGLE_ADMIN_IMPERSONATE_EMAIL,
    GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY,
    JWT_EXPIRES_IN,
    OAUTH_ADMIN_ROLES,
    OAUTH_ALLOWED_DOMAINS,
    OAUTH_ALLOWED_ROLES,
    OAUTH_DEPARTMENT_CLAIM,
    OAUTH_EMAIL_CLAIM,
    OAUTH_GROUPS_CLAIM,
    OAUTH_MERGE_ACCOUNTS_BY_EMAIL,
    OAUTH_PICTURE_CLAIM,
    OAUTH_PROVIDERS,
    OAUTH_ROLES_CLAIM,
    OAUTH_USERNAME_CLAIM,
    WEBHOOK_URL,
    WEBUI_URL,
    AppConfig,
)
from open_webui.constants import ERROR_MESSAGES, WEBHOOK_MESSAGES
from open_webui.env import (
    GLOBAL_LOG_LEVEL,
    SRC_LOG_LEVELS,
    WEBUI_AUTH_COOKIE_SAME_SITE,
    WEBUI_AUTH_COOKIE_SECURE,
    WEBUI_NAME,
)
from open_webui.models.auths import Auths
from open_webui.models.groups import GroupModel, Groups, GroupUpdateForm
from open_webui.models.user_oauth_tokens import UserOAuthTokens
from open_webui.models.users import Users
from open_webui.services.organization_providers.google_provider import (
    get_google_admin_access_token,
)
from open_webui.utils.auth import create_token, get_password_hash
from open_webui.utils.misc import deidentify_email, parse_duration
from open_webui.utils.webhook import post_webhook
from starlette.responses import RedirectResponse

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["OAUTH"])

####################################
# Google Admin Directory API Helper
####################################


_GOOGLE_ADMIN_API_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _fetch_google_admin_user_info(email: str, access_token: str) -> dict | None:
    """Google Admin Directory API로 사용자 조직 정보를 가져온다."""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with aiohttp.ClientSession(timeout=_GOOGLE_ADMIN_API_TIMEOUT) as session:
            async with session.get(
                f"https://admin.googleapis.com/admin/directory/v1/users/{email}",
                headers=headers,
                params={"projection": "full"},
            ) as resp:
                if not resp.ok:
                    log.warning(
                        f"Google Admin user lookup failed for {email}: {resp.status} {await resp.text()}"
                    )
                    return None
                return await resp.json()
    except Exception as e:
        log.error(f"Google Admin user info error: {e}")
        return None


async def _fetch_google_admin_user_groups(email: str, access_token: str) -> list[str]:
    """Google Admin Directory API로 사용자가 속한 그룹 목록을 가져온다."""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        groups = []
        async with aiohttp.ClientSession(timeout=_GOOGLE_ADMIN_API_TIMEOUT) as session:
            page_token = None
            while True:
                params = {"userKey": email}
                if page_token:
                    params["pageToken"] = page_token
                async with session.get(
                    "https://admin.googleapis.com/admin/directory/v1/groups",
                    headers=headers,
                    params=params,
                ) as resp:
                    if not resp.ok:
                        log.warning(
                            f"Google Admin groups lookup failed for {email}: {resp.status} {await resp.text()}"
                        )
                        break
                    data = await resp.json()
                    for g in data.get("groups", []):
                        group_id = g.get("name") or g.get("email")
                        if group_id:
                            groups.append(group_id)
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break
        return groups
    except Exception as e:
        log.error(f"Google Admin groups error: {e}")
        return []


auth_manager_config = AppConfig()
auth_manager_config.DEFAULT_USER_ROLE = DEFAULT_USER_ROLE
auth_manager_config.ENABLE_OAUTH_SIGNUP = ENABLE_OAUTH_SIGNUP
auth_manager_config.OAUTH_MERGE_ACCOUNTS_BY_EMAIL = OAUTH_MERGE_ACCOUNTS_BY_EMAIL
auth_manager_config.ENABLE_OAUTH_ROLE_MANAGEMENT = ENABLE_OAUTH_ROLE_MANAGEMENT
auth_manager_config.ENABLE_OAUTH_GROUP_MANAGEMENT = ENABLE_OAUTH_GROUP_MANAGEMENT
auth_manager_config.ENABLE_OAUTH_ORG_UNIT_MANAGEMENT = ENABLE_OAUTH_ORG_UNIT_MANAGEMENT
auth_manager_config.OAUTH_ROLES_CLAIM = OAUTH_ROLES_CLAIM
auth_manager_config.OAUTH_GROUPS_CLAIM = OAUTH_GROUPS_CLAIM
auth_manager_config.OAUTH_EMAIL_CLAIM = OAUTH_EMAIL_CLAIM
auth_manager_config.OAUTH_PICTURE_CLAIM = OAUTH_PICTURE_CLAIM
auth_manager_config.OAUTH_USERNAME_CLAIM = OAUTH_USERNAME_CLAIM
auth_manager_config.OAUTH_ALLOWED_ROLES = OAUTH_ALLOWED_ROLES
auth_manager_config.OAUTH_ADMIN_ROLES = OAUTH_ADMIN_ROLES
auth_manager_config.OAUTH_ALLOWED_DOMAINS = OAUTH_ALLOWED_DOMAINS
auth_manager_config.OAUTH_DEPARTMENT_CLAIM = OAUTH_DEPARTMENT_CLAIM
auth_manager_config.WEBHOOK_URL = WEBHOOK_URL
auth_manager_config.JWT_EXPIRES_IN = JWT_EXPIRES_IN


class OAuthManager:
    def __init__(self, app):
        self.oauth = OAuth()
        self.app = app
        for _, provider_config in OAUTH_PROVIDERS.items():
            provider_config["register"](self.oauth)

    def reload(self):
        """
        멀티워커 환경에서 다른 워커가 OAuth 관련 PersistentConfig를 변경했을 때 호출.
        OAUTH_PROVIDERS 딕셔너리를 최신 PersistentConfig 값 기반으로 재구성한 뒤
        authlib OAuth 인스턴스도 새로 만들어 재등록한다.
        """
        from open_webui.config import load_oauth_providers

        load_oauth_providers()
        new_oauth = OAuth()
        for _, provider_config in OAUTH_PROVIDERS.items():
            provider_config["register"](new_oauth)
        self.oauth = new_oauth
        log.info(
            f"OAuthManager reloaded; active providers: {list(OAUTH_PROVIDERS.keys())}"
        )

    def get_client(self, provider_name):
        return self.oauth.create_client(provider_name)

    def get_user_role(self, user, user_data):
        if user and Users.get_num_users() == 1:
            # If the user is the only user, assign the role "admin" - actually repairs role for single user on login
            log.debug("Assigning the only user the admin role")
            return "admin"
        if not user and Users.get_num_users() == 0:
            # If there are no users, assign the role "admin", as the first user will be an admin
            log.debug("Assigning the first user the admin role")
            return "admin"

        if auth_manager_config.ENABLE_OAUTH_ROLE_MANAGEMENT:
            log.debug("Running OAUTH Role management")
            oauth_claim = auth_manager_config.OAUTH_ROLES_CLAIM
            oauth_allowed_roles = auth_manager_config.OAUTH_ALLOWED_ROLES
            oauth_admin_roles = auth_manager_config.OAUTH_ADMIN_ROLES
            oauth_roles = []
            # Default/fallback role if no matching roles are found
            default_role = auth_manager_config.DEFAULT_USER_ROLE
            if default_role.startswith("user:group:"):
                role = "user"
            else:
                role = default_role

            # Next block extracts the roles from the user data, accepting nested claims of any depth
            if oauth_claim and oauth_allowed_roles and oauth_admin_roles:
                claim_data = user_data
                nested_claims = oauth_claim.split(".")
                for nested_claim in nested_claims:
                    claim_data = claim_data.get(nested_claim, {})
                oauth_roles = claim_data if isinstance(claim_data, list) else []

            log.debug(f"Oauth Roles claim: {oauth_claim}")
            log.debug(f"User roles from oauth: {oauth_roles}")
            log.debug(f"Accepted user roles: {oauth_allowed_roles}")
            log.debug(f"Accepted admin roles: {oauth_admin_roles}")

            # If any roles are found, check if they match the allowed or admin roles
            if oauth_roles:
                # If role management is enabled, and matching roles are provided, use the roles
                for allowed_role in oauth_allowed_roles:
                    # If the user has any of the allowed roles, assign the role "user"
                    if allowed_role in oauth_roles:
                        log.debug("Assigned user the user role")
                        role = "user"
                        break
                for admin_role in oauth_admin_roles:
                    # If the user has any of the admin roles, assign the role "admin"
                    if admin_role in oauth_roles:
                        log.debug("Assigned user the admin role")
                        role = "admin"
                        break
        else:
            if not user:
                # If role management is disabled, use the default role for new users
                default_role = auth_manager_config.DEFAULT_USER_ROLE
                if default_role.startswith("user:group:"):
                    role = "user"
                else:
                    role = default_role
            else:
                # If role management is disabled, use the existing role for existing users
                role = user.role

        return role

    def update_user_groups(self, user, user_data, default_permissions):
        log.debug("Running OAUTH Group management")
        oauth_claim = auth_manager_config.OAUTH_GROUPS_CLAIM

        user_oauth_groups = []
        # Nested claim search for groups claim
        if oauth_claim:
            claim_data = user_data
            nested_claims = oauth_claim.split(".")
            for nested_claim in nested_claims:
                claim_data = claim_data.get(nested_claim, {})
            user_oauth_groups = claim_data if isinstance(claim_data, list) else []

        user_current_groups: list[GroupModel] = Groups.get_groups_by_member_id(user.id)
        all_available_groups: list[GroupModel] = Groups.get_groups()

        log.debug(f"Oauth Groups claim: {oauth_claim}")
        log.debug(f"User oauth groups: {user_oauth_groups}")
        log.debug(f"User's current groups: {[g.name for g in user_current_groups]}")
        log.debug(
            f"All groups available in OpenWebUI: {[g.name for g in all_available_groups]}"
        )

        # Remove groups that user is no longer a part of
        for group_model in user_current_groups:
            if user_oauth_groups and group_model.name not in user_oauth_groups:
                # Remove group from user
                log.debug(
                    f"Removing user from group {group_model.name} as it is no longer in their oauth groups"
                )

                user_ids = group_model.user_ids
                user_ids = [i for i in user_ids if i != user.id]

                # In case a group is created, but perms are never assigned to the group by hitting "save"
                group_permissions = group_model.permissions
                if not group_permissions:
                    group_permissions = default_permissions

                update_form = GroupUpdateForm(
                    name=group_model.name,
                    description=group_model.description,
                    permissions=group_permissions,
                    user_ids=user_ids,
                )
                Groups.update_group_by_id(
                    id=group_model.id, form_data=update_form, overwrite=False
                )

        # Add user to new groups
        for group_model in all_available_groups:
            if (
                user_oauth_groups
                and group_model.name in user_oauth_groups
                and not any(gm.name == group_model.name for gm in user_current_groups)
            ):
                # Add user to group
                log.debug(
                    f"Adding user to group {group_model.name} as it was found in their oauth groups"
                )

                user_ids = group_model.user_ids
                user_ids.append(user.id)

                # In case a group is created, but perms are never assigned to the group by hitting "save"
                group_permissions = group_model.permissions
                if not group_permissions:
                    group_permissions = default_permissions

                update_form = GroupUpdateForm(
                    name=group_model.name,
                    description=group_model.description,
                    permissions=group_permissions,
                    user_ids=user_ids,
                )
                Groups.update_group_by_id(
                    id=group_model.id, form_data=update_form, overwrite=False
                )

    def update_user_org_units(
        self, user, department: str, external_user_id: str = None
    ):
        """
        사용자의 부서 정보를 기반으로 조직 단위 멤버십 업데이트.
        Provider-agnostic: Microsoft, Keycloak, 기타 OIDC 모두 지원.

        Args:
            user: 사용자 모델 (oauth_sub, email 포함)
            department: 부서명 (e.g., "영업부", "Engineering")
            external_user_id: 외부 시스템 사용자 ID (e.g., Azure AD Object ID)
        """
        if not department:
            log.debug(
                f"User {user.email} has no department info, skipping org unit update"
            )
            return

        from open_webui.models.organization import (
            OrganizationalUnits,
            OrganizationalUnitUpdateForm,
        )

        log.info(
            f"Updating org unit membership for user {user.email}, department: {department}"
        )

        # 사용자를 식별할 수 있는 모든 ID 수집
        user_identifiers = {user.oauth_sub, user.email}
        if external_user_id:
            user_identifiers.add(external_user_id)
        user_identifiers.discard(None)

        # 모든 조직 단위 조회
        all_units = OrganizationalUnits.get_all_organizational_units()

        # 사용자가 현재 속한 조직 단위들
        current_unit_ids = []
        target_unit = None

        for unit in all_units:
            member_ids = unit.member_ids or []

            # 사용자가 이 조직 단위에 속해 있는지 확인
            if any(uid in member_ids for uid in user_identifiers):
                current_unit_ids.append(unit.id)

            # 부서명과 일치하는 조직 단위 찾기
            unit_name = unit.display_name or unit.name
            if unit_name == department or unit.name == department:
                target_unit = unit

        # 대상 조직 단위를 찾지 못한 경우
        if not target_unit:
            log.debug(f"No matching org unit found for department: {department}")
            return

        target_member_ids = target_unit.member_ids or []
        user_identifier = user.oauth_sub or user.email
        user_email_lc = (user.email or "").lower()

        def _meta_has_user(meta: Optional[dict]) -> bool:
            if not meta:
                return False
            members = meta.get("members") or []
            for m in members:
                if external_user_id and m.get("id") == external_user_id:
                    return True
                if user_email_lc and (m.get("email") or "").lower() == user_email_lc:
                    return True
            return False

        def _meta_without_user(meta: Optional[dict]) -> Optional[dict]:
            if not meta:
                return meta
            members = meta.get("members")
            if not members:
                return meta
            kept = [
                m
                for m in members
                if not (
                    (external_user_id and m.get("id") == external_user_id)
                    or (
                        user_email_lc
                        and (m.get("email") or "").lower() == user_email_lc
                    )
                )
            ]
            if len(kept) == len(members):
                return meta
            new_meta = {**meta, "members": kept}
            if "member_count" in new_meta:
                new_meta["member_count"] = len(kept)
            return new_meta

        def _meta_with_user(meta: Optional[dict]) -> dict:
            base = dict(meta) if meta else {}
            members = list(base.get("members") or [])
            members.append(
                {
                    "id": external_user_id or user.oauth_sub or "",
                    "name": user.name or user.email,
                    "email": user.email,
                    "job_title": "",
                }
            )
            base["members"] = members
            if "member_count" in base or meta is None:
                base["member_count"] = len(members)
            return base

        # 기존 조직 단위에서 사용자 제거 (같은 조직 내 다른 부서에서)
        for unit in all_units:
            if unit.id in current_unit_ids and unit.id != target_unit.id:
                # 같은 organization_id인 경우에만 제거 (다른 조직의 단위는 유지)
                if unit.organization_id == target_unit.organization_id:
                    member_ids = unit.member_ids or []
                    updated_members = [
                        m for m in member_ids if m not in user_identifiers
                    ]
                    updated_meta = _meta_without_user(unit.meta)

                    member_ids_changed = len(updated_members) != len(member_ids)
                    meta_changed = updated_meta is not unit.meta

                    if member_ids_changed or meta_changed:
                        OrganizationalUnits.update_organizational_unit_by_id(
                            unit.id,
                            OrganizationalUnitUpdateForm(
                                member_ids=updated_members
                                if member_ids_changed
                                else None,
                                meta=updated_meta if meta_changed else None,
                            ),
                        )
                        log.info(f"Removed user {user.email} from org unit {unit.name}")

        # 새 조직 단위에 사용자 추가 (member_ids + meta.members 모두 동기화)
        in_member_ids = user_identifier in target_member_ids
        in_meta_members = _meta_has_user(target_unit.meta)

        if in_member_ids and in_meta_members:
            log.debug(f"User {user.email} already in org unit {target_unit.name}")
            return

        new_member_ids = (
            target_member_ids
            if in_member_ids
            else target_member_ids + [user_identifier]
        )
        new_meta = (
            target_unit.meta if in_meta_members else _meta_with_user(target_unit.meta)
        )

        OrganizationalUnits.update_organizational_unit_by_id(
            target_unit.id,
            OrganizationalUnitUpdateForm(
                member_ids=new_member_ids if not in_member_ids else None,
                meta=new_meta if not in_meta_members else None,
            ),
        )
        log.info(
            f"Added user {user.email} to org unit {target_unit.name} "
            f"(member_ids={'updated' if not in_member_ids else 'kept'}, "
            f"meta.members={'updated' if not in_meta_members else 'kept'})"
        )

    async def handle_login(self, request, provider):
        if provider not in OAUTH_PROVIDERS:
            raise HTTPException(404)
        # If the provider has a custom redirect URL, use that, otherwise automatically generate one
        redirect_uri = OAUTH_PROVIDERS[provider].get("redirect_uri") or request.url_for(
            "oauth_callback", provider=provider
        )
        client = self.get_client(provider)
        if client is None:
            raise HTTPException(404)
        # Google: authlib 가 client_kwargs 의 access_type / prompt 를 authorize URL
        # 에 자동 포함시키지 않음 (token endpoint 호출용으로 보관).  Gmail / Calendar
        # 위임을 위해 refresh_token 이 필요한데 그건 ``access_type=offline`` 일 때만
        # Google 이 발급한다 — 누락 시 backend 가 row 저장을 skip → UI "미연결".
        extra_authorize_params: dict = {}
        if provider == "google":
            extra_authorize_params = {
                "access_type": "offline",
                "prompt": "consent",
            }
        return await client.authorize_redirect(
            request, redirect_uri, **extra_authorize_params
        )

    async def handle_callback(self, request, provider, response):
        if provider not in OAUTH_PROVIDERS:
            raise HTTPException(404)
        client = self.get_client(provider)
        try:
            token = await client.authorize_access_token(request)
        except Exception as e:
            log.warning(f"OAuth callback error: {e}")
            raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
        user_data: UserInfo = token.get("userinfo")
        if not user_data or auth_manager_config.OAUTH_EMAIL_CLAIM not in user_data:
            user_data: UserInfo = await client.userinfo(token=token)
        if not user_data:
            log.warning(f"OAuth callback failed, user data is missing: {token}")
            raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)

        # 프로바이더별 사용자 상세 정보 (부서, 직함, 그룹 등)
        ms_user_details = None
        google_admin_details = None
        google_admin_groups = []

        if provider == "microsoft":
            access_token = token.get("access_token")
            if access_token:
                # Microsoft Graph API 호출
                headers = {"Authorization": f"Bearer {access_token}"}
                async with aiohttp.ClientSession() as session:
                    # 조직 정보
                    async with session.get(
                        "https://graph.microsoft.com/v1.0/organization", headers=headers
                    ) as resp:
                        if resp.ok:
                            org_data = await resp.json()
                            log.debug(f"Microsoft organization data: {org_data}")

                    # 사용자 상세 정보 (부서, 직함 등)
                    async with session.get(
                        "https://graph.microsoft.com/v1.0/me",
                        headers=headers,
                        params={
                            "$select": "id,displayName,jobTitle,department,companyName,officeLocation"
                        },
                    ) as resp:
                        if resp.ok:
                            ms_user_details = await resp.json()
                            log.debug(f"Microsoft user details: {ms_user_details}")

        elif provider == "google" and ENABLE_GOOGLE_ADMIN_SYNC:
            # Google Admin Directory API로 조직/그룹 정보 가져오기
            # 서비스 계정 + 도메인 위임 방식 (사용자 OAuth token이 아닌 별도 인증)
            _email = user_data.get(auth_manager_config.OAUTH_EMAIL_CLAIM, "")
            if _email:
                _admin_token = await get_google_admin_access_token(
                    GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY,
                    GOOGLE_ADMIN_IMPERSONATE_EMAIL,
                )
                if _admin_token:
                    google_admin_details = await _fetch_google_admin_user_info(
                        _email, _admin_token
                    )
                    if google_admin_details:
                        log.debug(
                            f"Google Admin user details: orgUnitPath={google_admin_details.get('orgUnitPath')}"
                        )
                    google_admin_groups = await _fetch_google_admin_user_groups(
                        _email, _admin_token
                    )
                    if google_admin_groups:
                        log.debug(f"Google Admin user groups: {google_admin_groups}")
        sub = user_data.get(OAUTH_PROVIDERS[provider].get("sub_claim", "sub"))
        if not sub:
            log.warning(f"OAuth callback failed, sub is missing: {user_data}")
            raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
        provider_sub = f"{provider}@{sub}"
        # Entra/Azure AD 의 `oid` claim — tenant-wide 사용자 고유 ID.
        # Teams Activity.from.aadObjectId 와 동일한 값이라 외부 Entra 연동(봇 등)에서
        # 계정 매핑에 사용. microsoft 외 provider 는 보통 없음 (None 저장됨).
        oauth_oid = user_data.get("oid") if isinstance(user_data, dict) else None
        email_claim = auth_manager_config.OAUTH_EMAIL_CLAIM
        email = user_data.get(email_claim, "")
        # We currently mandate that email addresses are provided
        if not email:
            # If the provider is GitHub,and public email is not provided, we can use the access token to fetch the user's email
            if provider == "github":
                try:
                    access_token = token.get("access_token")
                    headers = {"Authorization": f"Bearer {access_token}"}
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "https://api.github.com/user/emails", headers=headers
                        ) as resp:
                            if resp.ok:
                                emails = await resp.json()
                                # use the primary email as the user's email
                                primary_email = next(
                                    (e["email"] for e in emails if e.get("primary")),
                                    None,
                                )
                                if primary_email:
                                    email = primary_email
                                else:
                                    log.warning(
                                        "No primary email found in GitHub response"
                                    )
                                    raise HTTPException(
                                        400, detail=ERROR_MESSAGES.INVALID_CRED
                                    )
                            else:
                                log.warning("Failed to fetch GitHub email")
                                raise HTTPException(
                                    400, detail=ERROR_MESSAGES.INVALID_CRED
                                )
                except Exception as e:
                    log.warning(f"Error fetching GitHub email: {e}")
                    raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
            else:
                log.warning(f"OAuth callback failed, email is missing: {user_data}")
                raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
        email = email.lower()
        if (
            "*" not in auth_manager_config.OAUTH_ALLOWED_DOMAINS
            and email.split("@")[-1] not in auth_manager_config.OAUTH_ALLOWED_DOMAINS
        ):
            log.warning(
                f"OAuth callback failed, e-mail domain is not in the list of allowed domains: {user_data}"
            )
            raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)

        # Check if the user exists
        user = Users.get_user_by_oauth_sub(provider_sub)

        if not user:
            # If the user does not exist, check if merging is enabled
            if auth_manager_config.OAUTH_MERGE_ACCOUNTS_BY_EMAIL:
                # Check if the user exists by email
                user = Users.get_user_by_email(email)
                if user:
                    # Update the user with the new oauth sub
                    Users.update_user_oauth_sub_by_id(user.id, provider_sub)

        if user:
            determined_role = self.get_user_role(user, user_data)
            if user.role != determined_role:
                Users.update_user_role_by_id(user.id, determined_role)
            # Backfill oauth_oid for existing users who logged in before this field
            # existed. 기존 로그인 동작엔 영향 없음 — 없으면 set, 바뀌면 갱신.
            if oauth_oid and getattr(user, "oauth_oid", None) != oauth_oid:
                Users.update_user_oauth_oid_by_id(user.id, oauth_oid)

        if not user:
            user_count = Users.get_num_users()

            # If the user does not exist, check if signups are enabled
            if auth_manager_config.ENABLE_OAUTH_SIGNUP:
                # Check if an existing user with the same email already exists
                existing_user = Users.get_user_by_email(email)
                if existing_user:
                    raise HTTPException(400, detail=ERROR_MESSAGES.EMAIL_TAKEN)

                picture_claim = auth_manager_config.OAUTH_PICTURE_CLAIM
                if picture_claim:
                    picture_url = user_data.get(
                        picture_claim, OAUTH_PROVIDERS[provider].get("picture_url", "")
                    )
                    if picture_url:
                        # Download the profile image into a base64 string
                        try:
                            access_token = token.get("access_token")
                            get_kwargs = {}
                            if access_token:
                                get_kwargs["headers"] = {
                                    "Authorization": f"Bearer {access_token}",
                                }
                            async with aiohttp.ClientSession() as session:
                                async with session.get(
                                    picture_url, **get_kwargs
                                ) as resp:
                                    if resp.ok:
                                        picture = await resp.read()
                                        base64_encoded_picture = base64.b64encode(
                                            picture
                                        ).decode("utf-8")
                                        guessed_mime_type = mimetypes.guess_type(
                                            picture_url
                                        )[0]
                                        if guessed_mime_type is None:
                                            # assume JPG, browsers are tolerant enough of image formats
                                            guessed_mime_type = "image/jpeg"
                                        picture_url = f"data:{guessed_mime_type};base64,{base64_encoded_picture}"
                                    else:
                                        picture_url = "/user.png"
                        except Exception as e:
                            log.error(
                                f"Error downloading profile image '{picture_url}': {e}"
                            )
                            picture_url = "/user.png"
                    if not picture_url:
                        picture_url = "/user.png"
                else:
                    picture_url = "/user.png"

                username_claim = auth_manager_config.OAUTH_USERNAME_CLAIM

                name = user_data.get(username_claim)
                if not name:
                    log.warning("Username claim is missing, using email as name")
                    name = email

                role = self.get_user_role(None, user_data)

                store_email = (
                    deidentify_email(email) if ENABLE_EMAIL_DEIDENTIFY else email
                )
                user = Auths.insert_new_auth(
                    email=store_email,
                    password=get_password_hash(
                        str(uuid.uuid4())
                    ),  # Random password, not used
                    name=name,
                    profile_image_url=picture_url,
                    role=role,
                    oauth_sub=provider_sub,
                )
                # oauth_oid 는 insert_new_auth signature 에 없어 별도 update 로 저장.
                # 신규 계정 생성에는 어차피 트랜잭션이 완료됐으니 추가 update 안전.
                if user and oauth_oid:
                    Users.update_user_oauth_oid_by_id(user.id, oauth_oid)

                # Add user to default group if configured
                default_role_setting = auth_manager_config.DEFAULT_USER_ROLE
                if user and default_role_setting.startswith("user:group:"):
                    default_group_id = default_role_setting[len("user:group:") :]
                    group = Groups.get_group_by_id(default_group_id)
                    if group:
                        user_ids = list(group.user_ids) if group.user_ids else []
                        if user.id not in user_ids:
                            user_ids.append(user.id)
                            Groups.update_group_by_id(
                                default_group_id,
                                GroupUpdateForm(
                                    name=group.name,
                                    description=group.description,
                                    permissions=group.permissions,
                                    user_ids=user_ids,
                                ),
                            )

                if auth_manager_config.WEBHOOK_URL:
                    post_webhook(
                        WEBUI_NAME,
                        auth_manager_config.WEBHOOK_URL,
                        WEBHOOK_MESSAGES.USER_SIGNUP(user.name),
                        {
                            "action": "signup",
                            "message": WEBHOOK_MESSAGES.USER_SIGNUP(user.name),
                            "user": user.model_dump_json(exclude_none=True),
                        },
                    )
            else:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.ACCESS_PROHIBITED
                )

        # 메일/캘린더 통합용 토큰 보관 — provider 가 refresh_token 을 발급한 경우만.
        # offline_access (Microsoft) / access_type=offline (Google) 동의가 빠지면
        # refresh_token 이 없어 1시간짜리 access_token 만 들어오므로 저장 가치 X.
        # 토큰 저장 실패는 로그인 흐름을 막지 않는다.
        if provider in ("microsoft", "google"):
            try:
                refresh_token = token.get("refresh_token")
                if refresh_token:
                    access_token_value = token.get("access_token")
                    expires_at = token.get("expires_at")
                    if not expires_at:
                        expires_in = int(token.get("expires_in") or 3600)
                        expires_at = int(time.time()) + expires_in
                    UserOAuthTokens.upsert(
                        user_id=user.id,
                        provider=provider,
                        access_token=access_token_value,
                        refresh_token=refresh_token,
                        expires_at=int(expires_at),
                        scopes=token.get("scope"),
                        account_email=user.email,
                    )
                else:
                    # offline_access scope 누락 시 refresh_token 미발급 — 1시간 후
                    # 재로그인이 필요하므로 토큰 보관하지 않는다.
                    log.warning(
                        f"OAuth refresh_token missing for {provider} user={user.email}; "
                        "offline_access scope likely not granted"
                    )
            except Exception as e:
                log.warning(f"Failed to persist OAuth token for {provider}: {e}")

        jwt_token = create_token(
            data={"id": user.id},
            expires_delta=parse_duration(auth_manager_config.JWT_EXPIRES_IN),
        )

        if auth_manager_config.ENABLE_OAUTH_GROUP_MANAGEMENT and user.role != "admin":
            # Google Admin API에서 그룹을 가져온 경우 user_data에 주입
            effective_user_data = user_data
            if provider == "google" and google_admin_groups:
                effective_user_data = {
                    **user_data,
                    (
                        auth_manager_config.OAUTH_GROUPS_CLAIM or "groups"
                    ): google_admin_groups,
                }
            self.update_user_groups(
                user=user,
                user_data=effective_user_data,
                default_permissions=request.app.state.config.USER_PERMISSIONS,
            )

        # 로그인 시 조직 단위 멤버십 자동 업데이트 (모든 OAuth 프로바이더)
        if auth_manager_config.ENABLE_OAUTH_ORG_UNIT_MANAGEMENT:
            try:
                department = None
                external_user_id = None

                if provider == "microsoft" and ms_user_details:
                    # Microsoft: Graph API에서 가져온 부서 정보
                    department = ms_user_details.get("department")
                    external_user_id = ms_user_details.get("id")
                elif provider == "google" and google_admin_details:
                    # Google: Admin Directory API에서 가져온 조직 경로
                    # orgUnitPath는 "/Engineering/Backend" 형태 → 마지막 세그먼트를 부서명으로 사용
                    org_unit_path = google_admin_details.get("orgUnitPath", "")
                    if org_unit_path and org_unit_path != "/":
                        department = org_unit_path.rstrip("/").split("/")[-1]
                    external_user_id = google_admin_details.get("id")
                else:
                    # Keycloak/기타 OIDC: userinfo claim에서 부서 추출
                    dept_claim = auth_manager_config.OAUTH_DEPARTMENT_CLAIM
                    if dept_claim:
                        # 중첩 claim 지원 (e.g., "realm_access.department")
                        department = user_data
                        for part in dept_claim.split("."):
                            if isinstance(department, dict):
                                department = department.get(part)
                            else:
                                department = None
                                break

                if department and isinstance(department, str):
                    self.update_user_org_units(
                        user=user,
                        department=department,
                        external_user_id=external_user_id,
                    )
            except Exception as e:
                log.warning(f"Failed to update user org units: {e}")

        # Set the cookie token
        response.set_cookie(
            key="token",
            value=jwt_token,
            httponly=True,  # Ensures the cookie is not accessible via JavaScript
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
        )

        if ENABLE_OAUTH_SIGNUP.value:
            oauth_id_token = token.get("id_token")
            response.set_cookie(
                key="oauth_id_token",
                value=oauth_id_token,
                httponly=True,
                samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
                secure=WEBUI_AUTH_COOKIE_SECURE,
            )
        # Redirect back to the frontend with the JWT token
        # Use WEBUI_URL for frontend redirect (supports dev environment with separate frontend/backend ports)
        frontend_url = (
            WEBUI_URL.value if WEBUI_URL.value else str(request.base_url).rstrip("/")
        )
        redirect_url = f"{frontend_url}/auth#token={jwt_token}"
        return RedirectResponse(url=redirect_url, headers=response.headers)
