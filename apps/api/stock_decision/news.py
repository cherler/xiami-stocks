"""资讯管道：抓 RSS、去重、把线索匹配到已建档的公司。

和公告收件箱的区别要说清楚：公告是交易所披露的一手事实，资讯是二手转述。
所以这里的默认动作不是"归档"，而是"给你看，并指出它对应哪家公司、原文在哪"。
资讯本身不作为证据，**只有当你点开原文确认过之后**，它才会以你确认的摘录进入证据档案。

预置了几个公开的中文财经 RSS，开箱就有内容，不需要先去配置源。抓不到的源会被标记出来，
而不是静默跳过——一个长期抓不到的源等于没有这个源，必须让人看见。

实体匹配分两层：
1. 代码先按公司名与股票代码做精确匹配（零成本、零误报）。
2. 剩下的交给模型，它只能在**已建档公司**这个封闭集合里选，选不出就说选不出。
   模型给的匹配一律标为待确认，不自动进入任何公司的时间线。
"""

import hashlib
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree

from . import llm
from .jsonio import loads_or_reformat
from .llm import ai_available

# 预置源：都是公开 RSS，不需要账号。用户可以增删，但开箱就有内容。
# 内置源都实测过能取到 XML。用户可以停用、也可以自己加。
# 一个源长期取不到就等于没有这个源，所以每次抓取的成败都记在 news_feeds 上。
DEFAULT_FEEDS: tuple[dict[str, str], ...] = (
    {"key": "eastmoney_finance", "name": "东方财富·财经要闻", "url": "http://rss.eastmoney.com/rss_partener.xml"},
    {"key": "wallstreetcn", "name": "华尔街见闻", "url": "https://dedicated.wallstreetcn.com/rss.xml"},
    {"key": "ths_news", "name": "同花顺财经", "url": "http://news.10jqka.com.cn/today_list/index.xml"},
    {"key": "xueqiu_topic", "name": "雪球·今日话题", "url": "https://xueqiu.com/hots/topic/rss"},
    {"key": "kr36", "name": "36 氪", "url": "https://www.36kr.com/feed"},
    {"key": "huxiu", "name": "虎嗅", "url": "https://rss.huxiu.com/"},
)

# 内置源的地址改过、或者某个源确认取不到了 —— **已经落库的那些行也要跟着动**。
#
# ensure_news_feeds 只在缺失时插入，从不更新已有行。所以光改上面那张表，
# 线上那条记录还是旧地址：修了等于没修。
#
# 键是旧地址；值是新地址，None 表示这个源已经取不到、停用它。
# 只对 builtin=1 且地址仍是旧值的行生效 —— 用户自己改过的不动。
RETIRED_FEED_URLS: dict[str, str | None] = {
    # 36 氪：不带 www 的那个地址返回的是网页不是 RSS（实测 200 + <!DOCTYPE html>）
    "https://36kr.com/feed": "https://www.36kr.com/feed",
    # 澎湃：feedx.net 解析到 Meta 的 CDN，服务器上 IPv4 超时、IPv6 无路由。
    # 找过新浪/证券时报/中国证券网/第一财经/界面/东财滚动，没有一个能用的替代。
    "https://feedx.net/rss/thepaper.xml": None,
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _parse_date(raw: str | None) -> str:
    if not raw:
        return datetime.now().isoformat(timespec="seconds")
    for pattern in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw.strip(), pattern)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


def fingerprint(title: str, url: str) -> str:
    """同一条新闻会被多家转载；用标题指纹去重，标题相同就当同一条。"""

    normalized = _WS_RE.sub("", title)[:80] or url
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


_ENCODING_RE = re.compile(rb'encoding=["\']([\w-]+)["\']')


def _parse_xml(raw: bytes):
    """解析 RSS。**按声明里的编码先解成 str，再交给 ElementTree。**

    直接把 bytes 丢进 `ElementTree.fromstring` 时，声明 GBK/GB2312 的源会抛
    `ValueError: multi-byte encodings are not supported` —— expat 只认单字节编码。

    2026-08-19 实测：同花顺财经的 XML 头就是 `encoding="GBK"`，于是这个源
    **从来没成功过一次**，页面上每轮都报一句「同花顺财经：ValueError」。
    按 gb18030 解出来是 50 条正常条目 —— 源是好的，是我们读不了。

    解成 str 之后要把声明里的 encoding 去掉：ElementTree 拿到 str 还看见
    encoding 声明会报 "encoding specified in XML declaration is incorrect"。
    """
    declared = _ENCODING_RE.search(raw[:200])
    encodings = ["utf-8"]
    if declared:
        name = declared.group(1).decode("ascii", "ignore").lower()
        # gb2312/gbk 都用 gb18030 解 —— 它是前两者的超集，能多认一些生僻字
        encodings.insert(0, "gb18030" if name.startswith(("gb", "GB")) else name)
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        return ElementTree.fromstring(_ENCODING_RE.sub(b"", text.encode("utf-8")).decode("utf-8"))
    return ElementTree.fromstring(raw)          # 都解不开就按原来的路走，让它照常报错


