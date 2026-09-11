"""三情景估值：把「我觉得便宜」变成一个可以被证伪的命题。

## 这不是目标价

**目标价是「我预测它会到多少」，这里是「如果你的假设成立，它值多少」。**
前者是预测，后者是条件推论——而条件是你自己填的，不是模型给的。
一份估值真正的产出不是那个数字，是**你被迫把假设写出来了**：
收入能涨多快、净利率守得住多少、几年后市场愿意给多少倍。

写出来之后它们才能被证伪。这也是本站其它地方一贯的做法（反证条件、复核到期）。

## 最有用的那个数是反推出来的

三个情景是「你怎么看」。而**「现在的价格要求这家公司未来五年净利润年增多少」
是市场怎么看**——它是一个关于当前价格的事实，不含任何预测成分。

把两者摆在一起，问题就从"贵不贵"变成了一个具体的问题：
**这个隐含增速，这家公司过去五年做到过吗？**

所以这里把反推排在三情景前面。

## 假设旁边必须摆历史实际值

一个人填 25% 的增速时，往往不知道这家公司过去五年只做到 11.9%。
把实际值摆在输入框旁边，是这套东西唯一能防住自欺的地方——
比任何"温馨提示"都有用。

## 默认值不许编

三个情景的初值全部来自这家公司自己的数据：

- 收入增速：过去五年实际复合增速（基准）、最差的一年（悲观）、最好的一年（乐观）
- 净利率：过去五年的中位数 / 最低 / 最高
- 退出 PE：**这家公司自己近五年 PE 的 25 / 50 / 75 分位**

最后一条尤其要紧。退出 PE 是整套里最主观、对结果影响又最大的一个数
（五年后的价值直接乘它）。用「当前 PE × 0.7」这种乘数是我在编，
用它自己的估值历史分位则是它自己的事实。

## 折现率是你要求的回报，不是无风险利率

`discount_rate` 的含义是「这笔钱我要求每年赚多少才值得占着」。
它是个人偏好，没有正确答案，所以必须可改并且写明白——
默认 10% 只是个常见的个人投资者要求，不是推荐值。

## 算术全在这里，模型无权报数

跟深度报告、荐股池同一条铁律。模型可以建议假设并说明理由，
但每一个数都由这个模块算出来，可测、可复现。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

# 看几年。五年是个折中：短到三年，退出 PE 几乎主导结果；长到十年，
# 收入假设的复利误差会把一切淹没，而没人能对十年后的净利率有意见。
DEFAULT_YEARS = 5
# 折现率＝你要求的年化回报。个人偏好，没有正确答案，默认值不是推荐值。
DEFAULT_DISCOUNT = 10.0

# 用最近几年来设定情景。**这条是被真实数据教出来的。**
#
# 第一版用全部历史取「最差的一年 / 最好的一年」。茅台库里有 28 期年报、回到 1998 年，
# 于是乐观情景拿到 2010 年的 +58% 增速、悲观情景拿到 2001 年的 20% 净利率——
# 而它近六年增速在 -1% 到 18%、净利率稳在 47–50%。算出来的乐观每股价值 16539 元，
# 现价 1309 元。
#
# 这不是极端值该不该用的问题：**那是另一家公司**。二十年前的茅台跟现在的茅台，
# 除了名字没有多少共同点。统计口径要跟结论的口径对上——正文说的是「过去五年」，
# 那统计就该只看过去五年。
#
# 完整序列仍然全部返回（长期曲线本身是有信息的），只是不参与设定情景。
RECENT_YEARS = 5

SCENARIO_KEYS = ("bear", "base", "bull")
SCENARIO_LABELS = {"bear": "悲观", "base": "基准", "bull": "乐观"}


@dataclass(frozen=True)
class Scenario:
    key: str
    revenue_growth: float     # 收入年复合增速，%
    net_margin: float         # 净利率，%
    exit_pe: float            # 第 n 年市场愿意给的市盈率

    @property
    def label(self) -> str:
        return SCENARIO_LABELS.get(self.key, self.key)


def _percentile(ordered: list[float], ratio: float) -> float | None:
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def annual_history(periods: list[dict[str, Any]],
                   window: int = RECENT_YEARS) -> dict[str, Any]:
    """从年报里读出这家公司实际做到过什么。

    **只用年报**（报告期以 12-31 结尾）。混进季报的话增速会变成
    「一季报比上一年年报」，那是个没有意义的数，而它看起来跟年度增速一模一样。

    **统计只看最近 `window` 年**（见 RECENT_YEARS 的说明），完整序列照样返回。
    """
    annual = sorted(
        (row for row in periods
         if str(row.get("report_date", "")).endswith("-12-31")
         and row.get("revenue") and row.get("net_profit") is not None),
        key=lambda row: row["report_date"])

    years: list[dict[str, Any]] = []
    for row in annual:
        revenue = float(row["revenue"])
        profit = float(row["net_profit"])
        years.append({
            "report_date": row["report_date"],
            "revenue": revenue,
            "net_profit": profit,
            "net_margin": round(profit / revenue * 100, 2) if revenue else None,
        })

    def cagr(span: int) -> float | None:
        """span 年的收入复合增速。样本不够就返回 None，**不用更短的年数凑**——
        「三年增速」和「五年增速」在周期股上能差出一倍，标错了比没有更糟。"""
        if len(years) < span + 1:
            return None
        first, last = years[-(span + 1)]["revenue"], years[-1]["revenue"]
        if first <= 0 or last <= 0:
            return None
        return round(((last / first) ** (1 / span) - 1) * 100, 2)

    # 设定情景只看最近这几年。二十年前的同一个代码，是另一家公司。
    recent = years[-(window + 1):]
    yearly_growth: list[float] = []
    for previous, current in zip(recent, recent[1:]):
        if previous["revenue"] > 0:
            yearly_growth.append(round((current["revenue"] / previous["revenue"] - 1) * 100, 2))
    margins = [y["net_margin"] for y in recent if y["net_margin"] is not None]

    return {
        "years": years,
        "cagr_3y": cagr(3),
        "cagr_5y": cagr(5),
        "yearly_growth": yearly_growth,
        "growth_worst": min(yearly_growth) if yearly_growth else None,
        "growth_best": max(yearly_growth) if yearly_growth else None,
        "margin_median": round(statistics.median(margins), 2) if margins else None,
        "margin_low": min(margins) if margins else None,
        "margin_high": max(margins) if margins else None,
        "covered": len(years),
        # **统计窗口里实际有几期。** 引用这些高低区间的地方必须说这个数，
        # 不能说 covered——那是完整序列的长度（茅台 28 期），而高低值只统计了最近 6 期。
        # 说错样本量最伤：它恰恰是让人相信这个数字的理由。
        "window_covered": len(recent),
        "window": window,
        "window_from": recent[0]["report_date"] if recent else None,
        "stat_note": (f"增速与净利率的高低区间只统计最近 {len(recent)} 期年报"
                      f"（{recent[0]['report_date'][:4]}–{recent[-1]['report_date'][:4]}）。"
                      f"库里共有 {len(years)} 期，更早的那些是另一个时代的这家公司。"
                      if recent else ""),
    }


def pe_band(points: list[float]) -> dict[str, float | None]:
    """这家公司自己近五年 PE 的分位。

    退出 PE 是整套里最主观、影响又最大的一个数。用「当前 PE × 0.7」这种乘数
    是我在编；用它自己的估值历史分位，则是它自己的事实。
    """
    ordered = sorted(value for value in points if value is not None and value > 0)
    return {
        "p25": _percentile(ordered, 0.25),
        "p50": _percentile(ordered, 0.50),
        "p75": _percentile(ordered, 0.75),
        "covered": len(ordered),
    }


def seed(history: dict[str, Any], band: dict[str, Any],
         current_pe: float | None = None) -> list[Scenario]:
    """三个情景的初值，**全部来自这家公司自己的数据**。

    拿不到历史时返回空——宁可让页面说「先同步财报」，也不要给一组
    看起来很专业、其实是我编的默认值。那种默认值最危险：它会被当成基准。
    """
    growth_base = history.get("cagr_5y") if history.get("cagr_5y") is not None else history.get("cagr_3y")
    margin_base = history.get("margin_median")
    if growth_base is None or margin_base is None:
        return []

    pe_base = band.get("p50") or current_pe
    if not pe_base:
        return []
    pe_low = band.get("p25") or pe_base
    pe_high = band.get("p75") or pe_base

    worst = history.get("growth_worst")
    best = history.get("growth_best")
    return [
        Scenario("bear",
                 revenue_growth=worst if worst is not None else growth_base,
                 net_margin=history.get("margin_low") or margin_base,
                 exit_pe=round(float(pe_low), 1)),
        Scenario("base", revenue_growth=growth_base, net_margin=margin_base,
                 exit_pe=round(float(pe_base), 1)),
        Scenario("bull",
                 revenue_growth=best if best is not None else growth_base,
                 net_margin=history.get("margin_high") or margin_base,
                 exit_pe=round(float(pe_high), 1)),
    ]


def value_of(scenario: Scenario, base_revenue: float, shares: float,
             years: int, discount_rate: float) -> dict[str, Any]:
    """一个情景算出的每股价值。

        n 年后收入 = 现在的收入 × (1+g)^n
        n 年后净利 = 上一行 × 净利率
        n 年后市值 = 上一行 × 退出 PE
        今天的价值 = 上一行 / (1+r)^n
    """
    if base_revenue <= 0 or shares <= 0 or years <= 0:
        return {"key": scenario.key, "label": scenario.label, "per_share": None}
    future_revenue = base_revenue * (1 + scenario.revenue_growth / 100) ** years
    future_profit = future_revenue * scenario.net_margin / 100
    future_cap = future_profit * scenario.exit_pe
    present_cap = future_cap / (1 + discount_rate / 100) ** years
    return {
        "key": scenario.key,
        "label": scenario.label,
        "revenue_growth": scenario.revenue_growth,
        "net_margin": scenario.net_margin,
        "exit_pe": scenario.exit_pe,
        "future_revenue": round(future_revenue, 2),
        "future_profit": round(future_profit, 2),
        "per_share": round(present_cap / shares, 2),
    }


def implied_growth(price: float, base_revenue: float, shares: float,
                   net_margin: float, exit_pe: float,
                   years: int, discount_rate: float) -> float | None:
    """把 value_of 反过来解：**当前价格要求收入年增多少**。

    这是这一整页最有价值的一个数，因为它**不含任何预测成分**——
    它是关于当前价格的一个事实。三个情景是"你怎么看"，这个是"市场怎么看"。

    把它跟历史实际增速摆在一起，问题就从"贵不贵"变成一个具体的问题：
    这个增速，这家公司过去五年做到过吗？
    """
    if price <= 0 or base_revenue <= 0 or shares <= 0 or net_margin <= 0 or exit_pe <= 0 or years <= 0:
        return None
    needed_future_cap = price * shares * (1 + discount_rate / 100) ** years
    needed_future_revenue = needed_future_cap / exit_pe / (net_margin / 100)
    ratio = needed_future_revenue / base_revenue
    if ratio <= 0:
        return None
    return round((ratio ** (1 / years) - 1) * 100, 2)


def build(facts: dict[str, Any], scenarios: list[Scenario],
          years: int = DEFAULT_YEARS,
          discount_rate: float = DEFAULT_DISCOUNT) -> dict[str, Any]:
    """把假设、算出来的价值、反推的隐含增速和历史实际值凑成一整页。"""
    base_revenue = float(facts.get("base_revenue") or 0)
    shares = float(facts.get("shares") or 0)
    price = facts.get("price")
    history = facts.get("history") or {}

    rows = [value_of(scenario, base_revenue, shares, years, discount_rate)
            for scenario in scenarios]
    base = next((s for s in scenarios if s.key == "base"), scenarios[0] if scenarios else None)

    implied = None
    if base is not None and price:
        implied = implied_growth(float(price), base_revenue, shares,
                                 base.net_margin, base.exit_pe, years, discount_rate)

    # 隐含增速跟历史比是什么概念。**这句话才是结论**，光给一个数没人知道该怎么读。
    verdict = ""
    actual = history.get("cagr_5y") if history.get("cagr_5y") is not None else history.get("cagr_3y")
    span = "五年" if history.get("cagr_5y") is not None else "三年"
    if implied is not None and actual is not None:
        if implied <= 0:
            verdict = (f"按基准情景的净利率与退出 PE 反推，当前价格**不要求收入增长**"
                       f"（隐含 {implied:g}%）。过去{span}它实际做到 {actual:g}%。")
        elif implied > actual:
            verdict = (f"当前价格要求收入年增 **{implied:g}%**，而过去{span}它实际做到 "
                       f"**{actual:g}%**。买它等于赌它比过去更快。")
        else:
            verdict = (f"当前价格要求收入年增 **{implied:g}%**，低于它过去{span}实际做到的 "
                       f"**{actual:g}%**。前提是净利率与退出 PE 守得住。")

    # 退出 PE 单独做敏感度：它最主观，而五年后的价值直接乘它。
    sensitivity = []
    if base is not None and base_revenue > 0 and shares > 0:
        for factor, name in ((0.8, "退出 PE 低两成"), (1.0, "基准"), (1.2, "退出 PE 高两成")):
            tweaked = Scenario(base.key, base.revenue_growth, base.net_margin,
                               round(base.exit_pe * factor, 1))
            sensitivity.append({"label": name, "exit_pe": tweaked.exit_pe,
                                "per_share": value_of(tweaked, base_revenue, shares,
                                                      years, discount_rate)["per_share"]})

    return {
        "years": years,
        "discount_rate": discount_rate,
        "price": price,
        "base_revenue": base_revenue,
        "base_report_date": facts.get("base_report_date"),
        "shares": shares,
        "scenarios": rows,
        "implied_growth": implied,
        "implied_verdict": verdict,
        "history": history,
        "sensitivity": sensitivity,
        "boundary": (
            "**这不是目标价。** 目标价是「我预测它会到多少」，上面算的是"
            "「如果这些假设成立，它值多少」——而假设是你填的，不是模型给的。"
            "三个情景也**不是概率分布**，基准不等于「最可能」。"
            "整套里最主观的是退出 PE，而五年后的价值直接乘它，所以单列了敏感度。"
            "折现率是**你要求的年化回报**，不是无风险利率，改它天经地义。"
        ),
    }
