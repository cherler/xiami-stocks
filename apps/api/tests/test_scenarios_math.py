"""三情景估值的算术：**反推必须是正算的精确逆。**

## 为什么单挑这一条来守

这一页最值钱的数字是「当前价格要求这家公司未来五年收入年增多少」。
它被摆在三个情景**前面**，因为它不含预测成分 —— 也正因为如此，
它错了没有任何东西会响：三个情景是你自己填的假设，你对不上会怀疑自己填错了；
而这个数是算出来的，你只会当它是事实。

`implied_growth` 是把 `value_of` 反过来解。中间隔着两个幂运算
（`(1+g)^n` 与 `(1+r)^n`）和三个乘除。任何一处指数写反、分子分母调换，
算出来仍然是一个**长得很合理的百分数** —— 12.4% 和 8.7% 在页面上没有区别。

## 2026-08-16 审这个模块时的实测

手工验了五组参数的往返，全部吻合；又拿线上真数据复算了两家的历史 CAGR
（茅台 2020→2025 收入 11.92%、格力 0.07%），跟代码给的一致。

**但那次是手算的，没有留下任何会响的东西。** 这个文件就是把那次验证沉淀下来：
下一个人改公式时，往返对不上会当场红。

（`scenarios.py` 244 行，此前测试里只被提到 4 次 —— 是全仓测试最薄的几个之一。）
"""

import pytest

from stock_decision import scenarios as sc


def _round_trip(growth: float, margin: float, exit_pe: float,
                years: int = 5, discount: float = 10.0):
    """设一个增速 → 算出每股价值 → 把那个价值当成价格反推 → 应该回到原增速。"""
    scenario = sc.Scenario(key="base", revenue_growth=growth,
                           net_margin=margin, exit_pe=exit_pe)
    value = sc.value_of(scenario, 1.0e11, 1.0e9, years, discount)
    back = sc.implied_growth(value["per_share"], 1.0e11, 1.0e9,
                             margin, exit_pe, years, discount)
    return value["per_share"], back


@pytest.mark.parametrize("growth,margin,exit_pe", [
    (12.0, 15.0, 18.0),
    (25.0, 30.0, 40.0),
    (-5.0, 8.0, 12.0),     # 负增长也要能往返 —— 收缩的公司照样要算得出来
    (0.0, 20.0, 25.0),
    (8.0, 12.5, 22.0),
    (3.5, 47.9, 19.0),     # 茅台那种高净利率
    (14.6, 16.9, 7.7),     # 格力那种低 PE
])
def test_the_implied_growth_is_the_exact_inverse(growth, margin, exit_pe):
    """**这一条是要害。** 差一个指数、调换一次分子分母，
    算出来仍然是个长得很合理的百分数，而页面上看不出区别。"""
    per_share, back = _round_trip(growth, margin, exit_pe)
    assert per_share is not None and back is not None
    assert abs(back - growth) < 0.05, (
        f"设增速 {growth}% 算出每股 {per_share}，把它当价格反推得到 {back}% —— "
        f"正算与反推对不上，两者之间有一处不是互逆的。")


@pytest.mark.parametrize("years", [1, 3, 5, 10])
@pytest.mark.parametrize("discount", [0.0, 5.0, 10.0, 15.0])
def test_it_stays_inverse_across_years_and_discount_rates(years, discount):
    """年限和折现率都是用户可改的。**改了之后仍然要互逆** ——
    只在默认的 5 年 10% 上对得上是不够的。"""
    _, back = _round_trip(11.0, 18.0, 20.0, years=years, discount=discount)
    assert back is not None and abs(back - 11.0) < 0.05, (
        f"{years} 年 / 折现 {discount}% 时反推得到 {back}%，应当是 11.0%")


def test_a_higher_required_return_demands_faster_growth():
    """折现率是「我要求每年赚多少」。要求得越高，同一个价格就要求越快的增长。

    **方向反了的话，页面上会把一个苛刻的要求显示成宽松的** —— 而这个数
    正是用来跟历史实际增速对照的，方向错了结论就整个反过来。
    """
    price = _round_trip(10.0, 15.0, 20.0)[0]
    lax = sc.implied_growth(price, 1.0e11, 1.0e9, 15.0, 20.0, 5, 5.0)
    strict = sc.implied_growth(price, 1.0e11, 1.0e9, 15.0, 20.0, 5, 15.0)
    assert lax < strict, f"折现 5% 要求 {lax}%、15% 要求 {strict}% —— 方向反了"


