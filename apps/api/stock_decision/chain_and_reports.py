"""经营关系线索与研究报告——两个都靠模型生成，但依据完全不同，所以边界也不同。

**经营关系线索**用的是模型的世界知识（谁可能是供应方、客户或对手），这是本项目里唯一一处依据不是
本地档案的地方。所以每一条关系都强制标成"待证实"，并且必须写出**该去哪份公开文件里核对它**。
不做这个标记，模型记错的供应商关系会和交易所披露的事实长得一模一样，那就毁掉整个档案的可信度。

**研究报告**相反：只准用已经归档的证据，每句话都要挂上证据编号。模型在这里的角色是复述与
归纳，不是补充。查不到就写"档案里没有"。
"""

from typing import Any

from . import llm
from .jsonio import loads_or_reformat
from .llm import ai_available

RELATIONS = ("上游供应", "下游客户", "同业对手", "替代方案")

# 图上一个节点放得下的字数。超过就不再是名字，是一句话。
_NODE_LABEL_LIMIT = 12


def node_label(counterpart: str) -> str:
    """把一栏 counterpart 压成图上放得下的短名。

    **提示词管不住这件事。** 要求"不超过 12 字、一条只写一个"之后，模型仍然会
    回「再保险公司（如中国再保、瑞士再保、慕尼黑再保）」「个人客户（寿险、产险、
    健康险投保人）」这样的东西——库里现有的 16 条全是这个样子。
    而只要 counterpart 是一段描述，这一页就画不成图，只能退回成一串文字，
    那正是它原来的毛病。

    所以在读取时统一派生：**存量数据不用迁移也能画成节点**，
    完整原文仍然摆在卡片里，一个字都不丢。

    切法是按"名字通常写在最前面"来的：先在括号处断（括号里多半是举例），
    再在顿号/逗号处断（那是并列清单），最后才硬截。
    """
    text = counterpart.strip()
    # **要判断分隔符在不在**，不能无脑 split 后 break —— 第一版就是这么写的，
    # 结果任何字符串都在第一个分隔符上"切完了"，后面的规则一条都轮不到。
    for separator in ("（", "(", "：", ":", "、", "，", ",", "/"):
        if separator in text:
            head = text.split(separator, 1)[0].strip()
            if head:
                text = head
                break
    if len(text) > _NODE_LABEL_LIMIT:
        text = text[:_NODE_LABEL_LIMIT] + "…"
    return text or counterpart[:_NODE_LABEL_LIMIT]

CHAIN_SYSTEM_PROMPT = """你在为一位 A 股个人投资者整理一家公司的经营关系线索。

这不是产业链地图。你只列出值得进一步核验的供应、客户、竞争和替代线索；
产品与服务为核心的产业链底图由另一套资料化工具维护。

这是你唯一被允许使用自身知识的场合，但因此有更严的要求：

1. 每一条关系都要写清楚**去哪里核对**：年报的哪一节、招股书、行业协会数据，还是公司官网。写不出核对位置的关系不要给。
2. 不要给市场份额、销售额占比这类具体数字——你的记忆里的数字很可能过期或错误。只描述定性关系。
3. 只给你有把握的关系。宁可给 3 条扎实的，也不要给 10 条似是而非的。
4. 关系类型只能是：上游供应、下游客户、同业对手、替代方案。
5. 不判断这条关系对股价是好是坏，不给投资建议。

6. **counterpart 必须是一个短名字，不超过 12 个字，而且一条只写一个。**
   写「再保险公司」，不要写「再保险公司（如中国再保、瑞士再保、慕尼黑再保）」；
   要写多个就拆成多条。这一栏是图上的一个节点，塞进一串顿号分隔的清单，
   图就退化成了一段文字——而那正是这一页原来的样子。
   补充说明写进 detail，那一栏不限长度。
7. 已上市的对方，尽量在 symbol 里给出 6 位 A 股代码；不确定就留空，**不要猜**。

只输出 JSON 数组，每项形如：
{"relation": "上游供应", "counterpart": "不超过12字的名称", "symbol": "600036 或留空",
 "segment": "这个环节做什么", "detail": "关系是什么，可以写长",
 "verify_at": "该去哪份公开文件的哪一节核对"}"""

