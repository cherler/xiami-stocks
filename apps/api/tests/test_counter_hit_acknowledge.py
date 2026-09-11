"""反证命中一旦出现就消不掉 —— 因为"确认"那个动作从来没接上。

`CounterHitBanner` 自己的文档写着：

    横幅不阻断你做别的事，但**在你确认之前它不消失** ——
    换页、刷新、明天再来，它都还在。

而确认的按钮一直没有：`POST /counter-hits/{id}/acknowledge` 从第一天就在，
前端一次都没调过（2026-08-15 普查：178 条路由里前端一处都搜不到的有 12 条）。
`acknowledged` 只有那一个接口能置 1，所以命中一旦出现就永远是"未处理"，
侧栏那个徽章也永远清不掉。

这恰恰是这个徽章当初要避开的东西 —— schemas.py 里写着：
「未读公告长期停在 646——一个永远清不完的红点第三天就成了背景色」。
为了避开它而做的徽章，自己成了一个永远清不完的红点。
"""

from stock_decision import access
from stock_decision.database import connection
from stock_decision.repository import open_counter_hits

from test_idor import client, owned  # noqa: F401


def _a_hit(client, owned):  # noqa: F811
    """造一条真实形状的命中：一条带认错条件的判断 + 一条公告 + 一条命中。"""
    client.as_user(access.OWNER_SCOPE)
    thesis = client.post(f"/api/v1/companies/{owned['company']}/theses", json={
        "claim": "赌定价权还在", "counter_condition": "2026 年中报毛利率跌破 27%"}).json()
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO company_calendar_events
               (company_id, category, title, event_date, source, refreshed_at, inbox_status)
               VALUES (?, '公告', ?, '2026-08-15', '测试', '2026-08-15', '待核验')""",
            (owned["company"], "毛利率跌破 27%"))   # % 必须走参数：psycopg2 会把它当占位符
        event_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO counter_hits (user_id, event_id, thesis_id, clause, reason, created_at)
               VALUES (?, ?, ?, ?, ?, '2026-08-15T10:00:00')""",
            (access.OWNER_SCOPE, event_id, thesis["id"], "毛利率跌破 27%", "公告里写了 26.4%"))
    return open_counter_hits()[0]["id"]


def test_a_hit_can_be_settled(client, owned):  # noqa: F811
    """能确认掉 —— 否则这条提醒会一直挂着，第三天就成了背景色。"""
    hit_id = _a_hit(client, owned)
    assert len(open_counter_hits()) == 1
    assert client.post(f"/api/v1/counter-hits/{hit_id}/acknowledge").status_code < 400
    assert open_counter_hits() == [], "确认过了还挂在那儿"


def test_the_dashboard_badge_goes_down_with_it(client, owned):  # noqa: F811
    """徽章数就是未处理命中数 —— 处理完必须跟着掉，不然徽章永远清不了。"""
    hit_id = _a_hit(client, owned)
    assert client.get("/api/v1/dashboard").json()["counter_hits"] == 1
    client.post(f"/api/v1/counter-hits/{hit_id}/acknowledge")
    assert client.get("/api/v1/dashboard").json()["counter_hits"] == 0


def test_the_frontend_actually_calls_it():
    """**这条盯的是"有没有人调"，不是"接口对不对"。**

    接口一直是对的；坏的是它没有调用方。所以这里直接查前端源码 ——
    这一类失败的形状恰恰是后端全绿、页面上没有那个按钮。
    """
    import pathlib

    web = pathlib.Path(__file__).resolve().parents[2] / "web" / "src"
    src = "\n".join(p.read_text(encoding="utf8")
                    for p in list(web.rglob("*.ts")) + list(web.rglob("*.tsx")))
    assert "counter-hits/${" in src or "acknowledgeCounterHit" in src, \
        "前端没有任何地方会确认一条命中 —— 那条横幅将永远不消失"
