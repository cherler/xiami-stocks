"""做 T 回测：算术必须自己能被手算复核。

这一整个模块的说服力全在「数字是对的」上面 —— 它要告诉使用者
「你做 T 会亏钱」，而那句话只有在他能自己验算的时候才站得住。

所以这里每条都在**手算一遍**，不是拿函数的输出去对函数的输出。
"""

from __future__ import annotations

import math

from stock_decision import swing


def bars(closes, *, opens=None, highs=None, lows=None, start_day=1):
    """造一段日线。日期用 2026-01-xx，只要单调递增就行。"""
    out = []
    for index, close in enumerate(closes):
        day = start_day + index
        out.append({
            "trade_date": f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}",
            "close": close,
            "open_price": None if opens is None else opens[index],
            "high": None if highs is None else highs[index],
            "low": None if lows is None else lows[index],
            "volume": 1000.0,
        })
    # 日期可能因为进位而重复，直接排一遍并去重
    seen, unique = set(), []
    for row in out:
        if row["trade_date"] in seen:
            continue
        seen.add(row["trade_date"])
        unique.append(row)
    return unique


# ── 二项检验 ────────────────────────────────────────────────────────────────


def test_精确二项检验对得上教科书的例子():
    """n=20、p=0.5、观测 15 次，双侧精确 p = 0.0414（R 的 binom.test 也是这个数）。"""
    value = swing.binomial_p_value(15, 20, 0.5)
    assert value is not None
    assert abs(value - 0.041389) < 1e-5, value


def test_样本不足时不给p值而不是给一个漂亮的数():
    """**「样本太少」和「没差别」不是一回事。**

    小样本上算出来的 p 值会稳定地不显著，而那读起来跟"已经验过、没规律"
    一模一样。所以少于 10 个样本时返回 None，页面据此说"样本不足"。
    """
    assert swing.binomial_p_value(5, 9, 0.5) is None
    assert swing.binomial_p_value(5, 10, 0.5) is not None


def test_完全符合基准时p值是1():
    assert abs(swing.binomial_p_value(50, 100, 0.5) - 1.0) < 1e-9


# ── 预处理 ──────────────────────────────────────────────────────────────────


def test_涨跌幅自己算而不是读库里那一列():
    """库里 990171 行日线只有 116880 行有 change_percent。

    读那一列的话，窗口里**超过八成的日子会悄悄消失**，而页面上只会显示
    一个变小了的样本数——没有任何地方会报错。
    """
    rows = swing.prepare(bars([10.0, 11.0, 9.9]), window=0)
    assert len(rows) == 2                      # 第一根没有前收，不进窗口
    assert abs(rows[0]["return"] - 0.1) < 1e-12
    assert abs(rows[1]["return"] - (9.9 / 11.0 - 1)) < 1e-12


def test_窗口截的是最近那一段():
    rows = swing.prepare(bars([float(x) for x in range(1, 40)]), window=5)
    assert len(rows) == 5
    assert rows[-1]["close"] == 39.0


# ── 规律检验 ────────────────────────────────────────────────────────────────


def test_完美交替的序列被判成有反转倾向():
    """**判据要拿必定命中的数据验一遍能不能亮。**

    一条永远判不出"有规律"的判据，跟没有判据是一样的，
    而两者在页面上长得完全一样。
    """
    closes = [100.0]
    for index in range(200):
        closes.append(closes[-1] * (1.02 if index % 2 == 0 else 1 / 1.02))
    view = swing.rhythm(bars(closes), window=0)
    assert view["enough"]
    assert view["verdict"] == "有反转倾向", view["headline"]
    assert view["autocorrelation_1"] < -0.5


def test_单调上涨的序列不会被判成有反转倾向():
    view = swing.rhythm(bars([100.0 * (1.005 ** i) for i in range(150)]), window=0)
    assert view["verdict"] == "看不出规律"


def test_条件概率永远跟基准一起给():
    """「涨完之后 52% 会跌」听起来像规律，跟 51% 的基准比就什么都不是。"""
    view = swing.rhythm(bars([100.0 + (i % 7) for i in range(120)]), window=0)
    for key in ("reversal", "rebound"):
        assert "base" in view[key] and "lift" in view[key]
        assert view[key]["lift"] == (view[key]["rate"] - view[key]["base"])


def test_样本太少直接说样本太少():
    view = swing.rhythm(bars([100.0, 101.0, 100.5]), window=0)
    assert view["enough"] is False
    assert "30" in view["note"]


