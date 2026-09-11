"""深度研究报告：联网找资料，配上库里的真实数字，写成一份带图的报告。

## 原来那份为什么"乏善可陈"

它只复述已归档的证据，而归档的多半是公告标题。写出来的东西没有任何档案之外
的信息，只是把你已经看过的东西重新排了一遍——**信息量为零是结构决定的**，
不是模型写得不好。

## 分工：数字归代码，判断归模型

这是从虾米跨境那套深度研究搬过来的铁律，也是本仓一贯的做法：

- **数字一律由代码给**：主营构成、同行位置、经营走势、估值分位，
  库里都有唯一来源。网页上的财务数字经常过期、口径不同，或者是别人抄错的。
  让模型从网页里抄数字，等于把最容易错、后果最严重的那一步交给它。
- **模型只写判断**：这些事实凑在一起说明什么、哪里互相矛盾、还缺什么。
  每一条判断必须挂证据编号，挂不上的不许写。

## 资料分级要传给模型

一手（交易所、监管、公司官网）可以直接当事实引用；媒体是二手转述，要写
"据某某报道"；研报和论坛是观点，只能写"市场在这样讨论"。
不把这个分级告诉模型，它会把股吧里的一句话跟年报里的一句话放在同一个位置上。

## 说不出来的就写进 unknowns

证据不足的章节明写不足，不注水。一份诚实地说"这三件事查不到"的报告，
比一份把三件事编圆了的报告有用得多——前者告诉你下一步该去查什么。
"""

from __future__ import annotations

from typing import Any

from . import llm, websearch
from .llm import SEARCH_CREDIT_COEFF as SEARCH_COEFF, credits_for_report
from .jsonio import Truncated, loads_or_reformat
from .llm import ai_available, model_name

# 一份报告搜几个问题。跟 websearch.MAX_SEARCHES 对齐，别在两处各写一个上限。
QUERY_COUNT = 5

SYSTEM_PROMPT = """你在为一位业余的 A 股个人投资者写一份公司研究报告。他不是专业分析师，需要的是「这家公司现在是怎么回事」，而不是术语堆砌。

严格遵守：

1. **数字只用「本地数据」里给出的**。检索到的网页资料只用来回答"发生了什么、
   公司自己怎么说、市场在讨论什么"。绝对不要从网页里抄任何财务数字——
   网上的数字经常过期或口径不同，本地那份是同步来的，以它为准。
2. **每一条判断都要挂资料编号**，形如 [3] 或 [1][4]。挂不上编号的话不许写。
3. **按资料分级说话**：标着「一手」的可以直接当事实（"公司公告称…"）；
   「媒体」是二手转述（"据某某报道…"）；「研报」「观点」只能写
   "市场上有观点认为…"，不能当事实。
   标着「其他」的是**本站认不出来源的网页**（个人站、百科、聚合转载、境外站）。
   它只能当线索：可以写"有资料提到…"，**不能单独支撑一条结论**——
   一条判断如果只挂得上「其他」，要么找到别的编号一起挂，要么写进 unknowns。
4. 不预测走势、不给目标价、不给买卖时点、不给评分、不写建议买入卖出。
5. 查不到的写进 unknowns，**不要绕过去、不要用常识补**。
6. 用中文，平实叙述，不用研报套话。**值里不要使用英文双引号**，用「」。

产出这几块：

- headline：一句话，这家公司现在最要紧的一件事。
- cards：三到四张结论卡，每张 {title, point, refs}。point 一句话说清，
  refs 是资料编号数组。这是整份报告最先被读到的部分。
- sections：分章正文，**最多 6 章**，每章 {title, lines}，lines 是一句一条的
  短句数组、**最多 12 句**，每条带编号。章节自己定，按这家公司实际的情况来，
  不要套模板。
- themes：这些资料在讨论哪几个主题，**最多 8 个**，每个 {name, direction, refs}。
  direction 只能是 正面 / 负面 / 中性 —— 指的是**对这家公司的经营而言**，
  不是对股价。refs 是支持这个判断的资料编号。
- unknowns：资料没覆盖、但会影响判断的问题，**最多 8 条**。

只输出一个 JSON 对象，键就是上面这五个。"""

# 重排时告诉模型该长成什么样。**必须跟上面那段提示词同形**——
# 两处写岔的话，重排会照着另一个形状改，改出来照样是合法 JSON，
# 只是字段对不上，然后下面那几个 .get() 静静地读出一堆空值，谁也不会报错。
REFORMAT_SHAPE = ('{"headline": "…", "cards": [{"title": "…", "point": "…", "refs": [1]}], '
                  '"sections": [{"title": "…", "lines": ["…"]}], '
                  '"themes": [{"name": "…", "direction": "正面/负面/中性", "refs": [1]}], '
                  '"unknowns": ["…"]}')

