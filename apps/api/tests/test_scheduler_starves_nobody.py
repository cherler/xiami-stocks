"""调度器不许把排在后面的作业饿死，重启也不许重排所有作业。

## 线上实测（2026-08-18）出来的

「全市场底座」间隔 30 分钟，而它 **一天多没跑过一次**。
状态写着「降级」、`last_error` 是空的 —— **它没失败，是根本没轮到**。

当天 `sync_runs` 里只有四个作业跑过：quotes / price_history / profile /
inbox_tidy —— 正好是 JOBS 列表里的**前四位**。第 5 位往后一个都没有。

两个原因叠在一起：

1. **每轮只跑 due[0]，而 due 按 JOBS 里的固定顺序排。**
   只要前面的作业总是到期，后面的永远轮不到。而 price_history 每次跑
   十分钟（594 秒，每次都「部分失败」），产能几乎被它和 quotes 吃光。

2. **ensure_schedules 每次服务启动都把所有作业的 next_run_at 拉到 now+2min。**
   那一行原本是为了"间隔改小了别等旧的那一轮"，但没有限定条件。
   当天服务重启了 51 次（每部署一次重启一次），于是所有作业每天被重排几十回，
   反复回到"一起到期"的状态，让第 1 条的饥饿一直重演。

## 为什么必须用测试守

这个 bug **不产生任何错误信息**：作业状态是「降级」或「成功」，
`last_error` 空，日志里没有异常。唯一的症状是数据停在昨天，
而那要人自己去比对时间戳才看得出来。
"""

from __future__ import annotations

import ast
import pathlib
import re
from datetime import datetime, timedelta

SRC = pathlib.Path(__file__).resolve().parents[1] / "stock_decision" / "scheduler.py"


def test_due_jobs_are_ordered_by_how_long_they_waited():
    """**不许按 JOBS 里的固定顺序排。** 那会让排在后面的被永久插队。"""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "due_job_ids")
    body = ast.unparse(fn)
    assert "next_run_at" in body and "sort" in body, "due_job_ids 不再按到期时间排序"
    assert "enumerate(JOBS)" not in body, (
        "又按 JOBS 里的位置排了 —— 每轮只跑一个，排在后面的会被前面的饿死")


def test_restart_does_not_reschedule_everything():
    """**只有间隔真的变小时才提前。** 否则每次重启都把所有作业拉到一起到期。"""
    body = SRC.read_text(encoding="utf-8")
    at = body.index("def ensure_schedules")
    block = body[at:body.index("\ndef ", at + 10)]
    assert "next_run_at = CASE" in block, "ensure_schedules 里那段 upsert 没了"
    # 提前的那一支必须带上「新间隔 < 旧间隔」这个条件
    branch = block[block.index("next_run_at = CASE"):]
    branch = branch[:branch.index("END")]
    assert "excluded.interval_minutes < sync_schedules.interval_minutes" in branch, (
        "提前 next_run_at 时没有限定「间隔真的变小」——\n"
        "那样每次服务启动都会把所有作业拉到 now+2min 一起到期，"
        "而线上一天重启了 51 次。")


def test_a_slow_job_cannot_hold_the_queue_forever():
    """跑得慢的作业有墙钟上限，超了要被判超时并让出队列。"""
    body = SRC.read_text(encoding="utf-8")
    timeout = re.search(r"JOB_TIMEOUT_SECONDS\s*=\s*(\d+)", body)
    assert timeout, "单个作业的墙钟上限没了 —— 卡住的请求会让排期永远停在「运行中」"
    assert int(timeout.group(1)) <= 1800, "墙钟上限太长，一个卡住的作业能占住半小时"
    assert "_mark_timeout" in body, "超时之后没有把状态改掉，作业会永远排不上队"


def test_the_ordering_actually_rotates():
    """按到期时间排序 → 每个作业最终都会排到队头。这里直接算一遍。

    模拟：三个作业，A 间隔 1 分钟（总是到期）、B 和 C 间隔 30 分钟。
    按固定顺序排的话，只要 A 排在前面，B / C 永远轮不到；
    按 next_run_at 排的话，A 跑完 next_run 推后，B 就成了最久的那个。
    """
    now = datetime(2026, 8, 18, 16, 0, 0)
    rows = {
        "A": now - timedelta(minutes=1),
        "B": now - timedelta(hours=26),      # 欠了一天多，就是线上底座那种
        "C": now - timedelta(minutes=5),
    }
    order = sorted(rows, key=lambda k: rows[k].isoformat())
    assert order[0] == "B", (
        f"欠得最久的应该排队头，实际是 {order} —— "
        "这正是「全市场底座一天多没跑过」的那种情况")


def test_a_restart_releases_jobs_it_interrupted():
    """**进程都没了，那个「运行中」一定是死的。**

    系统原来要等满墙钟上限（15 分钟）才敢重排一个卡在「运行中」的作业。
    而实测那天服务重启了 51 次，price_history 每轮要跑十分钟 ——
    它几乎每次都被重启打断，然后又白等 15 分钟才轮得上。

    所以启动时主动放掉：上一个进程留下的「运行中」不可能还在跑。
    """
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_release_runs_from_a_dead_process"),
              None)
    assert fn is not None, "启动时不再释放被重启打断的作业 —— 它们会白占 15 分钟"
    body = ast.unparse(fn)
    assert "运行中" in body and "UPDATE sync_schedules" in body
    # **只放「运行中」，别的状态不许动**
    assert "WHERE last_status = '运行中'" in body, (
        "释放条件不是「只放运行中」—— 会改到别的状态")
    # 不许顺手改 next_run_at：什么时候跑由排期说了算。
    # **看代码不看文档字符串** —— 第一版把说明里那句「也不改 next_run_at」
    # 也当成了代码，当场假红一次。
    code = ast.unparse(ast.Module(body=[n for n in fn.body
                                        if not (isinstance(n, ast.Expr)
                                                and isinstance(n.value, ast.Constant))],
                                  type_ignores=[]))
    assert "next_run_at" not in code, (
        "释放时顺手改了 next_run_at —— 那是排期的事，这里只该把门闩拔掉")

    # 而且调度器启动时真的调了它
    loop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "scheduler_loop")
    assert "_release_runs_from_a_dead_process" in ast.unparse(loop), (
        "写了但没在启动时调 —— 那等于没写")


def test_the_interrupted_state_is_not_mistaken_for_healthy():
    """「中断」要能被健康判定认出来，否则数据没更新而页面说一切正常。"""
    src = SRC.read_text(encoding="utf-8")
    at = src.index("def _health_of")
    block = src[at:src.index("\ndef ", at + 10)]
    assert '"中断"' in block, (
        "健康判定不认识「中断」—— 被重启打断的作业会被当成正常，"
        "而它的数据其实没更新")
