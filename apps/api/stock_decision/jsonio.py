"""模型返回的 JSON 的容错解析。

模型写中文时经常在值里夹英文双引号（比如 说明公司"稳定分红"的承诺），
那个引号会直接把 JSON 字符串截断。这不是提示词能百分百约束住的事——
只要有一次没听话，整次调用就白跑了，而且用户看到的是一句看不懂的 JSONDecodeError。

所以解析这一层要自己扛住：先按标准解析，失败了再逐个修常见毛病，
每一步都只做能确定是格式问题的修补，绝不猜内容。修不好就抛出原始文本，方便排查。
"""

import json
import re
from typing import Any


def _strip_fences(text: str) -> str:
    """去掉 ```json 围栏——模型经常在只要 JSON 的场合仍然包一层。"""

    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    return fence.group(1) if fence else text


def _slice_payload(text: str, opener: str, closer: str) -> str | None:
    start, end = text.find(opener), text.rfind(closer)
    return text[start : end + 1] if 0 <= start < end else None


def _escape_inner_quotes(payload: str) -> str:
    """把字符串值内部的裸双引号转义掉。

    判据：一个引号如果既不是键值结构的边界（后面跟 : , } ] 或行尾），
    也不在转义位置上，那它一定是内容的一部分。只改这一种，不动结构。
    """

    result: list[str] = []
    in_string = False
    for index, char in enumerate(payload):
        if char == '"' and (index == 0 or payload[index - 1] != "\\"):
            if not in_string:
                in_string = True
            else:
                # 往后找第一个非空白字符，判断这个引号是不是真的收尾
                rest = payload[index + 1 :]
                nxt = rest.lstrip()[:1]
                if nxt in {":", ",", "}", "]", ""}:
                    in_string = False
                else:
                    result.append("\\")
        # 字符串里的裸换行同样非法
        if in_string and char == "\n":
            result.append("\\n")
            continue
        result.append(char)
    return "".join(result)


_FULLWIDTH = {"，": ",", "：": ":", "；": ";", "（": "(", "）": ")", "【": "[", "】": "]"}


