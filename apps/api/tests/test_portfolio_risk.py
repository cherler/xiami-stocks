"""组合共同风险：我以为的分散，是不是同一个赌注下了五次。

分散不是由**只数**决定的，是由**它们会不会同时出事**决定的。
这一页要能说出券商持仓页说不出的话，同时**一个字都不许编**——
「这两家算不算同一个风险」一旦编错，后果是你据此调仓。

所以这里守的主要是"不许多说"：样本不够时不许下结论，
权重算不出来时不许退回按只数平均分，产业链那种推出来的数据必须带着置信度。
"""

import pytest

from stock_decision import portfolio_risk as pr


def _pos(symbol, name, weight=25.0, company_id=None):
    return {"symbol": symbol, "company_name": name, "weight": weight,
            "company_id": company_id or int(symbol[-1])}


FOUR = [_pos("600001", "甲", 30), _pos("600002", "乙", 30),
        _pos("600003", "丙", 25), _pos("600004", "丁", 15)]


def _market():
    """一份假的全市场分位池：1 到 100。分位数好算，断言才看得懂。"""
    pool = [float(i) for i in range(1, 101)]
    return {"market_pe": pool, "market_pb": pool, "market_cap": pool}


# ------------------------------------------------------------------ 说不出话的时候

def test_a_single_holding_is_told_it_is_all_in():
    """**门槛原来是 3 只，而那正好把最需要听的人挡在外面。**

    调研里散户的典型错误第一条就是「不懂仓位管理，总满仓单只个股」。
    对这种仓位说「谈不上分散」是废话；该说的是「你全押在这一家上，
    它的认错条件写了没有」——那不需要任何样本量。
    """
    view = pr.analyze(FOUR[:1], {}, _market())
    assert view["position_count"] == 1
    assert view["groups"] == []
    # **这一行原来断言的是「全部押在」，而夹具里这只票只占 30%。**
    #
    # 也就是说这条测试把那个 bug 当成了正确行为：2026-08-16 线上那句
    # 「你的50% 仓位全部押在格力电器一家上」是绿着的。上面那段理由没错 ——
    # 错的是它默认「只有一只持仓」就等于「全仓」。ratio 那种记法里不等于：
    # 剩下的仓位只是**没记账**（见 test_single_position_headline.py）。
    assert "30" in view["headline"] and "全部" not in view["headline"], view["headline"]
    assert "认错条件" in view["note"], "一只票的组合里，那条件是唯一的刹车"
    assert view["single"]["name"] == "甲", "要指名道姓，不能只说「这只票」"


def test_two_positions_still_get_overlap_checked():
    """两只票之间照样可能共用行业、共用上游——那就值得说。"""
    facts = {"600001": {"sw_level1": "银行"}, "600002": {"sw_level1": "银行"}}
    view = pr.analyze(FOUR[:2], facts, _market())
    assert any(g["kind"] == "industry" for g in view["groups"])


def test_an_empty_portfolio_says_so_plainly():
    view = pr.analyze([], {}, _market())
    assert view["position_count"] == 0
    assert "还没有持仓" in view["headline"]


def test_unweighted_portfolios_never_fall_back_to_equal_weight():
    """**这是这一页最容易犯的错。**

    权重算不出来（没同步行情、账本也不是只记占比）时，按只数平均分看起来
    人畜无害，实际上会把一只 60% 的票和一只 5% 的票说成一样重——
    而"这三只占我多少仓位"正是这一页唯一有用的那个数，结论会正好反过来。
    """
    naked = [{**p, "weight": None} for p in FOUR]
    facts = {p["symbol"]: {"sw_level1": "食品饮料"} for p in naked}
    view = pr.analyze(naked, facts, _market())
    assert view["weighted"] is False
    assert "按**只数**排" in view["note"]
    assert all(group["weight"] is None for group in view["groups"]), "算不出来就是算不出来，不许凑一个数"


# ------------------------------------------------------------------ 各条重合

def test_industry_overlap_is_found_and_weighted():
    facts = {"600001": {"sw_level1": "食品饮料"}, "600002": {"sw_level1": "食品饮料"},
             "600003": {"sw_level1": "食品饮料"}, "600004": {"sw_level1": "银行"}}
    view = pr.analyze(FOUR, facts, _market())
    group = next(g for g in view["groups"] if g["kind"] == "industry")
    assert group["member_count"] == 3
    assert group["weight"] == 85.0
    assert "85" in view["headline"]


