import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
import logging
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import ValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import access, assistant, assistant_agent, assistant_research, llm
from .database import integrity_errors
from .llm import credit_state
from .database import database_path, initialize_database
from .backup import BackupError, backup_file, create_backup, export_records, list_backups, local_data_summary, restore_backup
from .company_profile import CompanyProfileError
from .scheduler import ensure_schedules, run_strip, health_summary, list_jobs, list_runs, run_job, scheduler_loop, update_job
from .financial_data import FinancialDataError
from .valuation_data import ValuationDataError
from .market_data import MarketDataError, MarketQuoteNotFoundError, MarketSymbolError
from .background import latest_job, list_jobs as list_background_jobs, recover_stale_jobs, submit
from .background import update_job as update_background_job
from .repository import (
    archive_inbox_batch,
    auto_review_task,
    confirm_news,
    confirm_supply_chain_link,
    delete_supply_chain_link,
    list_industry_chain_themes,
    create_industry_chain_theme,
    fork_industry_chain_theme,
    get_industry_chain,
    industry_chain_compare,
    add_industry_chain_stage,
    add_industry_chain_node,
    set_industry_chain_node_market_size,
    add_industry_chain_edge,
    add_industry_chain_position,
    delete_industry_chain_record,
    company_industry_chain_positions,
    generate_briefing,
    generate_report,
    latest_briefing,
    get_company,
    get_research_task,
    get_supply_chain,
    ignore_news,
    delete_news_feed,
    list_news,
    mark_news_read,
    list_news_feeds,
    save_news_feed,
    toggle_news_feed,
    list_reports,
    refresh_news,
    refresh_supply_chain,
    rederive_universe_valuation,
    draft_thesis,
    tidy_inbox,
    method_detail,
    method_library,
    LedgerError,
    archive_inbox_item,
    classify_inbox,
    correction_stats,
    assessment_matrix,
    delete_thesis,
    draft_and_save_thesis,
    value_candidates,
    acknowledge_counter_hit,
    check_counter_hits,
    open_counter_hits,
    list_assessments,
    run_assessment,
    all_settings,
    set_setting,
    save_rule_term,
    delete_rule_term,
    ignore_by_relevance,
    create_company,
    create_company_from_quote,
    create_event,
    create_evidence,
    create_portfolio,
    create_thesis,
    create_research_task,
    create_thesis_review,
    create_trade,
    purge_company_trades,
    delete_portfolio,
    record_fill,
    delete_fill,
    company_fills,
    set_holding,
    drop_holding,
    delete_trade,
    update_portfolio,
    dashboard,
    decision_board,
    export_watchlist,
    get_company,
    import_watchlist,
    industry_comparison,
    get_portfolio,
    ignore_inbox_item,
    list_inbox,
    list_industries,
    list_screen_runs,
    save_candidate_review,
    latest_candidate_review,
    backfill_universe_range_returns,
    market_heatmap,
    market_fund_flow_view,
    market_lens_statuses,
    list_screen_strategies,
    candidate_review_target,
    delete_screen_strategy,
    screen_fields,
    list_portfolios,
    list_provider_statuses,
    list_research_tasks,
    list_revisions,
    list_companies,
    lookup_universe,
    fill_new_archive,
    bootstrap_real_examples,
    quote_preview,
    refresh_company_financials,
    refresh_company_market_history,
    refresh_company_profile,
    refresh_company_valuation,
    reopen_inbox_item,
    review_attribution,
    all_theses,
    review_queue,
    run_screen,
    save_screen_strategy,
    thesis_review_context,
    agent_pool,
    ai_pick_options,
    ai_pick_run,
    decision_attribution,
    company_industry_metrics,
    company_chain_position,
    load_samples,
    remove_samples,
    company_money_flow,
    company_schedule,
    save_document,
    rename_document,
    unverify_bulk_archived_evidence,
    save_digest,
    save_fundraising,
    company_fundraising,
    list_documents,
    get_document,
    delete_document,
    company_timeline,
    company_promises,
    promise_estimate,
    run_devils_advocate,
    # due_promises 曾经挂在这里，而没有任何一个接口用它 —— 这就是那条
    # 「到期了要顶到你面前」为什么一次都没顶过。现在它进了今日概览
    # （repository 里直接调，见 DashboardSummary.promises_due），
    # **不要再在这里 import 一次**：import 得到不等于有人调。
    extract_company_promises,
    save_promises,
    settle_promise,
    portfolio_common_risk,
    quick_thesis_context,
    write_quick_thesis,
    company_valuation,
    save_valuation,
    valuation_drift,
    sentiment_summary,
    trend_summary,
    universe_sample,
    universe_summary,
    universe_valuation_percentile,
    watchlist_groups,
    refresh_all_market_quotes,
    refresh_market_universe,
    update_company,
    update_event,
    update_thesis,
    update_research_task,
    delete_research_task,
    update_task_item,
    update_trade,
    business_segments,
    refresh_business_segments,
    evidence_direction,
    evidence_direction_plan,
    judge_evidence_direction,
    assess_task_item,
    deep_report_plan,
    generate_deep_report,
    add_supply_chain_link,
    delete_report,
    # 我的判断 · 做 T 回测 / 决策闭环 / 上涨类型
    swing_study,
    decision_loop_board,
    decision_card,
    save_decision_card,
    move_decision_state,
    ensure_decision_card,
    evaluate_decision_triggers,
    sync_decision_from_ledger,
    rally_view,
    rally_narration,
    rally_lookup,
)
from .peers import position as peer_position, table as peer_table
from .schemas import (
    ChainCompareView,
    AdvocateAsk,
    PromiseBatch,
    PromiseSettle,
    Billing,
    CompanyFromQuoteInput,
    CompanyDetail,
    CompanyInput,
    CompanyRecord,
    CompanyUpdate,
    DataProviderStatus,
    DashboardSummary,
    DecisionBoard,
    EvidenceCreate,
    EvidenceRecord,
    FinancialRefreshResult,
    CompanyProfileRefreshResult,
    MarketHistoryRefreshResult,
    BackupManifest,
    BackupRestoreResult,
    LocalDataSummary,
    PortfolioCreate,
    PortfolioUpdate,
    FillInput,
    HoldingInput,
    PortfolioDeleted,
    TradePurgeRequest,
    TradePurgeResult,
    PortfolioDetail,
    PortfolioSummary,
    InboxActionResult,
    InboxBatchResult,
    InboxTidyResult,
    NewsFeed,
    NewsFeedInput,
    NewsPage,
    NewsRefreshResult,
    ResearchReport,
    SupplyChainView,
    IndustryChainThemeCreate,
    IndustryChainDraftRequest,
    IndustryChainStageCreate,
    IndustryChainNodeCreate,
    IndustryChainNodeMarketSize,
    IndustryChainEdgeCreate,
    IndustryChainPositionCreate,
    IndustryChainThemeSummary,
    IndustryChainView,
    CompanyIndustryChainPositions,
    BackgroundJob,
    DailyBriefing,
    UniverseRederiveResult,
    ThesisDraft,
    InboxClassifyResult,
    ThesisMethod,
    ThesisMethodLibrary,
    InboxArchive,
    InboxItem,
    InboxPage,
    RecordRevision,
    ResearchTaskCreate,
    ResearchTaskItemUpdate,
    ResearchTaskRecord,
    ResearchTaskUpdate,
    ReviewAttribution,
    ReviewQueueItem,
    SyncJobStatus,
    SyncJobUpdate,
    SyncRunRecord,
    SyncRunResult,
    ValuationRefreshResult,
    IndustryComparison,
    IndustrySummary,
    HeatmapView,
    MarketFundFlowView,
    ScreenAdHoc,
    ScreenField,
    ScreenResult,
    ScreenRunRecord,
    CandidateReviewSave,
    CandidateReviewRecord,
    ScreenStrategy,
    ScreenStrategySave,
    UniversePercentile,
    UniverseRow,
    UniverseSummary,
    WatchGroupSummary,
    WatchlistExportRow,
    WatchlistImport,
    WatchlistImportResult,
    QuotePreview,
    UniverseMatch,
    ResearchEventCreate,
    ResearchEventRecord,
    ResearchEventUpdate,
    ThesisCreate,
    ThesisRecord,
    ThesisReviewContext,
    ThesisReviewCreate,
    ThesisUpdate,
    TradeCreate,
    TradeRecord,
    TradeUpdate,
)

logger = logging.getLogger(__name__)


def _attach_app_logs_to_uvicorn() -> None:
    """让本仓自己的日志跟 uvicorn 走同一条出口。

    ## 为什么需要这一句

    uvicorn 只配置它自己那几个 logger（uvicorn / uvicorn.error / uvicorn.access）。
    本仓各模块用的是 `logging.getLogger(__name__)` —— **没有 handler，
    默认级别 WARNING**，于是所有 `logger.info` 一句都进不了 journal。

    实测撞到的：调度器启动时释放「上一个进程留下的运行中」会打一行 info
    说明放了几个，我去 journal 里找，一行都没有 ——
    行为是对的（造场景验过），但**下次真出问题时你在日志里看不到它做了什么**。

    这里不用 basicConfig：那会给 root 加一个 handler，跟 uvicorn 自己的
    handler 叠在一起，每行日志打两遍。改成把 uvicorn 的 handler 借过来。
    """
    import logging

    # **不能只看 `uvicorn.error` 自己的 handlers。** uvicorn 的 LOGGING_CONFIG 里
    # `uvicorn.error` 只设了 level，handler 挂在父 logger `uvicorn` 上，靠冒泡输出。
    # 第一版写的是 `if not source.handlers: return` —— 线上当场就在这句返回了，
    # 于是这个函数上线之后一行日志都没多出来（守卫测试自己往 `uvicorn.error`
    # 上挂了个 handler 来"模拟 uvicorn"，测的是我的假设，不是 uvicorn 的真实配置）。
    #
    # 按 logging 真正派发的路径往上走：一路收 handler，遇到 propagate=False 就停。
    # **走到 root 之前停下** —— root 上的 handler 不是 uvicorn 的
    # （pytest、basicConfig 都会往那儿挂），认了它就等于"没跑在 uvicorn 下也照挂"。
    borrowed: list[logging.Handler] = []
    node: logging.Logger | None = logging.getLogger("uvicorn.error")
    while node is not None and node.name != "root":
        borrowed.extend(node.handlers)
        node = node.parent if node.propagate else None

    if not borrowed:
        return                     # 不是 uvicorn 起的（测试、脚本），保持安静
    ours = logging.getLogger("stock_decision")
    if ours.handlers:
        return                     # 已经接过了，别重复挂
    for handler in borrowed:
        ours.addHandler(handler)
    ours.setLevel(logging.INFO)
    ours.propagate = False         # 已经有 handler 了，再往上冒会打两遍


@asynccontextmanager
async def lifespan(_: FastAPI):
    _attach_app_logs_to_uvicorn()
    # **建表必须排在第一位。** 下面每一步都要读写数据库，而 recover_stale_jobs
    # 第一句就查 background_jobs —— 原来它排在建表之前，
    # 在一个全新的库上直接 `no such table: background_jobs` 然后进程退出。
    #
    # 线上一直没炸只是因为那张表早就建好了；换机器、换库、从备份重建，
    # 第一次启动就会起不来。而"第一天"恰恰是最少被跑到的状态。
    initialize_database()
    # 服务重启会让运行中的后台任务凭空消失，标成中断而不是永远显示运行中
    recover_stale_jobs()
    try:
        bootstrap_real_examples()
    except MarketDataError as exc:
        logger.warning("StockSDK starter sync skipped: %s", exc)
    ensure_schedules()
    _refuse_to_serve_without_isolation()
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(scheduler_loop(stop_event))
    # 助理盯盘单独一条循环，**不进调度器**：调度器同一时间只跑一个作业，
    # 一个几分钟的全量同步就能把「到价五分钟内告诉你」拖黄。默认关，.env 里开。
    watch_task = (asyncio.create_task(assistant.watch_loop(stop_event))
                  if assistant.watch_enabled() else None)
    try:
        yield
    finally:
        stop_event.set()
        for task in (scheduler_task, watch_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # 关闭时不因后台循环报错影响退出
                pass

def _refuse_to_serve_without_isolation() -> None:
    """开着多用户、却没有数据库层强制隔离时，**拒绝启动**。

    这两件事凑在一起才危险：只有站主能进的时候，隔离失效也没人能利用它。
    所以只在 multi/auto 姿态下检查，单机开发和 owner 模式不受影响。

    ## 为什么从"警告"升成"不启动"

    原来这里只写一条 warning 就继续对外服务了。而这条警告说的是
    **别人的研究记录可能被读到**——它跟"某个数据源今天没同步"不是一个量级，
    却用了同一种表达方式（日志里一行黄字，没人会看）。

    行级安全装不上有两种常见原因：连库的角色带 BYPASSRLS（云库主账号默认带），
    或者某张表的策略建失败了。两种都不是"过一会儿会自己好"的问题，
    继续跑只是把泄漏窗口拉长。所以让它在启动这一刻就停下，
    修好再起——修法在报错里写清楚了。
    """
    from .database import backend

    if backend() != "postgres" or access.mode() == "owner":
        return
    try:
        from . import pgbackend

        status = pgbackend.rls_status()
    except Exception as exc:
        logger.warning("查不到行级安全状态：%s", exc)
        return
    if not status["effective"]:
        raise RuntimeError(
            f"多用户模式（access={access.mode()}）下行级安全没有生效，拒绝启动。\n"
            f"  角色 {status['role']}｜绕过 RLS={status['bypasses_rls']}｜"
            f"受保护表 {status['protected_tables']}/{status['expected_tables']}\n"
            "  此时某条 SQL 忘了加数据域过滤就是静默泄漏——别人的研究记录会被读到。\n"
            "  修法：跑 scripts/setup_rls_role.py 换成不绕过 RLS 的专用角色；\n"
            "  确实只想自己用的话，把 .env 的 STOCK_ACCESS 设成 owner。")


app = FastAPI(
    title="虾米看股 API",
    summary="面向价值投资研究流程的数据与证据接口",
    version="0.15.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # 正常使用从主站的 /stocks 进入，浏览器看到的来源是 3000；
    # 5217 只是 Vite 内部开发端口，保留它便于本地调试但不作为产品入口。
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:5217",
        "http://localhost:5217",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


@app.middleware("http")
async def credit_context(request, call_next):
    """把「这次请求是谁发的」放进 contextvar，供深处的模型调用记账。

    只取 Cookie 头原样转发，**本进程不解析它、也不知道 user_id**——身份由主站认。
    这条边界是刻意的：本进程即使被攻破，也只能拿着受害者自己的 Cookie 扣他自己的分，
    没法遍历用户。

    `asyncio.create_task` 与 `asyncio.to_thread` 都会复制当前 context，所以从页面点出去的
    后台任务（同步档案、生成简报）自然记在点它的人头上；夜间调度器不在请求里跑，
    落到 llm.background_principal()。
    """
    cookie = request.headers.get("cookie") or ""

    # **先守门，再记账。**
    #
    # 本仓 33 张表没有一张带 user_id：所有数据是「这台机器上的唯一一份」。
    # 这对本地单机工作台是对的，但挂到公网之后就意味着谁能连上谁就拥有全部数据——
    # 实测过：不带 Cookie 读到全部档案、POST 建公司返回 201。
    # 所以这一层守的是「唯一那份数据」，不是「区分不同用户的数据」（见 access.py）。
    scope_token = None
    owner_token = None
    if request.url.path.startswith("/api/"):
        try:
            grant = access.check(cookie)
        except access.AccessDenied as exc:
            return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)
        # **游客只读。**
        #
        # 游客拿到的是一个自己什么都不拥有的数据域（access.GUEST_SCOPE），
        # 所有游客共用它。放开写就意味着游客甲建的公司档案出现在游客乙那里，
        # 而且没人能删。挡在这一处，不在一百个接口上各写一次。
        #
        # 顺带把花钱也挡住了：会调模型的动作全是 POST。
        # **监测上报是这条规则的唯一例外。** 它是写请求，但写的不是研究数据：
        # 只有几个毫秒数、一个白名单里的页面名和设备大类（见 rum.py）。
        # 而没登录的那次访问同样值得知道快不快 —— 把它挡在门外，
        # 收上来的样本就只剩登录用户，"首屏慢"这类问题恰恰最常发生在第一次打开。
        #
        # 上线后才发现的：本机冒烟跑的是 STOCK_ACCESS=open 的实例，那种姿态下
        # 根本走不到这条守卫，于是 401 一直到公网才露头。
        if grant.get("is_guest") and request.method not in {"GET", "HEAD", "OPTIONS"} \
                and request.url.path != "/api/v1/rum":
            return JSONResponse(
                {"detail": "登录虾米伙伴之后才能建档案、写判断。行情和公开资料不用登录也能看。",
                 "code": "guest_readonly"}, status_code=401)
        # 这次请求从此只看得见自己域里的数据（站主 = 存量数据域）。
        # asyncio.to_thread / create_task 都会复制 context，后台任务自然继承同一个域。
        scope_token = access.set_scope(grant["scope"])
        # 备份/还原这类整实例操作要按人挡（access.require_owner），按域过滤救不了它们。
        owner_token = access.set_owner_flag(grant["is_owner"])

    p_token = llm.set_principal(llm.Principal(cookie=cookie) if cookie else None)
    a_token = llm.start_accounting()
    try:
        return await call_next(request)
    finally:
        llm.reset_accounting(a_token)
        llm.reset_principal(p_token)
        if owner_token is not None:
            access.reset_owner_flag(owner_token)
        if scope_token is not None:
            access.reset_scope(scope_token)


@app.get("/api/v1/access")
def get_access() -> dict:
    """当前的访问姿态。给「数据状态」页说明用。"""
    return access.describe()


@app.get("/api/v1/credits/state")
def get_credit_state() -> dict:
    """本模块的计费口径与当前账户余额，给设置页说明用。查不到就如实说查不到。

    连同**未计费台账**一起返回：闸口不可用时调用照跑但没计上费，
    那些次数要看得见，否则「这段时间是免费的」只有事后翻日志才知道。
    """
    from . import billing_ledger

    state = credit_state()
    state["unbilled"] = billing_ledger.state()
    return state


@app.post("/api/v1/rum", status_code=status.HTTP_204_NO_CONTENT)
async def post_rum_sample(payload: dict) -> Response:
    """收一条真实用户样本。**不鉴权**：它跟 /health 一样不返回任何研究数据，
    而页面在未登录时也可能被打开（那时的慢同样值得知道）。

    收的东西只有毫秒数、页面名（服务端白名单）、设备大类。
    写失败不许影响页面——所以这里吞掉异常，只记日志。
    """
    from . import rum

    try:
        rum.record(payload if isinstance(payload, dict) else {})
    except Exception as exc:
        logger.warning("RUM 样本写入失败：%s", exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/rum/summary")
def get_rum_summary(days: int = Query(default=7, ge=1, le=90)) -> dict:
    """真实用户那边的首屏分位数与报错。**只有站主能看。**"""
    from . import rum

    access.require_owner("查看真实用户监测")
    return rum.summary(days)


@app.get("/api/v1/credits/unbilled")
def get_unbilled_calls(limit: int = Query(default=200, ge=1, le=500)) -> dict:
    """还没对账的未计费调用。**只有站主能看**——这是运营账，不是研究数据。"""
    from . import billing_ledger

    access.require_owner("查看未计费台账")
    return {"rows": billing_ledger.pending(limit), **billing_ledger.state()}


@app.post("/api/v1/credits/unbilled/settle")
def settle_unbilled_calls(payload: dict | None = None) -> dict:
    """对完账了，把当前这批标成已处理。**不删行**：删了就查不回当时漏了多少。"""
    from . import billing_ledger

    access.require_owner("结清未计费台账")
    note = str((payload or {}).get("note") or "")
    settled = billing_ledger.settle(note)
    return {"settled": settled, **billing_ledger.state()}


@app.exception_handler(access.AccessDenied)
async def access_denied_handler(_request, exc: access.AccessDenied):
    """接口内部抛的拒绝（如 require_owner）也要变成正经状态码。

    中间件那层的拒绝自己返回了响应，但 require_owner 是在接口里抛的——
    没有这个处理器它会变成 500，看起来像服务坏了，而不是「你没这个权限」。
    """
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)


@app.exception_handler(llm.CreditsError)
async def credits_error_handler(_request, exc: llm.CreditsError):
    """额度不足是「你需要充值」，不是「服务坏了」。504/503 会让人一直重试，402 才说得清。"""
    return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=402)