def _ascii_structure(payload: str) -> str:
    """把**结构位置**上的全角标点换成半角。字符串里面的一个都不动。

    中文模型最常见的一种坏 JSON 是在成员之间写了全角逗号：

        {"tool": "financials"，"shows": "毛利率从 30.08% 降到 27.61%"}
                              ↑ 这里

    报出来是 `Expecting ',' delimiter`，跟"全角"两个字毫无关系，
    而值里的中文逗号是完全合法的内容，所以不能整篇替换 ——
    必须跟着引号状态走，只改字符串外面的。
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for char in payload:
        if escaped:
            out.append(char)
            escaped = False
            continue
        if char == "\\" and in_string:
            out.append(char)
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            out.append(char)
            continue
        out.append(_FULLWIDTH[char] if (not in_string and char in _FULLWIDTH) else char)
    return "".join(out)


def _looks_like_bare_sequence(payload: str) -> bool:
    """像不像"逗号分隔的一串对象、缺了外层方括号"。

    判据保守：必须以 { 开头、以 } 结尾，且中间出现过 `},` 后面紧跟 `{`。
    只有这一种形状才补括号——猜错的代价是把本来能修的东西修成另一个样子。
    """
    body = payload.strip()
    if not (body.startswith("{") and body.endswith("}")):
        return False
    return re.search(r"\}\s*,\s*\{", body) is not None


def loads_lenient(text: str, expect: str = "object") -> Any:
    """按对象或数组解析模型输出；标准解析失败时逐步修补格式。"""

    opener, closer = ("{", "}") if expect == "object" else ("[", "]")
    payload = _slice_payload(_strip_fences(text), opener, closer)
    if payload is None:
        raise ValueError(f"模型没有返回可解析的{'对象' if expect == 'object' else '数组'}")

    def repairs(raw: str) -> list[str]:
        trimmed = re.sub(r",(\s*[}\]])", r"\1", raw)        # 尾随逗号
        ascii_ed = _ascii_structure(raw)                     # 结构位上的全角标点
        return [
            raw,
            trimmed,
            ascii_ed,
            _ascii_structure(trimmed),
            _escape_inner_quotes(raw),                       # 值里的裸引号
            _escape_inner_quotes(trimmed),
            _escape_inner_quotes(_ascii_structure(trimmed)), # 三样一起来的情况
        ]

    attempts = repairs(payload)
    # **一串对象、没有外层方括号。** 要 {"items": [...]} 的时候，模型经常直接回
    # `{"index":1,...},\n{"index":2,...}` —— 从第一个 { 到最后一个 } 切出来是
    # 合法的开头加一堆"多余数据"，标准解析报的是 Extra data，跟"少了括号"
    # 一点关系都没有。实测证据方向那次判了 74 件、内容全对，就因为这个整批丢掉。
    #
    # **但没写完的不许补这个括号。** 2026-08-15 实测：
    #
    #     {"index":1,"shares":100},{"index":2,"shares":200},{"index":3,"sha
    #
    # 切片取到最后一个完整的 `}`，**第三行连同它后面的全部内容被丢掉**，
    # 补上外层括号之后成了一段完美合法的 JSON —— 两行。不报错、不留痕。
    # 交割单读图那边早就写着这种坏法的样子：「看起来"读到了 12 条"，
    # 其实后面还有 30 条」，而账本少一笔，成本价就永久错。
    #
    # 别的修补（尾随逗号、全角标点、裸引号）都不丢数据，只有这一个会。
    # 所以只对它加这道闸：先按原样修，修不动而原文又没写完的，
    # 当场判成「没写完」，不要用补括号把它洗成一个"成功"。
    if _looks_like_bare_sequence(payload):
        if looks_truncated(text):
            raise Truncated(
                f"模型这段话没写完就被长度上限掐了（{len(text)} 字，括号没收平）。"
                f"补上外层括号能解析，但那样会**静静地丢掉最后没写完的那几条**——"
                f"宁可这次失败，也不要交一份看起来完整的半张表。")
        attempts += repairs(f"[{payload}]")
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError as exc:
            last_error = exc
    # **报错要能定位。** 原来只给开头 160 字，而错在第 18 行 —— 看不到就没法修，
    # 只能再花一次调用去复现。把出错那一行连同上下各一行摆出来。
    detail = ""
    if isinstance(last_error, json.JSONDecodeError):
        lines = payload.splitlines()
        lo = max(0, last_error.lineno - 2)
        hi = min(len(lines), last_error.lineno + 1)
        around = "\n".join(f"{i + 1:>3} | {lines[i]}" for i in range(lo, hi))
        detail = f"\n出错处（第 {last_error.lineno} 行第 {last_error.colno} 列）：\n{around}"
    raise ValueError(f"模型返回的 JSON 修不好：{last_error}{detail}\n原文开头：{payload[:160]}")


# ------------------------------------------------------------------ 是坏了，还是没写完

class Truncated(ValueError):
    """模型话没说完就被 max_tokens 掐了。**这跟"格式坏了"是两件事。**"""


def looks_truncated(text: str) -> bool:
    """这段 JSON 是不是根本没写完 —— 数字符串外面的括号，收不平就是没写完。

    ## 为什么必须跟"格式坏了"分开

    2026-08-14 线上实测：反方查完九张表，最后那段结论 5527 字，
    停在 `"claim": "收现比从 2023 年 109.06%` —— 半个词，括号还差三层。
    那不是模型写错了标点，是 max_tokens 到顶把它掐了。

    两件事必须分开处理，因为**处理方式相反**：

      · 格式坏了 → 让模型重排一次，能救回来
      · 没写完   → 重排**一定救不回来**。重排的规矩是「一个字都不许加」，
        而缺的那半截恰恰只能靠加。让它去重排，等于要么白花一次调用，
        要么逼它编一段原文没有的结论 —— 后者比前者糟得多。

    而且报错也得说对：跟使用者说「格式坏了」，他会去怀疑模型的输出质量；
    说「太长了被截断」，他才知道这是可以靠调预算解决的。
    """
    depth = 0
    in_string = False
    escaped = False
    for char in _strip_fences(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth > 0


# ------------------------------------------------------------------ 修不好的时候

_REFORMAT_SYSTEM = """把下面这段文字整理成合法 JSON。

