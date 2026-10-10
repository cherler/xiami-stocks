"""决策闭环落到库上：守卫接的是真表，触发不许重复推。

`test_decision_loop.py` 测的是纯逻辑（给一组事实必须永远给同一个答案）。
这里测的是另一半：**那组事实是不是真的从库里查出来的**。

两半都要有。只测纯逻辑的话，守卫可能查错了表而永远返回 False；
只测落库的话，判据本身写反了也看不出来（价格带那道校验第一版就是反的）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_decision import repository
from stock_decision.database import connection, now_iso
from stock_decision.repository import LedgerError
from stock_decision.schemas import CompanyInput, PortfolioCreate, ThesisCreate, TradeCreate


BANDS = {"watch": 310.0, "fair": 295.0, "ideal": 280.0, "extreme": 270.0}

# **日期一律相对今天算，不写死。**
#
# 两个理由：成交日期不许填未来（TradeCreate 自己拦），而写死的 "2026-09-23"
# 在写这个文件的那天就已经是明天了；再者「计划内」的判定要比对
# 决策卡的建卡时间（就是今天）与成交日，写死的日期会让这条判据
# 在某一天悄悄换一条分支走。
TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
LONG_AGO = (date.today() - timedelta(days=200)).isoformat()
PLAN = {"total_percent": 20, "first_percent": 6, "second_percent": 6, "third_percent": 6}


def _company(symbol: str = "300750", name: str = "宁德时代") -> int:
    return repository.create_company(
        CompanyInput(symbol=symbol, name=name, industry="电池"))["id"]


def _bar(symbol: str, day: str, close: float, **extra) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO price_bars (symbol, trade_date, close, open_price, high, low,
                                       volume, source, refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, '测试', ?)""",
            (symbol, day, close, extra.get("open"), extra.get("high"),
             extra.get("low"), extra.get("volume"), now_iso()))


def _valuation(company_id: int) -> None:
    # **三个情景要一起存**（save_valuation 自己会拦），只给 base 会报错。
    repository.save_valuation(company_id, {
        "years": 5, "discount_rate": 10,
        "scenarios": [
            {"key": "bear", "revenue_growth": -5.0, "net_margin": 8.0, "exit_pe": 12.0},
            {"key": "base", "revenue_growth": 8.0, "net_margin": 12.0, "exit_pe": 18.0},
            {"key": "bull", "revenue_growth": 18.0, "net_margin": 15.0, "exit_pe": 25.0},
        ],
        "note": "测试用"})


def _thesis(company_id: int, counter: str = "连续两个季度市占率掉到 30% 以下。") -> None:
    repository.create_thesis(company_id, ThesisCreate(
        claim="赌的是它的成本曲线还在往下走，而客户自研短期接不上。",
        counter_condition=counter))


# ── 建档即入闭环 ────────────────────────────────────────────────────────────


def test_第一次读卡片就会建出来并停在待研究():
    company_id = _company()
    card = repository.decision_card(company_id)
    assert card["state"] == "discovered"
    assert card["state_label"] == "待研究"


def test_建卡是幂等的():
    """重复调用不该冒出第二张卡——两张卡意味着两套价格带。"""
    company_id = _company()
    first = repository.ensure_decision_card(company_id)
    second = repository.ensure_decision_card(company_id)
    assert first["id"] == second["id"]


def test_不存在的公司拿不到卡片():
    assert repository.decision_card(999999) is None


# ── 守卫查的是真表 ──────────────────────────────────────────────────────────


def test_守卫读的是theses和valuations而不是卡片自己的副本():
    """**状态机不存任何已有的事实。** 投资逻辑在 theses、估值在 valuations，

    它只问那几张表「东西齐了没有」。复制出来的第二份迟早跟第一份说的不一样，
    而那时候没人知道该信哪份。
    """
    company_id = _company()
    repository.save_decision_card(company_id, {"watch_reason": "好公司遇到暂时性麻烦"})
    repository.move_decision_state(company_id, "researching", "开始读年报")

    guards = {g["key"]: g["ok"] for g in repository.decision_card(company_id)["guards"]}
    assert guards["thesis"] is False and guards["valuation"] is False

    _thesis(company_id)
    guards = {g["key"]: g["ok"] for g in repository.decision_card(company_id)["guards"]}
    assert guards["thesis"] is True and guards["counter_condition"] is True
    assert guards["valuation"] is False, "只写了逻辑，估值还没做"

    _valuation(company_id)
    guards = {g["key"]: g["ok"] for g in repository.decision_card(company_id)["guards"]}
    assert guards["valuation"] is True