def not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")


def charged(completion: Any, quoted: int) -> int:
    """事后要报的是**实扣**，不是事前那个估价。

    使用者报过这个：「弹窗显示这次大概花 约 17 分。但实际是冻结 7 积分、花费 3 积分」。
    事前只能估（还没调模型，不知道它会写多长），事后不该再估 —— 网关已经按真实
    token 结过账了，那个数就摆在 `completion.billing()` 里。

    **两个数不一致会直接毁掉这个功能的可信度**：页面说「本次 6 分」而余额掉了 3 分，
    读的人接下来会怀疑页面上每一个数字，包括那些从年报里读出来的。
    没走计量（本地调试、没配网关）时才退回用估价。
    """
    billing = completion.billing() if hasattr(completion, "billing") else {}
    if billing.get("metered"):
        return int(billing.get("credits") or 0)
    return quoted


@app.get("/health")
def health() -> dict[str, Any]:
    """不鉴权：它不返回任何研究数据，而部署探针不会带 Cookie。

    database 一栏必须如实反映**正在用的**后端。此前它无条件返回 SQLite 的文件名，
    于是线上明明跑在 RDS 的 PG 上，/health 却一直说 `stock_decision.db`——
    排查时第一眼就被带偏。只报后端类型与 schema，不报主机和库名：
    这个接口是公开的，连接信息不该从这里漏出去。
    """
    from .database import backend

    which = backend()
    payload = {"status": "ok", "service": "xiamimate-stock-lab-api", "access": access.mode()}
    if which == "postgres":
        from . import pgbackend
        payload["database"] = f"postgres · schema {pgbackend.SCHEMA}"
        # 行级安全是否真的生效。**要报出来**：它失效时查询照常成功、只是返回了
        # 所有人的行，除了在这里看一眼，没有别的地方能发现。
        try:
            payload["row_level_security"] = "生效" if pgbackend.rls_status()["effective"] else "未生效"
        except Exception:
            payload["row_level_security"] = "查不到"
    else:
        payload["database"] = f"sqlite · {database_path().name}"
        payload["row_level_security"] = "不适用（SQLite 没有行级安全，靠应用层过滤）"

    # **真的读一张业务表。** 只查系统表的健康检查有盲区：线上还原完一次备份后，
    # schema 属主变成了执行还原的账号，应用角色连 USAGE 都没有——
    # 那时服务「活着」、/health 也是 ok，而任何一次真实查询都报权限不足。
    try:
        from .database import connection

        with connection() as conn:
            conn.execute("SELECT 1 FROM companies LIMIT 1").fetchone()
    except Exception as exc:
        payload["status"] = "degraded"
        payload["database_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    # **运营脉搏：一个 URL 就能看出"要不要有人来管"。**
    #
    # 原来这里只回答"服务活着吗"。而这个系统真正会安静坏掉的地方是别的：
    # 积分闸口宕着（在免费送）、后台任务连着失败（用户点了没结果）、
    # 数据源好几天没同步（页面上全是旧数），这三件事都不会让 /health 变红，
    # 也没有任何一个地方会主动说话——只能靠有人恰好去点那一页。
    #
    # 所以把它们摊到同一个响应里，外部探针拿一个 URL 就够。**只出计数，
    # 不出任何研究内容**：这个接口是不鉴权的。
    # **不因为这些告警把 status 翻成 degraded。** status 回答的是
    # 「这个进程还能不能服务请求」——探针据此决定要不要重启、要不要摘流量。
    # 而"数据源三天没同步"不是进程的毛病，重启一百次也不会好；把它塞进 status
    # 只会让探针做出错误的动作。要有人来管的事写在 ops.alerts 里，谁看谁处理。
    payload["ops"] = _ops_pulse()
    return payload


# 脉搏算一次缓存 30 秒：探针可能每几秒打一次，而这几个 COUNT 没必要每次都跑。
_PULSE: dict[str, Any] = {"at": 0.0, "value": None}


def _ops_pulse() -> dict:
    """需要有人来管的三件事：漏计费、任务连着失败、数据源太旧。"""
    import time

    now = time.monotonic()
    if _PULSE["value"] is not None and now - _PULSE["at"] < 30:
        return _PULSE["value"]

    from . import billing_ledger
    from .database import connection

    alerts: list[str] = []
    pulse: dict[str, Any] = {}

    try:
        billing = billing_ledger.state()
        pulse["unbilled_recent"] = billing["recent"]
        pulse["unbilled_pending"] = billing["pending"]
        pulse["ai_paused"] = billing["paused"]
        if billing["paused"]:
            alerts.append(f"积分闸口连续不可用，AI 已暂停（{billing['window_minutes']} 分钟内 {billing['recent']} 次未计费）")
        elif billing["recent"] > 0:
            alerts.append(f"最近 {billing['window_minutes']} 分钟有 {billing['recent']} 次调用没计上费")
    except Exception as exc:
        pulse["unbilled_error"] = str(exc)[:120]

    try:
        with connection() as conn:
            # 一天内失败/中断的后台任务。**偶尔一个不算事，连着一片才是。**
            since = (datetime.now() - timedelta(days=1)).replace(microsecond=0).isoformat()
            failed = conn.execute(
                "SELECT COUNT(*) AS n FROM background_jobs WHERE status IN ('失败', '已中断') AND updated_at >= ?",
                (since,)).fetchone()["n"]
            pulse["jobs_failed_24h"] = int(failed or 0)
            if int(failed or 0) >= 5:
                alerts.append(f"过去一天有 {failed} 个后台任务失败或中断")

            # **调度作业连着失败，健康卡上原来一个字都没有。**
            #
            # 上面那个 jobs_failed_24h 数的是 background_jobs —— 那是**用户点出来的**
            # 任务（反方、起草、AI 选股）。调度器写的是另一张表 sync_runs，
            # 而这段代码从来没读过它。于是全市场底座连挂三天（2026-08-12～14，
            # division by zero），健康卡照样显示 alerts 空、jobs_failed_24h 0。
            #
            # 下面那条 provider_syncs 的陈旧告警要到第 3 天才响，而且它说的是
            # "数据旧了"，不是"有个作业每天都在同一个地方摔倒" —— 后者才指得到病因。
            #
            # 判据用**连续**失败而不是失败次数：偶发抖动本来就该被重试吃掉，
            # 连着两次同一个作业才说明是它自己的问题。
            try:
                recent = conn.execute(
                    """SELECT job_id, status FROM sync_runs
                       WHERE status IN ('成功', '降级', '部分失败', '失败')
                       ORDER BY started_at DESC LIMIT 60""").fetchall()
                streak: dict[str, int] = {}
                done: set[str] = set()
                for run in recent:
                    job_id = run["job_id"]
                    if job_id in done:
                        continue
                    if run["status"] == "失败":
                        streak[job_id] = streak.get(job_id, 0) + 1
                    else:
                        done.add(job_id)          # 这个作业最近一次是好的，不用管
                broken = {job: n for job, n in streak.items() if n >= 2}
                pulse["jobs_failing"] = broken
                for job_id, times in sorted(broken.items()):
                    alerts.append(f"定时任务「{job_id}」连续失败 {times} 次，数据已经停在上次成功那天")
            except Exception as exc:              # 读不到就说读不到，别把整张健康卡带塌
                pulse["sync_runs_error"] = str(exc)[:120]

            # 列名是 last_success_at / display_name（**第一版我按 provider、finished_at
            # 猜的，真跑起来才报 column "provider" does not exist** —— 而那次它被
            # except 吞成了 jobs_error 一行字，接口照样 200。所以这里的 except
            # 只兜"读不到"，不兜"写错了"：写错了必须在测试里炸出来）。
            stale = conn.execute(
                "SELECT display_name, last_success_at FROM provider_syncs "
                "WHERE last_success_at IS NOT NULL ORDER BY last_success_at ASC LIMIT 1").fetchone()
            if stale is not None and stale["last_success_at"]:
                pulse["oldest_sync"] = {"provider": stale["display_name"], "at": stale["last_success_at"]}
                behind = (datetime.now() - datetime.fromisoformat(str(stale["last_success_at"]))).days
                if behind >= 3:
                    alerts.append(f"{stale['display_name']} 已经 {behind} 天没有同步成功")
    except Exception as exc:
        pulse["jobs_error"] = str(exc)[:120]

    pulse["alerts"] = alerts
    _PULSE.update(at=now, value=pulse)
    return pulse


@app.get("/api/v1/decision-board", response_model=DecisionBoard)
def get_decision_board() -> DecisionBoard:
    """每只票一行：现在卡在哪一步，因此该做什么。不给评分与买卖时点。"""
    return DecisionBoard(**decision_board())


@app.get("/api/v1/dashboard", response_model=DashboardSummary)
def get_dashboard() -> DashboardSummary:
    return dashboard()


@app.post("/api/v1/market/refresh", response_model=BackgroundJob)
async def post_market_refresh() -> BackgroundJob:
    """同步行情。**你建档的公司 + 全市场底座，两样一起，走后台任务。**

    以前这里只刷前者（`refresh_all_market_quotes`），而首页那张云图和市场脉搏
    吃的是后者（`market_universe`）—— 于是点完同步：下面「我的公司」是新的、
    上面云图纹丝不动。**这个反差比两个都旧更迷惑人**，因为它让人以为同步生效了。

    **为什么改成后台任务。** 原来是同步等的，而前端的默认超时是 20 秒 ——
    这个按钮从来没成功过：2026-08-19 实测一次要 25 秒到几分钟不等
    （底座是全市场 5544 只，外部源快慢差很多），接口返回 200，
    却每次都被前端掐掉，而且掐完什么都不显示。

    我先把前端超时放宽到 90 秒，线上复验时**又超了**。
    继续加大只是把"静默失败"换成"干等四分钟"——一个要跑几分钟的活
    本来就不该占着一个 HTTP 请求。这台机器上「抓取新资讯」早就是这么做的。

    底座失败不让整个任务失败：你的公司行情已经刷好了，为了底座把整件事
    标成失败，等于把已经拿到的东西也丢掉。底座的新旧由页面上那个时间戳自己说。
    """
    def work(_job_id: int) -> str:
        refreshed, requested = refresh_all_market_quotes()
        note = f"已更新 {refreshed}/{requested} 家公司的行情"
        try:
            refresh_market_universe()
            note += "；全市场底座也刷过了。"
        except Exception:  # noqa: BLE001 —— 底座是附带的，失败不该拖垮已经成功的那一半
            logger.exception("同步行情时全市场底座刷新失败")
            note += "；全市场底座这次没刷成，云图仍是上一次的数。"
        return note

    return BackgroundJob(**await submit("market_refresh", 0, work, label="正在同步行情"))


@app.get("/api/v1/data-providers", response_model=list[DataProviderStatus])
def get_data_providers() -> list[DataProviderStatus]:
    return list_provider_statuses()


@app.get("/api/v1/quotes/resolve", response_model=QuotePreview)
def get_quote_preview(symbol: str = Query(min_length=1, max_length=16)) -> QuotePreview:
    try:
        return quote_preview(symbol)
    except MarketSymbolError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except MarketQuoteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.get("/api/v1/companies", response_model=list[CompanyRecord])
def get_companies(query: str | None = Query(default=None, max_length=80)) -> list[CompanyRecord]:
    return list_companies(query)


@app.get("/api/v1/universe/lookup", response_model=list[UniverseMatch])
def get_universe_lookup(
    q: str = Query(default="", max_length=40),
    limit: int = Query(default=8, ge=1, le=30),
) -> list[UniverseMatch]:
    """按名称或代码在全市场里找公司。**本地一条 SQL，不联网、不调模型、不计费。**

    顶栏搜索和新建档案都走这里：只搜已建档的话，还没建档的公司永远搜不到，
    而"想研究哪家"这件事总是发生在建档之前。
    """
    return [UniverseMatch(**row) for row in lookup_universe(q, limit)]


async def _fill_archive_later(company_id: int, name: str) -> None:
    """建档之后在后台把公开数据补齐。**不调模型、不花积分。**

    在这之前，新建的档案打开来几乎每一页都是空的（时间轴没有曲线、大事提醒没有公告、
    财务待补充），每一页都得自己去点一次同步。这里一次拉齐。

    补数据失败不能影响"档案已经建好了"这个事实，所以起任务本身也包在 try 里。
    """
    def work(_job_id: int):
        return fill_new_archive(company_id)["note"]

    try:
        await submit("archive_fill", company_id, work, label=f"正在为「{name}」补齐公开数据")
    except Exception:                                  # noqa: BLE001
        pass


@app.post("/api/v1/companies", response_model=CompanyDetail, status_code=status.HTTP_201_CREATED)
async def post_company(payload: CompanyInput) -> CompanyDetail:
    try:
        company = create_company(payload)
    except integrity_errors() as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="证券代码已存在") from exc
    await _fill_archive_later(company["id"], company["name"])
    return company


