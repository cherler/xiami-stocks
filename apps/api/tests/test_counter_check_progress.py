"""比对完得留痕，否则它每天重比同一批、每天烧一次积分，而进度是零。

2026-08-15 线上端到端走这条链，断在这一环：

    ③ 撞认错条件 → 「比对了 40 条公告，0 条命中反证」
    ⑤ 提醒       → 「还有 103 条没比对过」   ← 一条没减

因为"比过没比过"原来是看它**在不在 counter_hits 里**，而只有**命中**才会落一行。
比完 0 命中的那 40 条，在库里跟没比过一模一样。两个后果：

  · 页面上那个数永远不减（点多少次都是 103）
  · 定时任务每天拿同一批 40 条重跑，**每天真金白银烧一次积分**，永不收敛

命中与否是结论，比没比过是事实 —— 两件事不能共用一个存放处。
"""

import pytest

from stock_decision import access
from stock_decision.database import connection
from stock_decision.repository import (check_counter_hits, uncompared_counter_events)

from test_idor import client, owned  # noqa: F401


@pytest.fixture()
def one_pending(client, owned, monkeypatch):  # noqa: F811
    """一条带认错条件的判断 + 一条待核验公告，且模型判为不命中。"""
    from stock_decision import counters

    client.as_user(access.OWNER_SCOPE)
    client.post(f"/api/v1/companies/{owned['company']}/theses", json={
        "claim": "赌定价权还在", "counter_condition": "毛利率跌破 27%"})
    with connection() as conn:
        conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', ?, '2026-08-15', '测试', '2026-08-15', '待核验')""",
            (owned["company"], "一条跟毛利率无关的公告"))
    monkeypatch.setattr(counters, "find_hits", lambda *a, **k: [])   # 比了，但没命中


def test_a_compared_announcement_stops_being_counted_as_uncompared(one_pending):
    """**这条是那个死循环的闸。** 比过就得算比过，哪怕一条都没命中。"""
    before = uncompared_counter_events()
    assert before >= 1
    result = check_counter_hits()
    assert result["checked"] >= 1 and result["hits"] == 0
    assert uncompared_counter_events() < before, "比完了，那个数一点没动"


def test_the_second_run_has_nothing_left_to_do(one_pending):
    """跑第二遍不该再花钱 —— 原来它会把同一批再比一次，天天如此。"""
    check_counter_hits()
    again = check_counter_hits()
    assert again["checked"] == 0, "同一批公告被重比了一次，每天一次就是每天一笔钱"


def test_a_new_counter_condition_puts_them_back_in_the_queue(client, owned, one_pending):  # noqa: F811
    """写下**新的**认错条件时要重新排队。

    不然新条件只对以后的公告生效 —— 而你写下它的那一刻，脑子里想的恰恰是
    "库里那些我还没细看的公告，有没有已经踩到它"。
    """
    check_counter_hits()
    assert uncompared_counter_events() == 0
    client.as_user(access.OWNER_SCOPE)
    client.post(f"/api/v1/companies/{owned['company']}/theses", json={
        "claim": "再赌一条", "counter_condition": "前五大客户集中度高于 85%"})
    assert uncompared_counter_events() >= 1, "新条件写下了，旧公告却不会拿去撞它"


