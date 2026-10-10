"""从「我的估值」推一组价格带的建议值。

## 这个模块要接的那根断线

估值模块已经算出了悲观 / 基准 / 乐观三个每股价值，而隔壁的四段价格带
**要你从零手填四个数**。两个模块之间没有一根线 —— 于是实测结果是：
账本里 23 笔买入，「计划内 / 计划外」判定覆盖 0 笔，因为价格带没人填。
而那个指标是整套决策闭环存在的唯一理由。

## 为什么锚在「基准」，不锚在悲观或乐观

拿宁德时代 2026-09-23 那组真实数据说：

    悲观每股    68 元     （收入五年负增长 −9.7%）
    基准每股   255 元
    乐观每股  3508 元     （把历史最好的一年 +53% 复合五年）
    现价       305 元

乐观值高出现价十倍，拿它当观察区等于永远在观察区；悲观值低于现价 78%，
拿它当极端机会区等于这一格永远不会命中。**两端都不是价格带，是边界条件。**
基准值才是"如果我的假设成立，它值多少"，价格带问的正是"相对这个数便宜多少"。

## 这里的三个系数是约定，不是算出来的 —— 所以它们必须露在外面

安全边际 20%、观察区溢价 10%、极端机会区两倍安全边际，**都是人定的规矩，
不是从这家公司的数据里推出来的**。本仓的纪律是「不许编默认值」，
而那条禁的是**把编的数当成事实端上去**。这里的做法不同：

  - 每一段都把算式写在旁边（「基准 255 × (1 − 20%) = 204」），
  - 三个系数在页面上可以改，改完四段跟着重算，
  - 返回值里明写 `is_convention: True`。

一个看得见算式、改得动系数的建议值，和一个悄悄填进输入框的默认值，
不是一回事。**但它仍然是建议，不是推荐买点** —— 落库的永远是你确认过的那组。

## 时间

价格带是**一个有保质期的东西**：它由基准每股价值推出，而基准每股价值来自
某一期财报。那一期过时了，这组价格带就跟着过时 —— 而它在页面上长得跟
昨天刚定的一模一样。所以 `propose` 的返回值一定带上 `as_of` 与 `base_report_date`，
调用方必须把它们一起存下来（见 repository 的 block_stamps）。
"""

from __future__ import annotations

from typing import Any

# 安全边际：理想区比基准值低多少才动手。
# 20% 是价值投资里最常被引用的那个档位（本仓 methods.py 的「安全边际」
# 那一条也是这么说的：「只在市价明显低于区间下沿时买入，差额就是安全边际」）。
# **它是个约定**，页面上可改。
DEFAULT_SAFETY_MARGIN = 20.0
# 观察区：比基准值还贵一点，但已经值得盯着。
DEFAULT_WATCH_PREMIUM = 10.0

# 极端机会区 = 基准值 × (1 − 安全边际 × 这个倍数)。
# 两倍不是"更保守"，是**另一件事**：跌到这里通常意味着市场知道了你不知道的东西，
# 所以那一格的说明写着「必须强制重新检查基本面」，而不是「加倍买入」。
EXTREME_MULTIPLE = 2.0


def propose(per_share_base: float | None, *,
            safety_margin: float = DEFAULT_SAFETY_MARGIN,
            watch_premium: float = DEFAULT_WATCH_PREMIUM,
            as_of: str | None = None,
            base_report_date: str | None = None) -> dict[str, Any] | None:
    """按基准每股价值推四段上沿。

    `per_share_base` 取不到就返回 None —— **不退回某个"通用"倍数**。
    没有估值就没有价格带，这正是「已估值」排在「等待价格」前面的原因。
    """
    if per_share_base is None or not (per_share_base > 0):
        return None
    if not (0 <= safety_margin < 100) or not (0 <= watch_premium < 1000):
        return None

    base = float(per_share_base)
    margin = safety_margin / 100.0
    premium = watch_premium / 100.0
    extreme_margin = min(margin * EXTREME_MULTIPLE, 0.95)

    values = {
        "watch": base * (1 + premium),
        "fair": base,
        "ideal": base * (1 - margin),
        "extreme": base * (1 - extreme_margin),
    }
    formulas = {
        "watch": f"基准 {base:.2f} × (1 + {watch_premium:g}%)",
        "fair": f"基准每股价值 {base:.2f}，原样",
        "ideal": f"基准 {base:.2f} × (1 − {safety_margin:g}%)",
        "extreme": f"基准 {base:.2f} × (1 − {safety_margin:g}% × {EXTREME_MULTIPLE:g})",
    }
    means = {
        "watch": "还没到你算的价值，但已经值得盯着。",
        "fair": "跌到你自己算的价值以下了。基本面没坏的话，可以考虑第一笔小仓。",
        "ideal": f"留足了 {safety_margin:g}% 的安全边际——主要建仓区间。",
        "extreme": "明显低估。**跌到这里必须强制重新检查基本面**，不是越跌越该买。",
    }

    bands = {key: round(value, 2) for key, value in values.items()}
    # 四舍五入之后可能撞在一起（基准很小的时候）。撞了就不给建议——
    # 一组「合理区和理想区一样高」的价格带过不了 validate_bands，
    # 而它会在用户点了「用这组」之后才报错，显得像是系统坏了。
    ordered = [bands["watch"], bands["fair"], bands["ideal"], bands["extreme"]]
    if any(a <= b for a, b in zip(ordered, ordered[1:])):
        return None

    return {
        "bands": bands,
        "rows": [
            {"key": key, "value": bands[key], "formula": formulas[key], "means": means[key]}
            for key in ("watch", "fair", "ideal", "extreme")
        ],
        "per_share_base": round(base, 2),
        "safety_margin": safety_margin,
        "watch_premium": watch_premium,
        "extreme_multiple": EXTREME_MULTIPLE,
        # **这两个是这组数的保质期。** 缺了它们，一组去年的价格带
        # 跟今天刚定的在页面上长得一模一样。
        "as_of": as_of,
        "base_report_date": base_report_date,
        "is_convention": True,
        "note": ("这是**建议值，不是推荐买点**：三个系数是人定的规矩（安全边际 "
                 f"{safety_margin:g}%、观察区溢价 {watch_premium:g}%），不是从这家公司"
                 "的数据里推出来的。每一段的算式都写在旁边，系数可以改。"),
    }


