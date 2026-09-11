"""财务算子表：所有比率的唯一定义处。

**模型永远不碰计算。** 它拿到的每一个数值都是这里算好的，连同口径一起给它；
它写不出没算过的数，也改不了口径。这样出问题时能定位到是取数错、算子错，还是模型读错——
如果让模型自己从原始科目里算，这三者会混成一团，而且它算错了没人发现。

（这条原则来自 AI4Finance 的 FinRobot：确定性的财务计算与 LLM 叙述严格分开。）

每个算子声明四件事：
- inputs：它需要哪些科目。缺一个就返回 None 和缺了什么，而不是当成 0。
- formula：口径。同一个"毛利率"不同网站算法不同，口径不跟着数走就没法交叉验证。
- caveat：这个比率本身的陷阱。有陷阱的数字比没有数字更危险，因为它看起来是可信的。
- fn：纯函数，只依赖传进来的 row。

算子对两类输入都成立：定期报告的一期（`financial_periods` 的一行）与全市场底座的一行
（`market_universe`），因为它们只是字段名不同的同一批科目。取不到的字段就是 None。
"""

from dataclasses import dataclass
from typing import Any, Callable


def _ratio(numerator: Any, denominator: Any, *, scale: float = 100.0, digits: int = 2) -> float | None:
    """比值。分母为 0 或缺失一律返回 None——不要用 0 或极大值替代。"""

    if numerator is None or denominator in (None, 0):
        return None
    try:
        return round(float(numerator) / float(denominator) * scale, digits)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _period_days(report_date: str | None) -> int | None:
    """报告期覆盖的天数，用来把存货、应收换算成周转天数。"""

    if not report_date or len(str(report_date)) < 10:
        return None
    return {"03-31": 90, "06-30": 181, "09-30": 273, "12-31": 365}.get(str(report_date)[5:10])


@dataclass(frozen=True)
class Operator:
    key: str
    label: str
    unit: str
    formula: str
    inputs: tuple[str, ...]
    fn: Callable[[dict[str, Any]], float | None]
    caveat: str = ""
    group: str = "其他"


def _positive(value: Any) -> bool:
    return value is not None and value > 0


