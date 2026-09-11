"""备份必须用一个能看见所有行的角色。

## 为什么单独测这个

开了行级安全之后，应用角色只看得见当前数据域的行。用它跑 pg_dump，
两种坏法都可能：

· 表上有 FORCE RLS —— 数据库直接拒绝（"query would be affected by row-level
  security policy"），备份根本建不出来。CI 上就是这样，红了一整天。
· 表上没有 FORCE RLS —— **备份成功、大小正常、内容残缺**。
  这种坏法要等到真去恢复的那天才会发现，那时已经晚了。

真正跑一次备份的那条测试（test_backup_and_restore_verifies_record_counts）
在开发机上是 skip 的：它要求 pg_dump 与服务端大版本一致，而本机常常对不上。
**一条在开发机永远跳过、在 CI 永远失败的测试，等于没有测试。**

所以这里不跑 pg_dump，只检查那个前提条件——不依赖任何外部二进制，
开发机和 CI 上都会真的执行。
"""

import os

import pytest

from stock_decision.database import is_postgres


@pytest.mark.skipif(not is_postgres(), reason="行级安全只有 PostgreSQL 有")
def test_backup_uses_a_role_that_sees_everything():
    from stock_decision import pgbackend

    app_user = pgbackend.dsn()["user"]
    backup_user = pgbackend.admin_dsn()["user"]

    assert backup_user != app_user, (
        f"备份用的还是应用角色 {app_user}。它受行级安全约束，"
        "pg_dump 要么被数据库拒绝，要么导出一份内容残缺的备份——"
        "而后者要等到真去恢复的那天才会发现。请配 PG_ADMIN_USER。"
    )


@pytest.mark.skipif(not is_postgres(), reason="行级安全只有 PostgreSQL 有")
def test_the_app_role_really_cannot_bypass_row_security():
    """顺带钉住整个隔离测试的前提。

    带 BYPASSRLS 的角色会让所有策略形同虚设，而**从应用这边完全看不出来**：
    查询照常返回，只是返回了所有人的行。用那种角色跑，隔离测试会全绿而线上真出事。
    """
    from stock_decision import pgbackend

    with pgbackend.connect() as conn:
        row = conn.execute(
            "SELECT rolbypassrls AS bypass FROM pg_roles WHERE rolname = current_user"
        ).fetchone()

    assert row["bypass"] is False, (
        "测试角色带 BYPASSRLS —— 行级安全策略对它形同虚设，"
        "隔离测试会全绿而线上真出事。"
    )


def test_admin_credentials_are_configured_for_tests():
    """CI 上没有 .env，凭据得由 conftest 自己补上。

    补不上时备份测试会失败，而失败信息（"assert 422 == 201"）跟真正的原因
    ——测试环境没配管理员——离得很远。在这里说清楚。
    """
    if not is_postgres():
        pytest.skip("SQLite 备份不需要额外凭据")

    assert os.environ.get("PG_ADMIN_USER"), (
        "PG_ADMIN_USER 没有设置。conftest 应当把管理员凭据传给备份模块，"
        "否则 pg_dump 会以受 RLS 约束的测试角色运行。"
    )
