"""Adversarial unit tests for the DbSphere SQL classifier.

핵심 시나리오: 첫 키워드만 보면 READ 처럼 보이지만 실제로 WRITE 인 케이스 +
저장 프로시저 / 익명 블록 / 다중 statement / 코멘트 처리.

This is the safety gate before the executor runs user-typed SQL — every case
here is a real shoot-yourself-in-the-foot scenario for at least one supported
DB dialect.
"""

from extension_modules.dbsphere.sql_classifier import StmtClass, classify_statement


class TestSqlClassifierHappyPath:
    def test_simple_select(self):
        assert classify_statement("SELECT * FROM t") == StmtClass.READ

    def test_simple_select_with_where(self):
        assert (
            classify_statement("SELECT id, name FROM users WHERE active = 1")
            == StmtClass.READ
        )

    def test_show_tables(self):
        assert classify_statement("SHOW TABLES") == StmtClass.READ

    def test_describe(self):
        assert classify_statement("DESCRIBE users") == StmtClass.READ
        assert classify_statement("DESC users") == StmtClass.READ

    def test_simple_insert(self):
        assert classify_statement("INSERT INTO t VALUES (1)") == StmtClass.WRITE

    def test_simple_update(self):
        assert classify_statement("UPDATE t SET x = 1 WHERE id = 1") == StmtClass.WRITE

    def test_simple_delete(self):
        assert classify_statement("DELETE FROM t WHERE id = 1") == StmtClass.WRITE

    def test_drop_table(self):
        assert classify_statement("DROP TABLE t") == StmtClass.WRITE

    def test_truncate(self):
        assert classify_statement("TRUNCATE TABLE t") == StmtClass.WRITE

    def test_create_table(self):
        assert classify_statement("CREATE TABLE t (id INT)") == StmtClass.WRITE

    def test_alter_table(self):
        assert classify_statement("ALTER TABLE t ADD COLUMN x INT") == StmtClass.WRITE

    def test_merge(self):
        sql = "MERGE INTO t USING s ON t.id=s.id WHEN MATCHED THEN UPDATE SET t.x=s.x"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_grant_revoke(self):
        assert classify_statement("GRANT SELECT ON t TO me") == StmtClass.WRITE
        assert classify_statement("REVOKE SELECT ON t FROM me") == StmtClass.WRITE


class TestSqlClassifierAdversarial:
    """Stage 1 critique H4 — first-keyword-only 분류가 놓치는 패턴들."""

    def test_explain_select_is_read(self):
        # EXPLAIN <SELECT> 는 안전 — 플랜만 출력, 실행 안 함.
        assert classify_statement("EXPLAIN SELECT * FROM t") == StmtClass.READ

    def test_explain_analyze_select_is_read(self):
        # EXPLAIN ANALYZE <SELECT> — SELECT 실행은 하지만 결과는 플랜 통계로만.
        # 보수적으로 READ 로 두되, 이게 위험하다면 다른 deny-list 추가 검토.
        assert classify_statement("EXPLAIN ANALYZE SELECT * FROM t") == StmtClass.READ

    def test_explain_analyze_delete_is_write(self):
        # PG: EXPLAIN ANALYZE <DML> 은 DML 을 실제로 실행한다 → 반드시 WRITE.
        assert (
            classify_statement("EXPLAIN ANALYZE DELETE FROM t WHERE 1=1")
            == StmtClass.WRITE
        )

    def test_explain_analyze_update_is_write(self):
        assert classify_statement("EXPLAIN ANALYZE UPDATE t SET x=1") == StmtClass.WRITE

    def test_explain_with_options_analyze_delete_is_write(self):
        # PG: `EXPLAIN (ANALYZE, VERBOSE) <DML>` 옵션 표기.
        assert (
            classify_statement("EXPLAIN (ANALYZE, VERBOSE) DELETE FROM t WHERE id = 1")
            == StmtClass.WRITE
        )

    def test_explain_buffers_analyze_delete_is_write(self):
        assert (
            classify_statement("EXPLAIN (BUFFERS, ANALYZE) UPDATE t SET x = 1")
            == StmtClass.WRITE
        )

    def test_cte_with_select_is_read(self):
        sql = "WITH x AS (SELECT 1 AS n) SELECT * FROM x"
        assert classify_statement(sql) == StmtClass.READ

    def test_cte_with_delete_is_write(self):
        # PG: `WITH ... AS (DELETE FROM t RETURNING *) SELECT * FROM x` 실제 DELETE.
        sql = "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_cte_with_insert_is_write(self):
        sql = "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_cte_with_update_is_write(self):
        sql = "WITH x AS (UPDATE t SET x=1 RETURNING *) SELECT * FROM x"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_cte_multiline_with_delete_is_write(self):
        sql = """WITH
            deleted AS (
                DELETE FROM audit_log
                WHERE created_at < 0
                RETURNING *
            )
            SELECT count(*) FROM deleted"""
        assert classify_statement(sql) == StmtClass.WRITE

    def test_call_proc_is_write(self):
        # 저장 프로시저는 내부에서 무엇이든 가능 — 보수적으로 WRITE.
        assert classify_statement("CALL my_proc(1, 2)") == StmtClass.WRITE

    def test_exec_proc_is_write(self):
        # MSSQL: `EXEC sp_x` / `EXECUTE sp_x`.
        assert classify_statement("EXEC my_proc 1, 2") == StmtClass.WRITE
        assert classify_statement("EXECUTE my_proc(1, 2)") == StmtClass.WRITE

    def test_do_block_is_write(self):
        # PG anonymous code block — 본문에 DELETE 등 가능.
        sql = "DO $$ BEGIN DELETE FROM t; END $$"
        assert classify_statement(sql) == StmtClass.WRITE


