"""方法体检：这家公司在投资方法库的每个方法下，读出来是什么样。

它回答的是**「该用哪个方法看这家公司」**，是写投资逻辑的前一步。
在这之前你只能盲选方法——不知道茅台适合用护城河五问还是安全边际，
也不知道选了之后数据够不够支撑。

## 十五个方法里只有八个能自动做

这个划分不是为了省事，是诚实问题。模型对「闲聊法」能写出一段像模像样的话，
但它没问过任何一个客户——**让它假装能做，比不做更糟**：你会以为这一环已经
有人替你办了，于是真的跳过。

能自动的那八个共同点是：判据落在财报、估值、公告这些已经同步进来的事实上。
剩下七个的判据在你身上——你懂不懂这门生意、你以前怎么亏的、你和市场哪里不同。

## 一次调用评完所有方法

八个方法拆成八次调用要贵八倍（每次都要重发一遍公司资料）。合成一次，
公司资料只发一遍，约 8000 token ≈ 2 分。

## 结论必须带依据

不是为了谨慎。两个很实际的理由：模型会把去年的数当成今年的，带依据你一眼
能看出来；而且看多了「净利润 46.2 亿、经营现金流 52.1 亿大于它，所以九问
打分这项算改善」，方法本身就学会了——只给结论学不到。

数据不够就报缺口，写明该去同步什么。硬编一个结论比不给更糟。
"""

from __future__ import annotations

import json
from typing import Any

from . import llm
from .drafting import _fact_lines
from .llm import ai_available
from .methods import METHODS, METHODS_BY_KEY
from .jsonio import loads_or_reformat

# 判据落在已同步事实上的方法 —— 模型可以直接读数作答。
AUTOMATABLE_METHODS: tuple[str, ...] = (
    "magic_formula",        # 两个指标排序法：资本回报率 + 股票收益率
    "f_score",              # 九问打分：九项财报同比
    "lynch_categories",     # 先分类，再定预期：增速与分红把公司归类
    "margin_of_safety",     # 安全边际：估值区间与当前价的距离
    "expectations_investing",  # 读出价格里的预期：从价格反推隐含增速
    "three_layer_value",    # 三层估值：资产／盈利能力／增长各占多少
    "moat_five",            # 护城河五问：高毛利与高回报能不能持续（部分可判）
    "contrarian",           # 最悲观点：跌幅里有多少是公司本身的问题
)

# 判据在你身上的方法。**不交给模型**，只把模板列出来提醒你自己做。
def manual_methods() -> tuple[Any, ...]:
    return tuple(m for m in METHODS if m.key not in AUTOMATABLE_METHODS)


def automatable_methods() -> tuple[Any, ...]:
    """按方法库里的顺序返回，别按上面那个元组的顺序——
    页面上的分组（找什么／生意好不好／价格贵不贵）要跟方法库一致。"""
    return tuple(m for m in METHODS if m.key in AUTOMATABLE_METHODS)


# 档位说的是「这个方法读出来对这笔投资是好话还是坏话」，不是「是不是符合标准」。
#
# 第一版用的是「符合／不符合／数据不足」，结果八个方法全返回「数据不足」——
# 两个原因：一是提示词写成「判不了就说判不了」，模型把「有缺口」当成了「判不了」；
# 二是「符合」这个词对半数方法根本不适用（三层估值没有符不符合，它回答的是
# 「你付的钱主要买的是哪一层」）。
#
# 「数据不足」保留，但只留给**连方向都给不出**的情况。有缺口照样可以有方向，
# 缺口单独列——那才是它真正的用处：告诉你去同步什么就能把这一格补上。
VERDICTS = ("有利", "不利", "中性", "数据不足")

