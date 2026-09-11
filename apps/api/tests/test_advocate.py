"""对话式反方：钉在一家公司上，专门找你这条判断可能错在哪。

一个会附和你的荐股 Agent 是这个产品里最没价值也最危险的东西——
你已经买了、已经写了逻辑，多一个声音说"有道理"只是把确信度往上推一格。

反方的价值全部建立在**它说的话有出处**这一点上。所以这个文件守的
就是那几条硬约束，而且它们都在代码里，不靠提示词自觉：

- 引不出数据的主张当场丢掉
- 说出来的数字回原始数据里找一遍，找不到的标出来
- 工具挂了要如实说，不许伪造空结果
- 只能提议，一个字都不写库
"""

import json

import pytest

from stock_decision import devils_advocate as da


class _Script:
    """按脚本回答的假模型：第 i 轮返回第 i 段 content 块。"""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0

    def __call__(self, system, messages, tools, **kwargs):
        blocks = self.rounds[min(self.calls, len(self.rounds) - 1)]
        self.calls += 1
        completion = type("C", (), {"billing": lambda self: {"metered": False}})()
        return {"content": blocks, "completion": completion, "stop_reason": "end_turn"}


def _final(payload):
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


def _use(name, tool_id="t1", args=None):
    return [{"type": "tool_use", "id": tool_id, "name": name, "input": args or {}}]


def _run(monkeypatch, rounds, runner=None, question="我这条逻辑最可能错在哪？"):
    monkeypatch.setattr(da.llm, "call_tools", _Script(rounds))
    monkeypatch.setattr(da, "ai_available", lambda: (True, ""))
    return da.converse(question, runner or (lambda name, args: {"rows": []}))


GOOD = {"points": [{
    "claim": "合同负债占收入连续两年下滑，渠道打款意愿在走弱",
    "evidence": [{"tool": "industry_metrics", "shows": "合同负债占收入从 12.3% 掉到 4.74%"}],
    "counter_condition": "2026 年年报合同负债占收入继续低于 5%",
    "task": "查一下经销商数量这两年的变化"}],
    "not_challenged": "毛利率确实还很稳", "gaps": []}


# ------------------------------------------------------------------ 引不出数据的丢掉

def test_a_claim_without_evidence_is_dropped(monkeypatch):
    """**一句听着有道理、其实凭空捏的反驳，比没有反驳糟得多。**

    它会让你放弃一条本来对的判断，而你连它错在哪都查不出来——
    因为它压根没有可查的出处。
    """
    result = _run(monkeypatch, [_final({"points": [
        {"claim": "估值偏高，需要注意风险", "evidence": []}]})])
    assert result["points"] == []
    assert any("拿不出数据支撑" in gap for gap in result["gaps"]), "丢了要说丢了几条、为什么"


def test_empty_evidence_text_does_not_count_as_evidence(monkeypatch):
    """挂一个空壳 evidence 就想蒙混过关——不认。"""
    result = _run(monkeypatch, [_final({"points": [
        {"claim": "有风险", "evidence": [{"tool": "financials", "shows": "  "}]}]})])
    assert result["points"] == []


def test_a_well_supported_claim_survives_with_its_conversions(monkeypatch):
    result = _run(monkeypatch, [_final(GOOD)])
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert point["evidence"][0]["tool"] == "industry_metrics"
    assert point["counter_condition"], "反证条件是这个功能的产出，不能丢"
    assert point["task"]


# ------------------------------------------------------------------ 数字要能溯源

def test_numbers_that_are_not_in_the_data_get_flagged(monkeypatch):
    """**标出来，不是删掉。**

    有些数是它自己算的（两期相减），删掉会把有用的话一起丢了。
    但标出来之后你会立刻知道该核哪几个。
    """
    runner = lambda name, args: {"rows": [{"合同负债占收入": 4.74}]}
    result = _run(monkeypatch, [_use("industry_metrics"), _final({"points": [{
        "claim": "合同负债占收入只有 4.74%，而三年前是 12.3%",
        "evidence": [{"tool": "industry_metrics", "shows": "最新一期 4.74%"}]}]})], runner)
    point = result["points"][0]
    assert "4.74" not in point["untraceable"], "查到过的数不该被标"
    assert "12.3" in point["untraceable"], "没查到的数必须标出来"


