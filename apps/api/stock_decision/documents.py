"""读进来的文件：存、找、问。

## 先定位再读，不是全文摘要

那份 64 万字的年报全文喂给模型，按本仓的读文档定价是 27 分（约 3 元）——
不算贵，但**大部分内容你不会看**，而且每问一个新问题就要再喂一次。

所以问答走检索：**先按关键词挑出相关的几页，只把那几页喂进去**。
一次问答通常只用五到十页、一两万字，两三分钱。这不只是省钱 ——
喂三十万字进去，模型答出来的东西你根本没法核对；喂十页，你能一页页翻。

## 检索为什么不用向量

一个中文财务文档的问答，关键词命中比向量相似度更靠谱，因为**问的往往是专有名词**
（「营业成本」「回购」「前五大客户」）—— 那正是关键词最强、向量最弱的场合。
而且向量要一个模型、一次嵌入调用、一张表，成本和复杂度都不是这一步该付的。

命中不到才是真问题，所以：**一个都没命中时不许沉默地喂前几页** ——
那会答出一段跟问题无关但看起来很像回答的东西。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 一次问答最多喂几页。**十页足够回答一个具体问题**，而且十页你翻得动 ——
# 喂三十页答出来的东西没法核对，那就退回成了"随便找个模型问问"。
MAX_CONTEXT_PAGES = 10
# 一次问答最多喂多少字。表格页很长，十页也可能超。
MAX_CONTEXT_CHARS = 40_000

# 检索时忽略的词。**只挡问句里的功能词**，不挡任何名词 ——
# 挡错一个专有名词，命中就没了，而它表现成"这份文件里没有"。
_STOP = frozenset("的了吗呢吧是在有和与及对为它他她这那什么怎么如何多少哪些哪个请帮我你")


def keywords(question: str) -> list[str]:
    """从问句里取检索词。

    中文不分词，取**二字滑窗**：「营业成本」会产出「营业」「业成」「成本」，
    其中两个是真词。多出来的那个是噪声，但它命中不到东西，不影响排序。
    英文与数字按整词取（`ROE`、`2025`）。
    """
    text = re.sub(r"[\s，。？！、；：（）()【】\[\]「」《》]+", " ", str(question or ""))
    out: list[str] = []
    for token in text.split():
        if re.fullmatch(r"[A-Za-z0-9.%\-]+", token):
            if len(token) >= 2:
                out.append(token.lower())
            continue
        chars = [c for c in token if c not in _STOP]
        for i in range(len(chars) - 1):
            out.append("".join(chars[i:i + 2]))
        if len(chars) == 1:
            out.append(chars[0])
    return list(dict.fromkeys(out))


# 一个词出现在超过这个比例的页上，就当它没有信息量。
#
# **「公司」在年报的每一页上都有。** 不挡的话，「公司的比特币持仓」会命中十页 ——
# 而这份年报里一个字都没提比特币。那比答错更糟：使用者拿到一段跟问题无关、
# 却引着真页码的回答，**没有任何线索知道它是编的**。
COMMON_TERM_RATIO = 0.5


def informative(terms: list[str], pages: list[dict[str, Any]]) -> list[str]:
    """把在整份文件里到处都是的词挑出去。

    这是最简单的一版 IDF：不算权重，只做有无。年报里「公司」「本期」「万元」
    都会被挡掉，而「比特币」「回购」「前五名」不会 —— 后者正是问题真正在问的东西。

    **全被挡光时返回原样**：一个只由常见词组成的问题（「公司情况如何」）
    本来也答不好，但那时候该由模型说"问得太泛"，不该由检索假装没找到。
    """
    texts = [p.get("text") or "" for p in pages if p.get("text")]
    if not texts:
        return terms
    ceiling = max(1, int(len(texts) * COMMON_TERM_RATIO))
    kept = [t for t in terms if sum(1 for text in texts if t in text) <= ceiling]
    return kept or terms


def rank_pages(pages: list[dict[str, Any]], question: str) -> list[dict[str, Any]]:
    """按跟问题的相关度给页排序，**只返回真的命中过的页**。

    一个都没命中时返回空 —— 调用方必须据此告诉使用者"这份文件里没找到"，
    而不是退回去喂前几页。那样答出来的东西跟问题无关，却长得很像回答。
    """
    terms = informative(keywords(question), pages)
    if not terms:
        return []
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for page in pages:
        text = page.get("text") or ""
        if not text:
            continue
        hits = sum(text.count(term) for term in terms)
        # 命中的**不同**关键词数比总次数更能说明相关：一页里「营业」出现四十次
        # （表格里每行都有）不代表它回答了这个问题。
        distinct = sum(1 for term in terms if term in text)
        if not distinct:
            continue
        scored.append((distinct, hits, page))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [page for _, _, page in scored]


def build_context(pages: list[dict[str, Any]], question: str) -> dict[str, Any]:
    """挑出要喂给模型的那几页。返回 `{pages, text, chars, note}`。

    每一页都带页码标头 —— **答案里的每个数字要指得回页码**，
    而模型只有看得见页码才写得出来。
    """
    terms = informative(keywords(question), pages)
    ranked = rank_pages(pages, question)
    if not ranked:
        # **往"没找到"这边失败，不往"给一段看起来像回答的东西"那边失败。**
        #
        # 「公司情况如何」这种全是常见词的问题也会落到这里：那些词在每一页上都有，
        # 等于没有信息量。说"没找到"会让人换个问法（便宜），
        # 而返回十页会让人拿到一段引着真页码的、跟问题无关的回答（贵得多）。
        return {"pages": [], "text": "", "chars": 0,
                "note": "这份文件里没找到跟这个问题相关的页。"
                        "**换一个更具体的问法**——用文件里会出现的词（科目名、"
                        "「回购」「解禁」「前五名」这类），别用「情况如何」这种。"}

    picked: list[dict[str, Any]] = []
    parts: list[str] = []
    total = 0
    for page in ranked[:MAX_CONTEXT_PAGES]:
        chunk = f"【第 {page['page']} 页 · {page['mode']}】\n{page['text']}"
        if total and total + len(chunk) > MAX_CONTEXT_CHARS:
            break
        picked.append(page)
        parts.append(chunk)
        total += len(chunk)

    # 页码按顺序摆给模型看，但**挑是按相关度挑的** —— 两件事分开。
    picked.sort(key=lambda page: page["page"])
    numbers = [page["page"] for page in picked]
    note = (f"从 {len(pages)} 页里挑了 {len(picked)} 页喂进去（第 "
            + "、".join(str(n) for n in numbers) + " 页）。")
    if len(ranked) > len(picked):
        # **砍掉的要报数。** 少喂几页跟"这份文件里没有"长得一模一样。
        note += f"另有 {len(ranked) - len(picked)} 页也命中了，这次没喂 —— 太长了答不准。"

    # **命中很弱时要说出来。**
    #
    # 茅台半年报里根本没有「前五名客户」（那是年报才有的），而问它「前五大客户占
    # 销售总额多少」照样返回十页 —— 因为「前五」「客户」「销售」各自在别处出现过。
    # 检索到此为止就只能这样：**它挑的是候选，不是答案**。
    # 所以把强度如实报出来，剩下的交给模型（提示词要求它答不出就说"这几页里没有"）
    # 和使用者（页面上摆着喂了哪几页，他自己能判断对不对）。
    best = max((sum(1 for t in terms if t in page["text"]) for page in picked), default=0)
    if terms and best * 2 < len(terms):
        note += (f"　⚠️ 命中不强：最相关的那一页只对上了 {best}/{len(terms)} 个词，"
                 f"**这份文件里可能根本没有这件事**。")
    return {"pages": numbers, "text": "\n\n".join(parts), "chars": total, "note": note}


ASK_SYSTEM_PROMPT = """你在读一份中国 A 股的披露文件（年报、公告、研究报告或调研纪要）。