@app.post("/api/v1/companies/from-quote", response_model=CompanyDetail, status_code=status.HTTP_201_CREATED)
async def post_company_from_quote(payload: CompanyFromQuoteInput) -> CompanyDetail:
    try:
        company = create_company_from_quote(payload)
        await _fill_archive_later(company["id"], company["name"])
        return company
    except MarketSymbolError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except MarketQuoteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except integrity_errors() as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="证券代码已存在") from exc


@app.get("/api/v1/companies/groups", response_model=list[WatchGroupSummary])
def get_watch_groups() -> list[WatchGroupSummary]:
    return watchlist_groups()


@app.get("/api/v1/companies/export", response_model=list[WatchlistExportRow])
def get_watchlist_export(response: Response) -> list[WatchlistExportRow]:
    """导出研究池。**必须带 Content-Disposition，否则它不是"导出"。**

    前端那个入口是一个裸 `<a href>`，没有 download 属性。少了这个响应头，
    浏览器就照 application/json 直接渲染 —— 点一下，整个应用被一屏 JSON
    顶掉，人得按后退才能回来，而且一个文件都没拿到。
    2026-08-19 全站巡检实测：点完 url 变成 /api/v1/companies/export，
    页面开头是 `[{"symbol":"002948",...`。

    这件事在导入那一栏写得很清楚：「选择"导出研究池"下载到的 JSON 文件」——
    也就是说这条闭环从第一步就是断的。

    文件名带上日期：研究池是会变的，两次导出叫同一个名字，
    存到本地就分不出哪份是哪天的。
    """
    stamp = date.today().isoformat()
    response.headers["Content-Disposition"] = (
        f'attachment; filename="xiami-research-pool-{stamp}.json"'
    )
    return export_watchlist()


@app.post("/api/v1/companies/import", response_model=WatchlistImportResult)
def post_watchlist_import(payload: WatchlistImport) -> WatchlistImportResult:
    return import_watchlist(payload)


@app.get("/api/v1/companies/{company_id}", response_model=CompanyDetail)
def get_company_detail(company_id: int) -> CompanyDetail:
    company = get_company(company_id)
    if not company:
        raise not_found("company")
    return company


@app.post("/api/v1/companies/{company_id}/market-history/refresh", response_model=MarketHistoryRefreshResult)
def post_company_market_history_refresh(company_id: int) -> MarketHistoryRefreshResult:
    try:
        refreshed_bars = refresh_company_market_history(company_id)
    except MarketDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if refreshed_bars is None:
        raise not_found("company")
    return MarketHistoryRefreshResult(
        company_id=company_id,
        refreshed_bars=refreshed_bars,
        as_of=datetime.now().replace(microsecond=0),
    )


@app.post("/api/v1/companies/{company_id}/profile/refresh", response_model=CompanyProfileRefreshResult)
def post_company_profile_refresh(company_id: int) -> CompanyProfileRefreshResult:
    try:
        refreshed_events = refresh_company_profile(company_id)
    except CompanyProfileError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if refreshed_events is None:
        raise not_found("company")
    return CompanyProfileRefreshResult(
        company_id=company_id,
        refreshed_events=refreshed_events,
        as_of=datetime.now().replace(microsecond=0),
    )


@app.post("/api/v1/companies/{company_id}/valuation/refresh", response_model=ValuationRefreshResult)
def post_company_valuation_refresh(company_id: int) -> ValuationRefreshResult:
    try:
        refreshed_points = refresh_company_valuation(company_id)
    except ValuationDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if refreshed_points is None:
        raise not_found("company")
    return ValuationRefreshResult(
        company_id=company_id,
        refreshed_points=refreshed_points,
        as_of=datetime.now().replace(microsecond=0),
    )


@app.post("/api/v1/companies/{company_id}/financials/refresh", response_model=FinancialRefreshResult)
def post_company_financials_refresh(company_id: int) -> FinancialRefreshResult:
    try:
        refreshed_periods = refresh_company_financials(company_id)
    except FinancialDataError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if refreshed_periods is None:
        raise not_found("company")
    return FinancialRefreshResult(
        company_id=company_id,
        refreshed_periods=refreshed_periods,
        as_of=datetime.now().replace(microsecond=0),
    )


@app.patch("/api/v1/companies/{company_id}", response_model=CompanyDetail)
def patch_company(company_id: int, payload: CompanyUpdate) -> CompanyDetail:
    company = update_company(company_id, payload)
    if not company:
        raise not_found("company")
    return company


@app.post("/api/v1/companies/{company_id}/theses", response_model=ThesisRecord, status_code=status.HTTP_201_CREATED)
def post_thesis(company_id: int, payload: ThesisCreate) -> ThesisRecord:
    """认错条件空着**允许写下，但不会被当成没事**。

    产品里只有这一条硬规矩（quick.py：「那不是少填一栏，是这条记录作废」），
    而它此前只拦在三个门里的一个：`/quick-thesis` 走 quick.validate，
    这个门和 AI 那个门都不拦，schema 里 counter_condition 干脆默认空串。
    后果是**这条记录静默地退出整张网** —— check_counter_hits 只查
    `counter_condition <> ''`，它永远不会被任何事实撞上，而且没有任何地方报错。

    ## 为什么这里不硬拦

    我先写成 422 了，然后改回来。理由不是"会弄红一堆测试"，是：

    **硬拦会逼出一句敷衍的条件，而假条件比空条件更糟。**
    空的至少是诚实的空白，数得出来、提示得了；一句「基本面恶化」看起来
    这条已经有人盯着了，实际上它同样永远不会触发 —— 而且再也没人会去补。

    所以改成：空着能写（想法先落下来，这是 quick.py 那套"降摩擦"的同一个道理），
    但**它不许沉默** —— dashboard.theses_without_counter 把这些数出来，
    首页折叠标题上直接写「N 条判断还差认错条件」。
    30 秒那条路（/quick-thesis）仍然硬拦：那条路的全部意义就是这三句话。
    """
    thesis = create_thesis(company_id, payload)
    if not thesis:
        raise not_found("company")
    return thesis


@app.patch("/api/v1/theses/{thesis_id}", response_model=ThesisRecord)
def patch_thesis(thesis_id: int, payload: ThesisUpdate) -> ThesisRecord:
    """改一条判断。**认错条件可以改，但不能被清空。**

    跟"新建时允许空着"不矛盾：新建时空着是"还没写"，清空是**把一条已经在网里的
    记录拿出来作废**，而且作废得悄无声息 —— 页面上它照样是一条判断，
    只是从此再也不会被任何事实撞上。要作废该改状态（已破坏），不是抹掉条件。
    不传这个字段则不动它。"""
    from .quick import validate as validate_thesis

    if payload.counter_condition is not None and not payload.counter_condition.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=validate_thesis("占位够长的一句", ""))
    thesis = update_thesis(thesis_id, payload)
    if not thesis:
        raise not_found("thesis")
    return thesis


@app.post("/api/v1/companies/{company_id}/evidences", response_model=EvidenceRecord, status_code=status.HTTP_201_CREATED)
def post_evidence(company_id: int, payload: EvidenceCreate) -> EvidenceRecord:
    try:
        evidence = create_evidence(company_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not evidence:
        raise not_found("company")
    return evidence


@app.post("/api/v1/companies/{company_id}/events", response_model=ResearchEventRecord, status_code=status.HTTP_201_CREATED)
def post_event(company_id: int, payload: ResearchEventCreate) -> ResearchEventRecord:
    try:
        event = create_event(company_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not event:
        raise not_found("company")
    return event


@app.patch("/api/v1/events/{event_id}", response_model=ResearchEventRecord)
def patch_event(event_id: int, payload: ResearchEventUpdate) -> ResearchEventRecord:
    event = update_event(event_id, payload)
    if not event:
        raise not_found("event")
    return event


@app.get("/api/v1/portfolios", response_model=list[PortfolioSummary])
def get_portfolios() -> list[PortfolioSummary]:
    return list_portfolios()


@app.post("/api/v1/portfolios", response_model=PortfolioSummary, status_code=status.HTTP_201_CREATED)
def post_portfolio(payload: PortfolioCreate) -> PortfolioSummary:
    try:
        return create_portfolio(payload)
    except integrity_errors() as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="组合名称已存在") from exc


@app.get("/api/v1/portfolios/{portfolio_id}", response_model=PortfolioDetail)
def get_portfolio_detail(portfolio_id: int) -> PortfolioDetail:
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise not_found("portfolio")
    return portfolio


@app.delete("/api/v1/portfolios/{portfolio_id}", response_model=PortfolioDeleted)
def remove_portfolio(portfolio_id: int) -> PortfolioDeleted:
    """删掉一个组合，连里面的持仓一起。**删了就回不来。**

    返回它带走了多少只持仓：删一个空组合和删掉一个装满记录的组合，
    在界面上长得一模一样。
    """
    result = delete_portfolio(portfolio_id)
    if not result["deleted"]:
        raise not_found("portfolio")
    return PortfolioDeleted(**result)


@app.patch("/api/v1/portfolios/{portfolio_id}", response_model=PortfolioSummary)
def patch_portfolio(portfolio_id: int, payload: PortfolioUpdate) -> PortfolioSummary:
    try:
        result = update_portfolio(portfolio_id, payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not result:
        raise not_found("portfolio")
    return result


# ── 读文档 ────────────────────────────────────────────────────────────────
#
# **解析不花钱**（全在本地跑），花钱的只有问答那一步，而且是先检索再问：
# 只把命中的十页喂进去，一次两三分钱。见 documents.py 开头那段。

# ⚠️ **这几条不挂 access.require_owner。**
#
# 第一版挂了，理由写的是「会影响所有人的数据」—— 而这是抄错了模板：
# 上传的文件按 user_id 隔离（documents 在 _SCOPED_BY_USER 里），
# 各看各的，跟备份/还原那种整实例操作完全不是一回事。
# 线上用测试账号一试就 403：一个登录用户读不了自己上传的文件。
# 隔离由 _sw() 保证，跟建一家公司同一套。


def _parse_and_save(body: bytes, *, title: str, source: str, url: str = "",
                    company_id: int | None = None, kind: str = "文件",
                    fetch_note: str = "") -> dict:
    from .disclosure import describe_body
    from .pdfread import MAX_PDF_BYTES, PdfUnreadable, read_pages, summarize

    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有收到文件")
    if len(body) > MAX_PDF_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"文件超过 {MAX_PDF_BYTES // 1024 // 1024}MB")
    if body[:5] != b"%PDF-":
        # **说出取回来的是什么，别只说"这不是 PDF"。**
        #
        # 原来这句是「这不是 PDF 文件。现在只读得了 PDF。」—— 它把原因指向了链接。
        # 而实测最常见的原因是：服务器取到了一段几百字节的反爬校验页，
        # 响应头里的 content-type 还写着 application/pdf。使用者拿着同一个链接
        # 在本地能读、线上读不了，照着那句消息只会去反复检查链接（他真的这么做了）。
        detail = f"取回来的不是 PDF：{describe_body(body)}。"
        if url:
            detail += "这个链接在浏览器里能打开的话，多半是这个站点拦了服务器的请求。"
        if fetch_note:
            detail += f"（{fetch_note}）"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail[:400])
    try:
        pages = read_pages(body)
    except PdfUnreadable as caught:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(caught)) from caught
    summary = summarize(pages)
    if not summary["read"]:
        # **整份都没有文字层。** 这不是我们的错误，但也不能存一份空文件让他以为读过了。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"这份文件 {summary['pages']} 页里一页文字都读不出来，多半是扫描件。"
                   f"现在还不会认扫描件里的字。")
    # **标题从第一页读，不用文件名。**
    #
    # 贴链接读进来的原来叫 `H3_AP202405221634315503_1.pdf` —— 对读的人零信息量，
    # 两份研报并排放着分不出哪份是哪份。而文件自己第一页上就印着标题。
    # 调用方显式传了标题（比如脚本里指定的）就尊重它，不去覆盖。
    from . import documents as doc

    fallback = str(title or "").strip() or "未命名文件"
    looks_like_filename = fallback.lower().endswith(".pdf") or fallback == "未命名文件"
    named = doc.guess_title(pages, fallback=fallback) if looks_like_filename else fallback
    # 认类型要用**定下来的标题**：文件名认不出「半年度报告」，而第一页上写着。
    settled_kind = kind if kind not in ("", "文件") else doc.detect_kind(named, pages)
    document_id = save_document(pages, summary, title=named, source=source, url=url,
                                company_id=company_id, kind=settled_kind,
                                tags=doc.guess_tags(pages, settled_kind))
    return {"id": document_id, "title": named, **summary}


@app.post("/api/v1/documents", status_code=status.HTTP_201_CREATED)
async def post_document(file: UploadFile = File(...),
                        company_id: int | None = Form(default=None),
                        kind: str = Form(default="文件")) -> dict:
    """上传一份 PDF，读成一页一页的文字存起来。**这一步不调模型，所以不扣分** ——
    但别把这句话摆到页面上当卖点：使用者要的是「读完给我结果」，
    而那一步（走清单出结论）是要花钱的。页面上只说花钱的那件事花多少。"""
    body = await file.read()
    return _parse_and_save(body, title=file.filename or "未命名文件",
                           source="upload", company_id=company_id, kind=kind)


@app.post("/api/v1/documents/from-url", status_code=status.HTTP_201_CREATED)
def post_document_from_url(payload: dict) -> dict:
    """给一个 PDF 链接，抓回来解析。巨潮、交易所、券商官网的直链都行。

    取回来这一步有两条路（见 `disclosure.fetch_bytes`）：**东方财富那个域名对
    Python 的 urllib 返回反爬校验页，而同一台机器上的 curl 直接拿到 PDF**。
    所以直连取到的不是 PDF 时会换 curl 再试一次。
    """
    url = str(payload.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="请给一个 http/https 开头的 PDF 链接")
    from .disclosure import fetch_bytes

    got = fetch_bytes(url)
    if not got["body"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"这个链接取不到 —— {got['note'] or '没有响应'}")
    title = str(payload.get("title") or "").strip() or url.rsplit("/", 1)[-1][:120]
    return _parse_and_save(body=got["body"], title=title, source="url", url=url,
                           company_id=payload.get("company_id"),
                           kind=str(payload.get("kind") or "文件"),
                           fetch_note=got["note"])


@app.get("/api/v1/documents")
def get_documents(company_id: int | None = Query(default=None)) -> dict:
    """读过的文件。**读法分布和读不到的页一起返回** —— 那是摆给使用者的交代。

    **不返回 boundary。** 这里原来常驻一句解释计费方式的话，先是
    「解析在本地做，不花积分」（讲的是我们内部分了几步，而且读起来像"读文档不花钱"，
    跟结果里的「本次 4 分」自相矛盾），改写一遍之后使用者说「去掉这句不必要的解释」。

    他是对的，而且这条规矩他说过不止一次。价钱在结果里如实报了一次
    （「本次 N 分」），那就够了 —— **常驻一句解释等于每次都在替一个还没发生的
    疑问辩解**，而它占的是每一屏的版面。
    """
    return {"rows": list_documents(company_id)}


@app.post("/api/v1/documents/{document_id}/retitle")
def post_document_retitle(document_id: int) -> dict:
    """按第一页重认这份文件的标题、类型和标签。**不调模型，不花积分。**

    给老文件用：标题从第一页读这件事是后加的，之前贴链接读进来的都叫
    `H3_AP202405221634315503_1.pdf`。让人为了一个标题重读一遍要再花几分钱，
    而那几页原文就在库里。
    """
    from . import documents as doc

    view = get_document(document_id)
    if view is None:
        raise not_found("document")
    # **人自己起的标题不动。** 只有还挂着文件名的才替换 ——
    # 实测线上那四份的标题是手工给的（「民生证券：寒武纪-U 首次覆盖报告」，
    # 带了第一页上没有的券商名），按第一页重认会把那个信息抹掉。
    # 那几份要的只是补标签。
    old = str(view["title"] or "")
    named = (doc.guess_title(view["pages"], fallback=old)
             if old.lower().endswith(".pdf") or not old else old)
    kind = doc.detect_kind(named, view["pages"])
    tags = doc.guess_tags(view["pages"], kind)
    rename_document(document_id, named, kind, tags)
    return {"id": document_id, "title": named, "kind": kind, "tags": tags,
            "changed": named != view["title"]}


