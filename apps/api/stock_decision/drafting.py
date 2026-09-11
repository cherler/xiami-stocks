"""用已同步的资料起草一条投资逻辑。

为什么这件事可以交给模型：投资逻辑的价值不在于"写它的人已经想明白了"，而在于**它先被写下来，
之后股价和基本面变化时才有一个可以对照的基准**。没有基准，看到跌 8% 就只能凭情绪反应。

为什么它仍然只是草稿：模型不认识你的风险承受度、持有期限和别的持仓。它能做的是把档案里已有的
事实组织成一句可以被证伪的话，以及一条你能真正核对的反证条件。判断对不对、要不要保存，是你的事。

硬边界（写进提示词，也在这里说明）：
- 只用传进去的事实。档案里没有的，写成"档案里没有"，不许从训练记忆里补。
- 不给目标价、不给买卖时点、不给评分、不说"建议买入/卖出"。
- 反证条件必须能用本站已经同步的字段核对（财报科目、估值分位、公告类别），否则等于没写。
"""

from typing import Any

from . import llm
from .jsonio import Truncated, loads_or_reformat
from .llm import ai_available
from .methods import METHODS_BY_KEY

DRAFT_SYSTEM_PROMPT = """你在帮一位业余的 A 股个人投资者，把他研究台里已经同步到的公开资料，组织成一条可以被事实检验的投资逻辑草稿。

严格遵守：
1. 只使用用户消息里给出的事实。资料里没有的信息，明确写"档案里没有"，绝对不要凭记忆补充任何数字、事件或行业判断。
   **也不要自己做任何计算**：所有比率都已经由系统算好并标注了口径，你直接引用，不要自己去除。
2. 不给目标价，不给买入或卖出的时点，不给评分，不写"建议买入/持有/卖出"这类结论。
3. 判断要具体到可以被后续财报或公告推翻，不要写"公司基本面良好""长期看好"这种无法证伪的话。
4. 反证条件必须能用列出的可跟踪字段核对（财报科目、估值分位、公告类别），并且要写清楚数值门槛或方向。
5. 用中文，语气平实，不用营销词。
6. **值里不要使用英文双引号**；需要引用时用「」，否则会破坏 JSON。

7. **headline 必须能一口气读完**：一句话，最多四十个字，说清「赌的是什么」。
   把理由拆进 basis，不要堆在 headline 里——堆在一起没人看得出重点。
8. 每条反证条件是一个对象，指标、门槛、含义分开写。写成一段话的反证条件没法逐条核对，
   等于没写。
9. **counters 给二到四条，basis 给二到四条。** 实测给七条反证时里面有两条讲的是同一件事，
   而条目一多，人就不会逐条去查了——那等于回到没有反证的状态。挑最能证伪这条判断的那几条。

只输出一个 JSON 对象，不要任何解释文字：
{
  "headline": "一句话，最多四十字：这笔投资赌的是什么",
  "basis": [
    {"point": "支撑这条判断的一个要点", "evidence": "资料里的具体数值", "as_of": "哪一期／哪一天"}
  ],
  "counters": [
    {"metric": "要盯的指标（例如 净利率）", "threshold": "触发线（例如 连续两期低于 47.85%）",
     "means": "一旦触发说明什么（例如 品牌定价权在松动）"}
  ],
  "review": {"when": "什么时候复核（例如 2026 年中报，约 8 月底）",
             "what": ["到时候查哪几个数字"]},
  "used_facts": ["实际用到的事实，逐条抄自资料，不要改写数字"],
  "unknowns": ["写这条判断时缺少、但应该补上的信息"]
}"""


# 重排坏 JSON 时给模型看的目标结构。**跟上面 DRAFT_SYSTEM_PROMPT 里那一段同形** ——
# 两处写岔的话，重排会照着一个跟主提示词不一样的形状去改，改出来照样是合法 JSON，
# 只是字段对不上，然后 _shape 静静地读出一堆空值，谁也不会报错。
DRAFT_SHAPE = """{
  "headline": "…",
  "basis": [{"point": "…", "evidence": "…", "as_of": "…"}],
  "counters": [{"metric": "…", "threshold": "…", "means": "…"}],
  "review": {"when": "…", "what": ["…"]},
  "used_facts": ["…"],
  "unknowns": ["…"]
}"""


