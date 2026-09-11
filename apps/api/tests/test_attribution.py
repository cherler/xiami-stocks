"""决策归因：我写下的判断，后来怎么样了。

这一版**只报机械可验证的事实**，所以测试守的主要是"不许多说"：
样本不够时不许凑出洞察，「没动作」不许被写成「做错了」。

一份编出来的归因比没有归因更糟——**你会照着它改行为**，
而它可能只是三次巧合。
"""

import pytest

from stock_decision import attribution as at


def _thesis(tid=1, price=100.0, counter="连续两期营收下滑", claim="海外还能涨"):
    return {"id": tid, "company_id": tid, "company_name": f"公司{tid}", "symbol": f"60000{tid}",
            "claim": claim, "counter_condition": counter, "status": "watching",
            "created_at": "2026-01-01T00:00:00", "price_at_write": price}


def _hit(when="2026-03-01T00:00:00"):
    return {"created_at": when}


# ------------------------------------------------------------------ 单条

def test_the_three_states_are_kept_apart():
    """**触发过没有、触发后动没动，是三件不同的事。**

    合成一个"健康度"分数会把它们抹平，而它们对你意味着的事完全不同。
    """
    assert at.outcome(_thesis(), 120.0, [_hit()], acted=True)["state"] == "触发过，也动过"
    assert at.outcome(_thesis(), 120.0, [_hit()], acted=False)["state"] == "触发过，但一直没动"
    assert at.outcome(_thesis(), 120.0, [], acted=False)["state"] == "还没触发"
    assert at.outcome(_thesis(counter=""), 120.0, [], acted=False)["state"] == "没写认错条件"


def test_price_move_needs_a_starting_point():
    """没有写下时的价格，「后来涨了跌了」这句话没有起点——**给 None，不给 0**。"""
    assert at.outcome(_thesis(price=100.0), 120.0, [], False)["price_move"] == 20.0
    assert at.outcome(_thesis(price=None), 120.0, [], False)["price_move"] is None
    assert at.outcome(_thesis(price=100.0), None, [], False)["price_move"] is None


# ------------------------------------------------------------------ 汇总

def test_it_refuses_to_talk_about_patterns_without_enough_records():
    """**样本不够就明说不够——但要说成进度，不是说成一堵墙。**

    三条判断里两条错了说明不了任何事，而「67% 的失误率」这种说法会被当真，
    所以"不谈倾向"这条不能松。但原来那句「只有 3 条，谈不上规律」是死的：
    读完没有下文，也看不出还差多远。所以这里守的是**意图**不是措辞：
    不许下结论、要给进度、并且要点明门槛之下已经能看的东西。
    """
    rows = [at.outcome(_thesis(i), 110.0, [], False) for i in range(1, 4)]
    summary = at.summarize(rows)
    assert summary["enough"] is False
    assert summary["progress"] == {"have": 3, "need": at.MIN_FOR_PATTERN}
    assert str(at.MIN_FOR_PATTERN) in summary["note"]
    assert "不谈倾向" in summary["note"], "样本不够时不许谈倾向，这条不能松"
    # **门槛之下也要给东西**：逐条的事实一条样本都不需要
    assert "现在就能看" in summary["note"]


def test_the_threshold_is_a_progress_not_a_wall():
    """0 条时也要有进度——空状态最容易被写成一句"还没有"然后到此为止。"""
    summary = at.summarize([])
    assert summary["progress"] == {"have": 0, "need": at.MIN_FOR_PATTERN}
    assert str(at.MIN_FOR_PATTERN) in summary["note"]


def test_enough_records_stops_the_disclaimer():
    rows = [at.outcome(_thesis(i), 110.0, [], False) for i in range(1, at.MIN_FOR_PATTERN + 1)]
    summary = at.summarize(rows)
    assert summary["enough"] is True
    assert summary["note"] == ""


def test_the_silent_ones_are_counted_and_asked_about():
    """**这是这一页最重的一句。**

    「触发了但你什么都没做」——它不带判断，因为没做也可能完全正确
    （你重新想过，认为那条件写得太紧）。但它必须被数出来摆在面前，
    因为这正是人最容易骗自己的地方：当时想着"再看看"，然后就没有然后了。
    """
    rows = [
        at.outcome(_thesis(1), 90.0, [_hit()], acted=False),
        at.outcome(_thesis(2), 90.0, [_hit()], acted=False),
        at.outcome(_thesis(3), 90.0, [_hit()], acted=True),
        at.outcome(_thesis(4), 90.0, [], acted=False),
    ]
    summary = at.summarize(rows)
    assert summary["fired"] == 3
    assert summary["silent"] == 2
    assert "2 条触发之后没有任何动作" in summary["headline"]
    assert "再看看" in summary["question"]


