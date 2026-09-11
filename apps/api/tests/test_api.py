import asyncio
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from stock_decision.database import configure_database, initialize_database
from stock_decision.main import app
import stock_decision.repository as repository


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path) -> None:
    configure_database(tmp_path / "stock-decision-test.db")
    initialize_database()


async def request(method: str, path: str, json: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json)


def test_health_and_empty_dashboard() -> None:
    health = asyncio.run(request("GET", "/health"))
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    response = asyncio.run(request("GET", "/api/v1/dashboard"))
    assert response.status_code == 200
    body = response.json()
    assert body["demo"] is False
    assert body["watchlist"] == []
    # 数据健康改为按同步任务汇总；空库时五个任务都还没成功过
    assert "同步任务" in body["data_health"]


def test_company_research_archive_flow() -> None:
    company_response = asyncio.run(
        request(
            "POST",
            "/api/v1/companies",
            {
                "symbol": "601999",
                "name": "测试公司",
                "industry": "先进制造",
                "description": "用于验证本地研究档案流程。",
                "watch_group": "研究池",
                "valuation_percentile": 36,
                "roe_trend": "待中报验证",
            },
        )
    )
    assert company_response.status_code == 201
    company_id = company_response.json()["id"]

    thesis_response = asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company_id}/theses",
            {
                "claim": "订单结构改善能够带来稳定的现金回收。",
                "counter_condition": "应收周转连续恶化。",
                "status": "watching",
                "next_review_trigger": "中报经营现金流",
            },
        )
    )
    assert thesis_response.status_code == 201
    thesis_id = thesis_response.json()["id"]

    evidence_response = asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company_id}/evidences",
            {
                "thesis_id": thesis_id,
                "source_name": "测试公告",
                "source_url": "https://example.com/announcement",
                "excerpt": "经营现金流改善，需要在正式报告中确认。",
                "polarity": "support",
                "verification": "已核验",
            },
        )
    )
    assert evidence_response.status_code == 201

    event_response = asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company_id}/events",
            {
                "thesis_id": thesis_id,
                "category": "公司公告",
                "title": "发布中报预告",
                "importance": "high",
                "verification": "待核验",
            },
        )
    )
    assert event_response.status_code == 201

    detail_response = asyncio.run(request("GET", f"/api/v1/companies/{company_id}"))
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["name"] == "测试公司"
    assert detail["theses"][0]["evidence_count"] == 1
    assert detail["events"][0]["title"] == "发布中报预告"


def test_market_refresh_persists_a_stock_sdk_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    company_response = asyncio.run(
        request(
            "POST",
            "/api/v1/companies",
            {"symbol": "600519", "name": "待同步名称", "industry": "待补充"},
        )
    )
    assert company_response.status_code == 201

    monkeypatch.setattr(
        repository,
        "fetch_cn_quotes",
        lambda _: [
            {
                "code": "600519",
                "name": "贵州茅台",
                "price": 1351.0,
                "prevClose": 1350.6,
                "changePercent": 0.03,
                "pe": 20.42,
                "pb": 7.25,
                "high52w": 1539.98,
                "low52w": 1151.01,
                "totalMarketCap": 16888.6,
                "timestamp": 1785729949000,
                "source": "tencent",
            }
        ],
    )
    # **同步行情是后台任务**（2026-08-19 改的）：接口起完就返回，
    # 实测这活要跑 25 秒到几分钟，底座是全市场 5544 只 ——
    # 同步等的话前端只能靠放宽超时，而那条路走过，走不通。
    #
    # 所以这里要跟提交处共用一个事件循环，等任务真的跑完，
    # 否则下面查看板时快照还没落库。
    async def refresh_and_wait() -> dict:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = await client.post("/api/v1/market/refresh")
            assert started.status_code == 200
            assert started.json()["kind"] == "market_refresh"
            for _ in range(200):
                job = (await client.get("/api/v1/jobs/market_refresh/0")).json()
                if job and job["status"] not in {"排队中", "运行中"}:
                    return job
                await asyncio.sleep(.02)
        raise AssertionError("同步行情的后台任务没有在预期时间内结束")

    job = asyncio.run(refresh_and_wait())
    assert job["status"] == "已完成", job.get("error") or job.get("note")
    # 刷了几家要说出来 —— 「已更新 0 家」和「已更新 1 家」是两回事。
    assert "已更新 1/1 家" in (job.get("note") or ""), job.get("note")

    dashboard = asyncio.run(request("GET", "/api/v1/dashboard")).json()
    quote = dashboard["watchlist"][0]
    assert quote["name"] == "贵州茅台"
    assert quote["latest_price"] == 1351.0
    assert quote["market_source"] == "tencent"


def test_create_company_from_real_quote_and_record_provider_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository,
        "resolve_cn_quote",
        lambda _: {
            "code": "300750",
            "name": "宁德时代",
            "price": 393.27,
            "changePercent": -0.51,
            "pe": 21.41,
            "pb": 4.80,
            "timestamp": 1785729949000,
            "source": "tencent",
        },
    )
    monkeypatch.setattr(repository, "refresh_company_market_history", lambda _: 0)

    preview = asyncio.run(request("GET", "/api/v1/quotes/resolve?symbol=sz300750"))
    assert preview.status_code == 200
    assert preview.json()["name"] == "宁德时代"
    assert preview.json()["exchange"] == "深圳证券交易所"

    company = asyncio.run(
        request(
            "POST",
            "/api/v1/companies/from-quote",
            {"symbol": "300750", "watch_group": "重点观察", "description": "等待用户补充研究缘起。"},
        )
    )
    assert company.status_code == 201
    body = company.json()
    assert body["name"] == "宁德时代"
    assert body["industry"] == "待补充"
    assert body["latest_price"] == 393.27

    providers = asyncio.run(request("GET", "/api/v1/data-providers"))
    assert providers.status_code == 200
    provider = providers.json()[0]
    assert provider["provider_id"] == "stocksdk_quote"
    assert provider["last_status"] == "已同步"


def test_refresh_daily_history_builds_real_market_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    start = date(2025, 1, 1)
    bars = [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "close": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "changePercent": 1.0,
        }
        for index in range(30)
    ]
    monkeypatch.setattr(repository, "fetch_cn_daily_history", lambda _: bars)

    refreshed = asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/market-history/refresh"))
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshed_bars"] == 30

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    history = detail["market_history"]
    assert history["source"] == "StockSDK（东方财富日线）"
    assert history["price_5d_change"] == round((129 / 124 - 1) * 100, 2)
    assert len(history["bars"]) == 30


def test_refresh_financial_reports_persists_trend_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    monkeypatch.setattr(
        repository,
        "fetch_financial_periods",
        lambda _: [
            {
                "report_date": "2024-12-31",
                "revenue": 174_144_000_000,
                "net_profit": 86_228_000_000,
                "operating_cash_flow": 92_453_000_000,
                "total_assets": 300_000_000_000,
                "total_liabilities": 78_000_000_000,
                "equity": 222_000_000_000,
                "debt_ratio": 26.0,
                "roe_estimate": 42.5,
                "currency": "CNY",
                "audit_status": "是",
                "announcement_date": "2025-03-29",
            },
            {
                "report_date": "2025-03-31",
                "revenue": 50_000_000_000,
                "net_profit": 25_000_000_000,
                "operating_cash_flow": 24_000_000_000,
                "total_assets": 320_000_000_000,
                "total_liabilities": 80_000_000_000,
                "equity": 240_000_000_000,
                "debt_ratio": 25.0,
                "roe_estimate": None,
                "currency": "CNY",
                "audit_status": "待确认",
                "announcement_date": "2025-04-25",
            },
        ],
    )

    refreshed = asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/financials/refresh"))
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshed_periods"] == 2

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    financials = detail["financials"]
    assert financials["periods"][-1]["revenue"] == 50_000_000_000
    assert financials["periods"][-2]["roe_estimate"] == 42.5
    assert financials["periods"][-1]["debt_ratio"] == 25.0


def _company_with_quote(monkeypatch: pytest.MonkeyPatch, symbol: str = "600519", price: float = 120.0) -> dict:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": symbol, "name": "测试持仓公司", "industry": "待补充"})
    ).json()
    monkeypatch.setattr(
        repository,
        "fetch_cn_quotes",
        lambda _: [{"code": symbol, "name": "测试持仓公司", "price": price, "timestamp": 1785729949000, "source": "tencent"}],
    )
    assert asyncio.run(request("POST", "/api/v1/market/refresh")).status_code == 200
    return company


def test_trade_ledger_builds_position_from_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company_with_quote(monkeypatch, price=120.0)
    thesis = asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/theses",
            {"claim": "现金流改善可以支撑长期持有。", "status": "watching"},
        )
    ).json()

    portfolios = asyncio.run(request("GET", "/api/v1/portfolios")).json()
    assert len(portfolios) == 1 and portfolios[0]["name"] == "主组合"
    portfolio_id = portfolios[0]["id"]

    first = asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "thesis_id": thesis["id"],
                "side": "buy",
                "trade_date": "2026-01-05",
                "shares": 100,
                "price": 100,
                "fee": 5,
                "rationale": "首次建仓，验证经营现金流改善。",
                "expectation": "两个季度内现金流继续为正。",
                "review_due": "2026-04-30",
            },
        )
    )
    assert first.status_code == 201
    # 下单时的逻辑原文会留档，之后逻辑被改写也能回看当初依据。
    assert first.json()["thesis_claim_snapshot"] == "现金流改善可以支撑长期持有。"
    assert first.json()["amount"] == 10005.0

    asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "side": "buy",
                "trade_date": "2026-02-10",
                "shares": 100,
                "price": 110,
                "fee": 5,
                "rationale": "季报确认现金流改善后加仓。",
            },
        )
    )
    sell = asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "side": "sell",
                "trade_date": "2026-03-15",
                "shares": 50,
                "price": 130,
                "fee": 5,
                "rationale": "单一持仓权重过高，减持一部分。",
            },
        )
    )
    assert sell.status_code == 201

    detail = asyncio.run(request("GET", f"/api/v1/portfolios/{portfolio_id}")).json()
    position = detail["positions"][0]
    assert position["shares"] == 150
    # 移动加权平均：(10005 + 11005) / 200 = 105.05
    assert position["average_cost"] == 105.05
    assert position["cost_value"] == round(105.05 * 150, 2)
    assert position["realized_pnl"] == round(50 * (130 - 105.05) - 5, 2)
    assert position["market_value"] == 150 * 120.0
    assert position["weight"] == 100.0
    assert position["next_review_due"] == "2026-04-30"
    assert detail["trade_count"] == 3
    assert detail["largest_weight"] == 100.0


def test_sell_beyond_holding_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company_with_quote(monkeypatch)
    portfolio_id = asyncio.run(request("GET", "/api/v1/portfolios")).json()[0]["id"]
    asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "side": "buy",
                "trade_date": "2026-01-05",
                "shares": 100,
                "price": 100,
                "rationale": "建仓理由记录在案。",
            },
        )
    )
    rejected = asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "side": "sell",
                "trade_date": "2026-02-05",
                "shares": 200,
                "price": 130,
                "rationale": "超额卖出应当被拒绝。",
            },
        )
    )
    assert rejected.status_code == 422
    assert "持仓" in rejected.json()["detail"]


def test_company_ledger_and_dashboard_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company_with_quote(monkeypatch, price=120.0)
    portfolio_id = asyncio.run(request("GET", "/api/v1/portfolios")).json()[0]["id"]
    asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "side": "buy",
                "trade_date": "2026-01-05",
                "shares": 200,
                "price": 100,
                "fee": 0,
                "rationale": "建仓理由记录在案。",
                "review_due": "2026-06-30",
            },
        )
    )

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    ledger = detail["ledger"]
    assert ledger["shares"] == 200
    assert ledger["average_cost"] == 100
    assert ledger["unrealized_pnl"] == 4000.0
    assert ledger["portfolio_names"] == ["主组合"]
    assert len(ledger["trades"]) == 1

    dashboard = asyncio.run(request("GET", "/api/v1/dashboard")).json()
    assert dashboard["exposure_basis"] == "持仓市值"
    assert dashboard["portfolio_exposure"][0]["weight"] == 100.0
    assert dashboard["holding_market_value"] == 24000.0


def test_company_profile_refresh_stores_facts_and_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    today = date.today()
    monkeypatch.setattr(
        repository,
        "fetch_company_profile",
        lambda _: {
            "source": "AKShare / 巨潮资讯",
            "missing_sections": ["限售解禁"],
            "full_name": "贵州茅台酒股份有限公司",
            "english_name": "Kweichow Moutai Co., Ltd.",
            "industry": "酒、饮料和精制茶制造业",
            "market": "上交所",
            "legal_representative": "陈华",
            "registered_capital": 1_250_081_601.0,
            "founded_date": "1999-11-20",
            "listed_date": "2001-08-27",
            "website": "www.moutaichina.com",
            "registered_address": "贵州省仁怀市茅台镇",
            "office_address": "贵州省仁怀市茅台镇",
            "main_business": "茅台酒及系列酒的生产与销售。",
            "product_type": "茅台酒、其他系列酒",
            "business_scope": "茅台酒系列产品的生产与销售。",
            "introduction": "公司于 1999 年设立。",
            "total_shares": 1_250_081_601.0,
            "circulating_shares": 1_250_081_601.0,
            "share_structure_date": "2026-05-28",
            "share_change_reason": "股份回购",
            "issue_price": 31.39,
            "raised_net": 2_202_179_475.0,
            "underwriter": "南方证券有限公司",
            "latest_dividend_period": "2025年报",
            "latest_dividend_plan": "10派280.2423元(含税)",
            "latest_dividend_progress": "实施方案",
            "latest_dividend_payout_ratio": "42.68%",
            "latest_dividend_record_date": "2026-06-25",
            "latest_dividend_ex_date": "2026-06-26",
            "events": [
                {
                    "category": "分红",
                    "event_date": (today + timedelta(days=20)).isoformat(),
                    "title": "10派280.2423元(含税)",
                    "detail": "2025年报 · 实施方案",
                    "url": None,
                    "source": "同花顺分红方案",
                },
                {
                    "category": "公告",
                    "event_date": (today - timedelta(days=5)).isoformat(),
                    "title": "贵州茅台重大事项公告",
                    "detail": "",
                    "url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600519",
                    "source": "巨潮资讯公告",
                },
            ],
        },
    )

    refreshed = asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/profile/refresh"))
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshed_events"] == 2

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    profile = detail["profile"]
    assert profile["full_name"] == "贵州茅台酒股份有限公司"
    assert profile["total_shares"] == 1_250_081_601.0
    assert profile["latest_dividend_plan"] == "10派280.2423元(含税)"
    # 缺失的板块要显式说明，不能用占位内容冒充已接入。
    assert profile["missing_sections"] == ["限售解禁"]
    assert profile["upcoming_events"][0]["category"] == "分红"
    assert profile["upcoming_events"][0]["upcoming"] is True
    assert profile["recent_events"][0]["title"] == "贵州茅台重大事项公告"
    assert profile["event_count"] == 2

    providers = asyncio.run(request("GET", "/api/v1/data-providers")).json()
    assert any(item["provider_id"] == "akshare_cninfo_profile" and item["last_status"] == "已同步" for item in providers)


