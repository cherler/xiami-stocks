import json
import math
import re
import sqlite3
import statistics
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from pydantic import ValidationError

from .access import GUEST_SCOPE, OWNER_SCOPE, current_scope
from .database import connection, integrity_errors, now_iso
from .jsonio import tidy_decimals


def _sw(alias: str = "") -> str:
    """当前数据域的过滤片段（以 AND 开头，值已内联校验）。

    系统域（调度器，scope=None）返回空串——它要替所有用户同步数据。
    值不走占位符是刻意的：这些 SQL 大量是既有字符串拼接，占位符要重排每一处参数表；
    而 scope 只有两种来源（哨兵常量 / 主站返回的 user_id），这里再白名单校验一次。
    """
    scope = current_scope()
    if scope is None:
        return ""
    if scope != OWNER_SCOPE and not scope.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"非法的数据域：{scope!r}")
    column = f"{alias}.user_id" if alias else "user_id"
    return f" AND {column} = '{scope}'"


def _swc(column: str = "company_id") -> str:
    """按所属公司过滤子表（收件箱等按 company_id 挂靠、自身不带 user_id 的表）。"""
    scope = current_scope()
    if scope is None:
        return ""
    return f" AND {column} IN (SELECT id FROM companies WHERE 1=1{_sw()})"


def _symbol_of(conn, company_id: int) -> str | None:
    """company_id → symbol。

    行情/财务/简况从 v32 起按 symbol 全局共享（见 database.py 那段注释），
    而调用链上层拿到的仍是 company_id —— 这个函数是两者之间的唯一转换点。
    查不到就返回 None，调用方据此当作「没有这只票」处理，而不是拿一个 None
    去当 symbol 查出一堆空结果。
    """
    row = conn.execute(f"SELECT symbol FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
    return row["symbol"] if row else None


def _stamp() -> str:
    """新建根记录时盖的域章。系统上下文里创建（bootstrap）归站主。"""
    return current_scope() or OWNER_SCOPE
from .classification import RELEVANCE_LEVELS, ai_available, classify_by_rules, classify_with_model, set_user_terms
from .company_profile import CompanyProfileError, company_profile_provider, fetch_company_profile
from . import evidence_polarity, llm
from .chain_and_reports import RELATIONS as CHAIN_RELATIONS
from .chain_and_reports import node_label as chain_node_label
from .providers.akshare_segments import FILLER as SEGMENT_FILLER, AkShareSegmentProvider
from .financial_data import FinancialDataError, fetch_financial_periods, financial_provider
from .drafting import draft_with_model
from .chain_and_reports import map_supply_chain, write_briefing, write_report
from .news import DEFAULT_FEEDS, RETIRED_FEED_URLS, fetch_feed, match_by_rules, match_with_model
from .researching import review_candidates
from .methods import CATEGORIES, METHODS, METHODS_BY_KEY, Method
from .operators import OPERATORS_BY_KEY, compute as operator_compute, dupont
from .operators import values as operator_values
from .strategies import FIELD_LABELS, PRESETS, PRESETS_BY_KEY, TREND_FIELDS, Rule, Strategy, check_rule, value_of
from .universe_data import UniverseDataError, fetch_index_members, fetch_market_fundamentals, fetch_market_sentiment, fetch_market_spot, fetch_market_trend, universe_provider, fetch_market_dividends
from .valuation_data import ValuationDataError, fetch_valuation_history, valuation_provider
from .providers import board_of, exchange_of, fetch_brief, fetch_reports, latest_annual_period, official_links, latest_report_period, normalize_cn_symbol
from .market_data import (
    STARTER_SYMBOLS,
    MarketDataError,
    MarketQuoteNotFoundError,
    MarketSymbolError,
    fetch_cn_daily_history,
    fetch_cn_quotes,
    fetch_market_fund_flow,
    quote_provider,
    quote_timestamp,
    resolve_cn_quote,
)
from .schemas import (
    PortfolioUpdate,
    ThesisDraft,
    ThesisMethod,
    ThesisMethodCategory,
    ThesisMethodLibrary,
    ThesisMethodSummary,
    CompanyFromQuoteInput,
    CompanyInput,
    CompanyUpdate,
    DashboardSummary,
    EvidenceCreate,
    EvidencePolarity,
    NewsFeedInput,
    InboxArchive,
    InboxTarget,
    PortfolioCreate,
    ResearchEventCreate,
    ResearchEventUpdate,
    ThesisCreate,
    ResearchTaskCreate,
    ResearchTaskItemUpdate,
    ResearchTaskUpdate,
    ScreenStrategySave,
    ThesisReviewCreate,
    WatchlistImport,
    WatchlistImportRow,
    ThesisUpdate,
    TradeCreate,
    TradeUpdate,
)


class LedgerError(ValueError):
    """账本层的用户输入错误，例如卖出股数超过持仓。"""


def exchange_for_symbol(symbol: str) -> str:
    """A-share exchange is a deterministic property of the six-digit code."""

    if symbol.startswith("6"):
        return "上海证券交易所"
    if symbol.startswith(("4", "8")):
        return "北京证券交易所"
    return "深圳证券交易所"


def _record_provider_sync(
    provider_id: str,
    display_name: str,
    category: str,
    status: str,
    refreshed_items: int = 0,
    error: str | None = None,
) -> None:
    timestamp = now_iso()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO provider_syncs (
                provider_id, display_name, category, last_status, last_attempt_at,
                last_success_at, last_error, refreshed_items
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id) DO UPDATE SET
                display_name = excluded.display_name,
                category = excluded.category,
                last_status = excluded.last_status,
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = excluded.last_success_at,
                last_error = excluded.last_error,
                refreshed_items = excluded.refreshed_items
            """,
            (
                provider_id,
                display_name,
                category,
                status,
                timestamp,
                timestamp if status == "已同步" else None,
                error,
                refreshed_items,
            ),
        )


def _fetch_market_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    try:
        quotes = fetch_cn_quotes(symbols)
    except MarketDataError as exc:
        _record_provider_sync(quote_provider.provider_id, quote_provider.display_name, quote_provider.category, "异常", error=str(exc))
        raise
    _record_provider_sync(quote_provider.provider_id, quote_provider.display_name, quote_provider.category, "已同步", refreshed_items=len(quotes))
    return quotes


def _resolve_market_quote(symbol: str) -> dict[str, Any]:
    try:
        quote = resolve_cn_quote(symbol)
    except MarketSymbolError:
        raise
    except MarketQuoteNotFoundError:
        _record_provider_sync(quote_provider.provider_id, quote_provider.display_name, quote_provider.category, "已同步", refreshed_items=0)
        raise
    except MarketDataError as exc:
        _record_provider_sync(quote_provider.provider_id, quote_provider.display_name, quote_provider.category, "异常", error=str(exc))
        raise
    _record_provider_sync(quote_provider.provider_id, quote_provider.display_name, quote_provider.category, "已同步", refreshed_items=1)
    return quote


def _fetch_daily_history(symbol: str) -> list[dict[str, Any]]:
    try:
        bars = fetch_cn_daily_history(symbol)
    except MarketDataError as exc:
        _record_provider_sync(
            quote_provider.history_provider_id,
            quote_provider.display_name,
            quote_provider.history_category,
            "异常",
            error=str(exc),
        )
        raise
    _record_provider_sync(
        quote_provider.history_provider_id,
        quote_provider.display_name,
        quote_provider.history_category,
        "已同步",
        refreshed_items=len(bars),
    )
    return bars


def _fetch_market_fund_flow() -> list[dict[str, Any]]:
    try:
        rows = fetch_market_fund_flow()
    except MarketDataError as exc:
        _record_provider_sync(
            quote_provider.fund_flow_provider_id,
            quote_provider.display_name,
            quote_provider.fund_flow_category,
            "异常",
            error=str(exc),
        )
        raise
    _record_provider_sync(
        quote_provider.fund_flow_provider_id,
        quote_provider.display_name,
        quote_provider.fund_flow_category,
        "已同步",
        refreshed_items=len(rows),
    )
    return rows


def _fetch_financial_reports(symbol: str) -> list[dict[str, Any]]:
    try:
        periods = fetch_financial_periods(symbol)
    except FinancialDataError as exc:
        _record_provider_sync(
            financial_provider.provider_id,
            financial_provider.display_name,
            financial_provider.category,
            "异常",
            error=str(exc),
        )
        raise
    _record_provider_sync(
        financial_provider.provider_id,
        financial_provider.display_name,
        financial_provider.category,
        "已同步",
        refreshed_items=len(periods),
    )
    return periods


# --- 研究记录的版本留痕 ---------------------------------------------------
# 逻辑与交易理由属于用户手写、不可再生的内容；修改一律追加版本，旧版本不覆盖。

THESIS_VERSIONED_FIELDS = ("claim", "counter_condition", "status", "next_review_trigger")
TRADE_VERSIONED_FIELDS = ("rationale", "expectation", "review_due", "thesis_id")

REVISION_FIELD_LABELS = {
    "claim": "主张",
    "counter_condition": "反证条件",
    "status": "状态",
    "next_review_trigger": "复核触发条件",
    "rationale": "交易理由",
    "expectation": "预期与证伪条件",
    "review_due": "复核日期",
    "thesis_id": "关联逻辑",
}


def _record_revision(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    snapshot: dict[str, Any],
    changed_fields: list[str],
    change_note: str = "",
) -> int:
    version = int(
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS next FROM record_revisions WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        ).fetchone()["next"]
    )
    conn.execute(
        """
        INSERT INTO record_revisions (entity_type, entity_id, version, snapshot, changed_fields, change_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            entity_id,
            version,
            json.dumps(snapshot, ensure_ascii=False, default=str),
            "、".join(REVISION_FIELD_LABELS.get(field, field) for field in changed_fields),
            change_note.strip(),
            now_iso(),
        ),
    )
    return version


def _revision_count(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM record_revisions WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        ).fetchone()["count"]
    )


def list_revisions(entity_type: str, entity_id: int) -> list[dict[str, Any]] | None:
    table = {"thesis": "theses", "trade": "trades"}.get(entity_type)
    if table is None:
        return None
    with connection() as conn:
        # 主体不属于当前用户就当作不存在。修订快照里有买入理由、逻辑原文，
        # 是全站最私密的一部分；这道门没关的话，知道 id 就能翻别人的历史。
        if not conn.execute(
                f"SELECT id FROM {table} WHERE id = ?{_swc('company_id')}", (entity_id,)).fetchone():
            return None
        rows = _rows(
            conn.execute(
                """
                SELECT id, entity_type, entity_id, version, snapshot, changed_fields, change_note, created_at
                FROM record_revisions WHERE entity_type = ? AND entity_id = ?
                ORDER BY version DESC
                """,
                (entity_type, entity_id),
            ).fetchall()
        )
    for row in rows:
        row["snapshot"] = json.loads(row["snapshot"])
    return rows


def _as_bool(row: dict[str, Any], key: str) -> dict[str, Any]:
    row[key] = bool(row[key])
    return row


def _one_or_none(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def list_companies(query: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT c.*, ms.price AS latest_price, ms.change_percent, ms.pe, ms.pb, ms.high_52w, ms.low_52w,
            ms.market_timestamp, ms.source AS market_source
        FROM companies c
        LEFT JOIN market_snapshots ms ON ms.id = (
            SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
            ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1
        )
    """
    params: list[str] = []
    sql += f" WHERE 1=1{_sw('c')}"
    if query:
        # **三个字段都要带 c. 前缀。**
        #
        # `symbol` 在 companies 和 join 进来的 market_snapshots 上都有，不带前缀
        # PostgreSQL 直接报 AmbiguousColumn，而 SQLite 会自己挑一个照跑不误——
        # 于是这条在 SQLite 上写完、测完、发出去，换到 PG 之后一搜就 500。
        # name / industry 眼下不冲突，但一起带上：加列的人不该被迫记住这条。
        sql += " AND (c.symbol LIKE ? OR c.name LIKE ? OR c.industry LIKE ?)"
        needle = f"%{query.strip()}%"
        params.extend([needle, needle, needle])
    sql += " ORDER BY is_watched DESC, watch_group, name"
    with connection() as conn:
        return [_as_bool(item, "is_watched") for item in _rows(conn.execute(sql, params).fetchall())]


def lookup_universe(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """在**全市场**里按名称或代码找公司，并标出哪几家你已经建过档。

    ## 为什么不能只搜档案

    `list_companies` 只搜已经建档的公司。可"我想看看哪家"这件事**永远发生在建档之前**：
    搜「宁德时代」搜不到，不是因为没这家公司，是因为你还没建它的档。
    而建档那一栏又只认六位代码——于是想研究一家公司，得先自己去别处查它的代码。
    **那是把数据库主键当成人的入口。**

    全市场底座（market_universe，五千多行）本来就在库里，一条 SQL 就查到，
    不调模型、不联网、**不花积分**。

    ## 排序按"你多半在找哪一个"

    代码精确 > 名称精确 > 名称开头 > 名称包含 > 代码包含 > 行业包含。
    同一档里按总市值从大到小——「中国*」「*科技」这类近名满地都是，
    靠市值和行业区分比按代码排有用得多。

    company_id 不为空表示这家已经在你的档案里；页面据此显示「打开档案」
    而不是再让你建一遍。
    """
    needle = query.strip()
    if not needle:
        return []
    like = f"%{needle}%"
    prefix = f"{needle}%"
    # 子查询里的 companies 必须带数据域过滤：**在不在档案里是每个人自己的事**，
    # 少了这个条件，别人建过的公司会显示成你建过的。
    sql = """
        SELECT u.symbol, u.name, u.industry, u.board, u.exchange,
            u.price, u.change_percent, u.total_market_cap,
            (SELECT c.id FROM companies c WHERE c.symbol = u.symbol{scope} ORDER BY c.id LIMIT 1) AS company_id
        FROM market_universe u
        WHERE u.symbol LIKE ? OR u.name LIKE ? OR u.industry LIKE ?
        ORDER BY
            CASE
                WHEN u.symbol = ? THEN 0
                WHEN u.name = ? THEN 1
                WHEN u.name LIKE ? THEN 2
                WHEN u.name LIKE ? THEN 3
                WHEN u.symbol LIKE ? THEN 4
                ELSE 5
            END,
            COALESCE(u.total_market_cap, 0) DESC,
            u.symbol
        LIMIT ?
    """.format(scope=_sw("c"))
    params: list[Any] = [like, like, like, needle, needle, prefix, like, prefix, max(1, min(int(limit), 30))]
    with connection() as conn:
        rows = _rows(conn.execute(sql, params).fetchall())
    for row in rows:
        row["in_archive"] = row["company_id"] is not None
    return rows


def get_company(company_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        company = _one_or_none(conn.execute(
            """
            SELECT c.*, ms.price AS latest_price, ms.change_percent, ms.pe, ms.pb, ms.high_52w, ms.low_52w,
                ms.market_timestamp, ms.source AS market_source
            FROM companies c
            LEFT JOIN market_snapshots ms ON ms.id = (
                SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
                ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1
            )
            WHERE c.id = ?{scope}
            """.format(scope=_sw("c")),
            (company_id,),
        ).fetchone())
        if not company:
            return None
        _as_bool(company, "is_watched")
        theses = _rows(
            conn.execute(
                """
                SELECT t.*, 
                    SUM(CASE WHEN e.polarity = 'support' THEN 1 ELSE 0 END) AS evidence_count,
                    SUM(CASE WHEN e.polarity = 'counter' THEN 1 ELSE 0 END) AS counter_evidence_count,
                    (SELECT COUNT(*) FROM record_revisions r WHERE r.entity_type = 'thesis' AND r.entity_id = t.id) AS revision_count
                FROM theses t
                LEFT JOIN evidences e ON e.thesis_id = t.id
                WHERE t.company_id = ?
                GROUP BY t.id
                ORDER BY t.updated_at DESC
                """,
                (company_id,),
            ).fetchall()
        )
        for thesis in theses:
            thesis["evidence_count"] = thesis["evidence_count"] or 0
            thesis["counter_evidence_count"] = thesis["counter_evidence_count"] or 0
        company["theses"] = theses
        company["evidences"] = _rows(
            conn.execute(
                "SELECT * FROM evidences WHERE company_id = ? ORDER BY occurred_at DESC, id DESC", (company_id,)
            ).fetchall()
        )
        company["events"] = _rows(
            conn.execute(
                "SELECT * FROM research_events WHERE company_id = ? ORDER BY occurred_at DESC, id DESC", (company_id,)
            ).fetchall()
        )
        company["market_history"] = _market_history_summary(conn, company_id)
        company["financials"] = _financial_summary(conn, company_id)
        company["profile"] = _company_profile_summary(conn, company_id)
        company["valuation"] = _valuation_summary(conn, company_id)
        company["ledger"] = _company_ledger(conn, company_id)
        return company


def _percent_change(current: float, reference: float | None) -> float | None:
    if reference is None or reference == 0:
        return None
    return round((current / reference - 1) * 100, 2)


def _market_history_summary(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    bars = _rows(
        conn.execute(
            """
            SELECT trade_date, close, high, low, change_percent, source, refreshed_at
            FROM price_bars WHERE symbol = ?
            ORDER BY trade_date ASC
            """,
            (_symbol_of(conn, company_id),),
        ).fetchall()
    )
    if not bars:
        return None
    latest = bars[-1]
    latest_close = float(latest["close"])
    latest_date = date.fromisoformat(latest["trade_date"])

    def sessions_ago(sessions: int) -> float | None:
        index = len(bars) - sessions - 1
        return float(bars[index]["close"]) if index >= 0 else None

    year_start = date(latest_date.year, 1, 1)
    ytd_reference = next((float(bar["close"]) for bar in bars if date.fromisoformat(bar["trade_date"]) >= year_start), None)
    one_year_target = latest_date - timedelta(days=365)
    one_year_reference = next(
        (float(bar["close"]) for bar in reversed(bars) if date.fromisoformat(bar["trade_date"]) <= one_year_target),
        None,
    )
    # 覆盖约一年交易日，供档案页切换 3 月/6 月/近一年窗口并计算 MA20、MA60。
    recent_bars = bars[-260:]
    return {
        "source": latest["source"],
        "adjusted": "前复权日线",
        "refreshed_at": latest["refreshed_at"],
        "latest_trade_date": latest["trade_date"],
        "price_5d_change": _percent_change(latest_close, sessions_ago(5)),
        "price_20d_change": _percent_change(latest_close, sessions_ago(20)),
        "ytd_change": _percent_change(latest_close, ytd_reference),
        "one_year_change": _percent_change(latest_close, one_year_reference),
        "bars": [
            {
                "trade_date": bar["trade_date"],
                "close": bar["close"],
                "high": bar["high"],
                "low": bar["low"],
                "change_percent": bar["change_percent"],
            }
            for bar in recent_bars
        ],
    }


# --- 财务派生指标 ---------------------------------------------------------
# 派生值一律标明口径与所用报告期；来源没有的科目保持为空，不用 0 顶替。

PERIOD_DAYS = {"03-31": 90, "06-30": 181, "09-30": 273, "12-31": 365}


def _safe_ratio(numerator: float | None, denominator: float | None, digits: int = 2) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return round(numerator / denominator * 100, digits)


def _period_days(report_date: str) -> int | None:
    return PERIOD_DAYS.get(report_date[5:])


# 定期报告能支撑的算子；全市场底座字段更少，用的是另一组
PERIOD_OPERATORS = (
    "gross_margin", "net_margin", "roa", "roe_estimate", "cash_conversion", "free_cash_flow",
    "fcf_margin", "debt_ratio", "interest_debt_ratio", "equity_multiplier", "asset_turnover",
    "receivable_days", "inventory_days", "rnd_ratio",
)


def _attach_financial_metrics(periods: list[dict[str, Any]]) -> None:
    """按报告期计算毛利率、净利率、自由现金流、周转天数与 TTM。"""

    by_date = {period["report_date"]: period for period in periods}
    for period in periods:
        revenue = period.get("revenue")
        cost = period.get("operating_cost")
        net_profit = period.get("net_profit")
        ocf = period.get("operating_cash_flow")
        capex = period.get("capex")
        days = _period_days(period["report_date"])

        # 比率一律由算子表算，这里不再各写一份口径。
        # 数据源自己披露的口径优先（比如年报的加权 ROE、披露的资产负债率）：
        # 算子只补数据源没给的，不覆盖已有值，否则同一字段会在不同公司之间口径不一致。
        for key, value in operator_values(period, PERIOD_OPERATORS).items():
            if period.get(key) is None:
                period[key] = value

        # TTM：年报直接取本身；其余按"本期累计 + 上年年报 − 上年同期累计"。
        year = int(period["report_date"][:4])
        suffix = period["report_date"][4:]
        if suffix == "-12-31":
            period["revenue_ttm"] = revenue
            period["net_profit_ttm"] = net_profit
            period["ttm_basis"] = "年报本身"
        else:
            last_annual = by_date.get(f"{year - 1}-12-31")
            same_period_last_year = by_date.get(f"{year - 1}{suffix}")
            if last_annual and same_period_last_year:
                def ttm(field: str) -> float | None:
                    current = period.get(field)
                    annual = last_annual.get(field)
                    prior = same_period_last_year.get(field)
                    if current is None or annual is None or prior is None:
                        return None
                    return round(current + annual - prior, 2)

                period["revenue_ttm"] = ttm("revenue")
                period["net_profit_ttm"] = ttm("net_profit")
                period["ttm_basis"] = f"本期累计 + {year - 1} 年报 − {year - 1}{suffix} 累计"
            else:
                period["revenue_ttm"] = None
                period["net_profit_ttm"] = None
                period["ttm_basis"] = "缺少上年年报或上年同期，无法计算 TTM"


def _financial_metric_cards(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not periods:
        return []
    latest = periods[-1]
    annuals = [item for item in periods if item["report_date"].endswith("-12-31")]
    # 最新期是年报时与上一个年报比；是季报或中报时与最近的年报比。
    if latest["report_date"].endswith("-12-31"):
        previous_annual = annuals[-2] if len(annuals) >= 2 else None
    else:
        previous_annual = annuals[-1] if annuals else None
    period_label = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}.get(latest["report_date"][5:], "报告期")

    def card(key: str, label: str, value: float | None, unit: str, basis: str) -> dict[str, Any]:
        previous = previous_annual.get(key) if previous_annual else None
        return {
            "key": key,
            "label": label,
            "value": value,
            "unit": unit,
            "basis": basis,
            "previous_annual": previous,
            "previous_annual_date": previous_annual["report_date"] if previous_annual and previous is not None else None,
            "unavailable_reason": None if value is not None else "来源未提供所需科目",
        }

    # 卡片列表直接由算子表生成：标签、口径、缺失原因都跟着算子走，不在这里另写一份
    shown = (
        "gross_margin", "net_margin", "cash_conversion", "free_cash_flow", "fcf_margin",
        "debt_ratio", "interest_debt_ratio", "roa", "asset_turnover", "equity_multiplier",
        "receivable_days", "inventory_days", "rnd_ratio",
    )
    cards = []
    for key in shown:
        computed = operator_compute(key, latest)
        cards.append(card(
            key,
            computed["label"],
            latest.get(key) if latest.get(key) is not None else computed["value"],
            computed["unit"].strip() or "",
            f"{latest['report_date']} {period_label}：{computed['formula']}"
            + (f"（{computed['caveat']}）" if computed["caveat"] else ""),
        ))
    return cards


def _financial_warnings(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只描述数据本身的异常或值得注意之处，不给出任何操作建议。"""

    warnings: list[dict[str, Any]] = []
    if not periods:
        return warnings
    latest = periods[-1]
    annuals = [item for item in periods if item["report_date"].endswith("-12-31")]

    if latest.get("net_profit") is not None and latest.get("operating_cash_flow") is not None:
        if latest["net_profit"] > 0 and latest["operating_cash_flow"] < 0:
            warnings.append({
                "level": "注意",
                "title": "净利润为正但经营现金流为负",
                "detail": f"{latest['report_date']}：归母净利润 {latest['net_profit'] / 1e8:.2f} 亿，经营现金流 {latest['operating_cash_flow'] / 1e8:.2f} 亿。",
            })
    if latest.get("cash_conversion") is not None and latest["cash_conversion"] < 50:
        warnings.append({
            "level": "注意",
            "title": "经营现金流不足净利润的一半",
            "detail": f"{latest['report_date']}：现金含量 {latest['cash_conversion']:.1f}%（口径：经营现金流 / 归母净利润）。",
        })
    if len(annuals) >= 2:
        current, previous = annuals[-1], annuals[-2]
        if all(item.get("receivables") is not None and item.get("revenue") not in {None, 0} for item in (current, previous)):
            receivable_growth = current["receivables"] / previous["receivables"] - 1 if previous["receivables"] else None
            revenue_growth = current["revenue"] / previous["revenue"] - 1 if previous["revenue"] else None
            if receivable_growth is not None and revenue_growth is not None and receivable_growth > revenue_growth + 0.3:
                warnings.append({
                    "level": "注意",
                    "title": "应收增速明显快于营收",
                    "detail": f"{previous['report_date']} → {current['report_date']}：应收 {receivable_growth * 100:+.1f}%，营收 {revenue_growth * 100:+.1f}%。",
                })
        if all(item.get("gross_margin") is not None for item in (current, previous)):
            change = current["gross_margin"] - previous["gross_margin"]
            if abs(change) >= 5:
                warnings.append({
                    "level": "注意",
                    "title": "毛利率同比变动超过 5 个百分点",
                    "detail": f"{previous['report_date']} {previous['gross_margin']:.1f}% → {current['report_date']} {current['gross_margin']:.1f}%。",
                })
    missing = [
        label
        for label, key in (("营业成本", "operating_cost"), ("资本开支", "capex"), ("应收", "receivables"), ("存货", "inventory"), ("有息负债", "interest_bearing_debt"))
        if latest.get(key) is None
    ]
    if missing:
        warnings.append({
            "level": "缺口",
            "title": "最新报告期缺少部分科目",
            "detail": f"来源未提供：{('、').join(missing)}；相关指标显示为空而不是 0。",
        })
    return warnings


def _financial_summary(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    symbol = _symbol_of(conn, company_id)
    rows = _rows(
        conn.execute(
            """
            SELECT report_date, revenue, net_profit, operating_cash_flow, operating_cost,
                rnd_expense, capex, receivables, inventory, interest_bearing_debt, total_assets,
                total_liabilities, equity, debt_ratio, roe_estimate, currency, audit_status,
                announcement_date, source, refreshed_at
            FROM financial_periods
            WHERE symbol = ?
            ORDER BY report_date DESC
            LIMIT 32
            """,
            (symbol,),
        ).fetchall()
    )
    if not rows:
        return None
    latest = rows[0]
    latest_annual_roe = next((row for row in rows if row["roe_estimate"] is not None), None)
    universe_roe = _one_or_none(conn.execute(
        """SELECT annual_roe, annual_report_date, fundamental_source
           FROM market_universe WHERE symbol = ?""",
        (symbol,),
    ).fetchone()) or {}
    reference_value = (
        latest_annual_roe["roe_estimate"] if latest_annual_roe
        else universe_roe.get("annual_roe")
    )
    reference_date = (
        latest_annual_roe["report_date"] if latest_annual_roe
        else universe_roe.get("annual_report_date")
    )
    if reference_date:
        raw_date = str(reference_date)[:10]
        if len(raw_date) == 8 and raw_date.isdigit():
            reference_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    ordered = list(reversed(rows))
    _attach_financial_metrics(ordered)
    return {
        "source": latest["source"],
        "refreshed_at": latest["refreshed_at"],
        "latest_report_date": latest["report_date"],
        "latest_audit_status": latest["audit_status"],
        "latest_annual_roe_report_date": latest_annual_roe["report_date"] if latest_annual_roe else None,
        "roe_reference_value": reference_value,
        "roe_reference_report_date": reference_date,
        "roe_reference_source": latest["source"] if latest_annual_roe else universe_roe.get("fundamental_source"),
        "periods": ordered,
        "metrics": _financial_metric_cards(ordered),
        # 杜邦分解回答"高 ROE 是靠赚得多、转得快，还是靠借得多"，三者可持续性完全不同
        "dupont": dupont(ordered[-1]) if ordered else None,
        "warnings": _financial_warnings(ordered),
    }


def create_company(payload: CompanyInput) -> dict[str, Any]:
    timestamp = now_iso()
    symbol = payload.symbol.strip().upper()
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO companies (
                user_id, symbol, name, exchange, industry, description, watch_group, is_watched,
                valuation_percentile, roe_trend, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                _stamp(),
                symbol,
                payload.name.strip(),
                exchange_for_symbol(symbol),
                payload.industry.strip(),
                payload.description.strip(),
                payload.watch_group.strip(),
                payload.valuation_percentile,
                payload.roe_trend.strip(),
                timestamp,
                timestamp,
            ),
        )
    return get_company(cursor.lastrowid)  # type: ignore[return-value]


def quote_preview(symbol: str) -> dict[str, Any]:
    quote = _resolve_market_quote(symbol)
    canonical_symbol = str(quote["code"])
    return {
        "symbol": canonical_symbol,
        "name": str(quote["name"]).strip(),
        "exchange": exchange_for_symbol(canonical_symbol),
        "price": quote.get("price"),
        "change_percent": quote.get("changePercent"),
        "pe": quote.get("pe"),
        "pb": quote.get("pb"),
        "market_timestamp": quote_timestamp(quote),
        "source": str(quote.get("source") or quote_provider.display_name),
    }


def create_company_from_quote(payload: CompanyFromQuoteInput) -> dict[str, Any]:
    """Create an archive only after the entered code has a real quote response."""

    quote = _resolve_market_quote(payload.symbol)
    symbol = str(quote["code"])
    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO companies (
                user_id, symbol, name, exchange, industry, description, watch_group, is_watched,
                valuation_percentile, roe_trend, created_at, updated_at
            ) VALUES (?, ?, ?, ?, '待补充', ?, ?, 1, NULL, '待真实财务数据接入', ?, ?)
            """,
            (
                _stamp(),
                symbol,
                str(quote["name"]).strip(),
                exchange_for_symbol(symbol),
                payload.description.strip(),
                payload.watch_group.strip(),
                timestamp,
                timestamp,
            ),
        )
        company_id = cursor.lastrowid
    store_market_quotes([quote])
    try:
        # A newly created archive should immediately have the same factual market baseline
        # as an existing one. Failure here must not discard the valid company archive.
        refresh_company_market_history(company_id)
    except MarketDataError:
        pass
    return get_company(company_id)  # type: ignore[arg-type, return-value]


# 建档之后要补齐的公开数据。**每一样都是免费的公开源，不调模型、不花积分。**
#
# 顺序按"没有它就看不了这一页"排：简况（顺带把公告写进大事提醒）→ 历史估值
# （时间轴那条曲线的唯一来源）→ 定期报告财务。
FRESH_ARCHIVE_STEPS: tuple[tuple[str, str], ...] = (
    ("公司简况与公告", "refresh_company_profile"),
    ("历史估值", "refresh_company_valuation"),
    ("定期报告财务", "refresh_company_financials"),
)


def fill_new_archive(company_id: int) -> dict[str, Any]:
    """把一份刚建好的档案补齐到"能看"的程度。

    ## 为什么建档时不做

    这三样都是外部网络请求，加起来十几秒，而且任何一个都可能超时。
    塞进 POST 里的结果是**建档变慢、还可能因为补数据失败而让建档看起来失败了**——
    档案本身是有效的，不该被这些拖累。所以建档立即返回，这里在后台补。

    ## 为什么必须补

    在这之前，新建的档案只有当天行情和前复权日线。于是：

      · 「行情与估值」的时间轴一条线都没有（它读 valuation_points，
        而那张表只有点过「同步历史估值」才有数据）
      · 「大事提醒」是空的，于是「从公告里找承诺」无公告可读
      · 财务、行业对照全是待补充

    换句话说，**新建的档案打开来几乎每一页都是空的**，而每一页都得自己去点一次同步。
    使用者的原话："按理说，新建公司，这几个数据都应该默认同步才对"。

    一样失败不影响另一样：逐个 try，把失败的名字报出来，别让一次超时
    把整份档案的补齐都拖掉。
    """
    done: list[str] = []
    failed: list[str] = []
    for label, func_name in FRESH_ARCHIVE_STEPS:
        try:
            globals()[func_name](company_id)
            done.append(label)
        except Exception as exc:                      # noqa: BLE001 —— 补数据失败不该炸掉任务
            failed.append(f"{label}（{type(exc).__name__}）")
    note = f"已补齐：{'、'.join(done)}" if done else "一样都没补上"
    if failed:
        note += f"　没补上：{'、'.join(failed)}，可以到对应页签手动同步。"
    return {"company_id": company_id, "done": done, "failed": failed, "note": note}


def update_company(company_id: int, payload: CompanyUpdate) -> dict[str, Any] | None:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return get_company(company_id)
    columns = list(updates)
    assignments = ", ".join(f"{column} = ?" for column in columns)
    values = [int(value) if isinstance(value, bool) else value for value in updates.values()]
    values.extend([now_iso(), company_id])
    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE companies SET {assignments}, updated_at = ? WHERE id = ?{_sw()}", values
        )
        if not cursor.rowcount:
            return None
    return get_company(company_id)


def _recheck_counters_for(company_id: int) -> None:
    """把这家公司的公告"比对过"的戳清掉，让新写下的认错条件能撞到已有公告。

    **不清的话，新条件只对以后的公告生效** —— 而你写下它的那一刻，
    脑子里想的恰恰是"库里那些我还没细看的公告有没有已经踩到它"。
    清戳只是让它们重新排队，命中与否仍然由模型判。
    """
    with connection() as conn:
        conn.execute(
            f"""UPDATE company_calendar_events SET counter_checked_at = NULL
                WHERE company_id = ? AND counter_checked_at IS NOT NULL{_swc()}""",
            (company_id,))


def create_thesis(company_id: int, payload: ThesisCreate) -> dict[str, Any] | None:
    company = get_company(company_id)
    if not company:
        return None
    timestamp = now_iso()
    # 写下这条判断时的股价。**当场记，因为事后推不出来**——
    # 归因时最要紧的一句是「我当时是在什么价位这么想的」，
    # 没有它，"后来涨了/跌了"这句话没有起点。
    with connection() as conn:
        quote = conn.execute("SELECT price FROM market_universe WHERE symbol = ?",
                             (company["symbol"],)).fetchone()
    price_at_write = dict(quote).get("price") if quote else None
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO theses (company_id, claim, counter_condition, status, next_review_trigger,
                                method_key, method_name, price_at_write, price_source,
                                created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                payload.claim.strip(),
                payload.counter_condition.strip(),
                payload.status.value,
                payload.next_review_trigger.strip(),
                payload.method_key,
                (METHODS_BY_KEY[payload.method_key].name if payload.method_key in METHODS_BY_KEY else None),
                price_at_write,
                "当场记录" if price_at_write is not None else "",
                timestamp,
                timestamp,
            ),
        )
        thesis_id = int(cursor.lastrowid)
        _record_revision(
            conn,
            "thesis",
            thesis_id,
            {field: getattr(payload, field).value if field == "status" else getattr(payload, field).strip() for field in THESIS_VERSIONED_FIELDS},
            list(THESIS_VERSIONED_FIELDS),
            change_note="建立逻辑",
        )
        row = conn.execute(
            "SELECT *, 0 AS evidence_count, 0 AS counter_evidence_count, 1 AS revision_count FROM theses WHERE id = ?", (thesis_id,)
        ).fetchone()
    # 新写下一条认错条件，就让这家公司的公告重新排一次队 —— 见 _recheck_counters_for。
    if payload.counter_condition.strip():
        _recheck_counters_for(company_id)
    return _one_or_none(row)


def delete_thesis(thesis_id: int) -> bool:
    """删掉一条投资逻辑。

    **之前只能加不能减。** 模型起草之后必然会产生一些不满意的版本，没有删除
    就只能靠状态标成「已破坏」压在列表里——而那个状态本来的意思是「事实推翻了它」，
    不是「我不要这条」。两件事混在一起，列表很快就没法看了。

    证据和事件不跟着删：它们是已经发生的事实，不因为某条判断被丢掉而失效。
    外键是 SET NULL，删完它们会挂回公司名下。
    """
    with connection() as conn:
        return bool(conn.execute(
            f"DELETE FROM theses WHERE id = ?{_swc('company_id')}", (thesis_id,)).rowcount)


def update_thesis(thesis_id: int, payload: ThesisUpdate) -> dict[str, Any] | None:
    updates = payload.model_dump(exclude_unset=True)
    change_note = str(updates.pop("change_note", "") or "")
    if "status" in updates and updates["status"] is not None:
        updates["status"] = updates["status"].value
    updates = {key: value for key, value in updates.items() if value is not None and key in THESIS_VERSIONED_FIELDS}
    with connection() as conn:
        # 带上数据域：不带的话，任何登录用户拿着 id 就能改掉别人的投资逻辑。
        # 实测过——PATCH /theses/{id} 返回 200，站主再读出来已经是别人写的内容。
        current = _one_or_none(conn.execute(
            f"SELECT * FROM theses WHERE id = ?{_swc('company_id')}", (thesis_id,)).fetchone())
        if not current:
            return None
        if isinstance(updates.get("claim"), str):
            updates["claim"] = updates["claim"].strip()
        if isinstance(updates.get("counter_condition"), str):
            updates["counter_condition"] = updates["counter_condition"].strip()
        if isinstance(updates.get("next_review_trigger"), str):
            updates["next_review_trigger"] = updates["next_review_trigger"].strip()
        changed = [field for field, value in updates.items() if current.get(field) != value]
        if changed:
            assignments = ", ".join(f"{field} = ?" for field in changed)
            conn.execute(
                f"UPDATE theses SET {assignments}, updated_at = ? WHERE id = ?",
                [*(updates[field] for field in changed), now_iso(), thesis_id],
            )
            snapshot = {field: updates.get(field, current.get(field)) for field in THESIS_VERSIONED_FIELDS}
            _record_revision(conn, "thesis", thesis_id, snapshot, changed, change_note)
        row = conn.execute(
            """
            SELECT t.*, 
                SUM(CASE WHEN e.polarity = 'support' THEN 1 ELSE 0 END) AS evidence_count,
                SUM(CASE WHEN e.polarity = 'counter' THEN 1 ELSE 0 END) AS counter_evidence_count
            FROM theses t LEFT JOIN evidences e ON e.thesis_id = t.id
            WHERE t.id = ? GROUP BY t.id
            """,
            (thesis_id,),
        ).fetchone()
        result = _one_or_none(row)
        if result:
            result["evidence_count"] = result["evidence_count"] or 0
            result["counter_evidence_count"] = result["counter_evidence_count"] or 0
            result["revision_count"] = _revision_count(conn, "thesis", thesis_id)
    # 改了认错条件也要重新排队：改一个门槛（27% → 25%）跟新写一条是同一件事。
    if result and "counter_condition" in updates:
        _recheck_counters_for(int(result["company_id"]))
    return result


def _thesis_belongs_to_company(conn: sqlite3.Connection, company_id: int, thesis_id: int | None) -> bool:
    if thesis_id is None:
        return True
    return bool(conn.execute("SELECT 1 FROM theses WHERE id = ? AND company_id = ?", (thesis_id, company_id)).fetchone())


def create_evidence(company_id: int, payload: EvidenceCreate) -> dict[str, Any] | None:
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        if not _thesis_belongs_to_company(conn, company_id, payload.thesis_id):
            raise ValueError("selected thesis does not belong to company")
        cursor = conn.execute(
            """
            INSERT INTO evidences (
                company_id, thesis_id, source_name, source_url, excerpt, polarity,
                occurred_at, verification, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                payload.thesis_id,
                payload.source_name.strip(),
                str(payload.source_url) if payload.source_url else None,
                payload.excerpt.strip(),
                payload.polarity.value,
                payload.occurred_at.replace(microsecond=0).isoformat(),
                payload.verification.strip(),
                timestamp,
            ),
        )
        return _one_or_none(conn.execute("SELECT * FROM evidences WHERE id = ?", (cursor.lastrowid,)).fetchone())


def create_event(company_id: int, payload: ResearchEventCreate) -> dict[str, Any] | None:
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        if not _thesis_belongs_to_company(conn, company_id, payload.thesis_id):
            raise ValueError("selected thesis does not belong to company")
        cursor = conn.execute(
            """
            INSERT INTO research_events (
                company_id, thesis_id, category, title, occurred_at, importance, verification, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                payload.thesis_id,
                payload.category.strip(),
                payload.title.strip(),
                payload.occurred_at.replace(microsecond=0).isoformat(),
                payload.importance.value,
                payload.verification.strip(),
                timestamp,
            ),
        )
        return _one_or_none(conn.execute("SELECT * FROM research_events WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_event(event_id: int, payload: ResearchEventUpdate) -> dict[str, Any] | None:
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        assignments = ", ".join(f"{column} = ?" for column in updates)
        with connection() as conn:
            cursor = conn.execute(
                f"UPDATE research_events SET {assignments} WHERE id = ?{_swc('company_id')}",
                [*updates.values(), event_id],
            )
            if not cursor.rowcount:
                return None
    with connection() as conn:
        return _one_or_none(conn.execute(
            f"SELECT * FROM research_events WHERE id = ?{_swc('company_id')}", (event_id,)).fetchone())


def bootstrap_real_examples() -> int:
    """Create real, SDK-backed starter companies only for an empty personal archive."""

    with connection() as conn:
        if conn.execute("SELECT COUNT(*) AS count FROM companies").fetchone()["count"]:
            return 0
    quotes = _fetch_market_quotes(STARTER_SYMBOLS)
    if not quotes:
        return 0
    timestamp = now_iso()
    with connection() as conn:
        for quote in quotes:
            symbol = str(quote["code"])
            conn.execute(
                """
                INSERT OR IGNORE INTO companies (
                    user_id, symbol, name, exchange, industry, description, watch_group, is_watched,
                    valuation_percentile, roe_trend, created_at, updated_at
                ) VALUES (?, ?, ?, ?, '待补充', '', '观察池', 1, NULL, '待真实财务数据接入', ?, ?)
                """,
                (_stamp(), symbol, str(quote.get("name") or symbol), exchange_for_symbol(symbol), timestamp, timestamp),
            )
    return store_market_quotes(quotes)


def store_market_quotes(quotes: list[dict[str, Any]]) -> int:
    """Persist an immutable quote snapshot and refresh only SDK-owned company names."""

    timestamp = now_iso()
    refreshed = 0
    with connection() as conn:
        company_ids = {
            row["symbol"]: row["id"]
            for row in conn.execute("SELECT id, symbol FROM companies").fetchall()
        }
        for quote in quotes:
            symbol = str(quote.get("code") or "")
            company_id = company_ids.get(symbol)
            if not company_id:
                continue
            name = quote.get("name")
            if isinstance(name, str) and name.strip():
                conn.execute("UPDATE companies SET name = ?, updated_at = ? WHERE id = ?", (name.strip(), timestamp, company_id))
            conn.execute(
                """
                INSERT INTO market_snapshots (
                    symbol, price, prev_close, change_percent, pe, pb, high_52w, low_52w,
                    total_market_cap, market_timestamp, source, refreshed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _symbol_of(conn, company_id),
                    quote.get("price"),
                    quote.get("prevClose"),
                    quote.get("changePercent"),
                    quote.get("pe"),
                    quote.get("pb"),
                    quote.get("high52w"),
                    quote.get("low52w"),
                    quote.get("totalMarketCap"),
                    quote_timestamp(quote),
                    str(quote.get("source") or "stocksdk"),
                    timestamp,
                ),
            )
            # 顺带留一条当日估值快照：这是本地自建的、口径与实时行情一致的历史序列。
            snapshot_date = str(quote_timestamp(quote) or timestamp)[:10]
            for metric, key in (("pe_ttm", "pe"), ("pb", "pb")):
                value = quote.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    conn.execute(
                        """
                        INSERT INTO valuation_points (symbol, metric, point_date, value, source, refreshed_at)
                        VALUES (?, ?, ?, ?, 'StockSDK', ?)
                        ON CONFLICT(symbol, metric, point_date, source) DO UPDATE SET
                            value = excluded.value,
                            refreshed_at = excluded.refreshed_at
                        """,
                        (symbol, metric, snapshot_date, float(value), timestamp),
                    )
            refreshed += 1
    return refreshed


def store_daily_history(company_id: int, bars: list[dict[str, Any]]) -> int:
    """Persist adjusted daily bars. Source bars remain facts, not research conclusions.

    日线按 symbol 全局共享（v32），所以先把 company_id 换成 symbol。
    换不出来就直接不写：往共享表里塞一条 symbol 为空的行，会污染所有人的数据，
    而且查的时候看不出是哪来的。
    """

    timestamp = now_iso()
    source = "StockSDK（东方财富日线）"
    stored = 0
    with connection() as conn:
        symbol = _symbol_of(conn, company_id)
        if not symbol:
            return 0
        for bar in bars:
            trade_date = bar.get("date")
            close = bar.get("close")
            if not isinstance(trade_date, str) or not isinstance(close, (int, float)):
                continue
            conn.execute(
                """
                INSERT INTO price_bars (
                    symbol, trade_date, close, high, low, volume, amount,
                    change_percent, source, refreshed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date, source) DO UPDATE SET
                    close = excluded.close,
                    high = excluded.high,
                    low = excluded.low,
                    volume = excluded.volume,
                    amount = excluded.amount,
                    change_percent = excluded.change_percent,
                    refreshed_at = excluded.refreshed_at
                """,
                (
                    symbol,
                    trade_date,
                    close,
                    bar.get("high"),
                    bar.get("low"),
                    bar.get("volume"),
                    bar.get("amount"),
                    bar.get("changePercent"),
                    source,
                    timestamp,
                ),
            )
            stored += 1
    return stored


def refresh_company_market_history(company_id: int) -> int | None:
    with connection() as conn:
        row = conn.execute(f"SELECT symbol FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
    if not row:
        return None
    bars = _fetch_daily_history(row["symbol"])
    return store_daily_history(company_id, bars)


def store_financial_periods_by_symbol(symbol: str, periods: list[dict[str, Any]]) -> int:
    """按代码存财务序列——不需要这只股票在谁的档案里。

    financial_periods 从 v32 起就是按 symbol 的全局表（茅台的年报谁看都一样），
    只是入口一直要求先有 company_id。候选体检需要的正是"还没建档但想看财务"，
    所以把入口开出来；拉一次别人也能用，不会重复拉。
    """
    return _store_financial_periods(symbol, periods)


def store_financial_periods(company_id: int, periods: list[dict[str, Any]]) -> int:
    """Persist only normalized report-period facts and their audit/source metadata."""

    with connection() as conn:
        symbol = _symbol_of(conn, company_id)
    return _store_financial_periods(symbol, periods) if symbol else 0


def _store_financial_periods(symbol: str, periods: list[dict[str, Any]]) -> int:
    """Persist only normalized report-period facts and their audit/source metadata."""

    timestamp = now_iso()
    source = "AKShare（新浪财经定期报告）"
    stored = 0
    with connection() as conn:
        for period in periods:
            report_date = period.get("report_date")
            if not isinstance(report_date, str):
                continue
            conn.execute(
                """
                INSERT INTO financial_periods (
                    symbol, report_date, revenue, net_profit, operating_cash_flow,
                    operating_cost, rnd_expense, capex, receivables, inventory, interest_bearing_debt,
                    total_assets, total_liabilities, equity, debt_ratio, roe_estimate,
                    currency, audit_status, announcement_date, source, refreshed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, source) DO UPDATE SET
                    revenue = excluded.revenue,
                    net_profit = excluded.net_profit,
                    operating_cash_flow = excluded.operating_cash_flow,
                    operating_cost = excluded.operating_cost,
                    rnd_expense = excluded.rnd_expense,
                    capex = excluded.capex,
                    receivables = excluded.receivables,
                    inventory = excluded.inventory,
                    interest_bearing_debt = excluded.interest_bearing_debt,
                    total_assets = excluded.total_assets,
                    total_liabilities = excluded.total_liabilities,
                    equity = excluded.equity,
                    debt_ratio = excluded.debt_ratio,
                    roe_estimate = excluded.roe_estimate,
                    currency = excluded.currency,
                    audit_status = excluded.audit_status,
                    announcement_date = excluded.announcement_date,
                    refreshed_at = excluded.refreshed_at
                """,
                (
                    symbol,
                    report_date,
                    period.get("revenue"),
                    period.get("net_profit"),
                    period.get("operating_cash_flow"),
                    period.get("operating_cost"),
                    period.get("rnd_expense"),
                    period.get("capex"),
                    period.get("receivables"),
                    period.get("inventory"),
                    period.get("interest_bearing_debt"),
                    period.get("total_assets"),
                    period.get("total_liabilities"),
                    period.get("equity"),
                    period.get("debt_ratio"),
                    period.get("roe_estimate"),
                    str(period.get("currency") or "CNY"),
                    str(period.get("audit_status") or "待确认"),
                    period.get("announcement_date"),
                    source,
                    timestamp,
                ),
            )
            # 白名单科目：**同一次同步顺手落库，不多一次网络请求。**
            # 三张表本来就全下下来了，此前挑走十几个字段就把其余全扔了——
            # 而能分辨生意的那几个数（合同负债、净利息收入、销售回款）全在被扔的那部分。
            for item, value in (period.get("line_items") or {}).items():
                conn.execute(
                    """INSERT INTO financial_line_items (symbol, report_date, item, value, source, refreshed_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(symbol, report_date, item) DO UPDATE SET
                           value = excluded.value, refreshed_at = excluded.refreshed_at""",
                    (symbol, report_date, item, value, source, timestamp))
            stored += 1
    return stored


def refresh_company_financials(company_id: int) -> int | None:
    with connection() as conn:
        row = conn.execute(f"SELECT symbol FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
    if not row:
        return None
    periods = _fetch_financial_reports(row["symbol"])
    return store_financial_periods(company_id, periods)


# ---------------------------------------------------------------- 证据方向


def evidence_direction_plan(company_id: int) -> dict[str, Any] | None:
    """跑之前先看要判多少件、大概花多少积分。

    花钱的事要让人在点之前就知道大概多少，而不是点完看账单。
    """
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        theses = _rows(conn.execute(
            "SELECT id, claim, counter_condition FROM theses WHERE company_id = ? "
            "ORDER BY id DESC", (company_id,)).fetchall())
        rows = _rows(conn.execute(
            "SELECT id, company_id, excerpt, occurred_at FROM evidences WHERE company_id = ?",
            (company_id,)).fetchall())

    if not theses:
        return {"ready": False, "events": 0, "credits": 0, "documents": len(rows),
                "note": ("这家公司还没写过投资逻辑，方向判不了——"
                         "「支持」和「削弱」都是相对于某条判断说的。"
                         "同一件事对不同的判断方向可以相反：分红率提高，"
                         "对「靠稳定分红拿回报」是支持，对「靠产能扩张成长」反而是削弱。"
                         "先写下一条判断，再回来跑这个。")}

    events = evidence_polarity.cluster(rows)
    return {
        "ready": bool(events),
        "documents": len(rows),
        "events": len(events),
        "credits": evidence_polarity.estimate_credits(len(events)),
        "thesis": {"id": theses[0]["id"], "claim": theses[0]["claim"]},
        "note": (f"{len(rows)} 份公告归并成 {len(events)} 件事再判。"
                 "一次公司行为会拆成五到九份文件（草案、考核办法、核查意见、法律意见书…），"
                 "按份判等于同一件事判五遍，还会在时间轴上同一天堆出五个点。"
                 if events else "没有可判的实质公告——归档的都是程序性文件。"),
    }


def judge_evidence_direction(company_id: int) -> dict[str, Any] | None:
    """让模型判一遍这家公司的证据相对于投资逻辑的方向，并写回库里。"""
    plan = evidence_direction_plan(company_id)
    if plan is None:
        return None
    if not plan.get("ready"):
        return plan

    with connection() as conn:
        thesis = _one_or_none(conn.execute(
            "SELECT id, claim, counter_condition FROM theses WHERE id = ?",
            (plan["thesis"]["id"],)).fetchone())
        rows = _rows(conn.execute(
            "SELECT id, company_id, excerpt, occurred_at FROM evidences WHERE company_id = ?",
            (company_id,)).fetchall())

    judged = evidence_polarity.judge(evidence_polarity.cluster(rows), thesis)

    counts: dict[str, int] = {}
    now = now_iso()
    with connection() as conn:
        for item in judged:
            counts[item["polarity"]] = counts.get(item["polarity"], 0) + 1
            # **同一件事的所有文档一起改。** 只改代表那一份的话，时间轴上同一天
            # 会同时出现一个「支持」和四个「中性」，看着像五件事在互相矛盾。
            for evidence_id in item["evidence_ids"]:
                conn.execute(
                    "UPDATE evidences SET polarity = ?, polarity_reason = ?, "
                    "polarity_source = ?, thesis_id = ? WHERE id = ?",
                    (item["polarity"], item["reason"], f"模型 {llm.model_name()}",
                     item["thesis_id"], evidence_id))
        # **这里原来会写 last_reviewed_at = now，那是错的，已经删掉。**
        #
        # 给证据打极性标签是模型在贴标签，**不是你复核了这条判断**。
        # 后果很隐蔽：写进去之后复核队列认为"你已经看过了"，于是这条逻辑
        # 连同它新变成反证的那几份证据一起，从待复核里消失——
        # 而 thesis_reviews 表里一条记录都没有，决策归因那一页也是空的。
        #
        # 实测就是这么发生的：使用者的两条判断显示 last_reviewed_at = 08-06 22:31，
        # 而那个时刻是极性判定作业跑的时间，他本人从没复核过。
        # 首页一直在报「有反证」（对的），复核工作台一直是空的（错的），
        # 而我第一轮排查时把首页改安静了——**方向反了**，根因在这一行。
        #
        # 复核的唯一入口是 record_thesis_review()，它会同时写 thesis_reviews。

    return {
        "ready": True,
        "judged": len(judged),
        "counts": counts,
        "thesis": {"id": thesis["id"], "claim": thesis["claim"]},
        "note": (f"判了 {len(judged)} 件事：支持 {counts.get('support', 0)}、"
                 f"削弱 {counts.get('counter', 0)}、中性 {counts.get('neutral', 0)}。"
                 "方向是相对于上面那条判断说的，不是「对股价好不好」。"
                 "说不出依据的一律退回中性——一个没有理由的「削弱」会让人白紧张一场。"),
    }


def evidence_direction(company_id: int) -> dict[str, Any] | None:
    """时间轴要的数据：按时间排好的、带方向和理由的事件。"""
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        rows = _rows(conn.execute(
            "SELECT id, excerpt, polarity, polarity_reason, polarity_source, "
            "occurred_at, source_url, thesis_id FROM evidences "
            "WHERE company_id = ? ORDER BY occurred_at", (company_id,)).fetchall())
        theses = _rows(conn.execute(
            "SELECT id, claim, created_at FROM theses WHERE company_id = ? ORDER BY id",
            (company_id,)).fetchall())

    judged = [r for r in rows if r["polarity"] != "neutral" or r["polarity_reason"]]
    return {
        "events": [{
            "id": r["id"],
            "date": str(r["occurred_at"])[:10],
            "title": r["excerpt"],
            "polarity": r["polarity"],
            "reason": r["polarity_reason"],
            "source": r["polarity_source"],
            "url": r["source_url"] or "",
        } for r in judged],
        "theses": [{"id": t["id"], "claim": t["claim"],
                    "date": str(t["created_at"])[:10]} for t in theses],
        "total_documents": len(rows),
        "boundary": ("方向是相对于你写下的那条判断说的，不是「对股价好不好」。"
                     "只显示判过方向的；程序性文件（法律意见书、制度文件）不进这根轴。"),
    }


# ---------------------------------------------------------------- 主营构成

_segment_provider = AkShareSegmentProvider()


def refresh_business_segments(company_id: int) -> dict[str, Any] | None:
    """拉一次年报分部构成并入库。

    存的是全局表（按 symbol）：茅台按产品分了几块、每块毛利率多少，
    谁看都是同一份，没有「我的分部构成」。
    """
    with connection() as conn:
        row = conn.execute(f"SELECT symbol FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
    if not row:
        return None

    symbol = row["symbol"]
    try:
        rows = _segment_provider.fetch_segments(symbol, periods=4)
    except Exception as exc:                            # noqa: BLE001
        _record_provider_sync(_segment_provider.provider_id, _segment_provider.display_name,
                              _segment_provider.category, "异常", error=str(exc))
        raise
    _record_provider_sync(_segment_provider.provider_id, _segment_provider.display_name,
                          _segment_provider.category, "已同步", refreshed_items=len(rows))

    now = now_iso()
    with connection() as conn:
        for item in rows:
            conn.execute(
                """
                INSERT INTO business_segments (
                    symbol, report_date, dimension, segment,
                    revenue, revenue_share, cost, profit, profit_share, gross_margin, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, dimension, segment) DO UPDATE SET
                    revenue = excluded.revenue,
                    revenue_share = excluded.revenue_share,
                    cost = excluded.cost,
                    profit = excluded.profit,
                    profit_share = excluded.profit_share,
                    gross_margin = excluded.gross_margin,
                    updated_at = excluded.updated_at
                """,
                (item["symbol"], item["report_date"], item["dimension"], item["segment"],
                 item["revenue"], item["revenue_share"], item["cost"], item["profit"],
                 item["profit_share"], item["gross_margin"], now),
            )
    return business_segments(company_id)


def business_segments(company_id: int) -> dict[str, Any] | None:
    """这家公司靠什么赚钱：最近一期年报的分部收入与毛利率。

    **只取年报。** 半年报也有分部构成，但它跟年报不可比——累计口径加上季节性，
    把两者放进同一张构成图，看到的变化多半是日历造成的。
    """
    with connection() as conn:
        row = conn.execute(f"SELECT symbol, name FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
        if not row:
            return None
        symbol = row["symbol"]
        latest = conn.execute(
            "SELECT max(report_date) AS d FROM business_segments "
            "WHERE symbol = ? AND substr(report_date, 6) = '12-31'", (symbol,)).fetchone()
        report_date = latest["d"] if latest else None
        rows = _rows(conn.execute(
            "SELECT * FROM business_segments WHERE symbol = ? AND report_date = ? "
            "ORDER BY dimension, revenue_share DESC",
            (symbol, report_date)).fetchall()) if report_date else []

    by_dimension: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        by_dimension.setdefault(item["dimension"], []).append({
            "segment": item["segment"],
            "revenue": item["revenue"],
            "revenue_share": item["revenue_share"],
            "profit_share": item["profit_share"],
            "gross_margin": item["gross_margin"],
            # 数据源补的差额行不是业务分部，页面要能把它画成灰色
            "filler": item["segment"] == SEGMENT_FILLER,
        })

    return {
        "symbol": symbol,
        "company_name": row["name"],
        "report_date": report_date,
        "dimensions": [{"key": key, "items": items} for key, items in by_dimension.items()],
        "boundary": (
            "来自年报的分部附注，是披露过的事实，不是推断——这一点跟同一页上的"
            "经营关系线索不同，那些每条都标着「待证实」。"
            "占比按主营收入计算；毛利率是各分部自己的，不是公司整体的。"
            if rows else
            "还没有同步过主营构成。点上面的按钮拉一次，就知道这家公司的钱具体来自哪几块。"
        ),
    }


def refresh_all_market_quotes() -> tuple[int, int]:
    with connection() as conn:
        symbols = [row["symbol"] for row in conn.execute(f"SELECT symbol FROM companies WHERE is_watched = 1{_sw()}").fetchall()]
    quotes = _fetch_market_quotes(symbols)
    return store_market_quotes(quotes), len(symbols)


def list_provider_statuses() -> list[dict[str, Any]]:
    configured = {
        quote_provider.provider_id: {
            "provider_id": quote_provider.provider_id,
            "display_name": quote_provider.display_name,
            "category": quote_provider.category,
            "last_status": "未同步",
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
            "refreshed_items": 0,
        },
        quote_provider.history_provider_id: {
            "provider_id": quote_provider.history_provider_id,
            "display_name": quote_provider.display_name,
            "category": quote_provider.history_category,
            "last_status": "未同步",
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
            "refreshed_items": 0,
        },
        financial_provider.provider_id: {
            "provider_id": financial_provider.provider_id,
            "display_name": financial_provider.display_name,
            "category": financial_provider.category,
            "last_status": "未同步",
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
            "refreshed_items": 0,
        },
    }
    with connection() as conn:
        rows = _rows(conn.execute("SELECT * FROM provider_syncs ORDER BY category, display_name").fetchall())
    for row in rows:
        configured[row["provider_id"]] = row
    return list(configured.values())


def _data_alerts() -> list[dict[str, Any]]:
    try:
        from .scheduler import alerts

        return alerts()
    except Exception:
        return []


def _data_health_text(snapshot_count: int, company_count: int) -> str:
    """总览只给一句话；细节留在“数据状态”页。"""

    try:
        from .scheduler import health_summary

        summary = health_summary()
        counts = summary["counts"]
        from .scheduler import TROUBLE_HEALTH

        trouble = sum(counts.get(key, 0) for key in TROUBLE_HEALTH)
        if trouble:
            return f"{summary['jobs']} 个同步任务：{summary['summary']}"
        return f"{summary['jobs']} 个同步任务正常 · 行情 {snapshot_count}/{company_count} 已同步"
    except Exception:
        return f"StockSDK：{snapshot_count}/{company_count} 已同步"


def decision_attribution() -> dict[str, Any]:
    """闭环的第三环：我写下的判断，后来怎么样了。

    **只报机械可验证的事实**：写下时的价、现在的价、认错条件触发过没有、
    触发之后你动没动。不做模式识别——那需要几十条记录，而且判定本身就是一次判断，
    很容易变成一句听着很像回事、其实是编的话。
    """
    from . import attribution as at

    with connection() as conn:
        rows = _rows(conn.execute(
            f"""SELECT t.*, c.name AS company_name, c.symbol
                FROM theses t JOIN companies c ON c.id = t.company_id
                WHERE 1=1{_swc('t.company_id')}
                ORDER BY t.created_at DESC""").fetchall())
        prices = {row["symbol"]: row["price"] for row in
                  conn.execute("SELECT symbol, price FROM market_universe").fetchall()}
        hits = _rows(conn.execute(
            f"""SELECT h.thesis_id, h.created_at, h.acknowledged
                FROM counter_hits h WHERE 1=1{_sw('h')}
                ORDER BY h.created_at""").fetchall())
        # 「触发之后你做了什么」= 触发之后这条逻辑被改过（状态/措辞），
        # 或者有过一次复核。**光把命中标成已读不算动作**——
        # 那只是"我看见了"，而这里问的是"你做了什么"。
        # **version > 1**：第 1 版是写下这条逻辑时自动存的创建快照，
        # 而「创建」不是「动作」。不排掉的话，任何一条逻辑都会被算成
        # "触发之后你动过了"——这个功能就整个失效了，而且不报错。
        revisions = _rows(conn.execute(
            """SELECT entity_id AS thesis_id, created_at FROM record_revisions
               WHERE entity_type = 'thesis' AND version > 1""").fetchall())
        reviews = _rows(conn.execute(
            f"""SELECT rv.thesis_id, rv.created_at FROM thesis_reviews rv
                JOIN companies c ON c.id = rv.company_id
                WHERE 1=1{_swc('rv.company_id')}""").fetchall())

    by_thesis: dict[int, list[dict[str, Any]]] = {}
    for hit in hits:
        by_thesis.setdefault(hit["thesis_id"], []).append(hit)
    actions: dict[int, list[str]] = {}
    for item in revisions + reviews:
        actions.setdefault(item["thesis_id"], []).append(item["created_at"])

    out = []
    for row in rows:
        fired = by_thesis.get(row["id"], [])
        acted = False
        if fired:
            first = fired[0]["created_at"]
            # 触发之后才算数：触发之前改的那次跟这次命中没有关系。
            acted = any(when > first for when in actions.get(row["id"], []))
        out.append(at.outcome(row, prices.get(row["symbol"]), fired, acted))

    summary = at.summarize(out)
    return {"rows": out, **summary}


def quick_thesis_context(symbol_or_id: str) -> dict[str, Any]:
    """写之前先把这家公司的认错条件候选备好。

    **不要求公司已经建档**：给个代码就行。一闪而过的念头撑不到
    "先去建档、等同步、再回来"那么远。
    """
    from . import quick

    company = None
    symbol = str(symbol_or_id).strip()
    if symbol.isdigit() and len(symbol) < 6:
        company = get_company(int(symbol))
    if company is None:
        with connection() as conn:
            row = conn.execute(
                f"SELECT * FROM companies WHERE symbol = ?{_sw()}", (symbol,)).fetchone()
            company = dict(row) if row else None

    name = company["name"] if company else None
    if name is None:
        with connection() as conn:
            row = conn.execute("SELECT name FROM market_universe WHERE symbol = ?",
                               (symbol,)).fetchone()
            name = dict(row)["name"] if row else None

    facts = {"history": {}, "pe_band": {}, "current_pe": None}
    if company:
        with connection() as conn:
            facts = _valuation_facts(conn, company)
    return {
        "symbol": company["symbol"] if company else symbol,
        "name": name,
        "company_id": company["id"] if company else None,
        "known": company is not None,
        "suggestions": quick.counter_suggestions(
            facts["history"], facts.get("pe_band") or {}, facts.get("current_pe")),
        "note": ("" if company else
                 "这家还没建档。写下判断时会自动建，行情与财务随后同步。"),
    }


def write_quick_thesis(payload: dict[str, Any]) -> dict[str, Any]:
    """三十秒写下一个判断：没建档就顺手建，然后落一条投资逻辑。

    **把建档吞掉是这件事的关键。** 「先去建档」这一步就是绝大多数念头死掉的地方。
    """
    from . import quick

    claim = str(payload.get("claim") or "").strip()
    counter = str(payload.get("counter_condition") or "").strip()
    problem = quick.validate(claim, counter)
    if problem:
        raise LedgerError(problem)

    symbol = str(payload.get("symbol") or "").strip()
    company_id = payload.get("company_id")
    created_company = False
    if not company_id:
        with connection() as conn:
            row = conn.execute(
                f"SELECT id FROM companies WHERE symbol = ?{_sw()}", (symbol,)).fetchone()
        if row:
            company_id = dict(row)["id"]
        else:
            outcome = import_watchlist(WatchlistImport(symbols=[symbol], watch_group="观察池"))
            detail = (outcome["results"] or [{}])[0]
            if detail.get("status") == "失败":
                raise LedgerError(f"{symbol}：{detail.get('detail') or '建档失败'}")
            with connection() as conn:
                row = conn.execute(
                    f"SELECT id FROM companies WHERE symbol = ?{_sw()}", (symbol,)).fetchone()
            if not row:
                raise LedgerError(f"{symbol}：建档没成功，先去公司档案手动建一次")
            company_id = dict(row)["id"]
            created_company = True

    thesis = create_thesis(int(company_id), ThesisCreate(
        claim=claim, counter_condition=counter,
        # 其余一律走默认值。**这三句之外的东西都可以事后补**，
        # 而在这里多问一个字段，就多一次半途放弃的机会。
        next_review_trigger=str(payload.get("next_review_trigger") or "手动复核")[:200],
        method_key=payload.get("method_key") or None))
    if thesis is None:
        raise LedgerError("公司不存在")
    company = get_company(int(company_id))
    return {
        "company_id": int(company_id),
        "company_name": (company or {}).get("name"),
        "symbol": (company or {}).get("symbol"),
        "thesis_id": thesis["id"],
        "created_company": created_company,
        "note": ("已建档并写下判断，行情与财务会在后台同步。" if created_company
                 else "已写下判断。"),
    }


def open_drift_questions(limit: int = 5) -> list[dict[str, Any]]:
    """还没回答的假设漂移问题。**决策总览要用它。**

    藏在公司页的一个页签里，这个机制就废了——它的全部意义在于**撞到你脸上**。
    一个你想不起来去看的诚实机制，等于没有。

    只报 ask 级（假设跟着价格走，而这期间什么都没发生）和 unexplained 级
    （改了一轮但说不出依据）。note 和 good 不往首页放：**首页每多一条，
    每一条的分量就少一分**。
    """
    with connection() as conn:
        ids = [row["id"] for row in conn.execute(
            f"SELECT DISTINCT company_id AS id FROM valuations WHERE 1=1{_sw()}").fetchall()]
    out: list[dict[str, Any]] = []
    for company_id in ids:
        view = valuation_drift(company_id)
        if not view:
            continue
        for item in view["changes"]:
            if item["reading"]["level"] not in ("ask", "unexplained"):
                continue
            out.append({
                "company_id": company_id, "company_name": view["company_name"],
                "symbol": view["symbol"], "at": item["change"]["to_at"],
                "level": item["reading"]["level"],
                "headline": item["reading"]["headline"],
                "question": item["reading"]["question"],
            })
    out.sort(key=lambda item: item["at"] or "", reverse=True)
    return out[:limit]


def dashboard() -> dict[str, Any]:
    with connection() as conn:
        thesis_rows = _rows(
            conn.execute(
                """
                SELECT t.id, c.id AS company_id, c.symbol, c.name AS company_name, t.claim, t.status,
                    t.next_review_trigger,
                    SUM(CASE WHEN e.polarity = 'support' THEN 1 ELSE 0 END) AS evidence_count,
                    SUM(CASE WHEN e.polarity = 'counter' THEN 1 ELSE 0 END) AS counter_evidence_count
                FROM theses t
                JOIN companies c ON c.id = t.company_id
                LEFT JOIN evidences e ON e.thesis_id = t.id
                WHERE 1=1{scope}
                -- 裸列要写全。SQLite 容忍 GROUP BY t.id 后面跟一堆没聚合的列（它随便挑一行），
                -- PG 直接拒绝——而 PG 是对的：那些列取哪一行本来就没定义。
                GROUP BY t.id, c.id, c.symbol, c.name, t.claim, t.status, t.next_review_trigger, t.updated_at
                ORDER BY CASE t.status WHEN 'challenged' THEN 0 WHEN 'broken' THEN 1 WHEN 'watching' THEN 2 ELSE 3 END,
                         t.updated_at DESC
                """.format(scope=_sw("c"))
            ).fetchall()
        )
        for item in thesis_rows:
            item["evidence_count"] = item["evidence_count"] or 0
            item["counter_evidence_count"] = item["counter_evidence_count"] or 0

        watchlist = _rows(
            conn.execute(
                """
                SELECT c.id, c.symbol, c.name, c.industry, c.valuation_percentile, c.roe_trend,
                    COALESCE((SELECT t.status FROM theses t WHERE t.company_id = c.id ORDER BY t.updated_at DESC LIMIT 1), 'watching') AS thesis_status,
                    (SELECT date(t.updated_at) FROM theses t WHERE t.company_id = c.id ORDER BY t.updated_at DESC LIMIT 1) AS last_reviewed_at,
                    ms.price AS latest_price, ms.change_percent, ms.pe, ms.pb, ms.market_timestamp, ms.source AS market_source
                FROM companies c
                LEFT JOIN market_snapshots ms ON ms.id = (
                    SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
                    ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1
                )
                WHERE c.is_watched = 1{scope}
                ORDER BY c.watch_group, c.name, c.id
                """.format(scope=_sw("c"))
            ).fetchall()
        )
        events = _rows(
            conn.execute(
                """
                SELECT e.id, e.company_id, c.symbol, c.name AS company_name, e.category, e.title,
                    e.occurred_at, e.importance, e.verification
                FROM research_events e JOIN companies c ON c.id = e.company_id
                WHERE 1=1{scope}
                -- e.id 是**必须的**兜底，不是装饰：同一天的公告 occurred_at 完全相同，
                -- 没有决胜键时返回哪 8 条由存储引擎决定 —— SQLite 给 rowid 序、
                -- PG 给堆序，同一份数据两边首页显示的公告不一样。
                ORDER BY CASE e.verification WHEN '待核验' THEN 0 WHEN '待交叉核验' THEN 1 ELSE 2 END,
                         e.occurred_at DESC, e.id DESC
                LIMIT 8
                """.format(scope=_sw("c"))
            ).fetchall()
        )
        market_tiles = _rows(
            conn.execute(
                """
                SELECT c.name, COALESCE(ms.total_market_cap, 1) AS value,
                    COALESCE(ms.change_percent, 0) AS change, c.watch_group AS "group"
                FROM companies c
                LEFT JOIN market_snapshots ms ON ms.id = (
                    SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
                    ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1
                )
                WHERE c.is_watched = 1{scope} ORDER BY value DESC
                """.format(scope=_sw("c"))
            ).fetchall()
        )
        exposure = _rows(
            conn.execute(
                """
                SELECT watch_group AS name, ROUND(COUNT(*) * 100.0 / NULLIF((SELECT COUNT(*) FROM companies WHERE is_watched = 1{scope}), 0), 1) AS weight
                FROM companies WHERE is_watched = 1{scope} GROUP BY watch_group ORDER BY weight DESC
                """.format(scope=_sw())
            ).fetchall()
        )
        snapshot_count = conn.execute("SELECT COUNT(DISTINCT symbol) AS count FROM market_snapshots").fetchone()["count"]
        company_count = conn.execute(f"SELECT COUNT(*) AS count FROM companies WHERE is_watched = 1{_sw()}").fetchone()["count"]
        holdings_exposure, holdings_summary = _holdings_exposure(conn)
        # 「中」级的积压：还没定性，但踩不到你任何一条认错条件。
        # 数出来是为了在收件箱页面交代一句，不是为了顶在首页。
        inbox_backlog = int(conn.execute(
            f"SELECT COUNT(*) AS count FROM company_calendar_events "
            f"WHERE inbox_status = '待核验' AND relevance IN ('中', '低'){_swc()}"
        ).fetchone()["count"])
        inbox_pending = int(
            # **只数「高」。** 决策看板本来就只对「高」派活（见 decision_board
            # 里那句 relevance = '高'），而这里原来数的是全部待核验——
            # 于是首页显示 193，点进去一件事都不用做。
            #
            # 实测这 193 条全是「中」级，且**没有一条属于你写过判断的公司**，
            # 也就是说它们踩不到任何一条认错条件。分级对高低两档是有效的
            # （高 1120 条已归档、低 725 条已忽略），失效的是「中」——
            # 它没有出口，就一直堆着。堆着可以，但不该顶在首页当待办：
            # **首页显示的待办数，必须等于点进去真的会让你做事的数量。**
            # 「高」要看；**「未分级」也要算上**——它只是还没跑过分级，
            # 不是已经判定为不重要。把它排除掉的话，分级作业一挂，
            # 首页就会显示"没事可做"，而收件箱里正在堆积。
            # 「中」「低」不算：见下面 inbox_backlog 的说明。
            conn.execute(f"SELECT COUNT(*) AS count FROM company_calendar_events "
                         f"WHERE inbox_status = '待核验' "
                         f"AND (relevance = '高' OR relevance IS NULL){_swc()}").fetchone()["count"]
        )

    statuses = [item["status"] for item in thesis_rows]
    queue = review_queue()
    return DashboardSummary(
        as_of=datetime.now().replace(microsecond=0),
        intact_theses=statuses.count("intact"),
        # **必须与复核工作台同一个来源。**
        #
        # 原来这里数的是「状态不是 intact 的逻辑」，而工作台数的是「有具体理由该复核的」。
        # 两个问题不一样：一条昨天刚写下、状态还是 watching 的逻辑，前者算，后者不算——
        # 于是总览显示「需要复核 2 条」，点进去一条也没有。
        # 而这张卡片的副标题写的是「出现新证据或已到复核期」，那正是工作台的口径。
        # 数字与它旁边那句话必须说的是同一件事，否则用户只会以为工作台坏了。
        theses_to_review=len(queue),
        total_theses=len(statuses),
        # 「有逻辑，但今天不用管」——这是最常见的状态，必须显示出来，
        # 否则两个 0 会让人以为逻辑丢了。
        theses_watching=len(statuses) - statuses.count("intact") - len(queue),
        next_review_due=_earliest_review_due(),
        unread_events=sum(event["verification"] in {"待核验", "待交叉核验"} for event in events),
        data_health=_data_health_text(snapshot_count, company_count),
        data_alerts=_data_alerts(),
        market_tiles=market_tiles or [{"name": "尚未建立研究池", "value": 1, "change": 0, "group": "本地档案"}],
        watchlist=watchlist,
        theses=thesis_rows,
        events=events,
        # 有交易流水时展示真实持仓集中度；没有时退回研究池分布，并在界面标明口径。
        portfolio_exposure=holdings_exposure or exposure,
        exposure_basis="持仓市值" if holdings_exposure else "研究池分布",
        holding_market_value=holdings_summary.get("market_value"),
        holding_unrealized_percent=holdings_summary.get("unrealized_percent"),
        holdings_reviews_due=holdings_summary.get("reviews_due", 0),
        inbox_pending=inbox_pending,
        # 未处理的反证命中。侧栏徽章用它——见 DashboardSummary.counter_hits 的说明。
        counter_hits=len(open_counter_hits()),
        # 还没比对过的公告数。**必须跟上面那个数分开摆** ——
        # 只给「命中 0」的话，"比过了没事"和"压根没比过"在页面上一模一样。
        counter_uncompared=uncompared_counter_events(),
        # 有几条判断根本没写认错条件。**它们不在网里** ——
        # 反证比对只查写了条件的，所以这些记录永远不会被撞上，而且不报错。
        theses_without_counter=theses_missing_counter(),
        inbox_backlog=inbox_backlog,
        # 这一份是不是以游客身份查出来的。见 DashboardSummary.viewer_is_guest：
        # 游客域查出来的空档案，不许长得像"你还没有公司"。
        viewer_is_guest=current_scope() == GUEST_SCOPE,
        # 还没回答的假设漂移。**这是"不会心软的记录者"唯一有效的出口**——
        # 藏在公司页的一个页签里，它就废了：那里要你自己想起来去看，
        # 而这个机制专门用来对付"想不起来"。
        drift_questions=open_drift_questions(),
        # 到期还没核对的承诺。**这个函数一直存在、也一直没人调用**——
        # 见 DashboardSummary.promises_due 的说明。
        promises_due=due_promises(),
    ).model_dump(mode="json")


# --- 持仓与交易账本 -------------------------------------------------------
# 持仓不单独存表，一律由交易流水推导，避免流水与持仓两处事实互相矛盾。
# 成本口径：移动加权平均；买入手续费计入成本，卖出手续费冲减已实现盈亏。

_TRADE_SELECT = """
    SELECT t.id, t.portfolio_id, p.name AS portfolio_name, t.company_id, c.symbol,
        c.name AS company_name, t.thesis_id, t.side, t.trade_date, t.shares, t.price, t.fee,
        t.weight_percent, t.cash_amount,
        t.rationale, t.expectation, t.review_due, t.thesis_claim_snapshot, t.thesis_status_snapshot,
        t.created_at,
        (SELECT COUNT(*) FROM record_revisions r WHERE r.entity_type = 'trade' AND r.entity_id = t.id) AS revision_count
    FROM trades t
    JOIN companies c ON c.id = t.company_id
    JOIN portfolios p ON p.id = t.portfolio_id
"""


def _trade_records(rows) -> list[dict[str, Any]]:
    trades = _rows(rows)
    for trade in trades:
        trade["revision_count"] = trade.get("revision_count") or 0
        trade["amount"] = _trade_amount(trade)
    return trades


def _trade_amount(trade: dict[str, Any]) -> float | None:
    """这一行的现金流。ratio 模式只把成本价作为上下文，不计算总金额。

    0 会被读成「这笔没花钱」，而事实是「我们故意没有记金额」——
    两者在页面上长得一样，但含义完全相反。
    """
    fee = float(trade.get("fee") or 0)
    side = trade["side"]
    if side == "dividend":
        cash = trade.get("cash_amount")
        return round(float(cash) - fee, 2) if cash is not None else None
    shares, price = trade.get("shares"), trade.get("price")
    if shares is None or price is None:
        return None
    gross = float(shares) * float(price)
    # 买入与配股是付出，卖出是收回，送股不动钱。
    if side in ("buy", "rights"):
        return round(gross + fee, 2)
    if side == "sell":
        return round(gross - fee, 2)
    return 0.0


def _accumulate_positions(trades: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    states: dict[int, dict[str, Any]] = {}
    for trade in sorted(trades, key=lambda item: (item["trade_date"], item["id"])):
        state = states.setdefault(
            trade["company_id"],
            {
                "company_id": trade["company_id"],
                "shares": 0.0,
                # ratio 口径不记录股数与金额，但可以可选记录成本价作为研究上下文。
                "average_cost_snapshot": None,
                "cost_value": 0.0,
                "realized_pnl": 0.0,
                # 已经卖掉的那部分当初花了多少本金。总回报率的分母要用
                # 「投入过的本金」，只用当前成本会在卖掉一半后让收益率凭空翻倍。
                "realized_cost": 0.0,
                "dividend_income": 0.0,
                "weight_percent": None,
                "trade_count": 0,
                "first_trade_date": trade["trade_date"],
                "last_trade_date": trade["trade_date"],
                "next_review_due": None,
            },
        )
        side = trade["side"]
        fee = float(trade.get("fee") or 0)
        shares = float(trade["shares"]) if trade.get("shares") is not None else 0.0
        price = float(trade["price"]) if trade.get("price") is not None else 0.0

        if trade.get("weight_percent") is not None:
            # ratio 模式：每一行记的是「这次之后它占我多少」，取最后一次即可。
            state["weight_percent"] = float(trade["weight_percent"])
            if trade.get("price") is not None and float(trade["price"]) > 0:
                state["average_cost_snapshot"] = float(trade["price"])

        if side == "dividend":
            # **分红不进 realized_pnl。** 卖出赚的差价与拿着收的现金是两种钱，
            # 合并之后就再也看不出这笔投资是靠差价还是靠现金流回报的。
            cash = trade.get("cash_amount")
            if cash is not None:
                state["dividend_income"] += float(cash) - fee
        elif side == "bonus":
            # 送股/转增：股数增加，投入的钱一分没变 —— 于是每股成本自然被摊薄。
            # 不做这一步的话，除权后价格腰斩而成本不动，账面会凭空显示巨亏。
            state["shares"] += shares
        elif side in ("buy", "rights"):
            state["shares"] += shares
            state["cost_value"] += shares * price + fee
        elif side == "sell":
            held = state["shares"]
            if held <= 0:
                # 没有对应持仓的卖出：只记现金流，不构造负持仓和负成本。
                state["realized_pnl"] += shares * price - fee
            else:
                sold = min(shares, held)
                average = state["cost_value"] / held
                state["realized_pnl"] += sold * (price - average) - fee
                state["realized_cost"] += average * sold
                state["cost_value"] = max(0.0, state["cost_value"] - average * sold)
                state["shares"] = held - sold
                if state["shares"] < 1e-6:
                    state["shares"] = 0.0
                    state["cost_value"] = 0.0
        state["trade_count"] += 1
        state["last_trade_date"] = max(state["last_trade_date"], trade["trade_date"])
        state["first_trade_date"] = min(state["first_trade_date"], trade["trade_date"])
        if trade["review_due"]:
            current = state["next_review_due"]
            state["next_review_due"] = trade["review_due"] if current is None else min(current, trade["review_due"])
    return states


def _company_context(conn: sqlite3.Connection, company_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not company_ids:
        return {}
    placeholders = ",".join("?" for _ in company_ids)
    rows = _rows(
        conn.execute(
            f"""
            SELECT c.id, c.symbol, c.name AS company_name, c.industry,
                ms.price AS latest_price, ms.market_timestamp,
                (SELECT t.status FROM theses t WHERE t.company_id = c.id ORDER BY t.updated_at DESC LIMIT 1) AS thesis_status
            FROM companies c
            LEFT JOIN market_snapshots ms ON ms.id = (
                SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
                ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1
            )
            WHERE c.id IN ({placeholders})
            """,
            company_ids,
        ).fetchall()
    )
    return {row["id"]: row for row in rows}


def _build_positions(conn: sqlite3.Connection, trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    states = _accumulate_positions(trades)
    context = _company_context(conn, list(states))
    positions: list[dict[str, Any]] = []
    for state in states.values():
        info = context.get(state["company_id"], {})
        latest_price = info.get("latest_price")
        shares = state["shares"]
        cost_value = round(state["cost_value"], 2)
        market_value = round(shares * float(latest_price), 2) if latest_price and shares > 0 else None
        unrealized = round(market_value - cost_value, 2) if market_value is not None else None
        positions.append(
            {
                **state,
                "symbol": info.get("symbol", ""),
                "company_name": info.get("company_name", ""),
                "industry": info.get("industry", ""),
                "shares": round(shares, 4),
                "cost_value": cost_value,
                "realized_cost": round(state["realized_cost"], 2),
                "average_cost": (
                    round(cost_value / shares, 4) if shares > 0
                    else (round(float(state["average_cost_snapshot"]), 4)
                          if state.get("average_cost_snapshot") is not None else None)
                ),
                "latest_price": latest_price,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "unrealized_percent": round(unrealized / cost_value * 100, 2) if unrealized is not None and cost_value > 0 else None,
                "realized_pnl": round(state["realized_pnl"], 2),
                "dividend_income": round(state["dividend_income"], 2),
                # 摊薄视角：已收分红从成本里扣掉。券商不这么显示，所以另开一个字段，
                # average_cost 保持与券商一致，两种看法都摆出来。
                "cost_after_dividends": (
                    round(max(0.0, cost_value - state["dividend_income"]) / shares, 4)
                    if shares > 0 else None),
                "thesis_status": info.get("thesis_status"),
                "market_timestamp": info.get("market_timestamp"),
                "weight": None,
            }
        )
    # **持有与否不能只看股数。** ratio 口径（只记仓位占比、不落总金额）下
    # shares 永远是 0，于是一笔 30% 的持仓会被划进"已清仓"，组合里一只票都不剩——
    # 而这正是站主自己选的隐私口径，坏了不报错，只是页面上空空如也。
    # 判据改成「股数为正 **或** 最后一次记的占比为正」，两种口径各自成立。
    def _is_open(item: dict[str, Any]) -> bool:
        if item["shares"] > 0:
            return True
        return item["shares"] <= 0 and (item.get("weight_percent") or 0) > 0
    open_positions = [item for item in positions if _is_open(item)]
    closed_positions = [item for item in positions if not _is_open(item)]
    priced_value = sum(item["market_value"] for item in open_positions if item["market_value"] is not None)
    for item in open_positions:
        if item["market_value"] is not None and priced_value > 0:
            item["weight"] = round(item["market_value"] / priced_value * 100, 2)
        elif item.get("weight_percent") is not None:
            # ratio 口径：占比就是你自己记的那个数，不用再算一遍。
            item["weight"] = round(float(item["weight_percent"]), 2)
    open_positions.sort(key=lambda item: (item["market_value"] is None,
                                          -(item["market_value"] or item["cost_value"] or item["weight"] or 0)))
    closed_positions.sort(key=lambda item: item["last_trade_date"], reverse=True)
    return open_positions, closed_positions


def _portfolio_summary(row: dict[str, Any], open_positions: list[dict[str, Any]], closed_positions: list[dict[str, Any]], trade_count: int) -> dict[str, Any]:
    today = date.today().isoformat()
    priced = [item for item in open_positions if item["market_value"] is not None]
    cost_value = round(sum(item["cost_value"] for item in open_positions), 2)
    market_value = round(sum(item["market_value"] for item in priced), 2) if priced else None
    priced_cost = round(sum(item["cost_value"] for item in priced), 2)
    unrealized = round(market_value - priced_cost, 2) if market_value is not None else None
    weights = sorted((item["weight"] or 0) for item in open_positions)
    return {
        **row,
        "position_count": len(open_positions),
        "trade_count": trade_count,
        "cost_value": cost_value,
        "market_value": market_value,
        "unrealized_pnl": unrealized,
        "unrealized_percent": round(unrealized / priced_cost * 100, 2) if unrealized is not None and priced_cost > 0 else None,
        "realized_pnl": round(sum(item["realized_pnl"] for item in open_positions + closed_positions), 2),
        "dividend_income": round(sum(item.get("dividend_income") or 0 for item in open_positions + closed_positions), 2),
        "largest_weight": weights[-1] if weights else None,
        "top3_weight": round(sum(weights[-3:]), 2) if weights else None,
        "priced_positions": len(priced),
        "reviews_due": sum(1 for item in open_positions if item["next_review_due"] and item["next_review_due"] <= today),
        "quote_as_of": max((item["market_timestamp"] for item in priced if item["market_timestamp"]), default=None),
    }


def ensure_default_portfolio() -> int:
    with connection() as conn:
        return _ensure_default_portfolio(conn)


def _ensure_default_portfolio(conn: sqlite3.Connection) -> int:
    row = conn.execute(f"SELECT id FROM portfolios WHERE 1=1{_sw()} ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    timestamp = now_iso()
    cursor = conn.execute(
        "INSERT INTO portfolios (user_id, name, objective, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (_stamp(), "主组合", "", timestamp, timestamp),
    )
    return int(cursor.lastrowid)


def list_portfolios() -> list[dict[str, Any]]:
    with connection() as conn:
        _ensure_default_portfolio(conn)
        summaries = []
        for row in _rows(conn.execute(f"SELECT * FROM portfolios WHERE 1=1{_sw()} ORDER BY id").fetchall()):
            trades = _trade_records(conn.execute(f"{_TRADE_SELECT} WHERE t.portfolio_id = ?{_sw(chr(112))}", (row["id"],)).fetchall())
            open_positions, closed_positions = _build_positions(conn, trades)
            summaries.append(_portfolio_summary(row, open_positions, closed_positions, len(trades)))
        return summaries


def get_portfolio(portfolio_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = _one_or_none(conn.execute(f"SELECT * FROM portfolios WHERE id = ?{_sw()}", (portfolio_id,)).fetchone())
        if not row:
            return None
        trades = _trade_records(
            conn.execute(f"{_TRADE_SELECT} WHERE t.portfolio_id = ?{_sw(chr(112))} ORDER BY t.trade_date DESC, t.id DESC", (portfolio_id,)).fetchall()
        )
        open_positions, closed_positions = _build_positions(conn, trades)
        return {
            **_portfolio_summary(row, open_positions, closed_positions, len(trades)),
            "positions": open_positions,
            "closed_positions": closed_positions,
            "trades": trades,
        }


def create_portfolio(payload: PortfolioCreate) -> dict[str, Any]:
    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO portfolios (user_id, name, objective, amount_mode, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_stamp(), payload.name.strip(), payload.objective.strip(), payload.amount_mode.value,
             timestamp, timestamp),
        )
        row = _one_or_none(conn.execute("SELECT * FROM portfolios WHERE id = ?", (cursor.lastrowid,)).fetchone())
    return _portfolio_summary(row or {}, [], [], 0)


def scan_trade_screenshot(image_bytes: bytes, media_type: str, hint: str = "",
                          company_id: int | None = None) -> dict[str, Any]:
    """读一张券商截图，返回待确认的流水。**不写库。**"""

    from .ledger_scan import scan_screenshot

    with connection() as conn:
        # **这里原来漏了数据域过滤**，整张 companies 表都进了匹配名单：
        # 落库那一步有 _sw() 兜着所以写不进去，但「代码 600519」这类匹配说明
        # 会指向别人的档案，而且别人研究了哪些票会从这里泄出去。
        roster = _rows(conn.execute(
            f"SELECT id, symbol, name FROM companies WHERE 1=1{_sw()} ORDER BY id").fetchall())
    return scan_screenshot(image_bytes, media_type, roster, hint, company_id=company_id)


# Pydantic 的原文是英文（"Input should be greater than 0"）。这批错误会直接摆在
# 读图确认页上，逐条挨着中文的流水显示——夹一句英文进去，人第一反应是"系统坏了"。
_FIELD_LABEL = {"shares": "股数", "price": "成交价", "cash_amount": "到账金额", "fee": "费用",
                "trade_date": "日期", "company_id": "公司", "rationale": "理由",
                "weight_percent": "仓位占比", "side": "方向"}


def _readable_validation(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = next((str(part) for part in reversed(first.get("loc") or ()) if isinstance(part, str)), "")
    label = _FIELD_LABEL.get(field, field or "内容")
    kind = first.get("type", "")
    raw_limit = (first.get("ctx") or {}).get("gt", (first.get("ctx") or {}).get("ge"))
    # Pydantic 给的是浮点数：「股数必须大于 0.0」读起来像系统在说机器话。
    limit = (int(raw_limit) if isinstance(raw_limit, (int, float)) and raw_limit == int(raw_limit)
             else raw_limit)
    if kind == "greater_than":
        return f"{label}必须大于 {limit}"
    if kind == "greater_than_equal":
        return f"{label}不能小于 {limit}"
    if kind == "missing":
        return f"{label}不能为空"
    if kind in ("float_parsing", "int_parsing"):
        return f"{label}需要填数字"
    if kind in ("date_parsing", "date_from_datetime_parsing"):
        return f"{label}的日期格式不对"
    if kind in ("string_too_short", "too_short"):
        return f"{label}太短了"
    return f"{label}：{first.get('msg', '填写有误')}"


def mark_known_trades(portfolio_id: int, rows: list[dict[str, Any]]) -> list[int]:
    """这批读出来的流水里，哪几条账本里**已经有了**。

    补录时最容易出的事：上次只记了勾上的那些，这次回来想补剩下的，
    一个「全选」就把已经记过的又记一遍。而账本里两笔一模一样的交易，
    事后没有任何办法分辨哪一笔是多的——**它不会报错，只会让成本价一直偏**。

    判据是「同组合·同公司·同日·同方向·同价·同量」。**只标记，不拦截**：
    同一天拆单成交出两笔完全相同的记录是真会发生的，替人决定不记就是替人做主。
    """
    with connection() as conn:
        existing = {
            (r["company_id"], str(r["trade_date"]), r["side"],
             None if r["shares"] is None else round(float(r["shares"]), 4),
             None if r["price"] is None else round(float(r["price"]), 4),
             None if r["cash_amount"] is None else round(float(r["cash_amount"]), 2))
            for r in conn.execute(
                f"""SELECT company_id, trade_date, side, shares, price, cash_amount
                    FROM trades WHERE portfolio_id = ? AND portfolio_id IN
                    (SELECT id FROM portfolios WHERE 1=1{_sw()})""", (portfolio_id,)).fetchall()}

    def key(row: dict[str, Any]):
        def num(value, digits):
            return None if value is None else round(float(value), digits)
        return (row.get("company_id"), str(row.get("trade_date") or ""), row.get("side"),
                num(row.get("shares"), 4), num(row.get("price"), 4), num(row.get("cash_amount"), 2))

    return [index for index, row in enumerate(rows) if key(row) in existing]


def keep_scan_rows(trades: list[dict[str, Any]]) -> int:
    """记完之后，把还没记的那几条存回读图任务里；一条不剩就把结果清掉。

    **此前记完再进来，同一批流水原样还在。** 那个"回来还能接上"是有意做的
    （读图在服务端跑几分钟，切页面不该白跑），但它没有区分"还没记"和"已经记过"——
    于是点两次就记两遍，而账本里两笔一模一样的交易，事后没有任何办法分辨哪笔是多的。
    """
    with connection() as conn:
        row = conn.execute(
            f"""SELECT id, result_json FROM background_jobs
                WHERE kind = 'ledger_scan' AND target_id = 0{_sw()}
                ORDER BY id DESC LIMIT 1""").fetchone()
        if not row:
            return 0
        if not trades:
            conn.execute("UPDATE background_jobs SET result_json = NULL, note = ? WHERE id = ?",
                         ("这批流水已经全部处理完了。", row["id"]))
            return 0
        try:
            payload = json.loads(row["result_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        payload["trades"] = trades
        conn.execute("UPDATE background_jobs SET result_json = ?, note = ? WHERE id = ?",
                     (json.dumps(payload, ensure_ascii=False, default=str),
                      f"还剩 {len(trades)} 条没记。", row["id"]))
        return len(trades)


def delete_trade(trade_id: int) -> bool:
    """删掉一笔交易。

    **此前删不掉，而逻辑、报告、产业链、策略都能删** —— 这不是写下来的取舍，
    是漏了。而交易恰恰是最需要能删的那一类：读交割单会把方向读反、会多读一行，
    手记也会记错组合。删不掉的话，唯一的补救是再记一笔反向交易去抵消，
    那等于往账本里写一笔**从未发生过的事**，比留着错的更糟。

    **不做软删。** 账本是按流水推导持仓的，一笔"标记为已删"的交易要么参与计算
    （那就没删）、要么不参与（那跟删掉没区别，只是多了一条永远查不到的记录）。
    删掉的东西在修订历史里还有（record_revisions 只追加不覆盖）。
    """
    with connection() as conn:
        return bool(conn.execute(
            f"""DELETE FROM trades WHERE id = ? AND portfolio_id IN
                (SELECT id FROM portfolios WHERE 1=1{_sw()})""", (trade_id,)).rowcount)


def create_trades_batch(portfolio_id: int, payloads: list[Any]) -> dict[str, Any]:
    """批量确认读图结果。

    **逐条独立成败**，不做「一条错全部回滚」：截图里十条有一条日期读错，
    因为它把另外九条也退回去，用户就得整批重录——那正是读图想省掉的事。
    每条的失败原因单独返回，改完再补那一条。
    """

    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for index, raw in enumerate(payloads):
        # **校验放在循环里，不放在请求模型上。** 放在模型上的话一条坏行会让
        # Pydantic 在进这个函数之前就 422 掉整批，上面那句「逐条独立成败」就是空话。
        try:
            payload = raw if isinstance(raw, TradeCreate) else TradeCreate.model_validate(raw)
        except ValidationError as exc:
            failed.append({"index": index, "error": _readable_validation(exc)})
            continue
        try:
            trade = create_trade(portfolio_id, payload)
            if trade is None:
                failed.append({"index": index, "error": "组合不存在"})
            else:
                created.append(trade)
        except LedgerError as exc:
            failed.append({"index": index, "error": str(exc)})
    return {"created": created, "failed": failed,
            "note": f"记入 {len(created)} 条" + (f"，{len(failed)} 条没记（原因见下）" if failed else "。")}


def update_portfolio(portfolio_id: int, payload: "PortfolioUpdate") -> dict[str, Any] | None:
    """改组合设置。**口径切换要挡住**：已有金额记录的组合改成 ratio，
    要么把金额删掉、要么保留着但界面不显示——两种都是在骗人。所以先清空再切。"""

    with connection() as conn:
        row = conn.execute(f"SELECT * FROM portfolios WHERE id = ?{_sw()}", (portfolio_id,)).fetchone()
        if not row:
            return None
        updates: dict[str, Any] = {}
        if payload.name is not None:
            updates["name"] = payload.name.strip()
        if payload.objective is not None:
            updates["objective"] = payload.objective.strip()
        if payload.amount_mode is not None and payload.amount_mode.value != (row["amount_mode"] or "full"):
            if payload.amount_mode.value == "ratio":
                has_amounts = conn.execute(
                    "SELECT COUNT(*) AS c FROM trades WHERE portfolio_id = ? "
                    "AND (price IS NOT NULL OR cash_amount IS NOT NULL)", (portfolio_id,)
                ).fetchone()["c"]
                if has_amounts:
                    raise LedgerError(
                        f"这个组合里已经有 {has_amounts} 条带金额的记录。改成只记比例之前，"
                        "请先删掉它们——留着不显示等于假装没记。")
            updates["amount_mode"] = payload.amount_mode.value
        if updates:
            updates["updated_at"] = now_iso()
            assignments = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE portfolios SET {assignments} WHERE id = ?",
                         (*updates.values(), portfolio_id))
    return get_portfolio(portfolio_id)


def _held_shares(conn: sqlite3.Connection, portfolio_id: int, company_id: int) -> float:
    trades = _trade_records(
        conn.execute(f"{_TRADE_SELECT} WHERE t.portfolio_id = ? AND t.company_id = ?{_sw(chr(112))}", (portfolio_id, company_id)).fetchall()
    )
    state = _accumulate_positions(trades).get(company_id)
    return float(state["shares"]) if state else 0.0


# 不是你的决定的那几种，理由可以不写——系统替你写清楚它是怎么来的。
AUTOMATIC_RATIONALE = {
    "dividend": "现金分红到账，非主动操作。",
    "bonus": "送股/转增到账，非主动操作。",
    "rights": "参与配股。",
}


def _validate_trade(payload: TradeCreate, amount_mode: str) -> None:
    """按「记录类型 × 账本口径」检查该填的字段。

    校验放在这里而不是 Pydantic 上：必填与否取决于组合是 full 还是 ratio，
    而 schema 层看不到组合。
    """
    side = payload.side.value
    if amount_mode == "ratio":
        if payload.weight_percent is None:
            raise LedgerError("这个组合只记仓位占比，请填写这次之后它占多少（0–100）。")
        if any(v is not None for v in (payload.shares, payload.cash_amount)):
            raise LedgerError("这个组合只记仓位占比；股数与现金流水请放到完整账本。")
        if payload.price is not None and payload.price <= 0:
            raise LedgerError("成本价要大于 0；如果不想记录成本，可以留空。")
        return

    if side == "dividend":
        if payload.cash_amount is None:
            raise LedgerError("现金分红请填写税后到账金额。")
        return
    if side == "bonus":
        if not payload.shares:
            raise LedgerError("送股/转增请填写增加的股数。")
        return
    if not payload.shares:
        raise LedgerError("请填写股数。")
    if payload.price is None:
        raise LedgerError("请填写成交价。")
    if payload.price <= 0:
        raise LedgerError("成交价要大于 0。")


def create_trade(portfolio_id: int, payload: TradeCreate) -> dict[str, Any] | None:
    with connection() as conn:
        portfolio = conn.execute(
            f"SELECT id, amount_mode FROM portfolios WHERE id = ?{_sw()}", (portfolio_id,)).fetchone()
        if not portfolio:
            return None
        amount_mode = portfolio["amount_mode"] or "full"
        _validate_trade(payload, amount_mode)
        company = conn.execute(f"SELECT id FROM companies WHERE id = ?{_sw()}", (payload.company_id,)).fetchone()
        if not company:
            raise LedgerError("该公司不在本地档案中，请先建立公司档案。")
        if not _thesis_belongs_to_company(conn, payload.company_id, payload.thesis_id):
            raise LedgerError("关联的投资逻辑不属于这家公司。")
        if payload.side == "sell" and amount_mode == "full" and payload.shares:
            held = _held_shares(conn, portfolio_id, payload.company_id)
            if payload.shares > held + 1e-6:
                raise LedgerError(f"卖出股数超过该组合的持仓：当前持有 {held:g} 股。")
        rationale = payload.rationale.strip() or AUTOMATIC_RATIONALE.get(payload.side.value, "")
        if not rationale:
            raise LedgerError("买入卖出必须写下当时的理由——事后补写的理由已经不是当时的想法了。")
        claim_snapshot = ""
        status_snapshot = ""
        if payload.thesis_id:
            thesis = conn.execute("SELECT claim, status FROM theses WHERE id = ?", (payload.thesis_id,)).fetchone()
            if thesis:
                # 记录下单当时的逻辑原文，日后逻辑被修改也能回看当初的判断。
                claim_snapshot = thesis["claim"]
                status_snapshot = thesis["status"]
        cursor = conn.execute(
            """
            INSERT INTO trades (
                portfolio_id, company_id, thesis_id, side, trade_date, shares, price, fee,
                weight_percent, cash_amount,
                rationale, expectation, review_due, thesis_claim_snapshot, thesis_status_snapshot, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                payload.company_id,
                payload.thesis_id,
                payload.side.value,
                payload.trade_date.isoformat(),
                payload.shares,
                payload.price,
                payload.fee,
                payload.weight_percent,
                payload.cash_amount,
                rationale,
                payload.expectation.strip(),
                payload.review_due.isoformat() if payload.review_due else None,
                claim_snapshot,
                status_snapshot,
                now_iso(),
            ),
        )
        trade_id = int(cursor.lastrowid)
        _record_revision(
            conn,
            "trade",
            trade_id,
            {
                "rationale": payload.rationale.strip(),
                "expectation": payload.expectation.strip(),
                "review_due": payload.review_due.isoformat() if payload.review_due else None,
                "thesis_id": payload.thesis_id,
            },
            list(TRADE_VERSIONED_FIELDS),
            change_note="记录交易",
        )
        conn.execute("UPDATE portfolios SET updated_at = ? WHERE id = ?", (now_iso(), portfolio_id))
        rows = conn.execute(f"{_TRADE_SELECT} WHERE t.id = ?{_sw(chr(112))}", (trade_id,)).fetchall()
    return _trade_records(rows)[0]


def update_trade(trade_id: int, payload: TradeUpdate) -> dict[str, Any] | None:
    fields = payload.model_dump(exclude_unset=True)
    change_note = str(fields.pop("change_note", "") or "")
    with connection() as conn:
        # 这里不带域的后果比"读到别人的"更糟：UPDATE 照样生效，随后的回读被域过滤
        # 挡住，于是接口 500 而数据已经被改了——看日志像是服务坏了，其实是越权写入。
        current = _one_or_none(conn.execute(
            f"SELECT * FROM trades WHERE id = ?{_swc('company_id')}", (trade_id,)).fetchone())
        if not current:
            return None
        updates: dict[str, Any] = {}
        if "review_due" in fields:
            updates["review_due"] = fields["review_due"].isoformat() if fields["review_due"] else None
        if fields.get("expectation") is not None:
            updates["expectation"] = str(fields["expectation"]).strip()
        if fields.get("rationale") is not None:
            updates["rationale"] = str(fields["rationale"]).strip()
        changed = [field for field, value in updates.items() if current.get(field) != value]
        if changed:
            assignments = ", ".join(f"{field} = ?" for field in changed)
            conn.execute(
                f"UPDATE trades SET {assignments} WHERE id = ?",
                [*(updates[field] for field in changed), trade_id],
            )
            snapshot = {field: updates.get(field, current.get(field)) for field in TRADE_VERSIONED_FIELDS}
            _record_revision(conn, "trade", trade_id, snapshot, changed, change_note)
        rows = conn.execute(f"{_TRADE_SELECT} WHERE t.id = ?{_sw(chr(112))}", (trade_id,)).fetchall()
    return _trade_records(rows)[0]


def _company_ledger(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    trades = _trade_records(
        conn.execute(f"{_TRADE_SELECT} WHERE t.company_id = ?{_sw(chr(112))} ORDER BY t.trade_date DESC, t.id DESC", (company_id,)).fetchall()
    )
    if not trades:
        return None
    open_positions, closed_positions = _build_positions(conn, trades)
    position = (open_positions or closed_positions)[0]
    return {
        "shares": position["shares"],
        "average_cost": position["average_cost"],
        "cost_value": position["cost_value"],
        "market_value": position["market_value"],
        "unrealized_pnl": position["unrealized_pnl"],
        "unrealized_percent": position["unrealized_percent"],
        "realized_pnl": position["realized_pnl"],
        "dividend_income": position["dividend_income"],
        "cost_after_dividends": position["cost_after_dividends"],
        # 总回报 = 浮动盈亏 + 已实现差价 + 已收分红。
        # 这才是"这笔投资到底赚没赚"的答案；只看浮动盈亏会漏掉后两块。
        "total_return": _total_return(position),
        "total_return_percent": _total_return_percent(position),
        "next_review_due": position["next_review_due"],
        "portfolio_names": sorted({trade["portfolio_name"] for trade in trades}),
        # 仓位口径：把最后一次记的占比和账本口径一起带出去。
        # 不带的话前端只能看 shares，而 ratio 口径下它永远是 0 —— 于是
        # 「仓位 50%」被显示成「已清仓」。组合页早就处理了这件事（见 _is_open），
        # 公司页这条路一直漏着。
        "weight_percent": position.get("weight_percent"),
        # **只有"没有股数、但记了仓位"才算仓位口径。**
        # 同一家公司可能同时躺在完整组合（有股数）和轻量组合（只有占比）里，
        # 账本是按公司合并的 —— 那种情况下股数是真的，市值与盈亏都算得出来，
        # 不该被当成仓位口径把这些藏掉。第一版判据只看 weight_percent 不为空，
        # 实测就撞上了这一幕（格力：4700 股 + 50% 同时存在）。
        "amount_mode": ("ratio" if (position["shares"] <= 0 and position.get("weight_percent") is not None)
                        else "full"),
        "trades": trades,
    }


def _total_return(position: dict[str, Any]) -> float | None:
    parts = [position.get("unrealized_pnl"), position.get("realized_pnl"), position.get("dividend_income")]
    if all(part is None for part in parts):
        return None
    return round(sum(part or 0 for part in parts), 2)


def _total_return_percent(position: dict[str, Any]) -> float | None:
    """分母用「投入过的本金」而不是「当前成本」。

    卖掉一半之后当前成本减半，拿它当分母会让收益率凭空翻倍——
    那个数字好看，但回答不了"我这笔钱赚了多少"。
    """
    total = _total_return(position)
    invested = (position.get("cost_value") or 0) + max(0.0, position.get("realized_cost") or 0)
    base = invested or position.get("cost_value") or 0
    if total is None or base <= 0:
        return None
    return round(total / base * 100, 2)


def _holdings_exposure(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """全部组合合并后的持仓集中度；没有交易记录时返回空列表。"""

    trades = _trade_records(conn.execute(f"{_TRADE_SELECT} WHERE 1=1{_sw(chr(112))}").fetchall())
    if not trades:
        return [], {}
    open_positions, closed_positions = _build_positions(conn, trades)
    summary = _portfolio_summary({}, open_positions, closed_positions, len(trades))
    exposure = [
        {"name": item["company_name"] or item["symbol"], "weight": item["weight"] or 0.0}
        for item in open_positions
        if item["weight"] is not None
    ]
    return exposure, summary


# --- 公司简况（概况、股本、分红、解禁、公告） ---------------------------------
# 全部字段来自公开披露的数据源；缺失的部分留空并在页面标明，不用推测值填充。

_PROFILE_COLUMNS = (
    "full_name", "english_name", "industry", "market", "legal_representative", "registered_capital",
    "founded_date", "listed_date", "website", "registered_address", "office_address", "main_business",
    "product_type", "business_scope", "introduction", "total_shares", "circulating_shares",
    "share_structure_date", "share_change_reason", "issue_price", "raised_net", "underwriter",
    "latest_dividend_period", "latest_dividend_plan", "latest_dividend_progress",
    "latest_dividend_payout_ratio", "latest_dividend_record_date", "latest_dividend_ex_date",
)


def _fetch_company_profile_payload(symbol: str) -> dict[str, Any]:
    try:
        payload = fetch_company_profile(symbol)
    except CompanyProfileError as exc:
        _record_provider_sync(
            company_profile_provider.provider_id,
            company_profile_provider.display_name,
            company_profile_provider.category,
            "异常",
            error=str(exc),
        )
        raise
    _record_provider_sync(
        company_profile_provider.provider_id,
        company_profile_provider.display_name,
        company_profile_provider.category,
        "已同步",
        refreshed_items=len(payload.get("events", [])),
    )
    return payload


def store_company_profile(company_id: int, payload: dict[str, Any]) -> int:
    timestamp = now_iso()
    events = payload.get("events", [])
    columns = ", ".join(_PROFILE_COLUMNS)
    placeholders = ", ".join("?" for _ in _PROFILE_COLUMNS)
    updates = ", ".join(f"{column} = excluded.{column}" for column in _PROFILE_COLUMNS)
    values = [payload.get(column) for column in _PROFILE_COLUMNS]
    with connection() as conn:
        symbol = _symbol_of(conn, company_id)
        if not symbol:
            return 0
        conn.execute(
            f"""
            INSERT INTO company_profiles (symbol, {columns}, missing_sections, source, refreshed_at)
            VALUES (?, {placeholders}, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                {updates},
                missing_sections = excluded.missing_sections,
                source = excluded.source,
                refreshed_at = excluded.refreshed_at
            """,
            [symbol, *values, "、".join(payload.get("missing_sections", [])), payload.get("source", "AKShare"), timestamp],
        )
        for event in events:
            conn.execute(
                """
                INSERT INTO company_calendar_events (company_id, category, event_date, title, detail, url, source, refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_id, category, event_date, title) DO UPDATE SET
                    detail = excluded.detail,
                    url = excluded.url,
                    source = excluded.source,
                    refreshed_at = excluded.refreshed_at
                """,
                (
                    company_id,
                    event["category"],
                    event["event_date"],
                    event["title"],
                    event.get("detail", ""),
                    event.get("url"),
                    event.get("source", payload.get("source", "AKShare")),
                    timestamp,
                ),
            )
    return len(events)


def refresh_company_profile(company_id: int) -> int | None:
    with connection() as conn:
        row = conn.execute(f"SELECT symbol FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
    if not row:
        return None
    payload = _fetch_company_profile_payload(row["symbol"])
    stored = store_company_profile(company_id, payload)
    industry = payload.get("industry")
    if industry:
        with connection() as conn:
            # 只在用户还没填过行业时回填，不覆盖用户写的分类
            conn.execute(
                """
                UPDATE companies SET industry = ?, industry_source = '巨潮资讯（证监会分类）', updated_at = ?
                WHERE id = ? AND (industry = '待补充' OR industry = '')
                """,
                (industry, now_iso(), company_id),
            )
    return stored


def _company_profile_summary(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    profile = _one_or_none(conn.execute(
        "SELECT * FROM company_profiles WHERE symbol = ?", (_symbol_of(conn, company_id),)).fetchone())
    if not profile:
        return None
    profile.pop("company_id", None)
    profile["missing_sections"] = [item for item in (profile.pop("missing_sections", "") or "").split("、") if item]
    today = date.today().isoformat()
    upcoming = _rows(
        conn.execute(
            """
            SELECT id, category, event_date, title, detail, url, source, inbox_status, archived_as FROM company_calendar_events
            WHERE company_id = ? AND event_date >= ? ORDER BY event_date ASC, id DESC LIMIT 8
            """,
            (company_id, today),
        ).fetchall()
    )
    recent = _rows(
        conn.execute(
            """
            SELECT id, category, event_date, title, detail, url, source, inbox_status, archived_as FROM company_calendar_events
            WHERE company_id = ? AND event_date < ? ORDER BY event_date DESC, id DESC LIMIT 12
            """,
            (company_id, today),
        ).fetchall()
    )
    for event in upcoming:
        event["upcoming"] = True
    for event in recent:
        event["upcoming"] = False
    profile["upcoming_events"] = upcoming
    profile["recent_events"] = recent
    profile["event_count"] = conn.execute(
        "SELECT COUNT(*) AS count FROM company_calendar_events WHERE company_id = ?", (company_id,)
    ).fetchone()["count"]
    return profile


# --- 历史估值与分位 -------------------------------------------------------
# 分位只是"当前值在历史样本中的位置"这一事实描述。
# 每个分位都必须带上样本区间、样本量和截止日；样本不足时给出原因，而不是给一个看起来能用的数字。

VALUATION_METRIC_LABELS = {"pe_ttm": "市盈率 TTM", "pb": "市净率"}
VALUATION_WINDOWS = ((3, "近 3 年"), (5, "近 5 年"))
MIN_PERCENTILE_SAMPLES = 30


def _fetch_valuation_payload(symbol: str) -> dict[str, Any]:
    try:
        payload = fetch_valuation_history(symbol)
    except ValuationDataError as exc:
        _record_provider_sync(
            valuation_provider.provider_id,
            valuation_provider.display_name,
            valuation_provider.category,
            "异常",
            error=str(exc),
        )
        raise
    _record_provider_sync(
        valuation_provider.provider_id,
        valuation_provider.display_name,
        valuation_provider.category,
        "已同步",
        refreshed_items=len(payload.get("points", [])),
    )
    return payload


def store_valuation_points(company_id: int, payload: dict[str, Any]) -> int:
    timestamp = now_iso()
    source = payload.get("source", "AKShare")
    points = payload.get("points", [])
    with connection() as conn:
        symbol = _symbol_of(conn, company_id)
        if not symbol:
            return 0
        for point in points:
            conn.execute(
                """
                INSERT INTO valuation_points (symbol, metric, point_date, value, source, refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, metric, point_date, source) DO UPDATE SET
                    value = excluded.value,
                    refreshed_at = excluded.refreshed_at
                """,
                (symbol, point["metric"], point["point_date"], point["value"], source, timestamp),
            )
    return len(points)


def refresh_company_valuation(company_id: int) -> int | None:
    with connection() as conn:
        row = conn.execute(f"SELECT symbol FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
    if not row:
        return None
    payload = _fetch_valuation_payload(row["symbol"])
    return store_valuation_points(company_id, payload)


def _percentile_of(values: list[float], current: float) -> float:
    """当前值在样本中的位置：不高于当前值的样本占比。"""

    if not values:
        return 0.0
    at_or_below = sum(1 for value in values if value <= current)
    return round(at_or_below / len(values) * 100, 1)


def _window_percentile(points: list[dict[str, Any]], years: int, latest_date: str) -> dict[str, Any]:
    cutoff = (date.fromisoformat(latest_date) - timedelta(days=365 * years)).isoformat()
    window = [point for point in points if point["point_date"] >= cutoff]
    sample = [float(point["value"]) for point in window]
    current = float(points[-1]["value"])
    first_date = points[0]["point_date"]
    result: dict[str, Any] = {
        "window_years": years,
        "sample_size": len(sample),
        "sample_start": window[0]["point_date"] if window else None,
        "sample_end": window[-1]["point_date"] if window else None,
        "percentile": None,
        "minimum": None,
        "median": None,
        "maximum": None,
        "unavailable_reason": None,
        # 样本实际横跨几年，以及"没铺满窗口"时的那句话。见下面那段。
        "covered_years": None,
        "coverage_note": None,
    }
    if len(sample) < MIN_PERCENTILE_SAMPLES:
        result["unavailable_reason"] = (
            f"窗口内仅 {len(sample)} 个样本，少于 {MIN_PERCENTILE_SAMPLES} 个，不计算分位"
            if sample
            else f"来源样本从 {first_date} 开始，未覆盖{years}年窗口"
        )
        return result
    ordered = sorted(sample)
    middle = len(ordered) // 2
    result["percentile"] = _percentile_of(sample, current)
    result["minimum"] = round(ordered[0], 2)
    result["maximum"] = round(ordered[-1], 2)
    result["median"] = round(ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2, 2)

    # **样本没铺满窗口时必须说出来。**
    #
    # 这里原来有三行：判断条件写对了，动作却是 `unavailable_reason = None` ——
    # 而那一步是空操作（走到这儿它本来就是 None）。注释写着"也要说清楚"，
    # 实际一个字都没说。
    #
    # 2026-08-14 线上实测（寒武纪）：它 2025-04 才转正，之前没有 PE，
    # 所以 pe_ttm 序列只有 1.32 年。而页面给的是
    #
    #     「近 3 年分位」1.7%      「近 5 年分位」1.7%
    #
    # 同一个数 —— 因为背后是同一批 16 个月的样本。读的人会理解成
    # "比过去五年里 98% 的时间都便宜"，而**过去五年根本没有数据**。
    # 这不是少一句提示，是这个数字在说一件没发生过的事。
    #
    # 处理方式跟这一节的既定原则一致（"样本不足时给出原因，
    # 而不是给一个看起来能用的数字"）：数字保留（16 个月也是信息），
    # 但把真实跨度一并给出去，由页面标在数字旁边。
    covered_days = (date.fromisoformat(result["sample_end"])
                    - date.fromisoformat(result["sample_start"])).days
    result["covered_years"] = round(covered_days / 365, 2)
    # 留 35 天余量：序列起点通常不会正好落在 cutoff 那一天。
    if covered_days < 365 * years - 35:
        result["coverage_note"] = (
            f"样本只覆盖 {result['covered_years']:g} 年，不足 {years} 年"
            f"（序列从 {result['sample_start']} 才开始）—— 这个分位不能当成"
            f"{years}年历史位置来读。")
    return result


def _valuation_summary(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    rows = _rows(
        conn.execute(
            """
            SELECT metric, point_date, value, source, refreshed_at FROM valuation_points
            WHERE symbol = ? AND source <> 'StockSDK'
            ORDER BY metric, point_date
            """,
            (_symbol_of(conn, company_id),),
        ).fetchall()
    )
    if not rows:
        return None
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_metric.setdefault(row["metric"], []).append(row)

    metrics: list[dict[str, Any]] = []
    for metric, label in VALUATION_METRIC_LABELS.items():
        points = by_metric.get(metric, [])
        if not points:
            metrics.append(
                {
                    "metric": metric,
                    "label": label,
                    "current": None,
                    "current_date": None,
                    "windows": [
                        {"window_years": years, "sample_size": 0, "sample_start": None, "sample_end": None, "percentile": None,
                         "minimum": None, "median": None, "maximum": None, "unavailable_reason": "来源未返回该指标"}
                        for years, _ in VALUATION_WINDOWS
                    ],
                    "history": [],
                }
            )
            continue
        latest = points[-1]
        metrics.append(
            {
                "metric": metric,
                "label": label,
                "current": round(float(latest["value"]), 2),
                "current_date": latest["point_date"],
                "windows": [_window_percentile(points, years, latest["point_date"]) for years, _ in VALUATION_WINDOWS],
                "history": [{"point_date": point["point_date"], "value": round(float(point["value"]), 2)} for point in points],
            }
        )

    local_snapshots = conn.execute(
        """
        SELECT COUNT(DISTINCT point_date) AS days, MIN(point_date) AS first_date
        FROM valuation_points WHERE symbol = ? AND source = 'StockSDK'
        """,
        (_symbol_of(conn, company_id),),
    ).fetchone()
    return {
        "source": rows[0]["source"],
        "refreshed_at": rows[0]["refreshed_at"],
        "metrics": metrics,
        "local_snapshot_days": int(local_snapshots["days"] or 0),
        "local_snapshot_start": local_snapshots["first_date"],
    }


# --- 待核验收件箱 ---------------------------------------------------------
# 已同步的公告先进收件箱，由用户决定是否归档为证据或事件；系统不自动认定它影响了投资逻辑。

INBOX_CATEGORIES = ("公告", "分红", "解禁")


def list_inbox(
    status: str = "待核验",
    limit: int = 40,
    days: int | None = 90,
    relevance: str | None = None,
) -> dict[str, Any]:
    """默认只看最近一段时间且只看"值得看"的那几档；程序性公告不该占用你的注意力。

    **但那条默认只对「待核验」成立。** 翻「已忽略」的时候，要看的恰恰就是
    被扫走的那些程序性文件 —— 拿"值得看"的档位去筛它，列表必然是空的，
    而计数还照实显示 23 条：页面上就成了"说有 23 条、一条都不给看"。
    （2026-08-15 线上实测就是这个样子，那一版是我自己刚加的状态切换。）
    """

    placeholders = ",".join("?" for _ in INBOX_CATEGORIES)
    since = (date.today() - timedelta(days=days)).isoformat() if days else "0000-00-00"

    # **显式选了等级，就严格按那个等级筛。**
    #
    # 下面那句 WHERE 原来一律带着 `relevance IS NULL OR`：还没分级的条目也要
    # 露出来，否则新进来的公告在被分级之前谁都看不见。这在默认视图下是对的。
    #
    # 但用户点「只看实质」时它照样生效 —— 2026-08-19 线上实测：
    # `relevance=高` 返回 14 条、**全部是未分级的**；`relevance=低` 返回同样那 14 条。
    # 两个互斥的筛选给出一模一样的结果，而摘要里 high=0、low=0。
    # 也就是说：点「只看实质」，看到的是 14 条明确不是实质的东西。
    if relevance:
        levels = [relevance]
        grade_clause = f"e.relevance IN ({','.join('?' for _ in levels)})"
    else:
        levels = ["高", "中"] if status == "待核验" else ["高", "中", "低"]
        # 待核验：收件箱本身要替你挡掉程序性文件。
        # 已忽略/已归档：挡掉的那些正是你回头要看的。
        # 两种情况下都要放行未分级的 —— 那是"还没轮到它"，不是"判过了不值得看"。
        grade_clause = f"(e.relevance IS NULL OR e.relevance IN ({','.join('?' for _ in levels)}))"
    with connection() as conn:
        items = _rows(
            conn.execute(
                f"""
                SELECT e.id, e.company_id, c.symbol, c.name AS company_name, e.category, e.event_date,
                    e.title, e.detail, e.url, e.source, e.inbox_status, e.archived_as, e.archived_ref_id,
                    e.handled_at, e.relevance, e.relevance_reason, e.relevance_source, e.relevance_topic, e.summary
                FROM company_calendar_events e
                JOIN companies c ON c.id = e.company_id
                WHERE e.inbox_status = ? AND e.category IN ({placeholders}) AND e.event_date >= ?
                    AND {grade_clause}{_swc('e.company_id')}
                ORDER BY CASE e.relevance WHEN '高' THEN 0 WHEN '中' THEN 1 ELSE 2 END,
                         e.event_date DESC, e.id DESC
                LIMIT ?
                """,
                (status, *INBOX_CATEGORIES, since, *levels, limit),
            ).fetchall()
        )
        totals = conn.execute(
            """
            SELECT COUNT(*) AS total,
                SUM(CASE WHEN event_date >= ? THEN 1 ELSE 0 END) AS in_window,
                SUM(CASE WHEN relevance IS NULL THEN 1 ELSE 0 END) AS ungraded,
                SUM(CASE WHEN relevance = '高' THEN 1 ELSE 0 END) AS high,
                SUM(CASE WHEN relevance = '中' THEN 1 ELSE 0 END) AS medium,
                SUM(CASE WHEN relevance = '低' THEN 1 ELSE 0 END) AS low
            FROM company_calendar_events
            WHERE inbox_status = ? AND category IN ({placeholders}){scope}
            """.format(placeholders=placeholders, scope=_swc()),
            (since, status, *INBOX_CATEGORIES),
        ).fetchone()
    return {
        "items": items,
        "total": int(totals["total"] or 0),
        "in_window": int(totals["in_window"] or 0),
        "ungraded": int(totals["ungraded"] or 0),
        "high": int(totals["high"] or 0),
        "medium": int(totals["medium"] or 0),
        "low": int(totals["low"] or 0),
        "window_days": days,
        "since": None if not days else since,
    }


def _inbox_item(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    return _one_or_none(
        conn.execute(
            """
            SELECT e.*, c.symbol, c.name AS company_name FROM company_calendar_events e
            JOIN companies c ON c.id = e.company_id WHERE e.id = ?{scope}
            """.format(scope=_sw("c")),
            (item_id,),
        ).fetchone()
    )



# ── 从纠错里学 ──────────────────────────────────────────────────────────────
#
# **纠错信号已经在你的日常动作里了，不需要另做一个「这条判错了」按钮。**
# 把一条判成「程序性」的公告归档为证据 = 它其实是实质变化；
# 把一条判成「高」的公告直接忽略 = 它其实不用看。
# 这两个动作你每天都在做，只是以前没人记下来。

def _record_correction(conn, item: dict[str, Any], now_relevance: str) -> None:
    """记一次分级纠错。判得对的不记——只记「你的动作与分级不一致」的那些。"""
    was = str(item.get("relevance") or "").strip()
    if not was or was == now_relevance:
        return
    conn.execute(
        "INSERT INTO inbox_corrections (user_id, event_id, title, was_relevance, was_source, now_relevance, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (_stamp(), item["id"], item["title"], was, item.get("relevance_source") or "", now_relevance, now_iso()),
    )


# 候选词的长度范围。太短（3 字以下）会误伤一大片，太长（10 字以上）只匹配得上它自己。
_TERM_MIN, _TERM_MAX = 4, 10
_TERM_NOISE = re.compile(r"^[0-9\W_]+$")

# 公司名与文书套话。这些词在**每一条**公告标题里都有，出现频率再高也没有区分力，
# 学进规则表只会把所有公告一网打尽。不排掉的话，挖出来的第一名会是「股份有限公司」。
_BOILERPLATE = re.compile(
    r"股份有限公司|有限公司|律师事务所|会计师事务所|证券股份|关于公司|的公告|公告$|"
    r"第[一二三四五六七八九十百]+期|[0-9]{4}年|集团股份|科技股份|新能源科技")


def learned_terms(min_hits: int = 2) -> list[dict[str, Any]]:
    """从纠错记录里挖候选规则词，**只提议，不生效**。

    规则词表直接决定几百条公告的去向，一个学歪的词会静悄悄地把一整类实质公告
    扔进程序性堆里，而且从页面上看不出来——只会觉得「最近公告怎么变少了」。
    所以这里只负责给出「这个词出现在 N 条你改过的标题里，而且没出现在你没改过的标题里」，
    确认与否是你的事。

    min_hits 默认 2：只出现过一次的词多半是巧合。
    """
    with connection() as conn:
        corrections = _rows(conn.execute(
            f"SELECT title, was_relevance, now_relevance FROM inbox_corrections WHERE 1=1{_sw()} ORDER BY id DESC LIMIT 500"
        ).fetchall())
        # 对照组：没有被纠正过的标题。一个词若两边都常见，它就没有区分力。
        agreed = [r["title"] for r in _rows(conn.execute(
            f"SELECT title FROM company_calendar_events "
            f"WHERE inbox_status <> '待核验' AND title IS NOT NULL{_swc()} "
            f"AND id NOT IN (SELECT event_id FROM inbox_corrections) LIMIT 2000"
        ).fetchall())]
        existing = {r["term"] for r in _rows(conn.execute(f"SELECT term FROM rule_terms WHERE 1=1{_sw()}").fetchall())}

    buckets: dict[tuple[str, str], list[str]] = {}
    for row in corrections:
        for length in range(_TERM_MIN, _TERM_MAX + 1):
            title = row["title"]
            for start in range(len(title) - length + 1):
                gram = title[start:start + length]
                if _TERM_NOISE.match(gram) or gram in existing:
                    continue
                buckets.setdefault((gram, row["now_relevance"]), []).append(title)

    suggestions = []
    for (gram, relevance), titles in buckets.items():
        if len(titles) < min_hits:
            continue
        if _BOILERPLATE.search(gram):
            continue
        # 有区分力才提议：在没改过的标题里也常见的词，学了只会制造新的误判。
        noise = sum(1 for title in agreed if gram in title)
        if noise > len(titles):
            continue
        suggestions.append({
            "term": gram, "relevance": relevance,
            "corrections": len(titles), "also_in_agreed": noise,
            "examples": titles[:3],
        })

    # **同一个短语会被切成一串重叠的 n-gram**（「注销到期未行权期权」会同时产出
    # 「注销到期未行权期」「销到期未行权期权」「到期未行权期权」…）。全都列出来，
    # 用户要在七八条几乎一样的词里挑，等于没帮上忙。
    # 同一族里只留最长的那个：它最具体，误伤最小。
    suggestions.sort(key=lambda item: (-item["corrections"], item["also_in_agreed"], -len(item["term"])))
    kept: list[dict[str, Any]] = []
    for item in suggestions:
        family = any(
            item["relevance"] == other["relevance"]
            and (item["term"] in other["term"] or other["term"] in item["term"])
            for other in kept
        )
        if family:
            continue
        kept.append(item)
    return kept[:20]


def list_rule_terms() -> list[dict[str, Any]]:
    with connection() as conn:
        return _rows(conn.execute(f"SELECT * FROM rule_terms WHERE 1=1{_sw()} ORDER BY created_at DESC").fetchall())


# 每个人自己的偏好。key 用白名单，不接受任意字符串：
# 拼错一个字母就会写进一条永远读不到的设置，而且看不出哪里错了。
SETTING_KEYS = {
    # 要不要让后台每天替我调模型分级。默认关：这会花积分，而且是在没人点的时候花。
    "inbox_auto_grade": False,
}


def get_setting(key: str) -> bool:
    """读当前用户的偏好。没设过就用默认值。"""
    if key not in SETTING_KEYS:
        raise LedgerError(f"没有这个设置项：{key}")
    with connection() as conn:
        row = conn.execute(
            f"SELECT value FROM user_settings WHERE key = ?{_sw()}", (key,)).fetchone()
    if row is None:
        return SETTING_KEYS[key]
    return str(row["value"]).strip().lower() in {"1", "true", "yes", "on"}


def set_setting(key: str, value: bool) -> dict[str, Any]:
    if key not in SETTING_KEYS:
        raise LedgerError(f"没有这个设置项：{key}")
    with connection() as conn:
        conn.execute(
            "INSERT INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (_stamp(), key, "1" if value else "0", now_iso()),
        )
    return {"key": key, "value": bool(value)}


def all_settings() -> dict[str, bool]:
    return {key: get_setting(key) for key in SETTING_KEYS}


def scopes_with_setting(key: str) -> list[str]:
    """哪些数据域把这项设置打开了。给调度器用——它要知道该替谁干活。

    在系统域（scope=None）跑，所以看得到所有人；这正是调度器该有的视野。
    """
    if key not in SETTING_KEYS:
        raise LedgerError(f"没有这个设置项：{key}")
    with connection() as conn:
        rows = conn.execute(
            "SELECT user_id, value FROM user_settings WHERE key = ?", (key,)).fetchall()
    return [r["user_id"] for r in rows
            if str(r["value"]).strip().lower() in {"1", "true", "yes", "on"}]


def save_rule_term(term: str, relevance: str, topic: str = "自定义", note: str = "") -> dict[str, Any]:
    term = term.strip()
    if len(term) < _TERM_MIN:
        raise LedgerError(f"规则词至少 {_TERM_MIN} 个字——太短会误伤一大片公告。")
    if relevance not in ("高", "中", "低"):
        raise LedgerError("分级只能是 高 / 中 / 低。")
    with connection() as conn:
        conn.execute(
            "INSERT INTO rule_terms (user_id, term, relevance, topic, note, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, term) DO UPDATE SET relevance = excluded.relevance, topic = excluded.topic, "
            "note = excluded.note",
            (_stamp(), term, relevance, topic.strip() or "自定义", note.strip(), now_iso()),
        )
    _load_user_terms()
    return {"term": term, "relevance": relevance, "topic": topic}


def delete_rule_term(term: str) -> bool:
    with connection() as conn:
        cursor = conn.execute(f"DELETE FROM rule_terms WHERE term = ?{_sw()}", (term,))
        deleted = (cursor.rowcount or 0) > 0
    _load_user_terms()
    return deleted


def _load_user_terms() -> None:
    """把用户确认过的词装进分级引擎。每轮分级前与每次增删后调用。"""
    try:
        with connection() as conn:
            terms = _rows(conn.execute(
                f"SELECT term, relevance, topic FROM rule_terms WHERE 1=1{_sw()} ORDER BY length(term) DESC").fetchall())
        set_user_terms(terms)
    except Exception:
        # 表还没建（首次启动）时不该拖垮分级，退回只用内置规则。
        set_user_terms([])


def correction_stats() -> dict[str, Any]:
    with connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM inbox_corrections WHERE 1=1{_sw()}").fetchone()["c"]
        by_direction = _rows(conn.execute(
            f"SELECT was_relevance, now_relevance, COUNT(*) AS c FROM inbox_corrections "
            f"WHERE 1=1{_sw()} GROUP BY was_relevance, now_relevance ORDER BY c DESC").fetchall())
    return {"total": int(total), "by_direction": by_direction,
            "suggestions": learned_terms(), "terms": list_rule_terms()}


def archive_inbox_item(item_id: int, payload: InboxArchive) -> dict[str, Any] | None:
    with connection() as conn:
        item = _inbox_item(conn, item_id)
        if not item:
            return None
        if item["inbox_status"] == "已归档":
            raise LedgerError("这条已经归档过了；如果需要重新处理，请先在对应公司档案里删除或修改归档记录。")
        if not _thesis_belongs_to_company(conn, item["company_id"], payload.thesis_id):
            raise LedgerError("关联的投资逻辑不属于这家公司。")
        # 把判成「程序性」的东西归档为证据 = 分级判错了。这就是纠错信号。
        _record_correction(conn, item, "高")

    occurred_at = datetime.fromisoformat(f"{item['event_date']}T00:00:00")
    detail = str(item["detail"] or "").strip()
    if payload.target == "evidence":
        created = create_evidence(
            item["company_id"],
            EvidenceCreate(
                thesis_id=payload.thesis_id,
                source_name=str(item["source"]),
                source_url=item["url"] or None,
                excerpt=payload.note.strip() or (f"{item['title']}｜{detail}" if detail else str(item["title"])),
                polarity=payload.polarity,
                occurred_at=occurred_at,
                verification=payload.verification,
            ),
        )
    else:
        created = create_event(
            item["company_id"],
            ResearchEventCreate(
                thesis_id=payload.thesis_id,
                category=str(item["category"]),
                title=payload.note.strip() or str(item["title"]),
                occurred_at=occurred_at,
                importance=payload.importance,
                verification=payload.verification,
            ),
        )
    if not created:
        raise LedgerError("归档失败：未找到对应公司。")

    with connection() as conn:
        conn.execute(
            "UPDATE company_calendar_events SET inbox_status = '已归档', archived_as = ?, archived_ref_id = ?, handled_at = ? WHERE id = ?",
            (payload.target, created["id"], now_iso(), item_id),
        )
        updated = _inbox_item(conn, item_id)
    return {"item": updated, "created_type": payload.target, "created_id": created["id"]}


def tidy_inbox(use_ai: bool = True, limit: int = 2000) -> dict[str, Any]:
    """把收件箱里已经明确的部分自动处理掉，只把拿不准的留给人。

    自动化的边界在这里：**分档是判断"是不是实质变化"，不是判断"对你意味着什么"**。
    - 高：一定是实质变化（分红、解禁、业绩、股权变动、重组、诉讼…）→ 自动归档为证据，
      来源与链接保留，极性留在中性，等你在证据档案里判断方向。
    - 低：走流程的文件（股东大会通知、法律意见书、更正补充…）→ 自动忽略，仍留在库里可查回。
    - 中：规则和模型都拿不准的 → 留在收件箱，等你手动处理。这一档才是真正需要人的部分。

    没有窗口限制：积压的旧公告一次清干净，否则清完当期又被更早的填满，等于没清。
    """

    # 每次整理都按当前口径重判一遍「中」，否则口径改了旧条目也出不来。
    # 单次调用有批次上限，循环到不再有进展为止——否则每点一次只处理一部分，看着像没生效。
    classified = classify_inbox(limit=limit, use_ai=use_ai, regrade=True)
    for _ in range(9):
        if not use_ai:
            break
        again = classify_inbox(limit=limit, use_ai=use_ai)
        if again["by_model"] == 0:
            break
        classified["scanned"] += again["scanned"]
        classified["by_model"] += again["by_model"]
        classified["counts"] = again["counts"]
    archived = archive_inbox_batch(relevance="高", days=0, limit=limit)
    ignored = ignore_by_relevance("低")
    with connection() as conn:
        remaining = int(
            conn.execute(f"SELECT COUNT(*) FROM company_calendar_events WHERE inbox_status = '待核验'{_swc()}").fetchone()[0]
        )
    return {
        "classified": classified["scanned"],
        "by_model": classified["by_model"],
        "archived": archived["archived"],
        "ignored": ignored,
        "remaining": remaining,
        "note": (
            f"分级 {classified['scanned']} 条（模型处理 {classified['by_model']} 条）；"
            f"实质变化 {archived['archived']} 条已归档为证据，来源与链接保留、极性留在中性；"
            f"程序性 {ignored} 条已忽略，仍可按状态查回。"
            f"收件箱里还剩 {remaining} 条——这些是规则和模型都拿不准的，需要你自己看。"
        ),
    }


def archive_inbox_batch(relevance: str = "高", days: int = 90, limit: int = 500) -> dict[str, Any]:
    """把某一档的公告批量归档为证据。

    公告本身是带来源的事实，归档只是把它从"还没看过"挪到"已经进档案、可追溯"。
    这一步是机械的，没必要一条条点。真正需要人判断的是它对你的投资逻辑是支持还是反证——
    所以极性一律留在"中性"，等你在复核时自己改，系统不代你判断方向。
    """

    if relevance not in RELEVANCE_LEVELS:
        raise LedgerError(f"相关度只能是 {'、'.join(RELEVANCE_LEVELS)} 之一。")
    cutoff = (date.today() - timedelta(days=days)).isoformat() if days > 0 else "0000-00-00"
    with connection() as conn:
        rows = _rows(
            conn.execute(
                """
                SELECT id FROM company_calendar_events
                WHERE inbox_status = '待核验' AND relevance = ? AND event_date >= ?{scope}
                ORDER BY event_date DESC, id DESC LIMIT ?
                """.format(scope=_swc()),
                (relevance, cutoff, limit),
            ).fetchall()
        )
    archived = 0
    failed = 0
    for row in rows:
        try:
            # **批量归档不许替人盖「已核验」。** 一次五百条，没有一条被人看过；
            # 而「已核验」是在说"这条我看过了、是真的"——复盘时你不会再去核它。
            result = archive_inbox_item(row["id"], InboxArchive(target=InboxTarget.evidence))
        except LedgerError:
            failed += 1
            continue
        if result:
            archived += 1
    note = (
        f"已把 {archived} 条{relevance}相关度的公告归档为证据，来源与链接都保留了下来。"
        "**都标成「待核验」**，极性一律中性——这条公告对你的判断是支持还是反证、"
        "内容是不是真的对得上，都由你在证据档案里逐条过。"
    )
    if failed:
        note += f" 另有 {failed} 条归档失败，仍留在收件箱。"
    return {"archived": archived, "failed": failed, "note": note}


def ignore_inbox_item(item_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        item = _inbox_item(conn, item_id)
        if not item:
            return None
        # 判成「高」的却被直接忽略 = 它其实不用看。同样是纠错信号。
        _record_correction(conn, item, "低")
        conn.execute(
            "UPDATE company_calendar_events SET inbox_status = '已忽略', handled_at = ? WHERE id = ?",
            (now_iso(), item_id),
        )
        return _inbox_item(conn, item_id)


def reopen_inbox_item(item_id: int) -> dict[str, Any] | None:
    """把误忽略的条目放回待核验；已归档的条目不回退，避免和已建立的证据/事件不一致。"""

    with connection() as conn:
        item = _inbox_item(conn, item_id)
        if not item:
            return None
        if item["inbox_status"] == "已归档":
            raise LedgerError("已归档的条目不能退回收件箱。")
        conn.execute(
            "UPDATE company_calendar_events SET inbox_status = '待核验', handled_at = NULL WHERE id = ?",
            (item_id,),
        )
        return _inbox_item(conn, item_id)


# --- 复核工作台与判断归因 -------------------------------------------------
# 复核回答的是同一个问题：当初的理由现在还成立吗。
# 系统只负责把当时的判断、之后的事实和市场变化并排摆出来，结论仍由用户写。

REVIEW_VERDICTS = {
    "supported": ("仍然成立", "intact"),
    "challenged": ("受到挑战", "challenged"),
    "broken": ("已被推翻", "broken"),
    "watching": ("维持观察", "watching"),
}
DEFAULT_REVIEW_INTERVAL_DAYS = 90


def _review_queue_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    return _rows(
        conn.execute(
            """
            SELECT t.id AS thesis_id, t.company_id, c.symbol, c.name AS company_name, t.claim,
                t.counter_condition, t.status, t.next_review_trigger, t.next_review_date,
                COALESCE(t.last_reviewed_at, t.created_at) AS since,
                t.last_reviewed_at, t.created_at,
                -- **从没复核过的，挂在它下面的反证全部算数。**
                --
                -- 原来这里写 `e.created_at >= t.created_at`，意思是"写下判断之后才出现的"。
                -- 听着合理，但一份证据是**什么时候变成反证的**跟它什么时候归档是两回事：
                -- 实测那几份文档 08-04 就归档了，而模型 08-06 才把它判成反证——
                -- 那一刻它才跟这条判断有关系，而按归档时间比会把它当成"早就知道了"。
                --
                -- 没有"何时变成反证"这个时间戳，就用一条更简单也更保守的规矩：
                -- **从没坐下来复核过，就是从没权衡过这些反证。**
                -- 复核过的仍然只看上次复核之后新增的。
                (SELECT COUNT(*) FROM evidences e WHERE e.thesis_id = t.id AND e.polarity = 'counter'
                    AND (t.last_reviewed_at IS NULL OR e.created_at > t.last_reviewed_at))
                    AS new_counter_evidence,
                -- **认错条件被踩到，是最该触发复核的那一条 —— 而它原来不在这张表里。**
                --
                -- 到期理由只看 evidences（人手归档的反证）和 research_events，
                -- counter_hits 一次都没出现。于是这条链走到最后一步就断了：
                -- 公告进来 → 撞上你写的条件 → 横幅提醒 → 你点「我处理过了」→ **然后没有然后**。
                -- 而这正是这个产品唯一不可替代的那件事。
                --
                -- **已确认的照样算数。** 确认清掉的是横幅（"我看见了"），
                -- 复核清掉的才是这件事本身（"我重新判过了"）。
                -- 确认要是能让它从队列里消失，那个按钮就成了一键免除义务。
                (SELECT COUNT(*) FROM counter_hits h WHERE h.thesis_id = t.id
                    AND (t.last_reviewed_at IS NULL OR h.created_at > t.last_reviewed_at))
                    AS new_counter_hits,
                (SELECT COUNT(*) FROM evidences e WHERE e.thesis_id = t.id AND e.polarity = 'support'
                    AND (CASE WHEN t.last_reviewed_at IS NULL THEN e.created_at >= t.created_at
                              ELSE e.created_at > t.last_reviewed_at END)) AS new_support_evidence,
                (SELECT COUNT(*) FROM research_events r WHERE r.thesis_id = t.id AND r.importance = 'high'
                    AND (CASE WHEN t.last_reviewed_at IS NULL THEN r.created_at >= t.created_at
                              ELSE r.created_at > t.last_reviewed_at END)) AS new_high_events,
                (SELECT MIN(review_due) FROM trades tr WHERE tr.thesis_id = t.id AND tr.review_due IS NOT NULL
                    AND tr.review_due <= ?
                    AND (t.last_reviewed_at IS NULL OR tr.review_due > date(t.last_reviewed_at))) AS trade_review_due,
                (SELECT COUNT(*) FROM thesis_reviews rv WHERE rv.thesis_id = t.id) AS review_count,
                (SELECT COUNT(*) FROM trades tr WHERE tr.company_id = t.company_id) AS company_trade_count
            FROM theses t JOIN companies c ON c.id = t.company_id
            WHERE 1=1{scope}
            ORDER BY t.updated_at DESC
            """.format(scope=_sw("c")),
            (today,),
        ).fetchall()
    )


def _review_rank(row: dict[str, Any]) -> int:
    """这条该排在队列的多前面。**只分档，不评分，不对用户显示。**

    ## 为什么光按日期排不行

    2026-08-16 实测，队列的排序键是 `(due_since, company_name)` —— 纯按日期。
    于是：

        1. 2025-06-01 格力电器 — 距建立已超过 90 天
        2. 2026-08-10 贵州茅台 — 你写下的认错条件被踩到了

    **一条"很久没看了"排在"你写下的卖出条件被触发了"前面。** 只要那条被踩到的
    判断写得比较近，它就会沉到底下 —— 而复核工作台是真正干活的那一页，
    卡片的先后就是他动手的先后。

    这个道理这个文件里已经写过一遍：`_review_reasons` 里那句
    「其余几条是"有新材料，你该看看"；这一条是"你自己写下的那个门槛被越过了"
    —— 性质不同，不该跟它们并列在后面」。**但它只管了一张卡片里几行字的次序，
    没管哪张卡片排在前面。**

    ## 次序跟决策看板同一套

    命中 > 反证 > 其余，跟 `_ACTION_WEIGHT` 是同一个概念的同一种排法。
    **不在这里另定一套**：两处各排一次迟早会不一致，而不一致的那次没人会发现
    （第二十一条就是这么来的）。
    """
    if row.get("new_counter_hits"):
        return 0
    if row.get("new_counter_evidence"):
        return 1
    return 2


def _review_reasons(row: dict[str, Any]) -> list[str]:
    today = date.today().isoformat()
    stale_before = (date.today() - timedelta(days=DEFAULT_REVIEW_INTERVAL_DAYS)).isoformat()
    reasons: list[str] = []
    # **没复核过和复核过，说法不一样。** 对一条从没复核过的判断说
    # 「上次复核后新增 2 条反证」是在说一件没发生过的事，
    # 而使用者会去找那次不存在的复核。
    seen = "上次复核后新增" if row.get("last_reviewed_at") else "有"
    tail = "" if row.get("last_reviewed_at") else "，而这条判断从写下起还没复核过"
    # **排在最前面。** 其余几条是"有新材料，你该看看"；这一条是
    # "你自己写下的那个门槛被越过了" —— 性质不同，不该跟它们并列在后面。
    #
    # 这句话原来写在这儿，而它下面的 append 排在两条日期理由之后 —— 也就是第三行。
    # 现在真的放在第一行了；卡片之间的先后见 _review_rank。
    if row.get("new_counter_hits"):
        times = row["new_counter_hits"]
        reasons.append(f"你写下的认错条件被踩到了{f' {times} 次' if times > 1 else ''}{tail}")
    if row.get("next_review_date") and row["next_review_date"] <= today:
        reasons.append(f"复核日期 {row['next_review_date']} 已到")
    if row.get("trade_review_due"):
        reasons.append(f"关联交易的复核日期 {row['trade_review_due']} 已到")
    if row.get("new_counter_evidence"):
        reasons.append(f"{seen} {row['new_counter_evidence']} 条反证{tail}")
    if row.get("new_high_events"):
        reasons.append(f"{seen} {row['new_high_events']} 条高重要度事件{tail}")
    if row["status"] in {"challenged", "broken"} and not row.get("last_reviewed_at"):
        reasons.append("逻辑已标为受挑战或已推翻，但还没有写过复核结论")
    if not reasons and row["since"][:10] <= stale_before:
        label = "上次复核" if row.get("last_reviewed_at") else "建立"
        reasons.append(f"距{label}已超过 {DEFAULT_REVIEW_INTERVAL_DAYS} 天")
    return reasons


def _earliest_review_due() -> "date | None":
    """还没到期的逻辑里，最早哪一天该复核。

    队列空的时候要能回答「那什么时候才该看」——只说「暂无」等于让人下次还得再来问一遍。
    """
    with connection() as conn:
        rows = _rows(conn.execute(
            f"SELECT next_review_date, last_reviewed_at, created_at FROM theses WHERE 1=1{_swc()}").fetchall())
    dues: list[str] = []
    for row in rows:
        if row.get("next_review_date"):
            dues.append(row["next_review_date"])
        else:
            since = (row.get("last_reviewed_at") or row["created_at"])[:10]
            dues.append((date.fromisoformat(since) + timedelta(days=DEFAULT_REVIEW_INTERVAL_DAYS)).isoformat())
    upcoming = sorted(d for d in dues if d > date.today().isoformat())
    return date.fromisoformat(upcoming[0]) if upcoming else None


def review_queue() -> list[dict[str, Any]]:
    with connection() as conn:
        rows = _review_queue_rows(conn)
    queue: list[dict[str, Any]] = []
    for row in rows:
        reasons = _review_reasons(row)
        if not reasons:
            continue
        row["reasons"] = reasons
        row["due_since"] = row.get("next_review_date") or row.get("trade_review_due") or row["since"][:10]
        row["has_position"] = bool(row.get("company_trade_count"))
        queue.append(row)
    # **先按性质，再按日期。** 光按日期排的话，一条"很久没看了"会压在
    # "你写下的卖出条件被触发了"上面 —— 见 _review_rank 里那段实测。
    # 同一档之内仍然是老的在前：同样紧急时，先看放得久的那条。
    queue.sort(key=lambda item: (_review_rank(item), item["due_since"], item["company_name"]))
    return queue


def all_theses() -> list[dict[str, Any]]:
    """你写过的全部投资逻辑，一页看完。

    ## 为什么必须有这一页

    首页那张卡片写着「投资逻辑 5 条」，点进去是**复核工作台**——
    而复核工作台按定义只放"有具体理由该重看的"，5 条都不到复核期时是空的。
    使用者看到的是：我有 5 条判断，点一下，什么都没有。

    更能说明问题的是复核工作台自己的空状态文案：「想逐条翻看全部逻辑，
    去公司档案里看」——**这句话本身就是在承认没有这样一页**，
    而判断恰恰是这个产品唯一的核心产出。

    ## 排序：该操心的在前

    受挑战 / 已推翻 排最前（它们要么在等你改，要么已经错了），
    其次是没写反证条件的（那种逻辑永远不会提醒你），
    最后按更新时间。**不按公司名排**——公司名跟"要不要看它"没有关系。
    """
    with connection() as conn:
        rows = _rows(conn.execute(
            f"""SELECT t.id, t.company_id, t.claim, t.counter_condition, t.status,
                       t.next_review_trigger, t.next_review_date, t.last_reviewed_at,
                       t.created_at, t.updated_at, t.method_name, t.price_at_write,
                       c.symbol, c.name AS company_name, c.industry,
                       (SELECT COUNT(*) FROM evidences e WHERE e.thesis_id = t.id
                          AND e.polarity = 'counter') AS counter_evidence,
                       (SELECT COUNT(*) FROM evidences e WHERE e.thesis_id = t.id
                          AND e.polarity = 'support') AS support_evidence,
                       (SELECT COUNT(*) FROM thesis_reviews rv WHERE rv.thesis_id = t.id) AS review_count
                FROM theses t JOIN companies c ON c.id = t.company_id
                WHERE 1=1{_sw('c')}
                ORDER BY t.updated_at DESC""").fetchall())
    weight = {"broken": 0, "challenged": 1, "watching": 2, "intact": 3}
    for row in rows:
        row["no_counter_condition"] = not str(row.get("counter_condition") or "").strip()
        # **「从没复核过」要摆出来。** 一条写下就再没回头看过的判断，
        # 跟一条刚复核过的在列表里长得一样——而它们的可信度完全不同。
        row["never_reviewed"] = not row.get("last_reviewed_at")
    rows.sort(key=lambda row: (weight.get(row["status"], 4),
                               0 if row["no_counter_condition"] else 1,
                               row["updated_at"]), reverse=False)
    return rows


def thesis_review_context(thesis_id: int) -> dict[str, Any] | None:
    """复核所需的全部并排材料：当初的判断、之后的事实、期间的价格与估值。"""

    with connection() as conn:
        thesis = _one_or_none(
            conn.execute(
                """
                SELECT t.*, c.symbol, c.name AS company_name, c.industry
                FROM theses t JOIN companies c ON c.id = t.company_id WHERE t.id = ?{scope}
                """.format(scope=_sw("c")),
                (thesis_id,),
            ).fetchone()
        )
        if not thesis:
            return None
        company_id = thesis["company_id"]
        since = thesis["last_reviewed_at"] or thesis["created_at"]

        revisions = _rows(
            conn.execute(
                """
                SELECT version, snapshot, changed_fields, change_note, created_at FROM record_revisions
                WHERE entity_type = 'thesis' AND entity_id = ? ORDER BY version ASC
                """,
                (thesis_id,),
            ).fetchall()
        )
        for revision in revisions:
            revision["snapshot"] = json.loads(revision["snapshot"])

        evidences = _rows(
            conn.execute(
                """
                SELECT id, company_id, thesis_id, source_name, source_url, excerpt, polarity, occurred_at,
                    verification, created_at
                FROM evidences WHERE thesis_id = ? ORDER BY occurred_at DESC, id DESC
                """,
                (thesis_id,),
            ).fetchall()
        )
        events = _rows(
            conn.execute(
                """
                SELECT id, company_id, thesis_id, category, title, occurred_at, importance, verification, created_at
                FROM research_events WHERE thesis_id = ? ORDER BY occurred_at DESC, id DESC
                """,
                (thesis_id,),
            ).fetchall()
        )
        reviewed = thesis["last_reviewed_at"] is not None
        for item in (*evidences, *events):
            item["since_last_review"] = item["created_at"] > since if reviewed else item["created_at"] >= since

        trades = _trade_records(
            conn.execute(f"{_TRADE_SELECT} WHERE t.thesis_id = ?{_sw(chr(112))} ORDER BY t.trade_date DESC", (thesis_id,)).fetchall()
        )
        company_trades = _trade_records(
            conn.execute(f"{_TRADE_SELECT} WHERE t.company_id = ?{_sw(chr(112))}", (company_id,)).fetchall()
        )
        open_positions, closed_positions = _build_positions(conn, company_trades) if company_trades else ([], [])
        position = (open_positions or closed_positions or [None])[0]

        history = _market_history_summary(conn, company_id)
        valuation = _valuation_summary(conn, company_id)
        reviews = _rows(
            conn.execute(
                "SELECT * FROM thesis_reviews WHERE thesis_id = ? ORDER BY created_at DESC", (thesis_id,)
            ).fetchall()
        )
        quote = _one_or_none(
            conn.execute(
                """
                SELECT price, change_percent, pe, pb, market_timestamp FROM market_snapshots
                WHERE symbol = ? ORDER BY refreshed_at DESC, id DESC LIMIT 1
                """,
                (_symbol_of(conn, company_id),),
            ).fetchone()
        )

    thesis["reasons"] = _review_reasons(
        {
            **thesis,
            "since": since,
            "new_counter_evidence": sum(1 for item in evidences if item["since_last_review"] and item["polarity"] == "counter"),
            "new_high_events": sum(1 for item in events if item["since_last_review"] and item["importance"] == "high"),
            "trade_review_due": min(
                (
                    trade["review_due"]
                    for trade in trades
                    if trade["review_due"]
                    and trade["review_due"] <= date.today().isoformat()
                    and (not thesis["last_reviewed_at"] or trade["review_due"] > thesis["last_reviewed_at"][:10])
                ),
                default=None,
            ),
        }
    )
    percentiles = []
    for metric in (valuation or {}).get("metrics", []):
        window = next((item for item in metric["windows"] if item["window_years"] == 5), None)
        percentiles.append(
            {
                "label": metric["label"],
                "current": metric["current"],
                "percentile": window["percentile"] if window else None,
                "sample_note": None if not window else (window["unavailable_reason"] or f"近 5 年 {window['sample_size']} 个样本"),
            }
        )
    return {
        "thesis": thesis,
        "since": since,
        "revisions": revisions,
        "evidences": evidences,
        "events": events,
        "trades": trades,
        "position": position,
        "price": {
            "latest": quote["price"] if quote else None,
            "change_percent": quote["change_percent"] if quote else None,
            "market_timestamp": quote["market_timestamp"] if quote else None,
            "price_20d_change": (history or {}).get("price_20d_change"),
            "ytd_change": (history or {}).get("ytd_change"),
            "one_year_change": (history or {}).get("one_year_change"),
            "latest_trade_date": (history or {}).get("latest_trade_date"),
        },
        "valuation": percentiles,
        "reviews": reviews,
    }


def create_thesis_review(thesis_id: int, payload: ThesisReviewCreate) -> dict[str, Any] | None:
    context = thesis_review_context(thesis_id)
    if not context:
        return None
    if payload.verdict not in REVIEW_VERDICTS:
        raise LedgerError("复核结论不在允许的取值范围内。")
    label, mapped_status = REVIEW_VERDICTS[payload.verdict]
    new_status = (payload.new_status.value if payload.new_status else mapped_status)
    thesis = context["thesis"]
    since = context["since"]
    timestamp = now_iso()
    price = context["price"]["latest"]
    pe_percentile = next((item["percentile"] for item in context["valuation"] if item["label"].startswith("市盈率")), None)
    position = context["position"] or {}

    with connection() as conn:
        conn.execute(
            """
            INSERT INTO thesis_reviews (
                thesis_id, company_id, verdict, note, previous_status, new_status, next_review_date,
                thesis_version, support_evidence, counter_evidence, event_count,
                price_at_review, pe_percentile_at_review, unrealized_at_review, realized_at_review, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thesis_id,
                thesis["company_id"],
                payload.verdict,
                payload.note.strip(),
                thesis["status"],
                new_status,
                payload.next_review_date.isoformat() if payload.next_review_date else None,
                len(context["revisions"]),
                sum(1 for item in context["evidences"] if item["since_last_review"] and item["polarity"] == "support"),
                sum(1 for item in context["evidences"] if item["since_last_review"] and item["polarity"] == "counter"),
                sum(1 for item in context["events"] if item["since_last_review"]),
                price,
                pe_percentile,
                position.get("unrealized_pnl"),
                position.get("realized_pnl"),
                timestamp,
            ),
        )
        conn.execute(
            "UPDATE theses SET last_reviewed_at = ?, next_review_date = ?, updated_at = ? WHERE id = ?",
            (timestamp, payload.next_review_date.isoformat() if payload.next_review_date else None, timestamp, thesis_id),
        )
        due_trades = (
            _rows(
                conn.execute(
                    "SELECT * FROM trades WHERE thesis_id = ? AND review_due IS NOT NULL AND review_due <= ?",
                    (thesis_id, date.today().isoformat()),
                ).fetchall()
            )
            if payload.next_review_date
            else []
        )
    # 这次复核已经覆盖了到期的关联交易，把它们的复核日期一并推进，并同样留下版本
    for trade in due_trades:
        update_trade(
            trade["id"],
            TradeUpdate(review_due=payload.next_review_date, change_note=f"随逻辑复核推进：{label}"),
        )

    # 结论作为逻辑的新版本追加，旧判断不被覆盖
    update_thesis(
        thesis_id,
        ThesisUpdate(
            status=new_status,
            next_review_trigger=payload.next_review_trigger or thesis["next_review_trigger"],
            change_note=f"复核：{label}｜{payload.note.strip()[:120]}",
        ),
    )
    return thesis_review_context(thesis_id)


def method_attribution() -> list[dict[str, Any]]:
    """按方法统计：用某某方法写下的逻辑，后来站住了几条。

    方法库不记这个的话，它永远只是一份读物。记了之后它才能回答那个真正的问题：
    **我更适合哪一套。** 没套用方法的单列一组「自由发挥」——那也是一种答案，
    而且往往是最该拿来对照的那一组。

    样本小的时候这些数字没有意义，所以把条数一起给出来，由页面提醒不要过度解读。
    """
    with connection() as conn:
        rows = _rows(conn.execute(
            """
            SELECT COALESCE(t.method_name, '自由发挥') AS method,
                   t.status, COUNT(*) AS c
            FROM theses t WHERE 1=1{scope} GROUP BY method, t.status
            """.format(scope=_swc("t.company_id"))
        ).fetchall())
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = buckets.setdefault(row["method"], {
            "method": row["method"], "total": 0,
            "intact": 0, "watching": 0, "challenged": 0, "broken": 0,
        })
        bucket["total"] += row["c"]
        if row["status"] in bucket:
            bucket[row["status"]] += row["c"]
    out = []
    for bucket in buckets.values():
        settled = bucket["intact"] + bucket["broken"]
        out.append({
            **bucket,
            # 只在「已经有结论」的那些里算命中率：还在观察的既不算对也不算错，
            # 把它们算进分母会让所有方法看起来都很差。
            "settled": settled,
            "hit_rate": round(bucket["intact"] / settled * 100, 1) if settled else None,
            "note": "样本太少，先不要据此下结论。" if bucket["total"] < 5 else "",
        })
    out.sort(key=lambda item: (-item["total"], item["method"]))
    return out


def review_attribution(quarters: int = 4) -> dict[str, Any]:
    """按季度归因：每一季有哪些逻辑被支持、被挑战、被推翻，以及当时对应的盈亏。"""

    with connection() as conn:
        rows = _rows(
            conn.execute(
                """
                SELECT rv.*, t.claim, c.symbol, c.name AS company_name
                FROM thesis_reviews rv
                JOIN theses t ON t.id = rv.thesis_id
                JOIN companies c ON c.id = rv.company_id
                WHERE 1=1{scope}
                ORDER BY rv.created_at DESC
                """.format(scope=_sw("c"))
            ).fetchall()
        )
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        moment = datetime.fromisoformat(row["created_at"])
        period = f"{moment.year}Q{(moment.month - 1) // 3 + 1}"
        bucket = buckets.setdefault(
            period,
            {"period": period, "supported": 0, "challenged": 0, "broken": 0, "watching": 0, "reviews": [], "realized": 0.0, "unrealized": 0.0},
        )
        bucket[row["verdict"]] = bucket.get(row["verdict"], 0) + 1
        bucket["realized"] += float(row["realized_at_review"] or 0)
        bucket["unrealized"] += float(row["unrealized_at_review"] or 0)
        row["verdict_label"] = REVIEW_VERDICTS.get(row["verdict"], (row["verdict"], ""))[0]
        bucket["reviews"].append(row)
    ordered = sorted(buckets.values(), key=lambda item: item["period"], reverse=True)[:quarters]
    for bucket in ordered:
        bucket["realized"] = round(bucket["realized"], 2)
        bucket["unrealized"] = round(bucket["unrealized"], 2)
        bucket["total"] = bucket["supported"] + bucket["challenged"] + bucket["broken"] + bucket["watching"]
    return {"quarters": ordered, "total_reviews": len(rows), "by_method": method_attribution()}


# --- 研究池管理 -----------------------------------------------------------

def watchlist_groups() -> list[dict[str, Any]]:
    with connection() as conn:
        return _rows(
            conn.execute(
                """
                SELECT watch_group AS name,
                    SUM(CASE WHEN is_watched = 1 THEN 1 ELSE 0 END) AS watched,
                    SUM(CASE WHEN is_watched = 0 THEN 1 ELSE 0 END) AS archived
                FROM companies WHERE 1=1{scope} GROUP BY watch_group ORDER BY watched DESC, name
                """.format(scope=_sw())
            ).fetchall()
        )


def export_watchlist() -> list[dict[str, Any]]:
    """导出研究池：只含用户可再导入的字段，行情等来源数据不写进去。"""

    with connection() as conn:
        return _rows(
            conn.execute(
                """
                SELECT symbol, name, exchange, industry, watch_group, is_watched, description,
                    valuation_percentile, roe_trend, created_at
                FROM companies WHERE 1=1{scope} ORDER BY is_watched DESC, watch_group, symbol
                """.format(scope=_sw())
            ).fetchall()
        )


def import_watchlist(payload: WatchlistImport) -> dict[str, Any]:
    """按代码批量加入研究池，或直接回灌导出的文件。

    无论哪种方式，公司名称与行情都必须由行情源返回；导出文件里只有用户写的
    分组、研究缘起和是否关注会被回灌，已有的逻辑、证据、事件不会被触碰。
    """

    entries: list[WatchlistImportRow] = list(payload.rows)
    entries.extend(WatchlistImportRow(symbol=item) for item in payload.symbols)
    results: list[dict[str, Any]] = []
    created = skipped = updated = failed = 0
    with connection() as conn:
        existing = {row["symbol"]: dict(row) for row in conn.execute(f"SELECT id, symbol, industry FROM companies WHERE 1=1{_sw()}").fetchall()}

    for entry in entries:
        symbol = entry.symbol.strip()
        if not symbol:
            continue
        try:
            canonical = normalize_cn_symbol(symbol)
        except (MarketSymbolError, ValueError) as exc:
            failed += 1
            results.append({"symbol": symbol, "status": "失败", "detail": str(exc) or "不是有效的 A 股代码"})
            continue

        group = (entry.watch_group or payload.watch_group).strip() or "观察池"
        description = entry.description if entry.description is not None else payload.description

        if canonical in existing:
            if not payload.restore_existing:
                skipped += 1
                results.append({"symbol": canonical, "status": "已存在", "detail": "研究池里已经有这家公司"})
                continue
            company_id = existing[canonical]["id"]
            fields: dict[str, Any] = {"watch_group": group}
            if description:
                fields["description"] = description
            if entry.is_watched is not None:
                fields["is_watched"] = 1 if entry.is_watched else 0
            if entry.industry and existing[canonical]["industry"] in {"待补充", ""}:
                fields["industry"] = entry.industry
            assignments = ", ".join(f"{key} = ?" for key in fields)
            with connection() as conn:
                conn.execute(
                    f"UPDATE companies SET {assignments}, updated_at = ? WHERE id = ?",
                    [*fields.values(), now_iso(), company_id],
                )
            updated += 1
            results.append({"symbol": canonical, "status": "已恢复", "detail": f"分组、研究缘起等字段已按文件恢复（{group}）"})
            continue

        try:
            company = create_company_from_quote(
                CompanyFromQuoteInput(symbol=canonical, watch_group=group, description=description)
            )
            if entry.is_watched is False:
                with connection() as conn:
                    conn.execute("UPDATE companies SET is_watched = 0 WHERE id = ?", (company["id"],))
            existing[canonical] = {"id": company["id"], "symbol": canonical, "industry": company["industry"]}
            created += 1
            results.append({"symbol": canonical, "status": "已建档", "detail": company["name"]})
        except (MarketDataError, *integrity_errors()) as exc:
            failed += 1
            results.append({"symbol": canonical, "status": "失败", "detail": str(exc)})
    return {"created": created, "skipped": skipped, "updated": updated, "failed": failed, "results": results}


# --- 行业与同业对照 -------------------------------------------------------
# 标签只列研究池覆盖到的行业，避免把一百多个行业塞进页面；比较基准则来自
# 全 A 底座里的申万二级同行。两层必须分开，否则用户会把自己的关注池误认成市场样本。

def _valuation_snapshot(conn: sqlite3.Connection, company_id: int) -> dict[str, Any]:
    rows = _rows(
        conn.execute(
            """
            SELECT metric, point_date, value FROM valuation_points
            WHERE symbol = ? AND source <> 'StockSDK' ORDER BY metric, point_date
            """,
            (_symbol_of(conn, company_id),),
        ).fetchall()
    )
    snapshot: dict[str, Any] = {}
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_metric.setdefault(row["metric"], []).append(row)
    for metric in ("pe_ttm", "pb"):
        points = by_metric.get(metric, [])
        if not points:
            snapshot[metric] = {"current": None, "percentile": None, "note": "未同步历史估值"}
            continue
        window = _window_percentile(points, 5, points[-1]["point_date"])
        snapshot[metric] = {
            "current": round(float(points[-1]["value"]), 2),
            "percentile": window["percentile"],
            "note": window["unavailable_reason"] or f"近 5 年 {window['sample_size']} 个样本",
        }
    return snapshot


def _financial_snapshot(conn: sqlite3.Connection, company_id: int) -> dict[str, Any]:
    rows = _rows(
        conn.execute(
            """
            SELECT report_date, revenue, net_profit, operating_cash_flow, operating_cost, capex,
                receivables, inventory, interest_bearing_debt, total_assets, total_liabilities,
                equity, debt_ratio, roe_estimate
            FROM financial_periods WHERE symbol = ? ORDER BY report_date
            """,
            (_symbol_of(conn, company_id),),
        ).fetchall()
    )
    if not rows:
        return {"report_date": None, "note": "未同步财务报告"}
    _attach_financial_metrics(rows)
    latest = rows[-1]
    annuals = [row for row in rows if row["report_date"].endswith("-12-31")]
    latest_roe = next((row["roe_estimate"] for row in reversed(rows) if row["roe_estimate"] is not None), None)
    revenue_growth = None
    if len(annuals) >= 2 and annuals[-2]["revenue"] not in {None, 0} and annuals[-1]["revenue"] is not None:
        revenue_growth = round((annuals[-1]["revenue"] / annuals[-2]["revenue"] - 1) * 100, 1)
    return {
        "report_date": latest["report_date"],
        "gross_margin": latest.get("gross_margin"),
        "net_margin": latest.get("net_margin"),
        "cash_conversion": latest.get("cash_conversion"),
        "debt_ratio": latest.get("debt_ratio"),
        "interest_debt_ratio": latest.get("interest_debt_ratio"),
        "roe_estimate": latest_roe,
        "roe_report_date": next((row["report_date"] for row in reversed(rows) if row["roe_estimate"] is not None), None),
        "revenue_growth": revenue_growth,
        "revenue_growth_basis": f"{annuals[-2]['report_date']} → {annuals[-1]['report_date']}" if revenue_growth is not None else None,
        "note": None,
    }


def list_industries() -> list[dict[str, Any]]:
    """列研究池覆盖到的申万二级行业。

    页面仍只列用户研究池里真正出现过的行业，避免把 128 个全市场行业全塞进标签栏；
    但行业名称改用全市场底座的申万二级分类，这样点进去后能和全 A 基准严格对上。
    底座尚未给出分类的公司才回退到档案里的证监会门类。
    """
    with connection() as conn:
        return _rows(
            conn.execute(
                """
                SELECT COALESCE(NULLIF(u.industry, ''), NULLIF(c.industry, ''), '待补充') AS name,
                    COUNT(*) AS company_count,
                    SUM(CASE WHEN c.is_watched = 1 THEN 1 ELSE 0 END) AS watched_count,
                    GROUP_CONCAT(c.name, '、' ORDER BY c.name) AS companies
                FROM companies c
                LEFT JOIN market_universe u ON u.symbol = c.symbol
                WHERE 1=1{scope}
                GROUP BY COALESCE(NULLIF(u.industry, ''), NULLIF(c.industry, ''), '待补充')
                ORDER BY company_count DESC, name
                """.format(scope=_sw("c"))
            ).fetchall()
        )


def industry_comparison(industry: str | None = None) -> dict[str, Any]:
    with connection() as conn:
        sql = """
            SELECT c.id, c.symbol, c.name,
                COALESCE(NULLIF(u.industry, ''), c.industry) AS industry,
                CASE WHEN u.industry IS NOT NULL AND u.industry <> ''
                    THEN '全市场底座（申万二级）' ELSE c.industry_source END AS industry_source,
                u.annual_roe AS universe_annual_roe,
                u.annual_gross_margin AS universe_annual_gross_margin,
                u.annual_report_date AS universe_annual_report_date,
                c.is_watched,
                COALESCE(ms.price, u.price) AS latest_price,
                COALESCE(ms.change_percent, u.change_percent) AS change_percent,
                ms.market_timestamp
            FROM companies c
            LEFT JOIN market_universe u ON u.symbol = c.symbol
            LEFT JOIN market_snapshots ms ON ms.id = (
                SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
                ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1
            )
        """
        params: list[Any] = []
        sql += f" WHERE 1=1{_sw('c')}"
        if industry:
            sql += " AND COALESCE(NULLIF(u.industry, ''), c.industry) = ?"
            params.append(industry)
        sql += " ORDER BY c.name"
        companies = _rows(conn.execute(sql, params).fetchall())
        for company in companies:
            annual_roe = company.pop("universe_annual_roe", None)
            annual_gross_margin = company.pop("universe_annual_gross_margin", None)
            annual_report_date = company.pop("universe_annual_report_date", None)
            if annual_report_date and len(str(annual_report_date)) == 8 and str(annual_report_date).isdigit():
                compact = str(annual_report_date)
                annual_report_date = f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
            company["is_watched"] = bool(company["is_watched"])
            company["valuation"] = _valuation_snapshot(conn, company["id"])
            company["financials"] = _financial_snapshot(conn, company["id"])
            # 行业基准使用年报 ROE / 毛利率，公司也必须保持同一口径。
            # 否则把一季报 ROE 与年报 ROE 摆在一条标尺上，位置会被系统性画低。
            if annual_roe is not None:
                company["financials"]["roe_estimate"] = round(float(annual_roe), 2)
                company["financials"]["roe_report_date"] = annual_report_date or company["financials"].get("roe_report_date")
            if annual_gross_margin is not None:
                company["financials"]["gross_margin"] = round(float(annual_gross_margin), 2)

        benchmark_sql = """
            SELECT price, pe_ttm, pb,
                COALESCE(annual_roe, roe) AS roe_estimate,
                COALESCE(annual_gross_margin, gross_margin) AS gross_margin,
                CASE WHEN revenue IS NOT NULL AND revenue <> 0 AND net_profit IS NOT NULL
                    THEN net_profit / revenue * 100 ELSE NULL END AS net_margin,
                CASE WHEN eps IS NOT NULL AND eps <> 0 AND ocf_per_share IS NOT NULL
                    THEN ocf_per_share / eps * 100 ELSE NULL END AS cash_conversion,
                revenue_growth, report_date, fundamental_as_of, fundamental_source
            FROM market_universe
        """
        benchmark_params: list[Any] = []
        if industry:
            benchmark_sql += " WHERE industry = ?"
            benchmark_params.append(industry)
        benchmark_rows = _rows(conn.execute(benchmark_sql, benchmark_params).fetchall())

    # 基准统计来自全市场底座，而不是用户恰好建档的几家公司。只按已有值计算，
    # 估值倍数排除非正值；平均值与中位数都保留各自的有效样本数。
    metric_keys = (
        "pe_ttm", "pb", "roe_estimate", "gross_margin", "net_margin",
        "cash_conversion", "revenue_growth",
    )

    def metric_values(key: str) -> list[float]:
        values = [float(row[key]) for row in benchmark_rows if row.get(key) is not None]
        if key in {"pe_ttm", "pb"}:
            values = [value for value in values if value > 0]
        return values

    def aggregate_row(reducer: Callable[[list[float]], float]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "latest_price": None,
            "pe_ttm_percentile": None,
            "pb_percentile": None,
            "debt_ratio": None,
        }
        coverage = {
            "latest_price": 0,
            "pe_ttm_percentile": 0,
            "pb_percentile": 0,
            "debt_ratio": 0,
        }
        for key in metric_keys:
            values = metric_values(key)
            result[key] = round(reducer(values), 2) if values else None
            coverage[key] = len(values)
        result["coverage"] = coverage
        result["sample_count"] = len(benchmark_rows)
        return result

    def percentile(values: list[float], ratio: float) -> float:
        """线性插值得到小样本也稳定的四分位值。"""
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * ratio
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    average = aggregate_row(lambda values: sum(values) / len(values))
    lower_quartile = aggregate_row(lambda values: percentile(values, 0.25))
    median = aggregate_row(statistics.median)
    upper_quartile = aggregate_row(lambda values: percentile(values, 0.75))
    benchmark_dates = sorted(
        str(row.get("fundamental_as_of") or row.get("report_date"))[:10]
        for row in benchmark_rows if row.get("fundamental_as_of") or row.get("report_date")
    )
    benchmark_sources = sorted({str(row["fundamental_source"]) for row in benchmark_rows if row.get("fundamental_source")})
    return {
        "industry": industry,
        "benchmark_company_count": len(benchmark_rows),
        "benchmark_source": " / ".join(benchmark_sources) or "全市场底座",
        "benchmark_as_of": benchmark_dates[-1] if benchmark_dates else None,
        "company_count": len(companies),
        "coverage": "行业平均与中位来自全 A 底座；下方公司明细只列研究池里已经建档的公司",
        "industry_basis": "行业口径为申万二级分类；每项只按有值样本计算，PE 与 PB 排除非正值",
        "companies": companies,
        "average": average,
        "lower_quartile": lower_quartile,
        "median": median,
        "upper_quartile": upper_quartile,
    }


# --- 全 A 与主要指数的数据底座 ---------------------------------------------
# 覆盖范围：全 A 股票 + 沪深300/中证500/上证50/中证1000。
# 这一层只存事实与来源，任何筛选、排序、评分都在上层做，并且必须带上数据截止日。

def _derive_universe_valuation(conn: sqlite3.Connection) -> int:
    """快照源被挡住时，从财务底座推算市值、PB 与 PE。

    口径：总股本 = 归母净利润 / 基本每股收益（同一报告期，期间因素相消）；
          总市值 = 现价 × 总股本；PB = 现价 / 每股净资产；PE = 总市值 / 最近年报归母净利润。
    PE 分母用年报而不是把当期利润年化——年化对有季节性的生意会系统性失真。
    只填空缺，不覆盖快照源给的值。
    """

    # 三个字段各自独立补：市值填过了不代表 PE 也填过了，
    # 绑在同一个条件上会让后补的年报净利润永远用不上。
    filled = conn.execute(
        """
        UPDATE market_universe SET
            total_shares = net_profit / eps,
            total_market_cap = price * (net_profit / eps),
            valuation_basis = '由财务底座推算：总股本＝归母净利润／每股收益'
        WHERE total_market_cap IS NULL AND price IS NOT NULL AND eps IS NOT NULL AND eps > 0 AND net_profit IS NOT NULL
        """
    ).rowcount
    filled += conn.execute(
        """
        UPDATE market_universe SET pb = price / bps
        WHERE pb IS NULL AND price IS NOT NULL AND bps IS NOT NULL AND bps > 0
        """
    ).rowcount
    filled += conn.execute(
        """
        UPDATE market_universe SET
            pe_ttm = total_market_cap / annual_net_profit,
            valuation_basis = COALESCE(valuation_basis, '') || '；市盈率分母为 ' || COALESCE(annual_report_date, '最近年报') || ' 归母净利润'
        WHERE pe_ttm IS NULL AND total_market_cap IS NOT NULL
          AND annual_net_profit IS NOT NULL AND annual_net_profit > 0
        """
    ).rowcount
    return filled


def rederive_universe_valuation() -> dict[str, Any]:
    """不联网，只用库里已有的财务数据重算一遍估值字段。

    换了推算口径、或者同步时快照源恰好可用过一次之后，用这个立刻补齐，而不用等下一次全量同步。
    """

    notes: list[str] = []
    with connection() as conn:
        missing_annual = int(
            conn.execute("SELECT COUNT(*) FROM market_universe WHERE annual_net_profit IS NULL").fetchone()[0]
        )
    # PE 的分母是最近年报净利润；缺了就先去取，这一份数据走的是业绩报表接口，
    # 和被挡住的行情快照不是同一个来源，所以快照失败不代表这一步也会失败。
    if missing_annual:
        period = latest_annual_period()
        try:
            payload = fetch_market_fundamentals(period)
        except UniverseDataError as exc:
            notes.append(f"年报业绩报表取不到（{exc}），市盈率暂时无法推算。")
        else:
            timestamp = now_iso()
            with connection() as conn:
                for row in payload["rows"]:
                    if row.get("net_profit") is None:
                        continue
                    conn.execute(
                        "UPDATE market_universe SET annual_net_profit = ?, annual_report_date = ?, updated_at = ? WHERE symbol = ?",
                        (row["net_profit"], period, timestamp, row["symbol"]),
                    )
            notes.append(f"补齐了 {period} 年报净利润，用作市盈率的分母。")

    with connection() as conn:
        derived = _derive_universe_valuation(conn)
        coverage = dict(
            conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(pe_ttm) AS pe, COUNT(pb) AS pb, COUNT(total_market_cap) AS cap
                FROM market_universe
                """
            ).fetchone()
        )
    return {
        "derived": derived,
        "total": coverage["total"],
        "pe_coverage": coverage["pe"],
        "pb_coverage": coverage["pb"],
        "market_cap_coverage": coverage["cap"],
        "note": (
            f"重算了 {derived} 只。当前覆盖：总市值 {coverage['cap']}/{coverage['total']}、"
            f"市净率 {coverage['pb']}/{coverage['total']}、市盈率 {coverage['pe']}/{coverage['total']}。"
            "亏损股（每股收益 ≤ 0）推算不出总股本，留空是对的。"
            + ("　" + "　".join(notes) if notes else "")
        ),
    }


# 底座里有多大比例的股票已经有申万二级分类时，就不再重跑这个作业。
#
# **行业成分一年调整一两次，而这个作业要发 131 次请求、跑三分钟。**
# 跟着底座天天跑纯属浪费。用覆盖率当闸门而不是用时间戳，是因为它自我调节：
# 新股上市会让覆盖率慢慢掉下来，掉破线就自动补一次，不需要额外存一列。
#
# 门槛定在 0.90 是实测出来的：一次完整同步之后覆盖率是 5193/5538 = **93.8%**，
# 那 345 只（退市整理期、B 股、新上市还没进指数）本来就不在申万成分里。
# 门槛设成 0.95 的话这个作业每天都会重跑一遍——我第一版就是这么写的，
# 而它看起来完全正常：跑了三分钟、更新了 5193 只，没有任何地方显示"这次是白跑的"。
SW_COVERAGE_ENOUGH = 0.90


def refresh_sw_industries(force: bool = False) -> dict[str, Any]:
    """把申万一级／二级行业分类写进底座。

    **这两列建了之后一直没有写入方**（实测全库 5538 行、0 行有值），
    行业特有指标因此对 12 家档案公司一条都没算出来过——分类三级回退
    实际只剩证监会门类，而别名表是照申万写的，对不上。见 providers/akshare_sw。
    """
    from .providers.akshare_sw import fetch_sw_industry_map

    with connection() as conn:
        counts = _one_or_none(conn.execute(
            "SELECT COUNT(*) AS total, COUNT(NULLIF(sw_level2, ?)) AS have "
            "FROM market_universe", ("",)).fetchone()) or {}
    total = int(counts.get("total") or 0)
    have = int(counts.get("have") or 0)
    if not force and total and have / total >= SW_COVERAGE_ENOUGH:
        return {"updated": 0, "matched": have, "failed": [], "skipped": True,
                "note": f"底座里 {have}/{total} 只已有申万分类，这次跳过——"
                        f"行业成分一年才调整一两次，而这个作业要发 131 次请求。"}

    payload = fetch_sw_industry_map()
    mapping = payload["mapping"]
    if not mapping:
        return {"updated": 0, "matched": 0, "skipped": False,
                "note": "申万分类一条都没取到，底座没有改动。",
                "failed": payload["failed"]}

    updated = 0
    with connection() as conn:
        for symbol, tiers in mapping.items():
            cursor = conn.execute(
                "UPDATE market_universe SET sw_level1 = ?, sw_level2 = ? WHERE symbol = ?",
                (tiers["sw_level1"], tiers["sw_level2"], symbol))
            updated += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
    failed = payload["failed"]
    note = (f"从 {payload['industries']} 个申万二级行业里取到 {len(mapping)} 只股票的分类，"
            f"底座里对上 {updated} 只。")
    if failed:
        # **取不到的要点名。** 不点名的话，某个行业长期取不到会表现成
        # "这几家公司没有专属指标"，跟"这个行业本来就没定义指标"一模一样。
        note += f"　有 {len(failed)} 个行业没取到：{'、'.join(failed[:6])}。"
    return {"updated": updated, "matched": len(mapping), "failed": failed,
            "skipped": False, "note": note}


def refresh_market_universe(report_date: str | None = None) -> dict[str, Any]:
    """全量刷新市场底座：价格与估值、按报告期的财务、指数成分。"""

    started = now_iso()
    period = report_date or latest_report_period()
    price_payload: dict[str, Any] = {"rows": [], "source": None, "degraded": False, "missing_fields": []}
    fundamental_payload: dict[str, Any] = {"rows": [], "source": None, "report_date": period}
    index_payload: dict[str, Any] = {"members": [], "source": None, "missing_indexes": []}
    notes: list[str] = []

    try:
        price_payload = fetch_market_spot()
    except UniverseDataError as exc:
        notes.append(f"行情快照失败：{exc}")
    try:
        fundamental_payload = fetch_market_fundamentals(period)
    except UniverseDataError as exc:
        notes.append(f"业绩报表失败：{exc}")
    # 年报净利润只用来做 PE 的分母；取不到就退回不算 PE，不拿当期利润年化凑数
    annual_period = latest_annual_period()
    annual_profit: dict[str, float] = {}
    # **比率也要留年报口径的。**
    #
    # 底座里的 roe/gross_margin 来自「最新报告期」，也就是一季报——那是**单季**的数字，
    # 中位数 1.03%。而策略里写的 `ROE ≥ 15%` 是年度概念。拿单季 ROE 去比年度门槛，
    # 全市场只有 124 只能过，「质量稳健型」因此长期几乎筛不出东西——
    # 而这看上去像是「条件严格」，不像是「口径错了」，所以一直没人发现。
    # 换成年报口径后同一条件命中 1790 只。
    annual_ratios: dict[str, dict[str, float | None]] = {}

    def _absorb_annual(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            if row.get("net_profit") is not None:
                annual_profit[row["symbol"]] = row["net_profit"]
            annual_ratios[row["symbol"]] = {"roe": row.get("roe"), "gross_margin": row.get("gross_margin")}

    if annual_period != period:
        try:
            _absorb_annual(fetch_market_fundamentals(annual_period)["rows"])
        except UniverseDataError as exc:
            notes.append(f"年报业绩报表失败，PE 与年度比率将无法推算：{exc}")
    else:
        _absorb_annual(fundamental_payload["rows"])
    try:
        index_payload = fetch_index_members()
    except UniverseDataError as exc:
        notes.append(f"指数成分失败：{exc}")

    # 股息率：走东财 datacenter（分红送配），与被墙的 push2 行情不是一条路。
    # 「东财拿不到数据」这个笼统结论把股息现金流策略挡了很久，实际上一个函数就取到了。
    dividends: dict[str, dict[str, Any]] = {}
    dividend_period = latest_annual_period()
    try:
        dividend_payload = fetch_market_dividends(dividend_period)
        dividends = {row["symbol"]: row for row in dividend_payload["rows"]}
    except UniverseDataError as exc:
        notes.append(f"分红送配失败，股息率将为空：{exc}")

    if price_payload["degraded"]:
        notes.append(f"行情来源降级为{price_payload['source']}，缺少：{('、').join(price_payload['missing_fields'])}")
    if index_payload.get("missing_indexes"):
        notes.append(f"未取到的指数：{('、').join(index_payload['missing_indexes'])}")

    timestamp = now_iso()
    fundamentals = {row["symbol"]: row for row in fundamental_payload["rows"]}
    with connection() as conn:
        for row in price_payload["rows"]:
            symbol = row["symbol"]
            finance = fundamentals.get(symbol, {})
            conn.execute(
                """
                INSERT INTO market_universe (
                    symbol, name, exchange, board, industry, price, change_percent, pe_ttm, pb,
                    total_market_cap, float_market_cap, turnover_rate, ytd_change, change_60d, report_date, revenue,
                    revenue_growth, net_profit, net_profit_growth, roe, gross_margin, eps, bps,
                    ocf_per_share, annual_net_profit, annual_report_date,
                    annual_roe, annual_gross_margin,
                    dividend_yield, dividend_per_10, dividend_period,
                    price_source, price_as_of, fundamental_source, fundamental_as_of, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name, exchange = excluded.exchange, board = excluded.board,
                    industry = COALESCE(excluded.industry, market_universe.industry),
                    price = excluded.price, change_percent = excluded.change_percent,
                    pe_ttm = excluded.pe_ttm, pb = excluded.pb,
                    total_market_cap = excluded.total_market_cap,
                    -- **降级的源不该有权清空满源填好的字段。**
                    --
                    -- 快照降级到新浪之后，这四列拿回来的一律是 NULL（provider 里
                    -- 显式写着 turnover_rate: None）。原来这里直接赋值，于是
                    -- 「全市场底座」每天把趋势作业刚填好的换手率冲成空——
                    -- 现在没爆只是因为调度顺序凑巧（底座 → 情绪面 → 趋势面，
                    -- 趋势那步又补了回来）；手动重跑一次底座就没了，要等 24 小时才回来。
                    --
                    -- 同一条语句里的财务字段本来就全是 COALESCE，行情字段没有——
                    -- 这个不一致本身就是 bug。
                    --
                    -- pe_ttm / pb / total_market_cap 刻意不动：它们有 _derive_universe_valuation
                    -- 那条恢复路径（`WHERE total_market_cap IS NULL`），包上 COALESCE
                    -- 反而会让推算不再触发，留下一个来路不明的旧值。
                    float_market_cap = COALESCE(excluded.float_market_cap, market_universe.float_market_cap),
                    turnover_rate = COALESCE(excluded.turnover_rate, market_universe.turnover_rate),
                    ytd_change = COALESCE(excluded.ytd_change, market_universe.ytd_change),
                    change_60d = COALESCE(excluded.change_60d, market_universe.change_60d),
                    report_date = COALESCE(excluded.report_date, market_universe.report_date),
                    revenue = COALESCE(excluded.revenue, market_universe.revenue),
                    revenue_growth = COALESCE(excluded.revenue_growth, market_universe.revenue_growth),
                    net_profit = COALESCE(excluded.net_profit, market_universe.net_profit),
                    net_profit_growth = COALESCE(excluded.net_profit_growth, market_universe.net_profit_growth),
                    roe = COALESCE(excluded.roe, market_universe.roe),
                    gross_margin = COALESCE(excluded.gross_margin, market_universe.gross_margin),
                    eps = COALESCE(excluded.eps, market_universe.eps),
                    bps = COALESCE(excluded.bps, market_universe.bps),
                    ocf_per_share = COALESCE(excluded.ocf_per_share, market_universe.ocf_per_share),
                    annual_net_profit = COALESCE(excluded.annual_net_profit, market_universe.annual_net_profit),
                    annual_roe = COALESCE(excluded.annual_roe, market_universe.annual_roe),
                    annual_gross_margin = COALESCE(excluded.annual_gross_margin, market_universe.annual_gross_margin),
                    annual_report_date = COALESCE(excluded.annual_report_date, market_universe.annual_report_date),
                    dividend_yield = COALESCE(excluded.dividend_yield, market_universe.dividend_yield),
                    dividend_per_10 = COALESCE(excluded.dividend_per_10, market_universe.dividend_per_10),
                    dividend_period = COALESCE(excluded.dividend_period, market_universe.dividend_period),
                    price_source = excluded.price_source, price_as_of = excluded.price_as_of,
                    fundamental_source = COALESCE(excluded.fundamental_source, market_universe.fundamental_source),
                    fundamental_as_of = COALESCE(excluded.fundamental_as_of, market_universe.fundamental_as_of),
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    row["name"],
                    exchange_of(symbol),
                    board_of(symbol),
                    finance.get("industry"),
                    row.get("price"),
                    row.get("change_percent"),
                    row.get("pe_ttm"),
                    row.get("pb"),
                    row.get("total_market_cap"),
                    row.get("float_market_cap"),
                    row.get("turnover_rate"),
                    row.get("ytd_change"),
                    row.get("change_60d"),
                    period if finance else None,
                    finance.get("revenue"),
                    finance.get("revenue_growth"),
                    finance.get("net_profit"),
                    finance.get("net_profit_growth"),
                    finance.get("roe"),
                    finance.get("gross_margin"),
                    finance.get("eps"),
                    finance.get("bps"),
                    finance.get("ocf_per_share"),
                    annual_profit.get(symbol),
                    annual_period if annual_profit.get(symbol) is not None else None,
                    (annual_ratios.get(symbol) or {}).get("roe"),
                    (annual_ratios.get(symbol) or {}).get("gross_margin"),
                    (dividends.get(symbol) or {}).get("dividend_yield"),
                    (dividends.get(symbol) or {}).get("dividend_per_10"),
                    dividend_period if dividends.get(symbol) else None,
                    price_payload["source"],
                    timestamp,
                    fundamental_payload["source"] if finance else None,
                    timestamp if finance else None,
                    timestamp,
                ),
            )
        # 快照源被挡住时，PE/PB/总市值 用财务底座推算，而不是留空让四套策略全部不可用。
        # 口径：总股本 = 归母净利润 / 基本每股收益（同一报告期，期间因素相消）；
        #       总市值 = 现价 × 总股本；PB = 现价 / 每股净资产；PE = 总市值 / 最近年报归母净利润。
        # PE 分母用年报而不是把当期利润年化——年化对有季节性的生意会系统性失真。
        derived = _derive_universe_valuation(conn)
        if derived:
            notes.append(
                f"{derived} 只的市值、PB 与 PE 由财务底座推算（快照源没有提供）；"
                "口径写在每条记录的推算说明里，与交易所口径可能有小幅差异。"
            )

        _UNUSED = conn.execute(
            """
            UPDATE market_universe SET
                total_shares = net_profit / eps,
                total_market_cap = price * (net_profit / eps),
                pb = CASE WHEN bps > 0 THEN price / bps ELSE NULL END,
                pe_ttm = CASE WHEN annual_net_profit > 0 THEN price * (net_profit / eps) / annual_net_profit ELSE NULL END,
                valuation_basis = '由财务底座推算：总股本＝归母净利润／每股收益，PE 分母为 ' || COALESCE(annual_report_date, '最近年报') || ' 归母净利润'
            WHERE total_market_cap IS NULL AND price IS NOT NULL AND eps IS NOT NULL AND eps > 0 AND net_profit IS NOT NULL
            """
        ).rowcount

        # 全市场没有可直接取到的历史估值序列，只能从今天起自己累积；
        # 样本不足时分位不给数字，只说明还差多少。
        today = date.today().isoformat()
        for row in price_payload["rows"]:
            if row.get("pe_ttm") is None and row.get("pb") is None and row.get("price") is None:
                continue
            # **0 不是价格，是"今天没有报价"（停牌）。** 存进去它会以两种方式害人：
            # 当分母时炸掉整个作业（见 backfill_universe_range_returns），
            # 当样本时把一段停牌期算成"股价归零"。所以这里把 0 归一成 None。
            if not row.get("price"):
                row = {**row, "price": None}
            conn.execute(
                """
                INSERT INTO universe_valuation_history (symbol, point_date, pe_ttm, pb, close, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, point_date) DO UPDATE SET
                    pe_ttm = excluded.pe_ttm, pb = excluded.pb, close = excluded.close, source = excluded.source
                """,
                (row["symbol"], today, row.get("pe_ttm"), row.get("pb"), row.get("price"), price_payload["source"]),
            )
        if index_payload["members"]:
            conn.execute("DELETE FROM index_members")
            for member in index_payload["members"]:
                # 写成 ON CONFLICT DO UPDATE 而不是 INSERT OR REPLACE：后者是 SQLite 方言，
                # PG 上直接语法错误。这条一错整个「全市场底座」作业就挂，而它是后台跑的，
                # 报错只留在 sync_schedules.last_error 里，页面上只表现为云图没数据。
                conn.execute(
                    """
                    INSERT INTO index_members (index_code, index_name, symbol, source, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(index_code, symbol) DO UPDATE SET
                        index_name = excluded.index_name, source = excluded.source, updated_at = excluded.updated_at
                    """,
                    (member["index_code"], member["index_name"], member["symbol"], index_payload["source"], timestamp),
                )
        if price_payload["rows"] and fundamental_payload["rows"]:
            # 行数完整不等于字段完整。降级行情源仍然可以写满全 A 的价格，
            # 但 PE/PB/市值等字段可能缺失；把它标成「成功」会让驾驶舱误以为
            # 这一轮底座与主源同样完整。
            status = "降级" if price_payload["degraded"] else "成功"
        else:
            status = "部分失败" if price_payload["rows"] or fundamental_payload["rows"] else "失败"
        conn.execute(
            """
            INSERT INTO universe_snapshots (
                started_at, finished_at, status, price_rows, fundamental_rows, index_rows,
                price_source, fundamental_source, report_date, degraded, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started,
                now_iso(),
                status,
                len(price_payload["rows"]),
                len(fundamental_payload["rows"]),
                len(index_payload["members"]),
                price_payload["source"],
                fundamental_payload["source"],
                period,
                1 if price_payload["degraded"] else 0,
                "；".join(notes),
            ),
        )
    # 当天收盘价已写入历史后顺手重算区间镜头；否则数据积满了也要用户另外
    # 找一个隐藏接口触发，驾驶舱会一直停在“4/5”。
    range_result = backfill_universe_range_returns()
    if any(range_result["filled"].values()):
        notes.append("区间涨跌已随本次全市场同步更新")
    return {
        "status": status,
        "price_rows": len(price_payload["rows"]),
        "fundamental_rows": len(fundamental_payload["rows"]),
        "index_rows": len(index_payload["members"]),
        "report_date": period,
        "notes": notes,
    }


def refresh_market_sentiment() -> dict[str, Any]:
    """全市场情绪面。一次请求拿全 A，不按公司循环。

    **失败不清空旧数据。** 用 UPSERT 而不是先 DELETE 再插：情绪面拉取失败时，
    昨天的数据仍然比"什么都没有"有用——人气这种东西一天之内不会翻盘，
    而空表会让荐股池里的情绪那一列整列消失，看上去像这个功能坏了。
    """
    payload = fetch_market_sentiment()
    timestamp = now_iso()
    with connection() as conn:
        for row in payload["rows"]:
            conn.execute(
                """
                INSERT INTO market_sentiment (
                    symbol, name, trade_date, main_cost, institution_participation,
                    comment_score, attention_rank, rank_change, attention_index,
                    turnover_rate, xq_followers, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name, trade_date = excluded.trade_date,
                    main_cost = excluded.main_cost,
                    institution_participation = excluded.institution_participation,
                    comment_score = excluded.comment_score,
                    attention_rank = excluded.attention_rank,
                    rank_change = excluded.rank_change,
                    attention_index = excluded.attention_index,
                    turnover_rate = excluded.turnover_rate,
                    -- 雪球那一份可能没拿到；没拿到时保留上一次的值，不要用 NULL 盖掉
                    xq_followers = COALESCE(excluded.xq_followers, market_sentiment.xq_followers),
                    source = excluded.source, updated_at = excluded.updated_at
                """,
                (row["symbol"], row["name"], row["trade_date"], row["main_cost"],
                 row["institution_participation"], row["comment_score"], row["attention_rank"],
                 row["rank_change"], row["attention_index"], row["turnover_rate"],
                 row["xq_followers"], payload["source"], timestamp),
            )
        followers = sum(1 for row in payload["rows"] if row.get("xq_followers") is not None)
    notes = [payload["note"]] if payload.get("note") else []
    return {
        "status": "成功" if payload["rows"] else "失败",
        "rows": len(payload["rows"]),
        "with_followers": followers,
        "trade_date": payload.get("trade_date"),
        "source": payload["source"],
        "notes": notes,
    }


def agent_pool(limit: int = 5, stance: str = "value") -> dict[str, Any]:
    """综合榜 · 打底层：五套规则取并集，按命中数排序。**不调模型。**

    只做 IO：把底座、情绪面、研究池取出来交给 agent_picker，打分逻辑一行都不在这里。
    这样打分能单独测——不需要一个数据库就能跑一遍五千行的打分。
    """
    from . import agent_picker

    with connection() as conn:
        rows = _universe_rows(conn)
        watched = {row["symbol"] for row in conn.execute(
            f"SELECT symbol FROM companies WHERE 1=1{_sw()}").fetchall()}
        sentiment = {row["symbol"]: dict(row) for row in
                     conn.execute("SELECT * FROM market_sentiment").fetchall()}
    if not rows:
        raise LedgerError("全市场底座还没有数据，先在数据状态页跑一次「全市场底座」")
    for row in rows:
        row["in_research_pool"] = row["symbol"] in watched

    try:
        result = agent_picker.build_pool(rows, list_screen_strategies(), sentiment,
                                         limit=limit, stance=stance)
    except ValueError as exc:
        raise LedgerError(str(exc)) from exc
    if not result["rows"] and stance != "value":
        # 空池子要说清楚是"规则太严"还是"数据没同步"——这两件事你该做的完全不同。
        result["note"] += (" 一只都没有。趋势规则要用同花顺榜单那几列，"
                           "先去数据状态页跑一次「全市场趋势面」。")
    if not sentiment:
        # 情绪面没同步时不装作有：人气那一项会整列缺，分数的分母也变了，
        # 页面必须知道这件事，否则一份「少了一项」的分数看起来跟完整的一模一样。
        result["note"] += " 情绪面还没同步过，人气那一项整列为空——去数据状态页跑一次「全市场情绪面」。"
    return result


# ---------------------------------------------------------------- 三情景估值


def _valuation_facts(conn, company: dict[str, Any]) -> dict[str, Any]:
    """算术的起点必须是真的。假设可以是你的，基数不行。"""
    from . import scenarios as sc

    symbol = company["symbol"]
    periods = _rows(conn.execute(
        "SELECT report_date, revenue, net_profit FROM financial_periods "
        "WHERE symbol = ? ORDER BY report_date", (symbol,)).fetchall())
    history = sc.annual_history(periods)
    band = sc.pe_band([row["value"] for row in conn.execute(
        "SELECT value FROM valuation_points WHERE symbol = ? AND metric = 'pe_ttm'",
        (symbol,)).fetchall()])
    universe = conn.execute(
        "SELECT price, total_shares, pe_ttm, total_market_cap FROM market_universe "
        "WHERE symbol = ?", (symbol,)).fetchone()
    universe = dict(universe) if universe else {}

    latest = history["years"][-1] if history["years"] else None
    # 总股本：底座那一列是推算的（净利润／每股收益）。取不到就用市值除以股价——
    # 两条都不通就别硬算，页面会说缺什么。
    shares = universe.get("total_shares")
    if not shares and universe.get("total_market_cap") and universe.get("price"):
        shares = universe["total_market_cap"] / universe["price"]
    return {
        "base_revenue": latest["revenue"] if latest else 0,
        "base_report_date": latest["report_date"] if latest else None,
        "shares": shares or 0,
        "price": universe.get("price"),
        "current_pe": universe.get("pe_ttm"),
        "history": history,
        "pe_band": band,
    }


def company_money_flow(company_id: int, report_date: str | None = None) -> dict[str, Any] | None:
    """钱从哪来、去了哪：那张桑基图的原料。

    ## 哪些期能选

    **年报、中报、三季报、一季报都能画** —— 利润表和现金流量表的科目每一期都在库里
    （线上 486 期，每期 20~27 个科目）。区别只在两处，两处都在图上说明：

    - 季报是**累计口径**，而四种期画出来形状一模一样 —— 所以口径写进标题和说明
    - **分部附注只有年报和中报有**，一季报三季报画不出收入按业务拆开的那一层

    上一版只取最近一期年报。那不是刻意的选择，是还没做选择。

    ## 默认仍然是最近一期年报

    年报是审计过的、科目最全的、跟别家可比的那一期。选期是一个"你要的话可以"，
    不是"每次都得挑一次"。
    """
    from . import money_flow as mf

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, symbol, name FROM companies WHERE id = ?{_sw()}",
            (company_id,)).fetchone())
        if not company:
            return None
        symbol = company["symbol"]
        # 能选的期：有收入的那些。**不要求它有科目明细** —— 只有收入和净利也画得出
        # 两根诚实的流（见 test_with_only_revenue_and_profit_...），把这种期从清单里
        # 划掉，反而会让一家只同步过主表的公司整个看不到图。
        periods = _rows(conn.execute(
            """SELECT report_date, revenue, net_profit FROM financial_periods
               WHERE symbol = ? AND revenue IS NOT NULL AND revenue > 0
               ORDER BY report_date DESC""", (symbol,)).fetchall())
        if not periods:
            return {"company_id": company_id, "symbol": symbol, "available": False,
                    "periods": [],
                    "note": "还没有同步过财务数据。到公司档案里点一次「同步财务数据」。"}

        by_date = {row["report_date"]: row for row in periods}
        # **只认清单里的那些日期。** 传进来的字符串直接进 SQL 之前先落到白名单上，
        # 顺手也解决了"传个不存在的日期得到一张空图"这件事。
        period = by_date.get(str(report_date or ""))
        if period is None:
            # 默认最近一期年报；一家刚上市、还没出过年报的公司退回最近一期。
            period = next((row for row in periods
                           if str(row["report_date"]).endswith("-12-31")), periods[0])

        items = {row["item"]: float(row["value"]) for row in conn.execute(
            "SELECT item, value FROM financial_line_items WHERE symbol = ? AND report_date = ?",
            (symbol, period["report_date"])).fetchall() if row["value"] is not None}

        # 分部附注给图的左半边（钱是从哪几门生意进来的）。
        #
        # **必须是同一期的分部**，不能用 `business_segments()` —— 那个函数固定取
        # "最近一期年报"。选期开放之后，它会把 2025 年报的分部拿去分 2024 的收入，
        # 或者拿年报的分部去分中报的收入：**加起来照样接近、覆盖率照样过**，
        # 于是画出来是一张看不出错的错图。所以这里按选中的 report_date 直接查。
        #
        # 一季报、三季报没有分部附注（不是强制披露项），查出来是空的，
        # 那一层就不画 —— money_flow 会在图下说明为什么。
        rows = _rows(conn.execute(
            """SELECT dimension, segment, revenue FROM business_segments
               WHERE symbol = ? AND report_date = ? AND revenue IS NOT NULL
               ORDER BY revenue DESC""", (symbol, period["report_date"])).fetchall())

    # 按产品分的那一维最贴"钱从哪来"；没有就退回出现的第一维（有的公司只按行业分）。
    by_dimension: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_dimension.setdefault(row["dimension"], []).append({
            "segment": row["segment"], "revenue": row["revenue"],
            # 数据源补的差额行不是业务分部：算覆盖率时它算数，画的时候并进「其他业务」。
            "filler": row["segment"] == SEGMENT_FILLER,
        })
    segments = by_dimension.get("产品") or next(iter(by_dimension.values()), [])

    view = mf.build(dict(period), items, segments)
    view.update({
        "company_id": company_id, "symbol": symbol, "company_name": company["name"],
        # 选择器要的清单。**带上口径名**，别让前端再解析一次日期 ——
        # 「2025 三季报」这四个字是这一页最要紧的一句话，只该有一个地方拼它。
        "periods": [{"report_date": row["report_date"],
                     "label": mf.period_label(row["report_date"]),
                     "annual": str(row["report_date"]).endswith("-12-31")}
                    for row in periods],
    })
    if not view["available"]:
        # **说清楚是哪一步缺的。** 只说"画不出来"的话，他不知道该去点哪个按钮。
        view["note"] = (f"{mf.period_label(period['report_date'])}里还没有拼得出这张图的科目"
                        f"（当前有 {len(items)} 个）。到公司档案里点一次「同步财务数据」，"
                        f"它会把利润表与现金流量表的白名单科目一起取回来。")
    return view


def company_valuation(company_id: int) -> dict[str, Any] | None:
    """这家公司的三情景估值。存过就用你存的，没存过就按它自己的历史给一组初值。

    **初值不是推荐值**，是"你还没填时，它自己过去长什么样"。
    """
    from . import scenarios as sc

    company = get_company(company_id)
    if company is None:
        return None
    with connection() as conn:
        facts = _valuation_facts(conn, company)
        saved = conn.execute(
            f"SELECT * FROM valuations WHERE company_id = ?{_sw()} ORDER BY id DESC LIMIT 1",
            (company_id,)).fetchone()

    years, discount = sc.DEFAULT_YEARS, sc.DEFAULT_DISCOUNT
    scenarios: list[sc.Scenario] = []
    saved_at = None
    price_at_write = None
    note = ""
    if saved:
        saved = dict(saved)
        years, discount = int(saved["years"]), float(saved["discount_rate"])
        scenarios = [sc.Scenario(item["key"], float(item["revenue_growth"]),
                                 float(item["net_margin"]), float(item["exit_pe"]))
                     for item in json.loads(saved["scenarios"])]
        saved_at, price_at_write, note = saved["created_at"], saved["price_at_write"], saved["note"]
    if not scenarios:
        scenarios = sc.seed(facts["history"], facts["pe_band"], facts.get("current_pe"))

    if not scenarios:
        # 编一组默认假设是这套东西最危险的失败方式：它看起来很专业，会被当成基准，
        # 而且没有任何报错。宁可明说缺什么。
        missing = []
        if facts["history"].get("cagr_5y") is None and facts["history"].get("cagr_3y") is None:
            missing.append("至少四期年报（算复合增速要用）")
        if not facts["pe_band"].get("p50") and not facts.get("current_pe"):
            missing.append("历史估值序列或当前市盈率")
        return {"company_id": company_id, "company_name": company["name"],
                "symbol": company["symbol"], "ready": False,
                "missing": missing, "history": facts["history"],
                "note": "先在公司档案里同步定期报告与历史估值，再回来填假设。"
                        "这里不给默认值——一组编出来的假设会被当成基准。"}

    view = sc.build(facts, scenarios, years, discount)
    view.update({
        "company_id": company_id, "company_name": company["name"], "symbol": company["symbol"],
        "ready": True, "missing": [], "saved": saved is not None, "saved_at": saved_at,
        "price_at_write": price_at_write, "note": note,
        "pe_band": facts["pe_band"], "current_pe": facts.get("current_pe"),
        "seeded_from": ("你保存的假设" if saved else
                        "还没填过——下面是按这家公司自己的历史给的初值，不是推荐值"),
    })
    return view


def _happened_between(conn, company: dict[str, Any], since: str, until: str) -> dict[str, Any]:
    """两次保存之间，这家公司到底发生过什么。

    **这一半才是漂移检测的杀伤力所在。** 光说「你改了假设」谁都不当回事；
    「而这期间什么都没发生」才让人停下来。而它完全是从库里数出来的，
    一个模型都不用调。

    时间口径刻意各不相同：
    - 证据用 `created_at`（**你什么时候归档的**，不是它什么时候发生的）——
      问的是"你这期间学到了什么"，那就该按你接收的时刻算。
    - 公告用 `event_date`（它什么时候发生的），并且只数「高/中」相关——
      股东大会通知这类程序性文件不构成"新信息"。
    - 定期报告用 `announcement_date`，取不到时退回 `report_date`。
    """
    company_id, symbol = company["id"], company["symbol"]
    evidences = int(conn.execute(
        f"SELECT COUNT(*) AS n FROM evidences WHERE company_id = ?{_swc('company_id')} "
        "AND created_at > ? AND created_at <= ?", (company_id, since, until)).fetchone()["n"])
    material = int(conn.execute(
        f"""SELECT COUNT(*) AS n FROM company_calendar_events
            WHERE company_id = ?{_swc('company_id')}
              AND event_date > ? AND event_date <= ?
              AND COALESCE(relevance, '') IN ('高', '中')""",
        (company_id, since[:10], until[:10])).fetchone()["n"])
    reports = int(conn.execute(
        """SELECT COUNT(DISTINCT report_date) AS n FROM financial_periods
           WHERE symbol = ? AND COALESCE(announcement_date, report_date) > ?
             AND COALESCE(announcement_date, report_date) <= ?""",
        (symbol, since[:10], until[:10])).fetchone()["n"])
    return {"evidences": evidences, "material_events": material, "reports": reports}


def company_tool_runner(company_id: int) -> Callable[[str, dict[str, Any]], Any]:
    """一家公司的只读工具。**全部只读，全部钉死在这一家公司上。**

    钉死是关键：工具不接受 company_id 参数，模型没有办法去查别家公司，
    更没有办法去查别人的数据。它想查什么都只能在这家公司的范围里查。

    反方 Agent 和起草投资逻辑共用这一份。共用是有意的：两边要的是同一件事，
    各写一份会立刻分叉，然后其中一边悄悄少掉一个工具或少一道隔离。
    """
    def run(name: str, args: dict[str, Any]) -> Any:
        if name == "financials":
            annual = args.get("annual_only", True) is not False
            limit = min(int(args.get("limit") or 12), 40)
            with connection() as conn:
                symbol = _symbol_of(conn, company_id)
                if not symbol:
                    return {"error": "这家公司不在档案里"}
                rows = _rows(conn.execute(
                    """SELECT report_date, revenue, net_profit, operating_cash_flow,
                              operating_cost, total_assets, total_liabilities, equity,
                              debt_ratio, roe_estimate
                       FROM financial_periods WHERE symbol = ?
                       ORDER BY report_date DESC""", (symbol,)).fetchall())
            if annual:
                rows = [r for r in rows if str(r["report_date"]).endswith("-12-31")]
            return {"unit": "元", "periods": list(reversed(rows[:limit]))}
        if name == "industry_metrics":
            view = company_industry_metrics(company_id) or {}
            return {"industry": view.get("resolved"), "note": view.get("note"),
                    "rows": [{k: r[k] for k in ("label", "unit", "formula", "series", "latest", "change")}
                             for r in view.get("rows", []) if r.get("applicable")]}
        if name == "segments":
            return business_segments(company_id) or {"note": "还没有同步分部构成"}
        if name == "valuation":
            with connection() as conn:
                symbol = _symbol_of(conn, company_id)
                current = _one_or_none(conn.execute(
                    "SELECT pe_ttm, pb, total_market_cap, price FROM market_universe WHERE symbol = ?",
                    (symbol,)).fetchone()) or {}
            return {"current": current, "scenarios": company_valuation(company_id) or {}}
        if name == "announcements":
            limit = min(int(args.get("limit") or 25), 60)
            with connection() as conn:
                # 这几张表**按 company_id 挂靠、自身没有 user_id 列**（见 pgbackend
                # 的 _RLS_COMPANY_TABLES），所以过滤要用 _swc 而不是 _sw。
                # 用错了不是查不到，是直接 UndefinedColumn 报错。
                return {"rows": _rows(conn.execute(
                    f"""SELECT event_date, category, title, relevance, summary, url
                        FROM company_calendar_events WHERE company_id = ?{_swc()}
                        ORDER BY event_date DESC LIMIT ?""", (company_id, limit)).fetchall())}
        if name == "announcement_text":
            # **这是这组工具里最值钱的一个**（#41 做完才有）：
            # 「关于股份回购进展情况的公告」这十四个字里没有信息，
            # 信息在正文的「不低于 50 亿元」「不超过 12 个月」里。
            keyword = str(args.get("title_contains") or "").strip()
            if not keyword:
                return {"error": "要指明标题里的关键词，不然不知道读哪一条"}
            day = str(args.get("event_date") or "").strip()
            with connection() as conn:
                # 字面 % 会被 psycopg2 当成占位符 —— 通配符必须走参数。
                rows = _rows(conn.execute(
                    f"""SELECT id, event_date, title, url FROM company_calendar_events
                        WHERE company_id = ?{_swc()} AND title LIKE ?
                        {"AND event_date = ?" if day else ""}
                        ORDER BY event_date DESC LIMIT 3""",
                    (company_id, f"%{keyword}%", *( (day,) if day else () ))).fetchall())
            if not rows:
                return {"error": f"没有标题里带「{keyword}」的公告"}
            fetched = announcement_bodies(rows, budget=3)
            bodies = fetched["bodies"]
            out = []
            for row in rows:
                body = bodies.get(int(row["id"]))
                out.append({
                    "event_date": row["event_date"], "title": row["title"],
                    # 取不到要说清楚是取不到，不能返回空串——
                    # 空串会被当成"这条公告什么都没写"。
                    "text": body if body else None,
                    "note": None if body else "这一条取不到正文（可能是扫描件或已撤下）",
                })
            return {"rows": out}
        if name == "theses":
            with connection() as conn:
                return {
                    "theses": _rows(conn.execute(
                        f"""SELECT id, claim, counter_condition, status, next_review_trigger,
                                   price_at_write, created_at
                            FROM theses WHERE company_id = ?{_swc()}""", (company_id,)).fetchall()),
                    "evidences": _rows(conn.execute(
                        f"""SELECT polarity, source_name, excerpt, occurred_at
                            FROM evidences WHERE company_id = ?{_swc()}
                            ORDER BY occurred_at DESC LIMIT 40""", (company_id,)).fetchall()),
                }
        if name == "promises":
            view = company_promises(company_id) or {}
            return {"headline": view.get("headline"),
                    "rows": [{k: r.get(k) for k in
                              ("statement", "subject", "category", "promised_on",
                               "due_date", "status", "check")}
                             for r in view.get("rows", [])]}
        if name == "peers":
            from .peers import table as peer_table
            company = get_company(company_id)
            return peer_table(company) if company else {"note": "还没有同行数据"}
        return {"error": f"没有这个工具：{name}"}

    return run


def run_devils_advocate(company_id: int, question: str,
                        history: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """跑一轮反方对话。**只读、只提议，一个字都不写库。**"""
    from . import devils_advocate as da

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, name, symbol FROM companies WHERE id = ?{_sw()}",
            (company_id,)).fetchone())
    if not company:
        return None
    view = da.converse(question.strip(), company_tool_runner(company_id), history)
    return {"company_id": company_id, "company_name": company["name"],
            "symbol": company["symbol"], "question": question.strip(), **view}


def _promise_facts(conn: sqlite3.Connection, symbol: str) -> dict[str, dict[str, float]]:
    """自动核对用得上的那几个数。**全部来自库里已有的报表，不联网、不过模型。**"""
    facts: dict[str, dict[str, float]] = {"net_profit": {}, "revenue": {},
                                          "latest_dividend_payout_ratio": {}}
    for row in conn.execute(
            "SELECT report_date, revenue, net_profit FROM financial_periods WHERE symbol = ?",
            (symbol,)).fetchall():
        for key in ("revenue", "net_profit"):
            if row[key] is not None:
                facts[key][row["report_date"]] = float(row[key])
    profile = conn.execute(
        "SELECT latest_dividend_period, latest_dividend_payout_ratio "
        "FROM company_profiles WHERE symbol = ?", (symbol,)).fetchone()
    if profile and profile["latest_dividend_payout_ratio"]:
        # 分红比例在档案里是文本（「30.15%」这种），取得出数才用。
        match = re.search(r"-?\d+(\.\d+)?", str(profile["latest_dividend_payout_ratio"]))
        if match:
            facts["latest_dividend_payout_ratio"][
                str(profile["latest_dividend_period"] or "")] = float(match.group(0))
    return facts


def company_promises(company_id: int) -> dict[str, Any] | None:
    """管理层承诺兑现台账：公司说过的话，到期之后有没有人回头看。"""
    from . import promises as pr

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, symbol, name FROM companies WHERE id = ?{_sw()}",
            (company_id,)).fetchone())
        if not company:
            return None
        rows = _rows(conn.execute(
            f"""SELECT * FROM management_promises
                WHERE company_id = ?{_sw()}
                ORDER BY (due_date IS NULL), due_date, promised_on DESC""",
            (company_id,)).fetchall())
        facts = _promise_facts(conn, company["symbol"])

    today = date.today().isoformat()
    for row in rows:
        row["check"] = pr.auto_check(row, facts)
        row["overdue"] = bool(
            row["status"] == "待到期" and row["due_date"]
            and row["due_date"] <= (date.today() - timedelta(days=pr.DUE_GRACE_DAYS)).isoformat())
    return {"company_id": company_id, "company_name": company["name"],
            "symbol": company["symbol"], "as_of": today, "rows": rows,
            **pr.summarize(rows)}


def announcement_bodies(events: list[dict[str, Any]],
                        budget: int | None = None) -> dict[str, Any]:
    """给这批公告配上正文。

    返回 {"bodies": {event_id: 正文}, "read": n, "failed": n, "pending": n}。

    **抓过的不再抓第二次**——正文存在 announcement_texts 里，全局一份。
    取不到的也记（status='取不到'），否则一条已撤下的公告会在每次抽取时被重试。

    budget 是这一轮最多新抓几份；缓存命中的不占预算。

    **pending 必须报出来。** 60 条公告、一轮预算 24 份，一次抽取读不完；
    不说的话使用者看到的是"读了 60 条公告，找到 3 条承诺"，
    会以为已经读完了——而实际上还有三十几份正文没看过，
    里面很可能正好有他要的那条。
    """
    from . import disclosure

    if budget is None:
        budget = disclosure.MAX_FETCH_PER_RUN
    wanted = disclosure.readable(events)
    if not wanted:
        return {"bodies": {}, "read": 0, "failed": 0, "pending": 0}

    by_ident: dict[str, list[dict[str, Any]]] = {}
    for event in wanted:
        ident = disclosure.announcement_id(event.get("url"))
        by_ident.setdefault(ident, []).append(event)

    idents = list(by_ident)
    with connection() as conn:
        cached = {
            row["announcement_id"]: row
            for row in _rows(conn.execute(
                f"SELECT announcement_id, status, note, body FROM announcement_texts "
                f"WHERE announcement_id IN ({', '.join('?' for _ in idents)})",
                idents).fetchall())
        }

    # 没缓存的按排好的顺序抓，抓到预算用完为止。排序在 disclosure.readable 里：
    # 越像有承诺的越靠前，所以预算优先花在最可能有产出的公告上。
    todo = [ident for ident in idents if ident not in cached][:max(0, budget)]
    if todo:
        urls = {ident: str(by_ident[ident][0].get("url") or "") for ident in todo}
        fetched = disclosure.fetch_many([urls[ident] for ident in todo])
        timestamp = now_iso()
        with connection() as conn:
            for ident in todo:
                result = fetched.get(urls[ident]) or {"status": "取不到", "body": "", "note": "未返回"}
                body = str(result.get("body") or "")
                conn.execute(
                    """
                    INSERT INTO announcement_texts
                        (announcement_id, pdf_url, status, note, char_count, body, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(announcement_id) DO UPDATE SET
                        pdf_url = excluded.pdf_url, status = excluded.status,
                        note = excluded.note, char_count = excluded.char_count,
                        body = excluded.body, fetched_at = excluded.fetched_at
                    """,
                    (ident, str(result.get("pdf_url") or ""), str(result.get("status") or "取不到"),
                     str(result.get("note") or ""), len(body), body, timestamp))
                cached[ident] = {"announcement_id": ident, "status": result.get("status"),
                                 "note": result.get("note"), "body": body}

    out: dict[int, str] = {}
    failed = 0
    # 取不到的原因要带回去。**一份都没取到时，这是唯一能说明"卡在哪一步"的线索**——
    # 少了它，界面上只能说「一条正文都没取到」，而使用者没法判断该等一等还是该报修。
    # （实测那次的原因是 `解析失败：ModuleNotFoundError`——服务器 venv 少装了 pypdf。）
    reasons: list[str] = []
    for ident, rows in by_ident.items():
        row = cached.get(ident)
        if not row or row.get("status") != "已取正文" or not row.get("body"):
            if row:
                failed += 1
                note = str(row.get("note") or row.get("status") or "").strip()
                if note:
                    reasons.append(note)
            continue
        for event in rows:
            if event.get("id") is not None:
                out[int(event["id"])] = str(row["body"])
    return {"bodies": out, "read": len(out), "failed": failed, "reasons": reasons,
            # 还没轮到的：这一轮预算不够，下次再点会接着读。
            "pending": len([ident for ident in idents if ident not in cached])}


def extract_company_promises(company_id: int, limit: int = 60) -> dict[str, Any] | None:
    """从这家公司已归档的公告里找承诺。**只抽取，不落库**——每条都要你确认。"""
    from . import promises as pr

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, name FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone())
        if not company:
            return None
        # 只看实质性公告。程序性那一堆里没有承诺，喂进去只是烧 token。
        #
        # **这里原来写的是 _sw()，而 company_calendar_events 没有 user_id 列。**
        # 后果是任何登录用户点「抽取承诺」都会撞上 UndefinedColumn 直接 500 ——
        # 这个功能上线以来一次都没成功过。测试没抓到是因为测试跑在系统域下
        # （current_scope() 为 None，_sw() 返回空串，那一句 AND 根本不存在）。
        # 这张表按 company_id 挂靠，过滤要走 _swc()。
        events = _rows(conn.execute(
            f"""SELECT id, category, event_date, title, detail, summary, url
                FROM company_calendar_events
                WHERE company_id = ?{_swc()} AND COALESCE(relevance, '') <> '低'
                ORDER BY event_date DESC LIMIT ?""",
            (company_id, limit)).fetchall())
        known = {row["statement"] for row in conn.execute(
            f"SELECT statement FROM management_promises WHERE company_id = ?{_sw()}",
            (company_id,)).fetchall()}

    if not events:
        return {"company_id": company_id, "found": [], "known": 0,
                "note": "这家公司还没有归档的实质性公告。先到「大事提醒」里同步一次。"}

    # **先把正文取回来。** 只喂标题的话这个功能不可能有产出——实测 12 家公司
    # 抽出 0 条，而格力那条回购公告的正文里躺着四条带数字带期限的承诺。
    fetched = announcement_bodies(events)
    bodies = fetched["bodies"]
    for event in events:
        body = bodies.get(int(event["id"])) if event.get("id") is not None else None
        if body:
            event["body"] = body
    # 有正文的排前面。分批是按正文长度切的，让有正文的先进批次，
    # 免得预算被一堆只有标题的公告占掉。
    events.sort(key=lambda event: bool(event.get("body")), reverse=True)

    # **一份正文都没有就别调模型。**
    #
    # 2026-08-12 实测：线上 venv 缺 pypdf，24 份正文全部记成「取不到」
    # （note 是 `解析失败：ModuleNotFoundError`），于是模型每次只拿到标题，
    # 抽出 0 条——这个功能上线以来一次都没有产出过。
    #
    # 那一次任务记的是 credits=1 / tokens=2087：钱花得不多，但它是**空转**——
    # 一次结构上不可能有产出的调用。而使用者看到的是"没找到承诺"，
    # 跟"这家公司真的没承诺"长得一模一样。
    #
    # 只喂标题抽不出承诺，这是这个功能的前提（见上面那段注释），不是运气问题。
    # 所以前提不成立就当场停下，说清楚是哪一步断的，一分不花。
    if not fetched["read"]:
        pending = fetched["pending"]
        why = "；".join(sorted(set(fetched.get("reasons") or []))[:3]) or "原因未记录"
        return {"company_id": company_id, "found": [], "known": len(known),
                "scanned": len(events), "read_full_text": 0, "pending_full_text": pending,
                "batch_failures": [], "blocked": True,
                "note": (f"这 {len(events)} 条公告**一份正文都没取到**（{why}），"
                         "只有标题的话抽不出承诺——所以这次没有调模型，也没有花积分。"
                         "等公告正文能读了再点一次。"),
                "boundary": pr._BOUNDARY}

    batch_failures: list[str] = []
    found = [item for item in pr.extract(events, failures=batch_failures)
             if item["statement"] not in known]
    read, pending = fetched["read"], fetched["pending"]
    # **读了几份正文要说出来。** 只说"读了 60 条公告"的话，一次网络故障
    # 导致 0 份正文、于是 0 条承诺，看起来跟"这家公司真的没承诺"一模一样。
    source = (f"其中 {read} 条读了公告原文" if read else
              "但一条正文都没取到（可能是网络不通，或这些公告都没有 PDF），"
              "只看到了标题")
    # 还没读完的必须顶出来，否则使用者会以为已经读完了。
    more = (f"　还有 {pending} 份正文这一轮没排上，再点一次会接着读。" if pending else "")
    # 读失败的批次要摆出来。**不摆的话一次限流就等于"这家公司没有承诺"**，
    # 而这两件事在界面上长得一模一样。
    if batch_failures:
        more += "　" + "".join(batch_failures)
    return {"company_id": company_id, "found": found, "known": len(known),
            "scanned": len(events), "read_full_text": read, "pending_full_text": pending,
            "batch_failures": batch_failures,
            "note": (f"从 {len(events)} 条公告里找出 {len(found)} 条可以被证伪的承诺"
                     f"（{source}），逐条确认之后才进台账。{more}" if found else
                     f"读了 {len(events)} 条公告（{source}），没有找到符合标准的承诺——"
                     f"要有原文、有数字或期限、能被证伪。「将努力提升股东回报」这类不收。{more}"),
            "boundary": pr._BOUNDARY}


def save_promises(company_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """把确认过的承诺记进台账。"""
    timestamp = now_iso()
    saved = 0
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            raise LedgerError("这家公司不在你的档案里。")
        for item in items:
            statement = str(item.get("statement") or "").strip()
            promised_on = str(item.get("promised_on") or "").strip()
            if not statement or not promised_on:
                continue
            conn.execute(
                """INSERT INTO management_promises (
                       user_id, company_id, event_id, source_title, source_url, promised_on,
                       subject, statement, category, due_date,
                       check_metric, check_op, check_value, check_period,
                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, company_id, statement, promised_on) DO NOTHING""",
                (_stamp(), company_id, item.get("event_id"),
                 str(item.get("source_title") or "")[:300], item.get("source_url"), promised_on,
                 str(item.get("subject") or "公司")[:40], statement[:500],
                 str(item.get("category") or "其他"),
                 str(item.get("due_date") or "") or None,
                 str(item.get("check_metric") or ""), str(item.get("check_op") or ""),
                 item.get("check_value"), str(item.get("check_period") or ""),
                 timestamp, timestamp))
            saved += 1
    return {"saved": saved, "note": f"记了 {saved} 条。到期时会顶到你面前。"}


def settle_promise(promise_id: int, status: str, note: str = "") -> dict[str, Any] | None:
    """给一条承诺下结论。**结论由人下**——自动核对只说对上没对上。"""
    allowed = {"待到期", "已兑现", "未兑现", "部分兑现", "无法核对", "已放弃"}
    if status not in allowed:
        raise LedgerError(f"不认识的状态「{status}」。")
    timestamp = now_iso()
    with connection() as conn:
        row = conn.execute(
            f"""SELECT p.id FROM management_promises p
                WHERE p.id = ?{_sw('p')}""", (promise_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            """UPDATE management_promises
               SET status = ?, outcome_note = ?, settled_at = ?, updated_at = ?
               WHERE id = ?""",
            (status, note[:500], timestamp if status != "待到期" else None, timestamp, promise_id))
    return {"id": promise_id, "status": status}


def due_promises() -> list[dict[str, Any]]:
    """所有已经到期还没核对的承诺。给今日概览用——**到期了要顶到面前**，
    而不是等你哪天想起来去某家公司的档案里翻。"""
    from . import promises as pr

    cutoff = (date.today() - timedelta(days=pr.DUE_GRACE_DAYS)).isoformat()
    with connection() as conn:
        return _rows(conn.execute(
            f"""SELECT p.id, p.company_id, c.name AS company_name, c.symbol,
                       p.subject, p.statement, p.category, p.due_date, p.source_url
                FROM management_promises p JOIN companies c ON c.id = p.company_id
                WHERE p.status = '待到期' AND p.due_date IS NOT NULL
                  AND p.due_date <= ?{_sw('p')}
                ORDER BY p.due_date""", (cutoff,)).fetchall())


def load_samples() -> dict[str, Any]:
    """载入三个示例公司档案。**由使用者在空态点一下，不自动种。**

    自动种是"替他做决定"；而这三份是示例、不是他的研究，
    该由他自己决定要不要。空态那个按钮本身也在解释这个产品是干什么的。

    已经有同代码公司的跳过——**不覆盖他自己的档案**。
    """
    from .samples import SAMPLES
    from .schemas import CompanyInput

    created: list[str] = []
    skipped: list[str] = []
    synced: list[str] = []
    failures: list[str] = []
    timestamp = now_iso()
    for sample in SAMPLES:
        with connection() as conn:
            exists = conn.execute(
                f"SELECT id FROM companies WHERE symbol = ?{_sw()}",
                (sample["symbol"],)).fetchone()
        if exists:
            skipped.append(sample["name"])
            continue
        company = create_company(CompanyInput(
            symbol=sample["symbol"], name=sample["name"], industry=sample["industry"],
            description=sample["description"], watch_group=sample["watch_group"]))
        company_id = company["id"]
        with connection() as conn:
            conn.execute(f"UPDATE companies SET is_sample = 1 WHERE id = ?{_sw()}", (company_id,))
            for event in sample.get("events", []):
                conn.execute(
                    """INSERT INTO company_calendar_events
                       (company_id, category, event_date, title, detail, url, source,
                        refreshed_at, inbox_status, relevance)
                       VALUES (?, ?, ?, ?, '', NULL, ?, ?, '已归档', '高')""",
                    (company_id, event["category"], event["event_date"], event["title"],
                     "示例档案", timestamp))
            thesis = sample["thesis"]
            cursor = conn.execute(
                """INSERT INTO theses (company_id, is_sample, claim, counter_condition,
                                       status, next_review_trigger, created_at, updated_at)
                   VALUES (?, 1, ?, ?, 'watching', ?, ?, ?)""",
                (company_id, thesis["claim"], thesis["counter_condition"],
                 thesis["next_review_trigger"], timestamp, timestamp))
            thesis_id = cursor.lastrowid
            for item in sample.get("evidence", []):
                conn.execute(
                    """INSERT INTO evidences (company_id, thesis_id, source_name, source_url,
                                              excerpt, polarity, occurred_at, verification, created_at)
                       VALUES (?, ?, ?, NULL, ?, ?, ?, '已核验', ?)""",
                    (company_id, thesis_id, item["source_name"], item["excerpt"],
                     item["polarity"], item["occurred_at"], timestamp))
            for item in sample.get("promises", []):
                conn.execute(
                    """INSERT INTO management_promises
                       (company_id, source_title, promised_on, subject, statement,
                        category, due_date, created_at, updated_at)
                       VALUES (?, '示例档案', ?, ?, ?, ?, ?, ?, ?)""",
                    (company_id, item["promised_on"], item["subject"], item["statement"],
                     item["category"], item["due_date"], timestamp, timestamp))
        # **示例就该是完整的。**
        #
        # 行业特有指标（合同负债、收现比这些）要 financial_line_items，
        # 而那张表是按需同步的——不补的话，示例里有两家的「这门生意该盯的那几个数」
        # 是空的，旁边还写着标题。**那正是我们要消灭的空态，只是换了个地方出现。**
        #
        # 只补缺的：这张表是全局的，别人同步过就直接有了。
        # 失败不拖垮载入——**没有行业指标的示例仍然是有用的示例**。
        try:
            with connection() as conn:
                has_items = conn.execute(
                    "SELECT 1 FROM financial_line_items WHERE symbol = ? LIMIT 1",
                    (sample["symbol"],)).fetchone()
            if not has_items:
                refresh_company_financials(company_id)
                synced.append(sample["name"])
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{sample['name']} 的报表科目没同步上（{type(exc).__name__}），"
                            f"行业指标那一块会是空的")
        created.append(sample["name"])
    note = (f"载入了 {len(created)} 份示例：{'、'.join(created)}。"
            if created else "三份示例你都已经有同代码的档案了，没有覆盖。")
    if skipped:
        note += f"　跳过 {'、'.join(skipped)}（你已经有这几家的档案）。"
    if synced:
        note += f"　顺带同步了 {'、'.join(synced)} 的报表科目（行业指标要用）。"
    if failures:
        note += "　" + "；".join(failures) + "。"
    return {"created": created, "skipped": skipped, "synced": synced,
            "failures": failures, "note": note,
            "boundary": "示例带「示例」记号，随时可以一键删掉；删掉之后不会自己回来。"}


def remove_samples() -> dict[str, Any]:
    """删掉全部示例。**不能删的示例等于强塞。**"""
    with connection() as conn:
        rows = _rows(conn.execute(
            f"SELECT id, name FROM companies WHERE is_sample = 1{_sw()}").fetchall())
        for row in rows:
            conn.execute(f"DELETE FROM companies WHERE id = ?{_sw()}", (row["id"],))
    return {"removed": [r["name"] for r in rows],
            "note": (f"删掉了 {len(rows)} 份示例。" if rows else "没有示例可删。")}


def company_chain_position(company_id: int, refresh: bool = False) -> dict[str, Any] | None:
    """这家公司在产业链上被谁卡着：年报披露的客户与供应商集中度。

    **抽取是纯正则，不花积分**（见 chain_position）。抓年报正文要几秒，
    所以结果落库，第二次直接读。

    银行与保险的年报里没有这一节（不适用这项披露），那种情况如实说明——
    留空会让人以为还没抓过，而"没抓"和"不适用"要做的事完全不同。
    """
    from . import chain_position as cpos
    from . import disclosure

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, symbol, name, industry FROM companies WHERE id = ?{_sw()}",
            (company_id,)).fetchone())
        if not company:
            return None
        symbol = company["symbol"]
        cached = None if refresh else _one_or_none(conn.execute(
            "SELECT * FROM chain_positions WHERE symbol = ?", (symbol,)).fetchone())

    if cached is None:
        with connection() as conn:
            # **只取年度报告。** 半年报没有这一节——搜到的「前五大客户」
            # 全在财务附注的信用风险段里，那是另一件事，拿来当集中度是错的。
            # `LIKE '%年度报告%'` 会把「半年度报告」也匹配进来，所以要显式排掉。
            report = _one_or_none(conn.execute(
                f"""SELECT event_date, title, url FROM company_calendar_events
                    WHERE company_id = ?{_swc()} AND title LIKE ?
                      AND title NOT LIKE ? AND title NOT LIKE ? AND title NOT LIKE ?
                    ORDER BY event_date DESC LIMIT 1""",
                (company_id, "%年度报告%", "%半年度%", "%摘要%", "%英文%")).fetchone())
        if not report:
            return {"company_id": company_id, "symbol": symbol, "available": False,
                    "note": "库里还没有这家公司的年度报告。先到「大事提醒」同步一次公告。",
                    "boundary": _CHAIN_BOUNDARY}
        got = disclosure.fetch_one(report["url"])
        if got["status"] != "已取正文":
            return {"company_id": company_id, "symbol": symbol, "available": False,
                    "note": f"取不到这份年报的正文：{got['note']}", "boundary": _CHAIN_BOUNDARY}
        parsed = cpos.extract(got["body"])
        timestamp = now_iso()
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO chain_positions (symbol, report_title, report_date, source_url,
                    customer_ratio, customer_amount, supplier_ratio, supplier_amount,
                    top_json, excerpt, note, extracted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    report_title = excluded.report_title, report_date = excluded.report_date,
                    source_url = excluded.source_url,
                    customer_ratio = excluded.customer_ratio, customer_amount = excluded.customer_amount,
                    supplier_ratio = excluded.supplier_ratio, supplier_amount = excluded.supplier_amount,
                    top_json = excluded.top_json, excerpt = excluded.excerpt,
                    note = excluded.note, extracted_at = excluded.extracted_at
                """,
                (symbol, report["title"], report["event_date"], report["url"],
                 parsed.get("customer_ratio"), parsed.get("customer_amount"),
                 parsed.get("supplier_ratio"), parsed.get("supplier_amount"),
                 json.dumps(parsed.get("top") or [], ensure_ascii=False),
                 parsed.get("excerpt", ""), parsed.get("note", ""), timestamp))
        with connection() as conn:
            cached = _one_or_none(conn.execute(
                "SELECT * FROM chain_positions WHERE symbol = ?", (symbol,)).fetchone())

    row = dict(cached or {})
    customer, supplier = row.get("customer_ratio"), row.get("supplier_ratio")
    available = customer is not None or supplier is not None
    return {
        "company_id": company_id, "symbol": symbol, "available": available,
        "report_title": row.get("report_title") or "", "report_date": row.get("report_date") or "",
        "source_url": row.get("source_url"),
        "customer_ratio": customer, "supplier_ratio": supplier,
        "customer_amount": row.get("customer_amount"), "supplier_amount": row.get("supplier_amount"),
        "top": (top := json.loads(row.get("top_json") or "[]")),
        "excerpt": row.get("excerpt") or "",
        # **逐名明细要传进去。** 只给前五合计的话，「合计 29.3% 但第一名占 17%」
        # 会被读成「下游分散，没有哪一家能单独左右它」—— 而那张表就在旁边摆着 17%。
        "reading": cpos.read_position(customer, supplier, top) if available else "",
        "note": (row.get("note") or "") if not available else "",
        "boundary": _CHAIN_BOUNDARY,
    }


_CHAIN_BOUNDARY = (
    "这两个数是代码从年报原文里抽的，**不过模型、不花积分**，"
    "下面那段原文就是出处。银行与保险的年报没有这一节，属于不适用。"
)


def company_industry_metrics(company_id: int) -> dict[str, Any] | None:
    """这门生意该盯的那几个数。

    行业口径按**申万二级 → 申万一级 → 档案行业**依次找，取第一个恰好匹配的。
    模糊匹配一律不做：把「食品饮料」当「白酒」算出来的合同负债结论，
    对乳制品公司是错的，而它看起来跟对的一模一样。
    """
    from . import industry_metrics as im

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, symbol, name, industry FROM companies WHERE id = ?{_sw()}",
            (company_id,)).fetchone())
        if not company:
            return None
        symbol = company["symbol"]
        universe = _one_or_none(conn.execute(
            "SELECT sw_level1, sw_level2 FROM market_universe WHERE symbol = ?",
            (symbol,)).fetchone()) or {}
        base = _rows(conn.execute(
            """SELECT report_date, revenue, operating_cost, total_assets
               FROM financial_periods WHERE symbol = ? ORDER BY report_date""",
            (symbol,)).fetchall())
        items = _rows(conn.execute(
            "SELECT report_date, item, value FROM financial_line_items WHERE symbol = ?",
            (symbol,)).fetchall())

    by_date: dict[str, dict[str, float]] = {}
    for row in items:
        if row["value"] is not None:
            by_date.setdefault(row["report_date"], {})[row["item"]] = float(row["value"])
    periods = [{**row, "items": by_date.get(row["report_date"], {})} for row in base]

    industry = (universe.get("sw_level2") or universe.get("sw_level1")
                or company["industry"] or "")
    # **第二把钥匙。** 申万分类在库里全是空的（实测 5538 行 0 个有值），
    # 三级回退实际只剩证监会门类，而「酒、饮料和精制茶制造业」这种粗名字
    # 一个都匹配不上——这个功能因此对 12 家公司一条指标都没算出来过。
    # 主营业务里的确切词（「白酒」「银行」）配上粗分类才能定行业，
    # 单靠其中任何一个都不行。
    with connection() as conn:
        profile = _one_or_none(conn.execute(
            "SELECT main_business, introduction FROM company_profiles WHERE symbol = ?",
            (symbol,)).fetchone()) or {}
    hint = " ".join(str(profile.get(k) or "") for k in ("main_business", "introduction"))
    hint += " " + str(company["name"] or "")
    view = im.analyze(industry, periods, hint=hint)
    # 分类口径三个都摆出来：算不出指标时，你得看得见是哪一级没对上。
    view["industry_sources"] = {"申万二级": universe.get("sw_level2") or "",
                                "申万一级": universe.get("sw_level1") or "",
                                "档案行业": company["industry"] or ""}
    if not by_date:
        view["note"] = ((view["note"] + " " if view["note"] else "")
                        + "报表原始科目还没同步过——点这一页上面那个「更新财务数据」跑一次就有了"
                          "（同一次请求里顺带落库，不多花一次网络）。")
    return {"company_id": company_id, "company_name": company["name"],
            "symbol": symbol, **view}


def portfolio_common_risk(portfolio_id: int) -> dict[str, Any] | None:
    """组合共同风险：我以为的分散，是不是同一个赌注下了五次。

    这里只负责**把事实取齐**，判断全在 portfolio_risk 里，而那一层没有数据库
    也没有模型——它拿到什么就只能说什么，编不出东西来。
    """
    from . import portfolio_risk

    detail = get_portfolio(portfolio_id)
    if detail is None:
        return None
    positions = detail["positions"]
    symbols = [p["symbol"] for p in positions if p["symbol"]]
    company_ids = [p["company_id"] for p in positions]

    facts: dict[str, dict[str, Any]] = {s: {} for s in symbols}
    market: dict[str, list[float]] = {}
    with connection() as conn:
        if symbols:
            marks = ",".join("?" for _ in symbols)
            for row in _rows(conn.execute(
                    f"""SELECT symbol, industry, sw_level1, sw_level2, pe_ttm, pb,
                               total_market_cap, above_ma60, new_high_level, rising_days
                        FROM market_universe WHERE symbol IN ({marks})""", symbols).fetchall()):
                facts[row["symbol"]].update(row)
            # 档案上的行业是你自己填的，全市场底座里没有这只票时它是唯一的口径。
            for row in _rows(conn.execute(
                    f"""SELECT symbol, industry FROM companies
                        WHERE symbol IN ({marks}){_sw()}""", symbols).fetchall()):
                facts[row["symbol"]].setdefault("industry", row["industry"])
                if not facts[row["symbol"]].get("industry"):
                    facts[row["symbol"]]["industry"] = row["industry"]

            # 分部构成：**只取年报**，跟 business_segments 同一条规矩——
            # 半年报是累计口径加季节性，跟年报放一起比出来的差异多半是日历造成的。
            for symbol in symbols:
                latest = conn.execute(
                    "SELECT max(report_date) AS d FROM business_segments "
                    "WHERE symbol = ? AND substr(report_date, 6) = '12-31'", (symbol,)).fetchone()
                if not (latest and latest["d"]):
                    continue
                facts[symbol]["segments"] = _rows(conn.execute(
                    "SELECT dimension, segment, revenue_share FROM business_segments "
                    "WHERE symbol = ? AND report_date = ?", (symbol, latest["d"])).fetchall())

        if company_ids:
            marks = ",".join("?" for _ in company_ids)
            by_company = {p["company_id"]: p["symbol"] for p in positions}
            for row in _rows(conn.execute(
                    f"""SELECT company_id, relation, counterpart, confidence
                        FROM supply_chain_links
                        WHERE company_id IN ({marks}){_swc()}""", company_ids).fetchall()):
                symbol = by_company.get(row["company_id"])
                if symbol:
                    facts.setdefault(symbol, {}).setdefault("chain", []).append(row)
            for row in _rows(conn.execute(
                    f"""SELECT company_id, counter_condition FROM theses
                        WHERE company_id IN ({marks}){_swc()}
                          AND counter_condition <> ''""", company_ids).fetchall()):
                symbol = by_company.get(row["company_id"])
                if symbol:
                    facts.setdefault(symbol, {}).setdefault(
                        "counters", []).append(row["counter_condition"])

        # 估值/市值的档位一律按**全市场**分位判，不按组合内部——
        # 组合内部永远有人在前 30%，那不叫贵。
        for key, column in (("market_pe", "pe_ttm"), ("market_pb", "pb"),
                            ("market_cap", "total_market_cap")):
            market[key] = sorted(
                float(row[column]) for row in conn.execute(
                    f"SELECT {column} FROM market_universe "
                    f"WHERE {column} IS NOT NULL AND {column} > 0").fetchall())

    view = portfolio_risk.analyze(positions, facts, market)
    return {"portfolio_id": portfolio_id, "portfolio_name": detail.get("name", ""),
            "amount_mode": detail.get("amount_mode", "full"), **view}


def valuation_drift(company_id: int) -> dict[str, Any] | None:
    """你的估值假设改过几次、每次是不是跟着股价走的。

    这是「不会心软的记录者」的第一个具体形态：数据早就在了（每次保存插一行、
    带着当时的股价），缺的只是有人把它摆回你面前。
    """
    from . import drift as dr

    company = get_company(company_id)
    if company is None:
        return None
    with connection() as conn:
        rows = _rows(conn.execute(
            f"SELECT * FROM valuations WHERE company_id = ?{_sw()} ORDER BY id",
            (company_id,)).fetchall())
        facts = _valuation_facts(conn, company)
        records = [{**row, "scenarios": json.loads(row["scenarios"])} for row in rows]

        changes = []
        for previous, current in zip(records, records[1:]):
            change = dr.compare(previous, current, facts)
            if not change.get("comparable"):
                continue
            context = _happened_between(conn, company,
                                        previous["created_at"], current["created_at"])
            reading = dr.read(change, context)
            if reading["level"] in ("none", "quiet"):
                # 噪音级的改动不往外报。**问得太频繁的机制会被整个关掉。**
                continue
            changes.append({"change": change, "context": context, "reading": reading})

    changes.reverse()      # 最近的排前面
    return {
        "company_id": company_id, "company_name": company["name"], "symbol": company["symbol"],
        "saves": len(records), "changes": changes,
        "summary": dr.summarize(changes),
        "open_questions": sum(1 for item in changes if item["reading"]["level"] == "ask"),
        "boundary": ("调高假设**可能完全正确**——世界真的会变。这里只摆事实并提出问题，"
                     "答案由你给。写成判决的话，判错时你会不再信它，"
                     "判对时你会开始绕开它——**一个你会绕开的诚实机制等于没有**。"),
    }


def save_valuation(company_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    """存假设。**每次存插一行**，最新的是当前值，旧的留着看你的判断怎么变的。"""
    from . import scenarios as sc

    company = get_company(company_id)
    if company is None:
        return None
    rows = []
    for item in payload.get("scenarios") or []:
        if item.get("key") not in sc.SCENARIO_KEYS:
            raise LedgerError(f"情景只能是 {'、'.join(sc.SCENARIO_KEYS)}")
        rows.append({"key": item["key"],
                     "revenue_growth": float(item["revenue_growth"]),
                     "net_margin": float(item["net_margin"]),
                     "exit_pe": float(item["exit_pe"])})
    if len(rows) != len(sc.SCENARIO_KEYS):
        raise LedgerError("三个情景要一起存：悲观、基准、乐观")

    with connection() as conn:
        price = conn.execute("SELECT price FROM market_universe WHERE symbol = ?",
                             (company["symbol"],)).fetchone()
        conn.execute(
            """INSERT INTO valuations (user_id, company_id, years, discount_rate,
                   scenarios, price_at_write, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (_stamp(), company_id, int(payload.get("years") or sc.DEFAULT_YEARS),
             float(payload.get("discount_rate") or sc.DEFAULT_DISCOUNT),
             json.dumps(rows, ensure_ascii=False),
             # 写下时的股价推不出来，而复盘时"我当时是在什么价位这么想的"最要紧
             (dict(price).get("price") if price else None),
             str(payload.get("note") or "")[:2000], now_iso()))
    return company_valuation(company_id)


def refresh_market_trend() -> dict[str, Any]:
    """全市场趋势面。走同花顺榜单，不走被挡住的东财。

    **只重置这一轮真取到的那几组列。** 四个榜单是四个独立的请求，任何一个挂了
    都不该让另外三个的数据被清零——第一版是只要主力那份成功就整表重置，于是
    另外三个挂掉时 above_ma60 与 new_high_level 被刷成 0，「趋势突破型」和
    「创新高型」当天筛出 0 只，而作业还报「成功」、页面还提示"去跑一次趋势面"。

    顺手把 `turnover_rate` 也填上：它在库里长期是 0% 覆盖（新浪快照不给），
    而千股千评那份已经在同步了，白拿。
    """
    from .providers.akshare_trend import COLUMN_GROUPS, RESET_VALUES

    payload = fetch_market_trend()
    timestamp = now_iso()
    synced: list[str] = list(payload["synced"])
    expected: list[str] = list(payload["expected"])
    columns = [name for group in synced for name in COLUMN_GROUPS[group]]

    with connection() as conn:
        # 先把取到的那几列刷成"不在榜上"，再写榜上的值。
        # 「不在量价齐升榜上」是一个事实（= 0 天），跟「没同步过」（NULL）不是一回事；
        # 不刷的话，昨天上榜今天掉下来的票会一直留着昨天的值，
        # 而那看起来跟"它今天还在榜上"一模一样。
        if columns:
            assignments = ", ".join(f"{name} = ?" for name in columns)
            conn.execute(
                f"UPDATE market_universe SET {assignments}, trend_source = ?, trend_as_of = ?",
                tuple(RESET_VALUES[name] for name in columns) + (payload["source"], timestamp))
        written = 0
        for row in payload["rows"]:
            assignments = ", ".join(f"{name} = ?" for name in columns)
            written += conn.execute(
                f"UPDATE market_universe SET {assignments} WHERE symbol = ?",
                tuple(row[name] for name in columns) + (row["symbol"],)).rowcount
        # 换手率来自千股千评（情绪面那一份），底座自己的源给不了。
        turnover = conn.execute(
            """UPDATE market_universe SET turnover_rate = (
                   SELECT s.turnover_rate FROM market_sentiment s WHERE s.symbol = market_universe.symbol)
               WHERE EXISTS (SELECT 1 FROM market_sentiment s
                             WHERE s.symbol = market_universe.symbol AND s.turnover_rate IS NOT NULL)"""
        ).rowcount

    missing = [g for g in expected if g not in synced]
    notes = list(payload["notes"])
    if missing:
        # 说清楚哪几列是旧的。**不说的话，一份缺了两列的数据看起来跟完整的一模一样。**
        stale = "、".join(name for g in missing for name in COLUMN_GROUPS[g])
        notes.append(f"这几列没能刷新，保留的是上一次的值：{stale}")
    return {
        "status": "成功" if not missing else "部分失败",
        "rows": len(payload["rows"]),
        "matched": written,
        "turnover_filled": turnover,
        "synced": synced,
        "missing": missing,
        "source": payload["source"],
        "notes": notes,
    }


def trend_summary() -> dict[str, Any]:
    """趋势面的覆盖与新鲜度。"""
    with connection() as conn:
        row = dict(conn.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(CASE WHEN rising_days > 0 THEN 1 END) AS rising,
                      COUNT(CASE WHEN above_ma60 > 0 THEN 1 END) AS above_ma,
                      COUNT(CASE WHEN new_high_level > 0 THEN 1 END) AS new_high,
                      COUNT(turnover_rate) AS turnover,
                      MAX(trend_as_of) AS updated_at, MAX(trend_source) AS source
               FROM market_universe""").fetchone())
    return {
        "total": row["total"] or 0,
        "rising": row["rising"] or 0,
        "above_ma60": row["above_ma"] or 0,
        "new_high": row["new_high"] or 0,
        "turnover": row["turnover"] or 0,
        "updated_at": row["updated_at"],
        "source": row["source"] or "",
        "reading": ("榜单是当日快照，明天就换一批；阶段涨幅的窗口每只票都不一样，"
                    "当排序用可以，当收益率读就错了。"),
    }


def sentiment_summary() -> dict[str, Any]:
    """情绪面的覆盖与新鲜度。页面靠它判断这一列能不能信。"""
    with connection() as conn:
        row = dict(conn.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(attention_rank) AS ranked,
                      COUNT(xq_followers) AS followed,
                      MAX(trade_date) AS trade_date,
                      MAX(updated_at) AS updated_at,
                      MAX(source) AS source
               FROM market_sentiment""").fetchone())
    return {
        "total": row["total"] or 0,
        "ranked": row["ranked"] or 0,
        "followed": row["followed"] or 0,
        "trade_date": row["trade_date"],
        "updated_at": row["updated_at"],
        "source": row["source"] or "",
        "reading": ("人气要反着读：排名越靠前说明讨论得越充分，能想到的理由多半已经在价格里了。"
                    "对着眼长期的研究者，「别人还没看见」才是稀缺的。"),
    }


def universe_summary() -> dict[str, Any]:
    """底座的覆盖范围与字段完整度；没有数据时也要说清楚缺什么。"""

    with connection() as conn:
        total = int(conn.execute("SELECT COUNT(*) AS c FROM market_universe").fetchone()["c"])
        snapshot = _one_or_none(
            conn.execute("SELECT * FROM universe_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        )
        if total == 0:
            return {
                "total": 0,
                "boards": [],
                "indexes": [],
                "completeness": [],
                "last_snapshot": snapshot,
                "coverage": "尚未建立全市场底座；点击“立即运行”后会抓取全 A 与主要指数",
            }
        boards = _rows(conn.execute("SELECT board AS name, COUNT(*) AS count FROM market_universe GROUP BY board ORDER BY count DESC").fetchall())
        indexes = _rows(
            conn.execute(
                "SELECT index_code, index_name, COUNT(*) AS count FROM index_members GROUP BY index_code, index_name ORDER BY index_code"
            ).fetchall()
        )
        fields = (
            ("price", "最新价"),
            ("pe_ttm", "市盈率 TTM"),
            ("pb", "市净率"),
            ("total_market_cap", "总市值"),
            ("roe", "净资产收益率"),
            ("gross_margin", "销售毛利率"),
            ("revenue_growth", "营收同比"),
            ("net_profit_growth", "净利润同比"),
            ("ocf_per_share", "每股经营现金流"),
            ("ytd_change", "年初至今涨跌"),
        )
        completeness = []
        for column, label in fields:
            filled = int(conn.execute(f"SELECT COUNT(*) AS c FROM market_universe WHERE {column} IS NOT NULL").fetchone()["c"])
            completeness.append({"field": column, "label": label, "filled": filled, "ratio": round(filled / total * 100, 1)})
        report_date = _one_or_none(conn.execute("SELECT report_date FROM market_universe WHERE report_date IS NOT NULL LIMIT 1").fetchone())
        history = conn.execute(
            "SELECT COUNT(DISTINCT point_date) AS days, MIN(point_date) AS first_date FROM universe_valuation_history"
        ).fetchone()
    valuation_days = int(history["days"] or 0)
    return {
        "total": total,
        "boards": boards,
        "indexes": indexes,
        "completeness": completeness,
        "last_snapshot": snapshot,
        "report_date": (report_date or {}).get("report_date"),
        "valuation_history_days": valuation_days,
        "valuation_history_start": history["first_date"],
        "valuation_history_note": (
            f"全市场估值历史已自建 {valuation_days} 个交易日"
            + (f"（自 {history['first_date']} 起）" if history["first_date"] else "")
            + "；累计满 250 个交易日后才会给出全市场 PE/PB 分位，在此之前只显示当期值。"
        ),
        "coverage": f"覆盖 {total} 只 A 股与 {len(indexes)} 个主要指数；财务口径为 {(report_date or {}).get('report_date') or '未同步'} 报告期",
    }


def universe_sample(limit: int = 20, board: str | None = None) -> list[dict[str, Any]]:
    with connection() as conn:
        sql = "SELECT * FROM market_universe"
        params: list[Any] = []
        if board:
            sql += " WHERE board = ?"
            params.append(board)
        sql += " ORDER BY total_market_cap DESC NULLS LAST, symbol LIMIT ?"
        params.append(limit)
        return _rows(conn.execute(sql, params).fetchall())


# --- 价值候选清单与策略库 -------------------------------------------------
# 不设条件也能出候选：预置策略开箱可用；每套策略声明依赖字段与已知偏差，
# 字段缺失时该策略不可用并说明原因。输出是"接下来研究哪几家"，不是买入建议。

MIN_FIELD_COVERAGE = 50.0

# **空值是答案、不是缺口的字段。** 它们不受覆盖度闸门管。
#
# 「阶段涨幅」只对当下在量价齐升榜上的票有意义 —— providers/akshare_trend.py
# 写得很清楚：「没上榜就没有"阶段涨幅"这回事，0 会被当成'涨了 0%'」，
# 所以它存 NULL。线上 17% 的覆盖度说的是「17% 的股票现在处在那个状态」，
# 不是「83% 的数据没取到」。拿覆盖度去关它，等于把这两句话当成一句。
#
# 股息率同理：不分红的公司没有股息率，那是事实不是缺失。
#
# **这条不是给覆盖度开后门。** 覆盖度照常量、照常显示，
# 只是不用它来判「这个字段能不能用」——对这几个字段，那个判断本身没有意义。
CONDITIONAL_FIELDS = ("stage_gain", "stage_turnover", "dividend_yield", "dividend_per_10")
# 派生字段：库里没有这一列，值是现算的。**列全**——漏一个在这里，
# 它就会走到下面那条"按列名量覆盖"的路上，量到 0、然后被永久关掉。
DERIVED_FIELDS = ("cash_ratio", "peg", "graham_number", "earnings_yield", "pb_over_roe")
DERIVED_SOURCES = {
    "cash_ratio": ("eps", "ocf_per_share"),
    "peg": ("pe_ttm", "net_profit_growth"),
    "graham_number": ("pe_ttm", "pb"),
    "earnings_yield": ("pe_ttm",),
    "pb_over_roe": ("pb", "roe"),
}


def _universe_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(conn.execute("SELECT * FROM market_universe").fetchall())


def _field_coverage(conn: sqlite3.Connection) -> tuple[dict[str, float], int]:
    """每个可筛字段在底座里的完整度。

    **量的是 FIELD_LABELS 里的每一个字段，不是一张手写的列名单。**

    原来这里写死了 11 列。而条件编辑器列出 27 个字段 —— 剩下那些
    `coverage.get(name, 0.0)` 取到默认 0，`usable = 0 >= 50` 恒为假，
    于是**永久不可用，且理由是"完整度不足"**。

    2026-08-15 线上实测，被这么关掉的 13 个里有 9 个数据是齐的：

        annual_roe 99.0%   annual_gross_margin 98.1%   dividend_yield 65.3%
        rising_days 100%   above_ma60 100%   new_high_level 100%
        volume_days 100%   turnover_rate 93.7%   dividend_per_10 65.3%

    代价是实打实的：用户说「净资产收益率高于 12%」，能筛的只剩**单季** roe。
    茅台单季 10.57 / 年报 32.53，汾酒单季 12.57 / 年报 33.48 ——
    按单季筛，汾酒进了、茅台被排除，而这跟他要的东西正好相反。
    文档里那套「待数据的股息现金流型」策略也是这么"待"下来的，
    股息率的数一直都在。
    """
    total = int(conn.execute("SELECT COUNT(*) AS c FROM market_universe").fetchone()["c"])
    if total == 0:
        return {}, 0
    # **逐列去问，问不到就跳过。** 不写死列名（那正是上面那个 bug 的形状），
    # 也不靠"取一行看看有哪些键"——表是空的时候那条路什么都认不出来。
    coverage: dict[str, float] = {}
    for column in FIELD_LABELS:
        if column in DERIVED_FIELDS:      # 派生字段没有对应列，按来源算，见 screen_fields
            continue
        try:
            filled = int(conn.execute(
                f"SELECT COUNT({column}) AS c FROM market_universe").fetchone()["c"])
        except Exception:                 # noqa: BLE001  这一列库里没有，不是错
            continue
        coverage[column] = round(filled / total * 100, 1)
    return coverage, total


def _saved_strategies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _rows(conn.execute(f"SELECT * FROM screen_strategies WHERE 1=1{_sw()} ORDER BY id").fetchall())
    for row in rows:
        row["rules"] = json.loads(row["rules"])
        row["biases"] = json.loads(row["biases"])
    return rows


def _strategy_payload(strategy: Strategy) -> dict[str, Any]:
    return {
        "key": strategy.key,
        "name": strategy.name,
        "summary": strategy.summary,
        "provenance": strategy.provenance,
        "biases": list(strategy.biases),
        "rules": [{"field": rule.field, "op": rule.op, "value": rule.value, "unit": rule.unit, "text": rule.text} for rule in strategy.rules],
        "sort_field": strategy.sort_field,
        "sort_desc": strategy.sort_desc,
        "sort_label": strategy.sort_label,
        "preset": True,
        "kind": strategy.kind,
        "forked_from": None,
        "required_fields": list(strategy.required_fields),
    }


def _saved_payload(row: dict[str, Any]) -> dict[str, Any]:
    rules = [Rule(**{key: item[key] for key in ("field", "op", "value", "unit") if key in item}) for item in row["rules"]]
    return {
        "key": row["key"],
        "name": row["name"],
        "summary": row["summary"],
        "provenance": row["provenance"] or "由你自己设定",
        "biases": row["biases"],
        "rules": [{"field": rule.field, "op": rule.op, "value": rule.value, "unit": rule.unit, "text": rule.text} for rule in rules],
        "sort_field": row["sort_field"],
        "sort_desc": bool(row["sort_desc"]),
        "sort_label": row["sort_label"],
        "preset": False,
        # 自定义策略的口味按它实际用了哪些字段推出来，跟预置那边同一条规则
        # （Strategy.kind）。这样你自己配一套趋势条件，它会自动落进趋势池。
        "kind": "trend" if any(rule.field in TREND_FIELDS for rule in rules) else "value",
        "forked_from": row["forked_from"],
        "required_fields": list(dict.fromkeys([rule.field for rule in rules] + [row["sort_field"]])),
    }


def list_screen_strategies() -> list[dict[str, Any]]:
    with connection() as conn:
        coverage, total = _field_coverage(conn)
        saved = [_saved_payload(row) for row in _saved_strategies(conn)]
    payloads = [_strategy_payload(strategy) for strategy in PRESETS] + saved
    for payload in payloads:
        preset = PRESETS_BY_KEY.get(payload["key"])
        if preset and not preset.available:
            payload["available"] = False
            payload["unavailable_reason"] = preset.unavailable_reason
            continue
        if total == 0:
            payload["available"] = False
            payload["unavailable_reason"] = "全市场底座还没有数据，先在数据状态页运行一次“全市场底座”"
            continue
        missing = []
        for name in payload["required_fields"]:
            parts = DERIVED_SOURCES.get(name, (name,))
            if any(coverage.get(part, 0.0) < MIN_FIELD_COVERAGE for part in parts
                   if part in coverage and part not in CONDITIONAL_FIELDS):
                missing.append(FIELD_LABELS.get(name, name))
        payload["available"] = not missing
        payload["unavailable_reason"] = None if not missing else f"底座里这些字段的完整度不足 {MIN_FIELD_COVERAGE:g}%：{('、').join(missing)}"
    return payloads


def _rules_of(payload: dict[str, Any]) -> list[Rule]:
    return [Rule(field=item["field"], op=item["op"], value=float(item["value"]), unit=item.get("unit", "")) for item in payload["rules"]]


def _evaluate(rows: list[dict[str, Any]], rules: list[Rule]) -> list[dict[str, Any]]:
    matched = []
    for row in rows:
        checks = [check_rule(row, rule) for rule in rules]
        if checks and all(check["passed"] for check in checks):
            matched.append({"row": row, "checks": checks})
    return matched


SCREEN_FIELD_HINTS = {
    "pe_ttm": ("倍", "越低越便宜，但低 PE 也可能是盈利见顶"),
    "pb": ("倍", "越低越接近账面价值，重资产行业天然更低"),
    "roe": ("%", "越高越好，但可能靠高杠杆撑起来"),
    "gross_margin": ("%", "越高说明定价权越强，行业之间不可直接比"),
    "revenue_growth": ("%", "单期同比，低基数会放大"),
    "net_profit_growth": ("%", "单期同比，一次性收益会放大"),
    "net_profit": ("元", "用来排除亏损公司"),
    "eps": ("元", "每股收益"),
    "bps": ("元", "每股净资产"),
    "ocf_per_share": ("元", "每股经营现金流，大于 0 表示经营在回款"),
    "total_market_cap": ("元", "用来排除过小的公司"),
    "cash_ratio": ("%", "经营现金流对利润的覆盖度，一次性损益会失真"),
    "peg": ("倍", "市盈率除以单期增速，对增长持续性无能为力"),
    "graham_number": ("", "PE 与 PB 的乘积"),
}


def screen_fields() -> list[dict[str, Any]]:
    """条件编辑器可选的字段：带口径提示与底座里的完整度，避免设出跑不了的条件。"""

    with connection() as conn:
        coverage, total = _field_coverage(conn)
    fields = []
    for name, label in FIELD_LABELS.items():
        unit, hint = SCREEN_FIELD_HINTS.get(name, ("", ""))
        derived = name in DERIVED_FIELDS
        if derived:
            parts = DERIVED_SOURCES[name]
            ratio = min((coverage.get(part, 0.0) for part in parts), default=0.0) if total else 0.0
        else:
            ratio = coverage.get(name, 0.0) if total else 0.0
        fields.append({
            "field": name,
            "label": label,
            "unit": unit,
            "hint": hint,
            "derived": derived,
            "coverage": ratio,
            "usable": ratio >= MIN_FIELD_COVERAGE or name in CONDITIONAL_FIELDS,
        })
    return fields


def delete_screen_strategy(key: str) -> bool:
    if key in PRESETS_BY_KEY:
        raise LedgerError("预置策略不能删除；可以复制一份再改。")
    with connection() as conn:
        cursor = conn.execute(f"DELETE FROM screen_strategies WHERE key = ?{_sw()}", (key,))
        return bool(cursor.rowcount)


def run_screen(
    strategy_key: str | None = None,
    limit: int = 30,
    record: bool = True,
    ad_hoc: dict[str, Any] | None = None,
    sort_field: str | None = None,
    sort_desc: bool | None = None,
    only_symbols: set[str] | None = None,
    only_industries: list[str] | None = None,
) -> dict[str, Any] | None:
    """跑一套规则。

    `only_symbols` / `only_industries` 把候选面先收窄再跑规则，AI 选股用它来
    落地「概念」和「行业」这两种规则表达不了的限定。**必须先收窄再筛，
    不能先筛再收窄**：先跑数值条件取前 200 名、再从里面挑概念成分股，
    多半一家都剩不下——概念成分股本来就是全市场里的几十只，
    它们没有任何理由出现在按 PE 排序的前 200 名里。

    收窄之后 `universe_total` 报的是收窄后的样本数，不是 5541——
    这是**故意的**：那一栏问的是「这次是在多大范围里筛的」。

    `sort_field` / `sort_desc` 是**只影响这一次查看**的覆盖，不写回策略。
    分开的理由：规则是策略的一部分（该跟着策略走），排序和条数是**看的方式**
    （该跟着你当下的问题走）。原来两者绑在一起，想换个排法就得改策略、保存，
    把策略库弄脏——于是实际上没人换，所有人只能看那一种顺序。
    """
    strategies = {item["key"]: item for item in list_screen_strategies()}
    if ad_hoc is not None:
        target = {
            "key": "ad_hoc",
            "name": ad_hoc.get("name") or "临时条件",
            "summary": "尚未保存的条件，只用于这次试跑",
            "provenance": ad_hoc.get("provenance") or "由你临时设定",
            "biases": ad_hoc.get("biases") or ["这是临时条件，还没有沉淀成一套有出处的策略；结论同样只是研究起点。"],
            "rules": ad_hoc["rules"],
            "sort_field": ad_hoc["sort_field"],
            "sort_desc": ad_hoc.get("sort_desc", True),
            "sort_label": ad_hoc.get("sort_label") or "自定义排序",
            "preset": False,
            "forked_from": ad_hoc.get("forked_from"),
            "required_fields": list(dict.fromkeys([rule["field"] for rule in ad_hoc["rules"]] + [ad_hoc["sort_field"]])),
        }
        with connection() as conn:
            coverage, total = _field_coverage(conn)
        if total == 0:
            raise LedgerError("全市场底座还没有数据，先在数据状态页运行一次“全市场底座”")
        missing = []
        for name in target["required_fields"]:
            parts = DERIVED_SOURCES.get(name, (name,))
            if any(coverage.get(part, 0.0) < MIN_FIELD_COVERAGE for part in parts if part in coverage):
                missing.append(FIELD_LABELS.get(name, name))
        if missing:
            raise LedgerError(f"底座里这些字段的完整度不足 {MIN_FIELD_COVERAGE:g}%：{('、').join(missing)}")
        target["available"] = True
        target["unavailable_reason"] = None
        strategy_key = "ad_hoc"
    else:
        target = strategies.get(strategy_key or "")
        if not target:
            return None
        if not target["available"]:
            raise LedgerError(target["unavailable_reason"] or "这套策略当前不可用")

    with connection() as conn:
        rows = _universe_rows(conn)
        watched = {row["symbol"] for row in conn.execute(f"SELECT symbol FROM companies WHERE 1=1{_sw()}").fetchall()}
        index_members = _rows(conn.execute("SELECT symbol, index_name FROM index_members").fetchall())
    if only_symbols is not None:
        rows = [row for row in rows if row["symbol"] in only_symbols]
    if only_industries:
        rows = [row for row in rows if row["industry"] in set(only_industries)]
    membership: dict[str, list[str]] = {}
    for member in index_members:
        membership.setdefault(member["symbol"], []).append(member["index_name"])

    matched = _evaluate(rows, _rules_of(target))
    # 交集：同一批数据下，还有哪几套（逻辑不同的）策略也选中了它
    others = {
        item["key"]: {entry["row"]["symbol"] for entry in _evaluate(rows, _rules_of(item))}
        for item in strategies.values()
        if item["key"] != strategy_key and item["available"] and item["rules"]
    }
    # 本次查看的覆盖（不写回策略）。给了就用，没给就用策略自己声明的。
    if sort_field:
        target = {**target, "sort_field": sort_field,
                  "sort_desc": target["sort_desc"] if sort_desc is None else sort_desc,
                  "sort_label": f"{FIELD_LABELS.get(sort_field, sort_field)}由{'高到低' if (target['sort_desc'] if sort_desc is None else sort_desc) else '低到高'}"}
    elif sort_desc is not None:
        target = {**target, "sort_desc": sort_desc,
                  "sort_label": f"{FIELD_LABELS.get(target['sort_field'], target['sort_field'])}由{'高到低' if sort_desc else '低到高'}"}
    sort_field = target["sort_field"]
    for entry in matched:
        symbol = entry["row"]["symbol"]
        entry["also"] = [strategies[key]["name"] for key, symbols in others.items() if symbol in symbols]
        entry["sort_value"] = value_of(entry["row"], sort_field)
    # **排序的第一关键字是「被几套策略同时选中」，不是 sort_field。**
    # 这一条页面上一直没说，而卡片上写着「按 PEG 由低到高」——于是列表第一条
    # 是「另有 2 套策略也选中」的那家，而不是 PEG 最低的那家，看起来像排错了。
    # 逻辑本身是对的（多套规则同时看中，比单项指标更值得先看），
    # 错的是没把它说出来。现在 sort_explain 把两级都写清楚。
    matched.sort(
        key=lambda entry: (
            -len(entry["also"]),
            -(entry["sort_value"] or 0) if target["sort_desc"] else (entry["sort_value"] if entry["sort_value"] is not None else float("inf")),
        )
    )

    candidates = []
    for entry in matched[:limit]:
        row = entry["row"]
        candidates.append(
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "board": row["board"],
                "industry": row["industry"],
                "price": row["price"],
                "change_percent": row["change_percent"],
                "total_market_cap": row["total_market_cap"],
                "report_date": row["report_date"],
                "price_as_of": row["price_as_of"],
                "in_indexes": membership.get(row["symbol"], []),
                "in_research_pool": row["symbol"] in watched,
                "also_matched": entry["also"],
                "sort_value": entry["sort_value"],
                "checks": entry["checks"],
            }
        )

    report_date = next((row["report_date"] for row in rows if row["report_date"]), None)
    price_as_of = next((row["price_as_of"] for row in rows if row["price_as_of"]), None)
    if record:
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO screen_runs (user_id, strategy_key, strategy_name, rules, universe_total, matched,
                    report_date, price_as_of, executed_at, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _stamp(),
                    strategy_key,
                    target["name"],
                    json.dumps(target["rules"], ensure_ascii=False),
                    len(rows),
                    len(matched),
                    report_date,
                    price_as_of,
                    now_iso(),
                    f"排序：{target['sort_label']}；同一批数据下的多策略交集优先",
                ),
            )
    return {
        "strategy": target,
        "universe_total": len(rows),
        "matched": len(matched),
        "returned": len(candidates),
        # **把排序说全。** 页面原来只显示 sort_label（「按 PEG 由低到高」），
        # 而实际的第一关键字是「被几套策略同时选中」——于是列表第一条是
        # 「另有 2 套策略也选中」的那家而不是 PEG 最低的，看起来像排错了。
        # 逻辑本身对（多套规则同时看中，比单项指标更值得先看），错在没说出来。
        "sort_explain": f"先按命中几套规则，再按{target['sort_label']}",
        "report_date": report_date,
        "price_as_of": price_as_of,
        "candidates": candidates,
        "boundary": "这是一份研究起点清单：它只说明这些公司符合你选的条件，不代表值得买入。是否成立仍要逐家看生意、管理层与价格。",
    }


def save_screen_strategy(payload: ScreenStrategySave) -> dict[str, Any]:
    source = PRESETS_BY_KEY.get(payload.forked_from) if payload.forked_from else None
    timestamp = now_iso()
    rules = [{"field": rule.field, "op": rule.op, "value": rule.value, "unit": rule.unit} for rule in payload.rules]
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO screen_strategies (user_id, key, name, summary, provenance, biases, rules, sort_field,
                sort_desc, sort_label, forked_from, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
                name = excluded.name, summary = excluded.summary, rules = excluded.rules,
                sort_field = excluded.sort_field, sort_desc = excluded.sort_desc,
                sort_label = excluded.sort_label, updated_at = excluded.updated_at
            """,
            (
                _stamp(),
                payload.key,
                payload.name,
                payload.summary,
                f"从预置策略「{source.name}」复制后自行调整" if source else "由你自己设定",
                json.dumps(list(source.biases) if source else [], ensure_ascii=False),
                json.dumps(rules, ensure_ascii=False),
                payload.sort_field,
                1 if payload.sort_desc else 0,
                payload.sort_label or "自定义排序",
                payload.forked_from,
                timestamp,
                timestamp,
            ),
        )
    return next(item for item in list_screen_strategies() if item["key"] == payload.key)


def list_screen_runs(limit: int = 20) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = _rows(conn.execute(f"SELECT * FROM screen_runs WHERE 1=1{_sw()} ORDER BY id DESC LIMIT ?", (limit,)).fetchall())
    for row in rows:
        row["rules"] = json.loads(row["rules"])
    return rows


def save_candidate_review(payload) -> dict[str, Any]:
    """把一次模型复核结果作为研究资产保存，不重新调用模型。"""

    timestamp = now_iso()
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO candidate_review_runs
                (user_id, strategy_key, strategy_name, width, rows, note, boundary, estimated_credits, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _stamp(),
                payload.strategy_key,
                payload.strategy_name,
                payload.width,
                json.dumps(payload.rows, ensure_ascii=False),
                payload.note,
                payload.boundary,
                payload.estimated_credits,
                timestamp,
            ),
        )
        review_id = int(cursor.lastrowid)
    return get_candidate_review(review_id) or {}


def get_candidate_review(review_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        row = _one_or_none(conn.execute(
            f"SELECT * FROM candidate_review_runs WHERE id = ?{_sw()}", (review_id,)).fetchone())
    if not row:
        return None
    row["rows"] = json.loads(row.get("rows") or "[]")
    return row


def latest_candidate_review(strategy_key: str, width: int | None = None) -> dict[str, Any] | None:
    width_sql = " AND width = ?" if width is not None else ""
    params: tuple[Any, ...] = (strategy_key, width) if width is not None else (strategy_key,)
    with connection() as conn:
        row = _one_or_none(conn.execute(
            f"SELECT * FROM candidate_review_runs WHERE strategy_key = ?{width_sql}{_sw()} ORDER BY id DESC LIMIT 1",
            params,
        ).fetchone())
    if not row:
        return None
    row["rows"] = json.loads(row.get("rows") or "[]")
    return row


def candidate_review_target(strategy_key: str, strategy_name: str, width: int) -> dict[str, Any]:
    """为找票复核取得稳定的后台任务目标。

    后台任务的 target_id 不能直接用字符串策略名；单独的目标表把
    ``策略 + 宽度`` 映射成一个稳定整数，页面切换回来仍能找到同一任务。
    """

    timestamp = now_iso()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO candidate_review_targets
                (user_id, strategy_key, strategy_name, width, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, strategy_key, width) DO UPDATE SET
                strategy_name = excluded.strategy_name,
                updated_at = excluded.updated_at
            """,
            (_stamp(), strategy_key, strategy_name, width, timestamp, timestamp),
        )
        row = _one_or_none(conn.execute(
            f"SELECT * FROM candidate_review_targets WHERE strategy_key = ? AND width = ?{_sw()}",
            (strategy_key, width),
        ).fetchone())
    return row or {}


def _reuse_candidate_review(task_id: int, strategy_key: str | None) -> int:
    """把同一套策略最近一次找票评语带进研究任务，不重复烧一次模型费。

    只补还没有结论的条目；用户已经写过的结论永远优先。找票与研究任务
    共享的是同一份「结论 / 支持 / 待核实」资产，而不是只共享一套 CSS。
    """

    if not strategy_key:
        return 0
    saved = latest_candidate_review(strategy_key)
    if not saved:
        return 0
    by_symbol = {str(row.get("symbol")): row for row in saved.get("rows") or []}
    if not by_symbol:
        return 0
    changed = 0
    with connection() as conn:
        items = _rows(conn.execute(
            f"SELECT id, symbol FROM research_task_items WHERE task_id = ? AND (conclusion IS NULL OR conclusion = '')",
            (task_id,),
        ).fetchall())
        for item in items:
            review = by_symbol.get(str(item["symbol"]))
            if not review:
                continue
            conclusion = str(review.get("conclusion") or review.get("reason") or "").strip()
            if not conclusion:
                continue
            conn.execute(
                """UPDATE research_task_items
                   SET conclusion = ?, verdict = ?, reasons = ?, concerns = ?, updated_at = ?
                   WHERE id = ? AND (conclusion IS NULL OR conclusion = '')""",
                (
                    conclusion,
                    str(review.get("verdict") or "先放着"),
                    json.dumps(review.get("reasons") or [], ensure_ascii=False),
                    json.dumps(review.get("concerns") or [], ensure_ascii=False),
                    now_iso(),
                    item["id"],
                ),
            )
            changed += 1
    return changed


# --- 市场云图 -------------------------------------------------------------
# 面积用总市值，颜色用所选指标。比率类指标在行业层用中位数聚合而不是平均值：
# 单只极端值（例如亏损公司的负 PE）会把整个行业的平均值拉到没有意义。

HEATMAP_METRICS = {
    "roe": {"label": "净资产收益率", "unit": "%", "kind": "sequential", "note": "来自最新报告期业绩报表"},
    "gross_margin": {"label": "销售毛利率", "unit": "%", "kind": "sequential", "note": "行业之间不可直接比较"},
    "revenue_growth": {"label": "营收同比", "unit": "%", "kind": "diverging", "note": "单期同比，低基数会放大"},
    "net_profit_growth": {"label": "净利润同比", "unit": "%", "kind": "diverging", "note": "单期同比，一次性收益会放大"},
    "pe_ttm": {"label": "市盈率 TTM", "unit": "倍", "kind": "sequential", "note": "只反映当期估值高低，不代表贵或便宜"},
    "pb": {"label": "市净率", "unit": "倍", "kind": "sequential", "note": "重资产行业天然更低"},
    "ytd_change": {"label": "年初至今涨跌", "unit": "%", "kind": "diverging", "note": "区间价格变化，不含分红再投资"},
    "change_60d": {"label": "近 60 日涨跌", "unit": "%", "kind": "diverging", "note": "区间价格变化，不构成任何判断"},
    "change_percent": {"label": "当日涨跌", "unit": "%", "kind": "diverging", "note": "只是当天的价格变化，不构成任何判断"},
    "change_5d": {"label": "近 5 日涨跌", "unit": "%", "kind": "diverging", "note": "由自建日线算出，接入时间不足时为空"},
    "change_20d": {"label": "近 20 日涨跌", "unit": "%", "kind": "diverging", "note": "由自建日线算出，接入时间不足时为空"},
    "turnover_rate": {"label": "换手率", "unit": "%", "kind": "sequential", "note": "只表示交易活跃度，不等同于资金净流入"},
    "abs_change": {"label": "当日波动幅度", "unit": "%", "kind": "sequential", "note": "取当日涨跌幅绝对值，只描述波动大小，不表示方向"},
    "attention_index": {"label": "市场关注度", "unit": "", "kind": "sequential", "note": "来自东方财富千股千评，口径不公开，只用于横向观察"},
}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return round(ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2, 2)


UNIVERSE_PERCENTILE_MIN_DAYS = 250


def universe_valuation_percentile(symbol: str, metric: str = "pe_ttm") -> dict[str, Any]:
    """用自建的全市场估值历史算分位；样本不足时不给数字，只说明还差多少。"""

    column = "pe_ttm" if metric == "pe_ttm" else "pb"
    with connection() as conn:
        rows = _rows(
            conn.execute(
                f"SELECT point_date, {column} AS value FROM universe_valuation_history WHERE symbol = ? AND {column} IS NOT NULL ORDER BY point_date",
                (symbol,),
            ).fetchall()
        )
    if not rows:
        return {"symbol": symbol, "metric": metric, "current": None, "percentile": None, "sample_size": 0,
                "sample_start": None, "sample_end": None,
                "unavailable_reason": "还没有这只股票的全市场估值历史；每次同步底座会累积一天"}
    values = [float(row["value"]) for row in rows]
    current = values[-1]
    if len(values) < UNIVERSE_PERCENTILE_MIN_DAYS:
        return {"symbol": symbol, "metric": metric, "current": round(current, 2), "percentile": None,
                "sample_size": len(values), "sample_start": rows[0]["point_date"], "sample_end": rows[-1]["point_date"],
                "unavailable_reason": f"自建历史只有 {len(values)} 个交易日，少于 {UNIVERSE_PERCENTILE_MIN_DAYS} 天，暂不给分位"}
    return {"symbol": symbol, "metric": metric, "current": round(current, 2),
            "percentile": _percentile_of(values, current), "sample_size": len(values),
            "sample_start": rows[0]["point_date"], "sample_end": rows[-1]["point_date"], "unavailable_reason": None}


# --- 云图为什么原来要等一秒半 ---------------------------------------------
#
# 首屏一次要四张云图（当日涨跌铺主图，另外三个只为算三个中位数）。四发请求读的
# 是**同一份 5541 行全市场底座**，而原来每一发都 `SELECT u.*` 全表扫一遍。
#
# 实测：单发 180ms，四发并发变成**各自 650ms**——它们不是并行，是排队。聚合是
# 纯 Python，GIL 一次只放一个线程跑，四发就是四倍墙钟。前端又在 Promise.all
# 上等齐四份才画图，于是首屏 1.5 秒才见到第一块砖。
#
# 这里改两处：
#
#   1. **只取真的会用到的列。** u.* 是 46 列，psycopg 光把它们塞进 DictRow 就
#      897927 次 __setitem__、160ms；取 6 列是 27ms。剩下 40 列一个也没人读。
#   2. **把与用户无关的那一半缓存住。** 钥匙是底座自己的水位（最后同步时间 +
#      行数）：底座只在「同步实时行情」时变，中间怎么翻镜头都是同一份数据。
#
# **缓存里不许放跟数据域有关的东西。** `watched`（哪个行业里有你的公司）跟着
# RLS 的 app.scope 走，把它缓存进来就是把甲的自选发给乙——所以核心里只留每块
# 的成员代码，谁的灯塔谁自己点。这是全仓最容易在「优化」时捅出来的洞。
_HEATMAP_CACHE: dict[tuple[str, str, int], tuple[str, dict[str, Any]]] = {}
_HEATMAP_CACHE_LOCK = threading.Lock()
_HEATMAP_CACHE_MAX = 240

# 面积、广度、行业名永远要用到的列；镜头那一列另拼。
_HEATMAP_BASE_COLUMNS = ("symbol", "name", "industry", "total_market_cap", "change_percent")


def _universe_stamp(conn) -> str:
    """全市场底座的水位。它一变，所有云图缓存作废。自身 2.6ms，比缓存省下的便宜得多。"""

    row = conn.execute("SELECT MAX(updated_at) AS latest, COUNT(*) AS total FROM market_universe").fetchone()
    return f"{row['latest']}·{row['total']}"


def _heatmap_columns(metric: str) -> str:
    """镜头指标那一列。metric 已经过 HEATMAP_METRICS 白名单，拼进 SQL 是安全的。"""

    picks = [f"u.{name}" for name in _HEATMAP_BASE_COLUMNS]
    if metric == "attention_index":
        # 情绪面与底座分开同步：左连一次，情绪源挂了只是这一个镜头缺数，不拖垮整张图。
        picks.append("s.attention_index AS attention_index")
    elif metric != "abs_change" and metric not in _HEATMAP_BASE_COLUMNS:
        # abs_change 没有对应的列，它是 change_percent 取绝对值算出来的。
        picks.append(f"u.{metric}")
    return ", ".join(picks)


def _heatmap_core(conn, scope: str, metric: str, limit: int) -> dict[str, Any]:
    """云图里与「你是谁」无关的那一半：面积、颜色、广度、可选范围。可以缓存。"""

    meta = HEATMAP_METRICS[metric]
    params: list[Any] = []
    sql = f"SELECT {_heatmap_columns(metric)} FROM market_universe u"
    if metric == "attention_index":
        sql += " LEFT JOIN market_sentiment s ON s.symbol = u.symbol"
    scope_label = "全 A"
    if scope.startswith("index:"):
        code = scope.split(":", 1)[1]
        sql += " JOIN index_members m ON m.symbol = u.symbol AND m.index_code = ?"
        params.append(code)
        row = conn.execute("SELECT index_name FROM index_members WHERE index_code = ? LIMIT 1", (code,)).fetchone()
        scope_label = row["index_name"] if row else code
    elif scope.startswith("industry:"):
        industry = scope.split(":", 1)[1]
        sql += " WHERE u.industry = ?"
        params.append(industry)
        scope_label = industry
    elif scope.startswith("board:"):
        board = scope.split(":", 1)[1]
        sql += " WHERE u.board = ?"
        params.append(board)
        scope_label = board
    elif scope.startswith("exchange:"):
        exchange = scope.split(":", 1)[1]
        sql += " WHERE u.exchange = ?"
        params.append(exchange)
        scope_label = {"上海证券交易所": "沪市", "深圳证券交易所": "深市", "北京证券交易所": "北交所"}.get(exchange, exchange)
    rows = _rows(conn.execute(sql, params).fetchall())
    indexes = _rows(
        conn.execute("SELECT index_code, index_name, COUNT(*) AS count FROM index_members GROUP BY index_code, index_name ORDER BY index_code").fetchall()
    )

    # 波动镜头只取已存在的真实涨跌幅绝对值，不推算一个看起来很专业的波动率。
    for row in rows:
        move = row.get("change_percent")
        row["abs_change"] = abs(float(move)) if isinstance(move, (int, float)) else None

    # 涨跌家数比中位数更能反映广度：中位数会被几只权重股带偏，家数不会
    moves = [row["change_percent"] for row in rows if row.get("change_percent") is not None]
    breadth = {
        "advancing": sum(1 for value in moves if value > 0),
        "declining": sum(1 for value in moves if value < 0),
        "unchanged": sum(1 for value in moves if value == 0),
        "median_change": _median(moves),
        "covered": len(moves),
        "note": "涨跌家数按当日涨跌幅统计，停牌与无行情的不计入。它只描述当天的分布，不预示任何走向。",
    }

    level = "company" if scope.startswith("industry:") else "industry"
    with_metric = [row for row in rows if row.get(metric) is not None]
    # 市值是面积的首选口径；行情源降级时市值会整体缺失，这时退回按公司家数铺面积并写明。
    capped = [row for row in rows if row.get("total_market_cap") is not None]
    size_basis = "总市值" if len(capped) >= max(1, len(rows) // 2) else "公司家数（行情源未提供市值）"
    use_cap = size_basis == "总市值"

    def size_of(row: dict[str, Any]) -> float:
        return float(row["total_market_cap"]) if use_cap and row.get("total_market_cap") is not None else 1.0

    # 每块记下成员代码而不是「已建档公司」——后者跟着数据域走，不能进缓存。
    tiles: list[dict[str, Any]] = []
    if level == "company":
        ordered = sorted(rows, key=lambda item: (size_of(item), item.get(metric) or 0), reverse=True)
        for row in ordered[:limit]:
            if row.get(metric) is None:
                continue
            tiles.append({
                "name": row["name"],
                "symbol": row["symbol"],
                "industry": row["industry"],
                "size": size_of(row),
                "metric_value": round(float(row[metric]), 2),
                "count": 1,
                "members": [row["symbol"]],
            })
    else:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            buckets.setdefault(row["industry"] or "未分类", []).append(row)
        for industry, members in buckets.items():
            values = [float(item[metric]) for item in members if item.get(metric) is not None]
            if not values:
                continue
            tiles.append({
                "name": industry,
                "symbol": None,
                "industry": industry,
                "size": sum(size_of(item) for item in members),
                "metric_value": _median(values),
                "count": len(members),
                "members": [item["symbol"] for item in members],
            })
        tiles.sort(key=lambda item: item["size"], reverse=True)
        tiles = tiles[:limit]

    # **数据自己的日期，不是今天。**
    #
    # 页面上原来印的是 `dashboard.as_of`（= date.today()），而云图和市场脉搏吃的是
    # market_universe —— 那张表由计划任务刷，顶栏那个「同步实时行情」根本不碰它
    # （它调的是 refresh_all_market_quotes，只刷你建过档的那几家）。
    # 于是 2026-08-17 开盘大涨的当天，页面顶着「2026-08-17」显示 08-14 收盘的
    # 「69% 股票下跌」。**日期标签在替一份过期数据背书**，比不写日期糟得多。
    # 用 price_as_of 而不是 updated_at：前者是**行情数据自己是哪一天的**，
    # 后者只是这一行什么时候被写过 —— 一次只补基本面的同步也会把它推到今天，
    # 那样这个日期又会替过期的行情背书，跟原来的 bug 一模一样。
    stale = _one_or_none(conn.execute(
        "SELECT max(price_as_of) AS at, max(price_source) AS src FROM market_universe"
    ).fetchone()) or {}
    # **降级要现形。**
    #
    # 主源（东方财富全市场快照）从服务器连不上时会退到新浪那一路，而新浪只给
    # 价格和涨跌幅 —— **没有 PE、PB、市值、换手率**。云图的面积按市值算、
    # 估值那几个镜头按 PE 算，于是它照常画出一张图，而那张图的面积和估值是缺的或旧的。
    # 状态只记在 sync_schedules.last_status（「降级」）里，页面上一个字都没有。
    # 2026-08-17 实测三次全是 ConnectionError，而首页看起来完全正常。
    source = str(stale.get("src") or "")
    return {
        "scope": scope,
        "scope_label": scope_label,
        "as_of": str(stale.get("at") or "")[:19],
        "source": source,
        # 新浪那一路缺的就是云图最吃的那几个字段，所以这里直接说缺了什么。
        "degraded": "降级" in source,
        "missing_fields": ["市盈率", "市净率", "市值", "换手率"] if "降级" in source else [],
        "level": level,
        "metric": metric,
        "metric_label": meta["label"],
        "metric_unit": meta["unit"],
        "metric_kind": meta["kind"],
        "metric_note": meta["note"],
        "aggregation": "行业层用成员中位数，避免单只极端值主导" if level == "industry" else "每块是一家公司",
        "universe_total": len(rows),
        "with_metric": len(with_metric),
        "tiles": tiles,
        "indexes": indexes,
        "size_basis": size_basis,
        "breadth": breadth,
        "scopes": _heatmap_scopes(conn),
        "coverage": f"覆盖范围：{scope_label} {len(rows)} 只，其中 {len(with_metric)} 只有「{meta['label']}」数据；面积为{size_basis}",
        "boundary": "云图只描述市场结构与指标分布，不排序推荐，也不提供短线追涨入口。",
    }


def market_heatmap(scope: str = "all", metric: str = "roe", limit: int = 60) -> dict[str, Any]:
    """scope: all | index:<代码> | industry:<名称>；前两者按行业聚合，后者列出行业内公司。"""

    if metric not in HEATMAP_METRICS:
        raise LedgerError(f"不支持的指标：{metric}")

    key = (scope, metric, limit)
    with connection() as conn:
        stamp = _universe_stamp(conn)
        with _HEATMAP_CACHE_LOCK:
            cached = _HEATMAP_CACHE.get(key)
        core = cached[1] if cached and cached[0] == stamp else None
        if core is None:
            core = _heatmap_core(conn, scope, metric, limit)
            with _HEATMAP_CACHE_LOCK:
                # 底座一换水位，全部旧条目都作废；顺手给个上限，防止有人把
                # industry:<名称> 一个个点过去把内存堆满。
                if len(_HEATMAP_CACHE) >= _HEATMAP_CACHE_MAX:
                    _HEATMAP_CACHE.clear()
                _HEATMAP_CACHE[key] = (stamp, core)
        # 每次都现查：这一份是「你的」公司，跟着数据域走。
        watched = {
            row["symbol"]: {"company_id": row["id"], "symbol": row["symbol"], "name": row["name"]}
            for row in conn.execute(f"SELECT id, symbol, name FROM companies WHERE 1=1{_sw()}").fetchall()
        }

    view = dict(core)
    view["tiles"] = [
        {name: value for name, value in tile.items() if name != "members"}
        | {"watched": [watched[symbol] for symbol in tile["members"] if symbol in watched]}
        for tile in core["tiles"]
    ]
    return view


def _heatmap_scopes(conn) -> list[dict[str, Any]]:
    """可选范围直接从底座里数出来，不写死——没有成分的指数不该出现在选项里。

    收调用方的连接：原来自己 `with connection()` 再开一条，而云图那边本来就
    握着一条，等于每张图都多借还一次连接。
    """

    scopes: list[dict[str, Any]] = [{"key": "all", "label": "全 A", "group": "全市场"}]
    for row in conn.execute(
        "SELECT index_code, index_name, COUNT(*) AS count FROM index_members GROUP BY index_code, index_name ORDER BY index_code"
    ).fetchall():
        scopes.append({"key": f"index:{row['index_code']}", "label": row["index_name"], "group": "指数", "count": row["count"]})
    for row in conn.execute(
        "SELECT exchange, COUNT(*) AS count FROM market_universe WHERE exchange IS NOT NULL GROUP BY exchange ORDER BY exchange"
    ).fetchall():
        label = {"上海证券交易所": "沪市", "深圳证券交易所": "深市", "北京证券交易所": "北交所"}.get(row["exchange"], row["exchange"])
        scopes.append({"key": f"exchange:{row['exchange']}", "label": label, "group": "交易所", "count": row["count"]})
    for row in conn.execute(
        "SELECT board, COUNT(*) AS count FROM market_universe WHERE board IS NOT NULL GROUP BY board ORDER BY board"
    ).fetchall():
        scopes.append({"key": f"board:{row['board']}", "label": row["board"], "group": "板块", "count": row["count"]})
    return scopes


UNIVERSE_RANGE_WINDOWS = {"change_5d": 5, "change_20d": 20}


def market_lens_statuses() -> list[dict[str, Any]]:
    """Tell the cockpit which time lenses are honest enough to open."""

    with connection() as conn:
        trading_days = int(
            conn.execute("SELECT COUNT(DISTINCT point_date) FROM universe_valuation_history WHERE close IS NOT NULL").fetchone()[0]
        )
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN change_5d IS NOT NULL THEN 1 ELSE 0 END) AS five,
                 SUM(CASE WHEN change_20d IS NOT NULL THEN 1 ELSE 0 END) AS twenty,
                 SUM(CASE WHEN ytd_change IS NOT NULL THEN 1 ELSE 0 END) AS ytd
               FROM market_universe"""
        ).fetchone()
    coverage = {
        "change_5d": int(row["five"] or 0),
        "change_20d": int(row["twenty"] or 0),
        "ytd_change": int(row["ytd"] or 0),
    }
    result: list[dict[str, Any]] = []
    for metric, required in (*UNIVERSE_RANGE_WINDOWS.items(), ("ytd_change", None)):
        filled = coverage[metric]
        available = filled > 0
        if available:
            message = f"已覆盖 {filled} 只股票"
        elif required is not None:
            remaining = max(0, required - trading_days)
            message = f"本地已积累 {trading_days}/{required} 个交易日" + (f"，还差 {remaining} 日" if remaining else "，等待区间计算")
        else:
            message = "当前批量行情源未提供年内涨跌，暂不展示空图"
        result.append({
            "metric": metric,
            "available": available,
            "filled": filled,
            "trading_days": trading_days,
            "required_days": required,
            "message": message,
        })
    return result


# 资金流本地快照多久算新鲜。两小时：这组数一个交易日只变一次，
# 而每次请求都去拉一次供应商，等于把驾驶舱的可用性绑在对方身上。
_FUND_FLOW_TTL_SECONDS = 2 * 3600


def _store_fund_flow(rows: list[dict[str, Any]]) -> None:
    """把拉回来的资金流写进本地快照。**按日期覆盖**，同一天重复拉不会堆行。"""
    if not rows:
        return
    stamp = now_iso()
    with connection() as conn:
        for row in rows:
            if not row.get("date"):
                continue
            conn.execute(
                """
                INSERT INTO market_fund_flow
                    (date, main_net_inflow, main_net_inflow_percent, super_large_net_inflow,
                     large_net_inflow, medium_net_inflow, small_net_inflow,
                     sh_close, sh_change_percent, sz_close, sz_change_percent, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date) DO UPDATE SET
                    main_net_inflow = excluded.main_net_inflow,
                    main_net_inflow_percent = excluded.main_net_inflow_percent,
                    super_large_net_inflow = excluded.super_large_net_inflow,
                    large_net_inflow = excluded.large_net_inflow,
                    medium_net_inflow = excluded.medium_net_inflow,
                    small_net_inflow = excluded.small_net_inflow,
                    sh_close = excluded.sh_close,
                    sh_change_percent = excluded.sh_change_percent,
                    sz_close = excluded.sz_close,
                    sz_change_percent = excluded.sz_change_percent,
                    synced_at = excluded.synced_at
                """,
                (row.get("date"), row.get("mainNetInflow"), row.get("mainNetInflowPercent"),
                 row.get("superLargeNetInflow"), row.get("largeNetInflow"),
                 row.get("mediumNetInflow"), row.get("smallNetInflow"),
                 row.get("shClose"), row.get("shChangePercent"),
                 row.get("szClose"), row.get("szChangePercent"), stamp),
            )


def _read_fund_flow(limit: int = 120) -> tuple[list[dict[str, Any]], str]:
    """读本地快照，返回（点位, 最近一次同步时间）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM market_fund_flow ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    points = [{
        "date": row["date"],
        "main_net_inflow": row["main_net_inflow"],
        "main_net_inflow_percent": row["main_net_inflow_percent"],
        "super_large_net_inflow": row["super_large_net_inflow"],
        "large_net_inflow": row["large_net_inflow"],
        "medium_net_inflow": row["medium_net_inflow"],
        "small_net_inflow": row["small_net_inflow"],
        "sh_close": row["sh_close"],
        "sh_change_percent": row["sh_change_percent"],
        "sz_close": row["sz_close"],
        "sz_change_percent": row["sz_change_percent"],
    } for row in rows]
    points.reverse()          # 存的时候倒序取，画图要按时间正序
    synced = max((row["synced_at"] or "" for row in rows), default="")
    return points, synced


def market_fund_flow_view() -> dict[str, Any]:
    """资金流：**先看本地快照，过期了才去拉**，拉不到就给上一份并说明截至何时。

    原来这里每次请求都直接拉供应商——冷启动或对方抖一下，整块驾驶舱就是 503。
    而这组数一个交易日只变一次，把可用性绑在对方身上不划算。
    """
    cached, synced = _read_fund_flow()
    fresh = False
    if synced:
        try:
            fresh = (datetime.now() - datetime.fromisoformat(synced)).total_seconds() < _FUND_FLOW_TTL_SECONDS
        except ValueError:
            fresh = False
    if fresh and cached:
        return _fund_flow_payload(cached, synced, degraded=False)

    try:
        rows = _fetch_market_fund_flow()
    except MarketDataError as exc:
        if cached:
            # **有旧数据就别报错。** 一屏"截至昨天"的图，比一个 503 有用得多。
            return _fund_flow_payload(cached, synced, degraded=True, reason=str(exc))
        raise
    _store_fund_flow(rows)
    points, synced = _read_fund_flow()
    return _fund_flow_payload(points, synced, degraded=False)


def _fund_flow_payload(points: list[dict[str, Any]], synced: str,
                       degraded: bool, reason: str = "") -> dict[str, Any]:
    note = ""
    if degraded:
        note = f"资金流数据源暂时取不到（{reason[:80]}），下面是最近一次同步的结果。"
    return {
        "source": "StockSDK · 东方财富资金流",
        "as_of": points[-1]["date"] if points else "",
        "unit": "元",
        "points": points,
        "synced_at": synced,
        "degraded": degraded,
        "note": note,
        "boundary": "资金流按成交单大小统计，只描述当日资金结构，不等同于机构真实持仓变化，也不构成买卖信号。",
    }


def backfill_universe_range_returns() -> dict[str, Any]:
    """用自建的日收盘序列算 5 日与 20 日涨跌。

    全市场的区间涨跌没有可直接取到的来源（东财行情推送被挡），所以只能从同步那天起自己累积。
    样本不够就明确说还差多少天，不给残缺的数字。
    """

    filled: dict[str, int] = {}
    with connection() as conn:
        available = int(
            conn.execute("SELECT COUNT(DISTINCT point_date) FROM universe_valuation_history WHERE close IS NOT NULL").fetchone()[0]
        )
        for column, window in UNIVERSE_RANGE_WINDOWS.items():
            if available < window:
                filled[column] = 0
                continue
            # **`close > 0`，不是 `IS NOT NULL`。**
            #
            # 停牌那天快照给的价是 0 —— 那不是"这天值 0 元"，是"这天没有报价"。
            # 拿它当分母，Postgres 直接抛 division by zero，**整个全市场底座作业当场死掉**；
            # SQLite 那边只会给 NULL，所以本地和单测都看不见。
            #
            # 2026-08-14 线上实测：universe_valuation_history 里有 18 行 close = 0，
            # 最早一条落在 08-10，正好在 08-12 进入 5 日窗口 ——
            # 而这个作业的「上次成功」就停在 08-11，之后连挂三天。
            # 候选清单、云图、全市场分位全靠它，于是一起停在三天前的数据上。
            #
            # 改成 `> 0` 还顺手修对了口径：停牌日本来就不该算进"过去 5 个交易日"，
            # 跳过它之后 OFFSET 数的才是真正有报价的那几天。
            filled[column] = conn.execute(
                f"""
                UPDATE market_universe SET {column} = (
                    SELECT ROUND(CAST((market_universe.price - h.close) / h.close * 100 AS NUMERIC), 2)
                    FROM universe_valuation_history h
                    WHERE h.symbol = market_universe.symbol AND h.close > 0
                    ORDER BY h.point_date DESC LIMIT 1 OFFSET ?
                )
                WHERE price IS NOT NULL AND price > 0
                """,
                (window - 1,),
            ).rowcount
    return {
        "trading_days": available,
        "filled": filled,
        "note": (
            f"自建日线已累积 {available} 个交易日。"
            + ("".join(f"{name} 需要 {window} 天；" for name, window in UNIVERSE_RANGE_WINDOWS.items() if available < window) or "")
            + "全市场区间涨跌没有可直接取到的来源，只能从接入那天起累积，不足时不给数字。"
        ),
    }


# --- 研究任务：把一份候选清单固化下来 -------------------------------------
# 清单是某一时刻、某一套条件、某一份数据下的产物。存成任务时把这三样一起留档，
# 之后才能回答"当初为什么把它列进来"，也才能看出哪些看完了、哪些排除了。

TASK_ITEM_STATUSES = ("待看", "已建档", "已排除")


def create_research_task(payload: ResearchTaskCreate) -> dict[str, Any] | None:
    # 综合榜和「一句话选股」都不是 screen_strategies 里的普通策略：
    # 前者是前端把五套规则取并集后的当前结果，后者是模型当次挑出来的那几家。
    # **两者都不能靠重跑规则复现**——综合榜重跑会得到另一份榜单，
    # 而一句话选股哪怕规则一样，"模型挑哪几家写理由"这一步也不保证挑出同一批。
    # 所以它们保存时直接用页面传来的 symbols；其它策略继续走规则重算，
    # 保证任务仍然带着完整的筛选依据。
    if payload.strategy_key in SENTINEL_LIST_NAMES:
        list_name = SENTINEL_LIST_NAMES[payload.strategy_key]
        if not payload.symbols:
            raise LedgerError(f"请先跑出{list_name}的结果，再保存为研究任务。")
        with connection() as conn:
            universe = _universe_rows(conn)
        by_symbol = {str(row["symbol"]): row for row in universe}
        candidates = []
        for symbol in dict.fromkeys(payload.symbols):
            row = by_symbol.get(str(symbol))
            if row is None:
                continue
            candidates.append({
                "symbol": row["symbol"],
                "name": row["name"],
                "industry": row.get("industry") or "",
                "checks": [],
            })
        result = {
            "strategy": {"name": list_name, "rules": []},
            "candidates": candidates,
            "universe_total": len(universe),
            "matched": len(candidates),
            "report_date": next((row.get("report_date") for row in universe if row.get("report_date")), None),
            "price_as_of": next((row.get("price_as_of") for row in universe if row.get("price_as_of")), None),
        }
    else:
        result = run_screen(payload.strategy_key, limit=payload.limit, record=False)
    if not result:
        return None
    wanted = set(payload.symbols)
    candidates = [item for item in result["candidates"] if not wanted or item["symbol"] in wanted]
    if not candidates:
        raise LedgerError("这份清单里没有可加入的候选。")

    timestamp = now_iso()
    data_note = (
        f"{result['strategy']['name']}｜全市场 {result['universe_total']} 只中命中 {result['matched']} 家；"
        f"财务口径 {result['report_date'] or '未同步'} 报告期；行情截至 {str(result['price_as_of'] or '')[:10] or '未同步'}"
    )
    # 如果找票页已经完成过同一策略的模型复核，创建研究任务时直接带入评语。
    # 这样“保存任务”不是把同一批公司再送进模型一次。
    saved_review = latest_candidate_review(payload.strategy_key)
    saved_by_symbol = {str(row.get("symbol")): row for row in (saved_review or {}).get("rows", [])}
    with connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO research_tasks (user_id, title, source, strategy_key, strategy_name, rules, data_note,
                status, due_date, created_at, updated_at)
            VALUES (?, ?, '候选清单', ?, ?, ?, ?, '进行中', ?, ?, ?)
            """,
            (
                _stamp(),
                payload.title.strip(),
                payload.strategy_key,
                result["strategy"]["name"],
                json.dumps(result["strategy"]["rules"], ensure_ascii=False),
                data_note,
                payload.due_date.isoformat() if payload.due_date else None,
                timestamp,
                timestamp,
            ),
        )
        task_id = int(cursor.lastrowid)
        known = {row["symbol"]: row["id"] for row in conn.execute(f"SELECT id, symbol FROM companies WHERE 1=1{_sw()}").fetchall()}
        for candidate in candidates:
            saved = saved_by_symbol.get(str(candidate["symbol"])) or {}
            conclusion = str(saved.get("conclusion") or saved.get("reason") or "").strip()
            conn.execute(
                """
                INSERT INTO research_task_items
                    (task_id, symbol, name, industry, evidence, status, company_id,
                     conclusion, verdict, reasons, concerns, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    candidate["symbol"],
                    candidate["name"],
                    candidate["industry"],
                    json.dumps(candidate["checks"], ensure_ascii=False),
                    "已建档" if candidate["symbol"] in known else "待看",
                    known.get(candidate["symbol"]),
                    conclusion,
                    str(saved.get("verdict") or ""),
                    json.dumps(saved.get("reasons") or [], ensure_ascii=False),
                    json.dumps(saved.get("concerns") or [], ensure_ascii=False),
                    timestamp,
                ),
            )
    return get_research_task(task_id)


def _task_row(conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
    task = _one_or_none(conn.execute(f"SELECT * FROM research_tasks WHERE id = ?{_sw()}", (task_id,)).fetchone())
    if not task:
        return None
    task["rules"] = json.loads(task["rules"])
    items = _rows(conn.execute("SELECT * FROM research_task_items WHERE task_id = ? ORDER BY id", (task_id,)).fetchall())
    for item in items:
        item["evidence"] = json.loads(item["evidence"])
        item["links"] = json.loads(item.get("links") or "[]")
        item["reports"] = json.loads(item.get("reports") or "[]")
        item["brief"] = item.get("brief") or ""
        item["brief_source"] = item.get("brief_source") or ""
        # 初筛的结构化输出。老条目这两列是空的，页面回退到整段 note。
        #
        # **读出来的时候再收一次小数。** 喂进提示词之前取整只在生成那一刻有效，
        # 而模型产出是会被存下来反复读的资产——生成器修好之前存的东西会一直那样显示。
        # 实测库里有 97 处小数位 ≥ 4 的数（「营收同比 200.596381199%」），
        # 而生成器早在两天后就修好了。见 jsonio.tidy_decimals。
        item["conclusion"] = tidy_decimals(item.get("conclusion") or "")
        item["note"] = tidy_decimals(item.get("note") or "")
        item["brief"] = tidy_decimals(item["brief"])
        item["verdict"] = item.get("verdict") or ""
        item["assessment"] = json.loads(item.get("assessment") or "[]")
        item["assessed_at"] = item.get("assessed_at") or ""
        item["reasons"] = [tidy_decimals(x) for x in json.loads(item.get("reasons") or "[]")]
        item["concerns"] = [tidy_decimals(x) for x in json.loads(item.get("concerns") or "[]")]
    task["items"] = items
    task["total"] = len(items)
    task["pending"] = sum(1 for item in items if item["status"] == "待看")
    task["adopted"] = sum(1 for item in items if item["status"] == "已建档")
    task["dropped"] = sum(1 for item in items if item["status"] == "已排除")
    return task


def get_research_task(task_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        return _task_row(conn, task_id)


def list_research_tasks(limit: int = 20) -> list[dict[str, Any]]:
    with connection() as conn:
        ids = [row["id"] for row in conn.execute(f"SELECT id FROM research_tasks WHERE 1=1{_sw()} ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        tasks = [_task_row(conn, task_id) for task_id in ids]
    return [task for task in tasks if task]


def assess_task_item(item_id: int) -> dict[str, Any] | None:
    """给一个候选跑方法体检——**不要求先建档**。

    体检本来就是用来帮你决定「要不要花时间建档」的。要求先建档才能体检，
    等于把这个决定提到了体检前面，顺序反了。

    所以这里用候选自己的代码、名称、行业拼一个临时的公司壳交给模型，
    财务序列直接按 symbol 从底座取（那本来就是全局共享的，不挂在档案上）。
    结果存在候选行上，不进 method_assessments——那张表挂在 company_id 上，
    而且它记的是"档案里这家公司的持续记录"，跟一次性的筛选判断不是一回事。
    """
    from .assessment import assess_company

    with connection() as conn:
        item = _one_or_none(conn.execute(
            """SELECT i.*, t.id AS owner_task FROM research_task_items i
               JOIN research_tasks t ON t.id = i.task_id
               WHERE i.id = ?""" + _sw("t"), (item_id,)).fetchone())
    if not item:
        return None

    symbol = item["symbol"]
    # **先把底座里已有的数喂进去。** 第一版没喂，八个方法里六个回「数据不足」，
    # 而缺的那些——PE、PB、ROE、营收增速、毛利率——全市场底座里本来就有，
    # 只是没送到模型面前。花了积分只换回一句"缺数据"，那不叫体检。
    with connection() as conn:
        universe = _one_or_none(conn.execute(
            "SELECT * FROM market_universe WHERE symbol = ?", (symbol,)).fetchone()) or {}
        has_periods = conn.execute(
            "SELECT count(*) AS n FROM financial_periods WHERE symbol = ?",
            (symbol,)).fetchone()["n"]

    # 财务序列（历年年报）是「九问打分」「三层估值」这类方法的唯一依据，
    # 底座那一行给不了。没有就现拉一次——它按 symbol 全局共享，拉了别人也能用。
    if not has_periods:
        try:
            store_financial_periods_by_symbol(symbol, _fetch_financial_reports(symbol))
        except Exception:            # noqa: BLE001 — 拉不到就照常体检，模型会如实写 gaps
            pass

    shell = {
        "name": item["name"],
        "symbol": symbol,
        "industry": item.get("industry") or universe.get("industry") or "",
        # 简况是初筛时补过的，喂给体检能让"找什么"那几个方法落得了地
        "profile": {"main_business": item.get("brief") or "",
                    "source": item.get("brief_source") or "候选初筛"},
        "latest_price": universe.get("price"),
        "change_percent": universe.get("change_percent"),
        "market_metrics": {
            "市盈率 TTM": universe.get("pe_ttm"),
            "市净率": universe.get("pb"),
            "净资产收益率": universe.get("roe"),
            "年报净资产收益率": universe.get("annual_roe"),
            "毛利率": universe.get("gross_margin"),
            "营收同比": universe.get("revenue_growth"),
            "净利润同比": universe.get("net_profit_growth"),
            "股息率": universe.get("dividend_yield"),
            "每股收益": universe.get("eps"),
            "每股净资产": universe.get("bps"),
            "每股经营现金流": universe.get("ocf_per_share"),
            "总市值": universe.get("total_market_cap"),
        },
    }
    result = assess_company(shell, theses=None)

    now = now_iso()
    with connection() as conn:
        conn.execute(
            "UPDATE research_task_items SET assessment = ?, assessed_at = ? WHERE id = ?",
            (json.dumps(result["results"], ensure_ascii=False), now, item_id))

    counts: dict[str, int] = {}
    for row in result["results"]:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {
        "item_id": item_id,
        "symbol": item["symbol"],
        "name": item["name"],
        "assessed_at": now,
        "results": result["results"],
        "counts": counts,
        "model": result["model"],
        "boundary": ("这是按投资方法库逐条打的分，用来决定「要不要花时间深入」，"
                     "不是「要不要买」。建档之后可以在公司档案里跑一次完整的——"
                     "那一次会带上你写过的判断，结论会更贴。"),
    }


def update_research_task(task_id: int, payload: ResearchTaskUpdate) -> dict[str, Any] | None:
    fields = payload.model_dump(exclude_unset=True)
    with connection() as conn:
        if not conn.execute(f"SELECT id FROM research_tasks WHERE id = ?{_sw()}", (task_id,)).fetchone():
            return None
        updates: dict[str, Any] = {}
        if fields.get("status"):
            updates["status"] = fields["status"]
            updates["closed_at"] = now_iso() if fields["status"] in {"已完成", "已放弃"} else None
        if fields.get("conclusion") is not None:
            updates["conclusion"] = str(fields["conclusion"]).strip()
        if "due_date" in fields:
            updates["due_date"] = fields["due_date"].isoformat() if fields["due_date"] else None
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE research_tasks SET {assignments}, updated_at = ? WHERE id = ?",
                [*updates.values(), now_iso(), task_id],
            )
        return _task_row(conn, task_id)


def delete_research_task(task_id: int) -> bool | None:
    """删除一整份研究任务及其候选条目。

    删除前拒绝正在运行的任务，避免后台线程在任务被删后继续写入孤立结果；
    已完成/已中断的任务连同对应的后台历史一起清理。候选公司档案本身不受影响。
    """
    with connection() as conn:
        task = _one_or_none(conn.execute(f"SELECT id FROM research_tasks WHERE id = ?{_sw()}", (task_id,)).fetchone())
        if not task:
            return None
        item_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM research_task_items WHERE task_id = ?", (task_id,)
        ).fetchall()]
        running_conditions = ["(kind = 'task_auto_review' AND target_id = ?)"]
        running_params: list[Any] = [task_id]
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            running_conditions.append(f"(kind = 'item_assessment' AND target_id IN ({placeholders}))")
            running_params.extend(item_ids)
        active = conn.execute(
            f"SELECT COUNT(*) AS n FROM background_jobs WHERE ({' OR '.join(running_conditions)})"
            f" AND status IN ('排队中', '运行中'){_sw()}",
            running_params,
        ).fetchone()["n"]
        if active:
            raise LedgerError("这份任务正在后台运行，等它完成或中断后再删除。")

        job_conditions = ["(kind = 'task_auto_review' AND target_id = ?)"]
        job_params: list[Any] = [task_id]
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            job_conditions.append(f"(kind = 'item_assessment' AND target_id IN ({placeholders}))")
            job_params.extend(item_ids)
        conn.execute(
            f"DELETE FROM background_jobs WHERE ({' OR '.join(job_conditions)}){_sw()}",
            job_params,
        )
        conn.execute(f"DELETE FROM research_tasks WHERE id = ?{_sw()}", (task_id,))
    return True


def update_task_item(item_id: int, payload: ResearchTaskItemUpdate) -> dict[str, Any] | None:
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("status") and fields["status"] not in TASK_ITEM_STATUSES:
        raise LedgerError(f"条目状态只能是：{('、').join(TASK_ITEM_STATUSES)}")
    with connection() as conn:
        item = _one_or_none(conn.execute("SELECT * FROM research_task_items WHERE id = ?", (item_id,)).fetchone())
        if not item:
            return None
        updates: dict[str, Any] = {}
        if fields.get("status"):
            updates["status"] = fields["status"]
        if fields.get("note") is not None:
            updates["note"] = str(fields["note"]).strip()
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE research_task_items SET {assignments}, updated_at = ? WHERE id = ?",
                [*updates.values(), now_iso(), item_id],
            )
        return _task_row(conn, item["task_id"])


# --- 收件箱分级 -----------------------------------------------------------
# 规则先跑，模型只补规则拿不准的部分；两者都只做分级，不替用户判断是否影响投资逻辑。

def _model_should_look_again(item: dict[str, Any], terms_changed_at: str) -> bool:
    """这条还值得再让模型看一遍吗。

    值得的只有两种：模型压根没看过（新条目，或只有规则判过），
    以及模型看过之后你又改了规则词——那时旧结论是按旧口径下的，该重来。
    其余一律不重来：模型判完还是「中」说明它也拿不准，再问一遍还是「中」，
    只是又付一次钱。
    """
    if (item.get("relevance_source") or "") != "模型":
        return True
    return (item.get("classified_at") or "") < terms_changed_at


def classify_inbox(
    limit: int = 400,
    use_ai: bool = True,
    ai_batch: int = 25,
    max_ai_batches: int = 8,
    regrade: bool = False,
    force_model: bool = False,
) -> dict[str, Any]:
    """regrade=True 时连已经判成「中」的也重新过一遍。

    判定口径改过之后，旧的「中」是按旧口径判的；不重判，它们会永远卡在收件箱里。

    **但「重判」不等于「重新花钱」。** 模型判完仍是「中」的条目，正是模型也拿不准、
    要留给人处理的那些；它们会一直躺在收件箱里，直到你去点。如果每天的自动整理
    都把它们再送一遍模型，就是为同一批拿不准的条目按天付费，而且越积越多——
    上线当天实测：模型几分钟前刚判过的 2 条，下一次整理又原样送了一遍。

    所以模型这一步有个闸：只送**模型还没看过的**，以及**判完之后你又改过规则词的**
    （拿 rule_terms 的最新 created_at 和条目的 classified_at 比）。
    规则那一步不花钱，照常每次重跑。

    `force_model=True` 才无条件重送模型——留给你在页面上主动点「重新分级」，
    那是你明确要求的一次重做，不是后台自作主张。
    """

    # 先把你确认过的规则词装进引擎——它们排在内置词表前面。
    _load_user_terms()

    pending_where = "relevance IS NULL OR relevance = ''"
    if regrade:
        pending_where += " OR relevance = '中'"
    with connection() as conn:
        pending = _rows(
            conn.execute(
                f"""
                SELECT id, category, title, relevance_source, classified_at
                FROM company_calendar_events
                WHERE inbox_status = '待核验' AND ({pending_where})
                ORDER BY event_date DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
        # 口径最后一次变动的时间。没有自定义词就是空串，比什么都小，于是谁也不会因它重送。
        terms_changed_at = (conn.execute(
            f"SELECT COALESCE(MAX(created_at), '') AS t FROM rule_terms WHERE 1=1{_sw()}"
        ).fetchone()["t"] or "")

        # 规则判成"中"的交给模型细分；已经跑过模型的不重复花钱。
        rule_uncertain = _rows(
            conn.execute(
                """
                SELECT id, category, title FROM company_calendar_events
                WHERE inbox_status = '待核验' AND relevance = '中' AND relevance_source = '规则'
                ORDER BY event_date DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

    if regrade and not force_model:
        # 模型判过、且判完之后口径没变的，整条跳过——**连规则也不重跑**。
        # 只挡模型那一步是不够的：规则重跑会把结果写回去，把 relevance_source
        # 从「模型」改成「规则」，于是下一轮它又落进 rule_uncertain，照样被送去模型。
        # 省钱的闸门开在这里才关得住。
        pending = [item for item in pending if _model_should_look_again(item, terms_changed_at)]

    if not pending and not (use_ai and rule_uncertain):
        return {"scanned": 0, "by_rules": 0, "by_model": 0, "uncertain": len(rule_uncertain), "counts": {}, "note": "没有需要分级的条目"}

    timestamp = now_iso()
    graded: dict[int, dict[str, Any]] = {}
    for item in pending:
        graded[item["id"]] = classify_by_rules(item["title"], item["category"])

    seen = {item["id"] for item in pending}
    uncertain = [item for item in pending if graded[item["id"]]["relevance"] == "中"]
    uncertain += [item for item in rule_uncertain if item["id"] not in seen]
    model_note = ""
    by_model = 0
    if use_ai and uncertain:
        available, detail = ai_available()
        if not available:
            model_note = detail
        else:
            for index in range(0, min(len(uncertain), ai_batch * max_ai_batches), ai_batch):
                batch = uncertain[index : index + ai_batch]
                try:
                    for result in classify_with_model(batch):
                        graded[result["id"]] = result
                        by_model += 1
                except Exception as exc:
                    model_note = f"模型分级中断（已完成 {by_model} 条，其余保留规则结果）：{exc}"
                    break
            model_note = model_note or f"模型（{detail}）补充了 {by_model} 条规则拿不准的"

    with connection() as conn:
        for item_id, result in graded.items():
            conn.execute(
                """
                UPDATE company_calendar_events SET relevance = ?, relevance_reason = ?, relevance_source = ?,
                    relevance_topic = ?, summary = ?, classified_at = ?
                WHERE id = ?
                """,
                (
                    result["relevance"],
                    result.get("reason", ""),
                    result.get("source", "规则"),
                    result.get("topic"),
                    result.get("summary", ""),
                    timestamp,
                    item_id,
                ),
            )
        counts = {
            row["relevance"]: row["count"]
            for row in conn.execute(
                "SELECT relevance, COUNT(*) AS count FROM company_calendar_events WHERE inbox_status = '待核验' AND relevance IS NOT NULL GROUP BY relevance"
            ).fetchall()
        }
    return {
        "scanned": len(pending) + len([item for item in uncertain if item["id"] not in seen]),
        "by_rules": len(pending),
        "by_model": by_model,
        "uncertain": sum(1 for result in graded.values() if result["relevance"] == "中"),
        "counts": counts,
        "note": model_note or "只用规则分级",
    }


def ignore_by_relevance(relevance: str = "低") -> int:
    """把某一档全部标为已忽略；忽略只是不再出现在待处理里，条目本身仍然保留。"""

    with connection() as conn:
        cursor = conn.execute(
            f"UPDATE company_calendar_events SET inbox_status = '已忽略', handled_at = ? "
            f"WHERE inbox_status = '待核验' AND relevance = ?{_swc()}",
            (now_iso(), relevance),
        )
        return cursor.rowcount


# ---------------------------------------------------------------- 投资逻辑方法库


def _method_summary(method: Method) -> ThesisMethodSummary:
    return ThesisMethodSummary(
        key=method.key,
        name=method.name,
        category=method.category,
        category_label=_CATEGORY_LABELS[method.category],
        one_liner=method.one_liner,
        core_question=method.core_question,
        beginner=method.beginner,
        effort=method.effort,
        related_strategy=method.related_strategy,
    )


_CATEGORY_LABELS = {key: label for key, label, _ in CATEGORIES}


def method_library() -> ThesisMethodLibrary:
    categories = [
        ThesisMethodCategory(
            key=key,
            label=label,
            intro=intro,
            methods=[_method_summary(method) for method in METHODS if method.category == key],
        )
        for key, label, intro in CATEGORIES
    ]
    return ThesisMethodLibrary(
        categories=categories,
        boundary="这些方法来自公开出版的书与论文，写明出处是为了让你能回去查原文。它们提供的是提问方式和写作结构，不是买卖建议；同一家公司用不同方法会得出不同结论，这本身就是信息。",
    )


def method_detail(method_key: str) -> ThesisMethod | None:
    method = METHODS_BY_KEY.get(method_key)
    if method is None:
        return None
    summary = _method_summary(method)
    return ThesisMethod(
        **summary.model_dump(),
        origin=method.origin,
        steps=list(method.steps),
        claim_template=method.claim_template,
        counter_template=method.counter_template,
        trigger_template=method.trigger_template,
        fits=list(method.fits),
        not_fits=list(method.not_fits),
        caution=method.caution,
    )


# ---------------------------------------------------------------- 价值候选


# 综合榜的哨兵 key。**前端那个常量与这里必须一致**——不一致的话
# 使用者会看到「没有这个策略：__agent_pool__」，一个内部标识符漏到页面上。
AGENT_POOL_KEY = "__agent_pool__"
# 「用一句话选股」同理。它挑出哪几家是**模型当次挑的**，不是规则重跑能复现的，
# 所以它跟综合榜一样，存研究任务时只能按前端给的 symbols 存。
AI_PICK_KEY = "__ai_pick__"
# 这两把哨兵 key 存任务时都走 symbols 分支。名字要能出现在任务标题旁边，
# 不能让 `__ai_pick__` 这种内部标识符漏到页面上。
SENTINEL_LIST_NAMES = {AGENT_POOL_KEY: "综合榜", AI_PICK_KEY: "一句话选股"}


def value_candidates(strategy_key: str = "undervalued_defensive", width: int = 20,
                     assess: bool = True) -> dict[str, Any]:
    """全市场漏斗：规则先筛，前 N 名再交给模型看。

    **顺序不能反。** 五千多只全交给模型是不可能的（既慢又贵），而规则筛是免费的：
    ROE、PE、增速这些指标算一遍不花钱。模型只用在最后一步——规则挑不出来的那种
    「指标都合格，但组合起来到底像不像一门好生意」。

    width 由用户定：页面上标着预计花多少分，让他按当时的余额决定看多宽。
    默认 20 是个折中——再窄容易漏掉，再宽的话人也看不完。
    """
    from .assessment import estimate_candidate_credits

    # **综合榜不是一套策略，是五套的并集。**
    #
    # 页面上它跟五张策略卡并排（选哪份清单是同一个决定），所以「让模型看一遍」
    # 那一步理应也能作用在它上面。而它的 key 是个哨兵值 __agent_pool__，
    # 拿去查策略库必然查不到——使用者看到的是「没有这个策略：__agent_pool__」，
    # 一个内部标识符漏到了页面上。
    if strategy_key == AGENT_POOL_KEY:
        pool = agent_pool(limit=max(width, 1), stance="both")
        # **两种行的形状不一样，要在这里对齐。**
        #
        # 策略筛出来的行里 checks 是「字典列表」（每条带门槛、实际值、过没过），
        # 而综合榜的行里 checks 是个字典、matched 是字符串列表。
        # 直接塞给 build_candidate_prompt 会在 check.get("actual") 上炸
        # （AttributeError: 'str' object has no attribute 'get'）——
        # **而我上一版只验了 assess=false 那条路，没走到这里。**
        rows = []
        for row in pool.get("rows") or []:
            facts = [{"rule": f"命中 {name}", "label": name, "actual": None,
                      "passed": True, "missing": True}
                     for name in (row.get("matched") or [])]
            facts += [{"rule": f"{d['label']} 在这批候选里的分位",
                       "field": d["key"], "label": d["label"],
                       "actual": d.get("score"), "passed": True,
                       "missing": d.get("score") is None}
                      for d in (row.get("scores") or [])]
            rows.append({**row, "checks": facts})
        screen = {"strategy": {"key": AGENT_POOL_KEY, "name": "综合榜",
                               "sort_label": "命中的规则数"},
                  "candidates": rows}
    else:
        screen = run_screen(strategy_key=strategy_key, limit=max(width, 1), record=False)
        if screen is None:
            raise LedgerError(f"没有这个策略：{strategy_key}")
    # **返回的键是 candidates，不是 rows。** 读错键名会拿到空列表，
    # 而表现是「五个策略全部筛出 0 家」——看起来像策略太严或数据缺失，
    # 我为此查了半天数据源和字段覆盖率。
    rows = screen.get("candidates") or []
    if not rows or not assess:
        return {"strategy": screen.get("strategy"), "width": width, "rows": rows,
                "assessed": False, "estimated_credits": estimate_candidate_credits(len(rows)),
                "note": "只跑了规则筛，没有让模型看。"}

    # 找票页与研究任务共用同一套「候选初筛」评语。
    # 以前这里另调 assessment.assess_candidates，只返回 reason；研究任务则用
    # researching.review_candidates，返回 conclusion / reasons / concerns，导致
    # 同一家公司在两个页面会得到两套口径。把规则命中的实际值摊平后交给同一个
    # review_candidates，模型读到的事实与研究任务保持一致。
    from .researching import review_candidates

    review_rows = []
    for row in rows:
        normalized = dict(row)
        for check in row.get("checks") or []:
            if isinstance(check, dict) and check.get("field") and check.get("actual") is not None:
                normalized.setdefault(check["field"], check["actual"])
        review_rows.append(normalized)
    strategy_rules = screen.get("strategy") or {}
    rules_text = "、".join(rule.get("text") or rule.get("field", "") for rule in strategy_rules.get("rules", []))
    picks = {p["symbol"]: p for p in review_candidates(
        review_rows,
        strategy_rules.get("name") or "价值候选",
        rules_text,
        f"报告期 {next((row.get('report_date') for row in rows if row.get('report_date')), '—')}",
    )}
    merged = []
    for row in rows:
        pick = picks.get(str(row.get("symbol")))
        merged.append({**row,
                       "verdict": (pick or {}).get("verdict", "未评"),
                       # reason 保留给旧版客户端；新的两页都读 conclusion。
                       "reason": (pick or {}).get("conclusion", ""),
                       "conclusion": (pick or {}).get("conclusion", ""),
                       "reasons": (pick or {}).get("reasons", []),
                       "concerns": (pick or {}).get("concerns", [])})
    # 值得细看的排前面。同档位内保持规则筛的原始名次——那是客观的，
    # 而模型的档位是主观的，不该整个盖掉规则的排序。
    order = {"值得深入": 0, "值得细看": 0, "先放着": 1, "未评": 2, "直接排除": 3}
    merged.sort(key=lambda r: order.get(r["verdict"], 9))
    worth = sum(1 for r in merged if r["verdict"] in {"值得深入", "值得细看"})
    return {
        "strategy": screen.get("strategy"),
        "width": width,
        "rows": merged,
        "assessed": True,
        "estimated_credits": estimate_candidate_credits(len(rows)),
        "note": f"规则筛出 {len(rows)} 家，模型认为 {worth} 家值得建档细看。",
        "boundary": ("规则用的是全市场底座里的指标，模型只看了这些指标——"
                     "没有公告、没有研报、没有你自己的判断。它回答的是「值不值得再花时间」，"
                     "不是「该不该买」。真要看，先建公司档案再做完整的方法体检。"),
    }


# ---------------------------------------------------------------- AI 选股


def ai_pick_options() -> dict[str, Any]:
    """页面上那几个默认问法，以及它们现在能不能用。不花钱，不调模型。"""
    from . import ai_pick as picker
    from . import websearch

    web_ok, web_reason = websearch.available()
    return {
        "asks": picker.usable_default_asks(screen_fields()),
        "web_available": web_ok,
        "web_reason": "" if web_ok else web_reason,
    }


def ai_pick_run(question: str, allow_web: bool = True) -> dict[str, Any]:
    """一句话 → 条件 → 全 A 跑一遍 → 模型从命中里挑几家。

    **两次模型调用，中间夹一次代码执行。** 这个顺序是这个功能的全部设计：
    模型两头都只碰文字（把话翻成条件、把数读成理由），中间那 5541 行数据
    它一行都看不到。所以它没法把一只没过条件的票放进结果里——
    不是因为提示词禁止它，是因为它根本没有那个机会。
    """
    from . import ai_pick as picker
    from . import websearch
    from .researching import _row_brief

    question = (question or "").strip()
    if not question:
        raise LedgerError("先说一句你想找什么样的公司。")

    fields = screen_fields()
    with connection() as conn:
        industries = [row[0] for row in conn.execute(
            "SELECT DISTINCT industry FROM market_universe "
            "WHERE industry IS NOT NULL AND industry <> '' ORDER BY industry").fetchall()]
        universe_total = int(conn.execute("SELECT COUNT(*) FROM market_universe").fetchone()[0])
    if universe_total == 0:
        raise LedgerError("全市场底座还没有数据，先在数据状态页跑一次「全市场底座」")

    try:
        plan = picker.plan_screen(question, fields, industries)
    except picker.PlanError as exc:
        raise LedgerError(str(exc)) from exc

    # ---- 概念 → 公司名单。只有模型说需要、而且你允许联网时才走这一步。
    theme_hits: dict[str, list[dict[str, str]]] = {}
    web = {"used": False, "queries": [], "hits": 0, "matched": 0, "note": "", "sources": []}
    searches = 0
    if plan["theme_queries"] and allow_web:
        ok, reason = websearch.available()
        if not ok:
            web["note"] = f"没能联网找「{plan['theme']}」的名单：{reason}"
        else:
            found = websearch.gather(plan["theme_queries"])
            searches = len(found["queries"])
            with connection() as conn:
                rows = _universe_rows(conn)
            theme_hits = picker.theme_symbols(found["hits"], rows)
            web = {
                "used": True,
                "queries": found["queries"],
                "hits": len(found["hits"]),
                "matched": len(theme_hits),
                "note": found["note"],
                # 出处跟着名单一起交出去：每家公司是哪篇文章提到的，点得进去。
                "sources": [{"title": hit["title"], "url": hit["url"], "kind": hit["kind"]}
                            for hit in found["hits"]],
            }
            if not theme_hits:
                web["note"] += (f"　但搜回来的文章里，没有一家能跟底座里的公司对上号——"
                                f"「{plan['theme']}」这一层没起作用，下面是**只按财务条件**筛的结果。")
    elif plan["theme_queries"] and not allow_web:
        web["note"] = f"你关掉了联网，所以「{plan['theme']}」这个概念没参与筛选，只按财务条件筛。"

    # ---- 代码筛。先收窄（概念、行业）再跑条件，顺序不能反。
    ad_hoc = {"name": plan["name"], "rules": plan["rules"],
              "sort_field": plan["sort_field"], "sort_desc": plan["sort_desc"],
              "sort_label": plan["sort_label"],
              "provenance": f"由 AI 把你的一句话翻译而来：{question[:60]}",
              "biases": ["这套条件是模型翻译出来的，不是有出处的方法论；它只是把你的话变成了可执行的门槛。"]}
    try:
        screen = run_screen(limit=picker.PICK_POOL, record=False, ad_hoc=ad_hoc,
                            only_symbols=set(theme_hits) if theme_hits else None,
                            only_industries=plan["industries"] or None)
    except LedgerError:
        raise
    rows = (screen or {}).get("candidates") or []

    base = {
        "question": question,
        "plan": plan,
        "web": web,
        "screened": {
            "universe_total": universe_total,
            "searched_in": (screen or {}).get("universe_total", 0),
            "matched": (screen or {}).get("matched", 0),
            "returned": len(rows),
            "sort_explain": (screen or {}).get("sort_explain", ""),
            "report_date": (screen or {}).get("report_date"),
        },
        # 这套条件原样可存成策略——**这是这个功能跟「模型直接给你五只票」的分界线**：
        # 你能看见它凭什么筛，不同意就改，改完还是你自己的策略。
        "savable": {"name": plan["name"], "rules": plan["rules"],
                    "sort_field": plan["sort_field"], "sort_desc": plan["sort_desc"],
                    "sort_label": plan["sort_label"]},
        "rows": rows,
        "picks": [],
        "passed": [],
        "boundary": (
            "**筛选是代码做的，模型只做了两件事：把你的话翻成条件、从命中的公司里挑几家写理由。**"
            "它读到的每个数都来自全市场底座，它不许自己报数、自己算。"
            + ("联网只用来把概念词变成一串公司名，而且是靠文章里逐字出现的公司名对上号的——"
               "有文章提到不等于它主营就是这件事。" if web["used"] else "")
            + "结果回答的是「值不值得你花时间看」，不是「该不该买」。"
        ),
    }

    if not rows:
        base["note"] = (
            f"这套条件在{'这批概念公司' if theme_hits else '全市场'}里一家都没命中。"
            "条件可能太紧了——下面的规则可以直接改，改完再跑一次不花钱。")
        return base

    # ---- 模型挑。**行号制**：它回的是序号，不是股票代码。
    #
    # 喂给它的是**底座原始行**，不是上面筛选结果里那一行——后者是裁剪过的，
    # 财务字段只留了这套规则用到的那几个（实测只剩三个数）。
    # 主营业务只有建过档的公司才有，能带上就带上，没有就让它明说不知道。
    # 主营业务在 company_profiles，不在 companies——后者只有 description。
    # 覆盖很薄（眼下全库 12 家），所以这是「有就带上」，不是「靠它工作」：
    # 提示词里已经写明绝大多数公司只有行业和数字，让模型直说它不知道，
    # 而不是凭公司名猜。
    with connection() as conn:
        base_rows = {row["symbol"]: row for row in _universe_rows(conn)}
        profiles = {row["symbol"]: row["main_business"] for row in _rows(conn.execute(
            "SELECT symbol, main_business FROM company_profiles "
            "WHERE main_business IS NOT NULL AND main_business <> ''").fetchall())}
    briefs = []
    for row in rows:
        source = dict(base_rows.get(row["symbol"]) or row)
        if profiles.get(row["symbol"]):
            source["main_business"] = profiles[row["symbol"]]
        briefs.append(picker.brief_of(source))
    picked = picker.pick_from(question, plan, rows, briefs, theme_hits, searches=searches)

    by_symbol = {str(row["symbol"]): row for row in rows}
    base["picks"] = [{**pick, **{k: by_symbol[pick["symbol"]].get(k)
                                 for k in ("name", "industry", "price", "change_percent",
                                           "total_market_cap", "in_research_pool")},
                      "checks": by_symbol[pick["symbol"]].get("checks") or [],
                      "theme_sources": theme_hits.get(pick["symbol"]) or []}
                     for pick in picked["picks"] if pick["symbol"] in by_symbol]
    base["passed"] = picked["passed"]
    base["model"] = picked.get("model", "")
    base["note"] = picked.get("note") or f"从 {len(rows)} 家里挑了 {len(base['picks'])} 家。"
    return base


# ---------------------------------------------------------------- 反证命中


def theses_missing_counter() -> int:
    """有几条判断没写认错条件 —— **它们不在网里，而且没有任何地方会报错。**

    人手写的两个门现在拦着（main.post_thesis / patch_thesis），
    但 AI 那条路不拦（拦了等于丢掉已经花钱的一轮），历史数据里也可能有。
    所以数出来摆在明面上，别让它们悄悄躺着。
    """
    with connection() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS n FROM theses
                WHERE TRIM(COALESCE(counter_condition, '')) = ''
                  AND status <> 'broken'{_swc('company_id')}""").fetchone()
    return int(row["n"] if row else 0)


def uncompared_counter_events() -> int:
    """还有多少条待核验公告，没跟我写下的认错条件比对过。**不花钱，不过模型。**

    ## 为什么要单独有这个数

    页面上原来只有一个「反证命中 0」。而 0 有两种意思：

        · 比对过了，你的认错条件一条都没被撞上   ← 这是好消息
        · 压根没比对过                          ← 这是"你以为有人在盯，其实没有"

    两种在界面上长得一模一样，而第二种恰恰是常态：比对要手动点，
    而那个按钮在首页一个默认折叠的分区里。2026-08-14 线上实测：
    3 条判断全写了认错条件、40 条公告待核验、命中 0 —— 一次都没比过。

    所以把「没比过的还剩多少」如实报出来。它跟命中数是两个数，
    不能合并：一个说"发生了什么"，一个说"有多少还没看过"。

    口径跟 check_counter_hits 里那条查询一致（都只看待核验、且没进过
    counter_hits 的），否则页面说还剩 40，点一下只比了 12。
    """
    with connection() as conn:
        # 一条认错条件都没写的时候，这个数没有意义 —— 报 0，别报 40 吓人。
        has_condition = conn.execute(
            f"""SELECT 1 FROM theses WHERE counter_condition <> ''
                {_swc('company_id')} LIMIT 1""").fetchone()
        if not has_condition:
            return 0
        # 口径必须跟 check_counter_hits 那条选择语句一致，
        # 否则页面说还剩 103，点一下只比 40，数字还纹丝不动。
        row = conn.execute(
            f"""SELECT COUNT(*) AS n FROM company_calendar_events e
                WHERE e.inbox_status = '待核验'{_swc('e.company_id')}
                  AND e.counter_checked_at IS NULL""").fetchone()
    return int(row["n"] if row else 0)


def check_counter_hits(company_id: int | None = None, days: int = 180) -> dict[str, Any]:
    """把新公告拿去和已写下的反证条件逐条比对，命中就记下来。

    只看还没核验的公告：已经处理过的不再重复花钱比对。
    """
    from .counters import find_hits

    scope_sql = " AND e.company_id = ?" if company_id else ""
    params: tuple = (company_id,) if company_id else ()
    with connection() as conn:
        # **判据是 counter_checked_at，不是"在不在 counter_hits 里"。**
        # counter_hits 只存命中；拿它当"比过没比过"用的话，比完 0 命中的那些
        # 在库里跟没比过一模一样 —— 定时任务每天重比同一批，每天烧一次积分，
        # 而且永远不收敛（线上实测：跑完「未比对」还是 103）。
        events = _rows(conn.execute(
            f"""SELECT e.id, e.company_id, e.category, e.title, e.event_date
                FROM company_calendar_events e
                WHERE e.inbox_status = '待核验'{_swc('e.company_id')}{scope_sql}
                  AND e.counter_checked_at IS NULL
                ORDER BY e.event_date DESC LIMIT 40""", params).fetchall())
        theses = _rows(conn.execute(
            f"""SELECT id, company_id, claim, counter_condition FROM theses
                WHERE counter_condition <> ''{_swc('company_id')}""").fetchall())

    by_company: dict[int, list[dict[str, Any]]] = {}
    for thesis in theses:
        by_company.setdefault(thesis["company_id"], []).append(thesis)

    stored = 0
    checked = 0
    compared: list[int] = []
    failed: list[str] = []
    for cid, own in by_company.items():
        mine = [e for e in events if e["company_id"] == cid]
        if not mine:
            continue
        # **一家失败不拖垮其他家。** 这一层原来没有 try：三家公司三次模型调用，
        # 第三次超时就把整个函数抛出去 —— 前两家**已经花过钱**的比对结果一起作废，
        # 连戳都没打上，下一轮再花一次同样的钱。（线上实测：那一次扣了 2 分，
        # 而 checked 归零、未比对纹丝不动。）
        #
        # 跟 inbox_tidy 那边同一个规矩：失败的那家不打戳（下轮重来），
        # 成功的照常记账，并把失败如实说出来。
        try:
            hits = find_hits(mine, own)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{cid}: {exc}")
            continue
        checked += len(mine)
        compared.extend(int(e["id"]) for e in mine)
        for hit in hits:
            with connection() as conn:
                conn.execute(
                    """INSERT INTO counter_hits (user_id, event_id, thesis_id, clause, reason, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(user_id, event_id, thesis_id) DO NOTHING""",
                    (_stamp(), hit["event_id"], hit["thesis_id"], hit["clause"], hit["reason"], now_iso()))
            stored += 1
    # **比过就打上戳，命中与否都打。** 这一步漏掉的话，同一批公告会被
    # 每天重比一次：花的钱是真的，进度是零。
    #
    # 只给真的送进模型的那些打戳 —— 没有对应认错条件的公司，它的公告
    # 这一轮压根没被看过，打戳等于宣称比过了。
    if compared:
        with connection() as conn:
            marks = ",".join("?" for _ in compared)
            conn.execute(
                f"UPDATE company_calendar_events SET counter_checked_at = ? WHERE id IN ({marks})",
                (now_iso(), *compared))
    note = (f"比对了 {checked} 条公告，{stored} 条命中反证。"
            if checked else "没有需要比对的新公告——反证条件要先写下来，公告也要还没核验。")
    if failed:
        # 失败要说出来，而且要说清楚"没白花"：那几家下一轮会重来。
        note += f"　另有 {len(failed)} 家这一轮没跑成（下次会重试），已比对的照常算数。"
    return {"checked": checked, "hits": stored, "failures": len(failed), "note": note}


def open_counter_hits() -> list[dict[str, Any]]:
    """还没处理的命中。决策总览拿它排最前面。"""
    with connection() as conn:
        return _rows(conn.execute(
            f"""SELECT h.id, h.event_id, h.thesis_id, h.clause, h.reason, h.created_at,
                       e.title AS event_title, e.event_date, e.company_id,
                       c.name AS company_name, t.claim
                FROM counter_hits h
                JOIN company_calendar_events e ON e.id = h.event_id
                JOIN companies c ON c.id = e.company_id
                JOIN theses t ON t.id = h.thesis_id
                WHERE h.acknowledged = 0{_sw('h')}
                ORDER BY e.event_date DESC, h.id DESC""").fetchall())


def acknowledge_counter_hit(hit_id: int) -> bool:
    """标记「我看过了」。不代表同意——只是不再顶在最前面。"""
    with connection() as conn:
        return bool(conn.execute(
            f"UPDATE counter_hits SET acknowledged = 1 WHERE id = ?{_sw()}", (hit_id,)).rowcount)


# ---------------------------------------------------------------- 时间轴


def company_timeline(company_id: int, years: int = 2) -> dict[str, Any] | None:
    """把散在各页签里的东西放到同一根时间轴上。

    **这是列表在结构上做不到的事：对齐。** 估值分位在「行情与估值」、公告在「事件记录」、
    交易在「持仓与交易」、投资逻辑在「逻辑与证据」——四个页签来回切，就是没法回答
    「我买的时候 PE 分位在哪、之后出了哪几条实质公告、写下判断之后事实往哪走」。

    只取「高」和「中」相关的公告。低相关（股东大会通知、法律意见书这类程序性文件）
    在这根轴上是噪音——茅台近两年 51 条低相关，全画上去会把 53 条实质变化盖住。
    """
    company = get_company(company_id)
    if company is None:
        return None
    symbol = company["symbol"]
    since = (date.today() - timedelta(days=365 * years)).isoformat()

    with connection() as conn:
        valuation = _rows(conn.execute(
            """SELECT point_date, value FROM valuation_points
               WHERE symbol = ? AND metric = 'pe_ttm' AND point_date >= ?
               ORDER BY point_date""", (symbol, since)).fetchall())
        events = _rows(conn.execute(
            f"""SELECT event_date, title, category, relevance, inbox_status
                FROM company_calendar_events
                WHERE company_id = ?{_swc('company_id')} AND event_date >= ?
                  AND relevance IN ('高', '中')
                ORDER BY event_date""", (company_id, since)).fetchall())
        reports = _rows(conn.execute(
            """SELECT report_date, revenue, net_profit FROM financial_periods
               WHERE symbol = ? AND report_date >= ? ORDER BY report_date""",
            (symbol, since)).fetchall())
        trades = _rows(conn.execute(
            f"""SELECT trade_date, side, shares, price, weight_percent, rationale
                FROM trades WHERE company_id = ?{_swc('company_id')} AND trade_date >= ?
                ORDER BY trade_date""", (company_id, since)).fetchall())
        theses = _rows(conn.execute(
            f"""SELECT id, claim, status, created_at FROM theses
                WHERE company_id = ?{_swc('company_id')} ORDER BY created_at""",
            (company_id,)).fetchall())

    return {
        "company_id": company_id,
        "company_name": company["name"],
        "symbol": symbol,
        "since": since,
        "valuation": [{"date": r["point_date"], "value": r["value"]} for r in valuation],
        "events": [{"date": r["event_date"], "title": r["title"], "category": r["category"],
                    "relevance": r["relevance"], "handled": r["inbox_status"] != "待核验"}
                   for r in events],
        "reports": [{"date": r["report_date"], "revenue": r["revenue"],
                     "net_profit": r["net_profit"]} for r in reports],
        "trades": [{"date": str(r["trade_date"])[:10], "side": r["side"], "shares": r["shares"],
                    "price": r["price"], "weight_percent": r["weight_percent"],
                    "rationale": r["rationale"]} for r in trades],
        "theses": [{"id": r["id"], "claim": r["claim"][:60], "status": r["status"],
                    "date": str(r["created_at"])[:10]} for r in theses],
        "boundary": ("这根轴只画已经发生的事：估值分位、实质公告、财报期、你的买卖和写下判断的时点。"
                     "低相关公告（股东大会通知、法律意见书这类）不画——它们会把实质变化盖住。"),
    }


# ---------------------------------------------------------------- 方法体检


def save_assessment(company_id: int, payload: dict[str, Any]) -> int:
    """把一次体检的结果落库。同一家公司同一个方法只留最新一条。

    覆盖而不是追加：体检是「这家公司现在读出来什么样」，不是流水。
    要看历史变化，看的是投资逻辑的修订史（record_revisions），那才是你的判断在变。
    """
    stored = 0
    with connection() as conn:
        for item in payload.get("results", []):
            conn.execute(
                """
                INSERT INTO method_assessments (
                    user_id, company_id, method_key, verdict, summary,
                    evidence, gaps, data_fingerprint, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, company_id, method_key) DO UPDATE SET
                    verdict = excluded.verdict, summary = excluded.summary,
                    evidence = excluded.evidence, gaps = excluded.gaps,
                    data_fingerprint = excluded.data_fingerprint,
                    model = excluded.model, created_at = excluded.created_at
                """,
                (_stamp(), company_id, item["method_key"], item["verdict"], item["summary"],
                 json.dumps(item.get("evidence") or [], ensure_ascii=False),
                 json.dumps(item.get("gaps") or [], ensure_ascii=False),
                 payload.get("fingerprint", ""), payload.get("model", ""), now_iso()),
            )
            stored += 1
    return stored


def list_assessments(company_id: int) -> dict[str, Any]:
    """这家公司存着的体检结果，外加「哪些方法只有你自己能做」。

    两部分一起给，是因为少了后半截就会产生错觉：以为方法库里就这八个，
    以为该做的都已经有人做了。实际上判据在你身上的那七个才是真正拉开差距的地方。
    """
    from .assessment import automatable_methods, fingerprint, manual_methods

    company = get_company(company_id)
    if company is None:
        return None
    with connection() as conn:
        rows = _rows(conn.execute(
            f"SELECT * FROM method_assessments WHERE company_id = ?{_sw()} ORDER BY id",
            (company_id,)).fetchall())
    stored = {row["method_key"]: row for row in rows}

    current = fingerprint(company)
    results = []
    for method in automatable_methods():
        row = stored.get(method.key)
        # **方法本身要跟着结论一起给。** 只给「先分类，再定预期 · 中性」这一行，
        # 用户看不到这个方法到底在分哪几类、凭什么这么分——结论就成了一句无从判断
        # 的断言。方法自带的 one_liner 和 steps 正是那份判据表，一起带上。
        base = {
            "method_key": method.key,
            "method_name": method.name,
            "category": method.category,
            "one_liner": method.one_liner,
            "core_question": method.core_question,
            "steps": list(method.steps),
            "caution": method.caution,
        }
        if row is None:
            results.append({**base, "verdict": "未体检", "summary": "",
                            "evidence": [], "gaps": [], "stale": False, "checked_at": None})
            continue
        results.append({
            **base,
            "verdict": row["verdict"],
            "summary": row["summary"],
            "evidence": json.loads(row["evidence"] or "[]"),
            "gaps": json.loads(row["gaps"] or "[]"),
            # 数据换了版本就标过期，而不是继续显示一个看起来仍然新鲜的结论
            "stale": bool(row["data_fingerprint"] and row["data_fingerprint"] != current),
            "checked_at": row["created_at"],
        })
    return {
        "company_id": company_id,
        "company_name": company.get("name"),
        "results": results,
        "checked": bool(rows),
        "manual": [
            {"method_key": m.key, "method_name": m.name, "category": m.category,
             "core_question": m.core_question, "steps": list(m.steps)}
            for m in manual_methods()
        ],
        "boundary": (
            "体检读的是已同步的事实，回答的是「这个方法在这家公司上说得出什么」，"
            "不给目标价、不说买卖。下面那几个方法的判据在你自己身上，模型代替不了——"
            "它没问过任何一个客户，也不知道你以前是怎么亏的。"
        ),
    }


def assessment_matrix() -> dict[str, Any]:
    """研究池里每家公司在每个方法下的档位，摊成一张表。

    **只收已经体检过的公司。** 把没体检的也列进来，整张表大半是空格，
    真正的差异反而看不出来——那时该做的是去体检，不是盯着一张空表。
    """
    from .assessment import automatable_methods

    methods = automatable_methods()
    with connection() as conn:
        companies = _rows(conn.execute(
            f"""SELECT DISTINCT c.id, c.name, c.symbol
                FROM companies c JOIN method_assessments m ON m.company_id = c.id
                WHERE 1=1{_sw('c')} ORDER BY c.name""").fetchall())
        stored = _rows(conn.execute(
            f"SELECT company_id, method_key, verdict, summary FROM method_assessments WHERE 1=1{_sw()}"
        ).fetchall())

    by_company: dict[int, dict[str, dict[str, Any]]] = {}
    for row in stored:
        by_company.setdefault(row["company_id"], {})[row["method_key"]] = row

    rows = []
    for company in companies:
        own = by_company.get(company["id"], {})
        rows.append({
            "company_id": company["id"],
            "company_name": company["name"],
            "symbol": company["symbol"],
            "results": [{
                "method_key": m.key,
                "method_name": m.name,
                "category": m.category,
                "verdict": (own.get(m.key) or {}).get("verdict", "未体检"),
                "summary": (own.get(m.key) or {}).get("summary", ""),
            } for m in methods],
        })
    return {
        "rows": rows,
        "assessed": len(rows),
        "boundary": ("每一格是模型按那个方法读出来的档位，不是评分、更不是买卖建议。"
                     "一列看下来是「所有公司在这个方法下什么样」，一行看过去是"
                     "「这家公司哪一类方法说得上好话」。"),
    }


def run_assessment(company_id: int) -> dict[str, Any] | None:
    """跑一次体检并落库。"""
    from .assessment import assess_company

    company = get_company(company_id)
    if company is None:
        return None
    with connection() as conn:
        theses = _rows(conn.execute(
            f"SELECT claim FROM theses WHERE company_id = ?{_swc('company_id')}",
            (company_id,)).fetchall())
    payload = assess_company(company, theses)
    save_assessment(company_id, payload)
    return list_assessments(company_id)


def draft_and_save_thesis(company_id: int, method_key: str | None = None) -> dict[str, Any] | None:
    """起草并**直接写进档案**，不留一份要再点一次才生效的草稿。

    原来是两步：生成草稿 → 你点「保存」。问题是生成要二十多秒，而草稿只活在页面上——
    切走一个页签回来它就没了，得重新生成、重新等。实测就这么丢过一次。

    改成一步之后，「草稿」这个中间态由**投资逻辑自己的状态**承担：新写的一律是
    「待观察」，你看完可以修订，也可以删掉（删除是这次一并补上的——之前只能加不能减）。
    模型写的东西本来就该按草稿对待，而不是按「待确认的表单」对待。
    """
    draft = draft_thesis(company_id, method_key)
    if draft is None:
        return None
    created = create_thesis(company_id, ThesisCreate(
        claim=draft.claim,
        counter_condition=draft.counter_condition,
        next_review_trigger=draft.next_review_trigger,
    ))
    if created is None:
        return None
    # **模型没写出认错条件时不能就这么算了。**
    #
    # 人手写的那两个门现在拦着（见 main.post_thesis），但这条路不拦 ——
    # 拦了就等于把已经花掉的一整轮丢掉。可是不拦也不能装作没事：
    # 没有认错条件的判断**静默地退出整张网**，反证比对只查
    # `counter_condition <> ''`，它永远不会被任何事实撞上。
    #
    # 所以照实说一句，让它出现在返回里 —— 页面据此提示补一条。
    missing = not str(created.get("counter_condition") or "").strip()
    return {**created, "method": draft.method, "unknowns": draft.unknowns,
            "needs_counter": missing,
            "note": ("这条还差认错条件 —— 模型这次没写出来。"
                     "补上之前它不会被任何事实撞上（反证比对只看写了条件的）。"
                     if missing else "")}


def draft_thesis(company_id: int, method_key: str | None = None) -> ThesisDraft | None:
    """起草一条投资逻辑。**优先让模型自己查库**，模型不支持工具时回落。

    回落这条路必须留着，也必须留痕：后台模型是可切换的，而工具调用不是每个
    模型都支持。悄悄回落的话，使用者看到的是一条明显变差的草稿而没有任何解释，
    只会以为"这功能今天不太行"。
    """
    from . import drafting

    company = get_company(company_id)
    if company is None:
        return None
    try:
        return ThesisDraft(**drafting.draft_with_tools(
            company, company_tool_runner(company_id), method_key))
    except RuntimeError as exc:
        # 只对"这个模型不支持工具"回落。别的错（查了 8 轮没收敛、JSON 坏了）
        # 照样往上抛——**把它们也吞掉的话，一条半截草稿会被当成正常结果存进库。**
        if "不支持工具调用" not in str(exc):
            raise
        result = draft_with_model(company, method_key)
        result["read"] = (f"当前模型不支持工具调用，这一条是用固定资料写的"
                          f"（{len(drafting.build_prompt(company, method_key)[0])} 字），"
                          f"没有查库。换一个支持 tools 的模型会明显更好。")
        return ThesisDraft(**result)


# ---------------------------------------------------------------- 候选初筛（模型代读）


# 模型给的档位映射到任务条目已有的状态机，不另起一套
# 模型的结论只在「直接排除」这一档动 status —— 那确实等于「我不看了」，
# 而且「已排除」是系统认的值。另外两档不动：它回答的是「要不要花时间」，
# 不是「我处理到哪一步」，后者由人来点。
#
# 老版本这里写的是 {"值得深入": "深入研究", "直接排除": "排除"}，两个值都不在
# TASK_ITEM_STATUSES 里 —— 下拉框选不中、任务的三个计数也数不到，初筛等于白跑。
_VERDICT_STATUS = {"直接排除": "已排除"}


def enrich_task_items(task_id: int, symbols: list[str], on_progress: Callable[[int], None] | None = None) -> int:
    """给候选补上"这家公司是干什么的"：简况、官方入口、券商研报。

    只有指标没有生意描述，判断无从落地。官方入口是按代码拼的，抓取全挂了也点得进去。
    """

    done = 0
    for symbol in symbols:
        try:
            brief = fetch_brief(symbol)
        except Exception:
            brief = {"main_business": None, "introduction": None, "website": None, "source": None}
        try:
            reports = fetch_reports(symbol, limit=5)
        except Exception:
            reports = []
        links = official_links(symbol, brief.get("website"))
        with connection() as conn:
            conn.execute(
                "UPDATE research_task_items SET brief = ?, brief_source = ?, links = ?, reports = ? WHERE task_id = ? AND symbol = ?",
                (
                    (brief.get("main_business") or brief.get("introduction") or "")[:1200],
                    brief.get("source") or "",
                    json.dumps(links, ensure_ascii=False),
                    json.dumps(reports, ensure_ascii=False),
                    task_id,
                    symbol,
                ),
            )
        done += 1
        if on_progress:
            on_progress(done)
        time.sleep(0.35)  # 逐家请求要限速，别把数据源打挂
    return done


def auto_review_task(
    task_id: int,
    limit: int = 30,
    batch: int = 12,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any] | None:
    """让模型把这个任务里还没结论的候选逐家看一遍，只写回结论与去留。

    数字全部由底座提供，模型只读不算；它写不出档案里没有的数值。
    结论会标明来源是模型，人工改写会覆盖它并把来源改成人工。
    """

    task = get_research_task(task_id)
    if task is None:
        return None
    # 找票页先完成过同一策略的复核时，研究任务直接复用那份评语。
    # 这一步必须发生在计算 pending 之前，否则刚带入的结论仍会被重复送进模型。
    _reuse_candidate_review(task_id, task.get("strategy_key"))
    task = get_research_task(task_id)
    if task is None:
        return None
    # 判据是「模型还没看过」，不是「人还没写结论」——后者会让一条你自己
    # 随手写了一句的候选永远轮不到模型看。
    pending = [item for item in task["items"] if not (item.get("conclusion") or "").strip()][:limit]
    # 简况和结论是两件事：已经有结论但缺简况的，也要把简况补上
    missing_brief = [item["symbol"] for item in task["items"] if not (item.get("brief") or "").strip()][:limit]
    if not pending and not missing_brief:
        return {"reviewed": 0, "counts": {}, "note": "这个任务里的候选都已经有结论和简况了。"}
    if not pending:
        filled = enrich_task_items(
            task_id,
            missing_brief,
            on_progress=(lambda done: on_progress(done, len(missing_brief), "正在补公司简况与研报")) if on_progress else None,
        )
        return {
            "reviewed": 0,
            "counts": {},
            "note": f"候选都已经有结论了；补上了 {filled} 家的主营业务、官方入口与券商研报。",
        }

    symbols = [item["symbol"] for item in pending]
    enrich_targets = list(dict.fromkeys(symbols + missing_brief))
    total_steps = len(enrich_targets) + len(symbols)
    # 先补简况：没有"这家公司做什么"，后面的判断落不了地
    enrich_task_items(
        task_id,
        enrich_targets,
        on_progress=(lambda done: on_progress(done, total_steps, "正在补公司简况与研报")) if on_progress else None,
    )

    with connection() as conn:
        universe = {
            row["symbol"]: dict(row)
            for row in conn.execute(
                f"SELECT * FROM market_universe WHERE symbol IN ({','.join('?' * len(pending))})",
                symbols,
            ).fetchall()
        }
        briefs = {
            row["symbol"]: row["brief"]
            for row in conn.execute(
                "SELECT symbol, brief FROM research_task_items WHERE task_id = ?", (task_id,)
            ).fetchall()
        }

    payloads: list[dict[str, Any]] = []
    for item in pending:
        base = universe.get(item["symbol"], {})
        payloads.append({
            **base,
            "symbol": item["symbol"],
            "name": item["name"],
            "industry": item.get("industry"),
            "main_business": briefs.get(item["symbol"]),
        })

    rules_text = "、".join(rule.get("text", "") for rule in (task.get("rules") or []))
    reviewed = 0
    counts: dict[str, int] = {}
    for start in range(0, len(payloads), batch):
        chunk = payloads[start : start + batch]
        try:
            results = review_candidates(chunk, task.get("strategy_name") or "自定义条件", rules_text, task.get("data_note") or "")
        except RuntimeError:
            break
        with connection() as conn:
            for result in results:
                # 结论、支持、待核实各占一列。**拼成一段再存是不行的**：
                # 结论句子里本身就有分号和换行，拼平之后拆不回来。
                conn.execute(
                    """
                    UPDATE research_task_items
                    SET conclusion = ?, verdict = ?, reasons = ?, concerns = ?,
                        status = COALESCE(?, status), updated_at = ?
                    WHERE task_id = ? AND symbol = ?
                      AND (conclusion IS NULL OR conclusion = '')
                    """,
                    (
                        # **不再写进 note。** note 是你自己写的一句话，
                        # 模型那段几百字挤进同一个字段，页面上就是个单行输入框，
                        # 内容看不到，想写自己的还得先把它删掉。
                        result["conclusion"],
                        result["verdict"],
                        json.dumps(result["reasons"], ensure_ascii=False),
                        json.dumps(result["concerns"], ensure_ascii=False),
                        # COALESCE：不是「直接排除」就一个字不改。存量条目可能已经是
                        # 「已建档」，给它盖回「待看」等于把人做过的事抹掉。
                        _VERDICT_STATUS.get(result["verdict"]),
                        now_iso(),
                        task_id,
                        result["symbol"],
                    ),
                )
                counts[result["verdict"]] = counts.get(result["verdict"], 0) + 1
                reviewed += 1
        if on_progress:
            on_progress(len(enrich_targets) + min(start + batch, len(payloads)), total_steps, "模型正在逐家读")

    return {
        "reviewed": reviewed,
        "counts": counts,
        "note": (
            f"模型看了 {reviewed} 家：值得深入 {counts.get('值得深入', 0)} 家、"
            f"先放着 {counts.get('先放着', 0)} 家、直接排除 {counts.get('直接排除', 0)} 家。"
            "它只回答「要不要花时间」，不回答「要不要买」；结论里的数字全部取自底座，"
            "你改写任何一条都会覆盖它。"
        ),
    }


# ---------------------------------------------------------------- 资讯管道


def ensure_news_feeds() -> None:
    """内置源只在缺失时补进表；用户停用或删掉之后不会被重新塞回来。"""

    with connection() as conn:
        # **先修已经落库的那些。** 下面只补缺失的源，从不改已有行 ——
        # 于是内置源的地址写错过一次，线上就一直错着（36 氪那条就是这样）。
        for old_url, new_url in RETIRED_FEED_URLS.items():
            if new_url:
                conn.execute(
                    f"UPDATE news_feeds SET url = ? WHERE builtin = 1 AND url = ?{_sw()}",
                    (new_url, old_url),
                )
            else:
                # 取不到的源留着只会每轮报一次错。停用而不是删掉：
                # 哪天它活过来了，用户自己开回去就行，不用等我们改代码。
                conn.execute(
                    f"UPDATE news_feeds SET enabled = 0 WHERE builtin = 1 AND url = ?{_sw()}",
                    (old_url,),
                )
        existing = {row["key"] for row in conn.execute(f"SELECT key FROM news_feeds WHERE 1=1{_sw()}").fetchall()}
        seeded = bool(existing)
        for feed in DEFAULT_FEEDS:
            if feed["key"] in existing:
                continue
            if seeded:
                # 表已经有内容说明用户管过源了，新增的内置源默认停用，不擅自改变他的订阅
                enabled = 0
            else:
                enabled = 1
            conn.execute(
                "INSERT INTO news_feeds (user_id, key, name, url, enabled, builtin, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                (_stamp(), feed["key"], feed["name"], feed["url"], enabled, now_iso()),
            )


def list_news_feeds() -> list[dict[str, Any]]:
    ensure_news_feeds()
    with connection() as conn:
        return _rows(conn.execute(f"SELECT * FROM news_feeds WHERE 1=1{_sw()} ORDER BY builtin DESC, id").fetchall())


def save_news_feed(payload: NewsFeedInput) -> dict[str, Any]:
    key = payload.key or re.sub(r"[^a-z0-9_]", "_", payload.name.lower())[:40] or f"feed_{int(len(payload.url))}"
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO news_feeds (user_id, key, name, url, enabled, builtin, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET name = excluded.name, url = excluded.url, enabled = excluded.enabled
            """,
            (_stamp(), key, payload.name, str(payload.url), 1 if payload.enabled else 0, now_iso()),
        )
        return dict(conn.execute(f"SELECT * FROM news_feeds WHERE key = ?{_sw()}", (key,)).fetchone())


def toggle_news_feed(feed_id: int, enabled: bool) -> bool:
    with connection() as conn:
        return conn.execute(f"UPDATE news_feeds SET enabled = ? WHERE id = ?{_sw()}", (1 if enabled else 0, feed_id)).rowcount > 0


def delete_news_feed(feed_id: int) -> bool:
    with connection() as conn:
        return conn.execute(f"DELETE FROM news_feeds WHERE id = ? AND builtin = 0{_sw()}", (feed_id,)).rowcount > 0


def _why_feed_failed(exc: Exception) -> str:
    """把抓取失败说成人话。**别把异常类名摆给用户看。**

    页面上原来是这样一行：
        抓取失败的源：同花顺财经：ValueError、澎湃·财经：URLError、36 氪：ParseError
    `ValueError` 对用户没有任何意义，而且它把三件完全不同的事说成了同一种模糊。
    实际上：同花顺是我们读不了 GBK（我们的 bug）、澎湃是服务器连不上、
    36 氪是那个地址返回的是网页不是 RSS —— 三件事该做的处理各不相同。
    """
    import socket
    import urllib.error
    from xml.etree.ElementTree import ParseError

    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return f"站点拒绝了服务器的请求（{exc.code}）"
        if exc.code == 404:
            return "这个地址已经没有了（404）"
        return f"站点返回 {exc.code}"
    if isinstance(exc, urllib.error.URLError) or isinstance(exc, (socket.timeout, TimeoutError)):
        return "连不上这个站点"
    if isinstance(exc, ParseError):
        return "取回来的不是 RSS（多半这个地址现在返回的是网页）"
    if isinstance(exc, ValueError) and "encoding" in str(exc):
        return "这份 RSS 的编码我们读不了"
    return "没取成"


def refresh_news(limit_per_feed: int = 40) -> dict[str, Any]:
    """抓已启用的源，去重入库，再做实体匹配。资讯是二手转述，抓进来只是给人看，不自动成为证据。"""

    ensure_news_feeds()
    timestamp = now_iso()
    fetched = 0
    failures: list[str] = []
    for feed in list_news_feeds():
        if not feed["enabled"]:
            continue
        try:
            items = fetch_feed(feed, limit=limit_per_feed)
        except Exception as exc:  # 单个源挂掉不该拖垮整轮
            failures.append(f"{feed['name']}：{_why_feed_failed(exc)}")
            with connection() as conn:
                conn.execute("UPDATE news_feeds SET last_error = ? WHERE id = ?",
                             (f"{type(exc).__name__}：{exc}"[:200], feed["id"]))
            continue
        new_rows = 0
        with connection() as conn:
            for item in items:
                cursor = conn.execute(
                    """
                    INSERT INTO news_items (user_id, fingerprint, feed_key, feed_name, title, url, summary, published_at, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, fingerprint) DO NOTHING
                    """,
                    (feed.get("user_id") or _stamp(), item["fingerprint"], feed["key"], feed["name"], item["title"],
                     item["url"], item["summary"], item["published_at"], timestamp),
                )
                new_rows += cursor.rowcount
            conn.execute(
                "UPDATE news_feeds SET last_ok_at = ?, last_error = '', item_count = item_count + ? WHERE id = ?",
                (timestamp, new_rows, feed["id"]),
            )
        fetched += new_rows
    matched = match_news()
    note = f"抓到 {fetched} 条新资讯，匹配到公司 {matched['matched']} 条。"
    if failures:
        # 长期抓不到的源等于没有这个源，必须让人看见
        note += f" 抓取失败的源：{('、').join(failures)}。"
    return {"fetched": fetched, "matched": matched["matched"], "failures": failures, "note": note}


def match_news(limit: int = 120, use_ai: bool = True, ai_batch: int = 25) -> dict[str, Any]:
    with connection() as conn:
        companies = [dict(row) for row in conn.execute(f"SELECT id, symbol, name, industry FROM companies WHERE 1=1{_sw()}").fetchall()]
        pending = [
            dict(row)
            for row in conn.execute(
                f"SELECT id, fingerprint, title FROM news_items WHERE match_confidence = '未匹配'{_sw()} ORDER BY published_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    if not companies or not pending:
        return {"matched": 0, "by_rules": 0, "by_model": 0}

    by_rules = 0
    leftover: list[dict[str, Any]] = []
    with connection() as conn:
        for item in pending:
            hit = match_by_rules(item["title"], companies)
            if hit:
                conn.execute(
                    f"UPDATE news_items SET company_id = ?, match_confidence = ?, match_reason = ?, match_source = '规则' WHERE id = ?{_sw()}",
                    (hit["company_id"], hit["confidence"], hit["reason"], item["id"]),
                )
                by_rules += 1
            else:
                leftover.append(item)

    by_model = 0
    if use_ai and leftover:
        for start in range(0, len(leftover), ai_batch):
            chunk = leftover[start : start + ai_batch]
            try:
                results = match_with_model(chunk, companies)
            except RuntimeError:
                break
            with connection() as conn:
                for result in results:
                    conn.execute(
                        f"UPDATE news_items SET company_id = ?, match_confidence = ?, match_reason = ?, match_source = ? WHERE fingerprint = ?{_sw()}",
                        (result["company_id"], result["confidence"], result["reason"], f"模型 {result['model']}", result["fingerprint"]),
                    )
                    if result["company_id"] is not None:
                        by_model += 1
    return {"matched": by_rules + by_model, "by_rules": by_rules, "by_model": by_model}


def list_news(status: str = "待确认", company_id: int | None = None, limit: int = 60, read: str = "全部") -> dict[str, Any]:
    # 「全部」只影响列表，不影响下面的状态与阅读计数。
    scope_clauses: list[str] = []
    scope_params: list[Any] = []
    if company_id is not None:
        scope_clauses.append("n.company_id = ?")
        scope_params.append(company_id)
    # 阅读和处理是两条独立维度。兼容旧调用：以前把“已读/未读”塞在 status 里，
    # 现在统一由 read 参数承载，避免把两种状态拼成一套越来越长的枚举。
    status_filter = "全部" if status in {"已读", "未读"} else status
    read_filter = status if status in {"已读", "未读"} else read
    clauses = list(scope_clauses)
    params: list[Any] = list(scope_params)
    if read_filter in {"已读", "未读"}:
        clauses.append("n.read_at IS NOT NULL" if read_filter == "已读" else "n.read_at IS NULL")
    if status_filter != "全部":
        clauses.append("n.status = ?")
        params.append(status_filter)
    where = " AND ".join(clauses) if clauses else "1=1"
    scoped_where = " AND ".join(scope_clauses) if scope_clauses else "1=1"
    with connection() as conn:
        rows = _rows(
            conn.execute(
                f"""
                SELECT n.*, c.name AS company_name, c.symbol AS symbol
                FROM news_items n LEFT JOIN companies c ON c.id = n.company_id
                WHERE {where}{_sw('n')}
                ORDER BY n.published_at DESC, n.id DESC LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        )
        totals = dict(
            conn.execute(
                f"SELECT COUNT(*) AS total, SUM(CASE WHEN n.company_id IS NOT NULL THEN 1 ELSE 0 END) AS linked FROM news_items n WHERE {where}{_sw('n')}",
                tuple(params),
            ).fetchone()
        )
        status_rows = conn.execute(
            f"SELECT n.status, COUNT(*) AS count FROM news_items n WHERE {scoped_where}{_sw('n')} GROUP BY n.status",
            tuple(scope_params),
        ).fetchall()
        read_totals = dict(
            conn.execute(
                f"SELECT SUM(CASE WHEN n.read_at IS NOT NULL THEN 1 ELSE 0 END) AS read_count, "
                f"SUM(CASE WHEN n.read_at IS NULL THEN 1 ELSE 0 END) AS unread_count "
                f"FROM news_items n WHERE {scoped_where}{_sw('n')}",
                tuple(scope_params),
            ).fetchone()
        )
    status_counts = {str(row["status"]): int(row["count"] or 0) for row in status_rows}
    all_count = sum(status_counts.values())
    return {
        "items": rows,
        "total": int(totals["total"] or 0),
        "linked": int(totals["linked"] or 0),
        "all": all_count,
        "pending": status_counts.get("待确认", 0),
        "archived": status_counts.get("已归档", 0),
        "ignored": status_counts.get("已忽略", 0),
        "read": int(read_totals["read_count"] or 0),
        "unread": int(read_totals["unread_count"] or 0),
        "boundary": (
            "资讯是二手转述，不是交易所披露的一手事实。它不会自动进入公司时间线；"
            "打开原文或点“标记已读”会留下阅读状态；只有你确认过之后，它才会以摘录归档为证据。"
        ),
    }


def mark_news_read(news_id: int) -> dict[str, Any] | None:
    """记录一次阅读动作。幂等：重复打开不会刷新最初的阅读时间。"""

    timestamp = now_iso()
    with connection() as conn:
        updated = conn.execute(
            f"UPDATE news_items SET read_at = COALESCE(read_at, ?) WHERE id = ?{_sw()}",
            (timestamp, news_id),
        ).rowcount
        if not updated:
            return None
        row = conn.execute(f"SELECT read_at FROM news_items WHERE id = ?{_sw()}", (news_id,)).fetchone()
    return {"news_id": news_id, "read": True, "read_at": row["read_at"]}


def confirm_news(news_id: int, company_id: int | None = None) -> dict[str, Any] | None:
    """确认一条资讯并归档为证据。摘录用原标题与摘要，来源写明是媒体转述。"""

    with connection() as conn:
        item = conn.execute(f"SELECT * FROM news_items WHERE id = ?{_sw()}", (news_id,)).fetchone()
        if item is None:
            return None
        item = dict(item)
    target = company_id if company_id is not None else item["company_id"]
    if target is None:
        raise LedgerError("这条资讯还没有对应到公司，请先指定公司。")
    excerpt = f"{item['title']}｜{item['summary']}".strip("｜")[:1400]
    created = create_evidence(
        target,
        EvidenceCreate(
            source_name=f"{item['feed_name']}（媒体转述）",
            source_url=item["url"] or None,
            excerpt=excerpt,
            polarity=EvidencePolarity.neutral,
            occurred_at=datetime.fromisoformat(item["published_at"]),
            verification="待核验",
        ),
    )
    if not created:
        raise LedgerError("归档失败：未找到对应公司。")
    handled_at = now_iso()
    with connection() as conn:
        conn.execute(
            f"UPDATE news_items SET status = '已归档', company_id = ?, archived_ref_id = ?, read_at = COALESCE(read_at, ?), handled_at = ? WHERE id = ?{_sw()}",
            (target, created["id"], handled_at, handled_at, news_id),
        )
    return {"news_id": news_id, "evidence_id": created["id"]}


def ignore_news(news_id: int) -> bool:
    handled_at = now_iso()
    with connection() as conn:
        return conn.execute(
            f"UPDATE news_items SET status = '已忽略', read_at = COALESCE(read_at, ?), handled_at = ? WHERE id = ? AND status = '待确认'{_sw()}",
            (handled_at, handled_at, news_id),
        ).rowcount > 0


# ---------------------------------------------------------------- 产业链底图


_INDUSTRY_CHAIN_SKELETONS: dict[str, list[tuple[str, str]]] = {
    # 这里只给研究者一张空白的结构纸，不预填行业、公司或产品事实。
    "制造链": [
        ("原料与资源", "input"),
        ("部件与设备", "input"),
        ("生产制造", "core"),
        ("渠道交付", "output"),
        ("终端应用", "output"),
    ],
    "服务链": [
        ("获客与资源", "input"),
        ("产品与定价", "core"),
        ("履约与服务", "core"),
        ("客户与场景", "output"),
    ],
    "平台生态": [
        ("供给与能力", "input"),
        ("平台产品", "core"),
        ("分发与协同", "core"),
        ("用户场景", "output"),
    ],
}


# 开箱即用的行业底图。这里只预置公开资料明确写到的产品、服务与交付环节，
# **不预置任何公司位置**：某家公司到底覆盖哪个节点，仍要回到年报、公告或官网确认。
# 这些主题会在当前用户第一次打开产业链页时写入自己的数据域；之后可以继续增补，
# 但不能整张删除，避免页面再次退回“什么都没有”的半成品状态。
_DEFAULT_INDUSTRY_CHAIN_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "name": "保险产品与服务",
        "chain_type": "服务链",
        "description": "从客户触达、保险产品与承保，到保全理赔和风险保障场景。",
        "source_name": "国家金融监督管理总局 · 中华人民共和国保险法",
        "source_url": "https://www.nfra.gov.cn/chinese/docfile/2025/ca8d8237bdf746e9a3bff26a3bf2af39.pdf",
        "stages": (
            ("客户触达", "input", (
                ("保险代理与经纪", "渠道", "通过代理人、经纪人与专业中介触达客户。"),
                ("银行保险渠道", "渠道", "通过银行网点及其线上入口触达客户。"),
                ("线上直销", "渠道", "保险公司自营线上渠道与互联网触点。"),
            )),
            ("产品与承保", "core", (
                ("人寿保险", "服务", "以人的寿命为保险标的的人身保险业务。"),
                ("健康保险", "服务", "围绕疾病、医疗与健康风险提供保障。"),
                ("意外伤害保险", "服务", "围绕意外伤害及其后果提供保障。"),
                ("财产与责任保险", "服务", "覆盖财产损失、责任、信用与保证等风险。"),
            )),
            ("履约与资金", "core", (
                ("核保与承保", "服务", "评估风险、确定承保条件并形成保险合同。"),
                ("保全服务", "服务", "处理合同存续期内的信息和权益变更。"),
                ("理赔与给付", "服务", "保险事故发生后审核并赔偿或给付。"),
                ("再保险", "服务", "通过分入、分出分散保险经营风险。"),
                ("保险资金运用", "服务", "管理承保形成的保险资金与资产。"),
            )),
            ("保障场景", "output", (
                ("个人与家庭保障", "应用", "寿命、健康、意外与家庭财产风险。"),
                ("企业与团体保障", "应用", "企业财产、责任、信用和员工保障。"),
                ("养老与健康管理", "应用", "长期养老保障与健康服务场景。"),
            )),
        ),
        "edges": (
            ("保险代理与经纪", "人寿保险", "需求触达"),
            ("银行保险渠道", "健康保险", "渠道销售"),
            ("线上直销", "意外伤害保险", "线上投保"),
            ("人寿保险", "核保与承保", "风险审核"),
            ("健康保险", "核保与承保", "风险审核"),
            ("财产与责任保险", "核保与承保", "风险审核"),
            ("核保与承保", "保全服务", "合同存续"),
            ("保全服务", "理赔与给付", "保险履约"),
            ("理赔与给付", "个人与家庭保障", "风险补偿"),
            ("理赔与给付", "企业与团体保障", "风险补偿"),
        ),
    },
    {
        "name": "白酒生产与消费",
        "chain_type": "制造链",
        "description": "从粮谷与包装材料、酿造陈储，到成品流通和终端消费。",
        "source_name": "工业和信息化部 · 宜宾市白酒行业数字化转型实践样本",
        "source_url": "https://zjtx.miit.gov.cn/hy/%E5%AE%9C%E5%AE%BE%E5%B8%82%E7%99%BD%E9%85%92%E8%A1%8C%E4%B8%9A%E4%B8%AD%E5%B0%8F%E4%BC%81%E4%B8%9A%E6%95%B0%E5%AD%97%E5%8C%96%E8%BD%AC%E5%9E%8B%E5%AE%9E%E8%B7%B5%E6%A0%B7%E6%9C%AC.pdf",
        "stages": (
            ("原料与配套", "input", (
                ("高粱等粮谷", "原材料", "高粱、大米、小麦等酿酒原料。"),
                ("制曲原料", "原材料", "用于制曲和糖化发酵的粮谷原料。"),
                ("玻璃与陶瓷容器", "部件", "酒瓶、酒坛等储存和包装容器。"),
                ("纸制包装", "部件", "纸盒、纸箱等外包装。"),
                ("酿造与灌装设备", "设备", "发酵、蒸馏、输送和灌装设备。"),
            )),
            ("酿造生产", "core", (
                ("制曲", "环节", "培养糖化发酵所需的酒曲。"),
                ("蒸煮与糖化", "环节", "处理粮谷并把淀粉转化为可发酵糖。"),
                ("发酵与蒸馏", "环节", "经发酵、蒸馏形成原酒。"),
                ("基酒与原酒", "产品", "进入储存和勾调环节的半成品白酒。"),
            )),
            ("陈储与成品", "core", (
                ("储存陈酿", "环节", "基酒在适宜条件下储存与老熟。"),
                ("勾调", "环节", "按产品标准完成酒体设计与调配。"),
                ("灌装包装", "环节", "将成品酒灌装、包装并入库。"),
                ("成品白酒", "产品", "浓香、酱香、清香及其他香型产品。"),
            )),
            ("流通与消费", "output", (
                ("经销与零售", "渠道", "经销商、门店及商超等流通渠道。"),
                ("电商与直营网", "渠道", "线上平台和品牌直营渠道。"),
                ("终端消费", "应用", "餐饮、宴席、礼赠与家庭消费等场景。"),
            )),
        ),
        "edges": (
            ("高粱等粮谷", "蒸煮与糖化", "原料投入"),
            ("制曲原料", "制曲", "原料投入"),
            ("制曲", "发酵与蒸馏", "糖化发酵"),
            ("蒸煮与糖化", "发酵与蒸馏", "进入发酵"),
            ("发酵与蒸馏", "基酒与原酒", "形成"),
            ("基酒与原酒", "储存陈酿", "入库陈储"),
            ("储存陈酿", "勾调", "酒体设计"),
            ("勾调", "灌装包装", "形成成品"),
            ("灌装包装", "成品白酒", "交付"),
            ("成品白酒", "经销与零售", "流通"),
            ("成品白酒", "电商与直营网", "流通"),
            ("经销与零售", "终端消费", "销售"),
        ),
    },
    {
        "name": "家电制造与交付",
        "chain_type": "制造链",
        "description": "从基础材料与核心零部件、整机制造，到渠道交付和售后服务。",
        "source_name": "商务部贸易救济信息网 · 家电产业链分析",
        "source_url": "https://cacs.mofcom.gov.cn/article/flfwpt/jyjdy/cgal/202003/163321.html",
        "stages": (
            ("基础材料", "input", (
                ("钢板与金属材料", "原材料", "冷轧钢板、铜铝材等结构和导热材料。"),
                ("塑料与化工材料", "原材料", "外壳、保温、发泡及其他结构材料。"),
                ("电子元器件", "部件", "传感器、连接器、开关和电容等。"),
            )),
            ("核心零部件", "input", (
                ("压缩机", "部件", "制冷家电的核心动力部件。"),
                ("电机", "部件", "驱动压缩、风机和洗涤等机构。"),
                ("热交换器", "部件", "冷凝器、蒸发器等换热部件。"),
                ("电控系统", "部件", "控制器、功率器件与人机交互组件。"),
                ("结构件", "部件", "外壳、钣金、塑料与五金结构件。"),
            )),
            ("整机制造", "core", (
                ("空调", "产品", "家用及商用空气调节设备。"),
                ("冰箱与冷柜", "产品", "家用及商用制冷储藏设备。"),
                ("洗衣与清洁电器", "产品", "洗衣机及家庭清洁类电器。"),
                ("厨房与生活电器", "产品", "烹饪、热水与小家电产品。"),
            )),
            ("渠道与服务", "output", (
                ("经销与零售", "渠道", "经销商、连锁门店和专业零售。"),
                ("电商与直营网", "渠道", "平台电商和品牌自营渠道。"),
                ("物流安装", "服务", "仓储配送、入户安装与调试。"),
                ("维修与售后", "服务", "保修、维修和零部件服务。"),
            )),
            ("应用场景", "output", (
                ("家庭空间", "应用", "居住空间的制冷、清洁和生活需求。"),
                ("商业与公共空间", "应用", "办公、商业和公共设施应用。"),
            )),
        ),
        "edges": (
            ("钢板与金属材料", "结构件", "材料加工"),
            ("电子元器件", "电控系统", "部件集成"),
            ("压缩机", "空调", "整机装配"),
            ("热交换器", "空调", "整机装配"),
            ("电机", "洗衣与清洁电器", "整机装配"),
            ("电控系统", "厨房与生活电器", "整机装配"),
            ("空调", "经销与零售", "销售流通"),
            ("冰箱与冷柜", "电商与直营网", "销售流通"),
            ("经销与零售", "物流安装", "履约"),
            ("物流安装", "家庭空间", "交付"),
            ("维修与售后", "商业与公共空间", "持续服务"),
        ),
    },
    {
        "name": "锂电池材料与应用",
        "chain_type": "制造链",
        "description": "从锂资源与四大关键材料、电芯和电池系统，到动力、储能和消费应用。",
        "source_name": "工业和信息化部 · 全国锂离子电池行业运行情况",
        "source_url": "https://www.miit.gov.cn/gxsj/tjfx/dzxx/art/2024/art_7de3ac5f07514eec80039a81aa2e22d8.html",
        "stages": (
            ("资源与锂盐", "input", (
                ("锂矿与盐湖资源", "原材料", "锂精矿、盐湖卤水等资源来源。"),
                ("碳酸锂", "原材料", "正极材料和电解质的重要锂盐原料。"),
                ("氢氧化锂", "原材料", "高镍正极等路线使用的锂盐原料。"),
            )),
            ("关键材料", "input", (
                ("正极材料", "原材料", "磷酸铁锂、三元及其他正极体系。"),
                ("负极材料", "原材料", "石墨、硅基及其他负极体系。"),
                ("隔膜", "部件", "隔离正负极并允许锂离子通过。"),
                ("电解液", "原材料", "在正负极之间传导锂离子。"),
                ("铜箔与铝箔", "部件", "电极集流体及相关辅助材料。"),
            )),
            ("电芯与系统", "core", (
                ("电芯制造", "产品", "将正负极、隔膜与电解液装配为电芯。"),
                ("模组与PACK", "产品", "电芯组合、结构与热管理集成。"),
                ("电池管理系统", "部件", "监控电池状态并执行安全和能量管理。"),
            )),
            ("终端应用", "output", (
                ("动力电池", "应用", "新能源汽车及其他交通工具动力系统。"),
                ("储能电池", "应用", "电源侧、电网侧和用户侧储能。"),
                ("消费型电池", "应用", "手机、电脑与其他消费电子设备。"),
            )),
        ),
        "edges": (
            ("锂矿与盐湖资源", "碳酸锂", "提炼加工"),
            ("锂矿与盐湖资源", "氢氧化锂", "提炼加工"),
            ("碳酸锂", "正极材料", "材料制备"),
            ("氢氧化锂", "正极材料", "材料制备"),
            ("正极材料", "电芯制造", "电极装配"),
            ("负极材料", "电芯制造", "电极装配"),
            ("隔膜", "电芯制造", "电芯装配"),
            ("电解液", "电芯制造", "电芯装配"),
            ("电芯制造", "模组与PACK", "系统集成"),
            ("电池管理系统", "模组与PACK", "安全管理"),
            ("模组与PACK", "动力电池", "应用交付"),
            ("模组与PACK", "储能电池", "应用交付"),
            ("电芯制造", "消费型电池", "应用交付"),
        ),
    },
)

# 第二批系统底图。仍然只表达产品、服务与交付环节，不把任何上市公司硬钉到节点上。
# 一张图至少覆盖“投入—核心产品/服务—交付—客户/应用”，避免退化成上下游名词清单。
_DEFAULT_INDUSTRY_CHAIN_TEMPLATES += (
    {
        "name": "银行信贷与支付",
        "chain_type": "服务链",
        "description": "从资金与客户账户、授信定价，到信贷投放、支付清算和企业现金管理。",
        "source_name": "中国人民银行 · 支付结算办法",
        "source_url": "https://www.pbc.gov.cn/zhengwugongkai/attachDir/2025/11/2025111818072979794.pdf",
        "stages": (
            ("资金与账户", "input", (
                ("个人与企业存款", "资金", "个人、企业和机构沉淀在银行账户中的资金。"),
                ("同业与央行资金", "资金", "同业融资、公开市场和央行工具形成的资金来源。"),
                ("账户与客户识别", "服务", "开立账户、身份识别和客户信息管理。"),
            )),
            ("风险与定价", "core", (
                ("信用评估", "服务", "评估借款人的偿付能力、现金流和信用记录。"),
                ("授信审批", "服务", "确定授信额度、期限、担保与使用条件。"),
                ("利率与风险定价", "服务", "结合资金成本和风险确定产品价格。"),
            )),
            ("信贷与产品", "core", (
                ("公司贷款", "产品", "面向企业经营、项目和流动资金需求的融资。"),
                ("零售信贷", "产品", "住房、消费、经营等个人信贷产品。"),
                ("票据与供应链金融", "产品", "围绕贸易、应收账款和票据提供融资与结算。"),
                ("财富与现金管理", "服务", "存款、理财代销和企业资金归集等服务。"),
            )),
            ("支付与清算", "core", (
                ("转账与支付受理", "服务", "通过账户、银行卡和线上渠道发起支付。"),
                ("清算与结算", "服务", "完成支付指令交换、资金清算和最终结算。"),
                ("风控与反欺诈", "服务", "识别异常交易并控制支付和账户风险。"),
            )),
            ("客户场景", "output", (
                ("个人金融", "应用", "日常支付、消费、住房和财富管理。"),
                ("企业经营", "应用", "采购、销售、工资、融资和现金管理。"),
                ("公共与跨境服务", "应用", "公共缴费、贸易结算和跨境资金服务。"),
            )),
        ),
        "edges": (
            ("个人与企业存款", "公司贷款", "资金转化"),
            ("账户与客户识别", "信用评估", "客户识别"),
            ("信用评估", "授信审批", "风险判断"),
            ("授信审批", "公司贷款", "授信投放"),
            ("授信审批", "零售信贷", "授信投放"),
            ("公司贷款", "企业经营", "融资支持"),
            ("票据与供应链金融", "企业经营", "贸易支持"),
            ("转账与支付受理", "清算与结算", "支付处理"),
            ("清算与结算", "个人金融", "资金交付"),
            ("清算与结算", "公共与跨境服务", "资金交付"),
        ),
    },
    {
        "name": "证券与财富管理",
        "chain_type": "服务链",
        "description": "连接融资方与投资者，覆盖证券经纪、投行、信用、资管和财富配置。",
        "source_name": "中国证监会 · 证券市场中介机构",
        "source_url": "https://www.csrc.gov.cn/csrc/c100211/c1452109/content.shtml",
        "stages": (
            ("客户与资产", "input", (
                ("个人投资者", "客户", "有交易、配置和财富管理需求的个人客户。"),
                ("机构投资者", "客户", "基金、保险、银行理财和企业等机构客户。"),
                ("企业融资方", "客户", "需要股权、债券或并购融资的企业。"),
            )),
            ("交易服务", "core", (
                ("开户与托管", "服务", "投资者账户、资产托管和客户适当性管理。"),
                ("证券经纪", "服务", "接受委托、处理交易指令并办理清算交收。"),
                ("融资融券", "产品", "以信用账户提供融资和证券借贷。"),
                ("研究与投资顾问", "服务", "提供研究、资产配置和投资咨询。"),
            )),
            ("投资银行", "core", (
                ("IPO与再融资", "服务", "上市保荐、股票承销和再融资服务。"),
                ("债券承销", "服务", "企业和政府相关债券的发行承销。"),
                ("并购与财务顾问", "服务", "并购重组、资产交易和融资安排。"),
            )),
            ("资管与财富", "core", (
                ("券商资产管理", "产品", "受托管理客户资产并形成资管产品。"),
                ("金融产品代销", "服务", "向客户筛选和销售基金等金融产品。"),
                ("财富配置", "服务", "围绕风险偏好配置多类资产和服务。"),
            )),
            ("市场基础设施", "output", (
                ("交易场所", "基础设施", "证券交易和挂牌转让的组织场所。"),
                ("登记托管", "基础设施", "证券登记、存管和持有人名册服务。"),
                ("清算交收", "基础设施", "成交后的清算、结算和风险管理。"),
            )),
        ),
        "edges": (
            ("个人投资者", "开户与托管", "建立账户"),
            ("开户与托管", "证券经纪", "委托交易"),
            ("证券经纪", "清算交收", "成交结算"),
            ("机构投资者", "券商资产管理", "委托管理"),
            ("企业融资方", "IPO与再融资", "股权融资"),
            ("企业融资方", "债券承销", "债权融资"),
            ("企业融资方", "并购与财务顾问", "资本运作"),
            ("金融产品代销", "财富配置", "产品配置"),
            ("研究与投资顾问", "财富配置", "配置建议"),
            ("交易场所", "登记托管", "成交登记"),
        ),
    },
    {
        "name": "AI 数据中心",
        "chain_type": "平台生态",
        "description": "从机房、供配电和液冷，到AI芯片、服务器、算力平台及训练推理应用。",
        "source_name": "工业和信息化部 · 新型数据中心发展三年行动计划",
        "source_url": "https://www.miit.gov.cn/jgsj/txs/wjfb/art/2021/art_12cc04dc9daf4d57a7038811a57383b6.html",
        "stages": (
            ("机房基础设施", "input", (
                ("机房工程", "基础设施", "建筑、机柜、综合布线和消防等设施。"),
                ("供配电与UPS", "设备", "为高密度算力设备提供稳定电力。"),
                ("液冷与制冷", "设备", "带走服务器热量并控制能效。"),
                ("监控与运维", "服务", "监控能耗、环境、设备和安全状态。"),
            )),
            ("算力硬件", "input", (
                ("AI加速芯片", "部件", "承担模型训练和推理的并行计算。"),
                ("AI服务器", "设备", "集成处理器、加速卡和高速互连。"),
                ("存储系统", "设备", "保存训练数据、模型和业务数据。"),
                ("高速网络", "设备", "连接服务器、存储和数据中心集群。"),
            )),
            ("数据中心", "core", (
                ("通用数据中心", "服务", "提供通用计算、存储和托管能力。"),
                ("智能计算中心", "服务", "面向AI训练与推理提供高密度算力。"),
                ("边缘数据中心", "服务", "在靠近业务现场的位置提供低时延计算。"),
            )),
            ("算力平台", "core", (
                ("云计算服务", "平台", "以弹性资源方式交付计算、存储和网络。"),
                ("算力调度平台", "平台", "统一编排异构算力和任务队列。"),
                ("模型开发平台", "平台", "提供数据、训练、评测和部署工具。"),
            )),
            ("AI应用", "output", (
                ("模型训练", "应用", "大模型和行业模型的预训练与微调。"),
                ("在线推理", "应用", "面向终端请求提供模型推理服务。"),
                ("行业智能化", "应用", "制造、金融、医疗、政务等行业应用。"),
            )),
        ),
        "edges": (
            ("供配电与UPS", "AI服务器", "供电保障"),
            ("液冷与制冷", "AI服务器", "散热保障"),
            ("AI加速芯片", "AI服务器", "硬件集成"),
            ("存储系统", "智能计算中心", "数据供给"),
            ("高速网络", "智能计算中心", "集群互连"),
            ("AI服务器", "智能计算中心", "算力部署"),
            ("智能计算中心", "算力调度平台", "资源供给"),
            ("算力调度平台", "模型开发平台", "资源编排"),
            ("模型开发平台", "模型训练", "开发交付"),
            ("云计算服务", "在线推理", "服务交付"),
            ("在线推理", "行业智能化", "能力嵌入"),
        ),
    },
    {
        "name": "半导体",
        "chain_type": "制造链",
        "description": "从材料与设备、芯片设计和晶圆制造，到封装测试及终端应用。",
        "source_name": "工业和信息化部 · 集成电路产业发展有关情况",
        "source_url": "https://www.miit.gov.cn/jgsj/ghs/wjfb/art/2020/art_e5b943f217f74785b7170b941c76b031.html",
        "stages": (
            ("材料与设备", "input", (
                ("硅片与化合物材料", "原材料", "晶圆制造使用的衬底材料。"),
                ("电子化学品与特气", "原材料", "光刻、清洗、刻蚀和沉积所需材料。"),
                ("光刻与刻蚀设备", "设备", "形成并转移芯片图形的核心设备。"),
                ("薄膜与检测设备", "设备", "沉积薄膜并进行过程量测和缺陷检测。"),
            )),
            ("芯片设计", "core", (
                ("IP与EDA", "工具", "提供可复用设计模块和自动化设计工具。"),
                ("数字芯片设计", "服务", "处理器、存储、通信和控制芯片设计。"),
                ("模拟与功率芯片设计", "服务", "电源、信号链和功率半导体设计。"),
            )),
            ("晶圆制造", "core", (
                ("晶圆代工", "服务", "按照设计完成光刻、刻蚀、沉积和互连。"),
                ("特色工艺制造", "服务", "模拟、功率、传感器等特色工艺生产。"),
                ("晶圆检测", "服务", "在封装前检测芯片电性和缺陷。"),
            )),
            ("封装测试", "core", (
                ("传统封装", "服务", "切割、装片、互连和塑封形成芯片产品。"),
                ("先进封装", "服务", "通过倒装、晶圆级和多芯粒提升系统性能。"),
                ("成品测试", "服务", "验证芯片功能、性能与可靠性。"),
            )),
            ("终端应用", "output", (
                ("消费与通信", "应用", "手机、电脑、网络和消费电子。"),
                ("汽车与工业", "应用", "汽车电子、工业控制和能源设备。"),
                ("数据中心与AI", "应用", "服务器、存储和人工智能算力。"),
            )),
        ),
        "edges": (
            ("IP与EDA", "数字芯片设计", "设计支撑"),
            ("数字芯片设计", "晶圆代工", "设计流片"),
            ("模拟与功率芯片设计", "特色工艺制造", "设计流片"),
            ("硅片与化合物材料", "晶圆代工", "材料投入"),
            ("光刻与刻蚀设备", "晶圆代工", "制造装备"),
            ("晶圆代工", "晶圆检测", "过程验证"),
            ("晶圆检测", "先进封装", "合格晶圆"),
            ("先进封装", "成品测试", "封测交付"),
            ("成品测试", "汽车与工业", "芯片交付"),
            ("成品测试", "数据中心与AI", "芯片交付"),
        ),
    },
    {
        "name": "新能源汽车",
        "chain_type": "制造链",
        "description": "从关键材料与三电系统、智能化零部件，到整车制造、补能和回收服务。",
        "source_name": "国务院办公厅 · 新能源汽车产业发展规划（2021—2035年）",
        "source_url": "https://www.miit.gov.cn/xwdt/szyw/art/2020/art_4390362916324365a260ed97d7558f18.html",
        "stages": (
            ("材料与基础件", "input", (
                ("电池关键材料", "原材料", "正负极、隔膜、电解液等电池材料。"),
                ("轻量化材料", "原材料", "高强钢、铝合金和复合材料。"),
                ("汽车半导体", "部件", "功率、控制、传感和计算芯片。"),
            )),
            ("核心系统", "input", (
                ("动力电池系统", "部件", "电芯、PACK和电池管理系统。"),
                ("驱动电机", "部件", "将电能转化为车辆驱动力。"),
                ("电控与功率电子", "部件", "控制能量转换、驱动和整车运行。"),
                ("智能座舱与驾驶", "部件", "感知、计算、通信和软件系统。"),
            )),
            ("整车制造", "core", (
                ("纯电动汽车", "产品", "以动力电池和电机驱动的整车。"),
                ("插混与增程汽车", "产品", "组合电驱与燃油能源系统的整车。"),
                ("燃料电池汽车", "产品", "以燃料电池系统供能的整车。"),
            )),
            ("补能与运营", "output", (
                ("充电设备", "设备", "交流、直流及大功率充电设施。"),
                ("充换电运营", "服务", "站点建设、运营、支付和能源管理。"),
                ("车联网服务", "服务", "云控、数据、导航和远程服务。"),
            )),
            ("使用与循环", "output", (
                ("乘用与商用出行", "应用", "私人、公共和物流运输场景。"),
                ("售后维保", "服务", "车辆、三电和软件维护升级。"),
                ("电池梯次与回收", "服务", "退役电池检测、梯次利用和材料回收。"),
            )),
        ),
        "edges": (
            ("电池关键材料", "动力电池系统", "材料集成"),
            ("汽车半导体", "电控与功率电子", "控制支撑"),
            ("动力电池系统", "纯电动汽车", "整车装配"),
            ("驱动电机", "纯电动汽车", "整车装配"),
            ("电控与功率电子", "插混与增程汽车", "整车装配"),
            ("智能座舱与驾驶", "纯电动汽车", "智能化集成"),
            ("纯电动汽车", "充换电运营", "补能需求"),
            ("充电设备", "充换电运营", "设施交付"),
            ("充换电运营", "乘用与商用出行", "能源交付"),
            ("售后维保", "电池梯次与回收", "退役流转"),
        ),
    },
    {
        "name": "光伏发电",
        "chain_type": "制造链",
        "description": "从硅料、硅片、电池片和组件，到逆变器、光伏系统建设及电站运营。",
        "source_name": "工业和信息化部 · 全国光伏制造行业运行情况",
        "source_url": "https://www.miit.gov.cn/jgsj/dzs/gzdt/art/2024/art_23c220a8b3b34340851632dfae47a34e.html",
        "stages": (
            ("硅料与辅材", "input", (
                ("工业硅与多晶硅", "原材料", "晶硅光伏产品的上游硅材料。"),
                ("光伏玻璃", "部件", "保护电池片并保证光线透过。"),
                ("胶膜与背板", "部件", "封装、防护并提高组件可靠性。"),
                ("银浆与焊带", "原材料", "形成电极并连接电池片。"),
            )),
            ("硅片与电池", "core", (
                ("单晶硅片", "产品", "由硅棒切片形成电池片衬底。"),
                ("P型电池片", "产品", "PERC等P型晶硅电池技术产品。"),
                ("N型电池片", "产品", "TOPCon、HJT等N型技术产品。"),
            )),
            ("组件与设备", "core", (
                ("光伏组件", "产品", "将电池片串联封装为发电组件。"),
                ("光伏逆变器", "设备", "把直流电转换为并网使用的交流电。"),
                ("支架与跟踪系统", "设备", "支撑组件并优化受光角度。"),
                ("储能系统", "设备", "平滑发电波动并进行能量管理。"),
            )),
            ("系统建设", "output", (
                ("集中式电站", "应用", "大规模地面光伏发电项目。"),
                ("分布式光伏", "应用", "工商业和户用屋顶等就近发电。"),
                ("EPC与并网", "服务", "设计、采购、施工、调试和并网。"),
            )),
            ("发电运营", "output", (
                ("电站运维", "服务", "监控、检修、清洗和发电效率管理。"),
                ("电力销售", "服务", "通过电网或市场完成电量交易与结算。"),
            )),
        ),
        "edges": (
            ("工业硅与多晶硅", "单晶硅片", "拉晶切片"),
            ("单晶硅片", "P型电池片", "电池制造"),
            ("单晶硅片", "N型电池片", "电池制造"),
            ("N型电池片", "光伏组件", "串焊封装"),
            ("光伏玻璃", "光伏组件", "组件封装"),
            ("光伏组件", "集中式电站", "系统集成"),
            ("光伏逆变器", "分布式光伏", "电能转换"),
            ("支架与跟踪系统", "集中式电站", "系统集成"),
            ("EPC与并网", "电站运维", "项目交付"),
            ("电站运维", "电力销售", "发电交付"),
        ),
    },
    {
        "name": "粮油食品加工",
        "chain_type": "制造链",
        "description": "从粮油种植与收购、仓储物流，到米面油初加工、食品深加工和消费流通。",
        "source_name": "辽宁省粮食和物资储备局 · 粮食加工产业指导意见",
        "source_url": "https://lcj.ln.gov.cn/lswzcb/xwdt24/sjdt/2024091908395463151/index.shtml",
        "stages": (
            ("农业与原粮", "input", (
                ("稻谷与小麦", "原材料", "大米和面粉加工的主要原粮。"),
                ("玉米", "原材料", "食品、淀粉、饲料和深加工原料。"),
                ("大豆与油料", "原材料", "植物油、蛋白和饲料原料。"),
                ("收购与贸易", "服务", "连接种植端、进口和加工企业。"),
            )),
            ("仓储与物流", "input", (
                ("粮食仓储", "服务", "清理、干燥、检测和安全储存。"),
                ("港口与铁路中转", "服务", "完成大宗粮油跨区域运输。"),
                ("冷链与配送", "服务", "保障易腐食品储运和终端配送。"),
            )),
            ("基础加工", "core", (
                ("大米加工", "产品", "稻谷碾磨、分级和包装。"),
                ("面粉加工", "产品", "小麦制粉及专用粉生产。"),
                ("油脂压榨与精炼", "产品", "油料压榨、浸出、精炼和灌装。"),
                ("淀粉与饲料", "产品", "玉米、大豆等副产物综合加工。"),
            )),
            ("食品深加工", "core", (
                ("主食与烘焙食品", "产品", "米面主食、烘焙和方便食品。"),
                ("调味与功能食品", "产品", "调味品、营养和功能性食品。"),
                ("休闲与预制食品", "产品", "休闲、冷冻和预制食品。"),
            )),
            ("渠道与消费", "output", (
                ("商超与经销", "渠道", "商超、批发和区域经销网络。"),
                ("餐饮与食品工业", "客户", "餐饮企业和其他食品制造商。"),
                ("电商与家庭消费", "应用", "线上零售和家庭消费场景。"),
            )),
        ),
        "edges": (
            ("稻谷与小麦", "粮食仓储", "收储"),
            ("大豆与油料", "港口与铁路中转", "进口中转"),
            ("粮食仓储", "大米加工", "原粮供应"),
            ("粮食仓储", "面粉加工", "原粮供应"),
            ("大豆与油料", "油脂压榨与精炼", "压榨精炼"),
            ("大米加工", "主食与烘焙食品", "原料供给"),
            ("面粉加工", "主食与烘焙食品", "原料供给"),
            ("油脂压榨与精炼", "餐饮与食品工业", "产品交付"),
            ("休闲与预制食品", "冷链与配送", "仓配履约"),
            ("冷链与配送", "电商与家庭消费", "终端交付"),
        ),
    },
    {
        "name": "化工新材料",
        "chain_type": "制造链",
        "description": "从能源与基础化工原料、中间体，到高分子和功能材料及下游应用。",
        "source_name": "工业和信息化部 · 石化化工行业产品供需风险清单",
        "source_url": "https://wap.miit.gov.cn/jgsj/ycls/shhg/art/2026/art_b6af40e247c84673ad9dfe0e774fc2fb.html",
        "stages": (
            ("资源与能源", "input", (
                ("原油与天然气", "原材料", "石化路线的主要碳源和能源。"),
                ("煤与盐矿资源", "原材料", "煤化工、氯碱等路线的基础资源。"),
                ("工业气体", "原材料", "合成、氧化、保护和电子制造用气体。"),
            )),
            ("基础化工", "core", (
                ("烯烃与芳烃", "产品", "乙烯、丙烯和芳烃等有机基础原料。"),
                ("氯碱与无机化工", "产品", "烧碱、氯气、纯碱和无机盐。"),
                ("合成气与基础醇", "产品", "合成氨、甲醇等煤气化和天然气路线产品。"),
            )),
            ("中间体与配方", "core", (
                ("化工中间体", "产品", "连接基础原料和精细化工产品的中间产物。"),
                ("助剂与催化剂", "产品", "改善反应效率和材料加工性能。"),
                ("涂料与胶黏剂", "产品", "表面防护、粘接和复合材料配方。"),
            )),
            ("新材料", "core", (
                ("工程塑料", "产品", "高强、耐热和耐化学性的聚合物材料。"),
                ("高性能纤维与膜", "产品", "特种纤维、分离膜和薄膜材料。"),
                ("电子化学材料", "产品", "半导体、显示和新能源使用的高纯材料。"),
                ("新能源材料", "产品", "电池、光伏和储能相关化学材料。"),
            )),
            ("下游应用", "output", (
                ("汽车与装备", "应用", "轻量化、密封、涂装和结构部件。"),
                ("电子与半导体", "应用", "制造、封装、显示和绝缘应用。"),
                ("能源与环保", "应用", "电池、光伏、水处理和节能应用。"),
                ("建筑与消费", "应用", "建材、包装、纺织和日用消费品。"),
            )),
        ),
        "edges": (
            ("原油与天然气", "烯烃与芳烃", "炼化裂解"),
            ("煤与盐矿资源", "氯碱与无机化工", "资源加工"),
            ("烯烃与芳烃", "化工中间体", "化学合成"),
            ("化工中间体", "工程塑料", "聚合改性"),
            ("助剂与催化剂", "工程塑料", "性能改性"),
            ("化工中间体", "电子化学材料", "精制配方"),
            ("电子化学材料", "电子与半导体", "材料交付"),
            ("新能源材料", "能源与环保", "材料交付"),
            ("工程塑料", "汽车与装备", "材料交付"),
            ("涂料与胶黏剂", "建筑与消费", "产品应用"),
        ),
    },
    {
        "name": "航运与港口物流",
        "chain_type": "服务链",
        "description": "从货源组织、港口集疏运和装卸，到海运运力、货代通关与多式联运交付。",
        "source_name": "交通运输部 · 多式联运攻坚行动方案",
        "source_url": "https://xxgk.mot.gov.cn/jigou/zhghs/202606/t20260615_4207537.html",
        "stages": (
            ("货源与委托", "input", (
                ("集装箱货物", "货源", "制造业和贸易形成的标准箱货源。"),
                ("干散货与能源", "货源", "矿石、煤炭、粮食等大宗货物。"),
                ("液体散货", "货源", "原油、成品油和化工液体货物。"),
                ("货主与贸易商", "客户", "发起运输需求并组织贸易单证。"),
            )),
            ("港口与集疏运", "core", (
                ("港口码头", "基础设施", "泊位、堆场和港池等装卸节点。"),
                ("装卸与仓储", "服务", "货物装卸、堆存、理货和保管。"),
                ("铁路与公路集疏运", "服务", "连接港口和内陆货源地。"),
                ("内河与支线运输", "服务", "连接干线港和区域港口。"),
            )),
            ("海运运力", "core", (
                ("集装箱航运", "服务", "班轮网络承运标准箱货物。"),
                ("干散货航运", "服务", "散货船承运矿石、煤炭和粮食。"),
                ("油运与化学品船", "服务", "油轮和化学品船承运液体货物。"),
                ("船舶管理与租赁", "服务", "船舶运营、管理和运力租赁。"),
            )),
            ("物流与通关", "core", (
                ("货运代理", "服务", "订舱、单证、路线组织和异常处理。"),
                ("报关与检验", "服务", "完成海关申报、查验和口岸手续。"),
                ("多式联运", "服务", "衔接海运、铁路、公路和内河运输。"),
                ("航运金融与保险", "服务", "提供融资、结算和运输风险保障。"),
            )),
            ("交付场景", "output", (
                ("进出口贸易", "应用", "国际贸易货物的港到港和门到门交付。"),
                ("制造业供应链", "应用", "原料进口和产品出口的稳定运输。"),
                ("能源与大宗保供", "应用", "能源、矿石和粮食等战略物资运输。"),
            )),
        ),
        "edges": (
            ("集装箱货物", "港口码头", "集港"),
            ("干散货与能源", "装卸与仓储", "到港装卸"),
            ("铁路与公路集疏运", "港口码头", "集疏运"),
            ("港口码头", "集装箱航运", "装船"),
            ("装卸与仓储", "干散货航运", "装船"),
            ("集装箱航运", "货运代理", "运输执行"),
            ("货运代理", "报关与检验", "单证通关"),
            ("货运代理", "多式联运", "全程组织"),
            ("多式联运", "制造业供应链", "门到门交付"),
            ("干散货航运", "能源与大宗保供", "运输交付"),
        ),
    },
    {
        "name": "软件与云服务",
        "chain_type": "平台生态",
        "description": "从服务器、网络和基础软件，到云平台、SaaS、安全运维及行业数字化应用。",
        "source_name": "工业和信息化部 · 云计算综合标准化体系建设指南（2025版）",
        "source_url": "https://www.miit.gov.cn/cms_files/filemanager/1226211233/attach/20253/6ea5eda0c4f34976bc7d3a5577dd6a23.pdf",
        "stages": (
            ("算力与网络", "input", (
                ("服务器与存储", "设备", "运行软件和保存业务数据的计算设施。"),
                ("数据中心", "基础设施", "承载计算、存储、网络和运维设施。"),
                ("云网络", "服务", "连接云内、云间和终端的网络能力。"),
            )),
            ("基础软件", "input", (
                ("操作系统", "软件", "管理硬件资源并承载上层应用。"),
                ("数据库", "软件", "组织、存储和处理结构化与非结构化数据。"),
                ("中间件", "软件", "连接应用、数据和分布式系统。"),
                ("开发工具", "软件", "支持软件开发、测试、发布和协作。"),
            )),
            ("云平台", "core", (
                ("IaaS", "平台", "弹性交付计算、存储和网络资源。"),
                ("PaaS", "平台", "提供数据库、容器、开发和数据平台能力。"),
                ("云资源管控", "平台", "编排、计量、监控和治理云资源。"),
                ("云安全", "服务", "保护网络、数据、身份、系统和应用。"),
            )),
            ("软件服务", "core", (
                ("通用SaaS", "产品", "办公、协作、财务、人力等通用软件服务。"),
                ("工业软件", "产品", "研发设计、生产控制和经营管理软件。"),
                ("行业解决方案", "服务", "面向行业的集成软件、数据和咨询服务。"),
                ("实施与运维", "服务", "部署、迁移、集成、监控和持续服务。"),
            )),
            ("数字化场景", "output", (
                ("企业经营", "应用", "经营管理、客户服务和协同办公。"),
                ("智能制造", "应用", "研发、生产、供应链和设备管理。"),
                ("公共与行业云", "应用", "政务、金融、医疗、教育等行业场景。"),
            )),
        ),
        "edges": (
            ("服务器与存储", "数据中心", "基础设施部署"),
            ("数据中心", "IaaS", "资源供给"),
            ("操作系统", "IaaS", "运行环境"),
            ("数据库", "PaaS", "数据能力"),
            ("中间件", "PaaS", "应用支撑"),
            ("IaaS", "云资源管控", "资源编排"),
            ("PaaS", "通用SaaS", "平台支撑"),
            ("云安全", "行业解决方案", "安全保障"),
            ("工业软件", "智能制造", "软件交付"),
            ("行业解决方案", "公共与行业云", "方案交付"),
            ("实施与运维", "企业经营", "持续服务"),
        ),
    },
)

_INDUSTRY_CHAIN_CATEGORIES: dict[str, str] = {
    "保险产品与服务": "金融服务",
    "银行信贷与支付": "金融服务",
    "证券与财富管理": "金融服务",
    "白酒生产与消费": "消费与食品",
    "粮油食品加工": "消费与食品",
    "家电制造与交付": "消费与食品",
    "AI 数据中心": "数字科技",
    "半导体": "数字科技",
    "软件与云服务": "数字科技",
    "锂电池材料与应用": "新能源与制造",
    "新能源汽车": "新能源与制造",
    "光伏发电": "新能源与制造",
    "化工新材料": "材料与化工",
    "航运与港口物流": "交通与物流",
}

_INDUSTRY_CHAIN_RECOMMENDATION_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "保险产品与服务": {"symbols": ("601318", "601601", "601628", "601336", "601319"), "keywords": ("保险", "寿险", "财险", "再保险")},
    "银行信贷与支付": {"symbols": (), "keywords": ("银行", "支付", "信贷", "货币金融")},
    "证券与财富管理": {"symbols": (), "keywords": ("证券", "券商", "资本市场", "财富管理", "投资银行")},
    "白酒生产与消费": {"symbols": ("600519", "000858"), "keywords": ("白酒", "酒、饮料", "酿酒")},
    "粮油食品加工": {"symbols": (), "keywords": ("粮油", "食品加工", "农副食品", "饲料", "大豆", "食用油")},
    "家电制造与交付": {"symbols": ("000651", "000333"), "keywords": ("家电", "电器", "空调", "制冷")},
    "AI 数据中心": {"symbols": (), "keywords": ("数据中心", "算力", "服务器", "液冷", "人工智能", "云计算设备")},
    "半导体": {"symbols": (), "keywords": ("半导体", "集成电路", "芯片", "电子元件", "晶圆")},
    "软件与云服务": {"symbols": (), "keywords": ("软件", "信息技术服务", "云服务", "云计算", "SaaS")},
    "锂电池材料与应用": {"symbols": ("300750",), "keywords": ("锂电池", "动力电池", "电池材料", "储能电池")},
    "新能源汽车": {"symbols": ("002594",), "keywords": ("新能源汽车", "汽车制造", "汽车零部件", "整车")},
    "光伏发电": {"symbols": (), "keywords": ("光伏", "太阳能", "硅片", "逆变器")},
    "化工新材料": {"symbols": (), "keywords": ("化工", "化学原料", "新材料", "高分子", "电子化学")},
    "航运与港口物流": {"symbols": (), "keywords": ("航运", "港口", "水上运输", "物流", "海运")},
}

_DEFAULT_INDUSTRY_CHAIN_NAMES = frozenset(
    str(template["name"]) for template in _DEFAULT_INDUSTRY_CHAIN_TEMPLATES
)


def _ensure_default_industry_chains() -> None:
    """给当前用户安装有公开依据的系统底图，已安装的不会覆盖。"""
    scope = _stamp()
    timestamp = now_iso()
    for template in _DEFAULT_INDUSTRY_CHAIN_TEMPLATES:
        with connection() as conn:
            existing = conn.execute(
                f"SELECT id FROM industry_chain_themes WHERE name = ?{_sw()}",
                (template["name"],),
            ).fetchone()
            if existing:
                continue
            try:
                cursor = conn.execute(
                    """INSERT INTO industry_chain_themes
                       (user_id, name, chain_type, description, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (scope, template["name"], template["chain_type"], template["description"],
                     timestamp, timestamp),
                )
                theme_id = int(cursor.lastrowid)
                node_ids: dict[str, int] = {}
                for stage_index, (stage_name, stage_kind, nodes) in enumerate(template["stages"], start=1):
                    stage_cursor = conn.execute(
                        """INSERT INTO industry_chain_stages
                           (user_id, theme_id, name, stage_kind, description, stage_order,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, '', ?, ?, ?)""",
                        (scope, theme_id, stage_name, stage_kind, stage_index * 10, timestamp, timestamp),
                    )
                    stage_id = int(stage_cursor.lastrowid)
                    for node_index, (node_name, node_type, description) in enumerate(nodes, start=1):
                        node_cursor = conn.execute(
                            """INSERT INTO industry_chain_nodes
                               (user_id, theme_id, stage_id, name, node_type, description,
                                source_name, source_url, verification, node_order, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '已核验', ?, ?, ?)""",
                            (scope, theme_id, stage_id, node_name, node_type, description,
                             template["source_name"], template["source_url"],
                             node_index * 10, timestamp, timestamp),
                        )
                        node_ids[node_name] = int(node_cursor.lastrowid)
                for from_name, to_name, relation_type in template["edges"]:
                    conn.execute(
                        """INSERT INTO industry_chain_edges
                           (user_id, theme_id, from_node_id, to_node_id, relation_type, detail,
                            source_name, source_url, verification, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, '', ?, ?, '已核验', ?, ?)""",
                        (scope, theme_id, node_ids[from_name], node_ids[to_name], relation_type,
                         template["source_name"], template["source_url"], timestamp, timestamp),
                    )
            except integrity_errors():
                # 同一个用户的两个首屏请求可能同时安装；唯一索引保证只留一份。
                continue


def unverify_bulk_archived_evidence() -> dict[str, Any]:
    """把批量归档时被替人盖上「已核验」的证据退回「待核验」。

    ## 为什么需要这一步

    `archive_inbox_batch` 一次归档最多 500 条公告，每条都写「已核验」
    （默认值就是它，见 schemas.InboxArchive 那段说明）。线上实测：
    **280 条证据全部是「已核验」，没有一条被人看过** ——
    也就是说这个标记在整个库里没有任何信息量，它永远是那个值。

    「已核验」是在说"这条我看过了、是真的"。一个没人看过的判断被标成看过了，
    比没有这个标记糟得多：复盘时你不会再去核它。

    ## 只退回批量归档进来的那些

    判据是 `source_url` 指向巨潮/交易所公告且 excerpt 是原文照抄 ——
    这些是机器搬进来的。**手工写的证据不动**：那些是人自己敲的，
    他标什么就是什么，系统没有资格改。
    """
    # **evidences 没有自己的 user_id。** 它挂在 companies 上，而仓里本来就有
    # `_swc()` 专门给这种表用。第一版照抄了 `_sw()`，线上当场
    # `psycopg2.errors.UndefinedColumn: column "user_id" does not exist` ——
    # 这类表有两个不同的过滤函数，抄错一个不会在本地被发现（测试库里只有一个用户）。
    with connection() as conn:
        rows = _rows(conn.execute(
            f"""SELECT id, source_url FROM evidences
                WHERE verification = '已核验'{_swc()}""").fetchall())
        # **判据不是"来自哪个域名"，是"能不能回点原文"。**
        #
        # 第一版按巨潮/交易所三个域名认，线上退回 125 条、剩下 155 条 ——
        # 而那 155 条**一条链接都没有**：同花顺分红方案、新浪限售解禁、
        # 年报里抽出来的前五大客户……全是同步进来的，同样没人看过。
        # 按域名认漏掉了它们，因为它们压根没有域名。
        #
        # 仓里本来就有这条判据（_industry_chain_verification）：
        # 「**「已核验」必须同时有可辨认的来源名和可回点的链接**，
        # 不能只由前端自称」。这 155 条没有链接，按那条规矩就不该是已核验。
        # 沿用它：没有可回点链接的，一律退回待核验。
        machine = [r["id"] for r in rows if not str(r["source_url"] or "").strip()
                   or "cninfo.com.cn" in str(r["source_url"] or "")
                   or "sse.com.cn" in str(r["source_url"] or "")
                   or "szse.cn" in str(r["source_url"] or "")]
        for evidence_id in machine:
            conn.execute("UPDATE evidences SET verification = '待核验' WHERE id = ?",
                         (evidence_id,))
    return {"checked": len(rows), "reset": len(machine),
            "note": f"{len(rows)} 条标着「已核验」的证据里，{len(machine)} 条是批量归档搬进来的、"
                    f"没有人看过，已退回「待核验」。手工写的没有动。"}


def _industry_chain_verification(payload: dict[str, Any]) -> str:
    """“已核验”必须同时有可辨认的来源名和可回点的链接，不能只由前端自称。"""
    requested = str(payload.get("verification") or "待补证").strip()
    source_name = str(payload.get("source_name") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    return "已核验" if requested == "已核验" and source_name and source_url else "待补证"


def _industry_chain_recommendations() -> dict[str, dict[str, Any]]:
    """按研究池内容推荐底图；只做可解释的名称/行业/主营匹配，不让模型猜。"""
    with connection() as conn:
        companies = _rows(conn.execute(
            f"""SELECT c.symbol, c.name, c.industry, c.description,
                       COALESCE(p.main_business, '') AS main_business,
                       COALESCE(p.product_type, '') AS product_type,
                       COALESCE(p.business_scope, '') AS business_scope,
                       COALESCE(p.introduction, '') AS introduction
                FROM companies c
                LEFT JOIN company_profiles p ON p.symbol = c.symbol
                WHERE c.is_watched = 1{_sw('c')}
                ORDER BY c.updated_at DESC, c.id DESC"""
        ).fetchall())

    recommendations: dict[str, dict[str, Any]] = {}
    for theme_name, rule in _INDUSTRY_CHAIN_RECOMMENDATION_RULES.items():
        matched: list[str] = []
        score = 0
        symbols = set(rule["symbols"])
        keywords = rule["keywords"]
        for company in companies:
            symbol = str(company.get("symbol") or "")
            primary = " ".join(str(company.get(field) or "") for field in ("name", "industry")).lower()
            business = " ".join(str(company.get(field) or "") for field in (
                "description", "main_business", "product_type", "business_scope",
            )).lower()
            exact = symbol in symbols
            primary_hits = sum(1 for keyword in keywords if keyword.lower() in primary)
            business_hits = sum(1 for keyword in keywords if keyword.lower() in business)
            # 主营资料往往顺带列一长串外围业务；只命中一个泛词（如“物流”“软件”）
            # 不足以推荐整张底图，至少两条业务线索才算相关。
            if not exact and not primary_hits and business_hits < 2:
                continue
            matched.append(str(company.get("name") or symbol))
            score += (100 if exact else 0) + primary_hits * 40 + business_hits * 10
        if matched:
            names = "、".join(dict.fromkeys(matched[:3]))
            recommendations[theme_name] = {
                "recommended": True,
                "recommendation_score": score,
                "recommendation_reason": f"研究池中的 {names} 与该主题相关",
            }

    # 空研究池也不让入口退回空白：四张入门图是“起步推荐”，并明确不是个性化命中。
    if not recommendations:
        for theme_name in ("保险产品与服务", "白酒生产与消费", "家电制造与交付", "锂电池材料与应用"):
            recommendations[theme_name] = {
                "recommended": True,
                "recommendation_score": 1,
                "recommendation_reason": "常用入门底图",
            }
    return recommendations


def list_industry_chain_themes() -> list[dict[str, Any]]:
    """列出当前研究域里的产业链底图；首次进入就安装默认主题。"""
    _ensure_default_industry_chains()
    with connection() as conn:
        rows = _rows(conn.execute(
            f"""
            SELECT t.id, t.name, t.chain_type, t.description, t.updated_at,
                   COUNT(DISTINCT s.id) AS stage_count,
                   COUNT(DISTINCT n.id) AS node_count,
                   COUNT(DISTINCT p.company_id) AS company_count
            FROM industry_chain_themes t
            LEFT JOIN industry_chain_stages s ON s.theme_id = t.id AND s.user_id = t.user_id
            LEFT JOIN industry_chain_nodes n ON n.theme_id = t.id AND n.user_id = t.user_id
            LEFT JOIN industry_chain_company_positions p ON p.theme_id = t.id AND p.user_id = t.user_id
            WHERE 1=1{_sw('t')}
            GROUP BY t.id, t.name, t.chain_type, t.description, t.updated_at
            ORDER BY t.updated_at DESC, t.id DESC
            """
        ).fetchall())
    default_order = {name: index for index, name in enumerate(
        str(template["name"]) for template in _DEFAULT_INDUSTRY_CHAIN_TEMPLATES
    )}
    recommendations = _industry_chain_recommendations()
    for row in rows:
        row["is_default"] = row["name"] in _DEFAULT_INDUSTRY_CHAIN_NAMES
        row["category"] = _INDUSTRY_CHAIN_CATEGORIES.get(row["name"], "我的主题")
        row.update(recommendations.get(row["name"], {
            "recommended": False,
            "recommendation_score": 0,
            "recommendation_reason": "",
        }))
    return sorted(
        rows,
        key=lambda row: (
            0 if row["recommended"] else 1,
            -int(row["recommendation_score"]),
            0 if row["is_default"] else 1,
            default_order.get(row["name"], 999) if row["is_default"] else 0,
        ),
    )


def fork_industry_chain_theme(theme_id: int) -> dict[str, Any] | None:
    """复制一张底图为个人版本；系统底图本身始终保持可升级的只读基准。"""
    source = get_industry_chain(theme_id)
    if source is None:
        return None
    base_name = f"{source['name']} · 我的版本"
    name = base_name
    with connection() as conn:
        suffix = 2
        while conn.execute(
            f"SELECT 1 FROM industry_chain_themes WHERE name = ?{_sw()}", (name,)
        ).fetchone():
            name = f"{base_name} {suffix}"
            suffix += 1

    scope = _stamp()
    timestamp = now_iso()
    with connection() as conn:
        theme_cursor = conn.execute(
            """INSERT INTO industry_chain_themes
               (user_id, name, chain_type, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (scope, name, source["chain_type"], source["description"], timestamp, timestamp),
        )
        new_theme_id = int(theme_cursor.lastrowid)
        stage_ids: dict[int, int] = {}
        node_ids: dict[int, int] = {}
        for stage in source["stages"]:
            cursor = conn.execute(
                """INSERT INTO industry_chain_stages
                   (user_id, theme_id, name, stage_kind, description, stage_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope, new_theme_id, stage["name"], stage["stage_kind"], stage["description"],
                 stage["stage_order"], timestamp, timestamp),
            )
            stage_ids[int(stage["id"])] = int(cursor.lastrowid)
            for node in stage["nodes"]:
                node_cursor = conn.execute(
                    """INSERT INTO industry_chain_nodes
                       (user_id, theme_id, stage_id, parent_id, name, node_type, description,
                        source_name, source_url, verification, node_order, created_at, updated_at)
                       VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (scope, new_theme_id, stage_ids[int(stage["id"])], node["name"],
                     node["node_type"], node["description"], node["source_name"],
                     node["source_url"], node["verification"], node["node_order"],
                     timestamp, timestamp),
                )
                node_ids[int(node["id"])] = int(node_cursor.lastrowid)
                for position in node["positions"]:
                    conn.execute(
                        """INSERT INTO industry_chain_company_positions
                           (user_id, theme_id, node_id, company_id, role, detail, source_name,
                            source_url, verification, valid_from, valid_to, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (scope, new_theme_id, node_ids[int(node["id"])], position["company_id"],
                         position["role"], position["detail"], position["source_name"],
                         position["source_url"], position["verification"], position["valid_from"],
                         position["valid_to"], timestamp, timestamp),
                    )
        for edge in source["edges"]:
            conn.execute(
                """INSERT INTO industry_chain_edges
                   (user_id, theme_id, from_node_id, to_node_id, relation_type, detail,
                    source_name, source_url, verification, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope, new_theme_id, node_ids[int(edge["from_node_id"])],
                 node_ids[int(edge["to_node_id"])], edge["relation_type"], edge["detail"],
                 edge["source_name"], edge["source_url"], edge["verification"],
                 timestamp, timestamp),
            )
    return get_industry_chain(new_theme_id)


def create_industry_chain_theme(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    chain_type = str(payload.get("chain_type") or "制造链").strip()
    description = str(payload.get("description") or "").strip()
    if not name:
        raise LedgerError("请填写产业链底图名称。")
    if chain_type not in _INDUSTRY_CHAIN_SKELETONS:
        raise LedgerError("底图类型必须是制造链、服务链或平台生态。")
    timestamp = now_iso()
    scope = _stamp()
    try:
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO industry_chain_themes
                   (user_id, name, chain_type, description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (scope, name, chain_type, description, timestamp, timestamp),
            )
            theme_id = int(cursor.lastrowid)
            for index, (stage_name, stage_kind) in enumerate(_INDUSTRY_CHAIN_SKELETONS[chain_type], start=1):
                conn.execute(
                    """INSERT INTO industry_chain_stages
                       (user_id, theme_id, name, stage_kind, description, stage_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, '', ?, ?, ?)""",
                    (scope, theme_id, stage_name, stage_kind, index * 10, timestamp, timestamp),
                )
    except integrity_errors() as exc:
        raise LedgerError("已经有一张同名产业链底图。") from exc
    return get_industry_chain(theme_id)  # type: ignore[return-value]


def create_generated_industry_chain_theme(draft: dict[str, Any]) -> dict[str, Any]:
    """把“有来源的待确认初稿”一次性写成可编辑的个人底图。

    这里不复用逐个新增节点的接口，是为了让“创建底图、节点、连线”处在一个事务里：
    任意一条关系写失败都不能留下半张图。来源信息由 `industry_chain_draft` 在入库前
    已经收紧；本函数仍只接受它规定的少数字段，避免把模型原文直接扩散进数据库。
    """

    name = str(draft.get("name") or "").strip()[:80]
    chain_type = str(draft.get("chain_type") or "制造链").strip()
    description = str(draft.get("description") or "").strip()[:500]
    if not name:
        raise LedgerError("初稿没有可用的底图名称。")
    if chain_type not in _INDUSTRY_CHAIN_SKELETONS:
        raise LedgerError("初稿的交付结构不正确。")

    # 先把可写入的结构在内存里收紧，再打开事务。这样即使模型只给了半张图，
    # 也不会先落一条空主题、随后才在校验时失败。
    stages_to_write: list[dict[str, Any]] = []
    node_names: set[str] = set()
    for stage in draft.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        stage_name = str(stage.get("name") or "").strip()[:60]
        if not stage_name:
            continue
        stage_kind = str(stage.get("stage_kind") or "core").strip()[:20]
        if stage_kind not in {"input", "core", "output", "support"}:
            stage_kind = "core"
        nodes_to_write: list[dict[str, Any]] = []
        for node in stage.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_name = str(node.get("name") or "").strip()[:100]
            source_name = str(node.get("source_name") or "").strip()[:120]
            source_url = str(node.get("source_url") or "").strip()[:1000]
            if not node_name or node_name in node_names or not source_name or not source_url:
                continue
            node_type = str(node.get("node_type") or "产品").strip()[:20]
            if node_type not in {"产品", "服务", "原材料", "部件", "设备", "渠道", "应用", "平台", "基础设施", "数据与内容"}:
                node_type = "产品"
            nodes_to_write.append({
                "name": node_name,
                "node_type": node_type,
                "description": str(node.get("description") or "").strip()[:500],
                "source_name": source_name,
                "source_url": source_url,
            })
            node_names.add(node_name)
        if nodes_to_write:
            stages_to_write.append({
                "name": stage_name,
                "stage_kind": stage_kind,
                "description": str(stage.get("description") or "").strip()[:300],
                "nodes": nodes_to_write,
            })

    edges_to_write: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()
    for edge in draft.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        from_name = str(edge.get("from") or "").strip()[:100]
        to_name = str(edge.get("to") or "").strip()[:100]
        source_name = str(edge.get("source_name") or "").strip()[:120]
        source_url = str(edge.get("source_url") or "").strip()[:1000]
        key = (from_name, to_name)
        if (not from_name or not to_name or from_name == to_name or key in seen_edges
                or from_name not in node_names or to_name not in node_names
                or not source_name or not source_url):
            continue
        edges_to_write.append({
            "from": from_name,
            "to": to_name,
            "relation_type": str(edge.get("relation_type") or "流向").strip()[:30],
            "detail": str(edge.get("detail") or "").strip()[:500],
            "source_name": source_name,
            "source_url": source_url,
        })
        seen_edges.add(key)
    if len(stages_to_write) < 2 or len(node_names) < 4 or not edges_to_write:
        raise LedgerError("初稿结构不完整，没有保存。")

    scope = _stamp()
    timestamp = now_iso()
    try:
        with connection() as conn:
            # 同一个主题可以再次生成；保留历史初稿比用“同名”拦住研究流程更有用。
            # 同时避开系统底图名称，确保生成结果永远是个人可编辑副本。
            base_name = name
            final_name = base_name
            suffix = 2
            while conn.execute(
                f"SELECT 1 FROM industry_chain_themes WHERE name = ?{_sw()} LIMIT 1", (final_name,)
            ).fetchone() is not None:
                final_name = f"{base_name[:70]} · 初稿 {suffix}"
                suffix += 1
            cursor = conn.execute(
                """INSERT INTO industry_chain_themes
                   (user_id, name, chain_type, description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (scope, final_name, chain_type, description, timestamp, timestamp),
            )
            theme_id = int(cursor.lastrowid)
            node_ids: dict[str, int] = {}
            for stage_index, stage in enumerate(stages_to_write, start=1):
                stage_cursor = conn.execute(
                    """INSERT INTO industry_chain_stages
                       (user_id, theme_id, name, stage_kind, description, stage_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (scope, theme_id, stage["name"], stage["stage_kind"], stage["description"], stage_index * 10,
                     timestamp, timestamp),
                )
                stage_id = int(stage_cursor.lastrowid)
                for node_index, node in enumerate(stage["nodes"], start=1):
                    node_cursor = conn.execute(
                        """INSERT INTO industry_chain_nodes
                           (user_id, theme_id, stage_id, parent_id, name, node_type, description,
                            source_name, source_url, verification, node_order, created_at, updated_at)
                           VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, '待确认', ?, ?, ?)""",
                        (scope, theme_id, stage_id, node["name"], node["node_type"], node["description"],
                         node["source_name"], node["source_url"], node_index * 10, timestamp, timestamp),
                    )
                    node_ids[node["name"]] = int(node_cursor.lastrowid)

            for edge in edges_to_write:
                source_id = node_ids[edge["from"]]
                target_id = node_ids[edge["to"]]
                conn.execute(
                    """INSERT INTO industry_chain_edges
                       (user_id, theme_id, from_node_id, to_node_id, relation_type, detail,
                        source_name, source_url, verification, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, '待确认', ?, ?)""",
                    (scope, theme_id, source_id, target_id,
                     edge["relation_type"], edge["detail"], edge["source_name"], edge["source_url"],
                     timestamp, timestamp),
                )
    except integrity_errors() as exc:
        raise LedgerError("已经有一张同名产业链底图；换个名称再生成。") from exc

    return get_industry_chain(theme_id)  # type: ignore[return-value]


def get_industry_chain(theme_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        theme = _one_or_none(conn.execute(
            f"SELECT * FROM industry_chain_themes WHERE id = ?{_sw()}", (theme_id,)
        ).fetchone())
        if theme is None:
            return None
        stages = _rows(conn.execute(
            f"SELECT id, theme_id, name, stage_kind, description, stage_order "
            f"FROM industry_chain_stages WHERE theme_id = ?{_sw()} ORDER BY stage_order, id",
            (theme_id,),
        ).fetchall())
        nodes = _rows(conn.execute(
            f"""SELECT id, theme_id, stage_id, parent_id, name, node_type, description,
                       source_name, source_url, verification, node_order
                FROM industry_chain_nodes WHERE theme_id = ?{_sw()}
                ORDER BY node_order, id""",
            (theme_id,),
        ).fetchall())
        edges = _rows(conn.execute(
            f"""SELECT id, theme_id, from_node_id, to_node_id, relation_type, detail,
                       source_name, source_url, verification
                FROM industry_chain_edges WHERE theme_id = ?{_sw()} ORDER BY id""",
            (theme_id,),
        ).fetchall())
        positions = _rows(conn.execute(
            f"""SELECT p.id, p.company_id, c.name AS company_name, c.symbol, p.node_id,
                       p.role, p.detail, p.source_name, p.source_url, p.verification,
                       p.valid_from, p.valid_to
                FROM industry_chain_company_positions p
                JOIN companies c ON c.id = p.company_id
                WHERE p.theme_id = ?{_sw('p')}
                ORDER BY c.name, p.id""",
            (theme_id,),
        ).fetchall())

    positions_by_node: dict[int, list[dict[str, Any]]] = {}
    for position in positions:
        positions_by_node.setdefault(int(position["node_id"]), []).append(position)
    nodes_by_stage: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        node["positions"] = positions_by_node.get(int(node["id"]), [])
        nodes_by_stage.setdefault(int(node["stage_id"]), []).append(node)
    for stage in stages:
        stage["nodes"] = nodes_by_stage.get(int(stage["id"]), [])
    theme.update({
        "is_default": theme["name"] in _DEFAULT_INDUSTRY_CHAIN_NAMES,
        "stages": stages,
        "edges": edges,
        "node_count": len(nodes),
        "company_count": len({int(row["company_id"]) for row in positions}),
        "boundary": (
            "底图只表达产品、服务和交付关系；公司必须定位到具体节点，并留下来源。"
            "没有来源的节点与公司位置统一标为待补证，不会自动变成经营事实。"
        ),
    })
    return theme


def add_industry_chain_stage(theme_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = now_iso()
    scope = _stamp()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise LedgerError("请填写阶段名称。")
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM industry_chain_themes WHERE id = ?{_sw()}", (theme_id,)).fetchone():
            return None
        order = payload.get("stage_order")
        if order is None:
            row = conn.execute(
                f"SELECT COALESCE(MAX(stage_order), 0) AS n FROM industry_chain_stages WHERE theme_id = ?{_sw()}",
                (theme_id,),
            ).fetchone()
            order = int(row["n"]) + 10
        try:
            conn.execute(
                """INSERT INTO industry_chain_stages
                   (user_id, theme_id, name, stage_kind, description, stage_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope, theme_id, name,
                 str(payload.get("stage_kind") or "core")[:20],
                 str(payload.get("description") or "").strip(), int(order), timestamp, timestamp),
            )
            conn.execute(
                f"UPDATE industry_chain_themes SET updated_at = ? WHERE id = ?{_sw()}",
                (timestamp, theme_id),
            )
        except integrity_errors() as exc:
            raise LedgerError("这张底图里已经有同名阶段。") from exc
    return get_industry_chain(theme_id)


def add_industry_chain_node(theme_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = now_iso()
    scope = _stamp()
    stage_id = int(payload.get("stage_id") or 0)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise LedgerError("请填写产品或服务节点名称。")
    parent_id = payload.get("parent_id")
    upstream_id = payload.get("upstream_node_id")
    with connection() as conn:
        if not conn.execute(
                f"SELECT 1 FROM industry_chain_stages WHERE id = ? AND theme_id = ?{_sw()}",
                (stage_id, theme_id)).fetchone():
            return None
        if parent_id is not None and not conn.execute(
                f"SELECT 1 FROM industry_chain_nodes WHERE id = ? AND theme_id = ?{_sw()}",
                (parent_id, theme_id)).fetchone():
            raise LedgerError("父节点不属于这张底图。")
        if upstream_id is not None and not conn.execute(
                f"SELECT 1 FROM industry_chain_nodes WHERE id = ? AND theme_id = ?{_sw()}",
                (upstream_id, theme_id)).fetchone():
            raise LedgerError("上游节点不属于这张底图。")
        order = payload.get("node_order")
        if order is None:
            row = conn.execute(
                f"SELECT COALESCE(MAX(node_order), 0) AS n FROM industry_chain_nodes WHERE stage_id = ?{_sw()}",
                (stage_id,),
            ).fetchone()
            order = int(row["n"]) + 10
        try:
            cursor = conn.execute(
                """INSERT INTO industry_chain_nodes
                   (user_id, theme_id, stage_id, parent_id, name, node_type, description,
                    source_name, source_url, verification, node_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope, theme_id, stage_id, parent_id,
                 name, str(payload.get("node_type") or "产品")[:20],
                 str(payload.get("description") or "").strip(), str(payload.get("source_name") or "").strip(),
                 str(payload.get("source_url") or "").strip(), _industry_chain_verification(payload),
                 int(order), timestamp, timestamp),
            )
            node_id = int(cursor.lastrowid)
            if upstream_id is not None:
                conn.execute(
                    """INSERT INTO industry_chain_edges
                       (user_id, theme_id, from_node_id, to_node_id, relation_type, detail,
                        source_name, source_url, verification, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)""",
                    (scope, theme_id, int(upstream_id), node_id,
                     str(payload.get("relation_type") or "流向")[:30],
                     str(payload.get("source_name") or "").strip(), str(payload.get("source_url") or "").strip(),
                     _industry_chain_verification(payload), timestamp, timestamp),
                )
            conn.execute(
                f"UPDATE industry_chain_themes SET updated_at = ? WHERE id = ?{_sw()}",
                (timestamp, theme_id),
            )
        except integrity_errors() as exc:
            raise LedgerError("这个阶段里已经有同名节点，或连接已经存在。") from exc
    return get_industry_chain(theme_id)


def add_industry_chain_edge(theme_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    source = int(payload.get("from_node_id") or 0)
    target = int(payload.get("to_node_id") or 0)
    if source == target:
        raise LedgerError("一个节点不能连接到自己。")
    timestamp = now_iso()
    scope = _stamp()
    with connection() as conn:
        rows = conn.execute(
            f"SELECT id FROM industry_chain_nodes WHERE theme_id = ? AND id IN (?, ?){_sw()}",
            (theme_id, source, target),
        ).fetchall()
        if len(rows) != 2:
            return None
        try:
            conn.execute(
                """INSERT INTO industry_chain_edges
                   (user_id, theme_id, from_node_id, to_node_id, relation_type, detail,
                    source_name, source_url, verification, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope, theme_id, source, target, str(payload.get("relation_type") or "流向")[:30],
                 str(payload.get("detail") or "").strip(), str(payload.get("source_name") or "").strip(),
                 str(payload.get("source_url") or "").strip(), _industry_chain_verification(payload),
                 timestamp, timestamp),
            )
            conn.execute(
                f"UPDATE industry_chain_themes SET updated_at = ? WHERE id = ?{_sw()}",
                (timestamp, theme_id),
            )
        except integrity_errors() as exc:
            raise LedgerError("这条连接已经存在。") from exc
    return get_industry_chain(theme_id)


def add_industry_chain_position(theme_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    node_id = int(payload.get("node_id") or 0)
    company_id = int(payload.get("company_id") or 0)
    timestamp = now_iso()
    scope = _stamp()
    with connection() as conn:
        if not conn.execute(
                f"SELECT 1 FROM industry_chain_nodes WHERE id = ? AND theme_id = ?{_sw()}",
                (node_id, theme_id)).fetchone():
            return None
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            raise LedgerError("只能定位当前研究池里的公司。")
        try:
            conn.execute(
                """INSERT INTO industry_chain_company_positions
                   (user_id, theme_id, node_id, company_id, role, detail, source_name, source_url,
                    verification, valid_from, valid_to, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scope, theme_id, node_id, company_id, str(payload.get("role") or "参与者")[:30],
                 str(payload.get("detail") or "").strip(), str(payload.get("source_name") or "").strip(),
                 str(payload.get("source_url") or "").strip(), _industry_chain_verification(payload),
                 str(payload.get("valid_from") or "") or None, str(payload.get("valid_to") or "") or None,
                 timestamp, timestamp),
            )
            conn.execute(
                f"UPDATE industry_chain_themes SET updated_at = ? WHERE id = ?{_sw()}",
                (timestamp, theme_id),
            )
        except integrity_errors() as exc:
            raise LedgerError("这家公司已经以相同角色定位在该节点。") from exc
    return get_industry_chain(theme_id)


def delete_industry_chain_record(kind: str, record_id: int) -> bool:
    tables = {
        "theme": "industry_chain_themes",
        "stage": "industry_chain_stages",
        "node": "industry_chain_nodes",
        "edge": "industry_chain_edges",
        "position": "industry_chain_company_positions",
    }
    table = tables.get(kind)
    if table is None:
        return False
    with connection() as conn:
        if kind == "theme":
            row = conn.execute(
                f"SELECT name FROM industry_chain_themes WHERE id = ?{_sw()}", (record_id,)
            ).fetchone()
            if row and row["name"] in _DEFAULT_INDUSTRY_CHAIN_NAMES:
                return False
        if kind in {"stage", "node", "edge"}:
            row = conn.execute(
                f"""SELECT t.name
                    FROM {table} r
                    JOIN industry_chain_themes t ON t.id = r.theme_id AND t.user_id = r.user_id
                    WHERE r.id = ?{_sw('r')}""",
                (record_id,),
            ).fetchone()
            if row and row["name"] in _DEFAULT_INDUSTRY_CHAIN_NAMES:
                return False
        return conn.execute(f"DELETE FROM {table} WHERE id = ?{_sw()}", (record_id,)).rowcount > 0


def company_industry_chain_positions(company_id: int) -> dict[str, Any] | None:
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        rows = _rows(conn.execute(
            f"""SELECT p.id, p.theme_id, t.name AS theme_name, t.chain_type,
                       p.node_id, n.name AS node_name, n.node_type,
                       s.name AS stage_name, p.role, p.detail, p.source_name, p.source_url,
                       p.verification, p.valid_from, p.valid_to
                FROM industry_chain_company_positions p
                JOIN industry_chain_themes t ON t.id = p.theme_id AND t.user_id = p.user_id
                JOIN industry_chain_nodes n ON n.id = p.node_id AND n.user_id = p.user_id
                JOIN industry_chain_stages s ON s.id = n.stage_id AND s.user_id = p.user_id
                WHERE p.company_id = ?{_sw('p')}
                ORDER BY t.updated_at DESC, s.stage_order, n.node_order""",
            (company_id,),
        ).fetchall())
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        theme_id = int(row["theme_id"])
        entry = grouped.setdefault(theme_id, {
            "theme_id": theme_id,
            "theme_name": row["theme_name"],
            "chain_type": row["chain_type"],
            "positions": [],
        })
        entry["positions"].append({
            key: value for key, value in row.items()
            if key not in {"theme_id", "theme_name", "chain_type"}
        })
    return {"company_id": company_id, "themes": list(grouped.values())}


# ------------------------------------------------------------- 经营关系线索


def refresh_supply_chain(company_id: int) -> dict[str, Any] | None:
    company = get_company(company_id)
    if company is None:
        return None
    links = map_supply_chain(company)
    timestamp = now_iso()
    with connection() as conn:
        for link in links:
            conn.execute(
                """
                INSERT INTO supply_chain_links (company_id, relation, counterpart, segment, detail, confidence, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_id, relation, counterpart) DO UPDATE SET
                    segment = excluded.segment, detail = excluded.detail, source = excluded.source
                """,
                (company_id, link["relation"], link["counterpart"], link["segment"],
                 link["detail"], link["confidence"], link["source"], timestamp),
            )
    return get_supply_chain(company_id)


def get_supply_chain(company_id: int) -> dict[str, Any] | None:
    """不属于当前用户的公司返回 None，由接口转成 404。

    只过滤 links 是不够的：那样别人的公司会得到一个「空供应链」的 200，
    等于确认了这个 id 存在、并且能被逐个试出来。
    """
    with connection() as conn:
        if not conn.execute(
                f"SELECT id FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        rows = _rows(conn.execute(
            f"SELECT * FROM supply_chain_links WHERE company_id = ?{_swc('company_id')} "
            "ORDER BY relation, counterpart", (company_id,)
        ).fetchall())
    # 图上放得下的短名在**读取时**派生：存量数据里 counterpart 全是整段描述
    # （「个人客户（寿险、产险、健康险投保人）」这种），不迁移就画不成节点。
    # 完整原文原样留在 counterpart 里，卡片上一个字不少。
    for row in rows:
        row["label"] = chain_node_label(row["counterpart"])
    return {
        "links": rows,
        "confirmed": sum(1 for row in rows if row["confidence"] == "已证实"),
        "boundary": (
            "这里只是经营关系线索，不是产业链底图。关系来自模型的世界知识，可能过期也可能记错；"
            "每条都要回到年报、公告、招股书或官网核对。没确认的线索不会进入公司时间线，"
            "也不会被当成产品、服务或公司位置。"
        ),
    }


def add_supply_chain_link(company_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    """手动加一条关系。

    模型给的往往不全——实测工商银行的上游只给出「中央银行」一条。
    而你自己知道的（某家具体的供应商、某个刚冒出来的竞争者）没地方录，
    这一页就只能被动接受模型给什么看什么。

    手写内容代表用户已经确认这条线索，因此直接标记为「已证实」；来源仍可补充，
    用于以后回看时知道确认依据。模型生成的线索继续保持「待证实」。
    """
    with connection() as conn:
        if not conn.execute(f"SELECT 1 FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone():
            return None
        counterpart = str(payload.get("counterpart") or "").strip()
        relation = str(payload.get("relation") or "").strip()
        if not counterpart or relation not in CHAIN_RELATIONS:
            return None
        source = str(payload.get("source") or "").strip()[:200]
        confidence = "已证实"
        conn.execute(
            """INSERT INTO supply_chain_links
               (company_id, relation, counterpart, segment, detail, confidence, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, relation, counterpart[:120],
             str(payload.get("segment") or "")[:120], str(payload.get("detail") or "")[:400],
             confidence, source, now_iso()))
    return get_supply_chain(company_id)


# 这两条**必须限定在自己的公司下**。理由跟 delete_report 那儿写的一样：
# 只按 id 改／删的话，换个 id 就能动别人的记录，而且动了不留痕。
# supply_chain_links 自己不带 user_id，它挂在 company_id 上，所以走 _swc()。
#
# 线上目前打不穿，但**兜住它的是 Postgres 的 RLS，不是这两行 SQL**。
# 把过滤补回来是为了：RLS 哪天被绕过（超级用户连库、迁移时漏了 FORCE），
# 或者走 SQLite 那条路（本地单机、备份还原）时，这里不至于是敞开的。
# 一道防线不该只有一层。

def confirm_supply_chain_link(link_id: int, evidence_id: int | None = None) -> bool:
    with connection() as conn:
        return conn.execute(
            f"""UPDATE supply_chain_links SET confidence = '已证实', evidence_id = ?
                WHERE id = ?{_swc()}""",
            (evidence_id, link_id),
        ).rowcount > 0


def delete_supply_chain_link(link_id: int) -> bool:
    with connection() as conn:
        return conn.execute(
            f"DELETE FROM supply_chain_links WHERE id = ?{_swc()}", (link_id,)).rowcount > 0


# ---------------------------------------------------------------- 研究报告


def generate_report(company_id: int, limit: int = 40) -> dict[str, Any] | None:
    """只用已归档的证据写简报，每句话带编号。查不到的写成"档案里没有"。"""

    company = get_company(company_id)
    if company is None:
        return None
    # **编号在这里定死，不由模型来编。** 正文里的 [3] 要能点回真正的那条证据，
    # 而模型只会在文字里写编号——它不知道我们的 evidence id。所以送进去的时候
    # 就带上序号，回来照序号查表，中间没有"模型说的 3 是哪个 3"这种猜测。
    sources: list[dict[str, Any]] = []
    for evidence in company["evidences"][:limit]:
        sources.append({
            "ref": len(sources) + 1,
            "label": f"{evidence['source_name']} · {str(evidence['occurred_at'])[:10]}",
            "text": evidence["excerpt"],
            "kind": "evidence",
            "evidence_id": evidence["id"],
            "url": evidence.get("source_url") or "",
            "occurred_at": str(evidence["occurred_at"])[:10],
        })
    for event in company["events"][:10]:
        sources.append({
            "ref": len(sources) + 1,
            "label": f"事件记录 · {str(event['occurred_at'])[:10]}",
            "text": f"{event['category']}：{event['title']}",
            "kind": "event",
            "evidence_id": None,
            "url": "",
            "occurred_at": str(event["occurred_at"])[:10],
        })
    report = write_report(company, sources)
    # 用我们自己的清单覆盖模型回的 citations：模型给的 label 是它复述的，
    # 而这里要的是能点开的东西。序号是同一套，所以对得上。
    report["citations"] = [
        {"ref": item["ref"], "label": item["label"], "text": item["text"][:120],
         "kind": item["kind"], "evidence_id": item["evidence_id"],
         "url": item["url"], "occurred_at": item["occurred_at"]}
        for item in sources
    ]
    with connection() as conn:
        version = int(conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM research_reports WHERE company_id = ?", (company_id,)
        ).fetchone()[0])
        conn.execute(
            """
            INSERT INTO research_reports (company_id, version, title, body,
                                          business, changes, implications,
                                          citations, unknowns, source_count, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (company_id, version, report["title"], report["body"],
             json.dumps(report["business"], ensure_ascii=False),
             json.dumps(report["changes"], ensure_ascii=False),
             json.dumps(report["implications"], ensure_ascii=False),
             json.dumps(report["citations"], ensure_ascii=False),
             json.dumps(report["unknowns"], ensure_ascii=False), report["source_count"], report["model"], now_iso()),
        )
    return list_reports(company_id)[0]


def deep_report_plan(company_id: int) -> dict[str, Any] | None:
    """跑之前先说清楚要搜几个问题、大概多少积分。"""
    from . import deep_report as dr

    company = get_company(company_id)
    if company is None:
        return None
    return {"company_id": company_id, "company_name": company["name"], **dr.estimate(company)}


def generate_deep_report(company_id: int, limit: int = 25) -> dict[str, Any] | None:
    """联网找资料 + 库里的真实数字 → 一份带图的报告。

    **数字归代码、判断归模型。** 库里已经有主营构成、同行位置、经营走势，
    这些不该让模型从网页上抄——网上的财务数字经常过期或口径不同，
    而这一步恰恰是最容易错、后果最严重的。
    """
    from . import deep_report as dr
    from . import peers, websearch

    company = get_company(company_id)
    if company is None:
        return None
    symbol = company["symbol"]

    # 官网算一手来源。库里 company_profiles.website 早就有这个字段，
    # 不接的话公司自己发的公告会被归成"其他"，跟一个不认识的域名同级。
    own_site = str((company.get("profile") or {}).get("website") or "")

    # 底座的行业口径（申万二级）比档案里的证监会门类细，检索时按它搜才搜得准
    with connection() as conn:
        universe_row = conn.execute(
            "SELECT industry FROM market_universe WHERE symbol = ?", (symbol,)).fetchone()
    company["universe_industry"] = (universe_row["industry"] if universe_row else "") or ""

    found = websearch.gather(dr.build_queries(company), own_site=own_site) \
        if websearch.available()[0] else {"hits": [], "queries": [], "failures": [], "by_kind": {}}

    local = [{
        "source_name": e["source_name"], "excerpt": e["excerpt"],
        "occurred_at": e["occurred_at"], "url": e.get("source_url") or "",
        "evidence_id": e["id"],
    } for e in company["evidences"][:limit]]

    # 库里的数字：这三块是报告的"数据面"，页面也直接照它画图
    facts = {
        "segments": business_segments(company_id) or {},
        "peers": peers.position(company),
        "financials": (company.get("financials") or {}).get("periods") or [],
    }
    # 只留年报，且只留最近六期：季报是累计口径，混进来模型会读出假的季节性
    facts["financials"] = [p for p in facts["financials"]
                           if str(p.get("report_date", ""))[5:] == "12-31"][-6:]

    # **真实搜到几次就报几次。** 不是 build_queries 的条数——
    # 搜索可能失败或被去重，按计划数收钱等于收了没发生的服务。
    report = dr.compose(company, found["hits"], local, facts,
                        searches=len(found.get("queries") or []))

    # 引用清单：检索资料在前、本地证据在后，编号跟送给模型的那一份严格一致。
    # **两处各编一次是不行的**——只要中间筛掉过一条，正文里的 [3] 就会指到
    # 另一份资料上，而这种错完全看不出来：编号还在，指向的东西是错的。
    sources = [{
        "ref": index, "kind": hit["kind"], "title": hit["title"], "url": hit["url"],
        "published": hit.get("published") or "", "snippet": hit["snippet"][:200],
        "tier": hit.get("tier") or "",
    } for index, hit in enumerate(found["hits"], 1)]
    sources += [{
        "ref": len(found["hits"]) + index, "kind": "本地已归档",
        "title": f"{item['source_name']}：{item['excerpt'][:60]}", "url": item["url"],
        "published": str(item["occurred_at"])[:10], "snippet": item["excerpt"][:200],
        "evidence_id": item["evidence_id"], "tier": "",
    } for index, item in enumerate(local, 1)]

    with connection() as conn:
        version = int(conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM research_reports WHERE company_id = ?",
            (company_id,)).fetchone()[0])
        conn.execute(
            """
            INSERT INTO research_reports (company_id, version, title, body, kind,
                                          cards, sections, themes, sources, queries, facts,
                                          citations, unknowns, source_count, model, created_at)
            VALUES (?, ?, ?, ?, 'deep', ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?)
            """,
            (company_id, version, report["headline"][:200] or f"{company['name']}研究报告",
             "\n".join(line for s in report["sections"] for line in s["lines"]),
             json.dumps(report["cards"], ensure_ascii=False),
             json.dumps(report["sections"], ensure_ascii=False),
             json.dumps(report["themes"], ensure_ascii=False),
             json.dumps(sources, ensure_ascii=False),
             json.dumps(found["queries"], ensure_ascii=False),
             json.dumps(facts, ensure_ascii=False, default=str),
             json.dumps(report["unknowns"], ensure_ascii=False),
             len(sources), report["model"], now_iso()),
        )
    result = list_reports(company_id)[0]
    result["search_note"] = found.get("note", "")
    result["search_failures"] = found.get("failures", [])
    return result


def delete_report(report_id: int) -> bool:
    """删一份报告。**必须限定在自己的公司下**——只按 id 删的话，
    换个 id 就能删掉别人的报告，而且删了不留痕。"""
    with connection() as conn:
        return conn.execute(
            f"""DELETE FROM research_reports WHERE id = ? AND company_id IN
                (SELECT id FROM companies WHERE 1=1{_sw()})""", (report_id,)).rowcount > 0


def list_reports(company_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
    clause = "WHERE r.company_id = ?" if company_id is not None else ""
    params: list[Any] = [company_id] if company_id is not None else []
    with connection() as conn:
        rows = _rows(conn.execute(
            f"""
            SELECT r.*, c.name AS company_name, c.symbol AS symbol
            FROM research_reports r JOIN companies c ON c.id = r.company_id
            {clause} ORDER BY r.created_at DESC LIMIT ?
            """,
            (*params, limit),
        ).fetchall())
    for row in rows:
        row["citations"] = json.loads(row["citations"] or "[]")
        row["unknowns"] = json.loads(row["unknowns"] or "[]")
        for section in ("business", "changes", "implications",
                        "cards", "sections", "themes", "sources", "queries"):
            row[section] = json.loads(row.get(section) or "[]")
        row["facts"] = json.loads(row.get("facts") or "{}")
        row["kind"] = row.get("kind") or "local"
    return rows


# ---------------------------------------------------------------- 决策简报


def _briefing_context() -> dict[str, Any]:
    """简报只重述库里已有的东西，所以先把上下文老老实实拼出来，模型不再去别处取。"""

    heatmap = market_heatmap(scope="all", metric="change_percent", limit=200)
    tiles = [tile for tile in heatmap["tiles"] if tile.get("metric_value") is not None]
    tiles.sort(key=lambda item: item["metric_value"], reverse=True)
    industries = (tiles[:3] + tiles[-3:]) if len(tiles) > 6 else tiles

    with connection() as conn:
        theses = _rows(conn.execute(
            """
            SELECT t.claim, t.counter_condition, t.status, c.name AS company
            FROM theses t JOIN companies c ON c.id = t.company_id
            WHERE 1=1{scope}
            ORDER BY t.updated_at DESC LIMIT 12
            """.format(scope=_sw("c"))
        ).fetchall())
        announcements = _rows(conn.execute(
            """
            SELECT e.company_id, e.event_date, e.title, c.symbol, c.name AS company_name
            FROM company_calendar_events e JOIN companies c ON c.id = e.company_id
            WHERE e.relevance = '高'{scope} ORDER BY e.event_date DESC, e.id DESC LIMIT 8
            """.format(scope=_sw("c"))
        ).fetchall())
        pending_events = int(conn.execute(f"SELECT COUNT(*) FROM research_events WHERE verification = '待核验'{_swc()}").fetchone()[0])
        inbox_pending = int(conn.execute(f"SELECT COUNT(*) FROM company_calendar_events WHERE inbox_status = '待核验'{_swc()}").fetchone()[0])
        watchlist = [row["name"] for row in conn.execute(
            f"SELECT name FROM companies WHERE id NOT IN (SELECT DISTINCT company_id FROM theses){_sw()} LIMIT 10"
        ).fetchall()]

    # 持仓直接从交易流水汇总，不依赖别处的视图函数
    with connection() as conn:
        positions = _rows(conn.execute(
            """
            SELECT c.name, c.symbol,
                   (SELECT price FROM market_snapshots s WHERE s.symbol = c.symbol ORDER BY s.refreshed_at DESC LIMIT 1) AS latest_price,
                   SUM(CASE WHEN t.side IN ('buy', '买入') THEN t.shares ELSE -t.shares END) AS shares,
                   SUM(CASE WHEN t.side IN ('buy', '买入') THEN t.shares * t.price ELSE 0 END) AS bought_amount,
                   SUM(CASE WHEN t.side IN ('buy', '买入') THEN t.shares ELSE 0 END) AS bought_shares
            FROM trades t JOIN companies c ON c.id = t.company_id
            WHERE 1=1{scope}
            GROUP BY c.id
            -- HAVING 里必须重写整个聚合式，不能引用上面的别名 shares。
            -- SQLite 允许引用输出别名，PG 不允许：它会把 shares 解析成 t.shares，
            -- 报「must appear in the GROUP BY clause」——错在 HAVING，提示却指向 GROUP BY。
            HAVING SUM(CASE WHEN t.side IN ('buy', '买入') THEN t.shares ELSE -t.shares END) > 0
            """.format(scope=_sw("c"))
        ).fetchall())
    for item in positions:
        cost = (item["bought_amount"] / item["bought_shares"]) if item["bought_shares"] else None
        item["average_cost"] = round(cost, 2) if cost else None
        item["unrealized_pct"] = (
            round((item["latest_price"] - cost) / cost * 100, 2)
            if cost and item.get("latest_price") else None
        )
    return {
        "as_of": now_iso()[:10],
        "breadth": heatmap.get("breadth"),
        "industries": industries,
        "positions": positions,
        "theses": [
            {"company": row["company"], "claim": row["claim"], "counter": row["counter_condition"], "status": row["status"]}
            for row in theses
        ],
        "pending_events": pending_events,
        "inbox_pending": inbox_pending,
        "recent_announcements": announcements,
        "watchlist": watchlist,
    }


def generate_briefing() -> dict[str, Any]:
    context = _briefing_context()
    briefing = write_briefing(context)
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_briefings (user_id, as_of, headline, body, actions, gaps,
                                         context, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, as_of) DO UPDATE SET
                headline = excluded.headline, body = excluded.body, actions = excluded.actions,
                gaps = excluded.gaps, context = excluded.context,
                model = excluded.model, created_at = excluded.created_at
            """,
            (
                _stamp(), context["as_of"], briefing["headline"],
                json.dumps({k: briefing[k] for k in ("market", "holdings", "pending", "watchlist", "boundary")}, ensure_ascii=False),
                json.dumps(briefing["actions"], ensure_ascii=False),
                json.dumps(briefing["gaps"], ensure_ascii=False),
                # 只存页面要画图的那几块，不存整个上下文（theses 里有大段自由文本，
                # 存进来既占地方，页面也用不上）
                json.dumps({k: context.get(k) for k in
                            ("breadth", "industries", "positions", "pending_events",
                             "inbox_pending", "recent_announcements")},
                           ensure_ascii=False, default=str),
                briefing["model"], now_iso(),
            ),
        )
    return latest_briefing() or {}


def latest_briefing() -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(f"SELECT * FROM daily_briefings WHERE 1=1{_sw()} ORDER BY as_of DESC LIMIT 1").fetchone()
    if row is None:
        return None
    record = dict(row)
    body = json.loads(record.pop("body") or "{}")
    record.update(body)
    record["context"] = json.loads(record.get("context") or "{}")
    record["actions"] = json.loads(record["actions"] or "[]")
    record["gaps"] = json.loads(record["gaps"] or "[]")
    return record


# ── 决策看板 ──────────────────────────────────────────────────────────────
#
# **它与「今日简报」的分工。** 简报是模型写的一段叙述，回答「今天整体有什么变化」；
# 看板是每只票一行的结构化状态表，回答「这一只现在卡在哪一步」。
# 前者适合早上通读一遍，后者适合逐只处理。两者读的是同一批事实。
#
# **它不给买卖信号，这是刻意的。** 同类开源项目（daily_stock_analysis 之类）会给
# 评分与买卖建议，那需要一个「什么价位算贵、什么形态算买点」的模型——
# 而这个产品从第一行代码起就不做那件事：它记录你的判断，在事实变化时提醒你回头看，
# 判断权始终在你手上。所以这里每一格都是**已经发生的事实或已经到期的约定**，
# 没有一格是对未来的预测。

# 每种待办的紧要程度。数字只用于排序，不是评分，不对用户显示。
#
# **这张表必须覆盖 decision_board 会产出的每一种 kind。**
#
# 2026-08-16 实测：表里少了「命中」和「体检」两种，而 `.get(kind, 9)` 的兜底
# 恰好是「无」（今天不用管）的那一档 —— 于是：
#
#     1. [公告] 美的集团 — 3 条实质公告还没核验
#     2. [补全] 格力电器 — 还没写下判断
#     3. [命中] 贵州茅台 — 公告命中了你写的反证条件      ← 排在这里
#     4. [无]   宁德时代 — 今天不用管
#
# 而这张表下面十几行就写着「**命中排在最前面**……它是唯一一件不处理就等于
# 假装没看见的事」。它甚至排在「今天不用管」前面都只是巧合：两者权重都是 9，
# 只因为那只票恰好在持仓里，第二个排序键才把它抬了一位。
#
# 首页那个红点此前也犯过同一个错（只数「反证」不数「命中」），改的时候只补了
# **计数**，没补**排序** —— 两处用的是同一个概念，却各写了一份名单。
#
# test_decision_board_order.py 会从 decision_board 的源码里把所有 `kind = "…"`
# 抠出来跟这张表比：**新加一种待办而这里没跟上，测试就红**。
_ACTION_WEIGHT = {
    "命中": 0,      # 你写下的认错条件被事实踩到了 —— 唯一一件不处理就等于假装没看见的
    "反证": 1,      # 有反证证据，但逻辑状态还没跟着改
    "复核": 2,      # 到了当初约定的复核日
    "公告": 3,      # 收件箱里还有实质公告没核
    "补全": 4,      # 没写判断，或判断没写认错条件
    "体检": 5,      # 没做过方法体检，或体检里有方法说不利
    "无": 9,        # 今天不用管
}


def decision_board() -> dict[str, Any]:
    """每只票一行：现在的状态，以及**因此该做什么**。"""

    today = date.today().isoformat()
    with connection() as conn:
        companies = _rows(conn.execute(
            """
            SELECT c.id, c.symbol, c.name, c.industry, c.watch_group,
                   ms.price AS latest_price, ms.change_percent, ms.pe, ms.pb,
                   ms.market_timestamp
            FROM companies c
            LEFT JOIN market_snapshots ms ON ms.id = (
                SELECT latest.id FROM market_snapshots latest WHERE latest.symbol = c.symbol
                ORDER BY latest.refreshed_at DESC, latest.id DESC LIMIT 1)
            WHERE 1=1{scope}
            ORDER BY c.watch_group, c.name, c.id
            """.format(scope=_sw("c"))).fetchall())
        theses = _rows(conn.execute(
            f"SELECT id, company_id, claim, counter_condition, status, next_review_date, "
            f"last_reviewed_at, created_at, method_name FROM theses WHERE 1=1{_swc()} ORDER BY updated_at DESC").fetchall())
        # **只数"上次复核之后才出现"的反证。**
        #
        # 原来这里数的是这家公司所有的反证，于是首页说「有 2 条反证，
        # 但逻辑状态还没跟着改」，而点进复核工作台是**空的**——
        # 那两条反证是 08-04 归档的，判断在 08-06 复核过、当时就看见了，
        # 使用者复核完决定维持"观察中"。**那是一个已经做出的决定，
        # 不是一件待办**，而首页从此永远在催他。
        #
        # 两处口径必须一致：复核工作台用的就是「上次复核之后新增」
        # （见 _review_queue_rows），这里跟上。不一致的那次没人会发现——
        # 实测就是使用者点进去看到空白才暴露的。
        counters = {row["company_id"]: row["c"] for row in _rows(conn.execute(
            f"""SELECT e.company_id, COUNT(*) AS c FROM evidences e
                JOIN theses t ON t.id = e.thesis_id
                WHERE e.polarity = 'counter'{_swc('e.company_id')}
                  AND (t.last_reviewed_at IS NULL OR e.created_at > t.last_reviewed_at)
                GROUP BY e.company_id"""
        ).fetchall())}
        pending = {row["company_id"]: row["c"] for row in _rows(conn.execute(
            f"SELECT company_id, COUNT(*) AS c FROM company_calendar_events "
            f"WHERE inbox_status = '待核验' AND relevance = '高'{_swc()} GROUP BY company_id").fetchall())}
        trades = _trade_records(conn.execute(f"{_TRADE_SELECT} WHERE 1=1{_sw(chr(112))}").fetchall())

    positions, _closed = ([], [])
    if trades:
        with connection() as conn:
            positions, _closed = _build_positions(conn, trades)
    held = {item["company_id"]: item for item in positions}
    queue_ids = {row["thesis_id"] for row in review_queue()}
    hits_by_company: dict[int, dict[str, Any]] = {}
    for hit in open_counter_hits():
        hits_by_company.setdefault(hit["company_id"], hit)

    # 体检里说「不利」的方法数。**排在反证之后**：反证是判断已经被事实打脸，
    # 体检只是补充判断——把「有个方法说估值不便宜」排在「你写的卖出条件被触发了」
    # 前面，等于让次要的事挤掉真正紧急的。
    with connection() as conn:
        adverse = {row["company_id"]: row["c"] for row in _rows(conn.execute(
            f"""SELECT company_id, COUNT(*) AS c FROM method_assessments
                WHERE verdict = '不利'{_sw()} GROUP BY company_id""").fetchall())}
        assessed = {row["company_id"] for row in _rows(conn.execute(
            f"SELECT DISTINCT company_id FROM method_assessments WHERE 1=1{_sw()}").fetchall())}
    by_company: dict[int, list[dict[str, Any]]] = {}
    for thesis in theses:
        by_company.setdefault(thesis["company_id"], []).append(thesis)

    rows: list[dict[str, Any]] = []
    for company in companies:
        own = by_company.get(company["id"], [])
        position = held.get(company["id"])
        counter_count = counters.get(company["id"], 0)
        pending_count = pending.get(company["id"], 0)
        due = [t for t in own if t["id"] in queue_ids]

        # **待办只能有一件。** 列出五件「也可以做」的事等于没有指路——
        # 这一页的价值是让你按顺序处理，而不是再给你一份清单去排序。
        hit = hits_by_company.get(company["id"])
        if hit:
            # **命中排在最前面。** 别的待办是「该去看看」，这一条是「你写下的
            # 卖出条件被触发了」——它是唯一一件不处理就等于假装没看见的事。
            action, kind = (f"{hit['event_date'] or ''}「{str(hit['event_title'])[:24]}」"
                            f"命中了你写的反证：{str(hit['clause'])[:40]}", "命中")
        elif not own:
            action, kind = ("还没写下判断——先写一条可以被事实推翻的", "补全")
        elif counter_count and any(t["status"] in ("watching", "intact") for t in own):
            action, kind = (f"有 {counter_count} 条反证，但逻辑状态还没跟着改", "反证")
        elif due:
            action, kind = (f"{len(due)} 条逻辑到复核期了", "复核")
        elif pending_count:
            action, kind = (f"{pending_count} 条实质公告还没核验", "公告")
        elif any(not (t["counter_condition"] or "").strip() for t in own):
            action, kind = ("逻辑没写反证条件——那样它永远不会提醒你", "补全")
        elif company["id"] not in assessed:
            action, kind = ("还没做过方法体检——先看看哪个方法说得上话", "体检")
        elif adverse.get(company["id"]):
            action, kind = (f"体检里有 {adverse[company['id']]} 个方法说不利，值得回头看一眼", "体检")
        else:
            action, kind = ("今天不用管", "无")

        rows.append({
            "company_id": company["id"],
            "symbol": company["symbol"],
            "name": company["name"],
            "industry": company["industry"],
            "watch_group": company["watch_group"],
            "latest_price": company["latest_price"],
            "change_percent": company["change_percent"],
            "pe": company["pe"],
            "pb": company["pb"],
            "quote_as_of": company["market_timestamp"],
            "thesis_count": len(own),
            "thesis_status": own[0]["status"] if own else None,
            "claim": own[0]["claim"] if own else "",
            "counter_condition": own[0]["counter_condition"] if own else "",
            "method_name": own[0]["method_name"] if own else None,
            "counter_evidence": counter_count,
            "assessed": company["id"] in assessed,
            "adverse_methods": adverse.get(company["id"], 0),
            "pending_events": pending_count,
            "reviews_due": len(due),
            "next_review_date": min((t["next_review_date"] for t in own if t["next_review_date"]), default=None),
            "held": position is not None,
            "weight": (position or {}).get("weight"),
            "unrealized_percent": (position or {}).get("unrealized_percent"),
            "action": action,
            "action_kind": kind,
        })

    rows.sort(key=lambda item: (_ACTION_WEIGHT.get(item["action_kind"], 9),
                                not item["held"], item["name"]))
    todo = [row for row in rows if row["action_kind"] != "无"]
    return {
        "as_of": today,
        "rows": rows,
        "todo_count": len(todo),
        "held_count": sum(1 for row in rows if row["held"]),
        "boundary": (
            "这一页只摊开已经发生的事实与已经到期的约定：反证有没有出现、逻辑到没到复核期、"
            "公告核没核完。没有任何一格是对未来的预测，也不给评分与买卖时点——"
            "该不该动手，看完事实由你决定。"
        ),
    }


def company_schedule(company_id: int) -> dict[str, Any] | None:
    """这家公司未来有哪些日子在等着：承诺台账 + 限售股解禁，排成甘特图。

    ## ⚠️ 别跟 `company_timeline` 搞混，它们是两件事

    `company_timeline`（早就有的）：**估值走势 + 公告/交易/判断的时点标记**，
    问的是"我买的时候贵不贵、之后出了什么事"。
    这一个：**承诺与解禁的区间**，问的是"还有多久、会不会撞在一起"。

    前者的每一项是一个**时点**，后者的每一项是一段**时长** —— 画不到一张图上。
    我第一版把这个也叫 timeline，同名函数直接把上面那个盖掉了，
    接口路径也撞在同一个 `/timeline` 上（FastAPI 只认先注册的那个）。

    **募投进度画不出来** —— 库里没有那项数据。`schedule.NO_DATA` 里逐条写了原因，
    并且会随着结果一起返回：悄悄少一条泳道，看的人会以为这家公司没有募投项目。
    """
    from . import schedule as sc

    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id, symbol, name FROM companies WHERE id = ?{_sw()}",
            (company_id,)).fetchone())
        if not company:
            return None
        promises = _rows(conn.execute(
            f"""SELECT subject, statement, category, status, promised_on, due_date, source_url
                FROM management_promises WHERE company_id = ?{_sw()}
                ORDER BY promised_on""", (company_id,)).fetchall())
        # 解禁走日历事件的「解禁」类别。**按 event_date 排**，图上从早到晚。
        lockups = _rows(conn.execute(
            """SELECT event_date, title, detail, url FROM company_calendar_events
               WHERE company_id = ? AND category = '解禁'
               ORDER BY event_date""", (company_id,)).fetchall())
        # 股东会决议的日子。**「自股东会审议通过之日起 12 个月」的起点就是它** ——
        # 那个日期库里早就有，以前拿公告日凑，偏两个多月。不用模型，一次标题匹配。
        # `%` 走参数：写在 SQL 文本里 psycopg2 会当成占位符（本会话踩过三次）。
        meetings = [row["event_date"] for row in conn.execute(
            """SELECT event_date FROM company_calendar_events
               WHERE company_id = ? AND (title LIKE ? OR title LIKE ?)
               ORDER BY event_date""",
            (company_id, "%股东大会决议%", "%股东会决议%")).fetchall()]

    view = sc.build(promises, lockups, meetings=meetings,
                    fundraising=company_fundraising(company_id))
    view.update({"company_id": company_id, "symbol": company["symbol"],
                 "company_name": company["name"]})
    return view


# ── 读进来的文件 ───────────────────────────────────────────────────────────

def save_document(pages: list[dict[str, Any]], summary: dict[str, Any], *,
                  title: str, source: str, url: str = "",
                  company_id: int | None = None, kind: str = "文件",
                  tags: list[str] | None = None) -> int:
    """把解析好的一份文件落库。**一页一行** —— 页码是这一页存在的理由。"""
    from . import documents as doc

    scope = current_scope() or OWNER_SCOPE
    with connection() as conn:
        conn.execute(
            """INSERT INTO documents (user_id, company_id, title, kind, tags, source, url,
                                      page_count, read_pages, char_count, table_count,
                                      modes, unreadable, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (scope, company_id, title[:120], kind, doc.dumps(tags or []), source, url[:500],
             summary["pages"], summary["read"], summary["chars"], summary["tables"],
             doc.dumps(summary["modes"]), doc.dumps(summary["unreadable"]), now_iso()))
        document_id = int(_one_or_none(conn.execute(
            f"SELECT max(id) AS id FROM documents WHERE user_id = '{scope}'").fetchone())["id"])
        for page in pages:
            conn.execute(
                """INSERT INTO document_pages (document_id, page, mode, text, tables, note)
                   VALUES (?,?,?,?,?,?)""",
                (document_id, page["page"], page["mode"], page["text"],
                 page["tables"], page["note"]))
    return document_id


def list_documents(company_id: int | None = None) -> list[dict[str, Any]]:
    """读过的文件，新的在前。"""
    import json

    where = f"WHERE 1=1{_sw()}" + (" AND company_id = ?" if company_id else "")
    params = (company_id,) if company_id else ()
    with connection() as conn:
        rows = _rows(conn.execute(
            f"""SELECT id, company_id, title, kind, tags, source, url, page_count, read_pages,
                       char_count, table_count, modes, unreadable, created_at,
                       digest, digest_kind, digest_pages, digest_missed
                FROM documents {where} ORDER BY created_at DESC, id DESC LIMIT 100""",
            params).fetchall())
    for row in rows:
        row["modes"] = json.loads(row["modes"] or "{}")
        row["unreadable"] = json.loads(row["unreadable"] or "[]")
        row["tags"] = json.loads(row["tags"] or "[]")
        row["digest_pages"] = json.loads(row["digest_pages"] or "[]")
        row["digest_missed"] = json.loads(row["digest_missed"] or "[]")
    return rows


def get_document(document_id: int) -> dict[str, Any] | None:
    """一份文件 + 它的每一页。"""
    import json

    from . import documents as doc

    with connection() as conn:
        row = _one_or_none(conn.execute(
            f"SELECT * FROM documents WHERE id = ?{_sw()}", (document_id,)).fetchone())
        if not row:
            return None
        pages = _rows(conn.execute(
            "SELECT page, mode, text, tables, note FROM document_pages "
            "WHERE document_id = ? ORDER BY page", (document_id,)).fetchall())
    row["modes"] = json.loads(row["modes"] or "{}")
    row["unreadable"] = json.loads(row["unreadable"] or "[]")
    row["tags"] = json.loads(row["tags"] or "[]")
    row["digest_pages"] = json.loads(row["digest_pages"] or "[]")
    row["digest_missed"] = json.loads(row["digest_missed"] or "[]")
    row["pages"] = doc.rows_to_pages(pages)
    return row


def rename_document(document_id: int, title: str, kind: str, tags: list[str]) -> None:
    """把标题、类型、标签重新写一遍。**只用已经存在库里的页，不调模型、不花钱。**

    存在的理由是老文件：标题从第一页读这件事是后加的，之前贴链接读进来的都叫
    `H3_AP202405221634315503_1.pdf`。让人为了一个标题重读一遍要再花几分钱，
    而那几页原文明明就在库里。
    """
    from . import documents as doc

    with connection() as conn:
        conn.execute(
            f"""UPDATE documents SET title = ?, kind = ?, tags = ?
                WHERE id = ?{_sw()}""",
            (title[:120], kind, doc.dumps(tags or []), document_id))


def save_digest(document_id: int, digest: str, kind: str,
                pages: list[int], missed: list[str]) -> None:
    """把读完自动出的那份结果存到文件上。**重开不重付。**"""
    from . import documents as doc

    with connection() as conn:
        conn.execute(
            f"""UPDATE documents SET digest = ?, digest_kind = ?, digest_pages = ?,
                                     digest_missed = ? WHERE id = ?{_sw()}""",
            (digest, kind, doc.dumps(pages), doc.dumps(missed), document_id))


def delete_document(document_id: int) -> bool:
    """删一份。**页跟着走** —— 外键是 ON DELETE CASCADE，但 SQLite 要显式开，
    所以这里自己删一遍，两个后端行为一致。"""
    with connection() as conn:
        row = _one_or_none(conn.execute(
            f"SELECT id FROM documents WHERE id = ?{_sw()}", (document_id,)).fetchone())
        if not row:
            return False
        conn.execute("DELETE FROM document_pages WHERE document_id = ?", (document_id,))
        conn.execute(f"DELETE FROM documents WHERE id = ?{_sw()}", (document_id,))
    return True


def promise_estimate(company_id: int, limit: int = 60) -> dict[str, Any] | None:
    """抽承诺**这一次**大概几分 —— 按真的要喂多少字算，不查典型值表。

    ## 为什么不能用 TYPICAL_TOKENS

    那张表给 promise-extract 填 83000 token（17 分），是几家公司的实测均值。
    线上真跑一次：读 60 条公告、其中 24 条有正文，**冻结 7 分、实扣 3 分**。
    报 17 扣 3 差了五倍多 —— 而这个方向的错跟报低同样糟：**它会把人吓得不敢点**，
    而这个功能恰恰是承诺台账唯一的入口。

    ## 只按已经抓到的正文算，并说清楚

    还没抓的那些正文长度未知（要发网络请求才知道，而报价不该慢）。
    所以按已抓到的平均长度推，**并把"还有几份没抓"如实报出来** ——
    一个报价不说自己是怎么估的，跟一个拍脑袋的数没有区别。
    """
    with connection() as conn:
        company = _one_or_none(conn.execute(
            f"SELECT id FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone())
        if not company:
            return None
        events = _rows(conn.execute(
            f"""SELECT id, title, url FROM company_calendar_events
                WHERE company_id = ?{_swc()} AND COALESCE(relevance, '') <> '低'
                ORDER BY event_date DESC LIMIT ?""", (company_id, limit)).fetchall())
        if not events:
            return {"credits": 0, "events": 0, "note": "这家公司还没有归档的实质性公告。"}
        urls = [row["url"] for row in events if row.get("url")]
        cached = _rows(conn.execute(
            "SELECT char_count FROM announcement_texts WHERE status = '已取正文' "
            f"AND announcement_id IN ({','.join('?' * len(urls))})",
            tuple(_announcement_id(url) for url in urls)).fetchall()) if urls else []

    have = [int(row["char_count"] or 0) for row in cached]
    average = (sum(have) / len(have)) if have else 4000
    # 没抓过的按已抓到的平均长度算。**不是所有公告都有正文**（撤下的、扫描件的），
    # 所以再按已知的命中率打个折 —— 全按有正文算会重蹈"报高吓退人"的覆辙。
    hit_rate = (len(have) / len(urls)) if urls else 0.5
    missing = max(0, len(events) - len(have))
    chars = sum(have) + int(missing * average * max(hit_rate, 0.3))
    # 标题与提示词的固定开销：每条约 60 字。
    chars += len(events) * 60
    from .llm import credits_for

    tokens = int(chars / 1.2) + 3 * 2000        # 中文 1.2 字/token + 分批输出上限
    return {"credits": credits_for(tokens), "events": len(events),
            "with_text": len(have), "chars": chars,
            "note": f"要读 {len(events)} 条公告，其中 {len(have)} 条的正文已经在库里"
                    + (f"，另外 {missing} 条要现抓（按已有的平均长度估）" if missing else "")
                    + f"，合计约 {max(1, chars // 10000)} 万字。"}


def _announcement_id(url: str) -> str:
    """从巨潮的详情页地址里取公告编号（announcement_texts 的主键）。"""
    from .disclosure import announcement_id

    return announcement_id(url) or ""


def save_fundraising(company_id: int, document_id: int | None,
                     projects: list[dict[str, Any]]) -> int:
    """把抽出来的募投项目落库。**同一次发行同一个项目覆盖**，不堆重复行。"""
    from . import documents as doc

    scope = current_scope() or OWNER_SCOPE
    kept = 0
    with connection() as conn:
        for row in projects:
            project = str(row.get("project") or "").strip()[:80]
            if not project or not row.get("pages"):
                continue                      # 没有出处的不进库
            conn.execute(
                """INSERT INTO fundraising_projects
                       (user_id, company_id, document_id, batch, project, committed,
                        invested, progress, due_on, settled, source_pages, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id, company_id, batch, project) DO UPDATE SET
                       document_id = excluded.document_id,
                       committed = excluded.committed, invested = excluded.invested,
                       progress = excluded.progress, due_on = excluded.due_on,
                       settled = excluded.settled, source_pages = excluded.source_pages""",
                (scope, company_id, document_id, str(row.get("batch") or "")[:80], project,
                 row.get("committed_wan"), row.get("invested_wan"), row.get("progress_pct"),
                 str(row.get("due_on") or "") or None, 1 if row.get("settled") else 0,
                 doc.dumps(row.get("pages") or []), now_iso()))
            kept += 1
    return kept


def company_fundraising(company_id: int) -> list[dict[str, Any]]:
    """这家公司的募投项目。**给甘特图那条泳道用。**"""
    import json

    with connection() as conn:
        rows = _rows(conn.execute(
            f"""SELECT batch, project, committed, invested, progress, due_on, settled,
                       source_pages, document_id, created_at
                FROM fundraising_projects WHERE company_id = ?{_sw()}
                ORDER BY (due_on IS NULL), due_on, project""", (company_id,)).fetchall())
    for row in rows:
        row["source_pages"] = json.loads(row["source_pages"] or "[]")
    return rows