def test_没写反证条件的逻辑不算完成():
    """没有「什么证据能说明我错了」的逻辑没法被推翻，也就没法被检验。"""
    company_id = _company()
    repository.create_thesis(company_id, ThesisCreate(
        claim="我觉得它长期会很好，护城河很深，现在的麻烦是暂时的。",
        counter_condition=""))
    guards = {g["key"]: g["ok"] for g in repository.decision_card(company_id)["guards"]}
    assert guards["thesis"] is True
    assert guards["counter_condition"] is False


def test_持仓守卫读的是账本流水():
    company_id = _company()
    portfolio = repository.create_portfolio(PortfolioCreate(name="主账户", amount_mode="full"))
    guards = {g["key"]: g["ok"] for g in repository.decision_card(company_id)["guards"]}
    assert guards["position"] is False and guards["no_position"] is True

    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company_id, side="buy", trade_date=TODAY,
        shares=100, price=280.0,
        rationale="价格进了理想区，基本面复核之后按计划建第一笔。"))
    guards = {g["key"]: g["ok"] for g in repository.decision_card(company_id)["guards"]}
    assert guards["position"] is True and guards["no_position"] is False


# ── 推进与拦截 ──────────────────────────────────────────────────────────────


def test_走完整条路():
    company_id = _company()
    _bar("300750", TODAY, 308.61)
    repository.save_decision_card(company_id, {"watch_reason": "好公司遇到暂时性麻烦"})
    repository.move_decision_state(company_id, "researching", "开始读年报和电话会")
    _thesis(company_id)
    _valuation(company_id)
    repository.move_decision_state(company_id, "valued", "逻辑、反证、估值都齐了")
    repository.save_decision_card(company_id, {"bands": BANDS, "position_plan": PLAN})
    card = repository.move_decision_state(company_id, "waiting", "定好价格带，开始等")
    assert card["state"] == "waiting"
    assert [move["to_state"] for move in card["history"]] == ["waiting", "valued", "researching"]


def test_估值没做就推不到已估值():
    company_id = _company()
    repository.save_decision_card(company_id, {"watch_reason": "看着不错"})
    repository.move_decision_state(company_id, "researching", "开始看")
    _thesis(company_id)
    with pytest.raises(LedgerError) as caught:
        repository.move_decision_state(company_id, "valued", "我觉得差不多了")
    assert "估值" in str(caught.value)


def test_没做完研究就推不到等待买入():
    """产品原则四。**哪怕价格带和仓位计划都填好了也不行。**"""
    company_id = _company()
    repository.save_decision_card(company_id, {"bands": BANDS, "position_plan": PLAN})
    with pytest.raises(LedgerError) as caught:
        repository.move_decision_state(company_id, "waiting", "我就想现在开始等")
    assert "估值" in str(caught.value) or "研究" in str(caught.value)
    assert repository.decision_card(company_id)["state"] == "discovered"


def test_没有强制推进这条路():
    """留一个强制开关等于这套守卫不存在：用过一次之后，每一次卡住都会用它。"""
    import inspect
    source = inspect.getsource(repository.move_decision_state)
    assert "force" not in source.lower()


# ── 存卡片：校验不过一个字都不存 ────────────────────────────────────────────


def test_乱序的价格带存不进去而且不会存一半():
    company_id = _company()
    repository.save_decision_card(company_id, {"watch_reason": "原来的理由"})
    with pytest.raises(LedgerError):
        repository.save_decision_card(company_id, {
            "watch_reason": "改过的理由",
            "bands": {"watch": 270.0, "fair": 295.0, "ideal": 280.0, "extreme": 310.0}})
    card = repository.decision_card(company_id)
    assert card["bands"] == {}
    assert card["watch_reason"] == "原来的理由", "校验失败时连关注理由都不该被改掉"


def test_加仓总和超过计划总仓位存不进去():
    company_id = _company()
    with pytest.raises(LedgerError) as caught:
        repository.save_decision_card(company_id, {"position_plan": {
            "total_percent": 20, "first_percent": 10,
            "second_percent": 10, "third_percent": 10}})
    assert "20" in str(caught.value)


