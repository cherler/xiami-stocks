"""结果里的金额，要能回它自己标注的那几页去核。

提示词第 0 条写着「你输出里的每一个数都必须能在给你的原文里找到」。
**那是一句承诺，这个文件是管它的人。**

2026-08-19 全站巡检实测（贵州茅台 2026 半年报，线上真结果）：

    结果：「财务公司同业存放款项净增加 739.9 亿」（引第 5、7、33 页）
    原文第 33 页：「客户存款和同业存放款项净增加额 7,383,004,563.78」= 73.83 亿

差十倍。而这个数**正是它论证「706.91 亿经营现金流不是主营回款」的唯一论据** ——
73.83 亿只占 706.91 亿的一成，撑不起那个结论。数错了，结论跟着错。
这类错最贵：页码、格式、语气全对，只有数是坏的，读的人没法自己发现。

## 判定口径（三版试错换来的）

1. **数值比对，不是字符串包含。** 原文写 `70,690,750,119.06`，模型写 `706.91 亿` ——
   字符串永远对不上。第一版这么写，四份真结果误报 63 处。
2. **只核带金额单位的数。** 比率是算出来的（同比 +438.84%、占比 45.32%），
   原文里本来就没有。第二版把它们也算上，误报 39 处。
3. **元 / 万元 / 原样三种口径都试。** 同一个金额在报告里三种写法都有。
"""
from __future__ import annotations

from stock_decision.documents import unverified_figures

PAGES = [
    {"page": 5, "text": "经营活动产生的现金流量净额 70,690,750,119.06 13,119,061,031.33 438.84"},
    {"page": 33, "text": "客户存款和同业存放款项净增加额 7,383,004,563.78 -2,516,653,584.50"},
    {"page": 31, "text": "营业收入 46,033,330,566.78"},
    {"page": 7, "text": "研发费用 70,246.61 万元"},
]


def _digest(*blocks: str) -> str:
    return '{"watch": [' + ",".join(blocks) + '], "items": []}'


def test_抓得住那条差十倍的() -> None:
    bad = unverified_figures(
        _digest('{"point": "财务公司同业存放款项净增加 739.9 亿", "pages": [5, 33]}'), PAGES)
    assert [x["value"] for x in bad] == ["739.9"], bad
    assert bad[0]["where"] == "没有", "整份文件里都没有这个数，该说得更重"


def test_对的数不报() -> None:
    """706.91 亿 ← 70,690,750,119.06 元；73.83 亿 ← 7,383,004,563.78 元。"""
    assert unverified_figures(
        _digest('{"point": "经营活动现金流净额 706.91 亿，其中同业存放净增 73.83 亿", "pages": [5, 33]}'),
        PAGES) == []


def test_万元口径也认() -> None:
    """同一个金额，报告里元、万元、亿元三种写法都有。"""
    assert unverified_figures(
        _digest('{"point": "研发费用 7.02 亿", "pages": [7]}'), PAGES) == []


def test_比率不算数字对不上() -> None:
    """同比、占比是算出来的，原文里本来就没有 —— 一起核就成了天天误报。"""
    assert unverified_figures(
        _digest('{"point": "经营现金流同比 +438.84%，存货占比 45.32%", "pages": [5]}'), PAGES) == []


def test_页码引错和整份没有要分开说() -> None:
    """46,033,330,566.78 在第 31 页，而这条引的是第 5 页 —— 翻过去找不到。"""
    bad = unverified_figures(
        _digest('{"point": "营业收入 460.33 亿", "pages": [5]}'), PAGES)
    assert [(x["value"], x["where"]) for x in bad] == [("460.33", "别的页")], bad


def test_没标页码的不在这里判() -> None:
    """那由提示词第 2 条管（标不出页码就不要写那条结论）。"""
    assert unverified_figures(_digest('{"point": "某个数 12.34 亿", "pages": []}'), PAGES) == []


def test_读不出字的页不算错() -> None:
    """整页是扫描件时核不了，核不了不等于错。"""
    assert unverified_figures(
        _digest('{"point": "某个数 12.34 亿", "pages": [99]}'),
        PAGES + [{"page": 99, "text": ""}]) == []


def test_年份和页码不当金额() -> None:
    assert unverified_figures(
        _digest('{"point": "2026 年上半年营业收入 460.33 亿", "pages": [31]}'), PAGES) == []


def test_三条路径都要带上核对结果() -> None:
    """新读一次、读缓存、重新打开文件 —— 三条路径，少一条就等于没做。

    2026-08-19 我第一版只加在 /digest 接口上，而**界面初次渲染是从文档详情
    里拼结果的**（结果存在文件上，重开不重付，所以"重新打开"才是最常走的一条）。
    上线之后线上一条提示都没出现。
    """
    from pathlib import Path

    main = (Path(__file__).resolve().parents[1] / "stock_decision" / "main.py").read_text()
    lines = [ln for ln in main.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(lines)
    assert body.count("unverified_figures(") >= 3, (
        "unverified_figures 的调用少于三处 —— 新读、读缓存、文档详情，三条路径都要带上"
    )
    at = body.index("def get_document_detail")
    assert "unverified_figures(" in body[at:at + 700], "文档详情这条路径漏了（界面就是从它拼结果的）"


def test_前端从详情里取这个字段() -> None:
    from pathlib import Path

    tsx = (Path(__file__).resolve().parents[3] / "apps/web/src/components/Documents.tsx").read_text()
    at = tsx.index("missed: doc.digest_missed")
    assert "doc.digest_unverified" in tsx[at - 200:at + 200], (
        "初次渲染没把 digest_unverified 拼进去 —— 重新打开一份文件时提示会消失"
    )
