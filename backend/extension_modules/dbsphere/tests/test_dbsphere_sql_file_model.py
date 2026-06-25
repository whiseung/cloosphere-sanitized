"""Unit tests for models/dbsphere_sql_file.py.

Tests CRUD + optimistic-concurrency (`expected_updated_at`) + 256KB content cap.
격리된 SQLite DB 사용 — `conftest.py` 가 session-level 로 DB 격리 + function-level
truncate 를 자동 처리한다.
"""

from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestSqlFileCrud:
    def test_insert_and_get(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-1", "u-1", DbSphereSqlFileForm(name="A.sql", content="SELECT 1;")
        )
        assert created is not None
        assert created.dbsphere_id == "db-1"
        assert created.user_id == "u-1"
        assert created.name == "A.sql"
        assert created.content == "SELECT 1;"
        assert created.created_at == created.updated_at  # 신규 생성 시점

        fetched = DbSphereSqlFiles.get_sql_file_by_id(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_list_filters_by_dbsphere_and_user(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
        )

        # 동일 dbsphere + 다른 user.
        DbSphereSqlFiles.insert_new_sql_file(
            "db-list", "u-a", DbSphereSqlFileForm(name="a.sql")
        )
        DbSphereSqlFiles.insert_new_sql_file(
            "db-list", "u-a", DbSphereSqlFileForm(name="a2.sql")
        )
        DbSphereSqlFiles.insert_new_sql_file(
            "db-list", "u-b", DbSphereSqlFileForm(name="b.sql")
        )
        # 다른 dbsphere.
        DbSphereSqlFiles.insert_new_sql_file(
            "db-other", "u-a", DbSphereSqlFileForm(name="other.sql")
        )

        user_a = DbSphereSqlFiles.get_sql_files_by_dbsphere_and_user("db-list", "u-a")
        names_a = sorted([f.name for f in user_a])
        assert names_a == ["a.sql", "a2.sql"]

        user_b = DbSphereSqlFiles.get_sql_files_by_dbsphere_and_user("db-list", "u-b")
        assert [f.name for f in user_b] == ["b.sql"]

    def test_update_changes_name_and_content_bumps_updated_at(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
            DbSphereSqlFileUpdateForm,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-2", "u-1", DbSphereSqlFileForm(name="x.sql", content="SELECT 1;")
        )
        time.sleep(1.1)  # int(time.time()) bump 보장
        upd, err = DbSphereSqlFiles.update_sql_file_by_id(
            created.id,
            "u-1",
            DbSphereSqlFileUpdateForm(name="x-renamed.sql", content="SELECT 2;"),
        )
        assert err is None
        assert upd.name == "x-renamed.sql"
        assert upd.content == "SELECT 2;"
        assert upd.updated_at > created.updated_at

    def test_update_not_found(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFiles,
            DbSphereSqlFileUpdateForm,
        )

        upd, err = DbSphereSqlFiles.update_sql_file_by_id(
            "no-such-id", "u-1", DbSphereSqlFileUpdateForm(name="x")
        )
        assert upd is None
        assert err == "not_found"

    def test_update_forbidden_when_other_user(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
            DbSphereSqlFileUpdateForm,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-3", "u-owner", DbSphereSqlFileForm(name="o.sql")
        )
        upd, err = DbSphereSqlFiles.update_sql_file_by_id(
            created.id, "u-intruder", DbSphereSqlFileUpdateForm(name="hijack")
        )
        assert upd is None
        assert err == "forbidden"

    def test_update_optimistic_concurrency_returns_server_copy_on_conflict(self):
        """M2 — expected_updated_at mismatch → 'conflict' + server copy."""
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
            DbSphereSqlFileUpdateForm,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-4", "u-1", DbSphereSqlFileForm(name="c.sql", content="orig")
        )
        # 다른 브라우저 탭이 먼저 저장한 상황 — expected_updated_at 가 stale.
        stale_ts = created.updated_at - 1
        upd, err = DbSphereSqlFiles.update_sql_file_by_id(
            created.id,
            "u-1",
            DbSphereSqlFileUpdateForm(content="hijack", expected_updated_at=stale_ts),
        )
        assert err == "conflict"
        # 서버 copy (현재 DB 상태) 가 반환되어야 함 — UI 가 충돌 비교에 사용.
        assert upd is not None
        assert upd.id == created.id
        assert upd.content == "orig"  # 변경 안 됐음

    def test_update_no_check_when_expected_omitted(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
            DbSphereSqlFileUpdateForm,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-5", "u-1", DbSphereSqlFileForm(name="d.sql", content="v1")
        )
        upd, err = DbSphereSqlFiles.update_sql_file_by_id(
            created.id, "u-1", DbSphereSqlFileUpdateForm(content="v2")
        )
        assert err is None
        assert upd.content == "v2"

    def test_delete_happy(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-6", "u-1", DbSphereSqlFileForm(name="del.sql")
        )
        deleted, err = DbSphereSqlFiles.delete_sql_file_by_id(created.id, "u-1")
        assert deleted is True
        assert err is None
        assert DbSphereSqlFiles.get_sql_file_by_id(created.id) is None

    def test_delete_forbidden(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
        )

        created = DbSphereSqlFiles.insert_new_sql_file(
            "db-7", "u-owner", DbSphereSqlFileForm(name="forbidden.sql")
        )
        deleted, err = DbSphereSqlFiles.delete_sql_file_by_id(created.id, "u-other")
        assert deleted is False
        assert err == "forbidden"
        # row 는 아직 존재해야 함.
        assert DbSphereSqlFiles.get_sql_file_by_id(created.id) is not None

    def test_delete_not_found(self):
        from open_webui.models.dbsphere_sql_file import DbSphereSqlFiles

        deleted, err = DbSphereSqlFiles.delete_sql_file_by_id("no-such", "u-1")
        assert deleted is False
        assert err == "not_found"

    def test_cascade_delete_by_dbsphere(self):
        from open_webui.models.dbsphere_sql_file import (
            DbSphereSqlFileForm,
            DbSphereSqlFiles,
        )

        # 한 dbsphere 에 여러 user × 여러 파일.
        for u in ("u-a", "u-b"):
            for n in ("c1.sql", "c2.sql"):
                DbSphereSqlFiles.insert_new_sql_file(
                    "db-cascade", u, DbSphereSqlFileForm(name=n)
                )
        # 다른 dbsphere — 영향 없어야 함.
        DbSphereSqlFiles.insert_new_sql_file(
            "db-keep", "u-a", DbSphereSqlFileForm(name="keep.sql")
        )

        count = DbSphereSqlFiles.delete_sql_files_by_dbsphere_id("db-cascade")
        assert count == 4
        assert (
            DbSphereSqlFiles.get_sql_files_by_dbsphere_and_user("db-cascade", "u-a")
            == []
        )
        assert (
            len(DbSphereSqlFiles.get_sql_files_by_dbsphere_and_user("db-keep", "u-a"))
            == 1
        )


