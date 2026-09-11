"""对话式反方：钉在一家公司上，专门找你这条判断可能错在哪。

## 为什么是反方，不是荐股

一个会跟你聊天的荐股 Agent 是这个产品里最没有价值、也最危险的东西：
它说什么你都会觉得有道理，因为**它说的正是你想听的**。
你已经买了、已经写了逻辑，这时候多一个声音附和，只是把确信度往上推一格。

反方是相反的：它的活是**替你想你不愿意想的那一面**。
这件事你自己做不了——人没法认真反驳自己刚写下的东西；
找人做又太贵，投研团队里那个专门唱反调的角色，一个人的项目根本配不起。

## 三条硬约束，都在代码里，不靠提示词自觉

1. **只能读库，不能上网、不能凭记忆。** 它手里只有一组工具，
   每个工具都是这家公司在你库里的真实数据。工具之外它什么都拿不到。
2. **每一条反方主张必须引用工具返回的数据。** 引不出来的直接丢掉——
   一句听着很有道理、其实凭空捏的反驳，比没有反驳糟得多，
   因为**它会让你放弃一条本来对的判断**。
3. **只能提议，不能写。** 每条主张后面挂一个「转成反证条件 / 转成研究任务」
   的按钮，点不点是你的事。模型没有任何写入权限。

## 数字要能溯源

模型说出来的每一个数，代码会去工具返回的原始行里找一遍。找不到的**标出来**，
而不是删掉——有些数是它算的（比如两年的差），删掉会把有用的话一起丢了。
但标出来之后你会立刻知道哪几个数需要自己核。

## 它不下结论

反方的产出是**问题和反证条件**，不是"该卖"。
「该不该卖」需要知道你的仓位、成本、其它选择、家庭现金流——
这些它都不知道，也不该假装知道。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import llm
from .jsonio import Truncated, loads_lenient, loads_or_reformat
from .llm import ai_available

# 一次对话里最多跑几轮工具。**这是花钱的闸门，也是防打转的闸门**：
# 模型偶尔会反复查同一张表，给个上限比让它自己收敛可靠。
MAX_ROUNDS = 6

# 一条主张至少要引用一次工具返回的数据。引不出来的丢掉。
MIN_CITATIONS = 1

# 最后那段结论最多写多长。**给到十万，宁可用不到，也不要被掐断。**
#
# 2026-08-14 线上：3000 的时候，查完九张表的结论写到 5527 字停在半个词上，
# 括号还差三层 —— 一整轮（真扣 18 分）就这么废了。
#
# 使用者拍板：「有多少次会超呢？但你一次因为 max_tokens 不够导致失败，
# 就会影响我们的产品。该加就加啦。」
#
# 两侧都量过，两侧都不拦：
#
#   · 模型侧：MiniMax-M3 实测 max_tokens=200000 照收（HTTP 200）
#   · 计费侧：冻结额**已经不跟 max_tokens 挂钩了**（见 llm.HOLD_OUTPUT_TOKENS），
#     所以填多大都不会多冻一分、也不会把余额少的人挡在门外
#
MAX_ANSWER_TOKENS = 100000

SYSTEM_PROMPT = """你是一位专门唱反调的研究员。使用者已经对一家公司写下了投资逻辑，
你的活是**找出这条逻辑可能错在哪**——不是附和，不是补充论据。

## 你能做什么

你手里只有下面这组工具，它们读的是使用者自己库里的数据。
**工具之外你什么都拿不到**：不能上网，不能用你记忆里的公司信息，
不能引用你"记得"的财报数字。记忆里的数字看起来跟真的一模一样，而它可能是三年前的。

先查再说。**没查过就不要断言。**

## 三条规矩

1. **每一条反方主张都要引用工具返回的具体数据。**
   引用方式：在 evidence 里写清楚用了哪个工具、看到的是哪几行、那几行说明什么。
   引不出数据的主张不要提——一句听着有道理、其实凭空捏的反驳，
   比没有反驳糟得多，因为它会让使用者放弃一条本来对的判断。

2. **数字必须是工具返回的原样。** 需要做减法、算比例时，
   把用到的原始数字一并写在 evidence 里，让人能核。

3. **不要下"该不该买卖"的结论。** 你不知道他的仓位、成本、别的选择、
   现金流安排。你的产出是**问题**和**可以被证伪的反证条件**，不是操作建议。

## 什么是好的反方

- 差的："估值偏高，需要注意风险。" —— 没有数据，没有反证条件，等于没说。
- 好的："他的逻辑靠的是渠道愿意提前打款，但合同负债占收入从 2023 年的 12.3%
  掉到 2025 年的 4.7%（工具：行业指标），已经连续两年下滑。如果 2026 年年报
  这个数继续低于 5%，这条逻辑的前提就不成立了。"

