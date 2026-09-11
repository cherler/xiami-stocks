"""游客态：能看市场，看不见任何人的研究，一个字也写不进来。

## 为什么要有游客态

原来没登录一律 401。使用者的原话是「你现在直接拦住了，我怎么引新用户啊」——
一个点进来只看到「请先登录」的人，不知道这里有什么，也就没有登录的理由。

## 这里守的三件事，每一件失效都看不出来

1. **游客能进**。回归成 401 的话，产品又变回「先登录再说」。
2. **游客看不见别人的数据**。靠的是 RLS：游客域什么都匹配不到。
   这一条一旦破了，是把全部研究记录对公网敞开——而页面上一切正常。
3. **游客写不进来**。所有游客共用一个域，放开写等于游客甲建的档案
   出现在游客乙那里；而且花钱的动作全是 POST，挡住写就同时挡住了烧积分。

第 3 条尤其容易漏：它不在任何一个接口里，只在中间件那一行上。
"""

from __future__ import annotations

import pytest

from stock_decision import access


@pytest.fixture
def multi_mode(monkeypatch):
    """multi：任何登录用户可用。游客在这一档下应该看得见市场。"""
    monkeypatch.setenv("STOCK_ACCESS", "multi")
    monkeypatch.setattr(access.llm, "load_env", lambda: {"XM_API_BASE": "http://127.0.0.1:0"})
    yield


def test_guest_gets_in_without_a_cookie(multi_mode):
    """**游客能进。** 退回 401 的话就没法引新人了。"""
    grant = access.check("")
    assert grant["is_guest"] is True
    assert grant["is_owner"] is False


def test_guest_scope_owns_nothing(multi_mode):
    """游客的数据域不是站主域，也不是任何真实用户的域。

    **这一条错了就是把全部研究记录对公网敞开**，而页面上一切正常——
    游客会看到站主的公司、判断和持仓，跟自己的一样。
    """
    grant = access.check("")
    assert grant["scope"] == access.GUEST_SCOPE
    assert grant["scope"] != access.OWNER_SCOPE


def test_owner_mode_still_refuses_guests(monkeypatch):
    """owner 档的语义就是「钉死」，不给游客态。"""
    monkeypatch.setenv("STOCK_ACCESS", "owner")
    monkeypatch.setattr(access.llm, "load_env", lambda: {"XM_API_BASE": "http://127.0.0.1:0"})
    with pytest.raises(access.AccessDenied) as caught:
        access.check("")
    assert caught.value.status == 403


def test_guest_cannot_write(multi_mode):
    """**游客只读，挡在中间件那一行上。**

    所有游客共用一个域：放开写就是游客甲建的档案出现在游客乙那里，
    而且没人能删。这一条不在任何接口里，所以只能在这里钉住。
    """
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    posted = client.post("/api/v1/companies", json={"symbol": "600519", "name": "测试", "industry": "白酒"})
    assert posted.status_code == 401
    assert posted.json()["code"] == "guest_readonly"


def test_guest_can_read(multi_mode):
    """读要放行——不然「能看市场」这句话就是空的。"""
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    assert client.get("/api/v1/companies").status_code == 200


def test_every_write_verb_is_blocked(multi_mode):
    """POST 之外的写法也要挡。**只挡 POST 是最容易犯的错**——
    删除走 DELETE，改状态走 PATCH，漏一个就是游客能删别人的东西。"""
    from fastapi.testclient import TestClient

    from stock_decision.main import app

    client = TestClient(app)
    for call in (client.delete, client.put, client.patch):
        response = call("/api/v1/companies/1")
        assert response.status_code == 401, f"{call.__name__.upper()} 没被挡住"


def test_游客不能写_但监测上报是例外(monkeypatch: pytest.MonkeyPatch) -> None:
    """**上线之后才发现的**：线上是 multi 姿态，没登录 = 游客，而中间件
    对游客一律「只读」——于是监测上报在公网上返回 401，一条样本都收不到。

    本机冒烟当时打的是 STOCK_ACCESS=open 的实例，那种姿态根本走不到这条守卫。

    这条例外是有边界的：`/api/v1/rum` 写的不是研究数据（几个毫秒数 + 白名单里的
    页面名），而**没登录那次访问同样值得知道快不快**——首屏慢恰恰最常发生在
    第一次打开。除它以外，游客的写请求仍然一律挡住。
    """
    import asyncio

    from tests.test_api import request

    monkeypatch.setattr(access, "mode", lambda: "multi")
    monkeypatch.setattr(access, "check", lambda cookie: {
        "user": None, "scope": access.GUEST_SCOPE, "is_owner": False, "is_guest": True})

    ok = asyncio.run(request("POST", "/api/v1/rum",
                             {"page": "companies", "kind": "nav", "device": "desktop", "lcp_ms": 1200}))
    assert ok.status_code == 204, f"监测上报被挡了：{ok.status_code} {ok.text[:120]}"

    # 别的写请求照旧挡住 —— 例外只有这一个路径
    blocked = asyncio.run(request("POST", "/api/v1/companies",
                                  {"symbol": "600519", "name": "贵州茅台", "industry": "白酒"}))
    assert blocked.status_code == 401
    assert "登录" in blocked.text