def fetch_feed(feed: dict[str, str], timeout: int = 20, limit: int = 40) -> list[dict[str, Any]]:
    request = urllib.request.Request(feed["url"], headers={"User-Agent": "Mozilla/5.0 (compatible; xiamimate-stock-lab/1.0)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    root = _parse_xml(raw)
    items: list[dict[str, Any]] = []
    # RSS 2.0 与 Atom 的节点名不同，两种都收
    nodes = root.iter("item") if root.find(".//item") is not None else root.iter("{http://www.w3.org/2005/Atom}entry")
    for node in nodes:
        def text_of(*names: str) -> str | None:
            for name in names:
                found = node.find(name) if not name.startswith("{") else node.find(name)
                if found is not None:
                    return found.text or (found.get("href") if name.endswith("link") else None)
            return None

        title = _clean(text_of("title", "{http://www.w3.org/2005/Atom}title"))
        if not title:
            continue
        link = _clean(text_of("link", "{http://www.w3.org/2005/Atom}link")) or feed["url"]
        items.append(
            {
                "feed_key": feed["key"],
                "feed_name": feed["name"],
                "title": title,
                "url": link,
                "summary": _clean(text_of("description", "{http://www.w3.org/2005/Atom}summary"))[:600],
                "published_at": _parse_date(text_of("pubDate", "{http://www.w3.org/2005/Atom}updated")),
                "fingerprint": fingerprint(title, link),
            }
        )
        if len(items) >= limit:
            break
    return items


def match_by_rules(text: str, companies: list[dict[str, Any]]) -> dict[str, Any] | None:
    """公司全名或股票代码出现在标题里就算命中；这一层不会误报，也不花钱。"""

    for company in companies:
        if company["symbol"] in text:
            return {"company_id": company["id"], "confidence": "确定", "reason": f"标题里出现股票代码 {company['symbol']}"}
    for company in sorted(companies, key=lambda item: -len(item["name"])):
        if len(company["name"]) >= 3 and company["name"] in text:
            return {"company_id": company["id"], "confidence": "确定", "reason": f"标题里出现公司全称「{company['name']}」"}
    return None


MATCH_SYSTEM_PROMPT = """你在把财经新闻标题匹配到一个封闭的公司清单上。

严格遵守：
1. 只能从给出的公司清单里选，绝对不能选清单以外的公司，也不能凭记忆推断"这条新闻其实是讲某某公司"。
2. 只有当标题里出现了这家公司的简称、曾用名、主要品牌或它独有的业务标识时才算命中。
3. 行业新闻、政策新闻、大盘新闻不属于任何单家公司——这种情况 company_id 填 null。
4. 拿不准就填 null。漏掉一条的代价远小于把不相关的新闻挂到公司档案上。

只输出 JSON 数组，每项形如：
{"index": 1, "company_id": 3, "reason": "标题里的「格力」是这家公司的简称"}
不匹配的写 {"index": 1, "company_id": null, "reason": "这是行业政策新闻，没有指向具体公司"}"""

# 重排用的结构，跟上面那两行示例同形。
REFORMAT_SHAPE = '[{"index": 1, "company_id": 3, "reason": "…"}]'


def match_with_model(items: list[dict[str, Any]], companies: list[dict[str, Any]], timeout: int = 120) -> list[dict[str, Any]]:
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)
    roster = "\n".join(f"- id={company['id']} {company['name']}（{company['symbol']}，{company.get('industry') or '行业未标注'}）" for company in companies)
    listing = "\n".join(f"{index + 1}. {item['title']}" for index, item in enumerate(items))
    completion = llm.call(
        MATCH_SYSTEM_PROMPT,
        f"公司清单：\n{roster}\n\n把下面 {len(items)} 条标题匹配到清单上：\n{listing}",
        task="news-match", max_tokens=2500, timeout=timeout,
    )
    text = completion.text
    try:
        entries, _ = loads_or_reformat(text, task="news-match", expect="array",
                                       shape=REFORMAT_SHAPE, timeout=timeout)
    except ValueError:
        return []
    valid_ids = {company["id"] for company in companies}
    matches: list[dict[str, Any]] = []
    for entry in entries:
        try:
            index = int(entry.get("index", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(items):
            continue
        company_id = entry.get("company_id")
        # 模型选了清单外的 id 就当没匹配上，绝不放行
        if company_id is not None and company_id not in valid_ids:
            company_id = None
        matches.append(
            {
                "fingerprint": items[index]["fingerprint"],
                "company_id": company_id,
                "confidence": "待确认" if company_id is not None else "无匹配",
                "reason": str(entry.get("reason") or "")[:200],
                "model": llm.model_name(),
            }
        )
    return matches
