"""假设漂移。

这是全项目**最容易被绕开**的一个功能：它的作用就是让人不舒服。
所以这里守的不只是算得对不对，还有两条同样要紧的：

- 它给的必须是**问题**不是判决。写成判决，判错时人会不再信它，
  判对时人会开始绕开它——一个你会绕开的诚实机制等于没有。
- 它必须**问得够少**。噪音级的改动也要问一句的话，这个机制会被整个关掉，
  那比不问更糟。
"""

import pytest

from stock_decision import drift


FACTS = {"base_revenue": 1_000_000_000.0, "shares": 100_000_000.0}


def _record(growth, margin, pe, price, at="2026-01-01T00:00:00", years=5, discount=10.0):
    return {"created_at": at, "price_at_write": price, "years": years,
            "discount_rate": discount,
            "scenarios": [{"key": "base", "revenue_growth": growth,
                           "net_margin": margin, "exit_pe": pe}]}


def _nothing_happened():
    return {"evidences": 0, "reports": 0, "material_events": 0}


def _things_happened():
    return {"evidences": 4, "reports": 1, "material_events": 2}


# ------------------------------------------------------------------ 比较

def test_only_the_assumptions_are_compared_not_the_base():
    """**新年报进来会让每股价值变，哪怕你一个字没改。**

    所以两次比较必须用同一套基数重算，差值里只剩你自己动的那部分。
    不做这一步的话，一份营收下滑的年报会被读成「你把假设调低了」——
    而你其实什么都没改，那是一句冤枉话，而且没有任何报错。
    """
    same = _record(8, 20, 15, 100)
    change = drift.compare(same, {**same, "created_at": "2026-04-01T00:00:00"}, FACTS)
    assert change["fields"] == [], "什么都没改就不该报出任何字段变化"
    assert change["assumption_shift"] == 0


def test_fields_report_what_actually_moved():
    before = _record(8, 20, 15, 100)
    after = _record(14, 20, 18, 123, at="2026-04-01T00:00:00")
    change = drift.compare(before, after, FACTS)
    moved = {f["key"]: f["change"] for f in change["fields"]}
    assert moved == {"revenue_growth": 6.0, "exit_pe": 3.0}, "净利率没动就不该出现"
    assert change["assumption_shift"] > 0 and change["price_shift"] == pytest.approx(23.0)


# ------------------------------------------------------------------ 那句话

def test_the_hard_question_only_fires_when_nothing_happened():
    """**这是整个功能的核心那一句。**

    光说「你改了假设」没有杀伤力，「这期间什么都没发生」才有。
    """
    before = _record(8, 20, 15, 100)
    after = _record(14, 20, 18, 130, at="2026-04-01T00:00:00")
    reading = drift.read(drift.compare(before, after, FACTS), _nothing_happened())

    assert reading["level"] == "ask"
    assert "什么都没发生" in reading["headline"]
    assert "还是股价变了之后在给它找理由" in reading["question"]


def test_it_softens_when_new_information_did_arrive():
    """调高假设可能完全正确。有新东西时就不该用同一句话质问。"""
    before = _record(8, 20, 15, 100)
    after = _record(14, 20, 18, 130, at="2026-04-01T00:00:00")
    reading = drift.read(drift.compare(before, after, FACTS), _things_happened())

    assert reading["level"] == "note"
    assert "说得通" in reading["question"]
    # 但仍然要留一个可回答的问题，不是放行
    assert "撑得起" in reading["question"]


def test_it_is_always_a_question_never_a_verdict():
    """写成判决的两个后果：判错时不再信它，判对时开始绕开它。

    所以这里禁掉那几个下判决的词。**一个你会绕开的诚实机制等于没有。**
    """
    before = _record(8, 20, 15, 100)
    after = _record(14, 20, 18, 130, at="2026-04-01T00:00:00")
    for context in (_nothing_happened(), _things_happened()):
        text = drift.read(drift.compare(before, after, FACTS), context)["question"]
        for verdict in ("你在追高", "你错了", "不该", "违反", "错误"):
            assert verdict not in text, f"这是判决不是问题：{verdict}"


