"""行级安全：数据库自己挡住跨用户的读写。

**这一层要证明的和应用层不一样。** `test_idor.py` 证的是「现有接口挡得住」，
而这里证的是「**就算某条 SQL 完全没写过滤**，别人的行也出不来」——
前者靠一百零一处 `_sw()` 都没漏，后者不依赖任何一处。

本仓原本是单机工作台，多用户是后补的；同一天的审查里就找出八处忘了加过滤，
其中一处能直接改掉别人的投资逻辑。靠人记住一百处等于迟早还会漏，所以把判定
挪进了数据库。

默认就在 PG 上跑；显式设了 `STOCK_TEST_SQLITE=1` 时整个文件跳过
（SQLite 没有行级安全，那条路上隔离仍靠应用层的过滤）。
"""

import os

import pytest

from stock_decision import access, repository
from stock_decision.database import connection, is_postgres
from stock_decision.schemas import CompanyInput, ThesisCreate

pytestmark = pytest.mark.skipif(
    os.environ.get("STOCK_TEST_SQLITE", "").strip().lower() in {"1", "true", "yes", "on"},
    reason="行级安全只有 PostgreSQL 有；这一轮显式跑的是 SQLite")


def in_scope(scope, fn):
    token = access.set_scope(scope)
    try:
        return fn()
    finally:
        access.reset_scope(token)


@pytest.fixture()
def two_users():
    mine = in_scope(access.OWNER_SCOPE, lambda: repository.create_company(
        CompanyInput(symbol="600519", name="站主的票", industry="白酒")))
    in_scope(access.OWNER_SCOPE, lambda: repository.create_thesis(
        mine["id"], ThesisCreate(claim="站主的投资逻辑")))
    theirs = in_scope("user-7", lambda: repository.create_company(
        CompanyInput(symbol="000001", name="别人的票", industry="银行")))
    return mine, theirs


def _bare_query(sql):
    """故意不带任何数据域过滤 —— 模拟「某处忘了加 _sw()」。"""
    def run():
        with connection() as conn:
            return [dict(row) for row in conn.execute(sql).fetchall()]
    return run


def test_rls_is_actually_in_effect():
    """先确认这一层真的开着。

    **不能只看策略建了没有**：策略建好、ENABLE 和 FORCE 都开着，只要连库的角色带
    BYPASSRLS（超级用户默认带，云库主账号通常也带），一条都不生效，而查询照常返回。
    实测踩过——本地 docker 和线上 RDS 的账号都带，装完形同虚设。
    """
    from stock_decision import pgbackend

    status = pgbackend.rls_status()
    assert not status["bypasses_rls"], (
        f"角色 {status['role']} 会绕过 RLS，策略等于没装。"
        "跑 scripts/setup_rls_role.py 换成专用角色。")
    assert status["effective"], status


def test_unfiltered_select_cannot_see_another_users_rows(two_users):
    rows = in_scope("user-7", _bare_query("SELECT name FROM companies ORDER BY id"))
    names = [r["name"] for r in rows]
    assert names == ["别人的票"], f"没写过滤的查询捞到了别人的行：{names}"


def test_child_tables_inherit_ownership_from_their_company(two_users):
    """子表不带 user_id，靠策略里的子查询回溯 —— companies 自己也有策略，所以自动继承。"""
    rows = in_scope("user-7", _bare_query("SELECT claim FROM theses"))
    assert rows == [], f"别人的投资逻辑漏出来了：{rows}"

    rows = in_scope(access.OWNER_SCOPE, _bare_query("SELECT claim FROM theses"))
    assert [r["claim"] for r in rows] == ["站主的投资逻辑"]


def test_every_company_scoped_table_is_actually_covered(two_users):
    """**新加一张挂在公司下面的表，最容易忘的就是把它登记进 RLS 名单。**

    忘了的后果不是报错，是那张表对所有人可见——而从应用这边完全看不出来，
    因为应用层的 `_sw()` 照样在过滤。这条测试遍历名单里的每一张表，
    确认策略真的建上了；名单本身漏登记的话，下面那条针对性的测试会红。
    """
    from stock_decision import pgbackend

    with connection() as conn:
        covered = {row["tablename"] for row in conn.execute(
            f"SELECT tablename FROM pg_tables WHERE schemaname = '{pgbackend.SCHEMA}' "
            f"AND rowsecurity = true").fetchall()}
    missing = [t for t in pgbackend._RLS_COMPANY_TABLES if t not in covered]
    assert not missing, f"这几张表登记了却没真正开上行级安全：{missing}"