def test_the_first_industry_tier_that_speaks_wins():
    """一级已经报出来了就不再报二级——同一件事说两遍会让人不再看这一页。"""
    facts = {s: {"sw_level1": "食品饮料", "sw_level2": "白酒"} for s in
             ("600001", "600002", "600003", "600004")}
    view = pr.analyze(FOUR, facts, _market())
    tiers = {g["label"] for g in view["groups"] if g["kind"] == "industry"}
    assert len(tiers) == 1


def test_segment_overlap_is_the_one_a_broker_cannot_give_you():
    """**年报分部附注里的同名分部**——两家行业分类完全不同的公司，

    分部里都写着「光伏组件」。行业分类看不出来的东西，这里看得出来。
    而且这是真披露数据，不是推的。
    """
    facts = {
        "600001": {"sw_level1": "电力设备",
                   "segments": [{"dimension": "产品", "segment": "光伏组件", "revenue_share": 62}]},
        "600002": {"sw_level1": "机械设备",
                   "segments": [{"dimension": "产品", "segment": "光伏组件", "revenue_share": 31}]},
    }
    view = pr.analyze(FOUR, facts, _market())
    group = next(g for g in view["groups"] if g["kind"] == "segment")
    assert "光伏组件" in group["label"]
    assert "62" in group["evidence"] and "31" in group["evidence"], "占比要摆出来，不然没法判断轻重"


def test_chain_overlap_always_carries_its_confidence():
    """**产业链那张表多数是推的。**

    不写清楚的话，一条推测出来的"共同大客户"会被当成事实用来调仓。
    """
    facts = {"600001": {"chain": [{"relation": "客户", "counterpart": "宁德时代", "confidence": "待证实"}]},
             "600002": {"chain": [{"relation": "客户", "counterpart": "宁德时代", "confidence": "已证实"}]}}
    view = pr.analyze(FOUR, facts, _market())
    group = next(g for g in view["groups"] if g["kind"] == "chain")
    assert "宁德时代" in group["label"]
    assert "待证实" in group["evidence"]
    assert group["confidence"], "有一条是推的就必须提醒去核来源"


def test_confirmed_chains_do_not_nag():
    facts = {s: {"chain": [{"relation": "客户", "counterpart": "宁德时代", "confidence": "已证实"}]}
             for s in ("600001", "600002")}
    view = pr.analyze(FOUR, facts, _market())
    group = next(g for g in view["groups"] if g["kind"] == "chain")
    assert group["confidence"] == ""


def test_valuation_bands_are_judged_against_the_whole_market():
    """全市场分位，不是组合内部——组合内部永远有人在前 30%，那不叫贵。

    也不用绝对值：2015 年 40 倍是常态，2024 年 40 倍是高位，
    同一个阈值说的不是同一件事。
    """
    facts = {"600001": {"pe_ttm": 95}, "600002": {"pe_ttm": 90},
             "600003": {"pe_ttm": 88}, "600004": {"pe_ttm": 50}}
    view = pr.analyze(FOUR, facts, _market())
    group = next(g for g in view["groups"] if g["kind"] == "valuation")
    assert group["member_count"] == 3
    assert "分位" in group["evidence"]


def test_a_negative_pe_is_not_cheap():
    """负市盈率不是"便宜"，是没有 E。放进低估值那一档是纯粹的错。"""
    facts = {"600001": {"pe_ttm": -20}, "600002": {"pe_ttm": -35},
             "600003": {"pe_ttm": -8}, "600004": {"pe_ttm": -12}}
    view = pr.analyze(FOUR, facts, _market())
    assert [g for g in view["groups"] if g["kind"] == "valuation"] == []


def test_shared_wording_in_falsifiers_is_surfaced_verbatim():
    """**这是唯一一条能碰到「共同假设」的。**

    你为两家公司写的认错条件里出现同一句话，多半是因为心里想的是同一件事。
    如果它真的发生，两条判断会同时被推翻——你的认错条件本身就没有分散。

    所以要把那句话**原样抄出来**：对不对，你一眼就知道。
    """
    facts = {"600001": {"counters": ["如果新能源车渗透率见顶回落，我就错了"]},
             "600002": {"counters": ["新能源车渗透率见顶回落的话这条逻辑不成立"]}}
    view = pr.analyze(FOUR, facts, _market())
    group = next(g for g in view["groups"] if g["kind"] == "counter")
    assert "新能源车渗透率见顶回落" in group["evidence"]


