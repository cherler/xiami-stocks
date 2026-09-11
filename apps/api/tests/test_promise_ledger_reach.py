"""承诺台账：**同一件事只记一遍，到期了要有人被叫住。**

2026-08-15 拿真账号在线上跑了一轮真实抽取（格力，60 条公告读了 34 份正文，
3 次调用 35,822 token、8 分），两件事当场露出来：

一、**5 条里有 2 条是同一件事。** 同一句回购承诺在两份公告里各出现一次：

      方案公告 4635（04-29）  回购资金总额不低于 50 亿元…回购价格不超过 56.55 元/股
      进展公告 4574（08-04）  同一句 + 「回购期限…不超过 12 个月」

   去重的第一趟按「类别 + 句子里的数字」认，两句的数字集合差一个 12，认不出来；
   第二趟能认出包含关系，但被「只在同一条公告内部合并」那道安全线挡住了。
   而这个模块的开头写着：**台账被同一句话灌满，跟被套话灌满是一个后果 —— 没人再看它。**

二、**到期了没有任何人被叫住。** `due_promises()` 的注释写着"给今日概览用 ——
   到期了要顶到面前"，main.py 也把它 import 进来了，而全仓**没有一处调用**。
   台账面板的说明也写着「到期顶到你面前」。实际兑现方式是：你自己走进那家公司
   的档案页、翻到简报页签、往下拉 —— 那正是这个机制要对付的"想不起来"。
"""

from datetime import date, timedelta

import pytest

from stock_decision import access, promises as pm
from stock_decision.database import connection

from test_idor import client, owned  # noqa: F401


# 下面两句和那段正文都是线上真实数据（巨潮公告原文，仅截取）。
# **不要改成造出来的例子**：这一条修的就是"真实排版差异让去重失效"，
# 全角半角、空格、断行正是它失效的地方。
PLAN_BODY = (
    "重要内容提示：\n1.回购金额及回购价格：公司拟使用自有资金回购公司发行的部分人民币普通股（A\n"
    "股），回购资金总额不低于人民币 50 亿元（含）且不超过人民币 100 亿元（含），回\n"
    "购价格不超过人民币 56.55 元/股。\n2.回购数量：…")
PROGRESS_BODY = (
    "同意公司使用自有资金以集中竞价方式回购公司发行的部分人民币普通股（A\n"
    "股），回购资金总额不低于人民币 50 亿元（含）且不超过人民币 100 亿元（含），\n"
    "回购价格不超过人民币56.55 元/股，回购期限自公司股东会审议通过本次回购\n"
    "方案之日起不超过 12 个月。本次回购的股份不低于 70%将用于注销并减少注册\n资本…")

SHORT = "回购资金总额不低于人民币 50 亿元（含）且不超过人民币 100 亿元（含），回购价格不超过人民币 56.55 元/股"
LONG = ("回购资金总额不低于人民币 50 亿元（含）且不超过人民币 100 亿元（含），"
        "回购价格不超过人民币56.55 元/股，回购期限自公司股东会审议通过本次回购方案之日起不超过 12 个月")


class _Reply:
    def __init__(self, text):
        self.text = text


def _both_announcements(monkeypatch):
    """模型从两份公告里各抽出同一条回购承诺 —— 线上就是这么发生的。"""
    import json

    events = [
        {"id": 4635, "category": "公告", "event_date": "2026-04-29", "url": "https://x/plan",
         "title": "关于回购部分社会公众股份方案的公告暨回购股份报告书", "body": PLAN_BODY},
        {"id": 4574, "category": "公告", "event_date": "2026-08-04", "url": "https://x/progress",
         "title": "关于股份回购进展情况的公告", "body": PROGRESS_BODY},
    ]
    payload = {"promises": [
        {"subject": "公司", "statement": SHORT, "category": "回购",
         "promised_on": "2026-04-29", "due_date": "", "source_index": 1},
        {"subject": "公司", "statement": LONG, "category": "回购",
         "promised_on": "2026-08-04", "due_date": "2026-09-29", "source_index": 2},
    ]}
    monkeypatch.setattr(pm.llm, "call", lambda *a, **k: _Reply(json.dumps(payload, ensure_ascii=False)))
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    return events


def test_one_promise_restated_in_a_later_filing_is_recorded_once(monkeypatch):
    """**跨公告也要合。** 一条回购承诺会在每份进展公告里重述一遍，
    逐条确认时它们看着像两件事，记进台账就是两条内容相同的记录。"""
    found = pm.extract(_both_announcements(monkeypatch))
    assert len(found) == 1, f"同一条承诺记了 {len(found)} 遍：{[f['statement'][:30] for f in found]}"


def test_the_one_that_survives_is_the_one_that_can_expire(monkeypatch):
    """**留长的那条。**

    乍看跟「留最早说的那一份」相反，其实是同一个目的：长的那句多出来的正是
    「回购期限…12 个月」，而到期日就是从这句推出来的。上面那次实测里，
    短的那条 due_date 是空的 —— 留下短的，这条承诺永远不会到期，
    于是也永远不会有人被叫住去核对它。
    """
    kept = pm.extract(_both_announcements(monkeypatch))[0]
    assert "回购期限" in kept["statement"]
    assert kept["due_date"] == "2026-09-29", "留下的这条没有到期日，等于没进网"


