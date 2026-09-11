"""深度研究报告：数字归代码、判断归模型，引用要指得到。

原来那份"乏善可陈"是结构决定的：它只复述已归档的证据，而归档的多半是公告
标题——没有任何档案之外的信息，只是把你看过的东西重新排了一遍。

现在联网找资料，但**数字仍然不从网上取**。网页上的财务数字经常过期、口径
不同，或者是别人抄错的；库里那份是同步来的。让模型从网页里抄数字，等于把
最容易错、后果最严重的一步交给它。
"""

import pytest

from stock_decision import deep_report


COMPANY = {"name": "贵州茅台", "symbol": "600519", "industry": "酒、饮料和精制茶制造业",
           "universe_industry": "白酒Ⅱ"}
FACTS = {
    "segments": {"report_date": "2025-12-31", "dimensions": [
        {"key": "产品", "items": [
            {"segment": "茅台酒", "revenue_share": 86.77, "gross_margin": 93.53, "filler": False},
            {"segment": "其他(补充)", "revenue_share": 0.04, "gross_margin": -36.0, "filler": True}]}]},
    "peers": {"industry": "白酒Ⅱ", "peers": 19, "metrics": [
        {"label": "市盈率 TTM", "value": 19.9, "unit": "倍", "percentile": 40, "p50": 22.87}]},
    "financials": [{"report_date": "2025-12-31", "revenue": 1.7205e11,
                    "net_profit": 8.232e10, "operating_cash_flow": 6.152e10, "net_margin": 47.8}],
}
HITS = [{"kind": "一手", "title": "一季度经营数据公告", "snippet": "直销占比 54.75%",
         "url": "https://www.moutaichina.com/a", "published": "2026-04-27"}]
LOCAL = [{"source_name": "巨潮公告", "excerpt": "分红方案", "occurred_at": "2026-06-01",
          "url": "", "evidence_id": 7}]


def _fake_model(monkeypatch, payload: str):
    class _Completion:
        text = payload
    monkeypatch.setattr(deep_report.llm, "call", lambda *a, **k: _Completion())
    monkeypatch.setattr(deep_report, "ai_available", lambda: (True, ""))


def test_the_industry_query_uses_the_finer_classification():
    """档案里写的是「酒、饮料和精制茶制造业」——拿它去搜，搜回来的是饮料和茶叶。

    底座里是「白酒Ⅱ」，那才是这家公司真正的竞争场。
    """
    queries = deep_report.build_queries(COMPANY)

    assert any("白酒Ⅱ" in q for q in queries)
    assert not any("精制茶" in q for q in queries)


def test_local_numbers_reach_the_prompt(monkeypatch):
    """主营构成、同行位置、历年年报要摆在模型面前，并写明它们的地位。"""
    seen: dict[str, str] = {}

    class _Completion:
        text = '{"headline": "x", "cards": [], "sections": [], "themes": [], "unknowns": []}'

    def capture(system, user, **kwargs):
        seen["prompt"] = user
        return _Completion()

    monkeypatch.setattr(deep_report.llm, "call", capture)
    monkeypatch.setattr(deep_report, "ai_available", lambda: (True, ""))
    deep_report.compose(COMPANY, HITS, LOCAL, FACTS)

    prompt = seen["prompt"]
    assert "唯一可信的数字" in prompt, "没告诉模型这批数字的地位"
    assert "86.77" in prompt and "93.53" in prompt          # 主营构成
    assert "第 40 分位" in prompt                            # 同行位置
    assert "1720.5" in prompt                                # 历年年报，换算成亿元


def test_the_filler_row_is_not_fed_as_a_business_segment(monkeypatch):
    """数据源补的差额行不是业务分部，不该当成一块业务讲给模型听。"""
    seen: dict[str, str] = {}

    class _Completion:
        text = '{"headline": "x", "cards": [], "sections": [], "themes": [], "unknowns": []}'

    monkeypatch.setattr(deep_report.llm, "call",
                        lambda s, u, **k: seen.update(prompt=u) or _Completion())
    monkeypatch.setattr(deep_report, "ai_available", lambda: (True, ""))
    deep_report.compose(COMPANY, HITS, LOCAL, FACTS)

    assert "其他(补充)" not in seen["prompt"]


