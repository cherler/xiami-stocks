import asyncio
import json

import httpx

from stock_decision import access
from stock_decision import industry_chain_draft
from stock_decision.main import app
from stock_decision.repository import (
    create_generated_industry_chain_theme,
    create_industry_chain_theme,
    delete_industry_chain_record,
    get_industry_chain,
    list_industry_chain_themes,
)


async def request(method: str, path: str, json: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json)


async def submit_draft_and_wait(topic: str) -> dict:
    """和提交处共用一个事件循环，确保后台任务真的能跑完。"""

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post("/api/v1/industry-chains/draft", json={"topic": topic})
        assert submitted.status_code == 200
        assert submitted.json()["kind"] == "industry_chain_draft"
        for _ in range(80):
            status = await client.get("/api/v1/industry-chains/draft/status")
            job = status.json()
            if job and job["status"] not in {"排队中", "运行中"}:
                return job
            await asyncio.sleep(.02)
    raise AssertionError("产业链初稿后台任务没有在预期时间内结束")


def test_product_service_chain_map_is_separate_from_company_relationship_clues() -> None:
    company = asyncio.run(request("POST", "/api/v1/companies", json={
        "symbol": "601318", "name": "测试保险公司", "industry": "保险业",
    }))
    assert company.status_code == 201
    company_id = company.json()["id"]

    created = asyncio.run(request("POST", "/api/v1/industry-chains", json={
        "name": "保险服务链测试",
        "chain_type": "服务链",
        "description": "按产品与服务交付过程整理。",
    }))
    assert created.status_code == 201
    view = created.json()
    theme_id = view["id"]
    assert [stage["name"] for stage in view["stages"]] == [
        "获客与资源", "产品与定价", "履约与服务", "客户与场景",
    ]
    assert view["node_count"] == 0

    channel = asyncio.run(request("POST", f"/api/v1/industry-chains/{theme_id}/nodes", json={
        "stage_id": view["stages"][0]["id"],
        "name": "代理人渠道",
        "node_type": "渠道",
        "description": "仅用于验证节点结构。",
    }))
    assert channel.status_code == 200
    channel_node = channel.json()["stages"][0]["nodes"][0]
    assert channel_node["verification"] == "待补证"

    product = asyncio.run(request("POST", f"/api/v1/industry-chains/{theme_id}/nodes", json={
        "stage_id": view["stages"][1]["id"],
        "name": "寿险产品",
        "node_type": "服务",
        "upstream_node_id": channel_node["id"],
        "relation_type": "触达",
        "source_name": "公开产品资料",
        "source_url": "https://example.com/product",
        "verification": "已核验",
    }))
    assert product.status_code == 200
    product_view = product.json()
    product_node = product_view["stages"][1]["nodes"][0]
    assert product_view["edges"][0]["relation_type"] == "触达"

    positioned = asyncio.run(request("POST", f"/api/v1/industry-chains/{theme_id}/positions", json={
        "node_id": product_node["id"],
        "company_id": company_id,
        "role": "产品提供方",
        "source_name": "公司官网",
        "source_url": "https://example.com/company",
        "verification": "已核验",
    }))
    assert positioned.status_code == 200
    assert positioned.json()["company_count"] == 1
    position_id = positioned.json()["stages"][1]["nodes"][0]["positions"][0]["id"]

    company_positions = asyncio.run(request(
        "GET", f"/api/v1/companies/{company_id}/industry-chain-positions"
    ))
    assert company_positions.status_code == 200
    theme = company_positions.json()["themes"][0]
    assert theme["theme_name"] == "保险服务链测试"
    assert theme["positions"][0]["node_name"] == "寿险产品"
    assert theme["positions"][0]["stage_name"] == "产品与定价"

    # 删除定位只影响底图，不会删公司档案。
    deleted = asyncio.run(request(
        "DELETE", f"/api/v1/industry-chains/records/position/{position_id}"
    ))
    assert deleted.json() == {"deleted": True}
    detail = asyncio.run(request("GET", f"/api/v1/companies/{company_id}"))
    assert detail.status_code == 200


def test_industry_chain_rejects_unknown_skeleton_type() -> None:
    response = asyncio.run(request("POST", "/api/v1/industry-chains", json={
        "name": "错误模板", "chain_type": "随便画",
    }))
    assert response.status_code == 409
    assert "制造链、服务链或平台生态" in response.json()["detail"]


