"""估值 → 价格带那根线，以及「记录要带时间」。

两件事写在一个文件里，因为它们是同一个毛病的两半：
价格带原来既不知道自己该是多少（要人从零填四个数），也不知道自己是什么时候定的
（整张卡共用一个 updated_at）。使用者的原话是
「在过去正确的记录数字，放在现在就是错的」。
"""

from __future__ import annotations

import pytest

from stock_decision import bands as bd


# ── 建议值 ──────────────────────────────────────────────────────────────────

def test_四段从高到低且算式对得上():
    """手算过：基准 255，安全边际 20%，观察区溢价 10%。"""
    out = bd.propose(255.0)
    assert out is not None
    assert out["bands"] == {"watch": 280.5, "fair": 255.0, "ideal": 204.0, "extreme": 153.0}
    values = [out["bands"][k] for k in ("watch", "fair", "ideal", "extreme")]
    assert values == sorted(values, reverse=True)


def test_系数改了四段跟着变():
    """**系数必须是活的。** 写死在代码里的话它就是个编出来的默认值；
    页面上能改、算式跟着变，才叫一条看得见的规矩。"""
    tight = bd.propose(100.0, safety_margin=10.0)
    loose = bd.propose(100.0, safety_margin=40.0)
    assert tight is not None and loose is not None
    assert tight["bands"]["ideal"] == 90.0
    assert loose["bands"]["ideal"] == 60.0
    assert loose["bands"]["extreme"] == 20.0     # 100 × (1 − 40% × 2)


def test_算式字符串里带着那个基准数():
    """算式不是装饰。**看不见算式的建议值跟编出来的默认值没有区别**——
    使用者必须能一眼认出 204 是 255 打八折来的。"""
    out = bd.propose(255.0)
    assert out is not None
    formulas = {row["key"]: row["formula"] for row in out["rows"]}
    assert "255.00" in formulas["ideal"] and "20%" in formulas["ideal"]
    assert "255.00" in formulas["watch"] and "10%" in formulas["watch"]


def test_没有估值就没有价格带():
    """**不退回某个"通用"倍数。** 没估值就没有锚，而一组凭空的价格带
    会被当成系统算出来的东西。这正是「已估值」排在「等待价格」前面的原因。"""
    assert bd.propose(None) is None
    assert bd.propose(0) is None
    assert bd.propose(-5) is None


def test_四舍五入撞在一起时不给建议():
    """撞在一起的四段过不了 validate_bands，而那个错会在用户点了
    「填进去」并保存之后才冒出来，看起来像系统坏了。"""
    assert bd.propose(0.01) is None


def test_建议值自己声明它是个约定():
    """页面据此写「这是建议不是推荐买点」。漏了这个标记，
    一组人定的系数就会被读成从这家公司数据里算出来的结论。"""
    out = bd.propose(255.0)
    assert out is not None and out["is_convention"] is True
    assert "建议值" in out["note"]


# ── 时间 ────────────────────────────────────────────────────────────────────

def test_建议值一定带着它的保质期():
    """`as_of` 和 `base_report_date` 缺了的话，一组去年的价格带
    跟今天刚定的在页面上长得一模一样。"""
    out = bd.propose(255.0, as_of="2026-09-23T08:48:25", base_report_date="2025-12-31")
    assert out is not None
    assert out["as_of"] == "2026-09-23T08:48:25"
    assert out["base_report_date"] == "2025-12-31"


def test_财报换期了要说话():
    stale = bd.staleness("2025-12-31", "2026-06-30")
    assert "2025-12-31" in stale and "2026-06-30" in stale


def test_没换期就不要打扰():
    """**同一期、更老的一期、以及问不出来的时候都闭嘴。**
    一个天天喊过期的提醒，跟没有提醒是一个效果。"""
    assert bd.staleness("2026-06-30", "2026-06-30") == ""
    assert bd.staleness("2026-06-30", "2025-12-31") == ""
    assert bd.staleness(None, "2026-06-30") == ""
    assert bd.staleness("2026-06-30", None) == ""


# ── 对账 ────────────────────────────────────────────────────────────────────

def test_计划价高于自己算的价值时要点破():
    """这是这根线最值钱的一句话：计划买入价 300 和基准每股价值 255
    分别躺在两个模块里，谁也不知道它们差 18%。"""
    notes = bd.compare(255.0, {"watch": 310.0, "fair": 300.0, "ideal": 280.0, "extreme": 270.0},
                       300.0, 304.63)
    assert any("高 18%" in note and "计划买入价" in note for note in notes)
    assert any("合理区上沿" in note for note in notes)


def test_计划价留了安全边际就不要报警():
    """**判据要能分辨两种情况**，否则它只是一句无论如何都会出现的话。"""
    notes = bd.compare(255.0, None, 200.0)
    assert any("留了安全边际" in note for note in notes)
    assert not any("要么是这一笔本来就不在计划里" in note for note in notes)


def test_差得不多就不说话():
    """5% 以内不提。**每次都说话的提醒等于没有提醒。**"""
    assert bd.compare(255.0, None, 258.0) == []


def test_没估值时一句都不说():
    assert bd.compare(None, {"fair": 300.0}, 300.0) == []


@pytest.mark.parametrize("order_price", [None, "", 0])
def test_没填计划价不算成偏离(order_price):
    """**空和 0 要分开。** 没填是"还没决定"，填 0 是填错了；
    合成一个值的话会对着一个不存在的计划价算偏离。"""
    notes = bd.compare(255.0, None, order_price if isinstance(order_price, (int, float)) else None)
    assert not any("计划买入价" in note for note in notes)