def _speak(monkeypatch, events, promises):
    import json

    monkeypatch.setattr(pm.llm, "call",
                        lambda *a, **k: _Reply(json.dumps({"promises": promises}, ensure_ascii=False)))
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))
    return pm.extract(events)


def test_merging_across_filings_needs_the_words_not_just_the_numbers(monkeypatch):
    """**数字包含仍然只在同一份公告里合。**

    「未来 6 个月不减持」和某条带 6 的增持承诺数字上是包含关系，但它们是两件事
    —— 误伤掉的是一条真承诺。跨公告只认逐字包含：短的那句**原样**就是长的那句
    的一段，不可能是数字碰巧撞上。
    """
    events = [
        {"id": 1, "category": "公告", "event_date": "2026-01-01", "url": "https://x/1",
         "title": "股东承诺公告", "body": "控股股东承诺未来 6 个月内不减持公司股份。"},
        {"id": 2, "category": "公告", "event_date": "2026-02-01", "url": "https://x/2",
         "title": "增持计划公告", "body": "拟以自有资金 3 亿元增持，增持期限 6 个月，增持价格不设上限。"},
    ]
    found = _speak(monkeypatch, events, [
        {"subject": "控股股东", "statement": "未来 6 个月内不减持公司股份",
         "category": "锁定减持", "promised_on": "2026-01-01", "source_index": 1},
        {"subject": "控股股东", "statement": "拟以自有资金 3 亿元增持，增持期限 6 个月，增持价格不设上限",
         "category": "锁定减持", "promised_on": "2026-02-01", "source_index": 2},
    ])
    assert len(found) == 2, "两件不相干的事被数字包含并成了一条"


def test_two_shareholders_saying_the_same_thing_are_two_promises(monkeypatch):
    """**去重不能去过头。**

    锁定减持类公告里，几个股东各自作出同一句承诺是常态。指纹原来是
    「类别 + 数字」，于是这两条一模一样，京海互联那条被静默丢掉 ——
    而台账的用处正是"谁说过什么话、后来做到没有"。抹掉承诺人，
    剩下的那半张台账连问题都问不出来。
    """
    body = ("股东珠海明骏承诺自本公告之日起 6 个月内不减持公司股份；"
            "股东京海互联承诺自本公告之日起 6 个月内不减持公司股份。")
    events = [{"id": 1, "category": "公告", "event_date": "2026-01-01", "url": "https://x/1",
               "title": "股东承诺公告", "body": body}]
    found = _speak(monkeypatch, events, [
        {"subject": "珠海明骏", "statement": "珠海明骏承诺自本公告之日起 6 个月内不减持公司股份",
         "category": "锁定减持", "promised_on": "2026-01-01", "source_index": 1},
        {"subject": "京海互联", "statement": "京海互联承诺自本公告之日起 6 个月内不减持公司股份",
         "category": "锁定减持", "promised_on": "2026-01-01", "source_index": 1},
    ])
    assert {item["subject"] for item in found} == {"珠海明骏", "京海互联"}, \
        f"两个股东各自的承诺被合成了一条：{[(i['subject'], i['statement'][:20]) for i in found]}"


# ------------------------------------------------------------- 到期了要有人被叫住

def test_a_due_promise_reaches_the_front_page(client, owned):  # noqa: F811
    """**这一条才是真正的修复。**

    台账算得对、到期判得对、函数也写好了 —— 少的是一个调用。
    跟认错条件那次一模一样：算法层是对的，坏在"会不会有人看见"。
    """
    client.as_user(access.OWNER_SCOPE)
    long_ago = (date.today() - timedelta(days=pm.DUE_GRACE_DAYS + 30)).isoformat()
    client.post(f"/api/v1/companies/{owned['company']}/promises", json={"items": [{
        "statement": "未来三年每年现金分红不低于当年净利润的 30%",
        "category": "分红", "promised_on": "2023-04-01", "due_date": long_ago,
    }]})

    summary = client.get("/api/v1/dashboard").json()
    assert "promises_due" in summary, (
        "DashboardSummary 没声明这个字段 —— 后端算了、接口不带出去，"
        "页面上只表现为'这块从来不出现'，不报错（这个坑本仓踩过四次）")
    assert len(summary["promises_due"]) >= 1, "到期的承诺没有顶到今日概览"
    row = summary["promises_due"][0]
    # 要能点回去：只报一句话而不带公司，你不知道该去哪家公司看
    assert row["company_id"] == owned["company"] and row["statement"]


def test_a_promise_still_inside_its_grace_period_does_not_nag(client, owned):  # noqa: F811
    """到期当天就催是不合理的 —— 定期报告要等披露。两周的宽限在这里也要生效。"""
    client.as_user(access.OWNER_SCOPE)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post(f"/api/v1/companies/{owned['company']}/promises", json={"items": [{
        "statement": "拟在 12 个月内回购不低于 3 亿元", "category": "回购",
        "promised_on": "2025-08-01", "due_date": yesterday}]})
    assert client.get("/api/v1/dashboard").json()["promises_due"] == []


