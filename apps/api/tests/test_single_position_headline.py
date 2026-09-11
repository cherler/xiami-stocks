"""只有一只持仓时，那句加粗标题在事实上不成立。

## 2026-08-16 线上实测

「研究持仓」组合里只记了一只格力、占 50%，而这一页最上面加粗写着：

    **你的50% 仓位全部押在格力电器一家上。**

**50% 和「全部」自相矛盾**，而且读起来是句同义反复（"你的 50% 仓位全部在…"）。
没权重时更糟，模板拼出来是「你的全部仓位全部押在…」，两个「全部」。

口径查清了：ratio 那种记法里的 50% 是**你自己记的占比，剩下的没记账**。
那种情况下这一页连「分不分散」都答不了 —— 而这个模块开头就写着
「没数据时说没数据」。拿一句读着像结论的话糊过去，正是它自己禁止的事。

这个模块 343 行、测试里只被提到过 1 次，是全仓测试最薄的一块 ——
这一条就是照着"哪儿没人看过"找出来的。
"""

import pytest

from stock_decision.portfolio_risk import analyze


def _one(weight):
    return analyze([{"symbol": "000651", "company_name": "格力电器",
                     "company_id": 4, "weight": weight}], {}, {})


def test_half_a_portfolio_is_not_all_of_it():
    """**这一条是要害。** 只记了一半仓位，不能说成「全部押在一家上」。"""
    view = _one(50)
    assert "全部" not in view["headline"], view["headline"]
    assert "50" in view["headline"]


def test_it_says_the_rest_is_not_recorded():
    """剩下那一半没记账 —— 而这一页只看得见记下来的部分。
    不说这句的话，读的人会以为它已经把整个组合看过了。"""
    view = _one(50)
    assert "没有记在这个组合里" in view["note"]
    assert "答不了" in view["note"]


def test_a_full_position_still_says_so_plainly():
    """真的是全仓一只时，那句话是成立的，要照旧说。"""
    assert "全部仓位押在" in _one(100)["headline"]


def test_no_weight_means_no_number_is_quoted():
    """算不出权重就不要报数 —— 也不要拼出「全部仓位全部押在」这种两个全部的话。"""
    headline = _one(None)["headline"]
    assert "%" not in headline
    assert headline.count("全部") == 0, headline


def test_the_brake_line_survives_every_branch():
    """三条分支都要保留那句「认错条件是你唯一的刹车」——
    它才是这种仓位下真正要紧的事，不能因为改标题把它改没了。"""
    for weight in (50, 100, None):
        assert "认错条件" in _one(weight)["note"]
        assert "刹车" in _one(weight)["note"]
