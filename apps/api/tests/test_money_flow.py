"""钱从哪来、去了哪：桑基图的每一根流量都要能指回一个科目。

## 为什么这张图值得做

饼图回答「构成」，桑基图回答**「流向」**。而对一份年报要问的正是流向：
赚到的钱有多少分给了你、多少投回生意里、多少趴在账上。

这件事表格里都有，只是分散在三张报表上，**而且要减一次才看得见**。
减出来那个数恰恰最要紧：2025 年茅台经营现金流 615.2 亿、分红与利息 672.4 亿、
资本开支 31.3 亿 —— 相加**超出 88.5 亿**，也就是派息动用了账上存量。
表格里要翻两页再减一次；图上是一根反向的流。

## 这个文件守的两件事

1. **倒算出来的必须标成倒算。** 图上一根「税金与其他」跟一根「营业成本」
   长得一模一样，而前者不是报表上的任何一行。不标的话，它会被当成科目去核，
   核不到，然后整张图都不敢信了。
2. **凑不齐就不画，不用零填。** 缺一个科目的桑基图会把缺口摊到别的流上 ——
   那是最难发现的一种错：图还是平的，只是有一根粗了。
"""

import pytest

from stock_decision import money_flow as mf

# 茅台 2025 年报真数据（元）。**用真数据当夹具**：编的数字凑得太整齐，
# 正好躲开「倒算那一块有多大」这种真实里最容易出问题的地方。
MAOTAI = {
    "营业成本": 148.9e8, "销售费用": 72.5e8, "管理费用": 83.2e8, "研发费用": 1.9e8,
    "经营活动产生的现金流量净额": 615.2e8,
    "分配股利、利润或偿付利息所支付的现金": 672.4e8,
    "购建固定资产、无形资产和其他长期资产所支付的现金": 31.3e8,
}
PERIOD = {"report_date": "2025-12-31", "revenue": 1720.5e8, "net_profit": 823.2e8}

# 分部附注（茅台 2025 真数据）。**这是强制披露，不是推的** —— 图的左半边靠它。
SEGMENTS = [
    {"segment": "茅台酒", "revenue": 146499906480.49},
    {"segment": "其他系列酒", "revenue": 22274678707.16},
    {"segment": "其他(补充)", "revenue": 63517327.14, "filler": True},
]


def _links(block):
    return {(l["source"], l["target"]): l for l in block["links"]}


# ------------------------------------------------------------------ 利润表那张

def test_every_node_balances():
    """**每个中转节点都必须是平的**：进来多少、出去多少。

    只算总数不够 —— 总数对而某个节点进出不等，图照样是歪的（那会画成
    一根凭空变粗或变细的带子，而人眼看不出来）。
    """
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    out_of = lambda node: sum(l["value"] for l in block["links"] if l["source"] == node)
    into = lambda node: sum(l["value"] for l in block["links"] if l["target"] == node)

    for node in ("营业总收入", "归母净利润"):
        assert abs(out_of(node) - into(node)) < 1.0, f"{node} 进出不等"
    assert abs(into("营业总收入") - PERIOD["revenue"]) < 1.0


def test_it_is_one_chart_with_sources_a_trunk_and_destinations():
    """**参考图是三列：来源 → 总收入 → 各项去处。**

    中间那一版加了「毛利」一层，使用者一眼说别扭 —— 那条又粗又灰的带子把图
    切成两半，而它不回答任何新问题（毛利率一个数就够了，不必占一列）。
    """
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    assert not any(l["target"] == "毛利" for l in block["links"]), "不该再有毛利那一层"
    into_trunk = {l["source"] for l in block["links"] if l["target"] == "营业总收入"}
    assert "茅台酒" in into_trunk, "左边要有收入来源"
    out_of_trunk = {l["target"] for l in block["links"] if l["source"] == "营业总收入"}
    assert {"营业成本", "归母净利润"} <= out_of_trunk


def test_the_profit_goes_on_to_say_how_much_reached_the_shareholder():
    """**最后一段回答的才是他最关心的**：赚的钱有多少真的到了股东手上。"""
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    tail = {l["target"]: l for l in block["links"] if l["source"] == "归母净利润"}
    assert set(tail) == {"分红与利息", "留在公司"}
    assert tail["分红与利息"]["item"] == "分配股利、利润或偿付利息所支付的现金"
    assert tail["留在公司"]["derived"] is True
    assert abs(sum(l["value"] for l in tail.values()) - PERIOD["net_profit"]) < 1.0
    # **口径搬到那一根的提示框里了**（图下面原来是三行小字，使用者说"别那么多废话"）。
    # 它不许消失 —— 只是换了个只在你看那一根时才出现的地方。
    assert "不是严格的会计勾稽" in tail["分红与利息"]["explain"], \
        "口径要说清楚：分红是现金、利润是权责发生"
    assert "上一年度" in tail["分红与利息"]["explain"]


