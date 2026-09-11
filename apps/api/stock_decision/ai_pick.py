"""AI 选股：一句话变成一套跑得起来的条件，代码在全 A 上跑，模型再从命中里挑。

## 这一层跟「模型复核」不是一回事

页面底下已经有一个「模型复核」：你先选一套规则，它把前 N 家逐家标成
值得深入／先放着／直接排除。**那是模型在读代码选出来的名单。**

这里反过来：**你说你要什么，模型负责把它翻成条件，代码去筛。**
差别不在谁更聪明，在于规则表达不了的那部分——
「PE ≤ 15」写得出来，「现金流扎实、不靠一次性收益、别在热门赛道里」写不出来。
前者是八套预置策略已经覆盖的，后者是这个功能存在的全部理由。

## 分工：模型翻译，代码执行

```
你的一句话
  → 模型翻成 {字段, 比较符, 阈值} × N + 行业名单 + 要不要联网
  → 代码在 5541 只上跑（免费、确定、可复现）
  → 模型从命中里挑几家、说为什么
```

**筛选这一步永远是代码做的。** 模型给的是条件，不是名单——
它没法把一只没过条件的票塞进结果里，因为它根本不经手那 5541 行数据。

翻译出来的条件**摊开给你看，而且可以存成你自己的策略**。这是这套做法
相对「模型直接给你五只票」的关键区别：你能看见它凭什么筛，不同意就改。
一个说不出自己凭什么的荐股结果，跟股吧里的贴子没有区别。

## 为什么要联网，以及联网只准干一件事

底座里有申万行业，**没有概念**。「固态电池」「低空经济」「算力租赁」这些词
在库里一个字段都对不上，规则一条都写不出来——这是不联网就绝对做不到的那部分。

所以联网只干一件事：**把一个概念词变成一串公司名**。

而且落地方式是代码，不是模型：搜回来的正文里，凡是**逐字出现**了底座里某家
公司的名字或代码，那家才算数。模型不经手这个名单，所以它没法凭记忆
往里塞公司。每一个命中都带着那篇文章的链接——你可以自己去看它凭什么算。

数字一律不从网上取。这跟 websearch.py 里那条铁律是同一条：
网页上的财务数字过期、口径不同、抄错的都有，而库里的有唯一来源。

## 三道防幻觉的约束，一条都没松

1. **数字由代码算**：模型读到的每个数都是从底座取出来的，它不许自己算、自己报。
2. **引不出数据的主张丢掉**：挑中的理由必须落在给它的那几个数上。
3. **只能从代码选出来的行里挑**：模型回的是行号（index），不是股票代码——
   越界的行号直接丢。它连编一个代码出来的机会都没有。
"""

from __future__ import annotations

import math
import re
from typing import Any

from . import llm
from .jsonio import loads_or_reformat
from .llm import ai_available

# 一次最多翻出几条条件。**不是怕贵，是怕筛没。**
# 条件越多命中越少，而模型倾向于把你说的每个形容词都变成一条门槛——
# 「便宜、质量好、增长快、现金流足、别太热门」六条一叠，全市场剩两只。
MAX_RULES = 6

# 联网最多搜几次。websearch 自己也有封顶，这里再收一道：
# 概念词就一个，搜三次已经足够找齐名单，再多是在烧额度。
MAX_THEME_QUERIES = 2

# 交给模型挑的候选上限。**这个数决定了这次调用的价钱。**
# 每行大约 150 字，40 行 6000 字——再宽模型也读不细，而钱是线性涨的。
PICK_POOL = 40

# 合法的比较符。跟 strategies.Rule 用的是同一套，多一个都不认。
OPERATORS = ("gte", "lte", "gt", "lt")

# 公司名逐字匹配的最短长度。全 A 里最短的名字是三个字（实测：3 字 688 家、
# 4 字 4711 家、没有两字的），所以这里不需要为两字名开特例。
MIN_NAME_LEN = 3

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_HAN = re.compile(r"[一-鿿]")


