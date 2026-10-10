"""User-facing assistant flows, durable writes and trusted confirmation."""
import hashlib
import hmac
import importlib.util
import json
import time
from datetime import date
from pathlib import Path

import pytest

from stock_decision import access, assistant, assistant_agent as agent, repository
from stock_decision.database import connection, now_iso
from stock_decision.schemas import CompanyInput
from test_idor import client  # noqa: F401


def company(name="工业富联", symbol="601138"):
    return repository.create_company(CompanyInput(name=name, symbol=symbol, industry="电子"))["id"]


def message(operation, original="帮我记住这个想法", mid="m1", **kwargs):
    return agent.Envelope(command=agent.Command(operation=operation, **kwargs), channel="feishu", chat_id="private",
        sender_id="owner", session_key="feishu:private", message_id=mid, original_text=original, sent_at=int(time.time()))


def run(operation, original="帮我记住这个想法", mid="m1", **kwargs):
    return agent.dispatch(message(operation, original, mid, **kwargs))


def test_typo_and_alias_resolver_does_not_correct_codes():
    company("海光信息", "688041")
    assert assistant.resolve("海光信心")[0]["match"] == "fuzzy"
    assert assistant.resolve("海光")[0]["symbol"] == "688041"
    assert assistant.resolve("SH688041")[0]["symbol"] == "688041"
    assert assistant.resolve("688042") == []
    with pytest.raises(agent.AgentError, match="确认公司"):
        run("remember", stock="海光信心", text="这是一条想法")


def test_save_is_visible_on_web_and_retry_is_single_record():
    cid = company()
    e = message("remember", stock="工业富联", text="看订单能否转成现金")
    result = agent.dispatch(e)
    again = agent.dispatch(e)
    assert again["record_id"] == result["record_id"] and again["replayed"]
    reports = repository.list_reports(cid)
    assert len(reports) == 1
    assert "看订单能否转成现金" in reports[0]["body"]
    assert "用户原话" in reports[0]["body"]
    assert assistant.my_stocks()[0]["company_id"] == cid
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM decision_cards").fetchone()["n"] == 0
    context = run("context", mid="next", stock="它")
    assert context["company"]["id"] == cid
    assert context["records"][0]["id"] == result["report_id"]


def test_correction_and_undo_preserve_original():
    cid = company()
    first = run("remember", stock="工业富联", text="只考虑小仓位参与")
    revised = run("correct", mid="m2", record_id=first["record_id"], text="暂时观察现金流，不急着参与")
    assert len(repository.list_reports(cid)) == 2
    run("undo", mid="m3", record_id=revised["record_id"])
    reports = repository.list_reports(cid)
    assert len(reports) == 1 and reports[0]["id"] == first["report_id"]
    run("undo", mid="m4", record_id=first["record_id"])
    assert repository.list_reports(cid) == []


def test_confirmation_requires_real_text_and_survives_new_call():
    cid = company()
    draft = run("prepare_fill", stock="工业富联", price=30, shares=100)
    with pytest.raises(agent.AgentError, match="本人回复"):
        run("confirm", mid="m2", record_id=draft["record_id"])
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM decision_fills").fetchone()["n"] == 0
    confirmed = run("confirm", original="确认 " + draft["record_id"], mid="m3", record_id=draft["record_id"])
    assert confirmed["fill_id"]
    again = run("confirm", original="确认 " + draft["record_id"], mid="m3", record_id=draft["record_id"])
    assert again["fill_id"] == confirmed["fill_id"]
    assert len(repository.company_fills(cid)) == 1
    run("undo", mid="m4", record_id=confirmed["record_id"])
    assert repository.company_fills(cid) == []


def test_changed_mind_invalidates_earlier_draft():
    company()
    old = run("prepare_fill", stock="工业富联", price=30)
    new = run("prepare_fill", mid="m2", stock="工业富联", price=31)
    with pytest.raises(agent.AgentError, match="取消"):
        run("confirm", original="确认 " + old["record_id"], mid="m3", record_id=old["record_id"])
    run("cancel", mid="m4", record_id=new["record_id"])
    with pytest.raises(agent.AgentError, match="取消"):
        run("confirm", original="确认 " + new["record_id"], mid="m5", record_id=new["record_id"])


def test_plan_change_between_preview_and_confirm_is_not_silently_accepted():
    cid = company()
    repository.save_decision_card(cid, {"watch_reason": "看现金流", "order_plan": {"price": 30, "fraction": "1/3", "why_now": "记录计划"}})
    draft = run("prepare_fill", stock="工业富联", price=30)
    repository.save_decision_card(cid, {"order_plan": {"price": 28, "fraction": "1/3", "why_now": "记录计划"}})
    with pytest.raises(agent.AgentError, match="计划在确认前"):
        run("confirm", original="确认 " + draft["record_id"], mid="m2", record_id=draft["record_id"])