# 一份报告最多写多长。
#
# **原来是 5000，而这个数字从来没被量过。** 2026-08-15 线上实测（格力）：
# 入参 16,345 字、出参 4,353 字 = 2,033 个输出 token，离 5000 还有一半余量，
# 所以那一次没被截断 —— 但提示词允许的上界是 6 章 × 12 句 × 400 字，
# 真写到那个量级就会撞线，而撞线的表现是**整份报告连同已经花掉的 5 次检索一起丢掉**。
#
# 冻结额不跟 max_tokens 挂钩（见 llm.estimate_tokens），调大这个数不会
# 让任何人被「额度不足」挡在门外，结算也永远按真实 usage。那就没有理由留一个
# 刚好够用的上限。
MAX_ANSWER_TOKENS = 30000


def build_queries(company: dict[str, Any]) -> list[str]:
    """按公司拼检索问题。

    **不让模型来定问题。** 让它先想一轮问题要多花一次调用，而这几个问题
    的模式是固定的（近况、主业、风险、同行、分红），拼出来比问一遍更准也更省。
    """
    name = company.get("name") or ""
    # 行业用底座的申万二级，不用档案里的证监会门类。
    # 档案写的是「酒、饮料和精制茶制造业」——拿它去搜，搜回来的是饮料和茶叶；
    # 底座写的是「白酒Ⅱ」，那才是这家公司真正的竞争场。同业对照也是这个口径。
    industry = str(company.get("universe_industry") or company.get("industry") or "")
    return [q for q in (
        f"{name} 最新 财报 经营情况",
        f"{name} 主营业务 变化 战略",
        f"{name} 风险 问题 争议",
        f"{industry} 行业 需求 竞争格局" if industry else "",
        f"{name} 分红 股东回报",
    ) if q.strip()][:QUERY_COUNT]


def _numbers_block(facts: dict[str, Any]) -> str:
    """库里那些数，原样摆给模型看，并写明它们的地位。"""
    parts: list[str] = ["【本地数据】以下数字来自本站同步的数据源，是这份报告里唯一可信的数字。\n"]

    segments = facts.get("segments") or {}
    dims = segments.get("dimensions") or []
    if dims:
        parts.append(f"主营构成（{segments.get('report_date')} 年报分部附注）：")
        for dim in dims:
            items = ", ".join(
                f"{i['segment']} 占收入 {i['revenue_share']}%、毛利率 {i['gross_margin']}%"
                for i in dim["items"] if not i.get("filler"))
            parts.append(f"  按{dim['key']}：{items}")

    peers = facts.get("peers") or {}
    if peers.get("metrics"):
        parts.append(f"\n同行位置（{peers.get('industry')}，全行业 {peers.get('peers')} 家）：")
        for m in peers["metrics"]:
            parts.append(f"  {m['label']} {m['value']}{m['unit']}，"
                         f"排第 {m['percentile']} 分位（中位数 {m['p50']}{m['unit']}）")

    series = facts.get("financials") or []
    if series:
        parts.append("\n历年年报（亿元）：")
        for row in series[-6:]:
            def yi(key: str) -> str:
                value = row.get(key)
                return "—" if value is None else f"{value / 1e8:.1f}"
            parts.append(f"  {str(row['report_date'])[:4]}：营收 {yi('revenue')}、"
                         f"净利 {yi('net_profit')}、经营现金流 {yi('operating_cash_flow')}、"
                         f"净利率 {row.get('net_margin') or '—'}%")
    return "\n".join(parts)


def _sources_block(hits: list[dict[str, Any]], local: list[dict[str, Any]]) -> str:
    """检索资料 + 本地已归档证据，统一编号。

    **两类混在一起编号是刻意的**：报告正文里引用时不该关心它是哪来的，
    分级信息写在每条后面，模型据此决定怎么措辞。
    """
    lines: list[str] = []
    for index, hit in enumerate(hits, 1):
        lines.append(f"[{index}]（{hit['kind']}｜{hit.get('published') or '日期不详'}）"
                     f"{hit['title']}｜{hit['snippet'][:400]}")
    offset = len(hits)
    for index, item in enumerate(local, offset + 1):
        lines.append(f"[{index}]（本地已归档｜{str(item.get('occurred_at'))[:10]}）"
                     f"{item.get('source_name')}：{str(item.get('excerpt'))[:300]}")
    return "\n".join(lines)