def test_a_dividend_bigger_than_the_profit_is_not_drawn_as_coming_from_it():
    """分红超过当年净利时不画这一段 —— "从利润里分出去"这个说法本身不成立，
    而画出来的图会让人以为它成立。"""
    over = dict(MAOTAI, **{"分配股利、利润或偿付利息所支付的现金": 900.0e8})
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], over, SEGMENTS)
    assert not any(l["source"] == "归母净利润" for l in block["links"])
    assert "超过了这一期的归母净利润" in block["note"]


def test_a_token_dividend_is_said_in_words_not_drawn_as_a_hairline():
    """**小到画不出来的分红不画，但不许消失。**

    线上第一张真图（寒武纪）分红 0.04 亿、净利 20.6 亿 —— 画出来是一根
    「分红与利息 0.0 亿」的零宽线，标签还跟旁边两根叠在一起。
    而"几乎不分红"本身是个有意义的信号，所以它改成一句话说出来。
    """
    stingy = dict(MAOTAI, **{"分配股利、利润或偿付利息所支付的现金": 0.04e8})
    block = mf.income_flow(65.9e8, 20.6e8, stingy)
    assert not any(l["source"] == "归母净利润" for l in block["links"]), "零宽线不该画"
    assert "基本都留在公司里" in block["note"], "但这件事要说出来"


def test_no_dividend_line_at_all_says_so_too():
    """现金流量表里压根没有那一项时，也要说一句 —— 沉默会被读成"没分红"，
    而"没数据"和"没分红"是两回事。"""
    block = mf.income_flow(100.0, 30.0, {"营业成本": 40.0})
    assert "说不出" in block["note"]


def test_the_derived_bucket_is_marked_as_derived():
    """「税金与其他」是倒算出来的，图上必须能跟真科目区分开。"""
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    # 三根倒算：分部补差（其他业务 → 营业总收入）、税金与其他、留在公司
    derived = sorted(link["source"] + "→" + link["target"]
                     for link in block["links"] if link["derived"])
    assert derived == ["其他业务→营业总收入", "归母净利润→留在公司", "营业总收入→税金与其他"]
    assert all(link["item"] == "" for link in block["links"] if link["derived"]), \
        "倒算出来的不许挂一个科目名 —— 挂了就会有人拿它去核报表"
    # 「倒算」这个词要出现在每一根倒算流量的提示里 —— 图下面那段只留期特有的话了。
    assert all(link["explain"] for link in block["links"] if link["derived"]), \
        "倒算出来的每一根都要说得出自己是怎么减出来的"
    assert "少数股东损益" in _links(block)[("营业总收入", "税金与其他")]["explain"]


def test_every_real_flow_carries_its_line_item_name():
    """能核对是这一页存在的理由 —— 每根真流量都要带科目原名。"""
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI)
    for link in block["links"]:
        if not link["derived"]:
            assert link["item"], f"{link['target']} 这根流量没有科目名"


def test_a_tiny_line_is_merged_but_never_disappears():
    """**被并掉的小额要合成一根，不能凭空消失。**

    研发费用 1.9 亿只占 0.11%，单画是一条一像素的线，所以并进「其他费用」。
    第一版写成了"跳过不画、但算进已知" —— 结果它从图上整个不见了，
    流量合计比收入少 1.9 亿。**桑基图不平是最难发现的一种错**：
    图还是那个形状，只是有一根细了。上面那条平衡测试当场抓到了它。

    也不能并进「税金与其他」：那一块本来就是个筐，再往里塞就更说不清了。
    """
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI)
    other = next(l for l in block["links"] if l["target"] == "其他费用")
    assert abs(other["value"] - 1.9e8) < 1e6
    assert "研发费用" in other["item"], "并进去的是哪几项，要写出来"
    assert other["derived"] is False, "它是真科目的合并，不是倒算"

    tax = next(l for l in block["links"] if l["target"] == "税金与其他")
    spent = sum(v for k, v in MAOTAI.items()
                if k in ("营业成本", "销售费用", "管理费用", "研发费用"))
    assert abs(tax["value"] - (PERIOD["revenue"] - spent - PERIOD["net_profit"])) < 1.0


def test_no_revenue_means_no_chart():
    assert mf.income_flow(None, 100.0, MAOTAI) is None
    assert mf.income_flow(0.0, 100.0, MAOTAI) is None
    assert mf.income_flow(100.0, None, MAOTAI) is None