def test_years_and_small_integers_are_not_chased(monkeypatch):
    """年份和"两期""三年"这种小整数不值得追——它们几乎不会是编出来的数据，

    每条都标只会让真正要紧的那个数淹掉。
    """
    result = _run(monkeypatch, [_final({"points": [{
        "claim": "2025 年这条逻辑连续 2 期不成立",
        "evidence": [{"tool": "financials", "shows": "看过了"}]}]})])
    assert result["points"][0]["untraceable"] == []


def test_the_same_number_written_differently_still_counts_as_traced(monkeypatch):
    """库里存的是元，模型多半会换算成亿说出来；4.7 和 4.70 也是同一个数。

    不认这些写法的话，"找不到出处"会满屏都是，然后你就不看它了。
    """
    runner = lambda name, args: {"periods": [{"net_profit": 812000000.0, "ratio": 4.7}]}
    result = _run(monkeypatch, [_use("financials"), _final({"points": [{
        "claim": "净利润 8.12 亿元，比例 4.70",
        "evidence": [{"tool": "financials", "shows": "年报"}]}]})], runner)
    assert result["points"][0]["untraceable"] == []


# ------------------------------------------------------------------ 工具

def test_the_tools_are_pinned_to_one_company():
    """**工具不接受 company_id 参数。**

    这不是省事，是边界：模型没有办法去查别家公司，更没有办法去查别人的数据。
    """
    for spec in da.tool_specs():
        properties = spec["input_schema"].get("properties") or {}
        assert "company_id" not in properties, f"{spec['name']} 不该让模型指定看哪家公司"
        assert "symbol" not in properties


def test_a_broken_tool_is_reported_not_faked(monkeypatch):
    """**不许伪造一个空结果。**

    空结果会被读成"查过了，没有数据"，然后它据此断言——
    而真相是这张表这次没读成功。
    """
    seen = {}

    def boom(name, args):
        raise RuntimeError("数据库连接断了")

    monkeypatch.setattr(da.llm, "call_tools",
                        lambda system, messages, tools, **k: seen.setdefault("m", messages)
                        or _Script([_use("financials"), _final({"points": []})])(system, messages, tools))
    monkeypatch.setattr(da, "ai_available", lambda: (True, ""))
    script = _Script([_use("financials"), _final({"points": []})])
    monkeypatch.setattr(da.llm, "call_tools", script)
    result = da.converse("问一句", boom)
    # 工具的报错要作为 tool_result 递回给模型，让它换一条路
    payloads = json.dumps(result["messages"], ensure_ascii=False, default=str)
    assert "数据库连接断了" in payloads
    assert result["tool_calls"][0]["rows"] == 0


def test_it_gives_up_out_loud_instead_of_returning_half_an_answer(monkeypatch):
    """跑满轮数还在查，说明它没收敛。

    **不要把半截结果当成答案**——半截的反方结论跟完整的长得一模一样。
    """
    result = _run(monkeypatch, [_use("financials", "t1")] * (da.MAX_ROUNDS + 2))
    assert result["points"] == []
    assert any("还没收敛" in gap for gap in result["gaps"])
    assert result["rounds"] == da.MAX_ROUNDS


# ------------------------------------------------------------------ 边界

def test_it_never_claims_to_know_whether_to_buy_or_sell(monkeypatch):
    """你的仓位、成本、别的选择、现金流安排它都不知道，也不该假装知道。"""
    result = _run(monkeypatch, [_final(GOOD)])
    # 断言的是**必须说到的意思**，不是原话。
    # 钉死措辞的话，一次正常的文案压缩就会让它红，而它守的规矩其实没变。
    assert "不会说该不该买卖" in result["boundary"]
    assert "不写库" in result["boundary"] or "不能写" in result["boundary"]


def test_the_prompt_forbids_memory_and_the_web():
    """记忆里的数字跟真的长得一模一样，而它可能是三年前的。"""
    assert "不能上网" in da.SYSTEM_PROMPT
    assert "记忆" in da.SYSTEM_PROMPT
    assert "没查过就不要断言" in da.SYSTEM_PROMPT


def test_it_asks_for_falsifiable_conditions_not_vague_warnings():
    """「估值偏高，需要注意风险」等于没说。提示词里必须把好坏两个例子都摆出来。"""
    assert "估值偏高" in da.SYSTEM_PROMPT and "等于没说" in da.SYSTEM_PROMPT


# ------------------------------------------------------------------ 走接口

