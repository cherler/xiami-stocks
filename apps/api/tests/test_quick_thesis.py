"""三十秒写下一个判断。

这个功能存在的理由是**降低摩擦**，所以测试守的也主要是摩擦：
少一步、少一个必填、少一次"先去别的地方办件事"。

唯一不肯降的是认错条件。省掉它，剩下的是一句无法被推翻的感想——
反证命中永远不会触发，复核无从谈起。**那不是少填一栏，是这条记录作废。**
"""

import pytest

from stock_decision import quick


def _history(years=6, margin_low=47.65, negatives=1):
    growth = [-1.2 if i < negatives else 12.0 for i in range(years - 1)]
    return {
        "years": [{"report_date": f"{2020 + i}-12-31"} for i in range(years)],
        "yearly_growth": growth, "margin_low": margin_low,
        "covered": 28, "window_covered": years,
    }


# ------------------------------------------------------------------ 候选

def test_suggestions_quote_the_window_not_the_whole_archive():
    """**样本量说错是最伤的一种错**，因为那句话恰恰是让人相信这个门槛的理由。

    margin_low 只统计最近几期，而完整序列有 28 期。写成「近 28 期的最低值」
    就是在说谎。
    """
    rows = quick.counter_suggestions(_history(), {})
    margin = next(r for r in rows if "净利率" in r["text"])
    assert "近 6 期" in margin["why"]
    assert "28" not in margin["why"]


def test_thresholds_come_from_the_company_itself_not_round_numbers():
    """门槛用它自己的历史值，不用一个整数。

    「净利率跌破 40%」是我在编；「跌破 47.65%（它自己最差的一年）」是它的事实。
    PE 同理——30 倍对白酒和对银行完全是两件事。
    """
    rows = quick.counter_suggestions(_history(margin_low=47.65),
                                     {"p75": 38.9}, current_pe=19.9)
    assert any("47.65%" in r["text"] for r in rows)
    pe = next(r for r in rows if "市盈率" in r["text"])
    assert "38.9" in pe["text"] and "75 分位" in pe["why"]
    assert "当前 19.9" in pe["why"]


def test_growth_condition_requires_two_periods_and_says_why():
    """单期下滑太常见，会让这条条件天天在响——所以要求连续两期，并说明它出现过几次。"""
    common = quick.counter_suggestions(_history(negatives=3), {})[0]
    assert "连续两个年度" in common["text"]
    assert "并不罕见" in common["why"]

    never = quick.counter_suggestions(_history(negatives=0), {})[0]
    assert "一次都没出现过" in never["why"]


def test_there_is_always_a_blank_one():
    """**必须留一条空的。**

    全是算出来的候选会让人以为认错条件只能是财务指标，
    而最要命的那几种（管理层换人、主业转向、监管变天）恰恰算不出来。
    """
    for history, band in ((_history(), {"p75": 38.9}), ({}, {})):
        rows = quick.counter_suggestions(history, band)
        blank = [r for r in rows if r["text"] == ""]
        assert len(blank) == 1
        assert "管理层换人" in blank[0]["why"]


def test_no_history_means_no_invented_thresholds():
    """没数据就只给那条空的，**不编一个看起来很专业的门槛**。"""
    rows = quick.counter_suggestions({}, {})
    assert [r["text"] for r in rows] == [""]


# ------------------------------------------------------------------ 那道关

def test_a_thesis_without_a_falsifier_is_refused():
    """这是唯一不肯降的摩擦。"""
    problem = quick.validate("这家公司的海外业务还能再涨三年", "")
    assert problem
    assert "无法被推翻的感想" in problem
    assert "候选" in problem, "拦住之后要告诉人下一步怎么办，不能只说不行"


def test_a_too_short_claim_is_refused():
    assert quick.validate("好", "净利率跌破 40%")


def test_a_complete_pair_passes():
    assert quick.validate("海外收入是主要增长来源", "连续两个年度营收同比下滑") == ""


def test_it_does_not_police_wording():
    """**这里是自己的记录本，不是作文课。** 只拦"没有"，不拦"写得不好"。"""
    assert quick.validate("感觉不错", "跌了我就走") == ""


# ------------------------------------------------------------------ 走接口

def test_writing_a_thesis_creates_the_company_on_the_way(monkeypatch):
    """**「先去建档」那一步就是绝大多数念头死掉的地方**，所以要把它吞掉。

    这条走 HTTP，因为省掉的正是"先调建档接口、再调写逻辑接口"这两步。
    """
    from fastapi.testclient import TestClient

    from stock_decision import repository
    from stock_decision.main import app

    monkeypatch.setattr(repository, "fetch_cn_quotes", lambda symbols: [
        {"code": "600519", "name": "贵州茅台", "price": 1309.0, "pe": 20.0,
         "pb": 7.0, "timestamp": 1785729949000, "source": "test"}])

    client = TestClient(app)
    response = client.post("/api/v1/quick-thesis", json={
        "symbol": "600519",
        "claim": "白酒的定价权还在，量减价增能撑住利润",
        "counter_condition": "连续两个年度营收同比下滑",
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_company"] is True, "没建过档的公司要顺手建出来"
    assert body["thesis_id"] and body["company_id"]
    assert body["symbol"] == "600519"

    # 第二条判断就不该再建一次档
    again = client.post("/api/v1/quick-thesis", json={
        "symbol": "600519", "claim": "渠道库存是这轮的关键变量",
        "counter_condition": "经销商数量连续两期净减少",
    })
    assert again.status_code == 201
    assert again.json()["created_company"] is False
    assert again.json()["company_id"] == body["company_id"]


def test_the_endpoint_refuses_a_thesis_with_no_falsifier():
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    response = TestClient(app).post("/api/v1/quick-thesis", json={
        "symbol": "600519", "claim": "我觉得它会涨", "counter_condition": "  "})
    assert response.status_code == 400
    assert "无法被推翻" in response.json()["detail"]


def test_context_works_for_a_company_that_was_never_filed():
    """给个代码就能开写。**要求先建档等于把摩擦又加回来了。**"""
    from fastapi.testclient import TestClient

    from stock_decision.database import connection, now_iso
    from stock_decision.main import app

    with connection() as conn:
        conn.execute("""INSERT INTO market_universe (symbol, name, exchange, board, updated_at)
                        VALUES ('000858', '五粮液', '深圳证券交易所', '主板', ?)""", (now_iso(),))

    body = TestClient(app).get("/api/v1/quick-thesis/context?symbol=000858").json()
    assert body["known"] is False
    assert body["name"] == "五粮液", "没建档也要能认出这是哪家"
    assert "自动建" in body["note"]
    assert len(body["suggestions"]) >= 1
