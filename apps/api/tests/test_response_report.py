from datetime import date, timedelta

from stock_decision import access, assistant_agent as agent, repository as repo
from stock_decision import response_model as model, response_report as reports
from stock_decision.database import connection
from stock_decision.schemas import CompanyInput
from test_idor import client  # noqa: F401


def bars(count=400, down=False):
    days, day = [], date.today()
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day -= timedelta(days=1)
    days.reverse()
    return [{"trade_date": day, "date": day, "close": 100 + (-.1 if down else .1) * i,
             "open_price": 100 + (-.1 if down else .1) * i,
             "open": 100 + (-.1 if down else .1) * i,
             "high": 101 + (-.1 if down else .1) * i,
             "low": 99 + (-.1 if down else .1) * i, "volume": 10000}
            for i, day in enumerate(days)]


def company(name="测试公司", symbol="601138", down=False):
    cid = repo.create_company(CompanyInput(name=name, symbol=symbol, industry="电子"))["id"]
    repo.store_daily_history(cid, bars(down=down))
    return cid


def test_fixed_baseline_costs_and_time_blocks():
    result = model.analyze(bars())
    assert result["ready"] and result["regime"] == "up"
    baseline, staged, trend = result["strategies"]
    assert baseline["trades"] == 1 and baseline["cost"] > 0
    assert staged["trades"] == 3
    assert baseline["return_pct"] < (139.9 / 112 - 1) * 100
    assert baseline["excess_pct"] == 0
    assert len(trend["blocks"]) >= 3
    assert trend["blocks"][0]["to"] < trend["blocks"][1]["from"]


def test_future_prices_cannot_change_past_simulation():
    rows = bars()
    records = tuple((r["date"], r["close"], r["open"], r["high"], r["low"]) for r in rows)
    a = model.simulate(records, 120, 200, "trend")
    changed = records[:200] + tuple((r[0], 900., 900., 1000., 800.) for r in records[200:])
    assert model.simulate(changed, 120, 200, "trend") == a
    # Today's close is not allowed to create today's opening trade.
    fallen = records[:120] + ((records[120][0], 60., 112., 113., 50.),) + records[121:]
    assert model.simulate(fallen, 120, 121, "trend")["trades"] == 1


def test_invalid_and_insufficient_data_does_not_invent_results():
    assert model.analyze(bars(30))["ready"] is False
    assert model.analyze(bars(100))["strategies"] == []
    rows = bars()
    rows[-1]["open_price"] = None
    assert model.analyze(rows)["strategies"] == []
    rows[-1]["close"] = float("nan")
    assert model.analyze(rows)["ready"] is False
    rows = bars()
    rows.append(rows[-1])
    assert model.analyze(rows)["ready"] is False
    assert model.analyze(bars(), today=date.today() + timedelta(days=15))["ready"] is False


def test_one_price_bars_never_fill():
    records = tuple((r["date"], 100., 100., 100., 100.) for r in bars())
    result = model.simulate(records, 120, 200, "hold")
    assert result["trades"] == 0 and result["return_pct"] == 0
    assert result["skipped_days"] == 80


def test_report_does_not_enroll_or_overwrite_user_plan():
    cid = company()
    view = reports.read(cid)
    assert view["action"] == "进入观察，先核对估值"
    assert view["position"] is None and view["previous_action"] is None
    assert reports.read(cid)["previous_action"] is None
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM decision_cards").fetchone()["n"] == 0
    repo.store_daily_history(cid, bars(down=True))
    changed = reports.read(cid)
    assert changed["action"] == "先等止跌，不急着抄底"
    assert changed["previous_action"] == view["action"]
    assert reports.read(cid)["previous_action"] == view["action"]


def test_scope_isolation_even_with_same_public_symbol(client):
    cid = company("甲的研究")
    reports.read(cid)
    token = access.set_scope("another")
    try:
        assert reports.read(cid) is None
        assert reports.watch(cid, True) is None
        other = company("乙的研究")
        assert reports.read(other)["previous_action"] is None
    finally:
        access.reset_scope(token)
    client.as_user("another")
    assert client.get(f"/api/v1/companies/{cid}/response-report").status_code == 404
    assert client.post(f"/api/v1/companies/{cid}/response-watch", json={"enabled": True}).status_code == 404


