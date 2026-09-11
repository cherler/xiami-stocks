"""假设漂移：把你说过的话摆回你面前。

## 这个系统唯一不可替代的能力

数据不稀缺，分析也不稀缺了。这台机器真正做得比人好的只有一件事：**它不会心软**。

你的朋友不会当面说「你三个月前说过跌破这条线就认错，它跌破了，你没走」。
你自己更不会说。而这件事恰恰只需要一台不带情绪的机器。

商业产品不做这个，是因为让用户不舒服的产品留不住用户。自用的产品可以做，
而这是它唯一的结构性优势。

## 具体查什么

估值表每次保存插一行，带着当时的股价。所以随时能算出：

> 你三个月前基准情景填的是收入年增 8%，当时股价 1309。现在改成了 14%，
> 股价涨了 23%。**这期间归档了 0 条证据、没有新的定期报告。**
> 你是看到了新东西，还是股价涨了之后你在给它找理由？

最后那半句才是重点。光说「你改了假设」没有杀伤力——**「这期间什么都没发生」
才有**。而这半句完全是从库里数出来的，一个模型都不用调。

## 它给的是问题，不是判决

调高假设**可能完全正确**：世界真的变了。所以这里只陈述事实并提出问题，
由人回答。写成判决（「你在追高」）会有两个后果：判错的时候你会不再信它，
判对的时候你会开始绕开它。**一个你会绕开的诚实机制，等于没有。**

## 只比假设，不比算出来的价值

新年报进来之后，基数变了，即使一个字没改每股价值也会变。所以两次比较时
**用同一套基数重算**，这样差值里只剩下你自己动的那部分。

不做这一步的话，一份「营收下滑年报」会被读成「你把假设调低了」——
而你其实什么都没改。
"""

from __future__ import annotations

from typing import Any

from . import scenarios as sc

# 小于这个幅度当噪音。8% 改成 8.3% 不值得问一句话——
# **问得太频繁的机制会被整个关掉**，那比不问更糟。
SIGNIFICANT = 5.0


def _relative(before: float | None, after: float | None) -> float | None:
    """相对变化 %。基数为 0 或缺失时返回 None，**不返回 0**——
    「没变」和「算不出」是两回事。"""
    if before is None or after is None or before == 0:
        return None
    return round((after - before) / abs(before) * 100, 1)


