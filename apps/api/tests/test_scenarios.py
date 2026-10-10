"""三情景估值的算术。

打分那一层还能靠"看着合理"糊过去，估值不行：**它算出来的每股价值会被当成钱**。
所以这里守两类东西——

1. 算术本身对不对（正推与反推必须能对上）
2. 那些"看起来只是默认值"的选择：默认值编不编、样本不够时是不是宁可不给

第 2 类比第 1 类更容易出事。一组编出来的默认假设看起来很专业，
而它会被当成基准——这是这套东西最危险的失败方式，而且没有任何报错。
"""

import pytest

from stock_decision import scenarios as S


def _scenario(key="base", growth=10.0, margin=20.0, pe=15.0) -> S.Scenario:
    return S.Scenario(key, revenue_growth=growth, net_margin=margin, exit_pe=pe)


def _years(rows):
    """rows = [(报告期, 收入, 净利)]"""
    return [{"report_date": d, "revenue": r, "net_profit": p} for d, r, p in rows]


# ------------------------------------------------------------------ 算术

def test_forward_and_reverse_agree():
    """**正推与反推必须严格互逆。**

    正推：假设 → 每股价值。反推：价格 → 隐含增速。
    把正推算出的每股价值当成价格喂回反推，必须还原出原来的增速。
    对不上就说明两边有一边写错了，而这种错**不会报错**，只会给出一个
    看起来很正常的数字。
    """
    base_revenue, shares, years, discount = 1_000_000_000.0, 100_000_000.0, 5, 10.0
    for growth in (-5.0, 0.0, 8.0, 25.0):
        scenario = _scenario(growth=growth, margin=20.0, pe=15.0)
        per_share = S.value_of(scenario, base_revenue, shares, years, discount)["per_share"]
        back = S.implied_growth(per_share, base_revenue, shares,
                                scenario.net_margin, scenario.exit_pe, years, discount)
        assert back == pytest.approx(growth, abs=0.05), f"增速 {growth}% 反推不回来"


def test_value_moves_the_way_the_assumptions_do():
    args = (1e9, 1e8, 5, 10.0)
    faster = S.value_of(_scenario(growth=15.0), *args)["per_share"]
    slower = S.value_of(_scenario(growth=5.0), *args)["per_share"]
    assert faster > slower
    richer = S.value_of(_scenario(pe=20.0), *args)["per_share"]
    cheaper = S.value_of(_scenario(pe=10.0), *args)["per_share"]
    assert richer > cheaper
    # 折现率越高，今天愿意付的越少
    demanding = S.value_of(_scenario(), 1e9, 1e8, 5, 20.0)["per_share"]
    relaxed = S.value_of(_scenario(), 1e9, 1e8, 5, 5.0)["per_share"]
    assert demanding < relaxed


def test_degenerate_inputs_return_none_not_zero():
    """算不出来要给 None。**给 0 会被读成「一文不值」**，那是一句很重的结论。"""
    assert S.value_of(_scenario(), 0, 1e8, 5, 10.0)["per_share"] is None
    assert S.value_of(_scenario(), 1e9, 0, 5, 10.0)["per_share"] is None
    assert S.implied_growth(0, 1e9, 1e8, 20.0, 15.0, 5, 10.0) is None
    assert S.implied_growth(50, 1e9, 1e8, 0, 15.0, 5, 10.0) is None
    assert S.implied_growth(50, 1e9, 1e8, 20.0, 0, 5, 10.0) is None


# ------------------------------------------------------------------ 历史

def test_history_ignores_quarterly_reports():
    """只用年报。

    混进季报的话，增速会变成「一季报比上一年年报」——那是个没有意义的数，
    而它看起来跟年度增速一模一样。
    """
    rows = _years([("2024-12-31", 100.0, 20.0), ("2025-03-31", 30.0, 6.0),
                   ("2025-12-31", 110.0, 22.0)])
    history = S.annual_history(rows)
    assert [y["report_date"] for y in history["years"]] == ["2024-12-31", "2025-12-31"]
    assert history["yearly_growth"] == [10.0]