# ------------------------------------------------------------------ 现金流那张

def test_the_shortfall_becomes_an_inflow_not_a_negative_flow():
    """**这是这张图最值钱的地方。**

    派息 + 资本开支超过经营现金流时，差额只能来自账上的存量或融资。
    负流量在桑基图上画不出来，而把它藏进别的流里就等于没说 ——
    所以它是左边**一路进来的钱**。
    """
    block = mf.cash_use(MAOTAI)
    assert block["shortfall"] > 0
    links = _links(block)
    inflow = links[("动用账上存量或融资", "这一年的钱")]
    assert abs(inflow["value"] - 88.5e8) < 1e7, inflow["value"]
    assert inflow["derived"] is True
    assert "超过经营现金流" in block["note"]


def test_the_cash_chart_is_also_balanced():
    block = mf.cash_use(MAOTAI)
    into = sum(l["value"] for l in block["links"] if l["target"] == "这一年的钱")
    out = sum(l["value"] for l in block["links"] if l["source"] == "这一年的钱")
    assert abs(into - out) < 1.0, f"进 {into} ≠ 出 {out}"


def test_a_company_that_lives_within_its_means_shows_what_is_left():
    """没超支时，剩下的那块要如实画出来 —— 它是"留在账上"，同样是倒算的。"""
    thrifty = dict(MAOTAI, **{"分配股利、利润或偿付利息所支付的现金": 200.0e8})
    block = mf.cash_use(thrifty)
    assert block["shortfall"] == 0
    left = _links(block)[("这一年的钱", "留在账上")]
    assert abs(left["value"] - (615.2e8 - 200.0e8 - 31.3e8)) < 1e7
    assert left["derived"] is True
    assert "倒算" in block["note"], "「留在账上」是减出来的，图上必须说"


def test_without_the_cash_items_it_draws_nothing():
    """**凑不齐就不画。** 缺一个科目的桑基图会把缺口摊到别的流上。"""
    assert mf.cash_use({"经营活动产生的现金流量净额": 615.2e8}) is None
    assert mf.cash_use({"分配股利、利润或偿付利息所支付的现金": 100.0}) is None
    assert mf.cash_use({}) is None


def test_a_negative_operating_cash_flow_draws_nothing():
    """经营现金流是负的时候，「赚到的钱去了哪」这个问题本身就不成立。"""
    assert mf.cash_use(dict(MAOTAI, **{"经营活动产生的现金流量净额": -50.0e8})) is None


# ------------------------------------------------------------------ 合起来

def test_with_only_revenue_and_profit_it_still_draws_the_honest_two_flows():
    """**只有收入和净利也能画，而且该画。**

    我一开始以为"科目不全就该整个不画"，写了条测试要求 available=False ——
    是测试错了：收入 → 净利 + 倒算的其余，这两根流量都是成立的，
    只是薄。薄不等于假，而拒绝画会让刚同步完基础财务的人看到一片空白。
    现金流那张仍然凑不齐，如实为 None。
    """
    view = mf.build(PERIOD, {})
    assert view["available"] is True
    out_of_revenue = sum(l["value"] for l in view["income"]["links"]
                         if l["source"] == "营业总收入")
    assert out_of_revenue == pytest.approx(PERIOD["revenue"], abs=1.0)


def test_build_carries_the_chart_on_real_data():
    view = mf.build(PERIOD, MAOTAI, SEGMENTS)
    assert view["available"] is True and view["income"]
    assert view["report_date"] == "2025-12-31"
    assert "减出来的" in view["boundary"] and len(view["boundary"]) < 60, \
        "图下面那句话要短 —— 每张图上都成立的话，写长了就是每张图上都是废话"


# --------------------------------------------------- 真的走一遍数据库（上面全是纯函数）