# ── 机器模拟 ────────────────────────────────────────────────────────────────

ZERO_COST = {"commission_rate": 0.0, "commission_min": 0.0, "stamp_tax_rate": 0.0,
             "transfer_fee_rate": 0.0, "slippage_rate": 0.0}


def test_天花板等于逐日最高减最低乘以股数():
    """手算：每天 (high − low) × 战术股数，零成本下必须**完全相等**。"""
    closes = [100.0 + i * 0.1 for i in range(60)]
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.0 for c in closes]
    run = swing.simulate(bars(closes, highs=highs, lows=lows),
                         strategy="oracle", window=0, base_shares=10000,
                         tactical_percent=20, costs=ZERO_COST)
    rows = swing.prepare(bars(closes, highs=highs, lows=lows), window=0)
    expected = sum((row["high"] - row["low"]) * 2000 for row in rows)
    assert abs(run["net"] - expected) < 1e-6, (run["net"], expected)
    assert run["fees"] == 0.0
    assert run["win_rate"] == 1.0


def test_每天反T的收益等于开盘减收盘的累加():
    # **至少 30 根**：模拟低于这个数会退回「样本不足」那条路，
    # 拿不到 net —— 上一版这里只给了 8 根，测试自己先错了。
    cycle_close = [100.0, 101.0, 99.0, 103.0, 102.0, 104.0, 101.5, 100.2]
    cycle_open = [99.5, 100.4, 100.1, 101.0, 103.0, 102.2, 103.1, 101.0]
    closes = (cycle_close * 6)[:45]
    opens = (cycle_open * 6)[:45]
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse",
                         window=0, base_shares=1000, tactical_percent=100, costs=ZERO_COST)
    rows = swing.prepare(bars(closes, opens=opens), window=0)
    expected = sum((row["open"] - row["close"]) * 1000 for row in rows)
    assert abs(run["net"] - expected) < 1e-6


def test_一字板当天不交易而且被单独数出来():
    """**被跳过的机会不许算进收益里。** 那是回测虚高最常见的来源。"""
    closes = [100.0] * 40
    # 全部日子都是一字板（high == low）
    run = swing.simulate(bars(closes, opens=closes, highs=closes, lows=closes),
                         strategy="always_reverse", window=0, costs=ZERO_COST)
    assert run["trades"] == 0
    assert run["skipped_locked"] == len(swing.prepare(bars(closes), window=0))
    assert "一字板" in run["note"]


def test_缺开盘价跟规则没触发说的不是同一句话():
    """两者在页面上长得一样，而能做的事完全不同：

    一个要去补数据，一个说明这条规则在这段时间里没有机会。
    """
    closes = [100.0 + (i % 3) for i in range(50)]
    no_open = swing.simulate(bars(closes), strategy="always_reverse", window=0)
    assert no_open["trades"] == 0
    assert "开盘价" in no_open["note"]
    assert no_open["skipped_no_open"] > 0

    # 门槛抬到 50%：有开盘价，但一天都触发不了
    opens = [c + 0.1 for c in closes]
    never = swing.simulate(bars(closes, opens=opens), strategy="reverse_t",
                           window=0, trigger_percent=50.0)
    assert never["trades"] == 0
    assert never["skipped_no_open"] == 0
    assert "没有一天满足" in never["note"]


def test_费用会把毛收益吃掉而且两种亏法要分得开():
    """毛收益是正的却净亏 → 频率问题；毛收益本身为负 → 方向问题。

    **两个病，两种药。** 混成一句「亏了」的话，人会去调费率，
    而真正该调的是规则的方向。
    """
    closes = [100.0] * 40
    opens = [100.05] * 40                      # 每天开盘比收盘高 0.05，毛收益为正
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse",
                         window=0, base_shares=1000, tactical_percent=100)
    assert run["gross"] > 0
    assert run["net"] < 0, "默认费率下这点价差应该不够付手续费"
    assert run["fees"] > run["gross"]


def test_打平所需价差是一个能拿去对盘面的数():
    closes = [100.0] * 40
    opens = [101.0] * 40
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse",
                         window=0, base_shares=10000, tactical_percent=100)
    # 手算：一次买 + 一次卖的费用 ÷ 平均成交金额
    per_trade_fee = run["fees"] / run["trades"]
    average_amount = (100.0 + 101.0) / 2 * 10000
    assert abs(run["breakeven_spread"] - per_trade_fee / average_amount) < 1e-12
    # 默认费率（万2.5 双边 + 万五印花 + 过户费）大约在千分之一以内
    assert 0.0005 < run["breakeven_spread"] < 0.002, run["breakeven_spread"]


