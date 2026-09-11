"""组合共同风险：我以为的分散，是不是同一个赌注下了五次。

## 这一页要回答的问题

持仓列表会告诉你「我有 6 只票，最大一只 22%」，于是你觉得自己是分散的。
但分散不是由**只数**决定的，是由**它们会不会同时出事**决定的。

六只票，三只的年报分部里都有「光伏组件」，两只的上游都是同一家电池厂，
五只的估值都在全市场前 30% 的高位——这不是六个赌注，是两三个赌注下了六次。
真出事的时候它们一起跌，而你以为自己有六层缓冲。

券商的持仓页永远不会告诉你这件事：它只按行业分类给你画一张饼，
而行业分类恰恰是重叠里最不值钱的那一种（它是公开的，你自己也知道）。

## 全部由代码算，一个字都不由模型编

这一页里每一条重叠都能被你点开验证：

- 行业重合 → 申万一级/二级，写着是哪个
- 分部重合 → **年报分部附注里的同名分部**，带营收占比，这是真披露数据
- 上下游重合 → 产业链表里指向同一个对手方，**带上原始的置信度标注**
- 估值/市值/位置重合 → 全市场分位，写着分位数
- 认错条件重合 → 直接把两条里那句一模一样的话抄给你看

模型不参与，因为「这两家算不算同一个风险」这种判断一旦编错，
后果是你据此调仓。所以这里只报**字面上重合**的事实，然后问你一句。

## 陈述事实，提出问题，不下判决

跟假设漂移、决策归因同一条规矩。集中不等于错——巴菲特的组合比这集中得多。
这一页只保证一件事：**你是知情地集中，而不是以为自己分散。**

## 没数据时说没数据

两只票谈不上分散不分散；权重算不出来（没同步行情、又不是比例口径）时
就说算不出来，**不要退回按只数平均分**——那会把一只 60% 的票和一只 5% 的票
说成一样重，而结论正好相反。
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

# 一个"共同风险"至少要有两只票踩到。一只票的行业不叫集中，叫持仓。
MIN_MEMBERS = 2

# 合计权重低于这个数的重合不往外报。**这是注意力预算，不是安全线**：
# 占你 8% 仓位的两只票共用一个上游，出事也动不了你的本金，
# 而每多报一条没用的，你下次就少看一眼真正要紧的那条。
MIN_WEIGHT = 20.0

# 少于这个只数，"分散"这个词本身就不成立——但**不成立不等于不该说话**。
#
# 原来这里是 3，理由是"两只票谈不上分散不分散"。单看没错，
# 放到真实用户身上就错了：调研里散户的典型错误第一条就是
# **「不懂仓位管理，总满仓单只个股」**。
# 也就是说，最需要听到这句话的人，恰恰是这个门槛选择沉默的那个人。
#
# 现在改成：1 只也说话，只是说的不是"你不分散"（那是废话），
# 而是"你 100% 押在这一家上，它的认错条件是这条，触发过没有"——
# 那不需要任何样本量，而且是这一页真正能帮上忙的地方。
MIN_POSITIONS_FOR_DIVERSITY = 1

# 全市场分位的档位：高于 HIGH 算贵/大/热，低于 LOW 算便宜/小/冷。
HIGH_PCT = 70.0
LOW_PCT = 30.0

# 认错条件的共同措辞：至少这么长才当回事。
# 短了全是「连续两期」这种结构词，报出来只会消耗你的信任。
MIN_PHRASE = 6

# 这些是写认错条件时的结构性说法，任何两条里都可能撞上，
# 撞上了也不说明它们是同一个风险。**宁可漏报也不要误报**——
# 误报一次，下次真的撞上时你就不看了。
GENERIC_PHRASES = (
    "连续两期", "连续两个季度", "连续三个季度", "连续两年", "连续三年",
    "同比下滑", "同比下降", "环比下滑", "低于百分之", "超过百分之",
    "如果发生", "我就认错", "我就承认", "承认这条判断错了", "这条判断就错了",
    "出现以下情况", "任意一条成立", "在此之前", "半年报或年报", "季报或年报",
)


def _cjk_only(text: str) -> str:
    """只留中文与数字。标点和空格会把同一句话切成两段，让重合查不出来。"""
    return re.sub(r"[^一-鿿0-9a-zA-Z%]", "", text or "")


def _phrases(text: str) -> set[str]:
    body = _cjk_only(text)
    return {body[i:i + MIN_PHRASE] for i in range(len(body) - MIN_PHRASE + 1)}


def _is_generic(phrase: str) -> bool:
    return any(g in phrase or phrase in g for g in GENERIC_PHRASES)


def _grow(phrase: str, texts: list[str]) -> str:
    """把命中的 n-gram 向两边长到最长的共同串，好让你一眼看出重合的是哪句话。

    只报 6 个字的片段，你没法判断它是不是同一件事；报整句就一目了然。

    **两个方向要分开长。** 一起长会在任意一边先分叉时整个停住——
    「如果新能源车渗透率见顶回落」与「新能源车渗透率见顶回落的话」左边一上来就不同，
    于是右边那四个字也跟着长不出来，最后只报「渗透率见顶回」这么半句。
    """
    bodies = [_cjk_only(t) for t in texts]
    spans = []
    for body in bodies:
        index = body.find(phrase)
        if index < 0:
            return phrase
        spans.append((body, index, index + len(phrase)))

    while all(end < len(body) for body, _, end in spans) and \
            len({body[end] for body, _, end in spans}) == 1:
        spans = [(body, start, end + 1) for body, start, end in spans]
    while all(start > 0 for _, start, _ in spans) and \
            len({body[start - 1] for body, start, _ in spans}) == 1:
        spans = [(body, start - 1, end) for body, start, end in spans]
    body, start, end = spans[0]
    return body[start:end]


def _pct_rank(values: list[float], target: float) -> float | None:
    """target 在 values 里的百分位。values 必须是**全市场**，不是组合内部——
    组合内部的分位永远有人在前 30%，那不叫贵。"""
    if not values:
        return None
    below = sum(1 for v in values if v < target)
    return round(below / len(values) * 100, 1)


def _weight_of(members: list[dict[str, Any]]) -> float | None:
    weights = [m.get("weight") for m in members]
    if any(w is None for w in weights):
        return None
    return round(sum(weights), 1)


def _group(kind: str, label: str, members: list[dict[str, Any]],
           evidence: str, question: str, confidence: str = "") -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "members": [{"symbol": m["symbol"], "name": m["company_name"],
                     "weight": m.get("weight"), "detail": m.get("_detail", "")}
                    for m in members],
        "member_count": len(members),
        "weight": _weight_of(members),
        "evidence": evidence,
        "confidence": confidence,
        "question": question,
    }


# ------------------------------------------------------------------ 各条探测

def _by_industry(positions: list[dict[str, Any]], facts: dict[str, dict]) -> list[dict]:
    """行业重合。**两个口径都看**：申万一级说不出问题的，二级往往说得出。

    「食品饮料」下面白酒和乳制品是两回事，但「白酒」下面三只就是一回事。
    """
    out = []
    for field, tier in (("sw_level1", "申万一级"), ("sw_level2", "申万二级"), ("industry", "档案行业")):
        buckets: dict[str, list] = defaultdict(list)
        for position in positions:
            name = (facts.get(position["symbol"], {}).get(field) or "").strip()
            if name and name not in ("待补充", "其他"):
                buckets[name].append(position)
        for name, members in buckets.items():
            if len(members) < MIN_MEMBERS:
                continue
            out.append(_group(
                "industry", f"{tier}「{name}」", members,
                f"{len(members)} 只持仓的{tier}分类都是「{name}」。",
                "这几只是三个独立的判断，还是同一个判断买了三次？"
                "板块估值中枢下移一档的时候，它们会一起跌。"))
        if out:
            break        # 一级已经报出来了就不用再报二级——同一件事说两遍
    return out


def _by_segment(positions: list[dict[str, Any]], facts: dict[str, dict]) -> list[dict]:
    """分部重合。**这是这一页最值钱的一条**，因为它是真披露数据。

    两家公司的行业分类可能完全不同，而年报分部附注里都写着「光伏组件」——
    行业分类看不出来的东西，这里看得出来。
    """
    buckets: dict[tuple[str, str], list] = defaultdict(list)
    for position in positions:
        for item in facts.get(position["symbol"], {}).get("segments") or []:
            name = (item.get("segment") or "").strip()
            if not name or name in ("其他", "其他业务", "合计", "小计", "其他(补充)"):
                continue
            copy = dict(position)
            share = item.get("revenue_share")
            copy["_detail"] = f"占营收 {share:g}%" if share is not None else "占比未披露"
            buckets[(item.get("dimension") or "", name)].append(copy)
    out = []
    for (dimension, name), members in buckets.items():
        # 同一家公司可能有多个同名分部口径，去重后才谈得上"几只票"
        unique: dict[str, dict] = {}
        for member in members:
            unique.setdefault(member["symbol"], member)
        members = list(unique.values())
        if len(members) < MIN_MEMBERS:
            continue
        out.append(_group(
            "segment", f"{dimension}分部「{name}」", members,
            f"{len(members)} 只持仓的最新年报分部附注里都有「{name}」这一项"
            f"（{'、'.join(m['company_name'] + ' ' + m['_detail'] for m in members)}）。",
            f"「{name}」这块生意如果整体走弱，这几只会一起受影响——"
            "你当初是分开算的账，还是其实算的同一笔？"))
    return out


def _by_chain(positions: list[dict[str, Any]], facts: dict[str, dict]) -> list[dict]:
    """上下游共同对手方。**必须带着置信度一起报。**

    产业链那张表大部分行是「待证实」——由模型从公开信息里推的。
    不写清楚的话，一条推测出来的"共同大客户"会被当成事实用来调仓。
    """
    buckets: dict[str, list] = defaultdict(list)
    for position in positions:
        for link in facts.get(position["symbol"], {}).get("chain") or []:
            name = (link.get("counterpart") or "").strip()
            if not name:
                continue
            copy = dict(position)
            copy["_detail"] = f"{link.get('relation') or ''}·{link.get('confidence') or '待证实'}"
            buckets[name].append(copy)
    out = []
    for name, members in buckets.items():
        unique: dict[str, dict] = {}
        for member in members:
            unique.setdefault(member["symbol"], member)
        members = list(unique.values())
        if len(members) < MIN_MEMBERS:
            continue
        levels = {m["_detail"].split("·")[-1] for m in members}
        confirmed = levels == {"已证实"}
        out.append(_group(
            "chain", f"共同对手方「{name}」", members,
            f"{len(members)} 只持仓的产业链里都指向「{name}」"
            f"（{'、'.join(m['company_name'] + '：' + m['_detail'] for m in members)}）。",
            f"如果「{name}」自己出了事——砍单、换供应商、自己下场做——"
            "这几只是一起受影响还是各自独立？",
            confidence="" if confirmed else "产业链这张表多数是推的，用之前先点开核一下来源。"))
    return out


def _by_number(positions: list[dict[str, Any]], facts: dict[str, dict],
               market: dict[str, list[float]]) -> list[dict]:
    """估值、市值、位置这三种"你在同一个位置上买的"重合。

    全部按**全市场分位**判档。用绝对值判会随行情整体漂移：
    2015 年 40 倍是常态，2024 年 40 倍是高位，同一个阈值说的不是同一件事。
    """
    specs = (
        ("pe_ttm", "market_pe", "估值", "市盈率", True),
        ("pb", "market_pb", "估值", "市净率", True),
        ("total_market_cap", "market_cap", "市值", "总市值", False),
    )
    out = []
    for field, pool_key, kind, label, invert in specs:
        pool = market.get(pool_key) or []
        high, low = [], []
        for position in positions:
            value = facts.get(position["symbol"], {}).get(field)
            if value is None or (invert and value <= 0):
                continue        # 负市盈率不是"便宜"，是没有 E，不进任何一档
            rank = _pct_rank(pool, float(value))
            if rank is None:
                continue
            copy = dict(position)
            copy["_detail"] = f"{label} {float(value):.4g}，全市场 {rank:g}% 分位"
            (high if rank >= HIGH_PCT else low if rank <= LOW_PCT else []).append(copy)
        for members, side, wording in ((high, "高", "贵"), (low, "低", "便宜")):
            if len(members) < MIN_MEMBERS:
                continue
            if kind == "市值":
                wording = "大盘" if side == "高" else "小盘"
                asked = ("小盘股一起被抽流动性的时候，这几只没有一只能独善其身。"
                         if side == "低" else
                         "全是大盘股意味着你几乎没有 α，赚的是指数的钱——这是你想要的吗？")
            else:
                asked = (f"这几只同时贵，靠的是同一种叙事吗？"
                         f"风格从成长切回价值的时候它们会一起被杀估值。"
                         if side == "高" else
                         "同时便宜的几只，是不是便宜在同一个原因上？"
                         "那个原因不变，它们就一起不涨。")
            out.append(_group(
                kind if kind != "估值" else "valuation",
                f"都在{label}的{side}位（{wording}）", members,
                f"{len(members)} 只持仓的{label}都在全市场 "
                f"{'前' if side == '高' else '后'} {100 - HIGH_PCT if side == '高' else LOW_PCT:g}% "
                f"（{'、'.join(m['company_name'] + ' ' + m['_detail'] for m in members)}）。",
                asked))
    return out


def _by_trend(positions: list[dict[str, Any]], facts: dict[str, dict]) -> list[dict]:
    """位置重合：是不是全都买在同一个技术位置上。

    这个字段是「在不在同花顺那张榜上」——**0 是事实（不在榜上），
    None 是没同步**，两者不能混，混了数据源挂掉没人知道。
    """
    specs = (("above_ma60", "都站在 60 日线上方",
              "全是趋势向上的票。趋势一起走坏的时候，它们会在同一周里一起破位——"
              "你的止损条件是各写各的，还是其实是同一条？"),
             ("new_high_level", "都在创新高的位置",
              "都买在新高上。这不一定是坏事，但它意味着你没有一只票是「跌下来才买的」，"
              "整个组合的成本都在高位。"))
    out = []
    for field, label, asked in specs:
        members = []
        for position in positions:
            value = facts.get(position["symbol"], {}).get(field)
            if value is None or float(value) <= 0:
                continue
            copy = dict(position)
            copy["_detail"] = label
            members.append(copy)
        if len(members) < MIN_MEMBERS:
            continue
        out.append(_group("trend", label, members,
                          f"{len(members)} 只持仓{label}（同花顺榜单）。", asked))
    return out


def _by_counter(positions: list[dict[str, Any]], facts: dict[str, dict]) -> list[dict]:
    """认错条件里的共同措辞。**放在最后，因为它最容易误报。**

    但它也是唯一一条能碰到「共同假设」的：你为两家公司写的认错条件里
    出现同一句话，多半是因为你心里想的是同一件事。
    所以这里把那句话原样抄出来给你看——对不对，你一眼就知道。
    """
    index: dict[str, set[str]] = defaultdict(set)
    texts: dict[str, str] = {}
    for position in positions:
        text = " ".join(facts.get(position["symbol"], {}).get("counters") or [])
        if not text.strip():
            continue
        texts[position["symbol"]] = text
        for phrase in _phrases(text):
            if not _is_generic(phrase):
                index[phrase].add(position["symbol"])

    by_symbols: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for phrase, symbols in index.items():
        if len(symbols) >= MIN_MEMBERS:
            by_symbols[tuple(sorted(symbols))].append(phrase)

    out = []
    seen_symbols: set[tuple[str, ...]] = set()
    for symbols, phrases in sorted(by_symbols.items(), key=lambda kv: -len(kv[0])):
        if symbols in seen_symbols:
            continue
        seen_symbols.add(symbols)
        longest = _grow(max(phrases, key=len), [texts[s] for s in symbols])
        members = [p for p in positions if p["symbol"] in symbols]
        out.append(_group(
            "counter", f"认错条件里有同一句话", members,
            f"这 {len(members)} 只的认错条件里都出现了「{longest}」。",
            "同一句话出现在两条认错条件里，通常是因为你心里想的是同一件事。"
            "如果它真的发生，这两条判断会同时被推翻——**你的认错条件本身就没有分散**。",
            confidence="按字面重合找出来的，不一定真是同一件事，看一眼就能判断。"))
    return out


# ------------------------------------------------------------------ 汇总

def analyze(positions: list[dict[str, Any]], facts: dict[str, dict],
            market: dict[str, list[float]]) -> dict[str, Any]:
    """positions 是当前持仓，facts 按 symbol 给每只票的事实，market 给全市场分位池。"""
    count = len(positions)
    weighted = all(p.get("weight") is not None for p in positions) and count > 0

    if count == 0:
        return {"position_count": 0, "weighted": False, "groups": [], "hidden": 0,
                "headline": "组合里还没有持仓。",
                "note": "有了两只以上持仓之后，这里会检查它们会不会同时出事。",
                "boundary": _BOUNDARY}
    # **只有一只的时候，重合检测确实无从谈起，但这一页仍然有话可说。**
    # 说"谈不上分散"是废话；该说的是"你全部押在这一家上"，
    # 并把注意力引到那家公司的认错条件上——那是这种仓位下唯一要紧的事。
    if count == 1:
        only = positions[0]
        weight = only.get("weight")
        # **这句话原来在事实上不成立。**
        #
        # 模板是 `你的{share}全部押在{名字}一家上`，而 share 在有权重时是
        # 「50% 仓位」—— 拼出来就是 **「你的50% 仓位全部押在格力电器一家上」**：
        # 50% 和「全部」自相矛盾，而且读起来是句同义反复。没权重时更糟，
        # 拼出来是「你的全部仓位全部押在…」，两个「全部」。
        # （2026-08-16 线上就是这一句，加粗摆在这一页的最上面。）
        #
        # 口径查清了：ratio 那种记法里的 50% 是**你自己记的占比，剩下的没记账**。
        # 那种情况下这一页连「分不分散」都答不了 —— 而这个模块开头写着
        # 「没数据时说没数据」，那就得真的说出来，不能拿一句读着像结论的话糊过去。
        if weight is None:
            headline = f"**这个组合里只有一只持仓：{only['company_name']}。**"
            tail = ""
        elif weight >= 99.5:
            headline = f"**你的全部仓位押在{only['company_name']}一家上。**"
            tail = ""
        else:
            headline = (f"**这个组合里你只记了一只票：{only['company_name']}，"
                        f"占 {weight:g}% 仓位。**")
            tail = (f"剩下的 {100 - weight:g}% 没有记在这个组合里，"
                    f"所以这一页**答不了「分不分散」**——它只看得见你记下来的部分。")
        return {"position_count": 1, "weighted": weighted, "groups": [], "hidden": 0,
                "single": {"symbol": only["symbol"], "name": only["company_name"],
                           "company_id": only.get("company_id")},
                "headline": headline,
                "note": (tail + " " if tail else "")
                        + "只有一只持仓，没有重合可查。"
                        "但这恰恰是最该盯紧一件事的仓位："
                        "**这家公司的认错条件写了没有、触发过没有。**"
                        "一只票的组合里，那条件就是你唯一的刹车。",
                "boundary": _BOUNDARY}

    groups = (_by_industry(positions, facts) + _by_segment(positions, facts)
              + _by_chain(positions, facts) + _by_number(positions, facts, market)
              + _by_trend(positions, facts) + _by_counter(positions, facts))

    # 权重算不出来的时候**不退回按只数平均分**：那会把 60% 的票和 5% 的票
    # 说成一样重，而结论正好相反。算不出来就说算不出来，只按只数排序。
    kept, hidden = [], 0
    for group in groups:
        if group["weight"] is not None and group["weight"] < MIN_WEIGHT:
            hidden += 1
            continue
        kept.append(group)
    kept.sort(key=lambda g: (-(g["weight"] if g["weight"] is not None else -1),
                             -g["member_count"]))

    note = ""
    if not weighted:
        note = ("这个组合的权重算不出来（没有行情价，账本口径也不是只记占比），"
                "所以下面只按**只数**排，不代表按仓位排。一只 60% 的票和一只 5% 的票"
                "在这里看起来一样重，而结论可能正好相反。")

    if not kept:
        headline = f"{count} 只持仓，没有查出会同时出事的重合。"
        if hidden:
            note = (note + " " if note else "") + \
                   f"另有 {hidden} 条重合合计仓位不到 {MIN_WEIGHT:g}%，没有列出。"
    else:
        top = kept[0]
        share = f"，合计 {top['weight']:g}% 仓位" if top["weight"] is not None else ""
        headline = (f"{count} 只持仓里，**{top['member_count']} 只{share}"
                    f"共用「{top['label']}」**"
                    + (f"；另外还查出 {len(kept) - 1} 处重合。" if len(kept) > 1 else "。"))

    return {"position_count": count, "weighted": weighted, "groups": kept,
            "hidden": hidden, "headline": headline, "note": note, "boundary": _BOUNDARY}


_BOUNDARY = (
    "重叠是从你自己写的逻辑、行业与估值位置里读出来的，只报事实、不打分——"
    "**集中不等于做错了**，真懂的人本来就该集中。\n\n"
    "**看不见的重合还有很多**：同一个宏观假设、同一批基金重仓、场外的资产——"
    "这里不猜，所以「没查出重合」不等于「你是分散的」。"
)
