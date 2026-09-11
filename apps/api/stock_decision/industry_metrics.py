"""行业特有指标：这门生意该盯的那几个数。

## 为什么通用指标不够

ROE、毛利率、负债率对任何公司都能算，也因此对任何公司都说不出多少东西。
真正能分辨一门生意好坏的数，往往只在这个行业里成立：

- **白酒看合同负债。** 经销商愿不愿意提前打款，比这个季度的报表收入
  领先一整个周期——收入是酒厂决定发多少货，合同负债是渠道愿意压多少钱。
- **银行看净息差和拨贷比。** 银行的"毛利率"没有意义（它的成本是利息支出），
  该看的是每一块钱资产赚多少利差，以及为坏账准备了多少。
- **地产看合同负债覆盖倍数和存货周转。** 报表收入是几年前卖的房子结转的，
  跟今年卖得好不好没关系；已售未结转才是未来收入的锁定度。

看着 ROE 买白酒，和看着合同负债买白酒，是两种完全不同的研究。

## 全部由代码算，每个数都摆出原料

每一条指标都写清楚：**用了哪两个科目、公式是什么、算出来多少**。
点开就能对着年报核。模型不参与——一个编出来的"净息差 2.1%"
跟真的长得一模一样，而你会拿它去做判断。

## 只用年报

流量科目（营业收入、销售商品收到的现金）在新浪的报表里是**累计口径**：
一季报是 Q1，中报是 H1，三季报是前三季。拿存量科目（合同负债是时点数）
去除以累计口径，一季度得出来的比值天然是年报的四倍——那不是"渠道打款变强了"，
那是日历。所以凡是涉及流量的指标一律**只取年报**，跟分部构成同一条规矩。

## 行业对不上就说对不上

一家公司的行业分类如果没同步到，或者它所在的行业这里还没定义过指标，
就明说「这个行业还没有专属指标」，**不要退回去算一遍通用指标然后假装是特有的**。
"""

from __future__ import annotations

from typing import Any

# 至少要有这么多期年报才画趋势。**两期连不成趋势**，
# 而两个点画出来的线看着跟趋势一模一样。
MIN_PERIODS_FOR_TREND = 3


class Metric:
    """一条指标：怎么算、为什么要看它、往哪个方向算好。

    `good` 只用来在页面上给一个方向提示，**不参与任何打分**——
    合同负债涨是好事，但涨到离谱就是压货，方向本身说明不了对错。
    """

    def __init__(self, key: str, label: str, unit: str, inputs: tuple[str, ...],
                 formula: str, why: str, good: str = "", annual_only: bool = True):
        self.key, self.label, self.unit = key, label, unit
        self.inputs, self.formula, self.why, self.good = inputs, formula, why, good
        self.annual_only = annual_only

    def compute(self, values: dict[str, float]) -> float | None:
        raise NotImplementedError


class Ratio(Metric):
    """两个科目相除，乘一个倍数。绝大多数指标都是这个形状。"""

    def __init__(self, key, label, unit, top, bottom, formula, why, good="",
                 scale=100.0, annual_only=True):
        super().__init__(key, label, unit, tuple(dict.fromkeys(top + bottom)),
                         formula, why, good, annual_only)
        self.top, self.bottom, self.scale = top, bottom, scale

    def compute(self, values):
        # 分子用「有哪个算哪个」：**合同负债与预收款项是同一件事的两种叫法**——
        # 2020 年新收入准则之前叫预收款项，之后改叫合同负债，
        # 同一家公司横跨两边，要求两个都在的话这条指标永远算不出来。
        #
        # 分母用「全都要有」：缺一个科目就返回 None，而不是把缺的当 0。
        # 「合同负债为 0」和「这张表上根本没有合同负债这一栏」是两件事，
        # 前者是渠道不打款，后者是银行股。
        numerator = _sum_any(values, self.top)
        denominator = _sum_all(values, self.bottom)
        if numerator is None or denominator in (None, 0):
            return None
        return round(numerator / denominator * self.scale, 2)


class Amount(Metric):
    """直接看科目本身的绝对额（换算成亿元）。"""

    def __init__(self, key, label, items, why, good="", annual_only=False):
        super().__init__(key, label, "亿元", tuple(items),
                         " + ".join(items) + " ÷ 1亿", why, good, annual_only)
        self.items = items

    def compute(self, values):
        total = _sum_any(values, self.items)
        return round(total / 1e8, 2) if total is not None else None


def _sum_all(values: dict[str, float], names: tuple[str, ...]) -> float | None:
    """全部都要有才算。少一个就是 None。"""
    got = [values.get(name) for name in names]
    return sum(got) if all(v is not None for v in got) else None