def test_合并视图在全亏时不说最好的是某某():
    """全亏的时候「最好的是某某」会被读成推荐，而它其实是"输得最少的"。"""
    closes = [100.0] * 60
    opens = [100.02] * 60
    view = swing.compare(bars(closes, opens=opens, highs=[101.0] * 60, lows=[99.0] * 60),
                         window=0, base_shares=10000, tactical_percent=100)
    assert "全部是亏的" in view["best_line"]
    assert "输得最少" in view["best_line"]


def test_天花板那条策略不混进能照着做的三条里():
    view = swing.compare(bars([100.0 + (i % 5) for i in range(80)],
                              opens=[100.0] * 80, highs=[105.0] * 80, lows=[95.0] * 80),
                         window=0)
    assert swing.STRATEGIES["oracle"]["needs_open"] is False
    ceiling = [run for run in view["runs"] if run["strategy"] == "oracle"]
    assert len(ceiling) == 1
    assert "天花板" in view["ceiling_line"]


def test_一整段价格不动时自相关算不出来而不是当场崩():
    """**「算不出来」是一种真实情况，不是一个不可能。**

    每日涨跌幅方差为 0 时（长期停牌后复牌、极端冷门股，或者被前复权抹平的
    一段历史），自相关没有定义。第一版三句判词全都直接 `f"{rho1:.3f}"`，
    于是整个接口 500，页面上只显示「请求失败」——
    而真相是这只票那段时间一个价都没动过。
    """
    view = swing.rhythm(bars([100.0] * 60), window=0)
    assert view["enough"]
    assert view["autocorrelation_1"] is None
    assert "算不出来" in view["headline"]
    # compare 里那几句话也要一起活下来
    whole = swing.compare(bars([100.0] * 60, opens=[100.0] * 60,
                               highs=[100.0] * 60, lows=[100.0] * 60), window=0)
    assert whole["rhythm"]["enough"]


# ── 正收益必须配上「它可能只是运气」 ────────────────────────────────────────


def test_正收益一定带着显著性判据():
    """**一个好看的回测最容易让人下重注**（agentpickerplan 第七节的原话）。

    所以只要结果是正的，页面上就必须同时出现"它可能只是运气"那个数——
    否则留在脑子里的只剩那个收益率。
    """
    # **价差要有波动。** 每天都正好赚两块的话单笔收益方差为 0，
    # t 值算不出来（分母是 0）—— 那是个合成数据才有的情形，
    # 而它会让这条测试验的东西跟真实情况对不上。
    closes = [100.0 + (i % 7) * 0.4 for i in range(60)]
    opens = [close + 1.2 + (index % 5) * 0.3 for index, close in enumerate(closes)]
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse",
                         window=0, base_shares=10000, tactical_percent=100)
    assert run["net"] > 0
    assert run["win_rate_p_value"] is not None
    assert run["t_stat"] is not None
    assert "small_sample" in run


def test_稳赚的序列胜率跟抛硬币分得开():
    closes = [100.0] * 80
    opens = [102.0] * 80
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse", window=0)
    assert run["win_rate"] == 1.0
    assert run["win_rate_p_value"] < 0.001


def test_一半一半的序列跟抛硬币分不开():
    closes = [100.0] * 80
    opens = [101.0 if i % 2 == 0 else 99.0 for i in range(80)]
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse",
                         window=0, base_shares=10000, tactical_percent=100)
    assert run["win_rate_p_value"] > 0.05, "半数胜率却说跟抛硬币分得开"


def test_样本不到一百笔要标出来():
    closes = [100.0] * 60
    opens = [102.0] * 60
    run = swing.simulate(bars(closes, opens=opens), strategy="always_reverse", window=0)
    assert run["small_sample"] is True, "几十笔在统计上是小样本，页面上它跟几百笔长得一样"


def test_调参过拟合那条警告排在第一():
    """讲模拟局限的那几条之前，先讲使用者会怎么骗自己——它更容易发生。"""
    view = swing.compare(bars([100.0 + (i % 5) for i in range(80)],
                              opens=[100.0] * 80, highs=[105.0] * 80, lows=[95.0] * 80),
                         window=0)
    assert "调出来的只是这一段历史的形状" in view["caveats"][0]