# ── 价格触发 ────────────────────────────────────────────────────────────────


def _waiting_card(symbol: str = "300750") -> int:
    company_id = _company(symbol)
    repository.save_decision_card(company_id, {"watch_reason": "等一个价"})
    repository.move_decision_state(company_id, "researching", "读")
    _thesis(company_id)
    _valuation(company_id)
    repository.move_decision_state(company_id, "valued", "齐了")
    repository.save_decision_card(company_id, {"bands": BANDS, "position_plan": PLAN})
    repository.move_decision_state(company_id, "waiting", "等")
    return company_id


def test_价格进带推成触发检查而不是持仓():
    """**价格到了只说明该重新看一眼。** 中间隔着一次基本面复核。"""
    company_id = _waiting_card()
    _bar("300750", TODAY, 308.61)
    result = repository.evaluate_decision_triggers()
    assert result["count"] == 1
    assert result["moved"][0]["band"] == "watch"
    card = repository.decision_card(company_id)
    assert card["state"] == "triggered"
    assert "不是买入信号" in card["entered_reason"]


def test_同一天同一段不重复推():
    """任何一个每天响十次的提醒，人都会把它关掉。"""
    _waiting_card()
    _bar("300750", TODAY, 308.61)
    assert repository.evaluate_decision_triggers()["count"] == 1
    assert repository.evaluate_decision_triggers()["count"] == 0


def test_价格还在带上方就不推():
    company_id = _waiting_card()
    _bar("300750", TODAY, 330.0)
    assert repository.evaluate_decision_triggers()["count"] == 0
    assert repository.decision_card(company_id)["state"] == "waiting"


def test_跌进极端机会区的提示是强制重新检查():
    _waiting_card()
    _bar("300750", TODAY, 262.0)
    result = repository.evaluate_decision_triggers()
    assert result["moved"][0]["band"] == "extreme"
    assert "强制重新检查" in result["moved"][0]["note"]


def test_没定价格带的卡片不会被触发():
    company_id = _company()
    _bar("300750", TODAY, 100.0)
    repository.save_decision_card(company_id, {"watch_reason": "还没想好价格"})
    assert repository.evaluate_decision_triggers()["count"] == 0


# ── 计划内 / 计划外 ─────────────────────────────────────────────────────────


# **纪律判定的原料是成交登记，不是账本流水。**
#
# 2026-09-24 换的源：持仓改成「只记股数和成本价」之后账本里再也不会有 buy，
# 这个指标原来查的就是 buy —— 不换的话它会永久归零而且不报错。
# 下面几条判据跟着从 create_trade 改成 record_fill，守的东西一个没变。


def test_触发检查里按价格带买入算计划内():
    company_id = _waiting_card()
    _bar("300750", TODAY, 275.0)
    repository.evaluate_decision_triggers()
    repository.record_fill(company_id, 276.0, filled_on=TODAY, shares=100,
                           note="价格进了理想区，复核完基本面没变，按计划建第一笔。")
    discipline = repository.decision_loop_board()["discipline"]
    assert discipline["inside_count"] == 1
    assert discipline["outside_count"] == 0
    assert discipline["inside"][0]["band"] == "ideal"


def test_价格还在带上方就买算计划外并说出为什么():
    company_id = _waiting_card()
    repository.record_fill(company_id, 330.0, filled_on=TODAY, shares=100,
                           note="怕买不到了，先上一点。")
    discipline = repository.decision_loop_board()["discipline"]
    assert discipline["outside_count"] == 1
    why = discipline["outside"][0]["why"]
    # 价格带存的是**上沿**（跌到这个价才算进这一段），文案跟着改过
    assert "观察区上沿" in why and "310" in why


