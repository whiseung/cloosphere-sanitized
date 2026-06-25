"""Unit tests for fact→dimension JOIN inference (v1 — structural 5-gate, same-name).

설계: dev/active/dbsphere-inference-redesign. ``_infer_column_semantics(table_details)``
는 추출된 스키마의 ``ColumnDetail.is_primary_key`` (시스템 카탈로그 introspection,
LLM 무오염) 만으로 fact→dim 조인 후보를 생성하고 5개 구조 게이트(G6/G1-PK/G2/G5/G4,
파이프라인 순)로 noise(surrogate-id fan-out·PLANT_CODE fan-out·composite-half·
double-target·non-key parent)를 차단한다.
DB·LLM 불요 — 순수 함수 + FakeRunner + table_details fixture.

v1 은 same-name only(결정론, LLM 없음). cross-name 의미매칭은 v2(G1-unique 동반).

게이트별 TDD:
- T1: InferredJoin dataclass + data-driven capability gate (PK 신호 0 → []).
"""

from __future__ import annotations

import logging

from extension_modules.dbsphere.memory.models import (
    ColumnDetail,
    InferredJoin,
    TableDetails,
)
from extension_modules.dbsphere.memory.schema_extractor import SchemaExtractor


# ---------------------------------------------------------------------------
# Fakes / builders
# ---------------------------------------------------------------------------
class FakeRunner:
    """추론(table_details 기반)은 runner 를 호출하지 않지만,
    ``_collect_verified_fks`` 의 verified-FK 수집은
    ``get_foreign_key_relationships`` 를 쓰므로 함께 흉내낸다(기본 빈 FK).
    dialect 라벨은 진단 로그용 best-effort(config 부재 시 클래스명 폴백)."""

    # pool 기반으로 표시해 hook 경로의 per-task runner 생성(create_sql_runner)
    # 분기를 건너뛴다 — 이 fake 엔 config 가 없다.
    is_pool_based = True

    def __init__(self, fks=None):
        self._fks = fks or []

    async def get_foreign_key_relationships(self, table_name=None):
        if table_name is None:
            return list(self._fks)
        return [fk for fk in self._fks if fk.get("SOURCE_TABLE") == table_name]


class _NoopAsyncCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeMemory:
    """extract_and_save_to_memory 의 hook 경로용 최소 memory fake.

    session()/save_ddl_memory/save_documentation/dbsphere_id 만 흉내(QA 경로는
    generate_sample_qa=False 로 비활성)."""

    def __init__(self, dbsphere_id="ds-test"):
        self.dbsphere_id = dbsphere_id
        self.docs: list = []
        self.ddl_saved = 0

    def session(self):
        return _NoopAsyncCtx()

    async def save_ddl_memory(self, **kwargs):
        self.ddl_saved += 1
        return True

    async def save_documentation(self, **kwargs):
        self.docs.append(kwargs)
        return object()

    async def get_table_schemas(self, table_names=None):
        # Option C full-S reload — empty store, so full S = the in-run batch only.
        return []

    async def delete_relationship_graph_doc(self):
        return True


def _col(name: str, pk: bool = False, fk: bool = False) -> ColumnDetail:
    return ColumnDetail(
        name=name, data_type="text", is_primary_key=pk, is_foreign_key=fk
    )


def _td(name: str, cols) -> TableDetails:
    return TableDetails(table_name=name, ddl="", description="", columns=list(cols))


# ---------------------------------------------------------------------------
# T1 — InferredJoin dataclass
# ---------------------------------------------------------------------------
def test_inferred_join_dataclass_shape():
    """검증 FK 의 constraint entry(source/target/pairs)와 정합하는 후보 모델.

    column_pairs 는 [(source_col, target_col), ...] — 복합 후보(G5)도 단일
    InferredJoin 으로 표현해 verified 렌더(1:1-pair/cartesian fallback)를 재사용.
    """
    j = InferredJoin(
        source_table="FACT",
        target_table="DIM",
        column_pairs=[("DIM_CODE", "DIM_CODE")],
    )
    assert j.source_table == "FACT"
    assert j.target_table == "DIM"
    assert j.column_pairs == [("DIM_CODE", "DIM_CODE")]
    assert j.confidence == "candidate"  # 기본 라벨 — verified 와 구별
    assert j.reason == ""


