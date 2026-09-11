"""按名字找公司——搜索栏和建档共用的那一条路。

## 两件事在这里汇合

**一是搜索栏一搜就 500。** `list_companies` 把 companies 和 market_snapshots
join 起来，两张表都有 symbol，而 WHERE 里写的是不带前缀的 `symbol LIKE ?`，
PostgreSQL 报 AmbiguousColumn。

那一笔修完之后我在文件头写了一句「本仓测试跑 SQLite、线上跑 PG，所以拦不住」——
**这句是错的。** conftest 从 3f645ab（2026-08-10）起默认就跑 PostgreSQL。
真正的原因平淡得多：**从来没有一条测试给 /api/v1/companies 带过 query。**
不是数据库不对，是那条路没人走过。所以这里补的是行为测试，不是源码扫描器。

**二是"想研究哪家"永远发生在建档之前。** 搜索只搜已建档的公司，
于是搜「宁德时代」什么也搜不到——不是没这家公司，是你还没建它的档。
而建档那一栏又只认六位代码。`lookup_universe` 走全市场底座，
本地一条 SQL，不联网、不调模型、不计费。
"""

from fastapi.testclient import TestClient

from stock_decision.database import connection, now_iso
from stock_decision.main import app

client = TestClient(app)


def _seed(rows: list[tuple[str, str, str, float]]) -> None:
    """(代码, 名称, 行业, 总市值)"""
    with connection() as conn:
        for symbol, name, industry, cap in rows:
            conn.execute(
                """INSERT INTO market_universe (symbol, name, exchange, board, industry,
                       price, change_percent, total_market_cap, updated_at)
                   VALUES (?, ?, '上海证券交易所', '主板', ?, 10.0, 1.5, ?, ?)""",
                (symbol, name, industry, cap, now_iso()))


def test_搜索已建档公司带上关键词不会五百():
    """join 之后的裸列名在 PG 上是 AmbiguousColumn。**这条路必须有人走过。**"""
    assert client.get("/api/v1/companies", params={"query": "茅台"}).status_code == 200
    assert client.get("/api/v1/companies", params={"query": "600519"}).status_code == 200
    assert client.get("/api/v1/companies", params={"query": "白酒"}).status_code == 200
    assert client.get("/api/v1/companies").status_code == 200


def test_按名字能在全市场里找到还没建档的公司():
    _seed([("300750", "宁德时代", "电池", 1.1e12)])

    rows = client.get("/api/v1/universe/lookup", params={"q": "宁德"}).json()

    assert [row["symbol"] for row in rows] == ["300750"]
    assert rows[0]["name"] == "宁德时代"
    assert rows[0]["in_archive"] is False, "还没建档，不该说已经在档案里"
    assert rows[0]["company_id"] is None


def test_已经建过档的显示成打开而不是再建一遍():
    _seed([("600519", "贵州茅台", "白酒Ⅱ", 1.6e12)])
    created = client.post("/api/v1/companies/from-quote", json={
        "symbol": "600519", "watch_group": "观察池", "description": ""})
    if created.status_code != 201:                     # 行情源不可达时退回手工建档
        created = client.post("/api/v1/companies", json={
            "name": "贵州茅台", "symbol": "600519", "exchange": "上海证券交易所",
            "industry": "白酒", "watch_group": "观察池"})
    assert created.status_code == 201, created.text

    row = client.get("/api/v1/universe/lookup", params={"q": "贵州茅台"}).json()[0]

    assert row["in_archive"] is True
    assert row["company_id"] == created.json()["id"]


def test_代码精确的排在最前名称开头的排在包含之前():
    """搜「中国」会命中一堆，顺序得是"你多半在找哪个"。"""
    # **市值故意反着给**：名字中间命中的那家市值最大。要是排序只按市值，
    # 「石油中国」就会排到「中国银行」前面——这条断言才真的在验开头优先。
    _seed([
        ("601988", "中国银行", "银行Ⅱ", 1.2e12),
        ("601857", "石油中国", "石油开采", 9.9e12),
        ("600030", "中信证券", "证券Ⅱ", 3.0e11),
    ])

    names = [row["name"] for row in client.get(
        "/api/v1/universe/lookup", params={"q": "中国"}).json()]

    assert names[0] == "中国银行", "名称开头命中的要排在名称中间命中的前面"
    assert names.index("中国银行") < names.index("石油中国")

    exact = client.get("/api/v1/universe/lookup", params={"q": "600030"}).json()
    assert exact[0]["symbol"] == "600030", "代码精确命中要排第一"


def test_重名靠行业和市值区分():
    """「中国电建」和「中国电研」光看名字分不清，所以这两个字段必须回。"""
    _seed([("601669", "中国电建", "基础建设", 1.0e11), ("688128", "中国电研", "仪器仪表", 2.0e10)])

    rows = client.get("/api/v1/universe/lookup", params={"q": "中国电"}).json()

    assert {row["industry"] for row in rows} == {"基础建设", "仪器仪表"}
    assert all(row["total_market_cap"] for row in rows)
    assert [row["symbol"] for row in rows] == ["601669", "688128"], "同一档里按市值从大到小"


def test_空查询返回空而不是把全市场倒出来():
    _seed([("600519", "贵州茅台", "白酒Ⅱ", 1.6e12)])

    assert client.get("/api/v1/universe/lookup", params={"q": ""}).json() == []
    assert client.get("/api/v1/universe/lookup", params={"q": "   "}).json() == []


def test_搜不到的时候是空列表不是报错():
    assert client.get("/api/v1/universe/lookup",
                      params={"q": "这家公司不存在"}).json() == []


def test_条数上限不接受任意大的值():
    assert client.get("/api/v1/universe/lookup", params={"q": "中", "limit": 999}).status_code == 422
    assert client.get("/api/v1/universe/lookup", params={"q": "中", "limit": 0}).status_code == 422


def test_别人建过的档案不会显示成你建过():
    """in_archive 是每个人自己的事。

    子查询里带了数据域过滤，PG 那边还有行级安全——**实测把过滤删掉这条仍是绿的**，
    因为 RLS 在数据库层就把别人的行挡住了。所以这条验的是行为（会不会串户），
    不是"某一行代码还在不在"。两层里任何一层还在，行为就是对的。
    """
    from stock_decision import access, repository
    from stock_decision.schemas import CompanyInput

    _seed([("002594", "比亚迪", "汽车", 8.0e11)])

    token = access.set_scope("u_alice000000000000000000")
    try:
        alice = repository.create_company(CompanyInput(
            symbol="002594", name="比亚迪", industry="汽车"))
        assert repository.lookup_universe("比亚迪")[0]["company_id"] == alice["id"]
    finally:
        access.reset_scope(token)

    token = access.set_scope("u_bob00000000000000000000")
    try:
        row = repository.lookup_universe("比亚迪")[0]
    finally:
        access.reset_scope(token)

    assert row["in_archive"] is False, "别人建的档案被当成了你的"
    assert row["company_id"] is None