SYSTEM_PROMPT = """你在帮一个普通投资者判断：他手上这家公司，用某个投资方法去看，读出来是什么样。

规则：
1. 只用给你的资料里的数字。资料里没有的，写进 gaps，不要推测、不要估算、不要用你记忆里的行业常识补。
2. 每条结论都要给依据，依据必须是资料里的具体数值加它的时间（例如「经营现金流 52.1 亿 > 净利润 46.2 亿，2025 年报」）。
3. verdict 只有四档：有利 / 不利 / 中性 / 数据不足。它说的是这个方法读出来对这笔投资是好话还是坏话。
   **有缺口不等于判不了。** 只要能给出方向就给方向，缺的东西写进 gaps。
   只有当核心判据整个缺失、连方向都说不出时，才用「数据不足」。
   缺 gaps 要写清楚缺哪个数据、同步哪个页面能补上——那是它真正的用处。
4. 不要给目标价，不要说买或卖。你的活是把这家公司在这个方法下的样子读出来，买不买是他自己定。
5. summary 用一句话说清结论，讲人话，别用行话。

只输出 JSON，形如：
{"assessments": [
  {"method_key": "f_score",
   "verdict": "符合",
   "summary": "九项里七项在改善，主要是现金流和负债两块",
   "evidence": [{"fact": "经营现金流大于净利润", "value": "52.1 亿 > 46.2 亿", "as_of": "2025年报"}],
   "gaps": ["缺上一期应收账款，应收周转率这项算不出来"]}
]}"""

# 重排用的结构，跟上面那段示例同形。
ASSESS_SHAPE = ('{"assessments": [{"method_key": "f_score", "verdict": "符合", '
                '"summary": "…", "evidence": [{"fact": "…", "value": "…", "as_of": "…"}], '
                '"gaps": ["…"]}]}')


def _method_brief(method) -> str:
    return (
        f"【{method.key}】{method.name}\n"
        f"  核心问题：{method.core_question}\n"
        f"  判断步骤：{'；'.join(method.steps)}\n"
        f"  已知盲区：{method.caution or '（未记录）'}"
    )


def financial_series(symbol: str, annual: int = 6, quarters: int = 4) -> list[dict[str, Any]]:
    """多年财务序列。

    **不给序列，一半方法判不了。** `_fact_lines` 只给最近一期加同比，而
    「先分类，再定预期」要看几年增速才能归类，「读出价格里的预期」要拿隐含增速
    跟过去实绩比——这两件都不是一期数据能回答的。实测：只给一期时，八个方法
    全部返回「数据不足」。

    库里茅台有 102 期，全发进去纯属浪费 token。年报看趋势、最近几个季报看当下，
    这两段合起来足够回答方法要问的问题。
    """
    from .database import connection

    with connection() as conn:
        annual_rows = conn.execute(
            """SELECT report_date, revenue, net_profit, operating_cash_flow, operating_cost,
                      total_assets, total_liabilities, equity, debt_ratio, roe_estimate,
                      receivables, inventory, interest_bearing_debt, rnd_expense, capex
               FROM financial_periods WHERE symbol = ? AND substr(report_date, 6) = '12-31'
               ORDER BY report_date DESC LIMIT ?""", (symbol, annual)).fetchall()
        recent_rows = conn.execute(
            """SELECT report_date, revenue, net_profit, operating_cash_flow, operating_cost,
                      total_assets, total_liabilities, equity, debt_ratio, roe_estimate,
                      receivables, inventory, interest_bearing_debt, rnd_expense, capex
               FROM financial_periods WHERE symbol = ? AND substr(report_date, 6) <> '12-31'
               ORDER BY report_date DESC LIMIT ?""", (symbol, quarters)).fetchall()
    return [dict(r) for r in [*annual_rows, *recent_rows]]


def missing_fields(rows: list[dict[str, Any]]) -> list[str]:
    """最近一期缺了哪些科目。

    **这件事要主动报，不能等体检说「数据不足」才发现。** 实测踩过：库里存着 102 期
    财报，看上去很齐全，但每期只有 7-8 个字段有值——因为那批数据是在代码开始抓
    营业成本、应收、存货之前同步的。表现是九问打分永远只能答五项，而缺口写在体检
    结论里，很容易被当成「这家公司就是没有这些数据」。

    重新同步一次就补上了：数据源一直给着，是本地存的旧。
    """
    if not rows:
        return []
    latest = rows[-1] if rows[-1].get("report_date", "") > rows[0].get("report_date", "") else rows[0]
    label = {
        "operating_cost": "营业成本", "receivables": "应收账款", "inventory": "存货",
        "interest_bearing_debt": "有息负债", "rnd_expense": "研发费用", "capex": "资本开支",
    }
    return [name for key, name in label.items() if latest.get(key) is None]


