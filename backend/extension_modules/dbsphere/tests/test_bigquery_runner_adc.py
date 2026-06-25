"""BigQueryRunner._get_client_sync — ADC branch vs service-account branch.

google-cloud-bigquery is not installed here; inject a fake module so we can
assert how bigquery.Client is constructed.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from extension_modules.dbsphere.dbsphere_state import DBConfig
from extension_modules.dbsphere.sql_runners.bigquery import BigQueryRunner


def _bigquery_config(**overrides) -> DBConfig:
    """DBConfig with the (unused-for-BigQuery) required connection fields filled."""
    base = dict(
        db_type="bigquery",
        host="",
        port=0,
        database="",
        username="",
        password="",
    )
    base.update(overrides)
    return DBConfig(**base)


@pytest.fixture
def fake_bigquery(monkeypatch):
    """Install a fake google.cloud.bigquery; capture Client() kwargs."""
    captured: dict = {}

    fake_bq = types.ModuleType("google.cloud.bigquery")

    class FakeClient:
        def __init__(self, project=None, credentials=None):
            captured["project"] = project
            captured["credentials"] = credentials
            self.project = project

        def close(self):
            pass

    fake_bq.Client = FakeClient

    google_mod = sys.modules.get("google") or types.ModuleType("google")
    cloud_mod = types.ModuleType("google.cloud")
    cloud_mod.bigquery = fake_bq

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_mod)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake_bq)
    return captured


def test_adc_builds_client_without_credentials(fake_bigquery):
    cfg = _bigquery_config(project_id="my-proj", use_adc=True)
    runner = BigQueryRunner(cfg)

    client = runner._get_client_sync()

    assert client.project == "my-proj"
    assert fake_bigquery["project"] == "my-proj"
    # ADC = no explicit credentials passed
    assert fake_bigquery["credentials"] is None
    asyncio.run(runner.close())


def test_adc_requires_project_id(fake_bigquery):
    cfg = _bigquery_config(project_id=None, use_adc=True)
    runner = BigQueryRunner(cfg)

    with pytest.raises(ValueError, match="project_id is required"):
        runner._get_client_sync()


def test_service_account_mode_still_requires_credentials(fake_bigquery):
    """Regression: use_adc=False (default) with no key raises as before."""
    cfg = _bigquery_config(project_id="my-proj", credentials_json=None)
    runner = BigQueryRunner(cfg)

    with pytest.raises(ValueError, match="credentials_json is required"):
        runner._get_client_sync()
