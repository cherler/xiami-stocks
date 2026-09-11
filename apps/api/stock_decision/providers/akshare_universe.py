"""全 A 与主要指数的市场底座数据。

来源分工：
- 价格、估值与市值：东方财富全市场快照（一次请求拿全 A）；失败时降级到新浪全市场快照，
  但新浪只有价格，降级会被显式标注，估值与市值留空而不是补 0。
- 财务核心指标：东方财富按报告期的业绩报表（一次请求拿全市场的 ROE、毛利率、增速与每股指标）。
- 指数成分：中证指数官网。

这一层只负责把事实取回来并标明覆盖范围与截止日；任何筛选与排序都在上层完成。
"""

from datetime import date, datetime
from typing import Any

from .base import QuoteProviderError

MAIN_INDEXES = (
    ("000300", "沪深300"),
    ("000905", "中证500"),
    ("000016", "上证50"),
    ("000852", "中证1000"),
)

# 五套预置策略要用到的字段并集；底座按它来决定抓什么。
FUNDAMENTAL_FIELDS = (
    "revenue",
    "revenue_growth",
    "net_profit",
    "net_profit_growth",
    "roe",
    "gross_margin",
    "eps",
    "bps",
    "ocf_per_share",
)


def _number(value: Any) -> float | None:
    if value is None or value != value:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _text(value: Any) -> str | None:
    if value is None or value != value:
        return None
    text = str(value).strip()
    return text or None


def board_of(symbol: str) -> str:
    if symbol.startswith("688"):
        return "科创板"
    if symbol.startswith("300") or symbol.startswith("301"):
        return "创业板"
    if symbol.startswith(("8", "4")):
        return "北交所"
    return "主板"


def exchange_of(symbol: str) -> str:
    if symbol.startswith("6"):
        return "上海证券交易所"
    if symbol.startswith(("4", "8")):
        return "北京证券交易所"
    return "深圳证券交易所"


