"""后台同步调度与数据健康。

设计取舍：
- 调度状态写在本地库里，程序关掉再打开也知道哪些任务已经过期，重开后会补跑。
- 每个任务失败只影响自己：某家公司抓取失败不会中断整批，某个任务异常也不会影响页面读取。
- 一切仍可手动触发；自动同步只负责把事实取回来，不做任何研究判断。
"""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .database import connection, now_iso

logger = logging.getLogger(__name__)

RETRY_DELAYS = (5, 20)  # 两次重试的间隔秒数，避免对来源连续猛敲
COMPANY_PAUSE_SECONDS = 0.8  # 逐家公司抓取之间的限流间隔
TICK_SECONDS = 60
JOB_TIMEOUT_SECONDS = 900  # 单个任务的墙钟上限：上游没有超时时，卡住的请求不该让排期永远停在"运行中"
_RUN_LOCK = threading.Lock()  # 只保护下面这条"当前运行"的记录，不用来长期占位
_ACTIVE_RUN: tuple[str, float] | None = None  # (job_id, 开始时刻)；上游卡死时按超时自动让位


@dataclass(frozen=True)
class SyncJob:
    job_id: str
    display_name: str
    category: str
    interval_minutes: int
    freshness_hours: int
    weekdays_only: bool
    runner: Callable[[], dict[str, Any]]
    description: str


def _companies() -> list[dict[str, Any]]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT id, symbol, name FROM companies ORDER BY id").fetchall()]


def _attempt(call: Callable[[], Any]) -> Any:
    """同一次抓取最多重试两次；来源偶发抖动不该直接判定为失败。

    **积分被拒不重试。** 重试是为了熬过对面的偶发抖动，而「余额不足」是个确定的答复：
    再问两遍还是同一句，只是让这个人的整理白白拖上几十秒，后面排队的人跟着等。
    闸口不可用是另一回事（那是抖动），llm 那边本来就不会把它抛成 CreditsError。
    """
    from .llm import CreditsError

    last_error: Exception | None = None
    for index in range(len(RETRY_DELAYS) + 1):
        try:
            return call()
        except CreditsError:
            raise
        except Exception as exc:  # 来源层已经把传输错误归一化，这里只关心成功与否
            last_error = exc
            if index < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[index])
    raise last_error if last_error else RuntimeError("未知错误")


def _per_company(refresh: Callable[[int], Any], label: str) -> dict[str, Any]:
    companies = _companies()
    items = 0
    failures: list[str] = []
    for index, company in enumerate(companies):
        if index:
            time.sleep(COMPANY_PAUSE_SECONDS)
        try:
            result = _attempt(lambda company_id=company["id"]: refresh(company_id))
            items += int(result or 0)
        except Exception as exc:
            failures.append(f"{company['name']}({company['symbol']})：{exc}")
    detail = f"{len(companies) - len(failures)}/{len(companies)} 家公司{label}成功，共 {items} 条"
    return {"items": items, "failures": len(failures), "detail": detail, "errors": failures}


def _run_quotes() -> dict[str, Any]:
    from .repository import refresh_all_market_quotes

    refreshed, requested = _attempt(refresh_all_market_quotes)
    return {"items": refreshed, "failures": 0, "detail": f"{refreshed}/{requested} 家公司行情已更新", "errors": []}


def _run_price_history() -> dict[str, Any]:
    from .repository import refresh_company_market_history

    return _per_company(refresh_company_market_history, "日线")


def _run_profile() -> dict[str, Any]:
    from .repository import refresh_company_profile

    return _per_company(refresh_company_profile, "简况与公告")


def background_ai_enabled() -> bool:
    """后台整理要不要调模型 —— **由每个用户自己在页面上决定，默认关。**

    「记到谁头上」不是问题：积分闸口本来就是为模型调用准备的，后台调用并不特殊，
    而这个作业逐用户跑、本来就知道是在替谁干活，所以各扣各的（principal_for_scope）。

    默认关是另一件事：**没人点过，费用却已经发生了。** 用户第二天看到余额少了
    一截，而他昨天什么都没做——这不是记错账，是没打招呼。所以做成他自己勾的开关
    （收件箱页面的「后台每天替我分级」），勾了才跑。

    没勾的人照样每天跑规则那一步，不花钱：实质变化自动归档、程序性自动忽略，
    只有「规则拿不准」那一档等他自己点。

    `STOCK_BACKGROUND_AI` 现在只是**全局关停闸**：设成 0/off 时所有人一律不跑，
    不管各自勾没勾。留着它是为了出事时能一把关掉，不用去改每个人的设置。
    它不能反过来替用户打开——那就绕过了「他自己勾」这件事本身。
    """
    return not _globally_disabled() and _user_opted_in()


def _globally_disabled() -> bool:
    from . import llm

    raw = (os.getenv("STOCK_BACKGROUND_AI") or llm.load_env().get("STOCK_BACKGROUND_AI") or "").strip().lower()
    return raw in {"0", "false", "no", "off"}


def _user_opted_in() -> bool:
    """当前数据域勾了没有。读不到就当没勾——出错要往不花钱的方向倒。"""
    from .repository import get_setting

    try:
        return get_setting("inbox_auto_grade")
    except Exception:
        logger.warning("读不到自动分级设置，本次按「未开启」处理")
        return False


