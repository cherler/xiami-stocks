"""AI 选股的挑选结果坏 JSON —— 前面两步全白做。

2026-08-15 线上实测（真实账号）：模型把 passed 数组提前收了口，
`}]` 之后又接了一个对象。而**内容完全正常** —— 有 picks、有理由、有疑点、
有一句总结 note，只是括号位置错了。整份被丢掉，扣了 2 分，任务标记为失败。

走到 parse_picks 的时候，翻译条件、全 A 筛选、把候选喂给模型都已经做完了，
前后两次模型调用都是真计费的。

**这个坑本会话已经在反方 Agent 和投资逻辑起草那儿修过两次**，
`jsonio.loads_or_reformat` 就是那时候抽出来共用的 —— 这个模块从来没接上。
所以这个文件盯的是"接没接上"，不是"解析器对不对"。
"""

import pytest

from stock_decision import ai_pick

ROWS = [{"symbol": "600519", "name": "甲"}, {"symbol": "000651", "name": "乙"}]

# 线上那次的形状：passed 数组提前收口，后面又跟了一个对象
BROKEN = ('{"picks": [{"index": 1, "why": "理由"}], '
          '"passed": [{"index": 2, "why": "放过它"}], {"index": 2, "why": "又一个"}], '
          '"note": "一句总结"}')
GOOD = ('{"picks": [{"index": 1, "why": "理由", "reasons": ["依据"], "concerns": []}], '
        '"passed": [{"index": 2, "why": "放过它"}], "note": "一句总结"}')


def test_a_broken_pick_result_is_reformatted_not_thrown_away(monkeypatch):
    """前面两步已经花过钱了，不能因为括号位置错了就整份丢掉。"""
    calls = []

    def _call(system, user, **kwargs):
        calls.append(system)
        return type("C", (), {"text": GOOD})()

    monkeypatch.setattr("stock_decision.llm.call", _call)
    result = ai_pick.parse_picks(BROKEN, ROWS)
    assert len(calls) == 1, "没走重排 —— 说明这个模块还是没接上共用的那一层"
    assert [p["symbol"] for p in result["picks"]] == ["600519"]
    assert result["note"] == "一句总结"


def test_a_good_result_costs_no_extra_call(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("解析得动的结果不该再调一次模型")

    monkeypatch.setattr("stock_decision.llm.call", _boom)
    assert ai_pick.parse_picks(GOOD, ROWS)["picks"]


def test_the_index_bound_still_holds_after_reformatting(monkeypatch):
    """**重排不能把边界检查绕过去。** 行号越界仍然一律丢 ——
    这是"模型编不出一只库外的票"的唯一保证。
    """
    monkeypatch.setattr("stock_decision.llm.call", lambda *a, **k: type(
        "C", (), {"text": '{"picks": [{"index": 99, "why": "编的"}], "passed": [], "note": ""}'})())
    result = ai_pick.parse_picks(BROKEN, ROWS)
    assert result["picks"] == [], "越界的行号被重排放进来了"