def test_比决策卡还老的成交算无法判定不算违规():
    """**把不知道说成违规，这个指标就没人肯看了。**

    一笔发生在建卡之前的成交，当时根本没有计划可违背。

    （原来这条测的是「压根没有决策卡」那条分支。`decision_fills.card_id` 带
    ON DELETE CASCADE，卡删了登记跟着没，所以那条分支现在只有在数据被外部
    改动过时才到得了 —— 代码里留着当兜底，判据换成走得到的这一条。）
    """
    company_id = _company()
    repository.ensure_decision_card(company_id)
    repository.save_decision_card(company_id, {"bands": BANDS, "position_plan": PLAN})
    repository.record_fill(company_id, 200.0, filled_on=LONG_AGO, shares=100,
                           note="很久以前买的，当时还没有这套东西。")
    discipline = repository.decision_loop_board()["discipline"]
    assert discipline["outside_count"] == 0
    assert discipline["undecidable_count"] == 1
    assert "决策卡建立之前" in discipline["undecidable"][0]["why"]


def test_只判买入_并且把为什么不判卖出说出来():
    """卖出逻辑是一段自由文本，机器判不了。**不判比瞎判好。**

    成交登记现在只登记买入（卖出没有可对照的计划），所以 sell_count 恒为 0——
    但**那句解释必须留着**：一个没有解释的 0 会被读成"我从来没卖过"。
    """
    company_id = _waiting_card()
    _bar("300750", TODAY, 275.0)
    repository.evaluate_decision_triggers()
    repository.record_fill(company_id, 276.0, filled_on=TODAY, shares=200,
                           note="按计划建仓。")
    discipline = repository.decision_loop_board()["discipline"]
    assert discipline["inside_count"] == 1
    assert discipline["sell_count"] == 0
    assert "机器判不了" in discipline["sell_note"]


# ── 首页分组 ────────────────────────────────────────────────────────────────


def test_首页按状态分组而且需要处理的排最前():
    _waiting_card()
    board = repository.decision_loop_board()
    order = [group["state"] for group in board["groups"]]
    assert order[0] == "triggered" and order[1] == "reviewing"
    assert board["groups"][0]["actionable"] is True


def test_还没完成判断的票不会被标成ready():
    """**「我错过了买点」和「我根本还没完成判断」必须分得开。**

    后者根本谈不上错过——这是整套东西里最要紧的一次区分。
    """
    company_id = _company("601138", "工业富联")
    repository.decision_card(company_id)
    board = repository.decision_loop_board()
    item = next(i for group in board["groups"] for i in group["items"]
                if i["company_id"] == company_id)
    assert item["ready"] is False
    assert item["state"] == "discovered"


def test_没进闭环的公司只报个数不自动建卡():
    """一次性把两百多家塞进「待研究」，那一格就再也没人看了。"""
    _company("600519", "贵州茅台")
    _company("000651", "格力电器")
    board = repository.decision_loop_board()
    assert board["total"] == 0
    assert board["not_in_loop"] == 2


# ── 取数层：两个不同的量不许共用一个变量名 ─────────────────────────────────


def test_盈利贡献不会被公告占比改写():
    """**这是个真的发生过的覆盖。**

    `rally_facts` 里「盈利贡献」和「公告后三天占了多少幅度」原来都叫 `share`，
    后者在几十行之后把前者改写了。结果是页面上「窗口内新报告期：没有」
    和「盈利贡献 -8%」同时出现——而按会计恒等式，没有新报告期时
    盈利贡献只能是 0。

    Python 不会为此报任何错，测试也不会红：两个数都是合法的浮点数。
    只有把它们摆在一起看才发现是同一个数。所以这条守卫直接比对这两栏。
    """
    company_id = _company()
    for offset, close in enumerate([100.0, 98.0, 96.0, 99.0, 97.0, 95.0,
                                    94.0, 96.0, 93.0, 92.0, 91.0, 90.0,
                                    92.0, 91.0, 89.0, 88.0, 90.0, 89.0,
                                    87.0, 86.0, 88.0, 87.0, 85.0, 84.0]):
        day = (date.today() - timedelta(days=60 - offset)).isoformat()
        _bar("300750", day, close, high=close + 1, low=close - 1, volume=1000)
    with connection() as conn:
        for offset in (5, 9):
            conn.execute(
                """INSERT INTO company_calendar_events
                   (company_id, category, event_date, title, detail, source, refreshed_at, relevance)
                   VALUES (?, '公告', ?, '关于回购公司股份的进展公告', '', '测试', ?, '高')""",
                (company_id, (date.today() - timedelta(days=60 - offset)).isoformat(), now_iso()))

    view = repository.rally_facts(company_id, 20)
    valuation = view["valuation"]
    assert valuation["report_in_window"] is False
    assert valuation["earnings_share"] == 0.0, "没有新报告期，盈利贡献只能是 0"
    if view["post_event"]:
        assert view["post_event"]["share"] != valuation["earnings_share"] or \
            view["post_event"]["share"] == 0.0, "这两栏又变成同一个数了"


