"""Router-level BigQuery ADC handling: form field, DBConfig conversion,
service-account credential stripping for persistence and masked-resolution."""

from __future__ import annotations

from open_webui.routers.dbsphere import (
    ConnectionTestForm,
    _form_to_dbconfig,
    _resolve_masked_connection_form,
    _strip_adc_service_account,
)


def test_connection_test_form_accepts_use_adc():
    form = ConnectionTestForm(db_type="bigquery", host="", use_adc=True, project_id="p")
    assert form.use_adc is True


def test_form_to_dbconfig_passes_use_adc_and_clears_key():
    form = ConnectionTestForm(
        db_type="bigquery",
        host="",
        use_adc=True,
        project_id="p",
        dataset_id="d",
        credentials_json='{"type": "service_account"}',
    )
    cfg = _form_to_dbconfig(form, "BIGQUERY")
    assert cfg.use_adc is True
    # ADC mode must not carry a service account key through.
    assert cfg.credentials_json == ""


def test_form_to_dbconfig_keeps_key_when_not_adc():
    form = ConnectionTestForm(
        db_type="bigquery",
        host="",
        use_adc=False,
        project_id="p",
        credentials_json='{"type": "service_account"}',
    )
    cfg = _form_to_dbconfig(form, "BIGQUERY")
    assert cfg.use_adc is False
    assert cfg.credentials_json == '{"type": "service_account"}'


def test_strip_adc_service_account_clears_key():
    data = {"connection": {"use_adc": True, "credentials_json": "secret"}}
    out = _strip_adc_service_account(data)
    assert out["connection"]["credentials_json"] == ""


def test_strip_adc_service_account_noop_when_not_adc():
    data = {"connection": {"credentials_json": "secret"}}
    out = _strip_adc_service_account(data)
    assert out["connection"]["credentials_json"] == "secret"


def test_resolve_masked_form_clears_credentials_for_adc():
    """ADC clears credentials_json up front, no DB lookup needed."""
    form = ConnectionTestForm(
        db_type="bigquery", host="", use_adc=True, credentials_json="**********"
    )
    _resolve_masked_connection_form(form)
    assert form.credentials_json == ""