def _format_series(rows: list[dict[str, Any]]) -> str:
    def money(value: Any) -> str:
        if value is None:
            return "—"
        return f"{value / 1e8:.1f}亿" if abs(value) >= 1e8 else f"{value:.0f}"

    lines = []
    for row in rows:
        lines.append(
            f"- {row['report_date']}：营收 {money(row.get('revenue'))}、"
            f"营业成本 {money(row.get('operating_cost'))}、"
            f"净利 {money(row.get('net_profit'))}、经营现金流 {money(row.get('operating_cash_flow'))}、"
            f"总资产 {money(row.get('total_assets'))}、净资产 {money(row.get('equity'))}、"
            f"应收 {money(row.get('receivables'))}、存货 {money(row.get('inventory'))}、"
            f"有息负债 {money(row.get('interest_bearing_debt'))}、"
            f"研发 {money(row.get('rnd_expense'))}、资本开支 {money(row.get('capex'))}、"
            f"资产负债率 {row.get('debt_ratio') if row.get('debt_ratio') is not None else '—'}"
            + (f"、ROE {row['roe_estimate']}" if row.get("roe_estimate") is not None else ""))
    return "\n".join(lines)


def build_prompt(company: dict[str, Any], theses: list[dict[str, Any]] | None = None) -> str:
    facts, _trackable = _fact_lines(company)
    parts = [
        "这家公司在研究台里已经同步到的全部资料：\n",
        "\n".join(f"- {line}" for line in facts),
    ]

    series = financial_series(str(company.get("symbol") or ""))
    if series:
        parts.append("\n\n历年与近期财务（年报看趋势，季报看当下；缺的科目标了 —，别当成 0）：\n")
        parts.append(_format_series(series))
        gaps = missing_fields(series)
        if gaps:
            # **不能一律说成「本地没同步」。** 银行和保险的利润表里本来就没有
            # 「营业成本」「存货」这些科目——实测平安和工行的 89 期全部为空，
            # 而制造业那几家是满的。说成「没同步」，模型会建议你去点一个
            # 点了也不会有的按钮；说成「公司没有」，又会把它误读成经营特征。
            # 所以只陈述事实，判断留给模型自己按行业去想。
            parts.append(f"\n\n注意：最近一期没有 {'、'.join(gaps)} 这几项。"
                         "金融、地产等行业的报表本来就没有其中某些科目，"
                         "制造业则通常是本地还没同步到。需要它们的判据请写进 gaps，"
                         "并说明你认为是哪种情况。")

    # 已经写过的判断也给模型看：体检的价值之一是「你认为 A，而数据显示 B」。
    # 这也是体检必须按用户存、不能全站共享的原因。
    if theses:
        parts.append("\n\n他自己已经写下的判断：\n")
        for thesis in theses:
            parts.append(f"- {str(thesis.get('claim') or '')[:300]}\n")

    parts.append("\n\n请逐个方法给出结论：\n\n")
    parts.append("\n\n".join(_method_brief(m) for m in automatable_methods()))
    return "".join(parts)


