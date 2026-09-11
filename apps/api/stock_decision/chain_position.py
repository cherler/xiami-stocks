"""产业链位置：这门生意被谁卡着脖子。

## 为什么原来那张图不算产业链地图

原来这一页是模型凭世界知识画的四个方框：上游、下游、同业、替代。
实测中国平安那张，上游七条里有三条是同一件事（「再保险人」「再保险公司」
「再保险公司」，其中两条字面完全相同），下游是「个人客户」「个人投保人」
「个人保险客户」——**三种说法一个意思，而且都不是产业链节点，是空词**。

更根本的问题：**这是整个产品里唯一一处数据不能回原文核对的地方**。
页面自己写着「关系来自模型的世界知识，可能过期也可能记错」。

## 换成年报里强制披露的那四个数

「产业链位置」这件事，年报里有确定的答案，而且是**强制披露项**：

    前五名客户合计销售金额占年度销售总额比例      ← 下游有多集中
    前五名供应商合计采购金额占年度采购总额比例    ← 上游有多集中
    应付账款 ÷ 营业成本                        ← 你能压上游多久的货款
    （合同负债 + 预收款项）÷ 营业收入            ← 下游愿不愿意先给你钱

前两个从年报正文里抽，后两个 industry_metrics 里已经在算。

实测（2025 年报）：

    格力电器   前五名客户 14.40%   第一名 5.91%
    雪人集团   前五名客户 29.30%   第一名 17.00%   ← 单一客户占 17%
    中粮资本   前五名客户  7.04%   第一名 2.33%

**这一个数比整张示意图有用得多。** 前五大客户占 10% 和占 39%，
是两种完全不同的生意：前者谁都卡不住它，后者被几家攥着。

## 只看年度报告

半年报**没有这一节**——它不是半年报的强制披露项。实测宁德、寒武纪的半年报里
搜到的「前五大客户」全在财务附注的信用风险段（"前五大客户的应收账款占…"），
那是另一件事，不能拿来当集中度用。

## 用代码解析，不花模型钱

这一节的格式在所有公司的年报里都一样（交易所模板）：

    前五名客户合计销售金额（元） 24,647,540,609.21
    前五名客户合计销售金额占年度销售总额比例 14.40%

所以正则就够了，而且**确定性比模型强**——一个抽错的百分比跟对的长得一模一样。
解析不出来时如实说"没抽到"，不猜、也不退回让模型编。

## 一处必须小心：标题会出现好几次

「主要销售客户和主要供应商情况」在一份年报里会命中七到九处（目录、正文、
附注引用）。**不能取第一处**——实测第一处落在研发段落上。
取的是「后面能解析出数字的那一处」，这是个选择规则，不是猜。
"""

from __future__ import annotations

import re
from typing import Any

# 定位用的标题。**顺序不重要，命中之后按"能不能解析出数字"筛。**
SECTION_HEADINGS = (
    "主要销售客户和主要供应商情况",
    "主要销售客户及主要供应商情况",
    "前五名客户合计销售金额",
    "前五名供应商合计采购金额",
)

# 从命中位置往后取多长来解析。这一节含客户表和供应商表，实测两千字够。
SECTION_SPAN = 4_000

# 数字：可能带千分位与小数
_NUM = r"([\d,]+(?:\.\d+)?)"

# **PDF 抽出来的文字到处是空格。** 「前五名客户销售额 576,030.47 万元」——
# 数字前后、单位前后都可能有空格甚至换行。第一版正则没允许空格，
# 于是寒武纪那条 88.66%（全场最高的客户集中度，最该抓到的那个）没抽到，
# 而它抽到了供应商那条，看起来像"这家只披露了供应商"。
_SP = r"\s*"

_CUSTOMER_TOTAL = re.compile(r"前五名客户合计销售金额[^\d]{0,14}" + _NUM)
_CUSTOMER_RATIO = re.compile(r"前五名客户合计销售金额占年度销售总额比例[^\d]{0,10}" + _NUM)
_SUPPLIER_TOTAL = re.compile(r"前五名供应商合计采购金额[^\d]{0,14}" + _NUM)
_SUPPLIER_RATIO = re.compile(r"前五名供应商合计采购金额占年度采购总额比例[^\d]{0,10}" + _NUM)
# 上交所口径写成一句话：「前五名客户销售额 576,030.47 万元，占年度销售总额88.66%」
_SSE_CUSTOMER = re.compile(
    r"前五名客户销售额" + _SP + _NUM + _SP + r"万元[^\d]{0,16}" + _NUM + _SP + r"%")
_SSE_SUPPLIER = re.compile(
    r"前五名供应商采购额" + _SP + _NUM + _SP + r"万元[^\d]{0,16}" + _NUM + _SP + r"%")
# 逐名明细：序号 名称 金额 占比
_RANKED = re.compile(r"[1-5]\s+(第[一二三四五]名|[^\s]{2,30}?)\s+" + _NUM + r"\s+" + _NUM + r"\s*%")