规矩：
1. **只用给你的这几页内容回答。** 这几页里没有的，就说"这几页里没有"，
   不要用你的常识补，也不要推测。
2. **每一个数字、每一句结论后面标出页码**，写成「（第 30 页）」。
   标不出页码的话就不要写那句话。
3. 原文是表格的地方，`|` 是单元格分隔符。**一格是空的就是空的** ——
   那说明这个科目本期没有数，不是 0，更不能拿旁边那一列的数顶上。
4. 金额的单位写在表头（元 / 万元 / 亿元）。**先找到单位再报数**。
5. 中国上市公司的报表里，合并报表和母公司报表长得一模一样并排着。
   **看清楚你引的是哪一张**，说不清就注明"未确认是合并还是母公司"。

回答用中文，简短，先给结论再给依据。"""


def build_prompt(question: str, context: str, title: str) -> str:
    return (f"文件：{title}\n\n"
            f"以下是这份文件里跟问题相关的几页原文：\n\n{context}\n\n"
            f"问题：{question}")


def rows_to_pages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """库里的行 → `pdfread` 那套页结构。两边字段一样，这里只做类型收拢。"""
    return [{"page": int(row["page"]), "mode": row["mode"], "text": row["text"] or "",
             "tables": int(row["tables"] or 0), "note": row["note"] or ""} for row in rows]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# ── 读完自动出结果 ─────────────────────────────────────────────────────────
#
# **一个空输入框不是产品。** 上传一份 200 页的年报，想要的是「这份文件说了什么」，
# 而不是先自己想出一个好问题 —— 想问题恰恰是最难的那一步。
#
# 做法：按文件类型走一张**固定的研究清单**，每一项各自检索（本地、免费），
# 把命中的页并起来，**一次模型调用**产出一份结构化的结果。
#
# 为什么是固定清单而不是"让模型自己看着办"：
# 220 万字喂不进去，总要挑几页。**挑法必须是可解释的** ——
# 让模型自己挑，它会给你一份看起来完整、其实漏掉重点的摘要，而你看不出漏了什么。
# 固定清单挑错了你至少知道它在找什么，也知道哪一条没找到。

CHECKLISTS: dict[str, tuple[str, ...]] = {
    "年报": (
        "主营业务构成：各分部收入与占比",
        "营业总收入、营业成本、三项费用与研发费用",
        "归母净利润、毛利率、净利率",
        "现金分红方案：每股派息、分红总额、股利支付率",
        "经营活动现金流净额，与净利润是否匹配",
        "有息负债、货币资金、资产负债率",
        "前五名客户与前五名供应商的集中度",
        "募集资金投向与在建工程进展",
        "管理层在讨论与分析里说的主要变化和原因",
        "风险因素与重大诉讼、担保、关联交易",
    ),
    "公告": (
        "这条公告说的是什么事",
        "涉及的金额、比例、期限、价格上下限",
        "生效条件与需要谁批准",
        "对公司或股东有什么约束，需要跟踪哪些日子",
    ),
    "研报": (
        "核心观点与投资建议",
        "盈利预测：未来几年的收入与净利润预测值",
        "估值方法、目标价与对应的倍数",
        "关键假设，以及哪些假设最容易被证伪",
        "风险提示",
    ),
}
DEFAULT_CHECKLIST = "年报"

_KIND_HINTS = (
    ("研报", ("研究报告", "深度报告", "首次覆盖", "评级", "目标价", "证券研究")),
    ("年报", ("年度报告", "半年度报告", "季度报告", "年报", "中报", "季报")),
    ("公告", ("公告", "决议", "回购", "解禁", "关于")),
)


# ── 标题与标签：从第一页读出来，不用文件名 ─────────────────────────────────
#
# 贴链接读进来的文件原来用 URL 最后一段当标题，于是列表里是
# `H3_AP202405221634315503_1.pdf` —— **对读的人零信息量**，两份研报并排放着
# 分不出哪份是哪份。而文件自己第一页上就印着标题。
#
# 四份实测文件的第一页各不相同（见 tests/test_document_title.py 里的原文）：
#   年报   第 0 行就是完整标题「贵州茅台酒股份有限公司2026年半年度报告」
#   公告   第 0 行是「证券代码：… 公告编号：…」，标题拆在第 3–5 行
#   研报   第 0 行是免责声明套话，第 5 行才是「寒武纪-U（688256.SH）首次覆盖报告」
# 所以要先把套话和元数据行挑掉，再看剩下的第一行；短到像个公司名就往下接。

# 第一页上的套话。**认出来只为了跳过**，不做别的判断。
_BOILERPLATE = ("免责声明", "证券研究报告", "请务必阅读", "本公司具备证券投资咨询",
                "保证本公告内容不存在", "承担法律责任", "分析师承诺")
# 元数据行：代码、简称、编号。它们是标签的原料，不是标题。
_META_LINE = re.compile(r"^(证券|公司|股票)?(代码|简称|编号)[:：]")
# 正文开头：编号小节、项目符号、"本公司/本报告"。到这里就该停了。
_BODY_START = re.compile(r"^([一二三四五六七八九十]+[、.]|[➢●■◆·]|\d+[、.]\s|本公司|本报告|目\s*录)")


def _title_lines(pages: list[dict[str, Any]] | None) -> list[str]:
    if not pages:
        return []
    first = next((p for p in pages if int(p.get("page") or 0) == 1), None) or pages[0]
    out: list[str] = []
    for raw in (first.get("text") or "").splitlines()[:40]:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or len(line) < 4:
            continue
        if any(hint in line for hint in _BOILERPLATE) or _META_LINE.match(line):
            continue
        out.append(line)
    return out


# 一份中国披露文件的标题，收尾几乎总是这几个词之一。
# **判"完整"靠结尾而不是长度** —— 长度那一版把公告断在了「与实际」。
_TITLE_ENDS = re.compile(
    r"(报告|公告|说明|意见|议案|纪要|预案|通知|承诺函|问询函|回复|摘要|草案|安排|办法|细则)$")

def guess_title(pages: list[dict[str, Any]] | None, fallback: str = "") -> str:
    """从第一页读出这份文件叫什么。读不出来就用 `fallback`（文件名）。

    **短到像个公司名就往下接**：公告的标题是拆开排版的
    （「中科寒武纪科技股份有限公司」/「关于公司 2026年半年度募集资金存放、管理与实际」/
    「使用情况的专项报告」三行），只取第一行会得到一个公司名，那跟文件名一样没用。
    """
    lines = _title_lines(pages)
    if not lines:
        return fallback
    title = lines[0]
    # 接下去几行，直到**这一行读起来是完整的**、或者撞上正文。
    #
    # 判"完整"不能只看长度：实测公告那份在 24 字处断成
    # 「…募集资金存放、管理与实际」——「实际」后面还有「使用情况的专项报告」。
    # 所以看结尾：以「报告/公告/说明/意见/议案/纪要/预案」这类文书名收尾才算完整。
    for line in lines[1:5]:
        if _BODY_START.match(line) or len(title) >= 70:
            break
        if _TITLE_ENDS.search(title):
            break
        title += line
    return re.sub(r"\s+", "", title)[:90] or fallback




_CODE = re.compile(r"(?:证券|公司|股票)?代码[:：]\s*([0-9]{6})|[（(]\s*([0-9]{6})\s*\.?(?:SH|SZ|BJ)?\s*[)）]")
_SHORT = re.compile(r"(?:证券|公司|股票)?简称[:：]\s*([^\s，,；;]{2,12})")
_PERIOD = re.compile(r"(20\d\d)\s*年?\s*(半年度|年度|第[一二三四]季度|一季度|三季度)报告")
# 公告编号。**三家写法各不相同**，这条正则是照着实测文件改宽的：
#   寒武纪   `公告编号：2026-027`
#   贵州茅台 `编号：临  2026－031`   ← 只写「编号」、值以「临」打头、破折号是全角
# 所以：「公告」两个字可有可无、值允许中文前缀、允许全角破折号和内部空格。
# 值取到行末或下一个分隔符，再把空白挤掉。
_ANN_NO = re.compile(r"(?:公告)?编号[:：]\s*([一-鿿]{0,3}\s*[0-9]{4}\s*[\-－—]\s*[0-9A-Za-z]+)")
_RPT_DATE = re.compile(r"(20\d\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_PERIOD_NAME = {"半年度": "半年报", "年度": "年报", "第一季度": "一季报", "一季度": "一季报",
                "第二季度": "中报", "第三季度": "三季报", "三季度": "三季报", "第四季度": "年报"}


def guess_tags(pages: list[dict[str, Any]] | None, kind: str = "") -> list[str]:
    """给这份文件几个标签：**类型 · 是谁 · 哪一期**。

    每一条都从第一页抽出来，**抽不到就不给** —— 猜一个标签比没有标签糟：
    列表上那几个标签是用来一眼分辨两份文件的，一个猜错的标签会让人打开错的那份。

    刻意不放的：页数、字数（facts 那行已经有了）、解析器的内部计数
    （「双栏 4」「表格 11」那种上一版撤掉过 —— 读的人拿它做不了任何判断）。
    """
    if not pages:
        return []
    first = next((p for p in pages if int(p.get("page") or 0) == 1), None) or pages[0]
    head = (first.get("text") or "")[:1500]
    tags: list[str] = []
    if kind:
        tags.append(kind)

    code_hit = _CODE.search(head)
    code = (code_hit.group(1) or code_hit.group(2)) if code_hit else ""
    short = _SHORT.search(head)
    who = " ".join(part for part in (code, short.group(1) if short else "") if part)
    if who:
        tags.append(who)

    period = _PERIOD.search(head)
    if period:
        tags.append(f"{period.group(1)} {_PERIOD_NAME.get(period.group(2), period.group(2))}")
    else:
        # 编号跟日期一样**只在标题块里找**：正文里也会出现「编号」
        #（引用别的公告、批复文号），而那些看起来跟本文编号一模一样。
        ann = _ANN_NO.search(_head_block(first))
        if ann:
            # **公告有编号就用编号，不再去找日期。**
            # 实测那份募集资金专项报告被打上了 `2023-04-06` —— 那是正文里
            # 募集资金**到账**的日子，不是这份公告的日期。
            # 抽出来的编号里可能夹着排版空格（「临  2026－031」），挤掉；
            # 全角破折号统一成半角，不然同一家公司两份公告的标签长得不一样。
            number = re.sub(r"\s+", "", ann.group(1)).replace("－", "-").replace("—", "-")
            tags.append(f"公告 {number}")
        else:
            # 研报没有"报告期"，日期印在标题底下。**只在标题块里找** ——
            # 往正文里找会捞到批复文号的年份、到账日、合同日期这些，
            # 而它们看起来跟文档日期一模一样。
            date = _RPT_DATE.search(_head_block(first))
            if date:
                tags.append(f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}")
    return tags[:4]


def _head_block(page: dict[str, Any]) -> str:
    """第一页的**标题块**：正文开始之前那几行。

    正文的起点认得出来：编号小节（「一、」）、项目符号（「➢」）、
    或者「本公司董事会…」这类固定开场。认不出来就取前 10 个非空行 ——
    标题和它底下的日期从来不会排到那么后面。

    **套话要先跳过再判正文开头。** 顺序反了当场就错：研报第一行的
    「**本公司**具备证券投资咨询业务资格…」正好撞上用来认正文的「本公司」
    （公告的正文确实以「本公司董事会…」开头），于是标题块在第 0 行就截断，
    日期标签整个没了。
    """
    lines: list[str] = []
    for raw in (page.get("text") or "").splitlines()[:40]:
        line = raw.strip()
        if not line:
            continue
        if any(hint in line for hint in _BOILERPLATE):
            continue
        if _BODY_START.match(line):
            break
        lines.append(line)
        if len(lines) >= 10:
            break
    return "\n".join(lines)


def detect_kind(title: str, pages: list[dict[str, Any]] | None = None) -> str:
    """这是年报、公告还是研报。**先看标题，标题认不出再看前两页。**

    认错了不致命：清单里那几条问题问不出东西时，结果里会写「没找到」——
    比按错的清单硬答一份好。
    """
    head = str(title or "")
    if pages:
        head += " " + " ".join(p.get("text", "")[:400] for p in pages[:2])
    for kind, hints in _KIND_HINTS:
        if any(hint in head for hint in hints):
            return kind
    return DEFAULT_CHECKLIST


# 一份结果最多喂多少页 / 多少字。**比单次问答宽，但不能宽太多**：
# 喂四十页出来的东西你没法核对，那就退回成了"随便找个模型读一遍"。
MAX_DIGEST_PAGES = 22
MAX_DIGEST_CHARS = 60_000


def build_digest_context(pages: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    """按清单逐条检索，把命中的页并起来。**检索全在本地，这一步不花钱。**

    返回里带 `covered`：清单里哪几条找到了页、哪几条一页都没命中。
    **没命中的要报出来** —— 一份缺了两条的结果和一份完整的结果，
    看起来是一样的，而它们的价值完全不同。
    """
    items = CHECKLISTS.get(kind) or CHECKLISTS[DEFAULT_CHECKLIST]
    picked: dict[int, dict[str, Any]] = {}
    covered: list[dict[str, Any]] = []
    for item in items:
        ranked = rank_pages(pages, item)
        hits = [p["page"] for p in ranked[:4]]
        covered.append({"item": item, "pages": hits})
        for page in ranked[:4]:
            picked.setdefault(page["page"], page)

    ordered = sorted(picked.values(), key=lambda p: p["page"])[:MAX_DIGEST_PAGES]
    parts, total = [], 0
    used: list[int] = []
    for page in ordered:
        chunk = f"【第 {page['page']} 页 · {page['mode']}】\n{page['text']}"
        if total and total + len(chunk) > MAX_DIGEST_CHARS:
            break
        parts.append(chunk); used.append(page["page"]); total += len(chunk)
    return {"kind": kind, "items": list(items), "covered": covered,
            "pages": used, "text": "\n\n".join(parts), "chars": total,
            "missed": [row["item"] for row in covered if not row["pages"]]}


DIGEST_SYSTEM_PROMPT = """你在读一份中国 A 股的披露文件，要给出一份**能被核对**的阅读结果。