def test_no_action_is_never_called_a_mistake():
    """跟假设漂移同一条规矩：**陈述事实、提出问题，不下判决。**

    写成判决的两个后果：判错时你不再信它，判对时你开始绕开它。
    """
    rows = [at.outcome(_thesis(i), 80.0, [_hit()], acted=False) for i in range(1, 4)]
    summary = at.summarize(rows)
    # 陈述与提问里一个判决词都不许有
    said = summary["headline"] + summary["question"]
    for verdict in ("你错了", "失误", "做错", "违反", "不该"):
        assert verdict not in said, f"这是判决不是事实：{verdict}"
    # 而边界里必须**明确说出**「没动不等于做错」——只是不提，人还是会自己脑补成指责
    assert "不等于做错了" in summary["boundary"]


def test_theses_without_a_falsifier_are_counted_separately():
    """没写认错条件的那些要单独数——它们根本没法被归因。"""
    rows = [at.outcome(_thesis(1, counter=""), 90.0, [], False),
            at.outcome(_thesis(2), 90.0, [], False)]
    summary = at.summarize(rows)
    assert summary["no_falsifier"] == 1
    assert "压根没写认错条件" in summary["headline"]


def test_an_empty_ledger_says_so_plainly():
    summary = at.summarize([])
    assert summary["total"] == 0
    assert "还没有可归因的判断" in summary["headline"]
    assert summary["enough"] is False


# ------------------------------------------------------------------ 走接口

def test_action_must_come_after_the_hit_not_before(monkeypatch):
    """触发之前改的那一次，跟这次命中没有关系。

    不分先后的话，一条你三个月前顺手改过措辞的逻辑，会被算成
    「触发之后你动过了」——而你其实什么都没做。
    """
    from fastapi.testclient import TestClient

    from stock_decision.database import connection, now_iso
    from stock_decision.main import app

    client = TestClient(app)
    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    thesis = client.post(f"/api/v1/companies/{company['id']}/theses", json={
        "claim": "定价权还在", "counter_condition": "连续两期营收下滑"}).json()

    with connection() as conn:
        # 先改一次（早于命中），再制造一次命中
        conn.execute("""INSERT INTO record_revisions (entity_type, entity_id, version, change_note, snapshot, created_at)
                        VALUES ('thesis', ?, 99, '改措辞', '{}', '2026-01-01T00:00:00')""", (thesis["id"],))
        conn.execute("""INSERT INTO company_calendar_events (company_id, category, event_date, title, source, refreshed_at)
                        VALUES (?, '公告', '2026-06-01', '营收下滑', 'test', ?)""",
                     (company["id"], now_iso()))
        event = conn.execute("SELECT id FROM company_calendar_events ORDER BY id DESC LIMIT 1").fetchone()["id"]
        conn.execute("""INSERT INTO counter_hits (user_id, event_id, thesis_id, clause, reason, created_at)
                        VALUES ('__owner__', ?, ?, '连续两期营收下滑', '命中', '2026-06-02T00:00:00')""",
                     (event, thesis["id"]))

    body = client.get("/api/v1/attribution").json()
    row = next(r for r in body["rows"] if r["thesis_id"] == thesis["id"])
    assert row["counter_fired"] == 1
    assert row["acted"] is False, "命中之前的那次修改不该算成「触发后动过」"
    assert row["state"] == "触发过，但一直没动"
    assert body["silent"] == 1


def test_the_sample_size_sentence_does_its_own_arithmetic():
    """**这句话里的数字要跟条数一起变。**

    原来写死的是「{total} 条里错了两条说明不了任何事，而「50% 的失误率」…」，
    而 2026-08-16 线上只有 1 条判断，于是它印出来是：

        「1 条里错了两条说明不了任何事，而「50% 的失误率」…」

    一条里错两条、由此得出的 50% —— 两个数都不成立。而这一页的全部纪律就是
    「只报机械可验证的事实」「不要凑出一段看起来有洞察的话」；
    在这上面印一句算不通的话，比不印更伤。
    """
    def note(count):
        rows = [{"counter_fired": 0, "acted": False, "counter_condition": "x",
                 "price_move": None}] * count
        return at.summarize(rows)["note"]

    assert "100%" in note(1) and "两条" not in note(1)
    assert "50%" in note(2)
    assert "33%" in note(3)
    # 够样本了就不再说这句
    assert note(at.MIN_FOR_PATTERN) == ""
