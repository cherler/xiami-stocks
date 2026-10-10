"""决策闭环：守卫必须真的挡得住，而且挡住的理由要说得出来。

一套永远拦不住任何人的守卫，跟没有守卫在页面上长得一模一样。
所以这里每条都**先拿会被挡的数据跑一遍**，确认它红；再拿该过的跑一遍。
"""

from __future__ import annotations

import pytest

from stock_decision import decision_loop as loop


ALL_GOOD = {key: True for key in loop.GUARDS}
NOTHING = {key: False for key in loop.GUARDS}


# ── 状态图本身 ──────────────────────────────────────────────────────────────


def test_每一条边的两端都是真实存在的状态():
    """**白名单漏登记的后果要是"走不过去"，不是"随便走"。**

    所以这里顺带确认边表里没有拼错的状态名——拼错的话那条边会静悄悄地
    永远走不通，而页面上只是少一个选项。
    """
    for state, targets in loop.TRANSITIONS.items():
        assert state in loop.STATES, state
        for target, guards in targets.items():
            assert target in loop.STATES, (state, target)
            for guard in guards:
                assert guard in loop.GUARDS, (state, target, guard)


def test_每个状态都排进了首页的顺序里():
    assert set(loop.STATE_ORDER) == set(loop.STATES)


def test_每个状态都走得出去():
    """走得进去却走不出去的状态是个陷阱：那只票会永远卡在那一格。"""
    for state in loop.STATES:
        assert loop.allowed_targets(state), f"{state} 是个死胡同"


# ── 被禁的那条边 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", ["discovered", "researching"])
def test_没做完研究就不许定买点(state):
    """产品原则四：没有完成研究和估值之前，系统不应允许给出正式买点。

    **哪怕守卫全绿也不许走。** 这条不是"条件没满足"，是这条边不存在——
    价格带填得再漂亮，它也不该从「待研究」直接跳到「等待价格」。
    """
    verdict = loop.check(state, "waiting", ALL_GOOD)
    assert verdict["ok"] is False
    assert "估值" in verdict["reason"] or "研究" in verdict["reason"]
    assert verdict["missing"] == [], "这是条不存在的边，不是缺东西"


def test_价格到了不能直接变成持仓():
    """价格触发之后必须过一次「触发检查」。跳过它等于把"价格到了"当成"可以买了"。"""
    verdict = loop.check("waiting", "holding", ALL_GOOD)
    assert verdict["ok"] is False
    assert "触发检查" in verdict["reason"]


def test_走不通的边要说出理由而不是只说不允许():
    """一个灰掉的按钮读起来像 bug；一句理由读起来是原则。"""
    for (state, target) in loop.FORBIDDEN_REASONS:
        reason = loop.why_forbidden(state, target)
        assert len(reason) > 20, (state, target, reason)
        assert loop.transition_requirements(state, target) is None, \
            f"{state}→{target} 既登记了禁令又开着边"


def test_禁边和账本专属边是两回事():
    """**「人工走不通」和「这条边不存在」不一样。**

    `waiting→holding` 人工点不动（必须先过触发检查），但账本推得动
    （你真买了，系统就得承认）。第一版把它塞进了 FORBIDDEN_REASONS，
    于是"禁令表里的边一定不存在"这条不变量被破坏——而那条不变量正是
    防止某条边被两处各管一半的。
    """
    for edge in loop.LEDGER_ONLY:
        state, target = edge
        assert loop.transition_requirements(state, target) is not None, \
            f"{state}→{target} 登记成账本专属，边却不存在"
        assert edge not in loop.FORBIDDEN_REASONS, \
            f"{state}→{target} 同时在禁令表和账本专属表里"
        human = loop.check(state, target, ALL_GOOD, actor="人工")
        assert human["ok"] is False, "人工不该点得动账本专属的边"
        ledger = loop.check(state, target, ALL_GOOD, actor="账本")
        assert ledger["ok"] is True, "账本该推得动"


def test_账本专属的边也要说清为什么人工点不动():
    for edge in loop.LEDGER_ONLY:
        reason = loop.check(edge[0], edge[1], ALL_GOOD, actor="人工")["reason"]
        assert "账本里的流水决定" in reason, (edge, reason)


# ── 守卫 ────────────────────────────────────────────────────────────────────


def test_缺什么就报什么而不是笼统说条件不满足():
    verdict = loop.check("researching", "valued", {**NOTHING, "thesis": True})
    assert verdict["ok"] is False
    keys = {item["key"] for item in verdict["missing"]}
    assert keys == {"counter_condition", "valuation"}
    for item in verdict["missing"]:
        assert item["fix"], "每一条缺口都要给一句「去哪补」"