# 重排用的结构，跟上面那行示例同形。
CHAIN_SHAPE = ('[{"relation": "上游供应", "counterpart": "…", "symbol": "600036", '
               '"segment": "…", "detail": "…", "verify_at": "…"}]')

REPORT_SYSTEM_PROMPT = """你在把一家公司已经归档的资料整理成一份研究简报。

严格遵守：
1. **只能使用用户消息里给出的编号资料**。绝对不要补充任何来自你自身知识的事实、数字或事件。
2. 每一个陈述后面都要标注它依据的资料编号，形如 [3] 或 [1][4]。没有编号支撑的句子不许写。
3. 不给目标价、不给买卖时点、不给评分、不写建议买入/卖出。
4. 资料没有覆盖到的方面，写进 unknowns，不要绕过去。
5. 用中文，平实叙述，不用研报套话。

这四节各写成一个字段，每节都是**一句一条**的短句数组，**每节最多 12 条**，
不要写成整段。一段话里塞五个陈述，读的人得自己拆；拆成条，一眼能看出有几件事、
哪件不成立。

只输出一个 JSON 对象：
{"title": "简报标题",
 "business": ["这家公司在做什么，一句一条，每条带 [编号]"],
 "changes": ["最近发生了什么变化"],
 "implications": ["这些变化指向什么"],
 "citations": [{"ref": 1, "label": "这条资料的来源与日期"}],
 "unknowns": ["资料没覆盖、还没有答案的问题"]}"""

# 重排用的结构，跟上面那段示例同形。
REPORT_SHAPE = ('{"title": "…", "business": ["…"], "changes": ["…"], '
                '"implications": ["…"], "citations": [{"ref": 1, "label": "…"}], '
                '"unknowns": ["…"]}')


def _call_model(system: str, user: str, max_tokens: int, timeout: int, task: str) -> str:
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)
    return llm.call(system, user, task=task, max_tokens=max_tokens, timeout=timeout).text


def model_name() -> str:
    return llm.model_name()


def map_supply_chain(company: dict[str, Any], timeout: int = 150) -> list[dict[str, Any]]:
    import json

    profile = company.get("profile") or {}
    context = [f"公司：{company['name']}（{company['symbol']}），行业：{company.get('industry') or '未标注'}"]
    if profile.get("main_business"):
        context.append(f"主营业务：{str(profile['main_business'])[:400]}")
    if profile.get("business_scope"):
        context.append(f"经营范围：{str(profile['business_scope'])[:400]}")
    text = _call_model(CHAIN_SYSTEM_PROMPT, "\n".join(context), 2500, timeout, "supply-chain")
    links: list[dict[str, Any]] = []
    entries, _ = loads_or_reformat(text, task="supply-chain", expect="array",
                                   shape=CHAIN_SHAPE, timeout=timeout)
    for entry in entries:
        relation = entry.get("relation")
        counterpart = str(entry.get("counterpart") or "").strip()
        if relation not in RELATIONS or not counterpart:
            continue
        links.append(
            {
                "relation": relation,
                "counterpart": counterpart,
                "symbol": str(entry.get("symbol") or "").strip()[:8],
                "segment": str(entry.get("segment") or "")[:120],
                "detail": str(entry.get("detail") or "")[:400],
                # 依据是模型知识而不是本地档案，所以一律待证实
                "confidence": "待证实",
                "source": f"模型 {model_name()} 推断 · 核对位置：{str(entry.get('verify_at') or '未指明')[:120]}",
            }
        )
    return links