def _same_sign(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and a * b > 0


def base_of(scenarios: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((row for row in scenarios if row.get("key") == "base"), None)


def compare(previous: dict[str, Any], current: dict[str, Any],
            facts: dict[str, Any]) -> dict[str, Any]:
    """两次保存之间，假设改了什么、价格动了多少、方向一不一致。

    `facts` 是**当前**的基数（营收、股本）。两边都用它重算，
    差值里就只剩下你自己动的那部分。
    """
    before = base_of(previous["scenarios"])
    after = base_of(current["scenarios"])
    if before is None or after is None:
        return {"comparable": False}

    def value(row: dict[str, Any]) -> float | None:
        scenario = sc.Scenario("base", float(row["revenue_growth"]),
                               float(row["net_margin"]), float(row["exit_pe"]))
        return sc.value_of(scenario, float(facts.get("base_revenue") or 0),
                           float(facts.get("shares") or 0),
                           int(current.get("years") or sc.DEFAULT_YEARS),
                           float(current.get("discount_rate") or sc.DEFAULT_DISCOUNT))["per_share"]

    assumption_shift = _relative(value(before), value(after))
    price_shift = _relative(previous.get("price_at_write"), current.get("price_at_write"))

    fields = []
    for key, label, unit in (("revenue_growth", "收入年增", "%"),
                             ("net_margin", "净利率", "%"),
                             ("exit_pe", "退出 PE", "")):
        old, new = float(before[key]), float(after[key])
        if old != new:
            fields.append({"key": key, "label": label, "unit": unit,
                           "before": old, "after": new,
                           "change": round(new - old, 2)})

    return {
        "comparable": True,
        "from_at": previous.get("created_at"),
        "to_at": current.get("created_at"),
        "price_before": previous.get("price_at_write"),
        "price_after": current.get("price_at_write"),
        "assumption_shift": assumption_shift,
        "price_shift": price_shift,
        "fields": fields,
        # 方向一致 = 假设跟着价格走。**这才是要问的那种情况。**
        "followed_price": (_same_sign(assumption_shift, price_shift)
                           and abs(assumption_shift or 0) >= SIGNIFICANT
                           and abs(price_shift or 0) >= SIGNIFICANT),
        "against_price": (assumption_shift is not None and price_shift is not None
                          and assumption_shift * price_shift < 0
                          and abs(assumption_shift) >= SIGNIFICANT),
    }


def read(change: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """要问的那句话。**是问题不是判决。**

    调高假设可能完全正确——世界真的变了。写成判决会有两个后果：
    判错时你不再信它，判对时你开始绕开它。而一个你会绕开的诚实机制等于没有。
    """
    if not change.get("comparable") or not change["fields"]:
        return {"level": "none", "question": "", "headline": ""}

    learned = (context.get("evidences", 0) + context.get("reports", 0)
               + context.get("material_events", 0))
    moved = f"假设推出的价值动了 {change['assumption_shift']:+g}%"
    priced = (f"同期股价动了 {change['price_shift']:+g}%"
              if change.get("price_shift") is not None else "同期股价不详")

    if change["followed_price"] and learned == 0:
        return {
            "level": "ask",
            "headline": "假设跟着价格走了，而这期间什么都没发生",
            "question": (f"{moved}，{priced}，方向一致。而这中间**没有新的定期报告、"
                         f"没有归档任何证据、也没有实质公告**。\n\n"
                         f"你是看到了新东西，还是股价变了之后在给它找理由？"),
        }
    if change["followed_price"]:
        return {
            "level": "note",
            "headline": "假设跟着价格走了，不过这期间确实有新东西",
            "question": (f"{moved}，{priced}，方向一致。这期间有 "
                         f"{context.get('reports', 0)} 份新报告、"
                         f"归档 {context.get('evidences', 0)} 条证据、"
                         f"{context.get('material_events', 0)} 条实质公告。\n\n"
                         f"那就说得通——值得确认的是：这些新东西**撑得起这么大的调整幅度**吗？"),
        }
    # 价格没怎么动、也没有任何新信息，而假设大改了一轮。
    #
    # **这一档是补出来的。** 第一版只查「假设跟着价格走」，于是同一天里把基准增速
    # 从 8% 改到 15%（股价一分没动、什么都没发生）被判成"噪音"，一声不吭。
    # 而那恰恰是最该留痕的一种：你改主意了，但说不出因为什么。
    if (abs(change.get("assumption_shift") or 0) >= SIGNIFICANT and learned == 0
            and not change["against_price"]):
        return {
            "level": "unexplained",
            "headline": "假设改了一轮，但这期间没有任何新信息",
            "question": (f"{moved}，而这中间**没有新的定期报告、没有归档任何证据、"
                         f"也没有实质公告**（{priced}）。\n\n"
                         f"改的依据是什么？如果只是「再想了想」，那也值得写下来——"
                         f"下次回头看，你会想知道当时想的是什么。"),
        }
    if change["against_price"]:
        return {
            "level": "good",
            "headline": "这次调整跟价格方向相反",
            "question": (f"{moved}，而{priced}。**方向是反的**——"
                         f"这通常说明你是按事实调的，不是按价格调的。记一笔。"),
        }
    return {"level": "quiet", "headline": "改动不大",
            "question": f"{moved}，{priced}。幅度在噪音范围内，没什么可问的。"}


def summarize(changes: list[dict[str, Any]]) -> str:
    """一句话说清这家公司的假设被改过几次、有几次是跟着价格走的。"""
    if not changes:
        return ""
    followed = sum(1 for item in changes if item["change"].get("followed_price"))
    asked = sum(1 for item in changes if item["reading"]["level"] == "ask")
    text = f"这家公司的估值假设改过 {len(changes)} 次"
    if followed:
        text += f"，其中 {followed} 次跟股价同向"
    if asked:
        text += f"；**有 {asked} 次同期没有任何新信息**"
    return text + "。"
