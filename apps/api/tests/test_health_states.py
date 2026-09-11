"""同步健康状态：**「哪几种算有问题」只许有一份名单。**

## 2026-08-16 主动排查抓到的

不是撞上的，是反过来搜「同一个概念被写了两份」搜出来的：

    后端 repository._data_health_text   已过期 / 有失败 / 从未成功 / **降级**
    前端 App.tsx 数据状态页             已过期 / 有失败 / 从未成功

前端那份少了「降级」。于是首页和它自己那一页说的不是同一件事 ——
线上此刻就有一个任务是「降级」，假如它是唯一的问题：

    首页        11 个同步任务：正常 10 · 降级 1
    数据状态页  11 个任务正常              ← 点进去反而说没事

而「降级」恰恰是最值得说的那一种：它是「有数据但能力变窄」。
scheduler 自己的注释记着那次 —— 行情源降级到备用之后，
**60 日涨跌与换手率在库里的覆盖率直接是 0**，页面照常渲染、数字照常显示，
只是有几列悄悄空了。

## 修法不是补词，是让前端不再有名单

每个任务带一个 `needs_attention` 出去，判定只在 `scheduler.TROUBLE_HEALTH`
这一处发生。前端读布尔值，没有可漂的东西。

下面这条守卫盯的是**新增状态**：`_health_of` 里加一档而 TROUBLE_HEALTH
没跟上，它就红 —— 那正是这次这个 bug 的来历。
"""

import ast
import inspect
import textwrap

import pytest

from stock_decision import scheduler