def test_source_grading_is_handed_to_the_model(monkeypatch):
    """不把分级告诉模型，它会把股吧里的一句话跟年报里的一句话放在同一个位置上。"""
    seen: dict[str, str] = {}

    class _Completion:
        text = '{"headline": "x", "cards": [], "sections": [], "themes": [], "unknowns": []}'

    monkeypatch.setattr(deep_report.llm, "call",
                        lambda s, u, **k: seen.update(prompt=u) or _Completion())
    monkeypatch.setattr(deep_report, "ai_available", lambda: (True, ""))
    deep_report.compose(COMPANY, HITS, LOCAL, FACTS)

    assert "（一手｜" in seen["prompt"]
    assert "（本地已归档｜" in seen["prompt"]


def test_an_out_of_range_reference_is_dropped(monkeypatch):
    """越界的编号丢掉，**不猜**。

    猜错会把一条结论挂到另一份资料上，而读的人点开才发现对不上——
    那比没有引用更糟：它看起来是有据可依的。
    """
    _fake_model(monkeypatch, """{"headline": "x",
      "cards": [{"title": "卡", "point": "话", "refs": [1, 99, "乱写"]}],
      "sections": [], "themes": [], "unknowns": []}""")

    report = deep_report.compose(COMPANY, HITS, LOCAL, FACTS)     # 共 2 条资料

    assert report["cards"][0]["refs"] == [1]


def test_an_invented_direction_falls_back_to_neutral(monkeypatch):
    """模型偶尔会写「偏正面」——那是它自己发明的档位，
    收进来图上就会多出一个谁也不知道该画多深的颜色。"""
    _fake_model(monkeypatch, """{"headline": "x", "cards": [], "sections": [],
      "themes": [{"name": "渠道", "direction": "偏正面", "refs": [1]}], "unknowns": []}""")

    report = deep_report.compose(COMPANY, HITS, LOCAL, FACTS)

    assert report["themes"][0]["direction"] == "中性"


def test_no_sources_means_no_report(monkeypatch):
    """既没检索到、本地也没有，就该明说写不出，而不是让模型自由发挥。"""
    _fake_model(monkeypatch, "{}")

    with pytest.raises(RuntimeError, match="写不出报告"):
        deep_report.compose(COMPANY, [], [], FACTS)


def test_the_estimate_is_given_before_spending():
    """花钱的事要在点之前知道，不是点完看账单。"""
    plan = deep_report.estimate(COMPANY)

    assert plan["searches"] == len(plan["queries"])
    assert plan["credits"] > 0
    assert plan["note"]


# --------------------------------------------------------------- 联网搜索的计费

def test_the_quote_is_computed_not_hardcoded():
    """**报价原来是写死的 `"credits": 3`**，而旁边那句「大约 3 个积分」
    让它看起来像算出来的。

    实测一份搜 5 次的报告实扣 3 分，而公式该收 9 分——少的 6 分正好是搜索那一项。
    """
    from stock_decision.llm import credits_for_report

    assert credits_for_report(5, 9000) == 9
    assert credits_for_report(0, 9000) == 2, "不搜的时候只按 token 收"
    # 搜得越多越贵，这是这条公式存在的全部意义
    assert credits_for_report(8, 9000) > credits_for_report(5, 9000)


def test_the_coefficient_matches_the_main_site():
    """**stock-lab 这份系数是给"事前报价"用的，主站那份才真扣钱。**

    两处不一致的后果很安静：页面上报 8 分、实扣 9 分，
    没有任何地方会报错，而使用者会觉得这个产品在偷偷多收。

    主站的值在 tools-backend/app/pricing.py:SEARCH_COEFF，线上 .env 设为 1.25。
    改任何一边都要同时改另一边——这条断言就是那个提醒。
    """
    from stock_decision.llm import SEARCH_CREDIT_COEFF

    assert SEARCH_CREDIT_COEFF == 1.25


def test_searches_reach_the_credit_gate(monkeypatch):
    """**搜索次数要真的送到闸口**，不然公式再对也收不到钱。"""
    from stock_decision import llm

    sent = {}

    def _fake_reserve(module, task, estimated_tokens, searches=0):
        sent["searches"] = searches
        return llm.Meter(module=module, task=task)

    monkeypatch.setattr(llm, "reserve", _fake_reserve)
    monkeypatch.setattr(llm, "load_env", lambda: {
        "MINIMAX_API_KEY": "k", "MINIMAX_BASE_URL": "http://x", "MINIMAX_MODEL": "m",
        "XM_CREDIT_MODULE": "stocks"})
    try:
        llm.call("sys", "user", task="deep-report", searches=5)
    except Exception:
        pass                      # 网络必然失败，这里只看有没有把次数传下去
    assert sent.get("searches") == 5
