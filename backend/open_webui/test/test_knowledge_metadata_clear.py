"""Unit tests for ``Knowledges.clear_knowledge_file_metadata_slots`` semantics.

The cleared keys must obey the same slot prefixes (``f_str_*``, ``f_int_*``,
``f_date_*``, ``f_col_*``) that ``patch_knowledge_file_metadata`` uses to
distinguish metadata slots from bookkeeping (``last_extracted_at``, etc).

Pure logic tests — the production method runs the loop inside a row-locked
transaction. We simulate the same loop on a plain dict so the test can run
without DB.
"""

SLOT_PREFIXES = ("f_str_", "f_int_", "f_date_", "f_col_")


def _clear_loop(file_metadata: dict, file_ids: list) -> tuple:
    cleared_per_file: dict = {}
    for file_id in file_ids:
        current = dict(file_metadata.get(file_id, {}))
        cleared = [k for k in current if k.startswith(SLOT_PREFIXES)]
        for k in cleared:
            current.pop(k, None)
        file_metadata[file_id] = current
        if cleared:
            cleared_per_file[file_id] = cleared
    return file_metadata, cleared_per_file


def test_clears_only_slot_prefixed_keys():
    fm = {
        "f1": {
            "f_str_dept": "HR",
            "f_int_year": 2024,
            "f_date_signed": "2024-03-15",
            "f_col_tags": ["a", "b"],
            "last_extracted_at": 1700000000,
            "extractor_version": "v3",
        }
    }
    out, cleared = _clear_loop(fm, ["f1"])
    assert "f_str_dept" not in out["f1"]
    assert "f_int_year" not in out["f1"]
    assert "f_date_signed" not in out["f1"]
    assert "f_col_tags" not in out["f1"]
    # 비-slot 키는 보존
    assert out["f1"]["last_extracted_at"] == 1700000000
    assert out["f1"]["extractor_version"] == "v3"
    assert set(cleared["f1"]) == {
        "f_str_dept",
        "f_int_year",
        "f_date_signed",
        "f_col_tags",
    }


def test_no_op_for_files_without_slots():
    fm = {"f1": {"last_extracted_at": 1700000000}}
    out, cleared = _clear_loop(fm, ["f1"])
    assert out["f1"] == {"last_extracted_at": 1700000000}
    assert cleared == {}


def test_skipped_files_left_untouched():
    fm = {
        "f1": {"f_str_dept": "HR"},
        "f2": {"f_str_dept": "Finance"},
    }
    out, cleared = _clear_loop(fm, ["f1"])  # f2 not in selection
    assert "f_str_dept" not in out["f1"]
    assert out["f2"]["f_str_dept"] == "Finance"
    assert list(cleared.keys()) == ["f1"]


def test_unknown_file_id_creates_empty_entry_but_no_clear():
    """알려지지 않은 file_id 가 들어와도 예외 없이 빈 dict 로 처리."""
    fm = {}
    out, cleared = _clear_loop(fm, ["unknown"])
    assert out == {"unknown": {}}
    assert cleared == {}
