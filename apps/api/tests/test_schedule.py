"""甘特图：承诺与解禁排到同一根轴上。

## 这个文件守的三件事

1. **没有终点的不许编一个。** 11 条承诺里只有 2 条有到期日，其余的期限写在原文里
   但是相对的（「自股东会审议通过之日起 12 个月内」）。给它们造一个终点，
   就是在图上凭空画一段时间。
2. **砍掉的要报数。** 格力的解禁能追到 2007 年，全画上横轴就是二十年，
   未来那两批挤成一条缝。所以只画近两年 —— 但少画了几条必须说出来，
   否则看起来就像这家公司历史上没解禁过几次。
3. **画不出来的泳道要写出来。** 募投进度库里根本没有数据。悄悄少一条，
   看的人会以为这家公司没有募投项目。
"""

from stock_decision import schedule as sc

TODAY = "2026-08-16"

PROMISES = [
    {"subject": "公司", "statement": "回购资金总额不低于 50 亿元", "category": "回购",
     "status": "待到期", "promised_on": "2026-06-30", "due_date": "2027-06-30"},
    {"subject": "公司", "statement": "现金分红比例不低于净利润的 50%", "category": "分红",
     "status": "待到期", "promised_on": "2025-06-18", "due_date": "2026-04-30"},
    # 金额上限：**没有期限，不该上轴**
    {"subject": "公司", "statement": "使用不超过 390 亿元闲置资金理财", "category": "其他",
     "status": "待到期", "promised_on": "2026-04-29", "due_date": None},
    {"subject": "公司", "statement": "很久以前说过、也早就了结了的一件事", "category": "其他",
     "status": "已兑现", "promised_on": "2018-01-01", "due_date": "2019-01-01"},
]
LOCKUPS = [
    {"event_date": "2026-10-23", "title": "第 8 批",
     "detail": "解禁 333.49 万股 · 解禁市值约 41.42 亿元 · 公告于 2025-10-21"},
    {"event_date": "2009-05-25", "title": "第 1 批",
     "detail": "解禁 100.00 万股 · 公告于 2008-05-20"},
]


def _lane(view, key):
    return next(lane for lane in view["lanes"] if lane["key"] == key)


def test_a_promise_with_no_term_at_all_stays_off_the_axis():
    """**没有期限的承诺在时间轴上没有位置。**

    第一版把它们画成说出口那天的一个点，而格力那 11 条里 6 条是同一份年报抽出来的
    金额上限（「回购不低于 50 亿」「不低于 70% 用于注销」）—— 公告日当然相同，
    于是**九个一模一样的点挤在同一条竖线上**。使用者：「这个图目前没有意义」。
    """
    view = sc.build(PROMISES, [], TODAY)
    titles = [bar["title"] for bar in _lane(view, "承诺")["items"]]
    assert not any("390 亿" in t for t in titles), "金额上限不是一段时间，不该上轴"
    assert any("50 亿" in t for t in titles), "有到期日的那条要在"


def test_how_many_stayed_off_the_axis_is_said_out_loud():
    """它们不消失，只是回台账去 —— 报数，并说清是哪一类。"""
    note = _lane(sc.build(PROMISES, [], TODAY), "承诺")["note"]
    assert "1 条没有期限" in note and "金额上限或比例约束" in note, note


def test_a_relative_term_becomes_a_date_and_says_it_is_a_guess():
    """「自股东会审议通过之日起 12 个月内」—— 期限写了，只是起点是股东会那天，
    而库里没有那个日期。按公告日推的终点会偏几周，**所以一律标成估算**。

    偏一点的日期仍然回答得了「这条承诺和那批解禁会不会撞上」，一个点回答不了。
    """
    row = [{"subject": "公司", "statement": "本次回购的期限为自股东会审议通过之日起12个月内",
            "category": "回购", "status": "待到期",
            "promised_on": "2026-04-29", "due_date": None}]
    bar = _lane(sc.build(row, [], TODAY), "承诺")["items"][0]
    assert bar["estimated"] is True and bar["end"] == "2027-04-29"
    assert "估算" in bar["detail"]
    assert "**1 条**的期限在原话里是相对的" in _lane(sc.build(row, [], TODAY), "承诺")["note"]