def test_watch_is_change_only_durable_and_pause_cancels_outbox():
    cid = company()
    assert reports.watch(cid, True)["watching"]
    assert agent.scan_subscriptions() == []
    # No repeat alerts for ordinary price changes within the same state.
    rows = bars(); rows[-1]["close"] += .2
    repo.store_daily_history(cid, rows)
    assert agent.scan_subscriptions() == []
    repo.store_daily_history(cid, bars(down=True))
    alerts = agent.scan_subscriptions()
    assert len(alerts) == 1 and "先等止跌" in alerts[0]["message"]
    assert agent.scan_subscriptions() == []
    reports.watch(cid, True)
    assert agent.scan_subscriptions() == []
    reports.watch(cid, False)
    with connection() as conn:
        row = conn.execute("SELECT delivery FROM assistant_alerts WHERE id=?", (alerts[0]["id"],)).fetchone()
        assert row["delivery"] == "skipped"


def test_report_readable_from_same_assistant_tool():
    from stock_decision.assistant_research import read
    from stock_decision.assistant_cloud import tools
    cid = company()
    assert read(cid, "response")["data"]["action"] == reports.read(cid)["action"]
    research = next(t for t in tools() if t["name"] == "research")
    assert "response" in research["input_schema"]["properties"]["section"]["enum"]


def test_watch_input_must_be_boolean(client):
    cid = company()
    assert client.post(f"/api/v1/companies/{cid}/response-watch", json={"enabled": "false"}).status_code == 422
    assert client.get(f"/api/v1/companies/{cid}/response-report").status_code == 200


def test_overview_is_bounded_and_scoped(client):
    cid = company()
    response = client.get(f"/api/v1/response-reports?company_ids={cid}")
    assert response.status_code == 200 and response.json()[0]["company_id"] == cid
    assert client.get("/api/v1/response-reports?company_ids=" + ",".join([str(cid)] * 21)).status_code == 422
    client.as_user("stranger")
    assert client.get(f"/api/v1/response-reports?company_ids={cid}").json() == []


def test_saved_thesis_and_position_constraints_override_trend(client):
    cid = company()
    portfolio = client.post("/api/v1/portfolios", json={"name": "我的组合"}).json()
    result = client.post(f"/api/v1/portfolios/{portfolio['id']}/trades", json={
        "company_id": cid, "side": "buy", "weight_percent": 15,
        "trade_date": date.today().isoformat(), "rationale": "建仓"})
    assert result.status_code < 300
    repo.ensure_decision_card(cid)
    with connection() as conn:
        conn.execute('UPDATE decision_cards SET position_plan=? WHERE company_id=?',
                     ('{"total_percent":10,"stop_buy":"现金流继续恶化"}', cid))
    view = reports.read(cid)
    assert view["summary"]["over_limit"] and view["action"] == "仓位已超计划，先处理超额部分"
    assert any("现金流继续恶化" in text for text in view["conditions"])
    result = client.post(f"/api/v1/companies/{cid}/theses", json={"claim": "原逻辑失效", "status": "broken"})
    assert result.status_code < 300
    assert reports.read(cid)["action"] == "先复核原判断，暂停加仓"


def test_guest_report_does_not_expose_owner_records():
    cid = company()
    token = access.set_scope(access.GUEST_SCOPE)
    try:
        assert reports.read(cid) is None
        assert reports.watch(cid, True) is None
    finally:
        access.reset_scope(token)


def test_rule_upgrade_resets_baseline_without_broadcast(monkeypatch):
    cid = company()
    reports.read(cid)
    reports.watch(cid, True)
    monkeypatch.setattr(model, "VERSION", "response-v-next")
    view = reports.read(cid)
    assert view["previous_action"] is None and view["change_note"] == ""
    assert agent.scan_subscriptions() == []
