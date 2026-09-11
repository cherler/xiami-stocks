"""导出只能拿到自己的记录；备份/还原这类整实例操作只有站主能做。

**这两条是不同性质的问题，修法也不同。**

导出是「每人一份」的功能，按数据域过滤就对了。而备份、还原、下载整库作用于
整个数据库：还原会用一份快照覆盖所有人的记录，下载拿到的是所有人的原始行——
这种操作没有「只做我那份」的版本，只能按人挡。

在只对站主开放的姿态下这些都看不出问题，但运营台上那个开关一勾就是多用户模式。
"""

import pytest

from stock_decision import access, backup, repository
from stock_decision.schemas import CompanyInput, ThesisCreate


@pytest.fixture()
def two_users():
    """站主和另一个用户各建一份数据。返回 (站主公司 id, 他人公司 id)。"""
    def in_scope(scope, fn):
        token = access.set_scope(scope)
        try:
            return fn()
        finally:
            access.reset_scope(token)

    mine = in_scope(access.OWNER_SCOPE, lambda: repository.create_company(
        CompanyInput(symbol="600519", name="站主的票", industry="白酒")))
    theirs = in_scope("user-7", lambda: repository.create_company(
        CompanyInput(symbol="000001", name="别人的票", industry="银行")))
    return in_scope, mine, theirs


def test_export_only_returns_my_companies(two_users):
    in_scope, mine, theirs = two_users
    payload = in_scope("user-7", backup.export_records)
    names = [c["name"] for c in payload["records"]["companies"]]
    assert names == ["别人的票"], f"导出里混进了别人的记录：{names}"


def test_the_owner_does_not_see_other_users_records_either(two_users):
    # 站主看到的是存量数据域，不是「所有人的并集」。
    in_scope, mine, theirs = two_users
    payload = in_scope(access.OWNER_SCOPE, backup.export_records)
    names = [c["name"] for c in payload["records"]["companies"]]
    assert "别人的票" not in names


def test_child_records_follow_their_company(two_users):
    """子表靠外键回溯，不能因为自己没有 user_id 就整表导出。"""
    in_scope, mine, theirs = two_users
    in_scope(access.OWNER_SCOPE, lambda: repository.create_thesis(
        mine["id"], ThesisCreate(claim="站主的逻辑")))

    payload = in_scope("user-7", backup.export_records)
    assert payload["records"]["theses"] == []

    payload = in_scope(access.OWNER_SCOPE, backup.export_records)
    assert [t["claim"] for t in payload["records"]["theses"]] == ["站主的逻辑"]


def test_every_exported_table_has_a_scope_filter():
    """漏一张表就是静悄悄多导别人的记录 —— 所以宁可当场报错。"""
    for table in backup.AUTHORED_TABLES:
        assert backup._export_filter(table), f"{table} 没有过滤片段"
    with pytest.raises(AssertionError):
        backup._export_filter("某张还没想过的表")


def test_export_asks_the_backend_aware_helper(monkeypatch):
    """曾经在 PG 上直接 500：这里自己硬写了一句 SQLite 专用的表清单查询。

    PG 上没有那张系统表，报 UndefinedTable，整个导出接口挂掉。测试跑在 SQLite 上，
    所以不能靠「跑一遍看崩不崩」来发现——只能钉住「必须走那个分后端的助手」，
    它才知道 PG 上该问 pg_tables。
    """
    called = []
    original = backup._existing_tables
    monkeypatch.setattr(backup, "_existing_tables",
                        lambda conn, **kw: (called.append(1), original(conn, **kw))[1])
    backup.export_records()
    assert called, "导出必须走 _existing_tables，否则换后端就会 500"


@pytest.mark.parametrize("what", ["查看备份", "创建备份", "还原备份", "下载备份"])
def test_instance_wide_operations_are_owner_only(what):
    token = access.set_owner_flag(False)
    try:
        with pytest.raises(access.AccessDenied) as caught:
            access.require_owner(what)
        assert caught.value.status == 403
        assert caught.value.code == "owner_only"
    finally:
        access.reset_owner_flag(token)


def test_the_owner_can_still_do_them():
    token = access.set_owner_flag(True)
    try:
        access.require_owner("还原备份")   # 不抛就是通过
    finally:
        access.reset_owner_flag(token)


def test_scripts_and_scheduler_count_as_owner():
    """默认必须是站主：否则单机模式、脚本、调度器全被自己挡在门外。"""
    assert access.is_owner() is True
