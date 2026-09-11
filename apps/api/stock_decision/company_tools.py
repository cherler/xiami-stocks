"""一家公司的只读工具集：让模型自己决定要看什么，而不是我们替它挑好。

## 为什么要有这一层

11 个花积分的动作里，10 个是**单次问答**：我们在代码里挑好一份资料塞给模型，
它读完写一段话。挑什么由我们决定，而我们只能挑一份"通用"的——
于是每家公司喂进去的东西都一样。

后果最清楚的是起草投资逻辑。实测茅台那条草稿写的是
「估值分位极低（PE 7.8% 分位）+ 现金含量好」——**没有一句关于这门生意**。
不是模型不会写，是它看不到：合同负债（白酒最硬的领先指标）、分部构成、
同行位置、管理层承诺、公告正文，一样都不在那 2331 字的提示词里。

塞进去也不行。全塞是几万字，而其中绝大部分对某一家公司是废话——
**茅台要看合同负债，银行要看拨贷比，地产要看已售未结转**，
哪个有用取决于是哪家公司，只有模型知道它此刻缺什么。

所以给工具，让它自己要。

## 三条边界

1. **全部只读。** 没有一个工具能写库。
2. **全部钉死在一家公司上。** 工具不接受 company_id 参数——模型没有办法
   去查别家公司，更没有办法去查别人的数据。这是隔离的底线，不靠提示词守。
3. **参数尽量少。** 参数越多模型越容易传错，而传错的后果不是报错，
   是查了一张空表然后照样断言。

## 不是所有动作都该改成工具循环

收件箱分级、资讯匹配、证据极性、认错条件命中——这几个是**高频、单事实进、
一个标签出**。给它们工具循环只会让每条公告多花几倍的钱和时间，
换不回任何东西：要判断的那件事就在那一句话里，没有别的可查。

候选打分、批量评语同理。承诺抽取刚按"读正文+分批"重做过，形状也不是工具循环。

**该改的是那些「要看什么取决于是哪家公司」的动作**：起草投资逻辑、方法体检。
这个判断写在这里，是为了下次有人想把剩下几个也改掉时，先看到这段话。
"""

from __future__ import annotations

from typing import Any, Callable


def specs() -> list[dict[str, Any]]:
    """给模型看的工具清单。"""
    return [
        {"name": "financials", "description":
            "这家公司的定期报告：营业收入、净利润、经营现金流、总资产、负债、ROE 估算。"
            "按报告期从旧到新。annual_only 传 true 只看年报（推荐，累计口径的季报不可比）。",
         "input_schema": {"type": "object", "properties": {
             "annual_only": {"type": "boolean", "description": "只看年报，默认 true"},
             "limit": {"type": "integer", "description": "最多返回几期，默认 12"}}}},
        {"name": "industry_metrics", "description":
            "这门生意该盯的那几个数（白酒的合同负债占收入、银行的拨贷比、地产的已售未结转），"
            "外加收现比、对上游占款、研发强度。每条带公式和历年序列。",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "segments", "description":
            "最新年报的分部构成：按产品/行业/地区分的收入占比与毛利率。",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "valuation", "description":
            "估值：当前市盈率市净率、历史分位，以及使用者自己写过的三情景估值假设。",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "announcements", "description":
            "已归档的公司公告与大事，从新到旧。**这里只有标题**——"
            "要看某一条写了什么，用 announcement_text。",
         "input_schema": {"type": "object", "properties": {
             "limit": {"type": "integer", "description": "最多几条，默认 25"}}}},
        # #41 做完之后才有的工具。**这是这一层最值钱的一个**：
        # 「关于股份回购进展情况的公告」这十四个字里没有信息，
        # 信息在「不低于 50 亿元」「不超过 12 个月」里。
        {"name": "announcement_text", "description":
            "读某一条公告的正文原文。先用 announcements 拿到标题和日期，"
            "再用这里读它写了什么。一次读一条，读之前先想清楚为什么是这条。",
         "input_schema": {"type": "object", "properties": {
             "event_date": {"type": "string", "description": "公告日期 YYYY-MM-DD"},
             "title_contains": {"type": "string", "description": "标题里的关键词，用来定位是哪一条"}},
             "required": ["title_contains"]}},
        {"name": "theses", "description":
            "使用者自己写下的投资逻辑、认错条件，以及归档的支持证据与反证证据。"
            "**先看这个**——他已经想过什么、已经写下什么认错条件，决定了你该补哪一块，"
            "而不是从头泛泛地评价这家公司。",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "promises", "description":
            "管理层承诺台账：公司说过的话、到期日、核对结果。",
         "input_schema": {"type": "object", "properties": {}}},
        {"name": "peers", "description": "同行对照：同行业公司的估值与盈利指标。",
         "input_schema": {"type": "object", "properties": {}}},
    ]