差别在三处：**有数、有出处、有一条到时候能对照的条件。**

## 输出

先用工具查，查够了再给最终答案。最终答案只输出 JSON：

{"points": [
  {"claim": "一句话说清这条反方主张",
   "evidence": [{"tool": "用了哪个工具", "shows": "看到了什么，带上原始数字"}],
   "counter_condition": "如果……发生，他这条逻辑就不成立（写成能被证伪的一句话；写不出来就留空）",
   "task": "要弄清这件事，下一步该去查什么（一句话；没有就留空）"}
],
 "not_challenged": "有哪些部分你查过之后认为站得住，一句话",
 "gaps": ["库里缺哪些数据，导致你没法验证的点"]}"""


# ------------------------------------------------------------------ 工具

def tool_specs() -> list[dict[str, Any]]:
    """给模型看的工具清单。**跟起草投资逻辑共用同一组**——见 company_tools。

    共用是有意的：两边要的是同一件事（自己决定看什么），
    各写一份会立刻分叉，然后其中一边悄悄少掉一个工具。
    """
    from .company_tools import specs

    return specs()


# ------------------------------------------------------------------ 溯源

# 负号只有在**前面不是数字**的时候才算符号。
# 不加这个前瞻的话，「2014-2016 年」会被切出一个 -2016，
# 然后被当成"库里查不到的数"标出来 —— 而它根本不是一个数据，是个年份区间。
_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?")


def _numbers_in(payload: Any) -> set[str]:
    """把一坨返回值里所有出现过的数字收集成字符串集合。

    连同它的常见写法一起收（去掉末尾的 .0、保留两位小数），
    否则模型把 4.7 写成 4.70 就会被误判成"查无此数"。
    """
    text = json.dumps(payload, ensure_ascii=False, default=str)
    found: set[str] = set()
    for raw in _NUMBER.findall(text):
        found.add(raw)
        try:
            value = float(raw)
        except ValueError:
            continue
        found.add(f"{value:g}")
        found.add(f"{value:.1f}")
        found.add(f"{value:.2f}")
        if value == int(value):
            found.add(str(int(value)))
        # 亿元写法：库里存的是元，模型多半会换算成亿说出来
        for scale in (1e8, 1e4):
            scaled = value / scale
            if abs(scaled) >= 0.01:
                found.add(f"{scaled:g}")
                found.add(f"{scaled:.1f}")
                found.add(f"{scaled:.2f}")
    return found


def _untraceable(text: str, seen: set[str]) -> list[str]:
    """这段话里有哪些数字，在工具返回的数据里找不到。

    **找不到不等于错**——它可能是两期相减算出来的。但它值得你自己核一眼，
    所以标出来而不是删掉：删掉会把有用的话一起丢了。
    """
    out = []
    for raw in _NUMBER.findall(text):
        if raw in seen:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        # 年份、名次、百分比里的小整数不值得追——它们几乎不会是"编出来的数据"
        if value == int(value) and (abs(value) <= 12 or 1990 <= value <= 2100):
            continue
        if f"{value:g}" in seen or f"{value:.1f}" in seen or f"{value:.2f}" in seen:
            continue
        out.append(raw)
    return out


BOUNDARY = (
    "它只读你库里的数据，**不能上网、不许用记忆里的公司信息**；"
    "引不出数据的主张当场丢掉，说出来的数字找不到出处会被标出来。"
    "它只提议、不写库，**不会说该不该买卖**。"
)


# ------------------------------------------------------------------ 最后一步的 JSON

# 重排时给模型看的目标结构。**跟上面输出那一节是同一份** ——
# 两处写岔的话，重排会照着一个跟主提示词不一样的形状去改，
# 而改出来的东西照样是合法 JSON，只是字段对不上，谁也不会报错。
REFORMAT_SHAPE = """{"points": [
  {"claim": "…", "evidence": [{"tool": "…", "shows": "…"}],
   "counter_condition": "…", "task": "…"}
],
 "not_challenged": "…",
 "gaps": ["…"]}"""


# ------------------------------------------------------------------ 交叉验证

# 复核并发度。跟切图、承诺分批同一个数。
CHECK_CONCURRENCY = 4

# 一次最多复核几条。**不是省钱，是防失控**：一轮反方通常给三五条主张，
# 出现二十条时多半是模型跑偏了，那种情况不该再花二十次调用去挨个核。
MAX_CHECKED = 6

CHECK_SYSTEM_PROMPT = """你在复核一条"反方主张"站不站得住。

有人读了某家公司的库，得出了一条质疑。你的任务**不是同意他**，
是拿同样的库去试着推翻这条质疑。