def test_company_without_profile_stays_empty() -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    assert detail["profile"] is None


def test_thesis_edits_append_versions_without_losing_history() -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "601999", "name": "测试公司", "industry": "待补充"})
    ).json()
    thesis = asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/theses",
            {"claim": "渠道改善能带来稳定的现金回收。", "counter_condition": "应收周转连续恶化。", "status": "watching"},
        )
    ).json()
    assert thesis["revision_count"] == 1

    updated = asyncio.run(
        request(
            "PATCH",
            f"/api/v1/theses/{thesis['id']}",
            {"claim": "渠道改善带来的现金回收已被中报确认。", "status": "intact", "change_note": "中报数据确认后更新"},
        )
    ).json()
    assert updated["revision_count"] == 2

    # 只提交相同内容不会产生新版本，避免版本历史被无意义的重复填满。
    unchanged = asyncio.run(request("PATCH", f"/api/v1/theses/{thesis['id']}", {"status": "intact"})).json()
    assert unchanged["revision_count"] == 2

    revisions = asyncio.run(request("GET", f"/api/v1/theses/{thesis['id']}/revisions")).json()
    assert [item["version"] for item in revisions] == [2, 1]
    assert revisions[0]["change_note"] == "中报数据确认后更新"
    assert revisions[0]["changed_fields"] == "主张、状态"
    # 旧版本原文仍可回看
    assert revisions[1]["snapshot"]["claim"] == "渠道改善能带来稳定的现金回收。"
    assert revisions[1]["snapshot"]["status"] == "watching"


def test_trade_rationale_edit_keeps_the_original_version(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company_with_quote(monkeypatch)
    portfolio_id = asyncio.run(request("GET", "/api/v1/portfolios")).json()[0]["id"]
    trade = asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "side": "buy",
                "trade_date": "2026-01-05",
                "shares": 100,
                "price": 100,
                "rationale": "建仓时依据的事实。",
                "expectation": "两个季度内现金流为正。",
            },
        )
    ).json()
    assert trade["revision_count"] == 1

    updated = asyncio.run(
        request(
            "PATCH",
            f"/api/v1/trades/{trade['id']}",
            {"rationale": "补充：建仓时还参考了渠道回款数据。", "review_due": "2026-09-30", "change_note": "补记遗漏的依据"},
        )
    ).json()
    assert updated["revision_count"] == 2
    assert updated["review_due"] == "2026-09-30"

    revisions = asyncio.run(request("GET", f"/api/v1/trades/{trade['id']}/revisions")).json()
    assert revisions[-1]["snapshot"]["rationale"] == "建仓时依据的事实。"
    assert revisions[0]["changed_fields"] == "复核日期、交易理由"


def test_backup_and_restore_verifies_record_counts(needs_matching_pg_client) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "601999", "name": "测试公司", "industry": "待补充"})
    ).json()
    asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/theses",
            {"claim": "备份前写下的第一条逻辑。", "status": "watching"},
        )
    )

    created = asyncio.run(request("POST", "/api/v1/backups", {"note": "P0.5 验收"}))
    # **失败时要把原因带出来。** 这条在 CI 上红了一整天，日志里只有一句
    # 「assert 422 == 201」——而 422 是 BackupError 转的，真正的原因
    # （pg_dump 说了什么、缺哪个客户端）全在 detail 里，被这句断言吞掉了。
    # 本地又因为 pg_dump 大版本对不上而 skip，于是永远看不见。
    assert created.status_code == 201, f"备份没建成：{created.json()}"
    manifest = created.json()
    assert manifest["counts"]["theses"] == 1
    assert manifest["note"] == "P0.5 验收"

    # 备份之后再写入的内容不在备份里
    asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/theses",
            {"claim": "备份之后写下的第二条逻辑。", "status": "watching"},
        )
    )
    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    assert len(detail["theses"]) == 2

    restored = asyncio.run(request("POST", f"/api/v1/backups/{manifest['name']}/restore")).json()
    assert restored["verified"] is True
    assert restored["restored_counts"]["theses"] == 1
    assert restored["before_counts"]["theses"] == 2
    # 恢复前会自动给当前库留一份安全备份，误操作可以再退回去
    backups = asyncio.run(request("GET", "/api/v1/backups")).json()
    assert any(item["name"] == restored["safety_backup"] and item["counts"]["theses"] == 2 for item in backups)

    detail_after = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    assert [item["claim"] for item in detail_after["theses"]] == ["备份前写下的第一条逻辑。"]


def test_export_contains_authored_records_only() -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "601999", "name": "测试公司", "industry": "待补充"})
    ).json()
    asyncio.run(
        request("POST", f"/api/v1/companies/{company['id']}/theses", {"claim": "导出应包含这条逻辑。", "status": "watching"})
    )
    export = asyncio.run(request("GET", "/api/v1/export"))
    assert export.status_code == 200
    body = export.json()
    assert body["counts"]["companies"] == 1
    assert body["records"]["theses"][0]["claim"] == "导出应包含这条逻辑。"
    assert body["records"]["record_revisions"][0]["entity_type"] == "thesis"
    # 行情、财务等来源数据可以重新同步，不进入导出正文
    assert "price_bars" not in body["records"]
    assert "price_bars" in body["source_counts"]


def test_local_data_summary_reports_schema_and_counts() -> None:
    summary = asyncio.run(request("GET", "/api/v1/local-data")).json()
    assert summary["schema_version"] == summary["expected_schema_version"]
    assert summary["authored_counts"]["companies"] == 0
    assert summary["backup_count"] == 0


def test_valuation_percentiles_carry_sample_window_and_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    latest = date(2026, 8, 3)
    # 五年样本：PE 从 40 均匀降到 20，最新值落在最低处；PB 只给 10 个点，用来验证样本不足的说明。
    pe_points = [
        {
            "metric": "pe_ttm",
            "point_date": (latest - timedelta(days=index * 5)).isoformat(),
            "value": 20 + index * 0.05,
        }
        for index in range(365)
    ]
    pb_points = [
        {"metric": "pb", "point_date": (latest - timedelta(days=index * 5)).isoformat(), "value": 6 + index * 0.1}
        for index in range(10)
    ]
    monkeypatch.setattr(
        repository,
        "fetch_valuation_history",
        lambda _: {"source": "AKShare / 百度股市通", "period": "近五年", "missing_metrics": [], "points": pe_points + pb_points},
    )

    refreshed = asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/valuation/refresh"))
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshed_points"] == 375

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    valuation = detail["valuation"]
    pe = next(item for item in valuation["metrics"] if item["metric"] == "pe_ttm")
    assert pe["current"] == 20.0
    assert pe["current_date"] == latest.isoformat()

    three_year = next(window for window in pe["windows"] if window["window_years"] == 3)
    five_year = next(window for window in pe["windows"] if window["window_years"] == 5)
    # 当前值是样本最低点，分位应当贴近 0；样本区间与截止日必须给出。
    assert three_year["percentile"] is not None and three_year["percentile"] < 1
    assert three_year["sample_end"] == latest.isoformat()
    assert three_year["sample_size"] < five_year["sample_size"]
    assert three_year["minimum"] == 20.0
    assert five_year["median"] is not None

    pb = next(item for item in valuation["metrics"] if item["metric"] == "pb")
    pb_window = pb["windows"][0]
    assert pb_window["percentile"] is None
    assert "样本" in pb_window["unavailable_reason"]


def test_market_refresh_also_keeps_a_local_valuation_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}))
    monkeypatch.setattr(
        repository,
        "fetch_cn_quotes",
        lambda _: [{"code": "600519", "name": "贵州茅台", "price": 1351.0, "pe": 20.42, "pb": 7.25, "timestamp": 1785729949000, "source": "tencent"}],
    )
    assert asyncio.run(request("POST", "/api/v1/market/refresh")).status_code == 200

    detail = asyncio.run(request("GET", "/api/v1/companies/1")).json()
    # 只有本地快照、没有历史来源时，估值区仍然为空，不用一天的样本冒充历史分位。
    assert detail["valuation"] is None
    summary = asyncio.run(request("GET", "/api/v1/local-data")).json()
    assert summary["source_counts"]["valuation_points"] == 2


def _company_with_announcements(monkeypatch: pytest.MonkeyPatch) -> dict:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    monkeypatch.setattr(
        repository,
        "fetch_company_profile",
        lambda _: {
            "source": "AKShare / 巨潮资讯",
            "missing_sections": [],
            "full_name": "贵州茅台酒股份有限公司",
            "events": [
                {
                    "category": "公告",
                    "event_date": "2026-07-18",
                    "title": "贵州茅台重大事项公告",
                    "detail": "",
                    "url": "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=600519",
                    "source": "巨潮资讯公告",
                },
                {
                    "category": "分红",
                    "event_date": "2026-06-26",
                    "title": "10派280.2423元(含税)",
                    "detail": "2025年报 · 实施方案",
                    "url": None,
                    "source": "同花顺分红方案",
                },
            ],
        },
    )
    asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/profile/refresh"))
    return company


def test_announcement_inbox_archives_as_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company_with_announcements(monkeypatch)
    thesis = asyncio.run(
        request("POST", f"/api/v1/companies/{company['id']}/theses", {"claim": "定价权仍然成立。", "status": "watching"})
    ).json()

    inbox_page = asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()
    inbox = inbox_page["items"]
    assert len(inbox) == 2 and inbox_page["total"] == 2
    announcement = next(item for item in inbox if item["category"] == "公告")
    assert announcement["inbox_status"] == "待核验"
    assert announcement["company_name"] == "贵州茅台"

    archived = asyncio.run(
        request(
            "POST",
            f"/api/v1/inbox/{announcement['id']}/archive",
            {"target": "evidence", "thesis_id": thesis["id"], "polarity": "support", "note": "公告确认了产能投放节奏。"},
        )
    )
    assert archived.status_code == 200
    body = archived.json()
    assert body["created_type"] == "evidence"
    assert body["item"]["inbox_status"] == "已归档"

    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    evidence = detail["evidences"][0]
    assert evidence["excerpt"] == "公告确认了产能投放节奏。"
    assert evidence["thesis_id"] == thesis["id"]
    assert evidence["polarity"] == "support"
    # 公告原文链接与披露日期一起带进证据，日后可回到来源核对
    assert evidence["source_url"].startswith("http://www.cninfo.com.cn/")
    assert evidence["occurred_at"].startswith("2026-07-18")

    # 已归档的条目不会再出现在待核验列表里，也不能重复归档
    remaining = asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()
    assert [item["category"] for item in remaining["items"]] == ["分红"]
    assert remaining["total"] == 1
    again = asyncio.run(request("POST", f"/api/v1/inbox/{announcement['id']}/archive", {"target": "event"}))
    assert again.status_code == 422


def test_inbox_archive_as_event_and_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    _company_with_announcements(monkeypatch)
    inbox = asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()["items"]
    dividend = next(item for item in inbox if item["category"] == "分红")
    announcement = next(item for item in inbox if item["category"] == "公告")

    archived = asyncio.run(
        request("POST", f"/api/v1/inbox/{dividend['id']}/archive", {"target": "event", "importance": "high"})
    ).json()
    assert archived["created_type"] == "event"

    dashboard = asyncio.run(request("GET", "/api/v1/dashboard")).json()
    assert dashboard["events"][0]["title"] == "10派280.2423元(含税)"
    assert dashboard["inbox_pending"] == 1

    ignored = asyncio.run(request("POST", f"/api/v1/inbox/{announcement['id']}/ignore")).json()
    assert ignored["inbox_status"] == "已忽略"
    assert asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()["items"] == []
    ignored_page = asyncio.run(request("GET", "/api/v1/inbox?status=已忽略&days=0")).json()
    assert len(ignored_page["items"]) == 1
    # 默认只看最近 90 天，更早的公告不会一次性铺开
    assert asyncio.run(request("GET", "/api/v1/inbox")).json()["items"] == []

    # 误忽略可以退回收件箱，已归档的不行
    reopened = asyncio.run(request("POST", f"/api/v1/inbox/{announcement['id']}/reopen")).json()
    assert reopened["inbox_status"] == "待核验"
    assert asyncio.run(request("POST", f"/api/v1/inbox/{dividend['id']}/reopen")).status_code == 422


def test_sync_jobs_expose_schedule_and_health() -> None:
    jobs = asyncio.run(request("GET", "/api/v1/sync/jobs")).json()
    # sw_industries 排在 universe 之后：它是全市场那一档的数据，
    # 但**单独一个作业、一周一次**——它要发 131 次请求跑三分钟，
    # 挂在日更的底座后面会让底座的耗时变得不可预测（挂过一次，见 scheduler）。
    # counter_match 紧跟在 profile / inbox_tidy 之后：新公告刚落地，
    # 正是拿它去撞「什么情况算我错」的时刻。它要过模型，所以默认不跑，
    # 由用户在收件箱页面自己勾（见 scheduler._run_counter_match）。
    assert [job["job_id"] for job in jobs] == ["quotes", "price_history", "profile", "inbox_tidy",
                                               "counter_match", "valuation", "financials",
                                               "universe", "sw_industries", "sentiment", "trend"]
    quotes = jobs[0]
    assert quotes["enabled"] is True
    assert quotes["health"] == "从未成功"
    assert quotes["next_run_at"] is not None

    changed = asyncio.run(request("PATCH", "/api/v1/sync/jobs/quotes", {"interval_minutes": 120, "enabled": False})).json()
    assert changed["interval_minutes"] == 120
    assert changed["enabled"] is False
    # 停用后不再自动运行，但仍要能手动触发
    assert changed["health"] == "已停用"
    assert asyncio.run(request("PATCH", "/api/v1/sync/jobs/unknown", {"enabled": True})).status_code == 404


def test_manual_run_records_result_and_marks_source_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}))
    monkeypatch.setattr(
        repository,
        "fetch_cn_quotes",
        lambda _: [{"code": "600519", "name": "贵州茅台", "price": 1351.0, "pe": 20.42, "pb": 7.25, "timestamp": 1785729949000, "source": "tencent"}],
    )
    result = asyncio.run(request("POST", "/api/v1/sync/jobs/quotes/run")).json()
    assert result["status"] == "成功"
    assert result["items"] == 1

    jobs = asyncio.run(request("GET", "/api/v1/sync/jobs")).json()
    quotes = next(job for job in jobs if job["job_id"] == "quotes")
    assert quotes["health"] == "正常"
    assert quotes["last_success_at"] is not None

    runs = asyncio.run(request("GET", "/api/v1/sync/runs")).json()
    assert runs[0]["job_id"] == "quotes"
    assert runs[0]["trigger"] == "手动"
    assert runs[0]["status"] == "成功"


