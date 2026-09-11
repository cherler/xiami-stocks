"""认错条件得有人拿事实去撞它，而且「没撞过」不许长得像「撞过了没事」。

2026-08-14 线上实测（真实账号）：3 条投资逻辑**全都写了**认错条件、
收件箱里 40 条公告待核验、反证命中 **0**。四十条公告和三条认错条件在库里躺着，
从来没有被放在一起看过一眼 —— 因为比对既没有调度任务，唯一的入口又是
首页一个**默认折叠**的分区里的文字按钮（折叠时连 children 都不渲染）。

而页面上那个「0」读起来是"查过了，没事"。这比不做还糟：它给的是假的安心。

这个文件守两件事：

  · 比对**在调度器里有位置**，而且逐用户跑、各扣各的账、默认不擅自花钱
  · 「还有多少条没比对过」是一个**独立的数**，不跟命中数混在一起
"""

import pytest

from stock_decision import access, scheduler
from stock_decision.database import connection
from stock_decision.repository import uncompared_counter_events

from test_idor import client, owned  # noqa: F401


def test_the_comparison_has_a_place_in_the_scheduler():
    """**不在调度器里 = 只有人想起来才会发生**，而这个机制专治想不起来。"""
    job = scheduler.JOBS_BY_ID.get("counter_match")
    assert job is not None, "认错条件比对没有排期，它就只会在你手动点的时候发生"
    # 排在 profile（新公告落地）之后才有意义 —— 公告刚进来，正是该撞一次的时刻。
    order = [j.job_id for j in scheduler.JOBS]
    assert order.index("counter_match") > order.index("profile")


def test_it_does_not_spend_anyone_credits_without_being_asked(monkeypatch):
    """比对要过模型。**没人勾过就一分钱都不许花** ——
    用户第二天看到余额少一截而昨天什么都没做，那不是记错账，是没打招呼。"""
    called: list[str] = []
    monkeypatch.setattr(scheduler, "background_ai_enabled", lambda: False)
    monkeypatch.setattr("stock_decision.repository.check_counter_hits",
                        lambda *a, **k: called.append("跑了") or {})

    result = scheduler._run_counter_match()
    assert called == [], "没人开后台比对，却还是跑了模型"
    assert "没开" in result["detail"], "没跑就要说清楚为什么没跑"


def test_never_compared_does_not_look_like_nothing_found(client, owned):  # noqa: F811
    """**0 有两种意思，界面上不能只有一个数。**

    比过了没事 → 好消息；压根没比过 → 你以为有人在盯，其实没有。
    """
    client.as_user(access.OWNER_SCOPE)
    # 写一条带认错条件的判断 + 一条待核验公告
    client.post(f"/api/v1/companies/{owned['company']}/theses",
                json={"claim": "赌定价权还在", "counter_condition": "2026 年中报毛利率跌破 27%"})
    with connection() as conn:
        conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', '一条还没人看过的公告', '2026-08-14', '测试', '2026-08-14', '待核验')""",
            (owned["company"],))

    assert uncompared_counter_events() >= 1, "没比对过的公告要被数出来，不能沉默"

    summary = client.get("/api/v1/dashboard").json()
    assert summary["counter_uncompared"] >= 1
    # 两个数必须分开给：合并成一个的话，这一条就白写了
    assert "counter_hits" in summary and "counter_uncompared" in summary


def test_without_any_counter_condition_the_number_is_zero(client, owned):  # noqa: F811
    """一条认错条件都没写的时候报 0 —— 报 40 是吓人，而且他也无从下手。"""
    client.as_user(access.OWNER_SCOPE)
    with connection() as conn:
        conn.execute("UPDATE theses SET counter_condition = ''")
        conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', '公告', '2026-08-14', '测试', '2026-08-14', '待核验')""",
            (owned["company"],))
    assert uncompared_counter_events() == 0


# ------------------------------------- 认错条件：允许空着写下，但不许沉默
#
# 产品里只有这一条硬规矩（quick.py：「那不是少填一栏，是这条记录作废」），
# 而它此前只拦在三个门里的一个：
#
#     POST /quick-thesis                 走 quick.validate  ✓ 拦
#     POST /companies/{id}/theses        schema 默认空串    ✗ 不拦
#     POST /companies/{id}/thesis-write  模型给什么存什么   ✗ 不拦
#
# **修法不是三个门都硬拦。** 硬拦会逼出一句敷衍的条件，而假条件比空条件更糟：
# 空的是诚实的空白，数得出来、提示得了；一句「基本面恶化」看起来已经有人盯着，
# 实际同样永远不会触发，而且再也没人会去补。
#
# 所以：空着能写，但**不许沉默** —— 数出来，摆在首页。
# 清空已有的那一条另说：那是把一条已经在网里的记录拿出来作废。


def test_writing_one_without_a_counter_condition_is_allowed(client, owned):  # noqa: F811
    """先把想法落下来 —— 降摩擦跟 quick.py 那套是同一个道理。"""
    client.as_user(access.OWNER_SCOPE)
    r = client.post(f"/api/v1/companies/{owned['company']}/theses",
                    json={"claim": "赌它便宜"})
    assert r.status_code == 201


def test_but_it_is_not_allowed_to_stay_quiet(client, owned):  # noqa: F811
    """**这才是真正的修复**：没写条件的那几条不在网里，而这件事得有人说。"""
    from stock_decision.repository import theses_missing_counter

    client.as_user(access.OWNER_SCOPE)
    client.post(f"/api/v1/companies/{owned['company']}/theses", json={"claim": "赌它便宜"})
    assert theses_missing_counter() >= 1
    assert client.get("/api/v1/dashboard").json()["theses_without_counter"] >= 1


def test_an_existing_condition_cannot_be_wiped(client, owned):  # noqa: F811
    """清空 ≠ 没写。清空是把一条已经在网里的记录拿出来作废，而且作废得悄无声息。
    要作废该改状态（已破坏），不是抹掉条件。"""
    client.as_user(access.OWNER_SCOPE)
    thesis = client.post(f"/api/v1/companies/{owned['company']}/theses",
                         json={"claim": "赌它便宜", "counter_condition": "毛利率跌破 27%"}).json()
    r = client.patch(f"/api/v1/theses/{thesis['id']}", json={"counter_condition": "   "})
    assert r.status_code == 422
    assert "认错条件" in r.text


def test_the_thirty_second_path_still_refuses(client, owned):  # noqa: F811
    """30 秒那条路仍然硬拦 —— 那条路的全部意义就是这三句话。"""
    client.as_user(access.OWNER_SCOPE)
    r = client.post("/api/v1/quick-thesis",
                    json={"symbol": "600519", "claim": "赌它便宜", "counter_condition": ""})
    assert r.status_code == 400 and "认错条件" in r.text
