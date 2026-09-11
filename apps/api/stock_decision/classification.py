"""公告分级：先用规则，再用模型补不确定的部分。

分工是刻意的：
- **分类**（这条是实质变化还是程序性公告）可以自动做，因为结果可核验——标题就在那儿，
  你一眼能看出分对没分对，分错了也只是多看或少看一条。
- **判断**（这条是否动摇了你的投资逻辑）不自动做。那是投资判断，必须由你在归档时确认。

规则永远先跑：它零成本、确定、可解释，而且能自己改。模型只处理规则拿不准的部分。
"""

import re
from typing import Any

from . import llm
from .jsonio import loads_or_reformat
from .llm import ai_available

RELEVANCE_LEVELS = ("高", "中", "低")

# 实质变化：经营、治理、股权、合规上真正发生了什么
SUBSTANTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"业绩预告|业绩快报|业绩预增|业绩预减|业绩说明", "业绩"),
    (r"年度报告(?!摘要)|半年度报告|季度报告|年报|中报", "定期报告"),
    (r"利润分配|权益分派|分红|派息|送股|转增", "分红"),
    (r"回购|增持|减持|股份变动|股权转让|要约收购", "股权变动"),
    (r"股权激励|员工持股|限制性股票", "激励"),
    (r"重大合同|中标|框架协议|战略合作", "经营合同"),
    (r"重大资产重组|收购|出售资产|资产置换|吸收合并", "重组"),
    (r"诉讼|仲裁|判决|执行", "诉讼"),
    (r"处罚|警示函|问询函|关注函|立案|违规|整改", "监管"),
    (r"退市风险|\*ST|风险警示|停牌|复牌|破产|重整", "风险"),
    (r"控股股东|实际控制人|控制权", "控制权"),
    (r"定向增发|非公开发行|可转债|配股|募投项目", "融资"),
    (r"计提|减值|商誉|会计政策变更|会计估计变更", "会计"),
    (r"担保", "担保"),
    (r"变更(公司)?名称|变更证券简称|注册资本", "工商变更"),
)

# 程序性：走流程必须发的公告，多数不需要人逐条看
PROCEDURAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"股东[大]?会.*(通知|决议|材料|资料)|召开.*股东[大]?会", "股东大会流程"),
    # **中间要允许隔字。** A 股的标准标题是「第三届董事会**第七次**会议决议公告」，
    # 而原来的 `董事会决议` 要求这四个字连着 —— 拿使用者线上真实的 113 条公告跑，
    # 这三个模式一条都匹配不上（0/113），而其中 10 条正是这个形状。
    # 最常见的一类程序性公告，于是永远停在「中」等人工处理。
    (r"(董事会|监事会).{0,8}会议决议|(董事会|监事会)决议", "会议决议"),
    (r"独立董事.*(意见|述职|提名|工作)", "独董文件"),
    (r"法律意见书|律师事务所.*意见", "法律意见"),
    (r"募集资金(存放|使用|管理).*(报告|情况)", "募资例行报告"),
    (r"会计师事务所|审计机构.*(续聘|变更)", "审计机构"),
    (r"更正公告|补充公告|澄清公告", "更正补充"),
    (r"投资者关系活动记录", "调研记录"),
    (r"(章程|制度|管理办法|工作细则)(修订|修改)?", "制度文件"),
    (r"内幕信息知情人", "内幕登记"),
    (r"证券事务代表|董事会秘书.*(聘任|变更)", "证代变更"),
    (r"日常关联交易|预计.*关联交易", "日常关联交易"),
    (r"网上业绩说明会|参加.*集体接待日", "说明会"),
)


# 附属文件：即使讲的是实质事项，本身也只是走流程的附件，先于主题判定
ATTACHMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"法律意见书", "法律意见书"),
    (r"独立董事.*意见|独立财务顾问报告", "独董/顾问意见"),
    (r"投资者关系活动记录", "调研记录"),
    (r"内幕信息知情人", "内幕登记"),
    (r"公告的(更正|补充)|更正公告|补充公告", "更正补充"),
    (r"摘要$", "报告摘要"),
)


# 例行进展：同一件事的后续执行，决议或方案本身才值得看
# 进展类公告带着具体数量与金额，是公司事实，不是流程文件。
# 之前把它们判成"中"是错的：归档只是把事实存档，不需要先判断影响有多大。
CORPORATE_ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"回购.*(进展|结果|实施情况)|每月.*回购", "回购进展"),
    (r"激励.*(归属|解锁|解除限售|行权|作废|注销)", "激励执行"),
    (r"募(集资金投资)?投项目.*(调整|结项|延期|置换)", "募投项目调整"),
    (r"(进展|实施情况)(公告)?$", "事项进展"),
    (r"减持(计划)?(时间过半|实施进展|结果|期限届满)", "减持进展"),
    (r"复牌|停牌.*进展", "停复牌进展"),
    (r"持股计划.*(归属|过户|锁定期|届满|完成)", "员工持股计划执行"),
    (r"(套期保值|外汇衍生品|期货).*(业务|分析报告|额度)", "套保与衍生品业务"),
    (r"(选举|聘任|辞[任职]|变更).*(董事|监事|高级管理人员|总经理|财务总监|董事会秘书)", "董监高变动"),
    (r"(风险提示|异常波动)", "交易风险提示"),
    (r"审计报告|(内部控制|内控).*(审计|评价)报告", "审计与内控报告"),
)


