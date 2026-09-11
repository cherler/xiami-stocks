"""每日整理不该为同一批「拿不准」的条目按天重复付费。

模型判完仍是「中」的，正是模型也拿不准、要留给人处理的那些；它们会一直躺在
收件箱里直到你去点。上线当天实测过：模型几分钟前刚判过的 2 条，下一次整理
又原样送了一遍——这笔钱会随着积压量一天天涨。

这里钉死三件事：模型看过的不重送、改了规则词要重送、页面上主动点重判要重送。
"""

import pytest

from stock_decision.repository import _model_should_look_again
from stock_decision.schemas import CompanyInput


LATER = "2026-08-05T18:00:00"
EARLIER = "2026-08-05T10:00:00"


def test_item_the_model_has_never_seen_goes_to_the_model():
    # 只有规则判过 —— 模型可能能把它从「中」里解出来，该送。
    assert _model_should_look_again(
        {"relevance_source": "规则", "classified_at": LATER}, EARLIER) is True


def test_brand_new_item_goes_to_the_model():
    assert _model_should_look_again({"relevance_source": None, "classified_at": None}, "") is True


def test_model_graded_item_is_not_re_sent_when_criteria_are_unchanged():
    # 这条就是会按天重复计费的那种。
    assert _model_should_look_again(
        {"relevance_source": "模型", "classified_at": LATER}, EARLIER) is False


def test_model_graded_item_is_re_sent_after_the_rules_change():
    # 判完之后又加了规则词 —— 旧结论按的是旧口径，该重来。
    assert _model_should_look_again(
        {"relevance_source": "模型", "classified_at": EARLIER}, LATER) is True


def test_no_custom_terms_never_triggers_a_re_send():
    # 没有自定义词时 terms_changed_at 是空串，比任何时间戳都小。
    assert _model_should_look_again(
        {"relevance_source": "模型", "classified_at": EARLIER}, "") is False


def test_the_todo_count_is_what_you_actually_have_to_do():
    """首页那个「公告待核」的数，必须等于**点进去真的会让你做事的数量**。

    实测过的错位：库里 193 条待核验全是「中」级，而决策看板本来就只对
    「高」派活（decision_board 里那句 relevance = '高'）——
    于是首页显示 193，点进去一件事都不用做。一个永远清不完的数字，
    第三天就被当成背景了，之后真正要紧的事再也没法用它提醒。

    **但「未分级」要算进去。** 它只是还没跑过分级，不是已经判定为不重要；
    排除掉的话，分级作业一挂，首页就显示"没事可做"而收件箱正在堆积。
    这条规则是被 test_inbox_archive_as_event_and_ignore 逼出来的——
    第一版只数「高」，把未分级一起漏了。
    """
    from stock_decision.database import connection, now_iso
    from stock_decision import repository

    company = repository.create_company(
        CompanyInput(symbol="600519", name="贵州茅台", industry="白酒"))
    with connection() as conn:
        for grade in ("高", "中", "低", None):
            conn.execute(
                """INSERT INTO company_calendar_events
                   (company_id, category, event_date, title, source, refreshed_at,
                    inbox_status, relevance)
                   VALUES (?, '公告', '2026-08-01', ?, 'test', ?, '待核验', ?)""",
                (company["id"], f"公告-{grade or '未分级'}", now_iso(), grade))

    board = repository.dashboard()
    assert board["inbox_pending"] == 2, "该数的是「高」与「未分级」"
    assert board["inbox_backlog"] == 2, "「中」「低」进积压，不进待办"