class PlanError(RuntimeError):
    """模型没能把这句话翻成一套能跑的条件。**要说清楚是哪一步不行**，
    不能笼统报「AI 选股失败」——用户下一步该改问法还是该去同步数据，
    完全取决于这个区别。"""


# ---------------------------------------------------------------- 默认问法


# 页面上给的默认选项。
#
# **每一条都是规则表达不了的**，这是挑选它们的唯一标准。「PE 小于 15」不在这里，
# 因为「低估防御型」已经有了——把一个现成策略换成一句话再花钱跑一遍，
# 是在卖弄而不是在帮忙。
#
# `needs` 是这条问法真正依赖的字段：底座里这些字段没同步时，页面把它标成
# 暂不可用并说明原因，而不是让人点了之后拿到一份空清单。
# （门槛没到的功能不要沉默——跟策略卡上的 unavailable_reason 是同一条规矩。）
#
# `short` 是按钮上的四五个字，`text` 是点下去填进输入框的整句。
# **原来按钮上直接印整句**，五条并排是一堵墙——使用者的原话是
# 「解释文字太多了，我看的都没兴趣去用了」。按钮该短到一眼扫完，
# 完整那句在鼠标停上去和点完之后都看得到。
DEFAULT_ASKS: tuple[dict[str, Any], ...] = (
    {"short": "赚的是真钱",
     "text": "赚到的是真钱：利润能变成现金流，不是靠应收账款堆出来的",
     "needs": ("ocf_per_share", "eps"), "web": False},
    {"short": "跌了但没变坏",
     "text": "跌了很多，但生意本身没变坏",
     "needs": ("pb", "roe"), "web": False},
    {"short": "小市值真增长",
     "text": "小市值但在真增长，别是刚上市那种",
     "needs": ("total_market_cap", "revenue_growth"), "web": False},
    {"short": "固态电池",
     "text": "固态电池相关的公司里，估值还没被炒上去的",
     "needs": ("pe_ttm",), "web": True},
    {"short": "算力／AI 基建",
     "text": "算力／AI 基建沾边，而且现在是真的在赚钱",
     "needs": ("net_profit", "roe"), "web": True},
)