def test_a_year_in_a_sentence_is_not_a_term():
    """**「考核年度」「2026 年度」里的年不是期限。** 少了这道关，
    `(\d+)年` 会推出一个两千多年长的承诺 —— 而它在图上只是一根很长的条，
    没有任何东西会响。"""
    assert sc.term_end("考核年度净资产收益率超过 18%，当年现金分红不低于净利润的 50%",
                       "2026-04-29") is None
    assert sc.term_end("公司拟使用总额不超过人民币390亿元自有闲置资金开展投资理财",
                       "2026-04-29") is None
    assert sc.term_end("公司所开展的所有大宗材料套期保值业务期限不超过1年",
                       "2026-04-29") == ("2027-04-29", True)


def test_what_got_cut_by_the_window_is_counted_not_hidden():
    """**格力的解禁能追到 2007 年。** 全画上横轴就是二十年，未来那两批挤成一条缝。
    所以只画近两年 —— 而少画了几条要报数，否则看起来就像这家公司没解禁过几次。"""
    view = sc.build(PROMISES, LOCKUPS, TODAY)
    lockups = _lane(view, "解禁")
    assert len(lockups["items"]) == 1, "2009 年那批不该画进来"
    assert "另有 **1 批**是两年以前的" in lockups["note"], lockups["note"]

    promises = _lane(view, "承诺")
    assert len(promises["items"]) == 2, "2018 年那条不该画进来（另一条是没期限的，本来就不上轴）"
    assert "还有 **1 条**在两年以前就结束了" in promises["note"], promises["note"]


def test_the_window_never_swallows_something_still_running():
    """起点在窗口以外、但**还没结束**的那些必须留下 —— 一条 2024 年说出口、
    2027 年才到期的承诺，正是这张图最该显示的东西。"""
    long_one = [{"subject": "公司", "statement": "一条横跨窗口的承诺", "category": "回购",
                 "status": "待到期", "promised_on": "2020-01-01", "due_date": "2027-12-31"}]
    view = sc.build(long_one, [], TODAY)
    assert len(_lane(view, "承诺")["items"]) == 1
    assert view["start"] == "2020-01-01", "横轴要退到能装下它的位置，不是把它截断"


def test_the_lockup_bar_is_the_lockup_period():
    """解禁的区间是**公告日 → 解禁日**，那就是这批股份还锁着的那段时间。
    股数与市值从 detail 里抠出来，抠不到就留空，不猜。"""
    bar = _lane(sc.build([], LOCKUPS, TODAY), "解禁")["items"][0]
    assert bar["start"] == "2025-10-21" and bar["end"] == "2026-10-23"
    assert "333.49 万股" in bar["detail"] and "41.42 亿元" in bar["detail"]
    assert bar["state"] == "未解禁"


def test_a_lockup_without_an_announcement_date_is_a_point():
    """抠不到公告日时退回解禁日 —— 画成一个点，而不是一段编出来的锁定期。"""
    bar = _lane(sc.build([], [{"event_date": "2026-12-01", "title": "某批",
                               "detail": "解禁 10.00 万股"}], TODAY), "解禁")["items"][0]
    assert bar["point"] is True and bar["start"] == bar["end"] == "2026-12-01"


def test_the_fundraising_lane_comes_from_a_document_that_was_read():
    """**第一条「读文档的结果喂给另一个功能」的链子。**

    募投这条泳道原来在 NO_DATA 里（"库里没有这项数据"）—— 那句话对（没有表），
    但公告里有：「募集资金存放、管理与实际使用情况的专项报告」里是一张结构化的表。
    实测寒武纪那份 21 页的报告，两次发行五个项目全在，读一次 2 分钱。
    """
    funds = [
        {"batch": "2025 年度向特定对象发行股票", "project": "面向大模型的芯片平台项目",
         "committed": 205427.94, "invested": 15384.54, "progress": 7.49,
         "due_on": "2028-10", "settled": 0, "source_pages": [20], "created_at": "2026-08-08"},
        # 已结项的也要在：它是"承诺兑现了没有"的证据
        {"batch": "2022 年度向特定对象发行股票", "project": "先进工艺平台芯片项目",
         "committed": 69973.68, "invested": 69973.68, "progress": 100.0,
         "due_on": "2026-05", "settled": 1, "source_pages": [15], "created_at": "2026-08-08"},
    ]
    view = sc.build(PROMISES, LOCKUPS, TODAY, fundraising=funds)
    lane = _lane(view, "募投")
    assert [item["title"] for item in lane["items"]] == \
        ["先进工艺平台芯片项目", "面向大模型的芯片平台项目"] or len(lane["items"]) == 2
    bar = next(i for i in lane["items"] if "芯片平台项目" == i["title"][-6:] or "大模型" in i["title"])
    assert bar["end"].startswith("2028-10"), bar["end"]
    assert "进度 7.5%" in bar["detail"] and "承诺 20.5 亿" in bar["detail"]
    # **出处要能翻回去** —— 这是模型读出来的数，核不回原文就没资格进库
    assert "第 20 页" in bar["detail"]
    assert "第几页" in lane["note"]


