"""选股到执行的闭环：状态机本身。

## 它解决的是哪一句话

> 我有一点选股系统，缺执行系统；没有标准流程，没有规则，没有闭环。

「闭环」在这里有一个很具体的意思：**每只票在任何时刻只能停在一格上，
而从这一格走到下一格，需要的东西是写死的、机器能判的。**

不写死的话，"等待买入"这四个字对不同的票意思不一样——有的票是真研究完了
在等价格，有的票只是"我挺喜欢它"。而这两种在页面上长得一模一样，
于是**「我错过了买点」和「我根本还没完成判断」被混成同一种焦虑**。

## 这里一行事实都不存

投资逻辑在 `theses`、估值在 `valuations`、持仓在 `trades`。状态机只做两件事：

1. 问那几张表「东西齐了没有」（`guards` 里每一条都是一次查询，不是一个副本）；
2. 记下「我什么时候从哪一格走到了哪一格，为什么」。

第二件是 `decision_transitions`。**退回也记**：把「我从等待买入退回研究中」
抹掉，等于把自己承认想错了的那一刻抹掉，而那是复盘里最值钱的东西。

## 被禁的那条边

`discovered / researching → waiting` 是明确禁掉的：

> 没有完成研究和估值之前，系统不应允许用户给出正式买点。

一个没有估值的"买点"只是一个喜欢的数字。它会在价格触及时给你一个
"该动手了"的信号，而那个信号背后什么都没有。

## 触发不是下单

`waiting → triggered` 由价格自动推，但它推到的是**触发检查**，不是持仓。
价格到了只说明"该重新看一眼了"，不说明"该买了"——中间隔着一次
「为什么会跌到这里、原来的假设还成立吗」。
"""

from __future__ import annotations

from typing import Any, Callable

# ── 状态 ────────────────────────────────────────────────────────────────────

STATES: dict[str, dict[str, str]] = {
    "discovered": {
        "label": "待研究",
        "means": "进了池子，还没开始看。",
        "next": "写下「为什么关注它」，就可以开始研究。",
    },
    "researching": {
        "label": "研究中",
        "means": "正在读，还没有结论。",
        "next": "写下投资逻辑、反证条件，并完成一次估值。",
    },
    "valued": {
        "label": "已估值",
        "means": "逻辑、反证条件和估值都有了，但还没有决定在什么价格、用多少仓位动手。",
        "next": "定四段价格带和仓位计划。",
    },
    "waiting": {
        "label": "等待价格",
        "means": "该想的都想完了，在等价格进区间。**这一格里没有交易是正常的，也是成功的。**",
        "next": "等价格触发；或者主动退回研究中（假设变了）。",
    },
    "committed": {
        "label": "待成交",
        "means": "检查做完了，决定买，**但还没成交**。挂单可能不成，也可能你自己又改了主意。",
        "next": "成交之后账本会把它推成「持仓中」；撤单或改主意就退回等待。",
    },
    "triggered": {
        "label": "触发检查",
        "means": "价格进了某一段。**这不是买入信号**，是「重新看一眼」的信号。",
        "next": "回答「为什么跌到这里、原假设还成立吗」，然后决定动手还是退回等待。",
    },
    "holding": {
        "label": "持仓中",
        "means": "账本里有这只票的买入流水。",
        "next": "按计划加仓 / 持有；到期或反证命中时进复盘。",
    },
    "reviewing": {
        "label": "需要复盘",
        "means": "到期、认错条件命中，或者刚清仓——该回头看一遍了。",
        "next": "写下复盘结论，再决定回到等待、持仓，还是搁置。",
    },
    "shelved": {
        "label": "已搁置",
        "means": "想过了，先不碰。**这也是一个结论**，不是没做完。",
        "next": "随时可以捡回来重新研究。",
    },
    "exited": {
        "label": "已清仓",
        "means": "卖完了，账本里持股为零。",
        "next": "复盘，然后决定是继续观察还是搁置。",
    },
}

