"""价值候选策略库。

设计原则：
- 不设任何条件时也能出候选：预置策略开箱可用，不满意就换一套，任何一套都能复制成自己的。
- 每套策略都写明**出处**与**已知偏差**。机械筛选一定有系统性盲区，不写出来，换策略就变成碰运气。
- 每套声明它依赖哪些字段；字段没同步到时该策略不可用，并说明缺什么，而不是用残缺数据出一份看着能用的清单。
- 策略不以人名命名。用人名会暗示这套筛选等同于那个人的方法，而他们的过程里大部分是机械筛选做不到的定性判断。
- 输出永远是"接下来值得研究哪几家"，不是买入建议：不给目标价、不给买卖时点、不给不说明依据的评分。
"""

from dataclasses import dataclass, field

from .operators import OPERATORS_BY_KEY, compute as operator_compute
from typing import Any, Callable

# 底座里可直接使用的字段，以及由它们推导出来的比值
FIELD_LABELS = {
    "pe_ttm": "市盈率 TTM",
    "pb": "市净率",
    "roe": "净资产收益率（最新报告期，可能是单季）",
    "gross_margin": "销售毛利率（最新报告期）",
    "annual_roe": "净资产收益率（年报）",
    "annual_gross_margin": "销售毛利率（年报）",
    "revenue_growth": "营收同比",
    "net_profit_growth": "净利润同比",
    "net_profit": "净利润",
    "eps": "每股收益",
    "bps": "每股净资产",
    "ocf_per_share": "每股经营现金流",
    "total_market_cap": "总市值",
    "dividend_yield": "股息率",
    "dividend_per_10": "每 10 股派息",
    # 趋势面（同花顺榜单）。行情快照降级到新浪之后，60 日涨跌与换手率在库里
    # 覆盖率是 0——东财那两条能给区间涨跌的路都被挡着，所以趋势只能走榜单。
    "rising_days": "量价齐升天数",
    "stage_gain": "阶段涨幅（量价齐升那一段）",
    "stage_turnover": "累计换手率（量价齐升那一段）",
    "above_ma60": "站上 60 日均线（1＝是）",
    "new_high_level": "新高档位（1 月／2 半年／3 一年／4 历史）",
    "volume_days": "持续放量天数",
    "turnover_rate": "换手率",
}

# 趋势类字段。策略按它判定自己是价值口味还是趋势口味——
# 而不是靠人在两处各维护一份名单（那种名单迟早对不上）。
TREND_FIELDS = frozenset({
    "rising_days", "stage_gain", "stage_turnover",
    "above_ma60", "new_high_level", "volume_days", "turnover_rate",
})
# 派生字段的标签与口径统一来自算子表
FIELD_LABELS.update({key: f"{op.label}（{op.formula}）" for key, op in OPERATORS_BY_KEY.items() if key in
                     ("cash_ratio", "peg", "graham_number", "earnings_yield", "pb_over_roe")})

OPERATOR_TEXT = {"gte": "≥", "lte": "≤", "gt": ">", "lt": "<"}

# **门槛的口径必须与字段的口径对上。**
#
# 底座里的 roe / gross_margin 来自「最新报告期」，眼下是一季报——单季数字，中位数 1.03%。
# 而「ROE ≥ 15%」这种门槛写的是年度概念。两者一比，全市场只有 124 只能过，
# 「质量稳健型」于是长期几乎筛不出东西。而这看上去像「条件严格」而不像「口径错了」，
# 所以一直没被发现。换成年报口径后，同一条件命中 1790 只。
#
# 结论：凡是年度概念的门槛，字段一律用 annual_ 前缀那一支。


# 比率不在这里算：算子表是唯一定义处，策略只挑用哪几个。
# 以前这里各写一份，同一个 PEG 在候选清单和初筛里可能算得不一样，还没人发现。
DERIVED: dict[str, Callable[[dict[str, Any]], float | None]] = {
    key: (lambda row, _key=key: operator_compute(_key, row)["value"])
    for key in ("cash_ratio", "peg", "graham_number", "earnings_yield", "pb_over_roe")
}