def test_a_project_without_a_target_date_stays_off_the_axis():
    """跟没有期限的承诺同一条规矩：一个不知道什么时候该完成的项目，
    在时间轴上没有位置 —— **但它没上轴这件事要报出来。**"""
    funds = [{"batch": "x", "project": "没写完成日的项目", "committed": 1000.0,
              "invested": 10.0, "progress": 1.0, "due_on": None, "settled": 0,
              "source_pages": [9], "created_at": "2026-08-08"},
             {"batch": "x", "project": "写了的", "committed": 1000.0, "invested": 500.0,
              "progress": 50.0, "due_on": "2027-06", "settled": 0,
              "source_pages": [9], "created_at": "2026-08-08"}]
    lane = _lane(sc.build([], [], TODAY, fundraising=funds), "募投")
    assert [i["title"] for i in lane["items"]] == ["写了的"]
    assert "**1 项**没写明预定可使用状态日期" in lane["note"], lane["note"]


def test_nothing_to_schedule_says_what_to_do():
    """空的时候要说得出下一步点哪里 —— 只说"排不出来"，他不知道该干什么。"""
    view = sc.build([], [], TODAY)
    assert view["available"] is False
    assert "从公告里找承诺" in view["note"]


def test_the_repository_query_actually_runs(client, owned):  # noqa: F811
    """**上面全是纯函数，而线上会挂的是那条查询。** 本会话已经踩过一次
    （money-flow 的 SQL 里一个百分号 500 了线上），所以这里真的走一遍数据库。"""
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import company_schedule

    client.as_user(access.OWNER_SCOPE)
    company = owned["company"]
    with connection() as conn:
        conn.execute(
            """INSERT INTO management_promises (company_id, source_title, promised_on, subject,
                                                statement, category, due_date, status,
                                                created_at, updated_at)
               VALUES (?, '公告', '2026-06-30', '公司', '一条承诺', '回购', '2027-06-30',
                       '待到期', '2026-08-16', '2026-08-16')""", (company,))
        conn.execute(
            """INSERT INTO company_calendar_events (company_id, category, event_date, title,
                                                    detail, source, refreshed_at)
               VALUES (?, '解禁', '2026-10-23', '第 8 批',
                       '解禁 333.49 万股 · 解禁市值约 41.42 亿元 · 公告于 2025-10-21',
                       '测试', '2026-08-16')""", (company,))

    view = company_schedule(company)
    assert view is not None and view["available"] is True, view
    assert {lane["key"] for lane in view["lanes"]} == {"承诺", "解禁"}


def test_only_lockup_events_feed_the_lockup_lane(client, owned):  # noqa: F811
    """日历里还有「公告」和「分红」两类，**它们不是区间**，不该混进解禁那条泳道。"""
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import company_schedule

    client.as_user(access.OWNER_SCOPE)
    company = owned["company"]
    with connection() as conn:
        for category, title in (("解禁", "第 9 批"), ("公告", "某某进展公告"), ("分红", "10派5元")):
            conn.execute(
                """INSERT INTO company_calendar_events (company_id, category, event_date, title,
                                                        detail, source, refreshed_at)
                   VALUES (?, ?, '2026-11-01', ?, '公告于 2026-01-01', '测试', '2026-08-16')""",
                (company, category, title))

    view = company_schedule(company)
    titles = [item["title"] for lane in view["lanes"] if lane["key"] == "解禁"
              for item in lane["items"]]
    assert titles == ["第 9 批"], titles


from test_idor import client, owned  # noqa: E402,F401


