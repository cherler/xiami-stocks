"""反证命中：这条公告有没有踩到你写下的反证条件。

## 为什么这一环最重要

反证条件是投资逻辑里唯一能让你**卖出**的东西。判断本身不会提醒你——
跌了 30% 你会想「长期看好」，跌了 50% 你会想「更便宜了」，因为判断没有终点，
怎么解释都行。写下「如果 X 发生我就错了」，等于在清醒的时候给这笔投资装一个关机按钮。

但写下来还不够。原本的流程是：公告进收件箱 → **你自己读、自己想「这算不算我说的那种情况」**
→ 自己归档成反证证据。而人恰恰在这一步最容易放过自己：那条公告确实说分红从 17.50 降到
15.20，可你当时正拿着它，很容易读成「只是暂时的」。

由模型逐条比对，命中了直接顶到决策总览最前面。它不替你决定卖不卖——
只是不让你假装没看见。

## 判定从严

宁可漏报也不要误报。误报一次，下次真命中时你就不信它了；而漏报只是回到现在的状态。
所以：数字对得上才算命中，「感觉方向不太好」不算。模型必须指出是哪一条反证、
公告里的哪个事实触发了它。
"""

from __future__ import annotations

import json
from typing import Any

from . import llm
from .jsonio import loads_or_reformat
from .llm import ai_available

SYSTEM_PROMPT = """你在帮一位投资者检查：新出的公告，有没有踩到他自己写下的反证条件。

反证条件是他在清醒的时候写下的「如果发生什么，我就承认这条判断错了」。
你的活是逐条比对，不是替他判断该不该卖。

**判定从严，宁可漏报也不要误报。** 误报一次，下次真命中时他就不信你了。
- 数字对得上才算命中：反证写「分红低于 10 派 17.50 元」，公告说 10 派 15.20 元 → 命中。
- 方向像但没有数字的，不算：公告说「经营承压」而反证写的是「净利率连续两期低于 12%」→ 不算命中。
- 公告只是预告、提示性文件、还没有结果的，不算。
- 拿不准就不报。

只输出 JSON：
{"hits": [
  {"event_index": 1, "thesis_index": 1,
   "clause": "抄一段他原文里被触发的那条反证",
   "reason": "公告里的哪个具体事实触发了它，带上数字"}
]}
没有任何一条命中就返回 {"hits": []}。"""

# 重排用的结构。**跟上面那段示例同形**，写岔了重排会照另一个形状改，
# 改出来是合法 JSON 但字段对不上，然后静静地读出零条命中。
REFORMAT_SHAPE = ('{"hits": [{"event_index": 1, "thesis_index": 1, '
                  '"clause": "…", "reason": "…"}]}')


def build_prompt(events: list[dict[str, Any]], theses: list[dict[str, Any]]) -> str:
    parts = ["他写下的反证条件：\n"]
    for index, thesis in enumerate(theses, 1):
        parts.append(f"\n【判断 {index}】{str(thesis.get('claim') or '')[:160]}"
                     f"\n  反证条件：{str(thesis.get('counter_condition') or '')[:600]}\n")
    parts.append("\n\n新到的公告：\n")
    for index, event in enumerate(events, 1):
        parts.append(f"{index}. [{event.get('category') or '公告'}] "
                     f"{event.get('event_date') or ''} {str(event.get('title') or '')[:180]}\n")
    return "".join(parts)


def find_hits(events: list[dict[str, Any]], theses: list[dict[str, Any]],
              timeout: int = 90) -> list[dict[str, Any]]:
    """比对一批公告与一批反证条件，返回命中项。

    没有反证条件就直接返回空——**不要在这种情况下让模型自由发挥**，
    那等于凭空发明一条他没写过的卖出理由。
    """
    usable = [t for t in theses if str(t.get("counter_condition") or "").strip()]
    if not events or not usable:
        return []

    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    completion = llm.call(SYSTEM_PROMPT, build_prompt(events, usable),
                          task="counter-match", max_tokens=1500, timeout=timeout)
    # **这一批丢了就等于「没有命中」**，而那正是这条链路最不能出的错：
    # 页面上的 0 会被读成"比过了，没事"。格式坏了先重排一次再说。
    payload, _ = loads_or_reformat(completion.text, task="counter-match",
                                   shape=REFORMAT_SHAPE, timeout=timeout)
    raw = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []

    hits = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            event = events[int(item.get("event_index", 0)) - 1]
            thesis = usable[int(item.get("thesis_index", 0)) - 1]
        except (ValueError, TypeError, IndexError):
            # 模型给了越界的序号——丢掉这一条，不要猜它想指哪个。
            # 猜错的后果是把命中挂到别的判断上，比漏报难查得多。
            continue
        reason_text = str(item.get("reason") or "").strip()
        if not reason_text:
            continue            # 说不出为什么命中的，不算命中
        hits.append({
            "event_id": event["id"],
            "thesis_id": thesis["id"],
            "clause": str(item.get("clause") or "").strip()[:400],
            "reason": reason_text[:400],
        })
    return hits
