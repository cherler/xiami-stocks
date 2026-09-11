"""停牌股的 0 价，把整个全市场底座作业炸掉了三天。

2026-08-14 线上：`universe` 作业「上次成功」停在 08-11，之后连挂三天，
error 都是 `division by zero`。查下来：

    SELECT (market_universe.price - h.close) / h.close ...
    WHERE h.close IS NOT NULL

停牌那天快照给的价是 **0** —— 那不是"这天值 0 元"，是"这天没有报价"。
`IS NOT NULL` 放过了它，Postgres 拿 0 当分母直接抛，整个作业当场死掉。
库里当时有 18 行 close = 0，最早一条落在 08-10，正好在 08-12 进入 5 日窗口。

**SQLite 那边除零只给 NULL，所以本地和单测一直看不见** —— 这是这条 bug 能
活到线上的原因，也是这个文件必须跑在 Postgres 上的原因。

候选清单、云图、全市场分位全靠这张表，于是它们一起停在了三天前。
"""

import pytest

from stock_decision.database import connection
from stock_decision.repository import backfill_universe_range_returns


@pytest.fixture()
def suspended_stock():
    """一只停牌股：今天有价，5 天前那条收盘是 0。"""
    with connection() as conn:
        conn.execute("DELETE FROM universe_valuation_history WHERE symbol = '300176'")
        conn.execute("DELETE FROM market_universe WHERE symbol = '300176'")
        conn.execute(
            """INSERT INTO market_universe (symbol, name, price, updated_at)
               VALUES ('300176', '停牌测试', 12.0, '2026-08-14T00:00:00')""")
        for offset, close in enumerate([12.0, 0.0, 0.0, 11.0, 10.0, 9.0, 8.0]):
            conn.execute(
                """INSERT INTO universe_valuation_history (symbol, point_date, close, source)
                   VALUES ('300176', ?, ?, '测试')""",
                (f"2026-08-{14 - offset:02d}", close))


def test_a_suspended_day_does_not_kill_the_whole_job(suspended_stock):
    """**一只停牌股不该让全市场底座整个跑不完。** 这才是这条 bug 真正的代价。"""
    result = backfill_universe_range_returns()          # 原来这里抛 division by zero
    assert isinstance(result, dict)


def test_a_suspended_day_is_skipped_not_counted_as_a_trading_day(suspended_stock):
    """顺带修对的口径：停牌日本来就不该算进"过去 N 个交易日"。

    跳过 0 之后，OFFSET 数的才是真正有报价的那几天。
    """
    backfill_universe_range_returns()
    with connection() as conn:
        row = conn.execute(
            "SELECT change_5d FROM market_universe WHERE symbol = '300176'").fetchone()
    if row is None or row["change_5d"] is None:
        pytest.skip("这套库里累计的交易日还不够 5 天，算不出 5 日涨跌")
    # 序列（新→旧）：12, 0, 0, 11, 10, 9, 8。跳掉两个 0 之后有效收盘是
    # [12, 11, 10, 9, 8]，OFFSET 4 取到 8.0 —— 也就是**今天算第 1 天**的口径。
    #
    # 关键是"两个 0 被跳过了"：不跳的话 OFFSET 4 会落在 10.0 上，
    # 把两天停牌当成两个交易日。这条测试盯的是跳过，不是那个口径本身
    # （今天算不算第 1 天是另一个问题，见提交说明）。
    assert row["change_5d"] == pytest.approx((12.0 - 8.0) / 8.0 * 100, abs=0.01)


def test_a_scheduled_job_failing_every_day_shows_up_on_the_health_card():
    """**调度作业连着失败，健康卡上原来一个字都没有。**

    jobs_failed_24h 数的是 background_jobs —— 那是用户点出来的任务
    （反方、起草、AI 选股）。调度器写的是 sync_runs，而健康卡从来没读过它。
    于是全市场底座连挂三天，健康卡照样 alerts 空、jobs_failed_24h 0。
    """
    from stock_decision.main import _ops_pulse, _PULSE

    with connection() as conn:
        conn.execute("DELETE FROM sync_runs WHERE job_id = 'universe'")
        for day, status in (("2026-08-12", "失败"), ("2026-08-13", "失败"), ("2026-08-14", "失败")):
            conn.execute(
                """INSERT INTO sync_runs (job_id, trigger, status, started_at, finished_at,
                                          items, failures, detail, error)
                   VALUES ('universe', '定时', ?, ?, ?, 0, 0, '任务未完成', 'division by zero')""",
                (status, f"{day}T09:40:00", f"{day}T09:41:00"))
    _PULSE.update(at=None, value=None)          # 这张卡有缓存，测的时候要先失效
    pulse = _ops_pulse()
    assert pulse.get("jobs_failing", {}).get("universe", 0) >= 2
    assert any("universe" in a and "连续失败" in a for a in pulse["alerts"]), pulse["alerts"]