def usable_default_asks(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """默认问法配上「现在能不能用」。字段没同步就说是哪个字段，别只说不可用。"""
    labels = {f["field"]: f["label"] for f in fields}
    usable = {f["field"] for f in fields if f.get("usable")}
    out = []
    for ask in DEFAULT_ASKS:
        missing = [labels.get(name, name) for name in ask["needs"] if name not in usable]
        out.append({"short": ask["short"], "text": ask["text"], "web": ask["web"],
                    "usable": not missing,
                    "unavailable_reason": ("底座里还没有" + "、".join(missing) if missing else "")})
    return out


# ---------------------------------------------------------------- 第一步：翻译


PLAN_SYSTEM_PROMPT = """你在帮一位 A 股个人投资者，把他用大白话说的选股要求，翻译成一套机器能执行的筛选条件。

**你不选股票，你只写条件。** 后面会由程序拿着你写的条件，在全市场五千多只股票上跑一遍。你看不到任何股票，也不需要看到。

严格遵守：
1. `rules` 里的 field 只能从「可用字段」清单里挑，一个字都不能改，也不要发明新字段。
   清单里没有的概念（比如「负债率」「机构持仓」），就不要写成条件——宁可少一条。
2. 阈值要能筛出东西。A 股五千多只，一条「净利润同比 ≥ 100%」大概只剩两百只，
   五条这样的条件叠起来就一只不剩了。**宁可宽，让人看到结果再收紧。**
   条件最多 6 条，通常 2–4 条就够。
3. 行业只能从「库里的行业名」清单里逐字挑，那是申万分类。用户说「制造业」这种大类，
   就挑出对应的几个具体行业名；对不上就留空数组，不要硬凑。
4. 概念、题材、赛道（例如「固态电池」「低空经济」「算力」）**在库里没有任何字段**，
   不要试图用行业去近似。把概念词填进 theme，程序会去联网找出哪些公司算。
   用户没提概念就把 theme 留空。
5. `reading` 用一句话说你是怎么理解他这句话的，特别是你做了哪些取舍
   （例如「他说的『便宜』我理解成市净率低而不是市盈率低，因为他同时说了周期」）。
   这句话会原样给他看，他要靠它判断你有没有理解错。
6. 值里不要使用英文双引号；需要引用时用「」，否则会破坏 JSON。

只输出一个 JSON 对象：
{"name": "给这套条件起个不超过 12 字的名字", "summary": "一句话说这套条件在找什么", "rules": [{"field": "pe_ttm", "op": "lte", "value": 20}], "sort_field": "pe_ttm", "sort_desc": false, "industries": [], "theme": "", "theme_queries": [], "reading": "我把你这句话理解成……"}

op 只能是 gte（≥）、lte（≤）、gt（>）、lt（<）四个之一。
sort_field 也必须来自可用字段清单；sort_desc 为 true 表示由大到小。"""


def build_plan_prompt(question: str, fields: list[dict[str, Any]], industries: list[str]) -> str:
    """**只把可用字段喂给它。**

    覆盖率不够的字段（例如眼下的股息率、趋势面那几列整列为空）如果也列出来，
    模型会理直气壮地用它们写条件，然后跑出来零命中——而页面上看起来像
    「市场上没有这样的公司」，不像「这个字段我们还没同步」。
    """
    usable = [f for f in fields if f.get("usable")]
    if not usable:
        raise PlanError("全市场底座还没有可用字段，先在数据状态页跑一次「全市场底座」")
    listing = "\n".join(
        f"- {f['field']}：{f['label']}"
        + (f"（{f['hint']}）" if f.get("hint") else "")
        + (f"　单位 {f['unit']}" if f.get("unit") else "")
        for f in usable
    )
    return (
        f"他的要求原话是：{question}\n\n"
        f"可用字段（field 只能从这里挑）：\n{listing}\n\n"
        f"库里的行业名（industries 只能从这里逐字挑，共 {len(industries)} 个）：\n"
        f"{('、').join(industries)}\n\n"
        "请把他这句话翻译成条件。"
    )


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # NaN 和 inf 会一路穿过 float()，塞进 SQL 之后表现是「条件没起作用」——
    # 不是报错，是静默地筛不掉任何东西，比报错难查得多。
    return out if math.isfinite(out) else None


# 重排坏 JSON 时给模型看的目标结构。**跟各自主提示词里那一行同形** ——
# 写岔了重排会照另一个形状去改，改出来照样是合法 JSON，只是字段对不上。
PLAN_SHAPE = ('{"name": "…", "summary": "…", "rules": [{"field": "…", "op": "…", "value": 0}], '
              '"sort_field": "…", "sort_desc": false, "industries": [], "theme": "", '
              '"theme_queries": [], "reading": "…"}')
PICK_SHAPE = ('{"picks": [{"index": 1, "why": "…", "reasons": ["…"], "concerns": ["…"]}], '
              '"passed": [{"index": 2, "why": "…"}], "note": "…"}')


def parse_plan(text: str, fields: list[dict[str, Any]], industries: list[str]) -> dict[str, Any]:
    """把模型的翻译收进合法范围。**丢掉什么必须记下来并显示。**

    静默丢弃是这里最危险的做法：模型写了「负债率 ≤ 50%」被丢掉，而页面上
    只显示剩下的两条，用户会以为负债率那条生效了——他据此以为筛过的东西，
    其实一次都没筛过。
    """
    try:
        plan, _ = loads_or_reformat(text, task="ai-pick", expect="object",
                                    shape=PLAN_SHAPE, timeout=90)
    except ValueError as exc:
        raise PlanError(f"模型没有返回可解析的条件：{exc}") from exc

    usable = {f["field"]: f for f in fields if f.get("usable")}
    known = {f["field"] for f in fields}
    dropped: list[str] = []

    rules: list[dict[str, Any]] = []
    for item in (plan.get("rules") or [])[: MAX_RULES * 2]:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        op = str(item.get("op") or "").strip()
        value = _number(item.get("value"))
        if field not in usable:
            # 分两种情况说：字段根本不存在 vs 字段存在但底座没同步。
            # 前者是模型编的，后者是你该去同步数据——用户下一步完全不同。
            dropped.append(f"「{field}」这个字段库里还没有数据" if field in known
                           else f"模型编了一个不存在的字段「{field}」")
            continue
        if op not in OPERATORS:
            dropped.append(f"「{usable[field]['label']}」的比较符 {op} 不认识")
            continue
        if value is None:
            dropped.append(f"「{usable[field]['label']}」的阈值不是一个数")
            continue
        rules.append({"field": field, "op": op, "value": value,
                      "unit": usable[field].get("unit") or ""})
        if len(rules) >= MAX_RULES:
            break

    if not rules:
        raise PlanError(
            "模型没能把这句话翻成一条能跑的条件。"
            + ("原因：" + "；".join(dropped) + "。" if dropped else "")
            + "换个说法试试——把你要的东西说成财务上的样子（多便宜、多赚钱、多大），"
            "而不是只说一个概念。"
        )

    sort_field = str(plan.get("sort_field") or "").strip()
    if sort_field not in usable:
        # 排序字段不合法不是致命错，但**不能沉默地换掉**：
        # 页面上写着「按 X 排」而实际按 Y 排，是这一页刚修好的那个 bug。
        if sort_field:
            dropped.append(f"排序字段「{sort_field}」不可用，改按第一条条件排")
        sort_field = rules[0]["field"]

    picked_industries = [name for name in (plan.get("industries") or [])
                         if isinstance(name, str) and name in set(industries)]
    unknown = [str(name) for name in (plan.get("industries") or [])
               if isinstance(name, str) and name not in set(industries)]
    if unknown:
        dropped.append("库里没有这些行业名：" + "、".join(unknown[:5]))

    # 搜索词由代码拼，不用模型给的。
    #
    # 实测两次跑同一个问题：第一次模型给的是「固态电池」，搜回来 8 篇科普文，
    # 对上 5 家；第二次它换了个说法，**一家都没对上**——概念这一层白跑了，
    # 而页面上看不出差别（结果照样有，只是少了概念这一层）。
    #
    # 我们要的不是「关于这个概念的文章」，是「哪些 A 股公司算这个概念」。
    # 这两个查询稳定地问的是后者，而模型的自由发挥问的经常是前者。
    theme = str(plan.get("theme") or "").strip()[:40]
    queries = [f"{theme} 概念股 A股上市公司 名单", f"{theme} 产业链 相关上市公司"] if theme else []

    sort_desc = bool(plan.get("sort_desc", True))
    return {
        "name": str(plan.get("name") or "这次的条件").strip()[:12] or "这次的条件",
        "summary": str(plan.get("summary") or "").strip()[:120],
        "rules": rules,
        "sort_field": sort_field,
        "sort_desc": sort_desc,
        # 排序标签要带方向。全站的写法都是「X 由低到高」，只写「X」的话
        # 页面上那句「按 X」读不出它到底是从大到小还是从小到大。
        #
        # 括号里的公式要去掉：派生字段的 label 自带公式（「每股现金含量
        # （每股经营现金流 / 每股收益（每股收益为正时才计算））」），
        # 拼上方向之后是一句三十多字的话，页面上那一行会塌。公式在
        # 「可用字段」那里说过了，这里只要名字。
        "sort_label": f"{usable[sort_field]['label'].split('（')[0]} 由{'高到低' if sort_desc else '低到高'}",
        "industries": picked_industries,
        "theme": theme,
        "theme_queries": queries[:MAX_THEME_QUERIES],
        "reading": str(plan.get("reading") or "").strip()[:200],
        "dropped": dropped,
    }


def brief_of(row: dict[str, Any]) -> str:
    """把一家公司压成一行喂给模型。

    **必须喂底座原始行，不能喂筛选结果的行。** run_screen 返回的候选是裁剪过的：
    财务字段只有这套规则用到的那几个会跟出来。实测一次「现金含量 + 市盈率」
    的筛选，模型只能看到市盈率、盈利收益率、市值三个数——它据此写出来的理由
    必然是空的，而空理由读起来跟有依据的理由长得一样。

    年报口径单独补一句：`roe` 是最新报告期（眼下是一季报，单季数字），
    而「这家公司赚钱能力如何」问的是年度概念。两个口径差得很远，
    只给前者会让模型把一季度的 1.9% 当成这家公司的 ROE。
    """
    from .researching import _row_brief

    parts = [_row_brief(row)]
    annual = []
    if row.get("annual_roe") is not None:
        annual.append(f"年报净资产收益率 {round(float(row['annual_roe']), 2):g}%")
    if row.get("annual_gross_margin") is not None:
        annual.append(f"年报毛利率 {round(float(row['annual_gross_margin']), 2):g}%")
    if row.get("annual_report_date"):
        annual.append(f"年报期 {row['annual_report_date']}")
    if annual:
        parts.append(" ｜ ".join(annual))
    return " ｜ ".join(parts)


# ---------------------------------------------------------------- 概念 → 公司


def _strip_publisher(title: str) -> str:
    """去掉标题结尾挂着的媒体名。

    实测两例，都来自同一次「固态电池」检索：

        固态电池离量产还有多远-新华网      → 匹配出 A 股的「新华网」(603888)
        固态电池_百度百科                  → 同一个模式

    中文资讯标题的结尾几乎都是「-站名」或「_站名」。不切掉的话，凡是被
    新华网、每经、证券时报报道过的题材，那家媒体自己就会进名单——
    而它跟这个题材毫无关系。**这不是理论上的风险，是第一次真实检索就撞上的。**
    """
    for sep in ("-", "_", "－", "｜", "|"):
        head, found, tail = title.rpartition(sep)
        # 尾巴要短才像站名（「新华网」「百度百科」），长的多半是标题本身的一部分
        if found and head.strip() and len(tail.strip()) <= 8:
            return head.strip()
    return title


def theme_symbols(documents: list[dict[str, Any]],
                  universe: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """搜回来的正文里，逐字出现了库里哪几家公司。**这一步没有模型参与。**

    让模型从搜索结果里"提取相关公司"是最省事的写法，也是最容易出事的写法：
    它会把记忆里知道的同类公司一起写出来，而那些公司根本没出现在这几篇文章里。
    做成逐字匹配之后，一家公司要进名单，必须有一篇具体的文章提到过它的名字，
    并且那篇文章的链接会跟着一起交出去。

    ## 逐字匹配有一部分错是修不掉的，所以要把证据句一起交出去

    实测「固态电池」一次检索，两类误伤：

        新华网(603888)   ← 正文里抓到了页面的面包屑：「…-新华网　新华网 > > 正文」
        机器人(300024)   ← 「eVTOL、机器人等细分场景」——前面就是顿号，边界完全合法，
                            而这家公司真叫这个名字。**这一条不可判定。**

    第一类能挡掉一部分（见 _strip_publisher），第二类挡不掉：三个字的公司名
    同时是个普通词，字符串层面没有任何信息能区分这两种用法。

    所以这一层的职责是**给出可核对的证据，不是给出正确答案**：
    每一家都带回那句原文和链接，交给模型判断（提示词里写明「有文章提到
    不等于它主营就是这件事」），也摆在页面上让你自己看。实测模型认出了
    新华网：「行业归属完全不相关，列入仅因名单匹配」。

    返回 {symbol: [{title, url, quote}]}——**出处跟着结论一起走**，不是可选的附加信息。
    """
    by_name = {row["name"]: row["symbol"] for row in universe
               if row.get("name") and len(row["name"]) >= MIN_NAME_LEN}
    known_codes = {row["symbol"] for row in universe if row.get("symbol")}
    hits: dict[str, list[dict[str, str]]] = {}

    for doc in documents:
        # websearch 返回的正文字段叫 snippet；content 是别处的叫法，两个都认——
        # 认错一个键的表现是「一条都没匹配上」，看起来像搜索没搜到东西。
        raw_title = str(doc.get("title") or "")
        text = f"{_strip_publisher(raw_title)}\n{doc.get('snippet') or doc.get('content') or ''}"
        url = str(doc.get("url") or "")
        found: dict[str, str] = {}
        for name, symbol in by_name.items():
            at = _mention_at(text, name)
            if at >= 0:
                found[symbol] = _quote_around(text, at, len(name))
        # 代码也认：很多概念梳理的文章是「XXX（300750）」这种写法，
        # 而其中一部分把公司名写成了简称，名字匹配不上。
        for match in _CODE.finditer(text):
            if match.group(1) in known_codes:
                found.setdefault(match.group(1), _quote_around(text, match.start(), 6))
        for symbol, quote in found.items():
            seen = hits.setdefault(symbol, [])
            if url and all(s["url"] != url for s in seen):
                seen.append({"title": raw_title[:80], "url": url, "quote": quote})
    return hits


def _quote_around(text: str, index: int, length: int) -> str:
    """把命中处那句原文摘出来。**这是这一层唯一真正可靠的产出。**

    名单可能有错（见 theme_symbols 的说明），但「这篇文章里确实有这么一句话」
    是可核对的事实。摘出来交给模型和用户，比给一个不带上下文的公司名有用得多——
    看到「eVTOL、机器人等细分场景」，人和模型都能立刻判断这不是在说那家公司。
    """
    quote = text[max(0, index - 45): index + length + 45].replace("\n", " ")
    return " ".join(quote.split())


def _mention_at(text: str, name: str) -> int:
    if len(name) > MIN_NAME_LEN:
        return text.find(name)
    start = 0
    while True:
        index = text.find(name, start)
        if index < 0:
            return -1
        if index == 0 or not _HAN.match(text[index - 1]):
            return index
        start = index + 1


def _mentions(text: str, name: str) -> bool:
    return _mention_at(text, name) >= 0


# ---------------------------------------------------------------- 第二步：挑


PICK_SYSTEM_PROMPT = """你在帮一位 A 股个人投资者，从一批已经通过筛选的公司里挑出最贴近他要求的几家，并说清楚为什么是这几家。

这批公司是程序按条件筛出来的，**每一家都已经满足了那些条件**。所以不要再复述「它 PE 低」——那是入选的前提，不是理由。你要回答的是：满足条件的这几十家里，为什么是这几家最贴近他原本那句话。

严格遵守：
1. 只使用下面列出的数字。绝对不要从记忆里补充任何财务数据、股价、事件、行业地位或市占率。
   **也不要自己做计算**，比率都已经算好了。
2. 每一条理由都必须落在给你的某个数上，或者落在给你的主营业务描述上。
   说不出依据的话就不要写——一句「行业龙头、护城河深」在这里是负分。
3. **绝大多数公司你只会看到行业和一串数字，没有主营业务描述**——全市场底座里没有这个字段，
   只有他已经建过档的公司才有。这种情况下就直说「档案里没有它的主营业务，只知道它属于 X 行业」，
   **然后就停在这里，直接去谈数字**。

   实测你会犯的错长这样（一字不改地抄自上一次输出）：

       「档案里没有主营业务描述，只知道属于电池行业。天赐材料是电解液主要供应商之一……」
       「档案里没有主营业务描述，只知道是电池行业。正极材料是固态电池另一条主线，厦钨新能主营正极方向。」

   前半句是诚实的，后半句把你记忆里的印象接了上去——而读的人会把整段当成
   同一个来源。**这是这套东西最危险的一种错，因为它读起来最像真的。**
   你对这家公司的任何印象都不许出现：不许说它做什么产品、在产业链哪个环节、
   是不是龙头、市占率多少。这些都不在给你的资料里。
4. 不给目标价，不给买卖时点，不给评分，不写建议买入／持有／卖出。
   你回答的是「值不值得他花时间看」，不是「该不该买」。
5. 看到异常必须写进 concerns：增速极高（可能是低基数或一次性收益）、
   每股经营现金流远低于每股收益（利润没变成现金）、净利润为负而增速为正、ST 标记。
6. `passed` 里写 1–3 家你**特意没挑**的，以及为什么。只说选了谁、不说放过了谁，
   读的人无法判断你的取舍。**但如果候选本来就很少、你把它们全挑了，就让 passed 是空数组**——
   不要把已经挑中的公司再写进 passed 说「未放过」，那是自相矛盾的话。
7. 值里不要使用英文双引号；需要引用时用「」，否则会破坏 JSON。

只输出一个 JSON 对象：
{"picks": [{"index": 3, "why": "先说它靠什么赚钱，再说哪个数支持", "reasons": ["依据"], "concerns": ["疑点"]}], "passed": [{"index": 7, "why": "为什么放过它"}], "note": "一句话说这批候选整体是什么样的"}

index 是下面清单里的序号，只能用清单里出现过的号。挑 3–6 家，宁少勿多。"""


def build_pick_prompt(question: str, plan: dict[str, Any], rows: list[dict[str, Any]],
                      briefs: list[str], theme_hits: dict[str, list[dict[str, str]]]) -> str:
    rules_text = "、".join(
        f"{r.get('label') or r['field']} {r['op']} {r['value']:g}" for r in plan["rules"])
    lines = []
    for index, (row, brief) in enumerate(zip(rows, briefs), start=1):
        # 概念命中要把**原文那一句**给它看，不能只给一个「名单里有它」的标记。
        # 实测：「eVTOL、机器人等细分场景」这句话里匹配出了公司「机器人」(300024)，
        # 而只看标记的话，模型没有任何办法知道这是误伤。给了原文它就能一眼看出来。
        sources = theme_hits.get(str(row.get("symbol"))) or []
        mark = ""
        if sources:
            quote = next((s.get("quote") for s in sources if s.get("quote")), "")
            mark = f"\n   ↳ 概念名单命中，原文：「{quote}」" if quote else "\n   ↳ 概念名单里有它"
        lines.append(f"{index}. {brief}{mark}")
    theme_note = ""
    if plan.get("theme"):
        covered = sum(1 for row in rows if theme_hits.get(str(row.get("symbol"))))
        theme_note = (
            f"\n他提到的概念是「{plan['theme']}」。下面标了「概念名单命中」的 {covered} 家，"
            "是联网搜到的文章里**逐字出现过公司名**——匹配是程序做的，它只会认字，不会判断。\n"
            "所以务必读一读附的原文那一句：如果那句话里的词其实是个普通名词"
            "（例如「机器人」既是公司名也是东西），或者只是网页的导航文字，"
            "**就在 passed 里写明它跟这个概念无关**，不要因为它在名单里就挑它。\n"
            "有文章提到它，不代表它主营就是这件事。\n")
    return (
        f"他的原话是：{question}\n"
        f"程序按这套条件筛过了：{rules_text}\n"
        + (f"并且限定在这些行业：{('、').join(plan['industries'])}\n" if plan.get("industries") else "")
        + theme_note
        + f"\n下面是筛出来的 {len(rows)} 家（数字都由系统算好，直接读）：\n"
        + "\n".join(lines)
        + "\n\n请挑出最贴近他那句话的 3–6 家。"
    )


def parse_picks(text: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """行号越界一律丢。**模型回的是行号不是代码，所以它编不出一只库外的票。**"""
    # **坏 JSON 不该让前面那两步白花。**
    #
    # 走到这里，翻译条件、全 A 筛选、把候选喂给模型都已经做完了 ——
    # 前后两次模型调用是真计费的。原来这里一抛，整个任务失败、结果不留，
    # 而使用者看到的只有一句 JSONDecodeError。
    #
    # 2026-08-15 线上实测：模型把 passed 数组提前收了口
    # （`}]` 之后又接了一个对象），内容**完全正常**（有理由、有疑点、有 note），
    # 整份被丢掉，扣了 2 分。
    #
    # 这个坑本会话已经在反方 Agent 和投资逻辑起草那儿修过两次，
    # `jsonio.loads_or_reformat` 就是那时候抽出来共用的 —— 这个模块没接上。
    try:
        parsed, _ = loads_or_reformat(text, task="ai-pick", expect="object",
                                      shape=PICK_SHAPE, timeout=90)
    except ValueError as exc:
        raise RuntimeError(f"模型没有返回可解析的挑选结果：{exc}") from exc

    def resolve(entry: Any) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            return None
        try:
            index = int(entry.get("index", 0)) - 1
        except (TypeError, ValueError):
            return None
        if not 0 <= index < len(rows):
            return None
        return {"row": rows[index], "entry": entry}

    picks = []
    seen: set[str] = set()
    for entry in (parsed.get("picks") or []):
        found = resolve(entry)
        if not found:
            continue
        symbol = str(found["row"].get("symbol"))
        if symbol in seen:
            continue
        seen.add(symbol)
        picks.append({
            "symbol": symbol,
            "why": str(found["entry"].get("why") or "").strip(),
            "reasons": [str(x) for x in (found["entry"].get("reasons") or [])],
            "concerns": [str(x) for x in (found["entry"].get("concerns") or [])],
        })

    # 「特意放过的」里不能出现已经挑中的那几家。
    #
    # 实测（固态电池那次，池子只有 3 家、3 家全挑了）模型把同样三家又填进 passed，
    # 理由写成「未放过，因其……」——它在硬凑一个我要求它必填的字段。
    # 池子里没有可放过的，正确答案是**这一栏为空**，而不是三句自相矛盾的话。
    passed = []
    for entry in (parsed.get("passed") or []):
        found = resolve(entry)
        if not found:
            continue
        symbol = str(found["row"].get("symbol"))
        if symbol in seen:
            continue
        passed.append({"symbol": symbol,
                       "name": str(found["row"].get("name") or ""),
                       "why": str(entry.get("why") or "").strip()})

    return {"picks": picks, "passed": passed,
            "note": str(parsed.get("note") or "").strip()[:300]}


# ---------------------------------------------------------------- 两次调用


def plan_screen(question: str, fields: list[dict[str, Any]], industries: list[str],
                timeout: int = 120) -> dict[str, Any]:
    available, reason = ai_available()
    if not available:
        raise PlanError(reason)
    completion = llm.call(
        PLAN_SYSTEM_PROMPT,
        build_plan_prompt(question, fields, industries),
        task="ai-pick-plan",
        max_tokens=1200,
        timeout=timeout,
    )
    return parse_plan(completion.text, fields, industries)


def pick_from(question: str, plan: dict[str, Any], rows: list[dict[str, Any]],
              briefs: list[str], theme_hits: dict[str, list[dict[str, str]]],
              searches: int = 0, timeout: int = 180) -> dict[str, Any]:
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)
    completion = llm.call(
        PICK_SYSTEM_PROMPT,
        build_pick_prompt(question, plan, rows, briefs, theme_hits),
        task="ai-pick",
        max_tokens=3000,
        timeout=timeout,
        # 联网那几次搜索跟着这一次调用一起结算——搜索是真金白银，
        # 不挂在某次调用上就永远收不到（见 llm.reserve 里那段）。
        searches=searches,
    )
    out = parse_picks(completion.text, rows)
    out["model"] = llm.model_name()
    return out