# 首页按这个顺序分组。**「需要我处理」排最前**，「等待机会」在中间，
# 「已搁置」压最后——打开系统第一眼看到的应该是"我现在该干什么"。
# 「待成交」排在「触发检查」后面、「持仓中」前面 —— 它就是那一段。
STATE_ORDER = ("triggered", "reviewing", "committed", "holding", "waiting",
               "valued", "researching", "discovered", "exited", "shelved")

# 「待成交」也算要盯着的一格：挂单不成、或者成交价跑偏，都需要你知道。
ACTIONABLE_STATES = ("triggered", "reviewing", "committed")

# 这几格里成交的买入算「计划内」。**「待成交」必须在里面** ——
# 「我决定在 300 附近买 1/3」写下来之后成交的那一笔，正是计划内的定义。
IN_PLAN_STATES = ("triggered", "committed", "holding")


# ── 守卫 ────────────────────────────────────────────────────────────────────
#
# 每一条守卫都是一句**机器能判**的话，判不了的不许写进来。
# 「我研究透了吗」判不了，「库里有没有一条带反证条件的投资逻辑」判得了。

# 每条守卫补在哪儿。**没有这个，"去公司档案的「逻辑与证据」写下核心主张"
# 就是一句话，人得自己找页面、找页签、再往下滚。** 使用者的原话：
# 「推进状态机，还必须填写理由；还必须跳转到对应页面？这一套流程，我真觉得麻烦」。
#
# `where` 只有三种落点，前端据此渲染一个能直接点的按钮：
#   card      —— 就在这张卡上（anchor 指向卡上的哪一块）
#   company   —— 公司档案的某个页签
#   portfolio —— 持仓账本
GUARD_GOTO: dict[str, dict[str, str]] = {
    "watch_reason": {"where": "card", "anchor": "watch", "label": "就在下面写"},
    "thesis": {"where": "company", "tab": "research", "label": "去写投资逻辑"},
    "counter_condition": {"where": "company", "tab": "research", "label": "去补反证条件"},
    "valuation": {"where": "company", "tab": "market", "label": "去做一次估值"},
    "bands": {"where": "card", "anchor": "plan", "label": "就在下面填"},
    "position_plan": {"where": "card", "anchor": "plan", "label": "就在下面填"},
    "order_plan": {"where": "card", "anchor": "plan", "label": "就在下面填"},
    "position": {"where": "portfolio", "label": "去持仓账本记一笔"},
    "no_position": {"where": "portfolio", "label": "去持仓账本看看"},
}


GUARDS: dict[str, dict[str, str]] = {
    "watch_reason": {
        "label": "写下了关注理由",
        "fix": "在卡片上补一句「为什么它进了我的池子」。",
    },
    "thesis": {
        "label": "有一条投资逻辑",
        "fix": "去公司档案的「逻辑与证据」写下核心主张。",
    },
    "counter_condition": {
        "label": "投资逻辑带反证条件",
        "fix": "补上「出现什么证据能说明我错了」——没有这一句的逻辑没法被推翻，也就没法被检验。",
    },
    "valuation": {
        "label": "做过一次估值",
        "fix": "去公司档案的「行情与估值」写下三情景假设。",
    },
    "bands": {
        "label": "四段价格带写全了",
        "fix": "定观察区 / 合理区 / 理想区 / 极端机会区四段的**上沿**，四个数必须从高到低。"
               "上沿的意思是「跌到这个价就算进了这一段」——写 300，那么 300 算合理区，301 还不算。",
    },
    "position_plan": {
        "label": "有仓位计划",
        "fix": "写下计划总仓位和首次建仓比例——价格解决赔率，仓位解决判断错误。",
    },
    "position": {
        "label": "账本里有持仓",
        "fix": "去持仓账本记一笔买入流水。**状态机不替你记账**：它只认账本里真有的东西。",
    },
    "no_position": {
        "label": "账本里已经没有持仓了",
        "fix": "还有持股的话，这只票属于「持仓中」，不该退回等待。",
    },
    "order_plan": {
        "label": "写下了这一笔打算买什么价、买多少",
        "fix": "填「计划成交价」和「这一笔占计划总仓位的几分之几」。"
               "**不写死具体数字的话，成交之后没法判断你是不是按计划做的**——"
               "而那正是「计划外交易」这个指标唯一的依据。",
    },
}