def _sum_any(values: dict[str, float], names: tuple[str, ...]) -> float | None:
    """有哪个算哪个。用于「合同负债 / 预收款项」这种同一件事的两种叫法——
    2020 年新收入准则之前叫预收款项，之后改叫合同负债，同一家公司会两个都出现过。"""
    got = [values[name] for name in names if values.get(name) is not None]
    return sum(got) if got else None


# ------------------------------------------------------------------ 指标定义

# 谁都该看的三条。放在最前面，因为它们在通用财务页上恰恰是缺的——
# 通用页给你 ROE 和毛利率，而这三条问的是"赚到的是不是真钱"。
UNIVERSAL: tuple[Metric, ...] = (
    Ratio("cash_ratio", "收现比", "%",
          ("销售商品、提供劳务收到的现金",), ("营业收入",),
          "销售商品收到的现金 ÷ 营业收入",
          "**收入是不是真的收到了钱。** 长期低于 100% 意味着收入靠赊账堆出来的，"
          "利润表好看而现金没进来；这是最早能看出问题的一个数，"
          "比应收账款周转率直接得多。含税收现通常在 110%–120% 之间。",
          good="高"),
    Ratio("upstream", "对上游的占款", "%",
          ("应付账款",), ("营业成本",),
          "应付账款 ÷ 营业成本",
          "**你能压多久上游的货款。** 这个比值高说明供应商愿意等你，"
          "是产业链地位的直接证据；配合下面的「下游预收」一起看，"
          "两头都占便宜的生意通常不需要自己掏营运资金。",
          good="高"),
    Ratio("rnd", "研发强度", "%", ("研发费用",), ("营业收入",),
          "研发费用 ÷ 营业收入",
          "研发投入占收入的比例。**它本身不分好坏**——制造业 5% 是重投入，"
          "白酒 0.1% 完全正常。要看的是同行之间的差距和自己这几年的方向。"),
)

BY_INDUSTRY: dict[str, tuple[Metric, ...]] = {
    "白酒": (
        Ratio("contract_liability", "合同负债占收入", "%",
              ("合同负债", "预收款项"), ("营业收入",),
              "（合同负债 + 预收款项）÷ 营业收入",
              "**这是白酒最领先的一个数。** 报表收入是酒厂决定发多少货，"
              "而合同负债是经销商自愿提前打进来的钱——渠道愿不愿意压款，"
              "比收入本身早一整个周期反映需求。它掉头往下的时候，"
              "收入通常还在涨。\n\n"
              "反过来也要警惕：这个数被人为做高（逼经销商打款）也是常见操作，"
              "所以要跟经销商数量、渠道库存一起看，不能单看。",
              good="高"),
        Amount("contract_amount", "合同负债余额", ("合同负债", "预收款项"),
               "绝对额。占比会被收入的分母影响，余额本身的逐年变化更直观。"),
    ),
    "银行": (
        Ratio("nim_proxy", "净利息收益率（对总资产）", "%",
              ("净利息收入",), ("总资产",),
              "净利息收入 ÷ 总资产",
              "**这是净息差的代理，不是净息差本身。** 真正的净息差分母是"
              "「生息资产平均余额」，报表上没有这一栏，年报正文里才有。"
              "这里用总资产做分母，口径偏保守（分母大一点），"
              "所以**同一家公司逐年比、以及同业之间比是有意义的，"
              "跟银行自己披露的净息差数字对不上是正常的**。",
              good="高"),
        Ratio("provision", "拨贷比", "%",
              ("减:贷款损失准备",), ("发放贷款及垫款",),
              "贷款损失准备 ÷ 发放贷款及垫款",
              "**为坏账准备了多少。** 监管底线是 2.5%。"
              "这个数突然下降，往往不是资产质量变好了，"
              "而是把拨备释放出来充当利润——那是一次性的，而且是借未来的钱。",
              good="高"),
        Ratio("fee_mix", "中间业务占比", "%",
              ("手续费及佣金净收入",), ("营业收入",),
              "手续费及佣金净收入 ÷ 营业收入",
              "不吃利差赚的钱占多少。**这部分不占用资本金**，"
              "占比高的银行在降息周期里抗打得多。"),
        Ratio("ldr", "存贷比", "%",
              ("发放贷款及垫款",), ("客户存款(吸收存款)",),
              "发放贷款及垫款 ÷ 客户存款",
              "放出去的贷款相当于存款的多少。太高说明负债端紧张、要靠同业拆借补，"
              "而同业资金比存款贵得多也不稳定。"),
    ),
    "房地产": (
        Ratio("presale_cover", "已售未结转覆盖倍数", "倍",
              ("合同负债", "预收款项"), ("营业收入",),
              "（合同负债 + 预收款项）÷ 营业收入",
              "**地产的报表收入说的是过去，不是现在。** 今年结转的是两三年前卖掉的房子，"
              "所以营业收入跟今年卖得好不好几乎无关。合同负债才是已经收了钱、"
              "还没结转成收入的部分——它相当于未来收入的锁定度。\n\n"
              "这个倍数在往下掉，意味着未来两年的收入已经被锁死了上限，"
              "而这件事在利润表上还要两年才看得见。",
              good="高", scale=1.0),
        Ratio("inventory_years", "存货周转年数", "年",
              ("存货",), ("营业成本",),
              "存货 ÷ 营业成本",
              "手里的土地和在建项目，按当前结转速度要几年才能消化完。"
              "**这个数变大不一定是坏事**（可能刚拿了地），"
              "但连续变大同时合同负债在缩，就是卖不动了。",
              good="低", scale=1.0),
    ),
    "证券": (
        Ratio("fee_mix", "手续费收入占比", "%",
              ("手续费及佣金净收入",), ("营业收入",),
              "手续费及佣金净收入 ÷ 营业收入",
              "经纪与投行这类靠牌照和客户赚的钱占多少。"
              "剩下的主要是自营——**自营是靠行情吃饭的**，"
              "占比高的券商业绩波动会大得多。"),
    ),
}