def _fact_lines(company: dict[str, Any]) -> tuple[list[str], list[str]]:
    """把公司档案压成事实清单与可跟踪字段清单。缺的就说缺，不补零。"""

    facts: list[str] = [f"公司：{company['name']}（{company['symbol']}），行业：{company.get('industry') or '未标注'}"]
    trackable: list[str] = []

    profile = company.get("profile") or {}
    if profile.get("main_business"):
        facts.append(f"主营业务（来自{profile.get('source', '公开资料')}）：{str(profile['main_business'])[:300]}")
    if profile.get("introduction"):
        facts.append(f"公司简介：{str(profile['introduction'])[:300]}")
    if profile.get("latest_dividend_plan"):
        facts.append(
            f"最近一期分红：{profile.get('latest_dividend_period') or ''} {profile['latest_dividend_plan']}"
            f"（股利支付率 {profile.get('latest_dividend_payout_ratio') or '未提供'}）"
        )

    if company.get("latest_price") is not None:
        facts.append(f"最新价 {company['latest_price']} 元，当日涨跌 {company.get('change_percent')}%")

    # 全市场底座那一行的估值与盈利指标。**候选体检全靠它**：候选没有档案、
    # 没同步过财务，而 PE / PB / ROE / 增速这些底座里本来就有——不喂进来的话，
    # 八个方法里六个会回「数据不足」，花了积分只换回一句"缺数据"。
    metrics = company.get("market_metrics") or {}
    filled = [f"{label} {value}" for label, value in metrics.items() if value is not None]
    if filled:
        facts.append("全市场底座最近一次同步的指标：" + "、".join(filled))
    if company.get("high_52w") is not None and company.get("low_52w") is not None:
        facts.append(f"52 周区间 {company['low_52w']} — {company['high_52w']} 元")

    valuation = company.get("valuation") or {}
    for metric in valuation.get("metrics", []):
        windows = [w for w in metric.get("windows", []) if w.get("percentile") is not None]
        if metric.get("current") is None:
            continue
        if windows:
            window = windows[-1]
            facts.append(
                f"{metric['label']}当前 {metric['current']}，处于近 {window['window_years']} 年 "
                f"{window['percentile']}% 分位（{window['sample_size']} 个样本，截至 {window['sample_end']}）"
            )
            trackable.append(f"{metric['label']}分位")
        else:
            facts.append(f"{metric['label']}当前 {metric['current']}，分位未计算（样本不足）")

    financials = company.get("financials") or {}
    if financials.get("latest_report_date"):
        facts.append(f"最新报告期 {financials['latest_report_date']}（{financials.get('latest_audit_status') or '状态未标注'}）")
    for metric in financials.get("metrics", []):
        if metric.get("value") is None:
            continue
        line = f"{metric['label']} {metric['value']}{metric.get('unit') or ''}（口径：{metric.get('basis') or '未标注'}）"
        if metric.get("previous_annual") is not None:
            line += f"，上一年度同口径 {metric['previous_annual']}{metric.get('unit') or ''}"
        facts.append(line)
        trackable.append(metric["label"])
    for warning in financials.get("warnings", []):
        facts.append(f"财务提示（{warning.get('level')}）：{warning.get('title')}——{warning.get('detail')}")

    profile_events = (profile.get("recent_events") or [])[:8]
    for event in profile_events:
        facts.append(f"近期{event.get('category')}：{event.get('event_date')} {event.get('title')}")
    if profile_events:
        trackable.append("公告类别（分红／解禁／业绩／股权变动）")

    missing = profile.get("missing_sections")
    if missing:
        facts.append(f"档案里缺失的部分：{missing}")

    return facts, list(dict.fromkeys(trackable))


def _method_keys(method_key: str | None) -> list[str]:
    """允许一次传多个方法（逗号分隔）。

    一条投资逻辑本来就该叠加几个方法看——方法库自己也这么说：
    「多数方法只覆盖判断的一个侧面」。先做完体检、挑出这家公司真正适用的那几个，
    再一起生成，比单挑一个方法写出来的判断完整得多。
    """
    if not method_key:
        return []
    keys = [k.strip() for k in str(method_key).split(",") if k.strip()]
    return [k for k in keys if k in METHODS_BY_KEY]


