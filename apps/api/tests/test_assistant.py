"""助理：替你盯、交易前替你拦（assistant.py）。

## 这里守的几件事

1. 「你的票」是四个清单的并集，**产业链导入的参考资料不算**——
   那两百多家要是也会响，这个助理就又变回了一份作业。
2. 交易前核验**只读**：问一句「我想买茅台」，不许顺手给茅台建一张卡。
3. 到价提醒**只在进去那一刻响一次**；边上来回蹭不重复响；改了计划价算新的一档。
4. **送不出去要落库**：「以为提醒过了、其实没送到」是这个功能最坏的坏法。
5. 别人的数据域只记不发——飞书那头是站主一个人的对话。
6. 说话只拿你自己的规则：没有「建议买」「目标价」。
"""

from __future__ import annotations

import os
import stat
from datetime import date, timedelta

import pytest

from stock_decision import access, assistant, repository
from stock_decision.database import connection, now_iso
from stock_decision.schemas import CompanyInput, PortfolioCreate, ThesisCreate

BANDS = {"watch": 310.0, "fair": 300.0, "ideal": 280.0, "extreme": 270.0}
ORDER = {"price": 300, "fraction": "1/3",
         "why_now": "去宁德化被叙事放大"}
PLAN = {"total_percent": 20, "first_percent": 6.7,
        "stop_buy": "市占率持续明显下降 / 毛利率结构性恶化"}

TODAY = date.today()


def _company(symbol: str, name: str, group: str = "链 · 动力电池") -> int:
    return repository.create_company(CompanyInput(symbol=symbol, name=name, industry="电池",
                                                  watch_group=group))["id"]


def _quote(symbol: str, price: float, *, day: date = TODAY, clock: str = "10:30") -> None:
    """一条盘中快照。**时点写在 market_timestamp 里**：新不新看的是它。"""
    with connection() as conn:
        conn.execute(
            """INSERT INTO market_snapshots (symbol, price, change_percent, market_timestamp,
                                             source, refreshed_at)
               VALUES (?, ?, ?, ?, 'test', ?)""",
            (symbol, price, -0.5, f"{day.isoformat()}T{clock}:00+08:00", now_iso()))


