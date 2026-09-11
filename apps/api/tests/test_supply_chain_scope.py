"""产业链条目的改与删，**一个数据域过滤都没有**。

`supply_chain_links` 自己不带 user_id，它挂在 company_id 上，所以过滤要走 `_swc()`
（跟收件箱同一种形状）。而这两个函数是这么写的：

    UPDATE supply_chain_links SET confidence='已证实' ... WHERE id = ?
    DELETE FROM supply_chain_links               WHERE id = ?

隔壁 `delete_report` 就写对了，注释还专门解释过为什么：
「**必须限定在自己的公司下** —— 只按 id 删的话，换个 id 就能删掉别人的报告，
而且删了不留痕」。同一句话原样适用于这里。

拿真实 id 打，不是拿 999999 打 —— 后者返回 200 只说明"没匹配到"，
证明不了任何事。

**补过滤之前这两条也是绿的** —— 兜住它的是 Postgres 的 RLS。
所以这个文件守的是「行为」而不是「某一层实现」：RLS 哪天被绕过、
或者走 SQLite 那条路（本地单机、备份还原）时，它照样该红。
"""

import pytest

from stock_decision.database import connection
from stock_decision import access

from test_idor import client, owned  # noqa: F401


@pytest.fixture()
def a_link(client, owned):  # noqa: F811
    """站主名下建一条产业链条目，返回它的 id。"""
    client.as_user(access.OWNER_SCOPE)
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO supply_chain_links
               (company_id, relation, counterpart, segment, detail, confidence, source, created_at)
               VALUES (?, '上游', '站主的供应商', '原料', '站主记的', '待核验', '手工', '2026-08-14')""",
            (owned["company"],))
        return int(cur.lastrowid)


def _link(link_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT confidence FROM supply_chain_links WHERE id = ?", (link_id,)).fetchone()
    return dict(row) if row else None


def test_a_stranger_cannot_confirm_my_supply_chain_link(client, a_link):  # noqa: F811
    """别人不能把我一条"待核验"的关系拍板成"已证实"。

    这条比听起来严重：产业链页是用来判断"这家公司靠谁吃饭"的，
    一条被冒名坐实的上下游关系会直接改变读图的人的结论。
    """
    client.as_user("user-9")
    client.post(f"/api/v1/supply-chain/{a_link}/confirm")
    assert _link(a_link)["confidence"] == "待核验", "别人把我的条目改成已证实了"


def test_a_stranger_cannot_delete_my_supply_chain_link(client, a_link):  # noqa: F811
    """删了不留痕 —— 站主下次打开产业链页只会觉得"我好像没记过这条"。"""
    client.as_user("user-9")
    client.delete(f"/api/v1/supply-chain/{a_link}")
    assert _link(a_link) is not None, "别人把我的条目删掉了"