def test_a_richer_price_demands_faster_growth():
    """价格越高，要求的增速越高。这是这个数唯一的用法，方向不能错。"""
    cheap = sc.implied_growth(100.0, 1.0e11, 1.0e9, 15.0, 20.0, 5, 10.0)
    dear = sc.implied_growth(300.0, 1.0e11, 1.0e9, 15.0, 20.0, 5, 10.0)
    assert cheap < dear


@pytest.mark.parametrize("bad", [
    {"price": 0.0}, {"price": -1.0}, {"net_margin": 0.0}, {"net_margin": -3.0},
    {"exit_pe": 0.0}, {"exit_pe": -8.0}, {"years": 0}, {"shares": 0.0},
])
def test_nonsense_inputs_return_nothing_rather_than_a_number(bad):
    """**算不出来就不要给数。**

    净利率为负、退出 PE 为负、股本为零 —— 这些情况下硬算得出来的那个百分数
    没有任何含义，而它会被摆在「市场要求的增速」那个位置上当成事实读。
    """
    args = {"price": 200.0, "base_revenue": 1.0e11, "shares": 1.0e9,
            "net_margin": 15.0, "exit_pe": 20.0, "years": 5, "discount_rate": 10.0}
    args.update(bad)
    assert sc.implied_growth(**args) is None, f"{bad} 时不该给出一个数"


# ------------------------------------------------------------------ 历史实际值

def _annual(revenues: list[tuple[str, float, float]]):
    return [{"report_date": d, "revenue": r, "net_profit": p} for d, r, p in revenues]


def test_the_cagr_matches_hand_arithmetic():
    """2026-08-16 拿线上真数据手算过：茅台 2020→2025 收入 CAGR 11.92%。
    这里用同一组数字钉住 —— 手算那次没留下任何会响的东西。"""
    periods = _annual([
        ("2020-12-31", 97993240501.21, 46697285429.81),
        ("2021-12-31", 109464278563.89, 52460144378.16),
        ("2022-12-31", 127553959355.97, 62717467870.12),
        ("2023-12-31", 150560330316.45, 74734071550.75),
        ("2024-12-31", 174144069958.25, 86228146421.62),
        ("2025-12-31", 172054171890.91, 82320067101.68),
    ])
    history = sc.annual_history(periods)
    assert history["cagr_5y"] == 11.92
    assert history["growth_worst"] == -1.2, "最差的那一年要如实报出来，它是悲观情景的种子"


def test_a_flat_five_years_is_not_dressed_up():
    """格力 2020→2025 收入几乎没长（实测 0.07%）。

    **这个数必须如实是 0.07**：它旁边就是「当前价格要求 14.62%」，
    两个数摆在一起才是这一页的全部意义。把它算大一点，那个对照就没了。
    """
    periods = _annual([
        ("2020-12-31", 170497415702.41, 22175108137.32),
        ("2021-12-31", 189654033523.50, 23063732372.62),
        ("2022-12-31", 190150672542.13, 24506623782.46),
        ("2023-12-31", 205018123834.21, 29017387604.18),
        ("2024-12-31", 190038071604.78, 32184570372.28),
        ("2025-12-31", 171118161275.41, 29003103411.66),
    ])
    history = sc.annual_history(periods)
    assert history["cagr_5y"] == 0.07
    assert history["cagr_3y"] == -3.45, "三年是负的，也要如实说"


def test_quarterly_reports_never_leak_into_the_growth_numbers():
    """混进季报的话，增速会变成「一季报比上一年年报」——
    那是个没有意义的数，而它**看起来跟年度增速一模一样**。"""
    periods = _annual([
        ("2024-12-31", 100.0, 10.0),
        ("2025-03-31", 28.0, 3.0),      # 一季报，不许进
        ("2025-06-30", 60.0, 6.0),      # 中报，不许进
        ("2025-12-31", 110.0, 11.0),
    ])
    history = sc.annual_history(periods)
    assert [row["report_date"] for row in history["years"]] == ["2024-12-31", "2025-12-31"]
    assert history["yearly_growth"] == [10.0]