# 你确认过的规则词。由 repository 在每轮分级前灌进来（这里不碰数据库：
# 分级逻辑要能脱离库单独测，而且它被大量单元测试直接调用）。
_USER_TERMS: list[dict[str, str]] = []


def set_user_terms(terms: list[dict[str, str]]) -> None:
    """装载用户确认过的规则词。空列表 = 只用内置规则。"""
    global _USER_TERMS
    _USER_TERMS = list(terms)


def classify_by_rules(title: str, category: str = "公告") -> dict[str, Any]:
    """分红与解禁本身就是实质事项；公告按标题匹配。

    用户确认过的词**排在最前**：它们是从真实纠错里来的，带着这个人自己的判断，
    比内置的通用词表更贴他的用法。内置词表管的是通用情形，个人偏好压在它上面。
    """

    for term in _USER_TERMS:
        if term["term"] and term["term"] in title:
            return {"relevance": term["relevance"],
                    "reason": f"命中你确认过的词「{term['term']}」",
                    "source": "规则", "topic": term.get("topic") or "自定义"}
    if category in {"分红", "解禁"}:
        return {"relevance": "高", "reason": f"{category}事项本身就是实质变化", "source": "规则", "topic": category}
    for pattern, topic in ATTACHMENT_PATTERNS:
        if re.search(pattern, title):
            return {"relevance": "低", "reason": f"「{topic}」是附属文件，主文件才是要看的", "source": "规则", "topic": topic}
    for pattern, topic in CORPORATE_ACTION_PATTERNS:
        if re.search(pattern, title):
            return {"relevance": "高", "reason": f"「{topic}」陈述了一件关于公司的事，可以直接归档", "source": "规则", "topic": topic}
    for pattern, topic in SUBSTANTIVE_PATTERNS:
        if re.search(pattern, title):
            return {"relevance": "高", "reason": f"标题命中「{topic}」类关键词", "source": "规则", "topic": topic}
    for pattern, topic in PROCEDURAL_PATTERNS:
        if re.search(pattern, title):
            return {"relevance": "低", "reason": f"标题命中「{topic}」类程序性关键词", "source": "规则", "topic": topic}
    return {"relevance": "中", "reason": "规则没有把握，等待模型或人工判断", "source": "规则", "topic": None}


SYSTEM_PROMPT = (
    "你是 A 股公告分级助手。这个分级只决定一件事：这条公告要不要归进公司的事实档案。\n"
    "严格遵守：只做分级与客观摘要；不判断利好利空，不预测股价，不给任何投资建议。\n"
    "分级标准：\n"
    "高＝这条公告本身陈述了一件关于公司的事（业绩、分红、回购、股权激励、增减持、重组、"
    "合同、诉讼监管、控制权、融资、人事、产能、经营数据等），无论事情大小。\n"
    "低＝走流程必须发的程序性文件，本身不含公司事实（股东大会通知与决议、董事会决议、"
    "独董意见、法律意见书、募集资金例行报告、制度修订、调研记录、更正补充等）。\n"
    "中＝只在标题模糊到看不出它在讲什么时使用。\n"
    "特别注意：**不要因为「需要看正文才能判断影响程度」而判中**。归档只是把事实存档，"
    "不需要先判断影响有多大——回购进展、激励归属、募投调整、减持进展这类都算高。\n"
    "中这一档要留给人工处理，所以尽量少用；能判断出它在讲一件什么事，就判高或低。\n"
    '只输出 JSON 数组，每项形如 {"index": 1, "relevance": "高", "topic": "业绩", "summary": "一句客观描述", "reason": "依据标题的哪几个字"}。'
)

# 重排用的结构，跟上面那句示例同形。**两处写岔的话**，重排会照另一个形状改，
# 改出来是合法 JSON 但字段对不上，然后这一批公告静静地全部落空。
REFORMAT_SHAPE = ('[{"index": 1, "relevance": "高", "topic": "业绩", '
                  '"summary": "…", "reason": "…"}]')


def classify_with_model(titles: list[dict[str, Any]], timeout: int = 90) -> list[dict[str, Any]]:
    """把规则拿不准的标题交给模型；失败时抛异常，由调用方保留规则结果。"""

    listing = "\n".join(f"{index + 1}. [{item.get('category', '公告')}] {item['title']}" for index, item in enumerate(titles))
    completion = llm.call(
        SYSTEM_PROMPT,
        f"给下面 {len(titles)} 条公告分级：\n{listing}",
        task="inbox-classify", max_tokens=2000, timeout=timeout,
    )
    text = completion.text
    # 一批分级就是一次真调用。格式坏了丢掉整批的话，这些公告会停在"未分级"，
    # 而未分级在收件箱里跟"已经看过、不重要"长得很像。
    parsed, _ = loads_or_reformat(text, task="inbox-classify", expect="array",
                                  shape=REFORMAT_SHAPE, timeout=timeout)
    results: list[dict[str, Any]] = []
    for item in parsed:
        index = int(item.get("index", 0)) - 1
        if not 0 <= index < len(titles):
            continue
        relevance = str(item.get("relevance", "中")).strip()
        results.append({
            "id": titles[index]["id"],
            "relevance": relevance if relevance in RELEVANCE_LEVELS else "中",
            "reason": str(item.get("reason", ""))[:200],
            "summary": str(item.get("summary", ""))[:300],
            "topic": str(item.get("topic", ""))[:40] or None,
            "source": "模型",
        })
    return results
