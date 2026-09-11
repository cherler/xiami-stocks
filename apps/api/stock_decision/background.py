"""后台任务：跑在服务进程里，和浏览器无关。

关掉页面、切到别的模块、刷新浏览器，任务都继续跑——因为它根本不在浏览器里。
进度写进数据库，前端只是轮询这张表；即使服务重启，也能从表里看出它当时跑到哪、为什么停的。

设计上刻意不做通用队列：只有"一个任务类型 + 一个目标 id"，同一目标同时只允许一个任务在跑。
够用，而且不会出现排查不了的并发问题。
"""

import asyncio
import json
import logging
import traceback
from typing import Any, Callable

from . import llm
from .access import OWNER_SCOPE, current_scope
from .database import connection, now_iso

# 进程内的运行句柄，用来防止同一目标被重复提交；持久状态一律以数据库为准
_RUNNING: dict[str, asyncio.Task[Any]] = {}


def _key(kind: str, target_id: int) -> str:
    return f"{kind}:{target_id}"


def create_job(kind: str, target_id: int, total: int = 0, label: str = "") -> int:
    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO background_jobs (user_id, kind, target_id, label, status, progress, total, created_at, updated_at)
            VALUES (?, ?, ?, ?, '排队中', 0, ?, ?, ?)
            """,
            (current_scope() or OWNER_SCOPE, kind, target_id, label, total, timestamp, timestamp),
        )
        return int(cursor.lastrowid)


def update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    with connection() as conn:
        conn.execute(f"UPDATE background_jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))


def _inflate(row) -> dict[str, Any] | None:
    if not row:
        return None
    job = dict(row)
    raw = job.pop("result_json", None)
    job["result"] = json.loads(raw) if raw else None
    return job


def _job_scope_sql() -> str:
    """任务按域可见：读图结果、简报花费都是私人的。系统域（调度器兜底）不过滤。"""
    scope = current_scope()
    if scope is None:
        return ""
    if scope != OWNER_SCOPE and not scope.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"非法的数据域：{scope!r}")
    return f" AND user_id = '{scope}'"


def get_job(job_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(f"SELECT * FROM background_jobs WHERE id = ?{_job_scope_sql()}", (job_id,)).fetchone()
    return _inflate(row)


def latest_job(kind: str, target_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            f"SELECT * FROM background_jobs WHERE kind = ? AND target_id = ?{_job_scope_sql()} ORDER BY id DESC LIMIT 1",
            (kind, target_id),
        ).fetchone()
    return _inflate(row)


def list_jobs(kind: str, target_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """读取一个目标的任务历史，最新的在前。

    后台任务本来就是每轮反驳的存档；列表接口只负责把这叠存档交给页面，
    不另建一份“历史结果”表，也不改变其它任务的最新结果读取方式。
    """
    safe_limit = max(1, min(int(limit), 100))
    with connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM background_jobs WHERE kind = ? AND target_id = ?{_job_scope_sql()} "
            "ORDER BY id DESC LIMIT ?",
            (kind, target_id, safe_limit),
        ).fetchall()
    return [job for row in rows if (job := _inflate(row)) is not None]


def active_job(kind: str, target_id: int) -> dict[str, Any] | None:
    job = latest_job(kind, target_id)
    return job if job and job["status"] in {"排队中", "运行中"} else None


async def submit(kind: str, target_id: int, work: Callable[[int], Any], label: str = "") -> dict[str, Any]:
    """提交一个后台任务；同一目标已经在跑就直接返回那一个，不重复起。"""

    existing = active_job(kind, target_id)
    if existing:
        return existing
    job_id = create_job(kind, target_id, label=label)

    async def runner() -> None:
        update_job(job_id, status="运行中", started_at=now_iso())
        # 这一轮的花费单独记账：任务跑完时 HTTP 响应早已返回，账不落在任务行上就没地方看了。
        token = llm.start_accounting()
        try:
            result = await asyncio.to_thread(work, job_id)
            spent = llm.collected()
            # 任务可以返回一句话（进 note），也可以返回 (一句话, 结构化产出)。
            # 后者用于读图这类产出本身就是数据的任务——note 只有 800 字，塞不下几十条流水。
            payload = None
            if isinstance(result, tuple) and len(result) == 2:
                result, payload = result
            update_job(job_id, status="已完成", note=str(result or "")[:800], finished_at=now_iso(),
                       credits=spent["credits"], tokens=spent["tokens"],
                       metered=1 if spent["metered"] else 0,
                       result_json=json.dumps(payload, ensure_ascii=False, default=str) if payload else None)
        except Exception as exc:  # 失败原因要留在表里，否则用户只看到它停了
            spent = llm.collected()
            update_job(
                job_id,
                status="失败",
                credits=spent["credits"],
                tokens=spent["tokens"],
                metered=1 if spent["metered"] else 0,
                error=f"{type(exc).__name__}：{exc}"[:500],
                note=traceback.format_exc()[-800:],
                finished_at=now_iso(),
            )
        finally:
            llm.reset_accounting(token)
            _RUNNING.pop(_key(kind, target_id), None)

    _RUNNING[_key(kind, target_id)] = asyncio.create_task(runner())
    return get_job(job_id) or {"id": job_id, "status": "排队中"}


# 服务重启后，中断任务上写的那句话。**要写清能不能重来、会不会重复扣钱**——
# 原来只有「服务重启，任务未完成」，看到的人第一反应是"那我刚才那笔积分呢"，
# 而这两件事的答案都是好的，只是没人说。
INTERRUPTED_NOTE = (
    "服务重启，任务未完成。可以直接重新跑一次：这一次是全新的任务，"
    "不会在上一次的结果上重复计费；上次冻结的额度会由积分服务自动退回。")


def recover_stale_jobs() -> int:
    """服务重启会让运行中的任务凭空消失；启动时把它们标成中断，而不是永远显示运行中。

    **中断 ≠ 失败。** 失败是这次活儿干砸了（模型报错、数据缺失），
    中断是这台机器重启了，跟这次活儿本身没关系——所以文案要给出下一步动作，
    而不是只报告一个状态。重跑是安全的：submit() 按 (kind, target) 去重，
    重启后旧任务已经不在运行中，新提交会正常开始，两份结果不会互相覆盖。
    """

    with connection() as conn:
        recovered = conn.execute(
            """
            UPDATE background_jobs SET status = '已中断', error = ?,
                   finished_at = ?, updated_at = ?
            WHERE status IN ('排队中', '运行中')
            """,
            (INTERRUPTED_NOTE, now_iso(), now_iso()),
        ).rowcount
    if recovered:
        # 一次重启中断了几个任务，是**运营该知道的事**：经常有中断说明进程在反复重启。
        logging.getLogger("stock_decision.background").warning(
            "服务重启中断了 %s 个后台任务，已标成「已中断」并提示可重跑", recovered)
    return recovered
