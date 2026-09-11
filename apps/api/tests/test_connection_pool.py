"""连接池：复用连接不能把身份带给下一个人。

**这是池化最危险的地方。** `app.scope` 是会话变量，跟着连接走而不是跟着请求走。
借出去的连接如果还留着上一个人的 scope，下一个请求就会以别人的身份查库——
而且它取决于谁先谁后，同样的代码时对时错，比忘了加 WHERE 难查得多。

所以身份在**每次借出时重设**，这个文件就是钉住这件事。
"""

import os

import pytest

from stock_decision import access, pgbackend
from stock_decision.database import connection
from stock_decision.schemas import CompanyInput

pytestmark = pytest.mark.skipif(
    os.environ.get("STOCK_TEST_SQLITE", "").strip().lower() in {"1", "true", "yes", "on"},
    reason="连接池是 PostgreSQL 后端的东西")


def in_scope(scope, fn):
    token = access.set_scope(scope)
    try:
        return fn()
    finally:
        access.reset_scope(token)


def _scope_seen_by_database():
    with connection() as conn:
        return conn.execute(
            "SELECT current_setting('app.scope', true) AS s").fetchone()["s"]


def test_reused_connection_carries_the_current_identity():
    """交替切换身份，每次拿到的都必须是当下这个，不是上一次留下的。"""
    for scope in ("__owner__", "user-a", "__owner__", "user-b", "user-b", "__owner__"):
        assert in_scope(scope, _scope_seen_by_database) == scope


def test_rows_follow_the_current_identity_not_the_previous_one():
    """光看变量还不够——要确认策略真的按当下身份过滤。"""
    in_scope(access.OWNER_SCOPE, lambda: __import__(
        "stock_decision.repository", fromlist=["x"]).create_company(
        CompanyInput(symbol="600519", name="站主的票", industry="白酒")))

    def count():
        with connection() as conn:
            return len(conn.execute("SELECT id FROM companies").fetchall())

    assert in_scope(access.OWNER_SCOPE, count) == 1
    assert in_scope("user-a", count) == 0
    assert in_scope(access.OWNER_SCOPE, count) == 1, "连上一次借出的身份被带过来了"


def test_connections_are_actually_reused():
    """确认池子真的在复用 —— 否则上面两条测的是「每次新建」，等于没测到风险。"""
    pgbackend.close_pool()
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()
    bucket = pgbackend._POOL[pgbackend._pool_key()]
    assert len(bucket) == 1

    reused = bucket[0]
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()
    assert pgbackend._POOL[pgbackend._pool_key()][0] is reused, "没有复用，池化没生效"


def test_the_pool_is_keyed_by_credentials():
    """换了账号就不能复用上一个账号的连接。

    这条是补的：第一版池子只有一个列表，测试在角色之间切换时拿到了上一个角色的
    连接，报出来是一句跟当前代码毫无关系的 permission denied。
    """
    import os

    pgbackend.close_pool()
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()
    first_key = pgbackend._pool_key()

    saved = os.environ.get("PG_USER")
    os.environ["PG_USER"] = "someone_else"
    try:
        assert pgbackend._pool_key() != first_key, "换了账号却算出同一个池子的键"
    finally:
        if saved is None:
            os.environ.pop("PG_USER", None)
        else:
            os.environ["PG_USER"] = saved


def test_a_dead_connection_is_replaced_transparently():
    """PG 那边掐掉连接（超时、重启）时，借出方不该看到报错。"""
    pgbackend.close_pool()
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()

    pgbackend._POOL[pgbackend._pool_key()][0].close()   # 模拟对面把它掐了

    with connection() as conn:          # 不该抛
        assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


def test_uncommitted_work_is_not_handed_to_the_next_borrower():
    """借出去的连接不能带着上一个人没提交的事务。"""
    pgbackend.close_pool()
    try:
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
            raise RuntimeError("模拟请求中途出错")
    except RuntimeError:
        pass

    with connection() as conn:
        # 还留着未结事务的话，这里会报 InFailedSqlTransaction
        assert conn.execute("SELECT 2 AS ok").fetchone()["ok"] == 2
