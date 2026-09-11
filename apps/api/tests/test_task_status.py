"""任务条目的状态只有三个值，而三个计数必须加得回总数。

## 这条为什么要守

v35 之前，候选初筛把模型的 verdict 直接塞进了 status——塞的是「深入研究」
「排除」，而全系统认的状态只有「待看 / 已建档 / 已排除」。代码那一侧后来改对了
（repository._VERDICT_STATUS 只在「直接排除」这一档动 status），**但库里已经
写下的行没人回填**。

结果：一个 30 项的任务，其中 11 项早就有结论了，页面上却显示「0 / 30 已处理」，
进度条一动不动，旁边又写着「待看 19」——三个数字互相矛盾，加起来也不等于 30。

**而页面不会报任何错。** 它只是安静地少数了三分之一。

## 守的是迁移函数本身，不是去扫线上数据

第一版写成「扫一遍库里有没有非法状态」，红验证时发现它**永远是绿的**——
测试连的是测试库，开发库里塞什么它都看不见。守错了地方的测试比没有更糟：
它给人一种"这条已经有人管了"的错觉。
"""

from __future__ import annotations

import sqlite3

from stock_decision.database import _canonicalise_task_item_status
from stock_decision.repository import TASK_ITEM_STATUSES


def _legacy_table() -> sqlite3.Connection:
    """造一张带老状态值的表，跟出问题时库里的样子一致。"""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE research_task_items (id INTEGER PRIMARY KEY, status TEXT, verdict TEXT)")
    conn.executemany(
        "INSERT INTO research_task_items (status, verdict) VALUES (?, ?)",
        [("深入研究", ""), ("深入研究", "值得深入"), ("排除", ""), ("待看", ""), ("已排除", "")],
    )
    return conn


def test_老状态值被搬回三个合法值():
    conn = _legacy_table()
    _canonicalise_task_item_status(conn)
    left = {row["status"] for row in conn.execute("SELECT DISTINCT status FROM research_task_items").fetchall()}
    assert left <= set(TASK_ITEM_STATUSES), (
        f"还剩这些非法状态：{left - set(TASK_ITEM_STATUSES)}。"
        "它们对三个计数都不可见——进度会永远差一截，而页面不会报错。"
    )


def test_排除换成已排除是同一件事():
    conn = _legacy_table()
    _canonicalise_task_item_status(conn)
    count = conn.execute("SELECT COUNT(*) AS n FROM research_task_items WHERE status = '已排除'").fetchone()["n"]
    assert count == 2, "原来的「排除」和「已排除」是同一件事，搬完应该合成两项"


def test_深入研究退回待看但判断不丢():
    """「深入研究」不是人的动作，是模型的判断——它属于 verdict 那一列。

    状态退回「待看」（人确实还没处理），判断补进 verdict。**不能只改状态**：
    那样搬完就把模型跑出来的结论丢了，而那一步是花过钱的。
    """

    conn = _legacy_table()
    _canonicalise_task_item_status(conn)
    rows = conn.execute("SELECT status, verdict FROM research_task_items WHERE verdict = '值得深入'").fetchall()
    assert len(rows) == 2, "两条「深入研究」都应该在 verdict 里留下判断"
    assert all(row["status"] == "待看" for row in rows), "它们的状态应该退回「待看」"


def test_没有老数据时不动手():
    """已经干净的库不该被这条迁移碰——每次启动都重写一遍是白白的写放大。"""

    conn = _legacy_table()
    conn.execute("UPDATE research_task_items SET status = '待看'")
    before = conn.execute("SELECT COUNT(*) AS n FROM research_task_items WHERE status = '待看'").fetchone()["n"]
    _canonicalise_task_item_status(conn)
    after = conn.execute("SELECT COUNT(*) AS n FROM research_task_items WHERE status = '待看'").fetchone()["n"]
    assert before == after == 5