def test_failed_run_keeps_last_success_and_reports_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}))

    def broken(_: object) -> None:
        raise repository.MarketDataError("来源暂时不可用")

    monkeypatch.setattr(repository, "fetch_cn_quotes", broken)
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    result = asyncio.run(request("POST", "/api/v1/sync/jobs/quotes/run")).json()
    assert result["status"] == "失败"
    assert "来源暂时不可用" in result["error"]

    jobs = asyncio.run(request("GET", "/api/v1/sync/jobs")).json()
    quotes = next(job for job in jobs if job["job_id"] == "quotes")
    # 失败不清空上一次成功的时间，页面据此说明"仍在用上一次成功的数据"
    assert quotes["consecutive_failures"] == 1
    assert quotes["health"] in {"从未成功", "有失败"}
    assert "来源暂时不可用" in (quotes["last_error"] or "")

    # 失败不影响其它接口
    assert asyncio.run(request("GET", "/api/v1/dashboard")).status_code == 200


def test_per_company_failure_does_not_abort_the_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    for symbol in ("600519", "000333"):
        asyncio.run(request("POST", "/api/v1/companies", {"symbol": symbol, "name": f"公司{symbol}", "industry": "待补充"}))

    calls: list[int] = []

    def flaky(company_id: int) -> int:
        calls.append(company_id)
        if company_id == 1:
            raise repository.CompanyProfileError("巨潮暂时不可用")
        return 7

    monkeypatch.setattr(repository, "refresh_company_profile", flaky)
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    monkeypatch.setattr("stock_decision.scheduler.COMPANY_PAUSE_SECONDS", 0)

    result = asyncio.run(request("POST", "/api/v1/sync/jobs/profile/run")).json()
    assert result["status"] == "部分失败"
    assert result["items"] == 7
    assert result["failures"] == 1
    assert "1/2 家公司简况与公告成功" in result["detail"]
    assert calls == [1, 2]


def test_stuck_run_is_treated_as_unfinished(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta as _timedelta

    from stock_decision import scheduler
    from stock_decision.database import connection

    asyncio.run(request("GET", "/api/v1/sync/jobs"))
    stale_start = (datetime.now() - _timedelta(seconds=scheduler.JOB_TIMEOUT_SECONDS + 60)).replace(microsecond=0)
    with connection() as conn:
        # 真实场景：任务开始后再没结束，next_run_at 停在开始前的那个值上
        conn.execute(
            "UPDATE sync_schedules SET last_status = '运行中', last_started_at = ?, next_run_at = ? WHERE job_id = 'quotes'",
            (stale_start.isoformat(), stale_start.isoformat()),
        )

    jobs = asyncio.run(request("GET", "/api/v1/sync/jobs")).json()
    quotes = next(job for job in jobs if job["job_id"] == "quotes")
    # 上游卡死或进程被杀会留下"运行中"；页面要说明它没有正常结束，排期也要能重新捡起来
    assert quotes["health"] == "有失败"
    assert "没有正常结束" in quotes["health_message"]
    # **必须钉一个工作日进去。**
    #
    # quotes 是 weekdays_only 的作业，而 due_job_ids() 不传参数就用「今天」——
    # 于是这条断言只在周一到周五成立。它潜伏了很久，直到某天跑在周六才现形，
    # 而那天的失败看起来跟当天改的东西有关，其实毫无关系。
    #
    # 这个测试问的是"卡死的任务能不能被重新捡起来"，跟周末排班无关，
    # 所以时间该由测试自己定，不该借用系统时钟。
    weekday = stale_start + _timedelta(seconds=scheduler.JOB_TIMEOUT_SECONDS + 120)
    while weekday.weekday() >= 5:
        weekday += _timedelta(days=1)
    assert "quotes" in scheduler.due_job_ids(weekday)


def test_only_one_sync_job_runs_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision import scheduler

    import time as _time

    scheduler.ensure_schedules()
    scheduler._ACTIVE_RUN = ("profile", _time.monotonic())
    try:
        skipped = scheduler.run_job("quotes", "手动")
        assert skipped["status"] == "已跳过"
        assert "正在运行" in skipped["detail"]
        # 卡死的运行超过墙钟上限后要让位，否则整条队列会被一个挂起的请求堵死
        scheduler._ACTIVE_RUN = ("profile", _time.monotonic() - scheduler.JOB_TIMEOUT_SECONDS - 1)
        monkeypatch.setattr(repository, "fetch_cn_quotes", lambda _: [])
        assert scheduler.run_job("quotes", "手动")["status"] == "成功"
    finally:
        scheduler._ACTIVE_RUN = None


def test_result_write_failure_does_not_leave_a_job_stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision import scheduler

    scheduler.ensure_schedules()
    monkeypatch.setattr(repository, "fetch_cn_quotes", lambda _: [])

    attempts: list[int] = []
    original = scheduler.connection

    def flaky_connection():
        attempts.append(1)
        # 只让收尾写库的第一次失败，模拟同一时刻页面也在写库
        if len(attempts) == 3:
            raise sqlite3.OperationalError("database is locked")
        return original()

    monkeypatch.setattr(scheduler, "connection", flaky_connection)
    monkeypatch.setattr("stock_decision.scheduler.time.sleep", lambda _: None)
    result = scheduler.run_job("quotes", "手动")
    assert result["status"] == "成功"

    jobs = asyncio.run(request("GET", "/api/v1/sync/jobs")).json()
    quotes = next(job for job in jobs if job["job_id"] == "quotes")
    assert quotes["last_status"] != "运行中"
    assert scheduler._ACTIVE_RUN is None


def _thesis_for_review(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, dict]:
    company = _company_with_quote(monkeypatch, price=120.0)
    thesis = asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/theses",
            {
                "claim": "渠道改善能带来稳定的现金回收。",
                "counter_condition": "应收周转连续两个季度恶化。",
                "status": "watching",
                "next_review_trigger": "2026 年中报",
            },
        )
    ).json()
    return company, thesis


def test_review_queue_explains_why_each_thesis_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    company, thesis = _thesis_for_review(monkeypatch)
    # 刚建立、没有反证也没到期的逻辑不该进队列
    assert asyncio.run(request("GET", "/api/v1/reviews/queue")).json() == []

    asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/evidences",
            {
                "thesis_id": thesis["id"],
                "source_name": "2026 中报",
                "excerpt": "应收账款周转天数继续上升。",
                "polarity": "counter",
                "verification": "已核验",
            },
        )
    )
    queue = asyncio.run(request("GET", "/api/v1/reviews/queue")).json()
    assert len(queue) == 1
    item = queue[0]
    assert item["thesis_id"] == thesis["id"]
    assert item["new_counter_evidence"] == 1
    # **从没复核过的，措辞不能说"上次复核后新增"** —— 那是在说一件没发生过的事，
    # 而使用者会去找那次不存在的复核。要说的是「有 1 条反证，而它还没被复核过」。
    assert any("1 条反证" in reason for reason in item["reasons"])
    assert any("还没复核过" in reason for reason in item["reasons"]), item["reasons"]


def test_review_context_puts_the_original_judgement_beside_new_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    company, thesis = _thesis_for_review(monkeypatch)
    portfolio_id = asyncio.run(request("GET", "/api/v1/portfolios")).json()[0]["id"]
    asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "thesis_id": thesis["id"],
                "side": "buy",
                "trade_date": "2026-01-05",
                "shares": 100,
                "price": 100,
                "rationale": "按这条逻辑建仓。",
                "expectation": "两个季度内现金流转正。",
                "review_due": "2026-06-30",
            },
        )
    )
    asyncio.run(
        request("PATCH", f"/api/v1/theses/{thesis['id']}", {"claim": "渠道改善的现金回收已被中报确认。", "change_note": "中报后收窄"})
    )

    context = asyncio.run(request("GET", f"/api/v1/theses/{thesis['id']}/review-context")).json()
    # 当初的原文与现在的版本都要在
    assert [item["version"] for item in context["revisions"]] == [1, 2]
    assert context["revisions"][0]["snapshot"]["claim"] == "渠道改善能带来稳定的现金回收。"
    assert context["trades"][0]["rationale"] == "按这条逻辑建仓。"
    assert context["position"]["shares"] == 100
    assert context["position"]["unrealized_pnl"] == 2000.0
    assert context["price"]["latest"] == 120.0
    assert context["reviews"] == []


def test_review_conclusion_appends_a_version_and_feeds_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    company, thesis = _thesis_for_review(monkeypatch)
    asyncio.run(
        request(
            "POST",
            f"/api/v1/companies/{company['id']}/evidences",
            {"thesis_id": thesis["id"], "source_name": "2026 中报", "excerpt": "应收继续恶化。", "polarity": "counter"},
        )
    )

    submitted = asyncio.run(
        request(
            "POST",
            f"/api/v1/theses/{thesis['id']}/reviews",
            {
                "verdict": "challenged",
                "note": "应收周转连续两个季度恶化，已触发当初写下的反证条件。",
                "next_review_date": "2026-11-30",
                "next_review_trigger": "2026 年三季报",
            },
        )
    )
    assert submitted.status_code == 201
    context = submitted.json()
    assert context["thesis"]["status"] == "challenged"
    assert context["thesis"]["next_review_date"] == "2026-11-30"
    assert context["reviews"][0]["verdict"] == "challenged"
    assert context["reviews"][0]["counter_evidence"] == 1
    assert context["reviews"][0]["price_at_review"] == 120.0
    # 结论作为逻辑的新版本追加，旧判断仍可回看
    versions = [item["version"] for item in context["revisions"]]
    assert versions == [1, 2]
    assert "复核：受到挑战" in context["revisions"][-1]["change_note"]

    # 复核过后不再重复出现在队列里
    assert asyncio.run(request("GET", "/api/v1/reviews/queue")).json() == []

    attribution = asyncio.run(request("GET", "/api/v1/reviews/attribution")).json()
    assert attribution["total_reviews"] == 1
    quarter = attribution["quarters"][0]
    assert quarter["challenged"] == 1 and quarter["total"] == 1
    assert quarter["reviews"][0]["company_name"] == "测试持仓公司"
    assert quarter["reviews"][0]["verdict_label"] == "受到挑战"


def test_review_advances_linked_trade_due_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    company, thesis = _thesis_for_review(monkeypatch)
    portfolio_id = asyncio.run(request("GET", "/api/v1/portfolios")).json()[0]["id"]
    trade = asyncio.run(
        request(
            "POST",
            f"/api/v1/portfolios/{portfolio_id}/trades",
            {
                "company_id": company["id"],
                "thesis_id": thesis["id"],
                "side": "buy",
                "trade_date": "2026-01-05",
                "shares": 100,
                "price": 100,
                "rationale": "按这条逻辑建仓。",
                "review_due": (date.today() - timedelta(days=5)).isoformat(),
            },
        )
    ).json()
    queue = asyncio.run(request("GET", "/api/v1/reviews/queue")).json()
    assert any("关联交易" in reason for reason in queue[0]["reasons"])

    future = (date.today() + timedelta(days=120)).isoformat()
    asyncio.run(
        request(
            "POST",
            f"/api/v1/theses/{thesis['id']}/reviews",
            {"verdict": "supported", "note": "现金流验证了当初的判断。", "next_review_date": future},
        )
    )
    # 复核覆盖了到期的交易，交易的复核日期跟着推进并留下版本
    detail = asyncio.run(request("GET", f"/api/v1/portfolios/{portfolio_id}")).json()
    updated = next(item for item in detail["trades"] if item["id"] == trade["id"])
    assert updated["review_due"] == future
    assert updated["revision_count"] == 2
    revisions = asyncio.run(request("GET", f"/api/v1/trades/{trade['id']}/revisions")).json()
    assert "随逻辑复核推进" in revisions[0]["change_note"]
    assert asyncio.run(request("GET", "/api/v1/reviews/queue")).json() == []


