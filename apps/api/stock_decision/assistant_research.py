"""供私人助理读取已有研究；沿用公司工具和当前用户的数据域。"""

from typing import Literal

from .database import connection
from . import repository as repo

ResearchSection = Literal[
    "theses", "financials", "industry_metrics", "segments", "valuation",
    "announcements", "announcement_text", "promises", "peers", "reports", "report",
]


def read(company_id: int, section: ResearchSection, *, annual_only: bool = True,
         keyword: str = "", event_date: str = "", report_id: int | None = None,
         offset: int = 0) -> dict | None:
    with connection() as conn:
        company = conn.execute(
            f"SELECT id, name, symbol FROM companies WHERE id = ?{repo._sw()}",
            (company_id,)).fetchone()
        if company is None:
            return None
        if section == "reports":
            result = {"reports": [dict(row) for row in conn.execute(
                "SELECT id, title, version, created_at, kind FROM research_reports "
                "WHERE company_id = ? ORDER BY created_at DESC, id DESC LIMIT 30",
                (company_id,)).fetchall()]}
        elif section == "report":
            row = conn.execute(
                "SELECT id, title, body, citations, sources, created_at FROM research_reports "
                "WHERE company_id = ? AND id = ?", (company_id, report_id)).fetchone()
            if row is None:
                return None
            body = row["body"] or ""
            result = {"id": row["id"], "title": row["title"], "created_at": row["created_at"],
                      "text": body[offset:offset + 12000], "offset": offset,
                      "next_offset": offset + 12000 if offset + 12000 < len(body) else None,
                      "citations": row["citations"], "sources": row["sources"]}
        else:
            result = None
    if result is None:
        result = repo.company_tool_runner(company_id)(section, {
            "annual_only": annual_only, "limit": 12,
            "title_contains": keyword, "event_date": event_date,
        })
    return {"company": dict(company), "section": section, "data": result,
            "note": "已有资料，日期以各条记录为准；研究观点不是已经确认的交易规则。"}