def _number(raw: str) -> float | None:
    try:
        return float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_section(text: str) -> dict[str, Any]:
    """从这一段文字里解析出集中度。解析不出来就返回空，**不猜**。"""
    out: dict[str, Any] = {}
    for key, pattern in (("customer_ratio", _CUSTOMER_RATIO),
                         ("supplier_ratio", _SUPPLIER_RATIO)):
        match = pattern.search(text)
        if match:
            out[key] = _number(match.group(1))
    for key, pattern in (("customer_amount", _CUSTOMER_TOTAL),
                         ("supplier_amount", _SUPPLIER_TOTAL)):
        match = pattern.search(text)
        if match:
            out[key] = _number(match.group(1))

    # 上交所那种一句话写完的写法，金额单位是万元
    if "customer_ratio" not in out:
        match = _SSE_CUSTOMER.search(text)
        if match:
            out["customer_amount"] = (_number(match.group(1)) or 0) * 1e4
            out["customer_ratio"] = _number(match.group(2))
    if "supplier_ratio" not in out:
        match = _SSE_SUPPLIER.search(text)
        if match:
            out["supplier_amount"] = (_number(match.group(1)) or 0) * 1e4
            out["supplier_ratio"] = _number(match.group(2))

    # 逐名明细。**很多公司只写「第一名」不写真名**，那也照收——
    # 「单一客户占 17%」这件事跟他叫什么无关。
    ranked = [{"name": m.group(1), "amount": _number(m.group(2)), "ratio": _number(m.group(3))}
              for m in _RANKED.finditer(text)]
    if ranked:
        out["top"] = ranked[:5]
    return out


def _anchor_in(text: str) -> int:
    """这段文字里，真正写着集中度那一句从第几个字开始。找不到就从头。"""
    spots = [m.start() for m in (
        _CUSTOMER_RATIO.search(text), _SSE_CUSTOMER.search(text),
        _SUPPLIER_RATIO.search(text), _SSE_SUPPLIER.search(text)) if m]
    if not spots:
        return 0
    # 往前退一点，把「公司主要销售客户情况」那半句一起带上，读起来才完整
    return max(0, min(spots) - 40)


def extract(body: str) -> dict[str, Any]:
    """从一份年报正文里抽出产业链位置的两个集中度。

    **标题会命中七到九处**（目录、正文、附注），所以逐处试，
    取第一处能解析出比例的。取不到就如实说取不到。
    """
    from .disclosure import find_section

    hits = find_section(body, SECTION_HEADINGS, span=SECTION_SPAN)
    for hit in hits:
        parsed = parse_section(hit["text"])
        if parsed.get("customer_ratio") is not None or parsed.get("supplier_ratio") is not None:
            # **摘录要锚在真正解析出数字的那一句上，不是命中标题的位置。**
            #
            # 标题在目录里也会命中，而目录那条的窗口（4000 字）常常一直伸到
            # 真表格上——于是数字是对的，摘出来的却是目录那一行。
            # 而摘录正是这一页可信度的全部依据：点开年报要能一字不差找到它。
            anchor = _anchor_in(hit["text"])
            parsed["found_at"] = hit["at"] + anchor
            parsed["heading"] = hit["heading"]
            parsed["excerpt"] = hit["text"][anchor:anchor + 600].strip()
            return parsed
    return {"note": f"这份年报里定位到 {len(hits)} 处相关标题，但没有一处能解析出集中度数字。"
            if hits else "这份年报里没有「主要销售客户和主要供应商情况」这一节。"}


# 单一客户占到这个数，就不能再说「没有哪一家能单独左右它」。
#
# 10% 不是拍的：它是**年报里「重大客户」的通行口径**，也是丢掉这一家之后
# 收入缺口大到必须在复核里单独交代的量级。
SINGLE_CUSTOMER_MATTERS = 10.0


def read_position(customer_ratio: float | None, supplier_ratio: float | None,
                  top: list[dict[str, Any]] | None = None) -> str:
    """把两个集中度读成一句人话。**只描述，不打分。**

    集中不等于差：给苹果供货的公司客户集中度极高，而那是好生意还是坏生意，
    取决于它有没有被替代的可能——这里不替使用者下这个判断。

    ## 为什么必须看逐名明细，不能只看前五合计

    这个模块开头自己举的例子就把只看合计这件事否掉了：

        雪人集团   前五名客户 29.30%   **第一名 17.00%**

    29.3% 落进「小于 30」那一档，于是这一页原来会说
    「前五大客户只占 29.3%，下游分散，**没有哪一家能单独左右它**」——
    而它的第一大客户一家就占 17%，丢掉这一家收入直接少一截。
    **旁边的表格就摆着 17%，而这句话在说没有。**

    `top` 一直就在同一个返回值里（repository 那边 top_json 解出来给页面用），
    只是从来没有传进这个函数。
    """
    parts: list[str] = []
    biggest = None
    for item in top or []:
        ratio = item.get("ratio")
        if isinstance(ratio, (int, float)) and (biggest is None or ratio > biggest):
            biggest = float(ratio)

    if customer_ratio is not None:
        if customer_ratio >= 50:
            parts.append(f"前五大客户占了 {customer_ratio}% 的收入——**这门生意的定价权很大程度上不在自己手里**")
        elif customer_ratio >= 30:
            parts.append(f"前五大客户占 {customer_ratio}%，下游偏集中，丢掉一个大客户会直接反映在收入上")
        elif biggest is not None and biggest >= SINGLE_CUSTOMER_MATTERS:
            # 合计不高、但有一家特别大 —— 这一档原来会被说成「下游分散」。
            parts.append(f"前五大客户合计只占 {customer_ratio}%，但**第一大客户一家就占 "
                         f"{biggest:g}%**——合计看着分散，实际压在一家身上")
        else:
            parts.append(f"前五大客户只占 {customer_ratio}%，下游分散，没有哪一家能单独左右它")
    if supplier_ratio is not None:
        if supplier_ratio >= 50:
            parts.append(f"前五大供应商占采购的 {supplier_ratio}%，上游同样集中，成本端受制于人")
        else:
            parts.append(f"前五大供应商占采购的 {supplier_ratio}%")
    return "；".join(parts)
