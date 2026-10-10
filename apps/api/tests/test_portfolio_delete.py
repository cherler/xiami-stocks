"""删组合。

此前根本删不掉（`/portfolios/{id}` 只有 GET 和 PATCH），于是一个手滑建出来的
空组合会永远杵在页签上。使用者 2026-09-23 的原话：「比例组合还是删不掉」。
"""

from __future__ import annotations

import pytest

from stock_decision import access
from stock_decision.repository import (
    create_company, create_portfolio, delete_portfolio, get_portfolio,
    list_portfolios, set_holding,
)
from stock_decision.schemas import CompanyInput, PortfolioCreate


def _portfolio(name: str) -> int:
    return create_portfolio(PortfolioCreate(name=name, amount_mode="full"))["id"]


def test_删掉空组合():
    keep, drop = _portfolio("留着"), _portfolio("删掉")
    result = delete_portfolio(drop)
    assert result == {"deleted": True, "name": "删掉", "holdings": 0}
    assert [p["id"] for p in list_portfolios()] == [keep]


def test_有持仓的组合也能删_但要说清带走了多少():
    """**不挡"里面还有东西"**：真要删一个有持仓的组合是合法意图，
    挡住只会逼人先一只只删干净再回来。

    但条数必须回给界面——删一个空组合和删掉一个装满记录的，长得一模一样。
    """
    portfolio = _portfolio("有货")
    gree = create_company(CompanyInput(symbol="000651", name="格力电器", industry="家电"))["id"]
    pingan = create_company(CompanyInput(symbol="601318", name="中国平安", industry="保险"))["id"]
    set_holding(portfolio, gree, 4700, 41.74)
    set_holding(portfolio, gree, 5000, 41.20)      # 改过一次，底下两行历史
    set_holding(portfolio, pingan, 600, 52.09)

    result = delete_portfolio(portfolio)
    assert result["deleted"] is True
    assert result["holdings"] == 2, "带走了几只没说对"
    assert get_portfolio(portfolio) is None


def test_删不存在的组合不算成功():
    """**静默成功会掩盖"删错了对象"。**"""
    assert delete_portfolio(999999) == {"deleted": False, "name": "", "holdings": 0}


def test_删一个不碰另一个():
    a, b = _portfolio("甲"), _portfolio("乙")
    company = create_company(CompanyInput(symbol="000651", name="格力电器", industry="家电"))["id"]
    set_holding(a, company, 100, 40.0)
    set_holding(b, company, 200, 41.0)

    delete_portfolio(a)
    left = get_portfolio(b)
    assert left is not None
    assert left["positions"][0]["shares"] == pytest.approx(200), "删甲把乙的持仓也动了"


def test_删掉最后一个组合也放行():
    """账本空着是一种合法状态（页面会说「还没有组合」），
    拦住它等于强迫人留一个自己不想要的东西。"""
    only = _portfolio("唯一一个")
    assert delete_portfolio(only)["deleted"] is True
    assert list_portfolios() == []
    assert list_portfolios() == [], "再次打开页面也不能自动建回主组合"
    created = _portfolio("重新开始")
    assert [p["id"] for p in list_portfolios()] == [created]


def test_清空组合不会影响其他用户的首次访问():
    token = access.set_scope("u_alice")
    try:
        only = list_portfolios()[0]["id"]
        assert delete_portfolio(only)["deleted"] is True
        assert list_portfolios() == []
        access.set_scope("u_bob")
        assert [p["name"] for p in list_portfolios()] == ["主组合"]
        access.set_scope("u_alice")
        assert list_portfolios() == []
    finally:
        access.reset_scope(token)