def test_the_repository_query_actually_runs(client, owned):  # noqa: F811
    """**上面十二条一条都碰不到数据库，而线上挂掉的正是那条查询。**

    2026-08-16：`money_flow.py` 的算术全绿、部署上线，页面一打开 500 ——
    `repository.company_money_flow` 里 `report_date LIKE '%-12-31'` 的百分号
    被 psycopg2 当成占位符，报 `IndexError: tuple index out of range`，
    一个跟百分号毫无关系的错。**本会话第三次踩它。**

    纯函数测试挡不住这个：它测的是"算得对不对"，而挂掉的是"取不取得出来"。
    所以这里真的建一家公司、真的塞一期年报、真的调那个函数。
    """
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import company_money_flow

    client.as_user(access.OWNER_SCOPE)
    company = client.get(f"/api/v1/companies/{owned['company']}").json()
    symbol = company["symbol"]
    with connection() as conn:
        conn.execute(
            """INSERT INTO financial_periods (symbol, report_date, revenue, net_profit,
                                              source, refreshed_at)
               VALUES (?, '2025-12-31', ?, ?, '测试', '2026-08-16')""",
            (symbol, 1720.5e8, 823.2e8))
        for item, value in (("营业成本", 148.9e8), ("销售费用", 72.5e8),
                            ("经营活动产生的现金流量净额", 615.2e8),
                            ("分配股利、利润或偿付利息所支付的现金", 672.4e8)):
            conn.execute(
                """INSERT INTO financial_line_items (symbol, report_date, item, value,
                                                     source, refreshed_at)
                   VALUES (?, '2025-12-31', ?, ?, '测试', '2026-08-16')""",
                (symbol, item, value))

    view = company_money_flow(owned["company"])
    assert view is not None and view["available"] is True, view
    assert view["report_date"] == "2025-12-31"
    assert view["income"], view


def test_the_default_period_is_the_latest_annual_report(client, owned):  # noqa: F811
    """**季报能选，但不是默认。**

    年报是审计过的、科目最全的、跟别家可比的那一期。而季报是累计口径，
    一张「前三季度」的图跟一张「全年」的图形状一模一样 —— 默认给错了，
    看的人不会发现自己在读什么。所以默认永远是最近一期年报，哪怕库里有更新的季报。
    """
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import company_money_flow

    client.as_user(access.OWNER_SCOPE)
    symbol = client.get(f"/api/v1/companies/{owned['company']}").json()["symbol"]
    with connection() as conn:
        for report_date, revenue in (("2025-12-31", 1000.0e8), ("2026-03-31", 280.0e8)):
            conn.execute(
                """INSERT INTO financial_periods (symbol, report_date, revenue, net_profit,
                                                  source, refreshed_at)
                   VALUES (?, ?, ?, ?, '测试', '2026-08-16')""",
                (symbol, report_date, revenue, revenue * 0.3))

    view = company_money_flow(owned["company"])
    assert view["report_date"] == "2025-12-31", "默认取到季报了"
    assert [p["report_date"] for p in view["periods"]] == ["2026-03-31", "2025-12-31"], \
        "两期都该出现在可选清单里"
    picked = company_money_flow(owned["company"], "2026-03-31")
    assert picked["report_date"] == "2026-03-31", "选了季报却没给季报"
    assert picked["period_label"] == "2026 一季报" and picked["span"] == "第一季度"
    assert "累计" in picked["income"]["note"], "季报的口径必须写在图上"
    assert company_money_flow(owned["company"], "1999-12-31")["report_date"] == "2025-12-31", \
        "库里没有的期该退回默认，而不是给一张空图或者报错"


from test_idor import client, owned  # noqa: E402,F401


# ------------------------------------------------- 左半边：钱是从哪几门生意进来的

def test_segments_become_the_left_hand_side():
    """使用者给的参考图左边是「产品销售 / 服务收入 / 其他」三路收入汇进总收入。

    A 股有个现成的、**强制披露**的对应物：年报分部附注。所以这一层不用编 ——
    茅台就是「茅台酒 1465 亿 / 其他系列酒 222.7 亿」，每一根都指回分部附注。
    """
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    into = [l for l in block["links"] if l["target"] == "营业总收入"]
    assert [l["source"] for l in into][:2] == ["茅台酒", "其他系列酒"], "要按金额从大到小"
    assert all("分部附注" in l["item"] for l in into if not l["derived"])
    assert abs(sum(l["value"] for l in into) - PERIOD["revenue"]) < 1.0, "左半边也要平"


def test_the_gap_between_segments_and_revenue_is_named_and_marked():
    """分部合计通常小于营业总收入（其他业务收入、抵消项）。那个差**要有名字、
    要标成倒算** —— 一根没有出处又没有名字的流，正是这张图不该出现的东西。"""
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    gap = next(l for l in block["links"] if l["source"] == "其他业务")
    assert gap["derived"] is True
    covered = sum(s["revenue"] for s in SEGMENTS if not s.get("filler"))
    assert abs(gap["value"] - (PERIOD["revenue"] - covered)) < 1.0


def test_segments_that_do_not_add_up_are_left_out_entirely():
    """**分部只覆盖一半收入时，宁可不画这一层。**

    画出来是一张缺了一大块的图，而缺口没有名字 —— 读的人会以为那家公司
    有一半收入来路不明。让图从营业总收入开始，反而是诚实的。
    """
    half = [{"segment": "只披露了一半", "revenue": PERIOD["revenue"] * 0.5}]
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, half)
    assert not any(l["target"] == "营业总收入" for l in block["links"])