# ── 允许的边 ────────────────────────────────────────────────────────────────
#
# 键是 from，值是 {to: 需要满足的守卫}。**不在这张表里的边一律不许走**，
# 白名单而不是黑名单：将来加状态时漏登记的后果是"走不过去"（看得见），
# 而不是"随便走"（看不见）。

TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "discovered": {
        "researching": ("watch_reason",),
        # **账本说了算的那条边。** 人推不动它（见 FORBIDDEN_REASONS），
        # 但账本里真有持仓时，系统必须承认这个事实 —— 一只你手上拿着的票
        # 却停在「待研究」，这套东西就开始跟现实脱节了。
        # 由 `sync_decision_from_ledger` 自己走，actor 记成「账本」。
        "holding": ("position",),
        "shelved": (),
    },
    "researching": {
        "valued": ("thesis", "counter_condition", "valuation"),
        "discovered": (),
        "holding": ("position",),        # 同上：账本说了算
        "shelved": (),
    },
    "valued": {
        "waiting": ("bands", "position_plan"),
        "researching": (),
        "holding": ("position",),        # 同上：账本说了算
        "shelved": (),
    },
    "waiting": {
        # 价格触发通常由机器推（evaluate_trigger），手动也允许——
        # 你可能因为一条新闻而不是价格想重新检查一遍。
        "triggered": (),
        "researching": (),
        "holding": ("position",),        # 同上：账本说了算
        "shelved": (),
    },
    "triggered": {
        "holding": ("position",),
        # 检查做完、决定买了 —— 但成交是另一件事，所以中间有一格。
        "committed": ("bands", "position_plan", "order_plan"),
        # **退回等待是一等公民。** 检查完发现"跌得有道理、假设已经坏了"，
        # 那就该退回去重新研究；发现"跌得没道理、假设没变"，就退回等待下一段。
        "waiting": (),
        "researching": (),
        "shelved": (),
    },
    "committed": {
        "holding": ("position",),        # 账本说了算
        # **撤单和改主意都要能退回来，而且都留痕。**
        # 一次"我决定买了、后来没买"是复盘时很值钱的记录：
        # 它要么说明你守住了纪律，要么说明你当时就没想清楚。
        "waiting": (),
        "triggered": (),
        "researching": (),
        "shelved": (),
    },
    "holding": {
        "reviewing": (),
        "exited": ("no_position",),
        # 加仓不改状态：持仓中加仓还是持仓中。
    },
    "reviewing": {
        "holding": ("position",),
        "waiting": ("no_position", "bands", "position_plan"),
        "researching": (),
        "exited": ("no_position",),
        "shelved": (),
    },
    "exited": {
        "reviewing": (),
        "researching": (),
        "shelved": (),
    },
    "shelved": {
        "discovered": (),
        "researching": (),
    },
}

# 明确禁掉、且值得专门解释一句的边。走不通的原因说清楚，
# 比只说「不允许」有用得多——前者是产品原则，后者像是个 bug。
FORBIDDEN_REASONS: dict[tuple[str, str], str] = {
    ("discovered", "waiting"):
        "没有完成研究和估值之前，不能给出正式买点。一个没有估值的买点只是一个你喜欢的数字，"
        "它会在价格触及时给你「该动手了」的信号，而那个信号背后什么都没有。",
    ("researching", "waiting"):
        "研究还没有收口。先把投资逻辑、反证条件和估值写完，再谈在什么价格动手。",
}


