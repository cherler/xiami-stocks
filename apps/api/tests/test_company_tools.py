"""工具循环：让模型自己决定看什么，而不是我们替它挑好。

11 个花积分的动作里 10 个是单次问答——我们在代码里挑一份"通用"资料塞给模型，
于是每家公司喂进去的东西都一样。实测茅台那条草稿写的是「估值分位低 + 现金好」，
没有一句关于这门生意。

这里守四件事：
- **跑满轮次不算写完。** 半截资料写出来的判断跟完整资料写出来的长得一模一样，
  而它会被当成后者存进库。
- **工具挂了要如实告诉模型**，不能伪造一个空结果——空结果会被读成
  "查过了，没有数据"，然后它据此断言。
- **回落要留痕。** 模型不支持工具时悄悄退回塞资料那条路，
  使用者看到的是一条明显变差的草稿而没有任何解释。
- **两条路共用同一份收尾**，否则其中一条会悄悄少掉 unknowns 而页面不报错。
"""

from __future__ import annotations

import pytest

from stock_decision import company_tools as ct
from stock_decision import drafting


class _Reply:
    """假的 llm.call_tools 返回。blocks 里有 tool_use 就继续循环。"""

    def __init__(self, blocks):
        self.blocks = blocks

    def as_reply(self):
        return {"content": self.blocks, "stop_reason": "",
                "completion": type("C", (), {"billing": lambda self: {}})()}


def _use(name, tid="t1", **args):
    return {"type": "tool_use", "id": tid, "name": name, "input": args}


def _text(body):
    return {"type": "text", "text": body}


# --------------------------------------------------------------- 循环本身

def test_the_loop_stops_when_the_model_stops_asking(monkeypatch):
    turns = [[_use("financials")], [_text('{"ok": 1}')]]
    monkeypatch.setattr(ct, "specs", lambda: [{"name": "financials"}])

    def _call(*_a, **_k):
        return _Reply(turns.pop(0)).as_reply()

    from stock_decision import llm
    monkeypatch.setattr(llm, "call_tools", _call)
    out = ct.run_loop("sys", [{"role": "user", "content": "q"}],
                      lambda name, args: {"rows": [1, 2, 3]},
                      task="t", max_rounds=5)
    assert out["text"] == '{"ok": 1}'
    assert out["exhausted"] is False
    assert out["tool_calls"] == [{"tool": "financials", "input": {}, "rows": 3}]


def test_running_out_of_rounds_is_not_a_finished_answer(monkeypatch):
    """**跑满还在查 = 手上是半截资料。**

    半截资料写出来的判断跟完整资料写出来的长得一模一样，
    所以必须让调用方知道，而不是把最后一轮的文字当结论。
    """
    monkeypatch.setattr(ct, "specs", lambda: [{"name": "financials"}])
    from stock_decision import llm
    monkeypatch.setattr(llm, "call_tools",
                        lambda *_a, **_k: _Reply([_use("financials")]).as_reply())
    out = ct.run_loop("sys", [{"role": "user", "content": "q"}],
                      lambda name, args: {"rows": []}, task="t", max_rounds=3)
    assert out["exhausted"] is True
    assert out["text"] == "", "跑满时不能给出文字，否则会被当成结论"
    assert len(out["tool_calls"]) == 3


def test_a_broken_tool_is_reported_to_the_model_not_faked_empty(monkeypatch):
    """工具挂了就如实说。**伪造一个空结果会被读成"查过了，没有数据"**，
    然后它据此断言——那是这里最危险的一种错。"""
    turns = [[_use("financials")], [_text("{}")]]
    monkeypatch.setattr(ct, "specs", lambda: [{"name": "financials"}])
    from stock_decision import llm
    monkeypatch.setattr(llm, "call_tools", lambda *_a, **_k: _Reply(turns.pop(0)).as_reply())

    def _boom(name, args):
        raise RuntimeError("表不存在")

    out = ct.run_loop("sys", [{"role": "user", "content": "q"}], _boom,
                      task="t", max_rounds=4)
    assert out["exhausted"] is False
    payload = out["payloads"][0]
    assert "error" in payload and "表不存在" in payload["error"]


def test_row_count_covers_every_tool_shape():
    """少一个键名不会报错，只会让「查了几行」显示成 1 ——
    而那正是使用者用来判断"它有没有真查"的数。"""
    assert ct.row_count({"rows": [1, 2]}) == 2
    assert ct.row_count({"periods": [1, 2, 3]}) == 3
    assert ct.row_count({"theses": [1]}) == 1
    assert ct.row_count({"promises": [1, 2]}) == 2
    assert ct.row_count({"items": [1, 2, 3, 4]}) == 4
    assert ct.row_count({"error": "没有这个工具"}) == 0


def test_the_advocate_and_the_drafter_share_one_tool_list():
    """各写一份会立刻分叉，然后其中一边悄悄少掉一个工具或少一道隔离。"""
    from stock_decision import devils_advocate as da

    assert [t["name"] for t in da.tool_specs()] == [t["name"] for t in ct.specs()]


def test_no_tool_takes_a_company_id():
    """**隔离的底线不靠提示词守。** 工具不接受 company_id 参数，
    模型就没有办法去查别家公司，更没有办法去查别人的数据。"""
    for spec in ct.specs():
        properties = spec["input_schema"].get("properties", {})
        assert "company_id" not in properties, spec["name"]
        assert "symbol" not in properties, spec["name"]


# --------------------------------------------------------------- 起草那一路