def write_report(company: dict[str, Any], sources: list[dict[str, Any]], timeout: int = 200) -> dict[str, Any]:
    import json

    if not sources:
        raise RuntimeError("这家公司还没有归档任何证据，没有可以引用的资料")
    # 编号用调用方给的 ref，不用这里的 enumerate —— 两处各编一次，
    # 只要上游筛掉过一条，正文里的 [3] 就会指到另一条资料上，
    # 而这种错完全看不出来：编号仍然存在，指向的东西是错的。
    listing = "\n".join(
        f"[{item.get('ref', index + 1)}] {item['label']}｜{item['text'][:400]}"
        for index, item in enumerate(sources)
    )
    prompt = (
        f"公司：{company['name']}（{company['symbol']}），行业：{company.get('industry') or '未标注'}\n\n"
        f"已归档的资料共 {len(sources)} 条：\n{listing}"
    )
    text = _call_model(REPORT_SYSTEM_PROMPT, prompt, 4000, timeout, "report")
    payload, _ = loads_or_reformat(text, task="report", shape=REPORT_SHAPE, timeout=timeout)
    sections = {key: _lines(payload.get(key)) for key in ("business", "changes", "implications")}
    return {
        "title": str(payload.get("title") or f"{company['name']}研究简报").strip(),
        **sections,
        # body 仍然存：导出、备份和老版本前端在读它。它由三节拼出来，
        # 而不是反过来——**拼平的方向只能有一个**，否则两边迟早对不上，
        # 而当它们对不上时，页面显示的和导出的会是两份不一样的简报。
        "body": _as_body(sections) or str(payload.get("body") or "").strip(),
        "citations": payload.get("citations") or [],
        "unknowns": [str(x) for x in (payload.get("unknowns") or [])],
        "source_count": len(sources),
        "model": model_name(),
    }


_SECTION_TITLE = {"business": "这家公司在做什么", "changes": "最近发生了什么变化",
                  "implications": "这些变化指向什么"}


def _lines(value: object) -> list[str]:
    """模型偶尔会把一节写成一整段而不是数组——那种时候按行拆，别整段丢掉。

    **12 这个上限同时写在提示词里。** 只在这一头切的话，模型写了 15 条、
    页面只显示 12 条 —— 被切掉的三条不报错、不留痕，而它们的钱已经付过了。
    （2026-08-16 主动排查「同一个概念写了两份」时抓到的第二处；
    第一处是深度报告，见 deep_report.SYSTEM_PROMPT 里那几个「最多」。）"""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()][:12]
    text = str(value or "").strip()
    return [line.strip("-· ").strip() for line in text.splitlines() if line.strip()][:12]


def _as_body(sections: dict[str, list[str]]) -> str:
    parts = [f"## {_SECTION_TITLE[key]}\n" + "\n".join(f"- {line}" for line in lines)
             for key, lines in sections.items() if lines]
    return "\n\n".join(parts)


BRIEFING_SYSTEM_PROMPT = """你在给一位业余的 A 股个人投资者写今天的决策简报。他打开研究台第一眼看的就是这一页。

这份简报要回答的只有一个问题：**今天有什么变化，可能影响他已经写下的判断**。不回答大盘会怎么走、该买什么、该不该加减仓。

严格遵守：
1. 只使用用户消息里给出的数据。绝对不要补充任何行情、新闻、宏观判断或行业观点。
   资料没覆盖的，写进 gaps，不要绕过去。
2. **不预测走势**：不写"或将""有望""预计上涨/回调"这类词。市场宽度只描述当天的分布，不指向明天。
3. 不给目标价、不给买卖时点、不给仓位建议、不给评分。
4. 每一段都要落到具体的公司、数字或事项上；写不出具体的就不写那一段。
5. 用中文，平实叙述，不用研报套话，不用感叹句。
6. **值里不要使用英文双引号**；需要引用公告标题或说法时用「」，否则会破坏 JSON。

**不要复述数字。** 涨跌家数、中位数、行业涨跌幅、持仓成本与浮盈，页面已经
按同一份数据画成图了；你再抄一遍既没有新信息，抄错了还会跟图对不上。
你的职责是说**这些数意味着什么**——每块两三句，直接讲判断，不铺垫。

按这四块写：
- market：今天这个分布对"该看哪些"有没有影响。**不要重复涨跌家数与中位数**。
- holdings：持仓与投资逻辑里，哪些出现了需要重新检查的信号。没有就直说没有。
- pending：待处理的事项里，哪几件最该今天看，为什么。
- watchlist：研究池里有什么值得今天推进一步的。

只输出一个 JSON 对象：
{"headline": "一句话概括今天最该看的一件事", "market": "…", "holdings": "…", "pending": "…", "watchlist": "…",
 "actions": ["今天可以做的具体动作，每条都要指向本站的某个页面或某家公司"], "gaps": ["资料没覆盖、但会影响判断的部分"]}"""

