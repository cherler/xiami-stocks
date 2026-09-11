"""公告正文：把十四个字的标题换成公告本身。

承诺台账在 12 家公司上抽出 0 条，原因不是抽取标准太严——是我们只给了模型
十四个字。格力那条《关于股份回购进展情况的公告》，「不低于 50 亿元」
「不超过 12 个月」「不低于 70% 用于注销」四条承诺全在正文里，一条都不在标题里。

这里守四件事：
- **PDF 地址从库里已有的链接推出来**，不发多余的请求（announcementTime 带时分秒是真踩过的坑）。
- **声明类公告整类挡掉**，否则台账会被任职套话灌满，而灌满之后就再也没人看它了。
- **抓过的不再抓第二次，取不到的也记**——不记的话已撤下的公告每次都会重试。
- **超预算就分批，绝不静默截断**：被截掉的公告不会报错、不会留痕，
  只会表现为"这家公司没有承诺"，跟真的没有承诺长得一模一样。
"""

from __future__ import annotations

import pytest

from stock_decision import disclosure as dc
from stock_decision import promises as pm

_DETAIL = ("http://www.cninfo.com.cn/new/disclosure/detail"
           "?stockCode=000651&announcementId=1225455000&announcementTime=")


def _event(index=1, title="关于股份回购进展情况的公告", when="2026-08-04", ident=1225455000):
    return {"id": 100 + index, "category": "公告", "event_date": when, "title": title,
            "url": ("http://www.cninfo.com.cn/new/disclosure/detail"
                    f"?stockCode=000651&announcementId={ident}&announcementTime={when}")}


# --------------------------------------------------------------- 地址推导

def test_pdf_url_derives_from_stored_link():
    """库里已有的详情页链接就够了，不需要再调查询接口。"""
    assert dc.pdf_url(_DETAIL + "2026-08-04") == (
        "http://static.cninfo.com.cn/finalpage/2026-08-04/1225455000.PDF")


def test_announcement_time_with_clock_is_truncated_to_the_day():
    """**这是踩过的坑。** announcementTime 有时是 '2026-08-07 20:16:09'，

    原样拼进 URL 会抛 InvalidURL（空格是控制字符），而当时的表现是
    三条公告"下载失败"、看起来像巨潮限流。
    """
    url = dc.pdf_url(_DETAIL + "2026-08-07 20:16:09")
    assert url == "http://static.cninfo.com.cn/finalpage/2026-08-07/1225455000.PDF"
    assert " " not in url


@pytest.mark.parametrize("url", [
    None, "", "https://finance.sina.com.cn/whatever",
    "http://www.cninfo.com.cn/new/disclosure/detail?announcementId=abc&announcementTime=2026-08-04",
    _DETAIL + "不是日期",
])
def test_unusable_links_yield_empty_not_a_broken_url(url):
    """拼不出来就返回空串，不要返回一个必然 404 的地址。"""
    assert dc.pdf_url(url) == ""


# --------------------------------------------------------------- 噪音过滤

def test_independent_director_declaration_is_excluded():
    """万科那条命中的《独立董事候选人声明与承诺》，五条全是任职套话。

    危险不在于它错，在于**它会把台账灌满，而灌满之后你就再也不看它了**。
    """
    assert dc.skipped("独立董事候选人声明与承诺")
    assert dc.skipped("北京市金杜律师事务所关于本次交易的法律意见书")
    assert dc.skipped("董事会审计委员会工作细则")


def test_real_promise_announcements_are_not_excluded():
    """排除名单写得窄——误伤掉的是真承诺，而真承诺是这个功能的全部产出。"""
    for title in ("关于股份回购进展情况的公告", "关于控股股东增持公司股份计划的公告",
                  "2026年半年度利润分配预案的公告", "关于回购股份注销完成的公告",
                  "2026年员工持股计划（草案）"):
        assert not dc.skipped(title), title


def test_management_measures_are_demoted_not_excluded():
    """《员工持股计划管理办法》长得像模板文件，但里面有锁定期和解锁业绩条件。

    排除掉就永久丢了这一类，所以只降权：排最后去读，预算够还是读。
    """
    assert not dc.skipped("2026年员工持股计划管理办法")
    # 只差这个后缀的两条，带后缀的排在后面——但两条都在，都会被读。
    events = [_event(1, "2026年员工持股计划管理办法", ident=1),
              _event(2, "2026年员工持股计划（草案）", ident=2)]
    assert [e["title"] for e in dc.readable(events)] == [
        "2026年员工持股计划（草案）", "2026年员工持股计划管理办法"]