def test_without_segments_the_chart_still_works():
    """分部没同步过的公司照旧从营业总收入开始画 —— 少一层，不是不画。"""
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, None)
    assert not any(l["target"] == "营业总收入" for l in block["links"])
    assert any(l["source"] == "营业总收入" for l in block["links"])


# 格力电器 2025 年报的真数据（元）。**留着当夹具**：这一组的覆盖率是 0.8987，
# 刚好卡在 0.9 那条线下面 0.13 个百分点 —— 编不出这么巧的数。
GREE_REVENUE = 171118161275.41
GREE_SEGMENTS = [
    {"segment": "消费电器", "revenue": 133055208627.13},
    {"segment": "工业制品及绿色能源", "revenue": 17380701260.95},
    {"segment": "其他(补充)", "revenue": 16665086190.11, "filler": True},
    {"segment": "其他", "revenue": 2665271980.81},
    {"segment": "智能装备", "revenue": 680790474.57},
]


def test_the_filler_row_counts_toward_coverage():
    """**数据源补的差额行也是收入，算覆盖率时不能剔掉。**

    格力 2025：主营分部合计 1537.8 亿，营业总收入 1711.2 亿，
    剔掉「其他(补充)」之后是 **0.8987** —— 比 0.9 这条线低 0.13 个百分点，
    整个左半边被判"凑不齐"而不画。页面上是一片空白，
    而空白说不出自己是"没数据"还是"被判掉了"。使用者截图圈的就是这块。

    把补充行算回去是 0.996，正常画。它本身不画成一个分部，并进「其他业务」。
    """
    block = mf.income_flow(GREE_REVENUE, 29003103411.66, MAOTAI, GREE_SEGMENTS)
    into = [l for l in block["links"] if l["target"] == "营业总收入"]
    assert into, "左半边没画出来 —— 覆盖率又把补充行剔掉了"
    assert [l["source"] for l in into][:2] == ["消费电器", "工业制品及绿色能源"]
    assert "其他(补充)" not in [l["source"] for l in into], "补充行不是一门生意，不该单画"
    assert abs(sum(l["value"] for l in into) - GREE_REVENUE) < 1.0, "左半边要平"


def test_what_got_merged_into_the_other_bucket_is_spelled_out():
    """并进「其他业务」的东西**要说得出是些什么**，否则那一根 180 亿的流没有出处。

    说明走 `explain` 不走 `item`：item 是拿来核年报的，里面只能有科目原名。
    """
    block = mf.income_flow(GREE_REVENUE, 29003103411.66, MAOTAI, GREE_SEGMENTS)
    other = next(l for l in block["links"] if l["source"] == "其他业务")
    assert other["derived"] is True and other["item"] == ""
    assert "智能装备" in other["explain"], "0.4% 的智能装备被并掉了，得说一声"


def test_the_profit_link_is_drawn_first_so_it_does_not_cross():
    """**归母净利润要排在第一根。**

    桑基图的上下次序跟着 links 的次序走，而每一列都从顶上开始摆。净利润后面还接着
    分红那两根，最后一列只有它们 —— 所以它们必然在最上面。净利润排在费用之后的话，
    那条绿带子要从图的底部一路兜到右上角，横穿整张图。使用者截图圈的就是这个交叉。
    """
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    out = [l["target"] for l in block["links"] if l["source"] == "营业总收入"]
    assert out[0] == "归母净利润", f"净利润那根没排在最前：{out}"
    assert out[-1] == "税金与其他", f"倒算出来的那根该收在费用那一摞末尾：{out}"


def test_a_missing_left_hand_side_says_why():
    """左边没画的时候得说得出为什么 —— 一片空白说不出自己是"没数据"还是"被判掉了"，
    而这两件事该点的按钮完全不一样。"""
    none = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, None)
    # **不靠一句指路，靠一个当场能按的按钮。**
    #
    # 这句话经历过两版都是错的：先写「点一次同步财务数据」（分部根本不走那个按钮），
    # 改成「到主营构成点一次同步主营构成」，而那块面板在**产业链页签**里 ——
    # 使用者的回应是「哪里有这个按钮？我就没看到」。
    # 现在图旁边直接给按钮，note 只负责说明缺的是什么；left_fix 决定画不画按钮。
    assert "分部附注" in none["note"]
    assert none["left_fix"] == "syncable", "缺分部数据时要能当场补上"
    assert "同步财务数据" not in none["note"], "指错按钮，照着点一百次也不会有"

    # 季报的缺口补不上（一季报三季报本来就没有分部附注），不许画那个按钮
    q3 = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, span="前三季度累计")
    assert q3["left_fix"] == "", "画一个按不出结果的按钮，比不画更糟"

    half = [{"segment": "只披露了一半", "revenue": PERIOD["revenue"] * 0.5}]
    thin = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, half)
    assert "50%" in thin["note"], thin["note"]
    assert thin["left_fix"] == "", "取过了但对不上，再点一次还是这个结果"


