"""点「只看实质」，看到的就该是实质变化 —— 而不是一堆还没分级的。

2026-08-19 线上实测（测试账号，待核验 / 近 90 天）：

    relevance=高 → 返回 14 条，**全部是未分级的**
    relevance=低 → 返回同样那 14 条
    摘要字段     → high=0、medium=3、low=0

两个互斥的筛选给出一模一样的结果，而正确答案是两边都 0 条。
根因是那句 WHERE 一律带着 `relevance IS NULL OR` —— 它是为默认视图加的
（新进来的公告在被分级之前谁都看不见），但用户显式选等级时不该再生效。

**接口返回 200、字段也齐全，坏的是"筛出来的东西对不对"。**
状态码和页面扫描都测不出这一类，只能拿数据本身对。
"""
from __future__ import annotations

import pytest

from stock_decision import repository


@pytest.fixture()
def inbox_with_mixed_grades() -> None:
    """造四条待核验：高 / 中 / 低 / 还没分级。

    直接写表 —— 跟 test_counter_hits 里同一个写法。收件箱条目在
    company_calendar_events，走 create_event 进的是另一张表。
    """
    from stock_decision.database import connection, now_iso
    from stock_decision.schemas import CompanyInput

    company = repository.create_company(
        CompanyInput(symbol="600519", name="测试公司", industry="白酒"))
    rows = [("高", "重大合同落地"), ("中", "股东会决议"),
            ("低", "更换会计师"), (None, "还没轮到它")]
    with connection() as conn:
        for relevance, title in rows:
            conn.execute(
                """INSERT INTO company_calendar_events
                   (company_id, category, title, event_date, inbox_status,
                    relevance, relevance_source, source, refreshed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (company["id"], "公告", title, "2026-08-18", "待核验",
                 relevance, "规则" if relevance else None, "测试", now_iso()))


def test_选了等级就只给那个等级(inbox_with_mixed_grades: None) -> None:
    for grade in ("高", "中", "低"):
        page = repository.list_inbox(status="待核验", relevance=grade, days=0, limit=50)
        got = {item["relevance"] for item in page["items"]}
        assert got <= {grade}, (
            f"选了「{grade}」却混进了 {sorted(got - {grade})} —— "
            "未分级的条目被 `relevance IS NULL OR` 一起放进来了"
        )
        assert page["items"], f"「{grade}」这一档一条都没有，造的数据里明明有"


def test_两个互斥的筛选不会给出同一批东西(inbox_with_mixed_grades: None) -> None:
    """这是线上那个 bug 最直白的形状：高和低返回了完全一样的列表。"""
    high = {item["id"] for item in repository.list_inbox(
        status="待核验", relevance="高", days=0, limit=50)["items"]}
    low = {item["id"] for item in repository.list_inbox(
        status="待核验", relevance="低", days=0, limit=50)["items"]}
    assert not (high & low), "「只看实质」和「程序性」筛出了同一批条目"


def test_不选等级时未分级的仍要露出来(inbox_with_mixed_grades: None) -> None:
    """严格筛是给显式选择的。默认视图里，"还没轮到它"必须看得见 ——
    否则新进来的公告在被分级之前谁都发现不了。"""
    page = repository.list_inbox(status="待核验", days=0, limit=50)
    grades = [item["relevance"] for item in page["items"]]
    assert None in grades, "默认视图把未分级的挡掉了 —— 新公告会就此消失"
    assert "低" not in grades, "待核验这一档本来就该替你挡掉程序性文件"


def test_按钮上的数要等于点开能看到的条数() -> None:
    """「值得看」这一档连未分级的一起显示，计数就得把它算进去。

    线上那一版按钮写着「值得看 3」，底下列表却是 17 条。
    """
    from pathlib import Path

    app_tsx = (Path(__file__).resolve().parents[3] / "apps/web/src/App.tsx").read_text()
    at = app_tsx.index("setGrade(undefined)")
    line = app_tsx[at:at + 200]
    assert "page.high + page.medium + page.ungraded" in line, (
        "「值得看」的计数没算上未分级的，而这一档会把它们显示出来：\n" + line[:120]
    )