def test_dividend_policy_documents_survive_the_template_filter():
    """《利润分配管理制度》长得跟《投资者关系管理制度》一样像模板，

    但它里面写着「每年现金分红不少于当年可分配利润的百分之多少」——
    带数字、能被证伪、年年都要核，**可能是最该进台账的一类**。
    实测全库 1587 条公告时误伤到它，这一行是给它开的口子。
    """
    assert not dc.skipped("利润分配管理制度（2025年8月）")
    assert not dc.skipped("分红管理制度")
    # 口子只给分红这一类，其余"管理制度"照挡
    assert dc.skipped("投资者关系管理制度")
    assert dc.skipped("董事、高级管理人员薪酬管理制度")


def test_third_party_opinions_are_always_excluded():
    """第三方出具的文件是**对某件事的见证，不是承诺本身**。

    承诺在《股权激励计划（草案）》里，律所那份意见书里只有"符合规定"。
    所以它不吃分红那个口子——否则《…关于利润分配的法律意见书》会漏进来。
    """
    assert dc.skipped("北京市嘉源律师事务所关于股权激励计划的法律意见书")
    assert dc.skipped("关于2025年度利润分配方案的法律意见书")
    assert dc.skipped("2025年年度审计报告")


def test_readable_puts_the_likely_ones_first():
    """抓取有预算，所以顺序决定了预算花在哪几份上。"""
    events = [_event(1, "关于召开股东大会的通知", ident=1),
              _event(2, "关于股份回购进展情况的公告", ident=2),
              _event(3, "独立董事候选人声明与承诺", ident=3),
              _event(4, "关于对外投资的公告", ident=4)]
    ordered = dc.readable(events)
    assert [event["title"] for event in ordered] == [
        "关于股份回购进展情况的公告", "关于对外投资的公告", "关于召开股东大会的通知"]


def test_readable_prefers_newer_when_equally_likely():
    """同分按日期新在前：新承诺还没到期，旧的多半已经核过了。

    这条盯的是排序实现——日期是字符串取不了负号，塞进同一个 key
    里只能同向排，那样"新在前"会悄悄变成"旧在前"。
    """
    events = [_event(1, "关于股份回购的公告", when="2024-01-01", ident=1),
              _event(2, "关于股份回购的公告", when="2026-08-04", ident=2)]
    assert [e["event_date"] for e in dc.readable(events)] == ["2026-08-04", "2024-01-01"]


# --------------------------------------------------------------- 抓取的失败面

def test_non_pdf_response_is_recorded_as_a_reason_not_an_exception(monkeypatch):
    """失败是要写进库的结果，不是异常——不写的话每次抽取都会重试一遍。"""
    class _Resp:
        def read(self, *_): return b"<html>404</html>"
        def __enter__(self): return self
        def __exit__(self, *_): return False

    monkeypatch.setattr(dc.urllib.request, "build_opener",
                        lambda *_: type("O", (), {"open": lambda *a, **k: _Resp()})())
    result = dc.fetch_one(_DETAIL + "2026-08-04")
    assert result["status"] == "取不到"
    # **理由要说出取回来的是什么**，不是猜「公告可能已撤下」。
    # 实测最常见的原因根本不是撤下，是站点给服务器返了一个校验页或错误页
    # （见 test_fetch_says_what_came_back.py 里的实测数据）。
    assert "网页" in result["note"], result["note"]


def test_oversized_file_is_skipped_with_a_readable_reason(monkeypatch):
    class _Resp:
        def read(self, *_): return b"%PDF-" + b"x" * (dc.MAX_PDF_BYTES + 1)
        def __enter__(self): return self
        def __exit__(self, *_): return False

    monkeypatch.setattr(dc.urllib.request, "build_opener",
                        lambda *_: type("O", (), {"open": lambda *a, **k: _Resp()})())
    result = dc.fetch_one(_DETAIL + "2026-08-04")
    # **不能再断言"年报"了。** 8MB 那条线当初就是为了跳过年报，
    # 而现在年报是主要目标——前五大客户与供应商是强制披露项，只在年报里。
    # 上限提到 60MB，超限的只剩真正异常的文件。
    assert result["status"] == "取不到" and "上限" in result["note"]