# 申万一级 → 这里定义过指标的行业名。分类口径对不上时用这张表兜一层，
# 对不上就明说对不上，**不要模糊匹配**——把「食品饮料」当成「白酒」来算，
# 得出来的合同负债结论对乳制品公司是错的。
INDUSTRY_ALIASES: dict[str, str] = {
    "白酒": "白酒", "白酒Ⅱ": "白酒", "酒类": "白酒",
    "银行": "银行", "国有大型银行Ⅱ": "银行", "股份制银行Ⅱ": "银行",
    "城商行Ⅱ": "银行", "农商行Ⅱ": "银行", "银行Ⅱ": "银行",
    "房地产": "房地产", "房地产开发": "房地产", "房地产开发Ⅱ": "房地产",
    "证券": "证券", "证券Ⅱ": "证券",
    "非银金融": "证券",
}


# 证监会门类 → （目标行业, 主营里必须出现的词之一）。**两把钥匙。**
#
# ## 为什么不能只靠证监会那个名字
#
# 上面那张表全是申万口径，而**申万分类在库里 5538 行全是空的**——
# 这个功能因此对 12 家公司一条指标都没算出来过，跟当初的承诺台账一样是死的。
# 库里实际存的是证监会门类，「酒、饮料和精制茶制造业」这种。
#
# 但这一类里同时有白酒、啤酒、饮料和茶。直接映射成「白酒」会让农夫山泉
# 也按合同负债去解读——**而错的结论跟对的长得一模一样**，这正是上面那句
# 「不许模糊匹配」要挡的事。
#
# 所以要第二把钥匙：粗分类相容**并且**主营业务里出现确切的词。
# 饮料公司的主营里不会写「白酒」，所以这一对键不可能误开。
CSRC_REFINE: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "酒、饮料和精制茶制造业": (("白酒", ("白酒", "酱香", "浓香", "基酒", "曲酒")),),
    "货币金融服务": (("银行", ("银行",)),),
    "房地产业": (("房地产", ("房地产开发", "商品房", "地产开发", "住宅开发")),),
    "资本市场服务": (("证券", ("证券经纪", "证券公司", "投资银行", "证券业务")),),
}


def resolve_industry(*candidates: str | None, hint: str = "") -> str:
    """从几个行业口径里挑出**恰好匹配**的那个。模糊的一律不认。

    hint 是这家公司的主营业务／简介／名称拼起来的一段文字，只用来给
    证监会那种粗分类当第二把钥匙——**它自己不能单独决定行业**，
    不然一句「公司参股某银行」就会把一家制造业公司算成银行。
    """
    for candidate in candidates:
        name = (candidate or "").strip()
        if name in INDUSTRY_ALIASES:
            return INDUSTRY_ALIASES[name]
    text = str(hint or "")
    if text:
        for candidate in candidates:
            name = (candidate or "").strip()
            for target, keywords in CSRC_REFINE.get(name, ()):
                if any(word in text for word in keywords):
                    return target
    return ""


# ------------------------------------------------------------------ 计算

