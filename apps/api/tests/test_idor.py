"""越权实测：拿着别人的记录 id 直接调接口，能不能读到、改到。

**这类问题静态看代码看不出来。** `SELECT * FROM theses WHERE id = ?` 单看没有毛病，
它安不安全取决于调用它之前有没有先按数据域查过一遍。全仓有九十多条这样的语句，
逐条读要么漏、要么把安全的也当成问题。所以这里改成：站主建一份数据，
换个身份把每条带 id 的路由都打一遍，看会不会漏出去。

判定标准是「拿不到」，不是某个具体状态码：404（装作不存在）和 403（明确拒绝）
都算合格，200 才是漏。删除类接口即使返回 200 也要确认对象还在。
"""

import pytest
from fastapi.testclient import TestClient

from stock_decision import access
from stock_decision.main import app


@pytest.fixture()
def client(monkeypatch):
    """让请求以指定数据域进入。默认站主，调 as_user() 切成别人。"""
    state = {"scope": access.OWNER_SCOPE, "is_owner": True}

    def fake_check(_cookie):
        return {"user": {"user_id": state["scope"]}, "scope": state["scope"],
                "is_owner": state["is_owner"]}

    monkeypatch.setattr(access, "check", fake_check)
    c = TestClient(app)

    def as_user(scope):
        state["scope"] = scope
        state["is_owner"] = scope == access.OWNER_SCOPE

    c.as_user = as_user
    return c


@pytest.fixture()
def owned(client):
    """站主建一整套记录，返回各自的 id。"""
    client.as_user(access.OWNER_SCOPE)

    company = client.post("/api/v1/companies", json={
        "symbol": "600519", "name": "站主的票", "industry": "白酒"}).json()
    thesis = client.post(f"/api/v1/companies/{company['id']}/theses",
                         json={"claim": "站主的投资逻辑"}).json()
    event = client.post(f"/api/v1/companies/{company['id']}/events", json={
        "category": "经营", "title": "站主的事件", "occurred_at": "2026-08-05"}).json()
    portfolio = client.post("/api/v1/portfolios", json={"name": "站主的组合"}).json()
    # 组合默认是「只记仓位占比、不记金额」模式，所以交易填 weight_percent。
    trade = client.post(f"/api/v1/portfolios/{portfolio['id']}/trades", json={
        "company_id": company["id"], "side": "buy", "weight_percent": 10.0,
        "trade_date": "2026-08-05", "rationale": "站主买入的理由"}).json()

    task = client.post("/api/v1/tasks", json={
        "title": "站主的研究任务", "company_id": company["id"]}).json()
    feed = client.post("/api/v1/news/feeds", json={
        "name": "站主的新闻源", "url": "https://example.com/rss"}).json()
    # key 只接受小写字母数字下划线；rules / sort_field 是必填
    client.post("/api/v1/screen/strategies", json={
        "key": "owner_strategy", "name": "站主的策略", "sort_field": "roe",
        "rules": [{"field": "roe", "op": "gte", "value": 15.0}]})

    return {"company": company["id"], "thesis": thesis["id"], "event": event["id"],
            "portfolio": portfolio["id"], "trade": trade["id"],
            "task": (task or {}).get("id", 0), "feed": (feed or {}).get("id", 0)}


def _leaked(response) -> bool:
    """这次调用算不算漏了。"""
    return response.status_code < 400


