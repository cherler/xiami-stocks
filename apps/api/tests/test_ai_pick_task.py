"""「用一句话选股」的结果也要能存成研究任务。

## 为什么这条是漏的、而且非补不可

价值候选那一页上，九套策略和综合榜跑完都能「存成研究任务」，
只有一句话选股不能——它只有「存成我的策略」。使用者一眼看出来了：
「其他都有把结果存为研究任务的选项，是不是漏掉了？」

而**这一份恰恰最存不住**：

  · 存成策略留下的是"条件"，下次能再跑一遍；
  · 但模型挑哪几家写理由是当次的判断，条件一样也不保证挑出同一批。

所以关掉页面之后，那几家就只剩一句「上次你问过……」。

## 存的时候不能重跑规则

跟综合榜同一个道理：这两把哨兵 key 走的都是"按前端给的 symbols 存"这条路，
不能拿 strategy_key 去策略库里查——查不到就会把 `__ai_pick__` 这种
内部标识符原样甩到页面上（综合榜那次就是这么翻的车）。
"""

import asyncio

import pytest

from stock_decision import repository

from tests.test_api import _seed_universe, _universe_row, request


def test_一句话选股的结果能存成研究任务(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [
        _universe_row("600001", "选中甲"),
        _universe_row("600002", "选中乙"),
        _universe_row("600003", "没选丙"),
    ])
    created = asyncio.run(request("POST", "/api/v1/tasks", {
        "title": "一句话选股 · 赚到的是真钱",
        "strategy_key": repository.AI_PICK_KEY,
        # 模型当次挑出来的那两家。**第三家没被挑中，就不该进任务。**
        "symbols": ["600001", "600002"],
        "limit": 2,
    }))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["total"] == 2
    assert [item["symbol"] for item in body["items"]] == ["600001", "600002"]
    # 任务旁边显示的是清单名字，不能是内部标识符
    assert body["strategy_name"] == "一句话选股"
    assert "__ai_pick__" not in body["strategy_name"] + body["data_note"]


def test_没给symbols的时候说人话(monkeypatch: pytest.MonkeyPatch) -> None:
    """哨兵 key 不能靠重跑规则补出清单来——这时要说「先跑一次」，
    而不是抛一个「没有这个策略：__ai_pick__」。"""
    _seed_universe(monkeypatch, [_universe_row("600001", "选中甲")])
    failed = asyncio.run(request("POST", "/api/v1/tasks", {
        "title": "空的一句话选股",
        "strategy_key": repository.AI_PICK_KEY,
        "symbols": [],
    }))
    assert failed.status_code >= 400
    assert "一句话选股" in failed.text
    assert "__ai_pick__" not in failed.text


def test_前后端的哨兵key必须是同一个字符串() -> None:
    """前端 App.tsx 里也写了一份 `const AI_PICK_KEY`。
    两边不一致的话，存任务会当场失败，而错误信息里带着内部标识符。"""
    assert repository.AI_PICK_KEY == "__ai_pick__"
    assert set(repository.SENTINEL_LIST_NAMES) == {repository.AGENT_POOL_KEY, repository.AI_PICK_KEY}