# ── 按代码查涨跌归因：池子外的票 ────────────────────────────────────────────


def _universe(symbol: str, name: str, industry: str, **extra) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO market_universe
               (symbol, name, exchange, board, industry, sw_level1, turnover_rate,
                float_market_cap, pe_ttm, change_20d, report_date, updated_at)
               VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, name, industry, industry, extra.get("turnover", 20.0),
             extra.get("float_cap", 5e9), extra.get("pe", 80.0),
             extra.get("change_20d", 100.0), extra.get("report_date"), now_iso()))


def _universe_series(symbol: str, closes: list[float]) -> None:
    with connection() as conn:
        for offset, close in enumerate(closes):
            day = (date.today() - timedelta(days=len(closes) - offset)).isoformat()
            conn.execute(
                """INSERT INTO universe_valuation_history
                   (symbol, point_date, pe_ttm, pb, source, close)
                   VALUES (?, ?, ?, 3.0, '测试', ?)""",
                (symbol, day, close * 2, close))


def test_不在研究池里的票也查得到():
    """**使用者最想问的那几只按定义就不在池子里**——他要是研究过它们，

    也就不会看不懂了。只能查池内等于这个功能在最需要它的那一刻用不上。
    """
    _universe("600127", "金健米业", "农林牧渔")
    for peer in range(5):
        _universe(f"60012{peer + 2}", f"同行{peer}", "农林牧渔", change_20d=3.0)
    _universe_series("600127", [10.0 * (1.09 ** i) for i in range(22)])

    view = repository.rally_lookup("600127", 20)
    assert view is not None
    assert view["facts"]["ok"] is True
    assert view["facts"]["company_id"] is None
    assert "全市场底座" in view["facts"]["source"]
    assert view["verdict"]["ok"] is True


def test_底座里没有的代码返回空而不是空结论():
    assert repository.rally_lookup("999999", 20) is None


def test_取不到公告时不许判成没有公告():
    """**「查不到」和「没有」是两件事。**

    池子外的票没有公告表。不区分的话，「窗口里没有实质性公告」这条判据会
    白白通过，于是任何一只查不到公告的票都往「情绪驱动」上靠——
    而那正是最需要谨慎的一类判定。跟 `none-has-two-sources` 同一个病。
    """
    _universe("600127", "金健米业", "农林牧渔", turnover=30.0, float_cap=5e9)
    for peer in range(5):
        _universe(f"60012{peer + 2}", f"同行{peer}", "农林牧渔", change_20d=2.0)
    _universe_series("600127", [10.0 * (1.05 ** i) for i in range(22)])

    view = repository.rally_lookup("600127", 20)
    facts = view["facts"]
    assert facts["events_available"] is False
    theme = next(t for t in view["verdict"]["types"] if t["key"] == "theme")
    no_news_check = theme["checks"][2]
    assert no_news_check["ok"] is False, "取不到公告却判成了「确实没有公告」"
    assert "说不出口" in no_news_check["detail"]


def test_少了哪几样要写在返回值里():
    """一份判据不全的结论跟判据齐全的结论长得一样，是最容易误导人的。"""
    _universe("600127", "金健米业", "农林牧渔")
    _universe_series("600127", [10.0 + i for i in range(22)])
    facts = repository.rally_lookup("600127", 20)["facts"]
    assert len(facts["unavailable"]) == 3
    assert facts["volume"]["ratio"] is None, "底座没有成交量，不许拿 0 顶替"
    assert facts["valuation"]["pe_percentile_start"] is None


def test_序列太短就直说算不出来():
    _universe("600127", "金健米业", "农林牧渔")
    _universe_series("600127", [10.0, 11.0])
    view = repository.rally_lookup("600127", 20)
    assert view["facts"]["ok"] is False
    assert "天的收盘价" in view["facts"]["note"]