def test_financial_metrics_state_their_basis_and_flag_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "测试公司", "industry": "待补充"})
    ).json()

    def period(report_date: str, revenue: float, cost: float, profit: float, ocf: float, **extra: float | None) -> dict:
        base = {
            "report_date": report_date,
            "revenue": revenue,
            "net_profit": profit,
            "operating_cash_flow": ocf,
            "operating_cost": cost,
            "rnd_expense": revenue * 0.01,
            "capex": revenue * 0.05,
            "receivables": revenue * 0.1,
            "inventory": cost * 0.5,
            "interest_bearing_debt": revenue * 0.2,
            "total_assets": revenue * 2,
            "total_liabilities": revenue * 0.6,
            "equity": revenue * 1.4,
            "debt_ratio": 30.0,
            "roe_estimate": None,
            "currency": "CNY",
            "audit_status": "是",
            "announcement_date": None,
        }
        base.update(extra)
        return base

    monkeypatch.setattr(
        repository,
        "fetch_financial_periods",
        lambda _: [
            period("2024-12-31", 1000.0, 400.0, 200.0, 220.0),
            period("2025-06-30", 600.0, 240.0, 120.0, 130.0),
            period("2025-12-31", 1200.0, 600.0, 240.0, 60.0, receivables=400.0),
            period("2026-06-30", 700.0, 280.0, 140.0, 150.0),
        ],
    )
    # 财报明细没有 ROE 时，允许引用同一只股票在全市场底座里的年报 ROE；
    # 来源和报告期必须一起返回，不能悄悄混口径。
    with repository.connection() as conn:
        conn.execute(
            """INSERT INTO market_universe (
                symbol, name, annual_roe, annual_report_date, fundamental_source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            ("600519", "测试公司", 14.2, "20251231", "测试全市场底座", "2026-08-10T10:00:00"),
        )
    asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/financials/refresh"))
    financials = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()["financials"]

    latest = financials["periods"][-1]
    assert financials["latest_report_date"] == "2026-06-30"
    assert financials["roe_reference_value"] == 14.2
    assert financials["roe_reference_report_date"] == "2025-12-31"
    assert financials["roe_reference_source"] == "测试全市场底座"
    assert latest["report_date"] == "2026-06-30"
    assert latest["gross_margin"] == 60.0
    assert latest["net_margin"] == 20.0
    assert latest["free_cash_flow"] == 150.0 - 35.0
    # 中报口径的 TTM：本期累计 + 上年年报 − 上年同期累计
    assert latest["revenue_ttm"] == 700.0 + 1200.0 - 600.0
    assert "2025 年报" in latest["ttm_basis"]
    # 周转天数按报告期天数折算，口径写在卡片里
    assert latest["receivable_days"] == round(70.0 / 700.0 * 181, 1)

    metrics = {item["key"]: item for item in financials["metrics"]}
    assert metrics["gross_margin"]["value"] == 60.0
    assert "营业成本" in metrics["gross_margin"]["basis"]
    assert metrics["gross_margin"]["previous_annual"] == 50.0
    assert metrics["inventory_days"]["unit"] == "天"

    titles = [item["title"] for item in financials["warnings"]]
    # 2025 年报：毛利率从 60% 掉到 50%，应收从 100 涨到 400 而营收只涨 20%
    assert "毛利率同比变动超过 5 个百分点" in titles
    assert "应收增速明显快于营收" in titles


def test_missing_source_fields_are_reported_not_zeroed(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "测试公司", "industry": "待补充"})
    ).json()
    monkeypatch.setattr(
        repository,
        "fetch_financial_periods",
        lambda _: [
            {
                "report_date": "2025-12-31",
                "revenue": 1000.0,
                "net_profit": 100.0,
                "operating_cash_flow": 20.0,
                "operating_cost": None,
                "capex": None,
                "receivables": None,
                "inventory": None,
                "interest_bearing_debt": None,
                "total_assets": 2000.0,
                "total_liabilities": 600.0,
                "equity": 1400.0,
                "debt_ratio": 30.0,
                "currency": "CNY",
                "audit_status": "是",
            }
        ],
    )
    asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/financials/refresh"))
    financials = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()["financials"]

    latest = financials["periods"][-1]
    assert latest["gross_margin"] is None and latest["free_cash_flow"] is None
    metrics = {item["key"]: item for item in financials["metrics"]}
    assert metrics["gross_margin"]["unavailable_reason"] == "来源未提供所需科目"
    gap = next(item for item in financials["warnings"] if item["level"] == "缺口")
    assert "营业成本" in gap["detail"] and "不是 0" in gap["detail"]
    # 现金含量仍可计算，因为净利润为正
    assert latest["cash_conversion"] == 20.0


def test_short_but_real_trade_reasons_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    company = _company_with_quote(monkeypatch)
    portfolio_id = asyncio.run(request("GET", "/api/v1/portfolios")).json()[0]["id"]

    def record(rationale: str) -> int:
        return asyncio.run(
            request(
                "POST",
                f"/api/v1/portfolios/{portfolio_id}/trades",
                {
                    "company_id": company["id"],
                    "side": "buy",
                    "trade_date": "2026-06-11",
                    "shares": 100,
                    "price": 52.69,
                    "fee": 5.05,
                    "rationale": rationale,
                    "expectation": "上涨 后期跌了一点",
                },
            )
        ).status_code

    # "补仓"两个字也是真实记录，不该被拒
    assert record("补仓") == 201
    # 但仍然不接受空白理由
    assert record(" ") == 422


def test_watchlist_import_validates_every_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}))
    quotes = {
        "000333": {"code": "000333", "name": "美的集团", "price": 85.9, "timestamp": 1785729949000, "source": "tencent"},
        "300750": {"code": "300750", "name": "宁德时代", "price": 393.27, "timestamp": 1785729949000, "source": "tencent"},
    }

    def resolve(symbol: str) -> dict:
        canonical = repository.normalize_cn_symbol(symbol)
        if canonical not in quotes:
            raise repository.MarketQuoteNotFoundError(f"未找到 {canonical} 的行情")
        return quotes[canonical]

    monkeypatch.setattr(repository, "resolve_cn_quote", resolve)
    monkeypatch.setattr(repository, "refresh_company_market_history", lambda _: 0)

    result = asyncio.run(
        request(
            "POST",
            "/api/v1/companies/import",
            {"symbols": ["000333", "300750", "600519", "999999", " "], "watch_group": "重点观察"},
        )
    ).json()
    assert result["created"] == 2 and result["skipped"] == 1 and result["failed"] == 1
    statuses = {item["symbol"]: item["status"] for item in result["results"]}
    assert statuses["000333"] == "已建档"
    assert statuses["600519"] == "已存在"
    assert statuses["999999"] == "失败"

    groups = asyncio.run(request("GET", "/api/v1/companies/groups")).json()
    assert {item["name"]: item["watched"] for item in groups}["重点观察"] == 2


def test_watchlist_export_and_archive_keep_research_records(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"})
    ).json()
    asyncio.run(
        request("POST", f"/api/v1/companies/{company['id']}/theses", {"claim": "这条逻辑必须在移出后仍然存在。"})
    )

    exported = asyncio.run(request("GET", "/api/v1/companies/export")).json()
    assert exported[0]["symbol"] == "600519" and exported[0]["is_watched"] is True

    # 移出研究池是软移除：档案与逻辑都还在，只是不再出现在关注列表
    asyncio.run(request("PATCH", f"/api/v1/companies/{company['id']}", {"is_watched": False, "watch_group": "已移出"}))
    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    assert detail["is_watched"] is False
    assert len(detail["theses"]) == 1

    dashboard = asyncio.run(request("GET", "/api/v1/dashboard")).json()
    assert dashboard["watchlist"] == []
    groups = asyncio.run(request("GET", "/api/v1/companies/groups")).json()
    assert {item["name"]: item["archived"] for item in groups}["已移出"] == 1


def test_industry_is_backfilled_from_profile_without_overwriting_user_input(monkeypatch: pytest.MonkeyPatch) -> None:
    auto = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"})
    ).json()
    manual = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "000333", "name": "美的集团", "industry": "家电"})
    ).json()
    monkeypatch.setattr(
        repository,
        "fetch_company_profile",
        lambda _: {"source": "AKShare / 巨潮资讯", "missing_sections": [], "industry": "酒、饮料和精制茶制造业", "events": []},
    )
    asyncio.run(request("POST", f"/api/v1/companies/{auto['id']}/profile/refresh"))
    asyncio.run(request("POST", f"/api/v1/companies/{manual['id']}/profile/refresh"))

    filled = asyncio.run(request("GET", f"/api/v1/companies/{auto['id']}")).json()
    assert filled["industry"] == "酒、饮料和精制茶制造业"
    assert filled["industry_source"] == "巨潮资讯（证监会分类）"
    # 用户自己写过的行业不会被来源覆盖
    kept = asyncio.run(request("GET", f"/api/v1/companies/{manual['id']}")).json()
    assert kept["industry"] == "家电"


def test_industry_comparison_states_coverage_and_missing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _company_with_quote(monkeypatch, symbol="000333", price=85.9)
    second = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "300750", "name": "宁德时代", "industry": "电气机械和器材制造业"})
    ).json()
    asyncio.run(request("PATCH", f"/api/v1/companies/{first['id']}", {"industry": "电气机械和器材制造业"}))

    monkeypatch.setattr(
        repository,
        "fetch_financial_periods",
        lambda _: [
            {
                "report_date": "2024-12-31", "revenue": 1000.0, "net_profit": 100.0, "operating_cash_flow": 120.0,
                "operating_cost": 600.0, "total_assets": 2000.0, "total_liabilities": 800.0, "equity": 1200.0,
                "debt_ratio": 40.0, "roe_estimate": 9.0, "currency": "CNY", "audit_status": "是",
            },
            {
                "report_date": "2025-12-31", "revenue": 1200.0, "net_profit": 150.0, "operating_cash_flow": 160.0,
                "operating_cost": 700.0, "total_assets": 2200.0, "total_liabilities": 900.0, "equity": 1300.0,
                "debt_ratio": 41.0, "roe_estimate": 12.0, "currency": "CNY", "audit_status": "是",
            },
        ],
    )
    asyncio.run(request("POST", f"/api/v1/companies/{first['id']}/financials/refresh"))

    # 行业基准来自全 A 底座，不应该随着用户建档了哪几家公司而改变。
    with repository.connection() as conn:
        conn.executemany(
            """INSERT INTO market_universe (
                symbol, name, industry, pe_ttm, pb, roe, annual_roe, annual_report_date, gross_margin,
                revenue, net_profit, revenue_growth, eps, ocf_per_share,
                fundamental_source, fundamental_as_of, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("000333", "美的集团", "电气机械和器材制造业", 12.0, 2.0, 12.0, 18.0, "20251231", 41.0, 1200.0, 150.0, 20.0, 3.0, 3.6, "测试底座", "2026-03-31", "2026-08-10T10:00:00"),
                ("300750", "宁德时代", "电气机械和器材制造业", 20.0, 4.0, 15.0, 15.0, "20251231", 28.0, 1800.0, 180.0, 15.0, 4.0, 3.2, "测试底座", "2026-03-31", "2026-08-10T10:00:00"),
                ("600690", "海尔智家", "电气机械和器材制造业", 10.0, 1.0, 9.0, 9.0, "20251231", 32.0, 900.0, 90.0, 8.0, 2.0, 2.2, "测试底座", "2026-03-31", "2026-08-10T10:00:00"),
            ],
        )

    industries = asyncio.run(request("GET", "/api/v1/industries")).json()
    assert {item["name"]: item["company_count"] for item in industries}["电气机械和器材制造业"] == 2

    comparison = asyncio.run(request("GET", "/api/v1/industries/comparison?industry=电气机械和器材制造业")).json()
    assert comparison["company_count"] == 2
    assert comparison["benchmark_company_count"] == 3
    assert "全 A" in comparison["coverage"]
    assert "申万二级" in comparison["industry_basis"]
    assert comparison["benchmark_source"] == "测试底座"
    assert comparison["benchmark_as_of"] == "2026-03-31"
    assert comparison["average"]["sample_count"] == 3
    assert comparison["average"]["roe_estimate"] == 14.0
    assert comparison["median"]["roe_estimate"] == 15.0
    assert comparison["average"]["pe_ttm"] == 14.0
    assert comparison["lower_quartile"]["pe_ttm"] == 11.0
    assert comparison["median"]["pe_ttm"] == 12.0
    assert comparison["upper_quartile"]["pe_ttm"] == 16.0
    assert comparison["lower_quartile"]["roe_estimate"] == 12.0
    assert comparison["upper_quartile"]["roe_estimate"] == 16.5
    assert comparison["average"]["coverage"]["roe_estimate"] == 3

    rows = {item["symbol"]: item for item in comparison["companies"]}
    synced = rows["000333"]
    assert synced["financials"]["gross_margin"] == round((1200 - 700) / 1200 * 100, 2)
    assert synced["financials"]["roe_estimate"] == 18.0
    assert synced["financials"]["roe_report_date"] == "2025-12-31"
    assert synced["financials"]["revenue_growth"] == 20.0
    # 没同步过的公司显示原因，而不是空着让人以为是 0
    assert rows["300750"]["financials"]["note"] == "未同步财务报告"
    assert rows["300750"]["valuation"]["pe_ttm"]["note"] == "未同步历史估值"
    assert second["id"] == rows["300750"]["id"]


def test_exported_watchlist_can_be_restored_into_a_new_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    quotes = {
        "600519": {"code": "600519", "name": "贵州茅台", "price": 1351.0, "timestamp": 1785729949000, "source": "tencent"},
        "000333": {"code": "000333", "name": "美的集团", "price": 85.9, "timestamp": 1785729949000, "source": "tencent"},
    }
    monkeypatch.setattr(repository, "resolve_cn_quote", lambda symbol: quotes[repository.normalize_cn_symbol(symbol)])
    monkeypatch.setattr(repository, "refresh_company_market_history", lambda _: 0)

    first = asyncio.run(
        request("POST", "/api/v1/companies/from-quote", {"symbol": "600519", "watch_group": "重点观察", "description": "先看渠道"})
    ).json()
    asyncio.run(request("POST", "/api/v1/companies/from-quote", {"symbol": "000333", "watch_group": "观察池"}))
    asyncio.run(request("PATCH", f"/api/v1/companies/{first['id']}", {"is_watched": False}))
    exported = asyncio.run(request("GET", "/api/v1/companies/export")).json()

    # 换一个空库，直接把导出的内容回灌。
    # 走 conftest 的助手而不是 configure_database：后者只对 SQLite 有效，
    # PG 模式下它只改了一个用不到的文件路径，「换到空库」这一步静静地没发生。
    from conftest import reset_to_empty_database

    reset_to_empty_database(Path(tempfile.mkdtemp()))
    assert asyncio.run(request("GET", "/api/v1/companies")).json() == []

    restored = asyncio.run(request("POST", "/api/v1/companies/import", {"rows": exported, "restore_existing": True})).json()
    assert restored["created"] == 2 and restored["failed"] == 0

    companies = {item["symbol"]: item for item in asyncio.run(request("GET", "/api/v1/companies")).json()}
    assert companies["600519"]["watch_group"] == "重点观察"
    assert companies["600519"]["description"] == "先看渠道"
    # 导出时已移出研究池的公司，回灌后仍然是移出状态
    assert companies["600519"]["is_watched"] is False
    assert companies["000333"]["is_watched"] is True


def test_restore_updates_existing_pool_fields_without_touching_research(monkeypatch: pytest.MonkeyPatch) -> None:
    company = asyncio.run(
        request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充", "watch_group": "观察池"})
    ).json()
    asyncio.run(request("POST", f"/api/v1/companies/{company['id']}/theses", {"claim": "回灌不能动到这条逻辑。"}))

    rows = [{"symbol": "600519", "watch_group": "重点观察", "description": "从备份恢复的研究缘起", "industry": "白酒", "is_watched": True}]
    skipped = asyncio.run(request("POST", "/api/v1/companies/import", {"rows": rows})).json()
    assert skipped["skipped"] == 1 and skipped["updated"] == 0

    restored = asyncio.run(request("POST", "/api/v1/companies/import", {"rows": rows, "restore_existing": True})).json()
    assert restored["updated"] == 1
    detail = asyncio.run(request("GET", f"/api/v1/companies/{company['id']}")).json()
    assert detail["watch_group"] == "重点观察"
    assert detail["description"] == "从备份恢复的研究缘起"
    assert detail["industry"] == "白酒"
    # 研究记录不受影响
    assert detail["theses"][0]["claim"] == "回灌不能动到这条逻辑。"


