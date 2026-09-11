"""坏 JSON 出现在一条**已经花掉了的**链路末尾时，不能一抛了事。

反方 Agent 查六轮库、投资逻辑起草查八轮，全是真调用、真计费。
原来这两处都是解析失败就抛：使用者付了一整轮的钱，拿到一句 JSONDecodeError。
而坏 JSON 恰恰是最常见的一种失败 —— 模型在中文值里夹一个英文引号就够了
（另见 test_jsonio_fullwidth.py：全角逗号那次，内容全对，整轮被丢）。

`loads_lenient` 已经在修常见毛病。修不好的时候，唯一还没试过的办法是
**把原文还给模型，只让它重排格式** —— 不带工具、不查库，比重跑一整轮
便宜一个数量级，救回的是已经花掉的那一整轮。

这个文件守两件事：

- 重排只在**修不好的时候**发生，而且只发生一次
- 重排的提示词只许改格式；救回来的必须还是原来那份结论
"""

import json

import pytest

from stock_decision import drafting
from stock_decision import jsonio

# **写完了、但格式坏了**：成员之间少一个逗号，而 `loads_lenient` 那几步修补
# （尾随逗号、全角标点、裸引号、补外层方括号）一条都够不着。
# 这个形状是真见过的 —— 2026-08-14 线上那次重排的产出就是
# `"not_challenged": "…"` 后面直接跟 `"gaps": [...]`，中间没有逗号。
#
# **括号必须是平的。** 少一个右括号的话它就成了"没写完"，
# 会走 Truncated 那条路，测不到重排。
BROKEN = ('{"headline": "赌的是品牌定价权还在"'
          ' "basis": [{"point": "毛利率还稳", "evidence": "30.08%", "as_of": "2025 年报"}]}')

GOOD = {"headline": "赌的是品牌定价权还在",
        "basis": [{"point": "毛利率还稳", "evidence": "30.08%", "as_of": "2025 年报"}],
        "counters": [{"metric": "净利率", "threshold": "连续两期低于 14%", "means": "定价权在松"}],
        "review": {"when": "2026 年中报", "what": ["毛利率"]},
        "used_facts": ["毛利率 30.08%"], "unknowns": []}


class _Reply:
    def __init__(self, text):
        self.text = text


def _model(monkeypatch, text, sink=None):
    """替掉 llm.call。jsonio 是局部 import 同一个模块对象，所以这里打得到。"""
    def _call(system, user, **kwargs):
        if sink is not None:
            sink.append({"system": system, "user": user, **kwargs})
        return _Reply(text)

    monkeypatch.setattr(jsonio.llm if hasattr(jsonio, "llm") else __import__(
        "stock_decision.llm", fromlist=["llm"]), "call", _call)


# ------------------------------------------------------------------ helper 本身

def test_a_parsable_answer_never_costs_a_second_call(monkeypatch):
    """能解析的一次都不许重排 —— 那是白花一次调用。"""
    from stock_decision import llm

    def _boom(*_a, **_k):
        raise AssertionError("解析得动的答案不该再调一次模型")

    monkeypatch.setattr(llm, "call", _boom)
    payload, reformatted = jsonio.loads_or_reformat(
        json.dumps(GOOD, ensure_ascii=False), task="t")
    assert payload == GOOD
    assert reformatted is False


def test_a_broken_answer_is_handed_back_verbatim_for_reformatting(monkeypatch):
    """**原文原样递回去**，不是递一段摘要 —— 摘要救回来的就不是原来那份了。"""
    calls: list[dict] = []
    _model(monkeypatch, json.dumps(GOOD, ensure_ascii=False), calls)

    payload, reformatted = jsonio.loads_or_reformat(BROKEN, task="t", shape='{"headline": "…"}')
    assert payload == GOOD
    assert reformatted is True
    assert len(calls) == 1, "只重排一次，不是无限重试"
    assert calls[0]["user"] == BROKEN
    assert "只改格式" in calls[0]["system"], "提示词必须禁止改内容"
    assert '{"headline": "…"}' in calls[0]["system"], "给了 shape 就要带上去"


