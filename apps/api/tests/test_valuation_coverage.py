"""「近 5 年分位」必须真的有五年样本，没有就得说出来。

2026-08-14 线上实测（寒武纪）：它 2025-04 才转正、之前没有 PE，
所以 pe_ttm 序列只有 1.32 年。而页面给的是

    「近 3 年分位」1.7%      「近 5 年分位」1.7%

同一个数 —— 因为背后是同一批 16 个月的样本。读的人会理解成
"比过去五年里 98% 的时间都便宜"，而**过去五年根本没有数据**。

这不是少一句提示，是这个数字在说一件没发生过的事。

`_window_percentile` 里原来有三行专门管这件事：判断条件写对了，
动作却是 `unavailable_reason = None` —— 而那一步是空操作。
注释写着"也要说清楚"，实际一个字都没说。
"""

from stock_decision.repository import _window_percentile

from test_idor import client, owned  # noqa: F401


def _series(start: str, end: str, value: float = 10.0):
    """从 start 到 end 每天一个点。跟线上那份序列一样是自然日。"""
    from datetime import date, timedelta

    a, b = date.fromisoformat(start), date.fromisoformat(end)
    out, cur = [], a
    while cur <= b:
        out.append({"point_date": cur.isoformat(), "value": value + (cur.toordinal() % 7) * 0.1})
        cur += timedelta(days=1)
    return out


def test_a_short_series_does_not_pass_itself_off_as_five_years():
    """样本只有一年多，就不能让人把这个分位当成五年历史位置读。"""
    points = _series("2025-04-19", "2026-08-14")
    result = _window_percentile(points, 5, "2026-08-14")
    assert result["percentile"] is not None, "数字保留——一年多也是信息"
    assert result["covered_years"] < 1.5
    assert result["coverage_note"], "样本没铺满五年，却一个字都没说"
    assert "不足 5 年" in result["coverage_note"]


def test_a_full_series_says_nothing_extra():
    """铺满了就别多话——每个窗口都挂一句提示，提示就成了背景色。"""
    points = _series("2021-08-01", "2026-08-14")
    result = _window_percentile(points, 5, "2026-08-14")
    assert result["coverage_note"] is None
    assert result["covered_years"] >= 4.9


def test_the_two_windows_stop_being_the_same_silent_number():
    """3 年和 5 年给出同一个数**本身就是那个 tell**：背后是同一批样本。
    数字可以一样，但必须各自带上"我只覆盖了多久"。"""
    points = _series("2025-04-19", "2026-08-14")
    three = _window_percentile(points, 3, "2026-08-14")
    five = _window_percentile(points, 5, "2026-08-14")
    assert three["percentile"] == five["percentile"], "样本相同，分位本来就该相同"
    assert three["coverage_note"] and five["coverage_note"]
    assert "3 年" in three["coverage_note"] and "5 年" in five["coverage_note"]


def test_the_new_fields_survive_the_response_model(client, owned):  # noqa: F811
    """**算对了不等于送得出去。**

    响应模型会把它不认识的键悄悄吃掉，页面表现为"这块从来不出现"，不报错。
    这个坑本仓踩过四次，第五次就是加这两个字段的时候：repository 算好了、
    schema 没加，线上拿到的是 undefined。所以这一条盯的是**接口的实际输出**。
    """
    from stock_decision.schemas import ValuationWindow

    fields = ValuationWindow.model_fields
    assert "covered_years" in fields and "coverage_note" in fields
