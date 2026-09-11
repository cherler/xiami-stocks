"""同业对照：比较对象必须是全市场同行，不是自己关注的那几家。

原来这张表比的是**研究池里恰好同行业的公司**。茅台旁边可能只站着一家洋河，
也可能一家都没有——比出来的高低完全取决于我自己加了谁。
样本是自己挑的，结论就没有意义。
"""

import pytest

from stock_decision import peers
from stock_decision.database import connection, now_iso


def _seed(rows: list[tuple[str, str, str, float, float]]) -> None:
    """(代码, 名称, 行业, 总市值, pe)"""
    with connection() as conn:
        for symbol, name, industry, cap, pe in rows:
            conn.execute(
                """INSERT INTO market_universe (symbol, name, industry, total_market_cap,
                       pe_ttm, pb, roe, gross_margin, revenue_growth, net_profit_growth,
                       dividend_yield, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, name, industry, cap, pe, 2.0, 10.0, 40.0, 5.0, 6.0, 2.0, now_iso()))


def test_peers_come_from_the_whole_market():
    """同行取自全市场底座，跟研究池里有没有建档无关。"""
    _seed([(f"6001{i:02d}", f"同行{i}", "白酒Ⅱ", (20 - i) * 1e10, 20.0 + i) for i in range(18)])
    _seed([("600519", "贵州茅台", "白酒Ⅱ", 1.6e12, 19.9)])

    view = peers.table({"symbol": "600519", "industry": "酒、饮料和精制茶制造业"})

    assert view["industry"] == "白酒Ⅱ", "应当用底座里更细的行业口径，不是档案里的证监会门类"
    assert view["total"] == 19
    assert len(view["rows"]) == peers._TABLE_LIMIT


def test_the_company_itself_is_always_in_the_table():
    """排不进前 12 也要在表里——这张表是给它当参照的，主角不在场就白做了。"""
    _seed([(f"6001{i:02d}", f"大厂{i}", "白酒Ⅱ", (30 - i) * 1e11, 20.0) for i in range(20)])
    _seed([("600519", "小酒厂", "白酒Ⅱ", 1e8, 19.9)])          # 市值最小，排最后

    view = peers.table({"symbol": "600519", "industry": "白酒Ⅱ"})

    assert any(r["is_self"] for r in view["rows"]), "本公司被截断掉了"
    assert len(view["rows"]) <= peers._TABLE_LIMIT


def test_the_median_is_over_the_whole_industry_not_the_visible_rows():
    """表是按市值截断过的，拿截断后的样本算中位数会系统性偏向大公司。

    人看表时会不自觉地拿「表里这些」当成「行业整体」，所以中位数必须是全行业的。
    """
    # 前 12 家 PE 都是 50，剩下 20 家都是 10 —— 全行业中位数应当靠近 10，而不是 50
    _seed([(f"6001{i:02d}", f"大厂{i}", "银行Ⅱ", (40 - i) * 1e11, 50.0) for i in range(12)])
    _seed([(f"6002{i:02d}", f"小行{i}", "银行Ⅱ", 1e9, 10.0) for i in range(20)])

    view = peers.table({"symbol": "600100", "industry": "银行Ⅱ"})

    assert view["median"]["pe_ttm"] == pytest.approx(10.0, abs=0.1), (
        f"中位数 {view['median']['pe_ttm']} 像是只按表里那 12 家算的")


def test_a_company_outside_the_universe_says_what_to_do():
    view = peers.table({"symbol": "999999", "industry": ""})

    assert view["rows"] == []
    assert "同步" in view["note"]
