"""本地数据比代码旧了没有。

同一天被同一个问题卡了两次，根因都不是代码：

1. 体检报「缺营业成本、应收、存货」——数据源好好的，是库里那批数据在这些字段
   加进代码之前同步的。重新同步就补上了。
2. 五个选股策略全部筛出 0 家——看着像条件太严，实际是 annual_roe 等三列全库为空。

**两次的共同点是「看不出来」**：表里 102 期财报、5535 只股票，数量看着很齐全，
缺的是列；而列缺了不会报错，只会让下游判断悄悄失去依据，然后表现成
「模型说数据不足」或「策略太严」，把人引向完全错误的方向。
"""

import pytest

from stock_decision import freshness
from stock_decision.database import connection, now_iso


def _seed_universe(rows: int, fill_annual_roe: bool) -> None:
    with connection() as conn:
        for index in range(rows):
            conn.execute(
                """INSERT INTO market_universe (symbol, name, price, pe_ttm, pb, annual_roe, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"60000{index}", f"公司{index}", 10.0, 12.0, 1.2,
                 15.0 if fill_annual_roe else None, now_iso()))


def test_an_empty_column_is_reported():
    """代码在写、库里全空的列要报出来——这正是卡了两次的那种情况。"""
    _seed_universe(20, fill_annual_roe=False)

    result = freshness.check()
    columns = {f["column"] for f in result["findings"] if f["table"] == "market_universe"}
    assert "annual_roe" in columns
    assert result["stale"] is True


def test_a_filled_column_is_not_reported():
    _seed_universe(20, fill_annual_roe=True)

    result = freshness.check()
    columns = {f["column"] for f in result["findings"] if f["table"] == "market_universe"}
    assert "annual_roe" not in columns


def test_findings_come_with_how_to_fix():
    """只说「缺了」没用——上次就是因为不知道怎么补，才去怀疑数据源。"""
    _seed_universe(20, fill_annual_roe=False)

    result = freshness.check()
    actions = {a["table"]: a for a in result["actions"]}
    assert "market_universe" in actions
    assert "同步" in actions["market_universe"]["how"]


def test_an_empty_table_is_not_reported():
    """表本身是空的（还没同步过）不算「数据比代码旧」——那是「还没开始」。

    两者要分开：前者要提醒重新同步，后者提醒了也没用，只会让首次使用的人
    一进来就看到一屏告警。
    """
    result = freshness.check()
    tables = {f["table"] for f in result["findings"]}
    assert "market_universe" not in tables


def test_every_expected_column_actually_exists():
    """清单里写的列必须真的在表上。

    写错列名会让检查静默失效——它会去数一个不存在的列，报错或者永远返回 0，
    而这个模块的全部价值就在于「别让缺失静默」。
    """
    from stock_decision.database import is_postgres

    with connection() as conn:
        for table, columns in freshness.EXPECTED.items():
            if is_postgres():
                from stock_decision import pgbackend

                # 用 pgbackend.SCHEMA 而不是 current_schema()：测试跑在
                # stocks_pytest 下，而 search_path 里并没有它——查出来会是空集，
                # 于是这条测试变成「每一列都缺」，看起来像真问题。
                rows = conn.execute(
                    "SELECT column_name AS name FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s",
                    (pgbackend.SCHEMA, table)).fetchall()
            else:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            existing = {r["name"] for r in rows}
            missing = [c for c in columns if c not in existing]
            assert not missing, f"{table} 上没有这些列：{missing}"