def test_cagr_refuses_to_use_a_shorter_span():
    """样本不够就返回 None，不用更短的年数凑。

    「三年增速」和「五年增速」在周期股上能差出一倍，标错了比没有更糟。
    """
    rows = _years([(f"{2022 + i}-12-31", 100.0 * (1.1 ** i), 20.0) for i in range(3)])
    history = S.annual_history(rows)
    assert history["cagr_5y"] is None
    assert history["cagr_3y"] is None      # 3 年增速需要 4 个年度点
    assert history["covered"] == 3


def test_cagr_is_compound_not_average():
    rows = _years([(f"{2020 + i}-12-31", 100.0 * (1.12 ** i), 20.0) for i in range(6)])
    history = S.annual_history(rows)
    assert history["cagr_5y"] == pytest.approx(12.0, abs=0.05)
    assert history["margin_median"] is not None


# ------------------------------------------------------------------ 默认值

def test_seed_refuses_to_invent_defaults_when_history_is_missing():
    """**这是最危险的失败方式。**

    拿不到历史时如果给一组编出来的默认假设，它看起来很专业，
    而且会被当成基准——没有任何报错，人也不会去质疑一个"系统给的默认值"。
    所以宁可返回空，让页面说「先同步财报」。
    """
    assert S.seed({}, {}) == []
    assert S.seed({"cagr_5y": 10.0}, {}) == []                 # 没有净利率
    assert S.seed({"cagr_5y": 10.0, "margin_median": 20.0}, {}) == []   # 没有 PE 可用


def test_seed_uses_the_company_own_pe_percentiles():
    """退出 PE 用这家公司自己的估值历史分位，不用「当前 PE × 0.7」那种乘数。

    退出 PE 是整套里最主观、对结果影响又最大的一个数（五年后的价值直接乘它）。
    乘数是我在编，分位是它自己的事实。
    """
    history = {"cagr_5y": 12.0, "cagr_3y": 10.0, "margin_median": 48.0,
               "margin_low": 47.0, "margin_high": 50.0,
               "growth_worst": -1.2, "growth_best": 17.0}
    band = {"p25": 21.8, "p50": 29.5, "p75": 38.9}
    bear, base, bull = S.seed(history, band)

    assert (bear.exit_pe, base.exit_pe, bull.exit_pe) == (21.8, 29.5, 38.9)
    # 三个情景的增速与净利率也来自它自己的历史，不是拍出来的乘数。
    # **增速取的是「持续做到过的速度」**：基准 = 三年复合 10.0，
    # 乐观 = 三年与五年里高的那个 12.0（不是最好的那一年 17.0）。
    # 理由见 seed() 里那段说明。
    assert (bear.revenue_growth, base.revenue_growth, bull.revenue_growth) == (-1.2, 10.0, 12.0)
    assert (bear.net_margin, base.net_margin, bull.net_margin) == (47.0, 48.0, 50.0)


def test_scenarios_are_ordered_bear_base_bull():
    history = {"cagr_5y": 12.0, "margin_median": 48.0, "margin_low": 47.0,
               "margin_high": 50.0, "growth_worst": -1.2, "growth_best": 17.0}
    seeded = S.seed(history, {"p25": 21.8, "p50": 29.5, "p75": 38.9})
    assert [s.key for s in seeded] == list(S.SCENARIO_KEYS)
    assert [s.label for s in seeded] == ["悲观", "基准", "乐观"]


# ------------------------------------------------------------------ 整页

def _facts(price=1309.22):
    rows = _years([("2020-12-31", 979.9e8, 467.0e8), ("2021-12-31", 1094.6e8, 524.6e8),
                   ("2022-12-31", 1275.5e8, 627.2e8), ("2023-12-31", 1505.6e8, 747.3e8),
                   ("2024-12-31", 1741.4e8, 862.3e8), ("2025-12-31", 1720.5e8, 823.2e8)])
    return {"base_revenue": 1720.5e8, "base_report_date": "2025-12-31",
            "shares": 1_251_953_717.0, "price": price, "history": S.annual_history(rows)}


def test_build_reads_the_implied_growth_against_history():
    """光给一个隐含增速没人知道该怎么读，**那句对比才是结论**。"""
    facts = _facts()
    seeded = S.seed(facts["history"], {"p25": 21.8, "p50": 29.5, "p75": 38.9})
    out = S.build(facts, seeded)

    assert out["implied_growth"] is not None
    assert "过去五年" in out["implied_verdict"]
    assert str(out["implied_growth"]).rstrip("0").rstrip(".") in out["implied_verdict"]
    assert len(out["scenarios"]) == 3
    assert all(row["per_share"] is not None for row in out["scenarios"])