def test_network_failure_does_not_escape(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise TimeoutError("超时")

    monkeypatch.setattr(dc.urllib.request, "build_opener",
                        lambda *_: type("O", (), {"open": _boom})())
    result = dc.fetch_one(_DETAIL + "2026-08-04")
    assert result["status"] == "取不到" and "TimeoutError" in result["note"]


def test_scanned_pdf_without_text_layer_is_not_silently_empty(monkeypatch):
    """扫描件没有文字层。这不是错误，但也不能当成"读到了正文"。"""
    class _Resp:
        def read(self, *_): return b"%PDF-1.7 whatever"
        def __enter__(self): return self
        def __exit__(self, *_): return False

    monkeypatch.setattr(dc.urllib.request, "build_opener",
                        lambda *_: type("O", (), {"open": lambda *a, **k: _Resp()})())
    monkeypatch.setattr(dc, "_extract_text", lambda _body: "")
    result = dc.fetch_one(_DETAIL + "2026-08-04")
    assert result["status"] == "取不到" and "扫描件" in result["note"]


# --------------------------------------------------------------- 喂给模型的那一段

def test_prompt_carries_the_body_when_there_is_one():
    """整条链路的目的就在这一行：模型看到的是正文，不是标题。"""
    event = _event(1)
    event["body"] = "回购资金总额不低于人民币50亿元（含）且不超过人民币100亿元（含）"
    text = pm.build_prompt([event])
    assert "不低于人民币50亿元" in text
    assert "公告正文" in text


def test_summary_is_labelled_as_not_the_original_wording():
    """没抓到正文时退回摘要，但**必须说明这是摘要**——

    statement 的全部价值在于它是原话；不说明的话模型会把转述抄进去。
    """
    event = _event(1)
    event["summary"] = "公司披露了回购进展"
    text = pm.build_prompt([event])
    assert "不是原文" in text


def test_over_budget_splits_into_batches_instead_of_truncating():
    """**超预算分批，绝不截断。**

    截断是这里最难发现的错：被截掉的公告不报错、不留痕，
    只表现为"这家公司没有承诺"——跟真的没有承诺长得一模一样。
    """
    events = []
    for index in range(12):
        event = _event(index, ident=1000 + index)
        event["body"] = "承" * dc.PROMPT_CHARS
        events.append(event)
    batches = pm._batches(events)
    assert len(batches) > 1
    # 一条都不能丢
    assert sum(len(batch) for batch in batches) == 12
    for batch in batches:
        assert sum(min(len(e["body"]), dc.PROMPT_CHARS) for e in batch) <= max(
            pm.BATCH_BODY_CHARS, dc.PROMPT_CHARS)


def test_source_index_is_resolved_within_its_own_batch(monkeypatch):
    """**分批之后 source_index 是批内序号。**

    直接汇总会让第二批的第 1 条指到第一批的第 1 条公告上，
    而出处指错比没有出处更糟：你点进去发现那条公告根本没说过这句话。
    """
    events = []
    for index in range(4):
        # 每条的数字都不同 —— 数字一样的会被去重合掉，那是另一条规则。
        event = _event(index, title=f"关于回购的公告{index}", ident=2000 + index)
        event["body"] = f"回购不低于{index + 1}亿元" + "承" * dc.PROMPT_CHARS
        events.append(event)

    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(pm, "_batches", lambda evts: [evts[:2], evts[2:]])

    seen: list[str] = []

    def _call(_system, user, **_kwargs):
        seen.append(user)
        # **原话要真的取自这一批的第一条公告。**
        # 随便编一句的话，回原文核对那一步会去别的公告里找它、然后"更正"出处——
        # 于是这条测试测的就不再是「批内序号」了，而是两件事混在一起。
        import re as _re
        first = _re.search(r"回购不低于\d+亿元", user).group(0)
        return type("C", (), {"text": '{"promises": [{"statement": "%s",'
                                      '"promised_on": "2026-08-04", "source_index": 1}]}' % first})()

    monkeypatch.setattr(pm.llm, "call", _call)
    found = pm.extract(events)
    assert len(seen) == 2, "两批就该调两次"
    # 两条承诺分别指向各自批次里的第一条公告，不是都指向 events[0]
    assert sorted(item["source_title"] for item in found) == [
        "关于回购的公告0", "关于回购的公告2"]


# --------------------------------------------------------------- 数据域（回归）

def test_extract_runs_under_a_real_user_scope(monkeypatch):
    """**这个功能上线以来一次都没成功过，而全套测试是绿的。**

    抽取那句 SQL 对 company_calendar_events 用了 _sw()，而这张表没有 user_id 列
    （它按 company_id 挂靠，过滤要走 _swc()）。任何登录用户点「抽取承诺」
    都会撞上 UndefinedColumn 直接 500。

    测试没抓到，是因为测试跑在系统域下——current_scope() 为 None 时 _sw()
    返回空串，那一句 AND 根本不存在。所以这条测试**必须显式设一个数据域**，
    否则它守不住任何东西。
    """
    from fastapi.testclient import TestClient

    from stock_decision import access
    from stock_decision import repository as repo
    from stock_decision.main import app

    company = TestClient(app).post("/api/v1/companies", json={
        "symbol": "600519", "name": "贵州茅台", "industry": "白酒"}).json()
    repo.store_company_profile(company["id"], {"events": [{
        "category": "公告", "event_date": "2026-08-04",
        "title": "关于股份回购进展情况的公告", "detail": "",
        "url": _DETAIL + "2026-08-04", "source": "巨潮资讯公告"}]})

    # **必须给一份正文。** read=0 现在会在调模型之前就停下（一份正文都没有时
    # 那次调用不可能有产出，见 extract_company_promises 里那段），
    # 于是这条测试就走不到它真正要守的那句 SQL 了。
    monkeypatch.setattr(repo, "announcement_bodies",
                        lambda events, budget=None: {
                            "bodies": {int(e["id"]): "公司拟回购不超过 1 亿元。" for e in events},
                            "read": len(events), "failed": 0, "pending": 0, "reasons": []})
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(pm.llm, "call",
                        lambda *a, **k: type("C", (), {"text": '{"promises": []}'})())

    token = access.set_scope(access.OWNER_SCOPE)
    try:
        result = repo.extract_company_promises(company["id"])
    finally:
        access.reset_scope(token)
    assert result is not None and result["scanned"] >= 1


# --------------------------------------------------------------- 并发（回归）

def test_every_batch_actually_runs(monkeypatch):
    """**我在这里犯过一次错，而它的表现是完全正常的。**

    并发跑批次时我复制了一份 contextvars.Context 给所有线程共用，
    结果除第一个线程外全部抛 "cannot enter context: ... is already entered"，
    异常又被 except 吞掉——12 批只有 1 批真的读了，界面上看是
    "读了 45 份正文，找到 1 条承诺"，跟真的只有 1 条长得一模一样。

    所以这条测试数的是**调用次数**，不是结果条数。
    """
    events = []
    for index in range(12):
        event = _event(index, title=f"关于回购的公告{index}", ident=3000 + index)
        event["body"] = "回购不低于1亿元" + "承" * dc.PROMPT_CHARS
        events.append(event)

    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    calls: list[int] = []

    # **必须逼线程真的重叠。** 用一个立刻返回的 mock，几个线程会自然排队
    # 依次进出同一份 Context，共用一份也不会报错——那样这条测试守不住任何东西。
    # 屏障让并发的那几个线程同时停在 Context 里面。
    import threading
    gate = threading.Barrier(min(pm.BATCH_CONCURRENCY, len(pm._batches(events))),
                             timeout=10)

    def _call(_system, _user, **_kwargs):
        calls.append(1)
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass
        return type("C", (), {"text": '{"promises": []}'})()

    monkeypatch.setattr(pm.llm, "call", _call)
    failures: list[str] = []
    pm.extract(events, failures=failures)
    gate.abort()
    assert len(calls) == len(pm._batches(events)) > 1, "每一批都必须真的跑到"
    assert failures == [], f"不该有失败批次：{failures}"


def test_a_failed_batch_is_reported_not_swallowed(monkeypatch):
    """一批失败不该带走其余几批，**但必须留痕**——

    静默返回空列表的话，一次限流会表现成"这家公司没有承诺"。
    """
    # 要多于一批 —— 只有一批时失败就该直接上抛（整个抽取失败了，
    # 那种情况使用者看到的是错误信息，不是"没有承诺"）。
    events = []
    for index in range(24):
        event = _event(index, title=f"关于回购的公告{index}", ident=4000 + index)
        event["body"] = "回购不低于1亿元" + "承" * dc.PROMPT_CHARS
        events.append(event)

    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    seen: list[int] = []

    def _call(_system, user, **_kwargs):
        seen.append(1)
        if len(seen) == 1:
            raise RuntimeError("429 限流")
        return type("C", (), {"text": '{"promises": []}'})()

    monkeypatch.setattr(pm.llm, "call", _call)
    failures: list[str] = []
    pm.extract(events, failures=failures)
    assert len(failures) == 1 and "没读成功" in failures[0]
    assert "条公告没被看过" in failures[0], "要说清楚丢了多少条，不能只说失败"


# --------------------------------------------------------------- 去重

def test_the_same_promise_restated_in_progress_reports_is_kept_once():
    """一条回购承诺会在每份进展公告里重述一遍。

    实测茅台一轮抽出 15 条里 5 条是同一句。**留最早说的那一份**——
    承诺是在原始公告那天做出的，留进展公告会让到期日整体往后漂。
    """
    def _item(when, event_id, text="回购金额不低于人民币15亿元且不超过30亿元"):
        return {"statement": text, "category": "回购", "promised_on": when,
                "event_id": event_id, "subject": "公司", "due_date": "",
                "check_metric": "", "check_op": "", "check_value": None,
                "check_period": "", "source_title": "", "source_url": None}

    rows = [_item("2026-05-20", 3), _item("2026-03-14", 1), _item("2026-04-10", 2)]
    unique: dict = {}
    for item in sorted(rows, key=lambda row: row["promised_on"]):
        unique.setdefault(pm._same_promise(item), item)
    assert len(unique) == 1
    assert list(unique.values())[0]["promised_on"] == "2026-03-14", "留最早说的那一份"


def test_the_same_promise_written_two_ways_is_still_one():
    """「15亿元」和「15 亿元」是同一句话，字面比对认不出来，按数字认。"""
    a = {"statement": "回购金额不低于人民币15亿元（含）且不超过30亿元", "category": "回购"}
    b = {"statement": "回购金额不低于人民币 15 亿元（含）且不超过 30 亿元", "category": "回购"}
    assert pm._same_promise(a) == pm._same_promise(b)


def test_two_different_buybacks_are_not_merged():
    """15/30 亿那次和 30/60 亿那次是两条承诺，合掉就丢了一条真承诺。"""
    a = {"statement": "回购金额不低于15亿元且不超过30亿元", "category": "回购"}
    b = {"statement": "回购金额不低于30亿元且不超过60亿元", "category": "回购"}
    assert pm._same_promise(a) != pm._same_promise(b)


# --------------------------------------------------------------- 长公告的取段

def test_excerpt_finds_the_promise_dense_part_of_a_long_filing():
    """**直接取前 3000 字是一刀静默的截断。**

    一份二十页的公告，承诺条款在第十页的话就永远看不到，
    而表现出来是"这条公告里没有承诺"——跟真的没有一模一样。
    """
    filler = "本公司及董事会全体成员保证信息披露内容真实准确完整。" * 300
    promise = "回购金额不低于人民币50亿元且不超过100亿元，回购期限不超过12个月。" * 20
    body = filler + promise + filler
    picked = dc.excerpt(body)
    assert "不低于人民币50亿元" in picked, "承诺埋在中间也要被取到"
    assert "从第" in picked and "字开始" in picked, "截掉了多少必须说出来"


def test_a_short_filing_is_passed_through_untouched():
    """够短的原样给，不要给它加一句没用的说明。"""
    body = "回购金额不低于人民币50亿元。"
    assert dc.excerpt(body) == body


def test_the_opening_wins_ties():
    """同样密度时取开头——公告的要点通常写在前面。"""
    piece = "回购不低于1亿元，期限12个月。"
    body = (piece * 40) + ("其他内容。" * 400) + (piece * 40)
    assert not dc.excerpt(body).startswith("（"), "平手时取开头，不加说明"


# --------------------------------------------------------------- 回原文核对

def test_a_statement_that_is_really_in_the_filing_passes():
    """照抄的原样收下。排版差异（「15亿元」vs「15 亿元」）不算改写。"""
    body = "回购资金总额不低于人民币 50 亿元（含）且不超过人民币 100 亿元（含）。"
    got = pm.verbatim_check("回购资金总额不低于人民币50亿元（含）且不超过人民币100亿元（含）", body)
    assert got["verdict"] == "原文"


def test_a_stitched_statement_is_repaired_to_the_real_wording():
    """**模型最常见的改写方式是把中间一段删掉再接起来。**

    实测宁德那条：「同意公司使用自有资金…回购部分股份」＋「回购的资金总额不低于
    20 亿元」，中间删掉了"用于实施股权激励计划"。原文是连续的，补回来就是真原话。
    """
    body = ("同意公司使用自有资金以集中竞价交易方式回购公司部分股份，"
            "用于实施股权激励计划或员工持股计划，回购的资金总额不低于人民币20亿元。")
    stitched = "同意公司使用自有资金以集中竞价交易方式回购公司部分股份，回购的资金总额不低于人民币20亿元。"
    got = pm.verbatim_check(stitched, body)
    assert got["verdict"] == "拼接"
    assert "用于实施股权激励计划或员工持股计划" in got["statement"], "补回来的必须是完整原话"
    assert got["statement"] in body, "还原出来的要能在原文里一字不差地找到"


def test_two_unrelated_sentences_glued_together_are_dropped():
    """头尾隔太远就不是"删了个连接词"，是**把两件事拼成了一条承诺**。

    这种不能靠补全洗白——补出来的"原话"里夹着几百字不相干的内容。
    """
    body = ("公司拟回购股份金额不低于人民币15亿元且不超过30亿元。"
            + "与本条无关的其他披露内容。" * 60
            + "公司为本次期货和衍生品交易业务设定人民币5000万元的最高累计亏损限额。")
    got = pm.verbatim_check(
        "公司拟回购股份金额不低于人民币15亿元且不超过30亿元，"
        "并为本次期货和衍生品交易业务设定人民币5000万元的最高累计亏损限额。", body)
    assert got["verdict"] == "找不到"
    assert "隔得太远" in got["note"]


def test_a_fabricated_statement_is_dropped():
    """正文里压根没有这句话。**提示词早就写着"抄不到原话的不要收"，
    现在由代码来执行**——实测拦下了「独立董事津贴 25 万元/年」这种。"""
    got = pm.verbatim_check("独立董事津贴标准为人民币25万元/年/人", "本公司回购股份不低于50亿元。")
    assert got["verdict"] == "找不到"


def test_only_the_opening_matching_is_not_enough():
    """只对上开头就放行的话，**后半句可以是模型自己接的**——
    而后半句往往正是带数字、你会拿去核对的那半句。"""
    body = "公司拟回购股份用于员工持股计划，具体金额由董事会另行确定。"
    got = pm.verbatim_check("公司拟回购股份用于员工持股计划，金额不低于人民币50亿元", body)
    assert got["verdict"] == "找不到"


def test_a_wrong_citation_is_repointed_not_dropped(monkeypatch):
    """句子是真的、原文也在，只是模型把出处指到了另一份公告上。

    **改出处比丢掉好**——同一条回购承诺会在好几份公告里重述，
    直接丢等于因为一个指错的链接扔掉一条真承诺。
    """
    events = [
        {**_event(1, "关于回购的进展公告", ident=5001),
         "body": "本次回购进展如下，累计已回购 100 万股。"},
        {**_event(2, "关于回购股份方案的公告", ident=5002),
         "body": "回购资金总额不低于人民币50亿元且不超过人民币100亿元。"},
    ]
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(pm.llm, "call", lambda *a, **k: type("C", (), {
        "text": '{"promises": [{"statement": "回购资金总额不低于人民币50亿元且不超过人民币100亿元",'
                '"promised_on": "2026-08-04", "category": "回购", "source_index": 1}]}'})())
    found = pm.extract(events)
    assert len(found) == 1, "不该因为指错出处就丢掉一条真承诺"
    assert found[0]["source_title"] == "关于回购股份方案的公告", "出处要改到原文真正所在那份"
    assert "指错了出处" in found[0]["verbatim_note"]


def test_an_ambiguous_repoint_is_dropped_not_guessed(monkeypatch):
    """两份公告都含这句话时**不猜**。

    猜一个出处比没有出处更糟：你点进去发现那份公告确实有这句话，
    但它不是最早说这话的那一份，到期日就从错误的那天起算了。
    """
    same = "回购资金总额不低于人民币50亿元。"
    events = [
        {**_event(1, "甲公告", ident=6001), "body": "无关内容。"},
        {**_event(2, "乙公告", ident=6002), "body": same},
        {**_event(3, "丙公告", ident=6003), "body": same},
    ]
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    monkeypatch.setattr(pm.llm, "call", lambda *a, **k: type("C", (), {
        "text": '{"promises": [{"statement": "回购资金总额不低于人民币50亿元。",'
                '"promised_on": "2026-08-04", "source_index": 1}]}'})())
    assert pm.extract(events) == []