# (方法, 路径模板, 请求体) —— 路径里的 {x} 用 owned 里的 id 填
CROSS_USER_ATTEMPTS = [
    ("GET", "/api/v1/companies/{company}", None),
    ("PATCH", "/api/v1/companies/{company}", {"name": "被改掉了"}),
    ("GET", "/api/v1/companies/{company}/supply-chain", None),
    ("POST", "/api/v1/companies/{company}/theses", {"claim": "插进别人档案"}),
    ("POST", "/api/v1/companies/{company}/events",
     {"category": "经营", "title": "插进别人档案", "occurred_at": "2026-08-05"}),
    ("POST", "/api/v1/companies/{company}/evidences",
     {"source_name": "x", "excerpt": "y", "polarity": "support", "occurred_at": "2026-08-05"}),
    ("PATCH", "/api/v1/theses/{thesis}", {"claim": "被改掉了"}),
    ("GET", "/api/v1/theses/{thesis}/review-context", None),
    ("GET", "/api/v1/theses/{thesis}/revisions", None),
    ("PATCH", "/api/v1/events/{event}", {"title": "被改掉了"}),
    ("GET", "/api/v1/portfolios/{portfolio}", None),
    ("PATCH", "/api/v1/portfolios/{portfolio}", {"name": "被改掉了"}),
    ("PATCH", "/api/v1/trades/{trade}", {"weight_percent": 99.0}),
    ("GET", "/api/v1/trades/{trade}/revisions", None),
    # 后台任务：拿别人的公司 id 触发同步 / 起草 / 生成报告，都会替他花积分
    ("POST", "/api/v1/companies/{company}/profile/refresh", None),
    ("POST", "/api/v1/companies/{company}/financials/refresh", None),
    ("POST", "/api/v1/companies/{company}/market-history/refresh", None),
    ("POST", "/api/v1/companies/{company}/valuation/refresh", None),
    ("POST", "/api/v1/companies/{company}/supply-chain/refresh", None),
    # **这一组是后台任务接口，最容易漏掉归属检查。**
    #
    # 同步接口里检查天然在返回值前面（查不到就 404）；改成后台任务之后，
    # submit() 在任务开跑前就返回 200，检查跑到任务内部——于是别人的公司
    # 也能提交一个任务。thesis-draft 从同步改成后台任务时就这么漏过一次，
    # 是这条测试抓住的。剩下五个当时不在清单里，一起补上。
    ("POST", "/api/v1/companies/{company}/thesis-draft", None),
    ("POST", "/api/v1/companies/{company}/promises/extract", None),
    ("POST", "/api/v1/companies/{company}/advocate", {"question": "问一句"}),
    ("POST", "/api/v1/companies/{company}/deep-report", None),
    ("POST", "/api/v1/companies/{company}/supply-chain", None),
    ("POST", "/api/v1/companies/{company}/report", None),
    ("POST", "/api/v1/companies/{company}/reports", None),
    ("POST", "/api/v1/theses/{thesis}/reviews",
     {"verdict": "维持", "note": "别人写的复核"}),
    # 往别人的组合里写交易 —— 直接污染他的持仓
    ("POST", "/api/v1/portfolios/{portfolio}/trades",
     {"company_id": 1, "side": "buy", "weight_percent": 5.0,
      "trade_date": "2026-08-05", "rationale": "塞进别人组合的交易"}),
    # 研究任务与新闻源
    ("GET", "/api/v1/tasks/{task}", None),
    ("PATCH", "/api/v1/tasks/{task}", {"title": "被改掉了"}),
    ("POST", "/api/v1/research-tasks/{task}/auto-review", None),
    ("PATCH", "/api/v1/news/feeds/{feed}", {"name": "被改掉了"}),
]


@pytest.mark.parametrize("method,template,body", CROSS_USER_ATTEMPTS,
                         ids=[f"{m} {t}" for m, t, _ in CROSS_USER_ATTEMPTS])
def test_another_user_cannot_reach_my_records(client, owned, method, template, body):
    client.as_user("user-7")
    path = template.format(**owned)
    response = client.request(method, path, json=body)
    assert not _leaked(response), (
        f"{method} {path} 返回 {response.status_code}，别人的记录漏出去了："
        f"{response.text[:200]}")


# 这几个接口用 200 表达「没做成」（批量逐条报错、删除返回 deleted:false）。
# 判据只看状态码会把它们误判成漏，所以单独按**效果**验：东西还在、没写进去。
def test_batch_trade_cannot_be_written_into_someone_elses_portfolio(client, owned):
    client.as_user("user-7")
    response = client.post(f"/api/v1/portfolios/{owned['portfolio']}/trades/batch", json={
        "trades": [{"company_id": owned["company"], "side": "buy", "weight_percent": 5.0,
                    "trade_date": "2026-08-05", "rationale": "批量塞进别人组合"}]})
    assert response.json()["created"] == [], "交易被写进了别人的组合"


def test_deleting_someone_elses_news_feed_does_nothing(client, owned):
    client.as_user("user-7")
    client.delete(f"/api/v1/news/feeds/{owned['feed']}")

    client.as_user(access.OWNER_SCOPE)
    names = [f["name"] for f in client.get("/api/v1/news/feeds").json()]
    assert "站主的新闻源" in names, "别人把站主的新闻源删掉了"


def test_screen_strategy_of_another_user_cannot_be_deleted(client, owned):
    client.as_user("user-7")
    client.delete("/api/v1/screen/strategies/owner_strategy")

    client.as_user(access.OWNER_SCOPE)
    keys = [s["key"] for s in client.get("/api/v1/screen/strategies").json()]
    assert "owner_strategy" in keys, "别人把站主的选股策略删掉了"