def _run_inbox_tidy() -> dict[str, Any]:
    """收件箱整理必须**逐用户**跑，不能在系统域一把梭。

    分级会用到各人自己确认过的规则词（rule_terms 按域隔离）——系统域跑一遍
    等于把 A 的词表用在 B 的公告上；归档产生的证据也要落在正确的域里。
    其余同步任务（行情、财报）是机械拉数，谁的都一样，留在系统域没问题。

    模型那一步由每个用户自己决定，默认不做，见 background_ai_enabled()。
    """
    from . import access, llm
    from .database import connection
    from .repository import tidy_inbox

    with connection() as conn:
        scopes = [row["user_id"] for row in conn.execute("SELECT DISTINCT user_id FROM companies").fetchall()]
    totals = {"classified": 0, "archived": 0, "ignored": 0, "remaining": 0}
    credits = 0
    ai_scopes = 0
    errors: list[str] = []
    for scope in scopes or [access.OWNER_SCOPE]:
        token = access.set_scope(scope)
        # 账记在这个域的主人头上。**必须逐域切换**：不切的话所有人的消耗都会
        # 落到 background_principal() 那一个 user_id 上，也就是站主替全站付钱。
        principal_token = llm.set_principal(llm.principal_for_scope(scope))
        accounting_token = llm.start_accounting()
        try:
            # 开关是**每个人自己的**，所以必须在切进他的域之后才读得到。
            # 放在循环外读一次，读到的永远是第一个人的选择，然后按它对待所有人。
            use_ai = background_ai_enabled()
            ai_scopes += 1 if use_ai else 0
            result = _attempt(lambda: tidy_inbox(use_ai=use_ai))
            for key in totals:
                totals[key] += int(result.get(key) or 0)
            credits += int(llm.collected().get("credits") or 0)
        except Exception as exc:                      # 一个用户失败不拖垮其他人
            # 余额不足也走这里：那是这个人的问题，不该让别人的整理跟着停。
            errors.append(f"{scope}: {exc}")
        finally:
            llm.reset_accounting(accounting_token)
            llm.reset_principal(principal_token)
            access.reset_scope(token)
    # 说清楚模型有没有参与：否则「待人工处理 2 条」看不出是"模型也拿不准"
    # 还是"压根没让模型看"，而这两种情况下你该做的事完全不同。
    total_scopes = len(scopes) or 1
    if ai_scopes == 0:
        how = "只用规则（要后台自动分级，请在收件箱页面勾上）"
    elif ai_scopes == total_scopes:
        how = "规则+模型"
    else:
        how = f"规则全跑，其中 {ai_scopes}/{total_scopes} 个开了模型分级"
    spent = f" · 共扣 {credits} 分（各记各的账）" if credits else ""
    return {
        "items": totals["classified"],
        "failures": len(errors),
        "detail": (f"{total_scopes} 个数据域 · {how}：归档 {totals['archived']} 条、"
                   f"忽略 {totals['ignored']} 条，待人工处理 {totals['remaining']} 条{spent}"),
        "errors": errors,
    }


def _run_counter_match() -> dict[str, Any]:
    """**把新公告拿去撞每个人写下的认错条件。** 逐用户跑，理由同 inbox_tidy。

    ## 为什么必须有这个作业

    「写下什么情况算我错，事实撞上时告诉你」是这个产品的中心承诺，
    而在这条作业之前，**它一次都不会自己发生**：比对只有一个入口——
    首页一个默认折叠的分区里的一个文字按钮。折叠着的时候那个按钮连 DOM 都没有。

    2026-08-14 线上实测（真实账号）：3 条投资逻辑全都写了认错条件、
    收件箱里 40 条公告待核验、反证命中 **0**。四十条公告和三条认错条件
    在库里躺着，从来没有被放在一起看过一眼。

    而页面上那个「反证 0」读起来是**"查过了，没事"**，不是"没查过" ——
    比不做还糟，它给的是一个假的安心。

    ## 花钱这件事跟 inbox_tidy 一样处理

    比对要过模型（counters.find_hits → llm.call），所以**默认不跑**，
    由用户自己勾。理由见 background_ai_enabled：没人点过、费用却已经发生，
    那不是记错账，是没打招呼。

    没勾的人不会被扣钱，但也不该被蒙在鼓里 —— 所以「还有多少条没比对过」
    这个数由接口如实给出（repository.uncompared_events），页面上写清楚。
    """
    from . import access, llm
    from .database import connection
    from .repository import check_counter_hits

    with connection() as conn:
        scopes = [row["user_id"] for row in
                  conn.execute("SELECT DISTINCT user_id FROM companies").fetchall()]
    stored = checked = credits = ai_scopes = 0
    errors: list[str] = []
    for scope in scopes or [access.OWNER_SCOPE]:
        token = access.set_scope(scope)
        # 各扣各的账。不切域的话所有人的消耗都落到站主一个人头上。
        principal_token = llm.set_principal(llm.principal_for_scope(scope))
        accounting_token = llm.start_accounting()
        try:
            # 开关是**每个人自己的**，必须切进他的域之后才读得到。
            if not background_ai_enabled():
                continue
            ai_scopes += 1
            result = _attempt(check_counter_hits)
            stored += int(result.get("stored") or 0)
            checked += int(result.get("checked") or 0)
            credits += int(llm.collected().get("credits") or 0)
        except Exception as exc:                      # 一个人失败不拖垮其他人
            errors.append(f"{scope}: {exc}")
        finally:
            llm.reset_accounting(accounting_token)
            llm.reset_principal(principal_token)
            access.reset_scope(token)
    total = len(scopes) or 1
    if ai_scopes == 0:
        detail = (f"{total} 个数据域都没开后台比对，这一轮没跑。"
                  f"要它自动跑，在收件箱页面勾上「后台每天替我分级」")
    else:
        spent = f" · 共扣 {credits} 分（各记各的账）" if credits else ""
        detail = (f"{ai_scopes}/{total} 个数据域开了：比对 {checked} 条公告，"
                  f"命中 {stored} 条{spent}")
    return {"items": stored, "failures": len(errors), "detail": detail, "errors": errors}