def build_prompt(company: dict[str, Any], method_key: str | None) -> tuple[str, list[str]]:
    facts, trackable = _fact_lines(company)
    parts = ["以下是这家公司在研究台里已经同步到的全部资料：\n", "\n".join(f"- {line}" for line in facts)]
    parts.append(
        "\n\n写反证条件时只能用这些可以持续跟踪的字段：\n"
        + ("、".join(trackable) if trackable else "（暂时没有可跟踪字段，请在 unknowns 里说明这一点）")
    )
    methods = [METHODS_BY_KEY[k] for k in _method_keys(method_key)]
    if len(methods) == 1:
        method = methods[0]
        parts.append(
            f"\n\n请按「{method.name}」这个方法的结构来组织。"
            f"\n这个方法的核心问题是：{method.core_question}"
            f"\n它的步骤是：{'；'.join(method.steps)}"
            f"\n它的已知盲区是：{method.caution or '（未记录）'}"
            "\n如果资料不足以支撑这个方法要求的判断，直接在 unknowns 里说明缺什么，不要编。"
        )
    elif methods:
        parts.append(f"\n\n请把下面这 {len(methods)} 个方法叠起来组织这条判断——"
                     "它们各覆盖一个侧面，不要只用其中一个，也不要写成几段并列的话，"
                     "要合成一条能被事实检验的主张：\n")
        for method in methods:
            parts.append(
                f"\n【{method.name}】核心问题：{method.core_question}"
                f"\n  步骤：{'；'.join(method.steps)}"
                f"\n  已知盲区：{method.caution or '（未记录）'}")
        parts.append("\n\n反证条件要覆盖到每个方法各自最可能被推翻的地方，"
                     "但合起来仍然是可以一条条去查的具体事实。"
                     "\n资料不足以支撑某个方法时，在 unknowns 里写明是哪个方法缺什么，不要编。")
    return "".join(parts), trackable


MAX_TOOL_ROUNDS = 8

# **第 1 条必须改口径。** 原话是「只使用用户消息里给出的事实」，
# 而工具版里事实是从工具返回里来的——不改的话它会认为查到的东西"不算给出的事实"
# 而拒绝使用，写出来一句「档案里没有」，白花一轮工具调用。
#
# 改的只是"事实从哪来"，**没有放松任何一条硬规矩**：不许用记忆补、不许自己算、
# 不给目标价、反证条件必须可核对，一条不动。
TOOL_SYSTEM_PROMPT = DRAFT_SYSTEM_PROMPT.replace(
    "1. 只使用用户消息里给出的事实。资料里没有的信息，明确写\"档案里没有\"，"
    "绝对不要凭记忆补充任何数字、事件或行业判断。",
    "1. 只使用**工具查回来的数据**和用户消息里给出的事实。两处都没有的信息，"
    "明确写\"档案里没有\"，绝对不要凭记忆补充任何数字、事件或行业判断。"
    "**查不到就说查不到**——查了一张空表然后照样断言，是这里最严重的错。",
    1)

# 工具版比塞好资料那版多的一段话。**只加"你可以自己查"，不放松任何一条硬规矩**——
# 能自己查库之后，编数字的诱惑更大而不是更小：查一次拿到几十个数，
# 随手多写一个看起来一样可信。
TOOL_PREAMBLE = """你可以自己查这家公司的库。**先查再写，不要凭手上这点资料就下笔。**

至少做到这几件事：
1. **先看使用者自己写过什么**（theses）。他已经想过的、已经写下的认错条件，
   决定了这条草稿该补哪一块。
2. **查这门生意该盯的那几个数**（industry_metrics）。白酒看合同负债、
   银行看拨贷比、地产看已售未结转——它们比通用的 PE、ROE 更早反映生意在变好还是变坏。
3. **看几年的序列，不要只看最新一期**（financials）。一个数字说明不了任何事，
   趋势才行。
4. 公告只看到标题不算看过。要用到某条公告时，用 announcement_text 读它的正文。

查完再写。**没查到的东西写进 unknowns，不要用记忆补。**
你查到的每个数字都会被代码回原始数据里核一遍，核不上的会被标出来给使用者看。
"""


