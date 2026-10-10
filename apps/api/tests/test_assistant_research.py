"""研究工具必须读到原文，并严格限制在当前用户和研究目录内。"""
import importlib.util
from pathlib import Path

from stock_decision import access, assistant_research, repository
from stock_decision.database import connection, now_iso
from stock_decision.schemas import CompanyInput, ThesisCreate
from test_idor import client, owned  # noqa: F401


def test_reads_existing_thesis_without_creating_plan():
    cid = repository.create_company(CompanyInput(symbol="601138", name="工业富联", industry="电子"))["id"]
    repository.create_thesis(cid, ThesisCreate(claim="验证订单能否变成现金"))
    result = assistant_research.read(cid, "theses")
    assert result["data"]["theses"][0]["claim"] == "验证订单能否变成现金"
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM decision_cards").fetchone()["n"] == 0


def test_research_endpoints_do_not_leak_other_users(client, owned):  # noqa: F811
    client.as_user("user-9")
    for section in ("theses", "financials", "valuation", "reports", "report"):
        assert client.get(f"/api/v1/assistant/research/{owned['company']}?section={section}").status_code == 404
    client.as_user(access.OWNER_SCOPE)
    assert client.get(f"/api/v1/assistant/research/{owned['company']}?section=delete").status_code == 422
    assert client.get(f"/api/v1/assistant/research/{owned['company']}?offset=-1").status_code == 422


def test_report_body_paginates_and_requires_its_own_company():
    one = repository.create_company(CompanyInput(symbol="601138", name="工业富联", industry="电子"))["id"]
    two = repository.create_company(CompanyInput(symbol="600519", name="贵州茅台", industry="白酒"))["id"]
    body = "原报告" * 5000
    with connection() as conn:
        report_id = int(conn.execute(
            "INSERT INTO research_reports (company_id, version, title, body, created_at) "
            "VALUES (?, 1, '原报告', ?, ?)", (one, body, now_iso())).lastrowid)
    catalog = assistant_research.read(one, "reports")["data"]["reports"]
    assert catalog[0]["id"] == report_id and "body" not in catalog[0]
    first = assistant_research.read(one, "report", report_id=report_id)["data"]
    second = assistant_research.read(one, "report", report_id=report_id, offset=first["next_offset"])["data"]
    assert first["text"] + second["text"] == body
    assert assistant_research.read(two, "report", report_id=report_id) is None


def _library():
    path = Path(__file__).resolve().parents[2] / "assistant" / "research_library.py"
    spec = importlib.util.spec_from_file_location("research_library_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_reports_preserve_dates_sources_and_pagination(tmp_path):
    lib = _library()
    lib.ROOT = tmp_path
    body = "---\ntitle: 工业富联分层估值\nupdated: 2026-09-23\n---\n" + "原文" * 7000
    (tmp_path / "fii.md").write_text(body)
    (tmp_path / "fii.sources.json").write_text('[{"key":"annual","url":"https://example.com/report"}]')
    assert lib.search("工业富联")["reports"][0]["id"] == "fii"
    first = lib.read("fii")
    second = lib.read("fii", first["next_offset"])
    assert first["text"] + second["text"] == body
    assert first["updated"] == "2026-09-23"
    assert first["sources"][0]["key"] == "annual"
    assert second["next_offset"] is None


def test_local_report_reader_rejects_paths_and_symlinks(tmp_path):
    lib = _library()
    root = tmp_path / "research"
    root.mkdir()
    lib.ROOT = root
    secret = tmp_path / "private.md"
    secret.write_text("secret")
    (root / "escape.md").symlink_to(secret)
    assert "error" in lib.read("../private")
    assert "error" in lib.read("escape")
    assert lib.search()["reports"] == []
    assert "error" in lib.read("any", -1)