只输出 JSON。下面这段是**形状示范**：

{"watch": [{"point": "一句话，最该跟进的事", "pages": [5, 7]}],   // 三条
 "items": [{"title": "清单里那一条的原文",
            "verdict": "一句话结论。**只有一句**，别写成段落。",
            "figures": [{"label": "科目名", "value": "○○.○○ 亿", "note": "同比 +○.○%"}],
            "tables": [{"title": "这张表叫什么",
                        "columns": ["科目（百万元）", "上一年", "本年"],
                        "rows": [["某个科目", "○○○", "○○○"],
                                 ["另一个科目", "-○○", "○○"]],
                        "note": "出自第 ○ 页"}],
            "pages": [7, 30],
            "found": true}]}

0. **上面那段里没有一个真数字，你输出里的每一个数都必须能在给你的原文里找到。**
   这一条是撞出来的：示范里原先带着一个别家公司的营业收入，模型照抄进了一份研报的
   结果，然后自己补了句「口径有误」—— 而那个数已经印在页面上了。
   在一个「每个数都能核」的工具里凭空冒出一个真实存在的数，**比没有这个数糟得多**。

规矩：
1. **只用给你的这几页内容。** 没有的把 `found` 写 false、`verdict` 写「这几页里没有」，
   `figures` 和 `tables` 留空。**不要跳过它** —— 漏掉的那一条正是读的人最需要知道的。
