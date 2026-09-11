"""管理层承诺兑现台账：公司说过的话，到期之后有没有人回头看。

「未来三年现金分红比例不低于 30%」说出来那天是利好、股价会涨，
而到期日**没有任何提醒、没有任何记录**。结果是一家从不兑现承诺的公司，
和一家次次说到做到的公司，在你的档案里长得一模一样。

这里守两件事：
- **抽取从严。** 一条编出来的承诺会变成你对管理层的成见，而成见不会被复核。
- **自动核对只算数，不下判决。** 「对上了/没对上」是算术，
  「这家管理层靠不靠谱」是判断，判断由人来下。
"""

from datetime import date

import pytest

from stock_decision import promises as pm


def _event(index=1, title="关于回购公司股份的公告", when="2026-03-14"):
    return {"id": 100 + index, "category": "公告", "event_date": when,
            "title": title, "url": f"https://x/{index}"}


class _Reply:
    def __init__(self, text):
        self.text = text


def _extract(monkeypatch, payload, events=None):
    import json
    monkeypatch.setattr(pm.llm, "call", lambda *a, **k: _Reply(json.dumps(payload)))
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    return pm.extract(events or [_event()])


# ------------------------------------------------------------------ 抽取从严

def test_a_promise_without_its_original_wording_is_dropped(monkeypatch):
    """**statement 必须是公告里的原话。**

    改写过的承诺没法拿去跟原文对，而你点进去发现对不上之后，
    整张台账就都不敢信了。
    """
    got = _extract(monkeypatch, {"promises": [
        {"statement": "", "promised_on": "2026-03-14", "source_index": 1}]})
    assert got == []


def test_a_promise_that_points_nowhere_is_dropped(monkeypatch):
    """指不到出处的承诺不许进台账。**猜一个出处比没有出处更糟。**"""
    got = _extract(monkeypatch, {"promises": [
        {"statement": "拟回购不低于3亿元", "promised_on": "2026-03-14", "source_index": 99}]})
    assert got == []


def test_a_promise_without_a_date_it_was_made_is_dropped(monkeypatch):
    """没有"什么时候说的"，这条既核对不了也追溯不了。"""
    got = _extract(monkeypatch, {"promises": [
        {"statement": "拟回购不低于3亿元", "promised_on": "", "source_index": 1}]})
    assert got == []


def test_an_unparseable_due_date_becomes_empty_never_a_guess(monkeypatch):
    """**猜一个到期日会让台账在错误的那天报「未兑现」。**

    「适时」「择机」推不出日期就留空，留空的进「没有明确期限」那一栏等人补。
    """
    got = _extract(monkeypatch, {"promises": [
        {"statement": "将择机回购", "promised_on": "2026-03-14",
         "due_date": "适时", "source_index": 1}]})
    assert got[0]["due_date"] == ""


def test_a_half_specified_check_is_thrown_away_entirely(monkeypatch):
    """量化条件缺一个字段就整组作废。

    只有指标没有目标值的「自动核对」会在到期日算出一个无意义的结论，
    而它看起来跟真的一模一样。
    """
    got = _extract(monkeypatch, {"promises": [
        {"statement": "2026年净利润不低于8亿元", "promised_on": "2026-03-14",
         "check_metric": "净利润", "check_op": ">=", "check_value": None, "source_index": 1}]})
    assert got[0]["check_metric"] == "" and got[0]["check_op"] == ""


def test_an_unknown_metric_is_not_made_checkable(monkeypatch):
    """库里只有净利润、营业收入、分红比例三样。

    「回购完成率」这种硬当成能自动核的，到期只会得出错的结论。
    """
    got = _extract(monkeypatch, {"promises": [
        {"statement": "回购完成率不低于90%", "promised_on": "2026-03-14",
         "check_metric": "回购完成率", "check_op": ">=", "check_value": 90, "source_index": 1}]})
    assert got[0]["check_metric"] == ""


def test_a_well_formed_promise_survives_intact(monkeypatch):
    got = _extract(monkeypatch, {"promises": [
        {"subject": "公司", "statement": "拟回购不低于人民币3亿元，回购期限12个月",
         "category": "回购", "promised_on": "2026-03-14", "due_date": "2027-03-13",
         "source_index": 1}]})
    assert len(got) == 1
    assert got[0]["due_date"] == "2027-03-13"
    assert got[0]["event_id"] == 101
    assert got[0]["source_url"] == "https://x/1", "出处链接要带上，不然核对时无处可查"


def test_no_announcements_means_no_model_call(monkeypatch):
    """没有公告就不调模型——白花一次钱换一个空列表。"""
    called = {"n": 0}
    monkeypatch.setattr(pm.llm, "call", lambda *a, **k: called.__setitem__("n", 1))
    assert pm.extract([]) == []
    assert called["n"] == 0


# ------------------------------------------------------------------ 自动核对是算术

def _promise(metric="净利润", op=">=", value=8e8, period="2026-12-31"):
    return {"check_metric": metric, "check_op": op, "check_value": value, "check_period": period}


def test_the_arithmetic_says_matched_or_not_and_nothing_more():
    facts = {"net_profit": {"2026-12-31": 8.12e8}}
    hit = pm.auto_check(_promise(), facts)
    assert hit["verdict"] == "对上了"
    assert hit["actual"] == 8.12e8

    miss = pm.auto_check(_promise(value=9e8), facts)
    assert miss["verdict"] == "没对上"