def allowed_targets(state: str) -> tuple[str, ...]:
    return tuple(TRANSITIONS.get(state, {}).keys())


def transition_requirements(state: str, target: str) -> tuple[str, ...] | None:
    """这条边需要哪些守卫。返回 None = 这条边不存在。"""
    return TRANSITIONS.get(state, {}).get(target)


def why_forbidden(state: str, target: str) -> str:
    if state == target:
        return "它已经在这一格了。"
    explicit = FORBIDDEN_REASONS.get((state, target))
    if explicit:
        return explicit
    return (f"从「{STATES.get(state, {}).get('label', state)}」不能直接走到"
            f"「{STATES.get(target, {}).get('label', target)}」。"
            f"可以走的下一格是："
            f"{'、'.join(STATES[t]['label'] for t in allowed_targets(state)) or '（没有）'}。")


# 只有账本推得动的边。**人工点不了它们**——
# 「我已经持仓了」不是一句可以自己宣布的话，它由流水决定。
LEDGER_ONLY: frozenset[tuple[str, str]] = frozenset({
    ("discovered", "holding"), ("researching", "holding"),
    ("valued", "holding"), ("waiting", "holding"),
    ("triggered", "holding"), ("committed", "holding"),
})

LEDGER_ONLY_REASON = (
    "「已经持仓」不是一句可以自己宣布的话，它由账本里的流水决定。"
    "去持仓账本记一笔买入，状态机会自己把它推过来——"
    "同时这几笔会进纪律统计（卡片还没走到触发检查就成交的，算计划外）。")

# 某几条账本专属的边值得多说一句。**「人工走不通」和「这条边不存在」不一样**，
# 所以它们不进 FORBIDDEN_REASONS —— 那张表是真正关死的边。
LEDGER_ONLY_NOTES: dict[tuple[str, str], str] = {
    ("waiting", "holding"):
        "价格触发之后本该先过一次「触发检查」：为什么跌到这里、原来的假设还成立吗。"
        "跳过这一步，等于把「价格到了」直接当成了「可以买了」。",
    ("discovered", "holding"):
        "没研究就买，闭环从第一格就断了。",
}


# 每一格往前走的那条主线边。「下一步」照它算，而不是照一句写死的话。
FORWARD: dict[str, str] = {
    "discovered": "researching", "researching": "valued", "valued": "waiting",
    "waiting": "triggered", "triggered": "committed", "committed": "holding",
    # 持仓中往前是复盘 —— **持有本身不是终点**，到期或反证命中就该回头看一遍。
    "holding": "reviewing",
    "reviewing": "waiting", "exited": "reviewing", "shelved": "researching",
}


def next_step(state: str, facts: dict[str, bool]) -> str:
    """现在到底还差什么。**不是一句写死的话。**

    写死的后果是它会让人去做已经做完的事：宁德那张卡上，投资逻辑和反证条件
    都写了、只缺估值，而「下一步」照旧写着「写下投资逻辑、反证条件，并完成
    一次估值」—— 读者会以为自己什么都没做。
    """
    target = FORWARD.get(state)
    if not target:
        return STATES.get(state, {}).get("next", "")
    needed = transition_requirements(state, target) or ()
    missing = [GUARDS[key]["label"] for key in needed if not facts.get(key)]
    label = STATES[target]["label"]
    if not missing:
        return f"该走的都齐了，可以进「{label}」。"
    return f"进「{label}」还差：{'、'.join(missing)}。"