2. **每条都要有 pages。** 标不出页码的话就不要写那条结论。
3. `verdict` **是一句话**，不是一段。数字一个都不许留在句子里：
   孤立的数进 `figures`（`label` 是它叫什么、`value` 是数值带单位、`note` 放同比或口径），
   **成组的数进 `tables`**。
   **这一条是这份结果好不好读的全部关键** —— 数字塞进句子里就又变成一堵墙了。
3b. `figures` 里只放**真的数**：金额、比率、倍数、股数、日期。
   **「风险条数 3 条」「共 5 项」这种计数不是数字**，那三条风险本身就写在
   `verdict` 里了，再占一格只是重复。
   `note` 是口径（同比、单位换算、哪张表、推算算式），**十几个字，一句话** ——
   不要把原文整句抄进来（实测出现过 `note` 里塞一句「原文表述："2024—2026 年
   营业收入为 15.36/26.74/33.42 亿元"」，而那串数正是该进 `tables` 的东西）。
4. **什么算成组：同一个科目有多个年份、多个分部、多家可比公司。**
   一行一个科目、一列一个年份或口径。写成
   「营收 2023A 709 → 2024E 1536 → 2025E 2674」这种**箭头串是错的**：谁都对不齐，
   也就看不出增速是在哪一年掉下来的。排成表一眼就看出来。
   原文本来就是一张表的（盈利预测、分部收入、可比公司估值、分红方案、
   募投项目进度），**照抄它的行和列**，别改结构。
   **整份结果最多三张表，每张最多八行。**超了就只留最要紧的那几行，
   并在这张表的 `note` 里写「原表还有 N 行」—— 写不完被掐断的话整份都作废，
   而一份少了三行的表还能用。