def test_management_promises_do_not_leak(two_users):
    """管理层承诺台账是新加的一张挂靠表。

    它记的是「我盯着哪家公司的哪句话」——跟投资逻辑一样，是研究意图，
    漏出去等于把研究方向摊给别人看。
    """
    mine, _ = two_users
    from stock_decision.database import now_iso

    def write():
        with connection() as conn:
            conn.execute(
                """INSERT INTO management_promises
                   (user_id, company_id, promised_on, statement, created_at, updated_at)
                   VALUES ('__owner__', ?, '2026-01-01', '站主记的承诺', ?, ?)""",
                (mine["id"], now_iso(), now_iso()))
    in_scope(access.OWNER_SCOPE, write)

    rows = in_scope("user-7", _bare_query("SELECT statement FROM management_promises"))
    assert rows == [], f"别人的承诺台账漏出来了：{rows}"
    assert in_scope(access.OWNER_SCOPE,
                    _bare_query("SELECT statement FROM management_promises"))


def test_the_scheduler_still_sees_everyone(two_users):
    """系统域必须看得见全部：调度器要替所有人同步数据。

    这条反过来也是防呆——如果哪天把系统域也一起挡了，后台作业会静静地
    什么都同步不到，而作业状态显示「成功」。
    """
    rows = in_scope(None, _bare_query("SELECT name FROM companies ORDER BY id"))
    assert [r["name"] for r in rows] == ["站主的票", "别人的票"]


def test_writing_into_another_users_company_is_refused(two_users):
    mine, _ = two_users
    created = in_scope("user-7", lambda: repository.create_thesis(
        mine["id"], ThesisCreate(claim="插进别人档案的逻辑")))
    assert not created, "把逻辑写进了别人的公司"

    rows = in_scope(access.OWNER_SCOPE, _bare_query("SELECT claim FROM theses"))
    assert [r["claim"] for r in rows] == ["站主的投资逻辑"]


def test_updating_another_users_row_touches_nothing(two_users):
    mine, _ = two_users

    def overwrite():
        with connection() as conn:
            conn.execute("UPDATE companies SET name = 'ָ被改掉了'")   # 没有 WHERE

    in_scope("user-7", overwrite)

    rows = in_scope(access.OWNER_SCOPE, _bare_query("SELECT name FROM companies"))
    assert [r["name"] for r in rows] == ["站主的票"], "别人的一条无 WHERE 的 UPDATE 改到了我的行"


def test_多用户模式下装不上行级安全就不许启动(monkeypatch):
    """**这条以前只是一行 warning。**

    「别人的研究记录可能被读到」跟「某个数据源今天没同步」不是一个量级，
    却用了同一种表达方式——日志里一行黄字，没人会看，服务照常对外。

    行级安全装不上的两种常见原因（角色带 BYPASSRLS、某张表策略建失败）
    都不是"过一会儿会自己好"的问题，继续跑只是把泄漏窗口拉长。
    """
    import pytest

    from stock_decision import access, main, pgbackend
    from stock_decision import database

    monkeypatch.setattr(database, "backend", lambda: "postgres")
    monkeypatch.setattr(main, "initialize_database", lambda: None, raising=False)
    monkeypatch.setattr(access, "mode", lambda: "multi")
    monkeypatch.setattr(pgbackend, "rls_status", lambda: {
        "role": "stocks_app", "bypasses_rls": True,
        "protected_tables": 3, "expected_tables": 40, "effective": False})

    with pytest.raises(RuntimeError) as caught:
        main._refuse_to_serve_without_isolation()
    text = str(caught.value)
    assert "拒绝启动" in text
    # 报错里必须写清怎么修，否则半夜看到它的人只能猜
    assert "setup_rls_role.py" in text and "STOCK_ACCESS" in text


def test_单机与owner模式不受这道闸影响(monkeypatch):
    """本地开发用 SQLite、或者只给站主用时，隔离失效没人能利用它——
    这时候拦启动只会把自己关在门外。"""
    from stock_decision import access, main
    from stock_decision import database

    monkeypatch.setattr(database, "backend", lambda: "sqlite")
    main._refuse_to_serve_without_isolation()      # 不该抛

    monkeypatch.setattr(database, "backend", lambda: "postgres")
    monkeypatch.setattr(access, "mode", lambda: "owner")
    main._refuse_to_serve_without_isolation()      # 也不该抛