# **哪几步必须你自己写一句理由。** 其余的机器自己写，见 auto_reason。
#
# 原来每一步都强制手写，使用者的原话是「推进状态机，还必须填写理由；
# 还必须跳转到对应页面？这一套流程，我真觉得麻烦」。他是对的：
# 待研究 → 研究中 的理由就是「我写下了关注理由」，那句话系统自己知道，
# 让人再打一遍是纯粹的税。**而税收够了，人就不推进了**——
# 于是状态机停在半路，比没有状态机更糟：它看起来是准的。
#
# 但有三种情况机器写不出来，也不该替你写：
#
#   1. **不是往前走的那一步**（退回、搁置、跳格）。往前走的理由是"条件齐了"，
#      而退回的理由只有你知道——假设变了？看错了？这恰恰是复盘最值钱的部分，
#      建表注释里那句「退回也留」说的就是它。
#   2. **决定买（待成交）**。这是唯一一步真的要花钱，也是「计划外交易」
#      这个指标唯一的锚。
#   3. **搁置**：为什么不看了，半年后的你一定想知道。
def requires_reason(state: str, target: str) -> bool:
    """这一步要不要你亲手写一句。"""
    if target == "committed":
        return True
    return FORWARD.get(state) != target


def reason_required_because(state: str, target: str) -> str:
    """为什么这一步不肯替你写。**说清楚，别只说"理由必填"。**"""
    if target == "committed":
        return ("进「待成交」必须自己写一句：这是唯一一步真的要花钱，"
                "也是「计划外交易」这个指标唯一的锚。成交之后要拿它对账。")
    if target == "shelved":
        return "搁置要写一句为什么不看了——半年后的你一定想知道。"
    label = STATES.get(target, {}).get("label", target)
    return (f"这一步不是往前走（往前走是「{STATES.get(FORWARD.get(state, ''), {}).get('label', '—')}」），"
            f"退回或跳到「{label}」的理由只有你知道：假设变了？看错了？"
            "**这恰恰是复盘时最值钱的那一句。**")


def auto_reason(state: str, target: str, facts: dict[str, bool]) -> str:
    """机器替你写的那一句。**只陈述事实，不替你表态。**

    写成"我看好它"那种话是危险的：复盘时你会以为那是当时自己的判断。
    所以它只说「哪几格是齐的」——那确实是机器知道的全部。
    """
    if requires_reason(state, target):
        return ""
    needed = transition_requirements(state, target) or ()
    met = [GUARDS[key]["label"] for key in needed if facts.get(key)]
    label = STATES.get(target, {}).get("label", target)
    if not met:
        return f"按流程进「{label}」。"
    return f"进「{label}」的条件齐了：{'、'.join(met)}。"


def check(state: str, target: str, facts: dict[str, bool],
          actor: str = "人工") -> dict[str, Any]:
    """能不能从 state 走到 target，缺什么。

    `facts` 是守卫名 → 真假，由 repository 查库填进来。
    **这个函数自己不碰数据库**，所以它能被单独测：给一组事实，
    它必须永远给出同一个答案。
    """
    if target not in STATES:
        return {"ok": False, "reason": f"没有「{target}」这一格。", "missing": []}
    needed = transition_requirements(state, target)
    if needed is None:
        return {"ok": False, "reason": why_forbidden(state, target), "missing": []}
    if actor == "人工" and (state, target) in LEDGER_ONLY:
        note = LEDGER_ONLY_NOTES.get((state, target), "")
        return {"ok": False,
                "reason": (note + " " if note else "") + LEDGER_ONLY_REASON,
                "missing": []}
    missing = [
        {"key": key, "label": GUARDS[key]["label"], "fix": GUARDS[key]["fix"]}
        for key in needed if not facts.get(key)
    ]
    if missing:
        return {
            "ok": False,
            "reason": (f"还差 {len(missing)} 件事才能进「{STATES[target]['label']}」："
                       + "、".join(m["label"] for m in missing) + "。"),
            "missing": missing,
        }
    return {"ok": True, "reason": "", "missing": []}