# 重排用的结构，跟上面那行示例同形。
BRIEFING_SHAPE = ('{"headline": "…", "market": "…", "holdings": "…", "pending": "…", '
                  '"watchlist": "…", "actions": ["…"], "gaps": ["…"]}')


def write_briefing(context: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    import json

    lines = [f"日期：{context['as_of']}"]
    breadth = context.get("breadth") or {}
    if breadth.get("covered"):
        lines.append(
            f"今日全市场：上涨 {breadth['advancing']} 家、下跌 {breadth['declining']} 家、平盘 {breadth['unchanged']} 家，"
            f"涨跌幅中位数 {breadth['median_change']}%，覆盖 {breadth['covered']} 只"
        )
    else:
        lines.append("今日全市场涨跌分布：底座里没有当日行情")
    if context.get("industries"):
        lines.append("行业当日涨跌中位数（仅列首尾）：" + "；".join(
            f"{item['name']} {item['metric_value']}%" for item in context["industries"]))
    if context.get("positions"):
        lines.append("持仓：" + "；".join(
            f"{item['name']}（{item['symbol']}）成本 {item['average_cost']}、现价 {item['latest_price']}、浮动 {item['unrealized_pct']}%"
            for item in context["positions"]))
    else:
        lines.append("持仓：账本里没有持仓记录")
    if context.get("theses"):
        lines.append("已写下的投资逻辑：" + "；".join(
            f"{item['company']}「{item['claim'][:80]}」当前状态 {item['status']}，反证条件：{item['counter'][:80] or '未写'}"
            for item in context["theses"]))
    else:
        lines.append("投资逻辑：一条都还没写")
    lines.append(f"待复核事项：{context['pending_events']} 件；待核验公告：{context['inbox_pending']} 条")
    if context.get("recent_announcements"):
        lines.append("最近的实质性公告：" + "；".join(
            f"{item['company_name']} {item['event_date']} {item['title'][:50]}" for item in context["recent_announcements"]))
    if context.get("watchlist"):
        lines.append("研究池里还没写逻辑的公司：" + "、".join(context["watchlist"]))

    text = _call_model(BRIEFING_SYSTEM_PROMPT, "\n".join(lines), 3000, timeout, "briefing")
    payload, _ = loads_or_reformat(text, task="briefing", shape=BRIEFING_SHAPE, timeout=timeout)
    return {
        "headline": str(payload.get("headline") or "").strip(),
        "market": str(payload.get("market") or "").strip(),
        "holdings": str(payload.get("holdings") or "").strip(),
        "pending": str(payload.get("pending") or "").strip(),
        "watchlist": str(payload.get("watchlist") or "").strip(),
        "actions": [str(x) for x in (payload.get("actions") or [])],
        "gaps": [str(x) for x in (payload.get("gaps") or [])],
        "model": model_name(),
        "boundary": (
            "这份简报只重述你库里已有的数据，不含任何行情预测、目标价与买卖建议。"
            "它回答的是「今天有什么变化可能影响你已经写下的判断」，不回答「明天会涨还是会跌」。"
        ),
    }