def assess_company(company: dict[str, Any], theses: list[dict[str, Any]] | None = None,
                   timeout: int = 180) -> dict[str, Any]:
    """跑一次体检。返回 {results: [...], model, fingerprint}。"""
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    completion = llm.call(SYSTEM_PROMPT, build_prompt(company, theses),
                          task="method-assessment", max_tokens=4000, timeout=timeout)
    try:
        # 这一轮的资料是代码算好喂进去的，模型只负责下判断——格式坏了就整轮丢掉
        # 太亏。先把原文递回去重排一次。
        payload, _ = loads_or_reformat(completion.text, task="method-assessment",
                                       shape=ASSESS_SHAPE, timeout=timeout)
    except ValueError as exc:
        raise RuntimeError(f"模型返回的不是可解析的 JSON：{exc}") from exc

    raw = payload.get("assessments") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise RuntimeError("模型没有按约定返回 assessments 列表")

    results = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("method_key") or "").strip()
        # **只收白名单里的方法。** 模型偶尔会自己发明一个 key，或者把该由人做的
        # 方法也答一遍——那正是这一层要挡住的东西。
        if key not in AUTOMATABLE_METHODS or key in seen:
            continue
        seen.add(key)
        verdict = str(item.get("verdict") or "").strip()
        results.append({
            "method_key": key,
            "method_name": METHODS_BY_KEY[key].name,
            "category": METHODS_BY_KEY[key].category,
            "verdict": verdict if verdict in VERDICTS else "数据不足",
            "summary": str(item.get("summary") or "").strip(),
            "evidence": _clean_evidence(item.get("evidence")),
            "gaps": [str(g).strip() for g in (item.get("gaps") or []) if str(g).strip()],
        })

    # 模型漏答的方法要补成「数据不足」，不能悄悄少几条：
    # 页面上少一行，看起来像这个方法不适用，其实是没答。
    for method in automatable_methods():
        if method.key not in seen:
            results.append({
                "method_key": method.key,
                "method_name": method.name,
                "category": method.category,
                "verdict": "数据不足",
                "summary": "这次体检没有得出结论。",
                "evidence": [],
                "gaps": ["模型这一轮没有回答这个方法，可以重跑一次。"],
            })

    order = {m.key: i for i, m in enumerate(automatable_methods())}
    results.sort(key=lambda r: order[r["method_key"]])
    return {
        "results": results,
        "model": llm.model_name(),
        "fingerprint": fingerprint(company),
        "billing": llm.collected(),
    }