def test_default_industry_chains_are_ready_to_read_without_user_input() -> None:
    response = asyncio.run(request("GET", "/api/v1/industry-chains"))
    assert response.status_code == 200
    themes = response.json()
    assert [item["name"] for item in themes[:4]] == [
        "保险产品与服务", "白酒生产与消费", "家电制造与交付", "锂电池材料与应用",
    ]
    assert all(item["is_default"] for item in themes[:4])
    assert all(item["node_count"] >= 13 for item in themes[:4])
    assert len([item for item in themes if item["is_default"]]) == 14
    assert {item["category"] for item in themes} >= {
        "金融服务", "消费与食品", "数字科技", "新能源与制造", "材料与化工", "交通与物流",
    }

    insurance = asyncio.run(request("GET", f"/api/v1/industry-chains/{themes[0]['id']}"))
    assert insurance.status_code == 200
    view = insurance.json()
    assert view["is_default"] is True
    assert view["stages"][0]["nodes"][0]["source_url"].startswith("https://www.nfra.gov.cn/")
    assert view["stages"][0]["nodes"][0]["verification"] == "已核验"

    # 默认底图是产品的起点，不能被整张删掉；用户仍可增补节点和公司位置。
    deleted = asyncio.run(request(
        "DELETE", f"/api/v1/industry-chains/records/theme/{themes[0]['id']}"
    ))
    assert deleted.json() == {"deleted": False}

    # 系统图结构不直接改；复制出的个人版本才是可编辑资产。
    copied = asyncio.run(request("POST", f"/api/v1/industry-chains/{themes[0]['id']}/fork"))
    assert copied.status_code == 201
    assert copied.json()["is_default"] is False
    assert copied.json()["node_count"] == view["node_count"]
    assert "我的版本" in copied.json()["name"]


def test_industry_chain_recommendations_follow_research_pool() -> None:
    ping_an = asyncio.run(request("POST", "/api/v1/companies", json={
        "symbol": "601318", "name": "中国平安", "industry": "保险业",
    }))
    assert ping_an.status_code == 201
    catl = asyncio.run(request("POST", "/api/v1/companies", json={
        "symbol": "300750", "name": "宁德时代", "industry": "电气机械和器材制造业",
    }))
    assert catl.status_code == 201

    themes = asyncio.run(request("GET", "/api/v1/industry-chains")).json()
    recommended = [item for item in themes if item["recommended"]]
    assert {item["name"] for item in recommended} >= {"保险产品与服务", "锂电池材料与应用"}
    insurance = next(item for item in recommended if item["name"] == "保险产品与服务")
    battery = next(item for item in recommended if item["name"] == "锂电池材料与应用")
    assert "中国平安" in insurance["recommendation_reason"]
    assert "宁德时代" in battery["recommendation_reason"]


def test_industry_chain_map_is_isolated_by_user_scope() -> None:
    theme = create_industry_chain_theme({"name": "站主产业链", "chain_type": "制造链"})

    token = access.set_scope("another-user")
    try:
        other_themes = list_industry_chain_themes()
        assert len(other_themes) == 14
        assert all(item["is_default"] for item in other_themes)
        assert get_industry_chain(theme["id"]) is None
        assert delete_industry_chain_record("theme", theme["id"]) is False
    finally:
        access.reset_scope(token)

    assert get_industry_chain(theme["id"])["name"] == "站主产业链"


def _sourced_draft_payload() -> str:
    """一张故意很小的模型回包；来源编号由解析器自己校验。"""

    return json.dumps({
        "name": "AI 数据中心交付链",
        "chain_type": "制造链",
        "description": "从算力设备到云服务交付。",
        "stages": [
            {"name": "算力设备", "stage_kind": "input", "nodes": [
                {"name": "AI 加速器", "node_type": "部件", "description": "提供算力。", "source_refs": [1]},
                {"name": "服务器整机", "node_type": "设备", "description": "承载加速器。", "source_refs": [1]},
            ]},
            {"name": "设施与交付", "stage_kind": "output", "nodes": [
                {"name": "供配电系统", "node_type": "基础设施", "description": "保障供电。", "source_refs": [2]},
                {"name": "云计算服务", "node_type": "服务", "description": "向用户交付算力。", "source_refs": [2]},
                # 没来源的节点不能随模型一起进库。
                {"name": "神秘生态", "node_type": "平台", "source_refs": []},
            ]},
        ],
        "edges": [
            {"from": "AI 加速器", "to": "服务器整机", "relation_type": "集成", "detail": "加速器装入服务器。", "source_refs": [1]},
            {"from": "服务器整机", "to": "云计算服务", "relation_type": "承载", "detail": "服务器用于云服务交付。", "source_refs": [2]},
            # 指向被丢弃节点的关系也必须被丢弃。
            {"from": "云计算服务", "to": "神秘生态", "relation_type": "流向", "source_refs": [1]},
        ],
        "unknowns": ["液冷方案需按机房等级补证"],
    }, ensure_ascii=False)