5. 单位写在表头那一格里（`"科目（百万元）"`、`"金额（亿元）"`），
   **不要每个格子都带单位** —— 带了单位那一列数字就对不齐了。
   `figures` 的 `value` 反过来，要带单位。
6. 表格里 `|` 是单元格分隔符，**一格是空的就是空的** —— 那说明这个科目没有数，
   不是 0，更不能拿旁边那一列顶上。输出的表里也照样留空。
7. 金额单位写在表头（元 / 万元 / 亿元），**先找到单位再报数**；
   `figures` 的 `value` 换算成「亿」并写出来。
8. 合并报表和母公司报表并排着，**看清楚你引的是哪一张**。
9. **自己算出来的数**要写「推算：算式」（`figures` 写在它的 `note` 里，
   表格写在表的 `note` 里并说清是哪一行）。实测过一次不标的：
   给了个 89.55% 的毛利率，年报上根本没有这个数，读的人核不到之后整份都不敢信了。
10. 一行里有两列数时，**左边那列是本期、右边是上期**。读反了每一条结论都是反的，
    而它看起来完全正常。

`watch` 三条：从上面挑最该跟进的，各一句话，各带页码。"""


def build_digest_prompt(title: str, kind: str, items: list[str], context: str) -> str:
    listing = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))
    return (f"文件：{title}（按「{kind}」的清单读）\n\n清单：\n{listing}\n\n"
            f"以下是这份文件里跟清单相关的几页原文：\n\n{context}")


# ── 从专项报告里抽募投进度 ─────────────────────────────────────────────────
#
# **这是第一条「读文档的结果喂给另一个功能」的链子。**
#
# 甘特图原来缺募投这条泳道，理由是"库里没有这项数据"—— 那句话对（没有表），
# 但公告里有：「募集资金存放、管理与实际使用情况的专项报告」里是一张结构化的表，
# 承诺投资额 / 累计投入 / 投入进度% / 预定可使用状态日期，一项一行。
# 实测寒武纪那份 21 页的报告，两次发行五个项目全在里面，读一次 2 分钱。

_FUND_HINTS = ("募集资金存放", "募集资金使用", "募集资金管理", "募投", "募集资金专项")


def looks_like_fundraising(title: str, pages: list[dict[str, Any]] | None = None) -> bool:
    """这份文件里可能有募投进度表吗。**只用来决定要不要显示那个按钮**，判错不致命。"""
    head = str(title or "")
    if pages:
        head += " " + " ".join(p.get("text", "")[:600] for p in pages[:3])
    return any(hint in head for hint in _FUND_HINTS)


FUND_QUERIES = (
    "募集资金承诺投资项目 承诺投资总额 截至期末累计投入金额 投资进度",
    "项目达到预定可使用状态日期 是否已结项",
    "募集资金变更用途 永久补充流动资金 节余资金",
)

FUND_SYSTEM_PROMPT = """你在读一份中国 A 股「募集资金存放、管理与实际使用情况的专项报告」，
要把里面的**募投项目进度表**抽成结构化数据。