# ── 价格带 ──────────────────────────────────────────────────────────────────
#
# 四段，**记的是每一段的上沿**，从高到低。
#
# 上沿的意思是「跌到这个价就算进了这一段」：合理区 300 = 跌到 300 才算合理区，
# 301 还不算。判定见 `band_of`：从最低那一段往上找第一个「价 ≤ 上沿」的。
#
# **这里原来写成「下沿」，而代码一直按上沿判。** 两处差一格，
# 表现是梯子上写着「观察区 = 310 以上」，而现价 305 被判进观察区 ——
# 页面自己跟自己说的不一样，是对着截图逐行念才发现的。
#
# 为什么不记"买点 = 280"：
# 一个数字把决策二元化成「能买 / 不能买」，而真实的判断是分层的——
# 310 尚可、290 不错、280 很好、270 非常舒服，对应的是不同的仓位，
# 不是不同的是非。

BANDS: tuple[dict[str, str], ...] = (
    {"key": "watch", "label": "观察区", "means": "进了视野，但赔率一般。通常不动手。"},
    {"key": "fair", "label": "合理区", "means": "价格合理了。基本面没坏的话，可以考虑第一笔小仓。"},
    {"key": "ideal", "label": "理想区", "means": "最想买的价格。主要建仓区间。"},
    {"key": "extreme", "label": "极端机会区", "means":
        "明显低估。**跌到这里必须强制重新检查基本面**——不许机械认为「越跌越该买」。"},
)

BAND_KEYS = tuple(b["key"] for b in BANDS)
BAND_LABELS = {b["key"]: b["label"] for b in BANDS}


def normalise_bands(raw: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in BAND_KEYS:
        value = (raw or {}).get(key)
        if isinstance(value, (int, float)) and value > 0:
            out[key] = float(value)
    return out


def validate_bands(bands: dict[str, float]) -> str:
    """四段必须从高到低且互不相等，否则一个价会同时命中两段。

    返回空串 = 没问题。**允许一段都不填**（还没想好），但只要填了就要全填：
    半张价格带在页面上跟整张长得一样，而它会在触发时漏掉一整段。
    """
    if not bands:
        return ""
    missing = [BAND_LABELS[k] for k in BAND_KEYS if k not in bands]
    if missing:
        return f"价格带要么一段都不填，要么四段填全。还缺：{'、'.join(missing)}。"
    values = [bands[k] for k in BAND_KEYS]
    for i in range(len(values) - 1):
        if values[i] <= values[i + 1]:
            return (f"{BAND_LABELS[BAND_KEYS[i]]}的上沿（{values[i]:g}）必须高于"
                    f"{BAND_LABELS[BAND_KEYS[i + 1]]}的上沿（{values[i + 1]:g}）——"
                    f"四段从高到低，交叠或相等的话同一个价会同时命中两段。")
    return ""


def band_of(price: float | None, bands: dict[str, float]) -> str | None:
    """这个价落在哪一段。高于观察区上沿 = 还没进任何一段，返回 None。

    判法是「小于等于某一段的上沿」，从最低的一段往上找第一个命中的，
    所以 265 落在极端机会区而不是理想区。

    以 310/300/280/270 为例：>310 没进任何一段；(300,310] 观察区；
    (280,300] 合理区；(270,280] 理想区；≤270 极端机会区。
    """
    if price is None or not bands:
        return None
    for key in reversed(BAND_KEYS):
        if key in bands and price <= bands[key]:
            return key
    return None


# ── 仓位计划 ────────────────────────────────────────────────────────────────

PLAN_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "total_percent", "label": "计划总仓位（%）", "kind": "number", "required": True,
     "hint": "这只票在整个组合里最多占多少。**满仓不等于全部身家**。"},
    {"key": "first_percent", "label": "首次建仓（%）", "kind": "number", "required": True,
     "hint": "第一次动手多大。它决定了你判断错的时候会有多疼。"},
    {"key": "second_percent", "label": "第二次加仓（%）", "kind": "number", "required": False,
     "hint": "价格进入更优区间时再加多少。"},
    {"key": "third_percent", "label": "第三次加仓（%）", "kind": "number", "required": False,
     "hint": "逻辑继续被验证时再加多少。"},
    {"key": "stop_buy", "label": "停止买入的条件", "kind": "text", "required": False,
     "hint": "什么情况下不再往里加钱——**写成事件，不要写成价格**。"},
    {"key": "exit_rule", "label": "卖出逻辑", "kind": "text", "required": False,
     "hint": "什么情况下减仓或清仓。"},
)