def _clean_evidence(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            fact = str(item.get("fact") or "").strip()
            if not fact:
                continue
            out.append({"fact": fact,
                        "value": str(item.get("value") or "").strip(),
                        "as_of": str(item.get("as_of") or "").strip()})
        elif str(item).strip():
            out.append({"fact": str(item).strip(), "value": "", "as_of": ""})
    return out


def fingerprint(company: dict[str, Any]) -> str:
    """这份体检是基于哪一版数据算的。

    换了财报期或换了交易日，旧结论就该标成过期——而不是继续显示一个
    看起来仍然新鲜的结论。只取会影响判断的几项，价格每天都变，
    但价格变一分钱就让整份体检过期是没意义的。
    """
    financials = company.get("financials") or {}
    parts = [
        str(financials.get("latest_report_date") or ""),
        str((company.get("valuation") or {}).get("as_of") or ""),
        str(company.get("symbol") or ""),
    ]
    return "|".join(parts)


# ── 候选体检（价值候选用）────────────────────────────────────────────────
#
# 跟公司档案里那个体检是同一件事，但读的是**全市场底座**而不是公司档案：
# 候选还没建档，没有公告、没有你写下的判断，只有 market_universe 里那一行指标。
#
# **所以判据更少，方法也更少。** 只跑四个真正只靠指标就能答的：两个指标排序法、
# 九问打分（部分）、安全边际、先分类。硬把「护城河五问」塞进来，模型只能靠
# 行业常识编——那正是我们在公司档案那边极力避免的事。

CANDIDATE_METHODS: tuple[str, ...] = (
    "magic_formula", "f_score", "margin_of_safety", "lynch_categories",
)

CANDIDATE_SYSTEM_PROMPT = """你在帮一个普通投资者初筛股票：给你一批公司的关键指标，
按几个投资方法各看一眼，判断哪些值得他花时间建档细看。

规则：
1. 只用给你的指标。没给的一律不推测——这一步是初筛，判据本来就少，编出来的判断
   会让他把时间花在错的公司上。
2. 每家给一个总的档位和一句话理由，理由里必须带具体数值。
3. 不要给目标价、不说买卖。你回答的是「值不值得他再花时间看看」。
4. 档位只有三档：值得细看 / 先放着 / 直接排除。

只输出 JSON：
{"picks": [
  {"symbol": "600519", "verdict": "值得细看",
   "reason": "ROE 34.5%、毛利率 91.2% 都在样本前 5%，而 PE 19.7 处于近 5 年 7% 分位",
   "concerns": ["营收增速已降到 -2.4%，稳定增长的前提在松动"]}
]}"""

# 重排用的结构，跟上面那段示例同形。
PICK_SHAPE = ('{"picks": [{"symbol": "600519", "verdict": "值得细看", '
              '"reason": "…", "concerns": ["…"]}]}')


def build_candidate_prompt(rows: list[dict[str, Any]]) -> str:
    parts = ["这批公司的关键指标：\n"]
    for row in rows:
        # **指标从 checks 里取，不是从行本身取。** 筛选返回的候选行只带展示字段
        # （名称、行业、价格、市值），ROE、毛利这些在 checks 里——那是规则实际
        # 比对过的值，带着门槛和是否通过，比另外再查一次准，也不会对不上。
        facts = []
        for check in row.get("checks") or []:
            # **不假设形状。** 不同来源的候选行里 checks 可能是字典列表，
            # 也可能是别的东西——遇到不认识的就跳过，而不是让整个请求 500。
            # 实测综合榜那条路送进来的是字符串列表，直接把接口打挂了。
            if not isinstance(check, dict):
                continue
            actual = check.get("actual")
            if actual is None or check.get("missing"):
                continue
            if check.get("field") == "total_market_cap":
                facts.append(f"总市值 {round(actual / 1e8)} 亿")
                continue
            # label 里带着口径说明（「每股现金含量（每股经营现金流 / 每股收益…）」），
            # 太长会挤掉真正的数字，截到括号前就够看了。
            label = str(check.get("label") or check.get("field") or "").split("（")[0]
            facts.append(f"{label} {round(actual, 2)}")

        parts.append(
            f"\n{row.get('symbol')} {row.get('name')}（{row.get('industry') or '行业未标注'}）："
            + "、".join(facts or ["指标缺失"])
            + f"、报告期 {row.get('report_date') or '—'}")

    parts.append("\n\n请按下面几个方法综合判断：\n\n")
    parts.append("\n\n".join(_method_brief(METHODS_BY_KEY[k]) for k in CANDIDATE_METHODS))
    return "".join(parts)


def assess_candidates(rows: list[dict[str, Any]], timeout: int = 180) -> list[dict[str, Any]]:
    """给一批候选做初筛体检。一次调用评完整批，不是一家一次。"""
    if not rows:
        return []
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    completion = llm.call(CANDIDATE_SYSTEM_PROMPT, build_candidate_prompt(rows),
                          task="candidate-assessment", max_tokens=3000, timeout=timeout)
    payload, _ = loads_or_reformat(completion.text, task="candidate-assessment",
                                   shape=PICK_SHAPE, timeout=timeout)
    raw = payload.get("picks") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []

    known = {str(r.get("symbol")) for r in rows}
    verdicts = ("值得细看", "先放着", "直接排除")
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        # 只收这一批里的代码：模型偶尔会带出它记忆里的别的股票，
        # 而那些没有经过规则筛，混进来等于绕过了整个漏斗。
        if symbol not in known or symbol in seen:
            continue
        seen.add(symbol)
        verdict = str(item.get("verdict") or "").strip()
        out.append({
            "symbol": symbol,
            "verdict": verdict if verdict in verdicts else "先放着",
            "reason": str(item.get("reason") or "").strip()[:300],
            "concerns": [str(c).strip()[:200] for c in (item.get("concerns") or []) if str(c).strip()][:3],
        })
    return out


def estimate_candidate_credits(count: int) -> int:
    """跑 N 家候选大概要几分。页面上先告诉用户，别让他点完才知道。

    一家约 120 字指标 + 模型输出约 80 字，合计约 200 token；
    加上方法说明那段固定开销（约 1500 token）。5000 token = 1 分。
    """
    tokens = 1500 + count * 200 + min(count * 120, 3000)
    return max(1, -(-tokens // 5000))