def test_inbox_actions_do_not_touch_another_users_items(client, owned):
    """收件箱条目挂在公司下面，自己不带 user_id —— 正是最容易漏过滤的形状。"""
    client.as_user(access.OWNER_SCOPE)
    inbox = client.get("/api/v1/inbox").json()
    items = inbox.get("items") or []
    if not items:
        pytest.skip("这个库里没有收件箱条目可测")
    item_id = items[0]["id"]

    client.as_user("user-7")
    for action in ("archive", "ignore", "reopen"):
        response = client.post(f"/api/v1/inbox/{item_id}/{action}")
        body = response.json() if response.status_code < 400 else {}
        assert response.status_code >= 400 or not body.get("ok", True), (
            f"user-7 对别人的收件箱条目做了 {action}：{response.status_code} {response.text[:120]}")


def test_scheduler_jobs_are_owner_only(client, owned):
    """定时任务是**整个实例**的，不是某个人的。

    普通用户能改间隔、能手动触发，等于替所有人改后台行为、替所有人花钱。
    """
    client.as_user("user-7")
    assert client.patch("/api/v1/sync/jobs/quotes",
                        json={"enabled": False}).status_code == 403
    assert client.post("/api/v1/sync/jobs/quotes/run").status_code == 403


def test_the_owner_can_still_reach_them(client, owned):
    """守卫别把主人自己挡在门外 —— 这才是回归测试该盯的另一半。"""
    client.as_user(access.OWNER_SCOPE)
    assert client.get(f"/api/v1/companies/{owned['company']}").status_code == 200
    assert client.get(f"/api/v1/portfolios/{owned['portfolio']}").status_code == 200
    assert client.get(f"/api/v1/theses/{owned['thesis']}/revisions").status_code == 200


def test_listing_endpoints_do_not_mix_users(client, owned):
    client.as_user("user-7")
    assert client.get("/api/v1/companies").json() == []

    # 组合列表不能断言为空：首次访问会给这个用户自动建一个「主组合」。
    # 要断言的是他看不到**站主那个**。
    names = [p["name"] for p in client.get("/api/v1/portfolios").json()]
    assert "站主的组合" not in names, f"看到了别人的组合：{names}"


def test_instance_wide_endpoints_reject_non_owners(client, owned):
    client.as_user("user-7")
    # /export 也在这一组里：它的手写记录是按数据域过滤的，
    # 但 source_counts 报的是**整库**条目数（valuation_points 18600 这种），
    # 而同样性质的 /local-data 一直是站主专属 —— 两处口径要一致。
    for path in ("/api/v1/backups", "/api/v1/local-data", "/api/v1/export",
                 # 同步任务是这台实例的运维面板：排期、上次成功、每次取回多少条、立即运行。
                 # 改和触发早就挡住了，**读一直敞着** —— 游客照样看得见整台机器的作息。
                 "/api/v1/sync/jobs", "/api/v1/sync/strip", "/api/v1/sync/runs",
                 # 订阅源是整个实例的配置：加一条，所有人的资讯证据都会多这个来源。
                 "/api/v1/news/feeds"):
        assert client.get(path).status_code == 403, f"{path} 对非站主开着"


def test_feed_config_is_not_writable_by_non_owners(client, owned):
    """订阅源的写入此前**一个守卫都没有**。

    游客被「只读」中间件挡着，所以从公网看不出问题；
    但任何**登录了的**非站主都能给全站加源、删源 —— 那不是他的数据。
    """
    client.as_user("user-7")
    assert client.post("/api/v1/news/feeds", json={"name": "混进来的源", "url": "https://example.com/rss.xml"}).status_code == 403
    assert client.delete("/api/v1/news/feeds/1").status_code == 403