def _health_states_the_code_can_return() -> set[str]:
    """从 `_health_of` 的源码里把它能返回的每一种状态抠出来。

    **不手写清单** —— 手写的那份正是这次出错的原因。
    赋值形如 `status, message = "已过期", "…"` 或 `status = "已过期"`，
    用语法树取，不用正则（正则漏跨行，第二十一条那次就是这么栽的）。
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(scheduler._health_of)))
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            names = ([getattr(n, "id", None) for n in target.elts]
                     if isinstance(target, ast.Tuple) else [getattr(target, "id", None)])
            if "status" not in names:
                continue
            values = (node.value.elts if isinstance(node.value, ast.Tuple) else [node.value])
            for name, value in zip(names, values):
                if name == "status" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out.add(value.value)
    return out


# 明确「不算有问题」的那几种，各写一句为什么。
# 跟导出那张名单同一个道理：**「不算」必须是一个被写下来的决定，不能是"忘了加"。**
BENIGN = {
    "正常": "就是正常",
    "运行中": "正在跑，还没有结论",
    "已停用": "你自己关的自动同步，不是故障",
}


def test_every_health_state_is_classified():
    """**新增一档而 TROUBLE_HEALTH 没跟上，这里就红。**

    不是"把降级补进去"，而是让它下次漏不掉。
    """
    produced = _health_states_the_code_can_return()
    assert produced, "没从源码里抠到任何状态 —— 赋值形状变了，这条守卫要跟着改"

    unclassified = sorted(produced - set(scheduler.TROUBLE_HEALTH) - set(BENIGN))
    assert not unclassified, (
        f"这几种健康状态既不在 TROUBLE_HEALTH 里，也没被写进「明确不算有问题」：{unclassified}\n"
        f"  不表态的后果是它被当成正常：首页会说有事，而数据状态页说全部正常。")


def test_a_degraded_job_needs_attention():
    """「降级」= 有数据但能力变窄。它必须算有问题 —— 这是这次那个 bug 本身。"""
    assert scheduler.needs_attention("降级")
    assert "降级" in scheduler.TROUBLE_HEALTH


def test_a_healthy_job_does_not():
    for state in BENIGN:
        assert not scheduler.needs_attention(state), state


def test_the_frontend_no_longer_keeps_its_own_list():
    """**前端不许再自己列一份。**

    修法是让它读后端算好的 needs_attention；哪天有人图省事又把中文状态词
    硬写回页面里，这条就红。守的是"别再长出第二份名单"，不是某一次的取值。
    """
    from pathlib import Path

    import re

    app = Path(__file__).resolve().parents[2] / "web" / "src" / "App.tsx"
    source = app.read_text(encoding="utf-8")
    # **先把注释剥掉。** 第一版没剥，结果把这次修复自己写的那句说明
    # （"这一行原来是 [已过期,有失败,从未成功]"）当成了名单 —— 守卫误报
    # 跟守卫漏报一样糟：下一个人会直接把它删掉。
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    # 找的是「一个数组字面量里同时出现两个以上健康状态词」这种形状
    for match in re.finditer(r"\[[^\[\]\n]{0,200}\]", code):
        hits = [w for w in ("已过期", "有失败", "从未成功", "降级") if f'"{w}"' in match.group(0)]
        assert len(hits) < 2, (
            f"App.tsx 里又长出了一份健康状态名单：{match.group(0)[:80]}\n"
            f"  判定归后端的 scheduler.TROUBLE_HEALTH，前端读 job.needs_attention。")


def test_the_response_model_carries_it():
    """**后端算了、接口不带出去，页面上只表现为"这一栏永远是 undefined"，不报错。**
    这个坑本仓踩过四次，所以每加一栏都钉一下。"""
    from stock_decision.schemas import SyncJobStatus

    assert "needs_attention" in SyncJobStatus.model_fields


# ------------------------------------------- 同一次排查抓到的第二处：上限写了两份

def test_every_slice_cap_is_also_stated_in_its_prompt():
    """**代码里切几条，提示词就要说几条。**

    只在代码这一头切的话，模型写了 15 条、页面只显示 12 条 ——
    被切掉的三条不报错、不留痕，而它们的钱已经付过了。

    深度报告那次是撞上的（sections 切 6、lines 切 12，提示词都没说）；
    这一条是反过来搜出来的：研究简报的 `_lines` 切 12，
    而 REPORT_SYSTEM_PROMPT 里一个字都没提。
    """
    from stock_decision import chain_and_reports as cr, deep_report as dr

    assert "最多 12 条" in cr.REPORT_SYSTEM_PROMPT, "简报每节切 12，提示词要说"
    for cap in ("最多 6 章", "最多 12 句", "最多 8 个", "最多 8 条"):
        assert cap in dr.SYSTEM_PROMPT, cap


def test_the_interval_in_code_wins_over_the_row_in_the_database():
    """**同一个概念写了两份，而库里那份赢了。**

    2026-08-17：把 universe 从 1440 分钟改成 30，部署完库里那一行还是 1440，
    下次运行仍然是明天 —— 改完、部署完、日志干净、什么都没报错，**只是没生效**。
    使用者的话：「上线了吗。为啥云图的结果还是没有同步更新？」

    间隔是产品决定（多久的数据算新鲜），归代码；`enabled` 是偏好，归用户。
    """
    from stock_decision.database import connection
    from stock_decision.scheduler import JOBS, ensure_schedules

    ensure_schedules()
    with connection() as conn:
        conn.execute("UPDATE sync_schedules SET interval_minutes = 99999, enabled = 0 "
                     "WHERE job_id = 'universe'")
    ensure_schedules()
    with connection() as conn:
        row = conn.execute(
            "SELECT interval_minutes, enabled FROM sync_schedules WHERE job_id = 'universe'"
        ).fetchone()
    wanted = next(job.interval_minutes for job in JOBS if job.job_id == "universe")
    assert row["interval_minutes"] == wanted, "间隔没跟着代码走 —— 改了也不会生效"
    assert not row["enabled"], "开关是用户的偏好，不该被覆盖"


def test_but_an_interval_the_user_set_is_left_alone():
    """**间隔本来就是可改的**（）。

    让代码一律覆盖会把那个功能弄坏 —— 我第一版就是这么写的，
    门禁里 test_sync_jobs_expose_schedule_and_health 当场红了。
    所以记一个 interval_overridden：代码管默认值，用户改过的不动。
    """
    from stock_decision.database import connection
    from stock_decision.scheduler import ensure_schedules, update_job

    ensure_schedules()
    update_job("universe", interval_minutes=180)
    ensure_schedules()
    with connection() as conn:
        row = conn.execute(
            "SELECT interval_minutes FROM sync_schedules WHERE job_id = 'universe'").fetchone()
    assert row["interval_minutes"] == 180, "用户改过的间隔被代码覆盖了"