def compose(company: dict[str, Any], hits: list[dict[str, Any]],
            local: list[dict[str, Any]], facts: dict[str, Any],
            timeout: int = 240, searches: int = 0) -> dict[str, Any]:
    """把资料写成报告。"""
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)
    if not hits and not local:
        raise RuntimeError("既没有检索到资料，也没有已归档的证据，写不出报告。")

    prompt = (
        f"公司：{company['name']}（{company['symbol']}），行业：{company.get('industry') or '未标注'}\n\n"
        + _numbers_block(facts)
        + f"\n\n【资料】共 {len(hits) + len(local)} 条，编号即引用编号：\n"
        + _sources_block(hits, local)
    )
    # **把真实搜索次数带上。** 报告的钱大头在搜索，而这条路以前只报 token——
    # 一份搜 5 次的报告实扣 3 分，公式该收 9 分。
    completion = llm.call(SYSTEM_PROMPT, prompt, task="deep-report",
                          max_tokens=MAX_ANSWER_TOKENS, timeout=timeout, searches=searches)
    # **这一轮的钱在写之前就已经花掉了**：5 次联网检索是真金白银（实测一份
    # 报告 10 分，大头在搜索）。最后一段格式坏了就整份丢掉，等于把已经买回来的
    # 资料扔进垃圾桶。重排只把原文递回去改格式，比重跑一整轮便宜一个数量级。
    try:
        payload, reformatted = loads_or_reformat(
            completion.text, task="deep-report", shape=REFORMAT_SHAPE, timeout=timeout)
    except Truncated as cut:
        # 没写完救不回来（重排的规矩是一个字都不许加），但**原因要说对**：
        # 说「格式坏了」会让人去怀疑模型，说「太长了被截断」他才知道这是预算问题。
        raise RuntimeError(f"报告写到一半被长度上限掐断了（{cut}）。资料已经检索到了，"
                           f"再点一次会重新写一遍。") from cut
    if not isinstance(payload, dict):
        raise RuntimeError("模型没有按约定返回一个 JSON 对象")

    total = len(hits) + len(local)

    def refs(value: Any) -> list[int]:
        """只收指得到的编号。**越界的丢掉，不猜**——猜错会把一条结论
        挂到另一份资料上，而读的人点开才发现对不上，那比没有引用更糟。"""
        out = []
        for item in value if isinstance(value, list) else []:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= total:
                out.append(number)
        return out

    # 下面这几个 [:N] 是硬上限。**上限必须同时写在提示词里** ——
    # 只在这一头切的话，模型写了 8 章、页面只显示 6 章，被切掉的两章
    # 不报错、不留痕，而它们的钱已经付过了。
    cards = [{
        "title": str(c.get("title") or "")[:60],
        "point": str(c.get("point") or "")[:300],
        "refs": refs(c.get("refs")),
    } for c in (payload.get("cards") or []) if isinstance(c, dict)][:4]

    sections = [{
        "title": str(s.get("title") or "")[:60],
        "lines": [str(x)[:400] for x in (s.get("lines") or []) if str(x).strip()][:12],
    } for s in (payload.get("sections") or []) if isinstance(s, dict)][:6]

    themes = [{
        "name": str(t.get("name") or "")[:40],
        # 只收这三个方向。模型偶尔会写"偏正面""略负面"——那是它自己发明的档位，
        # 收进来图上就会多出一个谁也不知道该画多深的颜色。
        "direction": str(t.get("direction") or "中性")
                     if str(t.get("direction") or "") in ("正面", "负面", "中性") else "中性",
        "refs": refs(t.get("refs")),
    } for t in (payload.get("themes") or []) if isinstance(t, dict)][:8]

    return {
        "headline": str(payload.get("headline") or "")[:200],
        "cards": [c for c in cards if c["title"]],
        "sections": [s for s in sections if s["title"] and s["lines"]],
        "themes": [t for t in themes if t["name"]],
        "unknowns": [str(x)[:200] for x in (payload.get("unknowns") or [])][:8],
        "model": model_name(),
    }


def estimate(company: dict[str, Any]) -> dict[str, Any]:
    """跑之前先说清楚要搜几次、大概多少积分。

    花钱的事要在点之前知道，不是点完看账单。
    """
    queries = build_queries(company)
    ok, reason = websearch.available()
    # **报价按公式算，不写死。**
    #
    # 原来这里是 `"credits": 3` 一个字面量，而旁边那句「大约 3 个积分」
    # 让它看起来像算出来的。实际一份搜 5 次的报告该收 9 分——
    # 少的 6 分正好是搜索那一项，因为搜索次数从来没被送进计费闸口。
    #
    # 公式跟主站一致：⌈ 搜索数 × SEARCH_COEFF + ⌈tokens/5000⌉ ⌉
    # 一次 compose 约 6000–9000 token，按 2 个桶估。
    searches = len(queries) if ok else 0
    credits = credits_for_report(searches, model_tokens=9000)
    return {
        "queries": queries,
        "searches": searches,
        "credits": credits,
        "search_ready": ok,
        "note": (f"会搜 {len(queries)} 个问题，再让模型写一遍，大约 {credits} 个积分"
                 f"（搜索 {searches} 次 × {SEARCH_COEFF} + 模型约 2 个处理单元）。"
                 if ok else f"{reason} 报告只会用已归档的证据，内容会比较单薄，"
                            f"约 {credits} 个积分。"),
    }
