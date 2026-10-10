"""按环节横排:同一环里的公司并排比估值与盈利,再除以市场盘子看拥挤度。

这一屏最容易出的不是崩溃,是**静静地骗人**:
取不到行情的公司被从名单里漏掉、整列空着看起来像「都没涨」、
没有口径的分母算出一个看着像结论的比值。所以下面每条测的都是这类事。
"""

import asyncio

import httpx

from stock_decision.database import connection, now_iso
from stock_decision.main import app


async def request(method: str, path: str, json: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json)


def _seed_universe(symbol: str, name: str, **fields) -> None:
    """往全市场底座塞一只票。没塞的字段留空——空着正是要测的情形之一。"""

    columns = {
        "symbol": symbol, "name": name, "exchange": "上海证券交易所", "board": "主板",
        "updated_at": now_iso(),
        **fields,
    }
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    with connection() as conn:
        conn.execute(f"INSERT INTO market_universe ({names}) VALUES ({marks})", tuple(columns.values()))


def _build_chain() -> tuple[int, int, list[int]]:
    """建一张底图:一个环节,三家公司(两家有行情、一家没有)。"""

    _seed_universe("600001", "有行情甲", price=10.0, pe_ttm=20.0, pb=2.0,
                   total_market_cap=200e8, revenue=50e8, net_profit=5e8,
                   annual_roe=12.0, annual_gross_margin=30.0)
    _seed_universe("600002", "有行情乙", price=20.0, pe_ttm=40.0, pb=4.0,
                   total_market_cap=600e8, revenue=100e8, net_profit=8e8,
                   annual_roe=8.0, annual_gross_margin=20.0)
    # 第三家**故意不塞进底座**:它必须照样出现在名单里,只是格子空着

    company_ids = []
    for symbol, name in (("600001", "有行情甲"), ("600002", "有行情乙"), ("600003", "没行情丙")):
        created = asyncio.run(request("POST", "/api/v1/companies", json={
            "symbol": symbol, "name": name, "industry": "测试业",
        }))
        assert created.status_code == 201, created.text
        company_ids.append(created.json()["id"])

    theme = asyncio.run(request("POST", "/api/v1/industry-chains", json={
        "name": "横排测试链", "chain_type": "制造链", "description": "测按环节横排。",
    }))
    assert theme.status_code == 201
    view = theme.json()
    theme_id = view["id"]
    stage_id = view["stages"][0]["id"]

    node = asyncio.run(request("POST", f"/api/v1/industry-chains/{theme_id}/nodes", json={
        "stage_id": stage_id, "name": "测试环节", "description": "这一环在干什么",
        "source_name": "地球运转图谱", "source_url": "https://example.com/seg", "verification": "已核验",
    }))
    assert node.status_code == 200, node.text
    node_id = [n for s in node.json()["stages"] for n in s["nodes"]][0]["id"]

    for company_id in company_ids:
        placed = asyncio.run(request("POST", f"/api/v1/industry-chains/{theme_id}/positions", json={
            "node_id": node_id, "company_id": company_id, "role": "参与者",
            "source_name": "公司年报", "source_url": "https://example.com/co", "verification": "已核验",
        }))
        assert placed.status_code == 200, placed.text
    return theme_id, node_id, company_ids


def test_compare_keeps_companies_without_quotes_and_says_how_many() -> None:
    theme_id, _, _ = _build_chain()

    response = asyncio.run(request("GET", f"/api/v1/industry-chains/{theme_id}/compare"))
    assert response.status_code == 200
    view = response.json()
    node = view["nodes"][0]

    # 三家都在名单里——取不到行情的那家不许被悄悄删掉
    assert node["count"] == 3
    assert {c["symbol"] for c in node["companies"]} == {"600001", "600002", "600003"}
    missing = next(c for c in node["companies"] if c["symbol"] == "600003")
    assert missing["price"] is None and missing["pe_ttm"] is None

    # 而且要显式说出「有几家没行情」,否则下面的中位数会被当成三家的
    assert node["missing_quote"] == 1
    assert node["pe_median"] == 30.0                      # (20 + 40) / 2,只算有数的两家
    assert node["market_cap_sum"] == 800e8
    assert node["revenue_sum"] == 150e8
    assert node["net_profit_sum"] == 13e8
    assert node["ps"] == round(800 / 150, 2)              # 合计市值 ÷ 合计营收


def test_compare_reports_column_coverage_so_an_empty_column_is_not_read_as_zero() -> None:
    theme_id, _, _ = _build_chain()

    view = asyncio.run(request("GET", f"/api/v1/industry-chains/{theme_id}/compare")).json()

    # 一列全是「—」和「这批公司都没涨」在屏幕上长得一模一样,所以填充数要交出来
    assert view["coverage"]["pe_ttm"] == 2
    assert view["coverage"]["total_market_cap"] == 2
    assert view["coverage"]["dividend_yield"] == 0        # 谁都没有股息率 → 前端会收起这一列并说明


def test_crowding_needs_a_size_and_a_basis_and_a_source() -> None:
    theme_id, node_id, _ = _build_chain()

    before = asyncio.run(request("GET", f"/api/v1/industry-chains/{theme_id}/compare")).json()
    assert before["nodes"][0]["crowding"] is None         # 没填盘子 → 不给拥挤度,也不给 0

    # 只给数不给口径与出处 → 整组作废。没有口径的分母比没有分母更危险:
    # 它会算出一个看着像结论的数,而没人知道那是在和什么比。
    half = asyncio.run(request(
        "PATCH", f"/api/v1/industry-chains/{theme_id}/nodes/{node_id}/market-size",
        json={"market_size_cny_yi": 1000},
    ))
    assert half.status_code == 200
    assert asyncio.run(request("GET", f"/api/v1/industry-chains/{theme_id}/compare")).json()["nodes"][0]["crowding"] is None

    full = asyncio.run(request(
        "PATCH", f"/api/v1/industry-chains/{theme_id}/nodes/{node_id}/market-size",
        json={
            "market_size_cny_yi": 1000,
            "market_size_basis": "全球该环节年度销售收入(2025)",
            "market_size_source_url": "https://example.com/size",
        },
    ))
    assert full.status_code == 200

    after = asyncio.run(request("GET", f"/api/v1/industry-chains/{theme_id}/compare")).json()["nodes"][0]
    assert after["market_size_cny_yi"] == 1000
    assert after["crowding"] == 0.8                       # 800 亿市值 ÷ 1000 亿盘子
    assert after["market_size_basis"].startswith("全球该环节")
    assert after["market_size_source_url"] == "https://example.com/size"


def test_compare_on_a_missing_theme_is_a_404_not_an_empty_chart() -> None:
    response = asyncio.run(request("GET", "/api/v1/industry-chains/999999/compare"))
    assert response.status_code == 404
