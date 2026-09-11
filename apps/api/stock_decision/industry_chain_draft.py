"""用公开资料为一个主题起草产业链底图。

这条能力的产物不是“模型知道的产业链”。它的顺序被刻意固定为：

    主题 → 公开检索 → 模型只整理给定资料 → 每个节点/连线带回来源 → 用户确认

模型不能直接把一张图标成已核验，也不能把公司凭印象钉到图上。它只负责把资料
里已经出现的产品、服务与交付关系组织成便于研究的初稿；每一项都保持“待确认”。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import llm, websearch
from .jsonio import Truncated, loads_or_reformat


QUERY_COUNT = 3
MAX_SOURCES = 24
MIN_SOURCES = 2
MAX_STAGES = 6
MAX_NODES_PER_STAGE = 8
MAX_EDGES = 28

# 一张底图最多写多长。
#
# **原来是 4200，而 2026-08-16 线上实测（「固态电池」，21 条资料）跑出 3418 ——
# 用掉了 81%。** 那一次没撞上，但离得很近：提示词允许的上界是
# 6 阶段 × 8 节点（每个节点 500 字描述）+ 28 条边（每条 500 字），
# 真写到那个量级一定撞线，而撞线的代价是**这一整轮连同 3 次联网检索一起丢掉**
# （实测一轮 7 分）。
#
# 冻结额不跟 max_tokens 挂钩（见 llm.estimate_tokens），调大不会让任何人
# 被「额度不足」挡在门外，结算也永远按真实 usage。那就没有理由留一个
# 刚好够用的上限。
MAX_ANSWER_TOKENS = 30000

_STAGE_KINDS = {"input", "core", "output", "support"}
_NODE_TYPES = {"产品", "服务", "原材料", "部件", "设备", "渠道", "应用", "平台", "基础设施", "数据与内容"}


SYSTEM_PROMPT = """你在协助一位长期价值投资者建立“产业链研究底图”。

这是一张产品、服务与交付关系图，不是概念股名单，也不是公司上下游传闻图。

你只能使用下面资料里明确给出的信息。资料不够时宁可少画，并把缺口写入 unknowns；
绝对不能用常识、记忆、行业印象补全。每个节点与每条连线都必须引用至少一个资料编号。

严格遵守：
1. 节点只写产品、服务、基础设施、渠道或应用场景；不要写上市公司、品牌、客户名单或“某某概念股”。
2. 从左到右组织价值如何交付：投入/供给 → 核心产品或服务 → 交付/渠道 → 客户或应用。服务链可按获客、产品、履约、场景组织。
3. stages 最多 6 个，每个 stage 最多 8 个节点。不要为了凑完整而写空泛词，例如“上游”“下游”“客户”“生态”。
4. node_type 只能是：产品、服务、原材料、部件、设备、渠道、应用、平台、基础设施、数据与内容。
5. stage_kind 只能是 input、core、output、support。edge 的 from/to 必须引用你已经写出的节点名称。
6. source_refs 只能引用资料中存在的编号；每项至少一个。它表达“这个初稿为什么这样画”，不等于已核验。
7. 不预测股价、不写投资建议、不评判公司优劣、不编造市场规模或财务数字。
8. 用简洁中文。值里不要使用英文双引号；需要引用时用「」。