def test_a_cheaper_price_implies_a_lower_required_growth():
    seeded = S.seed(_facts()["history"], {"p25": 21.8, "p50": 29.5, "p75": 38.9})
    dear = S.build(_facts(price=2000.0), seeded)["implied_growth"]
    cheap = S.build(_facts(price=800.0), seeded)["implied_growth"]
    assert dear > cheap


def test_exit_pe_sensitivity_is_shown_because_it_dominates():
    """退出 PE 最主观，而五年后的价值直接乘它——所以它必须单独可见。"""
    seeded = S.seed(_facts()["history"], {"p25": 21.8, "p50": 29.5, "p75": 38.9})
    rows = S.build(_facts(), seeded)["sensitivity"]
    assert [r["label"] for r in rows] == ["退出 PE 低两成", "基准", "退出 PE 高两成"]
    values = [r["per_share"] for r in rows]
    assert values[0] < values[1] < values[2]
    # 低两成到高两成，价值应当差出五成——这就是"它主导结果"的具体含义
    assert values[2] / values[0] == pytest.approx(1.5, abs=0.01)


def test_the_page_says_it_is_not_a_target_price():
    """边界必须跟着数据一起出去。放在前端硬编码的话，换个入口就丢了。"""
    seeded = S.seed(_facts()["history"], {"p25": 21.8, "p50": 29.5, "p75": 38.9})
    boundary = S.build(_facts(), seeded)["boundary"]
    assert "不是目标价" in boundary
    assert "不是概率分布" in boundary


def test_pe_band_ignores_junk():
    band = S.pe_band([30.0, -5.0, None, 10.0, 20.0])   # 负 PE 与空值不该进分位
    assert band["covered"] == 3
    assert band["p25"] is not None and band["p25"] > 0


def test_scenarios_are_seeded_from_recent_years_not_the_whole_archive():
    """**这条是被真实数据教出来的。**

    第一版用全部历史取「最差的一年 / 最好的一年」。茅台库里有 28 期年报、
    回到 1998 年，于是乐观情景拿到 2010 年的 +58% 增速、悲观情景拿到 2001 年的
    20% 净利率——而它近六年增速在 -1% 到 18%、净利率稳在 47–50%。
    算出来的乐观每股价值 16539 元，现价 1309 元。

    这不是"极端值该不该用"的问题：**二十年前的它是另一家公司**。
    而且正文写的是「过去五年」，统计口径必须跟结论的口径对上。
    """
    # 前十年高增长高波动，近六年温和——模拟真实档案的形状
    early = [(f"{2000 + i}-12-31", 100.0 * (1.5 ** i), 100.0 * (1.5 ** i) * 0.20)
             for i in range(10)]
    recent = [(f"{2020 + i}-12-31", 5000.0 * (1.12 ** i), 5000.0 * (1.12 ** i) * 0.48)
              for i in range(6)]
    history = S.annual_history(_years(early + recent))

    assert history["covered"] == 16, "完整序列要照样返回，长期曲线本身有信息"
    # 但统计只看最近的窗口
    assert history["growth_best"] < 20, f"乐观增速用了远古那一段：{history['growth_best']}"
    assert history["margin_low"] > 40, f"悲观净利率用了远古那一段：{history['margin_low']}"
    assert "另一个时代" in history["stat_note"]

    seeded = S.seed(history, {"p25": 20.0, "p50": 30.0, "p75": 40.0})
    bull = next(s for s in seeded if s.key == "bull")
    assert bull.revenue_growth < 20


def test_window_is_reported_so_the_page_can_say_which_years():
    history = S.annual_history(_years([(f"{2015 + i}-12-31", 100.0 * (1.1 ** i), 20.0 * (1.1 ** i))
                                       for i in range(10)]))
    assert history["window"] == S.RECENT_YEARS
    assert history["window_from"] == "2019-12-31"


