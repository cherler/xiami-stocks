"""闸口不可用时的未计费台账，以及"连续失败就停手"的熔断。

## 为什么要有这个

`llm.reserve()` 里有一句写明了理由的决定：**闸口连不上 ≠ 用户没钱**，
所以主站抖一下的时候不挡住调用，让研究台继续能用。这个判断是对的，
但它原来没有上限——闸口要是宕上一整天，这一天里所有 AI 调用都是免费的，
而且**账上一点痕迹都没有**，事后连"漏了多少"都算不出来。

所以补两件事，一件都不能少：

1. **台账**：每一次未计费的调用都落一行，跑完之后把实际 token 和按公式
   估出来的积分补上。闸口恢复后照着这张表对账。
2. **熔断**：10 分钟内未计费调用超过 20 次，就认定"这不是抖一下，是真宕了"，
   之后的调用直接拒绝并提示，而不是继续免费送。

## 阈值的含义

20 次/10 分钟是按"一个人正常研究的节奏"给的：连着二十次都没能计上费，
说明闸口不是偶发超时。**没有跨进程状态**——阈值是查表数出来的，
所以重启 API 也不会把熔断"忘掉"，多开一个 worker 也不会各算各的。

## 它不拦什么

本地单机（没配 XM_API_BASE）和未登录不会落账，也不会被熔断挡住：
那两种情况本来就不该计费，把它们算进来会在本地开发时误伤。
"""

from __future__ import annotations

import logging
from typing import Any

from datetime import datetime, timedelta

from .database import connection, now_iso

log = logging.getLogger("stock_decision.billing")

# 熔断阈值。改这两个数之前先想清楚：调大 = 宕机时漏得更多，
# 调小 = 主站偶发抖动就会让用户看到「AI 暂停」。
WINDOW_MINUTES = 10
MAX_UNBILLED_IN_WINDOW = 20

# 落账的原因。**"未登录"和"本地单机"不在这里**——那两种不算漏计。
REASON_UNREACHABLE = "闸口不可达"
REASON_REJECTED = "冻结被拒"


def record(module: str, task: str, reason: str, estimated_tokens: int, searches: int) -> int:
    """记一笔未计费调用，返回行号（跑完之后用它补实际用量）。"""
    stamp = now_iso()
    try:
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO unbilled_calls
                    (module, task, reason, estimated_tokens, searches, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (module, task, reason, max(0, int(estimated_tokens or 0)),
                 max(0, int(searches or 0)), stamp),
            )
            return int(cursor.lastrowid or 0)
    except Exception as exc:
        # 台账写不进去也**不能反过来打断业务调用**——那就把"闸口抖一下"
        # 升级成了"研究台不能用"，正好是这套设计要避免的事。
        log.error("未计费台账写入失败：%s", exc)
        return 0


def finish(row_id: int, tokens: int, searches: int, credits: int) -> None:
    """调用跑完了，把实际用量补进那一行。对账靠的就是这几个数。"""
    if not row_id:
        return
    try:
        with connection() as conn:
            conn.execute(
                "UPDATE unbilled_calls SET tokens = ?, searches = ?, credits_estimate = ? WHERE id = ?",
                (max(0, int(tokens or 0)), max(0, int(searches or 0)), max(0, int(credits or 0)), row_id),
            )
    except Exception as exc:
        log.error("未计费台账回填失败 id=%s：%s", row_id, exc)


def recent_count(minutes: int = WINDOW_MINUTES) -> int:
    """时间窗内有多少次没计上费。**只数没对过账的**。"""
    # **时间窗在 Python 里算，不写进 SQL。** `datetime('now','-10 minutes')`
    # 只有 SQLite 认，线上是 PostgreSQL —— 那种写法会在生产上抛语法错，
    # 而本机测试全绿。created_at 是 ISO 字符串，按字典序比就是按时间比。
    cutoff = (datetime.now().replace(microsecond=0) - timedelta(minutes=max(1, int(minutes)))).isoformat()
    try:
        with connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM unbilled_calls
                WHERE reconciled_at IS NULL AND created_at >= ?
                """,
                (cutoff,),
            ).fetchone()
        return int(row["n"] if row is not None else 0)
    except Exception as exc:
        # 数不出来的时候**不要熔断**：这一层是保护成本的，不该因为自己出错
        # 就把功能关掉。宁可漏计，也不要凭一个读不出来的数把人挡在门外。
        log.error("未计费计数失败，本次不熔断：%s", exc)
        return 0


def paused() -> bool:
    """现在是不是该停手了。"""
    return recent_count() > MAX_UNBILLED_IN_WINDOW


def state() -> dict[str, Any]:
    """给页面看的状态：最近漏了几次、停没停、一共欠着多少没对账。"""
    recent = recent_count()
    total = 0
    credits = 0
    oldest = None
    try:
        with connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n, COALESCE(SUM(credits_estimate), 0) AS c, MIN(created_at) AS oldest
                FROM unbilled_calls WHERE reconciled_at IS NULL
                """
            ).fetchone()
        if row is not None:
            total = int(row["n"] or 0)
            credits = int(row["c"] or 0)
            oldest = row["oldest"]
    except Exception:
        pass
    return {
        "recent": recent,
        "window_minutes": WINDOW_MINUTES,
        "threshold": MAX_UNBILLED_IN_WINDOW,
        "paused": recent > MAX_UNBILLED_IN_WINDOW,
        "pending": total,
        "pending_credits": credits,
        "oldest_at": oldest,
    }


def pending(limit: int = 200) -> list[dict[str, Any]]:
    """还没对账的那些，新的在前。"""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT id, module, task, reason, estimated_tokens, tokens, searches,
                   credits_estimate, created_at
            FROM unbilled_calls WHERE reconciled_at IS NULL
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (max(1, min(int(limit or 200), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def settle(note: str = "") -> int:
    """把当前所有未对账的标成已对账，返回条数。

    **不删行**：这张表是账，删掉就没法回头查"那天到底漏了多少"。
    """
    stamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE unbilled_calls SET reconciled_at = ?, note = ? WHERE reconciled_at IS NULL",
            (stamp, (note or "")[:200]),
        )
        return int(cursor.rowcount or 0)
