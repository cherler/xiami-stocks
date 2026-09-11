"""行业特有指标：这门生意该盯的那几个数。

ROE 和毛利率对任何公司都能算，也因此对任何公司都说不出多少东西。
白酒该看合同负债，银行该看拨贷比，地产该看已售未结转——
**看着 ROE 买白酒和看着合同负债买白酒，是两种完全不同的研究。**

这里守的是三件事：口径不许错（累计 vs 时点、季报 vs 年报）、
行业不许硬凑、算不出来时不许把"缺科目"说成"这个数是 0"。
"""

import pytest

from stock_decision import industry_metrics as im


def _p(date, items, **base):
    return {"report_date": date, "items": items, **base}


# ------------------------------------------------------------------ 口径

def test_flow_metrics_only_use_annual_reports():
    """**新浪的报表是累计口径。**

    一季报的营业收入只有四分之一年，拿时点数（合同负债）去除它，
    比值天然是年报的四倍——量出来的是日历，不是渠道打款变强了。
    """
    periods = [
        _p("2025-03-31", {"合同负债": 100.0}, revenue=25.0),     # 一季报：比值会是 400%
        _p("2025-12-31", {"合同负债": 100.0}, revenue=100.0),    # 年报：100%
    ]
    view = im.analyze("白酒", periods)
    row = next(r for r in view["rows"] if r["key"] == "contract_liability")
    assert [point["report_date"] for point in row["series"]] == ["2025-12-31"]
    assert row["latest"]["value"] == 100.0


def test_a_point_in_time_amount_is_compared_year_on_year():
    """余额这类时点数可以看季报，但**要跟去年同期比**。

    白酒的合同负债在春节后那一季天然是高点，拿一季报去比上一期年报，
    量出来的还是日历。
    """
    periods = [
        _p("2025-03-31", {"合同负债": 100e8}),
        _p("2025-12-31", {"合同负债": 300e8}),
        _p("2026-03-31", {"合同负债": 130e8}),
    ]
    view = im.analyze("白酒", periods)
    row = next(r for r in view["rows"] if r["key"] == "contract_amount")
    assert row["latest"]["value"] == 130.0
    assert row["change"] == 30.0, "该跟去年同期的 100 亿比，不是跟上一期年报的 300 亿比"
    assert row["compare_note"] == "较去年同期"


def test_the_two_names_of_the_same_thing_are_added_up_either_way():
    """2020 年新收入准则之前叫「预收款项」，之后改叫「合同负债」。

    要求两个都在的话，横跨准则变更的公司这条指标永远算不出来。
    """
    old = im.analyze("白酒", [_p("2018-12-31", {"预收款项": 50.0}, revenue=100.0)])
    new = im.analyze("白酒", [_p("2025-12-31", {"合同负债": 50.0}, revenue=100.0)])
    for view in (old, new):
        row = next(r for r in view["rows"] if r["key"] == "contract_liability")
        assert row["latest"]["value"] == 50.0


def test_a_missing_line_item_is_never_treated_as_zero():
    """**「合同负债为 0」和「这张表上没有合同负债这一栏」是两件事。**

    前者是渠道不打款，后者是银行股。当成 0 算，会给银行算出一个 0%
    的合同负债占比，而那个数看起来跟真的一模一样。
    """
    view = im.analyze("银行", [_p("2025-12-31", {"净利息收入": 10.0}, total_assets=1000.0)])
    row = next(r for r in view["rows"] if r["key"] == "upstream")
    assert row["latest"] is None
    assert row["applicable"] is False
    assert "营业成本" in row["missing"], "算不出来要说是缺哪个科目"


def test_a_computed_metric_reports_nothing_as_missing():
    """算出来了还列一串「缺」，会让人以为这个数是残缺的——而它是完整的。"""
    view = im.analyze("白酒", [_p("2025-12-31", {"合同负债": 50.0}, revenue=100.0)])
    row = next(r for r in view["rows"] if r["key"] == "contract_liability")
    assert row["missing"] == [] and row["applicable"] is True


# ------------------------------------------------------------------ 行业

