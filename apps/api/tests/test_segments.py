"""主营构成：这家公司靠什么赚钱。

**产业链那一页原来只有推断，没有事实。** 16 条关系全部标着「待证实」、
0 条确认过——一个业余投资者看完之后，对"钱从哪来"的了解并没有增加。
而年报的分部附注是披露过的：茅台酒占收入 86.8%、毛利率 93.5%；
工行的资金业务只占收入 11.2%，毛利率却是 75.7%（三块业务里最高的）。

所以这里测的重点是那两个会让人读错的地方：
只看占比会漏掉"小块高毛利"，以及数据源补的差额行不能被当成业务分部。
"""

import pytest

from stock_decision import repository
from stock_decision.database import connection, now_iso
from stock_decision.providers.akshare_segments import FILLER
from stock_decision.schemas import CompanyInput


def _company(symbol: str = "600519", name: str = "贵州茅台") -> int:
    return repository.create_company(
        CompanyInput(symbol=symbol, name=name, industry="白酒"))["id"]


def _seed(symbol: str, report_date: str, rows: list[tuple[str, str, float, float]]) -> None:
    """(口径, 分部, 收入占比, 毛利率)"""
    with connection() as conn:
        for dimension, segment, share, margin in rows:
            conn.execute(
                """INSERT INTO business_segments (symbol, report_date, dimension, segment,
                       revenue, revenue_share, cost, profit, profit_share, gross_margin, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, report_date, dimension, segment, share * 1e8, share,
                 None, None, None, margin, now_iso()))


def test_a_small_segment_can_carry_the_best_margin():
    """只看占比会漏掉这件事——工行资金业务占 11%，毛利率却是三块里最高的。"""
    company_id = _company("601398", "工商银行")
    _seed("601398", "2025-12-31", [
        ("产品", "公司金融业务", 48.99, 50.31),
        ("产品", "个人金融业务", 39.10, 43.26),
        ("产品", "资金业务", 11.21, 75.68),
    ])

    view = repository.business_segments(company_id)
    items = view["dimensions"][0]["items"]

    biggest = max(items, key=lambda i: i["revenue_share"])
    fattest = max(items, key=lambda i: i["gross_margin"])
    assert biggest["segment"] != fattest["segment"], "这一例的意义就在于两者不是同一块"
    # 两个数都要在返回里 —— 少任何一个，页面就只能给出一半的结论
    assert all(i["revenue_share"] is not None and i["gross_margin"] is not None for i in items)


def test_the_filler_row_is_kept_but_marked():
    """数据源补的差额行要留下，但要标出来。

    丢掉的话各块占比加起来不等于 100%，看图的人会以为我们算错了；
    不标的话它会被当成一个业务分部读。
    """
    company_id = _company()
    _seed("600519", "2025-12-31", [
        ("产品", "茅台酒", 86.77, 93.53),
        ("产品", "其他系列酒", 13.19, 76.11),
        ("产品", FILLER, 0.04, -35.99),
    ])

    items = repository.business_segments(company_id)["dimensions"][0]["items"]

    filler = [i for i in items if i["filler"]]
    assert len(filler) == 1 and filler[0]["segment"] == FILLER
    assert sum(i["revenue_share"] for i in items) == pytest.approx(100, abs=0.1)


def test_only_the_annual_report_is_used():
    """半年报也有分部构成，但它跟年报不可比。

    累计口径加上季节性，把两者放进同一张构成图，看到的变化多半是日历造成的。
    """
    company_id = _company()
    _seed("600519", "2025-12-31", [("产品", "茅台酒", 86.8, 93.5)])
    _seed("600519", "2026-06-30", [("产品", "茅台酒", 91.2, 94.1)])

    view = repository.business_segments(company_id)

    assert view["report_date"] == "2025-12-31"


def test_never_synced_says_what_to_do():
    company_id = _company()

    view = repository.business_segments(company_id)

    assert view["dimensions"] == []
    assert "同步" in view["boundary"]


def test_the_api_hands_back_the_segments():
    """走一趟 HTTP。响应模型没声明的字段会被静默丢掉——今天已经因此白屏过一次。"""
    import asyncio

    from tests.test_api import request

    company_id = _company()
    _seed("600519", "2025-12-31", [("产品", "茅台酒", 86.77, 93.53)])

    payload = asyncio.run(request("GET", f"/api/v1/companies/{company_id}/segments")).json()

    assert payload["dimensions"][0]["items"][0]["gross_margin"] == 93.53