def test_sourced_chain_draft_keeps_only_traceable_nodes_and_relations() -> None:
    sources = [
        {"title": "工业和信息化部算力基础设施文件", "url": "https://www.gov.cn/example-1", "kind": "一手", "snippet": "服务器与算力基础设施"},
        {"title": "国家数据局云计算资料", "url": "https://www.gov.cn/example-2", "kind": "一手", "snippet": "云计算服务交付"},
    ]
    draft = industry_chain_draft.parse_draft(_sourced_draft_payload(), sources, "AI 数据中心")

    names = {node["name"] for stage in draft["stages"] for node in stage["nodes"]}
    assert names == {"AI 加速器", "服务器整机", "供配电系统", "云计算服务"}
    assert all(node["verification"] == "待确认" for stage in draft["stages"] for node in stage["nodes"])
    assert all(node["source_url"].startswith("https://") for stage in draft["stages"] for node in stage["nodes"])
    assert [(edge["from"], edge["to"]) for edge in draft["edges"]] == [
        ("AI 加速器", "服务器整机"), ("服务器整机", "云计算服务"),
    ]

    created = create_generated_industry_chain_theme(draft)
    assert created["is_default"] is False
    assert created["node_count"] == 4
    assert len(created["edges"]) == 2
    assert all(edge["verification"] == "待确认" for edge in created["edges"])


def test_chain_draft_generation_is_sourced_and_can_be_repeated(monkeypatch) -> None:
    sources = [
        {"title": "工业和信息化部算力基础设施文件", "url": "https://www.gov.cn/example-1", "kind": "一手", "snippet": "服务器与算力基础设施"},
        {"title": "国家数据局云计算资料", "url": "https://www.gov.cn/example-2", "kind": "一手", "snippet": "云计算服务交付"},
    ]
    monkeypatch.setattr(industry_chain_draft.websearch, "available", lambda: (True, ""))
    monkeypatch.setattr(industry_chain_draft.llm, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(industry_chain_draft.websearch, "gather", lambda queries: {
        "hits": sources, "queries": queries, "failures": [],
    })
    monkeypatch.setattr(industry_chain_draft.llm, "call", lambda *_args, **_kwargs: type("Reply", (), {
        "text": _sourced_draft_payload(),
    })())
    monkeypatch.setattr(industry_chain_draft.llm, "model_name", lambda: "测试模型")

    first = industry_chain_draft.generate("AI 数据中心")
    second = industry_chain_draft.generate("AI 数据中心")

    assert first["sources"] == 2
    assert first["primary_sources"] == 2
    assert first["stages"] == 2
    assert first["nodes"] == 4
    assert first["edges"] == 2
    assert first["model"] == "测试模型"
    assert second["theme_name"] != first["theme_name"]
    assert "初稿" in second["theme_name"]


def test_chain_draft_api_returns_a_background_job_that_keeps_its_result(monkeypatch) -> None:
    monkeypatch.setattr(industry_chain_draft, "generate", lambda topic: {
        "theme_id": 42, "theme_name": f"{topic}产业链", "stages": 3, "nodes": 8, "edges": 7,
        "sources": 5, "primary_sources": 2, "queries": [topic], "search_failures": [],
        "unknowns": ["交付环节需核验"], "model": "测试模型", "boundary": "待确认",
    })

    job = asyncio.run(submit_draft_and_wait("低空经济"))

    assert job["status"] == "已完成"
    assert job["result"]["theme_id"] == 42
    assert job["result"]["unknowns"] == ["交付环节需核验"]
