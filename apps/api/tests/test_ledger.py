"""账本的五种记录类型与两种口径。

这些数字是手算过的。写死期望值而不是"跑一遍看看对不对"——
账本算错的后果是所有复盘结论都建立在错的基础上，而且从页面上完全看不出来。
"""

import pytest

from stock_decision.repository import _accumulate_positions, _trade_amount


def trade(**kw):
    base = {"id": kw.pop("id", 1), "company_id": 1, "trade_date": "2026-01-01",
            "shares": None, "price": None, "fee": 0.0, "weight_percent": None,
            "cash_amount": None, "review_due": None}
    base.update(kw)
    return base


def test_买入卖出的成本与已实现盈亏():
    trades = [
        trade(id=1, side="buy", trade_date="2026-01-01", shares=1000, price=10.0, fee=5.0),
        trade(id=2, side="buy", trade_date="2026-02-01", shares=1000, price=12.0, fee=5.0),
        trade(id=3, side="sell", trade_date="2026-03-01", shares=500, price=15.0, fee=5.0),
    ]
    state = _accumulate_positions(trades)[1]
    # 成本 = 10*1000+5 + 12*1000+5 = 22010，均价 11.005
    # 卖 500 股：500*(15 - 11.005) - 5 = 1992.5
    assert state["shares"] == 1500
    assert round(state["realized_pnl"], 2) == 1992.5
    assert round(state["cost_value"], 2) == round(22010 - 11.005 * 500, 2)


def test_送股只加股数不加成本_均价因此被摊薄():
    """不做这一步的话，除权后价格腰斩而成本不动，账面会凭空显示巨亏。"""
    trades = [
        trade(id=1, side="buy", shares=1000, price=20.0, fee=0.0),
        trade(id=2, side="bonus", trade_date="2026-06-01", shares=1000),   # 10 送 10
    ]
    state = _accumulate_positions(trades)[1]
    assert state["shares"] == 2000
    assert state["cost_value"] == 20000            # 投入的钱一分没变
    assert state["cost_value"] / state["shares"] == 10.0   # 均价自然减半，与除权后的价格对得上


def test_分红不进已实现盈亏而是单独一栏():
    """卖出赚的差价与拿着收的现金是两种钱，合并之后就看不出这笔投资靠什么回报。"""
    trades = [
        trade(id=1, side="buy", shares=1000, price=10.0, fee=0.0),
        trade(id=2, side="dividend", trade_date="2026-07-01", cash_amount=800.0, fee=0.0),
    ]
    state = _accumulate_positions(trades)[1]
    assert state["dividend_income"] == 800.0
    assert state["realized_pnl"] == 0.0            # 没卖过，就不该有已实现差价
    assert state["shares"] == 1000                 # 分红不改变股数
    assert state["cost_value"] == 10000            # 也不改变成本（券商口径）


def test_配股按买入计成本():
    trades = [
        trade(id=1, side="buy", shares=1000, price=10.0, fee=0.0),
        trade(id=2, side="rights", trade_date="2026-05-01", shares=200, price=7.0, fee=1.0),
    ]
    state = _accumulate_positions(trades)[1]
    assert state["shares"] == 1200
    assert state["cost_value"] == 10000 + 200 * 7 + 1


def test_比例口径只留最后一次的仓位占比():
    trades = [
        trade(id=1, side="buy", trade_date="2026-01-01", weight_percent=10.0),
        trade(id=2, side="buy", trade_date="2026-02-01", weight_percent=18.0),
    ]
    state = _accumulate_positions(trades)[1]
    assert state["weight_percent"] == 18.0
    assert state["cost_value"] == 0.0              # 没有金额，就不该凭空造出成本


def test_没有金额时现金流是未知而不是零():
    """0 会被读成「这笔没花钱」，而事实是「我们故意没记金额」——含义相反。"""
    assert _trade_amount(trade(side="buy", weight_percent=10.0)) is None
    assert _trade_amount(trade(side="buy", shares=100, price=10.0, fee=5.0)) == 1005.0
    assert _trade_amount(trade(side="sell", shares=100, price=10.0, fee=5.0)) == 995.0
    assert _trade_amount(trade(side="dividend", cash_amount=800.0, fee=0.0)) == 800.0
    assert _trade_amount(trade(side="bonus", shares=100, price=0.0)) == 0.0


def test_卖出后总回报率的分母是投入过的本金():
    """只用当前成本当分母，卖掉一半之后收益率会凭空翻倍。"""
    from stock_decision.repository import _total_return_percent

    position = {"unrealized_pnl": 500.0, "realized_pnl": 1000.0, "dividend_income": 200.0,
                "cost_value": 5000.0, "realized_cost": 5000.0}
    # (500 + 1000 + 200) / (5000 + 5000) = 17%
    assert _total_return_percent(position) == 17.0
    # 若错误地只用当前成本，会得到 34%
    assert _total_return_percent({**position, "realized_cost": 0.0}) == 34.0