def test_the_window_size_is_reported_separately_from_the_full_series():
    """**引用高低区间的地方必须说对样本量。**

    `covered` 是完整序列的长度（茅台 28 期），而 margin_low / growth_best
    只统计最近几期。写成「近 28 期的最低值」是在说谎——而那句话恰恰是
    让人相信这个门槛的理由。
    """
    rows = _years([(f"{2000 + i}-12-31", 100.0 * (1.1 ** i), 20.0 * (1.1 ** i))
                   for i in range(20)])
    history = S.annual_history(rows)
    assert history["covered"] == 20
    assert history["window_covered"] == S.RECENT_YEARS + 1
    assert history["window_covered"] < history["covered"]


# ------------------------------------------------------------------ 初值不许长成假象


def test_初值不拿某一年的峰值去复利():
    """**把单独一年的增速复利五年，得到的不是情景，是假象。**

    这条是拿宁德时代 2026-09-22 的真实数据写的。当时的初值是
    「五年复合（基准）、最差的一年（悲观）、最好的一年（乐观）」，
    于是乐观 = 最好的一年 +159.06% 复利五年 → **每股 48614 元，而它现价 305**。
    页面开场就是 +15858%，使用者原话「我人都麻了」。

    一个自明地荒唐的数字会让整页失去信任，连旁边那个真正有用的反推增速
    也一起被扔掉。
    """
    catl = {"cagr_3y": 8.84, "cagr_5y": 53.13, "margin_median": 11.66,
            "margin_low": 9.35, "margin_high": 17.04,
            "growth_worst": -9.7, "growth_best": 159.06}
    bear, base, bull = S.seed(catl, {"p25": 21.0, "p50": 24.8, "p75": 42.3})

    assert base.revenue_growth == 8.84, "基准要用三年复合（最近这个体制下的速度）"
    assert bull.revenue_growth == 53.13, "乐观要用连着做到过五年的速度，不是某一年的峰值"
    assert bull.revenue_growth != 159.06, "最好的一年复利五年是假象，不是乐观情景"

    base_revenue, shares = 423701834000.0, 4551419768.664564
    值 = {row.key: S.value_of(row, base_revenue, shares, 5, 10.0)["per_share"]
          for row in (bear, base, bull)}
    # 现价 304.63：基准落在同一个量级上，这份估值才有人肯看
    assert 150 < 值["base"] < 600, f"基准每股 {值['base']}，跟现价不在一个量级上"
    assert 值["bull"] < 值["base"] * 30, f"乐观每股 {值['bull']}，又长成假象了"


def test_三个初值天然有序():
    """悲观 ≤ 基准 ≤ 乐观。**不能出现「乐观比基准还低」**——

    三年复合快过五年复合的公司（刚加速的那种）最容易撞上这一条。
    """
    加速中 = {"cagr_3y": 30.0, "cagr_5y": 8.0, "margin_median": 10.0,
              "margin_low": 8.0, "margin_high": 14.0,
              "growth_worst": -5.0, "growth_best": 60.0}
    bear, base, bull = S.seed(加速中, {"p25": 15.0, "p50": 20.0, "p75": 28.0})
    assert bear.revenue_growth <= base.revenue_growth <= bull.revenue_growth, \
        (bear.revenue_growth, base.revenue_growth, bull.revenue_growth)
    assert base.revenue_growth == 30.0 and bull.revenue_growth == 30.0


def test_每个初值都说得出是从哪来的():
    """使用者看到「基准 8.84%」时，必须能立刻知道它不是编的。"""
    catl = {"cagr_3y": 8.84, "cagr_5y": 53.13, "margin_median": 11.66,
            "margin_low": 9.35, "margin_high": 17.04,
            "growth_worst": -9.7, "growth_best": 159.06}
    sources = S.seed_sources(catl)
    assert "8.84" in sources["base"] and "三年" in sources["base"]
    assert "53.13" in sources["bull"]
    assert "-9.7" in sources["bear"]
    assert "假象" in sources["note"]


def test_缺三年复合时退回五年():
    只有五年 = {"cagr_5y": 12.0, "margin_median": 10.0, "margin_low": 8.0,
                "margin_high": 14.0, "growth_worst": -3.0}
    bear, base, bull = S.seed(只有五年, {"p25": 15.0, "p50": 20.0, "p75": 28.0})
    assert base.revenue_growth == 12.0 and bull.revenue_growth == 12.0
