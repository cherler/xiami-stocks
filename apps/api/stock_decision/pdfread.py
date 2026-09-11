"""把一份 PDF 读成**能核对的**结构：一页一段，表格还是表格，读不到的说出来。

## 为什么不是「抽成一大段文字然后喂给模型」

那正是 `disclosure._extract_text` 在做的事，而它对公告够用、对年报不够用。
茅台 2026 半年报（110 页）实测：

    pdfplumber 认出 232 张表、2135 行、11033 个单元格
    其中 39% 是空单元格   →  纯文本抽取下它们直接消失，列就错位了
    617 个折行单元格      →  纯文本抽取下每个断成两行

具体长这样，同一页合并资产负债表：

    纯文本      所有者权益（或股东权
                益）合计 158,148,992,327.71 178,999,246,453.61
                已赚保费                       ← 空的？0？还是标签折行？分不出

    表格模式    | 所有者权益（或股东权益）合计 |   | 158,148,992,327.71 | 178,999,246,453.61 |
                | 专项储备                |   |                    |                    |

**分不清「这一项是 0」和「这一项没有」，对研究用途是硬伤。** 而且一行只剩一个数时，
你没法知道它是本期还是上期。

## 一页一种读法，不是一份文件一种读法

pypdf 6 自带 `extraction_mode="layout"`，零依赖、靠空白保住列位置。但实测双栏文档
（**券商研报大多是双栏**）：

    普通模式   way networks have not demonstrated accuracy gains with
               extremely increased depth (e.g., over 100 layers).        ← 对的

    layout     way networks have not demonstrated…   ReLU [29] and the biases
               extremely increased depth…            tations. The operationF   ← 两栏交错

**layout 对表格更好、对双栏更糟，而普通模式正好相反。**
所以模式按页判断：这一页有表格线就走表格，看起来是双栏就走普通，其余走 layout。

## 每一段都带页码

这一页的全部价值在于**能翻回原文核对**。摘要里的每个数字都要指得回页码，
否则跟随便找个模型问没有区别。所以切段的单位是页，不是字数。

## 读不到的要说出来

扫描件、加密、解析失败——**静默降级是最危险的一种失败**：它跟"这份文件里没有
这句话"长得一模一样。本仓已经在别处踩过三次，这里从一开始就把它当成结果的一部分。
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

# 单份上限。60MB 跟公告那条一致 —— 巨潮最大的年报约 30MB。
MAX_PDF_BYTES = 60 * 1024 * 1024
# 页数上限。500 页的招股书读完要几十秒，而且没人会一次读完。
MAX_PAGES = 500
# 一页最多留多少字。异常页（字体表被当成文字抽出来）能到十万字，
# 那一页会把整个上下文吃光，而它一个字都没用。
MAX_PAGE_CHARS = 20_000

# 双栏判据：一页里有多少比例的行，中间存在一段足够宽的空白。
# **只用来选读法，不用来下结论** —— 判错了最坏是这一页读法不理想，不会丢内容。
_TWO_COL_RATIO = 0.45
_WIDE_GAP = re.compile(r"\S {6,}\S")


class PdfUnreadable(Exception):
    """连页都翻不开（加密、损坏、根本不是 PDF）。**这跟"某一页读不到"是两回事。**"""


def looks_two_column(layout_text: str) -> bool:
    """这一页看起来是双栏吗？

    判据是「多数行的中间有一大段空白」—— 双栏排版在 layout 模式下必然如此，
    而单栏正文不会。表格也会有大段空白，所以这个判断只在没认出表格时才用。
    """
    lines = [line for line in layout_text.split("\n") if len(line.strip()) > 20]
    if len(lines) < 6:
        return False
    gapped = sum(1 for line in lines if _WIDE_GAP.search(line))
    return gapped / len(lines) >= _TWO_COL_RATIO


def _rows_to_text(table: list[list[Any]]) -> str:
    """把一张表排成人和模型都读得懂的样子。

    **空单元格保留成空**，用 ` | ` 分隔 —— 这正是纯文本抽取丢掉的那一半信息：
    一行里第二列是空的，说明这个科目本期没有数，而不是"这个数跑到第一列去了"。
    """
    out: list[str] = []
    for row in table:
        cells = ["" if cell is None else re.sub(r"\s+", " ", str(cell)).strip()
                 for cell in row]
        if not any(cells):
            continue                      # 整行皆空：分隔线，不是数据
        out.append(" | ".join(cells))
    return "\n".join(out)


def read_pages(body: bytes) -> list[dict[str, Any]]:
    """一页一条：`{page, mode, text, tables, note}`。**读不到的页也在列表里。**

    `mode` 是这一页用了哪种读法，摆给使用者看 —— 一页标着「双栏」而内容明显是
    表格时，他至少知道该怀疑什么。
    """
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    try:
        import pdfplumber
    except ModuleNotFoundError:           # pragma: no cover —— 部署里一定装了
        pdfplumber = None                 # type: ignore[assignment]

    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            # 空口令能开的加密 PDF 很常见（巨潮有一批），试一次再放弃。
            try:
                reader.decrypt("")
            except Exception as caught:   # noqa: BLE001
                raise PdfUnreadable("这份 PDF 加了密码，打不开") from caught
        total = len(reader.pages)
    except PdfUnreadable:
        raise
    except Exception as caught:           # noqa: BLE001
        raise PdfUnreadable(f"这份文件打不开（{type(caught).__name__}）") from caught

    plumber = None
    if pdfplumber is not None:
        try:
            plumber = pdfplumber.open(io.BytesIO(body))
        except Exception:                 # noqa: BLE001 —— 认不出表格不致命，退回文字
            plumber = None

    pages: list[dict[str, Any]] = []
    try:
        for index in range(min(total, MAX_PAGES)):
            pages.append(_read_one(reader, plumber, index))
    finally:
        if plumber is not None:
            plumber.close()

    if total > MAX_PAGES:
        # **砍掉的要报数。** 少读几页跟"这份文件里没有"长得一模一样。
        pages.append({"page": MAX_PAGES + 1, "mode": "截断", "text": "", "tables": 0,
                      "note": f"这份文件共 {total} 页，只读了前 {MAX_PAGES} 页"})
    return pages


def _read_one(reader: Any, plumber: Any, index: int) -> dict[str, Any]:
    """读一页。**每一步失败都变成这一页的 note，不往上抛** —— 一页坏掉不该毁掉整份。"""
    number = index + 1
    try:
        page = reader.pages[index]
        plain = (page.extract_text() or "").strip()
        layout = (page.extract_text(extraction_mode="layout") or "").strip()
    except Exception as caught:           # noqa: BLE001
        return {"page": number, "mode": "读不到", "text": "", "tables": 0,
                "note": f"这一页解析失败（{type(caught).__name__}）"}

    if not plain and not layout:
        # 没有文字层 —— 扫描件。**这不是错误，是这一页本来就取不到文字。**
        return {"page": number, "mode": "扫描件", "text": "", "tables": 0,
                "note": "这一页没有文字层（扫描件或整页图片），读不出内容"}

    tables: list[list[list[Any]]] = []
    if plumber is not None:
        try:
            tables = plumber.pages[index].extract_tables() or []
        except Exception:                 # noqa: BLE001
            tables = []

    if tables:
        # 表格模式：单元格结构是这一页最要紧的东西，宁可丢一点版面也要保住它。
        body_text = "\n\n".join(filter(None, (_rows_to_text(t) for t in tables)))
        # 表外的说明文字（"单位：元 币种：人民币" 这种）也要留 —— 金额单位写在表头，
        # 丢了它整张表的数量级就错了。
        return {"page": number, "mode": "表格", "tables": len(tables),
                "text": (plain + "\n\n" + body_text)[:MAX_PAGE_CHARS], "note": ""}

    if looks_two_column(layout):
        # 双栏：layout 会把两栏交错读成一行，普通模式反而是对的。
        return {"page": number, "mode": "双栏", "tables": 0,
                "text": plain[:MAX_PAGE_CHARS], "note": ""}

    return {"page": number, "mode": "版面", "tables": 0,
            "text": (layout or plain)[:MAX_PAGE_CHARS], "note": ""}


def summarize(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """这份文件读成了什么样 —— **摆给使用者看的那份交代**。

    读不到的页要能一眼数出来。「读了 108 页、2 页是扫描件」和「读了 110 页」
    是两个完全不同的结论，而后者会让人以为那 2 页里没有他要找的东西。
    """
    read = [p for p in pages if p["text"]]
    return {
        "pages": len(pages),
        "read": len(read),
        "chars": sum(len(p["text"]) for p in read),
        "tables": sum(p["tables"] for p in pages),
        "modes": {mode: sum(1 for p in pages if p["mode"] == mode)
                  for mode in sorted({p["mode"] for p in pages})},
        # 逐条列出读不到的页 —— 不是给一个总数，是给页码，他能自己去翻。
        "unreadable": [{"page": p["page"], "why": p["note"]} for p in pages if p["note"]],
    }
