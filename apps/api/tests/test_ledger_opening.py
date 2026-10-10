"""期初持仓与整段清空。

这两件事是一对：流水账烂掉之后，**逐条修是修不回来的**（缺的那几笔你也想不起来了），
唯一能回到"账对得上"的路是整段删掉 + 一条期初持仓重新声明现在有多少。
所以清空删不干净、或者期初持仓没覆盖住旧流水，都会让账本悄悄错着而不报错。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_decision.repository import (
    create_company, create_portfolio, create_trade, get_portfolio,
    purge_company_trades,
)
from stock_decision.schemas import CompanyInput, PortfolioCreate, TradeCreate


def _company(symbol: str, name: str) -> int:
    return create_company(CompanyInput(symbol=symbol, name=name, industry="测试"))["id"]


def _portfolio(name: str = "对账组合") -> int:
    # 组合名在 (user_id, name) 上有唯一约束，同一个测试里建两个要给不同的名字。
    return create_portfolio(PortfolioCreate(name=name, amount_mode="full"))["id"]


def _position(portfolio_id: int, company_id: int) -> dict | None:
    detail = get_portfolio(portfolio_id)
    assert detail is not None
    for row in detail["positions"]:
        if row["company_id"] == company_id:
            return row
    return None


def test_opening_replaces_earlier_trades_instead_of_adding():
    """期初持仓**覆盖**旧流水，不是加上去。

    这是最容易静默出错的一处：加上去的话持仓凭空翻倍，页面不会报任何错，
    只是成本和市值一起虚高——而那恰恰是这个功能要修的毛病。
    """
    portfolio = _portfolio()
    company = _company("000651", "格力电器")
    old = date.today() - timedelta(days=400)
    create_trade(portfolio, TradeCreate(
        company_id=company, side="buy", trade_date=old,
        shares=1000, price=40.0, rationale="两年前的老流水"))
    create_trade(portfolio, TradeCreate(
        company_id=company, side="buy", trade_date=old + timedelta(days=10),
        shares=2000, price=45.0, rationale="又买了一笔"))

    before = _position(portfolio, company)
    assert before is not None and before["shares"] == pytest.approx(3000)

    create_trade(portfolio, TradeCreate(
        company_id=company, side="opening", trade_date=date.today(),
        shares=4700, price=41.74, rationale=""))

    after = _position(portfolio, company)
    assert after is not None
    # 4700，不是 3000 + 4700 = 7700。
    assert after["shares"] == pytest.approx(4700)
    assert after["cost_value"] == pytest.approx(4700 * 41.74, rel=1e-6)
    assert after["average_cost"] == pytest.approx(41.74, rel=1e-6)


def test_opening_is_ordered_by_date_not_by_query_order():
    """**顺序由 _accumulate_positions 里那句 sorted 保证，不是调用处。**

    调用处恰恰不能指望：list_portfolios 和 _holdings_exposure 没写 ORDER BY，
    get_portfolio 和 _company_ledger 写的是 DESC。真按查询顺序结算，
    期初持仓会先算、旧买入再加上去，持仓翻倍且不报错。

    这里把期初持仓记在**中间**：它之后的买入应当加在它上面，之前的被它抹掉。
    """
    portfolio = _portfolio()
    company = _company("601318", "中国平安")
    day = date.today() - timedelta(days=30)
    create_trade(portfolio, TradeCreate(
        company_id=company, side="buy", trade_date=day,
        shares=800, price=50.0, rationale="期初之前，应当被抹掉"))
    create_trade(portfolio, TradeCreate(
        company_id=company, side="opening", trade_date=day + timedelta(days=10),
        shares=600, price=52.09, rationale=""))
    create_trade(portfolio, TradeCreate(
        company_id=company, side="buy", trade_date=day + timedelta(days=20),
        shares=100, price=54.0, rationale="期初之后，应当加上去"))

    position = _position(portfolio, company)
    assert position is not None
    assert position["shares"] == pytest.approx(700)   # 600 + 100，不含被抹掉的 800
    assert position["cost_value"] == pytest.approx(600 * 52.09 + 100 * 54.0, rel=1e-6)


def test_opening_keeps_realized_pnl_and_dividends():
    """期初持仓只重述**现在持有什么**，无权否认历史上真收到过的钱。

    把已实现盈亏和分红一起清掉的话，"这笔投资到底赚没赚"就再也算不出来了。
    """
    portfolio = _portfolio()
    company = _company("000333", "美的集团")
    day = date.today() - timedelta(days=200)
    create_trade(portfolio, TradeCreate(
        company_id=company, side="buy", trade_date=day,
        shares=1000, price=50.0, rationale="建仓"))
    create_trade(portfolio, TradeCreate(
        company_id=company, side="sell", trade_date=day + timedelta(days=5),
        shares=500, price=60.0, rationale="卖一半"))
    create_trade(portfolio, TradeCreate(
        company_id=company, side="dividend", trade_date=day + timedelta(days=10),
        cash_amount=1200.0, rationale=""))
    create_trade(portfolio, TradeCreate(
        company_id=company, side="opening", trade_date=date.today(),
        shares=300, price=55.0, rationale=""))

    position = _position(portfolio, company)
    assert position is not None
    assert position["shares"] == pytest.approx(300)
    assert position["realized_pnl"] == pytest.approx(500 * (60.0 - 50.0))
    assert position["dividend_income"] == pytest.approx(1200.0)


@pytest.mark.parametrize("shares, price, expected", [
    (None, 41.74, "股"),      # 只给均价
    (4700, None, "成本价"),   # 只给股数
    (4700, 0, "成本价"),      # 成本价 0 会让账面显示无穷大浮盈
])
def test_opening_refuses_half_filled(shares, price, expected):
    """两个数缺一不可。**这个守卫必须证明能失败**：只给股数不给均价，
    成本就是 0，浮盈会显示成无穷大。"""
    portfolio = _portfolio()
    company = _company("600519", "贵州茅台")
    with pytest.raises(Exception) as exc:
        create_trade(portfolio, TradeCreate(
            company_id=company, side="opening", trade_date=date.today(),
            shares=shares, price=price, rationale=""))
    assert expected in str(exc.value)


def test_opening_needs_no_rationale():
    """期初持仓不是一个决定，是一次对账——没有"当时的想法"可写。

    买卖必须写理由（事后补的理由已经不是当时的想法），但这条规则套在对账上
    只会逼人编一句废话。
    """
    portfolio = _portfolio()
    company = _company("002594", "比亚迪")
    trade = create_trade(portfolio, TradeCreate(
        company_id=company, side="opening", trade_date=date.today(),
        shares=100, price=300.0, rationale=""))
    assert trade is not None
    assert "对账" in trade["rationale"]


def test_purge_deletes_only_the_named_companies():
    """只清点名的那几家。**两只票只烂了一只，清空整个组合会把好的也赔进去。**"""
    portfolio = _portfolio()
    keep = _company("601318", "中国平安")
    drop = _company("000651", "格力电器")
    day = date.today() - timedelta(days=100)
    for i in range(3):
        create_trade(portfolio, TradeCreate(
            company_id=drop, side="buy", trade_date=day + timedelta(days=i),
            shares=100, price=40.0, rationale="要删的"))
    create_trade(portfolio, TradeCreate(
        company_id=keep, side="buy", trade_date=day,
        shares=600, price=52.0, rationale="要留的"))

    result = purge_company_trades(portfolio, [drop])
    assert result["deleted"] == 3
    assert [c["company_id"] for c in result["companies"]] == [drop]
    assert result["companies"][0]["trades"] == 3

    detail = get_portfolio(portfolio)
    assert detail is not None
    assert [p["company_id"] for p in detail["positions"]] == [keep]
    assert all(t["company_id"] == keep for t in detail["trades"])


def test_purge_reports_zero_when_nothing_matched():
    """**删 0 条和删 34 条在界面上长得一样。**

    所以条数必须回给界面：选错组合、或者 company_ids 里是别人的 id 时，
    账本不会变，而人会以为删过了。
    """
    portfolio = _portfolio("这一个有流水")
    other = _portfolio("这一个是空的")
    company = _company("000651", "格力电器")
    create_trade(portfolio, TradeCreate(
        company_id=company, side="buy", trade_date=date.today(),
        shares=100, price=40.0, rationale="在第一个组合里"))

    result = purge_company_trades(other, [company])
    assert result["deleted"] == 0
    assert result["companies"] == []

    detail = get_portfolio(portfolio)
    assert detail is not None and len(detail["trades"]) == 1


def test_purge_then_opening_is_the_whole_repair_path():
    """这两件事合起来才是完整的修法，单独任何一件都修不好一本烂账。"""
    portfolio = _portfolio()
    company = _company("000651", "格力电器")
    day = date.today() - timedelta(days=700)
    for i in range(12):
        create_trade(portfolio, TradeCreate(
            company_id=company, side="buy", trade_date=day + timedelta(days=i * 20),
            shares=100, price=40.0 + i, rationale="两年前记的，后来就断了"))

    assert purge_company_trades(portfolio, [company])["deleted"] == 12
    create_trade(portfolio, TradeCreate(
        company_id=company, side="opening", trade_date=date.today(),
        shares=4700, price=41.74, rationale=""))

    position = _position(portfolio, company)
    assert position is not None
    assert position["shares"] == pytest.approx(4700)
    assert position["average_cost"] == pytest.approx(41.74, rel=1e-6)
