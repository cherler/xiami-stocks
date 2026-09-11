"""资讯自动对应：把标题匹配到已建档的公司。

这里有过一个 `NameError: name 'model' is not defined` —— 拼结果那行引用了一个
根本不存在的变量，页面上表现成「请求失败（500）」。

**它能活下来是因为这条路径只在规则匹配不完时才走**：规则先按公司名和代码对，
剩下的才交给模型。测试里如果每条都被规则接住，模型那段就一次也不执行，
于是一个必然抛错的 NameError 可以一直躺在那儿。

所以下面每条都刻意构造成规则匹配不上的标题。
"""

import pytest

from stock_decision import news


def _fake_model(monkeypatch, payload: str):
    class _Completion:
        text = payload
        usage = None
    monkeypatch.setattr(news.llm, "call", lambda *a, **k: _Completion())
    monkeypatch.setattr(news, "ai_available", lambda: (True, ""))


COMPANIES = [
    {"id": 3, "name": "格力电器", "symbol": "000651", "industry": "家电"},
    {"id": 4, "name": "美的集团", "symbol": "000333", "industry": "家电"},
]
ITEMS = [
    {"fingerprint": "fp1", "title": "空调价格战再起，龙头份额松动"},
    {"fingerprint": "fp2", "title": "央行下调 LPR"},
]


def test_a_match_carries_every_field_the_caller_writes(monkeypatch):
    """整条结果都要拼得出来 —— 少一个字段就是 500。

    这正是那次 NameError 的形状：前面全对，最后拼 model 那一行炸掉。
    """
    _fake_model(monkeypatch, '[{"index": 1, "company_id": 3, "reason": "空调龙头指向格力"}]')

    matches = news.match_with_model(ITEMS, COMPANIES)

    assert len(matches) == 1
    hit = matches[0]
    assert set(hit) == {"fingerprint", "company_id", "confidence", "reason", "model"}
    assert hit["fingerprint"] == "fp1" and hit["company_id"] == 3
    assert hit["model"], "model 是空的——写进库里之后没人知道这条是谁匹配的"


def test_an_id_outside_the_roster_is_refused(monkeypatch):
    """模型选了清单外的 id 就当没匹配上。

    放行的后果是把不相关的新闻挂到别人的公司档案上，比漏掉一条严重得多。
    """
    _fake_model(monkeypatch, '[{"index": 1, "company_id": 999, "reason": "瞎猜的"}]')

    matches = news.match_with_model(ITEMS, COMPANIES)

    assert matches[0]["company_id"] is None
    assert matches[0]["confidence"] == "无匹配"


def test_an_out_of_range_index_is_dropped(monkeypatch):
    """越界的序号丢掉，不猜它想指哪条。"""
    _fake_model(monkeypatch, '[{"index": 99, "company_id": 3, "reason": "越界"}]')

    assert news.match_with_model(ITEMS, COMPANIES) == []


def test_unparseable_output_returns_empty_not_an_exception(monkeypatch):
    """模型回了一坨不是 JSON 的东西，要退回空列表而不是把整次抓取带崩。"""
    _fake_model(monkeypatch, "抱歉，我无法完成这个任务。")

    assert news.match_with_model(ITEMS, COMPANIES) == []


def test_no_model_call_when_ai_is_unavailable(monkeypatch):
    called = []
    monkeypatch.setattr(news, "ai_available", lambda: (False, "没配 API key"))
    monkeypatch.setattr(news.llm, "call", lambda *a, **k: called.append(1))

    with pytest.raises(RuntimeError, match="没配"):
        news.match_with_model(ITEMS, COMPANIES)
    assert not called