def test_universe_snapshot_records_coverage_and_completeness(monkeypatch: pytest.MonkeyPatch) -> None:
    spot_rows = [
        {"symbol": "600519", "name": "贵州茅台", "price": 1351.0, "change_percent": 0.6, "pe_ttm": 20.4,
         "pb": 6.2, "total_market_cap": 1.7e12, "float_market_cap": 1.7e12, "turnover_rate": 0.3},
        {"symbol": "688256", "name": "寒武纪", "price": 1028.0, "change_percent": -7.0, "pe_ttm": 250.0,
         "pb": 30.0, "total_market_cap": 4.3e11, "float_market_cap": 3.0e11, "turnover_rate": 5.0},
        {"symbol": "300750", "name": "宁德时代", "price": 394.4, "change_percent": -0.2, "pe_ttm": 21.5,
         "pb": 4.8, "total_market_cap": 1.7e12, "float_market_cap": 1.5e12, "turnover_rate": 0.8},
    ]
    fundamentals = [
        {"symbol": "600519", "name": "贵州茅台", "revenue": 1.7e11, "revenue_growth": 8.0, "net_profit": 8.6e10,
         "net_profit_growth": 9.0, "roe": 34.5, "gross_margin": 91.3, "eps": 68.0, "bps": 200.0,
         "ocf_per_share": 70.0, "industry": "酿酒行业", "announcement_date": "2026-04-17"},
        {"symbol": "300750", "name": "宁德时代", "revenue": 4.0e11, "revenue_growth": 17.0, "net_profit": 6.0e10,
         "net_profit_growth": 20.0, "roe": 24.7, "gross_margin": 23.9, "eps": 13.0, "bps": 60.0,
         "ocf_per_share": 20.0, "industry": "电池", "announcement_date": "2026-04-20"},
    ]
    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {"rows": spot_rows, "source": "东方财富全市场快照", "degraded": False, "missing_fields": []},
    )
    monkeypatch.setattr(
        repository, "fetch_market_fundamentals",
        lambda period: {"rows": fundamentals, "source": "东方财富业绩报表", "report_date": period},
    )
    monkeypatch.setattr(
        repository, "fetch_index_members",
        lambda: {"members": [{"index_code": "000300", "index_name": "沪深300", "symbol": "600519"},
                             {"index_code": "000300", "index_name": "沪深300", "symbol": "300750"}],
                 "source": "中证指数官网", "missing_indexes": []},
    )
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())

    result = asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run")).json()
    assert result["status"] == "成功"
    assert "全 A 3 只" in result["detail"]

    summary = asyncio.run(request("GET", "/api/v1/universe/summary")).json()
    assert summary["total"] == 3
    assert {item["name"]: item["count"] for item in summary["boards"]} == {"主板": 1, "科创板": 1, "创业板": 1}
    assert summary["indexes"][0]["count"] == 2
    coverage = {item["field"]: item for item in summary["completeness"]}
    assert coverage["pe_ttm"]["ratio"] == 100.0
    # 寒武纪没有业绩报表数据，完整度要如实反映而不是补 0
    assert coverage["roe"]["filled"] == 2
    assert round(coverage["roe"]["ratio"]) == 67

    rows = {item["symbol"]: item for item in asyncio.run(request("GET", "/api/v1/universe/sample?limit=5")).json()}
    assert rows["600519"]["board"] == "主板" and rows["600519"]["roe"] == 34.5
    assert rows["688256"]["roe"] is None
    assert rows["688256"]["fundamental_source"] is None


def test_universe_degraded_source_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {
            "rows": [{"symbol": "600519", "name": "贵州茅台", "price": 1351.0, "change_percent": 0.6,
                      "pe_ttm": None, "pb": None, "total_market_cap": None, "float_market_cap": None, "turnover_rate": None}],
            "source": "新浪全市场快照（降级）",
            "degraded": True,
            "missing_fields": ["市盈率", "市净率", "总市值", "流通市值", "换手率"],
        },
    )
    monkeypatch.setattr(
        repository, "fetch_market_fundamentals",
        lambda period: (_ for _ in ()).throw(repository.UniverseDataError("业绩报表来源不可达")),
    )
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": ["中证1000"]})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())

    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))
    summary = asyncio.run(request("GET", "/api/v1/universe/summary")).json()
    snapshot = summary["last_snapshot"]
    assert snapshot["status"] == "部分失败"
    assert snapshot["degraded"] is True
    # 降级与失败的原因都要落在记录里，页面才能说清楚缺什么
    assert "行情来源降级" in snapshot["note"]
    assert "业绩报表失败" in snapshot["note"]
    coverage = {item["field"]: item for item in summary["completeness"]}
    assert coverage["pe_ttm"]["filled"] == 0


def test_universe_degraded_success_is_visible_as_health_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """备用行情源仍能完成同步时，应显示为降级而不是失败。"""
    row = _universe_row("600519", "贵州茅台")
    spot = [{
        key: row.get(key)
        for key in (
            "symbol", "name", "price", "change_percent", "pe_ttm", "pb",
            "total_market_cap", "float_market_cap", "turnover_rate", "ytd_change", "change_60d",
        )
    }]
    fundamentals = [{
        key: row.get(key)
        for key in (
            "symbol", "name", "revenue", "revenue_growth", "net_profit", "net_profit_growth",
            "roe", "gross_margin", "eps", "bps", "ocf_per_share", "industry", "announcement_date",
        )
    }]
    monkeypatch.setattr(
        repository,
        "fetch_market_spot",
        lambda: {
            "rows": spot,
            "source": "新浪全市场快照（降级）",
            "degraded": True,
            "missing_fields": ["市盈率", "市净率", "总市值"],
        },
    )
    monkeypatch.setattr(
        repository,
        "fetch_market_fundamentals",
        lambda period: {"rows": fundamentals, "source": "东方财富业绩报表", "report_date": period},
    )
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr(repository, "fetch_market_dividends", lambda period: {"rows": [], "source": "东方财富分红数据"})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())

    result = asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run")).json()
    assert result["status"] == "降级"
    assert result["failures"] == 0

    jobs = asyncio.run(request("GET", "/api/v1/sync/jobs")).json()
    universe_job = next(item for item in jobs if item["job_id"] == "universe")
    assert universe_job["last_status"] == "降级"
    assert universe_job["health"] == "降级"
    assert universe_job["last_success_at"] is not None

    dashboard = asyncio.run(request("GET", "/api/v1/dashboard")).json()
    assert "降级" in dashboard["data_health"]


def _seed_universe(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> None:
    spot = [
        {k: row.get(k) for k in ("symbol", "name", "price", "change_percent", "pe_ttm", "pb", "total_market_cap", "float_market_cap", "turnover_rate", "ytd_change", "change_60d")}
        for row in rows
    ]
    fundamentals = [
        {k: row.get(k) for k in ("symbol", "name", "revenue", "revenue_growth", "net_profit", "net_profit_growth", "roe", "gross_margin", "eps", "bps", "ocf_per_share", "industry", "announcement_date")}
        for row in rows
    ]
    monkeypatch.setattr(repository, "fetch_market_spot", lambda: {"rows": spot, "source": "东方财富全市场快照", "degraded": False, "missing_fields": []})
    monkeypatch.setattr(repository, "fetch_market_fundamentals", lambda period: {"rows": fundamentals, "source": "东方财富业绩报表", "report_date": period})
    # **分红这一支也要喂。** 不喂的话 dividend_yield 全库为空，
    # 而「股息现金流型」这套策略正好依赖它 —— 以前这条测试能过，
    # 是因为覆盖度检查压根没量这一列（量不到的字段被 `if part in coverage` 跳过了）。
    # 量对之后，"没喂数据"就会如实表现成"这套策略跑不了"。
    dividends = [
        {k: row.get(k) for k in ("symbol", "name", "dividend_yield", "dividend_per_10")}
        for row in rows
    ]
    monkeypatch.setattr(repository, "fetch_market_dividends",
                        lambda period=None: {"rows": dividends, "source": "东方财富分红送配", "period": "2025年报"})
    # 趋势那四列同理：不喂的话全库为空，趋势三套策略会如实变成"跑不了"。
    # 计数类给 0（「今天不在榜上」是个事实），连续值给 None
    # （没上榜就没有"阶段涨幅"这回事，见 providers/akshare_trend.RESET_VALUES）。
    trend_rows = [{"symbol": row["symbol"], "rising_days": 3, "stage_gain": 12.0,
                   "stage_turnover": 8.0, "above_ma60": 1, "new_high_level": 2,
                   "volume_days": 2} for row in rows]
    monkeypatch.setattr(repository, "fetch_market_trend",
                        lambda: {"rows": trend_rows, "source": "东方财富技术选股",
                                 "synced": ["rising", "breakout", "new_high", "volume"],
                                 "expected": ["rising", "breakout", "new_high", "volume"],
                                 "notes": []})
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [{"index_code": "000300", "index_name": "沪深300", "symbol": rows[0]["symbol"]}], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))
    # 趋势那四列由**另一个作业**写（trend，不是 universe）——不跑它，
    # rising_days / above_ma60 / new_high_level / volume_days 全库为空。
    asyncio.run(request("POST", "/api/v1/sync/jobs/trend/run"))


def _universe_row(symbol: str, name: str, **overrides: float | str) -> dict:
    base = {
        "symbol": symbol, "name": name, "price": 50.0, "change_percent": 0.5,
        "pe_ttm": 12.0, "pb": 1.2, "total_market_cap": 5.0e10, "float_market_cap": 4.0e10, "turnover_rate": 0.5,
        "ytd_change": 5.0, "change_60d": 3.0,
        "revenue": 1.0e10, "revenue_growth": 15.0, "net_profit": 1.5e9, "net_profit_growth": 25.0,
        "roe": 18.0, "gross_margin": 35.0, "eps": 2.0, "bps": 12.0, "ocf_per_share": 2.4,
        # 年报口径单独一支：策略里的年度门槛只认这一支（见 strategies.py 顶部的说明）
        "annual_roe": 18.0, "annual_gross_margin": 35.0,
        "dividend_yield": 4.0, "dividend_per_10": 8.0,
        "industry": "测试行业", "announcement_date": "2026-04-20",
    }
    base.update(overrides)
    return base


def test_strategy_library_works_without_any_user_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "全能公司"),
        _universe_row("600002", "贵但优质", pe_ttm=60.0, pb=8.0),
        _universe_row("600003", "便宜但衰退", roe=4.0, gross_margin=12.0, net_profit_growth=-30.0, revenue_growth=-10.0, ocf_per_share=-0.5),
    ])

    strategies = {item["key"]: item for item in asyncio.run(request("GET", "/api/v1/screen/strategies")).json()}
    # 不设任何条件就有五套可用的价值策略。第五套（股息现金流型）曾因「底座里没有股息率」
    # 被关着，而那个结论是错的——分红送配走东财 datacenter，与被墙的 push2 行情不是一条路。
    #
    # **按口味数，不数总数。** 数总数的话，以后加一套策略这条就红，
    # 而它想守的从来不是"一共几套"，是"价值那五套开箱可用"。
    available = [item for item in strategies.values() if item["available"]]
    assert sum(1 for item in available if item["kind"] == "value") == 5
    assert sum(1 for item in available if item["kind"] == "trend") == 3
    # 每套都必须写明出处与已知偏差。**趋势那三套尤其不能省**：
    # 它们的偏差比价值那几套危险得多（榜单是事后的、拐点上反转最猛、
    # A 股的短期反转比动量更明显），不写清楚就等于在推荐追涨。
    for key in ("undervalued_defensive", "quality_steady", "improving_operations",
                "quality_growth", "dividend_cashflow",
                "trend_breakout", "trend_volume", "trend_new_high"):
        assert strategies[key]["provenance"]
        assert len(strategies[key]["biases"]) >= 2

    result = asyncio.run(request("POST", "/api/v1/screen/run?strategy=quality_steady&limit=10")).json()
    assert result["universe_total"] == 3
    symbols = [item["symbol"] for item in result["candidates"]]
    assert symbols == ["600001", "600002"]  # 便宜但衰退的那家不满足质量条件
    assert "研究起点" in result["boundary"]

    top = result["candidates"][0]
    # 每条判据都要给出实际值，方便逐条核对
    assert {check["label"] for check in top["checks"]} >= {"净资产收益率（年报）", "销售毛利率（年报）"}
    assert top["checks"][0]["actual"] == 18.0
    # 多策略交集：全能公司同时被其它逻辑不同的策略选中，排在最前
    assert "低估防御型" in top["also_matched"]
    assert top["in_indexes"] == ["沪深300"]


def test_strategy_is_unavailable_when_its_fields_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {"rows": [{"symbol": "600001", "name": "只有价格", "price": 10.0, "change_percent": 0.1,
                           "pe_ttm": None, "pb": None, "total_market_cap": None, "float_market_cap": None, "turnover_rate": None}],
                 "source": "新浪全市场快照（降级）", "degraded": True, "missing_fields": ["市盈率", "市净率", "总市值"]},
    )
    monkeypatch.setattr(repository, "fetch_market_fundamentals",
                        lambda period: {"rows": [{"symbol": "600001", "name": "只有价格", "roe": 20.0, "gross_margin": 40.0,
                                                  "revenue_growth": 12.0, "net_profit_growth": 30.0, "eps": None, "ocf_per_share": 1.2,
                                                  "revenue": 1e9, "net_profit": None, "bps": None, "industry": "测试", "announcement_date": None}],
                                        "source": "东方财富业绩报表", "report_date": period})
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))

    strategies = {item["key"]: item for item in asyncio.run(request("GET", "/api/v1/screen/strategies")).json()}
    # 行情降级导致估值字段缺失，依赖它们的策略必须停用并说清楚缺什么
    assert strategies["undervalued_defensive"]["available"] is False
    assert "市盈率 TTM" in strategies["undervalued_defensive"]["unavailable_reason"]
    assert strategies["improving_operations"]["available"] is True

    rejected = asyncio.run(request("POST", "/api/v1/screen/run?strategy=undervalued_defensive"))
    assert rejected.status_code == 422
    assert "完整度不足" in rejected.json()["detail"]


def test_strategy_can_be_forked_and_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "高 ROE", roe=26.0),
        _universe_row("600002", "中 ROE", roe=16.0),
    ])
    saved = asyncio.run(
        request(
            "POST",
            "/api/v1/screen/strategies",
            {
                "key": "my_quality",
                "name": "我的质量线",
                "summary": "把 ROE 门槛提高到 20%",
                "rules": [{"field": "roe", "op": "gte", "value": 20, "unit": "%"}],
                "sort_field": "roe",
                "sort_desc": True,
                "sort_label": "ROE 由高到低",
                "forked_from": "quality_steady",
            },
        )
    )
    assert saved.status_code == 201
    assert saved.json()["preset"] is False
    # fork 会带上原策略的已知偏差，避免复制后忘了它的盲区
    assert saved.json()["biases"]
    assert "质量稳健型" in saved.json()["provenance"]

    result = asyncio.run(request("POST", "/api/v1/screen/run?strategy=my_quality")).json()
    assert [item["symbol"] for item in result["candidates"]] == ["600001"]

    runs = asyncio.run(request("GET", "/api/v1/screen/runs")).json()
    assert runs[0]["strategy_key"] == "my_quality"
    assert runs[0]["universe_total"] == 2 and runs[0]["matched"] == 1


def test_condition_editor_can_try_before_saving(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "高 ROE", roe=26.0),
        _universe_row("600002", "中 ROE", roe=16.0),
        _universe_row("600003", "低 ROE", roe=9.0),
    ])

    fields = {item["field"]: item for item in asyncio.run(request("GET", "/api/v1/screen/fields")).json()}
    # 编辑器要知道每个字段的口径提示与底座完整度，避免设出跑不了的条件
    assert fields["roe"]["usable"] is True and fields["roe"]["unit"] == "%"
    assert "杠杆" in fields["roe"]["hint"]
    assert fields["cash_ratio"]["derived"] is True

    # 把 ROE 门槛从 15% 提到 20%，先试跑不保存
    preview = asyncio.run(
        request(
            "POST",
            "/api/v1/screen/run?limit=10",
            {
                "name": "质量稳健型（试）",
                "rules": [{"field": "roe", "op": "gte", "value": 20, "unit": "%"}],
                "sort_field": "roe",
                "sort_desc": True,
                "forked_from": "quality_steady",
            },
        )
    ).json()
    assert [item["symbol"] for item in preview["candidates"]] == ["600001"]
    assert preview["strategy"]["key"] == "ad_hoc"
    # 临时条件也要带上边界说明，且不写进运行记录
    assert preview["strategy"]["biases"]
    assert asyncio.run(request("GET", "/api/v1/screen/runs")).json() == []

    # 试跑满意后再保存，这时才落库
    asyncio.run(
        request(
            "POST",
            "/api/v1/screen/strategies",
            {"key": "roe20", "name": "ROE 20 线", "rules": [{"field": "roe", "op": "gte", "value": 20, "unit": "%"}],
             "sort_field": "roe", "sort_desc": True, "forked_from": "quality_steady"},
        )
    )
    saved = asyncio.run(request("POST", "/api/v1/screen/run?strategy=roe20")).json()
    assert saved["matched"] == 1
    assert len(asyncio.run(request("GET", "/api/v1/screen/runs")).json()) == 1