@app.get("/api/v1/documents/{document_id}")
def get_document_detail(document_id: int) -> dict:
    view = get_document(document_id)
    if view is None:
        raise not_found("document")
    # **界面初次渲染时是从这份详情里拼结果的，不走 /digest 接口。**
    # 只在那个接口里加「核不到的数字」的话，重新打开一份文件就什么提示都没有 ——
    # 而重新打开恰恰是最常走的一条路（结果存在文件上，重开不重付）。
    if view.get("digest"):
        from . import documents as doc

        view["digest_unverified"] = doc.unverified_figures(view["digest"], view["pages"])
    return view


@app.delete("/api/v1/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_endpoint(document_id: int) -> Response:
    if not delete_document(document_id):
        raise not_found("document")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 一份读文档结果最多写多长。
#
# **这个数不是猜的，是撞出来的。** 加了表格之后第一次重读那份研报就断了：
# 6000 token 的时候模型写到 2638 个中文字被掐断 —— 也就是 MiniMax 的中文
# 大约 2 token 一个字，6000 token 只够三千来字，而十条清单项各带结论、
# 数字和表格要一倍于此。
#
# 提示词那边同时也收紧了（最多三张表、每张最多八行）：**光抬上限不算解法** ——
# 上限抬一档、模型就多写一档，下次照样断。要一头封顶、一头限量。
# 写价 8000 token 1 分，这里满打满算不到两分钱。
DIGEST_MAX_TOKENS = 14_000


@app.post("/api/v1/documents/{document_id}/digest")
def post_document_digest(document_id: int, payload: dict | None = None) -> dict:
    """**读完自动出的那份结果。** 按文件类型走一张固定的研究清单，逐条检索、一次成文。

    存在文件上，**重开不重付**：已经有结果就直接返回，除非传 `redo`。
    `dry_run` 只报价（检索在本地做，报价不花钱）。
    """
    from . import documents as doc
    from .llm import call, credits_for_document

    payload = payload or {}
    view = get_document(document_id)
    if view is None:
        raise not_found("document")
    if view.get("digest") and not payload.get("redo"):
        return {"digest": view["digest"], "kind": view["digest_kind"],
                "pages": view["digest_pages"], "missed": view["digest_missed"],
                # 存量结果也要核 —— 这个检查是 2026-08-19 才加的，
                # 而库里那几份是之前跑的，它们身上的错一样在页面上摆着。
                "unverified": doc.unverified_figures(view["digest"], view["pages"]),
                "credits": 0, "cached": True}

    kind = str(payload.get("kind") or "") or doc.detect_kind(view["title"], view["pages"])
    context = doc.build_digest_context(view["pages"], kind)
    if not context["pages"]:
        # **别猜原因 —— 这两件事都是手上已有的事实。**
        #
        # 原来这句是「多半不是年报/公告/研报这几类，或者它整份都读不出字」。
        # 2026-08-19 巡检时它出现在一份**标着「公告」、读出了 0.1 万字**的文件上：
        # 两个猜测都被同一屏上的信息当场否掉了，人看完只会更糊涂。
        #
        # 类型是 detect_kind 判出来的，字数数一下就有。说事实，别说"多半"。
        readable = sum(len(page.get("text") or "") for page in view["pages"])
        if not readable:
            note = ("这份文件一页都读不出字 —— 多半是扫描件（图片版）。"
                    "换一份带文字层的 PDF 才能读。")
        else:
            note = (f"按「{kind}」那张清单逐条检索，{len(view['pages'])} 页里一条都没命中。"
                    "会议通知、人事变动这类短公告本来就没有清单上的内容 —— "
                    "文件读进来了，可以直接在下面问它。")
        return {"digest": "", "kind": kind, "pages": [], "missed": context["missed"],
                "credits": 0, "note": note}
    cost = credits_for_document(len(context["text"]), DIGEST_MAX_TOKENS)
    if payload.get("dry_run"):
        return {"digest": "", "kind": kind, "pages": context["pages"],
                "missed": context["missed"], "credits": cost, "chars": context["chars"]}

    from .jsonio import Truncated, loads_lenient

    completion = call(doc.DIGEST_SYSTEM_PROMPT,
                      doc.build_digest_prompt(view["title"], kind, context["items"],
                                              context["text"]),
                      # 默认 120 秒是按两三千 token 的输出定的。带表的结果长一倍，
                      # 而超时表现成一句「读取失败」—— 读的人只会以为功能坏了。
                      task="document-digest", max_tokens=DIGEST_MAX_TOKENS, timeout=240)
    # **存 JSON 原文。** 结构化之后页面才排得出层级 —— 一整段 markdown 渲染成
    # pre-wrap 就又是一堵墙，而"一堆文字没有组织"正是使用者反复说过的那件事。
    #
    # **写到一半被掐断的要当场说出来，不能 500，也不能存。**
    # 实测第一次带表的重读就撞上了这个：`loads_lenient` 对没写完的 JSON 抛
    # Truncated（它不肯补外层括号，因为那会静静地丢掉最后几条），而这里没接住 ——
    # 使用者看到的是「请求失败（500）」。这个仓里另外七个调用点全都显式接了它，
    # 只有读文档这两个没有。存下来更糟：半张表会被当成缓存，重开还是它。
    try:
        parsed = loads_lenient(completion.text)
    except Truncated as cut:
        return {"digest": "", "kind": kind, "pages": context["pages"],
                "missed": context["missed"], "credits": charged(completion, cost),
                "structured": False, "cached": False,
                "note": f"这一次的输出写到一半被长度上限掐断了（{len(completion.text)} 字），"
                        f"没存下来 —— 半张表当成结果比没有结果糟。**再点一次重读**；"
                        f"还是断的话说明这份文件的清单项太多，我这边要把上限再抬一档。"
                        f"（{cut}）"[:400]}
    body = doc.dumps(parsed) if isinstance(parsed, dict) else completion.text.strip()
    save_digest(document_id, body, kind, context["pages"], context["missed"])
    return {"digest": body, "kind": kind, "pages": context["pages"],
            "missed": context["missed"], "credits": charged(completion, cost),
            # **提示词第 0 条是一句承诺，这里是管它的人。**
            # 「你输出里的每一个数都必须能在给你的原文里找到」——
            # 2026-08-19 实测有一条写着「同业存放款项净增加 739.9 亿」，
            # 而它引的第 33 页写的是 7,383,004,563.78（73.83 亿），差十倍，
            # 且那个数正是它论证「706.91 亿现金流不是主营回款」的唯一论据。
            "unverified": doc.unverified_figures(body, view["pages"]),
            # 这里原来还有一句 boundary：「按…的清单读的，只用了上面那几页原文；
            # 每条后面的页码可以翻回去核；没找到的那几条也列出来了」——
            # **三件事全都摆在屏幕上看得见**：清单名和页码在标题行，页码在每条角标上，
            # 没找到的那几条自己就是一个折叠块。等于把界面上的东西又念了一遍。
            "structured": isinstance(parsed, dict), "cached": False}


@app.post("/api/v1/documents/{document_id}/fundraising")
def post_document_fundraising(document_id: int, payload: dict | None = None) -> dict:
    """从一份「募集资金存放、管理与实际使用情况的专项报告」里抽募投进度并落库。

    **这是第一条「读文档的结果喂给另一个功能」的链子** —— 抽完直接排进
    公司档案那张甘特图的第三条泳道。

    要绑到一家公司（`company_id`，或者这份文件读进来时就归好了）：
    募投进度是某家公司的事实，不落到公司上就没有归宿。
    """
    from . import documents as doc
    from .llm import call, credits_for_document
    from .jsonio import Truncated, loads_lenient

    payload = payload or {}
    view = get_document(document_id)
    if view is None:
        raise not_found("document")
    company_id = payload.get("company_id") or view.get("company_id")
    if not company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="要先把这份文件归到一家公司 —— 募投进度是某家公司的事实。")

    context = doc.build_fund_context(view["pages"])
    if not context["pages"]:
        return {"saved": 0, "pages": [], "credits": 0,
                "note": "这份文件里没找到募投项目表 —— 它可能不是募集资金专项报告。"}
    cost = credits_for_document(len(context["text"]), 2000)
    if payload.get("dry_run"):
        return {"saved": 0, "pages": context["pages"], "credits": cost,
                "chars": context["chars"]}

    completion = call(doc.FUND_SYSTEM_PROMPT,
                      f"文件：{view['title']}\n\n{context['text']}",
                      task="document-fundraising", max_tokens=4000, timeout=180)
    # 跟出结果那边同一条：**没写完不许 500，更不许存半份。**
    # 募投这里存半份格外贵 —— 少一个项目，甘特图上就少一条泳道，
    # 而它看起来跟"这次发行只有四个项目"一模一样。
    try:
        parsed = loads_lenient(completion.text) or {}
    except Truncated as cut:
        return {"saved": 0, "pages": context["pages"], "credits": charged(completion, cost),
                "note": f"抽到一半被长度上限掐断了，没存 —— **少一个项目跟"
                        f"「这次发行只有四个项目」看起来一模一样**。再点一次试试。（{cut}）"[:400]}
    projects = parsed.get("projects") if isinstance(parsed, dict) else None
    if not isinstance(projects, list) or not projects:
        return {"saved": 0, "pages": context["pages"], "credits": charged(completion, cost),
                "note": "模型没在这几页里找到募投项目表。"}
    saved = save_fundraising(int(company_id), document_id, projects)
    return {"saved": saved, "pages": context["pages"], "credits": charged(completion, cost),
            # 这里原来还有一句 boundary，前端从来没渲染过 —— 死的。
            # 抽完去哪了由 Fund 那个组件自己说一句就够：
            # 「抽出 N 个募投项目（出自第 X 页），已排进上面的『还有哪些日子在等着』」。
            "projects": company_fundraising(int(company_id))}


@app.post("/api/v1/documents/{document_id}/ask")
def post_document_ask(document_id: int, payload: dict) -> dict:
    """问这份文件一个问题。**先检索再问** —— 只把命中的十页喂进去。

    `dry_run` 只报价不调模型：检索在本地做，报价不该花钱。
    """
    from . import documents as doc
    from .llm import call, credits_for_document

    view = get_document(document_id)
    if view is None:
        raise not_found("document")
    question = str(payload.get("question") or "").strip()
    if len(question) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="问题太短了")

    context = doc.build_context(view["pages"], question)
    if not context["pages"]:
        # **没命中时不许沉默地喂前几页。** 那会答出一段跟问题无关、
        # 却长得很像回答的东西 —— 比说"没找到"糟得多。
        return {"answer": "", "pages": [], "note": context["note"], "credits": 0}

    # 追问同一份文件时模型那边命中前缀缓存，成本掉三十倍，这里也跟着掉。
    cached = bool(payload.get("followup"))
    cost = credits_for_document(len(context["text"]), 1200, cached=cached)
    if payload.get("dry_run"):
        return {"answer": "", "pages": context["pages"], "note": context["note"],
                "credits": cost, "chars": context["chars"]}

    completion = call(doc.ASK_SYSTEM_PROMPT,
                      doc.build_prompt(question, context["text"], view["title"]),
                      task="document-ask", max_tokens=1500)
    return {"answer": completion.text.strip(), "pages": context["pages"],
            "note": context["note"], "credits": charged(completion, cost),
            # 同样删掉一句 boundary：「回答只用了上面那几页的原文」——
            # 而 note 里就写着"从 N 页里挑了 M 页喂进去（第 …页）"，就在它上面一行。
            "chars": context["chars"]}


