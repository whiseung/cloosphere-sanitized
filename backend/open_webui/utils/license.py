"""
Cloosphere License Management Module

Offline JWT-based license verification using RS256.
Public key is embedded in the application; private key is used
by a separate key generator tool (not part of this codebase).

License Types:
- License Key: Determines the tier (Basic/Standard/Professional)
- Feature Key: Enables individual modules independently

Enforcement:
- Controlled by ENABLE_LICENSE_ENFORCEMENT flag
- When disabled (default), all features are available
- When enabled, features are gated by license tier + feature keys
"""

import logging
import os
from enum import Enum
from typing import Optional

import jwt
from fastapi import HTTPException, Request, status
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################################
# Public Key (RS256)
####################################

_env_pubkey = os.environ.get("CLOOSPHERE_PUBLIC_KEY", "").strip()
CLOOSPHERE_PUBLIC_KEY = (
    _env_pubkey
    or """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwCK7vQoNr+a1KnSqaBht
5WrmE8rzBgxnLloEU6wWyyBwPqQJ6OOM5NXQDNncuLpN/zZr7iOhEApy15JV97O5
qKmDL+v0xChouO+05DPAIfDeYFnskMv1fOJzHKrR4req7VyCnYkF87tsZFE3F9RA
OA1cNDFi18fW3VE77UCopmo6tfyIsNNaznMALbRowfdhPQoh9irUwQzmB0Ryurlv
8Hn2rk3f4v1uEyLSLySFVw6qn8kIa42lljhj9eGoBq0YlImjFL30kXRL4Mmo/nPx
bMm4uJXprP+eXR7YI7uwCXzmV9kp5A3P7Munt5SSGmMgbM4LcVUlpepR2JwY2YML
uwIDAQAB
-----END PUBLIC KEY-----"""
)

JWT_ALGORITHM = "RS256"
JWT_ISSUER = "cloosphere"


####################################
# Enums
####################################


class LicenseTier(str, Enum):
    BASIC = "basic"
    STANDARD = "standard"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    DEVELOPER = "developer"


class FeatureModule(str, Enum):
    # Standard tier
    AUDIT_LOG = "audit_log"
    GLOSSARY = "glossary"
    GUARDRAIL = "guardrail"
    IMAGE_GENERATION = "image_generation"
    KBSPHERE = "kbsphere"
    TOOLS = "tools"
    # Professional tier
    AGENT_FLOW = "agent_flow"
    AI_DASHBOARD = "ai_dashboard"
    BRANDING = "branding"
    DBSPHERE = "dbsphere"
    DOCUMENT_TEMPLATES = "document_templates"
    EMBED_WIDGET = "embed_widget"
    EVALUATION = "evaluation"
    TRACE = "trace"
    # Enterprise only
    CODE_GATEWAY = "code_gateway"
    ENCRYPTION = "encryption"
    FILE_GUARDRAIL = "file_guardrail"
    GLOBAL_GUARDRAIL = "global_guardrail"
    KNOWLEDGE_GRAPH = "knowledge_graph"


####################################
# Tier → Module Mapping
####################################

# 하드코딩 fallback — CLOOCUS_ADMIN_DATABASE_URL 미설정 시 (고객사 환경) 사용.
# 개발자 모드에서는 기능 레지스트리 DB가 이 매핑을 대체함.
TIER_INCLUDED_MODULES: dict[LicenseTier, set[FeatureModule]] = {
    LicenseTier.BASIC: set(),
    LicenseTier.STANDARD: {
        FeatureModule.AUDIT_LOG,
        FeatureModule.GLOSSARY,
        FeatureModule.GUARDRAIL,
        FeatureModule.IMAGE_GENERATION,
        FeatureModule.KBSPHERE,
        FeatureModule.TOOLS,
    },
    LicenseTier.PROFESSIONAL: {
        FeatureModule.AUDIT_LOG,
        FeatureModule.GLOSSARY,
        FeatureModule.GUARDRAIL,
        FeatureModule.IMAGE_GENERATION,
        FeatureModule.KBSPHERE,
        FeatureModule.TOOLS,
        FeatureModule.AGENT_FLOW,
        FeatureModule.AI_DASHBOARD,
        FeatureModule.BRANDING,
        FeatureModule.DBSPHERE,
        FeatureModule.DOCUMENT_TEMPLATES,
        FeatureModule.EMBED_WIDGET,
        FeatureModule.EVALUATION,
        FeatureModule.TRACE,
    },
    # ENTERPRISE 이상: has_all_features=True (향후 추가 모듈 자동 포함)
    # Enterprise 전용 모듈: CODE_GATEWAY, FILE_GUARDRAIL, GLOBAL_GUARDRAIL, KNOWLEDGE_GRAPH
    LicenseTier.ENTERPRISE: set(),
    LicenseTier.DEVELOPER: set(),
}

