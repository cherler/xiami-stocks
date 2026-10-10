"""推进时的理由，以及每一块各自的时间戳。

起因是使用者的两句话：

> 推进状态机，还必须填写理由；还必须跳转到对应页面？这一套流程，我真觉得麻烦
> 关于记录，要带上时间。因为在过去正确的记录数字，放在现在就是错的

第一句换来的是「往前走那一步不再强制手写」，第二句换来的是 block_stamps。
两件都有一个共同的坏法：**不报错**。理由强制填会让人干脆不推进（状态机停在
半路，比没有更糟，因为它看起来是准的）；时间戳一律刷新则会让一组去年的
价格带显示成今天刚定的。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_decision import repository
from stock_decision.repository import LedgerError
from stock_decision.schemas import CompanyInput, PortfolioCreate, ThesisCreate, TradeCreate

BANDS = {"watch": 310.0, "fair": 300.0, "ideal": 280.0, "extreme": 270.0}
PLAN = {"total_percent": 20, "first_percent": 6, "second_percent": 6, "third_percent": 6}
ORDER = {"price": 300, "fraction": "1/3"}


def _company(symbol: str = "300750", name: str = "宁德时代") -> int:
    return repository.create_company(CompanyInput(symbol=symbol, name=name, industry="电池"))["id"]


def _ready_card(company_id: int) -> None:
    """把一张卡填到「等待价格」该有的样子。"""
    repository.create_thesis(company_id, ThesisCreate(
        claim="去宁德化是真趋势但短期叙事被放大", counter_condition="市占率连续两季下降",
        next_review_trigger="下一期季报"))
    repository.save_decision_card(company_id, {
        "watch_reason": "好公司遇到暂时性麻烦",
        "bands": BANDS, "position_plan": PLAN, "order_plan": ORDER})


# ── 理由 ────────────────────────────────────────────────────────────────────

def test_往前走那一步可以不写理由_机器替你写():
    """待研究 → 研究中 的理由就是「我写下了关注理由」——系统自己知道。"""
    company = _company()
    repository.save_decision_card(company, {"watch_reason": "先看着", "bands": {},
                                            "position_plan": {}, "order_plan": {}})
    card = repository.move_decision_state(company, "researching", "")
    assert card is not None and card["state"] == "researching"
    # 机器写的那句只陈述事实，不替你表态。
    assert "写下了关注理由" in card["entered_reason"]
    assert "看好" not in card["entered_reason"]


def test_退回必须自己写():
    """**退回的理由只有你知道**，而那正是复盘最值钱的一句。"""
    company = _company()
    repository.save_decision_card(company, {"watch_reason": "先看着", "bands": {},
                                            "position_plan": {}, "order_plan": {}})
    repository.move_decision_state(company, "researching", "")
    with pytest.raises(LedgerError) as exc:
        repository.move_decision_state(company, "discovered", "")
    assert "只有你知道" in str(exc.value)

    card = repository.move_decision_state(company, "discovered", "看错了，先退回去")
    assert card is not None and card["entered_reason"] == "看错了，先退回去"


def test_搁置必须自己写():
    company = _company()
    repository.save_decision_card(company, {"watch_reason": "先看着", "bands": {},
                                            "position_plan": {}, "order_plan": {}})
    with pytest.raises(LedgerError) as exc:
        repository.move_decision_state(company, "shelved", "")
    assert "半年后的你" in str(exc.value)


def test_手写的理由永远盖过机器写的():
    company = _company()
    repository.save_decision_card(company, {"watch_reason": "先看着", "bands": {},
                                            "position_plan": {}, "order_plan": {}})
    card = repository.move_decision_state(company, "researching", "看完年报再说")
    assert card is not None and card["entered_reason"] == "看完年报再说"


def test_推进日志里记的是最终那句话_不是空的():
    """日志留的必须是真正写进卡片的那句，否则复盘时两处对不上。"""
    company = _company()
    repository.save_decision_card(company, {"watch_reason": "先看着", "bands": {},
                                            "position_plan": {}, "order_plan": {}})
    card = repository.move_decision_state(company, "researching", "")
    assert card is not None
    latest = card["history"][0]
    assert latest["to_state"] == "researching"
    assert latest["reason"] == card["entered_reason"]
    assert latest["reason"].strip() != ""


# ── 时间戳 ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def clock(monkeypatch):
    """把时间钉死并手动推进。

    **不钉的话这一组判据什么都没测。** 两次保存落在同一秒里，
    `set_at` 前后本来就相等 —— 于是"只给改过的那块盖新戳"和
    "一律盖新戳"两种实现都能让 `==` 成立。实测过：把逐块比对改成
    无条件刷新，这条判据照样全绿。
    """
    ticks = {"now": "2026-01-01T00:00:00"}

    def fake_now() -> str:
        return ticks["now"]

    monkeypatch.setattr(repository, "now_iso", fake_now)

    def advance(value: str) -> None:
        ticks["now"] = value

    return advance


def test_只给改过的那一块盖新时间戳(clock):
    """**一律刷新等于把"这组价格带有多旧"这个信号抹掉。**

    今天调一下仓位计划，价格带的日期不该跟着变成今天。
    """
    company = _company()
    _ready_card(company)
    first = repository.decision_card(company)
    assert first is not None
    assert first["block_stamps"]["bands"]["set_at"] == "2026-01-01T00:00:00"

    # 半年后，只改仓位计划，价格带原样存回去。
    clock("2026-07-01T00:00:00")
    repository.save_decision_card(company, {
        "watch_reason": "好公司遇到暂时性麻烦",
        "bands": BANDS, "position_plan": dict(PLAN, total_percent=25), "order_plan": ORDER})

    after = repository.decision_card(company)
    assert after is not None
    assert after["block_stamps"]["bands"]["set_at"] == "2026-01-01T00:00:00", \
        "价格带没改，时间戳不该被仓位计划带着走"
    assert after["block_stamps"]["position_plan"]["set_at"] == "2026-07-01T00:00:00"


def test_改了价格带就盖新时间戳(clock):
    """反过来也要成立，否则"只给改过的盖"就退化成"永远不盖"。"""
    company = _company()
    _ready_card(company)
    before = repository.decision_card(company)
    assert before is not None
    assert before["block_stamps"]["bands"]["set_at"] == "2026-01-01T00:00:00"

    clock("2026-07-01T00:00:00")
    repository.save_decision_card(company, {
        "watch_reason": "好公司遇到暂时性麻烦",
        "bands": dict(BANDS, fair=290.0), "position_plan": PLAN, "order_plan": ORDER})

    after = repository.decision_card(company)
    assert after is not None
    assert after["block_stamps"]["bands"]["set_at"] == "2026-07-01T00:00:00"
    assert after["bands"]["fair"] == 290.0


def test_价格带时间戳带着它依据的报告期():
    """价格带没有自己的有效期，它的有效期是它依据的那期财报的有效期。"""
    company = _company()
    _ready_card(company)
    card = repository.decision_card(company)
    assert card is not None
    stamp = card["block_stamps"]["bands"]
    assert "set_at" in stamp
    # 这个库里没同步财务数据，所以出处取不到——**取不到要如实为空，
    # 不许填一个今天的日期充数**（那会让过期判定永远说"没过期"）。
    assert "base_report_date" in stamp


def test_老卡片没有时间戳时如实为空():
    """**把不知道说成知道是这里最糟的失败方式。**

    block_stamps 这个字段是后加的，在它之前定的价格带没有时间。
    显示成"今天定的"会让一组两年前的数看起来刚刚复核过。
    """
    company = _company()
    repository.ensure_decision_card(company)
    card = repository.decision_card(company)
    assert card is not None
    assert card["block_stamps"] == {}