def test_守卫齐了就放行():
    assert loop.check("researching", "valued", ALL_GOOD)["ok"] is True
    assert loop.check("valued", "waiting", ALL_GOOD)["ok"] is True
    assert loop.check("triggered", "committed", ALL_GOOD)["ok"] is True
    # `triggered → holding` 从 2026-09-22 起是**账本专属**的边：
    # 「已经持仓」由流水说，人工点不动（见 test_禁边和账本专属边是两回事）。
    assert loop.check("triggered", "holding", ALL_GOOD, actor="账本")["ok"] is True


def test_还有持股时不许退回等待():
    facts = {**ALL_GOOD, "position": True, "no_position": False}
    verdict = loop.check("reviewing", "waiting", facts)
    assert verdict["ok"] is False
    assert any(item["key"] == "no_position" for item in verdict["missing"])


# ── 价格带 ──────────────────────────────────────────────────────────────────

GOOD_BANDS = {"watch": 310.0, "fair": 295.0, "ideal": 280.0, "extreme": 270.0}


def test_乱序的价格带要被拦下():
    """**这条判据第一版是反的**：校验函数里两个循环写岔了，

    结果是坏数据返回空串（通过），好数据也返回空串（通过）——
    也就是这道校验对任何输入都放行，而页面上完全看不出来。
    所以这里必须拿真的会交叠的数据跑一遍，确认它红。
    """
    problem = loop.validate_bands({"watch": 280.0, "fair": 295.0,
                                   "ideal": 300.0, "extreme": 270.0})
    assert problem, "乱序的价格带被放过去了"
    assert "观察区" in problem and "合理区" in problem


def test_两段相等也要被拦下():
    """相等一样会让同一个价命中两段。"""
    assert loop.validate_bands({**GOOD_BANDS, "fair": 310.0})


def test_正常的价格带通过():
    assert loop.validate_bands(GOOD_BANDS) == ""


def test_一段都不填是允许的但填一半不行():
    """**半张价格带在页面上跟整张长得一样**，却会在触发时漏掉一整段。"""
    assert loop.validate_bands({}) == ""
    problem = loop.validate_bands({"watch": 310.0})
    assert problem and "四段填全" in problem


def test_命中的是最低的那一段():
    assert loop.band_of(265, GOOD_BANDS) == "extreme"
    assert loop.band_of(275, GOOD_BANDS) == "ideal"
    assert loop.band_of(290, GOOD_BANDS) == "fair"
    assert loop.band_of(305, GOOD_BANDS) == "watch"


def test_高于观察区下沿不算进任何一段():
    """**这不叫错过，这叫在等。** 返回 None 而不是"最上面那一段"。"""
    assert loop.band_of(320, GOOD_BANDS) is None
    assert loop.band_of(None, GOOD_BANDS) is None
    assert loop.band_of(100, {}) is None


def test_边界上的价算进那一段():
    assert loop.band_of(310, GOOD_BANDS) == "watch"
    assert loop.band_of(270, GOOD_BANDS) == "extreme"


def test_极端机会区的提示必须说强制重新检查():
    """跌到明显低估区的原因，往往正是让它不再值这个价的原因。"""
    note = loop.trigger_note("extreme", 268.0)
    assert "强制重新检查" in note
    assert "买入信号" in loop.trigger_note("ideal", 275.0)


# ── 仓位计划 ────────────────────────────────────────────────────────────────


def test_三笔加仓不能超过计划总仓位():
    problem = loop.validate_plan({"total_percent": 20, "first_percent": 10,
                                  "second_percent": 10, "third_percent": 10})
    assert problem and "20" in problem


def test_填了一部分就要把必填的补齐():
    problem = loop.validate_plan({"second_percent": 6})
    assert problem and "计划总仓位" in problem


def test_一个字都不填是允许的():
    assert loop.validate_plan({}) == ""
    assert loop.validate_plan(None) == ""


def test_总仓位要在零到一百之间():
    assert loop.validate_plan({"total_percent": 140, "first_percent": 10})
    assert loop.validate_plan({"total_percent": 20, "first_percent": 6}) == ""


def test_只有必填项齐了才算计划完成():
    assert loop.plan_complete({"total_percent": 20, "first_percent": 6}) is True
    assert loop.plan_complete({"total_percent": 20}) is False
    assert loop.plan_complete({}) is False


# ── 待成交：决定买了但还没成交 ──────────────────────────────────────────────


