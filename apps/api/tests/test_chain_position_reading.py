"""产业链位置那句话：只看前五合计，会把「压在一家身上」说成「下游分散」。

## 这个模块自己的例子就把它否掉了

`chain_position.py` 开头列的实测数据里有这么一行：

    雪人集团   前五名客户 29.30%   **第一名 17.00%**

29.3% 落进「小于 30」那一档，于是这一页原来会说：

    前五大客户只占 29.3%，下游分散，**没有哪一家能单独左右它**

而它的第一大客户一家就占 17% —— 丢掉这一家收入直接少一截。
**旁边的表格摆着 17%，而这句话在说没有。**

逐名明细（`top`）一直就在同一个返回值里，只是从来没有传进 `read_position`。

（这个模块 129 行、测试里只被提到 1 次，是照着"哪儿没人看过"找过来的第二处。）
"""

import pytest

from stock_decision import chain_position as cp


def _top(*ratios):
    return [{"name": f"第{i+1}名", "amount": None, "ratio": r} for i, r in enumerate(ratios)]


def test_a_big_single_customer_is_not_called_diversified():
    """**这一条是要害。** 合计 29.3% 而第一名 17%，不能说成「下游分散」。"""
    reading = cp.read_position(29.30, None, _top(17.0, 5.1, 3.2))
    assert "分散" not in reading or "看着分散" in reading, reading
    assert "17" in reading, "那 17% 必须出现在句子里 —— 它就是这句话的理由"
    assert "没有哪一家能单独左右它" not in reading


def test_a_genuinely_spread_customer_base_still_reads_that_way():
    """格力：前五 14.4%、第一名 5.91% —— 那是真的分散，照旧这么说。"""
    reading = cp.read_position(14.40, None, _top(5.91, 3.2, 2.1))
    assert "下游分散" in reading and "没有哪一家能单独左右它" in reading


def test_without_the_detail_it_falls_back_to_the_old_sentence():
    """很多公司只披露合计、不披露逐名。**没有明细就不许暗示有** ——
    这时候只能按合计说话，不能凭空多一句「但第一名…」。"""
    assert "第一大客户" not in cp.read_position(29.30, None)
    assert "第一大客户" not in cp.read_position(29.30, None, [])


def test_the_high_bands_are_untouched():
    """合计本来就高的那两档不受影响 —— 它们已经在说「集中」了。"""
    assert "定价权很大程度上不在自己手里" in cp.read_position(62.0, None, _top(30.0))
    assert "下游偏集中" in cp.read_position(35.0, None, _top(20.0))


@pytest.mark.parametrize("biggest,flagged", [
    (9.9, False), (10.0, True), (17.0, True), (4.0, False),
])
def test_the_threshold_is_ten_percent(biggest, flagged):
    """10% 不是拍的：它是年报里「重大客户」的通行口径。
    改这个门槛要连同上面那句理由一起改。"""
    reading = cp.read_position(25.0, None, _top(biggest))
    assert ("第一大客户" in reading) is flagged, reading
    assert cp.SINGLE_CUSTOMER_MATTERS == 10.0


def test_a_missing_ratio_in_the_detail_does_not_crash():
    """逐名明细里常有只写名字没写比例的行（解析不出来就是 None）。
    那种行跳过，不能让整句话算不出来。"""
    messy = [{"name": "第一名", "amount": 1.0, "ratio": None},
             {"name": "第二名", "amount": 2.0, "ratio": 12.0}]
    assert "12" in cp.read_position(25.0, None, messy)
