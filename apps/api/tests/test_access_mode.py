"""访问姿态的解析，重点是 `auto` —— 跟随运营台那个开关。

`auto` 让「开放虾米看股」变成运营台上的一次点击：模块显示则所有登录用户可用，
隐藏则只有站主。它替掉的是「改前端 modules.ts + 登服务器改 .env」两件事，
而两件事各做一半正是最容易出的错——只开入口是所有人点进去 401，
只开服务端是数据敞开但没人找得到入口。

**这里最要紧的一条是最后那个：主站读不到时必须判定为「关」。**
这个函数的返回值决定要不要对所有登录用户敞开数据，任何异常都只能往关的方向倒。
"""

import json

import pytest

from stock_decision import access


@pytest.fixture()
def console(monkeypatch):
    """把「运营台配置」这一跳换掉，返回指定的 site-settings 载荷。

    传 payload=None 表示主站不可达（连接异常）。
    """

    def setup(payload):
        access._VIS_CACHE.clear()
        monkeypatch.setenv("STOCK_ACCESS", "auto")
        original = access.llm.load_env
        monkeypatch.setattr(
            access.llm, "load_env",
            lambda: {**original(), "XM_API_BASE": "http://127.0.0.1:9"})

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self): return json.dumps(payload).encode("utf-8")

        class _Opener:
            def open(self, request, timeout=0):
                if payload is None:
                    raise OSError("主站不可达")
                return _Response()

        monkeypatch.setattr(access.urllib.request, "build_opener", lambda *a: _Opener())

    return setup


def test_auto_opens_when_console_shows_the_module(console):
    console({"modulesVis": {"stocks": True}})
    assert access.mode() == "multi"


def test_auto_stays_closed_when_console_hides_the_module(console):
    console({"modulesVis": {"stocks": False}})
    assert access.mode() == "owner"


def test_auto_stays_closed_when_the_module_has_no_override(console):
    # 本模块在前端清单里是 planned（默认隐藏），所以「没有覆盖」就是没开放。
    console({"modulesVis": {}})
    assert access.mode() == "owner"


def test_auto_fails_closed_when_the_main_site_is_unreachable(console):
    # 宁可自己进不去，也不能因为对面抖一下就对所有登录用户敞开。
    console(None)
    assert access.mode() == "owner"


def test_auto_fails_closed_on_a_malformed_payload(console):
    # modulesVis 不是对象（接口改版、返回了错误体）也一样按关处理。
    console({"modulesVis": "yes"})
    assert access.mode() == "owner"


@pytest.mark.parametrize("configured", ["owner", "multi", "open"])
def test_explicit_modes_ignore_the_console(monkeypatch, configured):
    """显式配置是硬钉，不受运营台影响——想彻底锁死时用得上。"""
    monkeypatch.setenv("STOCK_ACCESS", configured)
    assert access.mode() == configured
