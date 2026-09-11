"""同行位置：一个数字只有放进它的行业里才有意义。

实测最能说明问题的一例：工商银行市盈率 7.4 倍。绝对值看着极便宜——
放进银行业 42 家的分布里，它排**第 86 分位**，是同行里偏贵的那一头。
只给「PE 7.4」这个数字，一个业余投资者会得出完全相反的结论。

所以这里测的重点不是"能算出分位数"，是那几个会把结论算反的边界：
亏损公司的负 PE、被极端值拉垮的坐标轴、样本太小、行业分类取哪一个。
"""

import pytest

from stock_decision import peers
from stock_decision.database import connection, now_iso


def _seed(rows: list[tuple[str, str, str, float | None, float | None]]) -> None:
    """(代码, 名称, 行业, pe_ttm, roe)"""
    with connection() as conn:
        for symbol, name, industry, pe, roe in rows:
            conn.execute(
                """INSERT INTO market_universe (symbol, name, industry, pe_ttm, pb, roe, gross_margin, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, name, industry, pe, 1.5, roe, 30.0, now_iso()))


# 贴着实测的银行股分布来：p25 5.32 / p50 6.19 / p75 7.02 —— 大多数挤在
# 4.5–7 之间，右边拖一条尾巴。**均匀分布是测不出这件事的**：均匀分布下
# 7.4 落在 57 分位，看起来"中间偏上"，而真实分布下它是第 86 分位。
# 分位数的全部意义就在于分布的形状，用一条直线当样本等于把它抹平了。
_BANK_PES = [4.3, 4.6, 4.8, 5.0, 5.2, 5.3, 5.5, 5.7, 5.9, 6.1,
             6.2, 6.3, 6.5, 6.6, 6.8, 6.9, 7.0, 7.1, 8.9, 11.2]


def _bank_field(count: int) -> list[tuple]:
    return [(f"6001{i:02d}", f"银行{i}", "银行Ⅱ", _BANK_PES[i % len(_BANK_PES)], 10.0 + i * 0.1)
            for i in range(count)]


def test_a_cheap_looking_number_can_be_expensive_among_peers():
    """整个模块存在的理由。7.4 倍在银行里是贵的一头。"""
    _seed(_bank_field(20))                       # PE 5.0 … 8.8
    _seed([("601398", "工商银行", "银行Ⅱ", 7.4, 2.2)])

    result = peers.position({"symbol": "601398", "industry": "货币金融服务"})
    pe = next(m for m in result["metrics"] if m["key"] == "pe_ttm")

    # 绝对值看着极便宜，在同行里却是偏贵的那一头 —— 这就是整个模块的用处
    assert pe["percentile"] >= 85, f"7.4 倍在银行里是贵的一头，实得第 {pe['percentile']} 分位"
    assert pe["p50"] < pe["value"]


def test_the_industry_comes_from_the_universe_not_the_file():
    """比较对象取全市场底座的分类，不是档案里自己填的那个。

    档案里写的是「货币金融服务」（证监会门类），底座里是「银行Ⅱ」（更细）。
    用档案里那个，同行会混进保险和券商——比出来的分位是错的。
    """
    _seed(_bank_field(20))
    _seed([("601398", "工商银行", "银行Ⅱ", 7.4, 2.2)])

    result = peers.position({"symbol": "601398", "industry": "货币金融服务"})

    assert result["industry"] == "银行Ⅱ"


def test_loss_makers_are_dropped_not_counted_as_zero():
    """负市盈率没有「低」的含义，混进分布会把中位数整个拉偏。"""
    _seed(_bank_field(20))
    _seed([(f"6009{i:02d}", f"亏损{i}", "银行Ⅱ", -30.0, -5.0) for i in range(10)])
    _seed([("601398", "工商银行", "银行Ⅱ", 7.4, 2.2)])

    result = peers.position({"symbol": "601398", "industry": "货币金融服务"})
    pe = next(m for m in result["metrics"] if m["key"] == "pe_ttm")

    assert pe["p10"] > 0, "分布里混进了负的市盈率"
    assert pe["sample"] == 21, "亏损公司应当被排除在市盈率分布之外"


def test_a_metric_with_no_data_is_left_out_entirely():
    """银行没有毛利率。整行不画，而不是画一行空的。

    画一行空的会让人以为「这家公司毛利率很低」，而事实是这个科目对它不存在。
    """
    with connection() as conn:
        for i in range(20):
            conn.execute(
                """INSERT INTO market_universe (symbol, name, industry, pe_ttm, pb, roe, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (f"6001{i:02d}", f"银行{i}", "银行Ⅱ", 5.0 + i * 0.2, 0.6, 10.0, now_iso()))

    result = peers.position({"symbol": "600100", "industry": "银行Ⅱ"})

    assert "gross_margin" not in {m["key"] for m in result["metrics"]}


def test_too_few_peers_means_no_chart():
    """三家公司的「第 75 分位」不是一个有意义的说法。"""
    _seed([("600001", "甲", "冷门行业", 10.0, 12.0),
           ("600002", "乙", "冷门行业", 12.0, 13.0),
           ("600003", "丙", "冷门行业", 14.0, 14.0)])

    result = peers.position({"symbol": "600001", "industry": "冷门行业"})

    assert result["metrics"] == []
    assert "不足" in result["note"]


def test_a_company_outside_the_universe_says_so():
    """底座里没有这家公司时要说清楚该去做什么，而不是给一张空图。"""
    result = peers.position({"symbol": "999999", "industry": ""})

    assert result["metrics"] == []
    assert "同步" in result["note"]


@pytest.mark.parametrize("fraction,expected", [(0.0, 1.0), (0.5, 3.0), (1.0, 5.0), (0.25, 2.0)])
def test_quantile_interpolates(fraction: float, expected: float):
    assert peers._quantile([1.0, 2.0, 3.0, 4.0, 5.0], fraction) == expected