TIER_PRIORITY = {
    LicenseTier.BASIC: 1,
    LicenseTier.STANDARD: 2,
    LicenseTier.PROFESSIONAL: 3,
    LicenseTier.ENTERPRISE: 4,
    LicenseTier.DEVELOPER: 5,
}

# 이 우선순위 이상이면 has_all_features=True (향후 추가 모듈 자동 포함)
TIER_ALL_FEATURES_THRESHOLD = 4  # ENTERPRISE 이상


def load_tier_modules_from_db() -> Optional[dict[LicenseTier, set["FeatureModule"]]]:
    """기능 레지스트리 DB에서 tier→module 매핑을 로드.

    CLOOCUS_ADMIN_DATABASE_URL 미설정이거나 오류 시 None 반환 (fallback 사용).
    """
    from open_webui.internal.cloocus_db import get_cloocus_db, is_cloocus_db_available

    if not is_cloocus_db_available():
        return None

    try:
        from open_webui.models.cloocus_admin import CloocusFeatureRegistry

        with get_cloocus_db() as db:
            features = (
                db.query(CloocusFeatureRegistry)
                .filter(CloocusFeatureRegistry.is_active.is_(True))
                .all()
            )

        result: dict[LicenseTier, set[FeatureModule]] = {
            tier: set() for tier in LicenseTier
        }

        for f in features:
            try:
                module = FeatureModule(f.module_id)
            except ValueError:
                continue

            if not f.tier_minimum:
                continue

            try:
                min_tier = LicenseTier(f.tier_minimum)
            except ValueError:
                continue

            min_priority = TIER_PRIORITY.get(min_tier, 0)

            # tier_minimum 이상의 모든 티어에 모듈 추가
            # (ENTERPRISE 이상은 has_all_features=True이므로 빈 set 유지)
            for tier, priority in TIER_PRIORITY.items():
                if priority >= min_priority and priority < TIER_ALL_FEATURES_THRESHOLD:
                    result[tier].add(module)

        log.info(
            f"Loaded tier-module mapping from feature registry DB: "
            f"{sum(len(v) for v in result.values())} module-tier pairs"
        )
        return result

    except Exception as e:
        log.error(f"Failed to load tier-module mapping from DB: {e}")
        return None


def get_tier_modules() -> dict[LicenseTier, set["FeatureModule"]]:
    """tier-module 매핑 반환. 개발자 DB 우선, 없으면 하드코딩 fallback."""
    db_mapping = load_tier_modules_from_db()
    if db_mapping is not None:
        return db_mapping
    return TIER_INCLUDED_MODULES


####################################
# Pydantic Models
####################################


class LicenseKeyPayload(BaseModel):
    iss: str
    type: str  # "license"
    tier: str
    company: str
    max_users: int = 0
    exp: Optional[int] = None
    iat: int


class FeatureKeyPayload(BaseModel):
    iss: str
    type: str  # "feature"
    module: str
    company: str
    exp: Optional[int] = None
    iat: int


class KeyInfo(BaseModel):
    token: str
    type: str  # "license" or "feature"
    payload: dict
    valid: bool
    error: Optional[str] = None


class LicenseStatus(BaseModel):
    has_license: bool = False
    tier: Optional[str] = None
    company: Optional[str] = None
    max_users: int = 0
    expires_at: Optional[int] = None
    license_keys: list[KeyInfo] = []
    feature_keys: list[KeyInfo] = []
    permissions: dict[str, bool] = {}
    enforcement_enabled: bool = False
    has_all_features: bool = False


####################################
# JWT Decode Functions
####################################


