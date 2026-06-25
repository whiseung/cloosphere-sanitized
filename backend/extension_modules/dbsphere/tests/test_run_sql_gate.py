"""C4 #3 — run_sql_read/write gate 가 classify_statement 로 CTE-DML 을 라우팅.

핵심 회귀 방지:
- run_sql_read 는 CTE-wrapped DML 을 거부(HITL 우회 차단).
- run_sql_write 는 그 CTE-DML 을 *수락*해 실제 실행(C-4: 두 도구 무한 반사 방지).
"""

import pandas as pd
from extension_modules.dbsphere.tools.run_sql import (
    create_run_sql_read_tool,
    create_run_sql_write_tool,
)


class _Runtime:
    tool_call_id = "tc1"


class _SpyRunner:
    """run_sql 호출 여부/인자를 기록. gate 가 거부하면 호출되지 않아야 한다."""

    def __init__(self):
        self.ran = []

    async def run_sql(self, sql):
        self.ran.append(sql)
        return pd.DataFrame()


def _msg(command):
    return command.update["messages"][0].content


_CTE_DML = "WITH x AS (SELECT 1) DELETE FROM t"


class TestRunSqlReadGate:
    async def test_cte_dml_rejected_from_read(self, tmp_path):
        runner = _SpyRunner()
        tool = create_run_sql_read_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(sql=_CTE_DML, runtime=_Runtime())
        assert "run_sql_read only executes read-only" in _msg(cmd)
        assert runner.ran == []  # 실행 안 됨 — HITL 우회 차단

    async def test_select_into_rejected_from_read(self, tmp_path):
        runner = _SpyRunner()
        tool = create_run_sql_read_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(
            sql="SELECT * INTO backup FROM live", runtime=_Runtime()
        )
        assert runner.ran == []

    async def test_plain_select_executes(self, tmp_path):
        runner = _SpyRunner()
        tool = create_run_sql_read_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(sql="SELECT 1", runtime=_Runtime())
        assert runner.ran == ["SELECT 1"]
        assert cmd.update.get("executed_sql") == "SELECT 1"

    async def test_cte_select_executes(self, tmp_path):
        runner = _SpyRunner()
        tool = create_run_sql_read_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(
            sql="WITH x AS (SELECT 1) SELECT * FROM x", runtime=_Runtime()
        )
        assert len(runner.ran) == 1


class TestRunSqlWriteGate:
    async def test_cte_dml_accepted_and_executed(self, tmp_path):
        # C-4: 거부만 하면 승인된 CTE-DML 이 영원히 실행 못 됨 → write 가 수락해야.
        runner = _SpyRunner()
        tool = create_run_sql_write_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(sql=_CTE_DML, runtime=_Runtime())
        assert runner.ran == [_CTE_DML]
        assert cmd.update.get("executed_sql") == _CTE_DML

    async def test_multi_statement_unknown_accepted_by_write(self, tmp_path):
        # UNKNOWN(multi-statement) 도 write 경로로 라우팅(default-deny).
        runner = _SpyRunner()
        tool = create_run_sql_write_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(sql="SELECT 1; DELETE FROM t", runtime=_Runtime())
        assert len(runner.ran) == 1

    async def test_plain_select_rejected_from_write(self, tmp_path):
        runner = _SpyRunner()
        tool = create_run_sql_write_tool(runner, working_directory=str(tmp_path))
        cmd = await tool.coroutine(sql="SELECT 1", runtime=_Runtime())
        assert "run_sql_write only executes" in _msg(cmd)
        assert runner.ran == []