@app.get("/api/v1/companies/{company_id}/promises/estimate")
def get_promise_estimate(company_id: int) -> dict:
    """抽承诺**这一次**大概几分 —— 按真的要喂多少字算，不查那张典型值表。

    线上真跑一次是「冻结 7 分、实扣 3 分」，而弹窗报的是 17 分（典型值表里的
    83000 token）。**报高跟报低同样糟：它会把人吓得不敢点**，
    而这个功能是承诺台账唯一的入口。要喂多少字在调模型之前就知道，既然算得出来就别猜。
    """
    view = promise_estimate(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/credits/estimates")
def get_credit_estimates() -> dict:
    """每个会花钱的动作点下去大概几分。页面拿它给按钮标价。

    **典型值，不是承诺**：真实用量取决于喂进去多少字，结算永远按真实 usage。
    """
    from .llm import TYPICAL_TOKENS, credits_for_report, typical_credits

    table = {task: typical_credits(task) for task in TYPICAL_TOKENS}
    # AI 选股联网时要另加搜索费，而这张表只认 token，算不出来。
    #
    # 原来的做法是在确认框里补一句「另计几分搜索费用」——**含糊，而且用词是错的**：
    # 这个产品的单位是积分不是钱。更要紧的是这个数根本不含糊：
    # 搜索次数是代码定死的（ai_pick.MAX_THEME_QUERIES），系数也是定死的，
    # 一乘就出来。**能算准的数不要用「几分」搪塞。**
    #
    # 算在后端：前端自己乘一遍的话，改了系数两边就会漂开
    # （见 credits.ts 开头那段：同一个数写在两处迟早会漂）。
    from .ai_pick import MAX_THEME_QUERIES
    from .industry_chain_draft import QUERY_COUNT as INDUSTRY_CHAIN_DRAFT_QUERY_COUNT

    table["ai-pick-web"] = credits_for_report(MAX_THEME_QUERIES, TYPICAL_TOKENS["ai-pick"])
    # 产业链初稿同样包含固定次数的公开检索；不能只显示模型整理那一部分的价格。
    table["industry-chain-draft"] = credits_for_report(
        INDUSTRY_CHAIN_DRAFT_QUERY_COUNT, TYPICAL_TOKENS["industry-chain-draft"]
    )
    return table


@app.put("/api/v1/portfolios/{portfolio_id}/holdings", response_model=TradeRecord,
         status_code=status.HTTP_200_OK)
def put_holding(portfolio_id: int, payload: HoldingInput) -> TradeRecord:
    """设定一只票的持仓：N 股、成本价 P。**新增和更新是同一个动作。**

    用 PUT 不用 POST：这是"把它设成这样"，不是"再加一笔"。重复调用同一组数
    结果一样（幂等），而 POST 的语义会让人以为调两次就是买了两次。
    """
    try:
        trade = set_holding(portfolio_id, payload.company_id,
                            payload.shares, payload.cost_price)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc
    if not trade:
        raise not_found("portfolio")
    return trade


@app.delete("/api/v1/portfolios/{portfolio_id}/holdings/{company_id}",
            response_model=TradePurgeResult)
def delete_holding(portfolio_id: int, company_id: int) -> TradePurgeResult:
    """把一只票从持仓里去掉，连同它的历史。**删掉就回不来了。**

    返回真实删除条数：删 0 条和删 34 条在界面上长得一样，
    静默成功会让人以为清过了。
    """
    result = drop_holding(portfolio_id, company_id)
    if result.get("missing_portfolio"):
        raise not_found("portfolio")
    return TradePurgeResult(**{k: v for k, v in result.items() if k != "missing_portfolio"})


@app.post("/api/v1/portfolios/{portfolio_id}/trades/purge", response_model=TradePurgeResult)
def post_trades_purge(portfolio_id: int, payload: TradePurgeRequest) -> TradePurgeResult:
    """把某几家公司在这个组合里的流水整段删掉。**删不回来。**

    这条路存在的理由见 repository.purge_company_trades：手工流水账烂掉之后
    逐条修是修不回来的，唯一能回到"账对得上"的路是整段翻篇 +
    一条期初持仓重新声明现在有多少。
    """
    result = purge_company_trades(portfolio_id, payload.company_ids)
    if result.get("missing_portfolio"):
        raise not_found("portfolio")
    return TradePurgeResult(**{k: v for k, v in result.items() if k != "missing_portfolio"})


@app.post("/api/v1/portfolios/{portfolio_id}/trades", response_model=TradeRecord, status_code=status.HTTP_201_CREATED)
def post_trade(portfolio_id: int, payload: TradeCreate) -> TradeRecord:
    try:
        trade = create_trade(portfolio_id, payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not trade:
        raise not_found("portfolio")
    return trade


@app.patch("/api/v1/trades/{trade_id}", response_model=TradeRecord)
def patch_trade(trade_id: int, payload: TradeUpdate) -> TradeRecord:
    trade = update_trade(trade_id, payload)
    if not trade:
        raise not_found("trade")
    return trade


@app.get("/api/v1/theses/{thesis_id}/revisions", response_model=list[RecordRevision])
def get_thesis_revisions(thesis_id: int) -> list[RecordRevision]:
    revisions = list_revisions("thesis", thesis_id)
    if revisions is None:
        raise not_found("thesis")
    return revisions


@app.delete("/api/v1/trades/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_trade(trade_id: int) -> Response:
    """删掉一笔交易。

    手记会记错组合、也会记重；删不掉的话唯一的补救是记一笔反向交易去抵消，
    那等于往账本里写一笔**从未发生过的事**——比留着错的更糟。
    """
    if not delete_trade(trade_id):
        raise not_found("trade")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/trades/{trade_id}/revisions", response_model=list[RecordRevision])
def get_trade_revisions(trade_id: int) -> list[RecordRevision]:
    revisions = list_revisions("trade", trade_id)
    if revisions is None:
        raise not_found("trade")
    return revisions


@app.get("/api/v1/settings")
def get_settings() -> dict:
    """当前用户自己的偏好。按数据域隔离，各看各的。"""
    return all_settings()


@app.patch("/api/v1/settings")
def patch_settings(payload: dict) -> dict:
    """改一项偏好。key 走白名单，未知的 key 直接拒。

    这里没有 require_owner：这些是「我自己的」偏好，本来就该每个人自己改。
    """
    try:
        for key, value in (payload or {}).items():
            set_setting(key, bool(value))
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return all_settings()


@app.get("/api/v1/local-data", response_model=LocalDataSummary)
def get_local_data() -> LocalDataSummary:
    # 报的是整库的表与条目数，不是某个人的那份。
    access.require_owner("查看整库数据概况")
    return local_data_summary()


@app.get("/api/v1/backups", response_model=list[BackupManifest])
def get_backups() -> list[BackupManifest]:
    access.require_owner("查看备份")
    return list_backups()


@app.post("/api/v1/backups", response_model=BackupManifest, status_code=status.HTTP_201_CREATED)
def post_backup(payload: dict | None = None) -> BackupManifest:
    access.require_owner("创建备份")
    note = str((payload or {}).get("note", ""))[:300]
    try:
        return create_backup(note=note)
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.post("/api/v1/backups/{name}/restore", response_model=BackupRestoreResult)
def post_backup_restore(name: str) -> BackupRestoreResult:
    # 还原会用一份快照覆盖**所有人**的记录，是这一组里最危险的一个。
    access.require_owner("还原备份")
    try:
        return restore_backup(name)
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.get("/api/v1/backups/{name}/download")
def get_backup_download(name: str) -> FileResponse:
    # 下载的是整库文件，里面是所有人的原始行。
    access.require_owner("下载备份")
    try:
        path = backup_file(name)
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/vnd.sqlite3", filename=path.name)


@app.get("/api/v1/export")
def get_export() -> JSONResponse:
    # 手写记录本身是按数据域过滤的（backup._export_filter），但 **source_counts 是整库计数**：
    # 未登录调它就能拿到 valuation_points 18600、price_bars 2421 这类全库规模。
    # 而同样性质的 /local-data 一直是站主专属 —— 两处口径不一致，按严的那边对齐。
    access.require_owner("导出研究记录")
    payload = export_records()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="xiamimate-research-{stamp}.json"'},
    )


@app.get("/api/v1/inbox", response_model=InboxPage)
def get_inbox(
    inbox_status: str = Query(default="待核验", max_length=20, alias="status"),
    limit: int = Query(default=40, ge=1, le=200),
    days: int = Query(default=90, ge=0, le=3650),
    relevance: str | None = Query(default=None, pattern="^(高|中|低)$"),
) -> InboxPage:
    return list_inbox(inbox_status, limit, days or None, relevance)


@app.post("/api/v1/research-tasks/{task_id}/auto-review", response_model=BackgroundJob)
async def post_task_auto_review(task_id: int, limit: int = Query(default=30, ge=1, le=120)) -> BackgroundJob:
    """提交后台任务后立刻返回：模型在服务进程里跑，切页面或关掉浏览器都不会打断它。"""

    if get_research_task(task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这个研究任务")

    def work(job_id: int) -> str:
        def progress(done: int, total: int, stage: str) -> None:
            update_background_job(job_id, progress=done, total=total, label=stage)

        result = auto_review_task(task_id, limit, on_progress=progress)
        return (result or {}).get("note", "")

    job = await submit("task_auto_review", task_id, work, label="正在补公司简况与研报")
    return BackgroundJob(**job)


@app.get("/api/v1/jobs/{kind}/{target_id}", response_model=BackgroundJob | None)
async def get_background_job(kind: str, target_id: int) -> BackgroundJob | None:
    job = latest_job(kind, target_id)
    return BackgroundJob(**job) if job else None


@app.post("/api/v1/universe/rederive", response_model=UniverseRederiveResult)
async def post_universe_rederive() -> UniverseRederiveResult:
    """不联网，只用库里已有的财务数据重算估值字段。"""

    return UniverseRederiveResult(**await asyncio.to_thread(rederive_universe_valuation))


@app.post("/api/v1/inbox/tidy", response_model=InboxTidyResult)
async def post_inbox_tidy(use_ai: bool = Query(default=True)) -> InboxTidyResult:
    return InboxTidyResult(**await asyncio.to_thread(tidy_inbox, use_ai))


@app.post("/api/v1/inbox/archive-batch", response_model=InboxBatchResult)
async def post_inbox_archive_batch(
    relevance: str = Query(default="高"),
    days: int = Query(default=90, ge=0, le=3650),
    limit: int = Query(default=500, ge=1, le=2000),
) -> InboxBatchResult:
    try:
        return InboxBatchResult(**archive_inbox_batch(relevance, days, limit))
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/v1/value-candidates")
async def post_value_candidates(
    strategy: str = Query(default="undervalued_defensive"),
    width: int = Query(default=20, ge=1, le=60),
    assess: bool = Query(default=True),
) -> dict:
    """全市场漏斗：规则先筛，前 width 名再交给模型看。

    width 上限 60 是刻意的：再宽人也看不完，而每宽一点都在花钱。
    assess=false 只跑规则筛，一分不花——想先看看规则筛出什么再决定的时候用。
    """
    try:
        return await asyncio.to_thread(value_candidates, strategy, width, assess)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except llm.CreditsError:
        # **CreditsError 是 RuntimeError 的子类**，不先放它过去的话，
        # 「额度不足 / 闸口熔断」会被下面那行改写成 503——而 503 的意思是
        # 「服务坏了，等会儿再试」，前端据此重试，用户看不到该看的那句话。
        # 真跑一遍才发现的：熔断触发时接口返回的是 503，不是 402。
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/v1/value-candidates/review", response_model=BackgroundJob)
async def post_value_candidate_review(
    strategy: str = Query(default="undervalued_defensive", min_length=1, max_length=80),
    width: int = Query(default=20, ge=1, le=60),
) -> BackgroundJob:
    """提交找票页的模型复核。

    规则筛选仍然是免费的即时请求；模型复核进入服务端后台，并在完成时自动
    写入 candidate_review_runs。页面只拿任务 id 轮询，不再把模型调用绑在浏览器
    这一次请求上。
    """

    strategies = {item["key"]: item for item in list_screen_strategies()}
    if strategy == "__agent_pool__":
        strategy_name = "综合榜"
    else:
        selected = strategies.get(strategy)
        if selected is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"没有这个策略：{strategy}")
        strategy_name = selected["name"]
    target = candidate_review_target(strategy, strategy_name, width)
    target_id = int(target["id"])

    def work(_job_id: int):
        result = value_candidates(strategy, width, True)
        saved = CandidateReviewSave(
            strategy_key=strategy,
            strategy_name=strategy_name,
            width=width,
            rows=result.get("rows") or [],
            note=result.get("note") or "",
            boundary=result.get("boundary") or "",
            estimated_credits=int(result.get("estimated_credits") or 0),
        )
        save_candidate_review(saved)
        return result.get("note") or "模型复核已完成", result

    try:
        job = await submit("candidate_review", target_id, work,
                           label=f"正在复核「{strategy_name}」前 {width} 家")
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BackgroundJob(**job)


@app.get("/api/v1/value-candidates/review/status", response_model=BackgroundJob | None)
async def get_value_candidate_review_status(
    strategy: str = Query(default="undervalued_defensive", min_length=1, max_length=80),
    width: int = Query(default=20, ge=1, le=60),
) -> BackgroundJob | None:
    """切回找票页时，按策略 + 宽度恢复最近一次后台复核。"""

    strategies = {item["key"]: item for item in list_screen_strategies()}
    strategy_name = "综合榜" if strategy == "__agent_pool__" else (strategies.get(strategy) or {}).get("name")
    if not strategy_name:
        return None
    target = candidate_review_target(strategy, strategy_name, width)
    job = latest_job("candidate_review", int(target["id"]))
    return BackgroundJob(**job) if job else None


@app.post("/api/v1/value-candidates/saved", response_model=CandidateReviewRecord, status_code=status.HTTP_201_CREATED)
def post_saved_candidate_review(payload: CandidateReviewSave) -> CandidateReviewRecord:
    try:
        return save_candidate_review(payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.get("/api/v1/value-candidates/saved", response_model=CandidateReviewRecord | None)
def get_saved_candidate_review(
    strategy: str = Query(min_length=1, max_length=80),
    width: int | None = Query(default=None, ge=1, le=60),
) -> CandidateReviewRecord | None:
    return latest_candidate_review(strategy, width)


@app.post("/api/v1/agent-pool")
async def post_agent_pool(limit: int = Query(default=5, ge=3, le=50),
                          stance: str = Query(default="value", max_length=12)) -> dict:
    """智能体荐股池 · 打底层：五套规则取并集，代码打分排序。

    **不调模型，不花积分。** 也不自动跑——由页面上点了才跑，跟其它花钱的功能
    保持同一套习惯，虽然这一层其实不花钱。

    `stance` 是口味：value 价值 / trend 趋势 / both 两边都在。
    **分池子不是分权重**——价值和动量负相关，把两种分数平均只会选出
    两边都平庸的票。

    返回 dict 而不是 response_model：这一路的字段还在长，而本仓因为
    response_model 漏字段导致白屏已经发生过三次（见 test_response_models.py）。
    """
    try:
        return await asyncio.to_thread(agent_pool, limit, stance)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# ---------------------------------------------------------------- AI 选股

# 后台任务的目标 id。AI 选股每人同时只跑一个——它不像「复核某套策略」那样
# 天然有一个目标对象，所以这里固定一个槽位。任务行本身是按用户分域的，
# 不同用户不会撞在一起。
_AI_PICK_SLOT = 0


@app.get("/api/v1/screen/ai-pick/options")
def get_ai_pick_options() -> dict:
    """默认问法 + 现在能不能联网。**不花钱**，页面一进来就可以拿。"""
    return ai_pick_options()


@app.post("/api/v1/screen/ai-pick", response_model=BackgroundJob)
async def post_ai_pick(
    question: str = Query(min_length=2, max_length=200),
    web: bool = Query(default=True),
) -> BackgroundJob:
    """一句话选股：模型翻条件 → 代码在全 A 上筛 → 模型从命中里挑。

    进后台跑，理由跟模型复核一样：两次模型调用加一次联网，一分钟量级，
    绑在浏览器这次请求上等于「切走就白花钱」。
    """

    def work(_job_id: int):
        result = ai_pick_run(question, allow_web=web)
        return result.get("note") or "选完了", result

    try:
        job = await submit("ai_pick", _AI_PICK_SLOT, work,
                           label=f"正在按「{question[:18]}」选股")
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BackgroundJob(**job)


@app.get("/api/v1/screen/ai-pick/status", response_model=BackgroundJob | None)
def get_ai_pick_status() -> BackgroundJob | None:
    """切回找票页时把上一次的结果找回来。**花过钱的东西不能因为切页面就没了。**"""
    job = latest_job("ai_pick", _AI_PICK_SLOT)
    return BackgroundJob(**job) if job else None


@app.post("/api/v1/companies/{company_id}/advocate", response_model=BackgroundJob)
async def post_devils_advocate(company_id: int, payload: AdvocateAsk) -> BackgroundJob:
    """对话式反方：钉在这家公司上，专门找你这条判断可能错在哪。

    **只读、只提议。** 模型手里只有一组读库的工具（不能上网、不许用记忆里的数字），
    每条主张必须引用工具查到的数据，引不出来的当场丢掉；转成反证条件或研究任务
    要你自己点。它不会说该不该买卖——你的仓位与成本它都不知道。

    后台跑：一轮里要查好几张表，前台等着会超时。
    """

    _require_company(company_id)

    def work(_job_id: int):
        result = run_devils_advocate(company_id, payload.question, payload.history)
        if result is None:
            raise LedgerError("这家公司不在你的档案里。")
        count = len(result["points"])
        # **没结论有两种，别混成一种。**「没有拿得出数据支撑的主张」是模型查完之后
        # 真的没挑出毛病；而「跑满轮次没收敛」「最后那段 JSON 坏了」是这一轮没跑通。
        # 两种在存档上长得一样的话，使用者会把后者读成"这家公司查过了、没问题"。
        # 所以 converse 遇上后者会自己带一句 note 回来，这里让它盖住。
        note = result.get("note") or (
            f"查了 {result['rounds']} 次库，提出 {count} 条反方主张。"
            if count else "这一轮没有拿得出数据支撑的反方主张。")
        return note, result

    return BackgroundJob(**await submit("advocate", company_id, work, label="反方正在查库"))


@app.get("/api/v1/companies/{company_id}/advocate/history", response_model=list[BackgroundJob])
async def get_devils_advocate_history(
    company_id: int,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[BackgroundJob]:
    """读取这家公司的反驳历史；每一轮结果都保留在后台任务存档里。"""

    _require_company(company_id)
    return [BackgroundJob(**job) for job in list_background_jobs("advocate", company_id, limit)]


@app.get("/api/v1/companies/{company_id}/promises")
def get_company_promises(company_id: int) -> dict:
    """管理层承诺兑现台账：公司说过的话，到期之后有没有人回头看。

    能机器核的（净利润、营收、分红比例）到期自动比对——**那一段是纯算术**；
    核不了的到期问你一句。一条都不会被自动判成「未兑现」。
    """
    view = company_promises(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.post("/api/v1/companies/{company_id}/promises/extract", response_model=BackgroundJob)
async def post_extract_promises(company_id: int) -> BackgroundJob:
    """从已归档的公告里找承诺。**后台跑**，只抽取不落库，每条都要你确认。"""
    _require_company(company_id)

    def work(_job_id: int):
        result = extract_company_promises(company_id)
        if result is None:
            raise LedgerError("这家公司不在你的档案里。")
        return result["note"], result

    return BackgroundJob(**await submit("promise_extract", company_id, work,
                                        label="正在从公告里找管理层承诺"))


@app.post("/api/v1/companies/{company_id}/promises")
def post_promises(company_id: int, payload: PromiseBatch) -> dict:
    """把确认过的承诺记进台账。"""
    try:
        return save_promises(company_id, [item.model_dump() for item in payload.items])
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.patch("/api/v1/promises/{promise_id}")
def patch_promise(promise_id: int, payload: PromiseSettle) -> dict:
    """给一条承诺下结论。**结论由人下**——自动核对只说对上没对上。"""
    try:
        result = settle_promise(promise_id, payload.status, payload.note)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise not_found("promise")
    return result


@app.post("/api/v1/samples")
def post_samples() -> dict:
    """载入三份示例档案。**由使用者在空态点一下，不自动种。**"""
    return load_samples()


@app.delete("/api/v1/samples")
def delete_samples() -> dict:
    """删掉全部示例。删掉之后不会自己回来。"""
    return remove_samples()


@app.get("/api/v1/companies/{company_id}/chain-position")
def get_chain_position(company_id: int, refresh: bool = Query(default=False)) -> dict:
    """产业链位置：年报披露的客户与供应商集中度。**纯正则抽取，不花积分。**"""
    view = company_chain_position(company_id, refresh=refresh)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这家公司")
    return view


@app.get("/api/v1/companies/{company_id}/industry-metrics")
def get_company_industry_metrics(company_id: int) -> dict:
    """这门生意该盯的那几个数：白酒的合同负债、银行的拨贷比、地产的已售未结转。

    全部由代码从报表原始科目算出来，每条都带着公式和用到的科目。
    行业对不上就明说对不上，不硬凑。
    """
    view = company_industry_metrics(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/portfolios/{portfolio_id}/common-risk")
def get_portfolio_common_risk(portfolio_id: int) -> dict:
    """组合共同风险：我以为的分散，是不是同一个赌注下了五次。

    全部由代码算，模型不参与——「这两家算不算同一个风险」一旦编错，
    后果是你据此调仓。所以只报字面上重合的事实，每一条都能点开核对。

    返回 dict 而不是 response_model：字段还在长，而本仓因为
    response_model 漏字段导致白屏已经发生过四次（见 test_response_models.py）。
    """
    view = portfolio_common_risk(portfolio_id)
    if view is None:
        raise not_found("portfolio")
    return view


@app.get("/api/v1/attribution")
def get_decision_attribution() -> dict:
    """我写下的判断，后来怎么样了。**只数事实，不做模式识别。**"""
    return decision_attribution()


@app.get("/api/v1/quick-thesis/context")
def get_quick_thesis_context(symbol: str = Query(max_length=20)) -> dict:
    """写之前先把这家公司的认错条件候选备好。**不要求已经建档。**"""
    return quick_thesis_context(symbol)


@app.post("/api/v1/quick-thesis", status_code=status.HTTP_201_CREATED)
def post_quick_thesis(payload: dict) -> dict:
    """三十秒写下一个判断：哪家 · 为什么 · 什么情况下我认错。

    没建档就顺手建——**「先去建档」那一步就是绝大多数念头死掉的地方**。
    """
    try:
        return write_quick_thesis(payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/v1/companies/{company_id}/money-flow")
def get_company_money_flow(company_id: int, report_date: str | None = None) -> dict:
    """钱从哪来、去了哪：一期报表的流向桑基图。

    `report_date` 不传就是最近一期年报。传了会先落到「这家公司真有的期」这份
    清单上，对不上就退回默认 —— **不报错**：链接是从页面上生成的，
    一个过期的链接应该给出一张图，而不是一句报错。

    **不声明 response_model 是刻意的。** 这个接口返回的是图的节点与连线，
    形状随科目多少而变；套一个模型只会在加一根流量时把它悄悄吃掉
    （见 test_response_model_fields.py 里那个坑）。
    """
    view = company_money_flow(company_id, report_date)
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/companies/{company_id}/schedule")
def get_company_schedule(company_id: int) -> dict:
    """未来有哪些日子在等着：承诺台账 + 限售股解禁，排成甘特图。

    **路径不能叫 timeline** —— 那个已经被"估值走势 + 事件标记"占了。
    两个同路径的 @app.get 不会报错，FastAPI 只认先注册的那个，
    于是后写的那个接口静悄悄地永远不会被调用。

    **不声明 response_model**，理由同 money-flow：返回的是图的泳道与条目，
    形状随数据多少而变，套模型只会在加一条泳道时把它悄悄吃掉。
    """
    view = company_schedule(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/companies/{company_id}/valuation")
def get_company_valuation(company_id: int) -> dict:
    """三情景估值。**不是目标价**——它回答的是「如果这些假设成立，它值多少」。

    没存过就按这家公司自己的历史给一组初值；历史不够就明说缺什么，
    **不给编出来的默认值**（那种默认值会被当成基准，而且没有任何报错）。
    """
    view = company_valuation(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.put("/api/v1/companies/{company_id}/valuation")
def put_company_valuation(company_id: int, payload: dict) -> dict:
    """存下你的假设。每次存插一行，旧的留着——那是你判断变迁的记录。"""
    try:
        view = save_valuation(company_id, payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/companies/{company_id}/valuation/drift")
def get_valuation_drift(company_id: int) -> dict:
    """你的估值假设改过几次、每次是不是跟着股价走的。

    **给的是问题不是判决。** 调高假设可能完全正确——世界真的会变。
    """
    view = valuation_drift(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/sentiment/summary")
def get_sentiment_summary() -> dict:
    """情绪面的覆盖与新鲜度。页面靠它判断人气那一列能不能信。"""
    return sentiment_summary()


@app.get("/api/v1/trend/summary")
def get_trend_summary() -> dict:
    """趋势面的覆盖与新鲜度。榜单是当日快照，页面要能看出它是哪天的。"""
    return trend_summary()


@app.get("/api/v1/counter-hits")
def get_counter_hits() -> list[dict]:
    """还没处理的反证命中。这是整个工作台里最该先看的一类事。"""
    return open_counter_hits()


@app.post("/api/v1/counter-hits/check")
async def post_check_counter_hits(company_id: int | None = Query(default=None)) -> dict:
    """把还没核验的公告拿去和已写下的反证条件比对。"""
    try:
        return await asyncio.to_thread(check_counter_hits, company_id)
    except llm.CreditsError:
        # **CreditsError 是 RuntimeError 的子类**，不先放它过去的话，
        # 「额度不足 / 闸口熔断」会被下面那行改写成 503——而 503 的意思是
        # 「服务坏了，等会儿再试」，前端据此重试，用户看不到该看的那句话。
        # 真跑一遍才发现的：熔断触发时接口返回的是 503，不是 402。
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/api/v1/counter-hits/{hit_id}/acknowledge")
def post_acknowledge_counter_hit(hit_id: int) -> dict:
    """标记「我看过了」。不代表同意——只是不再顶在最前面。"""
    if not acknowledge_counter_hit(hit_id):
        raise not_found("counter hit")
    return {"acknowledged": True}


@app.get("/api/v1/assessment-matrix")
def get_assessment_matrix() -> dict:
    """研究池 × 方法体检：一眼横向比较。"""
    return assessment_matrix()


@app.get("/api/v1/companies/{company_id}/timeline")
def get_company_timeline(company_id: int, years: int = Query(default=2, ge=1, le=10)) -> dict:
    """一根对齐的时间轴：估值分位、实质公告、财报期、你的买卖与写下判断的时点。"""
    payload = company_timeline(company_id, years)
    if payload is None:
        raise not_found("company")
    return payload


@app.get("/api/v1/companies/{company_id}/deep-report/plan")
def get_deep_report_plan(company_id: int) -> dict:
    """跑之前先看要搜几个问题、大概多少积分。点之前就该知道，不是点完看账单。"""
    payload = deep_report_plan(company_id)
    if payload is None:
        raise not_found("company")
    return payload


@app.post("/api/v1/companies/{company_id}/deep-report")
async def post_deep_report(company_id: int) -> BackgroundJob:
    """联网找资料 + 库里的真实数字，写一份带图的报告。走后台任务：一次一两分钟。"""
    if get_company(company_id) is None:
        raise not_found("company")

    _require_company(company_id)

    def work(_job_id: int) -> str:
        result = generate_deep_report(company_id)
        if result is None:
            raise RuntimeError("没有这家公司")
        return (f"{result['title'][:60]}　引用 {result['source_count']} 条。"
                + (result.get("search_note") or ""))

    return BackgroundJob(**await submit("deep_report", company_id, work,
                                        label="正在联网检索并写报告"))


@app.post("/api/v1/tasks/items/{item_id}/assessment")
async def post_task_item_assessment(item_id: int) -> BackgroundJob:
    """给一个候选跑方法体检。**不要求先建档**——体检就是用来帮你决定要不要建档的。

    走后台任务：一次要读六期年报四期季报再让模型逐个方法打分，二十秒起步。
    """
    # 跟 thesis-write 同一个道理：submit() 先返回 200，检查在任务内部就晚了。
    # 候选挂在研究任务下，所以按「这条候选属不属于我的任务」挡。
    _require_task_item(item_id)

    def work(_job_id: int) -> str:
        result = assess_task_item(item_id)
        if result is None:
            raise RuntimeError("没有这个候选")
        counts = "、".join(f"{k} {v}" for k, v in result["counts"].items())
        return f"{result['name']} 体检完成：{counts}。"

    return BackgroundJob(**await submit("item_assessment", item_id, work,
                                        label="模型正在按方法库逐条打分"))


@app.post("/api/v1/evidences/unverify-bulk")
def post_unverify_bulk() -> dict:
    """把批量归档时被替人盖上「已核验」的证据退回「待核验」。

    实测线上 280 条证据全部是「已核验」，没有一条被人看过 ——
    这个标记因此没有任何信息量。只退回机器搬进来的那些（来源是巨潮/交易所），
    手工写的不动。
    """
    return unverify_bulk_archived_evidence()


@app.get("/api/v1/companies/{company_id}/evidence-direction")
def get_evidence_direction(company_id: int) -> dict:
    """证据方向轴：判过方向的事件，按时间排好。"""
    payload = evidence_direction(company_id)
    if payload is None:
        raise not_found("company")
    return payload


@app.get("/api/v1/companies/{company_id}/evidence-direction/plan")
def get_evidence_direction_plan(company_id: int) -> dict:
    """跑之前先看要判多少件、大概花多少积分。点之前就该知道，不是点完看账单。"""
    payload = evidence_direction_plan(company_id)
    if payload is None:
        raise not_found("company")
    return payload


@app.post("/api/v1/companies/{company_id}/evidence-direction")
async def post_evidence_direction(company_id: int) -> dict:
    """让模型判一遍方向。走闸口计费——这是模型调用。"""
    try:
        payload = await asyncio.to_thread(judge_evidence_direction, company_id)
    except llm.CreditsError:
        # **CreditsError 是 RuntimeError 的子类**，不先放它过去的话，
        # 「额度不足 / 闸口熔断」会被下面那行改写成 503——而 503 的意思是
        # 「服务坏了，等会儿再试」，前端据此重试，用户看不到该看的那句话。
        # 真跑一遍才发现的：熔断触发时接口返回的是 503，不是 402。
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if payload is None:
        raise not_found("company")
    return payload


@app.get("/api/v1/companies/{company_id}/segments")
def get_company_segments(company_id: int) -> dict:
    """这家公司靠什么赚钱：年报分部附注里的收入占比与各块毛利率。"""
    payload = business_segments(company_id)
    if payload is None:
        raise not_found("company")
    return payload


@app.post("/api/v1/companies/{company_id}/segments")
def refresh_company_segments(company_id: int) -> dict:
    """重新拉一次主营构成。不过闸口——这是公开财报数据，不调用模型。"""
    payload = refresh_business_segments(company_id)
    if payload is None:
        raise not_found("company")
    return payload


@app.get("/api/v1/companies/{company_id}/peer-table")
def get_company_peer_table(company_id: int) -> dict:
    """同一行业里真正的同行（来自全市场底座），不是研究池里碰巧同行业的那几家。"""
    company = get_company(company_id)
    if company is None:
        raise not_found("company")
    return peer_table(company)


@app.get("/api/v1/companies/{company_id}/peer-position")
def get_company_peer_position(company_id: int) -> dict:
    """这家公司四项指标各自在同行业分布里的位置。

    单看「PE 21 倍」是判断不了贵贱的——对白酒算便宜，对银行算贵得离谱。
    比较对象取自全市场底座的行业分类，不是档案里自己填的那个。
    """
    company = get_company(company_id)
    if company is None:
        raise not_found("company")
    return peer_position(company)


@app.get("/api/v1/companies/{company_id}/assessment")
def get_company_assessment(company_id: int) -> dict:
    """这家公司存着的体检结果。没跑过就返回空壳，页面据此显示「还没体检」。"""
    payload = list_assessments(company_id)
    if payload is None:
        raise not_found("company")
    return payload


@app.post("/api/v1/companies/{company_id}/assessment")
async def post_company_assessment(company_id: int) -> dict:
    """跑一次体检。

    要花二十多秒（八个方法一次调用），所以放线程里，避免卡住事件循环里的其它请求。
    还没做成后台任务：它比同步公司档案快得多，切走页面重进能看到已落库的结果。
    """
    try:
        payload = await asyncio.to_thread(run_assessment, company_id)
    except llm.CreditsError:
        # **CreditsError 是 RuntimeError 的子类**，不先放它过去的话，
        # 「额度不足 / 闸口熔断」会被下面那行改写成 503——而 503 的意思是
        # 「服务坏了，等会儿再试」，前端据此重试，用户看不到该看的那句话。
        # 真跑一遍才发现的：熔断触发时接口返回的是 503，不是 402。
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if payload is None:
        raise not_found("company")
    payload["billing"] = llm.collected()
    return payload


@app.post("/api/v1/companies/{company_id}/thesis-write", response_model=BackgroundJob)
async def post_thesis_write(company_id: int, method: str | None = Query(default=None)) -> BackgroundJob:
    """按某个方法写一条投资逻辑，**后台跑并直接写进档案**。

    要二十多秒，所以走后台任务：切走页面回来它还在跑，跑完直接落库。
    原先是「同步生成草稿 + 你再点保存」，草稿只活在页面上——切一个页签就没了，
    得重新生成重新等。实测丢过一次。
    """
    # **归属检查要在 submit 之前。** submit() 在任务开跑前就返回 200，
    # 检查跑到任务内部的话，别人的公司 id 也能提交一个任务进来。
    # 六个兄弟接口（advocate / thesis-draft / deep-report / promises-extract /
    # supply-chain-refresh / reports）都在这儿挡了一道，这一个漏了。
    _require_company(company_id)

    def work(_job_id: int):
        result = draft_and_save_thesis(company_id, method)
        if result is None:
            raise RuntimeError("没有这家公司")
        return result

    return BackgroundJob(**await submit(
        "thesis_write", company_id, work, label="模型正在按方法写一条投资逻辑"))


@app.delete("/api/v1/theses/{thesis_id}")
def delete_thesis_endpoint(thesis_id: int) -> dict:
    """删掉一条投资逻辑。

    证据和事件不跟着删——它们是已经发生的事实，不因为某条判断被丢掉而失效。
    """
    if not delete_thesis(thesis_id):
        raise not_found("thesis")
    return {"deleted": True}


def _require_task_item(item_id: int) -> None:
    """这条候选是不是我的研究任务下的。**查不到就 404，不说"不是你的"** ——
    区分"不存在"和"不是你的"本身就是一次信息泄漏。"""
    from .database import connection
    from .repository import _sw

    with connection() as conn:
        row = conn.execute(
            """SELECT 1 FROM research_task_items i
               JOIN research_tasks t ON t.id = i.task_id
               WHERE i.id = ?""" + _sw("t"), (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这个候选。")


def _require_company(company_id: int) -> None:
    """确认这家公司是当前用户的，不是就 404。**必须在 submit() 之前调用。**

    ## 为什么后台任务接口特别容易漏这一步

    同步接口里，归属检查天然在返回值前面：查不到就 raise 404。
    改成后台任务之后，`submit()` 在任务开跑前就返回 200 了——
    检查跑到了任务内部，于是**别人的公司也能提交一个任务**，
    虽然它随后会失败，但攻击者已经拿到 200，还能从任务表里读到失败信息。

    实测就是这么漏的：thesis-draft 从同步改成后台任务之后，
    test_idor 立刻红了（「返回 200，别人的记录」）。
    """
    from .repository import get_company

    if get_company(company_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这家公司")


@app.post("/api/v1/companies/{company_id}/thesis-draft", response_model=BackgroundJob)
async def post_thesis_draft(company_id: int,
                            method: str | None = Query(default=None)) -> BackgroundJob:
    """起草一条投资逻辑。**后台跑。**

    ## 为什么从同步接口改成后台任务

    改成工具循环之后（模型自己查库），这个动作从 7 秒变成 **57 秒实测**。
    而接口一直是同步阻塞的，界面上唯一的反馈是按钮文字变成「正在查库起草…」——
    使用者点完等了几秒、看不出任何进展，判定它坏了。**那个判断很合理。**

    产品里其它慢动作（承诺抽取、反方 Agent、深度报告）早就都是后台任务了，
    只有这一个不是——因为它以前不慢。功能变慢了，承载它的形状就得跟着换。
    """
    _require_company(company_id)

    def work(_job_id: int):
        draft = draft_thesis(company_id, method)
        if draft is None:
            raise LedgerError("这家公司不在你的档案里。")
        payload = draft.model_dump()
        payload["billing"] = llm.collected()
        headline = (payload.get("structure") or {}).get("headline") or payload.get("claim") or ""
        return f"起草完成：{str(headline)[:60]}", payload

    return BackgroundJob(**await submit("thesis_draft", company_id, work,
                                        label="正在查库起草这条投资逻辑"))


@app.post("/api/v1/news/refresh", response_model=BackgroundJob)
async def post_news_refresh() -> BackgroundJob:
    """抓取并自动对应。**走后台任务。**

    实测一轮要 20 秒以上：十几个 RSS 源逐个抓（有的源本身就慢，还会超时），
    再把规则没接住的标题分批送给模型。同步跑的话页面就那么卡着，
    切走再回来还得从头点一次——而这一轮的花费已经产生了。
    """
    def work(_job_id: int) -> str:
        result = refresh_news()
        return str(result.get("note") or "抓取完成。")

    return BackgroundJob(**await submit("news_refresh", 0, work, label="正在抓取并自动对应"))


@app.get("/api/v1/news/feeds", response_model=list[NewsFeed])
async def get_news_feeds() -> list[NewsFeed]:
    # 订阅源是**整个实例**的一份配置：加一条，所有人的资讯证据都会多这个来源。
    # 此前四个接口一个守卫都没有 —— 游客被"只读"中间件挡着，
    # 但**任何登录用户都能给全站加源、删源**。
    access.require_owner("查看订阅源")
    return [NewsFeed(**row) for row in list_news_feeds()]


@app.post("/api/v1/news/feeds", response_model=NewsFeed, status_code=status.HTTP_201_CREATED)
async def post_news_feed(payload: NewsFeedInput) -> NewsFeed:
    access.require_owner("添加订阅源")
    return NewsFeed(**save_news_feed(payload))


@app.patch("/api/v1/news/feeds/{feed_id}")
async def patch_news_feed(feed_id: int, enabled: bool = Query(...)) -> dict[str, bool]:
    access.require_owner("开关订阅源")
    return {"updated": toggle_news_feed(feed_id, enabled)}


@app.delete("/api/v1/news/feeds/{feed_id}")
async def delete_news_feed_route(feed_id: int) -> dict[str, bool]:
    access.require_owner("删除订阅源")
    return {"deleted": delete_news_feed(feed_id)}


@app.get("/api/v1/news", response_model=NewsPage)
async def get_news(
    status: str = Query(default="待确认"),
    company_id: int | None = Query(default=None),
    limit: int = Query(default=60, ge=1, le=200),
    read: str = Query(default="全部"),
) -> NewsPage:
    return NewsPage(**list_news(status, company_id, limit, read))


@app.post("/api/v1/news/{news_id}/confirm")
async def post_news_confirm(news_id: int, company_id: int | None = Query(default=None)) -> dict[str, int]:
    try:
        result = confirm_news(news_id, company_id)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这条资讯")
    return result


@app.post("/api/v1/news/{news_id}/ignore")
async def post_news_ignore(news_id: int) -> dict[str, bool]:
    return {"ignored": ignore_news(news_id)}


@app.post("/api/v1/news/{news_id}/read")
async def post_news_read(news_id: int) -> dict[str, object]:
    result = mark_news_read(news_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这条资讯")
    return result


@app.get("/api/v1/industry-chains", response_model=list[IndustryChainThemeSummary])
def get_industry_chains() -> list[IndustryChainThemeSummary]:
    return [IndustryChainThemeSummary(**row) for row in list_industry_chain_themes()]


@app.post("/api/v1/industry-chains", response_model=IndustryChainView, status_code=status.HTTP_201_CREATED)
def post_industry_chain(payload: IndustryChainThemeCreate) -> IndustryChainView:
    try:
        return IndustryChainView(**create_industry_chain_theme(payload.model_dump()))
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/api/v1/industry-chains/draft", response_model=BackgroundJob)
async def post_industry_chain_draft(payload: IndustryChainDraftRequest) -> BackgroundJob:
    """输入一个主题，后台检索公开资料并生成一张待确认的可编辑初稿。"""

    topic = payload.topic.strip()

    def work(_job_id: int):
        from .industry_chain_draft import generate

        result = generate(topic)
        return f"已生成「{result['theme_name']}」：{result['stages']} 个阶段、{result['nodes']} 个节点，全部待确认。", result

    try:
        job = await submit("industry_chain_draft", 0, work, label=f"正在为「{topic[:24]}」查公开资料并起草底图")
    except (LedgerError, RuntimeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BackgroundJob(**job)


@app.get("/api/v1/industry-chains/draft/status", response_model=BackgroundJob | None)
async def get_industry_chain_draft_status() -> BackgroundJob | None:
    """回到地图页时恢复最近一次初稿任务；花过时间和积分的结果不能丢。"""

    job = latest_job("industry_chain_draft", 0)
    return BackgroundJob(**job) if job else None


@app.post("/api/v1/industry-chains/{theme_id}/fork", response_model=IndustryChainView,
          status_code=status.HTTP_201_CREATED)
def post_industry_chain_fork(theme_id: int) -> IndustryChainView:
    view = fork_industry_chain_theme(theme_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这张产业链底图")
    return IndustryChainView(**view)


@app.delete("/api/v1/industry-chains/records/{kind}/{record_id}")
def delete_industry_chain_record_route(kind: str, record_id: int) -> dict[str, bool]:
    if kind not in {"theme", "stage", "node", "edge", "position"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这种产业链记录")
    return {"deleted": delete_industry_chain_record(kind, record_id)}


@app.get("/api/v1/industry-chains/{theme_id}", response_model=IndustryChainView)
def get_industry_chain_route(theme_id: int) -> IndustryChainView:
    view = get_industry_chain(theme_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这张产业链底图")
    return IndustryChainView(**view)


@app.get("/api/v1/industry-chains/{theme_id}/compare", response_model=ChainCompareView)
def get_industry_chain_compare(theme_id: int) -> ChainCompareView:
    """按环节横排这张底图上的公司。

    行业分类(申万 / 证监会)是按公司主营分的,分不出「同一种材料在两条链上是两个市场」;
    底图把公司挂在环节上,所以这里能做到通用行业分类做不到的横比。
    指标全部来自全市场底座 `market_universe`,跟着 `universe` 同步任务走(每 30 分钟)。
    """
    view = industry_chain_compare(theme_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这张产业链底图")
    return ChainCompareView(**view)


@app.post("/api/v1/industry-chains/{theme_id}/stages", response_model=IndustryChainView)
def post_industry_chain_stage(theme_id: int, payload: IndustryChainStageCreate) -> IndustryChainView:
    try:
        view = add_industry_chain_stage(theme_id, payload.model_dump())
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这张产业链底图")
    return IndustryChainView(**view)


@app.post("/api/v1/industry-chains/{theme_id}/nodes", response_model=IndustryChainView)
def post_industry_chain_node(theme_id: int, payload: IndustryChainNodeCreate) -> IndustryChainView:
    try:
        view = add_industry_chain_node(theme_id, payload.model_dump())
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="阶段或底图不存在")
    return IndustryChainView(**view)


@app.patch("/api/v1/industry-chains/{theme_id}/nodes/{node_id}/market-size", response_model=IndustryChainView)
def patch_industry_chain_node_market_size(
    theme_id: int, node_id: int, payload: IndustryChainNodeMarketSize
) -> IndustryChainView:
    """给一个环节补上市场盘子(亿元人民币)+ 口径 + 出处,供「环节拥挤度」当分母。"""

    view = set_industry_chain_node_market_size(theme_id, node_id, payload.model_dump())
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点或底图不存在")
    return IndustryChainView(**view)


@app.post("/api/v1/industry-chains/{theme_id}/edges", response_model=IndustryChainView)
def post_industry_chain_edge(theme_id: int, payload: IndustryChainEdgeCreate) -> IndustryChainView:
    try:
        view = add_industry_chain_edge(theme_id, payload.model_dump())
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点或底图不存在")
    return IndustryChainView(**view)


@app.post("/api/v1/industry-chains/{theme_id}/positions", response_model=IndustryChainView)
def post_industry_chain_position(theme_id: int, payload: IndustryChainPositionCreate) -> IndustryChainView:
    try:
        view = add_industry_chain_position(theme_id, payload.model_dump(mode="json"))
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点或底图不存在")
    return IndustryChainView(**view)


@app.get("/api/v1/companies/{company_id}/industry-chain-positions", response_model=CompanyIndustryChainPositions)
def get_company_industry_chain_positions(company_id: int) -> CompanyIndustryChainPositions:
    view = company_industry_chain_positions(company_id)
    if view is None:
        raise not_found("company")
    return CompanyIndustryChainPositions(**view)


@app.get("/api/v1/companies/{company_id}/supply-chain", response_model=SupplyChainView)
async def get_company_supply_chain(company_id: int) -> SupplyChainView:
    view = get_supply_chain(company_id)
    if view is None:
        raise not_found("company")
    return SupplyChainView(**view)


@app.post("/api/v1/companies/{company_id}/supply-chain/refresh", response_model=BackgroundJob)
async def post_supply_chain_refresh(company_id: int) -> BackgroundJob:
    """提交后台任务：模型跑在服务里，切页面不会中断。"""

    if get_company(company_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这家公司")

    _require_company(company_id)

    def work(_job_id: int) -> str:
        view = refresh_supply_chain(company_id)
        return f"整理了 {len((view or {}).get('links', []))} 条线索，全部标为待证实。"

    return BackgroundJob(**await submit("supply_chain", company_id, work, label="模型正在整理经营关系线索"))


@app.post("/api/v1/companies/{company_id}/supply-chain", response_model=SupplyChainView)
def post_supply_chain_link(company_id: int, payload: dict) -> SupplyChainView:
    """手动加一条关系。模型给的往往不全，你自己知道的得有地方录。"""
    view = add_supply_chain_link(company_id, payload)
    if view is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="关系类型必须是上游供应/下游客户/同业对手/替代方案之一，且对方名称不能为空")
    return SupplyChainView(**view)


@app.delete("/api/v1/reports/{report_id}")
def delete_research_report(report_id: int) -> dict:
    """删一份报告。报告是可再生的——重跑一次就有，所以不做二次确认。"""
    return {"deleted": delete_report(report_id)}


@app.post("/api/v1/supply-chain/{link_id}/confirm")
async def post_supply_chain_confirm(link_id: int, evidence_id: int | None = Query(default=None)) -> dict[str, bool]:
    return {"confirmed": confirm_supply_chain_link(link_id, evidence_id)}


@app.delete("/api/v1/supply-chain/{link_id}")
async def delete_supply_chain(link_id: int) -> dict[str, bool]:
    return {"deleted": delete_supply_chain_link(link_id)}


@app.get("/api/v1/reports", response_model=list[ResearchReport])
async def get_reports(company_id: int | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100)) -> list[ResearchReport]:
    return [ResearchReport(**row) for row in list_reports(company_id, limit)]


@app.post("/api/v1/companies/{company_id}/reports", response_model=BackgroundJob)
async def post_company_report(company_id: int) -> BackgroundJob:
    """提交后台任务：简报要读几十条证据再写，切页面不会中断。"""

    if get_company(company_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这家公司")

    _require_company(company_id)

    def work(_job_id: int) -> str:
        report = generate_report(company_id)
        return f"生成了 v{(report or {}).get('version')}：{(report or {}).get('title')}"

    return BackgroundJob(**await submit("report", company_id, work, label="模型正在读已归档的证据"))


@app.get("/api/v1/methods", response_model=ThesisMethodLibrary)
async def get_methods() -> ThesisMethodLibrary:
    return method_library()


@app.get("/api/v1/methods/{method_key}", response_model=ThesisMethod)
async def get_method(method_key: str) -> ThesisMethod:
    method = method_detail(method_key)
    if method is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这个方法")
    return method


@app.post("/api/v1/inbox/classify", response_model=InboxClassifyResult)
async def post_inbox_classify(
    limit: int = Query(default=400, ge=1, le=2000),
    use_ai: bool = Query(default=True),
    regrade: bool = Query(default=False),
) -> InboxClassifyResult:
    # 分级要发网络请求，放到线程里跑，避免卡住事件循环。
    #
    # 页面上勾了「重新分级」= 你明确要求重做一遍，所以 force_model 跟着 regrade 走，
    # 无条件重送模型。后台每日整理走的是另一条路（force_model=False），
    # 只送模型没看过的和口径变过的——那才是会按天重复计费的地方。
    result = await asyncio.to_thread(classify_inbox, limit, use_ai, 25, 8, regrade, regrade)
    result = InboxClassifyResult(**result) if isinstance(result, dict) else result
    result.billing = Billing(**llm.collected())
    return result


@app.get("/api/v1/inbox/learning")
def get_inbox_learning() -> dict:
    """分级引擎从你的纠错里学到了什么。**只提议，不自动生效。**

    规则词表直接决定几百条公告的去向，学歪一个词会静悄悄地把一整类实质公告
    扔进程序性堆里——页面上看不出来，只会觉得「最近公告怎么变少了」。
    """
    return correction_stats()


@app.post("/api/v1/inbox/rule-terms")
def post_rule_term(
    term: str = Query(min_length=2, max_length=20),
    relevance: str = Query(pattern="^(高|中|低)$"),
    topic: str = Query(default="自定义", max_length=20),
    note: str = Query(default="", max_length=200),
) -> dict:
    try:
        return save_rule_term(term, relevance, topic, note)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.delete("/api/v1/inbox/rule-terms/{term}")
def delete_rule_term_route(term: str) -> dict[str, bool]:
    return {"deleted": delete_rule_term(term)}


@app.post("/api/v1/inbox/ignore-by-relevance")
def post_inbox_ignore_batch(relevance: str = Query(default="低", pattern="^(高|中|低)$")) -> dict[str, int]:
    return {"ignored": ignore_by_relevance(relevance)}


@app.post("/api/v1/inbox/{item_id}/archive", response_model=InboxActionResult)
def post_inbox_archive(item_id: int, payload: InboxArchive) -> InboxActionResult:
    try:
        result = archive_inbox_item(item_id, payload)
    except (LedgerError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not result:
        raise not_found("inbox item")
    return result


@app.post("/api/v1/inbox/{item_id}/ignore", response_model=InboxItem)
def post_inbox_ignore(item_id: int) -> InboxItem:
    item = ignore_inbox_item(item_id)
    if not item:
        raise not_found("inbox item")
    return item


@app.post("/api/v1/inbox/{item_id}/reopen", response_model=InboxItem)
def post_inbox_reopen(item_id: int) -> InboxItem:
    try:
        item = reopen_inbox_item(item_id)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not item:
        raise not_found("inbox item")
    return item


@app.get("/api/v1/sync/jobs", response_model=list[SyncJobStatus])
def get_sync_jobs() -> list[SyncJobStatus]:
    # **读也要挡。** 改间隔、手动触发早就是站主专属了，但列表一直敞着 ——
    # 于是游客能看到整台机器的排期、上次成功时间、每次取回多少条，
    # 还有一排「立即运行」按钮。这是这台实例的运维面板，不是给用户看的内容。
    access.require_owner("查看同步任务")
    return list_jobs()


@app.patch("/api/v1/sync/jobs/{job_id}", response_model=SyncJobStatus)
def patch_sync_job(job_id: str, payload: SyncJobUpdate) -> SyncJobStatus:
    # 定时任务是**整个实例**的一份配置，不是某个人的。改间隔、开关，
    # 影响的是所有人的后台行为——按数据域过滤在这里没有意义，只能按人挡。
    access.require_owner("修改定时任务")
    job = update_job(job_id, payload.enabled, payload.interval_minutes)
    if not job:
        raise not_found("sync job")
    return job


@app.post("/api/v1/sync/jobs/{job_id}/run", response_model=SyncRunResult)
async def post_sync_job_run(job_id: str) -> SyncRunResult:
    # 手动触发会把作业替**所有**数据域跑一遍（收件箱整理就是逐用户跑的），
    # 开了模型分级的人会因此被扣分——不是他自己点的。
    access.require_owner("手动触发定时任务")
    # 同步任务是阻塞 IO，放到线程里跑，避免卡住事件循环里的其它请求。
    result = await asyncio.to_thread(run_job, job_id, "手动")
    if not result:
        raise not_found("sync job")
    return result


@app.get("/api/v1/sync/strip")
def get_sync_strip(per_job: int = Query(default=24, ge=4, le=60)) -> list[dict]:
    """每个作业最近 N 次的成败。列表看不出规律，排成一行才看得出来。"""
    access.require_owner("查看同步任务的成败")
    return run_strip(per_job)


@app.get("/api/v1/sync/runs", response_model=list[SyncRunRecord])
def get_sync_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[SyncRunRecord]:
    access.require_owner("查看同步运行记录")
    return list_runs(limit)


@app.get("/api/v1/reviews/queue", response_model=list[ReviewQueueItem])
def get_review_queue() -> list[ReviewQueueItem]:
    return review_queue()


@app.get("/api/v1/theses")
def get_all_theses() -> list[dict]:
    """你写过的全部投资逻辑。

    **首页那张「投资逻辑 N 条」的卡片原来点进复核工作台**，而复核工作台
    按定义只放"有具体理由该重看的"——不到复核期时是空的。
    使用者看到的是：我有 5 条判断，点一下，什么都没有。
    """
    return all_theses()


@app.get("/api/v1/reviews/attribution", response_model=ReviewAttribution)
def get_review_attribution(quarters: int = Query(default=4, ge=1, le=12)) -> ReviewAttribution:
    return review_attribution(quarters)


@app.get("/api/v1/theses/{thesis_id}/review-context", response_model=ThesisReviewContext)
def get_thesis_review_context(thesis_id: int) -> ThesisReviewContext:
    context = thesis_review_context(thesis_id)
    if not context:
        raise not_found("thesis")
    return context


@app.post("/api/v1/theses/{thesis_id}/reviews", response_model=ThesisReviewContext, status_code=status.HTTP_201_CREATED)
def post_thesis_review(thesis_id: int, payload: ThesisReviewCreate) -> ThesisReviewContext:
    try:
        context = create_thesis_review(thesis_id, payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not context:
        raise not_found("thesis")
    return context


@app.get("/api/v1/industries", response_model=list[IndustrySummary])
def get_industries() -> list[IndustrySummary]:
    return list_industries()


@app.get("/api/v1/industries/comparison", response_model=IndustryComparison)
def get_industry_comparison(industry: str | None = Query(default=None, max_length=60)) -> IndustryComparison:
    return industry_comparison(industry)


@app.get("/api/v1/universe/summary", response_model=UniverseSummary)
def get_universe_summary() -> UniverseSummary:
    return universe_summary()


@app.get("/api/v1/universe/sample", response_model=list[UniverseRow])
def get_universe_sample(
    limit: int = Query(default=20, ge=1, le=200),
    board: str | None = Query(default=None, max_length=20),
) -> list[UniverseRow]:
    return universe_sample(limit, board)


@app.get("/api/v1/screen/strategies", response_model=list[ScreenStrategy])
def get_screen_strategies() -> list[ScreenStrategy]:
    return list_screen_strategies()


@app.post("/api/v1/screen/strategies", response_model=ScreenStrategy, status_code=status.HTTP_201_CREATED)
def post_screen_strategy(payload: ScreenStrategySave) -> ScreenStrategy:
    return save_screen_strategy(payload)


@app.get("/api/v1/screen/fields", response_model=list[ScreenField])
def get_screen_fields() -> list[ScreenField]:
    return screen_fields()


@app.delete("/api/v1/screen/strategies/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_screen_strategy_endpoint(key: str) -> None:
    try:
        removed = delete_screen_strategy(key)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not removed:
        raise not_found("strategy")


@app.post("/api/v1/screen/run", response_model=ScreenResult)
def post_screen_run(
    strategy: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=30, ge=1, le=200),
    # 只影响这一次查看，不写回策略——规则属于策略，排序属于「你现在想怎么看」。
    sort_field: str | None = Query(default=None, max_length=40),
    sort_desc: bool | None = Query(default=None),
    payload: ScreenAdHoc | None = None,
) -> ScreenResult:
    """带 strategy 参数时跑已保存的策略；带 body 时跑界面上刚改出来的临时条件。"""

    try:
        if payload is not None:
            result = run_screen(limit=limit, record=False, ad_hoc=payload.model_dump())
        elif strategy:
            result = run_screen(strategy, limit, sort_field=sort_field, sort_desc=sort_desc)
        else:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="需要指定策略或临时条件")
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not result:
        raise not_found("strategy")
    result = ScreenResult(**result) if isinstance(result, dict) else result
    result.billing = Billing(**llm.collected())
    return result


@app.get("/api/v1/screen/runs", response_model=list[ScreenRunRecord])
def get_screen_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[ScreenRunRecord]:
    return list_screen_runs(limit)


@app.post("/api/v1/universe/range-returns")
async def post_universe_range_returns() -> dict[str, object]:
    """用自建日线补 5 日与 20 日涨跌，不联网。"""

    return await asyncio.to_thread(backfill_universe_range_returns)


@app.get("/api/v1/briefing", response_model=DailyBriefing | None)
async def get_briefing() -> DailyBriefing | None:
    record = latest_briefing()
    return DailyBriefing(**record) if record else None


@app.post("/api/v1/briefing", response_model=BackgroundJob)
async def post_briefing() -> BackgroundJob:
    """后台生成：要读云图、持仓、逻辑与公告，切页面不该中断。"""

    def work(_job_id: int) -> str:
        result = generate_briefing()
        return result.get("headline", "")

    return BackgroundJob(**await submit("briefing", 0, work, label="模型正在读今天的变化"))


@app.get("/api/v1/heatmap", response_model=HeatmapView)
def get_heatmap(
    scope: str = Query(default="all", max_length=60),
    metric: str = Query(default="roe", max_length=30),
    limit: int = Query(default=60, ge=5, le=200),
) -> HeatmapView:
    try:
        return market_heatmap(scope, metric, limit)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.get("/api/v1/market/lenses")
def get_market_lenses() -> list[dict[str, object]]:
    return market_lens_statuses()


@app.get("/api/v1/market/fund-flow", response_model=MarketFundFlowView)
def get_market_fund_flow() -> MarketFundFlowView:
    try:
        return MarketFundFlowView(**market_fund_flow_view())
    except MarketDataError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/api/v1/universe/percentile", response_model=UniversePercentile)
def get_universe_percentile(
    symbol: str = Query(min_length=6, max_length=6),
    metric: str = Query(default="pe_ttm", pattern="^(pe_ttm|pb)$"),
) -> UniversePercentile:
    return universe_valuation_percentile(symbol, metric)


@app.post("/api/v1/tasks", response_model=ResearchTaskRecord, status_code=status.HTTP_201_CREATED)
def post_research_task(payload: ResearchTaskCreate) -> ResearchTaskRecord:
    try:
        task = create_research_task(payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not task:
        raise not_found("strategy")
    return task


@app.get("/api/v1/tasks", response_model=list[ResearchTaskRecord])
def get_research_tasks(limit: int = Query(default=20, ge=1, le=100)) -> list[ResearchTaskRecord]:
    return list_research_tasks(limit)


@app.get("/api/v1/tasks/{task_id}", response_model=ResearchTaskRecord)
def get_research_task_detail(task_id: int) -> ResearchTaskRecord:
    task = get_research_task(task_id)
    if not task:
        raise not_found("task")
    return task


@app.patch("/api/v1/tasks/{task_id}", response_model=ResearchTaskRecord)
def patch_research_task(task_id: int, payload: ResearchTaskUpdate) -> ResearchTaskRecord:
    task = update_research_task(task_id, payload)
    if not task:
        raise not_found("task")
    return task


@app.delete("/api/v1/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_research_task(task_id: int) -> Response:
    try:
        deleted = delete_research_task(task_id)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if deleted is None:
        raise not_found("task")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.patch("/api/v1/tasks/items/{item_id}", response_model=ResearchTaskRecord)
def patch_task_item(item_id: int, payload: ResearchTaskItemUpdate) -> ResearchTaskRecord:
    try:
        task = update_task_item(item_id, payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not task:
        raise not_found("task item")
    return task


# ═══════════════════════════════════════════════════════════════════════════
# 我的判断 · 做 T 回测 / 决策闭环 / 上涨类型
#
# 三个接口都**不声明 response_model**，理由跟 money-flow 那几个一样：
# 返回的是判据表与图的数据，形状随判据多少而变；套一个模型只会在加一条判据时
# 把它悄悄吃掉（见 test_response_model_fields.py 里那个坑）。
# ═══════════════════════════════════════════════════════════════════════════


@app.get("/api/v1/companies/{company_id}/swing")
def get_swing_study(
    company_id: int,
    window: int = Query(default=250, ge=0, le=2000),
    trigger_percent: float = Query(default=1.0, ge=0.0, le=20.0),
    base_shares: int = Query(default=10000, ge=100, le=100_000_000),
    tactical_percent: float = Query(default=20.0, gt=0.0, le=100.0),
    commission_rate: float = Query(default=0.00025, ge=0.0, le=0.01),
    commission_min: float = Query(default=5.0, ge=0.0, le=100.0),
    stamp_tax_rate: float = Query(default=0.0005, ge=0.0, le=0.01),
    transfer_fee_rate: float = Query(default=0.00001, ge=0.0, le=0.01),
    slippage_rate: float = Query(default=0.0, ge=0.0, le=0.05),
) -> dict:
    """做 T 的规律检验 + 四条策略的机器模拟。**纯算术，不调模型，不花积分。**

    费率全部开成参数：**费率差一倍，结论会反过来**，把它写死在代码里
    是这类工具最容易犯的错。默认值在 swing.py 里各自标了口径。
    """
    view = swing_study(
        company_id, window=window, trigger_percent=trigger_percent,
        base_shares=base_shares, tactical_percent=tactical_percent,
        costs={"commission_rate": commission_rate, "commission_min": commission_min,
               "stamp_tax_rate": stamp_tax_rate, "transfer_fee_rate": transfer_fee_rate,
               "slippage_rate": slippage_rate})
    if view is None:
        raise not_found("company")
    return view


@app.get("/api/v1/decision-loop")
def get_decision_loop() -> dict:
    """闭环首页：按状态分组，不按涨跌幅。

    顺带把「计划内 / 计划外交易」算出来——那是这一整套里最该盯的数字，
    而且它完全在使用者自己手里。
    """
    return decision_loop_board()


@app.post("/api/v1/decision-loop/evaluate")
def post_evaluate_triggers() -> dict:
    """按账本校正状态，再扫一遍价格触发。

    **两件事都是「按事实校正」，所以是同一个按钮。** 分成两个的话，
    其中一个永远不会被点 —— 而没被点的那个恰恰是让状态机跟账本不脱节的那个。

    **推到的是触发检查，不是持仓。** 价格到了只说明该重新看一眼。
    一天最多推一次，判定用日线收盘价——盘中价会在价格带边缘反复穿越。
    """
    return evaluate_decision_triggers()


# ── 助理（assistant.py）──────────────────────────────────────────────────
#
# 这几条是给助理读的（nanobot 那边的 MCP 工具，见 apps/assistant/）。
# **判断都在 assistant.py 里**，这里只转一手——换一个 agent 框架，这几条不用动。

@app.get("/api/v1/assistant/my-stocks")
def get_assistant_my_stocks() -> list[dict]:
    """「你的票」：观察池 / 候选池、有决策卡的、写过逻辑的、持有的，四个清单的并集。"""
    return assistant.my_stocks()


@app.post("/api/v1/assistant/command")
async def post_assistant_command(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > 800000:
        raise HTTPException(status_code=413, detail="内容太长，请拆成几段保存。")
    try:
        envelope = assistant_agent.verify_request(raw, request.headers.get("X-Stock-Signature", ""))
    except (assistant_agent.AgentError, ValidationError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        return await asyncio.to_thread(assistant_agent.dispatch, envelope)
    except assistant_agent.AgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/assistant/resolve")
def get_assistant_resolve(q: str = "") -> list[dict]:
    """「宁德」→ 宁德时代。先在你的票里找，找不到再去全部档案里找。"""
    return assistant.resolve(q[:40])


@app.get("/api/v1/assistant/check/{company_id}")
def get_assistant_check(company_id: int, price: float | None = None) -> dict:
    """交易前核验：合不合你自己写的计划。**只读，不建卡、不推状态。**"""
    if price is not None and not (0 < price < 1e6):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="价格要大于 0。")
    view = assistant.pre_trade_check(company_id, price)
    if view is None:
        raise not_found("company")
    return view


@app.post("/api/v1/assistant/watch")
def post_assistant_watch(send: bool = False, fetch: bool = True) -> dict:
    """手动盯一轮。**默认只看不发**：在页面上点着试的时候，不该真往飞书推。

    真要发（send=true）只有站主能点：提醒是送进站主自己的飞书对话的，
    别人触发一次，他的计划价就进了站主的聊天记录。
    """
    if send:
        access.require_owner("让助理往飞书发提醒")
    return assistant.watch_once(send=send, fetch=fetch)


@app.get("/api/v1/assistant/status")
def get_assistant_status() -> dict:
    """助理最近在干什么：最近几轮盯盘、最近几条提醒送没送到。"""
    return assistant.status()


@app.get("/api/v1/assistant/research/{company_id}")
def get_assistant_research(
    company_id: int, section: assistant_research.ResearchSection = "theses",
    annual_only: bool = True, keyword: str = Query(default="", max_length=100),
    event_date: str = Query(default="", max_length=10), report_id: int | None = None,
    offset: int = Query(default=0, ge=0, le=2000000),
) -> dict:
    view = assistant_research.read(company_id, section, annual_only=annual_only,
        keyword=keyword, event_date=event_date, report_id=report_id, offset=offset)
    if view is None:
        raise not_found("company or report")
    return view


@app.get("/api/v1/companies/{company_id}/decision-card")
def get_decision_card(company_id: int) -> dict:
    """一家公司的决策卡：状态、守卫、能走去哪、为什么走不了、价格带、推进史。"""
    view = decision_card(company_id)
    if view is None:
        raise not_found("company")
    return view


@app.post("/api/v1/companies/{company_id}/decision-card")
def post_decision_card(company_id: int, payload: dict) -> dict:
    """存关注理由、四段价格带、仓位计划。**校验不通过一个字都不存。**"""
    try:
        view = save_decision_card(company_id, payload)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc
    if view is None:
        raise not_found("company")
    return view


@app.post("/api/v1/companies/{company_id}/decision-card/move")
def post_decision_move(company_id: int, payload: dict) -> dict:
    """推进一格。守卫不过就 422，**没有强制推进**。

    留一个强制开关等于这套守卫不存在：用过一次之后，每一次卡住都会用它。
    """
    target = str(payload.get("state") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not target:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="要推到哪一格？")
    if not reason:
        # **理由是必填的。** 一次说不出所以然的状态推进，复盘时读起来跟没推进一样。
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="写一句为什么现在推进——复盘时这一句就是全部的线索。")
    try:
        view = move_decision_state(company_id, target, reason)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc
    if view is None:
        raise not_found("company")
    return view


@app.post("/api/v1/companies/{company_id}/fills")
def post_fill(company_id: int, payload: FillInput) -> dict:
    """登记一次真实成交。

    **这是「计划内 / 计划外」现在唯一的数据来源**：持仓改成只记两个数之后，
    账本里不会再有 buy 流水，那个指标必须换源，否则永久归零且不报错。
    """
    try:
        card = record_fill(company_id, payload.price,
                           payload.filled_on.isoformat() if payload.filled_on else None,
                           payload.shares, payload.note)
    except LedgerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc)) from exc
    if not card:
        raise not_found("company")
    return card


@app.delete("/api/v1/fills/{fill_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_fill(fill_id: int) -> Response:
    """删掉一条成交登记。**填错价格是常事**，而错的成交价会让纪律指标一直错。"""
    if not delete_fill(fill_id):
        raise not_found("fill")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/v1/companies/{company_id}/decision-card/enroll")
def post_decision_enroll(company_id: int) -> dict:
    """把这家公司放进闭环（停在「待研究」）。

    不自动给所有公司建卡：一次性把两百多家塞进「待研究」，那一格就再也没人看了。
    """
    view = ensure_decision_card(company_id)
    if view is None:
        raise not_found("company")
    return decision_card(company_id)


@app.get("/api/v1/rally")
def get_rally_by_symbol(
    symbol: str = Query(min_length=6, max_length=9),
    window: int = Query(default=20, ge=3, le=250),
) -> dict:
    """按代码查任意一只 A 股的涨跌归因。**不要求它在你的研究池里。**

    使用者最需要这个功能的那一刻，问的恰恰是池子外的票
    （「那只很烂的股票凭什么连着涨停」）——他要是研究过它，也就不会看不懂了。

    在池子里且日线够长就走档案那条路（判据最全）；否则用全市场底座，
    **取不到的三样（成交量、公告、历史估值分位）会明写在返回值里**，
    对应的判据按"不通过"算而不是按"通过"算。
    """
    view = rally_lookup(symbol, window)
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"全市场底座里没有 {symbol} 这只票。六位数字的 A 股代码，"
                   f"底座每天同步一次；新股可能还没进来。")
    return view


@app.get("/api/v1/companies/{company_id}/rally")
def get_rally(company_id: int, window: int = Query(default=20, ge=3, le=250)) -> dict:
    """这段涨跌属于什么类型。**规则层，不调模型，不花积分。**"""
    view = rally_view(company_id, window)
    if view is None:
        raise not_found("company")
    return view


@app.post("/api/v1/companies/{company_id}/rally/narrate")
def post_rally_narrate(company_id: int, window: int = Query(default=20, ge=3, le=250)) -> dict:
    """让模型把规则层的结论讲成一段人话。**要花积分。**

    分类由规则层定死，模型改不了；它说出来的数字在事实表里找不到出处会被标出来。
    判成「无法解释」或「没什么事发生」时这一步直接跳过——
    那两种情况下能写出来的只能是编的。
    """
    view = rally_narration(company_id, window)
    if view is None:
        raise not_found("company")
    return view
