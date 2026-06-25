"""Unit tests for Memory Phase 4 governance features.

Tests cover:
- SOURCE_RETENTION_MAP mapping
- Memory soft delete methods
- deleted_at IS NULL filtering
- insert_new_memory retention_class assignment
- RetentionPolicy.seed_defaults idempotency

Note: MemoryAuditLog tests removed — memory_audit_log 폐기됨 (audit_log 단일화).
"""

from contextlib import contextmanager
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Return a (db_mock, fake_get_db) pair usable for patching get_db."""
    db = MagicMock()

    @contextmanager
    def fake_get_db():
        yield db

    return db, fake_get_db


# ---------------------------------------------------------------------------
# 1. SOURCE_RETENTION_MAP
# ---------------------------------------------------------------------------


class TestSourceRetentionMap:
    def test_auto_maps_to_temporary(self):
        from open_webui.models.memory_retention_policy import SOURCE_RETENTION_MAP

        assert SOURCE_RETENTION_MAP["auto"] == "temporary"

    def test_manual_maps_to_standard(self):
        from open_webui.models.memory_retention_policy import SOURCE_RETENTION_MAP

        assert SOURCE_RETENTION_MAP["manual"] == "standard"

    def test_profile_maps_to_permanent(self):
        from open_webui.models.memory_retention_policy import SOURCE_RETENTION_MAP

        assert SOURCE_RETENTION_MAP["profile"] == "permanent"

    def test_unknown_source_defaults_to_standard(self):
        from open_webui.models.memory_retention_policy import SOURCE_RETENTION_MAP

        result = SOURCE_RETENTION_MAP.get("unknown_source", "standard")
        assert result == "standard"

    def test_map_has_exactly_three_entries(self):
        from open_webui.models.memory_retention_policy import SOURCE_RETENTION_MAP

        assert len(SOURCE_RETENTION_MAP) == 3


# ---------------------------------------------------------------------------
# 2. Memory soft delete methods
# ---------------------------------------------------------------------------


class TestSoftDeleteMemoryById:
    def test_soft_delete_live_memory_returns_true(self, mock_db):
        db, fake_get_db = mock_db
        # simulate 1 row affected
        db.query.return_value.filter_by.return_value.filter.return_value.update.return_value = 1

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.soft_delete_memory_by_id_and_user_id(
                id="mem-1", user_id="user-1"
            )

        assert result is True
        db.commit.assert_called_once()

    def test_soft_delete_already_deleted_returns_false(self, mock_db):
        db, fake_get_db = mock_db
        # simulate 0 rows affected (already soft-deleted)
        db.query.return_value.filter_by.return_value.filter.return_value.update.return_value = 0

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.soft_delete_memory_by_id_and_user_id(
                id="mem-1", user_id="user-1"
            )

        assert result is False

    def test_soft_delete_db_exception_returns_false(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.filter.return_value.update.side_effect = Exception(
            "DB error"
        )

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.soft_delete_memory_by_id_and_user_id(
                id="mem-1", user_id="user-1"
            )

        assert result is False


class TestSoftDeleteMemoriesByUserId:
    def _make_row(self, id_val: str):
        row = MagicMock()
        row.id = id_val
        return row

    def test_returns_affected_ids(self, mock_db):
        db, fake_get_db = mock_db
        rows = [self._make_row("id-1"), self._make_row("id-2")]
        db.query.return_value.filter_by.return_value.filter.return_value.all.return_value = rows

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.soft_delete_memories_by_user_id("user-1")

        assert result == ["id-1", "id-2"]
        db.commit.assert_called_once()

    def test_empty_user_returns_empty_list(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.filter.return_value.all.return_value = []

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.soft_delete_memories_by_user_id("user-no-memories")

        assert result == []
        # commit should NOT be called when there are no ids to update
        db.commit.assert_not_called()

    def test_db_exception_returns_empty_list(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.filter.return_value.all.side_effect = Exception(
            "DB error"
        )

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.soft_delete_memories_by_user_id("user-1")

        assert result == []


# ---------------------------------------------------------------------------
# 3. deleted_at IS NULL filtering
# ---------------------------------------------------------------------------


class TestDeletedAtFiltering:
    """Verify that methods chain .filter(Memory.deleted_at.is_(None)).

    We check that the query chain includes the deleted_at filter by inspecting
    the mock call chain — we cannot assert on SQLAlchemy internals directly,
    but we can verify the query is chained and executed from a filtered result.
    """

    def _setup_query_returning(self, db, return_value, mode="all"):
        """Set up db.query chain to return a specific value."""
        chain = db.query.return_value.filter_by.return_value.filter.return_value
        if mode == "all":
            chain.all.return_value = return_value
        elif mode == "first":
            chain.first.return_value = return_value
        elif mode == "count":
            chain.count.return_value = return_value
        return chain

    def test_get_memories_by_user_id_excludes_soft_deleted(self, mock_db):
        db, fake_get_db = mock_db
        self._setup_query_returning(db, [], mode="all")

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.get_memories_by_user_id("user-1")

        assert result == []
        # Verify filter() was called (deleted_at chain present)
        db.query.return_value.filter_by.return_value.filter.assert_called_once()

    def test_get_memory_count_excludes_soft_deleted(self, mock_db):
        db, fake_get_db = mock_db
        self._setup_query_returning(db, 3, mode="count")

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            count = Memories.get_memory_count_by_user_id("user-1")

        assert count == 3
        db.query.return_value.filter_by.return_value.filter.assert_called_once()

    def test_get_memory_by_id_returns_none_for_soft_deleted(self, mock_db):
        db, fake_get_db = mock_db
        # first() returns None → memory is either soft-deleted or missing
        self._setup_query_returning(db, None, mode="first")

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.get_memory_by_id("mem-1")

        assert result is None

    def test_get_profile_by_user_id_returns_none_for_soft_deleted(self, mock_db):
        db, fake_get_db = mock_db
        self._setup_query_returning(db, None, mode="first")

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            result = Memories.get_profile_by_user_id("user-1")

        assert result is None
        db.query.return_value.filter_by.return_value.filter.assert_called_once()

    def test_update_memory_cannot_update_soft_deleted(self, mock_db):
        db, fake_get_db = mock_db
        # update returns 0 rows (soft-deleted rows excluded by filter)
        db.query.return_value.filter_by.return_value.filter.return_value.update.return_value = 0

        # get_memory_by_id is called inside update_memory_by_id_and_user_id
        # patch it to return None (since memory is deleted)
        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            with patch.object(Memories, "get_memory_by_id", return_value=None):
                result = Memories.update_memory_by_id_and_user_id(
                    id="mem-1", user_id="user-1", content="new content"
                )

        assert result is None


# ---------------------------------------------------------------------------
# 4. insert_new_memory — retention_class assignment
# ---------------------------------------------------------------------------


class TestInsertNewMemoryRetentionClass:
    def _make_db_mock_for_insert(self, db):
        """Configure db mock so that db.refresh populates the ORM object attrs."""

        def refresh_side_effect(obj):
            # Simulate DB refresh — object stays as-is since we set attrs via Memory(**...)
            pass

        db.refresh.side_effect = refresh_side_effect

    def _call_insert(self, fake_get_db, **kwargs) -> Optional[object]:
        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import Memories

            return Memories.insert_new_memory(**kwargs)

    def test_auto_source_sets_temporary(self, mock_db):
        db, fake_get_db = mock_db
        self._make_db_mock_for_insert(db)

        captured = {}

        original_add = db.add

        def capture_add(obj):
            captured["obj"] = obj

        db.add.side_effect = capture_add

        # db.refresh must set attrs we can validate via model_validate
        def refresh(obj):
            pass

        db.refresh.side_effect = refresh

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()

            # Intercept model_validate to capture what was passed
            original_validate = MemoryModel.model_validate

            def patched_validate(obj, **kw):
                # obj is the Memory ORM instance — read its retention_class
                captured["retention_class"] = obj.retention_class
                return original_validate(obj, **kw)

            with patch.object(
                MemoryModel, "model_validate", side_effect=patched_validate
            ):
                table.insert_new_memory(user_id="u1", content="test", source="auto")

        assert captured["retention_class"] == "temporary"

    def test_manual_source_sets_standard(self, mock_db):
        db, fake_get_db = mock_db
        captured = {}

        def capture_add(obj):
            captured["retention_class"] = obj.retention_class

        db.add.side_effect = capture_add

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(MemoryModel, "model_validate", return_value=MagicMock()):
                table.insert_new_memory(user_id="u1", content="test", source="manual")

        assert captured["retention_class"] == "standard"

    def test_profile_source_sets_permanent(self, mock_db):
        db, fake_get_db = mock_db
        captured = {}

        def capture_add(obj):
            captured["retention_class"] = obj.retention_class

        db.add.side_effect = capture_add

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(MemoryModel, "model_validate", return_value=MagicMock()):
                table.insert_new_memory(user_id="u1", content="test", source="profile")

        assert captured["retention_class"] == "permanent"

    def test_explicit_retention_class_overrides_source(self, mock_db):
        db, fake_get_db = mock_db
        captured = {}

        def capture_add(obj):
            captured["retention_class"] = obj.retention_class

        db.add.side_effect = capture_add

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(MemoryModel, "model_validate", return_value=MagicMock()):
                # source="auto" would give "temporary", but explicit param should win
                table.insert_new_memory(
                    user_id="u1",
                    content="test",
                    source="auto",
                    retention_class="permanent",
                )

        assert captured["retention_class"] == "permanent"

    def test_unknown_source_defaults_to_standard(self, mock_db):
        db, fake_get_db = mock_db
        captured = {}

        def capture_add(obj):
            captured["retention_class"] = obj.retention_class

        db.add.side_effect = capture_add

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(MemoryModel, "model_validate", return_value=MagicMock()):
                table.insert_new_memory(
                    user_id="u1", content="test", source="unknown_source"
                )

        assert captured["retention_class"] == "standard"


# ---------------------------------------------------------------------------
# 5. MemoryAuditLog — REMOVED (memory_audit_log 폐기, audit_log 단일화)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. RetentionPolicy.seed_defaults
# ---------------------------------------------------------------------------


class TestRetentionPolicySeedDefaults:
    def test_seeds_three_default_policies_when_empty(self, mock_db):
        db, fake_get_db = mock_db
        # Simulate empty table
        db.query.return_value.filter_by.return_value.count.return_value = 0

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            table.seed_defaults()

        assert db.add.call_count == 3
        db.commit.assert_called_once()

    def test_skips_seeding_when_policies_exist(self, mock_db):
        db, fake_get_db = mock_db
        # Simulate 3 existing policies
        db.query.return_value.filter_by.return_value.count.return_value = 3

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            table.seed_defaults()

        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_seeded_policies_cover_all_retention_classes(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 0

        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)

        db.add.side_effect = capture_add

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            table.seed_defaults()

        classes = {obj.retention_class for obj in added_objects}
        assert classes == {"temporary", "standard", "permanent"}

    def test_seeded_permanent_has_null_ttl(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 0

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            table.seed_defaults()

        permanent = next(o for o in added_objects if o.retention_class == "permanent")
        assert permanent.ttl_days is None

    def test_seeded_temporary_has_30_day_ttl(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 0

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            table.seed_defaults()

        temporary = next(o for o in added_objects if o.retention_class == "temporary")
        assert temporary.ttl_days == 30

    def test_seeded_standard_has_180_day_ttl(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 0

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            table.seed_defaults()

        standard = next(o for o in added_objects if o.retention_class == "standard")
        assert standard.ttl_days == 180

    def test_db_error_does_not_raise(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.side_effect = Exception(
            "DB error"
        )

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            # seed_defaults catches exceptions internally — must not raise
            table.seed_defaults()


# ---------------------------------------------------------------------------
# Phase 5 — Section 7: RetentionPolicy.update_policy
# ---------------------------------------------------------------------------


class TestRetentionPolicyUpdatePolicy:
    def _make_policy(self, retention_class: str, ttl_days=30):
        policy = MagicMock()
        policy.id = "policy-1"
        policy.retention_class = retention_class
        policy.ttl_days = ttl_days
        policy.on_expire = "soft_delete"
        policy.org_id = None
        policy.created_at = 1000000
        policy.updated_at = 1000000
        return policy

    def test_update_temporary_ttl_returns_updated_policy(self, mock_db):
        db, fake_get_db = mock_db
        policy = self._make_policy("temporary", ttl_days=30)
        db.query.return_value.filter_by.return_value.first.return_value = policy

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyModel,
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            with patch.object(
                MemoryRetentionPolicyModel,
                "model_validate",
                side_effect=lambda obj, **kw: MagicMock(
                    id=obj.id,
                    retention_class=obj.retention_class,
                    ttl_days=obj.ttl_days,
                ),
            ):
                result = table.update_policy(id="policy-1", ttl_days=60)

        assert result is not None
        # ttl_days was mutated on the mock object
        assert policy.ttl_days == 60
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(policy)

    def test_update_permanent_returns_unchanged_policy(self, mock_db):
        db, fake_get_db = mock_db
        policy = self._make_policy("permanent", ttl_days=None)
        db.query.return_value.filter_by.return_value.first.return_value = policy

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyModel,
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            with patch.object(
                MemoryRetentionPolicyModel,
                "model_validate",
                return_value=MagicMock(retention_class="permanent"),
            ):
                result = table.update_policy(id="policy-1", ttl_days=90)

        assert result is not None
        # permanent policy — ttl_days must NOT be mutated, commit not called
        assert policy.ttl_days is None
        db.commit.assert_not_called()

    def test_update_nonexistent_policy_returns_none(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("open_webui.models.memory_retention_policy.get_db", fake_get_db):
            from open_webui.models.memory_retention_policy import (
                MemoryRetentionPolicyTable,
            )

            table = MemoryRetentionPolicyTable()
            result = table.update_policy(id="nonexistent", ttl_days=60)

        assert result is None
        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5 — Section 8: MemoryAuditLog.get_audit_logs — REMOVED
# (memory_audit_log 폐기, audit_log 단일화)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 5 — Section 9: Org memory methods
# ---------------------------------------------------------------------------

import uuid as _uuid_module


class TestOrgMemoryMethods:
    def _make_memory_row(
        self,
        scope: str = "org",
        org_id: str = "org-1",
        retention_class: str = "permanent",
    ):
        row = MagicMock()
        row.id = str(_uuid_module.uuid4())
        row.user_id = "admin-1"
        row.content = "Org policy: always use TLS"
        row.source = "manual"
        row.scope = scope
        row.org_id = org_id
        row.retention_class = retention_class
        row.deleted_at = None
        row.created_at = 1000000
        row.updated_at = 1000000
        return row

    def test_get_org_memories_filters_by_scope_org_and_org_id(self, mock_db):
        db, fake_get_db = mock_db
        rows = [self._make_memory_row(), self._make_memory_row()]
        # filter_by(scope='org', org_id=...) + filter(deleted_at IS NULL) + all
        db.query.return_value.filter_by.return_value.filter.return_value.all.return_value = rows

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(
                MemoryModel,
                "model_validate",
                side_effect=lambda obj, **kw: MagicMock(
                    id=obj.id, scope=obj.scope, org_id=obj.org_id
                ),
            ):
                result = table.get_org_memories("org-1")

        assert len(result) == 2
        # Verify filter_by was called (scope+org_id chain)
        db.query.return_value.filter_by.assert_called_once_with(
            scope="org", org_id="org-1"
        )
        # Verify deleted_at filter was also applied
        db.query.return_value.filter_by.return_value.filter.assert_called_once()

    def test_get_org_memories_excludes_deleted(self, mock_db):
        db, fake_get_db = mock_db
        # Return empty — all soft-deleted
        db.query.return_value.filter_by.return_value.filter.return_value.all.return_value = []

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable

            table = MemoriesTable()
            result = table.get_org_memories("org-1")

        assert result == []

    def test_insert_org_memory_sets_scope_and_retention(self, mock_db):
        db, fake_get_db = mock_db
        captured = {}

        def capture_add(obj):
            captured["scope"] = obj.scope
            captured["org_id"] = obj.org_id
            captured["retention_class"] = obj.retention_class

        db.add.side_effect = capture_add

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(MemoryModel, "model_validate", return_value=MagicMock()):
                table.insert_org_memory(
                    org_id="org-1",
                    content="All data must stay in EU",
                    admin_user_id="admin-1",
                )

        assert captured["scope"] == "org"
        assert captured["org_id"] == "org-1"
        assert captured["retention_class"] == "permanent"

    def test_get_memories_by_user_id_for_admin_returns_all_active(self, mock_db):
        db, fake_get_db = mock_db
        rows = [
            self._make_memory_row(scope="user"),
            self._make_memory_row(scope="user"),
        ]
        # filter_by + filter + order_by + all
        (
            db.query.return_value.filter_by.return_value.filter.return_value.order_by.return_value.all.return_value
        ) = rows

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable, MemoryModel

            table = MemoriesTable()
            with patch.object(
                MemoryModel,
                "model_validate",
                side_effect=lambda obj, **kw: MagicMock(id=obj.id),
            ):
                result = table.get_memories_by_user_id_for_admin("user-1")

        assert len(result) == 2
        # order_by chain was reached
        db.query.return_value.filter_by.return_value.filter.return_value.order_by.assert_called_once()

    def test_get_memories_by_user_id_for_admin_db_error_returns_empty(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.filter.return_value.order_by.return_value.all.side_effect = Exception(
            "DB error"
        )

        with patch("open_webui.models.memories.get_db", fake_get_db):
            from open_webui.models.memories import MemoriesTable

            table = MemoriesTable()
            result = table.get_memories_by_user_id_for_admin("user-1")

        assert result == []


# ---------------------------------------------------------------------------
# Phase 5 — Section 10: MemoryEntity methods
# ---------------------------------------------------------------------------


class TestMemoryEntityMethods:
    def _make_entity_row(
        self,
        name: str = "python",
        entity_type: str = "tech",
        user_id: str = "u1",
        memory_id: str = "mem-1",
    ):
        row = MagicMock()
        row.id = str(_uuid_module.uuid4())
        row.name = name
        row.entity_type = entity_type
        row.memory_id = memory_id
        row.user_id = user_id
        row.org_id = None
        row.created_at = 1000000
        return row

    def test_upsert_entity_creates_new_entity(self, mock_db):
        db, fake_get_db = mock_db
        # No existing entity
        db.query.return_value.filter_by.return_value.first.return_value = None
        captured = {}

        def capture_add(obj):
            captured["name"] = obj.name
            captured["entity_type"] = obj.entity_type
            captured["user_id"] = obj.user_id

        db.add.side_effect = capture_add

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import (
                MemoryEntityModel,
                MemoryEntityTable,
            )

            table = MemoryEntityTable()
            with patch.object(
                MemoryEntityModel, "model_validate", return_value=MagicMock()
            ):
                table.upsert_entity(
                    name="FastAPI",
                    entity_type="tech",
                    memory_id="mem-1",
                    user_id="u1",
                )

        # name is lowercased before store
        assert captured["name"] == "fastapi"
        assert captured["entity_type"] == "tech"
        assert captured["user_id"] == "u1"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    def test_upsert_entity_updates_existing_entity(self, mock_db):
        db, fake_get_db = mock_db
        existing = self._make_entity_row(name="fastapi", memory_id="old-mem")
        db.query.return_value.filter_by.return_value.first.return_value = existing

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import (
                MemoryEntityModel,
                MemoryEntityTable,
            )

            table = MemoryEntityTable()
            with patch.object(
                MemoryEntityModel, "model_validate", return_value=MagicMock()
            ):
                table.upsert_entity(
                    name="FastAPI",
                    entity_type="tech",
                    memory_id="new-mem-99",
                    user_id="u1",
                )

        # memory_id should be updated to new value
        assert existing.memory_id == "new-mem-99"
        db.add.assert_not_called()
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(existing)

    def test_get_entities_by_user_id_returns_list(self, mock_db):
        db, fake_get_db = mock_db
        rows = [
            self._make_entity_row("python", "tech"),
            self._make_entity_row("cloosphere", "project"),
        ]
        db.query.return_value.filter_by.return_value.all.return_value = rows

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import (
                MemoryEntityModel,
                MemoryEntityTable,
            )

            table = MemoryEntityTable()
            with patch.object(
                MemoryEntityModel,
                "model_validate",
                side_effect=lambda obj, **kw: MagicMock(
                    name=obj.name, entity_type=obj.entity_type, user_id=obj.user_id
                ),
            ):
                result = table.get_entities_by_user_id("u1")

        assert len(result) == 2
        db.query.return_value.filter_by.assert_called_once_with(user_id="u1")

    def test_find_matching_entities_matches_names_in_query(self, mock_db):
        db, fake_get_db = mock_db

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import (
                MemoryEntityModel,
                MemoryEntityTable,
            )

            entity1 = MagicMock(spec=MemoryEntityModel)
            entity1.name = "fastapi"
            entity2 = MagicMock(spec=MemoryEntityModel)
            entity2.name = "django"
            entity3 = MagicMock(spec=MemoryEntityModel)
            entity3.name = "kubernetes"

            table = MemoryEntityTable()
            with patch.object(
                table,
                "get_entities_by_user_id",
                return_value=[entity1, entity2, entity3],
            ):
                matched = table.find_matching_entities(
                    user_id="u1",
                    query_text="I prefer FastAPI over Django for REST APIs",
                )

        matched_names = {e.name for e in matched}
        assert "fastapi" in matched_names
        assert "django" in matched_names
        assert "kubernetes" not in matched_names

    def test_find_matching_entities_no_match_returns_empty(self, mock_db):
        db, fake_get_db = mock_db

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import (
                MemoryEntityModel,
                MemoryEntityTable,
            )

            entity = MagicMock(spec=MemoryEntityModel)
            entity.name = "angular"

            table = MemoryEntityTable()
            with patch.object(table, "get_entities_by_user_id", return_value=[entity]):
                matched = table.find_matching_entities(
                    user_id="u1",
                    query_text="I love using React and Vue",
                )

        assert matched == []


# ---------------------------------------------------------------------------
# Phase 5 — Section 11: EntityType.seed_defaults
# ---------------------------------------------------------------------------


class TestEntityTypeSeedDefaults:
    def test_seeds_five_types_when_empty(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 0

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import MemoryEntityTypeTable

            table = MemoryEntityTypeTable()
            table.seed_defaults()

        assert db.add.call_count == 5
        db.commit.assert_called_once()

    def test_skips_seeding_when_types_exist(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 5

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import MemoryEntityTypeTable

            table = MemoryEntityTypeTable()
            table.seed_defaults()

        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_seeded_types_include_default_names(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.return_value = 0

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import (
                DEFAULT_ENTITY_TYPES,
                MemoryEntityTypeTable,
            )

            table = MemoryEntityTypeTable()
            table.seed_defaults()

        seeded_names = {obj.name for obj in added_objects}
        expected_names = {et["name"] for et in DEFAULT_ENTITY_TYPES}
        assert seeded_names == expected_names

    def test_db_error_does_not_raise(self, mock_db):
        db, fake_get_db = mock_db
        db.query.return_value.filter_by.return_value.count.side_effect = Exception(
            "DB error"
        )

        with patch("open_webui.models.memory_entity.get_db", fake_get_db):
            from open_webui.models.memory_entity import MemoryEntityTypeTable

            table = MemoryEntityTypeTable()
            # Must not raise — exception is caught internally
            table.seed_defaults()


# ---------------------------------------------------------------------------
# Phase 5 — Section 12: _build_extraction_prompt
# ---------------------------------------------------------------------------


class TestBuildExtractionPrompt:
    """_build_extraction_prompt uses a lazy import inside the function body:
        from open_webui.models.memory_entity import EntityTypes
    So we patch the singleton on the source module (open_webui.models.memory_entity.EntityTypes).
    """

    def test_includes_db_entity_types_in_prompt(self):
        fake_type1 = MagicMock()
        fake_type1.name = "tech"
        fake_type2 = MagicMock()
        fake_type2.name = "project"
        fake_type3 = MagicMock()
        fake_type3.name = "person"

        mock_et = MagicMock()
        mock_et.get_all_types.return_value = [fake_type1, fake_type2, fake_type3]

        with patch("open_webui.models.memory_entity.EntityTypes", mock_et):
            from extension_modules.agent.memory_extractor import (
                _build_extraction_prompt,
            )

            prompt = _build_extraction_prompt()

        assert "tech" in prompt
        assert "project" in prompt
        assert "person" in prompt

    def test_falls_back_to_defaults_on_db_error(self):
        mock_et = MagicMock()
        mock_et.get_all_types.side_effect = Exception("DB down")

        with patch("open_webui.models.memory_entity.EntityTypes", mock_et):
            from extension_modules.agent.memory_extractor import (
                _build_extraction_prompt,
            )

            prompt = _build_extraction_prompt()

        # Default fallback list
        assert "tech" in prompt
        assert "concept" in prompt

    def test_falls_back_when_types_list_is_empty(self):
        mock_et = MagicMock()
        mock_et.get_all_types.return_value = []

        with patch("open_webui.models.memory_entity.EntityTypes", mock_et):
            from extension_modules.agent.memory_extractor import (
                _build_extraction_prompt,
            )

            prompt = _build_extraction_prompt()

        # Should fall back to default string, not empty
        assert "tech" in prompt
