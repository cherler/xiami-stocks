"""跟踪首页展示已有研究，不为浏览创建卡片，并保持数据域隔离。"""
from stock_decision import access, repository
from stock_decision.database import connection, now_iso
from stock_decision.schemas import CompanyInput, ThesisCreate


def company(symbol="600519"):
    return repository.create_company(CompanyInput(symbol=symbol, name="测试公司", industry="测试行业"))["id"]


def test_reading_existing_research_does_not_enroll_or_change_rules():
    cid = company()
    repository.create_thesis(cid, ThesisCreate(claim="原始判断，不应被复制成计划"))
    with connection() as conn:
        conn.execute("INSERT INTO research_reports (company_id, version, title, body, created_at) VALUES (?, 1, ?, ?, ?)",
                     (cid, "已有报告", "正文", now_iso()))
        conn.execute("INSERT INTO valuations (company_id, created_at) VALUES (?, ?)", (cid, now_iso()))
        before = conn.execute("SELECT COUNT(*) AS n FROM decision_cards").fetchone()["n"]
    for _ in range(2):
        board = repository.decision_loop_board()
        row = board["research"][0]
        assert row["company_id"] == cid
        assert row["latest_claim"] == "原始判断，不应被复制成计划"
        assert (row["thesis_count"], row["valuation_count"], row["report_count"]) == (1, 1, 1)
        assert row["report_title"] == "已有报告"
        assert row["price"] is None and row["price_date"] is None
        assert board["total"] == before == 0


def test_keeps_tracked_company_but_hides_removed_untracked_archive():
    tracked = company()
    removed = company("000651")
    repository.ensure_decision_card(tracked)
    with connection() as conn:
        conn.execute("UPDATE companies SET is_watched = 0 WHERE id IN (?, ?)", (tracked, removed))
    board = repository.decision_loop_board()
    assert [r["company_id"] for r in board["research"]] == [tracked]
    assert board["total"] == 1


def test_research_from_another_user_is_not_exposed():
    owner_company = company()
    repository.create_thesis(owner_company, ThesisCreate(claim="私有判断"))
    repository.ensure_decision_card(owner_company)
    token = access.set_scope("tracking_other_user")
    try:
        own_company = company("000651")
        board = repository.decision_loop_board()
        assert [r["company_id"] for r in board["research"]] == [own_company]
        assert board["research"][0]["latest_claim"] is None
        assert board["total"] == 0
    finally:
        access.reset_scope(token)
