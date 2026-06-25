"""
Google Workspace Organization Provider

Google Admin Directory API를 통해 조직 구조를 가져오는 Provider.
서비스 계정 + 도메인 전체 위임(Domain-Wide Delegation) 방식.

필요한 GCP API 스코프:
- https://www.googleapis.com/auth/admin.directory.user.readonly
- https://www.googleapis.com/auth/admin.directory.group.readonly
- https://www.googleapis.com/auth/admin.directory.group.member.readonly
- https://www.googleapis.com/auth/admin.directory.orgunit.readonly
- https://www.googleapis.com/auth/admin.directory.customer.readonly

설정 필요:
- GOOGLE_ADMIN_SERVICE_ACCOUNT_KEY: 서비스 계정 JSON 키 (문자열)
- GOOGLE_ADMIN_IMPERSONATE_EMAIL: 대행할 슈퍼 관리자 이메일
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

import aiohttp
from authlib.jose import jwt as jose_jwt

from open_webui.env import SRC_LOG_LEVELS

from .base import OrganizationData, OrganizationProvider, OrgUnitData

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

ADMIN_API_BASE = "https://admin.googleapis.com/admin/directory/v1"
_API_TIMEOUT = aiohttp.ClientTimeout(total=30)
# 동시 API 호출 수 제한 (env var override 가능)
# Google Admin Directory API quota: 100 q/s per user (default), 50 q/s 안전 버퍼
_DEFAULT_CONCURRENCY = int(os.getenv("GOOGLE_ADMIN_API_CONCURRENCY", "15"))
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds

# Google Admin Directory API 전체 scope (토큰 발급 시 공용)
GOOGLE_ADMIN_SCOPES = (
    "https://www.googleapis.com/auth/admin.directory.user.readonly "
    "https://www.googleapis.com/auth/admin.directory.group.readonly "
    "https://www.googleapis.com/auth/admin.directory.group.member.readonly "
    "https://www.googleapis.com/auth/admin.directory.orgunit.readonly "
    "https://www.googleapis.com/auth/admin.directory.customer.readonly"
)


async def get_google_admin_access_token(
    service_account_key: str,
    impersonate_email: str,
    scopes: str | None = None,
) -> str | None:
    """
    서비스 계정 + 도메인 위임으로 Google Admin Directory API용 access_token을 발급받는다.
    JWT를 직접 생성하여 Google OAuth2 token endpoint에 교환하는 방식.

    oauth.py (로그인 시 사용자 조회)와 google_provider (batch sync) 양쪽에서 공용으로 사용.
    """
    if not service_account_key or not impersonate_email:
        return None

    try:
        sa_info = json.loads(service_account_key)
    except json.JSONDecodeError as e:
        log.error(f"Google service account key is not valid JSON: {e}")
        return None

    private_key_pem = sa_info.get("private_key")
    client_email = sa_info.get("client_email")
    if not private_key_pem or not client_email:
        log.error(
            "Google service account key missing required fields: private_key, client_email"
        )
        return None

    try:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": client_email,
            "sub": impersonate_email,
            "scope": scopes or GOOGLE_ADMIN_SCOPES,
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }

        signed_jwt = jose_jwt.encode(header, claims, private_key_pem).decode("utf-8")

        async with aiohttp.ClientSession(timeout=_API_TIMEOUT) as session:
            async with session.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_jwt,
                },
            ) as resp:
                if not resp.ok:
                    log.error(
                        f"Google Admin token exchange failed: {resp.status} {await resp.text()}"
                    )
                    return None
                token_data = await resp.json()
                access_token = token_data.get("access_token")
                if not access_token:
                    log.error("Google Admin token response missing access_token")
                    return None
                return access_token
    except Exception as e:
        log.error(f"Google Admin access token error: {e}")
        return None


class GoogleOrganizationProvider(OrganizationProvider):
    """
    Google Admin Directory API 기반 Organization Provider

    사용 예시:
    ```python
    provider = GoogleOrganizationProvider.from_service_account(
        service_account_key='{"type":"service_account",...}',
        impersonate_email="admin@company.com",
        use_org_units=True,
        use_groups=True,
    )
    await provider.sync_to_db()
    ```
    """

    provider_type: str = "google"

    def __init__(
        self,
        access_token: str,
        customer_id: str = "my_customer",
        domain: Optional[str] = None,
        use_org_units: bool = True,
        use_groups: bool = False,
        max_concurrency: int = _DEFAULT_CONCURRENCY,
        impersonate_email: Optional[str] = None,
        **kwargs,
    ):
        """
        Args:
            access_token: Google Admin API 액세스 토큰
            customer_id: Google Workspace Customer ID ("my_customer" 기본값)
            domain: Primary 도메인 (자동 감지 가능)
            use_org_units: Organizational Units 가져올지
            use_groups: Google Groups도 조직 단위로 가져올지
            max_concurrency: 동시 API 호출 수 제한 (default 5)
            impersonate_email: 슈퍼 관리자 이메일 (도메인 추출 fallback용)
        """
        self.access_token = access_token
        self.customer_id = customer_id
        self.domain = domain
        self.use_org_units = use_org_units
        self.use_groups = use_groups

        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # 공유 세션 + 동시성 제한 (provider 인스턴스당 1개)
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # 워크스페이스 verified 도메인 캐시 (외부 멤버 필터링용)
        # None = 아직 로드 안 됨, set() = 로드 시도했으나 비어있음
        self._workspace_domains: Optional[set[str]] = None
        # 도메인 API 실패 시 fallback으로 사용할 도메인
        self._fallback_domain: Optional[str] = None
        if impersonate_email and "@" in impersonate_email:
            self._fallback_domain = impersonate_email.split("@", 1)[1].lower()

        # 워크스페이스 전체 사용자 캐시 (N+1 제거용)
        # email_idx: lowercase email/alias → normalized user dict
        # ou_idx: orgUnitPath → list of normalized user dicts (직속만)
        self._users_by_email: Optional[dict[str, dict]] = None
        self._users_by_ou: Optional[dict[str, list[dict]]] = None
        # 동시 gather 호출 시 중복 fetch 방지
        self._users_cache_lock = asyncio.Lock()

    def _ensure_session(self) -> aiohttp.ClientSession:
        """공유 ClientSession을 lazy 생성"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_API_TIMEOUT, headers=self._headers
            )
        return self._session

    async def aclose(self) -> None:
        """세션 정리 (sync 종료 후 호출 필수)"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "GoogleOrganizationProvider":
        self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _admin_request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> Optional[dict]:
        """Google Admin API 요청 (semaphore + 지수 백오프 재시도)"""
        url = f"{ADMIN_API_BASE}{endpoint}"
        session = self._ensure_session()

        async with self._semaphore:
            backoff = _INITIAL_BACKOFF
            last_error: Optional[str] = None

            for attempt in range(_MAX_RETRIES):
                try:
                    async with session.get(url, params=params) as resp:
                        if resp.ok:
                            return await resp.json()

                        # 429 (rate limit): Retry-After 헤더 우선
                        if resp.status == 429:
                            retry_after_hdr = resp.headers.get("Retry-After")
                            try:
                                wait = (
                                    float(retry_after_hdr)
                                    if retry_after_hdr
                                    else backoff
                                )
                            except ValueError:
                                wait = backoff
                            last_error = f"429 rate limited, retry in {wait:.1f}s"
                            log.warning(f"{last_error} (url={url})")
                            await asyncio.sleep(wait)
                        # 5xx: 일시적 서버 오류 → 재시도
                        elif 500 <= resp.status < 600:
                            last_error = (
                                f"{resp.status} server error, retry in {backoff:.1f}s"
                            )
                            log.warning(f"{last_error} (url={url})")
                            await asyncio.sleep(backoff)
                        # 그 외 4xx: 영구 오류 → 재시도 안 함
                        else:
                            error_text = await resp.text()
                            log.error(
                                f"Google Admin API error: {resp.status} - {error_text} (url={url})"
                            )
                            return None
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_error = f"network error: {e}"
                    log.warning(
                        f"{last_error}, retry in {backoff:.1f}s (url={url}, attempt={attempt + 1})"
                    )
                    await asyncio.sleep(backoff)

                backoff *= 2  # 지수 백오프: 1s → 2s → 4s

            log.error(f"Google Admin API max retries reached: {last_error} (url={url})")
            return None

    async def _ensure_workspace_domains(self) -> set[str]:
        """워크스페이스의 verified 도메인 목록을 lazy 로드 (멀티 도메인 지원)"""
        if self._workspace_domains is not None:
            return self._workspace_domains

        domains: set[str] = set()
        data = await self._admin_request(f"/customer/{self.customer_id}/domains")
        if data:
            for d in data.get("domains", []):
                if d.get("verified") and d.get("domainName"):
                    domains.add(d["domainName"].lower())

        # API 실패 또는 빈 응답 → fallback 도메인이라도 채움
        if not domains:
            if self.domain:
                domains.add(self.domain.lower())
            if self._fallback_domain:
                domains.add(self._fallback_domain)
            log.warning(f"Failed to fetch verified domains, using fallback: {domains}")
        else:
            log.info(f"Loaded {len(domains)} verified workspace domains: {domains}")

        self._workspace_domains = domains
        return domains

    def _is_workspace_email(self, email: str, domains: set[str]) -> bool:
        """이메일이 워크스페이스 verified 도메인 소속인지"""
        if not email or "@" not in email:
            return False
        domain = email.rsplit("@", 1)[1].lower()
        return domain in domains

    async def _ensure_users_cache(
        self,
    ) -> tuple[dict[str, dict], dict[str, list[dict]]]:
        """
        워크스페이스 전체 사용자를 1회 페이지네이션으로 가져와 dict로 인덱싱.

        그룹/OU 멤버 detail 조회 시 /users 호출 대신 이 캐시를 lookup → N+1 제거.
        동시 gather 호출 안전 (Lock으로 보호).

        Returns:
            (email_idx, ou_idx)
            email_idx: lowercase email 또는 alias → normalized user dict
            ou_idx: orgUnitPath → list of normalized user dicts (직속 멤버)
        """
        if self._users_by_email is not None and self._users_by_ou is not None:
            return self._users_by_email, self._users_by_ou

        async with self._users_cache_lock:
            # double-check (Lock 대기 중 다른 task가 채웠을 수 있음)
            if self._users_by_email is not None and self._users_by_ou is not None:
                return self._users_by_email, self._users_by_ou

            log.info("Pre-fetching all workspace users for cache...")
            all_users = await self._get_all_pages(
                "/users",
                result_key="users",
                params={
                    "customer": self.customer_id,
                    "projection": "full",
                },
            )

            email_idx: dict[str, dict] = {}
            ou_idx: dict[str, list[dict]] = {}
            alias_count = 0

            for user in all_users:
                primary_email = user.get("primaryEmail", "")
                if not primary_email:
                    continue
                normalized = self._normalize_user(user)
                email_idx[primary_email.lower()] = normalized

                # OU 인덱싱 (직속 OU만)
                ou_path = user.get("orgUnitPath", "/")
                ou_idx.setdefault(ou_path, []).append(normalized)

                # 별칭 등록 (그룹에 별칭으로 가입한 케이스 매칭용)
                for alias in user.get("aliases") or []:
                    if alias and alias.lower() not in email_idx:
                        email_idx[alias.lower()] = normalized
                        alias_count += 1

            log.info(
                f"User cache built: {len(all_users)} users, "
                f"{alias_count} aliases, {len(ou_idx)} OUs indexed"
            )

            self._users_by_email = email_idx
            self._users_by_ou = ou_idx
            return email_idx, ou_idx

    async def _get_all_pages(
        self,
        endpoint: str,
        result_key: str,
        params: Optional[dict] = None,
    ) -> list[dict]:
        """페이지네이션 처리하여 모든 결과 가져오기"""
        results = []
        page_token = None

        while True:
            req_params = dict(params) if params else {}
            if page_token:
                req_params["pageToken"] = page_token

            data = await self._admin_request(endpoint, req_params)
            if not data:
                break

            results.extend(data.get(result_key, []))
            page_token = data.get("nextPageToken")

            if not page_token:
                break

        return results

    async def fetch_organization(self) -> Optional[OrganizationData]:
        """Google Workspace 도메인 정보를 조직으로 매핑"""
        log.info("Fetching organization from Google Admin API...")

        # 도메인 정보 가져오기
        data = await self._admin_request(f"/customers/{self.customer_id}")
        if not data:
            log.warning("No customer data returned from Google Admin API")
            return None

        customer_id = data.get("id", self.customer_id)
        domain = data.get("customerDomain", self.domain or "unknown")
        if domain and domain != "unknown":
            self.domain = domain

        log.info(f"Organization fetched: {domain} (customer_id={customer_id})")

        # verified 도메인 미리 로드 (그룹 멤버 필터링 시 즉시 사용 가능)
        await self._ensure_workspace_domains()

        return OrganizationData(
            id=customer_id,
            tenant_id=customer_id,
            name=domain,
            display_name=domain,
            domain=domain,
            meta={
                "source": "google_workspace",
                "customer_id": customer_id,
                "language": data.get("language"),
                "creation_time": data.get("customerCreationTime"),
            },
        )

    async def fetch_organizational_units(
        self, organization_id: Optional[str] = None
    ) -> list[OrgUnitData]:
        """Google Workspace에서 조직 단위 가져오기"""
        units = []
        log.info(
            f"Fetching organizational units: org_units={self.use_org_units}, groups={self.use_groups}"
        )

        if self.use_org_units:
            ou_units = await self._fetch_org_units()
            log.info(f"Fetched {len(ou_units)} organizational units")
            units.extend(ou_units)

        if self.use_groups:
            group_units = await self._fetch_groups()
            log.info(f"Fetched {len(group_units)} groups")
            units.extend(group_units)

        log.info(f"Total units fetched: {len(units)}")
        return units

    async def _fetch_org_units(self) -> list[OrgUnitData]:
        """
        Google Workspace Organizational Units 가져오기

        GWS의 OU는 파일 시스템 경로 형태 (e.g., /Engineering/Backend).
        orgUnitPath를 기반으로 계층 구조를 재구성한다.
        """
        data = await self._admin_request(
            f"/customer/{self.customer_id}/orgunits",
            params={"type": "all"},
        )
        if not data:
            return []

        org_units = data.get("organizationUnits", [])

        # orgUnitPath → OrgUnitData 변환 + 계층 구조 구성
        path_to_unit: dict[str, OrgUnitData] = {}
        root_units: list[OrgUnitData] = []

        for ou in org_units:
            ou_path = ou.get("orgUnitPath", "/")
            ou_name = ou.get("name", "")
            parent_path = ou.get("parentOrgUnitPath", "/")

            unit = OrgUnitData(
                id=ou_path,
                name=ou_name,
                display_name=ou_name,
                description=ou.get("description"),
                type="organizational_unit",
                external_id=ou_path,  # fetch_unit_members가 "/"로 시작 여부로 분기하므로 ou_path 사용
                meta={
                    "source": "google_ou",
                    "org_unit_id": ou.get("orgUnitId"),
                    "org_unit_path": ou_path,
                    "parent_org_unit_path": parent_path,
                    "block_inheritance": ou.get("blockInheritance", False),
                },
            )
            path_to_unit[ou_path] = unit

        # 계층 구조 연결
        for ou_path, unit in path_to_unit.items():
            parent_path = unit.meta.get("parent_org_unit_path", "/")
            if parent_path in path_to_unit:
                parent = path_to_unit[parent_path]
                parent.children.append(unit)
            else:
                root_units.append(unit)

        return root_units

    async def _fetch_groups(self) -> list[OrgUnitData]:
        """Google Groups를 조직 단위로 가져오기"""
        params = {"customer": self.customer_id}
        if self.domain:
            params["domain"] = self.domain

        groups = await self._get_all_pages(
            "/groups", result_key="groups", params=params
        )

        units = []
        for group in groups:
            units.append(
                OrgUnitData(
                    id=group.get("id", ""),
                    name=group.get("name", group.get("email", "Unnamed")),
                    display_name=group.get("name"),
                    description=group.get("description"),
                    type="google_group",
                    external_id=group.get("id"),
                    meta={
                        "source": "google_group",
                        "email": group.get("email"),
                        "member_count": group.get("directMembersCount"),
                        "admin_created": group.get("adminCreated"),
                    },
                )
            )

        return units

    async def fetch_unit_members(self, unit_id: str) -> list[str]:
        """특정 조직 단위의 멤버 ID 목록 (호환용 — 상세는 with_detail 사용)"""
        member_ids, _ = await self.fetch_unit_members_with_detail(unit_id)
        return member_ids

    async def fetch_unit_members_with_detail(
        self, unit_id: str
    ) -> tuple[list[str], list[dict]]:
        """특정 조직 단위의 멤버 ID + 상세 정보 (name, email, job_title)"""
        # OU 멤버: orgUnitPath로 사용자 검색 (full projection으로 jobTitle 포함)
        if unit_id.startswith("/"):
            return await self._fetch_ou_members_detail(unit_id)
        # 그룹 멤버: group ID로 검색 (멤버 email 기반으로 사용자 조회)
        return await self._fetch_group_members_detail(unit_id)

    async def _fetch_ou_members_detail(
        self, org_unit_path: str
    ) -> tuple[list[str], list[dict]]:
        """특정 OU에 속한 사용자 목록 (사전 캐시에서 lookup, API 호출 0번)"""
        _, ou_idx = await self._ensure_users_cache()
        users = ou_idx.get(org_unit_path, [])

        member_ids: list[str] = []
        members_detail: list[dict] = []
        for user in users:
            email = user.get("email", "")
            if not email:
                continue
            member_ids.append(email.lower())
            members_detail.append(user)

        return member_ids, members_detail

    async def _fetch_group_members_detail(
        self, group_id: str
    ) -> tuple[list[str], list[dict]]:
        """특정 그룹의 워크스페이스 내부 멤버 (사전 캐시 lookup, /users 호출 0번)"""
        # Google Groups API가 id 필드에 "id:" prefix를 포함하는 경우가 있음
        # Members API는 prefix 없는 순수 ID만 허용
        if group_id.startswith("id:"):
            group_id = group_id[3:]
        members = await self._get_all_pages(
            f"/groups/{group_id}/members",
            result_key="members",
            params={"roles": "MEMBER,MANAGER,OWNER"},
        )

        # 도메인 + 사용자 캐시 (모두 lazy load, 첫 호출 시만 fetch)
        workspace_domains = await self._ensure_workspace_domains()
        users_by_email, _ = await self._ensure_users_cache()

        member_ids: list[str] = []
        members_detail: list[dict] = []
        seen_emails: set[str] = set()  # primary + alias 중복 방지
        skipped_external = 0
        skipped_ghost = 0

        for member in members:
            if member.get("type") != "USER":
                continue
            raw_email = member.get("email") or member.get("id", "")
            if not raw_email:
                continue
            email = raw_email.lower()

            # 외부 도메인은 사전 차단
            if not self._is_workspace_email(email, workspace_domains):
                skipped_external += 1
                continue

            # 캐시 lookup (primary email 또는 alias 매칭)
            detail = users_by_email.get(email)
            if not detail:
                # 캐시에 없음 = 삭제됐거나 정지된 ghost 멤버 → 스킵
                skipped_ghost += 1
                continue

            # primary email 기준으로 dedup (같은 사람이 alias로도 가입한 경우)
            primary_email = (detail.get("email") or email).lower()
            if primary_email in seen_emails:
                continue
            seen_emails.add(primary_email)

            member_ids.append(primary_email)
            members_detail.append(detail)

        if skipped_external or skipped_ghost:
            log.debug(
                f"Group {group_id}: skipped {skipped_external} external + "
                f"{skipped_ghost} ghost members"
            )

        return member_ids, members_detail

    @staticmethod
    def _normalize_user(user: dict) -> dict:
        """Google /users 응답을 meta.members 표준 형식으로 변환"""
        name_obj = user.get("name") or {}
        full_name = (
            name_obj.get("fullName")
            or " ".join(
                filter(None, [name_obj.get("givenName"), name_obj.get("familyName")])
            )
            or ""
        )

        # organizations[0].title을 job_title로 사용 (full projection에서만 제공)
        job_title = ""
        organizations = user.get("organizations") or []
        if organizations:
            job_title = organizations[0].get("title", "") or ""

        return {
            "id": user.get("id", ""),
            "name": full_name,
            "email": user.get("primaryEmail", ""),
            "job_title": job_title,
        }

    @classmethod
    async def from_service_account(
        cls,
        service_account_key: str,
        impersonate_email: str,
        **kwargs,
    ) -> "GoogleOrganizationProvider":
        """
        서비스 계정 + 도메인 위임으로 Provider 생성

        Args:
            service_account_key: 서비스 계정 JSON 키 문자열
            impersonate_email: 대행할 슈퍼 관리자 이메일
        """
        access_token = await get_google_admin_access_token(
            service_account_key, impersonate_email
        )
        if not access_token:
            raise Exception("Failed to get Google Admin access token")

        log.info("Google Admin access token obtained successfully")
        return cls(
            access_token=access_token,
            impersonate_email=impersonate_email,
            **kwargs,
        )
