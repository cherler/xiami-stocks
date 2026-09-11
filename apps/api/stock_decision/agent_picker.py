"""综合榜 · 打底层：规则取并集，按命中数排序。

**这里没有"智能体"。** 原来叫「智能体荐股池」，那个名字是按"做完之后的样子"
起的（本文件首个 commit 的标题写着「方案第 1、2 步」），而后面几步一直没做。
它实际做的事是：五套规则取并集、排个序——没有决策、没有循环、没有工具，
同样的数据跑一百次给一模一样的答案。这个产品里配得上"智能体"的只有反方 Agent。


这一层**不调模型，不花钱**。它先把五套预置策略的命中取并集，再用一套写在明处的
规则给每一只打分排序。模型视角是后面加上去的一层，加不加它，这一层都能单独用。

## 为什么打底层必须先能单独用

先做这一层是刻意的：**如果纯规则出来的池子已经不像样，加四个模型视角也救不回来**——
那说明问题在打底规则，不在缺智能体。花钱的东西加在一个还没验证的底子上，
最后分不清是底子差还是视角差。

## 汇总为什么用代码不用模型

让模型综合几份意见，它会写出一段读起来很像样、但权重完全不透明的话。
用代码是「五套规则里几套选中了它、每一项在池子里排第几分位」——
**规则写在明处，你可以不同意并且改**。这是本仓一贯的分工：数字归代码，判断归模型。

## 分位是池子内的分位，不是全市场分位

五项里有四项算的是**在这个池子里的分位**，不是在全市场的分位。原因是这个分数的
职责就是把池子内部排出先后：池子里的每一只都已经过了规则筛，跟全市场比"都很便宜"
是废话，要比的是它们之间谁更便宜。

代价说清楚：一只票的「价格 82 分」意思是"在这批候选里比 82% 的便宜"，
**不是**"比全市场 82% 的便宜"。页面上必须这么写。

## 人气反着读

`crowding` 这一项，**人气越低分越高**。一只票被讨论得越充分，能想到的理由越可能
已经在价格里了；对着眼长期的研究者，"别人还没看见"才是稀缺的。

这是一条立场，不是一条事实——想跟着热度走的人应该把这一项的权重调成 0，
而不是指望它自己反过来。所以权重是常量、在页面上写明。

## 综合得分与机构参与度不进打分

千股千评的「综合得分」和「机构参与度」是东财自己的模型算的，口径不公开。
它们可以横向比较，但**把一个黑箱的输出乘上权重算进总分，这个总分就没法解释了**——
而"能解释"正是这一层相对模型层唯一的优势。所以只展示，不计分。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any, Callable

from .strategies import DERIVED, FIELD_LABELS, Rule, check_rule, value_of


@dataclass(frozen=True)
class Dimension:
    """一个打分项。

    `inputs` 是 (字段, 越大越好) 的列表：几个字段各算一次池内分位再取平均。
    某个字段整池都缺时它不参与平均；全都缺则这一项判为「无数据」，
    **这一项不算数**，而不是记 0 分——记 0 分等于把"没数据"当成"很差"。
    """
    key: str
    label: str
    inputs: tuple[tuple[str, bool], ...]
    reading: str
    # 这一项读的方向跟直觉是反的（分越高＝那件事越少）。页面据此挂「反」记号。
    #
    # **必须由后端显式声明，不能让前端去匹配标签里有没有「反向」两个字。**
    # 那样改一次文案记号就无声消失，而这恰恰是最不能读错的一条——
    # 同一个人气字段在价值口味里是反着读、在趋势口味里是正着读的。
    reverse: bool = False


DIMENSIONS_VALUE: tuple[Dimension, ...] = (
    Dimension(
        "consensus", "多策略共识", (),
        "五套逻辑不同的规则里，有几套同时选中了它。这是五项里最客观的一项——"
        "低估、质量、改善、成长、股息各看各的，能同时过好几套不太可能是凑巧。",
    ),
    Dimension(
        "quality", "生意质量",
        (("annual_roe", True), ("annual_gross_margin", True)),
        "年报口径的净资产收益率与毛利率。**用年报不用最新报告期**："
        "最新报告期眼下是一季报，那是单季数字，跟年度概念的门槛不是一回事。",
    ),
    Dimension(
        "price", "价格",
        (("earnings_yield", True), ("pb", False)),
        "盈利收益率（PE 的倒数）与市净率。便宜得分高，但**便宜本身不是理由**——"
        "周期股在利润最高点时最便宜。",
    ),
    Dimension(
        "cash", "现金",
        (("cash_ratio", True), ("dividend_yield", True)),
        "经营现金流对每股收益的覆盖度，以及股息率。赚到的是不是现金，"
        "以及愿不愿意分出来。",
    ),
    Dimension(
        "crowding", "人气（反向）",
        (("attention_rank", True), ("attention_index", False)),
        "**分数越高说明越没人讨论。** 人气高意味着能想到的理由多半已经在价格里了；"
        "想跟着热度走的话，换成趋势口味——那边这一项是正着读的。",
        reverse=True,
    ),
)

# 趋势口味的打分项。**跟价值那套是两把不同的尺子，不是同一套调了权重。**
#
# 最要紧的差别在人气那一项：价值口味里它是反着读的（没人讨论才好），
# 趋势口味里是正着读的（趋势得有人参与才走得起来）。同一个数、两个方向，
# 而方向由口味决定——这是一条立场，所以写在明处、不藏在系数里。
DIMENSIONS_TREND: tuple[Dimension, ...] = (
    Dimension(
        "strength", "趋势强度",
        (("stage_gain", True), ("new_high_level", True)),
        "阶段涨幅与新高档位。**注意阶段涨幅的窗口每只票都不一样**"
        "（是它自己那段量价齐升持续了几天），当排序用可以，当收益率读就错了。",
    ),
    Dimension(
        "volume", "量能配合",
        (("rising_days", True), ("stage_turnover", True), ("volume_days", True)),
        "量价齐升了几天、这段换了多少手、放量持续了几天。"
        "**放量上涨也可能是有人在出货**——成交量不告诉你是谁在买谁在卖。",
    ),
    Dimension(
        "consensus", "多策略共识", (),
        "几套趋势规则同时选中了它。突破、量价、新高各看各的一面，"
        "同时过好几套说明这段行情不是只有一个口径看得见。",
    ),
    Dimension(
        "quality", "生意质量",
        (("annual_roe", True), ("annual_gross_margin", True)),
        "趋势口味里基本面只占一小块，但**不能是零**——完全不看的话，"
        "榜单会把纯题材炒作和被拉起来的垃圾股一起送上来。",
    ),
    Dimension(
        "crowding", "人气（正向）",
        # 这里是 False：attention_rank 越小越热，越热分越高。
        # 价值那套是 True（越冷越好）。同一个字段，方向由口味决定。
        (("attention_rank", False), ("attention_index", True)),
        "**分数越高说明讨论得越热。** 跟价值口味正好相反——趋势要有人参与才走得动。"
        "代价是：热到顶点的时候这一项也最高，而那往往是最差的介入位置。",
    ),
)

# 「两边都在」的打分项。**必须显式写出来，不能从上面两套里切片拼。**
#
# 第一版就是拼的（`DIMENSIONS_VALUE[:1] + DIMENSIONS_TREND[:2] + DIMENSIONS_VALUE[1:4]`），
# 结果权重加起来是 140 不是 100。算总分时按 weight_used 归一化了，所以数字看着正常，
# 但页面上那行「总分怎么来的：共识 25% · 趋势 30% · …」印出来是一串加不到 100 的百分比。
# **不会报错，只会印错。**
#
# 这里人气那一项直接去掉：价值口味说它该反着读、趋势口味说该正着读，
# 两边都在的时候没有一个诚实的方向，那就不给它权重，而不是取个中间值假装中立。
DIMENSIONS_BOTH: tuple[Dimension, ...] = (
    Dimension("strength", "趋势强度",
              (("stage_gain", True), ("new_high_level", True)),
              DIMENSIONS_TREND[0].reading),
    Dimension("quality", "生意质量",
              (("annual_roe", True), ("annual_gross_margin", True)),
              DIMENSIONS_VALUE[1].reading),
    Dimension("price", "价格",
              (("earnings_yield", True), ("pb", False)),
              DIMENSIONS_VALUE[2].reading),
    Dimension("volume", "量能配合",
              (("rising_days", True), ("stage_turnover", True), ("volume_days", True)),
              DIMENSIONS_TREND[1].reading),
    Dimension("consensus", "多策略共识", (),
              "价值那边和趋势那边各有几套选中了它。这个口味里它天然偏低——"
              "能同时过两种逻辑的规则本来就少。"),
    Dimension("cash", "现金",
              (("cash_ratio", True), ("dividend_yield", True)),
              DIMENSIONS_VALUE[3].reading),
)

# 口味。**分池子不是分权重。**
#
# 价值和动量在构造上是负相关的：一只票涨了一波，PE 就上去了，价值规则不会再选它。
# 把价值分和动量分平均，选出来的是"两边都平庸"的票——这是混合打分的经典陷阱，
# 而它不会报错，只会安静地给你一份谁都不像的清单。
#
# 「两边都在」用的是**交集**不是平均：必须同时过一套价值规则和一套趋势规则。
# 交集是合取，平均是折中，两者完全不同——这也是这三个口味里唯一真正稀缺的一个。
STANCES: dict[str, dict[str, Any]] = {
    "value": {
        "label": "价值型",
        "kinds": ("value",),
        "dimensions": DIMENSIONS_VALUE,
        "blurb": "五套价值规则取并集。人气反着读：没人讨论的才算便宜。",
    },
    "trend": {
        "label": "趋势型",
        "kinds": ("trend",),
        "dimensions": DIMENSIONS_TREND,
        "blurb": "三套趋势规则取并集。人气正着读：趋势得有人参与才走得动。",
    },
    "both": {
        "label": "两边都在",
        "kinds": ("value", "trend"),
        "dimensions": DIMENSIONS_BOTH,
        "blurb": "既过价值规则、又过趋势规则的那些。**这是交集不是折中**，"
                 "所以通常很少——又便宜又在涨本来就是稀缺的事。",
    },
}
DEFAULT_STANCE = "value"

# 一次给几只。**从 30 改成 5，理由是处理能力不是喜好。**
#
# 个人研究的实际节奏：宽筛几千只 → 挑 10–20 只浅研究（每家 1–2 小时）→
# 再挑 3–5 只深研究（每家 5–10 小时）。每周 5–10 小时的人，一个月能真正
# 研究透 4–8 家。
#
# 而这个池子原来一次给 30 只——**4 到 7 倍的过量供给**。
# 给你 30 个处理不完的候选，跟没给是一回事：你会扫一眼，然后一个都不研究。
#
# 5 只对应「这一周浅看几家」。想看更多仍然可以调，但默认值该匹配你真实的
# 处理能力，而不是显得很丰盛。
DEFAULT_LIMIT = 5

# 默认口味的打分项。测试与旧引用都指着它。
DIMENSIONS = DIMENSIONS_VALUE

# 情绪面里只展示、不计分的几个数。理由见模块头：黑箱输出不进总分。
CONTEXT_FIELDS = (
    ("comment_score", "综合得分", "东财自己的模型算的，口径不公开"),
    ("institution_participation", "机构参与度", "东财估算的机构交易占比，%"),
    ("main_cost", "主力成本", "东财估算的主力持仓成本，元"),
    ("xq_followers", "雪球关注", "关注人数，绝对量"),
    ("rank_change", "人气排名变化", "正数=比上期更受关注"),
)

# 打分要有意义，池子不能太小：三只票之间算分位，第一名永远 100 分、
# 最后一名永远 0 分，那不是分位是座次。
#
# **池子太小时不是"数据不足"。** 第一版把这两件事混在一起：不够排分位 →
# 每一项都算不出来 → 覆盖度掉到 15% → 判定"数据不足、不给总分"，
# 于是三只票的池子整页都是灰扑扑的「数据不足」卡片，**而六项数据全都是有的**，
# 缺的只是可比的同类。看起来像功能坏了，其实清单本身完全可用。
#
# 「两边都在」最容易撞上：它今天 40 只，冷清的一天很可能只剩个位数。
# 现在的做法是照实说「池子只有 N 只，排不出分位」，并把原始值列出来。
MIN_POOL_FOR_PERCENTILE = 5

# 至少要有这么多权重的项算得出来，才给总分。
#
# **不设这条线会出一个很难发现的错。** 缺项的权重是从分母里拿掉的（这是对的，
# 见下），但拿掉得只剩一项时，那一项自己就成了总分——一家除了「被两套规则选中」
# 之外什么数据都没有的公司，consensus 拿 100，总分就是 100，**排在池子第一**。
# 它看上去跟一家五项全优的公司一模一样，区别只写在一行小字的覆盖度里。
#
# 50 的意思是：一半以上的权重得有数据，否则宁可不给分、排到最后、明说数据不足。
# 六个维度里至少要有几项有数据，这一行才算说得上话。
#
# **原来这里是「至少覆盖 50% 的权重」。** 权重本身就是那个拍脑袋的判断
# （趋势强度该占 25% 还是 20% 没有依据），拿它衡量"数据够不够"是把同一个
# 主观判断又用了一遍。改成数个数：六项里有三项，就是一半。
MIN_DIMENSIONS_COVERED = 3


def _earnings_yield(row: dict[str, Any]) -> float | None:
    """盈利收益率 = 1 / PE。

    **用倒数不直接用 PE**：PE 是"越小越好"且分布长尾（几千倍的 PE 一堆），
    取分位时那条长尾会把所有正常估值压成一小段。倒数把它拉回线性，
    而且亏损股的负 PE 在倒数里自然变成负数，排在最后，不用特判。
    """
    pe = row.get("pe_ttm")
    if pe is None or pe == 0:
        return None
    return round(100.0 / float(pe), 4)


# 池子打分要用、但底座里没有直接存的字段。
# 派生比率一律走算子表（DERIVED），不在这里另写一份——同一个 cash_ratio
# 在候选清单和荐股池里算得不一样而没人发现，是这个仓库出过的事。
EXTRA_FIELDS: dict[str, Callable[[dict[str, Any]], float | None]] = {
    "earnings_yield": _earnings_yield,
}


def field_value(row: dict[str, Any], name: str) -> float | None:
    if name in EXTRA_FIELDS:
        return EXTRA_FIELDS[name](row)
    if name in DERIVED:
        return DERIVED[name](row)
    value = row.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(ordered: list[float], value: float, bigger_is_better: bool) -> float:
    """value 在这批数里排第几分位，0–100。**`ordered` 必须是已排好序的升序列表。**

    用「比它差的占比」而不是名次除以总数：并列的值会拿到同一个分数，
    而按名次排的话并列里谁在前面完全取决于排序是否稳定——那是实现细节，
    不该变成分数差。并列的取区间中点，避免并列一大片时全部拿满分或全部拿零分。

    ## 为什么要求先排序

    第一版是线性扫两遍，而且参数名叫 `sorted_values` 却**根本没排序**——
    既是个陷阱（照名字用 bisect 会静静算错），也让整个打分变成 O(n²)：
    实测并集 200 只跑 0.01 秒，4000 只要 3.00 秒。今天的价值池 668 只没事，
    但用户自己配一套宽条件（比如「净利润 > 0」）并集就是四五千。

    现在每列只排一次序，这里用二分拿到 lo/hi，O(log n)。结果与线性扫完全一致。
    """
    total = len(ordered)
    if total == 0:
        return 0.0
    lo = bisect_left(ordered, value)          # 严格小于 value 的个数
    hi = bisect_right(ordered, value)         # 小于等于 value 的个数
    worse = lo if bigger_is_better else total - hi
    same = hi - lo
    return round((worse + same / 2) / total * 100, 1)


def strategies_for(strategies: list[dict[str, Any]], stance: str) -> list[dict[str, Any]]:
    """这个口味该用哪几套规则。

    口味按 `kind` 挑，而 `kind` 是从规则用的字段推出来的（见 Strategy.kind）——
    不另外维护一份名单，那种名单迟早跟策略库对不上。
    """
    kinds = STANCES[stance]["kinds"]
    return [s for s in strategies
            if s.get("available") and s.get("rules") and s.get("kind", "value") in kinds]


def union_screen(rows: list[dict[str, Any]], strategies: list[dict[str, Any]],
                 require_all_kinds: bool = False) -> list[dict[str, Any]]:
    """规则各筛一遍，取并集。

    **取并集不取交集。** 交集是"每一套都同意的"，那会剩下极少数几只，而且系统性偏向
    某一类公司（同时又便宜、又高质量、又在改善、又高增长、又高股息的，多半是刚被
    错杀的周期股）。并集保留分歧，命中几套则记下来交给 consensus 那一项去打分。

    `require_all_kinds` 是「两边都在」那个口味用的：只留下**同时**命中价值规则
    和趋势规则的。注意这里的交集是**跨口味**的（既便宜又在涨），不是同口味内部
    的交集——后者才是上面说的那种会把清单筛没的做法。
    """
    usable = [s for s in strategies if s.get("available") and s.get("rules")]
    pool: dict[str, dict[str, Any]] = {}
    for strategy in usable:
        rules = [Rule(field=item["field"], op=item["op"], value=float(item["value"]),
                      unit=item.get("unit", "")) for item in strategy["rules"]]
        for row in rows:
            checks = [check_rule(row, rule) for rule in rules]
            if not checks or not all(check["passed"] for check in checks):
                continue
            entry = pool.setdefault(row["symbol"],
                                    {"row": row, "matched": [], "checks": {}, "kinds": set()})
            entry["matched"].append(strategy["name"])
            entry["checks"][strategy["name"]] = checks
            entry["kinds"].add(strategy.get("kind", "value"))
    entries = list(pool.values())
    if require_all_kinds:
        entries = [e for e in entries if {"value", "trend"} <= e["kinds"]]
    return entries


def _score_one(entry: dict[str, Any], columns: dict[str, list[float]],
               strategy_total: int, sentiment: dict[str, Any],
               dimensions: tuple[Dimension, ...], ranked: bool) -> dict[str, Any]:
    row = {**entry["row"], **sentiment}
    scores: list[dict[str, Any]] = []
    missing: list[str] = []
    covered = 0

    for dimension in dimensions:
        if dimension.key == "consensus":
            hits = len(entry["matched"])
            value = round(hits / strategy_total * 100, 1) if strategy_total else None
            detail = f"{hits}/{strategy_total} 套选中"
            has_data = value is not None
        else:
            parts: list[float] = []
            labels: list[str] = []
            for name, bigger_is_better in dimension.inputs:
                raw = field_value(row, name)
                if raw is None:
                    continue
                # **原始值先记下来，跟能不能排分位无关。** 排不出分位的时候，
                # 这几个数就是这张卡上仅有的信息——丢掉它等于把一张能读的卡变成空卡。
                labels.append(f"{FIELD_LABELS.get(name, name)} {raw:g}")
                series = columns.get(name) or []
                if len(series) >= MIN_POOL_FOR_PERCENTILE:
                    parts.append(percentile(series, raw, bigger_is_better))
            has_data = bool(labels)
            value = round(sum(parts) / len(parts), 1) if parts else None
            detail = "、".join(labels) if labels else "这几个字段都没有值"

        # **区分「没数据」和「排不出分位」。** 前者是这家公司的问题，
        # 后者是池子太小——两件事该说的话完全不同，混成一句就是在误导。
        if not has_data:
            missing.append(dimension.label)
        if value is not None:
            covered += 1
        scores.append({"key": dimension.key, "label": dimension.label,
                       "score": value, "detail": detail,
                       "reverse": dimension.reverse})

    # 缺项的权重从分母里拿掉，而不是记 0 分——记 0 分等于把「没数据」当成「很差」，
    # 而缺数据最常见的原因是这家公司刚上市或刚换过会计口径，跟好坏无关。
    # 但拿掉太多就不给分了（见 MIN_WEIGHT_COVERED）：只剩一项时那一项就是总分，
    # 一家什么数据都没有的公司会排在池子第一。
    # **总分取消了。**
    #
    # 原来这里把六个维度按 25/20/15/15/15/10 加权求和成一个 0–100 的分。
    # 页面自己都得写一句「权重写在代码里，不同意就改，别把它当成一个客观评分」——
    # 而那句话恰恰说明它不该存在：**一个需要免责声明的分数，就是不该给的分数。**
    #
    # 「趋势强度该占 25% 还是 20%」没有任何依据。而合成之后，
    # 一个拍脑袋的权重会让两只完全不同的票得出 71.3 和 70.8，
    # 看起来像"前者更好"，其实那 0.5 分是我瞎定的。
    #
    # 留下的是可数的事实：命中了几套规则、每个维度各自的分位。
    # 排序改用「命中规则数」——那是数出来的，不是拍出来的。
    enough = ranked and covered >= MIN_DIMENSIONS_COVERED
    _ = enough  # 覆盖度仍然用来决定要不要给分位说明，见 coverage
    return {
        "symbol": entry["row"]["symbol"],
        "name": entry["row"]["name"],
        "board": entry["row"].get("board"),
        "industry": entry["row"].get("industry"),
        "price": entry["row"].get("price"),
        "total_market_cap": entry["row"].get("total_market_cap"),
        "in_research_pool": entry["row"].get("in_research_pool", False),
        "matched": entry["matched"],
        "checks": entry["checks"],
        "scores": scores,
        # total 不再返回。**一个需要免责声明的分数，就是不该给的分数**——
        # 页面原来必须写「权重写在代码里，不同意就改，别把它当成一个客观评分」，
        # 那句话本身就说明它不该存在。各维度的分位照旧给（那是可比的），
        # 只是不再合成一个"71.3 比 70.8 好"的假区分度。
        "missing": missing,
        "dimensions_covered": covered,
        # 排不出分位时不说"数据不足"——那是在指责数据，而问题在样本量。
        "unranked": not ranked,
        "coverage": (
            f"{len(dimensions) - len(missing)}/{len(dimensions)} 项有数据"
            + ("" if ranked else "，但池子太小、排不出分位")
            + ("" if enough or not ranked else
               f"，不足 {MIN_DIMENSIONS_COVERED} 项，这几个分位别太当真")),
        "context": [
            {"key": key, "label": label, "value": sentiment.get(key), "note": note}
            for key, label, note in CONTEXT_FIELDS if sentiment.get(key) is not None
        ],
        "attention_rank": sentiment.get("attention_rank"),
        "sentiment_as_of": sentiment.get("trade_date"),
    }


def build_pool(rows: list[dict[str, Any]], strategies: list[dict[str, Any]],
               sentiment: dict[str, dict[str, Any]], limit: int = DEFAULT_LIMIT,
               stance: str = DEFAULT_STANCE) -> dict[str, Any]:
    """规则打底 + 代码打分，出一份排好序的池子。全程不调模型。

    `stance` 决定用哪几套规则打底、用哪把尺子打分。**价值和趋势是两个池子，
    不是一个池子里的两组权重**——把两种分数平均，选出来的是"两边都平庸"的票。
    """
    if stance not in STANCES:
        raise ValueError(f"没有这个口味：{stance}")
    spec = STANCES[stance]
    dimensions: tuple[Dimension, ...] = spec["dimensions"]
    usable = strategies_for(strategies, stance)
    entries = union_screen(rows, usable, require_all_kinds=(stance == "both"))

    # 分位的样本是**整个并集**，不是截断后的前 N 名：先截断再算分位，
    # 分数就会随 limit 变化——同一只票看 30 只时 60 分、看 50 只时 45 分，
    # 而它自己什么都没变。
    columns: dict[str, list[float]] = {}
    for dimension in dimensions:
        for name, _ in dimension.inputs:
            series = []
            for entry in entries:
                merged = {**entry["row"], **sentiment.get(entry["row"]["symbol"], {})}
                value = field_value(merged, name)
                if value is not None:
                    series.append(value)
            # 每列只排一次序，下面每一行都靠二分取分位（见 percentile 的说明）。
            columns[name] = sorted(series)

    # 池子太小就排不出分位。**这不是"数据不足"**，是没有可比的同类——
    # 两件事该说的话完全不同，而第一版把它们混成了一句。
    ranked = len(entries) >= MIN_POOL_FOR_PERCENTILE
    scored = [_score_one(entry, columns, len(usable),
                         sentiment.get(entry["row"]["symbol"], {}), dimensions, ranked)
              for entry in entries]
    # 没分的排最后：它们不是"分低"，是"算不出来"，混在中间会被当成中等。
    # **按「命中了几套规则」排，不按总分排。**
    #
    # 命中数是数出来的：这只票同时过了几套互不相同的规则。
    # 同样命中数的几只之间**没有客观先后**——所以按代码排，
    # 并在页面上说清楚"同一档里的顺序不代表优劣"。
    # 编一个小数点后一位的分来打破平局，是在制造一个不存在的区分度。
    scored.sort(key=lambda item: (-len(item.get("matched") or []), item["symbol"]))

    with_sentiment = sum(1 for item in scored if item["attention_rank"] is not None)
    top = scored[:limit]

    # 行业分布要跟着结果一起给出来。
    #
    # **这不是装饰，是这份清单最该被质疑的地方。** 价值类规则天然把银行、保险、
    # 公用事业推到前面——它们 PE 低、股息高、现金流稳，是规则的结构性偏好，
    # 不是"今年银行特别好"。实测前十里有五家银行保险。
    # 只给一份排好序的清单而不给分布，读的人会把这个偏好当成一个发现。
    counts: dict[str, int] = {}
    for item in top:
        counts[item["industry"] or "未标注"] = counts.get(item["industry"] or "未标注", 0) + 1
    industries = sorted(({"name": name, "count": count} for name, count in counts.items()),
                        key=lambda x: (-x["count"], x["name"]))
    # **只看第一名不够。** 申万把银行和保险分成两个二级行业（银行Ⅱ / 保险Ⅱ），
    # 于是"前十里五家银行保险"在单看第一名时只是 2/10，什么都不触发——
    # 而那恰恰是这份清单最明显的扎堆。所以再看一眼前三名合起来占多少。
    top_share = round(industries[0]["count"] / len(top) * 100) if top else 0
    head = industries[:3]
    head_share = round(sum(i["count"] for i in head) / len(top) * 100) if top else 0
    single = f"有 {industries[0]['count']} 只是{industries[0]['name']}（{top_share}%）" if top else ""
    cluster = (f"前三个行业（{('、').join(i['name'] for i in head)}）就占了 {head_share}%"
               if top and len(industries) > 1 else "")
    # 顺序有讲究：一个行业就过半时说那一个（说"前三个"会把它说小了）；
    # 否则优先说前三名合起来——那句话涵盖的信息更多，也正是单看第一名会漏掉的那种扎堆。
    if top and top_share >= 50:
        where = single
    elif cluster and head_share >= 60:
        where = cluster
    elif top and top_share >= 30:
        where = single
    else:
        where = ""
    why_clustered = ("价值类规则天然偏好低 PE、高股息、现金流稳的行业"
                     if stance == "value" else
                     "趋势榜单会整片整片地扎堆——一个板块动起来，里面的票会一起上榜")
    concentration = (
        f"这 {len(top)} 只里{where}。{why_clustered}，"
        "**这是规则的结构性偏好，不是这些行业眼下特别好**。"
    ) if where else ""

    return {
        "rows": top,
        "pool_total": len(scored),
        "returned": len(top),
        # 截断了多少要说出来。不说的话一份"前几名"读起来跟"全部结果"一模一样。
        "dropped": max(0, len(scored) - len(top)),
        "capacity_note": (
            "一次只给几只是刻意的：宽筛几千只 → 浅看 10–20 家（每家 1–2 小时）→ "
            "深研 3–5 家（每家 5–10 小时），每周 5–10 小时的人一个月能真正研究透 4–8 家。"
            "**给一份你处理不完的清单，跟没给是一回事。**"),
        "strategies": [s["name"] for s in usable],
        "universe_total": len(rows),
        "with_sentiment": with_sentiment,
        "industries": industries,
        "concentration": concentration,
        "stance": stance,
        "stance_label": spec["label"],
        "ranked": ranked,
        "unranked_reason": ("" if ranked else
                            f"这个口味今天只筛出 {len(entries)} 只，不够排分位"
                            f"（至少要 {MIN_POOL_FOR_PERCENTILE} 只）。"
                            "下面列的是原始数值——**清单本身是可用的，只是没有名次**。"),
        "stances": [{"key": key, "label": item["label"], "blurb": item["blurb"]}
                    for key, item in STANCES.items()],
        "dimensions": [{"key": d.key, "label": d.label,
                        "reading": d.reading, "reverse": d.reverse} for d in dimensions],
        "note": (f"{len(usable)} 套规则在 {len(rows)} 只里"
                 + ("取交集（要同时过价值和趋势两边）" if stance == "both" else "取并集")
                 + f"，得到 {len(scored)} 只，按代码打分取前 {len(top)} 只"
                 + (f"（另有 {len(scored) - len(top)} 只没进来）" if len(scored) > len(top) else "")
                 + f"。其中 {with_sentiment} 只有情绪面数据。"),
        "boundary": (
            "这是规则筛选加代码打分的结果，**没有调用模型**，也不是推荐。"
            "分位是**在这个池子里的分位**，不是全市场分位——"
            "「趋势强度 82 分」的意思是「在这批候选里比 82% 的强」。"
            + ("人气那一项是反着读的：分越高说明越没人讨论。" if stance == "value" else "")
            + ("人气那一项是正着读的：分越高说明讨论得越热——"
               "而热到顶点往往是最差的介入位置。" if stance == "trend" else "")
            + ("趋势数据来自同花顺的当日榜单，明天就换一批；"
               "阶段涨幅的窗口每只票都不一样，当排序用可以，当收益率读就错了。"
               if stance in ("trend", "both") else "")
            + "规则和权重都写在代码里，不同意就改，别把它当成一个客观评分。"
        ),
    }