REQUIRED_PLAN_KEYS = tuple(f["key"] for f in PLAN_FIELDS if f["required"])


ORDER_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "price", "label": "计划成交价", "kind": "number", "required": True,
     "hint": "不要求精准买在这个数，它是用来事后对账的：成交价离它多远。"},
    {"key": "fraction", "label": "这一笔占计划总仓位的几分之几", "kind": "text", "required": True,
     "hint": "比如「1/3」。**先买多少是主动选择，不是失误**——写下来，"
             "涨了才不会后悔买少了。"},
    {"key": "why_now", "label": "为什么是现在", "kind": "text", "required": False,
     "hint": "一句话。复盘时它是全部的线索。"},
)

REQUIRED_ORDER_KEYS = tuple(f["key"] for f in ORDER_FIELDS if f["required"])


def validate_order(order: dict[str, Any] | None) -> str:
    order = order or {}
    if not any(order.get(f["key"]) for f in ORDER_FIELDS):
        return ""
    price = order.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return "计划成交价要填一个大于 0 的数。"
    if not str(order.get("fraction") or "").strip():
        return "写下这一笔占计划总仓位的几分之几（比如「1/3」）。"
    return ""


def order_complete(order: dict[str, Any] | None) -> bool:
    order = order or {}
    return (isinstance(order.get("price"), (int, float)) and order["price"] > 0
            and bool(str(order.get("fraction") or "").strip()))


def validate_plan(plan: dict[str, Any] | None) -> str:
    plan = plan or {}
    if not any(plan.get(f["key"]) for f in PLAN_FIELDS):
        return ""
    missing = [f["label"] for f in PLAN_FIELDS
               if f["required"] and not isinstance(plan.get(f["key"]), (int, float))]
    if missing:
        return f"仓位计划还缺：{'、'.join(missing)}。"
    total = plan.get("total_percent")
    tranches = [plan.get(k) for k in ("first_percent", "second_percent", "third_percent")]
    summed = sum(v for v in tranches if isinstance(v, (int, float)))
    if isinstance(total, (int, float)) and summed > total + 1e-9:
        return (f"三笔加起来是 {summed:g}%，比计划总仓位 {total:g}% 还多。"
                f"要么抬总仓位，要么把某一笔调小。")
    if isinstance(total, (int, float)) and not 0 < total <= 100:
        return "计划总仓位要在 0 到 100 之间。"
    return ""


def plan_complete(plan: dict[str, Any] | None) -> bool:
    plan = plan or {}
    return all(isinstance(plan.get(key), (int, float)) and plan[key] > 0
               for key in REQUIRED_PLAN_KEYS)


# ── 触发 ────────────────────────────────────────────────────────────────────

TRIGGER_CHECKLIST: tuple[str, ...] = (
    "价格是怎么走到这里的——是大盘整体在跌，还是它自己在跌？",
    "同行业的其他公司是不是也在跌？只有它跌的话，市场在定价什么？",
    "最近有没有公告、财报或新闻，是我还没读过的？",
    "我当初写下的核心逻辑，有哪一条被新的事实碰到了？",
    "反证条件里有没有哪一条已经命中了？",
    "如果今天第一次看到这家公司，我还会按这个价格带买吗？",
)


def trigger_note(band: str, price: float) -> str:
    label = BAND_LABELS.get(band, band)
    head = f"价格 {price:g} 进入{label}。"
    if band == "extreme":
        return head + "**这一段是强制重新检查**：跌到明显低估区的原因，往往正是让它不再值这个价的原因。"
    return head + "这不是买入信号，是重新看一眼的信号。"