def quote(symbol, price):
    with connection() as conn:
        conn.execute("INSERT INTO market_snapshots (symbol, price, market_timestamp, refreshed_at, source) VALUES (?, ?, ?, ?, 'test')",
                     (symbol, price, date.today().isoformat() + 'T10:00:00+08:00', now_iso()))


def test_watch_threshold_is_not_autocorrected_and_alert_rearms():
    company()
    quote("601138", 32)
    with pytest.raises(agent.AgentError, match="补零"):
        run("watch", original="300以下提醒", stock="工业富联", kind="price", threshold=30)
    saved = run("watch", original="30以下提醒", stock="工业富联", kind="price", threshold=30)
    quote("601138", 29)
    assert len(agent.scan_subscriptions()) == 1
    assert agent.scan_subscriptions() == []
    quote("601138", 30.1)
    assert agent.scan_subscriptions() == []
    quote("601138", 32)
    assert agent.scan_subscriptions() == []
    quote("601138", 29)
    assert len(agent.scan_subscriptions()) == 1
    run("pause_watch", mid="m2", record_id=str(saved["subscription_id"]))
    assert agent.scan_subscriptions() == []


def test_research_watch_only_new_evidence_and_compare_keeps_context():
    cid = company()
    run("remember", stock="工业富联", text="只看利润是否变成现金")
    run("watch", mid="m2", stock="工业富联", kind="research", text="现金流是否改善")
    assert agent.scan_subscriptions() == []
    first = run("compare", mid="m3", stock="工业富联")
    assert first["baseline_at"] is None and first["changes"] is None
    with connection() as conn:
        conn.execute("""INSERT INTO company_calendar_events
            (company_id, category, event_date, title, url, source, refreshed_at)
            VALUES (?, '公告', ?, '半年报披露', 'https://example.com/report', '交易所', ?)""", (cid, date.today().isoformat(), now_iso()))
    alerts = agent.scan_subscriptions()
    assert len(alerts) == 1 and "现金流是否改善" in alerts[0]["message"]
    assert agent.scan_subscriptions() == []
    compared = run("compare", mid="m4", stock="它")
    assert compared["changes"]["announcements"][0]["title"] == "半年报披露"
    assert "利润是否变成现金" in compared["records"][0]["body"]


def test_records_and_memories_are_isolated():
    company()
    own = run("remember", stock="工业富联", text="我的私人研究")
    token = access.set_scope("other-user")
    try:
        assert run("context")["recent_actions"] == []
        with pytest.raises(agent.AgentError):
            run("undo", record_id=own["record_id"])
        assert assistant.resolve("工业富联") == []
    finally:
        access.reset_scope(token)


def test_signature_identity_and_confirmation_route(client, monkeypatch):  # noqa: F811
    company()
    monkeypatch.setattr(agent, "bridge_config", lambda: {"secret": "testing-secret", "channel": "feishu",
                                                        "chat_id": "private", "sender_ids": ["owner"]})
    e = message("remember", stock="工业富联", text="签名保存的研究")
    raw = e.model_dump_json().encode()
    assert client.post("/api/v1/assistant/command", content=raw).status_code == 403
    sig = hmac.new(b'testing-secret', raw, hashlib.sha256).hexdigest()
    assert client.post("/api/v1/assistant/command", content=raw, headers={"X-Stock-Signature": sig}).status_code == 200
    tampered = raw.replace(b'owner', b'other')
    assert client.post("/api/v1/assistant/command", content=tampered, headers={"X-Stock-Signature": sig}).status_code == 403


def test_mcp_has_no_model_callable_confirmation():
    source = (Path(__file__).resolve().parents[2] / "assistant/mcp_server.py").read_text()
    assert "def confirm_fill(" not in source
    assert "_proposals" not in source


def test_same_message_cannot_confirm_its_own_draft_and_plain_confirm_works():
    company()
    draft = run("prepare_fill", original="确认", stock="工业富联", price=30)
    with pytest.raises(agent.AgentError, match="本人回复"):
        run("confirm", original="确认", record_id=draft["record_id"])
    result = run("confirm", original="确认", mid="m2", record_id=draft["record_id"])
    assert result["fill_id"]


