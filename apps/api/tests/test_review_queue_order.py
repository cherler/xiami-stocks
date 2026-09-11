"""复核工作台的顺序：**「很久没看了」压在「你写下的卖出条件被触发了」上面。**

## 2026-08-16 实测

队列的排序键是 `(due_since, company_name)` —— 纯按日期。于是：

    1. 2025-06-01 格力电器 — 距建立已超过 90 天
    2. 2026-08-10 贵州茅台 — 你写下的认错条件被踩到了

只要那条被踩到的判断写得比较近，它就会沉到底下。而复核工作台是**真正干活的
那一页**：前端把 `reasons` 原样铺开、不重排，卡片的先后就是他动手的先后。

## 这个道理这个文件里已经写过一遍

`_review_reasons` 里那句：「其余几条是"有新材料，你该看看"；这一条是
"你自己写下的那个门槛被越过了" —— 性质不同，不该跟它们并列在后面。」

**但它只管了一张卡片里几行字的次序，没管哪张卡片排在前面。**
而且连那几行字它自己都没排对：那句注释下面的 append 排在两条日期理由之后，
也就是第三行。

跟第二十一条是同一个形状 —— 决策看板把「命中」漏在权重表外面，
复核队列把它漏在排序键外面；产品里同一个概念，三处各写了一份名单。
"""

from datetime import date, timedelta

import pytest

from stock_decision import access
from stock_decision.database import connection
from stock_decision.repository import _review_rank, _review_reasons, review_queue

from test_idor import client, owned  # noqa: F401


def _row(name, since, hits=0, evidence=0, reviewed=None):
    return {"thesis_id": 0, "company_name": name, "status": "watching", "since": since,
            "next_review_date": None, "last_reviewed_at": reviewed, "new_counter_hits": hits,
            "new_counter_evidence": evidence, "new_high_events": 0, "trade_review_due": None}


def _ordered(rows):
    for row in rows:
        row["reasons"] = _review_reasons(row)
        row["due_since"] = row["since"][:10]
    return sorted(rows, key=lambda item: (_review_rank(item), item["due_since"],
                                          item["company_name"]))


def test_a_tripped_condition_comes_before_a_stale_one():
    """**这一条是要害。** 一条写于上个月、认错条件今天被踩到的判断，
    必须排在一条放了一年多、只是"该看看了"的前面。"""
    order = _ordered([
        _row("格力电器", "2025-06-01T09:00:00"),                 # 只是很久没看
        _row("贵州茅台", "2026-08-10T09:00:00", hits=1),         # 认错条件被踩到
    ])
    assert order[0]["company_name"] == "贵州茅台", [r["company_name"] for r in order]


def test_the_three_tiers_are_the_same_ones_the_board_uses():
    """命中 > 反证 > 其余 —— 跟决策看板 _ACTION_WEIGHT 同一个概念的同一种排法。
    **不在这里另定一套**：两处各排一次迟早会不一致（第二十一条就是这么来的）。"""
    assert _review_rank(_row("A", "2026-01-01T00:00:00", hits=1)) == 0
    assert _review_rank(_row("A", "2026-01-01T00:00:00", evidence=1)) == 1
    assert _review_rank(_row("A", "2026-01-01T00:00:00")) == 2


def test_inside_one_tier_the_older_one_still_comes_first():
    """同样紧急时，先看放得久的那条 —— 日期排序没有被丢掉，只是降为第二键。"""
    order = _ordered([
        _row("宁德时代", "2026-05-01T09:00:00", hits=1),
        _row("寒武纪", "2026-01-01T09:00:00", hits=1),
    ])
    assert [r["company_name"] for r in order] == ["寒武纪", "宁德时代"]


def test_the_tripped_condition_is_the_first_line_on_the_card():
    """那句注释说它「排在最前面」，而它原来排在两条日期理由之后 —— 第三行。

    卡片上第一行就是他扫到的第一句话。
    """
    row = _row("贵州茅台", "2026-08-10T09:00:00", hits=2)
    row["next_review_date"] = "2026-01-01"          # 复核日期也到了
    row["trade_review_due"] = "2026-02-01"          # 关联交易也到期了
    reasons = _review_reasons(row)
    assert reasons[0].startswith("你写下的认错条件被踩到了"), reasons
    assert "2 次" in reasons[0]
    # 别的理由不能被挤掉，只是排在后面
    assert any("复核日期" in r for r in reasons)
    assert any("关联交易" in r for r in reasons)


def test_a_never_reviewed_thesis_is_not_told_about_a_review_that_never_happened():
    """对一条从没复核过的判断说「上次复核后新增 2 条反证」，
    是在说一件没发生过的事，而他会去找那次不存在的复核。"""
    fresh = _review_reasons(_row("A", "2026-01-01T00:00:00", evidence=2))
    assert "上次复核后" not in " ".join(fresh)
    assert "从写下起还没复核过" in " ".join(fresh)

    done = _review_reasons(_row("A", "2026-01-01T00:00:00", evidence=2,
                                reviewed="2026-02-01T00:00:00"))
    assert "上次复核后新增" in " ".join(done)


# ------------------------------------------------------- 真的跑一遍队列，不只是排序键

def test_the_real_queue_puts_the_hit_first(client, owned):  # noqa: F811
    """只断言排序键是不够的：键对了而 review_queue 没用它，表现完全一样。"""
    client.as_user(access.OWNER_SCOPE)
    long_ago = (date.today() - timedelta(days=200)).isoformat()

    stale = client.post(f"/api/v1/companies/{owned['company']}/theses",
                        json={"claim": "放了很久没看的那条",
                              "counter_condition": "毛利率跌破 27%"}).json()
    hit_thesis = client.post(f"/api/v1/companies/{owned['company']}/theses",
                             json={"claim": "刚写下就被踩到的那条",
                                   "counter_condition": "净利率连续两期低于 14%"}).json()
    with connection() as conn:
        # 老的那条：建立时间推到 200 天前，于是它会因为「距建立超过 90 天」进队列
        conn.execute("UPDATE theses SET created_at = ? WHERE id = ?",
                     (long_ago + "T09:00:00", stale["id"]))
        # 命中必须挂在一条真实公告上（event_id 是 NOT NULL 外键）——
        # 这也正是这条链的形状：公告进来 → 撞上你写的条件 → 才有这一行。
        cursor = conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', '2026 年半年度报告', ?, '测试', ?, '已归档')""",
            (owned["company"], date.today().isoformat(), date.today().isoformat()))
        event_id = int(cursor.lastrowid)
        # **百分号要走参数，不能写在 SQL 文本里。** psycopg2 会把 `14%` 里的
        # `%` 当成占位符的开头，然后报 `IndexError: tuple index out of range`——
        # 一个跟百分号毫无关系的错。这个坑本会话踩过一次，这里又踩了一次。
        conn.execute(
            """INSERT INTO counter_hits (user_id, thesis_id, event_id, clause,
                                         reason, acknowledged, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (access.OWNER_SCOPE, hit_thesis["id"], event_id,
             "净利率连续两期低于 14%", "中报净利率 13.2%", date.today().isoformat()))

    queue = review_queue()
    assert len(queue) >= 2, [r["claim"] for r in queue]
    assert queue[0]["thesis_id"] == hit_thesis["id"], (
        "被踩到的那条没排在最前面：" + str([(r["claim"], r["reasons"][0]) for r in queue]))
    assert queue[0]["reasons"][0].startswith("你写下的认错条件被踩到了")