只输出 JSON。下面这段是**形状示范，里面一个真数字都没有**：

{"projects": [
  {"batch": "哪一次发行（照抄报告里的说法）",
   "project": "项目名（照抄）",
   "committed_wan": 0.00,           // 承诺投资总额，单位万元
   "invested_wan": 0.00,            // 截至期末累计投入，单位万元
   "progress_pct": 0.00,            // 投入进度，百分数的数值
   "due_on": "○○○○-○○",             // 预定可使用状态日期；只到月就写到月
   "settled": false,                // 是否已结项
   "pages": [0]}                    // 这一行的数字来自哪几页
]}

**示范里的 0 是占位，不是数据。你输出的每一个数都必须能在给你的原文里找到。**
这一条是撞出来的：示范里原先带着某家公司专项报告的真实承诺投资额，
而这个接口的输出**直接落库、直接排进甘特图** ——
照抄一个别家的金额进来，它会长成一条看起来完全正常的承诺。

规矩：
1. **一个项目一行**，别把同一次发行的多个项目合并成一行。
2. **单位统一成万元。** 报表里写「元」的要除以 10000；写「万元」的照抄。
   拿不准单位就把这一项整个丢掉 —— 数量级错一位比缺一行糟得多。
3. 表格里 `|` 是单元格分隔符，**空格子就是空的**，不要拿旁边那列顶上。
4. `due_on` 只能来自「预定可使用状态日期」那一列。**推不出来就写 null**，
   不要拿报告期末或者别的日期凑。