def test_决定买了和已经买了是两格():
    """**「计划建仓，尚未成交」原来在状态机里无处安放。**

    使用者写完首次建仓决策日志时，状态是「决定买 1/3、等成交」——
    而当时只有「触发检查」和「持仓中」两格：前者假装还在检查，
    后者是假的。中间这一格丢了之后，成交回来时就分不清
    「计划 300 成交 302」和「临时起意在 302 买的」。
    """
    assert "committed" in loop.STATES
    assert loop.STATES["committed"]["label"] == "待成交"
    assert "committed" in loop.STATE_ORDER
    assert "committed" in loop.ACTIONABLE_STATES


def test_进待成交要先写下这一笔买什么价买多少():
    """不写死数字的话，成交之后没法判断你是不是按计划做的。"""
    verdict = loop.check("triggered", "committed", {**ALL_GOOD, "order_plan": False})
    assert verdict["ok"] is False
    assert any(m["key"] == "order_plan" for m in verdict["missing"])
    assert loop.check("triggered", "committed", ALL_GOOD)["ok"] is True


def test_待成交里成交的买入算计划内():
    """「我决定在 300 附近买 1/3」写下来之后成交的那一笔，正是计划内的定义。"""
    assert "committed" in loop.IN_PLAN_STATES
    assert "triggered" in loop.IN_PLAN_STATES
    assert "holding" in loop.IN_PLAN_STATES
    assert "waiting" not in loop.IN_PLAN_STATES, "还在等价格就成交，那是计划外"


def test_待成交退得回去而且留痕():
    """**一次「我决定买了、后来没买」是复盘时很值钱的记录**：

    它要么说明你守住了纪律，要么说明你当时就没想清楚。
    """
    for target in ("waiting", "triggered", "researching"):
        assert loop.check("committed", target, ALL_GOOD)["ok"] is True, target


def test_待成交也不能自己宣布成持仓():
    assert ("committed", "holding") in loop.LEDGER_ONLY
    assert loop.check("committed", "holding", ALL_GOOD)["ok"] is False
    assert loop.check("committed", "holding", ALL_GOOD, actor="账本")["ok"] is True


def test_下单计划的校验():
    assert loop.validate_order({}) == ""
    assert loop.validate_order({"price": 300, "fraction": "1/3"}) == ""
    assert "大于 0" in loop.validate_order({"price": -1, "fraction": "1/3"})
    assert "几分之几" in loop.validate_order({"price": 300})
    assert loop.order_complete({"price": 300, "fraction": "1/3"}) is True
    assert loop.order_complete({"price": 300}) is False


def test_下一步按实际缺口算不是写死的一句话():
    """**写死的会让人去做已经做完的事。**

    宁德那张卡上投资逻辑和反证条件都写了、只缺估值，而「下一步」照旧写着
    「写下投资逻辑、反证条件，并完成一次估值」—— 读者会以为自己什么都没做。
    """
    done = {**NOTHING, "thesis": True, "counter_condition": True}
    step = loop.next_step("researching", done)
    assert "做过一次估值" in step
    assert "有一条投资逻辑" not in step, step
    assert loop.next_step("researching", ALL_GOOD).startswith("该走的都齐了")


def test_每一格都有一条往前的主线():
    for state in loop.STATES:
        assert state in loop.FORWARD, f"{state} 没有「下一步」走向哪里"
        assert loop.FORWARD[state] in loop.STATES


# ── 价格带存的是「上沿」，显示和判定必须说同一件事 ──────────────────────────


def test_存的是上沿跌到这个价才算进这一段():
    """**这里原来差了一格。**

    文案写着「记的是每一段的下沿」，而 `band_of` 一直按上沿判。
    页面上的表现是：梯子写着「观察区 = 310 以上」，而现价 305 被判进观察区
    —— 页面自己跟自己说的不一样，是对着截图逐行念才发现的。

    以 310/300/280/270 为例，判定必须是：
        >310 没进任何一段 ｜ (300,310] 观察区 ｜ (280,300] 合理区
        ｜ (270,280] 理想区 ｜ ≤270 极端机会区
    """
    # **用这一节自己的价格带**，不要借 GOOD_BANDS（它的合理区上沿是 295）——
    # 借错常量之后失败信息会指向 band_of，而错的是测试。
    bands = {"watch": 310.0, "fair": 300.0, "ideal": 280.0, "extreme": 270.0}
    expected = [
        (320, None), (310.01, None),
        (310, "watch"), (305, "watch"), (300.01, "watch"),
        (300, "fair"), (290, "fair"), (280.01, "fair"),
        (280, "ideal"), (275, "ideal"), (270.01, "ideal"),
        (270, "extreme"), (265, "extreme"), (1, "extreme"),
    ]
    for price, want in expected:
        assert loop.band_of(price, bands) == want, f"{price} 应当落在 {want}"