def test_industries_are_matched_exactly_never_fuzzily():
    """**把「食品饮料」当成「白酒」来算，对乳制品公司是错的。**

    而错出来的数看起来跟对的一模一样，这是最危险的一类错。
    """
    assert im.resolve_industry("白酒") == "白酒"
    assert im.resolve_industry("食品饮料") == "", "一级行业不该被当成白酒"
    assert im.resolve_industry("白酒饮料制造业") == "", "包含关系不算匹配"
    assert im.resolve_industry(None, "", "银行") == "银行"


def test_an_undefined_industry_says_so_instead_of_pretending():
    view = im.analyze("环保设备", [_p("2025-12-31", {"研发费用": 5.0}, revenue=100.0)])
    assert view["resolved"] == ""
    assert "还没有定义专属指标" in view["note"]
    assert all(row["scope"] == "通用" for row in view["rows"])


def test_each_industry_gets_its_own_metrics():
    for industry, expected in (("白酒", "contract_liability"), ("银行", "provision"),
                               ("房地产", "presale_cover"), ("证券", "fee_mix")):
        keys = {r["key"] for r in im.analyze(industry, []).get("rows", [])}
        assert expected in keys, f"{industry} 少了 {expected}"


def test_the_bank_proxy_admits_it_is_a_proxy():
    """真正的净息差分母是「生息资产平均余额」，报表上没有这一栏。

    不说清楚的话，跟银行自己披露的净息差对不上时，你会以为是算错了。
    """
    row = next(r for r in im.analyze("银行", []).get("rows", []) if r["key"] == "nim_proxy")
    assert "代理" in row["why"] and "生息资产" in row["why"]


# ------------------------------------------------------------------ 说话的边界

def test_two_points_are_not_a_trend():
    """两个点画出来的线，看着跟趋势一模一样。"""
    two = im.analyze("白酒", [_p(f"202{i}-12-31", {"合同负债": 50.0}, revenue=100.0) for i in (4, 5)])
    three = im.analyze("白酒", [_p(f"202{i}-12-31", {"合同负债": 50.0}, revenue=100.0) for i in (3, 4, 5)])
    assert next(r for r in two["rows"] if r["key"] == "contract_liability")["trendable"] is False
    assert next(r for r in three["rows"] if r["key"] == "contract_liability")["trendable"] is True


def test_direction_hints_never_become_a_score():
    """合同负债涨是好事，涨到离谱就是压货。**方向本身说明不了对错。**"""
    view = im.analyze("白酒", [_p("2025-12-31", {"合同负债": 50.0}, revenue=100.0)])
    assert "不参与任何打分" in view["boundary"]
    for row in view["rows"]:
        assert "score" not in row and "verdict" not in row


def test_computable_metrics_come_first():
    """银行的通用三条全是空的，摆在最上面会让人以为功能坏了。"""
    view = im.analyze("银行", [_p("2025-12-31", {"净利息收入": 10.0}, total_assets=1000.0)])
    applicable = [r["applicable"] for r in view["rows"]]
    assert applicable == sorted(applicable, reverse=True)


def test_every_metric_shows_its_recipe():
    """点开就能对着年报核——这是"模型不参与"唯一有意义的证明方式。"""
    for industry in ("白酒", "银行", "房地产", "证券"):
        for row in im.analyze(industry, []).get("rows", []):
            assert row["formula"] and row["why"] and row["inputs"]


# ------------------------------------------------------------------ 走接口

def test_the_endpoint_shows_which_industry_field_it_used():
    """算不出指标时，你得看得见是哪一级分类没对上。"""
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    body = client.get(f"/api/v1/companies/{company['id']}/industry-metrics").json()
    assert body["resolved"] == "白酒"
    assert set(body["industry_sources"]) == {"申万二级", "申万一级", "档案行业"}
    assert "还没同步过" in body["note"], "没有原始科目时要说清楚去哪儿同步"


def test_the_endpoint_404s_on_a_missing_company():
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    assert TestClient(app).get("/api/v1/companies/999999/industry-metrics").status_code == 404