class AkShareUniverseProvider:
    provider_id = "akshare_universe"
    display_name = "AKShare / 东方财富·中证指数"
    category = "全市场底座"

    def fetch_spot(self) -> dict[str, Any]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步全市场快照") from exc

        try:
            frame = ak.stock_zh_a_spot_em()
            rows = [
                {
                    "symbol": _text(row.get("代码")),
                    "name": _text(row.get("名称")),
                    "price": _number(row.get("最新价")),
                    "change_percent": _number(row.get("涨跌幅")),
                    "pe_ttm": _number(row.get("市盈率-动态")),
                    "pb": _number(row.get("市净率")),
                    "total_market_cap": _number(row.get("总市值")),
                    "float_market_cap": _number(row.get("流通市值")),
                    "turnover_rate": _number(row.get("换手率")),
                    "ytd_change": _number(row.get("年初至今涨跌幅")),
                    "change_60d": _number(row.get("60日涨跌幅")),
                }
                for row in frame.to_dict(orient="records")
            ]
            return {
                "rows": [row for row in rows if row["symbol"] and row["name"]],
                "source": "东方财富全市场快照",
                "degraded": False,
                "missing_fields": [],
            }
        except Exception as primary_error:
            try:
                frame = ak.stock_zh_a_spot()
            except Exception as fallback_error:
                raise QuoteProviderError(
                    f"全市场快照两个来源都失败：东方财富 {primary_error}；新浪 {fallback_error}"
                ) from fallback_error
            rows = [
                {
                    "symbol": (_text(row.get("代码")) or "")[-6:],
                    "name": _text(row.get("名称")),
                    "price": _number(row.get("最新价")),
                    "change_percent": _number(row.get("涨跌幅")),
                    "pe_ttm": None,
                    "pb": None,
                    "total_market_cap": None,
                    "float_market_cap": None,
                    "turnover_rate": None,
                    "ytd_change": None,
                    "change_60d": None,
                }
                for row in frame.to_dict(orient="records")
            ]
            return {
                "rows": [row for row in rows if row["symbol"] and row["name"]],
                "source": "新浪全市场快照（降级）",
                "degraded": True,
                "missing_fields": ["市盈率", "市净率", "总市值", "流通市值", "换手率", "年初至今涨跌", "60 日涨跌"],
            }

    def fetch_fundamentals(self, report_date: str) -> dict[str, Any]:
        """按报告期取全市场业绩报表；report_date 形如 20251231。"""

        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步全市场财务") from exc
        try:
            frame = ak.stock_yjbb_em(date=report_date)
        except Exception as exc:
            raise QuoteProviderError(f"全市场业绩报表请求失败：{exc}") from exc
        rows = []
        for row in frame.to_dict(orient="records"):
            symbol = _text(row.get("股票代码"))
            if not symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "name": _text(row.get("股票简称")),
                    "revenue": _number(row.get("营业总收入-营业总收入")),
                    "revenue_growth": _number(row.get("营业总收入-同比增长")),
                    "net_profit": _number(row.get("净利润-净利润")),
                    "net_profit_growth": _number(row.get("净利润-同比增长")),
                    "roe": _number(row.get("净资产收益率")),
                    "gross_margin": _number(row.get("销售毛利率")),
                    "eps": _number(row.get("每股收益")),
                    "bps": _number(row.get("每股净资产")),
                    "ocf_per_share": _number(row.get("每股经营现金流量")),
                    "industry": _text(row.get("所处行业")),
                    "announcement_date": _text(row.get("最新公告日期")),
                }
            )
        return {"rows": rows, "source": "东方财富业绩报表", "report_date": report_date}

    def fetch_dividends(self, period: str) -> dict[str, Any]:
        """按报告期取全市场分红送配，含**股息率**。

        为什么这条能通而行情那条不通：东财的 push2 系列被墙了（实时行情走那里），
        但 datacenter 系列一直是通的 —— 分红送配、业绩报表都在 datacenter 上。
        「拿不到数据」这个结论要按接口分别验，不能按域名一刀切
        （股息现金流策略被这个笼统结论挡了很久，实际上一个函数就能取到）。

        period 形如 20241231。年报期的股息率才是完整年度口径。
        """
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步分红数据") from exc
        try:
            frame = ak.stock_fhps_em(date=period)
        except Exception as exc:
            raise QuoteProviderError(f"全市场分红送配请求失败：{exc}") from exc
        rows = []
        for row in frame.to_dict(orient="records"):
            symbol = _text(row.get("代码"))
            if not symbol:
                continue
            rows.append({
                "symbol": symbol,
                # **单位要在这里统一。** 东财这个字段是小数（0.1023 = 10.23%），
                # 而申万那份是百分数（2.34 = 2.34%）。两个源的数字混进同一列，
                # 筛选条件「股息率 > 3」会把 3% 与 300% 当成一回事——
                # 而且页面上完全看不出来。核对方式：广汇能源 6.22 元/10 股、
                # 股息率 0.1023 → 反推股价 6.08 元，与实际价格对得上。
                "dividend_yield": (lambda v: None if v is None else round(v * 100, 4))(
                    _number(row.get("现金分红-股息率"))),
                "dividend_per_10": _number(row.get("现金分红-现金分红比例")),
                "bonus_per_10": _number(row.get("送转股份-送转总比例")),
                "dividend_plan_date": _text(row.get("最新公告日期")),
            })
        return {"rows": rows, "source": "东方财富分红送配", "period": period}

    def fetch_sw_industries(self) -> dict[str, Any]:
        """申万一级/二级行业。

        东财的「所处行业」是它自己的分类，粒度粗且口径不透明（"电子"下面既有
        面板也有半导体设备，同业对照因此对不起来）。申万二级 131 个分类是
        行业研究的通行口径，且这个接口不在被墙的 push2 上。
        """
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步行业分类") from exc
        levels = []
        for label, call in (("一级", "sw_index_first_info"), ("二级", "sw_index_second_info")):
            try:
                frame = getattr(ak, call)()
            except Exception:
                continue
            for row in frame.to_dict(orient="records"):
                code = _text(row.get("行业代码"))
                if not code:
                    continue
                levels.append({
                    "level": label,
                    "code": code,
                    "name": _text(row.get("行业名称")),
                    "parent": _text(row.get("上级行业")),
                    "constituents": _number(row.get("成份个数")),
                    "pe_ttm": _number(row.get("TTM(滚动)市盈率")),
                    "pb": _number(row.get("市净率")),
                    "dividend_yield": _number(row.get("静态股息率")),
                })
        if not levels:
            raise QuoteProviderError("申万行业分类一个都没取到")
        return {"levels": levels, "source": "申万宏源"}

    def fetch_index_members(self) -> dict[str, Any]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步指数成分") from exc
        members: list[dict[str, Any]] = []
        missing: list[str] = []
        for code, name in MAIN_INDEXES:
            try:
                frame = ak.index_stock_cons_csindex(symbol=code)
            except Exception:
                missing.append(name)
                continue
            for row in frame.to_dict(orient="records"):
                symbol = _text(row.get("成分券代码"))
                if symbol:
                    members.append({"index_code": code, "index_name": name, "symbol": symbol})
        if not members:
            raise QuoteProviderError("主要指数成分都没有取到")
        return {"members": members, "source": "中证指数官网", "missing_indexes": missing}


def latest_annual_period(today: date | None = None) -> str:
    """最近一个已经披露完的年报期。年报净利润是最稳的 PE 分母：不受季节性影响，也不用年化。"""

    moment = today or date.today()
    return f"{moment.year - 1}1231" if moment.month >= 5 else f"{moment.year - 2}1231"


def latest_report_period(today: date | None = None) -> str:
    """业绩报表按报告期发布；取当前时点上一个已经披露完的报告期。"""

    moment = today or date.today()
    year, month = moment.year, moment.month
    if month >= 11:
        return f"{year}0930"
    if month >= 9:
        return f"{year}0630"
    if month >= 5:
        return f"{year}0331"
    return f"{year - 1}1231"


universe_provider = AkShareUniverseProvider()