def test_boilerplate_wording_is_not_reported_as_a_shared_risk():
    """「连续两期」这种结构词任何两条里都可能撞上，撞上了也说明不了什么。

    **宁可漏报也不要误报**——误报一次，下次真的撞上时你就不看了。
    """
    facts = {"600001": {"counters": ["连续两期营收下滑"]},
             "600002": {"counters": ["连续两期毛利率下滑"]}}
    view = pr.analyze(FOUR, facts, _market())
    assert [g for g in view["groups"] if g["kind"] == "counter"] == []


# ------------------------------------------------------------------ 注意力预算

def test_small_overlaps_are_counted_but_not_listed():
    """占 8% 仓位的两只票共用一个上游，出事也动不了你的本金。

    每多报一条没用的，你下次就少看一眼真正要紧的那条。
    """
    thin = [_pos("600001", "甲", 5), _pos("600002", "乙", 5),
            _pos("600003", "丙", 45), _pos("600004", "丁", 45)]
    facts = {"600001": {"sw_level1": "银行"}, "600002": {"sw_level1": "银行"}}
    view = pr.analyze(thin, facts, _market())
    assert view["groups"] == []
    assert view["hidden"] >= 1
    assert str(int(pr.MIN_WEIGHT)) in view["note"], "藏起来了要说藏了几条、门槛是多少"


def test_the_headline_names_the_single_biggest_overlap():
    facts = {s: {"sw_level1": "食品饮料"} for s in ("600001", "600002", "600003", "600004")}
    view = pr.analyze(FOUR, facts, _market())
    assert view["groups"][0]["weight"] == 100.0
    assert "食品饮料" in view["headline"]


def test_concentration_is_never_called_a_mistake():
    """跟假设漂移、决策归因同一条规矩：**陈述事实，提出问题，不下判决。**

    真懂的人本来就该集中。这一页只保证一件事：
    你是**知情地**集中，而不是以为自己分散。
    """
    facts = {s: {"sw_level1": "食品饮料"} for s in ("600001", "600002", "600003", "600004")}
    view = pr.analyze(FOUR, facts, _market())
    said = view["headline"] + view["boundary"] + "".join(g["question"] for g in view["groups"])
    for verdict in ("你错了", "太集中了", "应该分散", "风险过高", "建议减仓"):
        assert verdict not in said, f"这是判决不是事实：{verdict}"
    assert "集中不等于做错了" in view["boundary"]


def test_the_boundary_says_what_it_cannot_see():
    """查不出来的重合还有很多（同一个宏观假设、同一批基金重仓）。

    不说清楚的话，"没查出重合"会被读成"我是分散的"。
    """
    facts = {s: {"sw_level1": "银行"} for s in ("600001", "600002")}
    view = pr.analyze(FOUR, facts, _market())
    assert "宏观假设" in view["boundary"] and "这里不猜" in view["boundary"]


# ------------------------------------------------------------------ 走接口

def test_ratio_mode_positions_are_not_treated_as_closed():
    """**站主自己选的隐私口径此前是坏的。**

    ratio 口径（只记仓位占比、不落金额）下 shares 永远是 0，而"是不是还持有"
    只看 shares > 0 —— 于是一笔 30% 的持仓被划进"已清仓"，组合里一只票都不剩。
    它不报错，只是页面上空空如也，而这一整页共同风险也就无从谈起。
    """
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    portfolio = client.post("/api/v1/portfolios",
                            json={"name": "只记比例", "amount_mode": "ratio"}).json()
    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    client.post(f"/api/v1/portfolios/{portfolio['id']}/trades", json={
        "company_id": company["id"], "side": "buy", "trade_date": "2026-01-05",
        "weight_percent": 30, "rationale": "定价权"})

    detail = client.get(f"/api/v1/portfolios/{portfolio['id']}").json()
    assert detail["position_count"] == 1, "只记比例的持仓被当成已清仓了"
    assert detail["closed_positions"] == []
    assert detail["positions"][0]["weight"] == 30.0, "占比就是你自己记的那个数"


def test_the_endpoint_answers_for_a_thin_portfolio():
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    portfolio = client.post("/api/v1/portfolios", json={"name": "空组合"}).json()
    body = client.get(f"/api/v1/portfolios/{portfolio['id']}/common-risk").json()
    assert body["position_count"] == 0
    assert body["groups"] == []
    assert body["boundary"]


def test_the_endpoint_404s_on_a_missing_portfolio():
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    assert TestClient(app).get("/api/v1/portfolios/999999/common-risk").status_code == 404