def test_a_verdict_is_never_a_judgement():
    """**「对上没对上」是算术，「算不算食言」是判断。**

    自动判成"未兑现"会把一次会计口径变化或一次并表，
    变成你对管理层的永久成见。
    """
    facts = {"net_profit": {"2026-12-31": 5e8}}
    result = pm.auto_check(_promise(), facts)
    # 判决词不许出现在结论字段里。**出现在正文里问你一句是可以的**——
    # 「算不算食言，要你自己看」正是把判断交回给人，跟替人判决是反的。
    assert result["verdict"] == "没对上"
    for verdict in ("未兑现", "食言", "违约", "不可信", "已违约"):
        assert verdict != result["verdict"]
    for asserted in ("管理层不可信", "构成违约", "属于食言", "已经违约"):
        assert asserted not in result["note"], f"这是判决不是算术：{asserted}"
    assert "要你自己看" in result["note"]


def test_missing_data_is_said_out_loud_not_treated_as_a_miss():
    """**没数据不等于没做到。** 算成"没对上"就是凭空给管理层记了一笔。"""
    result = pm.auto_check(_promise(), {"net_profit": {}})
    assert result["verdict"] == "数据不够"
    assert result["actual"] is None


def test_a_promise_with_no_quantitative_condition_says_so():
    result = pm.auto_check({"check_metric": "", "check_op": "", "check_value": None}, {})
    assert result["verdict"] == "不能自动核"
    assert "自己看后续公告" in result["note"]


def test_when_no_period_is_given_it_uses_the_latest_and_says_which():
    """用了哪一期必须说出来——不然你不知道这个"对上了"说的是哪一年。"""
    facts = {"net_profit": {"2025-12-31": 1e8, "2026-12-31": 9e8}}
    result = pm.auto_check(_promise(period=""), facts)
    assert result["period"] == "2026-12-31" and result["verdict"] == "对上了"
    assert "2026-12-31" in result["note"]


# ------------------------------------------------------------------ 汇总

def _row(status="待到期", due="2026-01-01"):
    return {"status": status, "due_date": due}


def test_overdue_promises_get_a_grace_period():
    """到期当天就催是不合理的——定期报告要等披露。"""
    today = date(2026, 8, 8)
    just_due = pm.summarize([_row(due="2026-08-05")], today)
    long_due = pm.summarize([_row(due="2026-06-01")], today)
    assert just_due["due"] == 0
    assert long_due["due"] == 1
    assert str(pm.DUE_GRACE_DAYS) in long_due["note"]


def test_undated_promises_are_counted_separately():
    """没有明确期限的那些永远不会到期，但它们仍然是承诺，要单独数出来。"""
    summary = pm.summarize([_row(due=None), _row(due="2027-01-01")], date(2026, 8, 8))
    assert summary["undated"] == 1


def test_an_empty_ledger_tells_you_where_to_start():
    summary = pm.summarize([], date(2026, 8, 8))
    assert summary["total"] == 0
    assert "从公告里找承诺" in summary["note"]


def test_the_boundary_says_nothing_is_auto_judged():
    summary = pm.summarize([_row()], date(2026, 8, 8))
    assert "不会被自动判成" in summary["boundary"]
    assert "由你来下" in summary["boundary"]


# ------------------------------------------------------------------ 走接口

def test_the_whole_round_trip(monkeypatch):
    """记进台账 → 到期自动比对 → 人来下结论。"""
    from fastapi.testclient import TestClient

    from stock_decision import repository as repo
    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    repo.store_financial_periods(company["id"], [
        {"report_date": "2026-12-31", "revenue": 2.0e11, "net_profit": 8.12e8}])

    saved = client.post(f"/api/v1/companies/{company['id']}/promises", json={"items": [
        {"statement": "2026年净利润不低于8亿元", "promised_on": "2026-03-14",
         "due_date": "2027-04-30", "category": "业绩",
         "check_metric": "净利润", "check_op": ">=", "check_value": 8e8,
         "check_period": "2026-12-31"}]}).json()
    assert saved["saved"] == 1

    view = client.get(f"/api/v1/companies/{company['id']}/promises").json()
    assert view["total"] == 1
    row = view["rows"][0]
    assert row["check"]["verdict"] == "对上了", "算术要真的跑起来，不是留个占位"
    assert row["status"] == "待到期", "算术对上了也不自动改状态——那是判断"

    settled = client.patch(f"/api/v1/promises/{row['id']}",
                           json={"status": "已兑现", "note": "年报核对无误"}).json()
    assert settled["status"] == "已兑现"
    assert client.get(f"/api/v1/companies/{company['id']}/promises").json()["kept"] == 1


def test_the_same_promise_is_never_recorded_twice():
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "000651", "name": "格力电器", "industry": "白色家电"}).json()
    item = {"statement": "承诺三年分红比例不低于30%", "promised_on": "2026-01-01"}
    for _ in range(2):
        client.post(f"/api/v1/companies/{company['id']}/promises", json={"items": [item]})
    assert client.get(f"/api/v1/companies/{company['id']}/promises").json()["total"] == 1


def test_an_unknown_status_is_refused():
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "000333", "name": "美的集团", "industry": "白色家电"}).json()
    client.post(f"/api/v1/companies/{company['id']}/promises", json={"items": [
        {"statement": "承诺不减持", "promised_on": "2026-01-01"}]})
    row = client.get(f"/api/v1/companies/{company['id']}/promises").json()["rows"][0]
    assert client.patch(f"/api/v1/promises/{row['id']}",
                        json={"status": "大概兑现了吧"}).status_code == 400
