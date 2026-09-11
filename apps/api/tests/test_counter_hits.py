"""反证命中：公告踩到你写下的反证条件时要提醒，没踩到时不能瞎报。

**误报比漏报贵。** 误报一次，下次真命中时你就不信它了；漏报只是回到「靠自己读公告」
的原状。所以这里两个方向都要测——只测「该报的报了」，会养出一个见什么都报的东西。

模型那一段单独测（要花钱、要联网），这里测的是它周围那圈判断：
越界的序号、说不出理由的命中、没写反证时不许自由发挥。
"""

import pytest

from stock_decision import access, counters, repository
from stock_decision.schemas import CompanyInput, ThesisCreate


def test_no_counter_condition_means_no_model_call(monkeypatch):
    """没写反证条件时直接返回空。

    **不能在这种情况下让模型自由发挥**——那等于凭空发明一条他没写过的卖出理由。
    """
    called = []
    monkeypatch.setattr(counters.llm, "call", lambda *a, **k: called.append(1))

    events = [{"id": 1, "title": "分红方案", "category": "分红", "event_date": "2026-01-01"}]
    assert counters.find_hits(events, [{"id": 1, "claim": "x", "counter_condition": ""}]) == []
    assert counters.find_hits(events, []) == []
    assert not called, "没有反证条件却调用了模型"


def test_no_events_means_no_model_call(monkeypatch):
    called = []
    monkeypatch.setattr(counters.llm, "call", lambda *a, **k: called.append(1))
    assert counters.find_hits([], [{"id": 1, "claim": "x", "counter_condition": "净利率低于 10%"}]) == []
    assert not called


def _fake_model(monkeypatch, payload: str):
    class _Completion:
        text = payload
    monkeypatch.setattr(counters.llm, "call", lambda *a, **k: _Completion())
    monkeypatch.setattr(counters, "ai_available", lambda: (True, "测试"))


EVENTS = [{"id": 11, "title": "分红方案 10派12元", "category": "分红", "event_date": "2026-09-01"}]
THESES = [{"id": 21, "claim": "赌分红持续", "counter_condition": "分红低于 10派17.50元"}]


def test_a_real_hit_is_recorded(monkeypatch):
    _fake_model(monkeypatch, '{"hits": [{"event_index": 1, "thesis_index": 1, '
                             '"clause": "分红低于 10派17.50元", "reason": "公告是 10派12元，低于阈值"}]}')
    hits = counters.find_hits(EVENTS, THESES)
    assert len(hits) == 1
    assert hits[0]["event_id"] == 11 and hits[0]["thesis_id"] == 21
    assert "10派12元" in hits[0]["reason"]


def test_a_hit_without_a_reason_is_dropped(monkeypatch):
    """说不出为什么命中的不算命中——那种「感觉方向不好」正是误报的来源。"""
    _fake_model(monkeypatch, '{"hits": [{"event_index": 1, "thesis_index": 1, '
                             '"clause": "分红下调", "reason": ""}]}')
    assert counters.find_hits(EVENTS, THESES) == []


@pytest.mark.parametrize("bad", [
    '{"hits": [{"event_index": 9, "thesis_index": 1, "clause": "x", "reason": "y"}]}',
    '{"hits": [{"event_index": 1, "thesis_index": 9, "clause": "x", "reason": "y"}]}',
    '{"hits": [{"event_index": "一", "thesis_index": 1, "clause": "x", "reason": "y"}]}',
])
def test_out_of_range_indexes_are_dropped_not_guessed(monkeypatch, bad):
    """模型给了越界序号就丢掉这条，不要猜它想指哪个。

    猜错的后果是把命中挂到别的判断上——那比漏报难查得多。
    """
    _fake_model(monkeypatch, bad)
    assert counters.find_hits(EVENTS, THESES) == []


def test_empty_hits_is_the_normal_case(monkeypatch):
    _fake_model(monkeypatch, '{"hits": []}')
    assert counters.find_hits(EVENTS, THESES) == []


def test_acknowledging_removes_it_from_the_open_list():
    company = repository.create_company(
        CompanyInput(symbol="601318", name="中国平安", industry="保险"))
    thesis = repository.create_thesis(company["id"], ThesisCreate(
        claim="赌分红持续", counter_condition="分红低于 10派17.50元"))
    # 收件箱条目在 company_calendar_events，不是 research_events —— 命中挂的是前者
    from stock_decision.database import connection, now_iso
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, inbox_status, source, refreshed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (company["id"], "分红", "分红方案 10派12元", "2026-09-01", "待核验", "测试", now_iso()))
        event_id = cur.lastrowid
        conn.execute(
            """INSERT INTO counter_hits (user_id, event_id, thesis_id, clause, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (access.OWNER_SCOPE, event_id, thesis["id"], "分红低于 17.50", "10派12元", now_iso()))

    open_hits = repository.open_counter_hits()
    assert len(open_hits) == 1

    assert repository.acknowledge_counter_hit(open_hits[0]["id"]) is True
    assert repository.open_counter_hits() == [], "标记看过之后不该还顶在前面"


# --------------------------------------------------------------- 两处口径必须一致

def test_a_counter_already_seen_at_the_last_review_is_not_a_todo():
    """**复核完决定维持原状，是一个已经做出的决定，不是一件待办。**

    实测踩过：首页说「有 2 条反证，但逻辑状态还没跟着改」，点进复核工作台是空的。
    那两条反证是 08-04 归档的，判断在 08-06 复核过、当时就看见了——
    使用者复核完决定维持「观察中」，而首页从此永远在催他。

    首页和复核工作台是同一个问题的两个入口，**口径不一致的那次没人会发现**，
    因为它表现成"点进去是空的"，而不是报错。
    """
    from fastapi.testclient import TestClient

    from stock_decision import repository as repo
    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "601318", "name": "中国平安", "industry": "保险业"}).json()
    thesis = client.post(f"/api/v1/companies/{company['id']}/theses", json={
        "claim": "赌的是低估值兑现到股东回报", "counter_condition": "分红比例低于 20%",
        "status": "watching", "next_review_trigger": "年报"}).json()
    client.post(f"/api/v1/companies/{company['id']}/evidences", json={
        "thesis_id": thesis["id"], "source_name": "年报", "excerpt": "分红比例下滑",
        "polarity": "counter", "occurred_at": "2026-08-04"})

    # 还没复核：首页该报，队列该有
    board = repo.decision_board()["rows"]
    assert any(row["action_kind"] == "反证" for row in board), "没复核过就该报"
    assert len(repo.review_queue()) >= 1

    # 复核过之后：两边都该安静下来。
    # **证据要早于复核时刻**——这正是实测踩到的那个形状：
    # 反证 08-04 归档，判断 08-06 复核，复核时就已经看见它了。
    with repo.connection() as conn:
        conn.execute("UPDATE evidences SET created_at = ? WHERE thesis_id = ?",
                     ("2026-08-04T00:28:41", thesis["id"]))
        conn.execute("UPDATE theses SET last_reviewed_at = ? WHERE id = ?",
                     ("2026-08-06T22:31:32", thesis["id"]))
    board = repo.decision_board()["rows"]
    counters = [row for row in board if row["action_kind"] == "反证"]
    queue = repo.review_queue()
    assert counters == [] and queue == [], (
        f"复核过之后两边都该安静：首页 {len(counters)} 条、队列 {len(queue)} 条")