def test_年度门槛只能配年报口径的字段():
    """本仓踩过的坑：底座里的 roe 来自最新报告期（眼下是一季报，中位数 1.03%），
    而策略写的「ROE ≥ 15%」是年度概念。两者一比，全市场只有 21 只能过——
    看上去像「条件严格」，实际是口径错了。换成年报口径后同一条件命中 289 只。

    所以：凡是年度概念的门槛，字段一律用 annual_ 前缀那一支。这条要守住。
    """
    from stock_decision.strategies import PRESETS

    ANNUAL_CONCEPTS = {"roe", "gross_margin"}
    offenders = []
    for strategy in PRESETS:
        for rule in strategy.rules:
            if rule.field in ANNUAL_CONCEPTS:
                offenders.append(f"{strategy.key}: {rule.field}")
        if strategy.sort_field in ANNUAL_CONCEPTS:
            offenders.append(f"{strategy.key}: sort_field={strategy.sort_field}")
    assert not offenders, f"这些地方拿单季比率去比年度门槛：{offenders}"


def test_五套预置策略都是可用的():
    """股息现金流型曾经因为「底座里没有股息率」被关着，而那个结论是错的——
    东财 datacenter 的分红送配一直能取到，只是被「东财拿不到数据」这个
    笼统印象挡住了。可用性要按接口分别验，不能按域名一刀切。"""
    from stock_decision.strategies import PRESETS

    blocked = [s.key for s in PRESETS if not s.available]
    assert not blocked, f"这些策略仍不可用：{blocked}"


def test_a_trade_can_be_deleted():
    """**此前删不掉，而逻辑、报告、产业链、策略都能删。**

    交易恰恰最需要能删：手记会记错组合、也会记重。
    删不掉的唯一补救是记一笔反向交易去抵消——那是往账本里写一笔
    **从未发生过的事**，比留着错的更糟。
    """
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    portfolio = client.post("/api/v1/portfolios",
                            json={"name": "能删吗", "amount_mode": "full"}).json()
    company = client.post("/api/v1/companies", json={
        "symbol": "000651", "name": "格力电器", "industry": "白色家电"}).json()
    trade = client.post(f"/api/v1/portfolios/{portfolio['id']}/trades", json={
        "company_id": company["id"], "side": "buy", "trade_date": "2026-01-05",
        "shares": 500, "price": 40.0, "fee": 5.0, "rationale": "记错组合的一笔"}).json()

    before = client.get(f"/api/v1/portfolios/{portfolio['id']}").json()
    assert before["position_count"] == 1

    assert client.delete(f"/api/v1/trades/{trade['id']}").status_code == 204
    after = client.get(f"/api/v1/portfolios/{portfolio['id']}").json()
    assert after["trade_count"] == 0
    assert after["position_count"] == 0, "删掉之后持仓要跟着重算"
    # 删第二次是 404，不是静默成功——静默成功会掩盖"删错了对象"
    assert client.delete(f"/api/v1/trades/{trade['id']}").status_code == 404


def test_只记仓位的持仓_不能被显示成已清仓(monkeypatch: pytest.MonkeyPatch) -> None:
    """**使用者真撞上了这一幕**：他给格力记了 50% 仓位和成本价 40.86，
    页面顶上写着「已清仓」，合计 ¥0.00、浮动盈亏 —。

    原因是公司页那条路只看 shares，而仓位口径按设计就不记股数（shares 恒为 0）。
    组合页早就处理了这件事（`_is_open` 会看 weight_percent），公司页一直漏着。

    「清仓与否」不该由系统从 shares 猜——仓位口径下它根本无从判断。
    所以账本要把口径带出去，让页面显示「仓位 50%」，而清仓由用户显式记一条 0%。
    """
    import asyncio

    from tests.test_api import _seed_universe, _universe_row, request

    _seed_universe(monkeypatch, [_universe_row("000651", "格力电器")])
    company = asyncio.run(request("POST", "/api/v1/companies",
                                  {"symbol": "000651", "name": "格力电器", "industry": "家电"})).json()
    portfolio = asyncio.run(request("POST", "/api/v1/portfolios", {
        "name": "研究持仓", "objective": "只记仓位", "amount_mode": "ratio"})).json()
    created = asyncio.run(request("POST", f"/api/v1/portfolios/{portfolio['id']}/trades", {
        "company_id": company["id"], "side": "buy", "trade_date": "2026-08-13",
        "weight_percent": 50, "price": 40.86, "rationale": "持仓快照（非交易流水）"}))
    assert created.status_code in (200, 201), created.text

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    ledger = detail["ledger"]
    assert ledger is not None
    assert ledger["shares"] == 0, "仓位口径本来就不记股数"
    # 关键：口径和仓位要能被前端看见，否则它只能拿 shares 判断，然后写出「已清仓」
    assert ledger["amount_mode"] == "ratio"
    assert ledger["weight_percent"] == 50

    # 显式清仓：记一条 0%，这时才是真的清仓
    asyncio.run(request("POST", f"/api/v1/portfolios/{portfolio['id']}/trades", {
        "company_id": company["id"], "side": "sell", "trade_date": "2026-08-14",
        "weight_percent": 0, "rationale": "标记已清仓（持仓快照）"}))
    after = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()["ledger"]
    assert after["weight_percent"] == 0
