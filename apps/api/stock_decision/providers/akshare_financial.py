from datetime import datetime
from typing import Any

from .base import InvalidSymbolError, QuoteProviderError
from .stock_sdk import normalize_cn_symbol

# 三张表里除了通用字段之外，还要留下的科目。
#
# **这三张表本来就已经全下下来了**（147 + 83 + 71 列），此前只挑走十来个通用字段，
# 剩下的全部扔掉——而「白酒的合同负债、银行的净息差、地产的销售回款」这类
# 真正能分辨生意的数，恰恰都在被扔掉的那部分里。留下来不多花一次网络请求。
#
# 只留白名单里这些，不是全留：147 列 × 四十期 × 每家公司，绝大部分永远不会有人看。
#
# 银行的三张表**是另一套科目体系**（利润表上没有营业成本，只有净利息收入、
# 手续费及佣金净收入），所以两套科目都在这张单子里，取不到的那些自然是空。
LINE_ITEMS = {
    "资产负债表": (
        "合同负债", "预收款项", "预收账款",        # 下游先打钱：预收模式的领先指标
        "合同资产", "应付账款", "应付票据及应付账款",  # 对上游的占款：产业链地位
        "存货", "投资性房地产", "在建工程", "固定资产净额", "长期股权投资",
        "客户存款(吸收存款)", "吸收存款", "发放贷款及垫款", "减:贷款损失准备",   # 银行
        "流动资产合计", "流动负债合计", "货币资金",
    ),
    "利润表": (
        "营业总收入", "营业收入", "营业成本", "销售费用", "管理费用", "研发费用",
        # ── 银行与保险：**另一套科目体系**，利润表上没有营业成本。
        #
        # ⚠️ 这几个名字是**照着数据源真实的列名抄的**，不是想当然写的。
        # 上一版凭印象写了「净利息收入」「客户存款(吸收存款)」，线上一行都没取到 ——
        # 白名单里的名字对不上，表现出来只是"这家公司没有这个科目"，
        # 跟真的没有长得一模一样，所以两年都没人发现。
        # 真名（2026-08-17 实测 stock_financial_report_sina）：
        #   工行  业务及管理费用 / 营业税金及附加 / 手续费及佣金支出 / 减:所得税
        #   平安  业务及管理费   / 营业税金及附加 / 退保金 / 赔付支出 /
        #         提取保险责任准备金 / 银行业务利息净收入 / 减:所得税费用
        # 两家连「业务及管理费」都差一个字，所以两个都留。
        "利息净收入", "银行业务利息净收入", "利息收入", "利息支出",
        "手续费及佣金净收入", "手续费及佣金收入", "手续费及佣金支出",
        "业务及管理费", "业务及管理费用", "营业税金及附加",
        "营业支出",                                # 支出合计：拿来校验拆开的几项对不对
        "退保金", "赔付支出", "减:摊回赔付支出",
        "提取保险责任准备金", "减:摊回保险责任准备金", "分保费用",
        "投资收益", "减:所得税", "减:所得税费用",
        "房地产销售收入", "房地产销售成本",                        # 地产
        "信用减值损失", "资产减值损失",
    ),
    "现金流量表": (
        "销售商品、提供劳务收到的现金",     # 收现比：收入是不是真的收到了钱
        "购建固定资产、无形资产和其他长期资产所支付的现金",
        "经营活动产生的现金流量净额", "分配股利、利润或偿付利息所支付的现金",
    ),
}