def test_expired_proposal_and_other_session_cannot_commit():
    company()
    draft = run("prepare_fill", stock="工业富联", price=30)
    e = message("confirm", original="确认", mid="m2", record_id=draft["record_id"])
    e.session_key = 'other-session'
    with pytest.raises(agent.AgentError):
        agent.dispatch(e)
    with connection() as conn:
        conn.execute("UPDATE assistant_actions SET created_at = '2000-01-01T00:00:00' WHERE id = ?", (draft["record_id"],))
    assert run("confirm", original="确认", mid="m3", record_id=draft["record_id"])["state"] == "expired"


def test_concurrent_retry_does_not_duplicate_report():
    from concurrent.futures import ThreadPoolExecutor
    cid = company()
    e = message("remember", stock="工业富联", text="同一消息网络重试")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(agent.dispatch, [e, e]))
    assert results[0]["report_id"] == results[1]["report_id"]
    assert len(repository.list_reports(cid)) == 1


def test_repeating_unchanged_watch_does_not_realert():
    company()
    quote('601138', 29)
    first = run('watch', original='30以下提醒', stock='工业富联', kind='price', threshold=30)
    assert len(agent.scan_subscriptions()) == 1
    run('watch', original='30以下提醒', mid='m2', stock='工业富联', kind='price', threshold=30)
    assert agent.scan_subscriptions() == []
    assert first['subscription_id'] == run('context')['subscriptions'][0]['id']


def test_replay_of_undone_note_does_not_claim_it_is_saved():
    company()
    saved = run('remember', stock='工业富联', text='记录这次判断')
    run('undo', mid='m2', record_id=saved['record_id'])
    replay = run('remember', stock='工业富联', text='记录这次判断')
    assert replay['state'] == 'undone' and '已撤销' in replay['message']


def test_assistant_rls_tables_hide_direct_queries():
    from stock_decision.database import is_postgres
    if not is_postgres():
        pytest.skip('database RLS is PostgreSQL only')
    company()
    run('remember', stock='工业富联', text='私人记录')
    run('watch', mid='m2', stock='工业富联', kind='research')
    token = access.set_scope('other-user')
    try:
        with connection() as conn:
            for table in ('assistant_actions', 'assistant_memory', 'assistant_subscriptions'):
                assert conn.execute(f'SELECT COUNT(*) AS n FROM {table}').fetchone()['n'] == 0
    finally:
        access.reset_scope(token)


def test_paused_watch_removes_only_its_pending_message_parts(monkeypatch):
    from stock_decision import assistant_delivery
    cid = company()
    price = run("watch", original="30以下提醒", stock="工业富联", kind="price", threshold=30)
    research = run("watch", mid="r", stock="工业富联", kind="research", text="看现金流")
    quote("601138", 29)
    with connection() as conn:
        conn.execute("""INSERT INTO company_calendar_events
            (company_id, category, event_date, title, url, source, refreshed_at)
            VALUES (?, '公告', ?, '半年报披露', '', '交易所', ?)""", (cid, date.today().isoformat(), now_iso()))
    alerts = agent.scan_subscriptions()
    assert len(alerts) == 1
    run("pause_watch", mid="pause1", record_id=str(price["subscription_id"]))
    with connection() as conn:
        row = conn.execute("SELECT * FROM assistant_alerts WHERE id = ?", (alerts[0]["id"],)).fetchone()
        assert "半年报披露" in row["message"] and "现价" not in row["message"]
        assert row["delivery"] == "pending"
    run("pause_watch", mid="pause2", record_id=str(research["subscription_id"]))
    monkeypatch.setattr(assistant, "deliver", lambda _: pytest.fail("paused alert must not send"))
    assert assistant_delivery.transfer(alerts[0])[0] == "skipped"


def test_changed_threshold_cancels_failed_old_alert():
    company()
    run("watch", original="30以下提醒", stock="工业富联", kind="price", threshold=30)
    quote("601138", 29)
    alert = agent.scan_subscriptions()[0]
    assistant._record_delivery(alert["id"], "failed", "offline")
    run("watch", original="改成28以下提醒", mid="changed", stock="工业富联", kind="price", threshold=28)
    with connection() as conn:
        row = conn.execute("SELECT delivery FROM assistant_alerts WHERE id = ?", (alert["id"],)).fetchone()
        assert row["delivery"] == "skipped"
    assert agent.scan_subscriptions() == []


def test_missing_legacy_receipt_does_not_requeue_for_duplicate_send(monkeypatch):
    from types import SimpleNamespace
    from stock_decision import assistant_delivery
    monkeypatch.setattr(assistant_delivery, "bridge_config", lambda: {"nanobot_python": "python", "workspace": "/test"})
    monkeypatch.setattr(assistant_delivery.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout='{"state":"pending"}'))
    assert assistant_delivery.transfer({"id": 123, "message": "already queued"}, receipt=True) == ("queued", "")
