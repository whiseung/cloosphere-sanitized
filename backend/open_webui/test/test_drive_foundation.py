"""Foundation-layer tests for the Google Drive chat integration.

Covers the pure-unit, app-boot-free deliverables of the backend foundation:
  * config.py — ENABLE_DRIVE_INTEGRATION PersistentConfig + DEFAULT_USER_PERMISSIONS
  * models/agent_config.py — CapabilitiesConfig.drive + has_drive()
  * models/audit_log.py — DRIVE_CREATE_DOC / DRIVE_CREATE_DOC_FAILED

These mirror the existing Gmail/Calendar foundation exactly.
"""

from __future__ import annotations


def test_enable_drive_integration_config_path():
    from open_webui.config import ENABLE_DRIVE_INTEGRATION

    assert ENABLE_DRIVE_INTEGRATION.config_path == "google.integration.drive.enable"
    # Distinct from the pre-existing RAG file-picker flag.
    assert ENABLE_DRIVE_INTEGRATION.env_name == "ENABLE_DRIVE_INTEGRATION"


def test_default_user_permissions_has_drive_feature():
    from open_webui.config import DEFAULT_USER_PERMISSIONS

    assert "drive" in DEFAULT_USER_PERMISSIONS["features"]
    assert isinstance(DEFAULT_USER_PERMISSIONS["features"]["drive"], bool)


def test_has_drive_reflects_capability_on():
    from open_webui.models.agent_config import AgentConfig, CapabilitiesConfig

    cfg = AgentConfig(capabilities=CapabilitiesConfig(drive="on"))
    assert cfg.has_drive() is True


def test_has_drive_reflects_capability_user():
    from open_webui.models.agent_config import AgentConfig, CapabilitiesConfig

    cfg = AgentConfig(capabilities=CapabilitiesConfig(drive="user"))
    assert cfg.has_drive() is True


def test_has_drive_off_by_default():
    from open_webui.models.agent_config import AgentConfig, CapabilitiesConfig

    # Explicit off
    cfg = AgentConfig(capabilities=CapabilitiesConfig(drive="off"))
    assert cfg.has_drive() is False
    # Capabilities omitted entirely (legacy agent) → opt-in default off
    legacy = AgentConfig()
    assert legacy.has_drive() is False


def test_capabilities_drive_normalizes_legacy_bool():
    from open_webui.models.agent_config import CapabilitiesConfig

    assert CapabilitiesConfig(drive=True).drive == "on"
    assert CapabilitiesConfig(drive=False).drive == "off"
    # Field default is off (opt-in)
    assert CapabilitiesConfig().drive == "off"


def test_from_model_info_parses_drive_capability():
    from open_webui.models.agent_config import AgentConfig

    cfg = AgentConfig.from_model_info(
        params={},
        meta={"capabilities": {"drive": "on"}},
        model_id="m",
        base_model_id="base",
    )
    assert cfg.has_drive() is True


def test_audit_action_drive_create_doc_value():
    from open_webui.models.audit_log import AuditAction

    assert AuditAction.DRIVE_CREATE_DOC.value == "DRIVE_CREATE_DOC"
    assert AuditAction.DRIVE_CREATE_DOC_FAILED.value == "DRIVE_CREATE_DOC_FAILED"


def test_drive_document_not_added_to_resource_type_enum():
    from open_webui.models.audit_log import AuditResourceType

    # resource_type "drive_document" is a literal used at the call site,
    # intentionally NOT a member of the AuditResourceType enum.
    assert "drive_document" not in {m.value for m in AuditResourceType}
