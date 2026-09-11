"""导出说自己是「你手写的记录」，那它就得真的把手写的记录都装进去。

## 2026-08-15 实测

`AUTHORED_TABLES` 是最早那一版写下的七张表，之后加的功能**一张都没跟上**。
线上这个账号当时的实际情况：

    产业链节点 231、边 148、阶段 67、主题 14   一条都没导
    产业链条目（逐条确认过的）21              一条都没导
    方法论自评 8、订阅源 7、分级纠正 2         一条都没导
    研究报告 1（花钱生成的）、研究待办 5       一条都没导

承诺台账、复核记录、我的估值当时是 0 行，所以数字上看不出来，但同样不在里面。

备份没事（SQLite 是整库副本、PG 走 pg_dump，都是全量）。坏的是**导出那份 JSON**，
而页面上跟着一句「只包含你手写的记录与版本历史，来源数据不在其中」——
读起来是"少的只有能重新同步的东西"。**那句话不成立**，
而拿这份 JSON 当存档的人，丢的正是他手写的东西。

## 这个文件守的不是"补齐了"，是"下次漏不掉"

补一次名单只能修好今天。真正的修复是：**每一张按用户隔离的表都必须表态**，
要么在导出名单里，要么在「明确不导」名单里并写明理由。
新加一张表而两边都没进 —— 这里就红。
"""

import pytest

from stock_decision import access, backup
from stock_decision.database import connection, is_postgres
from stock_decision import pgbackend

from test_idor import client, owned  # noqa: F401


def _user_scoped_tables() -> dict[str, set[str]]:
    """库里所有按用户隔离的表 → 它的列。

    判据跟 repository 的 _sw / _swc 一致：自己带 user_id 的，
    或者挂在 company_id 上的（那说明它跟着某家公司走，而公司是按用户分的）。
    """
    out: dict[str, set[str]] = {}
    with connection() as conn:
        tables = backup._existing_tables(conn)
        for table in sorted(tables):
            columns = backup.table_columns(conn, table)
            if "user_id" in columns or "company_id" in columns:
                out[table] = columns
    return out


def test_every_user_table_says_whether_it_is_exported():
    """**「不导」必须是一个被写下来的决定，不能是"忘了加"。**

    这两件事在代码里长得一模一样，而后者正是那十几张表的来历。
    """
    known = set(backup.AUTHORED_TABLES) | set(backup.NOT_EXPORTED) | set(backup.SOURCE_TABLES)
    silent = sorted(set(_user_scoped_tables()) - known)
    assert not silent, (
        f"这几张按用户隔离的表既不在导出名单里，也没被写进「明确不导」：{silent}\n"
        f"  · 它是你手写的（或要你逐条确认过的）→ 加进 AUTHORED_TABLES，"
        f"并在 _SCOPED_BY_USER / _SCOPED_BY_COMPANY 里说清它按哪一列过滤；\n"
        f"  · 它能重新同步或重新生成 → 加进 NOT_EXPORTED，并写一句为什么。\n"
        f"  两边都不填的话，导出会静静地少掉这张表，而页面上写着「你手写的记录」。")


def test_the_lists_do_not_overlap():
    """一张表只能有一个答案。两边都写，读代码的人不知道该信哪个。"""
    both = set(backup.AUTHORED_TABLES) & set(backup.NOT_EXPORTED)
    assert not both, both


def test_every_exported_table_has_a_data_scope_filter():
    """漏一张就是把别人的记录一起导出去，而且导出成功、看起来一切正常。

    `_export_filter` 本来就写着「不认识的一条都不导」，这里把它跑一遍，
    确认新加的每一张都真的有归属判定 —— 而不是等到运行时抛 AssertionError。
    """
    for table in backup.AUTHORED_TABLES:
        clause = backup._export_filter(table)      # 不认识的会在这里抛
        assert "WHERE" in clause, table


def test_the_things_you_cannot_get_back_are_in_the_export():
    """点名守几张：**它们没有一样能重新同步回来。**

    复核记录是你每次复核写下的结论；估值是你自己的三情景假设；
    承诺台账每条都要你确认才入账；产业链是你逐条核验过的关系。
    """
    for table in ("thesis_reviews", "valuations", "management_promises",
                  "supply_chain_links", "industry_chain_nodes", "research_reports",
                  "rule_terms", "inbox_corrections"):
        assert table in backup.AUTHORED_TABLES, f"{table} 重建不回来，却不在导出里"


def test_the_export_actually_carries_the_new_tables(client, owned):  # noqa: F811
    """跑一次真的导出，看新加的那几张有没有真的出现在结果里。

    只断言名单是不够的：名单对了而查询挂了（比如 ORDER BY 一个不存在的列），
    表现同样是"这张表没有内容"。
    """
    client.as_user(access.OWNER_SCOPE)
    with connection() as conn:
        conn.execute(
            """INSERT INTO management_promises
               (user_id, company_id, subject, statement, category, promised_on, status, created_at, updated_at)
               VALUES (?, ?, '公司', '拟回购不低于 3 亿元', '回购', '2026-01-01', '待到期', '2026-01-01', '2026-01-01')""",
            (access.OWNER_SCOPE, owned["company"]))

    payload = backup.export_records()
    assert "management_promises" in payload["records"]
    assert payload["counts"]["management_promises"] >= 1
    # 偏好那张表没有 id 列，一句写死的 ORDER BY id 会让整个导出 500
    assert "user_settings" in payload["records"]


def test_a_stranger_still_only_gets_his_own(client, owned):  # noqa: F811
    """名单变长了，数据域过滤不能跟着松。**这一条比补齐名单更要紧**：
    补漏是少给，漏过滤是多给，而多给的那次没人会发现。"""
    client.as_user(access.OWNER_SCOPE)
    with connection() as conn:
        conn.execute(
            """INSERT INTO management_promises
               (user_id, company_id, subject, statement, category, promised_on, status, created_at, updated_at)
               VALUES (?, ?, '公司', '站主的承诺', '回购', '2026-01-01', '待到期', '2026-01-01', '2026-01-01')""",
            (access.OWNER_SCOPE, owned["company"]))
        conn.execute(
            """INSERT INTO supply_chain_links
               (company_id, relation, counterpart, segment, detail, confidence, source, created_at)
               VALUES (?, '上游', '站主的供应商', '原料', '站主记的', '待核验', '手工', '2026-01-01')""",
            (owned["company"],))

    # 数据域是 contextvar，正常由中间件按请求设；这里直接调导出函数，
    # 所以手动切过去 —— 换个人来跑同一段代码，正是这一条要问的问题。
    token = access.set_scope("user-9")
    try:
        payload = backup.export_records()
    finally:
        access.reset_scope(token)

    for table in ("companies", "management_promises", "supply_chain_links", "theses"):
        assert payload["records"].get(table) == [], f"别人的 {table} 被一起导出去了"
    # 而「不导」那几张连键都不该出现
    assert "background_jobs" not in payload["records"]
