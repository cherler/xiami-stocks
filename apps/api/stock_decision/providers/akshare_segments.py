"""主营构成：年报披露的分部收入、成本与毛利率。

**这是本项目里少有的、既是真数据又直接回答核心问题的东西。**「这家公司靠什么
赚钱」在档案里原本只有一句主营业务描述，和一张模型推断出来的产业链图——
前者太粗，后者每条都标着「待证实」。而年报的分部附注是披露过的事实：
茅台酒占收入 86.8%、毛利率 93.5%；系列酒占 13.2%、毛利率 76.1%。
一眼就知道钱从哪来、哪一块真赚钱。

三种口径都取：按产品、按行业、按地区。它们回答的是不同的问题
（卖什么 / 属于哪个行业 / 卖到哪里），不能互相替代，也不能加在一起。

## 「其他(补充)」

数据源会补一行差额，占比常常是 0.04% 这种量级，偶尔是负的。保留而不丢弃——
丢掉的话各块占比加起来不等于 100%，看图的人会以为我们算错了。
但它不是一个业务分部，所以标出来让页面能把它画成灰色。
"""

from typing import Any

from .base import QuoteProviderError
from .stock_sdk import normalize_cn_symbol

# 数据源的分类名 → 我们的口径名。只认这三种，其他忽略。
_DIMENSIONS = {"按产品分类": "产品", "按行业分类": "行业", "按地区分类": "地区"}

# 数据源补的差额行。不是业务分部，页面要能认出来单独处理。
FILLER = "其他(补充)"


class AkShareSegmentProvider:
    """东方财富的主营构成表。"""

    provider_id = "akshare_em_segments"
    display_name = "AKShare / 东方财富"
    category = "主营构成"

    def _provider_symbol(self, symbol: str) -> str:
        canonical = normalize_cn_symbol(symbol)
        if canonical.startswith("6"):
            return f"SH{canonical}"
        if canonical.startswith(("0", "3")):
            return f"SZ{canonical}"
        if canonical.startswith(("4", "8")):
            return f"BJ{canonical}"
        raise QuoteProviderError(f"主营构成源暂不支持代码 {canonical} 所属市场")

    def fetch_segments(self, symbol: str, periods: int = 4) -> list[dict[str, Any]]:
        """最近几个报告期的分部构成。默认取 4 期，够画一张构成变化图。"""
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步主营构成") from exc

        try:
            frame = ak.stock_zygc_em(symbol=self._provider_symbol(symbol))
        except Exception as exc:                       # noqa: BLE001 — 上游什么都可能抛
            raise QuoteProviderError(f"主营构成拉取失败：{exc}") from exc

        if frame is None or frame.empty:
            return []

        canonical = normalize_cn_symbol(symbol)
        # 报告期倒序取前 N 期。**不能只取最新一期**：最新可能是半年报，
        # 而半年报的分部构成跟年报不可比（累计口径 + 季节性）。
        # 把几期都存下来，由上层决定画哪一期。
        wanted = sorted(frame["报告日期"].astype(str).unique(), reverse=True)[:periods]

        rows: list[dict[str, Any]] = []
        for _, item in frame.iterrows():
            report_date = str(item["报告日期"])[:10]
            if report_date not in wanted:
                continue
            dimension = _DIMENSIONS.get(str(item["分类类型"]))
            if dimension is None:
                continue
            rows.append({
                "symbol": canonical,
                "report_date": report_date,
                "dimension": dimension,
                "segment": str(item["主营构成"]).strip(),
                "revenue": _number(item.get("主营收入")),
                # 源里的占比是小数（0.8677），换成百分数，跟站内其他比率一致
                "revenue_share": _percent(item.get("收入比例")),
                "cost": _number(item.get("主营成本")),
                "profit": _number(item.get("主营利润")),
                "profit_share": _percent(item.get("利润比例")),
                "gross_margin": _percent(item.get("毛利率")),
            })
        return rows


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result          # NaN


def _percent(value: Any) -> float | None:
    raw = _number(value)
    return None if raw is None else round(raw * 100, 2)