def draft_with_tools(company: dict[str, Any], runner: Any,
                     method_key: str | None = None,
                     timeout: int = 180) -> dict[str, Any]:
    """让模型自己查库，再写这条草稿。

    ## 为什么不是"把资料塞得更全一点"

    塞不进去。全塞是几万字，而其中绝大部分对某一家公司是废话——
    **茅台要看合同负债，银行要看拨贷比**，哪个有用取决于是哪家公司。
    我们在代码里只能挑一份通用的，于是每家公司喂进去的东西都一样，
    写出来的判断也就都一样：实测茅台那条草稿是「估值分位低 + 现金好」，
    没有一句关于这门生意。

    ## 跑满轮次不当成写完

    跑满还在查说明它没收敛，这时候手上是半截资料。**半截资料写出来的判断
    跟完整资料写出来的长得一模一样**，而你会把它当成后者存进库。所以直接报错。
    """
    from .company_tools import run_loop

    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    prompt, trackable = build_prompt(company, method_key)
    messages = [{"role": "user", "content": TOOL_PREAMBLE + "\n\n" + prompt}]
    # 跟反方同一个取舍：宁可用不到，也不要被掐断（见 devils_advocate.MAX_ANSWER_TOKENS）。
    # 冻结额不跟这个数挂钩，所以填大不多花钱。
    result = run_loop(TOOL_SYSTEM_PROMPT, messages, runner,
                      task="thesis-draft", max_rounds=MAX_TOOL_ROUNDS,
                      max_tokens=100000, timeout=timeout)
    if result["exhausted"]:
        raise RuntimeError(
            f"查了 {MAX_TOOL_ROUNDS} 轮还没写出草稿，这次没有结果。"
            f"半截资料写出来的判断跟完整资料写出来的长得一样，所以宁可不给。"
            f"指定一个方法（而不是让它自己挑）通常就能收敛。")

    # **坏 JSON 不该让已经花掉的八轮打水漂。**
    #
    # 到这一行为止，查库那几轮是真调用、真计费；原来这里一抛 RuntimeError，
    # 使用者付了一整轮的钱，拿到一句 JSONDecodeError。
    # 所以先把原文还给模型，只让它重排格式（不带工具、不查库，
    # 比重跑一轮便宜一个数量级）。
    #
    # **但重排失败仍然抛，这一点跟反方 Agent 不一样。** 反方那边可以交一份
    # 「这次没有结论」出去，因为它的产出是给人读的建议；而这里的产出会被
    # 存进库当成一条投资逻辑 —— 一条空的或半截的草稿存进去，
    # 比一个报错糟得多（见 draft_thesis 里为什么不吞这类错）。
    try:
        draft, reformatted = loads_or_reformat(
            result["text"], task="thesis-draft", shape=DRAFT_SHAPE, timeout=timeout)
    except Truncated as exc:
        raise RuntimeError(f"草稿写到一半被长度上限截断了，这次没有结果：{exc}") from exc
    except (ValueError, RuntimeError) as exc:
        raise RuntimeError(f"模型写完了，但那段草稿不是合法 JSON，重排一次也没修好：{exc}") from exc

    out = _shape(draft, trackable, method_key)
    # **查了哪几张表要摆出来。** 这是"它没瞎说"最直接的证明，
    # 也是使用者判断这条草稿值不值得读的第一个信号。
    out["read"] = "、".join(f"{c['tool']}（{c['rows']} 行）" for c in result["tool_calls"])
    if reformatted:
        # 重排过要留痕。内容没动（重排只许改格式），但「这条草稿返过一次工」
        # 是使用者该知道的事 —— 哪句读着别扭，他知道先怀疑这里。
        out["read"] += "；草稿格式坏过一次，已自动重排（只改格式、不改内容）"
    return out


def draft_with_model(company: dict[str, Any], method_key: str | None = None, timeout: int = 120) -> dict[str, Any]:
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)
    model = llm.model_name()
    prompt, trackable = build_prompt(company, method_key)
    completion = llm.call(DRAFT_SYSTEM_PROMPT, prompt, task="thesis-draft",
                          max_tokens=2000, timeout=timeout)
    # 这条路只花了一次调用，比工具那条便宜得多；但重排仍然值得 ——
    # 重跑一次拿到的是**另一份草稿**，重排拿回的是原来那一份。
    try:
        draft, _ = loads_or_reformat(completion.text, task="thesis-draft",
                                     shape=DRAFT_SHAPE, timeout=timeout)
    except (ValueError, RuntimeError) as exc:
        raise RuntimeError(f"模型写完了，但那段草稿不是合法 JSON，重排一次也没修好：{exc}") from exc

    return _shape(draft, trackable, method_key)


def _shape(draft: dict[str, Any], trackable: list[str],
           method_key: str | None) -> dict[str, Any]:
    """把模型返回的东西收成页面要的形状。

    **两条路（塞资料 / 自己查库）共用这一份。** 各写一份的话，
    其中一条会悄悄少掉 unknowns 或 structure，而页面不会报错，只会少显示一块。
    """
    def _as_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if value else []

    structure = _structure(draft)
    return {
        # 平文本仍然生成：数据库那两列不动，逻辑与证据页的旧数据照样能读，
        # 结构化的那份额外给出去，页面优先按块渲染，没有就回落到平文本。
        "claim": _flat_claim(structure) or str(draft.get("claim") or "").strip(),
        "counter_condition": _flat_counters(structure) or str(draft.get("counter_condition") or "").strip(),
        "next_review_trigger": _flat_review(structure) or str(draft.get("next_review_trigger") or "手动复核").strip(),
        "structure": structure,
        "used_facts": _as_list(draft.get("used_facts")),
        "unknowns": _as_list(draft.get("unknowns")),
        "trackable_fields": trackable,
        "model": llm.model_name(),
        "method": "＋".join(METHODS_BY_KEY[k].name for k in _method_keys(method_key)) or None,
        "boundary": (
            "这是草稿，不是结论。它只用了档案里已同步的事实，没有目标价、没有买卖时点。"
            "保存之前请逐句核对——尤其是反证条件，那是它以后真正能提醒你的地方。"
        ),
    }


