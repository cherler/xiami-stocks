"""候选初筛写回来的东西，页面得能用。

这块一条测试都没有，于是两个问题一直没人发现：

1. **结论写进了一个谁也不认的状态。** 模型判「值得深入」，代码往 status 里写
   「深入研究」——而全系统认的状态只有「待看/已建档/已排除」。结果是下拉框选不中
   任何一项，任务的三个计数（待看/已建档/已排除）也数不到它，初筛跑完等于白跑。
2. **结构被拼平了。** 模型返回的是 verdict + reasons + concerns 三段，
   落库时拼成一坨换行文本塞进 note。拼平之后拆不回来——结论句子里本身就有分号
   和换行——页面只能整段显示，人得自己在一段话里找哪句在帮它说话、哪句在拆台。

所以下面测的不是「函数跑通了」，是「跑完之后这条候选长什么样」。

**而且要走 HTTP 出来看。** 第一版这些测试全是直接调 repository 的，结果
FastAPI 的响应模型把新加的三个字段原样丢掉了——库里存着、repository 也返回了，
接口出去就是没有，前端拿 undefined 去 .length，整页白屏。
测试全绿、页面全白，就是因为测试停在了响应模型前面一层。
"""

import asyncio

import pytest

from stock_decision import repository
from stock_decision.database import connection

from tests.test_api import _seed_universe, _universe_row, request


def _task_with(monkeypatch: pytest.MonkeyPatch, verdicts: dict[str, str]) -> dict:
    """建一个任务，并让模型对每个代码给出指定结论。"""

    _seed_universe(monkeypatch, [
        _universe_row(symbol, f"候选{symbol[-1]}", roe=26.0) for symbol in verdicts
    ])
    task = asyncio.run(
        request("POST", "/api/v1/tasks", {"title": "初筛", "strategy_key": "quality_steady"})
    ).json()

    def fake_review(payloads, *_args, **_kwargs):
        return [{
            "symbol": row["symbol"],
            "verdict": verdicts[row["symbol"]],
            "conclusion": f"{row['name']}是做什么的；然后是数字",
            "reasons": ["毛利率连续三年在 40% 以上", "分红率稳定"],
            "concerns": ["应收账款增速快过收入"],
            "model": "test-model",
        } for row in payloads]

    monkeypatch.setattr(repository, "review_candidates", fake_review)
    monkeypatch.setattr(repository, "enrich_task_items", lambda *a, **k: 0)
    repository.auto_review_task(task["id"])
    return repository.get_research_task(task["id"])


def test_verdict_does_not_land_in_an_unknown_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """状态必须是系统认的那三个之一——不然下拉框和计数全部失灵。"""
    task = _task_with(monkeypatch, {"600001": "值得深入", "600002": "先放着", "600003": "直接排除"})

    for item in task["items"]:
        assert item["status"] in repository.TASK_ITEM_STATUSES, item["status"]
    # 三个计数加起来必须等于总数，一条都不能漏在计数之外
    assert task["pending"] + task["adopted"] + task["dropped"] == task["total"]


def test_verdict_is_its_own_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """「值不值得花时间」是模型的判断，「我处理到哪一步」是人的动作，两件事分开存。"""
    task = _task_with(monkeypatch, {"600001": "值得深入", "600002": "直接排除"})
    by_symbol = {item["symbol"]: item for item in task["items"]}

    assert by_symbol["600001"]["verdict"] == "值得深入"
    # 「值得深入」只是建议去看，不代表已经建档——status 保持人自己的进度
    assert by_symbol["600001"]["status"] == "待看"
    # 「直接排除」确实等于「我不看了」，这一档才动状态
    assert by_symbol["600002"]["verdict"] == "直接排除"
    assert by_symbol["600002"]["status"] == "已排除"


def test_reasons_and_concerns_survive_as_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """支持与疑点要分开存成两个数组，不能只剩一段拼好的文本。"""
    task = _task_with(monkeypatch, {"600001": "值得深入"})
    item = task["items"][0]

    assert item["reasons"] == ["毛利率连续三年在 40% 以上", "分红率稳定"]
    assert item["concerns"] == ["应收账款增速快过收入"]
    # 结论存在 conclusion 里，**不占用 note** —— note 是你自己写的那一栏。
    # 两者共用一个字段的后果是模型那段几百字被塞进单行输入框，想看都看不到。
    assert item["conclusion"].startswith("候选")
    assert item["note"] == ""