# ---------------------------------------------------------------------------
# Content size cap (L3)
# ---------------------------------------------------------------------------


class TestContentSizeCap:
    def test_create_rejects_oversized_content(self):
        from open_webui.models.dbsphere_sql_file import DbSphereSqlFileForm

        with pytest.raises(Exception) as exc_info:
            DbSphereSqlFileForm(name="big.sql", content="x" * (257 * 1024))
        assert "256KB" in str(exc_info.value) or "exceeds" in str(exc_info.value)

    def test_update_rejects_oversized_content(self):
        from open_webui.models.dbsphere_sql_file import DbSphereSqlFileUpdateForm

        with pytest.raises(Exception) as exc_info:
            DbSphereSqlFileUpdateForm(content="x" * (257 * 1024))
        assert "256KB" in str(exc_info.value) or "exceeds" in str(exc_info.value)

    def test_at_size_limit_accepted(self):
        """정확히 한계 byte — 통과해야 함."""
        from open_webui.models.dbsphere_sql_file import DbSphereSqlFileForm

        ok = DbSphereSqlFileForm(name="edge.sql", content="x" * (256 * 1024))
        assert len(ok.content) == 256 * 1024

    def test_unicode_content_size_in_bytes_not_chars(self):
        """utf-8 byte 기준이므로 한글 등 멀티바이트 문자는 글자 수보다 byte 수가 크다."""
        from open_webui.models.dbsphere_sql_file import DbSphereSqlFileForm

        # 한글 1글자 = 3 byte. 100000 글자 * 3 = 300000 > 256KB.
        with pytest.raises(Exception):
            DbSphereSqlFileForm(name="ko.sql", content="가" * 100_000)