def _run_valuation() -> dict[str, Any]:
    from .repository import refresh_company_valuation

    return _per_company(refresh_company_valuation, "历史估值")


def _run_universe() -> dict[str, Any]:
    from .repository import refresh_market_universe

    result = _attempt(refresh_market_universe)
    detail = (
        f"全 A {result['price_rows']} 只、财务 {result['fundamental_rows']} 条（{result['report_date']} 报告期）、"
        f"指数成分 {result['index_rows']} 条"
    )
    degraded = result["status"] == "降级"
    return {
        "status": result["status"],
        "items": result["price_rows"],
        # 降级是“有数据但能力变窄”，不是一次运行异常；它需要在健康页
        # 明确显示，却不应该被算成连续失败。
        "failures": 0 if result["status"] in {"成功", "降级"} else 1,
        "detail": f"{detail}（行情源降级，部分估值字段缺失）" if degraded else detail,
        "errors": result["notes"],
    }


def _run_sw_industries() -> dict[str, Any]:
    """申万行业分类。**单独一个作业，不塞进底座里。**

    我第一版是把它挂在「全市场底座」后面的，那是错的，而且立刻就出事了：
    底座是日更、几秒钟的事，这个要发 131 次请求跑三分钟——挂在一起之后
    底座作业的耗时变得不可预测，**而测试里那条跑底座的用例当场去连了外网，
    整套测试从 4.5 分钟变成十八分钟还没结束**。

    拆开还有一个好处：它有自己的一行状态。「申万分类 5202 只」看得见，
    塞在底座那行里只是一句更长的话，没人会读。

    间隔按周排：行业成分一年调整一两次，而 refresh_sw_industries 里
    还有一道覆盖率闸门，够了就直接跳过（实测 171 秒 → 0.05 秒）。
    """
    from .repository import refresh_sw_industries

    result = _attempt(refresh_sw_industries)
    return {
        "items": result["matched"],
        "failures": len(result["failed"]),
        "detail": result["note"],
        "errors": ([f"这几个行业没取到：{'、'.join(result['failed'][:8])}"]
                   if result["failed"] else []),
    }


def _run_sentiment() -> dict[str, Any]:
    from .repository import refresh_market_sentiment

    result = _attempt(refresh_market_sentiment)
    return {
        "items": result["rows"],
        "failures": 0 if result["status"] == "成功" else 1,
        "detail": (f"全市场 {result['rows']} 只的人气排名与关注指数"
                   f"（{result.get('trade_date') or '交易日不详'}），"
                   f"其中 {result['with_followers']} 只带雪球关注人数"),
        "errors": result["notes"],
    }


def _run_trend() -> dict[str, Any]:
    from .repository import refresh_market_trend

    result = _attempt(refresh_market_trend)
    # 部分榜单挂掉要判「部分失败」，不能因为主力那份成功就报成功——
    # 报成功的话，缺了两列的数据在页面上跟完整的一模一样。
    stale = f"；{len(result['missing'])} 组信号沿用上次的值" if result["missing"] else ""
    return {
        "items": result["matched"],
        "failures": 0 if result["status"] == "成功" else 1,
        "detail": (f"{len(result['synced'])}/4 个榜单到位，{result['rows']} 只上榜、"
                   f"对上底座 {result['matched']} 只；"
                   f"顺手补了 {result['turnover_filled']} 只的换手率{stale}"),
        "errors": result["notes"],
    }


def _run_financials() -> dict[str, Any]:
    from .repository import refresh_company_financials

    return _per_company(refresh_company_financials, "定期报告")