def test_the_runner_only_reads_and_stays_inside_one_company():
    from fastapi.testclient import TestClient

    from stock_decision import repository as repo
    from stock_decision.main import app

    client = TestClient(app)
    mine = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    client.post(f"/api/v1/companies/{mine['id']}/theses", json={
        "claim": "定价权还在", "counter_condition": "连续两期营收下滑"})

    run = repo.company_tool_runner(mine["id"])
    for name in ("financials", "industry_metrics", "segments", "valuation",
                 "announcements", "theses", "promises", "peers"):
        payload = run(name, {})
        assert payload is not None, f"{name} 应该返回点什么，哪怕是「还没同步」"
    assert "没有这个工具" in str(run("delete_everything", {}))


# --------------------------------------------------------------- 交叉验证（#43）

def test_every_claim_gets_independently_re_checked(monkeypatch):
    """**到复核之前，代码只核过它说的数字有没有出处，没核过那句话本身。**

    一条数字全对、推论错了的主张，看起来跟对的一模一样——
    而这一页的产出会被使用者拿去改自己的认错条件。
    """
    from stock_decision import company_tools as ct
    from stock_decision import devils_advocate as da

    points = [{"claim": f"主张{i}", "evidence": [{"tool": "financials", "shows": "x"}],
               "counter_condition": "", "task": "", "untraceable": []} for i in range(3)]
    asked: list[str] = []

    def _loop(system, messages, runner, **kwargs):
        asked.append(messages[0]["content"])
        # 第二条判"站不住"
        stands = "主张1" not in messages[0]["content"]
        return {"text": '{"stands": %s, "why": "查过了"}' % ("true" if stands else "false"),
                "tool_calls": [], "payloads": [], "messages": [], "billing": {},
                "exhausted": False}

    monkeypatch.setattr(ct, "run_loop", _loop)
    kept, refuted = da._cross_check(points, lambda n, a: {})
    assert len(asked) == 3, "每一条都要被独立复核，不是抽查"
    assert refuted == 1
    assert [p["claim"] for p in kept] == ["主张0", "主张2"]


def test_a_failed_re_check_lets_the_claim_through(monkeypatch):
    """**复核是加分项，不是准入门槛。**

    一次网络抖动不该把本来有效的反方主张全删掉——那会让整页突然空白，
    而空白跟"这次真的没找到问题"长得一模一样。
    """
    from stock_decision import company_tools as ct
    from stock_decision import devils_advocate as da

    def _boom(*_a, **_k):
        raise RuntimeError("限流")

    monkeypatch.setattr(ct, "run_loop", _boom)
    points = [{"claim": "主张", "evidence": [], "counter_condition": "", "task": "",
               "untraceable": []}]
    kept, refuted = da._cross_check(points, lambda n, a: {})
    assert len(kept) == 1 and refuted == 0


def test_claims_beyond_the_cap_are_marked_unchecked(monkeypatch):
    """超出上限的没复核过，**照原样留着但要标出来**——
    不标的话它们会假装自己也被核过了。"""
    from stock_decision import company_tools as ct
    from stock_decision import devils_advocate as da

    monkeypatch.setattr(ct, "run_loop", lambda *a, **k: {
        "text": '{"stands": true}', "tool_calls": [], "payloads": [],
        "messages": [], "billing": {}, "exhausted": False})
    points = [{"claim": f"c{i}", "evidence": [], "counter_condition": "", "task": "",
               "untraceable": []} for i in range(da.MAX_CHECKED + 2)]
    kept, _ = da._cross_check(points, lambda n, a: {})
    assert sum(1 for p in kept if p.get("unchecked")) == 2
    assert all(not p.get("unchecked") for p in kept[:da.MAX_CHECKED])


# ------------------------------------------------- 最后那段 JSON 坏了（#58）
#
# 到解析这一步为止，查库那几轮**已经花掉了**：工具轮次是真调用、真计费。
# 原来这里一个 ValueError 抛出去，整个后台任务就失败——使用者付了一轮的钱，
# 拿到一句 JSONDecodeError。而坏 JSON 恰恰是最常见的一种失败：
# 模型在中文值里夹一个英文引号就够了。

# **写完了、但格式坏了**：`not_challenged` 和 `gaps` 之间少一个逗号。
# 这个形状是真的 —— 2026-08-14 线上跑真实反方时，重排的产出就长这样。
#
# 括号必须是平的：少一个右括号的话它是"没写完"，走 Truncated 那条路，
# 重排根本不会被调用（见 test_json_reformat.py 里那一组）。
_BROKEN = ('{"points": [{"claim": "他赌的是渠道愿意提前打款",'
           ' "evidence": [{"tool": "financials", "shows": "合同负债占比 4.74%"}]}],'
           ' "not_challenged": "毛利率确实还稳" "gaps": []}')