@dataclass(frozen=True)
class Rule:
    field: str
    op: str
    value: float
    unit: str = ""

    @property
    def label(self) -> str:
        return FIELD_LABELS.get(self.field, self.field)

    @property
    def text(self) -> str:
        return f"{self.label} {OPERATOR_TEXT[self.op]} {self.value:g}{self.unit}"


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    summary: str
    provenance: str
    biases: tuple[str, ...]
    rules: tuple[Rule, ...]
    sort_field: str
    sort_desc: bool
    sort_label: str
    available: bool = True
    unavailable_reason: str | None = None
    extra_fields: tuple[str, ...] = field(default=())

    @property
    def kind(self) -> str:
        """价值口味还是趋势口味。**从规则用的字段推出来，不另外维护一份名单。**

        两处各写一份的话迟早对不上：加了一套新策略、名单忘了改，它就会被
        算进错误的那个池子里，而表现只是"这个池子里怎么混进来一只奇怪的票"。
        """
        return "trend" if any(rule.field in TREND_FIELDS for rule in self.rules) else "value"

    @property
    def required_fields(self) -> tuple[str, ...]:
        fields: list[str] = list(self.extra_fields)
        for rule in self.rules:
            if rule.field in DERIVED:
                fields.extend({"cash_ratio": ("eps", "ocf_per_share"), "peg": ("pe_ttm", "net_profit_growth"), "graham_number": ("pe_ttm", "pb")}[rule.field])
            else:
                fields.append(rule.field)
        if self.sort_field not in DERIVED:
            fields.append(self.sort_field)
        return tuple(dict.fromkeys(fields))


