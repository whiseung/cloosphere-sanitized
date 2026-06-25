"""DBConfig BigQuery ADC field — default + from_dbsphere_data backward compat."""

from __future__ import annotations

from extension_modules.dbsphere.dbsphere_state import DBConfig


def test_use_adc_defaults_to_false():
    cfg = DBConfig(
        db_type="bigquery",
        host="",
        port=0,
        database="",
        username="",
        password="",
        project_id="my-proj",
    )
    assert cfg.use_adc is False


def test_from_dbsphere_data_reads_use_adc_true():
    data = {
        "connection": {
            "db_type": "bigquery",
            "project_id": "my-proj",
            "dataset_id": "my_ds",
            "use_adc": True,
        }
    }
    cfg = DBConfig.from_dbsphere_data(data)
    assert cfg.use_adc is True
    assert cfg.project_id == "my-proj"


def test_from_dbsphere_data_missing_use_adc_is_false():
    """Existing rows have no use_adc key — must stay service-account mode."""
    data = {
        "connection": {
            "db_type": "bigquery",
            "project_id": "my-proj",
            "credentials_json": '{"type": "service_account"}',
        }
    }
    cfg = DBConfig.from_dbsphere_data(data)
    assert cfg.use_adc is False