def test_the_drafter_refuses_to_write_from_half_the_data(monkeypatch):
    """跑满轮次时**宁可不给**。一条半截草稿会被存进库，然后当成基准用一年。"""
    monkeypatch.setattr(drafting, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(drafting, "build_prompt", lambda *_a: ("资料", ["净利率"]))
    monkeypatch.setattr(ct, "run_loop",
                        lambda *a, **k: {"text": "{}", "tool_calls": [], "payloads": [],
                                         "messages": [], "billing": {}, "exhausted": True})
    with pytest.raises(RuntimeError, match="还没写出草稿"):
        drafting.draft_with_tools({"name": "x", "symbol": "1"}, lambda n, a: {})


def test_the_tool_prompt_keeps_every_hard_rule(monkeypatch):
    """**改的只是"事实从哪来"。** 能自己查库之后编数字的诱惑更大而不是更小，
    所以不给目标价、不许用记忆补、反证条件必须可核对，一条都不能松。"""
    assert drafting.TOOL_SYSTEM_PROMPT != drafting.DRAFT_SYSTEM_PROMPT, "替换没匹配上"
    for rule in ("不给目标价", "绝对不要凭记忆补充", "反证条件必须能用列出的可跟踪字段核对",
                 "也不要自己做任何计算"):
        assert rule in drafting.TOOL_SYSTEM_PROMPT, rule


def test_falling_back_to_the_fixed_payload_leaves_a_trace(monkeypatch):
    """模型不支持工具时回落，**但要说出来**——

    悄悄回落的话，使用者看到的是一条明显变差的草稿而没有任何解释，
    只会以为"这功能今天不太行"。
    """
    from stock_decision import repository as repo

    company = {"id": 1, "name": "贵州茅台", "symbol": "600519"}
    monkeypatch.setattr(repo, "get_company", lambda _id: company)
    monkeypatch.setattr(repo, "company_tool_runner", lambda _id: (lambda n, a: {}))

    def _no_tools(*_a, **_k):
        raise RuntimeError("当前模型（X）似乎不支持工具调用。")

    monkeypatch.setattr(drafting, "draft_with_tools", _no_tools)
    monkeypatch.setattr(drafting, "build_prompt", lambda *_a: ("一二三", []))
    monkeypatch.setattr(repo, "draft_with_model", lambda *_a: {
        "claim": "c", "counter_condition": "cc", "next_review_trigger": "r",
        "used_facts": [], "unknowns": [], "trackable_fields": [],
        "model": "X", "method": None, "boundary": "b"})

    draft = repo.draft_thesis(1)
    assert "不支持工具调用" in draft.read
    assert "没有查库" in draft.read


def test_other_failures_are_not_swallowed_by_the_fallback(monkeypatch):
    """只对"不支持工具"回落。**别的错也吞掉的话，一条半截草稿会被当成正常结果。**"""
    from stock_decision import repository as repo

    monkeypatch.setattr(repo, "get_company", lambda _id: {"id": 1, "name": "x", "symbol": "1"})
    monkeypatch.setattr(repo, "company_tool_runner", lambda _id: (lambda n, a: {}))

    def _exhausted(*_a, **_k):
        raise RuntimeError("查了 8 轮还没写出草稿，这次没有结果。")

    monkeypatch.setattr(drafting, "draft_with_tools", _exhausted)
    with pytest.raises(RuntimeError, match="8 轮"):
        repo.draft_thesis(1)


# --------------------------------------------------------------- 读公告正文（#41 接到 #42）

def test_reading_an_announcement_needs_a_keyword(monkeypatch):
    """不指明读哪一条就不读。**「随便挑一条」等于让模型自己选证据。**"""
    from stock_decision import repository as repo

    out = repo.company_tool_runner(1)("announcement_text", {})
    assert "error" in out and "关键词" in out["error"]


def test_an_unfetchable_announcement_is_not_an_empty_string(monkeypatch):
    """取不到正文要说取不到。**空串会被读成"这条公告什么都没写"**，
    然后它据此断言这条公告没有承诺、没有信息。"""
    from fastapi.testclient import TestClient

    from stock_decision import repository as repo
    from stock_decision.main import app

    company = TestClient(app).post("/api/v1/companies", json={
        "symbol": "000651", "name": "格力电器", "industry": "白色家电"}).json()
    repo.store_company_profile(company["id"], {"events": [{
        "category": "公告", "event_date": "2026-08-04",
        "title": "关于股份回购进展情况的公告", "detail": "",
        "url": ("http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000651"
                "&announcementId=1225455000&announcementTime=2026-08-04"),
        "source": "巨潮资讯公告"}]})
    monkeypatch.setattr(repo, "announcement_bodies",
                        lambda events, budget=None: {"bodies": {}, "read": 0,
                                                     "failed": 1, "pending": 0})
    out = repo.company_tool_runner(company["id"])(
        "announcement_text", {"title_contains": "回购"})
    assert len(out["rows"]) == 1
    assert out["rows"][0]["text"] is None, "取不到时必须是 None，不能是空串"
    assert "取不到正文" in out["rows"][0]["note"]


def test_the_keyword_goes_through_a_parameter_not_the_sql(monkeypatch):
    """LIKE 的 % 必须走参数。**字面 % 会被 psycopg2 当成占位符**，
    这个坑本仓踩过不止一次，表现是 IndexError 而不是 SQL 报错。
    """
    from stock_decision import repository as repo

    out = repo.company_tool_runner(999999)("announcement_text", {"title_contains": "100%"})
    # 查不到是对的（公司不存在），但它必须是"没有这条公告"，不是崩掉
    assert "error" in out
