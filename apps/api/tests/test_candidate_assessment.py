"""候选的方法体检：不要求先建档，而且要把底座里已有的数喂进去。

第一版跑出来八个方法里**六个回「数据不足」**——而缺的那些（PE、PB、ROE、
营收增速、毛利率）全市场底座里本来就有，只是没送到模型面前。
花了积分只换回一句"缺数据"，那不叫体检。喂进去之后同一次调用变成
「数据不足 1」，其余七项都判出了东西。

所以这里测两件事：入口不要求建档、底座那一行确实进了提示词。
"""

import pytest

from stock_decision import assessment, repository
from stock_decision.database import connection, now_iso


def _task_with_candidate(monkeypatch) -> int:
    """建一个任务，返回候选的 item_id。"""
    import asyncio

    from tests.test_api import _seed_universe, _universe_row, request

    # 底座里这一行是重点：体检要靠它才判得出东西
    _seed_universe(monkeypatch, [_universe_row("300475", "香农芯创", roe=31.53)])
    with connection() as conn:
        conn.execute(
            "UPDATE market_universe SET price = ?, pe_ttm = ?, pb = ?, revenue_growth = ?, "
            "net_profit_growth = ?, eps = ?, bps = ?, gross_margin = ?, updated_at = ? "
            "WHERE symbol = ?",
            (152.59, 130.05, 14.6, 200.6, 7835.06, 2.86, 10.45, 9.12, now_iso(), "300475"))

    task = asyncio.run(request("POST", "/api/v1/tasks",
                               {"title": "体检入口", "strategy_key": "quality_steady"})).json()
    assert task.get("items"), f"任务里没有候选：{task}"
    return task["items"][0]["id"]


def test_a_candidate_can_be_assessed_without_being_archived(monkeypatch):
    """**体检就是用来帮你决定要不要建档的。**

    要求先建档才能体检，等于把这个决定提到了体检前面，顺序反了。
    """
    item_id = _task_with_candidate(monkeypatch)
    monkeypatch.setattr(repository, "assess_company", lambda *a, **k: {
        "results": [{"method_key": "margin_of_safety", "verdict": "不利", "summary": "PE 130 倍"}],
        "model": "test-model", "fingerprint": "fp"}, raising=False)
    monkeypatch.setattr("stock_decision.assessment.assess_company", lambda *a, **k: {
        "results": [{"method_key": "margin_of_safety", "verdict": "不利", "summary": "PE 130 倍"}],
        "model": "test-model", "fingerprint": "fp"})

    result = repository.assess_task_item(item_id)

    assert result is not None
    assert result["counts"] == {"不利": 1}
    # 没有因此在档案里凭空多出一家公司
    with connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM companies").fetchone()["n"] == 0


def test_the_universe_row_reaches_the_prompt(monkeypatch):
    """底座里的 PE / ROE / 增速要进提示词。

    不喂的话，八个方法里六个会回「数据不足」——而那些数就在库里躺着。
    """
    item_id = _task_with_candidate(monkeypatch)
    seen: dict[str, str] = {}

    def capture(company, theses=None, timeout=180):
        seen["prompt"] = assessment.build_prompt(company, theses)
        return {"results": [], "model": "test-model", "fingerprint": "fp"}

    monkeypatch.setattr("stock_decision.assessment.assess_company", capture)
    repository.assess_task_item(item_id)

    prompt = seen["prompt"]
    assert "130.05" in prompt, "市盈率没进提示词"
    assert "31.53" in prompt, "净资产收益率没进提示词"
    assert "200.6" in prompt, "营收增速没进提示词"


def test_a_missing_item_returns_none():
    assert repository.assess_task_item(999999) is None


def test_the_result_is_handed_back_by_the_api(monkeypatch):
    """走一趟 HTTP——响应模型没声明的字段会被静默丢掉，这坑踩过两次。"""
    import asyncio

    from tests.test_api import request

    item_id = _task_with_candidate(monkeypatch)
    monkeypatch.setattr("stock_decision.assessment.assess_company", lambda *a, **k: {
        "results": [{"method_key": "margin_of_safety", "verdict": "不利",
                     "summary": "三个门槛全数超标", "gaps": []}],
        "model": "test-model", "fingerprint": "fp"})
    repository.assess_task_item(item_id)

    tasks = asyncio.run(request("GET", "/api/v1/tasks")).json()
    item = next(i for t in tasks for i in t["items"] if i["id"] == item_id)

    assert item["assessment"][0]["verdict"] == "不利"
    assert item["assessed_at"]


def test_a_row_whose_checks_are_not_dicts_does_not_crash():
    """**不同来源的候选行，checks 的形状不一样。**

    策略筛出来的行里 checks 是「字典列表」（每条带门槛、实际值、过没过），
    而综合榜的行里 matched 是字符串列表。第一版把并集结果直接塞进来，
    在 check.get("actual") 上炸出 AttributeError，**整个接口 500**——
    而使用者看到的只是「请求失败 500」。

    遇到不认识的形状就跳过那一条，不要让整个请求挂掉。
    """
    from stock_decision.assessment import build_candidate_prompt

    rows = [{"name": "某公司", "symbol": "000001", "industry": "测试",
             "checks": ["低估型", "质量型"]}]          # ← 字符串，不是字典
    text = build_candidate_prompt(rows)
    assert "某公司" in text


def test_the_pool_rows_carry_facts_the_model_can_read():
    """综合榜那条路要在源头把维度分位翻译成 checks 的形状。

    只做防御（跳过不认识的）不够——那样模型收到的是一家**没有任何数字**的公司，
    它只能凭名字瞎猜，而这跟"接口没挂"是两回事。
    """
    from stock_decision.assessment import build_candidate_prompt

    row = {"name": "某公司", "symbol": "000001", "industry": "测试",
           "checks": [{"rule": "命中 低估型", "label": "低估型", "actual": None,
                       "passed": True, "missing": True},
                      {"rule": "生意质量 在这批候选里的分位", "field": "quality",
                       "label": "生意质量", "actual": 80.8, "passed": True, "missing": False}]}
    text = build_candidate_prompt([row])
    assert "生意质量 80.8" in text