def test_在池子里且日线够长就走档案那条路():
    """两条路要能自己选对，而不是永远走降级的那条。"""
    company_id = _company("300750", "宁德时代")
    _universe("300750", "宁德时代", "电力设备")
    for offset in range(40):
        day = (date.today() - timedelta(days=40 - offset)).isoformat()
        _bar("300750", day, 300.0 + offset, high=301.0 + offset,
             low=299.0 + offset, volume=1000)
    facts = repository.rally_lookup("300750", 20)["facts"]
    assert facts["company_id"] == company_id
    assert facts.get("source") is None, "有档案有日线，不该降级到底座"
    assert facts["events_available"] is not False


def test_门槛用的波动取自窗口之前那一段():
    """**拿窗口自己的波动算门槛是循环的**：一次大涨把标准差抬上去，

    于是它把自己压到门槛之下，结果是"涨得越猛越判成没事发生"。
    这条用一段「前面很安静、窗口里暴涨」的数据验：
    算出来的 σ 必须是前半段那个小的，不是后半段那个大的。
    """
    company_id = _company()
    quiet_part = [100.0 + (i % 2) * 0.3 for i in range(140)]    # 日波动约 0.3%
    wild_part = [100.0 * (1.09 ** (i + 1)) for i in range(21)]  # 每天涨 9%
    for offset, close in enumerate(quiet_part + wild_part):
        day = (date.today() - timedelta(days=len(quiet_part) + len(wild_part) - offset)).isoformat()
        _bar("300750", day, close, high=close * 1.01, low=close * 0.99, volume=1000)

    facts = repository.rally_facts(company_id, 20)
    sigma = facts["prior_daily_sigma"]
    assert sigma is not None
    assert sigma < 0.02, f"σ={sigma:.4f} —— 看着像把窗口里那段暴涨也算进去了"

    from stock_decision import rally
    verdict = rally.classify(facts)
    assert verdict["primary"] != "quiet", \
        "前面很安静、窗口里翻了几倍，绝不该判成「没什么事发生」"


def test_日线不够长时不硬算波动():
    company_id = _company()
    for offset in range(25):
        day = (date.today() - timedelta(days=25 - offset)).isoformat()
        _bar("300750", day, 100.0 + offset, high=101.0 + offset, low=99.0 + offset, volume=1000)
    facts = repository.rally_facts(company_id, 20)
    assert facts["prior_daily_sigma"] is None, "只有 25 根日线，凑不出窗口之前那一段"


# ── 账本驱动：已经持有的票不许停在研究之前 ──────────────────────────────────


def test_账本里有持仓就把卡片推成持仓中():
    """**这里原来是个没兑现的承诺。**

    `FORBIDDEN_REASONS` 里写着「真买了的话，状态机会把它推成「持仓中」」，
    而代码里根本没有这一段。后果是一只手上实实在在拿着的票（格力 34 笔流水）
    停在「待研究」，因为它缺一份估值。**一套跟账本说的不一样的状态机，
    用两天就没人看了。**
    """
    company_id = _company()
    repository.ensure_decision_card(company_id)
    portfolio = repository.create_portfolio(PortfolioCreate(name="主账户", amount_mode="full"))
    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company_id, side="buy", trade_date=LONG_AGO,
        shares=1500, price=50.2, rationale="这套系统之前就买的，当时没有闭环可走。"))

    result = repository.sync_decision_from_ledger()
    assert result["count"] == 1
    assert result["moved"][0]["to"] == "holding"
    card = repository.decision_card(company_id)
    assert card["state"] == "holding"
    assert "账本" in card["entered_reason"]
    assert card["history"][0]["actor"] == "账本"


def test_持仓清零就推成已清仓():
    company_id = _company()
    portfolio = repository.create_portfolio(PortfolioCreate(name="主账户", amount_mode="full"))
    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company_id, side="buy", trade_date=LONG_AGO,
        shares=1000, price=50.0, rationale="建仓。"))
    repository.sync_decision_from_ledger()
    assert repository.decision_card(company_id)["state"] == "holding"

    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company_id, side="sell", trade_date=YESTERDAY,
        shares=1000, price=60.0, rationale="逻辑走完了，清掉。"))
    result = repository.sync_decision_from_ledger()
    assert result["moved"][0]["to"] == "exited"
    assert repository.decision_card(company_id)["state"] == "exited"


