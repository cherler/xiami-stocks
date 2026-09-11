"""产业链底图：**一句「资料不足」，可能是假的。**

2026-08-16 线上真跑了一张（主题「固态电池」，3 次检索 21 条资料、7 分）：
成功，6 个环节 22 个节点 23 条连线，一个节点都没被丢掉。这一轮量到两件事：

    输出 3,418 token / 上限 4,200   —— 用掉 81%
    模型给的 22 个节点全部有来源编号 —— 丢弃逻辑这次没触发

## 一、上限离得太近

提示词允许的上界是 6 阶段 × 8 节点（每个节点 500 字描述）+ 28 条连线
（每条 500 字），真写到那个量级一定撞线。而撞线的代价不是"少画几个节点"，
是**这一整轮连同 3 次联网检索一起丢掉**。

冻结额不跟 max_tokens 挂钩（使用者 2026-08-14 拍板），调大挡不住任何人。

## 二、四种静默丢弃，和一句可能不成立的话

节点会因为四件事被丢掉：没名字、没挂来源编号、重名、只是个空词。
全部静默。而在它们之后才说的那句是：

    「公开资料不足以形成可用初稿；换一个更具体的主题，或稍后重试。」

如果模型其实画了二十个节点、只是忘了挂来源编号，**这句话就是假的**：
资料一点都不少，缺的是引用。两件事的下一步完全相反 ——
一个该换主题，一个该直接重试一次。
"""

import pytest

from stock_decision import industry_chain_draft as icd


def _sources(count: int = 4) -> list[dict[str, str]]:
    return [{"kind": "媒体", "title": f"资料 {i}", "url": f"https://x/{i}",
             "snippet": "…", "published": "2026-01-01"} for i in range(1, count + 1)]


def _draft(stages, edges=None) -> str:
    import json

    return json.dumps({
        "name": "固态电池产业链", "chain_type": "制造链", "description": "…",
        "stages": stages, "edges": edges or [], "unknowns": [],
    }, ensure_ascii=False)


def test_the_answer_budget_is_not_a_near_miss():
    """实测用掉 81%。撞线的代价是整轮连同 3 次检索一起丢掉，不值得赌。"""
    assert icd.MAX_ANSWER_TOKENS >= 20000


def test_nodes_without_a_source_are_not_reported_as_missing_data():
    """**这一条是要害。** 模型画了 8 个节点、一个都没挂编号 ——
    资料有 4 条，一条不少。这时候说「公开资料不足」是把人往错的方向支。"""
    stages = [{"name": f"环节{s}", "stage_kind": "core", "nodes": [
        {"name": f"节点{s}{n}", "node_type": "产品", "description": "…"}   # 没有 source_refs
        for n in range(4)]} for s in range(2)]

    with pytest.raises(icd.IndustryChainDraftError) as caught:
        icd.parse_draft(_draft(stages), _sources(4), "固态电池")

    message = str(caught.value)
    assert "没挂来源编号" in message, message
    assert "再试一次" in message, "该说的是重试，不是换主题"
    assert "资料不足" not in message, "资料有 4 条，这句话不成立"


def test_when_the_material_really_is_thin_it_says_so():
    """反过来也要对：模型只画得出一个节点，那才是资料的问题。"""
    stages = [{"name": "环节", "stage_kind": "core", "nodes": [
        {"name": "唯一节点", "node_type": "产品", "description": "…", "source_refs": [1]}]}]

    with pytest.raises(icd.IndustryChainDraftError) as caught:
        icd.parse_draft(_draft(stages), _sources(2), "固态电池")
    assert "更具体的主题" in str(caught.value)


def test_a_draft_that_holds_up_still_comes_through():
    """加了统计不能把好的那条路弄坏 —— 够画的照旧画出来。"""
    stages = [
        {"name": "上游材料", "stage_kind": "input", "nodes": [
            {"name": "硫化锂", "node_type": "原材料", "description": "…", "source_refs": [1]},
            {"name": "固态电解质", "node_type": "部件", "description": "…", "source_refs": [2]}]},
        {"name": "电芯制造", "stage_kind": "core", "nodes": [
            {"name": "全固态电芯", "node_type": "产品", "description": "…", "source_refs": [1]},
            {"name": "干法电极设备", "node_type": "设备", "description": "…", "source_refs": [3]}]},
    ]
    edges = [{"from": "固态电解质", "to": "全固态电芯", "relation_type": "流向",
              "detail": "…", "source_refs": [1]}]

    draft = icd.parse_draft(_draft(stages, edges), _sources(4), "固态电池")
    assert len(draft["stages"]) == 2
    assert sum(len(s["nodes"]) for s in draft["stages"]) == 4
    assert len(draft["edges"]) == 1
    # 每一项都必须能点回一条真实资料，且都还没被确认过
    for stage in draft["stages"]:
        for node in stage["nodes"]:
            assert node["source_url"].startswith("https://")
            assert node["verification"] == "待确认"


def test_an_edge_pointing_at_a_dropped_node_is_named_as_such():
    """连线指向不存在的节点，通常是因为那个节点刚被丢掉了。
    只说「没整理成可核验的关系」，他不知道该重试还是该换主题。"""
    stages = [
        {"name": "上游", "stage_kind": "input", "nodes": [
            {"name": f"材料{i}", "node_type": "原材料", "description": "…", "source_refs": [1]}
            for i in range(2)]},
        {"name": "中游", "stage_kind": "core", "nodes": [
            {"name": f"产品{i}", "node_type": "产品", "description": "…", "source_refs": [2]}
            for i in range(2)]},
    ]
    edges = [{"from": "材料0", "to": "一个没画出来的节点", "relation_type": "流向",
              "detail": "…", "source_refs": [1]}]

    with pytest.raises(icd.IndustryChainDraftError) as caught:
        icd.parse_draft(_draft(stages, edges), _sources(4), "固态电池")
    assert "不在图上的节点" in str(caught.value)


def test_a_reference_out_of_range_is_dropped_not_guessed():
    """编号越界的丢掉，不猜它想指哪一条 —— 猜错会把一个节点挂到另一份资料上，
    而读的人点开才发现对不上，那比没有来源更糟。"""
    stages = [{"name": "环节", "stage_kind": "core", "nodes": [
        {"name": "节点", "node_type": "产品", "description": "…", "source_refs": [99]}]}]

    with pytest.raises(icd.IndustryChainDraftError) as caught:
        icd.parse_draft(_draft(stages), _sources(2), "固态电池")
    assert "没挂来源编号" in str(caught.value)