def test_review_does_not_overwrite_what_a_person_already_did(monkeypatch: pytest.MonkeyPatch) -> None:
    """已经建档的候选，初筛不能把它的状态盖回去。

    建任务时就在研究池里的公司会直接标成「已建档」。如果初筛无差别写 status，
    那条记录就被打回「待看」——人做过的事被一次自动任务抹掉。
    """
    _seed_universe(monkeypatch, [_universe_row("600519", "贵州茅台", roe=30.0)])
    asyncio.run(request("POST", "/api/v1/companies", {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"}))
    task = asyncio.run(request("POST", "/api/v1/tasks", {"title": "核对", "strategy_key": "quality_steady"})).json()
    assert task["items"][0]["status"] == "已建档"

    # 已建档的条目 note 还是空的，会被初筛捞进来
    monkeypatch.setattr(repository, "review_candidates", lambda payloads, *a, **k: [{
        "symbol": row["symbol"], "verdict": "先放着", "conclusion": "白酒", "reasons": [],
        "concerns": [], "model": "test-model"} for row in payloads])
    monkeypatch.setattr(repository, "enrich_task_items", lambda *a, **k: 0)
    repository.auto_review_task(task["id"])

    after = repository.get_research_task(task["id"])
    assert after["items"][0]["status"] == "已建档"
    assert after["items"][0]["verdict"] == "先放着"


def test_a_persons_own_note_does_not_block_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """自己写了一句，不该让这条候选永远轮不到模型看。

    两者分开存之后，判据是「模型还没看过」（conclusion 为空），
    不是「人还没写结论」——后者会把自己随手记一笔的候选排除在初筛之外。
    """
    _seed_universe(monkeypatch, [_universe_row("600001", "候选甲", roe=26.0)])
    task = asyncio.run(request("POST", "/api/v1/tasks", {"title": "初筛", "strategy_key": "quality_steady"})).json()
    asyncio.run(request("PATCH", f"/api/v1/tasks/items/{task['items'][0]['id']}", {"note": "我自己看过了"}))

    monkeypatch.setattr(repository, "review_candidates", lambda payloads, *a, **k: [{
        "symbol": row["symbol"], "verdict": "先放着", "conclusion": "模型的话",
        "reasons": [], "concerns": [], "model": "test-model"} for row in payloads])
    monkeypatch.setattr(repository, "enrich_task_items", lambda *a, **k: 0)
    repository.auto_review_task(task["id"])

    with connection() as conn:
        row = conn.execute(
            "SELECT note, conclusion FROM research_task_items WHERE task_id = ?",
            (task["id"],)).fetchone()
    assert row["note"] == "我自己看过了", "把人写的东西盖掉了"
    assert row["conclusion"] == "模型的话", "人写过一句，模型就不看了"


def test_the_api_actually_hands_back_the_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    """走一趟 HTTP —— 响应模型没声明的字段会被静默丢掉。

    这是白屏那次的真正断层：repository 返回得好好的，接口出去少三个字段。
    只测到 repository 是看不见的。
    """
    task = _task_with(monkeypatch, {"600001": "值得深入"})
    listed = asyncio.run(request("GET", "/api/v1/tasks")).json()
    item = next(t for t in listed if t["id"] == task["id"])["items"][0]

    assert item["verdict"] == "值得深入"
    assert item["reasons"] == ["毛利率连续三年在 40% 以上", "分红率稳定"]
    assert item["concerns"] == ["应收账款增速快过收入"]


def test_research_task_can_be_deleted_without_deleting_company(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_universe(monkeypatch, [_universe_row("600001", "候选甲", roe=26.0)])
    company = asyncio.run(request("POST", "/api/v1/companies", {
        "symbol": "600001", "name": "候选甲", "industry": "测试行业"
    })).json()
    task = asyncio.run(request("POST", "/api/v1/tasks", {
        "title": "待删除任务", "strategy_key": "quality_steady"
    })).json()

    deleted = asyncio.run(request("DELETE", f"/api/v1/tasks/{task['id']}"))
    assert deleted.status_code == 204
    assert all(item["id"] != task["id"] for item in asyncio.run(request("GET", "/api/v1/tasks")).json())
    assert asyncio.run(request("GET", f"/api/v1/tasks/{task['id']}" )).status_code == 404
    # 删除研究任务只删任务快照，不动用户的公司档案。
    assert asyncio.run(request("GET", f"/api/v1/companies/{company['id']}" )).status_code == 200


def test_中断的任务要写清能重跑且不会重复计费(monkeypatch: pytest.MonkeyPatch) -> None:
    """**中断 ≠ 失败。**

    失败是这次活儿干砸了；中断是机器重启把它打断了，跟这次活儿本身无关。
    原来两者写成同一句红字，而中断那句只有「服务重启，任务未完成」——
    看到的人第一反应是「那我刚才那笔积分呢」，第二反应是「我要从哪儿再点一次」。
    这两个问题的答案都是好的（可以重跑、不会重复计费），只是没人说。
    """
    from stock_decision.background import (
        INTERRUPTED_NOTE, create_job, get_job, recover_stale_jobs, update_job)

    job_id = create_job("deep_report", 1, label="正在生成深度研报")
    update_job(job_id, status="运行中")
    assert recover_stale_jobs() >= 1

    row = get_job(job_id)
    assert row["status"] == "已中断"
    assert row["error"] == INTERRUPTED_NOTE
    # 这三样缺一不可：能不能重来、会不会重复扣钱、上一次冻结怎么办
    assert "重新跑一次" in row["error"]
    assert "重复计费" in row["error"]
    assert "退回" in row["error"]