def test_人工点不动持仓中这条边():
    """**「已经持仓」不是一句可以自己宣布的话**，它由流水决定。

    留一个"我说我持仓了"的按钮，纪律统计立刻就废了：
    任何一笔计划外买入，事后把状态一改就变成计划内的。
    """
    company_id = _company()
    portfolio = repository.create_portfolio(PortfolioCreate(name="主账户", amount_mode="full"))
    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company_id, side="buy", trade_date=LONG_AGO,
        shares=100, price=50.0, rationale="买了。"))
    repository.ensure_decision_card(company_id)
    with pytest.raises(LedgerError) as caught:
        repository.move_decision_state(company_id, "holding", "我已经拿着了")
    assert "由账本里的流水决定" in str(caught.value)
    assert repository.decision_card(company_id)["state"] == "discovered"


def test_没有持仓时账本也推不动():
    company_id = _company()
    repository.ensure_decision_card(company_id)
    assert repository.sync_decision_from_ledger()["count"] == 0
    assert repository.decision_card(company_id)["state"] == "discovered"


def test_持仓把卡推成持仓中_不等于那一笔就算计划内():
    """**状态机承认事实，不等于替你把事实说成是计划内的。**

    填了持仓，卡片会被推成「持仓中」；但那笔 330 的成交发生在卡片还停在
    「待研究」的时候，事后的状态推进不该把它追认成计划内 ——
    能追认的话，先买再补状态就永远是满分。
    """
    company_id = _company()
    repository.ensure_decision_card(company_id)
    repository.save_decision_card(company_id, {"bands": BANDS, "position_plan": PLAN})
    repository.record_fill(company_id, 330.0, filled_on=TODAY, shares=100,
                           note="没等到价格，先上了一点。")
    portfolio = repository.create_portfolio(PortfolioCreate(name="主账户", amount_mode="full"))
    repository.set_holding(portfolio["id"], company_id, 100, 330.0)
    repository.sync_decision_from_ledger()
    assert repository.decision_card(company_id)["state"] == "holding"

    discipline = repository.decision_loop_board()["discipline"]
    assert discipline["inside_count"] == 0
    assert discipline["outside_count"] == 1, "推成持仓中之后，这笔就变计划内了？"


def test_扫描按钮同时做账本校正和价格触发():
    """分成两个按钮的话，其中一个永远不会被点——
    而没被点的那个恰恰是让状态机跟账本不脱节的那个。"""
    company_id = _company()
    repository.ensure_decision_card(company_id)
    portfolio = repository.create_portfolio(PortfolioCreate(name="主账户", amount_mode="full"))
    repository.create_trade(portfolio["id"], TradeCreate(
        company_id=company_id, side="buy", trade_date=LONG_AGO,
        shares=100, price=50.0, rationale="买了。"))
    result = repository.evaluate_decision_triggers()
    assert "ledger" in result
    assert result["ledger"]["count"] == 1
    assert repository.decision_card(company_id)["state"] == "holding"


# ── 产业链环节当对照组 ──────────────────────────────────────────────────────