OPERATORS: tuple[Operator, ...] = (
    # ---------------------------------------------------------------- 盈利
    Operator(
        key="gross_margin", label="毛利率", unit="%", group="盈利",
        formula="(营业总收入 − 营业成本) / 营业总收入",
        inputs=("revenue", "operating_cost"),
        caveat="不同行业的成本口径差别很大，跨行业比较没有意义。",
        fn=lambda row: _ratio(
            (row["revenue"] - row["operating_cost"]) if row.get("revenue") is not None and row.get("operating_cost") is not None else None,
            row.get("revenue"),
        ),
    ),
    Operator(
        key="net_margin", label="净利率", unit="%", group="盈利",
        formula="归母净利润 / 营业总收入",
        inputs=("net_profit", "revenue"),
        caveat="一次性损益会让单期净利率失真，要看多期。",
        fn=lambda row: _ratio(row.get("net_profit"), row.get("revenue")),
    ),
    Operator(
        key="roa", label="总资产收益率", unit="%", group="盈利",
        formula="归母净利润 / 总资产",
        inputs=("net_profit", "total_assets"),
        caveat="用期末总资产而非平均总资产，扩张期会偏低。",
        fn=lambda row: _ratio(row.get("net_profit"), row.get("total_assets")),
    ),
    Operator(
        key="roe_estimate", label="净资产收益率（本站估算）", unit="%", group="盈利",
        formula="归母净利润 / 期末归母净资产",
        inputs=("net_profit", "equity"),
        caveat="用期末净资产而非平均净资产；季报未年化，不能和年报的 ROE 直接比。",
        fn=lambda row: _ratio(row.get("net_profit"), row.get("equity")),
    ),
    # ---------------------------------------------------------------- 现金
    Operator(
        key="cash_conversion", label="现金含量", unit="%", group="现金",
        formula="经营活动现金流净额 / 归母净利润（净利润为负时不计算）",
        inputs=("operating_cash_flow", "net_profit"),
        caveat="低于 100% 说明利润没有全部变成现金；持续低于 50% 要查应收与存货。",
        fn=lambda row: _ratio(row.get("operating_cash_flow"), row["net_profit"]) if _positive(row.get("net_profit")) else None,
    ),
    Operator(
        key="free_cash_flow", label="自由现金流", unit=" 元", group="现金",
        formula="经营活动现金流净额 − 购建固定资产等支付的现金",
        inputs=("operating_cash_flow", "capex"),
        caveat="扩张期为负是正常的，要看它换回了什么产能。",
        fn=lambda row: round(row["operating_cash_flow"] - row["capex"], 2)
        if row.get("operating_cash_flow") is not None and row.get("capex") is not None else None,
    ),
    Operator(
        key="fcf_margin", label="自由现金流利润率", unit="%", group="现金",
        formula="(经营活动现金流净额 − 资本开支) / 营业总收入",
        inputs=("operating_cash_flow", "capex", "revenue"),
        caveat="重资产行业天然偏低，只在同行之间比较才有意义。",
        fn=lambda row: _ratio(
            (row["operating_cash_flow"] - row["capex"]) if row.get("operating_cash_flow") is not None and row.get("capex") is not None else None,
            row.get("revenue"),
        ),
    ),
    Operator(
        key="cash_ratio", label="每股现金含量", unit="%", group="现金",
        formula="每股经营现金流 / 每股收益（每股收益为正时才计算）",
        inputs=("ocf_per_share", "eps"),
        caveat="全市场底座里没有现金流量表，只能用每股口径近似；一次性损益会让它失真。",
        fn=lambda row: _ratio(row.get("ocf_per_share"), row["eps"]) if _positive(row.get("eps")) else None,
    ),
    # ---------------------------------------------------------------- 杠杆
    Operator(
        key="debt_ratio", label="资产负债率", unit="%", group="杠杆",
        formula="负债合计 / 资产总计",
        inputs=("total_liabilities", "total_assets"),
        caveat="金融与地产的正常水平远高于制造业，跨行业比无意义。",
        fn=lambda row: _ratio(row.get("total_liabilities"), row.get("total_assets")),
    ),
    Operator(
        key="interest_debt_ratio", label="有息负债率", unit="%", group="杠杆",
        formula="有息负债 / 资产总计",
        inputs=("interest_bearing_debt", "total_assets"),
        caveat="应付账款不算有息负债；这个比率比资产负债率更能反映真实偿债压力。",
        fn=lambda row: _ratio(row.get("interest_bearing_debt"), row.get("total_assets")),
    ),
    Operator(
        key="equity_multiplier", label="权益乘数", unit=" 倍", group="杠杆",
        formula="资产总计 / 归母净资产",
        inputs=("total_assets", "equity"),
        caveat="高 ROE 有多少来自杠杆，看这个数；它同时是杜邦分解的第三项。",
        fn=lambda row: _ratio(row.get("total_assets"), row.get("equity"), scale=1.0),
    ),
    # ---------------------------------------------------------------- 效率
    Operator(
        key="asset_turnover", label="总资产周转率", unit=" 次", group="效率",
        formula="营业总收入 / 资产总计",
        inputs=("revenue", "total_assets"),
        caveat="季报未年化，只能和同一报告期比。",
        fn=lambda row: _ratio(row.get("revenue"), row.get("total_assets"), scale=1.0),
    ),
    Operator(
        key="receivable_days", label="应收周转天数", unit=" 天", group="效率",
        formula="应收票据及应收账款 / 营业总收入 × 报告期天数",
        inputs=("receivables", "revenue", "report_date"),
        caveat="持续拉长说明放宽了账期换收入，要和收入增速一起看。",
        fn=lambda row: round(row["receivables"] / row["revenue"] * _period_days(row.get("report_date")), 1)
        if row.get("receivables") is not None and row.get("revenue") not in (None, 0) and _period_days(row.get("report_date")) else None,
    ),
    Operator(
        key="inventory_days", label="存货周转天数", unit=" 天", group="效率",
        formula="存货 / 营业成本 × 报告期天数",
        inputs=("inventory", "operating_cost", "report_date"),
        caveat="白酒等以陈化为工艺的行业，存货天数长是常态而非积压。",
        fn=lambda row: round(row["inventory"] / row["operating_cost"] * _period_days(row.get("report_date")), 1)
        if row.get("inventory") is not None and row.get("operating_cost") not in (None, 0) and _period_days(row.get("report_date")) else None,
    ),
    Operator(
        key="rnd_ratio", label="研发费用率", unit="%", group="效率",
        formula="研发费用 / 营业总收入",
        inputs=("rnd_expense", "revenue"),
        caveat="资本化的研发不在费用里，横比要先确认双方的资本化政策。",
        fn=lambda row: _ratio(row.get("rnd_expense"), row.get("revenue")),
    ),
    # ---------------------------------------------------------------- 估值
    Operator(
        key="earnings_yield", label="盈利收益率", unit="%", group="估值",
        formula="1 / 市盈率 TTM",
        inputs=("pe_ttm",),
        caveat="市盈率为负时不计算；它是 PE 的倒数，方便和债券收益率比。",
        fn=lambda row: _ratio(1, row["pe_ttm"]) if _positive(row.get("pe_ttm")) else None,
    ),
    Operator(
        key="peg", label="PEG", unit="", group="估值",
        formula="市盈率 TTM / 净利润同比增速",
        inputs=("pe_ttm", "net_profit_growth"),
        caveat="用单期增速计算，对增长的持续性无能为力；增长拐点处最容易误导。",
        fn=lambda row: _ratio(row["pe_ttm"], row["net_profit_growth"], scale=1.0)
        if _positive(row.get("pe_ttm")) and _positive(row.get("net_profit_growth")) else None,
    ),
    Operator(
        key="graham_number", label="PE × PB", unit="", group="估值",
        formula="市盈率 TTM × 市净率",
        inputs=("pe_ttm", "pb"),
        caveat="格雷厄姆给防御型投资者的 22.5 上限来自 1940 年代美国市场，照搬到 A 股会大量选中周期股。",
        fn=lambda row: round(row["pe_ttm"] * row["pb"], 2)
        if _positive(row.get("pe_ttm")) and _positive(row.get("pb")) else None,
    ),
    Operator(
        key="pb_over_roe", label="市净率／净资产收益率", unit="", group="估值",
        formula="市净率 / 净资产收益率（%）",
        inputs=("pb", "roe"),
        caveat="同样赚钱效率下谁更便宜；ROE 不可持续时这个比值会骗人。",
        fn=lambda row: _ratio(row["pb"], row["roe"], scale=1.0) if _positive(row.get("roe")) else None,
    ),
)