class TestSqlClassifierEdgeCases:
    def test_empty_invalid(self):
        assert classify_statement("") == StmtClass.INVALID
        assert classify_statement("   ") == StmtClass.INVALID
        assert classify_statement("\n\t  \n") == StmtClass.INVALID

    def test_comment_only_invalid(self):
        assert classify_statement("-- only a comment") == StmtClass.INVALID
        assert classify_statement("/* block */") == StmtClass.INVALID

    def test_multi_statement_unknown(self):
        sql = "SELECT 1; INSERT INTO t VALUES (2)"
        assert classify_statement(sql) == StmtClass.UNKNOWN

    def test_trailing_semicolon_single_statement(self):
        # 끝 세미콜론 하나는 single-statement.
        assert classify_statement("SELECT 1;") == StmtClass.READ
        assert classify_statement("INSERT INTO t VALUES (1);") == StmtClass.WRITE

    def test_line_comment_then_insert(self):
        sql = "-- harmless comment\nINSERT INTO t VALUES (1)"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_block_comment_then_delete(self):
        sql = "/* block */ DELETE FROM t WHERE 1=1"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_unknown_keyword(self):
        # `PRAGMA` (SQLite) 는 READ/WRITE 매핑이 모호하므로 UNKNOWN.
        assert classify_statement("PRAGMA foreign_keys = ON") == StmtClass.UNKNOWN

    def test_lowercase_input(self):
        # 대소문자 무관.
        assert classify_statement("select * from t") == StmtClass.READ
        assert classify_statement("delete from t") == StmtClass.WRITE
        assert classify_statement("explain analyze delete from t") == StmtClass.WRITE

    def test_leading_whitespace(self):
        assert classify_statement("   \n  SELECT 1") == StmtClass.READ


class TestSqlClassifierCteDmlHardening:
    """C4 #3 — CTE-then-DML / SELECT INTO 등 first-keyword 가드가 놓친 우회."""

    def test_cte_then_delete_is_write(self):
        # DML 이 CTE *바깥* main statement — 기존 AS(...) 패턴이 놓치던 갭.
        assert (
            classify_statement("WITH cte AS (SELECT 1) DELETE FROM t WHERE id=1")
            == StmtClass.WRITE
        )

    def test_cte_then_update_is_write(self):
        assert (
            classify_statement("WITH cte AS (SELECT 1) UPDATE t SET x = 1")
            == StmtClass.WRITE
        )

    def test_cte_then_insert_is_write(self):
        assert (
            classify_statement(
                "WITH cte AS (SELECT 1 AS n) INSERT INTO t SELECT n FROM cte"
            )
            == StmtClass.WRITE
        )

    def test_cte_then_delete_multiline_is_write(self):
        sql = """WITH cte AS (
            SELECT id FROM stale WHERE created_at < 0
        )
        DELETE FROM target WHERE id IN (SELECT id FROM cte)"""
        assert classify_statement(sql) == StmtClass.WRITE

    def test_second_cte_dml_is_write(self):
        sql = "WITH a AS (SELECT 1), b AS (DELETE FROM t RETURNING *) SELECT * FROM b"
        assert classify_statement(sql) == StmtClass.WRITE

    def test_cte_with_only_select_stays_read(self):
        assert (
            classify_statement("WITH x AS (SELECT 1 AS n) SELECT * FROM x")
            == StmtClass.READ
        )

    def test_select_into_table_is_write(self):
        # SQL Server / PostgreSQL: SELECT ... INTO <new> FROM ... 가 테이블 생성.
        assert (
            classify_statement("SELECT id, name INTO archive FROM users")
            == StmtClass.WRITE
        )

    def test_select_star_into_table_is_write(self):
        assert (
            classify_statement("SELECT * INTO backup_t FROM live_t") == StmtClass.WRITE
        )

    def test_select_into_outfile_is_write(self):
        # MySQL: SELECT ... INTO OUTFILE 가 파일 쓰기.
        assert (
            classify_statement("SELECT * FROM t INTO OUTFILE '/tmp/x.csv'")
            == StmtClass.WRITE
        )

    def test_plain_select_with_from_stays_read(self):
        assert classify_statement("SELECT a, b FROM t WHERE a > 1") == StmtClass.READ

    def test_select_mentioning_into_in_string_without_from_stays_read(self):
        # 'into' 가 단순 문자열에 있고 INTO <ident> FROM 형태가 아니면 READ 유지.
        assert (
            classify_statement("SELECT note FROM t WHERE note = 'put it into the box'")
            == StmtClass.READ
        )

    def test_select_into_quoted_target_is_write(self):
        # 따옴표 식별자(공백 포함) 대상 — FROM 앵커 분리 전엔 READ 로 새던 케이스.
        assert (
            classify_statement('SELECT a, b INTO "my schema".bak FROM live')
            == StmtClass.WRITE
        )

    def test_select_into_bracketed_target_is_write(self):
        # MSSQL 대괄호 식별자.
        assert (
            classify_statement("SELECT * INTO [my table] FROM live") == StmtClass.WRITE
        )

    def test_select_into_temp_table_is_write(self):
        # MSSQL #temp 테이블.
        assert classify_statement("SELECT * INTO #temp FROM live") == StmtClass.WRITE
