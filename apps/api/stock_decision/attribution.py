"""决策归因：我当时错在哪。

## 闭环的第三环

写下判断 → 世界变了没有 → **我错在哪**。前两环已经通了（三十秒写下、假设漂移），
而没有第三环，**什么都不会复利**——每一次决策都是从零开始的。

而这个系统里唯一会复利的资产，恰恰是「你自己的决策模型」：
我总为成长付太高的价、我卖得太早、我在周期股上老看错。
这个东西没有任何产品能给你，只能从你自己的记录里长出来。

## 但这一版**只报机械可验证的事实**

「我总为成长付太高的价」这类模式需要几十次决策才谈得上，而且判定本身
就是一次判断——很容易变成一句听着很像回事、其实是编的话。

所以这里只回答三个不需要任何判断的问题：

1. 你写下这条判断时是什么价，现在是什么价
2. 你当初写的认错条件，**触发过没有**
3. 触发之后，**你做了什么**

第三条是全部的重点。前两条任何行情软件都能给你，而第三条只有你自己的
记录本能回答，也只有它能改变行为。

## 「触发了但你什么都没做」是这里最重的一句

它不带任何判断——**没做也可能完全正确**（你重新想过，认为那条件写得太紧）。
但它必须被数出来并摆在你面前，因为这正是人最容易骗自己的地方：
当时想着"再看看"，然后就没有然后了。

跟假设漂移同一条规矩：**陈述事实，提出问题，不下判决。**

## 没有数据时说实话

三条判断谈不上任何规律。样本不够时明说不够，**不要凑出一段看起来有洞察的话**——
一份编出来的归因比没有归因更糟，因为你会照着它改行为。
"""

from __future__ import annotations

from typing import Any

# 少于这个数就别谈规律。**这不是谦虚，是算术**：三条判断里两条错了，
# 说明不了任何事，而"67% 的失误率"这种说法会被当真。
MIN_FOR_PATTERN = 10

# 认错条件触发之后，多久没动作算"没做"。
# 给一周：真看到了总要点时间想想，当天就要求动作是不合理的。
GRACE_DAYS = 7