def test_when_the_reformat_is_also_broken_it_still_raises(monkeypatch):
    """重排也修不好时照样抛 —— 这一层只负责救，不负责编一个能用的结果出来。"""
    _model(monkeypatch, "还是坏的")
    with pytest.raises(ValueError):
        jsonio.loads_or_reformat(BROKEN, task="t")


# ------------------------------------------------------------------ 起草那一路

def _drafter(monkeypatch, text):
    from stock_decision import company_tools as ct

    monkeypatch.setattr(drafting, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(drafting, "build_prompt", lambda *_a: ("资料", ["净利率"]))
    monkeypatch.setattr(ct, "run_loop", lambda *a, **k: {
        "text": text, "tool_calls": [{"tool": "financials", "rows": 12}],
        "payloads": [], "messages": [], "billing": {}, "exhausted": False})


def test_a_broken_draft_is_reformatted_instead_of_wasting_the_rounds(monkeypatch):
    """查库那几轮已经花掉了，不能因为最后一段格式坏了就全打水漂。"""
    _drafter(monkeypatch, BROKEN)
    _model(monkeypatch, json.dumps(GOOD, ensure_ascii=False))
    out = drafting.draft_with_tools({"name": "x", "symbol": "1"}, lambda n, a: {})
    assert out["structure"]["headline"] == GOOD["headline"]
    assert "financials（12 行）" in out["read"], "查过哪几张表还要照旧摆出来"
    assert "重排" in out["read"], "返过一次工要留痕，哪句读着别扭好知道先怀疑这里"


def test_a_clean_draft_says_nothing_about_reformatting(monkeypatch):
    _drafter(monkeypatch, json.dumps(GOOD, ensure_ascii=False))
    out = drafting.draft_with_tools({"name": "x", "symbol": "1"}, lambda n, a: {})
    assert "重排" not in out["read"]


def test_a_draft_that_cannot_be_repaired_is_refused_not_half_given(monkeypatch):
    """**这一点跟反方 Agent 不一样，别照抄。**

    反方可以交一份「这次没有结论」出去，因为它的产出是给人读的建议。
    起草的产出会被存进库当成一条投资逻辑 —— 一条空的或半截的草稿存进去，
    比一个报错糟得多：它会被当成基准用一年。
    """
    _drafter(monkeypatch, BROKEN)
    _model(monkeypatch, "还是坏的")
    with pytest.raises(RuntimeError, match="不是合法 JSON"):
        drafting.draft_with_tools({"name": "x", "symbol": "1"}, lambda n, a: {})


def test_the_reformat_shape_matches_the_prompt_it_reformats_for():
    """重排用的结构必须跟主提示词同形。

    两处写岔的话，重排会照着另一个形状去改，改出来照样是合法 JSON，
    只是字段对不上，然后 _shape 静静地读出一堆空值 —— 谁也不会报错。
    """
    for field in ("headline", "basis", "counters", "review", "used_facts", "unknowns"):
        assert field in drafting.DRAFT_SHAPE, field
        assert field in drafting.DRAFT_SYSTEM_PROMPT, field


# ----------------------------------- 「没写完」不是「写坏了」（2026-08-14 线上实测）
#
# 上线当天在线上跑了一轮真实的反方：查完九张表，结论写到 5527 字，
# 停在 `"claim": "收现比从 2023 年 109.06%` —— 半个词，括号还差三层。
# 那不是模型写错了标点，是 max_tokens 到顶把它掐了。
#
# 两件事的处理方式相反：格式坏了能靠重排救；没写完则**一定救不回来**，
# 因为重排的规矩是"一个字都不许加"，而缺的那半截只能靠加。
# 送去重排要么白花一次调用，要么逼它编一段原文里没有的结论。

CUT_OFF = ('{"points": [{"claim": "收现比从 2023 年 109.06% 降到",'
           ' "evidence": [{"tool": "financials", "shows": "收现比 10')


def test_a_cut_off_answer_is_not_sent_off_for_reformatting(monkeypatch):
    """没写完的一次调用都不许花 —— 重排救不回来，这是结构决定的，不是概率问题。"""
    from stock_decision import llm

    def _boom(*_a, **_k):
        raise AssertionError("没写完的东西不该送去重排")

    monkeypatch.setattr(llm, "call", _boom)
    with pytest.raises(jsonio.Truncated):
        jsonio.loads_or_reformat(CUT_OFF, task="t")


def test_truncation_is_told_apart_from_bad_formatting():
    """判据是**字符串外面的括号收不收得平**，不是长度、也不是有没有报错。"""
    assert jsonio.looks_truncated(CUT_OFF)
    assert jsonio.looks_truncated('{"a": [1, 2')
    # 完整的不算：值里的 } 在字符串内，不参与计数
    assert not jsonio.looks_truncated('{"a": [1, 2], "b": "}"}')
    # 格式坏但写完了的也不算 —— 那种该走重排
    assert not jsonio.looks_truncated(BROKEN)


def test_the_two_reasons_do_not_read_the_same(monkeypatch):
    """跟使用者说「格式坏了」，他会去怀疑模型的输出质量；
    说「太长了被截断」，他才知道这是调预算能解决的。混成一句就把人带偏了。"""
    from stock_decision import devils_advocate as da
    from stock_decision import llm

    monkeypatch.setattr(llm, "call", lambda *a, **k: _Reply("还是坏的"))
    monkeypatch.setattr(da, "ai_available", lambda: (True, ""))
    from stock_decision import company_tools as ct

    def _loop(text):
        return lambda *a, **k: {"text": text, "tool_calls": [{"tool": "financials", "rows": 9}],
                                "payloads": [], "messages": [], "billing": {}, "exhausted": False}

    monkeypatch.setattr(ct, "run_loop", _loop(CUT_OFF))
    cut = da.converse("q", lambda n, a: {})
    monkeypatch.setattr(ct, "run_loop", _loop(BROKEN))
    broken = da.converse("q", lambda n, a: {})

    assert "截断" in cut["note"] and "截断" not in broken["note"]
    assert "格式" in broken["note"]
    # 两种都要把查过的表留下 —— 这一轮的钱已经花了
    for r in (cut, broken):
        assert r["tool_calls"], r["note"]


def test_the_answer_budget_is_big_enough_for_a_real_rebuttal():
    """3000 实测不够（线上那次 5527 字还没写完）。这条钉住的是"别再调回去"。"""
    from stock_decision import devils_advocate as da

    assert da.MAX_ANSWER_TOKENS >= 100000


def test_the_hold_does_not_follow_max_tokens():
    """**冻结额不许跟 max_tokens 挂钩。**

    挂钩的话，为了不被截断而调大上限，会同时把冻结额按二十倍预期值抬上去，
    余额少的人被一个「额度不足」挡在门外 —— 而那次调用他其实付得起。
    使用者 2026-08-14 拍板：「冻结不要跟模型最多的 max_tokens 挂钩」。
    """
    from stock_decision import llm

    small = llm.estimate_tokens("s", "u", 8000)
    huge = llm.estimate_tokens("s", "u", 100000)
    assert small == huge, "上限翻十倍，冻结额一分都不该变"
    # 但也不能反过来变成零：输出那一段仍要冻，否则长答案会大幅少收。
    assert huge - len("s") - len("u") >= 4000


def test_a_tiny_budget_still_only_holds_what_it_asks_for():
    """上限比预期还小的时候，按上限冻 —— 冻一个它根本写不到的量是白占余额。"""
    from stock_decision import llm

    assert llm.estimate_tokens("", "", 500) == 500
