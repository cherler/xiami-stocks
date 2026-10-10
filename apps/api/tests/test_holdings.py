"""持仓：一只票一行，两个数，只有新增和更新。

使用者 2026-09-23 定的模型，原话：

> 持仓：只记持有股票数，只有一个数，新增和更新。
> 价格也是一个更新（采用成本价，更新）。

这套东西最危险的坏法是**更新变成加仓**：填 5000 得到 9700，页面不报任何错，
只是持仓和市值一起虚高。旧的「添加持仓」就是这么坏的（它记的是一笔 buy）。
"""

from __future__ import annotations

import pytest

from stock_decision.repository import (
    LedgerError, create_company, create_portfolio, drop_holding, get_portfolio, set_holding,
)
from stock_decision.schemas import CompanyInput, PortfolioCreate


def _company(symbol: str, name: str) -> int:
    return create_company(CompanyInput(symbol=symbol, name=name, industry="测试"))["id"]


def _portfolio(name: str = "我的持仓") -> int:
    return create_portfolio(PortfolioCreate(name=name, amount_mode="full"))["id"]


def _rows(portfolio_id: int) -> dict[int, dict]:
    detail = get_portfolio(portfolio_id)
    assert detail is not None
    return {row["company_id"]: row for row in detail["positions"]}


def test_新增一只():
    portfolio, company = _portfolio(), _company("000651", "格力电器")
    set_holding(portfolio, company, 4700, 41.74)
    row = _rows(portfolio)[company]
    assert row["shares"] == pytest.approx(4700)
    assert row["average_cost"] == pytest.approx(41.74, rel=1e-6)


def test_更新是覆盖不是加仓():
    """**这是整套模型最要紧的一条。**

    填 5000 就是 5000，不是 4700 + 5000。记成加仓的话页面不报任何错，
    只是持仓和成本一起翻倍——旧的「添加持仓」就是这么坏的（它记一笔 buy）。
    """
    portfolio, company = _portfolio(), _company("000651", "格力电器")
    set_holding(portfolio, company, 4700, 41.74)
    set_holding(portfolio, company, 5000, 41.20)

    row = _rows(portfolio)[company]
    assert row["shares"] == pytest.approx(5000), "更新变成了加仓"
    assert row["average_cost"] == pytest.approx(41.20, rel=1e-6)


def test_同一组数改两次还是那个数():
    """幂等。接口用 PUT 就是在承诺这件事——点两次不等于买了两次。"""
    portfolio, company = _portfolio(), _company("601318", "中国平安")
    for _ in range(3):
        set_holding(portfolio, company, 600, 52.09)
    row = _rows(portfolio)[company]
    assert row["shares"] == pytest.approx(600)


def test_改一只不碰另一只():
    portfolio = _portfolio()
    gree, pingan = _company("000651", "格力电器"), _company("601318", "中国平安")
    set_holding(portfolio, gree, 4700, 41.74)
    set_holding(portfolio, pingan, 600, 52.09)
    set_holding(portfolio, gree, 5000, 41.20)

    rows = _rows(portfolio)
    assert rows[gree]["shares"] == pytest.approx(5000)
    assert rows[pingan]["shares"] == pytest.approx(600), "改格力把平安也动了"


@pytest.mark.parametrize("shares, cost, expected", [
    (0, 41.74, "股"),
    (-100, 41.74, "股"),
    (4700, 0, "成本价"),
    (4700, -1, "成本价"),
])
def test_两个数都必须大于零(shares, cost, expected):
    """**成本价填 0 会让浮盈显示成无穷大。** 守卫要能真的拦住它。"""
    portfolio, company = _portfolio(), _company("000651", "格力电器")
    with pytest.raises(Exception) as exc:
        set_holding(portfolio, company, shares, cost)
    assert expected in str(exc.value) or "greater than" in str(exc.value)


def test_删掉一只连历史一起删():
    """删除不是"记一笔卖出"。这个模型里没有交易，只有"现在持有什么"。"""
    portfolio = _portfolio()
    gree, pingan = _company("000651", "格力电器"), _company("601318", "中国平安")
    set_holding(portfolio, gree, 4700, 41.74)
    set_holding(portfolio, gree, 5000, 41.20)      # 改过一次，底下有两行历史
    set_holding(portfolio, pingan, 600, 52.09)

    result = drop_holding(portfolio, gree)
    assert result["deleted"] == 2, "历史没删干净"

    rows = _rows(portfolio)
    assert gree not in rows
    assert pingan in rows, "删格力把平安也删了"


def test_删一只不存在的返回零条():
    """**删 0 条和删 2 条在界面上长得一样。** 所以条数必须如实返回，
    否则选错组合时人会以为已经删过了。"""
    portfolio, company = _portfolio(), _company("000651", "格力电器")
    assert drop_holding(portfolio, company)["deleted"] == 0


def test_改持仓会留下历史():
    """**副作用是好事**：你上次写的是多少还查得到。

    页面上不显示这些行（那是实现细节），但它们在库里，
    所以"我什么时候把成本价从 43 改成 41.74 的"是查得回来的。
    """
    portfolio, company = _portfolio(), _company("000651", "格力电器")
    set_holding(portfolio, company, 4700, 43.18)
    set_holding(portfolio, company, 4700, 41.74)

    detail = get_portfolio(portfolio)
    assert detail is not None
    mine = [t for t in detail["trades"] if t["company_id"] == company]
    assert len(mine) == 2
    assert {t["side"] for t in mine} == {"opening"}
    assert sorted(t["price"] for t in mine) == pytest.approx([41.74, 43.18])


def test_守卫看到的持仓和持仓表看到的是同一个数():
    """**同一个量不许有两份算法。**

    `_guard_facts` 原来自己按 side 手算一遍（buy 加、sell 减、bonus 加），
    而 `_accumulate_positions` 是另一份。2026-09-24 加 `opening` 时立刻炸出来：
    持仓表显示 4700 股，而「账本里有持仓」那道守卫是 False，
    卡片永远推不到「持仓中」—— **不报错，只是那一格永远进不去。**

    现在两边都走 `_accumulate_positions`。这条判据钉的就是"只有一份"。
    """
    from stock_decision.database import connection
    from stock_decision.repository import _guard_facts

    portfolio, company = _portfolio(), _company("000651", "格力电器")
    set_holding(portfolio, company, 4700, 41.74)

    assert _rows(portfolio)[company]["shares"] == pytest.approx(4700)
    with connection() as conn:
        facts = _guard_facts(conn, company, None)
    assert facts["position"] is True, "持仓表看得见，守卫看不见"
    assert facts["no_position"] is False


def test_填了持仓就会被拉进决策闭环():
    """手上拿着的票必须在闭环里。

    自动建卡那条查询原来只认 `side = 'buy'`，而新模型写的是 `opening` ——
    只认 buy 的话，一只你真拿着的票不会被拉进来，而且不报错。
    """
    from stock_decision import repository

    portfolio, company = _portfolio(), _company("000651", "格力电器")
    set_holding(portfolio, company, 4700, 41.74)

    result = repository.sync_decision_from_ledger()
    assert result["count"] >= 1
    card = repository.decision_card(company)
    assert card is not None and card["state"] == "holding"