PRESETS: tuple[Strategy, ...] = (
    Strategy(
        key="undervalued_defensive",
        name="低估防御型",
        summary="价格相对账面与盈利都不贵，且当期确实盈利。",
        provenance="格雷厄姆《聪明的投资者》防御型投资者的估值标准（PE 与 PB 的乘积上限）。",
        biases=(
            "周期股在利润最高点时 PE 最低，这套条件会在周期顶部把它们推给你。",
            "只看当期估值，不判断盈利能否持续；盈利下滑会让今天的低 PE 明天变高。",
            "资产负债率不在全市场底座里，这套条件没有负债约束，建档后需要在定期报告里自己确认。",
        ),
        rules=(
            Rule("pe_ttm", "lte", 15),
            Rule("pb", "lte", 1.5),
            Rule("graham_number", "lte", 22.5),
            Rule("net_profit", "gt", 0),
            Rule("total_market_cap", "gte", 5_000_000_000, " 元"),
        ),
        sort_field="graham_number",
        sort_desc=False,
        sort_label="PE × PB 由低到高",
    ),
    Strategy(
        key="quality_steady",
        name="质量稳健型",
        summary="生意本身赚钱，而且赚到的是现金。",
        provenance="以高 ROE、高毛利率与经营现金流对利润的覆盖度为核心的质量投资常见做法。",
        biases=(
            "偏好轻资产生意，会系统性漏掉重资产的好公司。",
            "ROE 高也可能是高杠杆撑起来的；底座里没有负债率，这一层要在建档后自己确认。",
            "现金含量用每股经营现金流除以每股收益近似，一次性损益会让它失真。",
        ),
        rules=(
            Rule("annual_roe", "gte", 15, "%"),
            Rule("annual_gross_margin", "gte", 30, "%"),
            Rule("cash_ratio", "gte", 80, "%"),
            Rule("total_market_cap", "gte", 10_000_000_000, " 元"),
        ),
        sort_field="annual_roe",
        sort_desc=True,
        sort_label="净资产收益率（年报）由高到低",
    ),
    Strategy(
        key="improving_operations",
        name="经营改善型",
        summary="最新报告期里收入、利润与经营现金流同时在好转。",
        provenance="借鉴 Piotroski F-Score 关注变化方向的思路，但只用了其中可从全市场业绩报表得到的几项，是简化版而不是 F-Score 本身。",
        biases=(
            "只看变化方向，不看起点；从很差改善到不太差也会入选。",
            "单期高增长常来自低基数或一次性收益，需要回看多期才能判断。",
            "完整的 F-Score 有九项且需要两年数据，这里只覆盖其中一部分。",
        ),
        rules=(
            Rule("net_profit_growth", "gte", 20, "%"),
            Rule("revenue_growth", "gte", 10, "%"),
            Rule("annual_roe", "gte", 8, "%"),
            Rule("ocf_per_share", "gt", 0),
        ),
        sort_field="net_profit_growth",
        sort_desc=True,
        sort_label="净利润同比由高到低",
    ),
    Strategy(
        key="quality_growth",
        name="质量成长型",
        summary="增长与估值都不极端，用 PEG 平衡两者。",
        provenance="GARP（Growth at a Reasonable Price）的常见量化表达。",
        biases=(
            "PEG 用单期增速计算，对增长的持续性无能为力，最容易在增长拐点买在高位。",
            "高增长公司常伴随高估值，这套条件会偏向增长刚起步或刚被压估值的阶段。",
        ),
        rules=(
            Rule("net_profit_growth", "gte", 20, "%"),
            Rule("annual_roe", "gte", 12, "%"),
            Rule("pe_ttm", "lte", 30),
            Rule("peg", "lte", 1),
        ),
        sort_field="peg",
        sort_desc=False,
        sort_label="PEG 由低到高",
    ),
    Strategy(
        key="dividend_cashflow",
        name="股息现金流型",
        summary="现金回报稳定且派息可持续。",
        provenance="以股息率与派息可持续性为核心的收益型选股。",
        biases=(
            "高股息常常是股价下跌造成的假象——分子没变，分母变小了。看到高股息率先去看股价走势。",
            "一次性大额分红会污染信号；底座里只有最近一个年度期的派息，看不出它连续派了几年。",
            "股息率按年报期计算，与当前股价存在时间差；分红方案公布后股价变动越大，这个数越不准。",
            "分红能力来自现金流，不是来自利润。这里用经营现金流对每股收益的覆盖度做了一层约束，"
            "但它替代不了看现金流量表。",
        ),
        rules=(
            Rule("dividend_yield", "gte", 3, "%"),
            # 派息要发得出来：光有高股息率而现金流撑不住，就是在借钱分红。
            Rule("cash_ratio", "gte", 70, "%"),
            Rule("annual_roe", "gte", 8, "%"),
            Rule("net_profit", "gt", 0),
            Rule("total_market_cap", "gte", 5_000_000_000, " 元"),
        ),
        sort_field="dividend_yield",
        sort_desc=True,
        sort_label="股息率由高到低",
    ),

    # ---------------------------------------------------------------- 趋势口味
    #
    # **这三套跟上面五套不是一类东西，别把它们混在一个池子里打分。**
    #
    # 价值和动量在构造上是负相关的：一只票涨了一波，PE 就上去了，上面五套
    # 没有一套还会选中它。把价值分和动量分平均，选出来的是"两边都平庸"的票。
    # 学术上（Asness/Moskowitz/Pedersen 那套）的做法也是两条腿分开跑，
    # 不是混成一个分。所以荐股池按口味分池子，不是在一个池子里调权重。
    #
    # 数据来自同花顺的榜单，不是连续指标。窗口每只票都不一样（是它自己那段
    # 量价齐升持续了几天），当排序用可以，**当收益率读就错了**。

    Strategy(
        key="trend_breakout",
        name="趋势突破型",
        summary="站上中期均线，而且是带着量涨上去的。",
        provenance="趋势跟随的常见表达：中期均线之上 + 量价配合。数据取自同花顺的"
                   "「向上突破 60 日均线」与「量价齐升」两个榜单。",
        biases=(
            "**榜单是事后的**。你看到它的时候，那段涨幅已经发生了——这套条件筛出来的"
            "永远是「已经涨过的」，不是「要涨的」。",
            "动量最怕拐点：反转来的时候，涨得最好的那一批跌得最猛，而且没有预兆。",
            "**A 股的短期反转效应比动量效应更明显**，这是和美股很不一样的地方。"
            "这套条件在 A 股上的历史表现，比同样的规则在美股上要弱。",
            "没有任何基本面约束（只挡掉了亏损的）。榜单上会有纯题材炒作和被游资拉起来的票。",
            "阶段涨幅的统计窗口每只票不一样，两只票的阶段涨幅严格来说不可直接比。",
            "高换手意味着高交易成本，而这份清单默认你会频繁换手——那和本站"
            "「长期研究」的定位是拧着的，用它之前先想清楚这一点。",
        ),
        rules=(
            Rule("above_ma60", "gte", 1),
            Rule("rising_days", "gte", 3, " 天"),
            Rule("stage_gain", "gte", 5, "%"),
            # 只挡掉亏损的。再多的基本面约束会把趋势口味重新变成价值口味。
            Rule("net_profit", "gt", 0),
        ),
        sort_field="stage_gain",
        sort_desc=True,
        sort_label="阶段涨幅由高到低",
    ),
    Strategy(
        key="trend_volume",
        name="量价齐升型",
        summary="连续多天量和价一起上，换手也确实起来了。",
        provenance="同花顺「量价齐升」与「持续放量」榜单。量在价先是技术分析里"
                   "流传最广的说法之一，但**它没有可靠的统计支持**，"
                   "这里只把它当作一个筛选口径，不当作规律。",
        biases=(
            "「放量上涨」同样可能是有人在出货——成交量本身不告诉你是谁在买谁在卖。",
            "连续放量的票已经被充分关注，接手的成本比几天前高得多。",
            "累计换手率高说明筹码换了好几轮，短期波动会比平时大。",
            "榜单是当日快照，明天就换一批。今天在榜上不代表明天还在。",
            "同样没有基本面约束，只挡掉了亏损与微型市值。",
        ),
        rules=(
            Rule("rising_days", "gte", 4, " 天"),
            Rule("stage_turnover", "gte", 15, "%"),
            Rule("net_profit", "gt", 0),
            Rule("total_market_cap", "gte", 3_000_000_000, " 元"),
        ),
        sort_field="rising_days",
        sort_desc=True,
        sort_label="量价齐升天数由多到少",
    ),
    Strategy(
        key="trend_new_high",
        name="创新高型",
        summary="价格创出阶段新高，而且还站在中期均线上。",
        provenance="创新高是最朴素的强势定义：没有套牢盘在上方。"
                   "数据取自同花顺「创新高」榜单的四个档位。",
        biases=(
            "**这是全站偏差最大的一套。** 创新高意味着买在历史最高的位置上，"
            "判断错了没有任何前人的成本可以作为参照。",
            "创月新高实测有 387 只，创一年新高只有 17 只——档位放宽一点，"
            "「新高」这个词的分量就完全不同了，别只看名字。",
            "新高之后回落是常态，不是异常。",
            "同样没有基本面约束，只挡掉了亏损与微型市值。",
        ),
        rules=(
            Rule("new_high_level", "gte", 1),
            Rule("above_ma60", "gte", 1),
            Rule("net_profit", "gt", 0),
            Rule("total_market_cap", "gte", 3_000_000_000, " 元"),
        ),
        sort_field="new_high_level",
        sort_desc=True,
        sort_label="新高档位由高到低",
    ),
)

PRESETS_BY_KEY = {strategy.key: strategy for strategy in PRESETS}


def value_of(row: dict[str, Any], field_name: str) -> float | None:
    if field_name in DERIVED:
        return DERIVED[field_name](row)
    value = row.get(field_name)
    return None if value is None else float(value)


def check_rule(row: dict[str, Any], rule: Rule) -> dict[str, Any]:
    actual = value_of(row, rule.field)
    if actual is None:
        return {"rule": rule.text, "field": rule.field, "label": rule.label, "actual": None, "passed": False, "missing": True}
    passed = {
        "gte": actual >= rule.value,
        "lte": actual <= rule.value,
        "gt": actual > rule.value,
        "lt": actual < rule.value,
    }[rule.op]
    return {"rule": rule.text, "field": rule.field, "label": rule.label, "actual": round(actual, 4), "passed": passed, "missing": False}