def test_segments_from_another_year_are_not_used(client, owned):  # noqa: F811
    """**分部停在 2024、利润表已经到 2025 的时候，不许拿去年的分部分今年的收入。**

    两张表不是一起同步的，而各自都取"最近一期年报"。错配之后加起来照样接近、
    覆盖率照样过 —— 画出来是一张看不出错的错图。
    """
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import company_money_flow

    client.as_user(access.OWNER_SCOPE)
    symbol = client.get(f"/api/v1/companies/{owned['company']}").json()["symbol"]
    with connection() as conn:
        conn.execute(
            """INSERT INTO financial_periods (symbol, report_date, revenue, net_profit,
                                              source, refreshed_at)
               VALUES (?, '2025-12-31', ?, ?, '测试', '2026-08-16')""",
            (symbol, 1000.0e8, 300.0e8))
        for segment, revenue in (("甲业务", 700.0e8), ("乙业务", 290.0e8)):
            conn.execute(
                """INSERT INTO business_segments (symbol, report_date, dimension, segment,
                                                  revenue, revenue_share, updated_at)
                   VALUES (?, '2024-12-31', '产品', ?, ?, 0, '2026-08-16')""",
                (symbol, segment, revenue))

    view = company_money_flow(owned["company"])
    into = [l for l in view["income"]["links"] if l["target"] == "营业总收入"]
    assert not into, "用了 2024 的分部去分 2025 的收入"


# --------------------------------------------------- 亏损的那些期（一开放选期就撞上）

# 寒武纪 2024 年报真数据（元）。收入 11.7 亿，四项费用合计 19.7 亿。
CAMBRICON_2024 = {
    "营业成本": 5.1e8, "销售费用": 0.7e8, "管理费用": 1.8e8, "研发费用": 12.2e8,
}


def test_a_loss_period_still_balances():
    """**桑基图画不出负的流量，而不平的桑基图看不出来。**

    寒武纪 2024：收入 11.7 亿，四项费用加起来 19.7 亿。照原来的画法，
    营业总收入这个节点进 11.7、出 19.7 —— 图还是那个形状，只是有一根凭空变粗了。
    这个错在只画最近一期年报时藏着（这些公司 2025 都赚钱），
    **一开放选期就撞上**：寒武纪九期里八期是亏的。
    """
    block = mf.income_flow(11.7e8, -4.5e8, CAMBRICON_2024)
    out_of = lambda node: sum(l["value"] for l in block["links"] if l["source"] == node)
    into = lambda node: sum(l["value"] for l in block["links"] if l["target"] == node)

    # **先证明有东西可查。** 第一版只写了下面那个循环，而在坏行为下中转节点
    # 一个都没有（图退化成一层扇形），循环体一次都不跑 —— 变异测试里它是绿的。
    # 又一次：**守卫在它要守的那件事上正好是瞎的。**
    middles = {l["target"] for l in block["links"]} & {l["source"] for l in block["links"]}
    assert middles, "一个中转节点都没有，图退化成一层扇形了 —— 下面的检查会全部落空"
    for node in middles:
        assert abs(into(node) - out_of(node)) < 1.0, f"{node} 进出不等，图是歪的"

    # 真正被踩的那条：营业总收入流出去的总额不许超过年报上那个数。
    assert out_of("营业总收入") - 11.7e8 < 1.0, (
        f"营业总收入进 11.7 亿、出 {out_of('营业总收入') / 1e8:.1f} 亿 —— "
        f"图还是那个形状，只是有一根凭空变粗了")


def test_the_shortfall_comes_in_from_the_left_and_says_so():
    """差额当成一路进来的钱画在左边 —— 跟 `cash_use()` 对付派息缺口是同一招。
    藏进别的流里就等于没说，而说出来它本身就是这一期最要紧的一件事。"""
    block = mf.income_flow(11.7e8, -4.5e8, CAMBRICON_2024)
    gap = next(l for l in block["links"] if l["source"] == "收入不够的部分")
    assert gap["derived"] is True and gap["item"] == ""
    assert abs(gap["value"] - 8.1e8) < 0.2e8, gap["value"]
    assert "支出比收入多" in block["note"] and "-4.5 亿" in block["note"]
    assert not any(l["target"] == "归母净利润" for l in block["links"]), \
        "净利润是负的，不许画成一根从主干里分出去的流"