def test_ad_hoc_conditions_respect_field_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {"rows": [{"symbol": "600001", "name": "只有价格", "price": 10.0, "change_percent": 0.1,
                           "pe_ttm": None, "pb": None, "total_market_cap": None, "float_market_cap": None, "turnover_rate": None}],
                 "source": "新浪全市场快照（降级）", "degraded": True, "missing_fields": ["市盈率"]},
    )
    monkeypatch.setattr(repository, "fetch_market_fundamentals",
                        lambda period: {"rows": [{"symbol": "600001", "name": "只有价格", "roe": 22.0, "gross_margin": 40.0,
                                                  "revenue_growth": 12.0, "net_profit_growth": 30.0, "eps": None, "ocf_per_share": 1.2,
                                                  "revenue": 1e9, "net_profit": None, "bps": None, "industry": "测试", "announcement_date": None}],
                                        "source": "东方财富业绩报表", "report_date": period})
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))

    rejected = asyncio.run(
        request("POST", "/api/v1/screen/run", {"rules": [{"field": "pe_ttm", "op": "lte", "value": 20}], "sort_field": "pe_ttm", "sort_desc": False})
    )
    assert rejected.status_code == 422 and "完整度不足" in rejected.json()["detail"]

    ok = asyncio.run(
        request("POST", "/api/v1/screen/run", {"rules": [{"field": "roe", "op": "gte", "value": 20, "unit": "%"}], "sort_field": "roe"})
    )
    assert ok.status_code == 200 and ok.json()["matched"] == 1


def test_saved_strategy_can_be_deleted_but_presets_cannot(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [_universe_row("600001", "测试")])
    asyncio.run(
        request("POST", "/api/v1/screen/strategies",
                {"key": "tmp_line", "name": "临时线", "rules": [{"field": "roe", "op": "gte", "value": 5}], "sort_field": "roe"})
    )
    assert asyncio.run(request("DELETE", "/api/v1/screen/strategies/tmp_line")).status_code == 204
    assert all(item["key"] != "tmp_line" for item in asyncio.run(request("GET", "/api/v1/screen/strategies")).json())

    protected = asyncio.run(request("DELETE", "/api/v1/screen/strategies/quality_steady"))
    assert protected.status_code == 422 and "预置策略不能删除" in protected.json()["detail"]


def test_heatmap_aggregates_by_industry_and_drills_into_companies(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "白酒甲", industry="酿酒", roe=30.0, total_market_cap=1.0e12),
        _universe_row("600002", "白酒乙", industry="酿酒", roe=20.0, total_market_cap=2.0e11),
        _universe_row("600003", "白酒丙", industry="酿酒", roe=-40.0, total_market_cap=1.0e10),
        _universe_row("300001", "电池甲", industry="电池", roe=18.0, total_market_cap=8.0e11),
    ])

    view = asyncio.run(request("GET", "/api/v1/heatmap?scope=all&metric=roe")).json()
    assert view["level"] == "industry" and view["universe_total"] == 4
    tiles = {tile["name"]: tile for tile in view["tiles"]}
    # 面积是行业总市值，颜色用成员中位数——亏损那家不会把整个行业拉成负数
    assert tiles["酿酒"]["size"] == 1.0e12 + 2.0e11 + 1.0e10
    assert tiles["酿酒"]["metric_value"] == 20.0
    assert tiles["酿酒"]["count"] == 3
    assert "中位数" in view["aggregation"]
    assert "不排序推荐" in view["boundary"]

    drill = asyncio.run(request("GET", "/api/v1/heatmap?scope=industry:酿酒&metric=roe")).json()
    assert drill["level"] == "company"
    assert [tile["symbol"] for tile in drill["tiles"]] == ["600001", "600002", "600003"]
    assert drill["tiles"][0]["metric_value"] == 30.0

    index_view = asyncio.run(request("GET", "/api/v1/heatmap?scope=index:000300&metric=roe")).json()
    # 只有第一只被放进了沪深300
    assert index_view["universe_total"] == 1 and index_view["scope_label"] == "沪深300"

    rejected = asyncio.run(request("GET", "/api/v1/heatmap?metric=不存在的指标"))
    assert rejected.status_code == 422


def test_heatmap_reports_missing_metric_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "有估值", pe_ttm=12.0),
        # 每股收益缺失 → 推算也补不出来，这才是真正"缺估值"
        _universe_row("600002", "缺估值", pe_ttm=None, eps=None, net_profit=None),
    ])
    view = asyncio.run(request("GET", "/api/v1/heatmap?metric=pe_ttm")).json()
    # 覆盖说明要写清楚多少只有这个指标，缺的那只不参与着色
    assert view["universe_total"] == 2 and view["with_metric"] == 1
    assert "其中 1 只有「市盈率 TTM」数据" in view["coverage"]
    assert view["size_basis"] == "总市值"
    assert "不代表贵或便宜" in view["metric_note"]


def test_heatmap_falls_back_to_company_count_when_market_cap_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {"rows": [
            {"symbol": "600001", "name": "甲", "price": 10.0, "change_percent": 1.0, "pe_ttm": None, "pb": None,
             "total_market_cap": None, "float_market_cap": None, "turnover_rate": None},
            {"symbol": "600002", "name": "乙", "price": 20.0, "change_percent": -1.0, "pe_ttm": None, "pb": None,
             "total_market_cap": None, "float_market_cap": None, "turnover_rate": None},
        ], "source": "新浪全市场快照（降级）", "degraded": True, "missing_fields": ["总市值"]},
    )
    monkeypatch.setattr(repository, "fetch_market_fundamentals", lambda period: {"rows": [
        {"symbol": "600001", "name": "甲", "roe": 20.0, "industry": "测试行业", "gross_margin": 30.0, "revenue_growth": 5.0,
         "net_profit_growth": 5.0, "eps": None, "bps": None, "ocf_per_share": 1.0, "revenue": 1e9, "net_profit": None, "announcement_date": None},
        {"symbol": "600002", "name": "乙", "roe": 10.0, "industry": "测试行业", "gross_margin": 20.0, "revenue_growth": 3.0,
         "net_profit_growth": 3.0, "eps": None, "bps": None, "ocf_per_share": 0.6, "revenue": 5e8, "net_profit": None, "announcement_date": None},
    ], "source": "东方财富业绩报表", "report_date": period})
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))

    view = asyncio.run(request("GET", "/api/v1/heatmap?metric=roe")).json()
    # 市值整体缺失时，面积退回按公司家数，并且在覆盖说明里写清楚
    assert view["size_basis"].startswith("公司家数")
    assert "面积为公司家数" in view["coverage"]
    assert view["tiles"][0]["size"] == 2 and view["tiles"][0]["metric_value"] == 15.0


def test_universe_accumulates_valuation_history_and_withholds_percentile(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [_universe_row("600001", "甲", pe_ttm=12.0, pb=1.2, ytd_change=8.5)])

    summary = asyncio.run(request("GET", "/api/v1/universe/summary")).json()
    # 全市场没有现成的历史估值序列，只能从今天起自己累积
    assert summary["valuation_history_days"] == 1
    assert "累计满 250 个交易日后" in summary["valuation_history_note"]
    coverage = {item["field"]: item for item in summary["completeness"]}
    assert coverage["ytd_change"]["ratio"] == 100.0

    percentile = asyncio.run(request("GET", "/api/v1/universe/percentile?symbol=600001")).json()
    # 样本只有一天，绝不能给出一个看起来能用的分位
    assert percentile["current"] == 12.0
    assert percentile["percentile"] is None
    assert "少于 250 天" in percentile["unavailable_reason"]

    missing = asyncio.run(request("GET", "/api/v1/universe/percentile?symbol=999999")).json()
    assert missing["sample_size"] == 0 and "还没有" in missing["unavailable_reason"]

    view = asyncio.run(request("GET", "/api/v1/heatmap?metric=ytd_change")).json()
    assert view["metric_label"] == "年初至今涨跌" and view["metric_kind"] == "diverging"
    assert view["tiles"][0]["metric_value"] == 8.5


def test_candidate_list_becomes_a_research_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "候选甲", roe=26.0),
        _universe_row("600002", "候选乙", roe=22.0),
        _universe_row("600003", "落选丙", roe=5.0, gross_margin=10.0),
    ])
    task = asyncio.run(
        request("POST", "/api/v1/tasks", {"title": "2026Q2 质量线复筛", "strategy_key": "quality_steady", "due_date": "2026-09-30"})
    )
    assert task.status_code == 201
    body = task.json()
    assert body["total"] == 2 and body["pending"] == 2
    # 任务要把"哪套条件、哪份数据"一起留档，否则日后看不出当初为什么把它列进来
    assert body["strategy_name"] == "质量稳健型"
    assert "全市场 3 只中命中 2 家" in body["data_note"]
    assert body["rules"]
    first = body["items"][0]
    assert first["symbol"] == "600001"
    assert first["evidence"][0]["label"] == "净资产收益率（年报）"

    # 逐条推进：看完一家排除，另一家建档
    dropped = asyncio.run(request("PATCH", f"/api/v1/tasks/items/{body['items'][1]['id']}", {"status": "已排除", "note": "毛利率靠一次性因素"})).json()
    assert dropped["dropped"] == 1 and dropped["pending"] == 1
    invalid = asyncio.run(request("PATCH", f"/api/v1/tasks/items/{body['items'][0]['id']}", {"status": "随便写"}))
    assert invalid.status_code == 422

    closed = asyncio.run(
        request("PATCH", f"/api/v1/tasks/{body['id']}", {"status": "已完成", "conclusion": "两家看完，一家进研究池，一家排除。"})
    ).json()
    assert closed["status"] == "已完成" and closed["closed_at"] is not None
    assert asyncio.run(request("GET", "/api/v1/tasks")).json()[0]["conclusion"].startswith("两家看完")


def test_task_marks_already_archived_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [_universe_row("600519", "贵州茅台", roe=30.0)])
    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"}))
    task = asyncio.run(request("POST", "/api/v1/tasks", {"title": "已建档核对", "strategy_key": "quality_steady"})).json()
    # 已经在研究池里的公司直接标为已建档，不需要再走一遍
    assert task["items"][0]["status"] == "已建档"
    assert task["items"][0]["company_id"] is not None
    assert task["pending"] == 0


def test_classify_by_rules_separates_substance_from_procedure():
    from stock_decision.classification import classify_by_rules

    assert classify_by_rules("2025年年度权益分派实施公告")["relevance"] == "高"
    assert classify_by_rules("10派1.48元(含税)", "分红")["relevance"] == "高"
    assert classify_by_rules("限售股上市流通（第 53 批）", "解禁")["relevance"] == "高"
    # 走流程的文件不该和实质变化混在一起
    assert classify_by_rules("关于召开2026年第一次临时股东大会的通知")["relevance"] == "低"
    assert classify_by_rules("北京市金杜律师事务所关于公司股权激励计划的法律意见书")["relevance"] == "低"
    # 进展类带着具体数量与金额，是可归档的公司事实——归档不需要先判断影响有多大
    assert classify_by_rules("关于回购股份事项的进展公告")["relevance"] == "高"
    assert classify_by_rules("关于2023年限制性股票激励计划第一个归属期符合归属条件的公告")["relevance"] == "高"
    # "中"只留给标题模糊到看不出在讲什么的
    assert classify_by_rules("关于坚定支持资本市场发展与提升股东回报的公告")["relevance"] == "中"


def test_classify_inbox_without_model_only_uses_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    _company_with_announcements(monkeypatch)
    result = asyncio.run(request("POST", "/api/v1/inbox/classify?use_ai=false")).json()
    assert result["by_model"] == 0
    assert result["scanned"] > 0
    # 分红与解禁本身就是实质变化
    assert result["counts"].get("高", 0) >= 1

    listing = asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()
    assert all(item["relevance"] in ("高", "中") for item in listing["items"])
    assert all(item["relevance_source"] == "规则" for item in listing["items"])
    assert listing["ungraded"] == 0


def test_method_library_every_method_is_actionable_and_sourced() -> None:
    library = asyncio.run(request("GET", "/api/v1/methods")).json()
    methods = [method for category in library["categories"] for method in category["methods"]]
    assert len(methods) >= 12
    assert {category["label"] for category in library["categories"]} == {"找什么", "生意好不好", "价格贵不贵", "怎么少犯错"}
    # 新手能直接上手的要占多数——这个库是给不知道怎么写买入理由的人用的
    assert sum(1 for method in methods if method["beginner"]) > len(methods) / 2

    for summary in methods:
        detail = asyncio.run(request("GET", f"/api/v1/methods/{summary['key']}")).json()
        # 没有出处的方法没法回去查原文，也没法在失效时知道错在哪一步
        assert len(detail["origin"]) > 15
        assert detail["steps"]
        # 反证条件是这个库的核心：不能被证伪的买入理由等于没有理由
        assert detail["counter_template"]
        assert detail["trigger_template"]

    assert asyncio.run(request("GET", "/api/v1/methods/not_a_method")).status_code == 404


def test_archive_inbox_batch_keeps_source_and_leaves_polarity_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    _company_with_announcements(monkeypatch)
    asyncio.run(request("POST", "/api/v1/inbox/classify?use_ai=false"))
    before = asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()
    high = [item for item in before["items"] if item["relevance"] == "高"]
    assert high

    result = asyncio.run(request("POST", "/api/v1/inbox/archive-batch?relevance=高&days=0")).json()
    assert result["archived"] == len(high)
    assert result["failed"] == 0

    company = asyncio.run(request("GET", "/api/v1/companies/1")).json()
    archived = {evidence["excerpt"].split("｜")[0] for evidence in company["evidences"]}
    for item in high:
        assert item["title"] in archived
    # 方向性判断不代劳：批量归档一律留在中性
    assert all(evidence["polarity"] == "neutral" for evidence in company["evidences"])
    assert all(evidence["source_name"] for evidence in company["evidences"])

    after = asyncio.run(request("GET", "/api/v1/inbox?days=0")).json()
    assert not [item for item in after["items"] if item["relevance"] == "高"]
    assert asyncio.run(request("POST", "/api/v1/inbox/archive-batch?relevance=很高")).status_code == 400