只输出一个 JSON 对象：
{
  "name": "不超过 30 字的底图名称",
  "chain_type": "制造链 或 服务链 或 平台生态",
  "description": "一句话说明这张图覆盖什么",
  "stages": [
    {"name": "阶段", "stage_kind": "input", "description": "阶段说明", "nodes": [
      {"name": "节点", "node_type": "产品", "description": "这个节点交付什么", "source_refs": [1]}
    ]}
  ],
  "edges": [
    {"from": "节点 A", "to": "节点 B", "relation_type": "流向", "detail": "关系说明", "source_refs": [1]}
  ],
  "unknowns": ["还需要核验的问题"]
}"""

# 重排用的结构。跟上面那段示例同形（只留骨架，重排不需要每条规矩）。
REFORMAT_SHAPE = ('{"name": "…", "chain_type": "制造链", "description": "…", '
                  '"stages": [{"name": "…", "stage_kind": "input", "description": "…", '
                  '"nodes": [{"name": "…", "node_type": "产品", "description": "…", '
                  '"source_refs": [1]}]}], '
                  '"edges": [{"from": "…", "to": "…", "relation_type": "流向", '
                  '"detail": "…", "source_refs": [1]}], "unknowns": ["…"]}')


class IndustryChainDraftError(RuntimeError):
    pass


def build_queries(topic: str) -> list[str]:
    """不让模型决定检索词，避免先花一次模型调用才开始找资料。"""

    name = topic.strip()
    return [
        f"{name} 产业链 上游 中游 下游 产品 服务",
        f"{name} 产业链 发展 指南 关键环节",
        f"{name} 产品 服务 交付 应用场景",
    ][:QUERY_COUNT]


def _source_name(hit: dict[str, Any]) -> str:
    kind = str(hit.get("kind") or "公开资料")
    title = str(hit.get("title") or "未命名资料").replace("\n", " ").strip()
    return f"{kind} · {title[:100]}"


def _sources_block(hits: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, hit in enumerate(hits, 1):
        title = str(hit.get("title") or "未命名资料")[:180]
        snippet = str(hit.get("snippet") or "")[:900]
        lines.append(
            f"[{index}]（{hit.get('kind') or '公开资料'}｜{hit.get('published') or '日期不详'}）"
            f"{title}\n链接：{hit.get('url') or ''}\n摘要：{snippet}"
        )
    return "\n\n".join(lines)


def _refs(value: Any, source_count: int) -> list[int]:
    refs: list[int] = []
    for raw in value if isinstance(value, list) else []:
        try:
            ref = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= ref <= source_count and ref not in refs:
            refs.append(ref)
    return refs


def _text(value: Any, limit: int) -> str:
    return str(value or "").replace("\n", " ").strip()[:limit]


def parse_draft(text: str, sources: list[dict[str, Any]], topic: str) -> dict[str, Any]:
    """收紧模型输出，保证存进底图的每项都可回到一个真实链接。"""

    # 一张底图前面是 3 次联网检索 + 一次长文生成（报价 30,000 token，
    # 是站里第二贵的动作）。最后一段格式坏了就整张丢掉，等于把检索到的资料
    # 连同这次生成一起扔了 —— 先把原文递回去重排一次。
    try:
        raw, _ = loads_or_reformat(text, task="industry-chain-draft", expect="object",
                                   shape=REFORMAT_SHAPE)
    except Truncated as cut:
        # 没写完救不回来，但**原因要说对**：说「格式坏了」他会去怀疑模型，
        # 说「太长了被截断」他才知道这是可以少画几个环节解决的。
        raise IndustryChainDraftError(
            f"这张底图画到一半被长度上限掐断了（{cut}）。"
            f"换一个窄一点的主题，或者少画几个环节再试一次。") from cut
    except ValueError as exc:
        raise IndustryChainDraftError(f"模型没有返回可解析的产业链结构：{exc}") from exc
    if not isinstance(raw, dict):
        raise IndustryChainDraftError("模型没有返回产业链结构。")

    source_count = len(sources)
    chain_type = _text(raw.get("chain_type"), 20)
    if chain_type not in {"制造链", "服务链", "平台生态"}:
        chain_type = "制造链"
    name = _text(raw.get("name"), 80) or f"{topic}产业链"
    description = _text(raw.get("description"), 500) or f"围绕{topic}的产品、服务与交付关系初稿。"

    stages: list[dict[str, Any]] = []
    node_index: dict[str, dict[str, Any]] = {}
    used_names: set[str] = set()
    dropped: Counter[str] = Counter()
    for stage_raw in (raw.get("stages") or [])[:MAX_STAGES]:
        if not isinstance(stage_raw, dict):
            continue
        stage_name = _text(stage_raw.get("name"), 60)
        if not stage_name:
            continue
        stage_kind = _text(stage_raw.get("stage_kind"), 20)
        if stage_kind not in _STAGE_KINDS:
            stage_kind = "core"
        nodes: list[dict[str, Any]] = []
        for node_raw in (stage_raw.get("nodes") or [])[:MAX_NODES_PER_STAGE]:
            if not isinstance(node_raw, dict):
                continue
            node_name = _text(node_raw.get("name"), 100)
            refs = _refs(node_raw.get("source_refs"), source_count)
            # 没来源、重名或只有“上游”这种空词的节点不会进入草稿。
            #
            # **丢掉的要数出来。** 这四种丢法都是静默的，而下面那句
            # 「公开资料不足以形成可用初稿」是在它们之后才说的 ——
            # 如果模型其实画了二十个节点、只是忘了挂来源编号，那句话就是假的：
            # 资料一点都不少，缺的是引用。两件事的下一步完全相反
            # （一个该换主题，一个该直接重试一次）。
            if not node_name:
                dropped["没有名字"] += 1
                continue
            if not refs:
                dropped["没挂来源编号"] += 1
                continue
            if node_name in used_names:
                dropped["重名"] += 1
                continue
            if node_name in {"上游", "下游", "客户", "产业链", "生态"}:
                dropped["只是个空词"] += 1
                continue
            node_type = _text(node_raw.get("node_type"), 20)
            if node_type not in _NODE_TYPES:
                node_type = "产品"
            source = sources[refs[0] - 1]
            node = {
                "name": node_name,
                "node_type": node_type,
                "description": _text(node_raw.get("description"), 500),
                "source_name": _source_name(source),
                "source_url": str(source.get("url") or "")[:1000],
                "source_refs": refs,
                # 有可点开的公开资料，但还没有经过用户逐条确认。
                "verification": "待确认",
            }
            nodes.append(node)
            node_index[node_name] = node
            used_names.add(node_name)
        if nodes:
            stages.append({
                "name": stage_name,
                "stage_kind": stage_kind,
                "description": _text(stage_raw.get("description"), 300),
                "nodes": nodes,
            })

    if len(stages) < 2 or len(node_index) < 4:
        # **说清楚是资料不够，还是画出来的被这里丢掉了。**
        # 这一轮已经花了 3 次联网检索加一次长文生成（实测 7 分），
        # 只回一句「资料不足」的话，他会去换主题 —— 而真正该做的可能只是重试一次。
        why = "、".join(f"{count} 个{reason}" for reason, count in dropped.most_common())
        raise IndustryChainDraftError(
            f"这一轮只整理出 {len(node_index)} 个节点、{len(stages)} 个环节，画不成一张图。"
            + (f"模型给的节点里有 {why}，被丢掉了 —— 资料本身有 {source_count} 条，"
               f"直接再试一次多半就好。" if dropped else
               f"资料只有 {source_count} 条，换一个更具体的主题会更容易画。"))

    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()
    for edge_raw in (raw.get("edges") or [])[:MAX_EDGES]:
        if not isinstance(edge_raw, dict):
            continue
        source_name = _text(edge_raw.get("from"), 100)
        target_name = _text(edge_raw.get("to"), 100)
        refs = _refs(edge_raw.get("source_refs"), source_count)
        key = (source_name, target_name)
        # 连线指向一个不存在的节点是最常见的一种丢法，而"不存在"往往是因为
        # 那个节点刚在上面被丢掉了（多半是没挂来源编号）。数出来，
        # 下面那句「没整理成可核验的关系」才说得具体。
        if source_name not in node_index or target_name not in node_index:
            dropped["连线指向了一个不在图上的节点"] += 1
            continue
        if not refs or source_name == target_name or key in seen_edges:
            continue
        source = sources[refs[0] - 1]
        edges.append({
            "from": source_name,
            "to": target_name,
            "relation_type": _text(edge_raw.get("relation_type"), 30) or "流向",
            "detail": _text(edge_raw.get("detail"), 500),
            "source_name": _source_name(source),
            "source_url": str(source.get("url") or "")[:1000],
            "source_refs": refs,
            "verification": "待确认",
        })
        seen_edges.add(key)

    if not edges:
        why = "、".join(f"{count} 条/个{reason}" for reason, count in dropped.most_common(3))
        raise IndustryChainDraftError(
            "有节点但一条可核验的连线都没有，画不成图。"
            + (f"被丢掉的有：{why}。直接再试一次多半就好。" if dropped else
               "请换一个更具体的主题再试。"))

    unknowns = [_text(item, 200) for item in (raw.get("unknowns") or []) if _text(item, 200)][:8]
    return {
        "name": name,
        "chain_type": chain_type,
        "description": description,
        "stages": stages,
        "edges": edges,
        "unknowns": unknowns,
    }


def generate(topic: str) -> dict[str, Any]:
    """检索、起草并持久化一张可编辑的个人底图。"""

    topic = topic.strip()
    if len(topic) < 2:
        raise IndustryChainDraftError("主题至少写两个字，例如「AI 数据中心」。")
    available, reason = websearch.available()
    if not available:
        raise IndustryChainDraftError("当前没有配置联网检索，不能生成带来源的产业链初稿。"
                                      "这一步不能只靠模型编图。")
    model_ready, model_reason = llm.ai_available()
    if not model_ready:
        raise IndustryChainDraftError(model_reason)

    found = websearch.gather(build_queries(topic))
    # 观点文章可作为线索，但不拿来当底图结构的唯一来源。
    sources = [item for item in found.get("hits") or [] if item.get("kind") != "观点"][:MAX_SOURCES]
    if len(sources) < MIN_SOURCES:
        raise IndustryChainDraftError(
            f"只找到 {len(sources)} 条可用公开资料，暂时不能画初稿。"
            "换一个更具体的产品、服务或场景名称，或稍后重试。"
        )

    prompt = (
        f"研究主题：{topic}\n\n"
        f"【公开资料】共 {len(sources)} 条；编号只能从这里引用：\n"
        f"{_sources_block(sources)}\n\n"
        "请先按资料组织成一张初稿。资料没有明确支持的节点和连线不要写。"
    )
    completion = llm.call(
        SYSTEM_PROMPT,
        prompt,
        task="industry-chain-draft",
        max_tokens=MAX_ANSWER_TOKENS,
        timeout=180,
        searches=len(found.get("queries") or []),
    )
    draft = parse_draft(completion.text, sources, topic)

    # 延迟导入避免 repository 在模块加载时反过来加载联网/模型模块。
    from .repository import create_generated_industry_chain_theme

    created = create_generated_industry_chain_theme(draft)
    return {
        "theme_id": created["id"],
        "theme_name": created["name"],
        "stages": len(created["stages"]),
        "nodes": created["node_count"],
        "edges": len(created["edges"]),
        "sources": len(sources),
        "primary_sources": sum(1 for source in sources if source.get("kind") == "一手"),
        "queries": found.get("queries") or [],
        "search_failures": found.get("failures") or [],
        "unknowns": draft["unknowns"],
        "model": llm.model_name(),
        "boundary": "这是一张带公开来源的待确认初稿；请逐条打开来源核验，再标注研究池公司。",
    }