def _period_values(period: dict[str, Any]) -> dict[str, float]:
    values = dict(period.get("items") or {})
    # 通用财务表里已有的两个科目，报表原始科目里未必单独存了，补上。
    for key, name in (("total_assets", "总资产"), ("revenue", "营业收入"),
                      ("operating_cost", "营业成本")):
        if period.get(key) is not None:
            values.setdefault(name, float(period[key]))
    return values


def analyze(industry: str, periods: list[dict[str, Any]],
            hint: str = "") -> dict[str, Any]:
    """periods 按报告期从旧到新，每期形如
    {"report_date": "2025-12-31", "items": {科目: 数}, "revenue": ..., "total_assets": ...}

    hint 是主营业务／简介／公司名拼起来的文字，给证监会那种粗分类当第二把钥匙。
    """
    resolved = resolve_industry(industry, hint=hint)
    specific = BY_INDUSTRY.get(resolved, ())
    annual = [p for p in periods if str(p.get("report_date", "")).endswith("-12-31")]

    rows: list[dict[str, Any]] = []
    for metric in UNIVERSAL + specific:
        source = annual if metric.annual_only else periods
        series = []
        for period in source:
            value = metric.compute(_period_values(period))
            if value is not None:
                series.append({"report_date": period["report_date"], "value": value})
        latest = series[-1] if series else None
        # **比较对象要选对。** 只用年报的指标跟上一份年报比；
        # 允许用季报的（合同负债这类时点数）要跟**去年同期**比——
        # 白酒的合同负债在春节后那一季天然是高点，
        # 拿一季报去比上一期年报，量出来的是日历不是生意。
        previous, compare_note = None, ""
        if latest and len(series) > 1:
            if metric.annual_only:
                previous, compare_note = series[-2], "较上一年报"
            else:
                stamp = latest["report_date"]
                same_quarter = f"{int(stamp[:4]) - 1}{stamp[4:]}"
                previous = next((p for p in series if p["report_date"] == same_quarter), None)
                compare_note = "较去年同期" if previous else ""
        rows.append({
            "key": metric.key, "label": metric.label, "unit": metric.unit,
            "scope": "行业特有" if metric in specific else "通用",
            "formula": metric.formula, "why": metric.why, "good": metric.good,
            "annual_only": metric.annual_only,
            "series": series,
            "latest": latest,
            "change": (round(latest["value"] - previous["value"], 2)
                       if latest and previous else None),
            "compare_note": compare_note,
            # 两期连不成趋势，而两个点画出来的线看着跟趋势一模一样。
            "trendable": len(series) >= MIN_PERIODS_FOR_TREND,
            "inputs": list(metric.inputs),
            # **只在算不出来的时候才说缺什么。** 算出来了还列一串"缺"，
            # 会让人以为这个数是残缺的——而它其实是完整的
            # （合同负债与预收款项本来就只会出现一个）。
            "missing": ([name for name in metric.inputs
                         if source and _period_values(source[-1]).get(name) is None]
                        if latest is None else []),
            # 这个行业的报表上根本没有这些科目（银行没有营业成本与研发费用）——
            # 那不是数据缺失，是不适用。两者要分开说。
            "applicable": latest is not None,
        })

    # 算得出来的排前面。银行的通用三条全是空的，摆在最上面会让人以为功能坏了。
    rows.sort(key=lambda r: (not r["applicable"], r["scope"] != "行业特有"))

    note = ""
    if not resolved:
        note = (f"「{industry or '未分类'}」这个行业还没有定义专属指标，"
                f"下面只有通用的那几条。**没有硬凑**——"
                f"把别的行业的指标套上来算出的数看着一样，结论却是错的。")
    elif not annual:
        note = "还没有同步到年报。涉及收入、成本的指标只用年报算（累计口径不可比），所以现在算不出来。"

    return {
        "industry": industry,
        "resolved": resolved,
        "rows": rows,
        "annual_periods": len(annual),
        "note": note,
        "boundary": (
            "这些数全部由代码从报表原始科目算出来，**每一条都写着用了哪几个科目、"
            "公式是什么**，点开就能对着年报核。模型不参与——"
            "一个编出来的「净息差 2.1%」跟真的长得一模一样，而你会拿它去做判断。\n\n"
            "涉及收入、成本的指标**只用年报**：新浪的报表是累计口径，"
            "一季报的分母只有四分之一年，比出来的差异是日历造成的，不是生意变了。\n\n"
            "方向提示（↑ 更好 / ↓ 更好）**不参与任何打分**。合同负债涨是好事，"
            "涨到离谱就是压货；方向本身说明不了对错。"
        ),
    }