PLAN_GAP_SILENT = 5.0     # 计划价离基准值 5% 以内不说：那是估值本身的误差
FAIR_GAP_SILENT = 10.0    # 合理区上沿离基准值 10% 以内不说


def gaps(per_share_base: float | None, bands: dict[str, float] | None,
         order_price: float | None, price: float | None = None) -> dict[str, float] | None:
    """几个数相对基准每股价值差多少（百分比，正数是高）。**说不说的门槛只在这里定。**

    页面上那几句（compare）和助理聊天里那一行（assistant.pre_trade_check）
    都从这里取数：同一个门槛写两处，迟早一边改了另一边没改。
    返回 None 表示没有基准值可比；某个键不在，表示那个数没填或差得不够说。
    """
    if per_share_base is None or not (per_share_base > 0):
        return None
    base = float(per_share_base)
    out: dict[str, float] = {}
    if order_price is not None and order_price > 0:
        gap = (order_price / base - 1) * 100
        if abs(gap) > PLAN_GAP_SILENT:
            out["plan"] = gap
    fair = (bands or {}).get("fair")
    if fair is not None and fair > 0:
        gap = (fair / base - 1) * 100
        if abs(gap) > FAIR_GAP_SILENT:
            out["fair"] = gap
    if price is not None and price > 0:
        out["price"] = (price / base - 1) * 100
    return out


def compare(per_share_base: float | None, bands: dict[str, float] | None,
            order_price: float | None, price: float | None = None) -> list[str]:
    """把你自己写下的几个数摆在一起，看它们对不对得上。

    **这才是"帮我省事"该长的样子**：不替你决定，只把你已经写下的两个数
    放在同一句话里。使用者的计划买入价 300 和他自己算的基准值 255
    分别躺在两个模块里，谁也不知道它们差 18%。
    """
    notes: list[str] = []
    found = gaps(per_share_base, bands, order_price, price)
    if found is None:
        return notes
    base = float(per_share_base)

    gap = found.get("plan")
    if gap is not None and gap > 0:
        notes.append(
            f"**你的计划买入价 {order_price:g} 比你自己算的基准每股价值 {base:.2f} 高 "
            f"{gap:.0f}%。** 不是说不能买——但这等于你在用比自己估值更高的价格动手，"
            "要么是估值假设保守了，要么是这一笔本来就不在计划里。两个答案对应的动作不一样。")
    elif gap is not None:
        notes.append(
            f"你的计划买入价 {order_price:g} 比基准每股价值 {base:.2f} 低 {-gap:.0f}%，"
            "留了安全边际。")

    gap = found.get("fair")
    if gap is not None:
        direction = "高" if gap > 0 else "低"
        notes.append(
            f"你写的合理区上沿 {bands['fair']:g} 比基准每股价值 {base:.2f} {direction} "
            f"{abs(gap):.0f}%。合理区的定义是「跌到你算的价值以下」，"
            "差这么多的话，两个数里有一个没跟上。")

    gap = found.get("price")
    if gap is not None:
        notes.append(f"现价 {price:g}，相对基准每股价值 {base:.2f} "
                     + (f"高 {gap:.0f}%。" if gap >= 0 else f"低 {-gap:.0f}%。"))
    return notes


def staleness(base_report_date: str | None, latest_report_date: str | None) -> str:
    """这组价格带背后的财报，是不是已经被新的一期顶掉了。

    **「在过去正确的记录数字，放在现在就是错的」** —— 使用者原话。
    价格带没有自己的有效期，它的有效期是它所依赖的那期财报的有效期。
    """
    if not base_report_date or not latest_report_date:
        return ""
    if str(latest_report_date) <= str(base_report_date):
        return ""
    return (f"**这组价格带算的时候用的是 {base_report_date} 那期财报，"
            f"而现在最新的一期已经是 {latest_report_date} 了。** "
            "回「我的估值」重算一次，再回来更新价格带。")