OPERATORS_BY_KEY = {operator.key: operator for operator in OPERATORS}


def compute(key: str, row: dict[str, Any]) -> dict[str, Any]:
    """算一个指标，连同口径与缺失原因一起返回。算不出就说缺什么，不用 0 顶替。"""

    operator = OPERATORS_BY_KEY[key]
    missing = [name for name in operator.inputs if row.get(name) is None]
    value = None if missing else operator.fn(row)
    if value is None and not missing:
        # 科目齐全但仍算不出，说明触发了算子自己的守卫（分母为零、净利润为负等）
        missing_reason = f"口径不适用：{operator.formula}"
    elif missing:
        missing_reason = f"缺少科目：{('、').join(missing)}"
    else:
        missing_reason = ""
    return {
        "key": operator.key,
        "label": operator.label,
        "value": value,
        "unit": operator.unit,
        "formula": operator.formula,
        "caveat": operator.caveat,
        "group": operator.group,
        "unavailable_reason": missing_reason or None,
    }


def compute_all(row: dict[str, Any], keys: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    return [compute(key, row) for key in (keys or tuple(OPERATORS_BY_KEY))]


def values(row: dict[str, Any], keys: tuple[str, ...] | None = None) -> dict[str, float | None]:
    """只要数值的场合用这个；需要口径时用 compute。"""

    return {item["key"]: item["value"] for item in compute_all(row, keys)}


def dupont(row: dict[str, Any]) -> dict[str, Any]:
    """杜邦分解：ROE = 净利率 × 总资产周转率 × 权益乘数。

    拆开是为了回答"高 ROE 是靠赚得多、转得快，还是靠借得多"——这三条的可持续性完全不同。
    """

    parts = {key: compute(key, row) for key in ("net_margin", "asset_turnover", "equity_multiplier")}
    missing = [item["label"] for item in parts.values() if item["value"] is None]
    product = None
    if not missing:
        product = round(
            parts["net_margin"]["value"] / 100 * parts["asset_turnover"]["value"] * parts["equity_multiplier"]["value"] * 100,
            2,
        )
    return {
        "components": list(parts.values()),
        "roe_reconstructed": product,
        "unit": "%",
        "formula": "净资产收益率 = 净利率 × 总资产周转率 × 权益乘数",
        "unavailable_reason": f"缺少：{('、').join(missing)}" if missing else None,
        "caveat": "三项都用期末数计算，与年报披露的加权 ROE 会有差异；季报未年化。",
    }