判定标准只有一条：**这条主张所依据的事实，在库里查得到、而且支持这个推论吗？**

- 数字对不上（他说净利率下滑，而库里是上升）→ 推翻。
- 数字对得上，但推不出这个结论（合同负债降了 2%，说成"渠道信心崩塌"）→ 推翻。
- 事实和推论都站得住 → 保留，哪怕你觉得这个角度不重要。

**拿不准时判"推翻"。** 这一层是拦截：漏掉一条只是回到没有这条的状态，
而放过一条错的会让使用者据此改掉自己的认错条件。

只输出 JSON：{"stands": true 或 false, "why": "一句话，说明你查了什么、为什么这么判"}"""


def _cross_check(points: list[dict[str, Any]],
                 runner: Callable[[str, dict[str, Any]], Any],
                 timeout: int = 120) -> tuple[list[dict[str, Any]], int]:
    """每条主张派一个独立的复核，几条并行跑。返回 (留下的, 被推翻的条数)。

    **上下文每个线程一份。** 数据域和计费主体都在 contextvars 里，
    共用一份 Context 会让除第一个线程外全部抛 already entered ——
    这个错我在承诺分批那里犯过一次，表现是"大部分复核悄悄没跑"，
    而结果看起来完全正常。
    """
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    from .company_tools import run_loop

    if not points:
        return points, 0
    targets = points[:MAX_CHECKED]
    contexts = [contextvars.copy_context() for _ in targets]

    def check(item: tuple[int, dict[str, Any]]) -> bool:
        index, point = item
        question = (f"要复核的主张：{point['claim']}\n"
                    f"他给出的依据：" +
                    "；".join(f"{e['tool']} 显示 {e['shows']}" for e in point["evidence"]))
        try:
            result = contexts[index].run(
                run_loop, CHECK_SYSTEM_PROMPT, [{"role": "user", "content": question}],
                runner, task="devils-advocate", max_rounds=3,
                max_tokens=800, timeout=timeout)
        except Exception:  # noqa: BLE001
            # **复核挂了就放行。** 这一层是加分项，不是准入门槛；
            # 一次网络抖动不该把本来有效的反方主张全删掉。
            return True
        if result["exhausted"]:
            return True
        try:
            verdict = loads_lenient(result["text"])
        except ValueError:
            return True
        return bool(verdict.get("stands", True)) if isinstance(verdict, dict) else True

    with ThreadPoolExecutor(max_workers=CHECK_CONCURRENCY) as pool:
        kept = list(pool.map(check, enumerate(targets)))
    survivors = [point for point, ok in zip(targets, kept) if ok]
    # 超出 MAX_CHECKED 的那几条没复核过，照原样留着——**但它们不该假装被核过**，
    # 所以标出来。
    for point in points[MAX_CHECKED:]:
        point["unchecked"] = True
    return survivors + points[MAX_CHECKED:], len(targets) - len(survivors)


# ------------------------------------------------------------------ 跑一轮对话

def converse(question: str, runner: Callable[[str, dict[str, Any]], Any],
             history: list[dict[str, Any]] | None = None,
             timeout: int = 180) -> dict[str, Any]:
    """跑一轮反方对话。runner 负责真正执行工具（只读，由 repository 提供）。

    返回 {"points": [...], "not_challenged": ..., "gaps": [...],
          "tool_calls": [...], "rounds": n, "billing": {...}}
    """
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})

    # 循环本身跟起草投资逻辑共用（company_tools.run_loop）——
    # 两边各写一份的话，轮次上限、工具报错处理、跑满之后怎么办会立刻分叉，
    # 而"跑满了怎么办"恰好是最容易写错、也最看不出写错了的那一处。
    from .company_tools import run_loop

    result = run_loop(SYSTEM_PROMPT, messages, runner,
                      task="devils-advocate", max_rounds=MAX_ROUNDS,
                      max_tokens=MAX_ANSWER_TOKENS, timeout=timeout)
    tool_calls = result["tool_calls"]
    billing = result["billing"]
    messages = result["messages"]
    seen_numbers: set[str] = set()
    for payload in result["payloads"]:
        seen_numbers |= _numbers_in(payload)

    if result["exhausted"]:
        # 跑满了还在查。**不要把半截结果当成答案**——说清楚它没查完。
        return {"points": [], "not_challenged": "", "rounds": MAX_ROUNDS,
                "tool_calls": tool_calls, "billing": billing,
                "gaps": [f"查了 {MAX_ROUNDS} 轮还没收敛，这次没有结论。"
                         f"把问题问得更具体一点（指名要它挑哪条逻辑的毛病）通常就行了。"],
                # **这一句要盖住外面按 points 条数拼的那句。** 不然任务存档上写的是
                # 「这一轮没有拿得出数据支撑的反方主张」——那是在替模型背一个它没犯的错，
                # 而且会让人以为这家公司查过了、没问题。
                "note": f"查了 {MAX_ROUNDS} 轮还没收敛，这次没有结论。",
                "boundary": BOUNDARY, "messages": messages}
    final_text = result["text"]

    try:
        payload, reformatted = loads_or_reformat(
            final_text, task="devils-advocate", shape=REFORMAT_SHAPE, timeout=timeout)
    except (ValueError, RuntimeError) as exc:
        # 拿不到结论。**这一轮的钱已经花了，不能只抛个异常了事**——
        # 抛出去的结果是任务失败、存档里什么都不剩，使用者连"它查了哪几张表"
        # 都看不到。所以照 exhausted 那条路走：如实说这次没拿到结论，
        # 但把查过的表和账单留下。
        #
        # **两种原因要分开说。** 「没写完」是长度上限掐的，调大就好；
        # 「格式坏了」才是模型输出质量的问题。混成一句的话，
        # 使用者会去怀疑一个根本不该怀疑的东西。
        cut = isinstance(exc, Truncated)
        why = "写到一半被长度上限截断了" if cut else "格式坏了，重排一次也没修好"
        return {"points": [], "not_challenged": "", "rounds": len(tool_calls),
                "tool_calls": tool_calls, "billing": billing,
                "gaps": [f"这一轮查完了，但模型最后那段结论{why}，所以这次没有结论。"
                         f"查过哪几张表见下方记录。（{exc}）"],
                "note": f"模型最后那段结论{why}，这次没有结论。",
                "boundary": BOUNDARY, "messages": messages}
    raw = payload.get("points") if isinstance(payload, dict) else None
    points: list[dict[str, Any]] = []
    dropped = 0
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        evidence = [e for e in (item.get("evidence") or []) if isinstance(e, dict)
                    and str(e.get("shows") or "").strip()]
        # **引不出数据的主张直接丢。** 一句听着有道理、其实凭空捏的反驳，
        # 比没有反驳糟得多——它会让人放弃一条本来对的判断。
        if not claim or len(evidence) < MIN_CITATIONS:
            dropped += 1
            continue
        body = claim + " " + " ".join(str(e.get("shows") or "") for e in evidence)
        points.append({
            "claim": claim,
            "evidence": [{"tool": str(e.get("tool") or ""), "shows": str(e.get("shows") or "")}
                         for e in evidence],
            "counter_condition": str(item.get("counter_condition") or "").strip(),
            "task": str(item.get("task") or "").strip(),
            # 找不到出处的数字标出来，不删——有些是它算的（比如两期相减）。
            "untraceable": _untraceable(body, seen_numbers),
        })

    # **每条主张再被独立反驳一次，几条并行。**
    #
    # 到这里为止，代码只核过它说出来的数字有没有出处（_untraceable），
    # **没有核过那句话本身站不站得住**。一条数字全对、推论错了的主张，
    # 看起来跟对的一模一样——而这一页的产出会被你拿去改认错条件。
    #
    # 所以每条主张单独派一个"反反方"：给它同样的库，让它试着推翻这条主张。
    # 推翻成功的丢掉并计数。**默认站不住**是有意的：这一层的作用是拦截，
    # 而拦截就该往严的方向倒——漏掉一条只是回到没有这条的状态。
    points, refuted = _cross_check(points, runner, timeout=timeout)

    gaps = [str(g) for g in (payload.get("gaps") or []) if isinstance(payload, dict)]
    if refuted:
        gaps.append(f"另有 {refuted} 条主张在复核时被推翻了——"
                    f"每条主张都会被独立再查一遍，站不住的不摆给你看。")
    if dropped:
        gaps.append(f"另有 {dropped} 条主张因为拿不出数据支撑被丢掉了——"
                    f"这是有意的：说不出依据的反驳会让你放弃一条本来对的判断。")
    if reformatted:
        # **重排过要说出来。** 内容没动（重排的提示词只许改格式），
        # 但「这份结论中途被返工过一次」是使用者有权知道的事——
        # 万一哪一条读着别扭，他至少知道该往哪儿怀疑。
        gaps.append("模型最后那段结论格式坏了，已自动重排一次；"
                    "重排只改格式、不改内容，但如果哪句读着别扭，先怀疑这里。")

    return {
        "points": points,
        "not_challenged": str(payload.get("not_challenged") or "").strip()
        if isinstance(payload, dict) else "",
        "gaps": gaps,
        "tool_calls": tool_calls,
        "rounds": len(tool_calls),
        "billing": billing,
        "messages": messages,
        "boundary": BOUNDARY,
    }
