"""模型在结构位置上写全角标点——整轮好内容因此被丢掉。

2026-08-12：反方 Agent 跑格力，模型的内容是对的
（「净利率下滑是『周期』，但毛利率本身已经先于净利率塌掉了」），
整轮却因为解析失败被丢弃：

    ValueError: 模型返回的 JSON 修不好：Expecting ',' delimiter: line 18 column 7

`Expecting ',' delimiter` 跟"全角"两个字毫无关系，而中文模型最常见的坏 JSON
就是在成员之间写了全角逗号：

    {"tool": "financials"，"shows": "毛利率 30.08% → 27.61%"}
                          ↑ 这里

**不能整篇替换**：值里的中文逗号是完全合法的内容，替掉就把原文改了。
所以修补必须跟着引号状态走，只动字符串外面的。
"""

import json

import pytest

from stock_decision.jsonio import loads_lenient


def test_结构位上的全角逗号能修():
    bad = '{"points": [{"claim": "毛利率先塌了"，"n": 1}]}'
    assert loads_lenient(bad) == {"points": [{"claim": "毛利率先塌了", "n": 1}]}


def test_值里的中文逗号一个都不许动():
    """**这条是这次修补的边界。** 改错了等于篡改模型说的话。"""
    bad = '{"claim": "净利率下滑是「周期」，但毛利率先塌了，而且塌在核心端"，"n": 1}'
    got = loads_lenient(bad)
    assert got["claim"] == "净利率下滑是「周期」，但毛利率先塌了，而且塌在核心端"
    assert got["claim"].count("，") == 2


def test_全角冒号也修():
    assert loads_lenient('{"a"："b"}') == {"a": "b"}


def test_全角和裸引号一起来():
    """实际返回里这两样经常同时出现，修补链要能叠着走。"""
    bad = '{"shows": "公司说"稳定分红""，"tool": "financials"}'
    got = loads_lenient(bad)
    assert got["tool"] == "financials"
    assert "稳定分红" in got["shows"]


def test_修不好的时候要指出是哪一行():
    """**原来只给开头 160 字**，而错在第 18 行——看不到就没法修，
    只能再花一次模型调用去复现。"""
    lines = ["{", '  "a": 1,'] + [f'  "k{i}": {i},' for i in range(20)] + ["  这里不是 JSON", "}"]
    with pytest.raises(ValueError) as caught:
        loads_lenient("\n".join(lines))
    text = str(caught.value)
    assert "出错处" in text
    assert "这里不是 JSON" in text, "报错里得看得见出错那一行的内容"


def test_正常的json不受影响():
    good = '{"points": [{"claim": "一切正常，没有全角", "evidence": []}]}'
    assert loads_lenient(good) == json.loads(good)