# 允许出现「下沿」的地方，每一条都要有理由。**新增一条就要在这里说明为什么。**
#
# 不写成"扫两个函数"是因为那正是上一版漏掉的原因：它只看 band_of 和
# validate_bands，而 2026-09-23 复查时，建表注释、纪律判定的文档字符串、
# 以及**页面上那句给用户看的提示**里都还写着「下沿」——
# 其中 DecisionLoop.tsx 那句是真的显示在屏幕上的。
# 判据只覆盖了出问题的那两处，没覆盖这个说法会出现的所有地方。
BANDS_WORDING_ALLOWED = {
    # 说明这个 bug 历史的注释，本来就要引用错误说法。
    "apps/api/stock_decision/decision_loop.py": ["**这里原来写成「下沿」"],
    "apps/web/src/components/DecisionLoop.tsx": ["第一版按下沿渲染"],
    # 估值区间的下沿是另一回事：那是"这家公司值多少"的区间，不是价格带。
    "apps/api/stock_decision/methods.py": ["只在市价明显低于区间下沿时买入", "低于下沿【幅度】"],
    # bands.py 在说明安全边际是哪来的时候，原样引了 methods.py 上面那一句。
    # **是引文，不是这里自己的说法**——所以连引号一起放进白名单，
    # 只放这一句，改了一个字就会重新报出来。
    "apps/api/stock_decision/bands.py": ["「只在市价明显低于区间下沿时买入，差额就是安全边际」"],
}


def test_文案里不许再出现下沿这个说法():
    """**差一格的病是从措辞开始的。** 判定按上沿，文案写下沿，
    于是显示层照着文案渲染，跟判定错开一整格。

    扫**整个产品源码**，不只扫那两个函数——见 BANDS_WORDING_ALLOWED 上面那段。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2].parent
    roots = [root / "apps" / "api" / "stock_decision", root / "apps" / "web" / "src"]
    offenders = []
    for base in roots:
        for path in sorted(base.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx"} or not path.is_file():
                continue
            key = str(path.relative_to(root))
            allowed = BANDS_WORDING_ALLOWED.get(key, [])
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "下沿" not in line:
                    continue
                if any(snippet in line for snippet in allowed):
                    continue
                offenders.append(f"{key}:{number}: {line.strip()}")

    assert not offenders, (
        "这些地方还写着「下沿」，而判定按上沿：\n" + "\n".join(offenders)
        + "\n改成「上沿」，或者确实是另一个意思就加进 BANDS_WORDING_ALLOWED 并写明理由。")


def test_下沿判据自己能失败():
    """**零容忍的判据最容易变成什么都没测。**

    上一版扫两个函数、全绿，而三处真的写错的地方它一个都看不见。
    所以这里钉住扫描范围本身：真去数一遍它读了多少个文件、
    并且确认它会对一行新写的「下沿」报警。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2].parent
    scanned = [
        path for base in (root / "apps" / "api" / "stock_decision", root / "apps" / "web" / "src")
        for path in base.rglob("*") if path.suffix in {".py", ".ts", ".tsx"} and path.is_file()
    ]
    # 分母会动就单独钉一条：文件数跌到个位数说明扫描范围塌了，而判据仍然全绿。
    assert len(scanned) > 60, f"扫描范围塌了，只读到 {len(scanned)} 个文件"
    assert any(p.name == "decision_loop.py" for p in scanned)
    assert any(p.name == "DecisionLoop.tsx" for p in scanned)
    assert any(p.name == "database.py" for p in scanned)   # 上一版漏掉的建表注释

    # 拿一行真的写错的文本自检：判据必须认得出它。
    bad = '        <PanelTitle hint="价格带记的是每一段的下沿，从高到低">'
    assert "下沿" in bad and not any(
        snippet in bad
        for snippets in BANDS_WORDING_ALLOWED.values() for snippet in snippets)


def test_最低那一段没有底():
    """极端机会区是「及以下」，不是一个区间 —— 跌到零它仍然在这一段里。
    页面上如果把它画成 270–280，那 265 就没有归属了。"""
    assert loop.band_of(0.01, GOOD_BANDS) == "extreme"
    assert loop.band_of(GOOD_BANDS["extreme"], GOOD_BANDS) == "extreme"
