"""让模型代替人把候选逐家看一遍，只把结论交回来。

用户的原话是"我只看结论，基于结论再展开是否值得继续调研"。所以这一层做的是**初筛**：
把候选从几十家收敛到几家值得亲自看的，而不是替人做投资决定。

分工遵循一条硬规则：**数字全部由代码算，模型只负责读数字后写判断**。
模型拿到的每一项都是从底座里取出来的既有数值，它不许自己产生数字。
（这一点和 FinRobot 的做法一致：确定性的财务计算与 LLM 叙述严格分开。）

输出三样东西：
- verdict：值得深入 / 先放着 / 直接排除——只回答"要不要花时间"，不回答"要不要买"
- conclusion：一句话结论，必须点到具体数字
- reasons / concerns：支持与反对各自的依据，都要能在给它的数据里找到
"""

from typing import Any

from . import llm
from .jsonio import loads_or_reformat
from .llm import ai_available
from .operators import OPERATORS_BY_KEY, compute_all

# 全市场底座能支撑的派生比率。模型拿到的是这些算好的值，不是让它自己去除。
SCREEN_OPERATORS = ("cash_ratio", "peg", "earnings_yield", "graham_number", "pb_over_roe")

VERDICTS = ("值得深入", "先放着", "直接排除")

RESEARCH_SYSTEM_PROMPT = """你在帮一位业余的 A 股个人投资者做候选公司的初筛。他没有时间逐家翻财报，需要你先看一遍再告诉他哪几家值得他亲自花时间。

你要回答的问题只有一个：**这家公司值不值得他继续花时间研究**。不要回答该不该买、什么价格买、能涨多少。

严格遵守：
1. 只使用用户消息里给出的数字。绝对不要从记忆里补充任何财务数据、股价、事件或行业排名。
   **也不要自己做任何计算**：比率都已经算好了，你算出来的数一旦和系统的口径不一致，就没人能对账。
2. 结论必须**先用一句话说清这家公司靠什么赚钱**（依据给出的主营业务），再谈数字。
   只有指标没有生意的结论对用户没用——他不认识这家公司。
   如果资料里没有主营业务，就写"档案里没有主营业务描述"，不要凭公司名猜。
3. 结论里必须点到至少一个具体数字，并且这个数字必须和给你的数据一字不差。
4. 不给目标价，不给买卖时点，不给评分，不写"建议买入/持有/卖出"。
5. 看到异常要说出来：增速极高（可能来自低基数或一次性收益）、每股经营现金流远低于每股收益（利润没变成现金）、
   ST 标记、净利润为负而增速为正等，都要写进 concerns。
6. **值里不要使用英文双引号**；需要引用时用「」，否则会破坏 JSON。
7. verdict 只能是这三个之一：值得深入、先放着、直接排除。
   - 值得深入：数据本身站得住，且没有明显的口径疑点。
   - 先放着：数据看着不错但有需要正文才能确认的疑点。
   - 直接排除：数据本身就说明它不符合这套条件的意图（例如增速来自极低基数、或现金流与利润严重背离）。

只输出一个 JSON 数组，每项形如：
{"index": 1, "verdict": "值得深入", "conclusion": "先说这家公司做什么，再说数字", "reasons": ["支持的依据"], "concerns": ["需要核实的疑点"]}"""

# 重排用的结构，跟上面那行示例同形。
REFORMAT_SHAPE = ('[{"index": 1, "verdict": "值得深入", "conclusion": "…", '
                  '"reasons": ["…"], "concerns": ["…"]}]')


def _row_brief(item: dict[str, Any]) -> str:
    """把一家候选压成一行。**所有比率由算子表算好再交给模型**，它只读不算。"""

    parts = [f"{item['name']}（{item['symbol']}，{item.get('industry') or '行业未标注'}）"]
    if item.get("main_business"):
        parts.append(f"主营：{str(item['main_business'])[:180]}")
    # 底座直接给的原始数值
    for label, key, unit in (
        ("净利润同比", "net_profit_growth", "%"),
        ("营收同比", "revenue_growth", "%"),
        ("净资产收益率", "roe", "%"),
        ("毛利率", "gross_margin", "%"),
        ("每股收益", "eps", " 元"),
        ("市盈率", "pe_ttm", ""),
        ("市净率", "pb", ""),
    ):
        value = item.get(key)
        if value is not None:
            # 浮点尾数没有信息量，喂进去只会原样出现在结论里
            parts.append(f"{label} {round(float(value), 2):g}{unit}")
    # 算子算出来的派生比率
    for computed in compute_all(item, SCREEN_OPERATORS):
        if computed["value"] is not None:
            parts.append(f"{computed['label']} {round(float(computed['value']), 2):g}{computed['unit']}")
    if item.get("net_profit") is not None:
        parts.append(f"净利润 {round(item['net_profit'] / 1e8, 2)} 亿")
    if item.get("total_market_cap") is not None:
        parts.append(f"总市值 {round(item['total_market_cap'] / 1e8)} 亿")
    return " ｜ ".join(parts)


def build_screen_prompt(items: list[dict[str, Any]], strategy_name: str, rules_text: str, data_note: str) -> str:
    listing = "\n".join(f"{index + 1}. {_row_brief(item)}" for index, item in enumerate(items))
    basis = "\n".join(
        f"- {OPERATORS_BY_KEY[key].label}：{OPERATORS_BY_KEY[key].formula}"
        + (f"（注意：{OPERATORS_BY_KEY[key].caveat}）" if OPERATORS_BY_KEY[key].caveat else "")
        for key in SCREEN_OPERATORS
    )
    return (
        f"这批候选来自「{strategy_name}」这套条件：{rules_text}\n"
        f"数据口径：{data_note}\n\n"
        f"下面这些派生比率已经由系统算好，你直接读，不要自己再算：\n{basis}\n\n"
        f"请逐家判断下面 {len(items)} 家值不值得他继续花时间：\n{listing}"
    )


def review_candidates(
    items: list[dict[str, Any]],
    strategy_name: str,
    rules_text: str,
    data_note: str,
    timeout: int = 180,
) -> list[dict[str, Any]]:
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)
    model = llm.model_name()
    completion = llm.call(
        RESEARCH_SYSTEM_PROMPT,
        build_screen_prompt(items, strategy_name, rules_text, data_note),
        task="screen",
        max_tokens=4000,
        timeout=timeout,
    )
    text = completion.text

    try:
        parsed, _ = loads_or_reformat(text, task="candidate-review", expect="array",
                                      shape=REFORMAT_SHAPE, timeout=timeout)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    results: list[dict[str, Any]] = []
    for entry in parsed:
        try:
            index = int(entry.get("index", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(items):
            continue
        verdict = entry.get("verdict")
        results.append(
            {
                "symbol": items[index]["symbol"],
                # 模型给了库外的档位就退回最保守的一档，而不是把它当成有效判断
                "verdict": verdict if verdict in VERDICTS else "先放着",
                "conclusion": str(entry.get("conclusion") or "").strip(),
                "reasons": [str(x) for x in (entry.get("reasons") or [])],
                "concerns": [str(x) for x in (entry.get("concerns") or [])],
                "model": model,
            }
        )
    return results