def test_the_trunk_is_renamed_when_it_is_no_longer_just_revenue():
    """主干上进来的钱已经不只是营业总收入了，**名字就不能再叫营业总收入** ——
    节点标签上写的是它的吞吐量，写着「营业总收入 19.7 亿」而年报上是 11.7 亿，
    那是一个能被当场核错的数。"""
    block = mf.income_flow(11.7e8, -4.5e8, CAMBRICON_2024)
    assert any(l["target"] == "这一期的钱" for l in block["links"])
    revenue_in = next(l for l in block["links"] if l["source"] == "营业总收入")
    assert abs(revenue_in["value"] - 11.7e8) < 1.0, "营业总收入这一根必须还是年报上那个数"


def test_a_loss_that_does_not_exceed_revenue_needs_no_extra_inflow():
    """亏在减值、财务费用这些图上没画的科目里时，四项费用还没到收入 ——
    这时候不该凭空多一路进项，但**亏损这件事仍然要说**。"""
    block = mf.income_flow(100e8, -3e8, {"营业成本": 60e8, "销售费用": 5e8})
    assert not any(l["source"] == "收入不够的部分" for l in block["links"])
    assert not any(l["target"] == "归母净利润" for l in block["links"])
    assert "-3.0 亿" in block["note"] and "税金与其他" in block["note"]


def test_the_period_kind_is_never_left_unsaid():
    """**四种期画出来长得一模一样。** 把三季报当年报读，后面每一个结论都是错的，
    所以口径必须出现在图上，而且排在最前面。"""
    assert mf.period_label("2025-09-30") == "2025 三季报"
    assert mf.period_span("2025-09-30") == "前三季度累计"
    assert mf.period_label("2025-06-30") == "2025 中报"
    assert mf.period_label("2025-03-31") == "2025 一季报"
    assert mf.period_label("2025-12-31") == "2025 年报"
    # 认不出来的日期原样返回，不猜
    assert mf.period_label("2025-08-15") == "2025-08-15"

    interim = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI,
                             span="前三季度累计")
    assert interim["note"].startswith("**这是前三季度累计的数**")
    annual = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI)
    assert "累计" not in annual["note"].split("。")[0], "年报不该被扣一顶累计的帽子"


def test_the_extra_inflow_is_not_called_a_loss_when_the_period_made_money():
    """**图上唯一一句会骗人的话。**

    寒武纪 2025：收入 65.0 亿，四项费用加归母净利润 65.9 亿 —— 差 0.9 亿。
    这 0.9 亿是投资收益、其他收益、利息收入，不是亏损；而这一期公司赚了 20.6 亿。
    第一版把它写成「收入不够的部分 · 差额来自这一期的亏损」，
    对一家当年赚钱的公司说它在亏。
    """
    block = mf.income_flow(65.0e8, 20.6e8,
                           {"营业成本": 29.1e8, "销售费用": 0.7e8,
                            "管理费用": 2.0e8, "研发费用": 13.5e8})
    extra = next(l for l in block["links"] if l["target"] == "这一期的钱" and l["derived"])
    assert extra["source"] == "收入以外的进项", extra["source"]
    assert "亏损" not in extra["explain"] and "亏损" not in block["note"]
    assert "投资收益" in block["note"]
    # 赚钱的那一期照样有净利润那一路
    assert any(l["target"] == "归母净利润" for l in block["links"])


def test_a_normal_profitable_year_is_left_exactly_as_it_was():
    """茅台、格力这种正常年份**一根流量都不该变** —— 上面那套只在差额为负时才启用。
    使用者已经看过并认可了那张图，改动不许溢出到它身上。"""
    block = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI, SEGMENTS)
    assert not any(l["target"] == "这一期的钱" for l in block["links"]), "主干被改名了"
    assert {l["source"] for l in block["links"] if l["target"] != "营业总收入"} == {"营业总收入", "归母净利润"}


# ------------------------------------------- 银行与保险：另一套利润表科目

# 中国平安 2025 三季报的真形态：营业总收入 10505.1 亿、归母净利 1583.0 亿，
# 而**利润表上没有营业成本** —— 四项通用费用一个都取不到。
PINGAN_REVENUE = 10505.1e8
PINGAN_PROFIT = 1583.0e8