def _text(raw):
    return [{"type": "text", "text": raw}]


def test_a_broken_final_json_is_reformatted_once_instead_of_wasting_the_round(monkeypatch):
    """坏 JSON **自费重排一次**，不要让已经花掉的那一轮打水漂。

    重排这次调用不带工具、不查库，输入就是那段坏文本 ——
    比重跑一整轮便宜一个数量级，而它救回的是已经花掉的那一整轮。
    """
    from stock_decision import devils_advocate as da

    asked: list[tuple[str, str]] = []

    def _fake_call(system, user, **kwargs):
        asked.append((system, user))
        return type("C", (), {"text": json.dumps(GOOD, ensure_ascii=False)})()

    monkeypatch.setattr(da.llm, "call", _fake_call)
    result = _run(monkeypatch, [_text(_BROKEN)])

    assert len(asked) == 1, "只重排一次，不是无限重试"
    assert "只改格式" in asked[0][0], "重排的提示词必须禁止改内容"
    assert asked[0][1] == _BROKEN, "要把原文原样递回去，不是递一段摘要"
    assert [p["claim"] for p in result["points"]] == [GOOD["points"][0]["claim"]]


def test_a_reformatted_answer_says_so(monkeypatch):
    """重排过要说出来。内容没动，但「这份结论返过一次工」使用者有权知道 ——
    万一哪一条读着别扭，他至少知道该往哪儿怀疑。"""
    from stock_decision import devils_advocate as da

    monkeypatch.setattr(da.llm, "call", lambda *a, **k: type(
        "C", (), {"text": json.dumps(GOOD, ensure_ascii=False)})())
    result = _run(monkeypatch, [_text(_BROKEN)])
    assert any("重排" in gap for gap in result["gaps"])


def test_a_good_answer_is_never_sent_back_for_reformatting(monkeypatch):
    """能解析的一次都不要重排 —— 那是白花一次调用。"""
    from stock_decision import devils_advocate as da

    def _boom(*_a, **_k):
        raise AssertionError("解析得动的答案不该再调一次模型")

    monkeypatch.setattr(da.llm, "call", _boom)
    result = _run(monkeypatch, [_final(GOOD)])
    assert result["points"]
    assert not any("重排" in gap for gap in result["gaps"])


def test_when_reformatting_also_fails_the_round_still_comes_back(monkeypatch):
    """重排也没救回来时，**不要只抛个异常了事**。

    抛出去的结果是任务失败、存档里什么都不剩，使用者连"它查了哪几张表"都看不到。
    这一轮的钱已经花了，至少要把查过的表和账单留下。
    """
    from stock_decision import devils_advocate as da

    monkeypatch.setattr(da.llm, "call", lambda *a, **k: type("C", (), {"text": "还是坏的"})())
    result = _run(monkeypatch, [_use("financials", "t1"), _text(_BROKEN)],
                  runner=lambda name, args: {"rows": [{"a": 1}]})
    assert result["points"] == []
    assert result["tool_calls"], "查过哪几张表必须留下来"
    # 断言的是**必须说到的意思**，不是原话：这一轮查完了、但没有结论，
    # 而且原因是格式而不是被截断（那是另一条路，见 test_json_reformat.py）。
    assert any("没有结论" in gap for gap in result["gaps"])
    assert "格式" in result["note"] and "截断" not in result["note"]


def test_a_round_that_produced_nothing_does_not_look_like_a_clean_bill(monkeypatch):
    """「没挑出毛病」和「这一轮没跑通」不能在存档上长成一个样。

    前者是查完之后真的没找到问题，后者是根本没跑通。混成一种的话，
    使用者会把后者读成"这家公司查过了、没问题"——而那正是这个产品最该避免的误读。
    """
    from stock_decision import devils_advocate as da

    monkeypatch.setattr(da.llm, "call", lambda *a, **k: type("C", (), {"text": "还是坏的"})())
    broken = _run(monkeypatch, [_text(_BROKEN)])
    exhausted = _run(monkeypatch, [_use("financials", "t1")] * (da.MAX_ROUNDS + 2))
    clean = _run(monkeypatch, [_final({"points": [], "not_challenged": "都还稳", "gaps": []})])

    assert broken.get("note") and exhausted.get("note")
    assert broken["note"] != exhausted["note"]
    # 真的没挑出毛病时不带 note —— 那一条交给调用方按主张条数拼。
    assert not clean.get("note")
