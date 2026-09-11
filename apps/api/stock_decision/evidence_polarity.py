"""证据往哪个方向走：支持、削弱，还是中性。

## 为什么要有这个

库里 855 条证据，853 条是 neutral、0 条挂在任何一条投资逻辑上。
画成时间轴就是一条平线——不是图有问题，是数据还没有方向。
而没有方向的"证据"，堆再多也只是一份公告存档，回答不了唯一要紧的那个问题：
**我写下那条判断之后，事实是在往它那边走，还是在反着走。**

## 判断的单位是事件，不是文档

这是第一版差点做错的地方。规则把 609/855 条判成"高相关"，看上去像是有 609 条
实质证据可判。实际抽样一看，8 条里 5 条是**同一次股权激励**拆出来的文件：
草案、考核管理办法、薪酬委员会核查意见、激励对象名单、律师事务所法律意见书。

一次公司行为产生五到九份文档。按文档判，等于把同一件事判五遍，
花五倍的钱，还会在时间轴上同一天堆出五个点——**看起来像是那天发生了五件事**。

所以先归并：同一家公司、同一天、同一个主题算一件事，取标题最短的那份作代表
（拆出来的配套文件名字都更长：「……的法律意见书」「……的核查意见」）。
实测 855 份文档归并成 732 件事，茅台那 103 份归并成几十件。

## 相对于什么判方向

**相对于这家公司自己写下的投资逻辑。** 不是相对于"股价会涨吗"——那是预测，
本站不做。「分红率提高」对一条"靠稳定分红拿回报"的判断是支持，对一条
"靠产能扩张成长"的判断反而是削弱（钱分掉了就不能用来扩产）。
脱离判断谈利好利空是没有意义的，也正是这类页面最容易变成噪音的地方。

没有写过投资逻辑的公司**不判**，直接返回并说明原因——那种情况下模型只能
按"一般来说是好事吗"来答，而那恰恰是本站承诺不做的事。

## 说不出理由的不算

跟反证匹配同一条规矩：判了方向却写不出依据的，退回中性。
一个没有理由的"削弱"会让人白紧张一场，而下一次真的削弱时他就不信了。
"""

from __future__ import annotations

from typing import Any

from . import llm
from .classification import classify_by_rules
from .jsonio import loads_lenient
from .llm import ai_available

# 一次送多少件。太大模型会开始糊弄（后面几条给一样的理由），
# 太小则调用次数上去、钱花在重复的系统提示上。
BATCH = 12

DIRECTIONS = {"支持": "support", "削弱": "counter", "中性": "neutral"}

SYSTEM_PROMPT = """你在判断一批已经归档的公司公告，对这家公司**已经写下的投资逻辑**是支持还是削弱。

严格遵守：
1. **只相对于给出的那条判断来判方向**，不要判"对股价是利好还是利空"。
   同一件事对不同的判断方向可以相反：分红率提高，对"靠稳定分红拿回报"是支持，
   对"靠产能扩张成长"是削弱——钱分掉了就不能用来扩产。
2. 只依据公告标题本身。标题里看不出来的，一律判"中性"，不要靠常识补。
3. **说不出依据就判中性。** 理由必须指向标题里的具体字眼，不能写"总体利好"这类话。
4. 不预测走势、不给买卖建议、不给评分。
5. 用中文，理由一句话，不超过 40 字。
6. **值里不要使用英文双引号**；需要引用公告里的说法时用「」。
   引号会把 JSON 字符串截断，一次没听话整批就白跑了。

只输出一个 JSON 对象：{"items": [{"index": 1, "direction": "支持|削弱|中性", "reason": "依据标题的哪几个字"}]}
index 是给你的那份清单里的序号，每条都要出现一次。"""