# ------------------------------------------------------------------ 工具循环

def row_count(payload: Any) -> int:
    """这次工具调用返回了多少行。摆给使用者看的——「查了 3 次库、各多少行」
    是"它没瞎说"最直接的证明。"""
    if isinstance(payload, dict):
        # 键名要覆盖到所有工具的返回形状。少一个不会报错，
        # 只会让「查了几行」显示成 1 —— 而那正是使用者用来判断"它有没有真查"的数。
        for key in ("rows", "periods", "items", "points", "theses", "promises"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return 1 if payload and "error" not in payload else 0
    if isinstance(payload, list):
        return len(payload)
    return 0


def run_loop(system: str, messages: list[dict[str, Any]],
             runner: Callable[[str, dict[str, Any]], Any], *,
             task: str, max_rounds: int, max_tokens: int = 3000,
             timeout: int = 180) -> dict[str, Any]:
    """跑一轮"模型自己查库"的循环，直到它不再要工具为止。

    **反方 Agent 和起草投资逻辑共用这一份。** 各写一份的话，两边的轮次上限、
    工具报错处理、跑满之后怎么办会立刻分叉——而"跑满了怎么办"恰好是
    最容易写错、也最看不出来写错了的那一处。

    返回 {"text", "tool_calls", "payloads", "messages", "billing", "exhausted"}。
    exhausted 为真表示**跑满轮次还在查**，调用方必须把这件事说出来：
    半截结果看起来跟完整结论一模一样。
    """
    import json

    from . import llm

    tool_specs = specs()
    tool_calls: list[dict[str, Any]] = []
    payloads: list[Any] = []
    billing: dict[str, Any] = {}

    for _round in range(max_rounds):
        reply = llm.call_tools(system, messages, tool_specs,
                               task=task, max_tokens=max_tokens, timeout=timeout)
        billing = reply["completion"].billing()
        blocks = reply["content"]
        messages.append({"role": "assistant", "content": blocks})

        uses = [b for b in blocks if b.get("type") == "tool_use"]
        if not uses:
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return {"text": text, "tool_calls": tool_calls, "payloads": payloads,
                    "messages": messages, "billing": billing, "exhausted": False}

        results = []
        for use in uses:
            name = use.get("name") or ""
            try:
                payload = runner(name, use.get("input") or {})
            except Exception as exc:  # noqa: BLE001
                # 工具挂了就如实告诉模型，让它换一条路——**不要伪造一个空结果**，
                # 空结果会被读成"查过了，没有数据"，然后它据此断言。
                payload = {"error": f"这个工具这次没跑成功：{exc}"}
            payloads.append(payload)
            tool_calls.append({"tool": name, "input": use.get("input") or {},
                               "rows": row_count(payload)})
            results.append({"type": "tool_result", "tool_use_id": use.get("id"),
                            "content": json.dumps(payload, ensure_ascii=False, default=str)[:12000]})
        messages.append({"role": "user", "content": results})

    # 跑满了还在查。**不要把半截结果当成答案。**
    return {"text": "", "tool_calls": tool_calls, "payloads": payloads,
            "messages": messages, "billing": billing, "exhausted": True}
