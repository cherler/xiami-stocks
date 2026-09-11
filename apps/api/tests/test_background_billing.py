"""后台分级的账记在各自头上，不是一律记给站主。

积分闸口本来就是为模型调用准备的，后台调用不特殊：花的 token 跟用户在页面上点
一次没有区别，唯一要回答的是记给谁——而逐用户跑的任务本来就知道答案。

此前所有后台调用都走 `background_principal()`，也就是同一个 `XM_OWNER_USER_ID`。
真开放多用户之后那意味着站主替全站付钱。
"""

import pytest

from stock_decision import access, llm, scheduler


@pytest.fixture()
def configured(monkeypatch):
    original = llm.load_env
    monkeypatch.setattr(llm, "load_env", lambda: {
        **original(), "XM_INTERNAL_KEY": "internal-key", "XM_OWNER_USER_ID": "owner-42"})


def test_owner_scope_maps_to_the_configured_owner_id(configured):
    # __owner__ 是哨兵值，不是真实 user_id —— 直接拿它去闸口会记到一个不存在的人头上。
    principal = llm.principal_for_scope(access.OWNER_SCOPE)
    assert principal is not None
    assert principal.user_id == "owner-42"


def test_other_scopes_bill_that_user(configured):
    principal = llm.principal_for_scope("user-7")
    assert principal is not None
    assert principal.user_id == "user-7"


def test_no_internal_key_means_no_billing(monkeypatch):
    original = llm.load_env
    monkeypatch.setattr(llm, "load_env", lambda: {
        **original(), "XM_INTERNAL_KEY": "", "XM_OWNER_USER_ID": "owner-42"})
    # 宁可不计费也不能记错人：记错账比不记账更难查。
    assert llm.principal_for_scope("user-7") is None


def test_owner_scope_without_owner_id_means_no_billing(monkeypatch):
    original = llm.load_env
    monkeypatch.setattr(llm, "load_env", lambda: {
        **original(), "XM_INTERNAL_KEY": "internal-key", "XM_OWNER_USER_ID": ""})
    assert llm.principal_for_scope(access.OWNER_SCOPE) is None


def test_each_scope_runs_under_its_own_principal(monkeypatch, configured):
    """作业逐域切换 principal —— 不切的话所有人的消耗都落到同一个 user_id 上。"""
    seen = []

    def fake_tidy(use_ai=True):
        current = llm._principal.get()
        seen.append((access.current_scope(), current.user_id if current else None))
        return {"classified": 0, "archived": 0, "ignored": 0, "remaining": 0}

    monkeypatch.setattr("stock_decision.repository.tidy_inbox", fake_tidy)
    monkeypatch.setattr(scheduler, "background_ai_enabled", lambda: True)

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def execute(self, *a, **k):
            return type("C", (), {"fetchall": lambda s: [
                {"user_id": access.OWNER_SCOPE}, {"user_id": "user-7"}]})()

    monkeypatch.setattr("stock_decision.database.connection", lambda *a, **k: _Conn())
    scheduler._run_inbox_tidy()

    assert seen == [(access.OWNER_SCOPE, "owner-42"), ("user-7", "user-7")]


def test_principal_is_restored_after_the_job(monkeypatch, configured):
    """跑完必须复位，否则下一个作业会顶着上一个用户的身份去扣费。"""
    monkeypatch.setattr("stock_decision.repository.tidy_inbox",
                        lambda use_ai=True: {"classified": 0, "archived": 0, "ignored": 0, "remaining": 0})
    before = llm._principal.get()
    scheduler._run_inbox_tidy()
    assert llm._principal.get() is before


def test_one_users_failure_does_not_stop_the_others(monkeypatch, configured):
    """余额不足是这个人的问题，不该让别人的整理跟着停。"""
    def flaky(use_ai=True):
        if access.current_scope() == "user-7":
            raise llm.CreditsError("积分不足")
        return {"classified": 1, "archived": 1, "ignored": 0, "remaining": 0}

    monkeypatch.setattr("stock_decision.repository.tidy_inbox", flaky)

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def execute(self, *a, **k):
            return type("C", (), {"fetchall": lambda s: [
                {"user_id": "user-7"}, {"user_id": access.OWNER_SCOPE}]})()

    monkeypatch.setattr("stock_decision.database.connection", lambda *a, **k: _Conn())
    result = scheduler._run_inbox_tidy()

    assert result["failures"] == 1
    assert any("user-7" in e for e in result["errors"])
    assert result["items"] == 1, "站主那一份仍然要跑完"


def test_a_credits_rejection_is_not_retried(monkeypatch, configured):
    """余额不足是确定答复，重试只是让这个人白白拖住后面排队的人。"""
    calls = []

    def broke(use_ai=True):
        calls.append(1)
        raise llm.CreditsError("积分不足")

    monkeypatch.setattr("stock_decision.repository.tidy_inbox", broke)
    scheduler._run_inbox_tidy()
    assert len(calls) == 1, f"应当只试一次，实际试了 {len(calls)} 次"