# ---------------------------------------------------------------------------
# T1 — capability gate (data-driven: any(is_primary_key) False → [])
# ---------------------------------------------------------------------------
async def test_capability_gate_no_pk_signal_returns_empty():
    """어느 컬럼도 PK 가 아니면(databricks/bigquery/empty-fabric) 추론 0 + skip.

    PK 가 영원히 False 인 dialect 에서 모든 후보가 G1 에서 reject 되므로,
    전역 PK 부재 시 candidate 생성·LLM 호출 전에 early-exit(낭비 방지·noise 0).
    """
    details = [
        _td("FACT", [_col("DIM_CODE"), _col("AMT")]),
        _td("DIM", [_col("DIM_CODE"), _col("NAME")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    assert await ext._infer_column_semantics(details) == []


async def test_capability_gate_empty_input_returns_empty():
    """table_details 자체가 비어도 안전하게 [] (any() over empty = False)."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    assert await ext._infer_column_semantics([]) == []


async def test_capability_gate_logs_no_pk_signal_diagnostic(caplog):
    """PK 신호 부재 시 dialect + 'no PK signal' 진단 로그(운영 가시성).

    databricks/bigquery(introspection 미지원) 와 Fabric(NOT ENFORCED) 가
    추론 0 인 이유를 단일 INFO 로그로 노출 — '왜 조인 가이드가 비었나' 추적용.
    """
    details = [_td("FACT", [_col("X")]), _td("DIM", [_col("X")])]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    with caplog.at_level(logging.INFO):
        await ext._infer_column_semantics(details)
    assert any("no pk signal" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# T2 — same-name candidate 생성 (deterministic, LLM 없음)
# ---------------------------------------------------------------------------
def test_same_name_generates_directed_candidates():
    """동일 컬럼명이 2개 테이블에 → 양방향 directed candidate (G1 이 orient).

    생성 단계는 어느 쪽이 dimension(PK 보유)인지 모르므로 양방향을 만들고,
    G1(target-is-key)이 잘못된 방향을 제거한다.
    """
    details = [
        _td("FACT", [_col("CODE"), _col("AMT")]),
        _td("DIM", [_col("CODE"), _col("NAME")]),
    ]
    cands = SchemaExtractor._generate_same_name_candidates(details)
    pairs = {(c.source_table, c.target_table) for c in cands}
    assert pairs == {("FACT", "DIM"), ("DIM", "FACT")}
    for c in cands:
        assert c.column_pairs == [("CODE", "CODE")]
        assert c.confidence == "candidate"


def test_no_shared_column_name_no_candidate():
    """공유 컬럼명이 없으면 후보 0 (서로 다른 컬럼은 join 후보 아님)."""
    details = [_td("A", [_col("X")]), _td("B", [_col("Y")])]
    assert SchemaExtractor._generate_same_name_candidates(details) == []


def test_case_insensitive_match_preserves_original_casing():
    """매칭은 case-insensitive(Oracle UPPER vs pg lower), 출력은 원본 casing 복원.

    복원 코드의 lowercase-lookup + casing 복원 validation 재사용 — A.code 와
    B.CODE 는 동일 컬럼으로 매칭하되 ON 절엔 각 원본 표기를 쓴다.
    """
    details = [_td("A", [_col("code")]), _td("B", [_col("CODE")])]
    cands = SchemaExtractor._generate_same_name_candidates(details)
    a_to_b = [c for c in cands if c.source_table == "A"]
    assert len(a_to_b) == 1
    assert a_to_b[0].column_pairs == [("code", "CODE")]


def test_single_table_occurrence_no_self_candidate():
    """컬럼명이 한 테이블에만 있으면 후보 없음(self-join/단일출현 차단)."""
    details = [
        _td("A", [_col("UNIQUE_A"), _col("SHARED")]),
        _td("B", [_col("UNIQUE_B"), _col("SHARED")]),
    ]
    cands = SchemaExtractor._generate_same_name_candidates(details)
    cols = {tuple(c.column_pairs) for c in cands}
    assert cols == {(("SHARED", "SHARED"),)}  # UNIQUE_* 는 후보 없음


def test_ubiquitous_name_generates_all_directed_pairs_pre_gate():
    """편재 컬럼은 게이트 전이라 전부 생성된다(G2 가 후속에서 fan-out 차단).

    생성기는 noise 판정을 하지 않는다 — 책임 분리(생성 vs 게이트).
    """
    details = [
        _td("A", [_col("P")]),
        _td("B", [_col("P")]),
        _td("C", [_col("P")]),
    ]
    cands = SchemaExtractor._generate_same_name_candidates(details)
    pairs = {(c.source_table, c.target_table) for c in cands}
    assert pairs == {
        ("A", "B"),
        ("A", "C"),
        ("B", "A"),
        ("B", "C"),
        ("C", "A"),
        ("C", "B"),
    }


# ---------------------------------------------------------------------------
# T3 — G1 target-is-key (structural)
# ---------------------------------------------------------------------------
def test_build_pk_set_lowercase_keyed():
    """pk_set 은 lowercase 테이블→{lowercase PK 컬럼} (case-insensitive 매칭)."""
    details = [
        _td("Fact", [_col("Id", pk=True), _col("Amt")]),
        _td("Dim", [_col("DCODE", pk=True), _col("X")]),
    ]
    assert SchemaExtractor._build_pk_set(details) == {
        "fact": {"id"},
        "dim": {"dcode"},
    }


def test_build_pk_set_composite_includes_all_members():
    """복합 PK 는 전 멤버를 set 으로 (G5 가 완전성 판정에 사용)."""
    details = [_td("CT", [_col("A", pk=True), _col("B", pk=True), _col("C")])]
    assert SchemaExtractor._build_pk_set(details) == {"ct": {"a", "b"}}


def test_build_pk_set_omits_tables_without_pk():
    """PK 없는 테이블은 맵에 없음(databricks/bigquery/empty-fabric)."""
    details = [_td("NoPK", [_col("X"), _col("Y")])]
    assert SchemaExtractor._build_pk_set(details) == {}


def test_g1_keeps_candidate_when_target_col_is_pk():
    """target 컬럼이 target PK → 통과 (FACT.SPLR_CODE → SPLR_MASTER.SPLR_CODE)."""
    cands = [InferredJoin("FACT", "SPLR_MASTER", [("SPLR_CODE", "SPLR_CODE")])]
    pk_set = {"splr_master": {"splr_code"}}
    assert SchemaExtractor._gate_target_is_key(cands, pk_set) == cands


def test_g1_rejects_non_key_target():
    """target 컬럼이 순수 속성(비-PK) → reject (PLANT_CODE/FMPF/PAR_OBJ_ID 동형)."""
    cands = [InferredJoin("A", "B", [("PLANT_CODE", "PLANT_CODE")])]
    pk_set = {"b": {"b_id"}}  # B.PLANT_CODE 는 PK 아님
    assert SchemaExtractor._gate_target_is_key(cands, pk_set) == []


def test_g1_rejects_when_target_has_no_pk():
    """target 테이블에 PK 자체가 없으면 reject (false-negative-safe)."""
    cands = [InferredJoin("A", "B", [("X", "X")])]
    assert SchemaExtractor._gate_target_is_key(cands, {}) == []


def test_g1_orients_bidirectional_candidates():
    """비-PK ↔ PK 양방향 후보 중 PK-target 방향만 생존 (G1 이 orient)."""
    details = [_td("FACT", [_col("CODE")]), _td("DIM", [_col("CODE", pk=True)])]
    cands = SchemaExtractor._generate_same_name_candidates(details)
    pk_set = SchemaExtractor._build_pk_set(details)
    kept = SchemaExtractor._gate_target_is_key(cands, pk_set)
    assert len(kept) == 1
    assert kept[0].source_table == "FACT"
    assert kept[0].target_table == "DIM"


def test_g1_composite_member_passes_completeness_deferred_to_g5():
    """복합 PK 의 부분 멤버도 '키 멤버'라 G1 통과 — 완전성은 G5 가 판정.

    이 보완성(G1 단독으론 composite-half 통과)이 G5 필수성의 근거.
    """
    cands = [InferredJoin("A", "B", [("C1", "C1")])]
    pk_set = {"b": {"c1", "c2"}}
    assert SchemaExtractor._gate_target_is_key(cands, pk_set) == cands


# ---------------------------------------------------------------------------
# T4 — G2 ubiquity suppress (structural)
# ---------------------------------------------------------------------------
def test_build_name_freq_counts_distinct_tables():
    """name_freq = lowercase 컬럼명 → 등장 테이블 수 (테이블당 1회)."""
    details = [
        _td("A", [_col("PLANT_CODE"), _col("X")]),
        _td("B", [_col("PLANT_CODE"), _col("Y")]),
        _td("C", [_col("plant_code")]),  # case-insensitive
    ]
    freq = SchemaExtractor._build_name_freq(details)
    assert freq["plant_code"] == 3
    assert freq["x"] == 1


def test_g2_suppresses_ubiquitous_non_pk_column():
    """순수 공유속성(어디서도 비-PK) + 편재(freq>k) → suppress (PLANT_CODE fan-out)."""
    cands = [
        InferredJoin("A", "B", [("PLANT_CODE", "PLANT_CODE")]),
        InferredJoin("B", "C", [("PLANT_CODE", "PLANT_CODE")]),
    ]
    name_freq = {"plant_code": 12}
    pk_set = {"a": {"a_id"}, "b": {"b_id"}, "c": {"c_id"}}  # PLANT_CODE 어디서도 비-PK
    assert SchemaExtractor._gate_ubiquity(cands, name_freq, pk_set, k=3) == []


def test_g2_keeps_pk_column_even_if_ubiquitous():
    """컬럼이 어딘가의 PK 면 편재해도 절대 suppress 안 함 (false-negative 방지).

    SPLR_CODE 가 4 fact 에 편재(freq 5)하지만 SPLR_MASTER 의 PK → multi-fact →
    single-dim star join 은 정당. M2 회귀.
    """
    cands = [
        InferredJoin("FACT1", "SPLR_MASTER", [("SPLR_CODE", "SPLR_CODE")]),
        InferredJoin("FACT2", "SPLR_MASTER", [("SPLR_CODE", "SPLR_CODE")]),
        InferredJoin("FACT3", "SPLR_MASTER", [("SPLR_CODE", "SPLR_CODE")]),
        InferredJoin("FACT4", "SPLR_MASTER", [("SPLR_CODE", "SPLR_CODE")]),
    ]
    name_freq = {"splr_code": 5}
    pk_set = {"splr_master": {"splr_code"}}  # SPLR_CODE 는 SPLR_MASTER PK
    kept = SchemaExtractor._gate_ubiquity(cands, name_freq, pk_set, k=3)
    assert kept == cands  # 4 fact 후보 전부 생존


def test_g2_keeps_non_ubiquitous_column():
    """편재하지 않으면(freq ≤ k) suppress 하지 않음 — G2 책임은 ubiquity 만."""
    cands = [InferredJoin("A", "B", [("RARE_CODE", "RARE_CODE")])]
    name_freq = {"rare_code": 2}
    pk_set = {"a": {"a_id"}}  # 비-PK 지만 비-편재
    assert SchemaExtractor._gate_ubiquity(cands, name_freq, pk_set, k=3) == cands


# ---------------------------------------------------------------------------
# T5 — G5 composite-aware grouping (critique C1, constraint_name 미사용)
# ---------------------------------------------------------------------------
def test_g5_composite_full_cover_merges_to_single_join():
    """복합 PK {MATR_CODE, PLANT_CODE} 를 한 source 가 전부 cover → 단일 composite."""
    cands = [
        InferredJoin("A", "B", [("MATR_CODE", "MATR_CODE")]),
        InferredJoin("A", "B", [("PLANT_CODE", "PLANT_CODE")]),
    ]
    pk_set = {"b": {"matr_code", "plant_code"}}
    out = SchemaExtractor._gate_composite(cands, pk_set)
    assert len(out) == 1
    j = out[0]
    assert j.source_table == "A" and j.target_table == "B"
    assert set(j.column_pairs) == {
        ("MATR_CODE", "MATR_CODE"),
        ("PLANT_CODE", "PLANT_CODE"),
    }


def test_g5_composite_partial_cover_rejected():
    """복합 PK 의 절반만 매칭(MATR_CODE 단독, PLANT_CODE 누락) → 전체 reject."""
    cands = [InferredJoin("A", "B", [("MATR_CODE", "MATR_CODE")])]
    pk_set = {"b": {"matr_code", "plant_code"}}
    assert SchemaExtractor._gate_composite(cands, pk_set) == []


def test_g5_single_member_pk_passes_through():
    """단일 멤버 PK 는 각 후보가 독립 full-cover → 그대로 통과."""
    cands = [InferredJoin("FACT", "DIM", [("CODE", "CODE")])]
    pk_set = {"dim": {"code"}}
    assert SchemaExtractor._gate_composite(cands, pk_set) == cands


def test_g5_multiple_sources_to_single_pk_dim_kept_separate():
    """여러 fact → 한 dim(단일 PK) star 는 합치지 않고 각각 유지 (오합침 방지).

    critique C1: 그룹핑을 cover-집합 단위로 — 단일 PK 는 각 source 가 독립
    full-cover 라 (source,target) 가 달라 별도 join 으로 남는다.
    """
    cands = [
        InferredJoin("FACT1", "DIM", [("CODE", "CODE")]),
        InferredJoin("FACT2", "DIM", [("CODE", "CODE")]),
    ]
    pk_set = {"dim": {"code"}}
    out = SchemaExtractor._gate_composite(cands, pk_set)
    assert len(out) == 2
    assert {c.source_table for c in out} == {"FACT1", "FACT2"}


# ---------------------------------------------------------------------------
# T6 — G4 double-target dedup (structural)
# ---------------------------------------------------------------------------
def test_g4_keeps_pk_target_drops_attribute_target():
    """한 source 컬럼이 PK-target + 속성-target 둘 다 → PK-target 1개만.

    SALES.ITEM_CODE → {ITEM_MASTER(PK), MATR_MASTER(속성)} → ITEM_MASTER.
    """
    cands = [
        InferredJoin("SALES", "MATR_MASTER", [("ITEM_CODE", "ITEM_CODE")]),
        InferredJoin("SALES", "ITEM_MASTER", [("ITEM_CODE", "ITEM_CODE")]),
    ]
    pk_set = {"item_master": {"item_code"}, "matr_master": {"matr_id"}}
    out = SchemaExtractor._gate_double_target(cands, pk_set)
    assert len(out) == 1
    assert out[0].target_table == "ITEM_MASTER"


def test_g4_dedups_multiple_pk_targets_to_one():
    """한 source 컬럼이 복수 PK-target → 결정론적으로 1개 (tie-break)."""
    cands = [
        InferredJoin("SALES", "ITEM_ARCHIVE", [("ITEM_CODE", "ITEM_CODE")]),
        InferredJoin("SALES", "ITEM_MASTER", [("ITEM_CODE", "ITEM_CODE")]),
    ]
    pk_set = {"item_master": {"item_code"}, "item_archive": {"item_code"}}
    out = SchemaExtractor._gate_double_target(cands, pk_set)
    assert len(out) == 1  # 모호 double-target → 1개로 축약


def test_g4_keeps_different_source_columns():
    """source 컬럼이 다르면 각각 유지(다른 dimension 참조)."""
    cands = [
        InferredJoin("SALES", "ITEM_MASTER", [("ITEM_CODE", "ITEM_CODE")]),
        InferredJoin("SALES", "CUST_MASTER", [("CUST_CODE", "CUST_CODE")]),
    ]
    pk_set = {"item_master": {"item_code"}, "cust_master": {"cust_code"}}
    out = SchemaExtractor._gate_double_target(cands, pk_set)
    assert len(out) == 2


def test_g4_keeps_star_multiple_sources_same_dim():
    """여러 fact → 한 dim(같은 컬럼)은 dedup 대상 아님(source 다름) — star 유지."""
    cands = [
        InferredJoin("FACT1", "DIM", [("CODE", "CODE")]),
        InferredJoin("FACT2", "DIM", [("CODE", "CODE")]),
    ]
    pk_set = {"dim": {"code"}}
    out = SchemaExtractor._gate_double_target(cands, pk_set)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# T6b — G6 source-not-sole-PK (direct gate unit, sibling pattern T3-T6)
# ---------------------------------------------------------------------------
def test_g6_rejects_sole_pk_source():
    """source 컬럼이 source 의 단일컬럼 PK 전체 → reject (surrogate id identity)."""
    cands = [InferredJoin("A", "B", [("id", "id")])]
    pk_set = {"a": {"id"}, "b": {"id"}}
    assert SchemaExtractor._gate_source_not_sole_pk(cands, pk_set) == []


def test_g6_exempts_composite_pk_source():
    """복합 PK(len>1) 멤버는 면제 — bridge/junction 의 정당한 FK 보존."""
    cands = [InferredJoin("ORDER_ITEM", "ORDERS", [("order_id", "order_id")])]
    pk_set = {"order_item": {"order_id", "item_id"}, "orders": {"order_id"}}
    assert SchemaExtractor._gate_source_not_sole_pk(cands, pk_set) == cands


def test_g6_keeps_non_key_source_col():
    """source 컬럼이 source PK 가 아니면(비-key 비즈니스키) 통과 (star FK)."""
    cands = [InferredJoin("FACT", "DIM", [("cust_code", "cust_code")])]
    pk_set = {"fact": {"sales_id"}, "dim": {"cust_code"}}
    assert SchemaExtractor._gate_source_not_sole_pk(cands, pk_set) == cands


def test_g6_keeps_source_without_pk():
    """source 에 PK 자체가 없으면 통과 — identity 판정 불가, fail-open(safe)."""
    cands = [InferredJoin("A", "B", [("code", "code")])]
    pk_set = {"b": {"code"}}  # A 는 pk_set 에 없음
    assert SchemaExtractor._gate_source_not_sole_pk(cands, pk_set) == cands


def test_g6_shared_pk_extension_dropped_known_tradeoff():
    """알려진 trade-off boundary pin: shared-PK 1:1 extension 의 정당한 FK 도 drop.

    USER_PROFILE.user_id 가 sole PK 인 동시에 USERS.user_id 로의 정당한 FK 라도
    구조 신호(source sole-PK == join 컬럼)가 surrogate identity 와 동일해 양방향
    drop 된다. gate 는 is_foreign_key 를 받지 않으므로(candidates+pk_set 만) 순수
    구조 동작을 고정 — G4 신호확장(is_foreign_key 면제)이 이 동작을 뒤집을 때
    이 테스트가 그 변경을 잡는다(intentional marker, not a passing-by-accident).
    """
    cands = [
        InferredJoin("USER_PROFILE", "USERS", [("user_id", "user_id")]),
        InferredJoin("USERS", "USER_PROFILE", [("user_id", "user_id")]),
    ]
    pk_set = {"user_profile": {"user_id"}, "users": {"user_id"}}
    assert SchemaExtractor._gate_source_not_sole_pk(cands, pk_set) == []


# ---------------------------------------------------------------------------
# 파이프라인 합성 — _infer_column_semantics (capability → generate → G6·G1·G2·G5·G4)
# ---------------------------------------------------------------------------
def _all_cols(j: InferredJoin) -> set:
    return {c for pair in j.column_pairs for c in pair}


async def test_infer_pipeline_signal_passes_noise_blocked():
    """end-to-end: SPLR_CODE→SPLR_MASTER(PK) 통과, PLANT_CODE 순수속성 fan-out 차단.

    surrogate PK 는 table-specific 명(FA_ID 등)이라 동일명 매칭 confound 없음.
    """
    details = [
        _td("SPLR_MASTER", [_col("SPLR_CODE", pk=True), _col("SPLR_NAME")]),
        _td("FACT_A", [_col("FA_ID", pk=True), _col("SPLR_CODE"), _col("PLANT_CODE")]),
        _td("FACT_B", [_col("FB_ID", pk=True), _col("SPLR_CODE"), _col("PLANT_CODE")]),
        _td("FACT_C", [_col("FC_ID", pk=True), _col("PLANT_CODE")]),
        _td("FACT_D", [_col("FD_ID", pk=True), _col("PLANT_CODE")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(details)
    splr = [j for j in joins if j.target_table == "SPLR_MASTER"]
    assert {j.source_table for j in splr} == {"FACT_A", "FACT_B"}
    # PLANT_CODE 는 어디서도 PK 아님 → 추론 0
    assert all("PLANT_CODE" not in _all_cols(j) for j in joins)


async def test_infer_pipeline_composite_full_cover():
    """복합 PK dim 을 fact 가 전 멤버 cover → 단일 composite join."""
    details = [
        _td(
            "DIM_MP",
            [_col("MATR_CODE", pk=True), _col("PLANT_CODE", pk=True), _col("X")],
        ),
        _td("FACT", [_col("F_ID", pk=True), _col("MATR_CODE"), _col("PLANT_CODE")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(details)
    assert len(joins) == 1
    j = joins[0]
    assert j.source_table == "FACT" and j.target_table == "DIM_MP"
    assert set(j.column_pairs) == {
        ("MATR_CODE", "MATR_CODE"),
        ("PLANT_CODE", "PLANT_CODE"),
    }


async def test_infer_pipeline_composite_partial_rejected():
    """fact 가 복합 PK 의 절반만(MATR_CODE) 매칭 → composite-half reject (추론 0)."""
    details = [
        _td("DIM_MP", [_col("MATR_CODE", pk=True), _col("PLANT_CODE", pk=True)]),
        _td("FACT", [_col("F_ID", pk=True), _col("MATR_CODE")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    assert await ext._infer_column_semantics(details) == []


async def test_infer_pipeline_db_bq_no_pk_returns_empty():
    """PK 신호 0(databricks/bigquery) → capability gate 에서 추론 0(noise 0)."""
    details = [
        _td("T1", [_col("SHARED"), _col("A")]),
        _td("T2", [_col("SHARED"), _col("B")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    assert await ext._infer_column_semantics(details) == []


# ---------------------------------------------------------------------------
# T8 — hook 배선 (extract_and_save_to_memory → _infer → _save)
# ---------------------------------------------------------------------------
async def test_hook_wires_inference_into_join_graph(monkeypatch):
    """gather 후·cancel checkpoint 뒤 _recompute_join_graph 호출 → inferred 가
    result["join_graph"] 에 렌더된다 (Option C: DOCUMENTATION doc 미저장).

    FakeRunner 는 verified FK 0 이지만 inferred(FACT.SPLR_CODE→SPLR_MASTER PK)가
    생성되어 join_graph 에 candidate 로 실린다(FK-less + inferred 핵심 유스케이스).
    """
    ext = SchemaExtractor(sql_runner=FakeRunner())
    td_map = {
        "FACT": _td("FACT", [_col("FA_ID", pk=True), _col("SPLR_CODE")]),
        "SPLR_MASTER": _td("SPLR_MASTER", [_col("SPLR_CODE", pk=True), _col("NM")]),
    }

    async def fake_extract(table_name, runner=None):
        return td_map[table_name]

    monkeypatch.setattr(ext, "extract_table_details", fake_extract)
    mem = FakeMemory()
    res = await ext.extract_and_save_to_memory(
        memory=mem, table_names=["FACT", "SPLR_MASTER"], generate_sample_qa=False
    )
    assert res["ddl_saved"] == 2
    g = res["join_graph"]
    assert "### Inferred (structural candidates — not verified FK)" in g
    assert (
        "- FACT → SPLR_MASTER (candidate)  ON FACT.SPLR_CODE = SPLR_MASTER.SPLR_CODE"
        in g
    )
    # Option C: relationship lives in dbsphere.data["join_graph"], not a doc.
    assert not any(
        d.get("memory_id", "").endswith("__relationship_graph") for d in mem.docs
    )


async def test_hook_passes_table_details_to_inference(monkeypatch):
    """추론은 result['table_details'] 를 입력으로 받는다(누적된 추출 결과)."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    seen = {}

    async def fake_extract(table_name, runner=None):
        return _td(table_name, [_col("ID", pk=True)])

    async def spy_infer(table_details):
        seen["n"] = len(table_details)
        return []

    monkeypatch.setattr(ext, "extract_table_details", fake_extract)
    monkeypatch.setattr(ext, "_infer_column_semantics", spy_infer)
    mem = FakeMemory()
    await ext.extract_and_save_to_memory(
        memory=mem, table_names=["A", "B", "C"], generate_sample_qa=False
    )
    assert seen["n"] == 3  # 3 테이블 details 누적 후 추론에 전달


async def test_hook_no_inference_when_cancelled(monkeypatch):
    """cancel checkpoint 존중 — 취소 시 추론·save 미실행."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    called = {"infer": 0}

    async def spy_infer(table_details):
        called["infer"] += 1
        return []

    monkeypatch.setattr(ext, "_infer_column_semantics", spy_infer)
    mem = FakeMemory()
    res = await ext.extract_and_save_to_memory(
        memory=mem,
        table_names=["FACT"],
        generate_sample_qa=False,
        should_cancel=lambda: True,
    )
    assert res.get("cancelled") is True
    assert called["infer"] == 0
    assert mem.docs == []


# ---------------------------------------------------------------------------
# T9 — 통합 회귀: 41-join 실데이터 subset fixture (same-name only)
#   testpaths: backend/extension_modules/dbsphere/tests 는 pyproject 에 등록됨(PC8).
# ---------------------------------------------------------------------------
def _qms_fixture():
    """DG_QMS류 enterprise 스키마의 same-name 핵심 subset.

    dimensions(PK) + facts + 순수속성 fan-out(PLANT_CODE) + cross-name(LINE/WRK)
    + composite PK(MATR_PLANT) 를 한 스키마에 담아 v1 파이프라인 전수 검증.
    """
    return [
        # ---- dimensions ----
        _td("T_SPLR_MASTER", [_col("SPLR_CODE", pk=True), _col("SPLR_NM")]),
        _td("T_ITEM_MASTER", [_col("ITEM_CODE", pk=True), _col("ITEM_NM")]),
        _td(
            "T_MATR_PLANT",
            [_col("MATR_CODE", pk=True), _col("PLANT_CODE", pk=True), _col("QTY")],
        ),
        # ---- facts ----
        _td(
            "T_MATR_WHIN",
            [
                _col("WHIN_ID", pk=True),
                _col("SPLR_CODE"),
                _col("ITEM_CODE"),
                _col("MATR_CODE"),
                _col("PLANT_CODE"),
            ],
        ),
        _td(
            "T_SALES",
            [_col("SALES_ID", pk=True), _col("ITEM_CODE"), _col("PLANT_CODE")],
        ),
        # T_PROD: MATR_CODE 만(PLANT_CODE 없음) → composite-half + SPLR multi-fact
        _td("T_PROD", [_col("PROD_ID", pk=True), _col("SPLR_CODE"), _col("MATR_CODE")]),
        # 순수속성 fan-out: PLANT_CODE 편재, sole-PK 아님
        _td("T_PLANT_USAGE", [_col("USAGE_ID", pk=True), _col("PLANT_CODE")]),
        # cross-name(v2): LINE_CODE ≠ WRK_CD → v1 same-name 미생성
        _td("T_LINE", [_col("LINE_ID", pk=True), _col("LINE_CODE")]),
        _td("T_WORK", [_col("WRK_CD", pk=True), _col("WRK_NM")]),
    ]


def _jkey(joins):
    return {(j.source_table, j.target_table, frozenset(j.column_pairs)) for j in joins}


async def test_integration_exact_signal_set():
    """전체 파이프라인 결과 = 정확히 5개 signal join (noise 0)."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(_qms_fixture())
    assert _jkey(joins) == {
        ("T_MATR_WHIN", "T_SPLR_MASTER", frozenset({("SPLR_CODE", "SPLR_CODE")})),
        ("T_PROD", "T_SPLR_MASTER", frozenset({("SPLR_CODE", "SPLR_CODE")})),
        ("T_MATR_WHIN", "T_ITEM_MASTER", frozenset({("ITEM_CODE", "ITEM_CODE")})),
        ("T_SALES", "T_ITEM_MASTER", frozenset({("ITEM_CODE", "ITEM_CODE")})),
        (
            "T_MATR_WHIN",
            "T_MATR_PLANT",
            frozenset({("MATR_CODE", "MATR_CODE"), ("PLANT_CODE", "PLANT_CODE")}),
        ),
    }


async def test_integration_multi_fact_to_single_dim():
    """multi-fact → single-dim false-negative 방지: SPLR_CODE 2 fact 모두 통과."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(_qms_fixture())
    splr = {j.source_table for j in joins if j.target_table == "T_SPLR_MASTER"}
    assert splr == {"T_MATR_WHIN", "T_PROD"}


async def test_integration_composite_signal_merged():
    """MATR_CODE+PLANT_CODE 전체 cover → 단일 composite, 절반(T_PROD/T_SALES) reject."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(_qms_fixture())
    to_mp = [j for j in joins if j.target_table == "T_MATR_PLANT"]
    assert len(to_mp) == 1
    assert to_mp[0].source_table == "T_MATR_WHIN"
    assert len(to_mp[0].column_pairs) == 2


async def test_integration_plant_code_fanout_blocked():
    """PLANT_CODE 순수 fan-out(비-composite target) 차단 — T_MATR_PLANT 외 target 없음."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(_qms_fixture())
    plant_targets = {
        j.target_table for j in joins if any("PLANT_CODE" in p for p in j.column_pairs)
    }
    assert plant_targets <= {"T_MATR_PLANT"}  # 오직 composite dim 만


async def test_integration_cross_name_not_generated_v1():
    """cross-name(LINE_CODE↔WRK_CD)은 다른 이름 → v1 same-name 미생성(v2 영역)."""
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(_qms_fixture())
    tables = {j.source_table for j in joins} | {j.target_table for j in joins}
    assert "T_WORK" not in tables
    assert "T_LINE" not in tables


async def test_integration_db_bq_no_pk_zero():
    """동일 스키마라도 PK 신호 0(databricks/bigquery) → 추론 0(noise 0)."""

    def _strip_pk(details):
        return [
            _td(td.table_name, [_col(c.name) for c in td.columns]) for td in details
        ]

    ext = SchemaExtractor(sql_runner=FakeRunner())
    assert await ext._infer_column_semantics(_strip_pk(_qms_fixture())) == []


async def test_integration_double_target_dedup():
    """double-target: 한 컬럼이 두 dim PK → fact 후보 1개로 dedup."""
    details = [
        _td("DIM_X", [_col("GRP_CODE", pk=True), _col("XN")]),
        _td("DIM_Y", [_col("GRP_CODE", pk=True), _col("YN")]),
        _td("FACT", [_col("F_ID", pk=True), _col("GRP_CODE")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(details)
    fact_joins = [j for j in joins if j.source_table == "FACT"]
    assert len(fact_joins) == 1


# ---------------------------------------------------------------------------
# T10 — G6 source-not-sole-PK (generic surrogate 'id' fan-out, backlog #5)
# ---------------------------------------------------------------------------
async def test_g6_generic_id_surrogate_pk_yields_no_inferred():
    """전 테이블 단일컬럼 'id' surrogate PK → 추론 0 (G6).

    프로덕션 증상 재현: id 가 모든 테이블에 sole PK 로 편재하면 same-name 생성이
    A.id↔B.id fan-out 을 만들고 G1(target id 도 PK)·G4(alpha tie-break)를 통과해
    모든 id → 알파벳 첫 id-PK 테이블(audit_log)로 붕괴한다. G6 가 근원에서 차단.
    """
    tbls = ["audit_log", "channels", "users", "orgs", "groups", "files"]
    details = [_td(t, [_col("id", pk=True), _col(t[:3] + "_nm")]) for t in tbls]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    assert await ext._infer_column_semantics(details) == []


async def test_g6_exempts_composite_pk_bridge():
    """복합 PK bridge 의 FK 멤버는 G6 면제(len>1) — junction join 보존.

    order_item PK=(order_id,item_id), 두 멤버가 각각 orders/items 의 PK 를 가리킨다.
    G6 는 source 의 단일컬럼 sole PK 만 차단하므로 복합 PK source 는 건드리지 않는다.
    """
    details = [
        _td("orders", [_col("order_id", pk=True), _col("amt")]),
        _td("items", [_col("item_id", pk=True), _col("nm")]),
        _td("order_item", [_col("order_id", pk=True), _col("item_id", pk=True)]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(details)
    bridge = {(j.source_table, j.target_table) for j in joins}
    assert bridge == {("order_item", "orders"), ("order_item", "items")}


async def test_g6_keeps_business_key_fk_from_surrogate_pk_source():
    """surrogate sole-PK fact 라도 non-key 비즈니스 컬럼 FK 는 보존(G6 미발화).

    fact 의 sole PK 는 sales_id(surrogate), join 컬럼 cust_code 는 non-key →
    G6 조건(source 컬럼 == source 의 sole PK) 불성립 → 외향 FK 유지.
    """
    details = [
        _td("cust_dim", [_col("cust_code", pk=True), _col("cust_nm")]),
        _td("fact_sales", [_col("sales_id", pk=True), _col("cust_code")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(details)
    assert {(j.source_table, j.target_table) for j in joins} == {
        ("fact_sales", "cust_dim")
    }


async def test_g6_mixed_schema_drops_only_id_noise():
    """signal+noise 혼재 → G6 는 id 노이즈만 제거, 비즈니스키 signal 은 전부 보존.

    ITEM_CODE(dim PK) signal 2개는 살리고, 3개 sole-id PK 테이블의 id↔id fan-out 은
    전부 차단 — 노이즈가 all-id 스키마에만 국한되지 않음 + 무회귀를 동시 증명.
    """
    details = [
        _td("ITEM_MASTER", [_col("ITEM_CODE", pk=True), _col("ITEM_NM")]),
        _td("FACT_SALES", [_col("id", pk=True), _col("ITEM_CODE")]),
        _td("FACT_RETURN", [_col("id", pk=True), _col("ITEM_CODE")]),
        _td("AUDIT", [_col("id", pk=True), _col("msg")]),
    ]
    ext = SchemaExtractor(sql_runner=FakeRunner())
    joins = await ext._infer_column_semantics(details)
    assert {(j.source_table, j.target_table) for j in joins} == {
        ("FACT_SALES", "ITEM_MASTER"),
        ("FACT_RETURN", "ITEM_MASTER"),
    }