def test_the_meeting_date_pins_a_relative_term_and_it_is_no_longer_a_guess():
    """**「自股东会审议通过之日起 12 个月」的起点，库里早就有。**

    日历里有 12 条「…股东会决议公告」。以前拿公告日凑 —— 格力那条回购
    公告于 2026-04-29、股东会 2026-07-01，**差了两个多月**。
    一次标题匹配就钉住了，不用模型、不花积分，而且能核对。
    """
    st = "本次回购的期限为自公司股东会审议通过本次回购方案之日起12个月内"
    assert sc.term_end(st, "2026-04-29") == ("2027-04-29", True), "没有决议公告时按公告日推，是估算"
    assert sc.term_end(st, "2026-04-29", ["2026-07-01"]) == ("2027-07-01", False), \
        "找到决议公告就用那天当起点，不再是估算"
    # 公告之前的那些股东会不算 —— 期限说的是"审议通过本次方案"那一次
    assert sc.term_end(st, "2026-04-29", ["2025-06-12", "2026-07-01"])[0] == "2027-07-01"


def test_twelve_months_is_a_year_not_360_days():
    """**「12 个月」按 30 天算是 360 天**，一年差五天、三年差半个月。
    这个偏差看不出来（就是一根稍短的条），但它会让「这条承诺和那批解禁差几天」
    这种判断错掉 —— 而那正是这张图存在的理由。"""
    assert sc.term_end("期限不超过12个月", "2026-04-29")[0] == "2027-04-29"
    assert sc.term_end("期限不超过3年", "2026-04-29")[0] == "2029-04-29"
    # 月末那天要落到目标月真实存在的最后一天上，不许溢出到下个月
    assert sc.term_end("期限不超过1个月", "2026-01-31")[0] == "2026-02-28"


def test_a_term_not_tied_to_a_meeting_still_uses_the_announcement_date():
    """「套期保值业务期限不超过 1 年」跟股东会没关系 —— 别把决议日期硬套上去。"""
    got = sc.term_end("公司所开展的所有大宗材料套期保值业务期限不超过1年",
                      "2026-04-29", ["2026-07-01"])
    assert got == ("2027-04-29", True)


def test_the_repository_actually_passes_meetings_and_fundraising(client, owned):  # noqa: F811
    """**接口没接上，而单元测试全绿。**

    `term_end` 和 `_fund_bar` 各自都测过，但 `company_schedule` 里那两个参数
    **一次都没传过** —— 两个功能上线之后一直是死的，
    而没有任何一层会响：泳道不出现跟"这家公司没有募投项目"长得一模一样。

    本会话第五次踩「守卫在它要守的那件事上是瞎的」。这一条走真的调用方。
    """
    from stock_decision import access
    from stock_decision.database import connection
    from stock_decision.repository import company_schedule, save_fundraising

    client.as_user(access.OWNER_SCOPE)
    company = owned["company"]
    with connection() as conn:
        # 一条相对期限的承诺 + 一次股东会决议：起点该用决议那天
        conn.execute(
            """INSERT INTO management_promises (company_id, source_title, promised_on, subject,
                                                statement, category, status, created_at, updated_at)
               VALUES (?, '公告', '2026-04-29', '公司',
                       '本次回购的期限为自公司股东会审议通过本次回购方案之日起12个月内',
                       '回购', '待到期', '2026-08-17', '2026-08-17')""", (company,))
        conn.execute(
            """INSERT INTO company_calendar_events (company_id, category, event_date, title,
                                                    detail, source, refreshed_at)
               VALUES (?, '公告', '2026-07-01', '2025年年度股东会决议公告', '', '测试', '2026-08-17')""",
            (company,))
    save_fundraising(company, None, [{"batch": "2025 年度发行", "project": "面向大模型的芯片平台项目",
                                   "committed_wan": 205427.94, "invested_wan": 15384.54,
                                   "progress_pct": 7.49, "due_on": "2028-10", "pages": [20]}])

    view = company_schedule(company)
    keys = {lane["key"] for lane in view["lanes"]}
    assert "募投" in keys, f"募投泳道没出现 —— fundraising 没传进去：{keys}"

    bar = next(item for lane in view["lanes"] if lane["key"] == "承诺"
               for item in lane["items"])
    assert bar["estimated"] is False, "meetings 没传进去 —— 还在按公告日凑，标成了估算"
    assert bar["end"] == "2027-07-01", f"起点不是股东会那天：{bar['end']}"