# ──────────────────────────────────────────────────────────────────
# 路由普查：每个 GET 接口都必须被表过态
#
# 每个 GET 接口都必须**被表过态**：要么写进下面的清单，要么挡住非站主。
#
# ## 为什么要有这道普查
#
# 原来只有一张手写的 `test_instance_wide_endpoints_reject_non_owners`，
# 里面列着几个已知要挡的路径。它的问题是**加新接口的人不会想起来去改它** ——
# 实测就这么漏了七个：
#
#     GET /api/v1/sync/jobs · /sync/strip · /sync/runs   整台机器的排期与作息
#     GET/POST/PATCH/DELETE /api/v1/news/feeds           整个实例的订阅源配置
#
# 改间隔、手动触发这些**写操作**早就挂了 require_owner，唯独读一直敞着；
# 而订阅源连写都没挂 —— 游客被「只读」中间件挡住，所以从公网看不出问题，
# 但任何**登录了的**非站主都能给全站加源、删源。使用者是自己用游客身份点进
# 设置页才发现的：同步排期、上次成功时间、每次取回多少条，明晃晃摆在那儿。
#
# 所以这道测试反过来做：**枚举所有 GET 路由**，非站主身份逐个打一遍，
# 凡是没被挡住的，必须出现在下面的 `PER_USER` 里并写清为什么可以给他看。
# 加了新接口而没表态 → 这里红 → 你必须回答「这个接口给谁看」。
#
# ## 为什么只查 GET
#
# 写操作有副作用，不能盲打。而且这次的洞恰恰全在读那一侧：
# 「写挡住了所以安全」是个很容易上当的直觉 —— 排期、条数、来源列表本身就是信息。
# 写那一侧由 `test_feed_config_is_not_writable_by_non_owners` 这类针对性用例覆盖。

# ── 允许非站主读的接口 ──────────────────────────────────────────
#
# 每一条都要能回答「凭什么给他看」。**只写前缀，不写正则** —— 看得懂比灵活重要。
PER_USER = {
    # 他自己的研究数据（按 access 的数据域过滤，各看各的）
    #
    # documents：他自己上传/贴链接读进来的文件。**按用户隔离，不是全局一份** ——
    # 跟公告正文（谁读都是同一份，进 _GLOBAL_MARKET_TABLES）不同，
    # 上传的可能是未公开的调研纪要。列表和详情都走 _sw()，各看各的。
    "/api/v1/documents",
    "/api/v1/companies", "/api/v1/portfolios", "/api/v1/theses", "/api/v1/trades",
    "/api/v1/events", "/api/v1/reviews", "/api/v1/tasks", "/api/v1/research-tasks",
    "/api/v1/dashboard", "/api/v1/screener", "/api/v1/news", "/api/v1/methods",
    "/api/v1/industries", "/api/v1/heatmap", "/api/v1/chains", "/api/v1/industry-chains",
    "/api/v1/reports", "/api/v1/jobs", "/api/v1/strategies", "/api/v1/evidences",
    "/api/v1/announcements", "/api/v1/notes", "/api/v1/valuation", "/api/v1/peers",
    # 全市场公开资料：行情、财务、公司简况 —— 谁看都一样，不按人分
    "/api/v1/market", "/api/v1/quotes", "/api/v1/universe", "/api/v1/prices",
    "/api/v1/data-providers", "/api/v1/samples", "/api/v1/settings", "/api/v1/preferences",
    # 身份与健康：页面靠它决定给登录引导还是给建档入口
    "/api/v1/access", "/api/v1/credits", "/api/v1/rum", "/api/v1/counter-hits",
    # 他自己那份的加工视图：体检矩阵、归因、简报、决策台、收件箱 —— 都按数据域过滤
    "/api/v1/assessment-matrix", "/api/v1/attribution", "/api/v1/briefing",
    "/api/v1/decision-board", "/api/v1/inbox", "/api/v1/quick-thesis",
    # 选股与候选：跑在全市场公开数据上，各人存各人的策略与结果
    "/api/v1/screen", "/api/v1/value-candidates",
    # 全市场的统计口径，不涉及任何人的记录
    "/api/v1/sentiment", "/api/v1/trend",
}


def _get_routes() -> list[str]:
    out = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.startswith("/api/v1/") and "GET" in methods:
            out.append(path)
    return sorted(set(out))


@pytest.mark.parametrize("path", _get_routes())
def test_every_get_route_is_classified(client, owned, path):
    client.as_user("user-7")
    # 路径参数塞一个不存在的 id：守卫跑在查库之前，所以挡没挡得住跟 id 无关。
    concrete = path
    while "{" in concrete:
        head, _, rest = concrete.partition("{")
        _, _, tail = rest.partition("}")
        concrete = f"{head}999999{tail}"

    status = client.get(concrete).status_code
    if status == 403:
        return  # 挡住了，无需表态

    assert any(concrete.startswith(prefix) for prefix in PER_USER), (
        f"{path} 对非站主开着（{status}），但它不在 PER_USER 名单里。\n"
        f"  · 如果它是「他自己的数据」或「全市场公开资料」→ 加进 PER_USER，并在那儿写清凭什么；\n"
        f"  · 如果它是整台实例的配置或运维信息（排期、来源、备份…）→ 加 access.require_owner。\n"
        f"  这道题必须回答，不能跳过 —— 同步任务和订阅源就是这么漏出去的。"
    )