# --------------------------------------------------------------- 行业分类（回归）

def test_shenwan_level_two_is_what_the_alias_table_expects():
    """**这张别名表是照申万写的，而申万分类在库里 5538 行全是空的。**

    sw_level1 / sw_level2 两列建了之后一直没有写入方，于是三级回退
    实际只剩证监会门类「酒、饮料和精制茶制造业」——对不上任何一条别名，
    这个功能因此对 12 家档案公司一条专属指标都没算出来过。

    同步补上之后（providers/akshare_sw），这几个名字必须还认得。
    """
    from stock_decision.industry_metrics import resolve_industry

    assert resolve_industry("白酒Ⅱ") == "白酒"
    assert resolve_industry("国有大型银行Ⅱ") == "银行"
    assert resolve_industry("房地产开发") == "房地产"
    assert resolve_industry("证券Ⅱ") == "证券"


def test_the_csrc_fallback_needs_two_keys():
    """证监会门类是粗分类：「酒、饮料和精制茶制造业」里同时有白酒、啤酒、饮料和茶。

    **直接映射会让饮料公司也按合同负债去解读，而错的结论跟对的长得一模一样。**
    所以要粗分类相容 + 主营里出现确切的词，缺一不可。
    """
    from stock_decision.industry_metrics import resolve_industry

    liquor = "公司主营白酒的生产与销售"
    drinks = "公司主营包装饮用水及茶饮料"
    assert resolve_industry("酒、饮料和精制茶制造业", hint=liquor) == "白酒"
    assert resolve_industry("酒、饮料和精制茶制造业", hint=drinks) == ""
    # 只有关键词、没有粗分类兜底，一样不认——
    # 否则一句「公司参股某银行」就会把一家制造业公司算成银行。
    assert resolve_industry("通用设备制造业", hint="公司参股某银行") == ""
    assert resolve_industry("酒、饮料和精制茶制造业") == ""


def test_unknown_industries_say_so_instead_of_guessing():
    """对不上就说对不上。**不要退回去算通用指标然后假装是特有的。**"""
    from stock_decision.industry_metrics import resolve_industry

    for name in ("白色家电", "电池", "半导体", "航运港口", "保险Ⅱ"):
        assert resolve_industry(name) == "", name


def test_the_sw_sync_skips_itself_when_coverage_is_already_good(monkeypatch):
    """**行业成分一年才调整一两次，而这个作业要发 131 次请求、跑三分钟。**

    跟着底座天天跑是白跑，而白跑看起来完全正常：跑完了、更新了 5193 只，
    没有任何地方显示"这次没有必要"。用覆盖率当闸门而不是时间戳——
    新股上市会让覆盖率慢慢掉下来，掉破线就自动补一次。
    """
    from stock_decision import repository as repo

    def _never(*_a, **_k):
        raise AssertionError("覆盖率够了就不该去取")

    monkeypatch.setattr("stock_decision.providers.akshare_sw.fetch_sw_industry_map", _never)
    with repo.connection() as conn:
        for index in range(20):
            conn.execute(
                "INSERT INTO market_universe (symbol, name, sw_level1, sw_level2, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET sw_level2 = excluded.sw_level2",
                (f"{600000 + index}", f"公司{index}", "食品饮料", "白酒Ⅱ", "2026-08-09"))
    result = repo.refresh_sw_industries()
    assert result["skipped"] is True
    assert "跳过" in result["note"]


def test_an_empty_universe_still_syncs(monkeypatch):
    """**一条都没有时必须去取。** 0/0 不能被当成"覆盖率 100%"——
    那会让这个功能在全新数据库上永远不同步，跟它之前压根没有写入方一样。
    """
    from stock_decision import repository as repo

    called: list[int] = []

    def _fetch(*_a, **_k):
        called.append(1)
        return {"mapping": {}, "industries": 0, "failed": [], "source": "t"}

    monkeypatch.setattr("stock_decision.providers.akshare_sw.fetch_sw_industry_map", _fetch)
    repo.refresh_sw_industries()
    assert called == [1]
