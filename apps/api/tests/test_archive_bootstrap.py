"""建档之后要补齐的东西，以及"注定没产出就别花钱"。

2026-08-12 使用者报的两件事，查下来都不是"确实没有数据"：

**一、「从公告里找承诺」从来没成功过。** 线上 venv 缺 pypdf，24 份公告正文全部
记成「取不到」（note 是 `解析失败：ModuleNotFoundError`），模型每次只拿到标题。
只喂标题抽不出承诺是这个功能的前提，不是运气——所以前提不成立就该当场停下，
而不是照样调一次模型、照样扣分、然后告诉人"没找到承诺"。

**二、新建的档案打开来几乎每一页都是空的。** 建档只同步了当天行情和前复权日线；
简况、公告、历史估值、财务全要自己一页页去点同步。使用者原话：
「按理说，新建公司，这几个数据都应该默认同步才对」。
"""

import pytest

from stock_decision import repository
from stock_decision.database import connection, now_iso


def _company(symbol: str = "600519", name: str = "贵州茅台") -> int:
    from stock_decision.schemas import CompanyInput

    return repository.create_company(CompanyInput(symbol=symbol, name=name, industry="白酒"))["id"]


def _event(company_id: int, title: str, url: str) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO company_calendar_events
                   (company_id, category, event_date, title, detail, url, source, relevance, refreshed_at)
               VALUES (?, '公告', '2026-08-01', ?, '', ?, '测试', '高', ?)""",
            (company_id, title, url, now_iso()))


def test_一份正文都没取到就不调模型(monkeypatch):
    """**这一条是这次的核心。** 前提不成立就停下，一分不花。"""
    company_id = _company()
    _event(company_id, "关于回购股份的公告", "http://example.com/a.pdf")

    monkeypatch.setattr(repository, "announcement_bodies", lambda events, budget=None: {
        "bodies": {}, "read": 0, "failed": 1, "pending": 0,
        "reasons": ["解析失败：ModuleNotFoundError"],
    })

    def 不该被调到(*args, **kwargs):
        raise AssertionError("一份正文都没有，不该去调模型——那一次调用不可能有产出")

    from stock_decision import promises as pr
    monkeypatch.setattr(pr, "extract", 不该被调到)

    result = repository.extract_company_promises(company_id)

    assert result["found"] == []
    assert result["blocked"] is True
    # 报出真正卡住的那一步，不是笼统的「没找到承诺」。
    assert "ModuleNotFoundError" in result["note"]
    assert "没有花积分" in result["note"]


def test_取到了正文就照常抽(monkeypatch):
    """别把闸门关过头：有正文时必须还是会去抽。"""
    company_id = _company("000651", "格力电器")
    _event(company_id, "关于回购股份的公告", "http://example.com/b.pdf")

    monkeypatch.setattr(repository, "announcement_bodies", lambda events, budget=None: {
        "bodies": {int(e["id"]): "公司承诺 2026 年度分红比例不低于 50%。" for e in events},
        "read": len(events), "failed": 0, "pending": 0, "reasons": [],
    })
    called: list[int] = []

    def fake_extract(events, timeout=120, failures=None):
        called.append(len(events))
        return [{"statement": "公司承诺 2026 年度分红比例不低于 50%。", "subject": "分红",
                 "category": "分红", "promised_on": "2026-08-01", "due_date": "2026-12-31"}]

    from stock_decision import promises as pr
    monkeypatch.setattr(pr, "extract", fake_extract)

    result = repository.extract_company_promises(company_id)

    assert called == [1], "有正文却没去抽"
    assert len(result["found"]) == 1
    assert not result.get("blocked")


def test_没有归档公告时也不调模型(monkeypatch):
    """这条路本来就有，钉住它别被上面那段改坏。"""
    company_id = _company("000858", "五粮液")

    from stock_decision import promises as pr
    monkeypatch.setattr(pr, "extract", lambda *a, **k: pytest.fail("没有公告还去调模型"))

    result = repository.extract_company_promises(company_id)
    assert result["found"] == []
    assert "还没有归档的实质性公告" in result["note"]


def test_建档之后补齐公开数据的三样都会跑(monkeypatch):
    company_id = _company("601138", "工业富联")
    ran: list[str] = []
    for name in ("refresh_company_profile", "refresh_company_valuation", "refresh_company_financials"):
        monkeypatch.setattr(repository, name, lambda cid, _n=name: ran.append(_n))

    result = repository.fill_new_archive(company_id)

    assert ran == ["refresh_company_profile", "refresh_company_valuation", "refresh_company_financials"]
    assert result["failed"] == []
    assert "公司简况与公告" in result["note"]


def test_建档接口会把补齐任务派出去(monkeypatch):
    """光有 fill_new_archive 不够——**没人调它就等于没做**。钉住这条线。"""
    from fastapi.testclient import TestClient

    from stock_decision import main

    fired: list[tuple[str, int]] = []

    async def fake_submit(kind, target_id, work, label=""):
        fired.append((kind, target_id))
        return {"id": 1, "kind": kind, "target_id": target_id, "status": "排队中",
                "label": label, "progress": 0, "total": 0, "note": "", "error": "",
                "created_at": now_iso(), "updated_at": now_iso(), "started_at": None,
                "finished_at": None, "credits": 0, "tokens": 0, "metered": False, "result": None}

    monkeypatch.setattr(main, "submit", fake_submit)

    response = TestClient(main.app).post("/api/v1/companies", json={
        "name": "宁德时代", "symbol": "300750", "exchange": "深圳证券交易所",
        "industry": "电池", "watch_group": "观察池"})

    assert response.status_code == 201, response.text
    assert fired == [("archive_fill", response.json()["id"])]


def test_一样超时不会把其他几样一起拖掉(monkeypatch):
    """三个都是外部网络请求。**任何一个失败都不该让另外两个也补不上。**"""
    company_id = _company("000001", "平安银行")
    ran: list[str] = []
    monkeypatch.setattr(repository, "refresh_company_profile",
                        lambda cid: (_ for _ in ()).throw(TimeoutError("巨潮超时")))
    monkeypatch.setattr(repository, "refresh_company_valuation", lambda cid: ran.append("估值"))
    monkeypatch.setattr(repository, "refresh_company_financials", lambda cid: ran.append("财务"))

    result = repository.fill_new_archive(company_id)

    assert ran == ["估值", "财务"], "一样失败之后就不往下走了"
    assert result["done"] == ["历史估值", "定期报告财务"]
    assert "公司简况与公告（TimeoutError）" in result["failed"][0]
    # 补不上的要说出来，并且告诉人还能自己去点——否则那一页永远是空的而没人知道为什么。
    assert "手动同步" in result["note"]
