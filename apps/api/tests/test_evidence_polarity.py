"""证据方向：写下判断之后，事实往哪边走。

原来这根轴画不出来：855 条证据里 853 条是 neutral、0 条挂在任何判断上，
画出来是一条平线——不是图有问题，是数据还没有方向。

这里测的是三件会让这个功能变成噪音的事：判断的单位、相对于什么判、
以及说不出理由的方向要不要算。
"""

import pytest

from stock_decision import evidence_polarity, repository
from stock_decision.schemas import CompanyInput, EvidenceCreate, EvidencePolarity, ThesisCreate


def _evidence(company_id: int, excerpt: str, day: str) -> dict:
    return repository.create_evidence(company_id, EvidenceCreate(
        source_name="巨潮资讯公告", source_url="http://example.test/a",
        excerpt=excerpt, polarity=EvidencePolarity.neutral,
        occurred_at=f"{day}T00:00:00"))


def _company_with_thesis() -> tuple[int, int]:
    company = repository.create_company(
        CompanyInput(symbol="601318", name="中国平安", industry="保险"))
    thesis = repository.create_thesis(company["id"], ThesisCreate(
        claim="赌的是低估值加高现金流开始兑现到股东回报，看分红能不能持续抬升。",
        counter_condition="连续两年不分配或股利支付率下滑到 15% 以下。"))
    return company["id"], thesis["id"]


def test_one_corporate_action_is_judged_once(monkeypatch):
    """一次股权激励会拆成五到九份文件，按份判等于同一件事判五遍。

    花五倍的钱是小事，更糟的是时间轴上同一天堆出五个点——**看起来像那天
    发生了五件事**，而实际上只有一件。
    """
    company_id, _ = _company_with_thesis()
    for title in [
        "2026年限制性股票激励计划（草案）",
        "2026年限制性股票激励计划实施考核管理办法",
        "董事会薪酬与考核委员会关于公司2026年限制性股票激励计划（草案）的核查意见",
        "2026年限制性股票激励计划激励对象名单",
    ]:
        _evidence(company_id, title, "2026-07-29")

    with_ids = [dict(e, company_id=company_id) for e in
                repository.get_company(company_id)["evidences"]]
    events = evidence_polarity.cluster(with_ids)

    assert len(events) == 1, f"同一次激励被拆成了 {len(events)} 件事"
    # 代表取最短的那个标题：配套文件名字总是更长
    assert events[0]["title"] == "2026年限制性股票激励计划（草案）"
    # 但同一件事的四份文档都要一起改方向，否则轴上会同时出现一个支持和三个中性
    assert len(events[0]["evidence_ids"]) == 4


def test_procedural_files_never_reach_the_axis():
    """法律意见书、制度文件不占额度，也不该出现在方向轴上。"""
    company_id, _ = _company_with_thesis()
    _evidence(company_id, "北京市中伦律师事务所关于本次激励计划的法律意见书", "2026-07-29")
    _evidence(company_id, "《总经理工作细则》（2026年7月修订）", "2026-07-30")

    with_ids = [dict(e, company_id=company_id) for e in
                repository.get_company(company_id)["evidences"]]

    assert evidence_polarity.cluster(with_ids) == []


def test_no_thesis_means_no_judgement():
    """没写过投资逻辑就不判——那种情况下模型只能按「一般来说是好事吗」来答，
    而那恰恰是本站承诺不做的事。"""
    company = repository.create_company(
        CompanyInput(symbol="600519", name="贵州茅台", industry="白酒"))
    _evidence(company["id"], "关于2026年中期分红方案的公告", "2026-07-01")

    plan = repository.evidence_direction_plan(company["id"])

    assert plan["ready"] is False
    assert "投资逻辑" in plan["note"]
    assert plan["credits"] == 0


def test_the_cost_is_known_before_spending(monkeypatch):
    """点之前就该知道大概花多少，而不是点完看账单。"""
    company_id, _ = _company_with_thesis()
    for index in range(30):
        _evidence(company_id, f"关于2026年第{index}次分红方案的公告", f"2026-0{index % 9 + 1}-0{index % 9 + 1}")

    plan = repository.evidence_direction_plan(company_id)

    assert plan["ready"] is True
    assert plan["events"] > 0
    assert plan["credits"] == evidence_polarity.estimate_credits(plan["events"])


def _fake_model(monkeypatch, payload: str):
    class _Completion:
        text = payload
    monkeypatch.setattr(evidence_polarity.llm, "call", lambda *a, **k: _Completion())
    monkeypatch.setattr(evidence_polarity, "ai_available", lambda: (True, ""))


