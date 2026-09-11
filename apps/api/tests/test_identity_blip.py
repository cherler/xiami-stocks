"""身份认错一次，首页空一整场。

## 2026-08-15 线上实测（站主本人的截图）

首页「我的公司」写着 **已建档 0 家**，还配着「建立第一家公司 →」的引导按钮，
而这个账号名下有 6 家公司档案 —— 同一屏上，市场云图的金色灯塔正标着
茅台、宁德时代、工业富联、寒武纪，决策看板也写着「反证出现 1」。

对着两边的日志读出来的经过：

    21:51:48  主站 GET /v1/me          → **401**
    21:51:48  看股 GET /api/v1/dashboard → 200（按游客查，空档案）
    21:51:57  主站 GET /v1/me          → 200（同一个人，九秒后就好了）
    21:52:12  之后所有请求都是站主：灯塔回来了、待办回来了
    ——        /api/v1/dashboard **再也没有被请求过**

三处叠在一起才有这个结果，所以三处都补：

1. **「没认出来」被缓存了 60 秒。** 401 恰恰是最可能瞬时的那一种
   （令牌正在刷新、刚登录、会话刚续期），而缓存把一次一秒的抖动
   放大成整整一分钟的错误身份。
2. **首页只在挂载时取一次 dashboard**，之后身份好了也不会重取。
3. **游客域查出来的空档案，长得跟"新用户什么都没有"一模一样** ——
   连下一步动作都给错了：一个该去登录，一个该去建档。
"""

import time

import pytest

from stock_decision import access


@pytest.fixture(autouse=True)
def _clean_cache():
    access._CACHE.clear()
    yield
    access._CACHE.clear()


def test_a_momentary_401_is_not_remembered_for_a_whole_minute(monkeypatch):
    """**这一条是根因。**

    认出来了缓存久一点是省一跳；没认出来缓存久了，是把对面抖的那一下
    变成自己这边一分钟的错误身份。
    """
    monkeypatch.setattr(access.llm, "load_env", lambda: {"XM_API_BASE": "http://x"})
    monkeypatch.setattr(access.urllib.request, "build_opener",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("回源了")))

    # 刚写下的"没认出来"还在有效期内：这一下不回源，吸收掉同一次进站的那一批。
    access._remember("ck", time.monotonic(), None)
    assert access._whoami("ck") is None

    # 过了否定缓存的时限就必须重新去问 —— 旧行为是一直用到 60 秒。
    access._remember("ck", time.monotonic() - (access._NEGATIVE_TTL_SECONDS + 1), None)
    with pytest.raises(AssertionError, match="回源了"):
        access._whoami("ck")



def test_a_confirmed_identity_is_still_cached_for_the_full_minute(monkeypatch):
    """正面结果照旧缓存 60 秒 —— 一次进站十来个接口，不能每个都回源问主站。"""
    monkeypatch.setattr(access.llm, "load_env", lambda: {"XM_API_BASE": "http://x"})
    known = {"user_id": "u_1", "email": "a@b.c"}
    access._remember("ck", time.monotonic() - (access._NEGATIVE_TTL_SECONDS + 1), known)

    monkeypatch.setattr(access.urllib.request, "build_opener",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("认出来了就不该再问")))
    assert access._whoami("ck") == known


def test_the_negative_window_is_short_enough_to_survive_one_page_load():
    """一次进站会并发打十来个接口，5 秒够吸收那一批，又短到下一次交互就重问。

    **不能干脆不缓存**：那等于把主站当压测目标。
    """
    assert 0 < access._NEGATIVE_TTL_SECONDS <= 10
    assert access._NEGATIVE_TTL_SECONDS < access._CACHE_TTL_SECONDS


def test_the_dashboard_says_it_answered_as_a_guest():
    """**「没查到」和「查了，是 0」必须能分辨。**

    游客域一行都匹配不到（RLS），返回的是处处为 0 的空档案。
    页面靠这一栏决定说「还没认出你是谁」还是「建立第一家公司 →」。
    """
    from stock_decision.schemas import DashboardSummary

    assert "viewer_is_guest" in DashboardSummary.model_fields, (
        "响应模型没声明这一栏 —— 后端算了、接口不带出去，"
        "页面上只表现为'这块从来不出现'，不报错（这个坑本仓踩过四次）")


def test_a_guest_dashboard_is_marked_as_such(client, owned):  # noqa: F811
    """站主查是 False，游客查是 True。"""
    client.as_user(access.OWNER_SCOPE)
    assert client.get("/api/v1/dashboard").json()["viewer_is_guest"] is False

    client.as_user(access.GUEST_SCOPE)
    guest = client.get("/api/v1/dashboard").json()
    assert guest["viewer_is_guest"] is True
    assert guest["watchlist"] == [], "游客不该看见任何人的公司"


from test_idor import client, owned  # noqa: E402,F401