JOBS: tuple[SyncJob, ...] = (
    SyncJob("quotes", "实时行情快照", "行情", 30, 24, True, _run_quotes, "价格、涨跌幅、PE/PB 与当日估值快照"),
    SyncJob("price_history", "前复权日线", "行情", 720, 48, True, _run_price_history, "区间表现与走势图所依赖的日线"),
    SyncJob("profile", "公司简况与公告", "披露", 1440, 72, False, _run_profile, "公司资料、分红、解禁与公告；新公告会进入待核验收件箱"),
    SyncJob("inbox_tidy", "收件箱自动整理", "披露", 1440, 72, False, _run_inbox_tidy, "只用规则：实质变化自动归档为证据，程序性自动忽略，拿不准的留在收件箱等你点「模型分级」。后台默认不调模型（STOCK_BACKGROUND_AI=1 可开）"),
    # **排在 profile 后面是有讲究的**：新公告刚进收件箱，正是该拿它撞一次认错条件的时刻。
    SyncJob("counter_match", "反证条件比对", "披露", 1440, 72, False, _run_counter_match,
            "把新公告拿去撞你写下的「什么情况算我错」。**要过模型，所以默认不跑**——"
            "在收件箱页面勾上「后台每天替我分级」才会自动比对；没勾也能随时手动点一次"),
    SyncJob("valuation", "历史估值序列", "估值", 1440, 72, False, _run_valuation, "PE(TTM) 与 PB 的近五年序列，用于分位计算"),
    SyncJob("financials", "定期报告", "财务", 10080, 720, False, _run_financials, "利润表、现金流量表与资产负债表"),
    # **30 分钟，不是一天一次。**
    #
    # 一天一次的后果实测到了：2026-08-17 那天它 09:33 跑完（开盘后三分钟），
    # 于是整个交易日里首页的云图和市场脉搏都停在「69% 股票下跌」——
    # 而当天收在 +1.26%、涨 4196 跌 1194。**数据的日期是对的，时间是错的**，
    # 而页面上只印日期，所以它看起来完全新鲜。
    #
    # 跟 quotes（30 分钟）对齐：那张表本来就是同一批行情的全市场版，
    # 两个刷新频率差 48 倍，「我的公司」是新的、上面的云图是开盘那一刻的，
    # 这个反差比两个都旧更迷惑人。
    SyncJob("universe", "全市场底座", "全市场", 30, 72, True, _run_universe, "全 A 与主要指数的行情、估值与财务核心指标，供云图与候选清单使用"),
    # 一周一次就够：行业成分一年调整一两次，而且函数里还有覆盖率闸门。
    SyncJob("sw_industries", "申万行业分类", "全市场", 10080, 720, False, _run_sw_industries,
            "申万一级／二级行业分类。**行业特有指标全靠它选对指标**——"
            "没有它的时候，「白酒看合同负债」这条对 12 家档案公司一次都没触发过"),
    SyncJob("sentiment", "全市场情绪面", "全市场", 1440, 72, True, _run_sentiment,
            "千股千评的人气排名、关注指数与机构参与度，外加雪球关注人数。"
            "**人气反着读**：排名越靠前说明已经被充分讨论，对长期研究者是减分项"),
    # 排在情绪面之后：换手率要从千股千评那份里取，情绪面先跑完才有得取。
    SyncJob("trend", "全市场趋势面", "全市场", 1440, 72, True, _run_trend,
            "同花顺的量价齐升、向上突破 60 日均线、创新高、持续放量四个榜单，"
            "外加补上换手率。**行情快照降级到新浪后，60 日涨跌与换手率在库里覆盖率是 0**，"
            "东财那两条能给区间涨跌的路都被挡着，趋势只能走榜单"),
)

JOBS_BY_ID = {job.job_id: job for job in JOBS}


def _next_run_after(job: SyncJob, moment: datetime) -> datetime:
    candidate = moment + timedelta(minutes=job.interval_minutes)
    if job.weekdays_only:
        while candidate.weekday() >= 5:  # A 股周末不开市，没必要空跑
            candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    return candidate.replace(microsecond=0)


def ensure_schedules() -> None:
    """把任务定义写进本地库。

    ## 间隔要跟着代码走，开关不要

    原来这里对已存在的行只更新名字和新鲜度，**间隔一律不动** ——
    理由是"不覆盖用户改过的"。而后果实测到了：把 universe 从 1440 分钟改成 30，
    部署完库里那一行还是 1440，下次运行仍然是明天 09:33。
    **同一个概念写了两份（代码常量 + 库里的行），而库里那份赢了。**
    改完部署完、日志干净、什么都没报错，只是没生效。

    现在：**间隔以代码为准**（它是产品决定，不是偏好），`enabled` 仍然归用户。
    间隔改小之后 `next_run_at` 也要一起往前挪 —— 不挪的话新间隔要等旧的那一轮
    跑完才生效，而那正是这次要修的那件事（等到明天）。

    ## 但用户改过的不能覆盖

    间隔本来就是可改的（`PATCH /sync/jobs/{id}`）。让代码一律覆盖会把那个功能
    弄坏 —— 门禁里 `test_sync_jobs_expose_schedule_and_health` 当场红了。
    所以记一个 `interval_overridden`：**代码管默认值，用户改过的不动。**
    """

    first_run = (datetime.now() + timedelta(minutes=2)).replace(microsecond=0).isoformat()
    with connection() as conn:
        for job in JOBS:
            conn.execute(
                """
                INSERT INTO sync_schedules (
                    job_id, display_name, category, interval_minutes, weekdays_only, enabled,
                    freshness_hours, next_run_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    category = excluded.category,
                    freshness_hours = excluded.freshness_hours,
                    -- **使用者自己改过的不动**（PATCH /sync/jobs 会把标记置 1）。
                    interval_minutes = CASE WHEN sync_schedules.interval_overridden = 1
                        THEN sync_schedules.interval_minutes
                        ELSE excluded.interval_minutes END,
                    -- **只在间隔真的变小时才把下次运行提前。**
                    --
                    -- 这一行原来是「现有时间晚于 now+2min 就拉到 now+2min」，
                    -- 意图是"间隔改小了别等旧的那一轮跑完"。但它没有限定条件，
                    -- 于是**每次服务启动都把所有作业拉到两分钟后一起到期**。
                    --
                    -- 线上实测（2026-08-18）：当天服务重启 51 次（每次部署一次），
                    -- 于是所有作业每天被重排几十回。而调度器每轮只跑 due[0]、
                    -- 按固定顺序取，前四个（quotes / price_history / profile /
                    -- inbox_tidy）就把产能吃光了 —— 排第 8 的「全市场底座」
                    -- **整整一天多没跑过一次**，而它的间隔明明是 30 分钟。
                    --
                    -- 现在只有两种情况提前：这一行是新建的（NULL），
                    -- 或者间隔真的被调小了（新间隔 < 库里那个）。
                    next_run_at = CASE
                        WHEN sync_schedules.interval_overridden = 1 THEN sync_schedules.next_run_at
                        WHEN sync_schedules.next_run_at IS NULL THEN excluded.next_run_at
                        WHEN excluded.interval_minutes < sync_schedules.interval_minutes
                             AND sync_schedules.next_run_at > excluded.next_run_at
                             THEN excluded.next_run_at
                        ELSE sync_schedules.next_run_at END
                """,
                (
                    job.job_id,
                    job.display_name,
                    job.category,
                    job.interval_minutes,
                    1 if job.weekdays_only else 0,
                    job.freshness_hours,
                    first_run,
                ),
            )