def _pct(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before == 0:
        return None
    return round((after - before) / abs(before) * 100, 1)


def outcome(thesis: dict[str, Any], price_now: float | None,
            hits: list[dict[str, Any]], acted: bool) -> dict[str, Any]:
    """一条判断到今天为止发生了什么。全部是事实，没有一句判断。"""
    move = _pct(thesis.get("price_at_write"), price_now)
    fired = len(hits)
    return {
        "thesis_id": thesis["id"],
        "company_id": thesis["company_id"],
        "company_name": thesis.get("company_name"),
        "symbol": thesis.get("symbol"),
        "claim": thesis.get("claim"),
        "counter_condition": thesis.get("counter_condition") or "",
        "status": thesis.get("status"),
        "written_at": thesis.get("created_at"),
        "price_at_write": thesis.get("price_at_write"),
        "price_now": price_now,
        "price_move": move,
        "counter_fired": fired,
        "first_fired_at": hits[0]["created_at"] if hits else None,
        "acted": acted,
        # **这三种情形要分开。** 合成一个"健康度"分数会把它们抹平，
        # 而它们对你意味着的事完全不同。
        "state": ("触发过，也动过" if fired and acted else
                  "触发过，但一直没动" if fired else
                  "还没触发" if thesis.get("counter_condition") else
                  "没写认错条件"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """把这些事实数一遍。**不解释，只计数。**"""
    total = len(rows)
    if total == 0:
        return {"total": 0, "headline": "还没有可归因的判断。",
                "note": f"写下第一条判断之后，这里就会开始记录它后来怎么样了——"
                        f"写下时什么价、认错条件触发过没有。"
                        f"到 **{MIN_FOR_PATTERN} 条**以上，它才谈得上「你更容易在哪类判断上看错」。",
                "enough": False, "silent": 0, "fired": 0, "no_falsifier": 0,
                "progress": {"have": 0, "need": MIN_FOR_PATTERN}}

    fired = sum(1 for r in rows if r["counter_fired"])
    silent = sum(1 for r in rows if r["counter_fired"] and not r["acted"])
    no_falsifier = sum(1 for r in rows if not r["counter_condition"])
    moves = [r["price_move"] for r in rows if r["price_move"] is not None]

    parts = [f"一共 {total} 条判断"]
    if fired:
        parts.append(f"{fired} 条的认错条件触发过")
    if silent:
        parts.append(f"**其中 {silent} 条触发之后没有任何动作**")
    if no_falsifier:
        parts.append(f"{no_falsifier} 条压根没写认错条件")

    note = ""
    if total < MIN_FOR_PATTERN:
        # **样本不够仍然要明说**——一份编出来的归因比没有归因更糟。
        #
        # 但「不够做统计」不等于「什么都不说」，而原来那句话是死的：
        # 「只有 4 条，谈不上规律」读完就没有下文，也看不出还差多远。
        # 改成进度，并且点明**门槛之下已经能看的东西**——
        # 下面那张表里逐条的"写下时什么价、现在什么价、认错条件触发过没有"
        # 一条样本都不需要，它现在就成立。
        # **这句话里的数字要跟 total 一起变。**
        #
        # 原来写死的是「{total} 条里错了两条说明不了任何事，而「50% 的失误率」
        # 这种说法会被当真」—— 2026-08-16 线上只有 1 条判断，于是它印出来是：
        #
        #     「1 条里错了两条说明不了任何事，而「50% 的失误率」…」
        #
        # 一条里错两条，和由此得出的 50%，两个数都不成立。而这一页的全部纪律
        # 就是「只报机械可验证的事实」「不要凑出一段看起来有洞察的话」——
        # 在这上面印一句算不通的话，比不印这句更伤。
        #
        # 改成从 total 现算：一条判断只要错一条就是 100%，那正好把这句话
        # 想说的道理说得更硬。
        share = round(100 / total)
        note = (f"**{total} / {MIN_FOR_PATTERN}**——再写 {MIN_FOR_PATTERN - total} 条，"
                f"这里会开始告诉你哪一类判断你更容易看错。"
                f"在那之前不谈倾向：{total} 条里只要错一条，算出来就是 {share}% 的失误率，"
                f"而这种数字会被当真。\n"
                f"**但下面每一条现在就能看**：写下时什么价、现在什么价、"
                f"认错条件触发过没有、触发之后你动没动——这些不需要样本量。")
    return {
        "total": total,
        "fired": fired,
        "silent": silent,
        "no_falsifier": no_falsifier,
        "enough": total >= MIN_FOR_PATTERN,
        # 还差几条才谈得上规律。**给个进度，而不是一句"不够"**——
        # 进度是可以往前推的，"不够"读完就到头了。
        "progress": {"have": total, "need": MIN_FOR_PATTERN},
        "median_move": round(sorted(moves)[len(moves) // 2], 1) if moves else None,
        "headline": "，".join(parts) + "。",
        "note": note,
        "question": (
            f"那 {silent} 条：当时是重新想过觉得条件写得太紧，还是想着「再看看」然后就没有然后了？"
            if silent else ""),
        "boundary": (
            "这里只数**机械可验证的事实**：写下时的价、现在的价、认错条件触发过没有、"
            "触发之后你动没动。**「没动」不等于做错了**——你可能重新想过，"
            "认为那条件当初写得太紧。但它必须被数出来摆在你面前，"
            "因为这正是人最容易骗自己的地方。"
            f"至于「我总为成长付太高的价」这类倾向，要到 {MIN_FOR_PATTERN} 条以上才谈得上，"
            "而且那需要你自己下判断，不是这里能替你算的。"),
    }