def _member(symbol: str, name: str, chain: str, segment: str) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO chain_segment_members
               (symbol, chain, segment, name, chain_label, stage, segment_label, what,
                source_url, source_title, source_quote, accessed, imported_at)
               VALUES (?, ?, ?, ?, '动力电池', '中游', '电芯', '卷成电芯',
                       'https://example.test/a', '年报', '引句', '2026-09-09', ?)""",
            (symbol, chain, segment, name, now_iso()))


def test_同环节的同行逐家点名():
    """**申万「电力设备」377 家里混着光伏、风电、电网设备。**

    拿它的中位数去问「只有它在跌吗」，答案被稀释掉了；
    而「宁德跌 19%，同环节的比亚迪跌 3.8%、亿纬跌 8%」是一句结结实实的话。
    """
    _universe("300750", "宁德时代", "电力设备", change_20d=-19.0)
    _universe("002594", "比亚迪", "汽车", change_20d=-3.8)
    _universe("300014", "亿纬锂能", "电力设备", change_20d=-8.0)
    for symbol, name in (("300750", "宁德时代"), ("002594", "比亚迪"), ("300014", "亿纬锂能")):
        _member(symbol, name, "battery", "cell")
    _universe_series("300750", [100.0 * (0.99 ** i) for i in range(22)])

    facts = repository.rally_facts_by_symbol("300750", 20)
    groups = facts["chain_peers"]["groups"]
    assert len(groups) == 1
    members = {m["name"]: m["change"] for m in groups[0]["members"]}
    assert members == {"宁德时代": -19.0, "比亚迪": -3.8, "亿纬锂能": -8.0}
    assert groups[0]["peer_count"] == 2, "同行数不算自己"


def test_不足三家只点名不算中位数():
    """两家的中位数只是其中一家，而它会长得跟一个统计量一样。"""
    _universe("300750", "宁德时代", "电力设备", change_20d=-19.0)
    _universe("002594", "比亚迪", "汽车", change_20d=-3.8)
    for symbol, name in (("300750", "宁德时代"), ("002594", "比亚迪")):
        _member(symbol, name, "battery", "cell")
    _universe_series("300750", [100.0 * (0.99 ** i) for i in range(22)])

    chain = repository.rally_facts_by_symbol("300750", 20)["chain_peers"]
    assert chain["best"] is None
    assert chain["groups"][0]["enough"] is False
    assert "不足 3 家" in chain["note"]


def test_不在产业链底图里要明说而不是给个空列表():
    """空列表在页面上跟「同环节没人在动」长得一样。"""
    _universe("000651", "格力电器", "家用电器", change_20d=-3.8)
    _universe_series("000651", [100.0] * 22)
    chain = repository.rally_facts_by_symbol("000651", 20)["chain_peers"]
    assert chain["groups"] == []
    assert "不在产业链底图里" in chain["note"]


def test_同行没有行情时留空不填零():
    """0 会被当成「没怎么动」。"""
    _universe("300750", "宁德时代", "电力设备", change_20d=-19.0)
    for symbol, name in (("300750", "宁德时代"), ("999001", "查无此票")):
        _member(symbol, name, "battery", "cell")
    _universe_series("300750", [100.0] * 22)
    members = repository.rally_facts_by_symbol("300750", 20)["chain_peers"]["groups"][0]["members"]
    ghost = next(m for m in members if m["symbol"] == "999001")
    assert ghost["change"] is None


def test_窗口不是五二十六十时说清楚给不出():
    _universe("300750", "宁德时代", "电力设备", change_20d=-19.0)
    _member("300750", "宁德时代", "battery", "cell")
    _universe_series("300750", [100.0] * 22)
    chain = repository.rally_facts_by_symbol("300750", 10)["chain_peers"]
    assert chain["groups"] == []
    assert "5 / 20 / 60" in chain["note"]


# ── 这一笔的下单计划 ────────────────────────────────────────────────────────


def test_下单计划存得下也校验得住():
    company_id = _company()
    repository.save_decision_card(company_id, {
        "order_plan": {"price": 300, "fraction": "1/3", "why_now": "叙事被放大"}})
    card = repository.decision_card(company_id)
    assert card["order_plan"]["price"] == 300
    assert {g["key"]: g["ok"] for g in card["guards"]}["order_plan"] is True

    with pytest.raises(LedgerError) as caught:
        repository.save_decision_card(company_id, {"order_plan": {"price": 300}})
    assert "几分之几" in str(caught.value)


def test_成交之后拿计划价对账():
    """「计划 300、成交 302」和「计划 300、成交 330」都在价格带里、都算计划内，
    **但后者值得你自己看一眼**。"""
    company_id = _waiting_card()
    _bar("300750", TODAY, 275.0)
    repository.evaluate_decision_triggers()
    repository.save_decision_card(company_id, {
        "bands": BANDS, "position_plan": PLAN,
        "order_plan": {"price": 276, "fraction": "1/3"}})
    repository.move_decision_state(company_id, "committed", "复核完基本面没变，决定买第一笔")
    repository.record_fill(company_id, 289.0, filled_on=TODAY, shares=100,
                           note="挂单没成，抬价买的。")

    discipline = repository.decision_loop_board()["discipline"]
    assert discipline["inside_count"] == 1, "待成交里成交的应当算计划内"
    row = discipline["inside"][0]
    assert row["planned_price"] == 276
    assert row["price_drift"] == pytest.approx(4.71, abs=0.01), "成交价比计划高 4.7%"
    assert row["fraction"] == "1/3"