def _schedule_rows() -> list[dict[str, Any]]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM sync_schedules").fetchall()]


def _run_is_stale(row: dict[str, Any], moment: datetime) -> bool:
    """标记为运行中但早已超过墙钟上限的，按未完成处理，否则这个任务会永远排不上队。"""

    started = row.get("last_started_at")
    if not started:
        return True
    return (moment - datetime.fromisoformat(started)).total_seconds() > JOB_TIMEOUT_SECONDS


def _health_of(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    last_success = row.get("last_success_at")
    age_hours = None
    if last_success:
        age_hours = round((now - datetime.fromisoformat(last_success)).total_seconds() / 3600, 1)
    if not row.get("enabled"):
        status, message = "已停用", "自动同步已关闭，仍可手动运行"
    elif row.get("last_status") == "运行中":
        if _run_is_stale(row, now):
            status, message = "有失败", "上一次运行没有正常结束（可能是来源无响应），下次排期会重新运行"
        else:
            status, message = "运行中", "正在同步"
    elif row.get("last_status") == "中断":
        # 被服务重启打断的。**这不算失败**（那一轮没跑完，不是跑坏了），
        # 但也不能当成正常：数据没更新，而下一轮什么时候到还得看排期。
        status, message = "有失败", "上一次运行被服务重启打断，下次排期会重新运行"
    elif row.get("last_status") == "降级":
        status, message = "降级", row.get("last_error") or "本次同步使用了备用数据源，部分字段可能缺失"
    elif last_success is None:
        status, message = "从未成功", "尚未成功同步过，可点击立即运行"
    elif age_hours is not None and age_hours > row["freshness_hours"]:
        status = "已过期"
        message = f"距上次成功已 {age_hours:.0f} 小时，超过期望的 {row['freshness_hours']} 小时"
    elif row.get("consecutive_failures"):
        status = "有失败"
        message = f"最近连续 {row['consecutive_failures']} 次失败，仍在用上一次成功的数据"
    else:
        status, message = "正常", f"距上次成功 {age_hours:.1f} 小时" if age_hours is not None else "正常"
    # needs_attention 跟着 health 一起出去：**判定只在后端发生一次**，
    # 前端拿到布尔值直接用，不再自己维护一份"哪几种算有问题"的名单。
    return {"health": status, "health_message": message, "age_hours": age_hours,
            "needs_attention": needs_attention(status)}


def list_jobs() -> list[dict[str, Any]]:
    ensure_schedules()
    now = datetime.now().replace(microsecond=0)
    jobs = []
    for row in _schedule_rows():
        job = JOBS_BY_ID.get(row["job_id"])
        if not job:
            continue
        row["enabled"] = bool(row["enabled"])
        row["weekdays_only"] = bool(row["weekdays_only"])
        row["description"] = job.description
        row.update(_health_of(row, now))
        jobs.append(row)
    order = {job.job_id: index for index, job in enumerate(JOBS)}
    jobs.sort(key=lambda item: order.get(item["job_id"], 99))
    return jobs


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*, s.display_name FROM sync_runs r
            LEFT JOIN sync_schedules s ON s.job_id = r.job_id
            ORDER BY r.started_at DESC, r.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_job(job_id: str, enabled: bool | None = None, interval_minutes: int | None = None) -> dict[str, Any] | None:
    if job_id not in JOBS_BY_ID:
        return None
    job = JOBS_BY_ID[job_id]
    with connection() as conn:
        row = conn.execute("SELECT * FROM sync_schedules WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        if enabled is not None:
            conn.execute("UPDATE sync_schedules SET enabled = ? WHERE job_id = ?", (1 if enabled else 0, job_id))
        if interval_minutes is not None:
            next_run = _next_run_after(job, datetime.now())
            conn.execute(
                # **置上 overridden**：从此这一行的间隔归使用者，
                # ensure_schedules 不再拿代码里的默认值覆盖它。
                "UPDATE sync_schedules SET interval_minutes = ?, next_run_at = ?, "
                "interval_overridden = 1 WHERE job_id = ?",
                (interval_minutes, next_run.isoformat(), job_id),
            )
    return next((item for item in list_jobs() if item["job_id"] == job_id), None)


def _finish_run(
    run_id: int,
    job_id: str,
    status: str,
    error: str | None,
    items: int,
    failures: int,
    detail: str,
    finished: datetime,
    next_run: datetime,
) -> None:
    for attempt in range(2):
        try:
            with connection() as conn:
                conn.execute(
                    """
                    UPDATE sync_runs SET finished_at = ?, status = ?, items = ?, failures = ?, error = ?, detail = ?
                    WHERE id = ?
                    """,
                    (finished.isoformat(), status, items, failures, error, detail, run_id),
                )
                conn.execute(
                    """
                    UPDATE sync_schedules SET
                        last_finished_at = ?,
                        last_status = ?,
                        last_error = ?,
                        last_items = ?,
                        last_success_at = CASE WHEN ? IN ('成功', '部分失败', '降级') THEN ? ELSE last_success_at END,
                        consecutive_failures = CASE WHEN ? IN ('成功', '降级') THEN 0 ELSE consecutive_failures + 1 END,
                        next_run_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        finished.isoformat(),
                        status,
                        error,
                        items,
                        status,
                        finished.isoformat(),
                        status,
                        next_run.isoformat(),
                        job_id,
                    ),
                )
            return
        except Exception as exc:
            logger.warning("recording sync result for %s failed (attempt %s): %s", job_id, attempt + 1, exc)
            time.sleep(1)


def run_job(job_id: str, trigger: str = "手动") -> dict[str, Any] | None:
    """同步执行一个任务并记录结果；异常在这里被吃掉，只落到运行记录里。

    任务体一律跑在**系统域**（scope=None，不过滤）：同步是替所有用户拉数据的。
    手动触发时请求上下文带着触发者的域，不清掉的话「立即运行」只会同步他自己的公司，
    而定时触发同步所有人——同一个按钮两种行为，没人能查明白。
    需要按域处理的任务（收件箱整理）在任务体内自己逐域循环。
    """
    from . import access

    scope_token = access.set_scope(None)
    try:
        return _run_job_scoped(job_id, trigger)
    finally:
        access.reset_scope(scope_token)


def _run_job_scoped(job_id: str, trigger: str = "手动") -> dict[str, Any] | None:
    job = JOBS_BY_ID.get(job_id)
    if not job:
        return None
    ensure_schedules()  # 手动触发可能早于调度器启动，先保证登记行存在
    global _ACTIVE_RUN
    with _RUN_LOCK:
        active = _ACTIVE_RUN
        # 卡死的线程不能永久占住位置：超过墙钟上限就允许新的任务顶上。
        if active and time.monotonic() - active[1] < JOB_TIMEOUT_SECONDS:
            return {
                "job_id": job_id,
                "status": "已跳过",
                "items": 0,
                "failures": 0,
                "detail": f"{JOBS_BY_ID[active[0]].display_name}正在运行，稍后再试",
                "error": None,
                "started_at": now_iso(),
                "finished_at": now_iso(),
                "next_run_at": _next_run_after(job, datetime.now()).isoformat(),
            }
        _ACTIVE_RUN = (job_id, time.monotonic())
    started = datetime.now().replace(microsecond=0)
    with connection() as conn:
        conn.execute(
            "UPDATE sync_schedules SET last_started_at = ?, last_status = '运行中' WHERE job_id = ?",
            (started.isoformat(), job_id),
        )
        cursor = conn.execute(
            "INSERT INTO sync_runs (job_id, trigger, started_at, status) VALUES (?, ?, ?, '运行中')",
            (job_id, trigger, started.isoformat()),
        )
        run_id = int(cursor.lastrowid)

    status = "成功"
    error: str | None = None
    items = 0
    failures = 0
    detail = ""
    try:
        result = job.runner()
        items = int(result.get("items", 0))
        failures = int(result.get("failures", 0))
        detail = str(result.get("detail", ""))
        # 个别任务（目前是全市场底座）能明确区分“成功但使用备用源”。
        # 这个状态必须一路写进运行记录和健康卡，否则会被 failures=0 抹成普通成功。
        runner_status = result.get("status")
        if runner_status in {"成功", "降级"}:
            status = runner_status
        if failures:
            status = "部分失败"
            error = "；".join(result.get("errors", [])[:3])
    except Exception as exc:
        status = "失败"
        error = str(exc)
        detail = "任务未完成"
        logger.warning("sync job %s failed: %s", job_id, exc)
    finally:
        with _RUN_LOCK:
            if _ACTIVE_RUN and _ACTIVE_RUN[0] == job_id:
                _ACTIVE_RUN = None

    finished = datetime.now().replace(microsecond=0)
    next_run = _next_run_after(job, finished)
    # 收尾写库本身也可能失败（例如同一时刻页面正在写）。这里重试一次，
    # 并且无论如何都不让状态停在"运行中"——那会让这个任务永远排不上队。
    _finish_run(run_id, job_id, status, error, items, failures, detail, finished, next_run)
    return {
        "job_id": job_id,
        "status": status,
        "items": items,
        "failures": failures,
        "detail": detail,
        "error": error,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "next_run_at": next_run.isoformat(),
    }


def due_job_ids(now: datetime | None = None) -> list[str]:
    moment = (now or datetime.now()).replace(microsecond=0)
    due: list[str] = []
    for row in _schedule_rows():
        job = JOBS_BY_ID.get(row["job_id"])
        if not job or not row["enabled"]:
            continue
        if row["last_status"] == "运行中" and not _run_is_stale(row, moment):
            continue
        if job.weekdays_only and moment.weekday() >= 5:
            continue
        next_run = row.get("next_run_at")
        if next_run is None or datetime.fromisoformat(next_run) <= moment:
            due.append(row["job_id"])
    # **按"等了多久"排，不按固定顺序。**
    #
    # 原来是 `due.sort(key=JOBS 里的位置)`，而调度器每轮只跑 due[0] ——
    # 于是只要排在前面的作业总是到期，后面的就**永远轮不到**。
    #
    # 线上实测（2026-08-18）：当天只有前四个作业跑过（quotes / price_history /
    # profile / inbox_tidy），第 5 位往后一个都没跑过。排第 8 的「全市场底座」
    # 间隔是 30 分钟，而它一天多没跑过一次 —— 页面上的表现是数据停在昨天，
    # 而作业状态写着「降级」、没有任何错误信息。**它没失败，是根本没轮到。**
    #
    # 改成按 next_run_at 升序：谁欠得最久谁先跑。同样是每轮一个，
    # 但每个作业最终都会排到队头，不会被前面的饿死。
    overdue = {row["job_id"]: row.get("next_run_at") or "" for row in _schedule_rows()}
    due.sort(key=lambda job_id: overdue.get(job_id) or "")
    return due


# 连续失败几次算「坏了」。1 次可能是网络抖动，2 次可能是运气差，
# 3 次就是那个源真的出问题了——这时候页面上必须说出来，而不是让人自己去数据状态页翻。
ALERT_AFTER_FAILURES = 3
# 数据多久没更新算「过期到会误导判断」。行情 1 天、财务 1 周不更新性质完全不同，
# 所以按各作业自己的间隔算：超过预定间隔的 3 倍就是明显不对了。
STALE_INTERVAL_MULTIPLE = 3


# 哪几种健康状态算「需要关注」。**这张表是唯一真源。**
#
# 2026-08-16 主动排查「同一个概念写了两份」时抓到的：后端这边算的是四种
# （已过期 / 有失败 / 从未成功 / **降级**），而数据状态页在前端**自己又写了一份**，
# 只有三种 —— 少了「降级」。
#
# 后果是首页和它自己那一页说的不是同一件事：线上此刻就有一个任务是「降级」，
# 假如它是唯一的问题，首页会写「11 个同步任务：正常 10 · 降级 1」，
# 而点进数据状态页看到的是 **「11 个任务正常」**。
#
# 而「降级」恰恰是最值得说的那一种：它是「有数据但能力变窄」——
# 行情源降级到备用之后，60 日涨跌与换手率在库里的覆盖率直接是 0（见上面那段注释），
# 页面照常渲染、数字照常显示，只是有几列悄悄空了。
#
# 所以不是把词补到前端那份名单里，而是**让前端不再有名单**：
# 每个任务带一个 needs_attention 出去，判定只发生在这里一处。
TROUBLE_HEALTH = ("已过期", "有失败", "从未成功", "降级")


def needs_attention(health: str) -> bool:
    return health in TROUBLE_HEALTH


def alerts() -> list[dict[str, Any]]:
    """需要你知道的同步问题。

    **为什么要主动报而不是等人去看。** 数据同步坏掉是静默的：页面照常渲染，
    数字照常显示，只是它们停在了三天前。而这个产品的全部判断都建立在那些数字上——
    简报会拿着过期行情说「今天」，候选清单会按过期财务排序。
    坏了要说出来，而且要说清楚**哪一块的判断因此不能信**。
    """
    out: list[dict[str, Any]] = []
    for job in list_jobs():
        failures = int(job.get("consecutive_failures") or 0)
        if failures >= ALERT_AFTER_FAILURES:
            out.append({
                "level": "严重",
                "job_id": job["job_id"],
                "title": f"{job['display_name']}连续失败 {failures} 次",
                "detail": (job.get("last_error") or "没有留下错误信息")[:200],
                "impact": job.get("description") or "",
            })
            continue
        if job.get("health") == "降级":
            out.append({
                "level": "提醒",
                "job_id": job["job_id"],
                "title": f"{job['display_name']}使用备用数据源",
                "detail": job.get("health_message") or "部分字段可能缺失",
                "impact": job.get("description") or "",
            })
            continue
        age = job.get("age_hours")
        interval = (job.get("interval_minutes") or 0) / 60
        if age is not None and interval and age > interval * STALE_INTERVAL_MULTIPLE:
            out.append({
                "level": "提醒",
                "job_id": job["job_id"],
                "title": f"{job['display_name']}已经 {age:.0f} 小时没有更新",
                "detail": f"预定每 {interval:.0f} 小时一次；上次状态：{job.get('last_status') or '未知'}",
                "impact": job.get("description") or "",
            })
    return out


def health_summary() -> dict[str, Any]:
    jobs = list_jobs()
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job["health"]] = counts.get(job["health"], 0) + 1
    parts = [f"{status} {count}" for status, count in counts.items()]
    return {"jobs": len(jobs), "counts": counts,
            "summary": " · ".join(parts) if parts else "尚未登记同步任务",
            "alerts": alerts()}


def _mark_timeout(job_id: str) -> None:
    job = JOBS_BY_ID.get(job_id)
    if not job:
        return
    finished = datetime.now().replace(microsecond=0)
    next_run = _next_run_after(job, finished)
    with connection() as conn:
        conn.execute(
            """
            UPDATE sync_schedules SET last_status = '超时', last_finished_at = ?, last_error = ?,
                consecutive_failures = consecutive_failures + 1, next_run_at = ?
            WHERE job_id = ?
            """,
            (finished.isoformat(), f"超过 {JOB_TIMEOUT_SECONDS // 60} 分钟仍未返回，已放弃本次运行", next_run.isoformat(), job_id),
        )
        conn.execute(
            "UPDATE sync_runs SET status = '超时', finished_at = ?, error = '来源长时间无响应' WHERE job_id = ? AND status = '运行中'",
            (finished.isoformat(), job_id),
        )


def _release_runs_from_a_dead_process() -> None:
    """启动时把上一个进程留下的「运行中」放掉。

    **进程都没了，那个「运行中」一定是死的。** 而系统原来要等满墙钟上限
    （15 分钟）才敢重排它 —— 见 `_run_is_stale`。

    这在今天的实测里是笔真账：服务当天重启了 51 次（每部署一次重启一次），
    而 price_history 每轮要跑十分钟 —— 它几乎每次都被重启打断，
    然后又白等 15 分钟才轮得上，于是一天下来真正跑完的次数寥寥。

    只放「运行中」，不动别的状态；也不改 next_run_at ——
    什么时候该跑由排期说了算，这里只是把门闩拔掉。
    """
    from .database import connection

    with connection() as conn:
        released = conn.execute(
            "UPDATE sync_schedules SET last_status = '中断', "
            "last_error = '上一次运行被服务重启打断（进程已退出）' "
            "WHERE last_status = '运行中'").rowcount
        conn.execute(
            "UPDATE sync_runs SET status = '中断', "
            "error = '上一次运行被服务重启打断（进程已退出）' "
            "WHERE status = '运行中'")
    if released:
        logger.info("released %s stuck job(s) left by a previous process", released)


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    """每分钟检查一次；每轮最多跑一个任务，避免刚打开程序时同时打满所有来源。"""

    ensure_schedules()
    _release_runs_from_a_dead_process()
    while not stop_event.is_set():
        try:
            due = due_job_ids()
            if due:
                job_id = due[0]
                logger.info("running scheduled sync job %s", job_id)
                try:
                    await asyncio.wait_for(asyncio.to_thread(run_job, job_id, "调度"), timeout=JOB_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    logger.warning("sync job %s exceeded %ss", job_id, JOB_TIMEOUT_SECONDS)
                    _mark_timeout(job_id)
        except Exception as exc:  # 调度器自身不能因为一次异常退出
            logger.warning("scheduler tick failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_SECONDS)
        except asyncio.TimeoutError:
            continue


def stale_since(hours: int) -> str:
    return (date.today() - timedelta(hours=hours)).isoformat()


def run_strip(per_job: int = 24) -> list[dict[str, Any]]:
    """每个作业最近 N 次的成败，画成一排小方块用。

    **列表看不出规律。** 同步记录按时间倒序排一屏，你只看得到最近十几条属于
    哪个作业；而「quotes 这个作业三分之一在失败」这种事，要把同一作业的历史
    排成一行才看得出来——实测就是这样：106 次成功、35 次失败，而页面上从没显出来过。

    今天三次卡壳（两次数据陈旧、一次策略全 0）根子都是「某个作业其实一直没跑对」。
    """
    from .database import connection

    with connection() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT job_id, status, started_at, finished_at, detail, error
               FROM sync_runs ORDER BY id DESC""").fetchall()]

    by_job: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = by_job.setdefault(row["job_id"], [])
        if len(bucket) < per_job:
            bucket.append(row)

    out = []
    for job in JOBS:
        history = by_job.get(job.job_id, [])
        failed = sum(1 for r in history if r["status"] in ("失败", "超时"))
        out.append({
            "job_id": job.job_id,
            "name": job.display_name,
            "category": job.category,
            # 从旧到新：条带要跟时间轴同向，否则「最近变好了」会被读成「最近变差了」
            "runs": [{
                "status": r["status"],
                "at": str(r["started_at"] or "")[:16],
                "note": (r["error"] or r["detail"] or "")[:160],
            } for r in reversed(history)],
            "failed": failed,
            "total": len(history),
        })
    return out