# ── 结构化 ────────────────────────────────────────────────────────────────
#
# **模型返回的本来就是结构，别再拍平成散文。** 之前 claim 和 counter_condition
# 各是一坨长文本，页面直接 <p>{text}</p> —— 四个方法叠出来的那条判断就是这么
# 变成一屏没有重点的字的。现在 headline / basis / counters / review 各自成块，
# 反证是可以逐条核对的清单而不是一段话。

def _structure(draft: dict[str, Any]) -> dict[str, Any]:
    """把模型返回的结构收干净。字段缺了就给空，不编。"""
    def text(value: Any, limit: int = 400) -> str:
        return str(value or "").strip()[:limit]

    basis = []
    for item in draft.get("basis") or []:
        if isinstance(item, dict) and text(item.get("point")):
            basis.append({"point": text(item["point"], 200),
                          "evidence": text(item.get("evidence"), 120),
                          "as_of": text(item.get("as_of"), 40)})
        elif text(item):
            basis.append({"point": text(item, 200), "evidence": "", "as_of": ""})

    counters = []
    for item in draft.get("counters") or []:
        if isinstance(item, dict) and (text(item.get("metric")) or text(item.get("threshold"))):
            counters.append({"metric": text(item.get("metric"), 60),
                             "threshold": text(item.get("threshold"), 160),
                             "means": text(item.get("means"), 200)})
        elif text(item):
            counters.append({"metric": "", "threshold": text(item, 160), "means": ""})

    # 提示词里要了二到四条，这里再兜一层：条目一多人就不会逐条去查，
    # 那等于回到没有反证的状态。截断而不是报错——模型多给了不是错误。
    basis = basis[:4]
    counters = counters[:4]

    review = draft.get("review") if isinstance(draft.get("review"), dict) else {}
    return {
        "headline": text(draft.get("headline"), 120),
        "basis": basis,
        "counters": counters,
        "review": {"when": text(review.get("when"), 120),
                   "what": [text(x, 120) for x in (review.get("what") or []) if text(x)]},
    }


# theses.claim 的长度上限（与 schemas.ThesisCreate 一致）。
# 拍平的结果必须塞得进去，否则后台写入会在最后一步被校验挡掉——
# 实测踩过：headline 加四条依据拼起来 600 多字，任务报 string_too_long。
_CLAIM_LIMIT = 500
_COUNTER_LIMIT = 500
_REVIEW_LIMIT = 200


def _flat_claim(structure: dict[str, Any]) -> str:
    """结构化字段拍平成一段话，存进 theses.claim。

    存平文本是为了不动数据库结构，也让还没升级的地方（导出、备份、修订史）
    照常工作。渲染时优先用结构，两者不会打架。

    **依据要能被截断。** headline 是判断本身，一个字都不能丢；依据是支撑，
    塞不下就少放几条——总比整条写入失败强。
    """
    headline = structure.get("headline") or ""
    if not headline:
        return ""
    parts = [headline]
    for item in structure.get("basis") or []:
        piece = item["point"]
        if item.get("evidence"):
            piece += f"（{item['evidence']}{'，' + item['as_of'] if item.get('as_of') else ''}）"
        candidate = "；".join([*parts, piece])
        if len(candidate) > _CLAIM_LIMIT:
            break
        parts.append(piece)
    return "；".join(parts)[:_CLAIM_LIMIT]


def _flat_counters(structure: dict[str, Any]) -> str:
    items = structure.get("counters") or []
    if not items:
        return ""
    out = []
    for index, item in enumerate(items, 1):
        piece = "、".join(x for x in (item.get("metric"), item.get("threshold")) if x)
        if item.get("means"):
            piece += f"——{item['means']}"
        out.append(f"{index}）{piece}")
    return " ".join(out)[:_COUNTER_LIMIT]


def _flat_review(structure: dict[str, Any]) -> str:
    review = structure.get("review") or {}
    if not review.get("when") and not review.get("what"):
        return ""
    what = "；".join(review.get("what") or [])
    return f"{review.get('when', '')}：{what}".strip("：")[:_REVIEW_LIMIT]