def cluster(evidences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把同一家公司同一天同一主题的多份文档归并成一件事。

    代表取标题最短的那份：拆出来的配套文件名字总是更长
    （「……的法律意见书」「……关于……的核查意见」），最短的那个通常就是主文件。
    """
    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for item in evidences:
        grade = classify_by_rules(item["excerpt"])
        if grade["relevance"] == "低":
            continue                       # 程序性文件不占额度，也不该出现在方向轴上
        key = (item["company_id"], str(item["occurred_at"])[:10], grade["topic"])
        buckets.setdefault(key, []).append(item)

    events: list[dict[str, Any]] = []
    for (company_id, day, topic), group in buckets.items():
        lead = min(group, key=lambda x: len(x["excerpt"]))
        events.append({
            "company_id": company_id,
            "day": day,
            "topic": topic,
            "title": lead["excerpt"],
            "lead_id": lead["id"],
            # 同一件事的全部文档都要一起改极性，否则时间轴上一天里
            # 会同时出现一个"支持"和四个"中性"，看着像五件事互相矛盾
            "evidence_ids": [x["id"] for x in group],
        })
    events.sort(key=lambda e: e["day"])
    return events


def estimate_credits(event_count: int) -> int:
    """跑之前先给个数。花钱的事要让人在点之前就知道大概多少。

    一批 12 件、每批约 1200 token 出头，按 ⌈tokens/5000⌉ 记，
    一批基本就是 1 个积分；不足一批也按一批算。
    """
    return max(1, -(-event_count // BATCH))


def _items(text: str) -> list[Any] | None:
    """从模型回的文本里取出条目清单。三种形状都要收。

    要 `{"items": [...]}` 的时候，模型实际会回：
    1. `{"items": [...]}`  —— 听话的那次
    2. `[{...}, {...}]`    —— 直接给数组，不给外层壳
    3. `{...},\n{...}`     —— 连数组括号都不给

    **先按数组解析，再退回对象。** 反过来会出事：loads_lenient 的 object 模式
    是"从第一个 { 切到最后一个 }"，喂给它一个数组，方括号会被切掉，
    只剩里面第一个对象——于是一整批只认下一条，而且完全不报错。
    实测就是这么丢的：74 件判得好好的，返回 0 件，钱照花。
    """
    for expect in ("array", "object"):
        try:
            payload = loads_lenient(text, expect=expect)
        except ValueError:
            continue
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            inner = payload.get("items")
            if isinstance(inner, list):
                return inner
            # 只回了一条、没套数组的情况
            if "index" in payload or "direction" in payload:
                return [payload]
    return None


# 重排用的结构，跟 SYSTEM_PROMPT 末尾那句同形。
REFORMAT_SHAPE = '{"items": [{"index": 1, "direction": "支持|削弱|中性", "reason": "…"}]}'


def _reformat_items(text: str, timeout: int) -> list[Any] | None:
    """把原文递回去只改格式，再按三种形状解一遍。修不好就返回 None。"""
    from .jsonio import looks_truncated

    if looks_truncated(text):
        return None                      # 没写完，重排救不回来
    try:
        reply = llm.call(
            "把下面这段文字整理成合法 JSON。**只改格式，一个字的内容都不要改**："
            "不要补充、不要删减、不要重写措辞，也不要替它补上你觉得该有的字段。"
            f"只输出 JSON，不要围栏、不要解释。\n\n结构：\n\n{REFORMAT_SHAPE}",
            text, task="evidence-polarity", max_tokens=1400, timeout=min(timeout, 120))
    except Exception:                    # noqa: BLE001 —— 救不回来就按原样跳过这一批
        return None
    return _items(reply.text)


def judge(events: list[dict[str, Any]], thesis: dict[str, Any],
          timeout: int = 90) -> list[dict[str, Any]]:
    """判一批事件相对于这条判断的方向。"""
    if not events:
        return []
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    results: list[dict[str, Any]] = []
    for start in range(0, len(events), BATCH):
        chunk = events[start : start + BATCH]
        listing = "\n".join(
            f"[{index + 1}] {item['day']}　{item['title'][:80]}"
            for index, item in enumerate(chunk))
        prompt = (
            f"这条投资逻辑：{thesis['claim']}\n"
            + (f"它的反证条件：{thesis['counter_condition']}\n" if thesis.get("counter_condition") else "")
            + f"\n要判的公告共 {len(chunk)} 条：\n{listing}"
        )
        completion = llm.call(SYSTEM_PROMPT, prompt, task="evidence-polarity",
                              max_tokens=1400, timeout=timeout)
        raw = _items(completion.text)
        if raw is None:
            # **三种形状都试过还是修不好，再花一次调用让模型只重排格式。**
            #
            # 这一批的钱已经花了（一批 12 件），而重排不带资料、不重新判断，
            # 比重跑一批便宜一个数量级。上面 `_items` 的注释记着实测那次：
            # 74 件判得好好的、返回 0 件、钱照花 —— 这一步就是给那种情况兜底。
            #
            # 没写完（Truncated）不送去重排：重排一个字都不许加，救不回来。
            raw = _reformat_items(completion.text, timeout)
        if raw is None:
            # **一批修不好不该拖垮整次判断。** 前面几批可能已经判得好好的，
            # 为最后一批的格式问题把它们一起丢掉，用户看到的是"跑了很久、
            # 一条没出来"，而钱已经花掉了。跳过这一批，继续下一批。
            continue

        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                event = chunk[int(entry.get("index", 0)) - 1]
            except (ValueError, TypeError, IndexError):
                # 越界的序号丢掉，不猜它想指哪条 —— 猜错会把方向挂到别的事情上
                continue
            direction = DIRECTIONS.get(str(entry.get("direction") or "").strip())
            reason_text = str(entry.get("reason") or "").strip()[:120]
            # 说不出依据的一律退回中性。一个没有理由的"削弱"会让人白紧张一场，
            # 而下次真的削弱时他就不信了。
            if direction is None or (direction != "neutral" and not reason_text):
                direction, reason_text = "neutral", reason_text or "标题里看不出方向"
            results.append({
                **event,
                "polarity": direction,
                "reason": reason_text,
                "thesis_id": thesis["id"],
            })
    return results