def test_tidy_inbox_leaves_only_the_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    _company_with_announcements(monkeypatch)
    result = asyncio.run(request("POST", "/api/v1/inbox/tidy?use_ai=false")).json()
    assert result["classified"] > 0

    remaining = asyncio.run(request("GET", "/api/v1/inbox?days=0&relevance=中")).json()
    # 自动化只处理确定的两端；拿不准的那一档必须原样留给人
    assert all(item["relevance"] == "中" for item in remaining["items"])
    assert remaining["high"] == 0
    assert remaining["low"] == 0
    assert result["remaining"] == len(remaining["items"])

    company = asyncio.run(request("GET", "/api/v1/companies/1")).json()
    assert len(company["evidences"]) == result["archived"]
    assert all(evidence["polarity"] == "neutral" for evidence in company["evidences"])


def test_thesis_draft_prompt_only_uses_archived_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision.drafting import DRAFT_SYSTEM_PROMPT, build_prompt
    from stock_decision.repository import get_company

    _company_with_announcements(monkeypatch)
    company = get_company(1)
    assert company is not None
    prompt, trackable = build_prompt(company, "lynch_monologue")

    assert company["name"] in prompt
    assert "两分钟独白" in prompt or "三句话说完" in prompt
    # 提示词必须堵住三个口子：编数据、给目标价、写不可核对的反证条件
    assert "绝对不要凭记忆补充" in DRAFT_SYSTEM_PROMPT
    assert "不给目标价" in DRAFT_SYSTEM_PROMPT
    assert "反证条件必须能用列出的可跟踪字段核对" in DRAFT_SYSTEM_PROMPT
    assert "写反证条件时只能用这些可以持续跟踪的字段" in prompt
    for field in trackable:
        assert field in prompt



def test_universe_derives_valuation_when_snapshot_source_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    """快照源被挡时不该让四套策略全部瘫痪——市值、PB、PE 都能从财务底座推出来。"""

    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {"rows": [{"symbol": "600001", "name": "推算公司", "price": 100.0, "change_percent": 0.1,
                           "pe_ttm": None, "pb": None, "total_market_cap": None, "float_market_cap": None, "turnover_rate": None}],
                 "source": "新浪全市场快照（降级）", "degraded": True, "missing_fields": ["市盈率", "市净率", "总市值"]},
    )
    # 期报与年报用同一份数据：净利润 10 亿、每股收益 1 元 → 10 亿股 → 市值 1000 亿
    monkeypatch.setattr(repository, "fetch_market_fundamentals",
                        lambda period: {"rows": [{"symbol": "600001", "name": "推算公司", "roe": 20.0, "gross_margin": 40.0,
                                                  "revenue_growth": 12.0, "net_profit_growth": 30.0, "eps": 1.0, "ocf_per_share": 1.2,
                                                  "revenue": 1e10, "net_profit": 1e9, "bps": 20.0, "industry": "测试", "announcement_date": None}],
                                        "source": "东方财富业绩报表", "report_date": period})
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))

    from stock_decision.database import connection as _connection

    with _connection() as conn:
        row = conn.execute(
            "SELECT total_market_cap, pb, pe_ttm, valuation_basis FROM market_universe WHERE symbol = '600001'"
        ).fetchone()
    assert row["total_market_cap"] == pytest.approx(1e11)   # 100 元 × 10 亿股
    assert row["pb"] == pytest.approx(5.0)                  # 100 / 20
    assert row["pe_ttm"] == pytest.approx(100.0)            # 1000 亿 / 10 亿
    # 推算口径必须留痕，否则用户无法判断这个 PE 能不能和交易所口径比
    assert "推算" in row["valuation_basis"]

    strategies = asyncio.run(request("GET", "/api/v1/screen/strategies")).json()
    usable = [item["key"] for item in strategies if item["available"]]
    assert "undervalued_defensive" in usable
    assert "quality_steady" in usable
    assert "quality_growth" in usable


def test_news_matching_never_invents_a_company(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision.news import MATCH_SYSTEM_PROMPT, match_by_rules

    companies = [{"id": 1, "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}]
    assert match_by_rules("贵州茅台发布年度权益分派", companies)["company_id"] == 1
    assert match_by_rules("600519 大宗交易", companies)["company_id"] == 1
    # 行业新闻不该被硬塞给某一家公司
    assert match_by_rules("白酒行业库存持续走高", companies) is None
    assert "绝对不能选清单以外的公司" in MATCH_SYSTEM_PROMPT
    assert "拿不准就填 null" in MATCH_SYSTEM_PROMPT


def test_news_pipeline_keeps_second_hand_sources_out_of_the_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    client_company = {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}
    asyncio.run(request("POST", "/api/v1/companies", client_company))
    monkeypatch.setattr(
        repository, "fetch_feed",
        lambda feed, limit=40: [{
            "feed_key": feed["key"], "feed_name": feed["name"], "title": f"{client_company['name']}发布年度权益分派",
            "url": "https://example.com/a", "summary": "摘要", "published_at": "2026-07-01T09:00:00",
            "fingerprint": f"fp-{feed['key']}",
        }],
    )
    # 抓取改成后台任务之后，接口回的是任务而不是结果 —— 领域行为直接调
    # repository 验，接口那层单独验它确实起了个任务（见 test_news_refresh_is_a_job）。
    result = repository.refresh_news()
    assert result["fetched"] >= 1
    assert result["matched"] >= 1

    page = asyncio.run(request("GET", "/api/v1/news")).json()
    item = page["items"][0]
    assert item["company_id"] == 1
    assert item["match_source"] == "规则"
    # 抓进来还不是证据——必须确认过才进档案
    company = asyncio.run(request("GET", "/api/v1/companies/1")).json()
    assert company["evidences"] == []

    asyncio.run(request("POST", f"/api/v1/news/{item['id']}/confirm"))
    company = asyncio.run(request("GET", "/api/v1/companies/1")).json()
    assert len(company["evidences"]) == 1
    evidence = company["evidences"][0]
    assert "媒体转述" in evidence["source_name"]      # 二手来源要标出来
    assert evidence["verification"] == "待核验"
    assert evidence["polarity"] == "neutral"


def test_supply_chain_links_are_never_presented_as_confirmed_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision.chain_and_reports import CHAIN_SYSTEM_PROMPT

    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}))
    monkeypatch.setattr(
        repository, "map_supply_chain",
        lambda company, timeout=150: [
            {"relation": "上游供应", "counterpart": "包装材料厂", "segment": "包材", "detail": "提供瓶身与包装",
             "confidence": "待证实", "source": "模型 X 推断 · 核对位置：年报「采购情况」"},
        ],
    )
    # 后台任务，切页面不中断
    asyncio.run(_submit_and_wait("POST", "/api/v1/companies/1/supply-chain/refresh", "supply_chain", 1))
    view = asyncio.run(request("GET", "/api/v1/companies/1/supply-chain")).json()
    # 依据是模型知识而不是本地档案，所以一律待证实，且必须写明去哪核对
    assert view["links"][0]["confidence"] == "待证实"
    assert "核对位置" in view["links"][0]["source"]
    assert view["confirmed"] == 0
    # 这条守的是「模型推断永远不能被当成已核实的事实」，**不是守某一句话的措辞**。
    # 找票那边把「产业链关系」改名成「经营关系线索」时，边界文案跟着重写了，
    # 而原来的断言盯的是 "唯一依据不是本地档案" 这七个字——文案一动就红，
    # 可产品保证一点没变。所以改成盯两件事：
    #   ① 说清依据是什么（模型的世界知识，不是本地档案）
    #   ② 说清该怎么办（回到原始文件核对）
    # 少任何一条，这块内容就可能被当成事实读。
    assert "模型的世界知识" in view["boundary"], "边界必须说清依据来自模型，不是本地档案"
    assert "核对" in view["boundary"], "边界必须说清每条都要回原始文件核对"
    assert "不要给市场份额" in CHAIN_SYSTEM_PROMPT

    asyncio.run(request("POST", f"/api/v1/supply-chain/{view['links'][0]['id']}/confirm"))
    assert asyncio.run(request("GET", "/api/v1/companies/1/supply-chain")).json()["confirmed"] == 1


def test_report_refuses_to_write_without_archived_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision.chain_and_reports import REPORT_SYSTEM_PROMPT

    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "待补充"}))
    # 没有证据时不许编：任务会失败，并且失败原因要留在任务记录里
    finished = asyncio.run(_submit_and_wait("POST", "/api/v1/companies/1/reports", "report", 1))
    assert finished["status"] == "失败"
    assert "没有归档任何证据" in finished["error"]
    assert "只能使用用户消息里给出的编号资料" in REPORT_SYSTEM_PROMPT
    assert "不给目标价" in REPORT_SYSTEM_PROMPT


def test_screen_prompt_leads_with_the_business_and_rounds_numbers() -> None:
    from stock_decision.researching import RESEARCH_SYSTEM_PROMPT, build_screen_prompt

    prompt = build_screen_prompt(
        [{"symbol": "300475", "name": "香农芯创", "industry": "其他电子Ⅱ",
          "main_business": "电子元器件分销业务。", "revenue_growth": 200.596381199, "eps": 2.8612345}],
        "经营改善型", "净利润同比 ≥ 20%", "20260331 报告期",
    )
    assert "电子元器件分销业务" in prompt
    # 浮点尾数没有信息量，会被模型原样抄进结论
    assert "200.6" in prompt and "200.596381199" not in prompt
    assert "2.86" in prompt and "2.8612345" not in prompt
    # 只有指标没有生意的结论对不认识这家公司的人没用
    assert "先用一句话说清这家公司靠什么赚钱" in RESEARCH_SYSTEM_PROMPT
    assert "不要凭公司名猜" in RESEARCH_SYSTEM_PROMPT


def test_background_job_survives_and_records_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_decision.background import create_job, get_job, latest_job, recover_stale_jobs, update_job

    job_id = create_job("demo", 7, total=3, label="测试")
    assert get_job(job_id)["status"] == "排队中"
    update_job(job_id, status="运行中", progress=2)
    assert latest_job("demo", 7)["progress"] == 2

    # 服务重启后运行中的任务必须被标成中断，而不是永远显示运行中
    assert recover_stale_jobs() >= 1
    recovered = get_job(job_id)
    assert recovered["status"] == "已中断"
    assert "服务重启" in recovered["error"]


def test_auto_review_returns_immediately_and_reports_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [_universe_row("600001", "全能公司")])
    task = asyncio.run(request("POST", "/api/v1/tasks", {"title": "后台初筛", "strategy_key": "quality_steady"})).json()
    response = asyncio.run(request("POST", f"/api/v1/research-tasks/{task['id']}/auto-review"))
    assert response.status_code == 200
    job = response.json()
    # 立刻返回一个可轮询的任务，而不是等模型跑完
    assert job["kind"] == "task_auto_review"
    assert job["status"] in {"排队中", "运行中", "已完成", "失败"}

    polled = asyncio.run(request("GET", f"/api/v1/jobs/task_auto_review/{task['id']}")).json()
    assert polled["id"] == job["id"]
    assert asyncio.run(request("POST", "/api/v1/research-tasks/9999/auto-review")).status_code == 404



async def _submit_and_wait(method: str, path: str, kind: str, target_id: int, attempts: int = 80) -> dict:
    """提交后台任务并等它结束。

    必须和提交在同一个事件循环里等——background.submit 用 asyncio.create_task，
    换一个 asyncio.run 就等于把任务连同上一个循环一起丢掉了。
    """

    submitted = (await request(method, path)).json()
    assert submitted["kind"] == kind
    for _ in range(attempts):
        job = (await request("GET", f"/api/v1/jobs/{kind}/{target_id}")).json()
        if job and job["status"] not in {"排队中", "运行中"}:
            return job
        await asyncio.sleep(0.05)
    raise AssertionError(f"后台任务 {kind}:{target_id} 没有在预期时间内结束")


def test_operator_table_is_the_only_place_ratios_are_defined() -> None:
    from stock_decision import operators
    from stock_decision.strategies import DERIVED

    row = {"revenue": 1000.0, "operating_cost": 600.0, "net_profit": 200.0, "operating_cash_flow": 180.0,
           "capex": 30.0, "total_assets": 2000.0, "total_liabilities": 800.0, "equity": 1200.0,
           "eps": 2.0, "ocf_per_share": 2.4, "pe_ttm": 10.0, "pb": 2.0, "roe": 20.0,
           "net_profit_growth": 25.0, "report_date": "2026-03-31", "receivables": 250.0, "inventory": 150.0}

    assert operators.compute("gross_margin", row)["value"] == 40.0
    assert operators.compute("net_margin", row)["value"] == 20.0
    assert operators.compute("cash_conversion", row)["value"] == 90.0
    assert operators.compute("debt_ratio", row)["value"] == 40.0
    assert operators.compute("peg", row)["value"] == 0.4
    assert operators.compute("earnings_yield", row)["value"] == 10.0

    # 策略库不再自己算：同一个 PEG 在候选清单和初筛里必须是同一个数
    assert DERIVED["peg"](row) == operators.compute("peg", row)["value"]
    assert DERIVED["cash_ratio"](row) == operators.compute("cash_ratio", row)["value"]

    # 缺科目要说缺哪个，不能用 0 顶替
    partial = operators.compute("gross_margin", {"revenue": 1000.0})
    assert partial["value"] is None
    assert "operating_cost" in partial["unavailable_reason"]
    # 分母为零/口径不适用要和"缺科目"分开，否则排查时分不清是取数错还是算子错
    guarded = operators.compute("cash_conversion", {"operating_cash_flow": 10.0, "net_profit": -5.0})
    assert guarded["value"] is None and "口径不适用" in guarded["unavailable_reason"]

    # 每个算子都要写明口径；没有口径的数字没法和别处交叉验证
    for operator in operators.OPERATORS:
        assert operator.formula and operator.label and operator.inputs


def test_dupont_explains_where_roe_comes_from() -> None:
    from stock_decision.operators import dupont

    row = {"net_profit": 200.0, "revenue": 1000.0, "total_assets": 2000.0, "equity": 1200.0}
    result = dupont(row)
    assert result["unavailable_reason"] is None
    assert [item["key"] for item in result["components"]] == ["net_margin", "asset_turnover", "equity_multiplier"]
    # 20% 净利率 × 0.5 周转 × 1.67 权益乘数 ≈ 16.7%，与 净利润/净资产 一致
    assert result["roe_reconstructed"] == pytest.approx(16.67, abs=0.05)

    assert dupont({"net_profit": 200.0})["unavailable_reason"] is not None