def _bar(symbol: str, day: date, close: float) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO price_bars (symbol, trade_date, close, source, refreshed_at)
               VALUES (?, ?, ?, 'test', ?)""",
            (symbol, day.isoformat(), close, now_iso()))


def _planned_card(symbol: str = "300750", name: str = "宁德时代", *, to: str = "valued",
                  order: dict | None = None) -> int:
    """一张写好了价格带和计划价的卡，停在 `to` 那一格。"""
    company = _company(symbol, name)
    repository.create_thesis(company, ThesisCreate(
        claim="好公司遇到暂时性麻烦", counter_condition="份额连续两季下降"))
    repository.save_valuation(company, {
        "years": 5, "discount_rate": 10,
        "scenarios": [
            {"key": "bear", "revenue_growth": -5.0, "net_margin": 8.0, "exit_pe": 12.0},
            {"key": "base", "revenue_growth": 8.0, "net_margin": 12.0, "exit_pe": 18.0},
            {"key": "bull", "revenue_growth": 18.0, "net_margin": 15.0, "exit_pe": 25.0},
        ],
        "note": "测试用"})
    repository.save_decision_card(company, {
        "watch_reason": "去宁德化被叙事放大", "bands": BANDS,
        "position_plan": PLAN, "order_plan": order or ORDER})
    path = ["researching", "valued", "waiting"]
    for state in path[:path.index(to) + 1] if to in path else []:
        repository.move_decision_state(company, state, "")
    return company


def _cards() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM decision_cards").fetchone()["n"])


def _alerts() -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM assistant_alerts ORDER BY id").fetchall()]


# ───────────────────────────────────────────────────────── 你的票

def test_你的票是四个清单的并集_参考资料不算():
    in_group = _company("600519", "贵州茅台", group="观察池")
    carded = _company("300274", "阳光电源")
    repository.ensure_decision_card(carded)
    thesised = _company("002423", "中粮资本")
    repository.create_thesis(thesised, ThesisCreate(claim="低估的金控平台"))
    held = _company("000651", "格力电器")
    portfolio = repository.create_portfolio(PortfolioCreate(name="主组合", amount_mode="full"))["id"]
    repository.set_holding(portfolio, held, 4700, 41.74)
    _company("601615", "明阳智能", group="链 · 风电")     # 只是产业链参考资料

    rows = {row["name"]: row for row in assistant.my_stocks()}
    assert set(rows) == {"贵州茅台", "阳光电源", "中粮资本", "格力电器"}, \
        "参考资料混进了「你的票」——它们一旦也会响，助理就又变回一份作业"
    assert "分组" in rows["贵州茅台"]["in_lists"]
    assert "决策卡" in rows["阳光电源"]["in_lists"]
    assert "投资逻辑" in rows["中粮资本"]["in_lists"]
    assert "持仓" in rows["格力电器"]["in_lists"]
    assert rows["格力电器"]["holding"]["shares"] == pytest.approx(4700)


def test_说宁德先找你的票():
    _planned_card()                                   # 宁德时代：有卡
    _company("002709", "宁德新能源材料")                # 同名前缀的参考资料
    found = assistant.resolve("宁德")
    assert [row["name"] for row in found] == ["宁德时代"]
    assert found[0]["mine"] is True


# ───────────────────────────────────────────────────────── 用哪个价

def test_盘中价比日线新就用盘中价():
    company = _company("300750", "宁德时代", group="观察池")
    _bar("300750", TODAY - timedelta(days=1), 301.0)
    _quote("300750", 296.41)
    with connection() as conn:
        quote = assistant.freshest_price(conn, "300750")
    assert quote["price"] == pytest.approx(296.41) and quote["source"] == "盘中", \
        "到价要今天就知道：盘中价比昨天收盘新，就该用盘中价"
    assert company


def test_收盘后用当天日线():
    _company("300750", "宁德时代", group="观察池")
    _quote("300750", 296.41, clock="14:59")
    _bar("300750", TODAY, 297.0)
    with connection() as conn:
        quote = assistant.freshest_price(conn, "300750")
    assert quote["price"] == pytest.approx(297.0) and quote["source"] == "收盘"


# ───────────────────────────────────────────────────────── 交易前核验

def test_没写过计划的票_核验不会顺手建一张卡():
    company = _company("600519", "贵州茅台", group="观察池")
    _quote("600519", 1235.6)
    before = _cards()
    view = assistant.pre_trade_check(company)
    assert view["has_plan"] is False and "没有决策卡" in view["text"]
    assert _cards() == before, "问一句「我想买茅台」就给它建了一张卡——闭环页上凭空多出一只"


def test_到了计划价又在合理区_核验说对得上():
    company = _planned_card()
    _quote("300750", 296.41)
    view = assistant.pre_trade_check(company)
    assert view["verdict"] == "和你写下的计划对得上", view["text"]
    marks = {item["key"]: item["mark"] for item in view["items"]}
    assert marks["price"] == "✓" and marks["band"] == "✓" and marks["state"] == "✓"
    assert "1/3" in view["text"] and "20%" in view["text"]
    assert "停止买入" in view["text"], "停止买入是自由文本，判不了，但必须摆出来请你自己对"
    assert "去宁德化被叙事放大" in view["text"], "你当时写的理由要摆在你眼前"


def test_价格高过计划价_要点名是价格():
    company = _planned_card()
    _quote("300750", 305.0)
    view = assistant.pre_trade_check(company)
    assert "价格" in view["deviations"]
    assert "高 1.7%" in view["text"]


def test_还在研究中的卡_核验要拦():
    company = _planned_card(to="researching")
    _quote("300750", 296.41)
    view = assistant.pre_trade_check(company)
    assert "闭环状态" in view["deviations"]
    assert "没估值就没有买点" in view["text"]


def test_卡在持仓中_账本却是空的_要点破():
    """清掉持仓准备重填时，卡片会停在「持仓中」。核验不能一边说「这笔是加仓」一边说「没有持仓」。"""
    company = _planned_card(to="waiting")
    portfolio = repository.create_portfolio(PortfolioCreate(name="主组合", amount_mode="full"))["id"]
    repository.set_holding(portfolio, company, 100, 290.0)
    repository.evaluate_decision_triggers()          # 按账本校正：推到「持仓中」
    repository.drop_holding(portfolio, company)       # 持仓清掉，卡片留在原地
    _quote("300750", 296.41)
    view = assistant.pre_trade_check(company)
    if view["state"] != "holding":
        pytest.skip(f"前提没立住：卡片在 {view['state']}，不在持仓中")
    assert "闭环状态" in view["deviations"]
    assert "这一笔是加仓" not in view["text"]


def test_同一件事说两遍只算一处(monkeypatch):
    """计划价和合理区上沿都比基准值高 15%，是一件事——数成两处会把话说重。"""
    company = _planned_card()
    _quote("300750", 296.41)
    monkeypatch.setattr(repository, "base_per_share", lambda view: 260.77)
    view = assistant.pre_trade_check(company)
    valuation = [item for item in view["items"] if item["key"] == "valuation" and item["mark"] == "⚠"]
    assert len(valuation) == 1, "同一件事拆成几行，推到手机上就是一堵墙"
    assert "计划价 300 高 15%" in valuation[0]["text"] and "合理区上沿 300 高 15%" in valuation[0]["text"]
    assert view["deviations"] == ["估值"]
    assert view["verdict"].startswith("有 1 处")


def test_核验与提醒里没有替你做决定的话(monkeypatch):
    """只拿你自己的规则说话。这条守住 PRODUCT.md 4.2：不给买卖点、不给目标价。"""
    company = _planned_card()
    _quote("300750", 296.41)
    monkeypatch.setattr(repository, "base_per_share", lambda view: 260.77)
    texts = [assistant.pre_trade_check(company)["text"]]
    texts += [alert["message"] for alert in assistant.scan_price_alerts()]
    assert len(texts) == 2
    for text in texts:
        for word in ("建议买", "建议卖", "建议你", "目标价", "应该买", "应该卖", "止盈", "止损"):
            assert word not in text, f"助理替你做了决定：「{word}」"


# ───────────────────────────────────────────────────────── 到价提醒

def test_进去那一刻响一次_不会一直响():
    _planned_card()
    _quote("300750", 296.41)
    first = assistant.scan_price_alerts()
    assert len(first) == 1
    assert set(first[0]["levels"]) == {"plan", "fair"}
    assert "到了你写的计划买入价 300" in first[0]["message"]
    assert "合理区" in first[0]["message"]
    assert assistant.scan_price_alerts() == [], "同一个价第二轮又响了——每三分钟响一次的提醒没人受得了"


def test_在门槛边上来回蹭不会重复响_真出去了才重新上膛():
    _planned_card()
    for price, expect in [(299.0, 1),     # 进去：响
                          (301.5, 0),     # 回到门槛之上，但还在 1% 回差里：不算出去
                          (299.5, 0),     # 又回来：因为没出去过，不响
                          (304.0, 0),     # 真出去了（>303）：重新上膛，但不响
                          (298.0, 1)]:    # 再进去：响
        _quote("300750", price)
        alerts = assistant.scan_price_alerts()
        plan_alerts = [a for a in alerts if "plan" in a["levels"]]
        assert len(plan_alerts) == expect, f"{price} 时计划价提醒响了 {len(plan_alerts)} 次"


def test_改了计划价_就是新的一档():
    company = _planned_card()
    _quote("300750", 296.0)
    assert len(assistant.scan_price_alerts()) == 1
    repository.save_decision_card(company, {"order_plan": {"price": 297, "fraction": "1/3"},
                                            "bands": BANDS, "position_plan": PLAN})
    again = assistant.scan_price_alerts()
    assert len(again) == 1 and again[0]["levels"] == ["plan"], \
        "计划价从 300 改到 297、现价 296 又到了——这是一次新的「到了」，要响"


def test_深跌一步跨过几档_只发一条():
    _planned_card()
    _quote("300750", 265.0)
    alerts = assistant.scan_price_alerts()
    assert len(alerts) == 1
    assert set(alerts[0]["levels"]) == {"plan", "fair", "ideal", "extreme"}
    assert "极端机会区" in alerts[0]["message"], "跨过几档时说最深的那一档"


def test_只进了观察区不响():
    """观察区的意思是「进了视野，但赔率一般，通常不动手」。
    为一个通常不动手的区间打扰你，正是这个系统原来让人烦的那种事。"""
    _planned_card()
    _quote("300750", 305.0)          # ≤310 观察区，但高于计划价 300 与合理区 300
    assert assistant.scan_price_alerts() == []


def test_搁置的票不响():
    company = _planned_card()
    repository.move_decision_state(company, "shelved", "看不懂储能那条线，先放一放")
    _quote("300750", 250.0)
    assert assistant.scan_price_alerts() == []


# ───────────────────────────────────────────────────────── 送出去

def _fake_nanobot(tmp_path, *, exit_code: int = 0) -> tuple[str, str]:
    """一个假的 nanobot：把收到的参数和正文写进文件。"""
    out = tmp_path / "delivered.txt"
    script = tmp_path / "nanobot"
    script.write_text(
        "#!/bin/sh\n"
        f"echo \"$@\" > '{tmp_path}/args.txt'\n"
        f"cat > '{out}'\n"
        f"echo 'boom' >&2\n"
        f"exit {exit_code}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), str(out)


def test_没配飞书时_提醒照样记下_标成没发():
    _planned_card()
    _quote("300750", 296.41)
    result = assistant.watch_once(send=True, fetch=False)
    assert len(result["alerts"]) == 1
    row = _alerts()[0]
    assert row["delivery"] == "skipped" and "STOCK_ASSISTANT_TRIGGER" in row["delivery_error"], \
        "没配的时候提醒只躺在库里——得说得出来，不然像是「没事」"


def test_送出去了_正文原样交给_nanobot_trigger(tmp_path, monkeypatch):
    binary, out = _fake_nanobot(tmp_path)
    monkeypatch.setenv("STOCK_ASSISTANT_NANOBOT", binary)
    monkeypatch.setenv("STOCK_ASSISTANT_TRIGGER", "trg_TEST1234")
    _planned_card()
    _quote("300750", 296.41)
    result = assistant.watch_once(send=True, fetch=False)
    assert result["alerts"][0]["delivery"] == "queued"
    assert (tmp_path / "args.txt").read_text().strip() == "trigger trg_TEST1234"
    assert "到了你写的计划买入价 300" in open(out, encoding="utf-8").read()
    assert not _alerts()[0]["delivered_at"], "入队不能当成飞书已经送达"


def test_送不出去要记成失败_不能当成没事(tmp_path, monkeypatch):
    binary, _ = _fake_nanobot(tmp_path, exit_code=3)
    monkeypatch.setenv("STOCK_ASSISTANT_NANOBOT", binary)
    monkeypatch.setenv("STOCK_ASSISTANT_TRIGGER", "trg_TEST1234")
    _planned_card()
    _quote("300750", 296.41)
    result = assistant.watch_once(send=True, fetch=False)
    row = _alerts()[0]
    assert row["delivery"] == "failed" and "boom" in row["delivery_error"]
    assert result["status"] == "partial" and "没送出去" in result["detail"]
    runs = assistant.status()["runs"]
    assert runs and runs[0]["status"] == "partial", "这一轮出过事，盯盘记录上要看得见"


def test_每一轮都留记录_没事也留():
    """安静必须是「看过了，没事」——没有这条记录，你分不清它是没事还是早停了。"""
    _company("600519", "贵州茅台", group="观察池")
    result = assistant.watch_once(send=True, fetch=False)
    assert result["alerts"] == [] and result["watched"] == 1
    runs = assistant.status()["runs"]
    assert len(runs) == 1 and runs[0]["status"] == "ok" and "盯了 1 只" in runs[0]["detail"]


def test_旧行情不触发今天的提醒():
    _planned_card()
    _bar("300750", TODAY - timedelta(days=1), 290)
    assert assistant.scan_price_alerts() == []
    _quote("300750", 290)
    assert len(assistant.scan_price_alerts()) == 1


def test_别人的数据域只记不发(tmp_path, monkeypatch):
    binary, out = _fake_nanobot(tmp_path)
    monkeypatch.setenv("STOCK_ASSISTANT_NANOBOT", binary)
    monkeypatch.setenv("STOCK_ASSISTANT_TRIGGER", "trg_TEST1234")
    token = access.set_scope("user-9")
    try:
        _planned_card()
        _quote("300750", 296.41)
        result = assistant.watch_once(send=True, fetch=False)
    finally:
        access.reset_scope(token)
    assert result["alerts"][0]["delivery"] == "skipped"
    assert not os.path.exists(out), "别人的计划价进了站主的飞书"


# ───────────────────────────────────────────────────────── 什么时候盯

@pytest.mark.parametrize("stamp,expected", [
    ("2026-09-24 09:20", False), ("2026-09-24 09:30", True), ("2026-09-24 11:40", False),
    ("2026-09-24 13:10", True), ("2026-09-24 15:10", False), ("2026-09-26 10:00", False),
])
def test_只在交易时段盯(stamp, expected):
    from datetime import datetime

    assert assistant.is_trading_time(datetime.strptime(stamp, "%Y-%m-%d %H:%M")) is expected


# ───────────────────────────────────────────────────────── 接口：别人碰不到

from test_idor import client, owned  # noqa: E402,F401  （复用越权测试的夹具）


def test_别人看不到你的交易前核验(client, owned):  # noqa: F811
    """核验里有你的计划价、仓位上限和当时的理由——漏出去等于漏出交易计划。"""
    client.as_user("user-9")
    assert client.get(f"/api/v1/assistant/check/{owned['company']}").status_code == 404
    names = [row["name"] for row in client.get("/api/v1/assistant/my-stocks").json()]
    assert "站主的票" not in names


def test_只有站主能让助理往飞书发(client, owned):  # noqa: F811
    client.as_user("user-9")
    assert client.post("/api/v1/assistant/watch?send=true&fetch=false").status_code == 403
    # 只看不发谁都可以点：看的是他自己的票，不往外发任何东西。
    assert client.post("/api/v1/assistant/watch?fetch=false").status_code == 200


def test_点着试的时候默认不发(client, owned, tmp_path, monkeypatch):  # noqa: F811
    binary, out = _fake_nanobot(tmp_path)
    monkeypatch.setenv("STOCK_ASSISTANT_NANOBOT", binary)
    monkeypatch.setenv("STOCK_ASSISTANT_TRIGGER", "trg_TEST1234")
    client.as_user(access.OWNER_SCOPE)
    _planned_card()                   # 一只真会响的票——不然「没发」只是因为本来就没话可说
    _quote("300750", 296.41)
    response = client.post("/api/v1/assistant/watch?fetch=false")
    assert response.status_code == 200
    assert len(response.json()["alerts"]) == 1, "前提没立住：这一轮应该有一条提醒"
    assert not os.path.exists(out), "在页面上点一下「盯一轮」就真往飞书推了"