def test_a_settled_promise_stops_nagging(client, owned):  # noqa: F811
    """核对过的不该再顶上来 —— 一个清不掉的提醒第三天就成了背景色。"""
    client.as_user(access.OWNER_SCOPE)
    long_ago = (date.today() - timedelta(days=pm.DUE_GRACE_DAYS + 30)).isoformat()
    client.post(f"/api/v1/companies/{owned['company']}/promises", json={"items": [{
        "statement": "拟在 12 个月内回购不低于 3 亿元", "category": "回购",
        "promised_on": "2025-01-01", "due_date": long_ago}]})
    with connection() as conn:
        promise_id = conn.execute("SELECT id FROM management_promises").fetchone()["id"]
    client.patch(f"/api/v1/promises/{promise_id}", json={"status": "已兑现", "note": "回购完成"})
    assert client.get("/api/v1/dashboard").json()["promises_due"] == []


def test_someone_elses_due_promise_is_not_my_problem(client, owned):  # noqa: F811
    """别人的承诺不该出现在我的首页 —— 而 due_promises 是新接上的一条查询路径。"""
    client.as_user(access.OWNER_SCOPE)
    long_ago = (date.today() - timedelta(days=pm.DUE_GRACE_DAYS + 30)).isoformat()
    client.post(f"/api/v1/companies/{owned['company']}/promises", json={"items": [{
        "statement": "未来三年每年现金分红不低于当年净利润的 30%", "category": "分红",
        "promised_on": "2023-04-01", "due_date": long_ago}]})

    client.as_user("user-9")
    assert client.get("/api/v1/dashboard").json()["promises_due"] == []


# ------------------------------------------------------------- 一批读失败要留痕

def test_a_single_batch_that_fails_says_so_instead_of_blowing_up(monkeypatch):
    """**一批也要走同一条兜底。**

    原来只有多批那条路有 try/except，单批是裸调用：一次坏 JSON 直接把整个任务
    打成"失败"，使用者看到的是一句 JSONDecodeError。而这一批里的公告有没有承诺，
    跟 JSON 好不好并没有关系。
    """
    # 抽取一次、重排一次，两次都交不出 JSON —— 重排也救不回来的那种。
    monkeypatch.setattr(pm.llm, "call", lambda *a, **k: _Reply("这不是 JSON"))
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))

    failures: list[str] = []
    found = pm.extract([{"id": 1, "category": "公告", "event_date": "2026-01-01",
                         "title": "回购公告", "url": "https://x/1", "body": "正文"}],
                       failures=failures)
    assert found == []
    assert failures, "读失败没有留痕 —— 界面上它跟'这家公司没有承诺'长得一模一样"


def test_being_cut_off_does_not_read_the_same_as_being_malformed(monkeypatch):
    """没写完是长度上限掐的，跟这批公告有没有承诺无关；混成一句「读失败」，
    使用者不知道该重点一次还是该来找人。

    抽取和重排走的是**同一个** `llm.call`，所以这里用一个函数管两次：
    第一次交出没写完的那段，第二次（如果真发生了）就地炸掉。
    """
    cut = '{"promises": [{"subject": "公司", "statement": "拟回购不低于人民币 3'
    calls: list[str] = []

    def _once(system, user, **kwargs):
        calls.append(kwargs.get("task", ""))
        if len(calls) > 1:
            raise AssertionError("没写完的东西不该送去重排 —— 重排一个字都不许加")
        return _Reply(cut)

    monkeypatch.setattr(pm.llm, "call", _once)
    monkeypatch.setattr(pm, "ai_available", lambda: (True, ""))

    failures: list[str] = []
    pm.extract([{"id": 1, "category": "公告", "event_date": "2026-01-01",
                 "title": "回购公告", "url": "https://x/1", "body": "正文"}], failures=failures)
    assert failures and "长度上限" in failures[0], failures


def test_the_batch_budget_is_not_three_thousand_tokens():
    """一批塞得下 24,000 字正文，而回答上限原来是 3,000 token。
    几份回购报告书撞在同一批里就会撞线，而撞线的表现是这一批整个丢掉。"""
    assert pm.MAX_ANSWER_TOKENS >= 20000
    assert pm.BATCH_BODY_CHARS == 24_000, "正文预算改了的话，回答上限也要重新量"


def test_the_reformat_shape_matches_the_prompt_it_reformats_for():
    """两处写岔的话，重排会照着另一个形状改 —— 改出来是合法 JSON，
    字段却对不上，然后静静地读出一堆空值，谁也不会报错。"""
    for field in ("promises", "statement", "promised_on", "due_date",
                  "check_metric", "check_op", "check_value", "source_index"):
        assert field in pm.REFORMAT_SHAPE, field
        assert field in pm.EXTRACT_SYSTEM_PROMPT, field
