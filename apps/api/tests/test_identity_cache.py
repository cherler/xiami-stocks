"""身份缓存不能只涨不落——键是 Cookie 本身。

## 原来是怎么坏的

`_whoami()` 把主站的应答按 Cookie 缓存 60 秒，判据只在**读**的时候：
不够新就重新去问，然后覆盖写回。写回那一行是 `_CACHE[cookie] = ...`，
所以过期条目一条都不会消失 —— 换一次浏览器、清一次 Cookie、来一个新用户，
字典里就多一条永不回收的键。

这有两层代价，第二层更要紧：

1. 进程内存随访问过的会话数单调增长，重启才归零；
2. 留下来的是**身份凭据本身**，长期驻留在内存里没有任何好处。

所以这里测的是「上限存在」和「过期会被清掉」，而不是命中率。
"""

import time

from stock_decision import access


def _reset() -> None:
    access._CACHE.clear()


def test_缓存有上限_超了丢最早的那条() -> None:
    _reset()
    now = time.monotonic()
    for i in range(access._CACHE_MAX_ENTRIES + 40):
        access._remember(f"cookie-{i}", now, {"id": i})
    assert len(access._CACHE) == access._CACHE_MAX_ENTRIES, (
        f"缓存涨到了 {len(access._CACHE)} 条——它是按 Cookie 做键的，没有上限就是只涨不落")
    # 丢的是最早写进去的那几条，留下的是最近的
    assert "cookie-0" not in access._CACHE
    assert f"cookie-{access._CACHE_MAX_ENTRIES + 39}" in access._CACHE


def test_过期条目会被清掉_不用等到它被读到() -> None:
    """**清理必须发生在写入这一侧。** 读命中时只碰一条，看不到全貌：
    一个再也不回来的 Cookie，它那一条永远不会被读到，也就永远不会被清。"""
    _reset()
    old = time.monotonic() - access._CACHE_TTL_SECONDS - 1
    for i in range(5):
        access._CACHE[f"走了的用户-{i}"] = (old, {"id": i})
    access._remember("刚来的", time.monotonic(), {"id": 99})
    assert list(access._CACHE) == ["刚来的"], (
        f"过期的没被清掉：{list(access._CACHE)}")


def test_同一个cookie重复写不会占两个位置() -> None:
    _reset()
    now = time.monotonic()
    for _ in range(10):
        access._remember("同一个人", now, {"id": 1})
    assert len(access._CACHE) == 1