5. **每一行都要有 pages。** 抽不出页码的那一行不要输出 ——
   核不回原文的数没有资格进库。
6. 已结项的项目也要输出（`settled: true`），它们是"承诺兑现了没有"的证据。

找不到募投项目表就输出 {"projects": []}。不要编。"""


def build_fund_context(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """按三条检索词并起来，只喂命中的页。跟出结果那一步同一套做法。"""
    picked: dict[int, dict[str, Any]] = {}
    for query in FUND_QUERIES:
        for page in rank_pages(pages, query)[:6]:
            picked.setdefault(page["page"], page)
    ordered = sorted(picked.values(), key=lambda p: p["page"])[:14]
    parts, total, used = [], 0, []
    for page in ordered:
        chunk = f"【第 {page['page']} 页 · {page['mode']}】\n{page['text']}"
        if total and total + len(chunk) > 40_000:
            break
        parts.append(chunk); used.append(page["page"]); total += len(chunk)
    return {"pages": used, "text": "\n\n".join(parts), "chars": total}


# ── 输出里的数，回所引的页去核 ────────────────────────────────────────

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 带金额单位的数：`59.96 亿`、`70,246.61 万元`、`1,234.00 元`。
# 后面跟 % 的不算 —— 那是算出来的比率，不是抄来的金额。
_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:亿元|亿|万元|万|元)(?!\s*/)")
_YEAR = re.compile(r"^(19|20)\d\d$")


def _numbers_in(text: str) -> list[float]:
    out: list[float] = []
    for raw in _NUM.findall(text or ""):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def unverified_figures(digest: str, pages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """挑出**在它自己标注的那几页里核不到**的数字。

    ## 为什么要有这一步

    提示词第 0 条写着「你输出里的每一个数都必须能在给你的原文里找到」。
    那是一句承诺，而承诺要有人管。2026-08-19 实测撞到一条：

        结果：「财务公司同业存放款项净增加 739.9 亿」（引第 5、7、33 页）
        原文第 33 页：「客户存款和同业存放款项净增加额 7,383,004,563.78」= 73.83 亿

    **差十倍，而且这个数是它论证「706.91 亿现金流不是主营回款」的唯一论据** ——
    73.83 亿只占 706.91 亿的一成，撑不起那个结论。数错了，结论跟着错。
    这类错最贵：页码、格式、语气全都对，只有数是坏的。

    ## 怎么核

    **数值比对，不是字符串包含。** 原文写 `70,690,750,119.06`，模型写 `706.91 亿`——
    字符串永远对不上（第一版就是这么写的，四份结果误报 63 处）。
    所以把两边的数都解析出来，按元 / 万元 / 原样三种口径比，容差取模型那个数的
    末位（它是四舍五入过的）。

    宁可漏报也不误报：一份天天误报的提示，三天之后就没人看了。
    """
    try:
        payload = json.loads(digest)
    except (ValueError, TypeError):
        return []

    by_page = {int(page.get("page", 0)): _numbers_in(page.get("text") or "") for page in pages}
    everywhere = [v for nums in by_page.values() for v in nums]
    suspects: list[dict[str, str]] = []

    def check(block: Any, cited: list[int]) -> None:
        pool = [v for p in cited for v in by_page.get(p, ())]
        if not pool:
            return                      # 那几页一个字都没读出来，核不了也不能算错
        # **只核带金额单位的数。** 比率是算出来的：同比 +438.84%、占比 45.32%
        # 这类数原文里本来就没有，一起核就成了天天误报（实测第二版误报 39 处）。
        # 金额是抄的，抄错了才是问题 —— 739.9 亿那条正是这一类。
        text = json.dumps(block, ensure_ascii=False)
        for match in _MONEY.finditer(text):
            raw = match.group(1)
            plain = raw.replace(",", "")
            digits = plain.replace(".", "")
            if _YEAR.match(plain) or len(digits) < 3 or plain in {str(p) for p in cited}:
                continue
            try:
                value = float(plain)
            except ValueError:
                continue
            # 模型那个数是四舍五入过的，容差按它的末位给，再放宽半档
            decimals = len(plain.split(".")[1]) if "." in plain else 0
            tol = 0.5 * (10 ** -decimals) * 1.05
            # 元 → 亿、万元 → 亿、原样，三种口径
            if any(abs(v / scale - value) <= tol
                   for v in pool for scale in (1.0, 1e4, 1e8)):
                continue
            # **分两类。** 「文档里有、只是页码引错了」和「整份文档里都没有」
            # 严重程度差得远：前者翻页能找到，后者多半是编的。
            elsewhere = any(abs(v / scale - value) <= tol
                            for v in everywhere for scale in (1.0, 1e4, 1e8))
            suspects.append({"value": plain, "where": "别的页" if elsewhere else "没有"})

    for key in ("watch", "items"):
        for block in payload.get(key) or []:
            if not isinstance(block, dict):
                continue
            cited = [int(p) for p in (block.get("pages") or []) if isinstance(p, (int, float))]
            if not cited:
                continue                # 没标页码的由提示词第 2 条管，不在这里判
            check(block, cited)

    seen: set[str] = set()
    return [s for s in suspects if not (s["value"] in seen or seen.add(s["value"]))]
