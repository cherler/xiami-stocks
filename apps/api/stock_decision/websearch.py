"""联网检索：给研究报告找公开资料。

## 为什么要有这个

原来的研究报告只复述已归档的证据，而归档的多半是公告标题——写出来的东西
"乏善可陈"是必然的：它没有任何档案之外的信息，只是把你已经看过的东西
重新排了一遍。

## 但数字仍然不从网上取

**这是最要紧的一条边界。** 网页上的财务数字经常是过期的、口径不同的，
或者干脆是别人抄错的。本站的财务数字有唯一来源：`financial_periods` 与
`market_universe`，都是从数据源同步的。所以检索回来的资料只用来回答
"发生了什么、市场在讨论什么、公司自己怎么说"，**数字一律以库里的为准**。

这跟虾米跨境那套的铁律是同一条：数字由代码给，模型无权报数。

## 两把 key：免费额度打头阵，付费版兜底

`TAVILY_API_KEY` 是一个**没开通按量付费的账号**，每月 1000 次免费额度——
它是正式 key，不是测试 key，用完就真的不能用了。
`TAVILY_API_KEY_VIP` 开了按量付费，作为兜底。

顺序是免费在前：额度是白给的，不用白不用；用完了自动切到付费那把，
而不是当场报错让用户干等。**切换要留痕**（返回 `tier`），
否则"这个月怎么开始扣钱了"没人说得清。

## 429 与 402 不是一回事

429 是突发限流——同一秒打太多请求，等一下就好，**不代表额度用完**。
402 才是真的没额度了。第一版把两者混在一起当"额度用完"，
后果是一次偶发的限流会让整份报告直接放弃搜索，而付费那把 key 明明还能用。

## 成本封顶写死在代码里

不靠"记得省着点用"，直接把上限写进常量：每份报告最多 `MAX_SEARCHES` 次搜索，
每次 `MAX_RESULTS` 条。**限流之外一律不重试**——重试是把额度烧光最快的方式，
一个超时的查询重试三次，额度就是三倍。

## 源的分级

交易所公告与公司官网是一手的，财经媒体是二手转述，券商研报是机构观点，
论坛与股吧是散户观点。四类都收，但**必须标出来**，因为它们在报告里的分量完全不同：
一手资料可以直接当事实引用，二手的要写"据某某报道"，观点只能当作
"市场在这样讨论"。不标的话，模型会把股吧里的一句话跟年报里的一句话
放在同一个位置上引用。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from . import llm

# 成本封顶。免费版额度有限，这两个数字是硬约束，不是建议。
MAX_SEARCHES = 6
MAX_RESULTS = 8
TIMEOUT = 30

# 一手来源：交易所、监管、公司官网。这些可以直接当事实引用。
_PRIMARY_HOSTS = (
    "sse.com.cn", "szse.cn", "bse.cn", "cninfo.com.cn",       # 交易所与信披
    "csrc.gov.cn", "pbc.gov.cn", "stats.gov.cn", "gov.cn",     # 监管与官方统计
)
# 二手转述：财经媒体。要写"据某某报道"。
#
# **这张表短一条，就多一条落进「其他」。** 2026-08-15 线上实测（格力那份深度报告）：
# 检索回来 36 条，**21 条被归成「其他」**，而正文 27 处引用里有 14 处指向它们 ——
# 也就是说过半的结论挂在一个连提示词都没定义过的档位上。翻开那 21 条看，
# 里面是财联社、界面、21 世纪经济报道、中国经济网、环球网财经、搜狐财经、
# 网易财经这些主流财经媒体，跟百度百科、境外研究站并排放在同一个桶里。
#
# 分级的全部意义是"这句话该按多重的分量引用"。一个占多数的未定义档位，
# 等于这套分级对多数资料不起作用。
_MEDIA_HOSTS = (
    "stcn.com", "cs.com.cn", "cnstock.com", "yicai.com", "caixin.com",
    "news.cn", "xinhuanet.com", "people.com.cn", "eastmoney.com",
    "sina.com.cn", "hexun.com", "jrj.com.cn", "10jqka.com.cn", "wallstreetcn.com",
    # 下面这批是实测里出现在「其他」桶中的主流财经媒体
    "cls.cn",            # 财联社
    "jiemian.com",       # 界面新闻
    "21jingji.com",      # 21 世纪经济报道
    "nbd.com.cn",        # 每日经济新闻
    "thepaper.cn",       # 澎湃
    "bjnews.com.cn",     # 新京报
    "ce.cn",             # 中国经济网
    "huanqiu.com",       # 环球网
    "cctv.com", "cnr.cn",
    "sohu.com", "163.com", "qq.com", "ifeng.com",   # 门户财经频道
    "chinatimes.net.cn", "time-weekly.com", "cbnweek.com",
)
# 券商研报。**单列一类**：它是机构的专业分析，比论坛观点重，但仍然是观点
# 不是事实——站内别处已经这么标了（"观点属机构，不代表本站判断"），这里对齐。
_RESEARCH_HOSTS = ("dfcfw.com", "pdf.dfcfw.com", "research.stockstar.com", "hibor.com.cn")
# 观点站：只能当作"市场在这样讨论"，不能当事实。
_FORUM_HOSTS = ("xueqiu.com", "guba.eastmoney.com", "zhihu.com", "zhuanlan.zhihu.com",
                "weibo.com", "tieba.baidu.com", "jianshu.com")


class SearchError(RuntimeError):
    pass


def _key(name: str) -> str:
    return (os.getenv(name) or llm.load_env().get(name) or "").strip()


def keys() -> list[tuple[str, str]]:
    """[(档位, key)]，按使用顺序。免费额度在前，付费兜底。

    免费额度是白给的，不用白不用；用完了自动切付费那把，
    而不是当场报错让用户干等。
    """
    ordered = []
    if _key("TAVILY_API_KEY"):
        ordered.append(("免费额度", _key("TAVILY_API_KEY")))
    if _key("TAVILY_API_KEY_VIP"):
        ordered.append(("按量付费", _key("TAVILY_API_KEY_VIP")))
    return ordered


def available() -> tuple[bool, str]:
    """没配 key 就明说，别让报告悄悄退化成"只有本地证据"那一版。"""
    if not keys():
        return False, "没有配 TAVILY_API_KEY，联网检索用不了。报告只会用已归档的证据。"
    return True, ""


def source_kind(url: str, own_site: str = "") -> str:
    """把一条结果归到一手 / 媒体 / 观点 / 其他。

    **必须标出来**：一手资料可以直接当事实引用，二手的要写"据某某报道"，
    观点只能当作"市场在这样讨论"。不标的话，模型会把股吧里的一句话
    跟年报里的一句话放在同一个位置上引用。

    `own_site` 是这家公司自己的官网（`company_profiles.website`，
    茅台是 www.moutaichina.com）。**它必须算一手**——第一版没接这个字段，
    结果茅台官网发的一季报被归成了"其他"，跟随便一个不认识的域名同级，
    而它恰恰是最该被当成事实引用的那一类。
    """
    host = (urlparse(url).hostname or "").lower()

    own = (own_site or "").strip().lower()
    own = own.removeprefix("http://").removeprefix("https://").split("/")[0].removeprefix("www.")
    if own and (host == own or host.endswith("." + own)):
        return "一手"
    # **同一家公司常有不止一个官网域名。** 2026-08-15 实测：格力档案里登记的是
    # gree.com.cn，而检索回来的两条官网内容在 www.gree.com 上 —— 于是格力自己
    # 发的东西被归成「其他」，跟百度百科同级。这正是 own_site 这个字段
    # 当初为茅台加上的那个问题，只是换了个域名后缀又犯一次。
    #
    # 只放宽后缀，不放宽名字：gree.com.cn / gree.com / gree.cn 认，
    # gree.xyz 不认。名字本身必须一模一样，靠的是 `stem` 的相等判断。
    stem = own.split(".")[0]
    if stem and any(host == f"{prefix}{stem}.{suffix}"
                    for prefix in ("", "www.")
                    for suffix in ("com", "cn", "com.cn", "net", "net.cn")):
        return "一手"
    # 先判论坛：guba.eastmoney.com 同时命中 eastmoney，顺序反了会被归成媒体
    if any(host == h or host.endswith("." + h) or h in host for h in _FORUM_HOSTS):
        return "观点"
    if any(host == h or host.endswith("." + h) for h in _RESEARCH_HOSTS):
        return "研报"
    if any(host == h or host.endswith("." + h) for h in _PRIMARY_HOSTS):
        return "一手"
    if any(host == h or host.endswith("." + h) for h in _MEDIA_HOSTS):
        return "媒体"
    return "其他"


def _call(query: str, key: str, days: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query, "search_depth": "basic", "max_results": MAX_RESULTS}
    if days:
        payload |= {"topic": "news", "days": max(1, min(30, days))}
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def search(query: str, days: int | None = None, own_site: str = "") -> list[dict[str, Any]]:
    """一次搜索。免费额度用尽就换付费那把，其余情况**一律不重试**。"""
    pool = keys()
    if not pool:
        raise SearchError(available()[1])

    body: dict[str, Any] | None = None
    used = ""
    last = ""
    for tier, key in pool:
        try:
            body = _call(query, key, days)
            used = tier
            break
        except urllib.error.HTTPError as exc:
            # 402 = 真没额度了，换下一把；429 = 突发限流，同一把也可能是暂时的，
            # 但这里同样换把（下一把是另一个账号，不共享限流窗口）。
            # 两者以外的错误不换 —— 换了也是一样的结果，白烧一次额度。
            if exc.code in (402, 429):
                last = f"HTTP {exc.code}"
                continue
            raise SearchError(f"搜索失败：HTTP {exc.code}") from exc
        except Exception as exc:                  # noqa: BLE001 — 网络什么都可能抛
            raise SearchError(f"搜索失败：{type(exc).__name__}") from exc

    if body is None:
        raise SearchError(
            f"两把 key 都用不了（最后一次 {last}）。免费额度每月 1000 次，"
            "付费那把也没通过——去 Tavily 后台看一下账号状态。")

    hits = []
    for item in body.get("results") or []:
        url = str(item.get("url") or "")
        if not url:
            continue
        hits.append({
            "title": str(item.get("title") or "")[:200],
            "url": url,
            "snippet": str(item.get("content") or "")[:1200],
            "score": item.get("score"),
            "kind": source_kind(url, own_site),
            "published": str(item.get("published_date") or "")[:10],
            # 哪把 key 出的结果要留痕，否则"这个月怎么开始扣钱了"没人说得清
            "tier": used,
        })
    return hits


def gather(queries: list[str], days: int | None = None, own_site: str = "") -> dict[str, Any]:
    """按几个问题各搜一次，汇合去重。

    去重按 URL：同一篇文章经常被多个查询命中，不去重的话它在报告里会被
    当成"多个来源都提到"——那是凭空造出来的佐证强度。
    """
    queries = [q for q in queries if q.strip()][:MAX_SEARCHES]
    seen: set[str] = set()
    hits: list[dict[str, Any]] = []
    failures: list[str] = []

    for query in queries:
        try:
            found = search(query, days=days, own_site=own_site)
        except SearchError as exc:
            failures.append(f"{query[:24]}：{exc}")
            # 额度用完就整体停下，继续搜只是浪费时间
            if "额度" in str(exc):
                break
            continue
        for hit in found:
            if hit["url"] in seen:
                continue
            seen.add(hit["url"])
            hit["query"] = query
            hits.append(hit)

    by_kind: dict[str, int] = {}
    for hit in hits:
        by_kind[hit["kind"]] = by_kind.get(hit["kind"], 0) + 1

    return {
        "hits": hits,
        "queries": queries,
        "failures": failures,
        "by_kind": by_kind,
        "note": (f"搜了 {len(queries)} 个问题，去重后 {len(hits)} 条资料"
                 f"（一手 {by_kind.get('一手', 0)}、媒体 {by_kind.get('媒体', 0)}、"
                 f"研报 {by_kind.get('研报', 0)}、观点 {by_kind.get('观点', 0)}、"
                 f"其他 {by_kind.get('其他', 0)}）。"),
    }
