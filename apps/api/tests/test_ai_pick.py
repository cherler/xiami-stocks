"""AI 选股：模型能说什么、不能说什么。

这里测的全是**边界**，不是功能。功能坏了页面上一眼能看见；边界坏了页面上
什么都看不出来——一份编出来的股票清单和一份筛出来的清单长得一模一样，
而这个产品跟股吧的全部区别就在这里。

四条底线：
1. 模型编的字段要被丢掉，**而且要说丢了什么**（静默丢弃比报错更危险）；
2. 模型回的是行号不是股票代码，越界的行号进不来；
3. 概念名单靠正文里逐字出现的公司名匹配，模型不经手；
4. 底座没同步的字段不许出现在给模型的清单里（否则筛出零家，看起来像市场上没有）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_decision import ai_pick  # noqa: E402


FIELDS = [
    {"field": "pe_ttm", "label": "市盈率 TTM", "unit": "", "hint": "", "usable": True},
    {"field": "roe", "label": "净资产收益率", "unit": "%", "hint": "", "usable": True},
    # 库里有这个字段，但底座没同步——**能用和存在是两回事**
    {"field": "dividend_yield", "label": "股息率", "unit": "%", "hint": "", "usable": False},
]
INDUSTRIES = ["煤炭开采", "专用设备", "白酒Ⅱ"]


def _plan(**overrides) -> str:
    import json

    base = {"name": "测试", "summary": "", "rules": [{"field": "pe_ttm", "op": "lte", "value": 20}],
            "sort_field": "pe_ttm", "sort_desc": False, "industries": [], "theme": "",
            "theme_queries": [], "reading": ""}
    base.update(overrides)
    return json.dumps(base, ensure_ascii=False)


# ---------------------------------------------------------------- 翻译这一步


def test_编出来的字段被丢掉并且说出来():
    plan = ai_pick.parse_plan(_plan(rules=[
        {"field": "pe_ttm", "op": "lte", "value": 20},
        {"field": "debt_ratio", "op": "lte", "value": 50},      # 库里根本没有
    ]), FIELDS, INDUSTRIES)

    assert [r["field"] for r in plan["rules"]] == ["pe_ttm"]
    assert any("debt_ratio" in note for note in plan["dropped"]), (
        "丢掉一条条件却不说，用户会以为它生效了——他据此以为筛过的东西，一次都没筛过。")


def test_字段存在但没同步时说的是另一句话():
    """「模型编的」和「你该去同步数据」，用户下一步做的事完全不同。"""
    plan = ai_pick.parse_plan(_plan(rules=[
        {"field": "pe_ttm", "op": "lte", "value": 20},
        {"field": "dividend_yield", "op": "gte", "value": 3},
    ]), FIELDS, INDUSTRIES)

    note = next(n for n in plan["dropped"] if "股息率" in n or "dividend_yield" in n)
    assert "还没有数据" in note, f"该说是底座缺数据，而不是说模型编的：{note}"


def test_一条都翻不出来时报错而不是跑一个空条件():
    with pytest.raises(ai_pick.PlanError) as caught:
        ai_pick.parse_plan(_plan(rules=[{"field": "vibes", "op": "gte", "value": 1}]),
                           FIELDS, INDUSTRIES)
    assert "换个说法" in str(caught.value), "报错要告诉他下一步做什么"


def test_不是数的阈值不许进去():
    """NaN / Infinity 是合法 JSON 字面量（Python 的 json 直接收），而且能穿过 float()。

    穿过去之后表现**不是报错，是这条条件静默地筛不掉任何东西**——
    「ROE ≥ NaN」的比较永远为假或永远为真，取决于比较方向，
    而页面上这条条件照样显示在那里。这种错比报错难查得多。
    """
    for literal in ('"很低"', "null", "NaN", "Infinity", "-Infinity"):
        text = ('{"name":"t","rules":[{"field":"pe_ttm","op":"lte","value":20},'
                f'{{"field":"roe","op":"gte","value":{literal}}}],'
                '"sort_field":"pe_ttm","sort_desc":false}')
        plan = ai_pick.parse_plan(text, FIELDS, INDUSTRIES)
        assert [r["field"] for r in plan["rules"]] == ["pe_ttm"], f"{literal} 不该变成一条条件"
        assert any("阈值不是一个数" in note for note in plan["dropped"]), f"{literal} 被丢掉了但没说"


def test_排序字段不合法时不许沉默地换掉():
    plan = ai_pick.parse_plan(_plan(sort_field="dividend_yield"), FIELDS, INDUSTRIES)
    assert plan["sort_field"] == "pe_ttm"
    assert any("排序" in note for note in plan["dropped"]), (
        "页面上写着按 X 排、实际按 Y 排——这正是这一页刚修好的那个 bug")


def test_库里没有的行业名进不来():
    plan = ai_pick.parse_plan(_plan(industries=["煤炭开采", "元宇宙"]), FIELDS, INDUSTRIES)
    assert plan["industries"] == ["煤炭开采"]
    assert any("元宇宙" in note for note in plan["dropped"])


def test_条件数量封顶():
    rules = [{"field": "pe_ttm", "op": "lte", "value": v} for v in range(1, 12)]
    plan = ai_pick.parse_plan(_plan(rules=rules), FIELDS, INDUSTRIES)
    assert len(plan["rules"]) <= ai_pick.MAX_RULES


def test_给模型的字段清单里没有不可用的字段():
    """喂了没同步的字段，模型会理直气壮地用它写条件，然后跑出零命中——
    而页面上看起来像「市场上没有这样的公司」。"""
    prompt = ai_pick.build_plan_prompt("找便宜的", FIELDS, INDUSTRIES)
    assert "pe_ttm" in prompt
    assert "dividend_yield" not in prompt


def test_搜索词由代码拼而不是听模型的():
    """实测同一个问题跑两次：第一次模型给「固态电池」搜回 8 篇科普、对上 5 家；
    第二次它换了说法，**一家都没对上**——概念这一层白跑了，而页面上看不出差别。

    我们要的不是「关于这个概念的文章」，是「哪些 A 股公司算这个概念」。"""
    plan = ai_pick.parse_plan(
        _plan(theme="固态电池", theme_queries=["固态电池是什么原理"]), FIELDS, INDUSTRIES)
    assert all("是什么原理" not in q for q in plan["theme_queries"]), "模型的自由发挥不该被采用"
    assert all("固态电池" in q for q in plan["theme_queries"])
    assert any("上市公司" in q for q in plan["theme_queries"]), "要问的是哪些公司算，不是这个概念是什么"


def test_没提概念就不搜():
    plan = ai_pick.parse_plan(_plan(theme="", theme_queries=["随便搜点什么"]), FIELDS, INDUSTRIES)
    assert plan["theme_queries"] == [], "没有概念却联网，是白花搜索费"


# ---------------------------------------------------------------- 概念 → 公司


UNIVERSE = [
    {"symbol": "300750", "name": "宁德时代"},
    {"symbol": "002074", "name": "国轩高科"},
    {"symbol": "600519", "name": "贵州茅台"},
]


def test_只认正文里逐字出现的公司():
    hits = ai_pick.theme_symbols([
        {"title": "固态电池梳理", "url": "https://a.com/1",
         "snippet": "宁德时代在固态电池上进展较快，另有国轩高科等。"},
    ], UNIVERSE)

    assert set(hits) == {"300750", "002074"}, "没被提到的公司不能进名单"
    assert hits["300750"][0]["url"] == "https://a.com/1", "每一家都要带得回是哪篇文章说的"


def test_六位代码也认但必须是库里有的():
    hits = ai_pick.theme_symbols([
        {"title": "", "url": "https://a.com/2", "snippet": "相关标的（300750）与（999999）。"},
    ], UNIVERSE)
    assert set(hits) == {"300750"}, "库里没有的代码不能凭空变成一只票"


def test_同一篇文章不会被记成两个出处():
    doc = {"title": "宁德时代", "url": "https://a.com/3", "snippet": "宁德时代宁德时代"}
    hits = ai_pick.theme_symbols([doc, doc], UNIVERSE)
    assert len(hits["300750"]) == 1, "同一个链接记两次，会凭空造出佐证强度"


def test_content_这个键也认():
    """websearch 给的是 snippet，别处叫 content。认错键的表现是一条都匹配不上，
    看起来像「搜索没搜到东西」。"""
    hits = ai_pick.theme_symbols(
        [{"title": "", "url": "https://a.com/4", "content": "贵州茅台"}], UNIVERSE)
    assert set(hits) == {"600519"}


# ---------------------------------------------------------------- 挑这一步


ROWS = [{"symbol": "000001", "name": "甲"}, {"symbol": "000002", "name": "乙"}]


def test_越界的行号进不来():
    out = ai_pick.parse_picks(
        '{"picks": [{"index": 1, "why": "有理由"}, {"index": 99, "why": "编的"}]}', ROWS)
    assert [p["symbol"] for p in out["picks"]] == ["000001"]


def test_模型给不了库外的股票代码():
    """**它回的是行号，不是代码。** 就算它写了一个代码字段，也不会被采用。"""
    out = ai_pick.parse_picks(
        '{"picks": [{"index": 2, "symbol": "600000", "why": "x"}]}', ROWS)
    assert out["picks"][0]["symbol"] == "000002", "代码只能来自行号对应的那一行"


def test_同一家挑两次只算一次():
    out = ai_pick.parse_picks(
        '{"picks": [{"index": 1, "why": "a"}, {"index": 1, "why": "b"}]}', ROWS)
    assert len(out["picks"]) == 1


def test_没挑的那几家也要能读出来():
    out = ai_pick.parse_picks(
        '{"picks": [{"index": 1, "why": "a"}], "passed": [{"index": 2, "why": "太贵"}]}', ROWS)
    assert out["passed"] == [{"symbol": "000002", "name": "乙", "why": "太贵"}]


def test_解析不了就报错不返回空清单():
    """静默返回空 = 页面显示「模型没挑出任何一家」，那是一句假话。"""
    with pytest.raises(RuntimeError):
        ai_pick.parse_picks("模型今天不想输出 JSON", ROWS)


# ---------------------------------------------------------------- 默认问法


def test_默认问法会说清楚为什么不能用():
    asks = ai_pick.usable_default_asks(FIELDS)
    assert asks, "页面上要有默认选项"
    for ask in asks:
        if not ask["usable"]:
            assert ask["unavailable_reason"], "不可用就要说是缺哪个字段，不能沉默地灰掉"


def test_喂给模型的候选行带着年报口径():
    """roe 是最新报告期（眼下是一季报），而「这家公司赚钱能力如何」问的是年度。
    只给前者，模型会把一季度的数当成这家公司的 ROE。"""
    brief = ai_pick.brief_of({
        "symbol": "000001", "name": "甲", "industry": "白酒Ⅱ",
        "roe": 1.9, "annual_roe": 22.4, "annual_report_date": "20251231",
    })
    assert "年报净资产收益率 22.4%" in brief
    assert "年报期 20251231" in brief


# ---------------------------------------------------------------- 接口


def test_默认问法接口不花钱也不需要模型():
    """页面一进来就要拿到默认选项。**这条接口不许碰模型**——
    一个还没点「开始选」就开始扣分的功能，没人敢再点第二次。"""
    import asyncio

    import httpx

    from stock_decision.database import configure_database, initialize_database
    from stock_decision.main import app

    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        configure_database(Path(folder) / "t.db")
        initialize_database()

        called: list[str] = []
        from stock_decision import llm
        original, llm.call = llm.call, lambda *a, **k: called.append("boom")

        async def go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/screen/ai-pick/options")

        try:
            response = asyncio.run(go())
        finally:
            llm.call = original

    assert response.status_code == 200
    body = response.json()
    assert body["asks"], "页面上要有默认选项"
    assert "web_available" in body
    assert called == [], "拿默认选项不该调模型"


def test_没跑过时状态接口返回空而不是报错():
    import asyncio
    import tempfile

    import httpx

    from stock_decision.database import configure_database, initialize_database
    from stock_decision.main import app

    with tempfile.TemporaryDirectory() as folder:
        configure_database(Path(folder) / "t.db")
        initialize_database()

        async def go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/screen/ai-pick/status")

        response = asyncio.run(go())

    assert response.status_code == 200
    assert response.json() is None


def test_联网那次的报价按公式算出来而不是含糊带过():
    """确认框原来写「另计几分搜索费用」——含糊，而且用词错了：
    这个产品的单位是积分，不是钱。

    而这个数根本不含糊：搜索次数（MAX_THEME_QUERIES）和系数
    （SEARCH_CREDIT_COEFF）都写死在代码里，一乘就出来。
    **能算准的数不要用「几分」搪塞。**
    """
    import asyncio
    import tempfile

    import httpx

    from stock_decision import llm
    from stock_decision.database import configure_database, initialize_database
    from stock_decision.main import app

    with tempfile.TemporaryDirectory() as folder:
        configure_database(Path(folder) / "t.db")
        initialize_database()

        async def go():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/credits/estimates")

        table = asyncio.run(go()).json()

    assert table["ai-pick"] == llm.credits_for(llm.TYPICAL_TOKENS["ai-pick"])
    assert table["ai-pick-web"] == llm.credits_for_report(
        ai_pick.MAX_THEME_QUERIES, llm.TYPICAL_TOKENS["ai-pick"])
    assert table["ai-pick-web"] > table["ai-pick"], "联网要更贵，否则那个开关等于没成本"