def test_a_bucket_holding_85_percent_of_revenue_is_not_called_tax():
    """**这张图上唯一一句彻底的假话。**

    照制造业那套画中国平安：四项费用一个都没有，于是 8922 亿（收入的 85%）
    塞进一个叫「税金与其他」的桶 —— 而那 8922 亿实际上是赔付支出、退保金、
    提取保险责任准备金。画不出来不丢人，把赔付支出叫成税才丢人。
    """
    block = mf.income_flow(PINGAN_REVENUE, PINGAN_PROFIT, {})
    residual = next(l for l in block["links"] if l["derived"] and l["target"] != "留在公司")
    assert residual["target"] == "没拆开的支出", residual["target"]
    assert "不是税" in block["note"] and "同步财务数据" in block["note"]


def test_the_biggest_flow_may_never_be_the_derived_one():
    """判据不是「拆出来的要占收入几成」—— 那条误伤茅台（毛利率 93%，四项成本
    只占收入 18%，而那张图是对的）。判据是**倒算出来的那一根不许是最粗的一根**：
    最大的一笔钱去了哪都说不出，就是没有拆开过。"""
    # 只匹配到一项 10 亿的费用 —— 剩下 8912 亿仍然是最粗的，判定没拆开
    thin = mf.income_flow(PINGAN_REVENUE, PINGAN_PROFIT, {"管理费用": 10e8})
    assert any(l["target"] == "没拆开的支出" for l in thin["links"])
    # 茅台：剩下 590.8 亿，而归母净利润 823.2 亿比它大 → 正常画
    good = mf.income_flow(PERIOD["revenue"], PERIOD["net_profit"], MAOTAI)
    assert not any(l["target"] == "没拆开的支出" for l in good["links"])
    assert any(l["target"] == "税金与其他" for l in good["links"])


def test_the_cost_set_is_picked_from_the_data_not_from_an_industry_label():
    """行业分类要么靠一张会过期的表，要么靠模型判断。**而利润表自己就说了答案。**"""
    insurer = {"赔付支出": 3200e8, "退保金": 900e8, "提取保险责任准备金": 2100e8,
               "手续费及佣金支出": 600e8, "业务及管理费": 1400e8,
               "营业税金及附加": 80e8, "营业支出": 8280e8}
    kind, _ = mf.pick_outflows(insurer)
    assert kind == "保险"
    block = mf.income_flow(PINGAN_REVENUE, PINGAN_PROFIT, insurer)
    drawn = [l["target"] for l in block["links"] if l["source"] == "营业总收入"]
    assert "赔付支出" in drawn and "退保金" in drawn
    assert "支出按**保险**的科目拆" in block["note"]

    assert mf.pick_outflows({"营业成本": 100e8, "管理费用": 3e8})[0] == "一般企业"
    assert mf.pick_outflows({"业务及管理费用": 1800e8, "信用减值损失": 1500e8})[0] == "银行"


def test_double_counting_is_caught_by_the_reported_total():
    """**银行的营业收入已经是净额**（利息净收入 + 手续费净收入 + …），
    支出侧再减一次利息支出就是重复扣 —— 而那样画出来图还是平的，只是每一根都偏。
    这种错自己不会暴露，所以拿报表上的「营业支出」对一下。"""
    wrong = {"业务及管理费用": 1800e8, "信用减值损失": 1500e8, "营业税金及附加": 90e8,
             "营业支出": 9000e8}          # 拆出来 3390，报表说 9000 —— 差太多
    block = mf.income_flow(PINGAN_REVENUE, PINGAN_PROFIT, wrong)
    assert any(l["target"] == "没拆开的支出" for l in block["links"]), \
        "对不上就该说没拆开，而不是画一张每根都偏的图"


def test_the_whitelist_uses_the_real_column_names():
    """**白名单里的名字对不上，一行都取不到，而它长得跟"这家公司没有这个科目"
    一模一样。** 上一版凭印象写的「净利息收入」「客户存款(吸收存款)」线上零命中。

    这几个是 2026-08-17 照着 `stock_financial_report_sina` 的真实列名抄的。
    """
    from stock_decision.providers.akshare_financial import LINE_ITEMS

    income = set(LINE_ITEMS["利润表"])
    for name in ("业务及管理费", "业务及管理费用", "营业税金及附加", "营业支出",
                 "退保金", "赔付支出", "提取保险责任准备金", "手续费及佣金支出"):
        assert name in income, f"{name} 不在白名单里，取不到就画不出金融股的支出"
    # 每一套支出口径用到的科目都必须在白名单里 —— 否则那一套永远匹配不上
    for kind, spec in mf._OUTFLOW_SETS:
        for key, _ in spec:
            assert key in income, f"{kind} 那套用到的「{key}」不在白名单里，取不到"
