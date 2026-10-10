"""涨跌归因：判据要经得起反着读。

这个模块判的是「它为什么涨」，而使用者最需要它的那一次往往是下跌
（"跌到我的买点了，是跌得有道理还是跌得没道理？"）。所以下面有一半用例
是拿跌的数据跑的 —— 第一版的方向词和分位判据在跌的那一侧全是错的。
"""

from __future__ import annotations

import math

from stock_decision import rally


def facts(**overrides):
    """一组默认事实：20 天涨 15%，行业中位涨 2%，无公告无财报。"""
    base = {
        "window_days": 20,
        "change": 15.0,
        "limit_percent": 10.0,
        "industry": {"name": "电力设备", "peer_count": 300, "median_change": 2.0},
        "volume": {"ratio": 2.0},
        "limit_up_days": 0,
        "max_limit_streak": 0,
        "turnover_rate": 1.0,
        "float_market_cap": 1.3e12,
        "valuation": {"pe_start": 20.0, "pe_end": 23.0, "earnings_share": 0.0,
                      "report_in_window": False, "report_dates": [],
                      "pe_percentile_start": 50.0},
        "events": [],
        "post_event": None,
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


# ── 会计恒等式 ──────────────────────────────────────────────────────────────


def test_盈利与估值的拆解用对数相加():
    """30% 的估值扩张加 10% 的盈利增长**不等于** 40% 的涨幅（实际 43%）。

    用百分比直接相减的话，那个差额会被硬塞进某一项里。
    """
    share = rally.earnings_share(43.0, 30.0)
    assert share is not None
    assert abs(share - (math.log(1.43) - math.log(1.30)) / math.log(1.43)) < 1e-12
    # 涨幅全部来自估值 → 盈利贡献 0
    assert abs(rally.earnings_share(30.0, 30.0)) < 1e-12


def test_缺PE序列时拆不开就说拆不开():
    assert rally.earnings_share(30.0, None) is None


def test_窗口内没新财报时盈利贡献恒为零():
    """**这是恒等式，不是估计。** 价格 = 市盈率 × 每股收益，EPS 没动过的话
    这段涨跌在会计上 100% 来自市盈率的变化。"""
    note = rally._accounting_note(
        {"report_in_window": False, "pe_start": 20.0, "pe_end": 23.0,
         "pe_start_date": "2026-08-25", "pe_end_derived": True}, 15.0)
    assert "100%" in note and "市盈率" in note
    assert "推出来的" in note


# ── 归因门槛 ────────────────────────────────────────────────────────────────


def test_幅度不到门槛就不编原因():
    """**不是每一段行情都有原因。** 给一段正常波动编一个故事，
    会让人在下一次真有事发生时也照着故事读。"""
    verdict = rally.classify(facts(change=3.0))
    assert verdict["primary"] == "quiet"
    assert verdict["suppressed_by_floor"] is True


def test_门槛跟着窗口长度缩放():
    assert rally.attribution_floor(5) < rally.attribution_floor(20) < rally.attribution_floor(60)
    # 20 天走 3% 不值得归因，走 15% 值得
    assert 3.0 < rally.attribution_floor(20) < 15.0


def test_超过门槛之后判据才被采信():
    verdict = rally.classify(facts(change=15.0))
    assert verdict["suppressed_by_floor"] is False
    assert verdict["primary"] != "quiet"


# ── 方向对称 ────────────────────────────────────────────────────────────────


def test_跌的时候方向词跟着各自的数走():
    """**第一版这里是错的**：同行业那句话的"涨/跌"照抄了个股的方向，

    于是「它跌了 3.8%，同行业中位跌了 3.6%」——而行业中位其实是 +3.5%。
    一个方向词写错，读者会得出完全相反的结论，而页面上看不出任何异常。
    """
    verdict = rally.classify(facts(change=-18.0, industry={"median_change": 3.5}))
    head = verdict["headline"]
    assert "跌了 18.0%" in head
    # 对照组现在**报名字**（产业链环节或申万一级），但方向词仍然各跟各的数：
    # 它跌了，同行涨了，两个动词必须相反。
    assert "中位涨了 3.5%" in head, head
    assert "多跌了 21.5 个百分点" in head, head
    assert "申万一级" in head, "对照组要报清是哪一组"


def test_涨要从低位起才叫估值修复():
    up_from_low = rally.classify(facts(change=25.0, valuation={"pe_percentile_start": 15.0}))
    rerating = next(t for t in up_from_low["types"] if t["key"] == "rerating")
    assert rerating["hit"] is True

    up_from_high = rally.classify(facts(change=25.0, valuation={"pe_percentile_start": 85.0}))
    rerating = next(t for t in up_from_high["types"] if t["key"] == "rerating")
    assert rerating["hit"] is False, "从 85% 分位涨上去不该被判成「估值修复」"


def test_跌要从高位起才叫估值压缩():
    """方向不翻的话，"从 90% 分位跌下来"和"从 10% 分位跌下来"会判成同一件事。"""
    down_from_high = rally.classify(facts(change=-25.0, industry={"median_change": -2.0},
                                          valuation={"pe_percentile_start": 85.0}))
    assert next(t for t in down_from_high["types"] if t["key"] == "rerating")["hit"] is True

    down_from_low = rally.classify(facts(change=-25.0, industry={"median_change": -2.0},
                                         valuation={"pe_percentile_start": 15.0}))
    assert next(t for t in down_from_low["types"] if t["key"] == "rerating")["hit"] is False


def test_行业性要求同方向():
    """它跌 20% 而行业涨 5%，绝不是"跟着板块走"。"""
    verdict = rally.classify(facts(change=-20.0, industry={"median_change": 5.0}))
    assert next(t for t in verdict["types"] if t["key"] == "sector")["hit"] is False


def test_行业同向且解释了大半才算行业性():
    verdict = rally.classify(facts(change=12.0, industry={"median_change": 9.0}))
    assert next(t for t in verdict["types"] if t["key"] == "sector")["hit"] is True


# ── 事件催化：不被公告密度骗 ────────────────────────────────────────────────


def test_公告盖满窗口时不算集中():
    """**这是第一版真的判错的那一个。**

    宁德时代窗口内有 9 条实质公告，各标记之后三天，20 个交易日盖掉 15 天。
    "公告后三天贡献 72% 的幅度"听着像集中，其实比 75% 的覆盖率还低——
    那几天反而比平均值弱。而判据写的是「≥50% 就算集中」，于是它稳稳命中。
    """
    verdict = rally.classify(facts(
        change=-18.0,
        events=[{"relevance": "高", "title": f"公告{i}"} for i in range(9)],
        post_event={"share": 0.72, "day_share": 0.75, "covered_days": 15,
                    "tradable_days": 20, "lift": 0.96, "events_used": 9}))
    catalyst = next(t for t in verdict["types"] if t["key"] == "catalyst")
    assert catalyst["hit"] is False, "覆盖 75% 的天数贡献 72% 的幅度，不叫集中"


def test_真的集中在公告之后才算事件催化():
    verdict = rally.classify(facts(
        change=15.0,
        events=[{"relevance": "高", "title": "重大合同中标"}],
        post_event={"share": 0.9, "day_share": 0.15, "covered_days": 3,
                    "tradable_days": 20, "lift": 6.0, "events_used": 1}))
    catalyst = next(t for t in verdict["types"] if t["key"] == "catalyst")
    assert catalyst["hit"] is True
    assert "6.00 倍" in catalyst["checks"][1]["detail"]


def test_公告太密时判据里要直说这个问题答不了():
    verdict = rally.classify(facts(
        change=15.0,
        events=[{"relevance": "高", "title": "x"} for _ in range(9)],
        post_event={"share": 0.8, "day_share": 0.8, "covered_days": 16,
                    "tradable_days": 20, "lift": 1.0, "events_used": 9}))
    catalyst = next(t for t in verdict["types"] if t["key"] == "catalyst")
    assert "答不了" in catalyst["checks"][1]["detail"]


# ── 其它类型 ────────────────────────────────────────────────────────────────


def test_情绪驱动要求超额放量且没有出处():
    verdict = rally.classify(facts(change=25.0, industry={"median_change": 2.0},
                                   volume={"ratio": 2.4}))
    assert next(t for t in verdict["types"] if t["key"] == "theme")["hit"] is True

    # 有实质公告 → 涨有出处，就不是"情绪"
    with_news = rally.classify(facts(change=25.0, volume={"ratio": 2.4},
                                     events=[{"relevance": "高", "title": "中标"}]))
    assert next(t for t in with_news["types"] if t["key"] == "theme")["hit"] is False


def test_资金博弈要四条一起命中():
    verdict = rally.classify(facts(
        change=40.0, limit_up_days=4, max_limit_streak=3,
        turnover_rate=22.0, float_market_cap=4.5e9))
    assert next(t for t in verdict["types"] if t["key"] == "flow")["hit"] is True

    # 大盘股不会是"小盘资金博弈"，哪怕涨停了
    big = rally.classify(facts(change=40.0, limit_up_days=4, max_limit_streak=3,
                               turnover_rate=22.0, float_market_cap=1.3e12))
    assert next(t for t in big["types"] if t["key"] == "flow")["hit"] is False


def test_一条都不命中就说无法解释而不是硬挑一个():
    """**一个什么都能解释的分类器等于没有分类器。**

    「查不出原因」本身就是对决策有用的信息，它是「先别碰」最诚实的理由。
    """
    verdict = rally.classify(facts(
        change=-18.0, industry={"median_change": -2.0},
        volume={"ratio": 1.28}, valuation={"pe_percentile_start": 21.0}))
    assert verdict["primary"] == "unexplained"


def test_半数判据命中不算命中():
    """用"满足一半就算"的打分会让每一类都亮一点，最后看起来像"什么都沾边"。"""
    verdict = rally.classify(facts(change=25.0, volume={"ratio": 1.1}))
    theme = next(t for t in verdict["types"] if t["key"] == "theme")
    assert theme["hit_count"] == 2 and theme["total"] == 3
    assert theme["hit"] is False


def test_每条判据都带着自己的数字():
    """只给"它属于题材情绪"这一个标签，使用者没办法复核，也没办法不同意。"""
    verdict = rally.classify(facts(change=25.0))
    for item in verdict["types"]:
        for check in item["checks"]:
            assert check["text"], item["key"]
            assert check["detail"], (item["key"], check["text"])


def test_没有涨跌幅就直说算不出来():
    assert rally.classify({"change": None})["ok"] is False


# ── 涨跌停幅度 ──────────────────────────────────────────────────────────────


def test_各板的涨跌停幅度():
    assert rally.limit_percent("主板", "格力电器") == 10.0
    assert rally.limit_percent("创业板", "润泽科技") == 20.0
    assert rally.limit_percent("科创板", "寒武纪") == 20.0
    assert rally.limit_percent("北交所", "某北交所股") == 30.0


def test_ST股不管在哪个板都是五个点():
    """**按名称判，不按代码判**：ST 是状态不是板块，一只票会戴上也会摘掉。"""
    assert rally.limit_percent("主板", "ST云动") == 5.0
    assert rally.limit_percent("创业板", "*ST某某") == 5.0
    assert rally.limit_percent("科创板", "*ST航图") == 5.0


def test_主判定排在第一张卡():
    """**第一版这里是矛盾的。**

    幅度没到门槛时页面长这样：标题写着「没什么事发生」，而第一张卡是命中
    2/2 的「估值重定价」——读起来像系统自己跟自己打架。
    """
    verdict = rally.classify(facts(change=2.5, valuation={"pe_percentile_start": 15.0}))
    assert verdict["primary"] == "quiet"
    assert verdict["types"][0]["key"] == "quiet", \
        [t["key"] for t in verdict["types"][:3]]


def test_盈利贡献和公告占比不是同一个数():
    """**取数层曾经把这两个量用同一个变量名装**，于是后者悄悄改写了前者：

    页面上「基本面驱动」写着「盈利贡献 -8%」，而「窗口内新报告期：没有」
    就在同一屏上——两句话自相矛盾。是对着截图比数字才发现的
    （同一个 -8% 在两个地方出现）。

    这条守在判据这一侧：窗口内没有新报告期时，盈利贡献只能是 0，
    不管公告那一侧算出来什么。
    """
    verdict = rally.classify(facts(
        change=-18.0,
        valuation={"report_in_window": False, "earnings_share": 0.0},
        events=[{"relevance": "高", "title": "x"}],
        post_event={"share": -0.075, "day_share": 0.3, "covered_days": 6,
                    "tradable_days": 20, "lift": -0.25, "events_used": 1}))
    fundamental = next(t for t in verdict["types"] if t["key"] == "fundamental")
    assert "盈利贡献 0%" in fundamental["checks"][1]["detail"], \
        fundamental["checks"][1]["detail"]


# ── 归因门槛按每只票自己的波动定 ────────────────────────────────────────────


def test_门槛跟着这只票自己的波动走():
    """**同样走 12%，在大盘股上是件事，在小盘股上是它每周都在做的事。**

    第一版用固定的 `2×√天数`（20 天 8.9%）——那是拍出来的。
    年化波动 20% 的票会漏判，年化波动 70% 的票会被硬扣上一个故事。
    """
    calm = rally.attribution_floor(20, 0.013)      # 年化约 20%
    wild = rally.attribution_floor(20, 0.045)      # 年化约 70%
    assert calm < 8.0 < wild, (calm, wild)
    assert wild > calm * 2.5


def test_取不到波动就退回通用式子并说清楚():
    """给一个十几根样本算出来的标准差，比不给更糟。"""
    assert rally.attribution_floor(20, None) == rally.attribution_floor(20)
    verdict = rally.classify(facts(change=3.0, prior_daily_sigma=None))
    assert verdict["floor_basis"].startswith("通用")
    quiet = next(t for t in verdict["types"] if t["key"] == "quiet")
    assert "通用式子" in quiet["checks"][0]["detail"]


def test_高波动的票走同样的幅度被判成正常抖动():
    quiet = rally.classify(facts(change=-19.0, prior_daily_sigma=0.040,
                                 industry={"median_change": -2.0}))
    loud = rally.classify(facts(change=-19.0, prior_daily_sigma=0.012,
                                industry={"median_change": -2.0}))
    assert quiet["primary"] == "quiet", "日波动 4% 的票跌 19% 还在 1.2σ 之内"
    assert loud["primary"] != "quiet", "日波动 1.2% 的票跌 19% 是件事"


def test_门槛不许拿窗口自己的波动算():
    """**循环了就会「涨得越猛越判成没事发生」。**

    一次大涨会把窗口内的标准差抬上去，于是它把自己压到门槛之下。
    所以 σ 只能取窗口之前那一段——这条守在取数层的函数名上（`_prior_daily_sigma`），
    判据这一侧确认它读的是 `prior_daily_sigma` 而不是别的什么。
    """
    import inspect
    source = inspect.getsource(rally.classify)
    assert 'facts.get("prior_daily_sigma")' in source
    assert '"daily_sigma"' not in source, "别读窗口自己的波动"


# ── 对照组优先用产业链环节 ──────────────────────────────────────────────────


def _chain(median, peers=3, label="电芯"):
    return {"groups": [{"key": "battery:cell", "chain_label": "动力电池", "stage": "中游",
                        "segment_label": label, "what": "", "peer_count": peers,
                        "median_change": median, "enough": peers >= 3, "members": []}],
            "best": "battery:cell" if peers >= 3 else None, "note": ""}


def test_同环节够三家就用它当对照组():
    """**申万「电力设备」有 377 家，混着光伏、风电、电网设备。**

    拿它的中位数去问「只有它在跌吗」，答案被稀释掉了。
    """
    verdict = rally.classify(facts(change=-19.0,
                                   industry={"name": "电力设备", "peer_count": 377,
                                             "median_change": -2.5},
                                   chain_peers=_chain(-4.1)))
    assert "电芯" in verdict["peer_source"]
    assert verdict["peer_median"] == -4.1
    assert "同环节" in verdict["peer_source"]


def test_同环节不足三家就退回申万并说清楚():
    """两家的中位数只是其中一家，而它会长得跟一个统计量一样。"""
    verdict = rally.classify(facts(change=-19.0,
                                   industry={"name": "电力设备", "peer_count": 377,
                                             "median_change": -2.5},
                                   chain_peers=_chain(-4.1, peers=2)))
    assert "申万一级" in verdict["peer_source"]
    assert verdict["peer_median"] == -2.5


def test_不在产业链底图里也能照常判():
    verdict = rally.classify(facts(change=-19.0,
                                   industry={"name": "家用电器", "peer_count": 92,
                                             "median_change": 3.5}))
    assert verdict["ok"] is True
    assert "申万一级" in verdict["peer_source"]


def test_换了对照组超额也跟着换():
    """超额是拿对照组算的——对照组换了它还用旧的，就是两处各说各的。"""
    wide = rally.classify(facts(change=-19.0,
                                industry={"name": "电力设备", "peer_count": 377,
                                          "median_change": -2.5}))
    narrow = rally.classify(facts(change=-19.0,
                                  industry={"name": "电力设备", "peer_count": 377,
                                            "median_change": -2.5},
                                  chain_peers=_chain(-4.1)))
    assert "16.5" in wide["headline"], wide["headline"]
    assert "14.9" in narrow["headline"], narrow["headline"]
