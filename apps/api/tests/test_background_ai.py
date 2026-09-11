"""后台模型分级由每个用户自己勾，默认关。

**默认必须是关。** 这个作业每天自己跑一次，没有任何人点过它。让没点过按钮的人
第二天发现余额少了一截，不是记错账，是没打招呼——所以做成他自己勾的开关。

「记到谁头上」不是问题（见 test_background_billing.py）：积分闸口本来就是为模型
调用准备的，逐用户跑的任务也本来就知道是在替谁干活。默认关是另一回事。

`STOCK_BACKGROUND_AI` 现在只是全局关停闸：出事时一把关掉所有人，
但**不能反过来替用户打开**——那就绕过了「他自己勾」这件事本身。
"""

import pytest

from stock_decision import access, repository, scheduler


@pytest.fixture(autouse=True)
def _no_global_switch(monkeypatch):
    """测的是没配全局闸时的行为。"""
    monkeypatch.delenv("STOCK_BACKGROUND_AI", raising=False)
    original = repository.__dict__  # 占位，避免误导：下面只改 llm 的读取
    from stock_decision import llm
    base = llm.load_env
    monkeypatch.setattr(llm, "load_env", lambda: {**base(), "STOCK_BACKGROUND_AI": ""})


def test_off_by_default():
    assert repository.get_setting("inbox_auto_grade") is False
    assert scheduler.background_ai_enabled() is False


def test_a_user_can_turn_it_on_for_themselves():
    repository.set_setting("inbox_auto_grade", True)
    assert scheduler.background_ai_enabled() is True


def test_one_users_choice_does_not_affect_another():
    """开关按数据域隔离 —— 否则一个人勾上，全站都开始花钱。"""
    repository.set_setting("inbox_auto_grade", True)          # 站主域勾上

    token = access.set_scope("user-7")
    try:
        assert repository.get_setting("inbox_auto_grade") is False
        assert scheduler.background_ai_enabled() is False
    finally:
        access.reset_scope(token)

    assert scheduler.background_ai_enabled() is True          # 站主的仍然开着


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_the_global_switch_can_turn_everyone_off(monkeypatch, value):
    repository.set_setting("inbox_auto_grade", True)
    monkeypatch.setenv("STOCK_BACKGROUND_AI", value)
    assert scheduler.background_ai_enabled() is False, "全局关停闸必须压过个人设置"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_the_global_switch_cannot_turn_anyone_on(monkeypatch, value):
    """把它写成 on 也不能替用户做决定 —— 否则「他自己勾」就成了摆设。"""
    monkeypatch.setenv("STOCK_BACKGROUND_AI", value)
    assert scheduler.background_ai_enabled() is False


def test_unknown_setting_keys_are_rejected():
    # 拼错一个字母就会写进一条永远读不到的设置，而且看不出哪里错了。
    with pytest.raises(repository.LedgerError):
        repository.get_setting("inbox_auto_grad")
    with pytest.raises(repository.LedgerError):
        repository.set_setting("随便什么", True)


def test_a_broken_read_falls_back_to_off(monkeypatch):
    """读不到设置时要往不花钱的方向倒。"""
    monkeypatch.setattr(scheduler, "_user_opted_in", scheduler._user_opted_in)
    def boom(_key):
        raise RuntimeError("数据库抖了一下")
    monkeypatch.setattr(repository, "get_setting", boom)
    assert scheduler.background_ai_enabled() is False


def test_the_job_reports_who_had_it_on(monkeypatch):
    """作业结果要说清有几个人开了 —— 否则看不出「待人工处理」是哪种情况。"""
    monkeypatch.setattr("stock_decision.repository.tidy_inbox",
                        lambda use_ai=True: {"classified": 0, "archived": 0, "ignored": 0, "remaining": 2})
    result = scheduler._run_inbox_tidy()
    assert "只用规则" in result["detail"]
    assert "收件箱页面勾上" in result["detail"]