def test_moving_against_the_price_is_called_out_as_good():
    """按事实调、不按价格调，是值得记一笔的事。

    只挑毛病的机制会让人只想躲开它。
    """
    before = _record(14, 20, 18, 130)
    after = _record(8, 20, 15, 160, at="2026-04-01T00:00:00")   # 价涨、假设降
    reading = drift.read(drift.compare(before, after, FACTS), _nothing_happened())
    assert reading["level"] == "good"
    assert "方向是反的" in reading["question"]


def test_noise_sized_edits_stay_quiet():
    """**问得太频繁的机制会被整个关掉**，那比不问更糟。"""
    before = _record(8.0, 20, 15, 100)
    after = _record(8.2, 20, 15, 101, at="2026-04-01T00:00:00")
    reading = drift.read(drift.compare(before, after, FACTS), _nothing_happened())
    assert reading["level"] == "quiet"


def test_no_edit_at_all_says_nothing():
    same = _record(8, 20, 15, 100)
    reading = drift.read(drift.compare(same, {**same, "created_at": "2026-04-01"}, FACTS),
                         _nothing_happened())
    assert reading["level"] == "none"
    assert reading["question"] == ""


# ------------------------------------------------------------------ 边角

def test_missing_price_does_not_crash_or_fake_a_zero():
    """当时的股价缺失时不能假装成 0——那会算出一个 -100% 的价格变化。

    仍然可以问「改的依据是什么」（那个问题不依赖价格），但**绝不能说
    「它跟着价格走」**——方向都不知道，那就是在编。
    """
    before = _record(8, 20, 15, None)
    after = _record(14, 20, 18, 130, at="2026-04-01T00:00:00")
    change = drift.compare(before, after, FACTS)
    assert change["price_shift"] is None
    assert change["followed_price"] is False
    assert change["against_price"] is False

    reading = drift.read(change, _nothing_happened())
    assert reading["level"] == "unexplained"
    assert "股价不详" in reading["question"]
    assert "跟着价格" not in reading["question"] and "方向一致" not in reading["question"]


def test_summary_counts_the_silent_ones():
    changes = [
        {"change": {"followed_price": True}, "reading": {"level": "ask"}},
        {"change": {"followed_price": True}, "reading": {"level": "note"}},
        {"change": {"followed_price": False}, "reading": {"level": "good"}},
    ]
    text = drift.summarize(changes)
    assert "改过 3 次" in text and "2 次跟股价同向" in text and "1 次同期没有任何新信息" in text
    assert drift.summarize([]) == ""


def test_a_big_edit_with_no_news_is_recorded_even_if_the_price_stood_still():
    """**这一档是被实跑补出来的。**

    第一版只查「假设跟着价格走」。于是同一天里把基准增速从 8% 改到 15%
    （股价一分没动、什么都没发生）被判成噪音，一声不吭——
    而那恰恰是最该留痕的一种：你改主意了，但说不出因为什么。

    注意它问的仍然不是"你错了"，而是"依据是什么"，并且明说
    「再想了想」也是一个可以接受的答案——只要写下来。
    """
    before = _record(8, 48, 28, 1309.22)
    after = _record(15, 49, 36, 1309.22, at="2026-04-01T00:00:00")   # 价格一分没动
    reading = drift.read(drift.compare(before, after, FACTS), _nothing_happened())

    assert reading["level"] == "unexplained"
    assert "没有任何新信息" in reading["headline"]
    assert "改的依据是什么" in reading["question"]
    assert "再想了想" in reading["question"], "要给一个人能诚实回答的出口"


def test_a_big_edit_backed_by_new_information_stays_quiet():
    """有新东西支撑的改动不该被追问——**只挑毛病的机制会让人只想躲开它**。"""
    before = _record(8, 48, 28, 1309.22)
    after = _record(15, 49, 36, 1309.22, at="2026-04-01T00:00:00")
    reading = drift.read(drift.compare(before, after, FACTS), _things_happened())
    assert reading["level"] == "quiet"
