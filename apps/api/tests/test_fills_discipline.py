"""成交登记，以及靠它活着的「计划内 / 计划外」。

## 为什么会有这个文件

持仓 2026-09-23 改成「只记股数和成本价」之后，账本里**再也不会出现 buy 流水**。
而 `_plan_discipline` 原来查的就是 `trades WHERE side IN ('buy','sell')` ——
那个指标会永久变成 0/0，**而且不报错**：页面上看起来只是"你还没交易过"。

它是使用者第一天提的那个闭环存在的唯一理由，所以换了数据源：
成交登记挪到决策卡上（`decision_fills`），在真正下单的那一刻填一次。

## 这里守的三件事

1. 登记之后指标**真的动**（换源换错了的话它会一直是 0，安静得很）
2. 计划价用的是**登记当时的快照**，不是事后现查卡片
3. 计划内 / 计划外 / 无法判定 三种结论都分得出来
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_decision import repository
from stock_decision.repository import LedgerError
from stock_decision.schemas import CompanyInput, ThesisCreate

BANDS = {"watch": 310.0, "fair": 300.0, "ideal": 280.0, "extreme": 270.0}
PLAN = {"total_percent": 20, "first_percent": 7}
ORDER = {"price": 300, "fraction": "1/3"}


def _armed_card(symbol: str = "300750", name: str = "宁德时代") -> int:
    """一张走到「触发检查」的卡 —— 计划内判定要求当时在这一格。"""
    company = repository.create_company(
        CompanyInput(symbol=symbol, name=name, industry="电池"))["id"]
    repository.create_thesis(company, ThesisCreate(
        claim="好公司遇到暂时性麻烦", counter_condition="份额连续两季下降",
        next_review_trigger="下一期季报"))
    # **三个情景要一起存**（save_valuation 自己会拦）。没有估值的话
    # 「等待价格」是一条禁边 —— 一个没有估值的买点只是一个你喜欢的数字。
    repository.save_valuation(company, {
        "years": 5, "discount_rate": 10,
        "scenarios": [
            {"key": "bear", "revenue_growth": -5.0, "net_margin": 8.0, "exit_pe": 12.0},
            {"key": "base", "revenue_growth": 8.0, "net_margin": 12.0, "exit_pe": 18.0},
            {"key": "bull", "revenue_growth": 18.0, "net_margin": 15.0, "exit_pe": 25.0},
        ],
        "note": "测试用"})
    repository.save_decision_card(company, {
        "watch_reason": "去宁德化被叙事放大",
        "bands": BANDS, "position_plan": PLAN, "order_plan": ORDER})
    # **一格一格走。** 待研究 → 等待价格 是条禁边（没估值的买点只是一个
    # 你喜欢的数字），不能跳。
    repository.move_decision_state(company, "researching", "")
    repository.move_decision_state(company, "valued", "")
    repository.move_decision_state(company, "waiting", "")
    repository.move_decision_state(company, "triggered", "价格进了观察区")
    return company


def _discipline() -> dict:
    return repository.decision_loop_board()["discipline"]


def test_登记之前这个指标是零():
    """**前提要钉住。** 不钉的话下一条判据"登记之后变成 1"
    可能只是因为库里本来就有东西。"""
    _armed_card()
    d = _discipline()
    assert d["inside_count"] == 0 and d["outside_count"] == 0
    assert d["discipline_rate"] is None


def test_带内成交算计划内_并且指标真的动了():
    """换源换错了的话这个数会一直是 0 —— 安静得很，页面上像"你还没交易过"。"""
    company = _armed_card()
    repository.record_fill(company, 302.0, shares=100)

    d = _discipline()
    assert d["inside_count"] == 1, "登记了成交，计划内却还是 0 —— 指标没接上"
    assert d["outside_count"] == 0
    assert d["discipline_rate"] == 1.0
    row = d["inside"][0]
    # 302 落在观察区：合理区上沿是 300，302 比它贵，所以还没进合理区。
    # **"计划内"不等于"买得便宜"** —— 它只说明你按自己写下的规矩动了手。
    assert row["band_label"] == "观察区"
    assert row["planned_price"] == 300


def test_带外成交算计划外_并说清为什么():
    """330 高于观察区上沿 310 —— 不在任何一段里。"""
    company = _armed_card()
    repository.record_fill(company, 330.0)

    d = _discipline()
    assert d["outside_count"] == 1
    assert "高于观察区上沿" in d["outside"][0]["why"]


def test_计划价用的是登记当时的快照():
    """**卡片上的计划价之后会被改，而"我当时计划的是多少"是这条记录的全部意义。**

    改了计划价之后回头看，旧那笔的对账必须仍然按旧计划算 ——
    否则你可以事后把计划价改成成交价，把任何一笔都变成"完美执行"。
    """
    company = _armed_card()
    repository.record_fill(company, 302.0)

    # 事后把计划价改成 302，想让那笔看起来分毫不差
    repository.save_decision_card(company, {
        "watch_reason": "去宁德化被叙事放大",
        "bands": BANDS, "position_plan": PLAN,
        "order_plan": {"price": 302, "fraction": "1/3"}})

    row = _discipline()["inside"][0]
    assert row["planned_price"] == 300, "计划价被事后修改带着走了"
    assert row["price_drift"] == pytest.approx((302 / 300 - 1) * 100, abs=0.01)


def test_没有价格带的卡片判成无法判定_不判成违规():
    """**把不知道说成违规，这个指标就没人肯看了。**"""
    company = repository.create_company(
        CompanyInput(symbol="000651", name="格力电器", industry="家电"))["id"]
    repository.ensure_decision_card(company)
    repository.record_fill(company, 40.0)

    d = _discipline()
    assert d["undecidable_count"] == 1
    assert d["outside_count"] == 0
    assert "价格带" in d["undecidable"][0]["why"]


def test_未来的成交日期要拒():
    company = _armed_card()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(LedgerError, match="未来"):
        repository.record_fill(company, 300.0, filled_on=tomorrow)


@pytest.mark.parametrize("price", [0, -1])
def test_成交价必须大于零(price):
    company = _armed_card()
    with pytest.raises(LedgerError, match="成交价"):
        repository.record_fill(company, price)


def test_登记能删掉():
    """**填错价格是常事**，而错的成交价会让纪律指标一直错。"""
    company = _armed_card()
    repository.record_fill(company, 330.0)
    assert _discipline()["outside_count"] == 1

    fills = repository.company_fills(company)
    assert len(fills) == 1
    assert repository.delete_fill(fills[0]["id"]) is True
    assert _discipline()["outside_count"] == 0
    # 删第二次是 False，不是静默成功 —— 静默成功会掩盖"删错了对象"
    assert repository.delete_fill(fills[0]["id"]) is False


def test_登记会出现在卡片上():
    """摆在卡上才改得掉。藏起来的话填错了只能干瞪眼。"""
    company = _armed_card()
    repository.record_fill(company, 302.0, shares=100, note="按计划的第一笔")
    card = repository.decision_card(company)
    assert card is not None
    assert len(card["fills"]) == 1
    assert card["fills"][0]["price"] == pytest.approx(302.0)
    assert card["fills"][0]["planned_price"] == 300


def test_登记不动持仓():
    """**成交登记和持仓是两件事。**

    持仓由你自己填（只记股数和成本价），登记只是"我这一刻动手了"。
    混在一起的话，登记一笔 100 股会让持仓凭空多 100 股，而你并没有那么填。
    """
    from stock_decision.schemas import PortfolioCreate

    company = _armed_card()
    portfolio = repository.create_portfolio(
        PortfolioCreate(name="我的持仓", amount_mode="full"))["id"]
    repository.set_holding(portfolio, company, 500, 300.0)

    repository.record_fill(company, 302.0, shares=100)

    detail = repository.get_portfolio(portfolio)
    assert detail is not None
    held = {row["company_id"]: row for row in detail["positions"]}
    assert held[company]["shares"] == pytest.approx(500), "登记成交把持仓也改了"