def test_rederive_fills_valuation_without_the_blocked_snapshot_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repository, "fetch_market_spot",
        lambda: {"rows": [{"symbol": "600001", "name": "只有价格", "price": 100.0, "change_percent": 0.1,
                           "pe_ttm": None, "pb": None, "total_market_cap": None, "float_market_cap": None, "turnover_rate": None}],
                 "source": "新浪全市场快照（降级）", "degraded": True, "missing_fields": ["市盈率", "市净率", "总市值"]},
    )
    monkeypatch.setattr(repository, "fetch_market_fundamentals",
                        lambda period: {"rows": [{"symbol": "600001", "name": "只有价格", "roe": 20.0, "gross_margin": 40.0,
                                                  "revenue_growth": 12.0, "net_profit_growth": 30.0, "eps": 1.0, "ocf_per_share": 1.2,
                                                  "revenue": 1e10, "net_profit": 1e9, "bps": 20.0, "industry": "测试", "announcement_date": None}],
                                        "source": "东方财富业绩报表", "report_date": period})
    monkeypatch.setattr(repository, "fetch_index_members", lambda: {"members": [], "source": "中证指数官网", "missing_indexes": []})
    monkeypatch.setattr("stock_decision.scheduler.RETRY_DELAYS", ())
    asyncio.run(request("POST", "/api/v1/sync/jobs/universe/run"))

    result = asyncio.run(request("POST", "/api/v1/universe/rederive")).json()
    assert result["market_cap_coverage"] == 1
    assert result["pb_coverage"] == 1
    assert result["pe_coverage"] == 1
    assert "推算" in result["note"] or "亏损股" in result["note"]

    # 四套依赖估值字段的策略应当因此恢复可用
    usable = {item["key"] for item in asyncio.run(request("GET", "/api/v1/screen/strategies")).json() if item["available"]}
    assert {"undervalued_defensive", "quality_steady", "quality_growth"} <= usable


def test_news_feeds_can_be_managed_and_builtin_ones_are_protected() -> None:
    feeds = asyncio.run(request("GET", "/api/v1/news/feeds")).json()
    assert len(feeds) >= 5
    assert all(feed["builtin"] for feed in feeds)
    assert all(feed["enabled"] for feed in feeds)

    added = asyncio.run(request("POST", "/api/v1/news/feeds",
                                {"name": "某垂直媒体", "url": "https://example.com/rss.xml"})).json()
    assert added["builtin"] is False and added["enabled"] is True

    asyncio.run(request("PATCH", f"/api/v1/news/feeds/{added['id']}?enabled=false"))
    listed = {feed["id"]: feed for feed in asyncio.run(request("GET", "/api/v1/news/feeds")).json()}
    assert listed[added["id"]]["enabled"] is False

    # 内置源可以停用，但不能删——删掉之后没有入口能加回来
    builtin_id = next(feed["id"] for feed in feeds if feed["builtin"])
    assert asyncio.run(request("DELETE", f"/api/v1/news/feeds/{builtin_id}")).json()["deleted"] is False
    assert asyncio.run(request("DELETE", f"/api/v1/news/feeds/{added['id']}")).json()["deleted"] is True


def test_refresh_news_skips_disabled_feeds_and_records_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(request("GET", "/api/v1/news/feeds"))
    feeds = asyncio.run(request("GET", "/api/v1/news/feeds")).json()
    for feed in feeds[1:]:
        asyncio.run(request("PATCH", f"/api/v1/news/feeds/{feed['id']}?enabled=false"))

    seen: list[str] = []

    def fake_fetch(feed, limit=40):
        seen.append(feed["key"])
        raise TimeoutError("超时")

    monkeypatch.setattr(repository, "fetch_feed", fake_fetch)
    result = repository.refresh_news()
    assert seen == [feeds[0]["key"]]                      # 停用的源不抓
    assert result["failures"]                             # 失败要点名，不静默跳过
    after = asyncio.run(request("GET", "/api/v1/news/feeds")).json()
    assert "TimeoutError" in after[0]["last_error"]       # 失败原因留在源上，方便判断该不该删


def test_news_refresh_is_a_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """接口必须立刻返回一个任务，不能同步跑完。

    实测一轮 20 秒以上：十几个 RSS 源逐个抓（有的源本身就慢，还会超时），
    再把规则没接住的标题分批送给模型。同步跑的话页面就那么卡着，
    切走再回来还得从头点一次——**而这一轮的花费已经产生了**。
    """
    monkeypatch.setattr(repository, "fetch_feed", lambda feed, limit=40: [])

    response = asyncio.run(request("POST", "/api/v1/news/refresh"))

    assert response.status_code == 200
    job = response.json()
    assert job["kind"] == "news_refresh"
    assert job["status"] in {"排队中", "运行中", "已完成"}


def test_briefing_prompt_forbids_prediction_and_uses_only_local_data() -> None:
    from stock_decision.chain_and_reports import BRIEFING_SYSTEM_PROMPT

    # 首页简报最容易滑向"明天怎么走"，所以这三条要锁死
    assert "不预测走势" in BRIEFING_SYSTEM_PROMPT
    assert "绝对不要补充任何行情、新闻、宏观判断或行业观点" in BRIEFING_SYSTEM_PROMPT
    assert "不给目标价、不给买卖时点、不给仓位建议、不给评分" in BRIEFING_SYSTEM_PROMPT
    assert "或将" in BRIEFING_SYSTEM_PROMPT and "有望" in BRIEFING_SYSTEM_PROMPT


def test_heatmap_reports_breadth_and_available_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "涨", change_percent=2.0),
        _universe_row("600002", "跌", change_percent=-1.5),
        _universe_row("300003", "平", change_percent=0.0),
    ])
    view = asyncio.run(request("GET", "/api/v1/heatmap?metric=change_percent")).json()
    breadth = view["breadth"]
    # 涨跌家数比中位数更能反映广度：中位数会被几只权重股带偏
    assert (breadth["advancing"], breadth["declining"], breadth["unchanged"]) == (1, 1, 1)
    assert breadth["covered"] == 3
    assert "不预示任何走向" in breadth["note"]

    groups = {item["group"] for item in view["scopes"]}
    assert {"全市场", "交易所", "板块"} <= groups
    # 板块范围直接从底座数出来，创业板那只应当被识别
    assert any(item["key"] == "board:创业板" for item in view["scopes"])
    assert asyncio.run(request("GET", "/api/v1/heatmap?scope=board:创业板&metric=change_percent")).json()["universe_total"] == 1


def test_heatmap_cockpit_lenses_and_archived_company_beacons(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "灯塔公司", industry="银行", change_percent=-2.0, turnover_rate=3.5),
        _universe_row("600002", "同行公司", industry="银行", change_percent=1.0, turnover_rate=0.5),
    ])
    company = asyncio.run(request("POST", "/api/v1/companies", {
        "symbol": "600001", "name": "灯塔公司", "industry": "银行",
    })).json()
    with repository.connection() as conn:
        conn.execute(
            """INSERT INTO market_sentiment
               (symbol, name, attention_index, source, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("600001", "灯塔公司", 88.0, "测试关注度", datetime.now().isoformat()),
        )

    volatility = asyncio.run(request("GET", "/api/v1/heatmap?metric=abs_change")).json()
    bank = next(tile for tile in volatility["tiles"] if tile["name"] == "银行")
    # 波动镜头取真实当日涨跌的绝对值；两家公司 2% 与 1% 的中位数是 1.5%。
    assert bank["metric_value"] == 1.5
    assert bank["watched"] == [{"company_id": company["id"], "symbol": "600001", "name": "灯塔公司"}]

    activity = asyncio.run(request("GET", "/api/v1/heatmap?metric=turnover_rate")).json()
    assert next(tile for tile in activity["tiles"] if tile["name"] == "银行")["metric_value"] == 2.0
    assert "不等同于资金净流入" in activity["metric_note"]

    attention = asyncio.run(request("GET", "/api/v1/heatmap?metric=attention_index")).json()
    assert attention["with_metric"] == 1
    assert next(tile for tile in attention["tiles"] if tile["name"] == "银行")["metric_value"] == 88.0


def test_range_returns_refuse_to_guess_without_enough_history() -> None:
    result = asyncio.run(request("POST", "/api/v1/universe/range-returns")).json()
    # 全市场区间涨跌没有可直接取到的来源，只能自己累积；不足时不给数字
    assert result["trading_days"] >= 0
    assert result["filled"]["change_5d"] == 0
    assert "只能从接入那天起累积" in result["note"]


def test_five_day_lens_opens_once_five_real_closes_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [_universe_row("600001", "五日样本", industry="银行", price=105.0)])
    with repository.connection() as conn:
        conn.execute("DELETE FROM universe_valuation_history")
        for day, close in enumerate((100.0, 101.0, 102.0, 103.0, 105.0), start=1):
            conn.execute(
                """INSERT INTO universe_valuation_history
                   (symbol, point_date, pe_ttm, pb, close, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("600001", f"2026-08-{day:02d}", 10.0, 1.0, close, "测试日线"),
            )
    result = asyncio.run(request("POST", "/api/v1/universe/range-returns")).json()
    assert result["filled"]["change_5d"] == 1
    statuses = {item["metric"]: item for item in asyncio.run(request("GET", "/api/v1/market/lenses")).json()}
    assert statuses["change_5d"]["available"] is True
    view = asyncio.run(request("GET", "/api/v1/heatmap?metric=change_5d")).json()
    assert view["tiles"][0]["metric_value"] == 5.0


def test_market_lenses_explain_unavailable_history_instead_of_opening_blank_chart() -> None:
    statuses = asyncio.run(request("GET", "/api/v1/market/lenses")).json()
    by_metric = {item["metric"]: item for item in statuses}
    assert by_metric["change_5d"]["available"] is False
    assert by_metric["change_5d"]["required_days"] == 5
    assert "5" in by_metric["change_5d"]["message"]
    assert by_metric["ytd_change"]["required_days"] is None
    assert "暂不展示空图" in by_metric["ytd_change"]["message"]


def test_market_fund_flow_keeps_real_order_size_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "fetch_market_fund_flow", lambda: [{
        "date": "2026-08-10",
        "mainNetInflow": -41_400_000_000,
        "mainNetInflowPercent": -1.64,
        "superLargeNetInflow": -29_100_000_000,
        "largeNetInflow": -12_300_000_000,
        "mediumNetInflow": 11_400_000_000,
        "smallNetInflow": 30_000_000_000,
        "shClose": 3966.59,
        "shChangePercent": 0.67,
        "szClose": 14316.96,
        "szChangePercent": 0.04,
    }])
    response = asyncio.run(request("GET", "/api/v1/market/fund-flow"))
    assert response.status_code == 200
    view = response.json()
    assert view["source"].startswith("StockSDK")
    assert view["as_of"] == "2026-08-10"
    assert view["points"][0]["main_net_inflow"] == -41_400_000_000
    assert "不等同于机构真实持仓变化" in view["boundary"]


def test_lenient_json_repairs_what_models_actually_get_wrong() -> None:
    from stock_decision.jsonio import loads_lenient

    # 中文里夹英文双引号——这是简报生成实际挂掉的那一种
    assert loads_lenient('{"a": "平安重申"稳定分红"承诺"}')["a"] == '平安重申"稳定分红"承诺'
    # 尾随逗号
    assert loads_lenient('{"a": ["x", "y",]}')["a"] == ["x", "y"]
    # 字符串里的裸换行
    assert loads_lenient('{"a": "上\n下"}')["a"] == "上\n下"
    # ```json 围栏
    assert loads_lenient('```json\n[{"i": 1}]\n```', "array") == [{"i": 1}]
    # 修不好要抛出可排查的信息，而不是静默返回空
    with pytest.raises(ValueError, match="没有返回可解析"):
        loads_lenient("模型今天不想输出 JSON")


def test_健康检查带着运营脉搏_而且不因为它翻红(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/health` 原来只回答「服务活着吗」。

    而这个系统真正会**安静坏掉**的地方是别的三件事：积分闸口宕着（在免费送）、
    后台任务连着失败（用户点了没结果）、数据源好几天没同步（页面上全是旧数）。
    三件都不会让服务停，也没有任何地方会主动说话——只能靠有人恰好点进那一页。

    所以把计数摊进 /health，外部探针一个 URL 就够。**但不能让它们翻 status**：
    status 决定探针要不要重启进程，而"数据源三天没同步"重启一百次也不会好。

    这条还挡一类具体的错：`_ops_pulse()` 里那几句 SQL 的列名是**手写的**。
    第一版按 provider / finished_at 猜，真跑起来报 column "provider" does not exist，
    而它被 except 吞成了一行字段、接口照样 200 —— 单测里 assert 到具体键，
    列名写错就会在这里炸出来，而不是在生产上安静地少一块。
    """
    response = asyncio.run(request("GET", "/health"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"

    ops = body["ops"]
    # 这几个键就是"要不要有人来管"的全部依据，少一个就有一类问题看不见
    for key in ("unbilled_recent", "unbilled_pending", "ai_paused", "jobs_failed_24h", "alerts"):
        assert key in ops, f"运营脉搏少了 {key}：{ops}"
    # SQL 写错时这两个键会变成 *_error，而不是安静地没有
    assert "jobs_error" not in ops, f"脉搏里的 SQL 出错了：{ops.get('jobs_error')}"
    assert "unbilled_error" not in ops, f"台账读不出来：{ops.get('unbilled_error')}"
    assert isinstance(ops["alerts"], list)


def test_真实用户监测只收数字_不收内容(monkeypatch: pytest.MonkeyPatch) -> None:
    """页面上全是持仓成本、买卖理由、还没公开的判断——**任何埋点都不该带走这些**。

    所以这条接口的字段是封闭的：页面名在服务端按白名单校验，不在名单里的
    一律记成 other；毫秒数做范围检查；报错只留类型与消息前 200 字。
    前端传进来的任何多余字段都不会落库。
    """
    import asyncio

    from stock_decision import rum

    # 混进来一段"内容"和一个不存在的页面名，两样都不该被原样存下
    payload = {
        "page": "../../etc/passwd?q=贵州茅台",
        "kind": "nav", "device": "mobile",
        "ttfb_ms": 120, "dom_ready_ms": 800, "load_ms": 1500, "lcp_ms": 2200,
        "note": "我的持仓成本是 40.86",          # 多余字段
        "error_message": "x" * 500,
    }
    response = asyncio.run(request("POST", "/api/v1/rum", payload))
    assert response.status_code == 204

    import json as _json

    from stock_decision.database import connection

    with connection() as conn:
        row = dict(conn.execute("SELECT * FROM rum_samples ORDER BY id DESC LIMIT 1").fetchone())
    assert row["page"] == "other", "白名单外的页面名必须落成 other"
    assert row["lcp_ms"] == 2200 and row["ttfb_ms"] == 120
    assert len(row["error_message"]) <= 200
    assert "持仓成本" not in _json.dumps(row, ensure_ascii=False), "多余字段不该进库"

    summary = rum.summary(7)
    assert summary["samples"] >= 1
    assert "不记 URL 参数" in summary["boundary"]


def test_离谱的毫秒数不进分位统计(monkeypatch: pytest.MonkeyPatch) -> None:
    """后台标签页、时钟回拨会产生几小时的"首屏时间"。
    **让它们进分位数，整张表就没法看了**——所以超范围的一律当成没测到（NULL），
    而不是填 0（0 会被读成"很快"）。"""
    from stock_decision import rum

    assert rum._clean_ms(-5) is None
    assert rum._clean_ms(60 * 60 * 1000) is None        # 一小时，显然不是首屏
    assert rum._clean_ms("abc") is None
    assert rum._clean_ms(None) is None
    assert rum._clean_ms(1500) == 1500
