"""
Organizations Router

조직 관리 API 엔드포인트.

기능:
- 조직 CRUD
- 조직 단위 CRUD
- Provider 기반 동기화 (JSON, MS Graph 등)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.organization import (
    OrganizationalUnitForm,
    OrganizationalUnitModel,
    OrganizationalUnits,
    OrganizationalUnitUpdateForm,
    OrganizationForm,
    OrganizationModel,
    Organizations,
    OrganizationUpdateForm,
)
from open_webui.models.users import Users
from open_webui.utils.auth import get_admin_user, get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

router = APIRouter()


############################
# Organization Endpoints
############################


@router.get("/", response_model=list[OrganizationModel])
async def get_organizations(user=Depends(get_verified_user)):
    """모든 조직 목록 가져오기"""
    return Organizations.get_all_organizations()


@router.post("/", response_model=Optional[OrganizationModel])
async def create_organization(
    form_data: OrganizationForm,
    user=Depends(get_admin_user),
):
    """새 조직 생성"""
    try:
        org = Organizations.insert_new_organization(form_data)
        if org:
            return org
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating organization"),
        )
    except Exception as e:
        log.exception(f"Error creating organization: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


############################
# Organizational Unit Endpoints
############################


@router.get("/units", response_model=list[OrganizationalUnitModel])
async def get_all_organizational_units(user=Depends(get_verified_user)):
    """모든 조직 단위 목록 가져오기"""
    return OrganizationalUnits.get_all_organizational_units()


@router.get("/{org_id}/units", response_model=list[OrganizationalUnitModel])
async def get_organizational_units_by_org(
    org_id: str,
    user=Depends(get_verified_user),
):
    """특정 조직의 조직 단위 목록 가져오기"""
    return OrganizationalUnits.get_organizational_units_by_organization_id(org_id)


@router.get("/{org_id}/units/tree", response_model=list[dict])
async def get_organizational_units_tree(
    org_id: str,
    user=Depends(get_verified_user),
):
    """조직 단위를 트리 구조로 가져오기"""
    units = OrganizationalUnits.get_organizational_units_by_organization_id(org_id)

    # 트리 구조로 변환
    unit_map = {u.id: {**u.model_dump(), "children": []} for u in units}
    tree = []

    for unit in units:
        unit_dict = unit_map[unit.id]
        if unit.parent_id and unit.parent_id in unit_map:
            unit_map[unit.parent_id]["children"].append(unit_dict)
        else:
            tree.append(unit_dict)

    return tree


@router.get("/units/{id}", response_model=Optional[OrganizationalUnitModel])
async def get_organizational_unit_by_id(id: str, user=Depends(get_verified_user)):
    """ID로 조직 단위 가져오기"""
    unit = OrganizationalUnits.get_organizational_unit_by_id(id)
    if unit:
        return unit
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# GetOrgUnitMemberEmails (Gmail 수신자 picker — 부서 → 멤버 이메일 펼침)
############################


class OrgUnitMemberEmail(BaseModel):
    name: str
    email: str


@router.get("/units/{id}/member-emails", response_model=list[OrgUnitMemberEmail])
async def get_org_unit_member_emails(id: str, user=Depends(get_verified_user)):
    """부서(org-unit) 멤버의 이메일 목록 — Gmail 카드에서 부서 선택 시 수신자 펼침.

    멤버 출처: ``meta.members`` (이메일 직접) + ``member_ids`` (user-id 또는 이메일).
    user-id 는 Users 로 이메일 해석, 이메일은 그대로.  email(lowercase) 로 dedup.
    """
    unit = OrganizationalUnits.get_organizational_unit_by_id(id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    out: dict[str, dict] = {}  # email(lower) -> {name, email}
    for m in (unit.meta or {}).get("members", []):
        email = (m.get("email") or "").strip()
        if email and email.lower() not in out:
            out[email.lower()] = {"name": m.get("name") or email, "email": email}
    id_like: list[str] = []
    for s in unit.member_ids or []:
        if not s:
            continue
        if "@" in s:
            if s.lower() not in out:
                out[s.lower()] = {"name": s, "email": s}
        else:
            id_like.append(s)
    if id_like:
        for u in Users.get_users_by_user_ids(id_like):
            email = (getattr(u, "email", "") or "").strip()
            if email and email.lower() not in out:
                out[email.lower()] = {"name": u.name or email, "email": email}
    return [OrgUnitMemberEmail(**v) for v in out.values()]


@router.post("/units", response_model=Optional[OrganizationalUnitModel])
async def create_organizational_unit(
    form_data: OrganizationalUnitForm,
    user=Depends(get_admin_user),
):
    """새 조직 단위 생성"""
    try:
        unit = OrganizationalUnits.insert_new_organizational_unit(form_data)
        if unit:
            return unit
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Error creating organizational unit"),
        )
    except Exception as e:
        log.exception(f"Error creating organizational unit: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


@router.post("/units/{id}", response_model=Optional[OrganizationalUnitModel])
async def update_organizational_unit(
    id: str,
    form_data: OrganizationalUnitUpdateForm,
    user=Depends(get_admin_user),
):
    """조직 단위 업데이트"""
    unit = OrganizationalUnits.update_organizational_unit_by_id(id, form_data)
    if unit:
        return unit
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


####################
# Org Unit Usage Limit (per-model)
####################


class OrgUnitUsageLimitResponse(BaseModel):
    per_model: dict[str, int] = {}


class OrgUnitUsageLimitForm(BaseModel):
    per_model: dict[str, int] = {}


def _extract_per_model_limit(payload) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    usage_limit = payload.get("usage_limit") or {}
    per_model = usage_limit.get("per_model") if isinstance(usage_limit, dict) else None
    if not isinstance(per_model, dict):
        return {}
    return {str(k): int(v) for k, v in per_model.items() if v is not None}


@router.get("/units/{id}/usage-limit", response_model=OrgUnitUsageLimitResponse)
async def get_unit_usage_limit(id: str, user=Depends(get_admin_user)):
    unit = OrganizationalUnits.get_organizational_unit_by_id(id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    return OrgUnitUsageLimitResponse(
        per_model=_extract_per_model_limit(unit.meta or {})
    )


@router.post("/units/{id}/usage-limit", response_model=OrgUnitUsageLimitResponse)
async def update_unit_usage_limit(
    id: str,
    form_data: OrgUnitUsageLimitForm,
    user=Depends(get_admin_user),
):
    unit = OrganizationalUnits.get_organizational_unit_by_id(id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    meta = dict(unit.meta or {})
    cleaned = {
        str(k): int(v) for k, v in (form_data.per_model or {}).items() if v is not None
    }
    if cleaned:
        meta["usage_limit"] = {"per_model": cleaned}
    else:
        meta.pop("usage_limit", None)

    OrganizationalUnits.update_organizational_unit_by_id(
        id, OrganizationalUnitUpdateForm(meta=meta)
    )
    return OrgUnitUsageLimitResponse(per_model=cleaned)


@router.delete("/units/{id}")
async def delete_organizational_unit(id: str, user=Depends(get_admin_user)):
    """조직 단위 삭제"""
    success = OrganizationalUnits.delete_organizational_unit_by_id(id)
    if success:
        return {"success": True}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# Sync Endpoints
############################


class JsonSyncRequest(BaseModel):
    """JSON 데이터로 조직 동기화 요청"""

    organization: dict
    units: list[dict] = []


class MSGraphSyncRequest(BaseModel):
    """MS Graph로 조직 동기화 요청"""

    access_token: Optional[str] = None  # 사용자 토큰 또는 서버에서 가져옴
    use_admin_units: bool = True
    use_groups: bool = False
    use_departments: bool = False
    group_filter: Optional[str] = None


@router.post("/sync/json")
async def sync_from_json(
    request: JsonSyncRequest,
    user=Depends(get_admin_user),
):
    """
    JSON 데이터로 조직 동기화

    요청 예시:
    ```json
    {
        "organization": {
            "tenant_id": "my-company",
            "name": "My Company",
            "domain": "mycompany.com"
        },
        "units": [
            {
                "id": "dept-1",
                "name": "Engineering",
                "type": "department",
                "children": [
                    {"id": "team-1", "name": "Backend Team", "type": "team"}
                ]
            }
        ]
    }
    ```
    """
    try:
        from open_webui.services.organization_providers import get_provider

        provider = get_provider(
            "json",
            organization=request.organization,
            units=request.units,
        )
        result = await provider.sync_to_db()
        return {"success": True, "result": result}
    except Exception as e:
        log.exception(f"Error syncing from JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


@router.post("/sync/msgraph")
async def sync_from_msgraph(
    request: MSGraphSyncRequest,
    http_request: Request,
    user=Depends(get_admin_user),
):
    """
    Microsoft Graph에서 조직 동기화

    access_token이 제공되지 않으면 서버 설정의 클라이언트 자격 증명 사용.
    """
    try:
        from open_webui.services.organization_providers import get_provider

        access_token = request.access_token

        if not access_token:
            # 서버 설정에서 클라이언트 자격 증명으로 토큰 획득
            from open_webui.config import (
                MICROSOFT_CLIENT_ID,
                MICROSOFT_CLIENT_SECRET,
                MICROSOFT_CLIENT_TENANT_ID,
            )

            if not all(
                [
                    MICROSOFT_CLIENT_ID.value,
                    MICROSOFT_CLIENT_SECRET.value,
                    MICROSOFT_CLIENT_TENANT_ID.value,
                ]
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Microsoft OAuth not configured. Provide access_token or configure server.",
                )

            from open_webui.services.organization_providers.msgraph_provider import (
                MSGraphOrganizationProvider,
            )

            provider = await MSGraphOrganizationProvider.from_client_credentials(
                tenant_id=MICROSOFT_CLIENT_TENANT_ID.value,
                client_id=MICROSOFT_CLIENT_ID.value,
                client_secret=MICROSOFT_CLIENT_SECRET.value,
                use_admin_units=request.use_admin_units,
                use_groups=request.use_groups,
                use_departments=request.use_departments,
                group_filter=request.group_filter,
            )
        else:
            provider = get_provider(
                "msgraph",
                access_token=access_token,
                use_admin_units=request.use_admin_units,
                use_groups=request.use_groups,
                use_departments=request.use_departments,
                group_filter=request.group_filter,
            )

        result = await provider.sync_to_db()
        return {"success": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Error syncing from MS Graph: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


class KeycloakSyncRequest(BaseModel):
    """Keycloak에서 조직 동기화 요청 (credentials는 환경변수에서 가져옴)"""

    use_groups: bool = True
    use_organizations: bool = False
    group_filter: Optional[str] = None


def _parse_keycloak_from_openid_url(openid_url: str) -> tuple[str, str]:
    """OPENID_PROVIDER_URL에서 server_url과 realm을 추출.

    e.g., https://keycloak.example.com/realms/cloosphere/.well-known/openid-configuration
    → ("https://keycloak.example.com", "cloosphere")
    """
    from urllib.parse import urlparse

    parsed = urlparse(openid_url)
    path = parsed.path.rstrip("/")

    # Remove .well-known/openid-configuration suffix if present
    well_known = "/.well-known/openid-configuration"
    if path.endswith(well_known):
        path = path[: -len(well_known)]

    # Extract realm from /realms/{realm} pattern
    parts = path.split("/")
    if "realms" in parts:
        realms_idx = parts.index("realms")
        if realms_idx + 1 < len(parts):
            realm = parts[realms_idx + 1]
            server_url = f"{parsed.scheme}://{parsed.netloc}"
            return server_url, realm

    raise ValueError(
        f"Cannot extract server_url/realm from OPENID_PROVIDER_URL: {openid_url}. "
        f"Expected format: https://host/realms/REALM/.well-known/openid-configuration"
    )


@router.post("/sync/keycloak")
async def sync_from_keycloak(
    request: KeycloakSyncRequest,
    user=Depends(get_admin_user),
):
    """
    Keycloak에서 조직 동기화

    환경변수의 OIDC 설정(OPENID_PROVIDER_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET)을
    사용하여 Keycloak Admin API에 접근합니다.
    """
    try:
        from open_webui.config import (
            OAUTH_CLIENT_ID,
            OAUTH_CLIENT_SECRET,
            OPENID_PROVIDER_URL,
        )

        if not all(
            [
                OAUTH_CLIENT_ID.value,
                OAUTH_CLIENT_SECRET.value,
                OPENID_PROVIDER_URL.value,
            ]
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Keycloak OIDC not configured. Set OPENID_PROVIDER_URL, OAUTH_CLIENT_ID, and OAUTH_CLIENT_SECRET environment variables.",
            )

        server_url, realm = _parse_keycloak_from_openid_url(OPENID_PROVIDER_URL.value)

        from open_webui.services.organization_providers.keycloak_provider import (
            KeycloakOrganizationProvider,
        )

        provider = await KeycloakOrganizationProvider.from_client_credentials(
            server_url=server_url,
            realm=realm,
            client_id=OAUTH_CLIENT_ID.value,
            client_secret=OAUTH_CLIENT_SECRET.value,
            use_groups=request.use_groups,
            use_organizations=request.use_organizations,
            group_filter=request.group_filter,
        )

        result = await provider.sync_to_db()
        return {"success": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Error syncing from Keycloak: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


class GoogleSyncRequest(BaseModel):
    """Google Workspace에서 조직 동기화 요청"""

    use_org_units: bool = True
    use_groups: bool = False


@router.post("/sync/google")
async def sync_from_google(
    request: GoogleSyncRequest,
    user=Depends(get_admin_user),
):
    """
    Google Workspace에서 조직 동기화

    서비스 계정 + 도메인 위임 방식.
    GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY, GOOGLE_ADMIN_IMPERSONATE_EMAIL 환경변수 필요.
    """
    try:
        from open_webui.config import (
            GOOGLE_ADMIN_IMPERSONATE_EMAIL,
            GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY,
        )

        if not GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY or not GOOGLE_ADMIN_IMPERSONATE_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google Admin API not configured. Set GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY and GOOGLE_ADMIN_IMPERSONATE_EMAIL environment variables.",
            )

        from open_webui.services.organization_providers.google_provider import (
            GoogleOrganizationProvider,
        )

        provider = await GoogleOrganizationProvider.from_service_account(
            service_account_key=GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY,
            impersonate_email=GOOGLE_ADMIN_IMPERSONATE_EMAIL,
            use_org_units=request.use_org_units,
            use_groups=request.use_groups,
        )

        try:
            result = await provider.sync_to_db()
        finally:
            await provider.aclose()
        return {"success": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Error syncing from Google Workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT(str(e)),
        )


@router.get("/sync/providers")
async def get_available_providers(user=Depends(get_admin_user)):
    """사용 가능한 Provider 목록"""
    return {
        "providers": [
            {
                "type": "json",
                "name": "JSON Import",
                "description": "Import organization structure from JSON data",
            },
            {
                "type": "msgraph",
                "name": "Microsoft Graph",
                "description": "Sync from Microsoft Entra ID (Azure AD)",
                "requires": [
                    "MICROSOFT_CLIENT_ID",
                    "MICROSOFT_CLIENT_SECRET",
                    "MICROSOFT_CLIENT_TENANT_ID",
                ],
            },
            {
                "type": "keycloak",
                "name": "Keycloak",
                "description": "Sync from Keycloak groups and organizations",
                "requires": [
                    "OPENID_PROVIDER_URL",
                    "OAUTH_CLIENT_ID",
                    "OAUTH_CLIENT_SECRET",
                ],
            },
            {
                "type": "google",
                "name": "Google Workspace",
                "description": "Sync from Google Workspace Directory",
                "requires": [
                    "GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY",
                    "GOOGLE_ADMIN_IMPERSONATE_EMAIL",
                ],
            },
        ]
    }


############################
# Organizational Unit Permissions
############################


@router.get("/units/{unit_id}/permissions")
async def get_organizational_unit_permissions(
    unit_id: str,
    user=Depends(get_admin_user),
):
    """
    조직 단위에 할당된 리소스 권한 목록 조회
    하위 조직 단위가 상속받는 권한도 포함
    """
    from open_webui.models.dbsphere import DbSpheres
    from open_webui.models.glossary import Glossaries
    from open_webui.models.guardrails import Guardrails
    from open_webui.models.knowledge import Knowledges
    from open_webui.models.models import Models
    from open_webui.models.prompts import Prompts
    from open_webui.models.tool_connections import ToolConnections

    # 해당 조직 단위와 모든 상위 조직 단위 ID 조회 (권한 상속)
    unit = OrganizationalUnits.get_organizational_unit_by_id(unit_id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # 상위 조직 단위들도 포함
    from open_webui.utils.access_control import get_org_unit_ancestors

    ancestor_ids = get_org_unit_ancestors(unit_id)

    permissions = {
        "knowledge": [],
        "tools": [],
        "prompts": [],
        "models": [],
        "databases": [],
        "glossaries": [],
        "guardrails": [],
    }

    def check_access_control(access_control: dict, org_unit_ids: list) -> dict:
        """access_control에서 org_unit_ids가 포함된 권한 체크"""
        if not access_control:
            return None

        result = {"read": False, "write": False, "inherited": False}

        read_org_units = access_control.get("read", {}).get("org_unit_ids", [])
        write_org_units = access_control.get("write", {}).get("org_unit_ids", [])

        for org_id in org_unit_ids:
            if org_id in read_org_units:
                result["read"] = True
                if org_id != unit_id:
                    result["inherited"] = True
            if org_id in write_org_units:
                result["write"] = True
                if org_id != unit_id:
                    result["inherited"] = True

        if result["read"] or result["write"]:
            return result
        return None

    # Knowledge 조회
    try:
        for kb in Knowledges.get_knowledge_bases():
            if kb.access_control:
                access = check_access_control(kb.access_control, ancestor_ids)
                if access:
                    permissions["knowledge"].append(
                        {
                            "id": kb.id,
                            "name": kb.name,
                            "description": kb.description,
                            **access,
                        }
                    )
    except Exception as e:
        log.warning(f"Error checking knowledge permissions: {e}")

    # Tool Connections 조회
    try:
        for tool in ToolConnections.get_tool_connections():
            if tool.access_control:
                access = check_access_control(tool.access_control, ancestor_ids)
                if access:
                    permissions["tools"].append(
                        {
                            "id": tool.id,
                            "name": tool.name,
                            "description": tool.description,
                            **access,
                        }
                    )
    except Exception as e:
        log.warning(f"Error checking tool_connections permissions: {e}")

    # Prompts 조회
    try:
        for prompt in Prompts.get_prompts():
            if prompt.access_control:
                access = check_access_control(prompt.access_control, ancestor_ids)
                if access:
                    permissions["prompts"].append(
                        {"id": prompt.id, "name": prompt.title, **access}
                    )
    except Exception as e:
        log.warning(f"Error checking prompts permissions: {e}")

    # Models 조회
    try:
        for model in Models.get_models():
            if model.access_control:
                access = check_access_control(model.access_control, ancestor_ids)
                if access:
                    permissions["models"].append(
                        {"id": model.id, "name": model.name, **access}
                    )
    except Exception as e:
        log.warning(f"Error checking models permissions: {e}")

    # Databases 조회
    try:
        for db in DbSpheres.get_dbspheres():
            if db.access_control:
                access = check_access_control(db.access_control, ancestor_ids)
                if access:
                    permissions["databases"].append(
                        {
                            "id": db.id,
                            "name": db.name,
                            "description": db.description,
                            **access,
                        }
                    )
    except Exception as e:
        log.warning(f"Error checking databases permissions: {e}")

    # Glossaries 조회
    try:
        for glossary in Glossaries.get_glossaries():
            if glossary.access_control:
                access = check_access_control(glossary.access_control, ancestor_ids)
                if access:
                    permissions["glossaries"].append(
                        {
                            "id": glossary.id,
                            "name": glossary.name,
                            "description": glossary.description,
                            **access,
                        }
                    )
    except Exception as e:
        log.warning(f"Error checking glossaries permissions: {e}")

    # Guardrails 조회
    try:
        for guardrail in Guardrails.get_guardrails():
            if guardrail.access_control:
                access = check_access_control(guardrail.access_control, ancestor_ids)
                if access:
                    permissions["guardrails"].append(
                        {
                            "id": guardrail.id,
                            "name": guardrail.name,
                            "description": guardrail.description,
                            **access,
                        }
                    )
    except Exception as e:
        log.warning(f"Error checking guardrails permissions: {e}")

    return {
        "unit_id": unit_id,
        "unit_name": unit.display_name or unit.name,
        "permissions": permissions,
        "ancestor_ids": ancestor_ids,
    }


############################
# Organization Guardrail Settings
############################


class OrgGuardrailForm(BaseModel):
    guardrail_ids: list[str] = []
    follow_global: bool = False


@router.get("/units/{unit_id}/guardrails")
async def get_unit_guardrails(unit_id: str, user=Depends(get_admin_user)):
    """조직 단위의 가드레일 설정 조회"""
    unit = OrganizationalUnits.get_organizational_unit_by_id(unit_id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    meta = unit.meta or {}
    return {
        "guardrail_ids": meta.get("guardrail_ids", []),
        "follow_global": meta.get("follow_global_guardrail", True),
    }


@router.post("/units/{unit_id}/guardrails")
async def update_unit_guardrails(
    unit_id: str,
    form_data: OrgGuardrailForm,
    user=Depends(get_admin_user),
):
    """조직 단위의 가드레일 설정 업데이트"""
    unit = OrganizationalUnits.get_organizational_unit_by_id(unit_id)
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    meta = unit.meta or {}
    meta["guardrail_ids"] = form_data.guardrail_ids
    meta["follow_global_guardrail"] = form_data.follow_global
    updated = OrganizationalUnits.update_organizational_unit_by_id(
        unit_id, OrganizationalUnitUpdateForm(meta=meta)
    )
    if updated:
        return {
            "guardrail_ids": meta["guardrail_ids"],
            "follow_global": meta["follow_global_guardrail"],
        }
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Error updating guardrail settings"),
    )


############################
# Organization by ID (와일드카드 — 반드시 마지막에 위치)
############################


@router.get("/{id}", response_model=Optional[OrganizationModel])
async def get_organization_by_id(id: str, user=Depends(get_verified_user)):
    """ID로 조직 가져오기"""
    org = Organizations.get_organization_by_id(id)
    if org:
        return org
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


@router.post("/{id}", response_model=Optional[OrganizationModel])
async def update_organization(
    id: str,
    form_data: OrganizationUpdateForm,
    user=Depends(get_admin_user),
):
    """조직 업데이트"""
    org = Organizations.update_organization_by_id(id, form_data)
    if org:
        return org
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


@router.delete("/{id}")
async def delete_organization(id: str, user=Depends(get_admin_user)):
    """조직 삭제"""
    success = Organizations.delete_organization_by_id(id)
    if success:
        return {"success": True}
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )
