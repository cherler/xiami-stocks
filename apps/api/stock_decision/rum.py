"""真实用户监测（RUM）：他们那边到底多快、有没有报错。

## 为什么要自建，而不是接一个现成的

页面上全是持仓成本、买卖理由、还没公开的判断。第三方 SDK（Sentry 之类）
默认会抓面包屑、DOM 文本、完整 URL —— 那等于把研究记录发给别人。
所以这里只做**最小的一份**：几个毫秒数、页面名、设备大类，落进自己的库。

## 它回答什么

- 那 626 kB 的首屏优化，对真人省了多少秒（我本机量的是千兆网）
- 哪一页在真实设备上最慢
- 有没有用户遇到过我这边从来没复现过的 JS 报错

## 它**不**收什么

URL 查询串、公司名、任何页面内容、IP、完整 User-Agent（那是指纹）。
页面名在服务端按白名单校验，白名单外的一律记成 other —— 前端传什么进来
都不会变成一个新的自由文本字段。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .database import connection, now_iso

# 页面名白名单。**服务端说了算**：前端传进来的值只在这张表里才被接受，
# 否则一律记成 other。这样即使前端哪天写错、或者有人手动打接口，
# 也不会往库里塞进一段自由文本（那是最容易夹带内容的地方）。
PAGES = {
    "dashboard", "review", "reviews", "companies", "company", "industries",
    "screener", "heatmap", "tasks", "methods", "news", "chain", "reports",
    "prefs", "portfolio", "data", "backups",
}
DEVICES = {"desktop", "mobile", "tablet"}
KINDS = {"nav", "error"}


def _clean_ms(value: Any) -> int | None:
    """毫秒数。**取不到就留空，不要填 0** —— 0 会被读成"很快"。"""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    # 负数和离谱的大数都是坏数据（时钟回拨、后台标签页），别让它们污染分位数
    if number < 0 or number > 10 * 60 * 1000:
        return None
    return number


def record(payload: dict[str, Any]) -> None:
    page = str(payload.get("page") or "")
    kind = str(payload.get("kind") or "nav")
    device = str(payload.get("device") or "")
    row = (
        page if page in PAGES else "other",
        kind if kind in KINDS else "nav",
        _clean_ms(payload.get("ttfb_ms")),
        _clean_ms(payload.get("dom_ready_ms")),
        _clean_ms(payload.get("load_ms")),
        _clean_ms(payload.get("lcp_ms")),
        str(payload.get("error_name") or "")[:80],
        str(payload.get("error_message") or "")[:200],
        device if device in DEVICES else "",
        now_iso(),
    )
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO rum_samples
                (page, kind, ttfb_ms, dom_ready_ms, load_ms, lcp_ms,
                 error_name, error_message, device, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )


def _percentile(values: list[int], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def summary(days: int = 7) -> dict[str, Any]:
    """按页面出分位数。**看 p75 不看平均**：平均会被几个极端值拉走，
    而慢的体验恰恰发生在那几个人身上。"""
    since = (datetime.now() - timedelta(days=max(1, int(days)))).replace(microsecond=0).isoformat()
    with connection() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM rum_samples WHERE created_at >= ? ORDER BY id DESC LIMIT 5000",
            (since,)).fetchall()]

    pages: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["kind"] != "nav":
            continue
        bucket = pages.setdefault(row["page"], {"page": row["page"], "samples": 0, "lcp": [], "load": [], "ttfb": []})
        bucket["samples"] += 1
        for key, column in (("lcp", "lcp_ms"), ("load", "load_ms"), ("ttfb", "ttfb_ms")):
            if row[column] is not None:
                bucket[key].append(int(row[column]))

    by_page = []
    for bucket in pages.values():
        by_page.append({
            "page": bucket["page"],
            "samples": bucket["samples"],
            "lcp_p75": _percentile(bucket["lcp"], 0.75),
            "load_p75": _percentile(bucket["load"], 0.75),
            "ttfb_p75": _percentile(bucket["ttfb"], 0.75),
        })
    by_page.sort(key=lambda item: (item["lcp_p75"] is None, -(item["lcp_p75"] or 0)))

    errors: dict[tuple[str, str], int] = {}
    for row in rows:
        if row["kind"] != "error":
            continue
        key = (row["error_name"], row["error_message"])
        errors[key] = errors.get(key, 0) + 1

    devices: dict[str, int] = {}
    for row in rows:
        devices[row["device"] or "未知"] = devices.get(row["device"] or "未知", 0) + 1

    return {
        "days": days,
        "samples": len(rows),
        "by_page": by_page,
        "errors": [{"name": name, "message": message, "count": count}
                   for (name, message), count in sorted(errors.items(), key=lambda kv: -kv[1])[:20]],
        "devices": devices,
        "boundary": "只记毫秒数、页面名与设备大类；不记 URL 参数、页面内容、IP 与完整 User-Agent。",
    }
