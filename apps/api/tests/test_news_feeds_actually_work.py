"""订阅源要真的取得到，取不到要说清是哪一种取不到。

2026-08-19 全站巡检：资讯页顶上每轮都挂着这么一行 ——

    抓取失败的源：同花顺财经：ValueError、澎湃·财经：URLError、36 氪：ParseError

七个内置源坏了三个，而且报的是异常类名。在服务器上逐个实测之后：

· 同花顺 —— **我们自己的 bug**。它的 XML 头是 `encoding="GBK"`，
  而 `ElementTree.fromstring(bytes)` 只认单字节编码。按 gb18030 解出来是
  50 条正常条目：源一直是好的，是我们读不了，而这个源从上线起没成功过一次。
· 36 氪 —— 地址少个 www。`https://36kr.com/feed` 返回的是网页（200 + <!DOCTYPE html>），
  `https://www.36kr.com/feed` 才是 RSS。
· 澎湃 —— feedx.net 解析到 Meta 的 CDN，服务器上 IPv4 超时、IPv6 无路由。
  找过新浪/证券时报/中国证券网/第一财经/界面/东财滚动，没有能用的替代，停用。

**这里不联网**：联网测试会因为别人的站点抖动而随机变红，那种测试很快就没人信了。
测的是"我们这头做对了没有"——编码认不认、地址对不对、话说得清不清楚。
真实可达性由页面上那行失败提示自己说。
"""
from __future__ import annotations

import urllib.error
from xml.etree.ElementTree import ParseError

import pytest

from stock_decision.news import DEFAULT_FEEDS, RETIRED_FEED_URLS, _parse_xml
from stock_decision.repository import _why_feed_failed

GBK_RSS = (
    '<?xml version="1.0" encoding="GBK" ?><rss version="2.0">'
    "<channel><title>同花顺</title>"
    "<item><title>贵州茅台发布半年报</title><link>http://x</link></item>"
    "<item><title>宁德时代扩产</title><link>http://y</link></item>"
    "</channel></rss>"
).encode("gb18030")


def test_读得了_gbk_的源() -> None:
    """同花顺就栽在这儿：50 条正常条目，一条都没进来。"""
    root = _parse_xml(GBK_RSS)
    titles = [node.findtext("title") for node in root.iter("item")]
    assert titles == ["贵州茅台发布半年报", "宁德时代扩产"], titles


def test_utf8_的源照旧() -> None:
    utf8 = ('<?xml version="1.0" encoding="UTF-8" ?><rss><channel>'
            "<item><title>比亚迪出海</title></item></channel></rss>").encode()
    assert [n.findtext("title") for n in _parse_xml(utf8).iter("item")] == ["比亚迪出海"]


def test_没有编码声明的也能读() -> None:
    plain = "<rss><channel><item><title>无声明</title></item></channel></rss>".encode()
    assert [n.findtext("title") for n in _parse_xml(plain).iter("item")] == ["无声明"]


def test_内置源里没有已知取不到的地址() -> None:
    dead = {url for url, replacement in RETIRED_FEED_URLS.items()}
    for feed in DEFAULT_FEEDS:
        assert feed["url"] not in dead, (
            f"{feed['name']} 用的还是已知取不到的地址 {feed['url']}"
        )


def test_落库的旧地址会被改过来() -> None:
    """ensure_news_feeds 只补缺失的源、从不改已有行 ——
    光改 DEFAULT_FEEDS 的话，线上那条记录还是旧地址，等于没修。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "stock_decision" / "repository.py").read_text()
    at = src.index("def ensure_news_feeds()")
    body = src[at:at + 1800]
    assert "RETIRED_FEED_URLS" in body, "已经落库的旧地址没人管"
    assert "UPDATE news_feeds SET url" in body, "没有把旧地址改过来"
    assert "UPDATE news_feeds SET enabled = 0" in body, "取不到的源没有停用"
    assert "builtin = 1" in body, "改到用户自己加的源上了"


@pytest.mark.parametrize(("exc", "want"), [
    (urllib.error.HTTPError("u", 403, "f", {}, None), "拒绝"),
    (urllib.error.HTTPError("u", 404, "f", {}, None), "已经没有了"),
    (urllib.error.URLError("unreachable"), "连不上"),
    (ParseError("not well-formed"), "不是 RSS"),
    (ValueError("multi-byte encodings are not supported"), "编码"),
    # 兜底那一支也要测：没被认出来的异常同样不该把类名漏出去。
    (RuntimeError("谁知道呢"), "没取成"),
])
def test_失败原因说人话(exc: Exception, want: str) -> None:
    said = _why_feed_failed(exc)
    assert want in said, said
    # 异常类名对用户没有意义，而且把几件完全不同的事说成了同一种模糊。
    assert type(exc).__name__ not in said, f"把类名摆给用户看了：{said}"