def test_a_direction_without_a_reason_falls_back_to_neutral(monkeypatch):
    """说不出依据的方向不算数。

    一个没有理由的「削弱」会让人白紧张一场，而下次真的削弱时他就不信了。
    """
    company_id, thesis_id = _company_with_thesis()
    _evidence(company_id, "关于2026年中期分红方案的公告", "2026-07-01")
    with_ids = [dict(e, company_id=company_id) for e in
                repository.get_company(company_id)["evidences"]]
    events = evidence_polarity.cluster(with_ids)

    _fake_model(monkeypatch, '{"items": [{"index": 1, "direction": "削弱", "reason": ""}]}')
    judged = evidence_polarity.judge(events, {"id": thesis_id, "claim": "x", "counter_condition": ""})

    assert judged[0]["polarity"] == "neutral"


def test_a_bare_array_reply_is_still_accepted(monkeypatch):
    """模型经常直接回数组，不给 {"items": …} 那个壳。

    只认一种形状的话，内容全对的一批会整批丢掉——实测发生过：
    74 件判得好好的，因为少一层括号全部丢弃，而钱已经花掉了。
    """
    company_id, thesis_id = _company_with_thesis()
    _evidence(company_id, "关于2026年中期分红方案的公告", "2026-07-01")
    with_ids = [dict(e, company_id=company_id) for e in
                repository.get_company(company_id)["evidences"]]
    events = evidence_polarity.cluster(with_ids)

    _fake_model(monkeypatch, '[{"index": 1, "direction": "支持", "reason": "标题含分红方案"}]')
    judged = evidence_polarity.judge(events, {"id": thesis_id, "claim": "x", "counter_condition": ""})

    assert judged and judged[0]["polarity"] == "support"


def test_an_out_of_range_index_is_dropped_not_guessed(monkeypatch):
    """越界的序号丢掉，不猜它想指哪条——猜错会把方向挂到别的事情上。"""
    company_id, thesis_id = _company_with_thesis()
    _evidence(company_id, "关于2026年中期分红方案的公告", "2026-07-01")
    with_ids = [dict(e, company_id=company_id) for e in
                repository.get_company(company_id)["evidences"]]
    events = evidence_polarity.cluster(with_ids)

    _fake_model(monkeypatch, '[{"index": 99, "direction": "支持", "reason": "越界"}]')
    judged = evidence_polarity.judge(events, {"id": thesis_id, "claim": "x", "counter_condition": ""})

    assert judged == []


def test_judging_polarity_is_not_a_review():
    """**给证据打极性标签是模型在贴标签，不是你复核了这条判断。**

    这里原来会写 last_reviewed_at = now，后果很隐蔽：写进去之后复核队列认为
    "你已经看过了"，于是这条逻辑连同它新变成反证的那几份证据一起，
    从待复核里消失——而 thesis_reviews 表里一条记录都没有，决策归因也是空的。

    实测就是这么发生的：使用者两条判断的 last_reviewed_at 是 08-06 22:31，
    那是极性判定作业跑的时间，他本人从没复核过。首页一直报「有反证」（对的），
    复核工作台一直是空的（错的）。

    复核的唯一入口是 record_thesis_review()，它会同时写 thesis_reviews。
    """
    from fastapi.testclient import TestClient

    from stock_decision import repository as repo
    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    thesis = client.post(f"/api/v1/companies/{company['id']}/theses", json={
        "claim": "赌定价权还在", "counter_condition": "合同负债连续两期下滑",
        "status": "watching", "next_review_trigger": "年报"}).json()

    # **必须有证据，否则 judge_evidence_direction 提前返回、根本走不到那一行。**
    # 第一版测试就是这么写的：它是绿的，而把 bug 放回去它还是绿的——
    # 一条守不住任何东西的测试。
    client.post(f"/api/v1/companies/{company['id']}/evidences", json={
        "source_name": "2026 年半年报", "excerpt": "合同负债同比下滑 18%",
        "polarity": "neutral", "occurred_at": "2026-08-04"})

    with repo.connection() as conn:
        before = conn.execute("SELECT last_reviewed_at FROM theses WHERE id = ?",
                              (thesis["id"],)).fetchone()["last_reviewed_at"]
    assert before is None

    # judge_evidence_direction 会调模型；这里只要证明"落库那一步不写 last_reviewed_at"，
    # 所以把模型那段换掉，直接走写库路径。
    import stock_decision.evidence_polarity as ep
    monkey = getattr(repo, "evidence_polarity", ep)
    original = monkey.judge
    monkey.judge = lambda *a, **k: []
    try:
        repo.judge_evidence_direction(company["id"])
    finally:
        monkey.judge = original

    with repo.connection() as conn:
        after = conn.execute("SELECT last_reviewed_at FROM theses WHERE id = ?",
                             (thesis["id"],)).fetchone()["last_reviewed_at"]
        reviews = conn.execute("SELECT COUNT(*) AS n FROM thesis_reviews WHERE thesis_id = ?",
                               (thesis["id"],)).fetchone()["n"]
    assert after is None, "打标签不许把逻辑标成已复核"
    assert reviews == 0