def test_one_company_failing_does_not_discard_the_others(client, owned, monkeypatch):  # noqa: F811
    """**一家超时，不能把另外几家已经花钱比完的结果一起作废。**

    线上实测：三家公司三次模型调用，第三次读超时 —— 整个函数抛出去，
    前两家已经扣过的 2 分白花，连戳都没打上，下一轮再花一次同样的钱。
    """
    from stock_decision import counters
    from stock_decision.repository import check_counter_hits, uncompared_counter_events

    client.as_user(access.OWNER_SCOPE)
    second = client.post("/api/v1/companies", json={
        "symbol": "000651", "name": "第二家", "industry": "白电"}).json()
    for cid in (owned["company"], second["id"]):
        client.post(f"/api/v1/companies/{cid}/theses", json={
            "claim": "赌一条", "counter_condition": "毛利率跌破 27%"})
        with connection() as conn:
            conn.execute(
                """INSERT INTO company_calendar_events
                   (company_id, category, title, event_date, source, refreshed_at, inbox_status)
                   VALUES (?, '公告', ?, '2026-08-15', '测试', '2026-08-15', '待核验')""",
                (cid, "一条公告"))

    seen: list[int] = []

    def flaky(events, theses, **kwargs):
        seen.append(events[0]["company_id"])
        if len(seen) > 1:                      # 第二家超时
            raise RuntimeError("The read operation timed out")
        return []

    monkeypatch.setattr(counters, "find_hits", flaky)
    before = uncompared_counter_events()
    result = check_counter_hits()

    assert result["failures"] == 1
    assert result["checked"] >= 1, "成功的那家也被一起抛掉了"
    assert uncompared_counter_events() < before, "成功的那家没打上戳，下轮还要再花一次钱"
    assert "没跑成" in result["note"], "失败了要说出来"


# ------------------------------------------ 链的最后一环：命中要能推动复核

def test_a_hit_puts_the_thesis_into_the_review_queue(client, owned):  # noqa: F811
    """**这是这条链的最后一环，原来是断的。**

    2026-08-15 线上端到端：公告进来 → 撞上写下的条件 → 横幅提醒 →
    点「我处理过了」→ **然后没有然后**。复核队列的到期理由只看 evidences
    和 research_events，counter_hits 一次都没出现。

    而"你说会证明你错的那件事真的发生了"，恰恰是最该让人坐下来重新判一次的理由 ——
    也是这个产品唯一不可替代的那件事。
    """
    from stock_decision.repository import review_queue

    client.as_user(access.OWNER_SCOPE)
    thesis = client.post(f"/api/v1/companies/{owned['company']}/theses", json={
        "claim": "赌一条", "counter_condition": "毛利率跌破 27%"}).json()
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', ?, '2026-08-15', '测试', '2026-08-15', '待核验')""",
            (owned["company"], "毛利率降到 26.4%"))
        conn.execute(
            """INSERT INTO counter_hits (user_id, event_id, thesis_id, clause, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (access.OWNER_SCOPE, int(cur.lastrowid), thesis["id"],
             "毛利率跌破 27%", "公告里写了 26.4%", "2026-08-15T10:00:00"))

    rows = [r for r in review_queue() if r["thesis_id"] == thesis["id"]]
    assert rows, "认错条件被踩到了，这条判断却没进复核队列"
    assert any("认错条件被踩到" in reason for reason in rows[0]["reasons"]), rows[0]["reasons"]


def test_acknowledging_does_not_dismiss_the_review(client, owned):  # noqa: F811
    """**确认清掉的是横幅，不是这件事本身。**

    如果点一下「我处理过了」就能让它从复核队列里消失，那个按钮就成了
    一键免除义务 —— 而它旁边那句提醒的全部价值就在于绕不开。
    """
    from stock_decision.repository import review_queue

    client.as_user(access.OWNER_SCOPE)
    thesis = client.post(f"/api/v1/companies/{owned['company']}/theses", json={
        "claim": "赌一条", "counter_condition": "毛利率跌破 27%"}).json()
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', ?, '2026-08-15', '测试', '2026-08-15', '待核验')""",
            (owned["company"], "毛利率降到 26.4%"))
        conn.execute(
            """INSERT INTO counter_hits (user_id, event_id, thesis_id, clause, reason, created_at, acknowledged)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (access.OWNER_SCOPE, int(cur.lastrowid), thesis["id"],
             "毛利率跌破 27%", "公告里写了 26.4%", "2026-08-15T10:00:00"))

    rows = [r for r in review_queue() if r["thesis_id"] == thesis["id"]]
    assert rows and any("认错条件被踩到" in r for r in rows[0]["reasons"]), \
        "点过确认就不用复核了 —— 那个按钮成了一键免除义务"