def decode_license_key(token: str) -> tuple[Optional[LicenseKeyPayload], Optional[str]]:
    """Decode and validate a license JWT token.

    Returns (payload, None) on success or (None, error_message) on failure.
    """
    try:
        data = jwt.decode(
            token,
            CLOOSPHERE_PUBLIC_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
        if data.get("type") != "license":
            return None, "Invalid key type: expected 'license'"
        payload = LicenseKeyPayload(**data)
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "License key has expired"
    except jwt.InvalidIssuerError:
        return None, "Invalid issuer"
    except jwt.InvalidSignatureError:
        return None, "Invalid signature"
    except jwt.DecodeError as e:
        return None, f"Failed to decode key: {e}"
    except Exception as e:
        return None, f"Validation error: {e}"


def decode_feature_key(token: str) -> tuple[Optional[FeatureKeyPayload], Optional[str]]:
    """Decode and validate a feature JWT token.

    Returns (payload, None) on success or (None, error_message) on failure.
    """
    try:
        data = jwt.decode(
            token,
            CLOOSPHERE_PUBLIC_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
        if data.get("type") != "feature":
            return None, "Invalid key type: expected 'feature'"
        payload = FeatureKeyPayload(**data)
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Feature key has expired"
    except jwt.InvalidIssuerError:
        return None, "Invalid issuer"
    except jwt.InvalidSignatureError:
        return None, "Invalid signature"
    except jwt.DecodeError as e:
        return None, f"Failed to decode key: {e}"
    except Exception as e:
        return None, f"Validation error: {e}"


def _decode_any_key(token: str) -> tuple[Optional[dict], Optional[str]]:
    """Decode a JWT token without type validation, returning raw payload."""
    try:
        data = jwt.decode(
            token,
            CLOOSPHERE_PUBLIC_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
        return data, None
    except jwt.ExpiredSignatureError:
        return None, "Key has expired"
    except jwt.InvalidIssuerError:
        return None, "Invalid issuer"
    except jwt.InvalidSignatureError:
        return None, "Invalid signature"
    except jwt.DecodeError as e:
        return None, f"Failed to decode key: {e}"
    except Exception as e:
        return None, f"Validation error: {e}"


####################################
# License Resolution
####################################


def resolve_license_status(
    license_keys: list[str],
    feature_keys: list[str],
    enforcement_enabled: bool = False,
    tier_modules: Optional[dict[LicenseTier, set["FeatureModule"]]] = None,
) -> LicenseStatus:
    """Resolve the overall license status from all registered keys.

    Processes all license keys and feature keys, determines the effective
    tier (highest valid tier wins), and computes per-module permissions.
    tier_modules가 주어지면 DB 기반 매핑 사용, 없으면 하드코딩 fallback.
    """
    status = LicenseStatus(enforcement_enabled=enforcement_enabled)

    # Initialize all permissions to False
    for module in FeatureModule:
        status.permissions[module.value] = False

    # Process license keys
    best_tier: Optional[LicenseTier] = None
    best_tier_priority = 0

    for token in license_keys:
        payload, error = decode_license_key(token)
        key_info = KeyInfo(
            token=token,
            type="license",
            payload=payload.model_dump() if payload else {},
            valid=payload is not None,
            error=error,
        )
        status.license_keys.append(key_info)

        if payload:
            try:
                tier = LicenseTier(payload.tier)
                priority = TIER_PRIORITY.get(tier, 0)
                if priority > best_tier_priority:
                    best_tier = tier
                    best_tier_priority = priority
                    status.has_license = True
                    status.tier = tier.value
                    status.company = payload.company
                    status.max_users = payload.max_users
                    status.expires_at = payload.exp
            except ValueError:
                key_info.valid = False
                key_info.error = f"Unknown tier: {payload.tier}"

    # Apply tier modules
    if best_tier:
        if best_tier_priority >= TIER_ALL_FEATURES_THRESHOLD:
            # PROFESSIONAL 이상: 모든 현재 및 미래 기능 자동 허용
            status.has_all_features = True
            for module in FeatureModule:
                status.permissions[module.value] = True
        else:
            effective_mapping = (
                tier_modules if tier_modules is not None else TIER_INCLUDED_MODULES
            )
            for module in effective_mapping.get(best_tier, set()):
                status.permissions[module.value] = True

    # Process feature keys (additive)
    for token in feature_keys:
        payload, error = decode_feature_key(token)
        key_info = KeyInfo(
            token=token,
            type="feature",
            payload=payload.model_dump() if payload else {},
            valid=payload is not None,
            error=error,
        )
        status.feature_keys.append(key_info)

        if payload:
            module_str = payload.module
            try:
                module = FeatureModule(module_str)
                status.permissions[module.value] = True
            except ValueError:
                # 미지 모듈: Enum에 없어도 동적으로 허용
                status.permissions[module_str] = True

    return status


####################################
# Feature Check Helpers
####################################


def is_feature_enabled(app, module: str) -> bool:
    """Check if a feature module is enabled based on current license status.

    Returns True if:
    - Enforcement is disabled (default), OR
    - has_all_features is True (PROFESSIONAL tier or above), OR
    - The module is permitted by the current license/feature keys
    """
    # Ensure LICENSE_STATUS is fresh across workers
    try:
        from open_webui.routers.license import ensure_license_status_fresh

        ensure_license_status_fresh(app)
    except ImportError:
        pass

    license_status: Optional[LicenseStatus] = getattr(app.state, "LICENSE_STATUS", None)
    if license_status is None or not license_status.enforcement_enabled:
        return True
    if license_status.has_all_features:
        return True
    return license_status.permissions.get(module, False)


def require_feature(module: str):
    """FastAPI dependency that gates access to a feature module.

    Usage:
        router = APIRouter(dependencies=[Depends(require_feature("dbsphere"))])

    Or per-endpoint:
        @router.get("/", dependencies=[Depends(require_feature("dbsphere"))])
    """

    async def _check_feature(request: Request):
        if not is_feature_enabled(request.app, module):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires a valid license. Module '{module}' is not enabled.",
            )

    return _check_feature