**只改格式，一个字的内容都不要改**：不要补充、不要删减、不要重写措辞，
也不要替它补上你觉得该有的字段。原文里没有的东西就是没有。

只输出 JSON，不要围栏、不要解释、不要前后缀。"""


def loads_or_reformat(text: str, *, task: str, expect: str = "object",
                      shape: str = "", timeout: int = 120,
                      max_tokens: int = 4000) -> tuple[Any, bool]:
    """先按上面那一套修；修不好就**把原文还给模型，只让它重排格式**。

    ## 为什么这一步值得再花一次调用

    坏 JSON 通常出现在一条**已经花掉了的**链路末尾：反方 Agent 查了六轮库、
    起草查了八轮，全是真调用真计费。而解析失败一抛，整件事就是失败——
    使用者付了一整轮的钱，拿到一句 JSONDecodeError。

    重排这次调用不带工具、不查库，输入就是那段坏文本，
    **比重跑一整轮便宜一个数量级**，救回的却是已经花掉的那一整轮。

    提示词只允许改格式。内容一改，救回来的就不是原来那份结论了，
    而使用者根本无从知道自己看的是第二稿。

    `shape` 是可选的目标结构示例——给了的话重排更稳，但不给也能用。

    返回 (payload, 是否重排过)。两次都失败时抛最后那个 ValueError。
    """
    try:
        return loads_lenient(text, expect), False
    except ValueError:
        pass
    # **没写完的不送去重排。** 重排只许改格式，而缺的那半截只能靠加 ——
    # 送过去要么白花一次调用，要么逼它编一段原文里没有的结论。
    if looks_truncated(text):
        raise Truncated(
            f"模型这段话没写完就被长度上限掐了（{len(text)} 字，括号没收平），"
            f"不是格式问题，重排救不回来。把这一步的 max_tokens 调大再来。")
    from . import llm  # 局部导入：这个模块被一堆纯解析的地方引用，不该拖上计费层

    system = _REFORMAT_SYSTEM + (f"\n\n结构：\n\n{shape}" if shape else "")
    reply = llm.call(system, text, task=task, max_tokens=max_tokens, timeout=min(timeout, 120))
    return loads_lenient(reply.text, expect), True


# ------------------------------------------------------------------ 数字体面

# 一个数：必须只有一个小数点，且小数位超过两位。
# 排除掉版本号（1.2.3）、日期（2026-08-04）、股票代码这些——它们没有小数点，
# 或者点不止一个。前后要求不是数字，免得把 1.23456 的一部分切走。
_LONG_DECIMAL = re.compile(r"(?<![\d.])(\d+)\.(\d{3,})(?![\d.])")


def tidy_decimals(text: str) -> str:
    """把文本里超过两位小数的数字收到两位。

    **为什么在读的时候做，而不是只在写的时候做。**

    模型产出是**会被存下来、被反复读的资产**。「喂进提示词之前先取整」只在
    生成那一刻有效——生成器修好之前存下的东西，会一直那样显示下去。
    实测：库里有 97 处小数位 ≥ 4 的数字（「营收同比 200.596381199%」
    「每股经营现金流 5.685126589991 元」），而生成器早在两天后就修好了。

    一个 12 位小数的同比增速传达的唯一信息，是没有人看过这段输出。
    """
    if not text:
        return text
    return _LONG_DECIMAL.sub(lambda m: f"{round(float(m.group(0)), 2):g}", text)
