"""**补外层括号会把"没写完"洗成一个"成功"，而丢掉的那几行不留痕。**

`loads_lenient` 有一步很有用的修补：模型该回 `{"items": [...]}` 却直接回了
一串逗号分隔的对象时，给它补上外层方括号。证据方向那次判了 74 件、内容全对，
就是靠这一步救回来的。

但这一步跟别的修补有一个本质区别：**它会丢数据。**

    {"index":1,"shares":100},{"index":2,"shares":200},{"index":3,"sha
                                                      └─ 被长度上限掐在这里

切片取到最后一个完整的 `}`，第三行连同它后面的全部内容被丢掉；
补上括号之后是一段**完美合法**的 JSON —— 两行。不报错、不留痕。

2026-08-15 实测 `loads_or_reformat` 也放过了它：它先试 `loads_lenient`，
成功就直接返回，`looks_truncated` 那道闸压根轮不到。

交割单读图那边的注释早就写着这种坏法长什么样：
「看起来"读到了 12 条"，其实后面还有 30 条」。而账本少一笔，成本价就永久错，
再也查不回来 —— 漏一笔核对时能发现，**少一笔你会当成真的**。

尾随逗号、全角标点、裸引号那几步都不丢数据，只有补括号这一步会。
所以只给它加闸：修不动而原文又没写完的，当场判成「没写完」。
"""

import pytest

from stock_decision import jsonio

# 长表被掐断的样子：前两行完整，第三行写到一半。
CUT_SEQUENCE = '{"index":1,"shares":100},{"index":2,"shares":200},{"index":3,"sha'

# 完整的一串裸对象 —— 这一种必须照旧救得回来，别把有用的修补一起关掉。
WHOLE_SEQUENCE = '{"index":1,"shares":100},\n{"index":2,"shares":200}'


def test_a_half_written_row_list_is_refused_not_silently_shortened():
    """**这一条是要害。** 返回两行、还是抛一个错，差别是账本对不对。"""
    with pytest.raises(jsonio.Truncated):
        jsonio.loads_lenient(CUT_SEQUENCE)


def test_a_complete_row_list_is_still_rescued():
    """证据方向那次 74 件靠的就是这一步，不能为了上面那条把它关掉。"""
    assert jsonio.loads_lenient(WHOLE_SEQUENCE) == [
        {"index": 1, "shares": 100}, {"index": 2, "shares": 200}]


def test_the_reformatter_does_not_pay_for_a_half_table_either(monkeypatch):
    """`loads_or_reformat` 先试 `loads_lenient`、成功就返回 —— 于是那道
    「没写完」的闸原来根本轮不到。现在在 `loads_lenient` 里就拦住了。"""
    from stock_decision import llm

    monkeypatch.setattr(llm, "call", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("没写完的东西不该送去重排")))
    with pytest.raises(jsonio.Truncated):
        jsonio.loads_or_reformat(CUT_SEQUENCE, task="t")


def test_the_error_says_what_would_have_been_lost():
    """报错要说清楚**为什么宁可失败**，否则下一个人会把这道闸去掉，
    理由是"明明能解析出来"。"""
    try:
        jsonio.loads_lenient(CUT_SEQUENCE)
    except jsonio.Truncated as caught:
        assert "丢掉" in str(caught) and "半张表" in str(caught)
    else:
        pytest.fail("没抛")


# --------------------------------------------------- 交割单读图：最贵的那次调用

def test_a_tile_that_ran_out_of_room_says_so_specifically():
    """没写完跟"读不出来"是两回事，下一步动作也不一样：

    · 没写完 → 这一段行数太多，把它截短一点重传
    · 读不出来 → 多半是图糊，重新截一张清楚的

    混成一句「没读成功」，使用者只会反复重传同一张图。
    """
    from stock_decision import ledger_scan

    assert hasattr(ledger_scan, "REFORMAT_SHAPE")
    # 重排的结构必须跟主提示词同形，否则重排出来字段对不上，_merge 读出零行
    for field in ("page_symbol", "page_company", "page_fee_total", "trades",
                  "side", "trade_date", "shares", "price", "fee", "cash_amount"):
        assert field in ledger_scan.REFORMAT_SHAPE, field
        assert field in ledger_scan.SCAN_SYSTEM_PROMPT, field