class AkShareFinancialProvider:
    """A-share report-period facts from AKShare's Sina financial-report adapter."""

    provider_id = "akshare_sina_financial"
    display_name = "AKShare / 新浪财经"
    category = "财务报告"

    def _provider_symbol(self, symbol: str) -> str:
        canonical = normalize_cn_symbol(symbol)
        if canonical.startswith("6"):
            return f"sh{canonical}"
        if canonical.startswith(("0", "3")):
            return f"sz{canonical}"
        raise InvalidSymbolError(f"当前财务源暂不支持代码 {canonical} 所属市场")

    def fetch_financial_periods(self, symbol: str) -> list[dict[str, Any]]:
        try:
            import akshare as ak
        except ModuleNotFoundError as exc:
            raise QuoteProviderError("AKShare 未安装，无法同步财务报告") from exc

        provider_symbol = self._provider_symbol(symbol)
        try:
            income = ak.stock_financial_report_sina(stock=provider_symbol, symbol="利润表")
            cashflow = ak.stock_financial_report_sina(stock=provider_symbol, symbol="现金流量表")
            balance = ak.stock_financial_report_sina(stock=provider_symbol, symbol="资产负债表")
        except Exception as exc:  # AKShare normalizes multiple upstream transport errors.
            raise QuoteProviderError("AKShare 财务报告请求失败") from exc

        def numeric(row: dict[str, Any], field: str) -> float | None:
            value = row.get(field)
            if value is None:
                return None
            try:
                if value != value:  # pandas NaN
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        def index_by_report_date(frame: Any) -> dict[str, dict[str, Any]]:
            rows: dict[str, dict[str, Any]] = {}
            for row in frame.to_dict(orient="records"):
                report_date = str(row.get("报告日") or "")
                if len(report_date) == 8 and report_date.isdigit():
                    rows.setdefault(report_date, row)
            return rows

        income_rows = index_by_report_date(income)
        cashflow_rows = index_by_report_date(cashflow)
        balance_rows = index_by_report_date(balance)
        periods: list[dict[str, Any]] = []
        for report_date in sorted(income_rows, reverse=True):
            income_row = income_rows[report_date]
            cashflow_row = cashflow_rows.get(report_date, {})
            balance_row = balance_rows.get(report_date, {})
            revenue = numeric(income_row, "营业总收入") or numeric(income_row, "营业收入")
            net_profit = numeric(income_row, "归属于母公司所有者的净利润") or numeric(income_row, "净利润")
            assets = numeric(balance_row, "资产总计")
            liabilities = numeric(balance_row, "负债合计")
            equity = numeric(balance_row, "归属于母公司股东权益合计") or numeric(balance_row, "所有者权益(或股东权益)合计")
            # 有息负债按公开口径合并：短期借款、一年内到期的非流动负债、长期借款与应付债券。
            interest_parts = [
                numeric(balance_row, "短期借款"),
                numeric(balance_row, "一年内到期的非流动负债"),
                numeric(balance_row, "长期借款"),
                numeric(balance_row, "应付债券"),
            ]
            interest_debt = sum(part for part in interest_parts if part is not None) if any(part is not None for part in interest_parts) else None
            announcement = str(income_row.get("公告日期") or "")
            periods.append(
                {
                    "report_date": datetime.strptime(report_date, "%Y%m%d").date().isoformat(),
                    "revenue": revenue,
                    "net_profit": net_profit,
                    "operating_cash_flow": numeric(cashflow_row, "经营活动产生的现金流量净额"),
                    "operating_cost": numeric(income_row, "营业成本"),
                    "rnd_expense": numeric(income_row, "研发费用"),
                    "capex": numeric(cashflow_row, "购建固定资产、无形资产和其他长期资产所支付的现金"),
                    "receivables": numeric(balance_row, "应收票据及应收账款") or numeric(balance_row, "应收账款"),
                    "inventory": numeric(balance_row, "存货"),
                    "interest_bearing_debt": interest_debt,
                    "total_assets": assets,
                    "total_liabilities": liabilities,
                    "equity": equity,
                    "debt_ratio": round(liabilities / assets * 100, 2) if assets not in {None, 0} and liabilities is not None else None,
                    "currency": str(income_row.get("币种") or "CNY"),
                    "audit_status": str(income_row.get("是否审计") or "待确认"),
                    "announcement_date": datetime.strptime(announcement, "%Y%m%d").date().isoformat() if len(announcement) == 8 and announcement.isdigit() else None,
                    # 白名单科目原样带出来。**存原始科目而不是存算好的比率**：
                    # 算术随时可以改，而改了之后老记录应该跟着重算，
                    # 不是背着一个按旧公式算出来的数。
                    "line_items": {
                        name: value
                        for sheet, row in (("资产负债表", balance_row), ("利润表", income_row),
                                           ("现金流量表", cashflow_row))
                        for name in LINE_ITEMS[sheet]
                        if (value := numeric(row, name)) is not None
                    },
                }
            )

        annual_periods = sorted((item for item in periods if item["report_date"].endswith("-12-31")), key=lambda item: item["report_date"])
        previous_equity: float | None = None
        annual_roe: dict[str, float] = {}
        for item in annual_periods:
            equity = item["equity"]
            net_profit = item["net_profit"]
            if isinstance(equity, float) and isinstance(net_profit, float) and equity != 0:
                average_equity = (previous_equity + equity) / 2 if previous_equity not in {None, 0} else equity
                annual_roe[item["report_date"]] = round(net_profit / average_equity * 100, 2)
            if isinstance(equity, float):
                previous_equity = equity
        for item in periods:
            item["roe_estimate"] = annual_roe.get(item["report_date"])
        return periods
