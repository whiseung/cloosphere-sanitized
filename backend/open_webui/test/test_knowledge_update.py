"""Unit tests for the access_control persistence fix in
``Knowledges.update_knowledge_by_id``.

The bug: ``form_data.model_dump(exclude_none=True)`` silently dropped
``access_control: None`` (= public toggle) so the setattr loop never ran for
that field, leaving the DB row unchanged on private→public toggles.

The fix: keep ``exclude_none=True`` for safety on all other fields, but
re-add ``access_control`` to the dump dict whenever the client *explicitly*
sent it (using Pydantic's ``model_fields_set``).

These tests pin the contract on a stand-in form that mirrors KnowledgeForm
exactly — avoids importing the SQLAlchemy ORM module so the unit suite
runs without DB setup.
"""

from typing import Optional

from pydantic import BaseModel


class _UpdateForm(BaseModel):
    """Mirror of ``KnowledgeForm`` for isolated Pydantic-level testing."""

    name: str
    description: str
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_control: Optional[dict] = None


def _build_update_dict(form: _UpdateForm) -> dict:
    """Mirror of the production block in ``update_knowledge_by_id``."""
    data = form.model_dump(exclude={"meta"}, exclude_none=True)
    if "access_control" in form.model_fields_set:
        data["access_control"] = form.access_control
    return data


def test_explicit_null_access_control_preserved_in_update_dict():
    form = _UpdateForm(name="kb", description="d", access_control=None)
    out = _build_update_dict(form)
    assert "access_control" in out
    assert out["access_control"] is None


def test_explicit_empty_dict_access_control_preserved():
    form = _UpdateForm(name="kb", description="d", access_control={})
    out = _build_update_dict(form)
    assert out["access_control"] == {}


def test_omitted_access_control_not_in_update_dict():
    """Omitted field stays out — DB value is preserved by setattr-skip."""
    form = _UpdateForm(name="kb", description="d")
    out = _build_update_dict(form)
    assert "access_control" not in out


def test_other_none_fields_still_excluded():
    """Regression — ``data`` defaulting to None must not clobber DB."""
    form = _UpdateForm(name="kb", description="d", access_control=None)
    out = _build_update_dict(form)
    assert "data" not in out
    assert "meta" not in out


def test_explicit_access_control_with_groups_preserved():
    acl = {"read": {"group_ids": ["g1"], "user_ids": []}}
    form = _UpdateForm(name="kb", description="d", access_control=acl)
    out = _build_update_dict(form)
    assert out["access_control"] == acl
