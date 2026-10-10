"""公告正文：把「关于股份回购进展情况的公告」这十四个字，换成公告本身。

## 这一条是整个产品里最划算的一处改动

承诺台账在 12 家公司上跑出 **0 条**。查下去有两个原因，都不是抽取标准太严：

1. **抽取接口对登录用户必然 500**（对一张没有 user_id 的表用了 _sw()），
   上线以来一次都没成功过。这条已经修掉，见 repository.extract_company_promises。
2. 就算它跑通，也抽不出东西——**我们只给了模型十四个字**。

格力 2026-08-04 那条公告，库里存的标题是《关于股份回购进展情况的公告》。
正文里是这些：

    · 回购资金总额不低于人民币 50 亿元（含）且不超过 100 亿元（含）
    · 回购价格不超过 56.5 元／股
    · 自董事会审议通过之日起不超过 12 个月
    · 回购股份中不低于 70% 将用于注销并减少注册资本

**四条带数字、带期限、可以被证伪的承诺，一条都没出现在标题里。**
模型没有做错任何事，是我们没给它可读的东西。

## 不需要新的数据源，也不需要新的接口调用

库里 1587 条公告的 url 是完整的，形如

    http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000651
        &announcementId=1225455000&announcementTime=2026-08-04

而 PDF 就在

    http://static.cninfo.com.cn/finalpage/{announcementTime 的日期}/{announcementId}.PDF

**这两个字段拼出来就是 PDF 地址**，实测 40/40 命中，串行 2.2 秒。
所以这里没有查询接口、没有列表接口、没有翻页——只有一次 GET。
`announcementTime` 有时带时分秒（`2026-08-07 20:16:09`），截前十位；
这个坑我踩过一次，`pdf_url` 里那句 `[:10]` 就是它。

## 抓过的不再抓第二次，抓不到的也记下来

正文存在 `announcement_texts`，主键是巨潮的公告编号——**全局一份**。
同一份公告谁看都是同一份，跟 K 线同理，所以它进 `_GLOBAL_MARKET_TABLES`
而不是按公司隔离。

失败也写库。不写的话，一条已经撤下的公告会在每次抽取时被重试一遍，
而它永远不会成功。

## 按需抓，不预抓

1587 条全抓约 240MB、1587 次请求，而其中绝大多数你永远不会用到。
所以只在真要读的时候抓。现在只有承诺台账用它；反方 Agent 和深度报告
先不接，等这一个跑出效果再说。

## 声明类公告要挡掉，否则台账会被套话灌满

万科那条命中的是《独立董事候选人声明与承诺》——「承诺」二字密度极高，
抽出来五条全是任职套话（"本人承诺将及时报名参加培训"）。

这类东西的危险不在于它错，而在于**它会把台账灌满，而灌满之后你就再也不看它了**。
一个没人看的台账等于没有台账。所以 `SKIP_TITLE` 里那几类整类排除。

排除名单写得窄，只放已经实测确认是纯套话的那几类。宁可漏掉一类，
也不要误伤——误伤掉的是真承诺，而真承诺正是这个功能的全部产出。
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# 单份 PDF 的上限。**从 8MB 提到 60MB：年报本来就该读。**
#
# 8MB 那条线当初是为了跳过年报（"年报里的承诺会在专门的公告里重述"），
# 而现在年报是主要目标之一——前五大客户与供应商是强制披露项，只在年报里。
MAX_PDF_BYTES = 60 * 1024 * 1024

# 单份公告存下来的正文上限。
#
# **从 40000 提到 200 万，等于不截断。** 40000 字对普通公告绰绰有余，
# 但年报有几十万字——而年报里最该读的那几节（主要客户与供应商、
# 分部构成、募投进度）恰恰排在很后面。实测茅台 2024 年报的
# 「前五名客户」那一节就在 4 万字之后，直接被切掉了。
#
# 截断的危险不在于丢字，在于**丢掉的部分不报错**：抽不到就等于"这家公司没披露"，
# 跟真的没披露长得一模一样。
#
# 保留一个上限只是防御异常文件（几百兆的扫描件转文字），不是省空间。
# 真正控制成本的是「定位到那一节再读」，不是「只读前面一段」——见 find_section。
MAX_TEXT_CHARS = 2_000_000

# 喂给模型时每份公告截多长。承诺条款通常在前几页，正文再长也是附表。
PROMPT_CHARS = 3_000

# 一次抽取最多抓几份。抓一份约 0.05 秒，但这是对外部站点发请求，
# 得有个上界——不设的话一次「全量重抽」会瞬间打出几百个请求。
MAX_FETCH_PER_RUN = 24

# 并发度。实测 4 路稳定；再高对巨潮不礼貌，收益也只有零点几秒。
FETCH_CONCURRENCY = 4

FETCH_TIMEOUT = 20

_UA = "Mozilla/5.0 (compatible; xiamimate-stock-lab/1.0)"

# 整类排除：这些文件里「承诺」二字密度极高，但没有一条是投资意义上的承诺。
#
# **每一条都是实测确认过的纯套话**，不是我凭感觉列的。名单保持窄——
# 误伤一类等于永久丢掉那一类里的真承诺，而真承诺是这个功能的全部产出。
SKIP_TITLE = re.compile(
    r"(独立董事候选人声明|独立董事提名人声明|董事候选人声明|监事候选人声明"
    r"|法律意见书|审计报告|内部控制评价报告"
    r"|议事规则|工作细则|管理制度|公司章程)")

# **上面那条名单有一处误伤，这一行是给它开的口子。**
#
# 《利润分配管理制度》《分红管理制度》长得跟《投资者关系管理制度》一样像模板，
# 但它里面写着「每年以现金方式分配的利润不少于当年可分配利润的百分之多少」——
# 那是一条带数字、能被证伪、而且年年都要核的承诺，可能是最该进台账的一类。
#
# 只给分红这一类开口子，不是给所有「管理制度」开：其余那些确实没有承诺。
KEEP_ANYWAY = re.compile(r"(利润分配|分红)")

# **「管理办法」没有进上面的排除名单，是想过之后的决定。**
#
# 它看起来跟「管理制度」「议事规则」是同一类模板文件，但《员工持股计划管理办法》
# 里写着锁定期和解锁的业绩条件——那是实打实、能被证伪的承诺。
# 排除掉就永久丢了这一类，所以改成降权：排到最后去读，预算够就还是读。

# 值得优先读的。抓取有上限，所以顺序决定了在预算内先读到哪几份。
#
# 这里只影响**读的顺序**，不影响能不能读——排在后面的公告只要预算没用完照样读。
PROMISE_HINTS = (
    ("回购", 10), ("增持", 10), ("承诺", 9), ("利润分配", 9), ("分红", 8),
    ("股权激励", 8), ("员工持股", 7), ("业绩", 7), ("重组", 6), ("收购", 6),
    ("减持", 5), ("募集资金", 5), ("投资", 3), ("股东大会决议", 3),
    # 见上：不排除，但排到最后。
    ("管理办法", -4),
)


def announcement_id(url: str | None) -> str:
    """从库里存的公告链接里取巨潮的公告编号。取不到返回空串。"""
    if not url or "announcementId" not in url:
        return ""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    value = (query.get("announcementId") or [""])[0].strip()
    return value if value.isdigit() else ""


def pdf_url(url: str | None) -> str:
    """把详情页链接换成 PDF 直链。拼不出来返回空串。"""
    ident = announcement_id(url)
    if not ident:
        return ""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(str(url)).query)
    # announcementTime 有时是 '2026-08-04'，有时是 '2026-08-07 20:16:09'。
    # 带时分秒的直接拼进 URL 会抛 InvalidURL（空格是控制字符）——截日期。
    day = (query.get("announcementTime") or [""])[0].strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return ""
    return f"http://static.cninfo.com.cn/finalpage/{day}/{ident}.PDF"


def skipped(title: str) -> bool:
    """这条是不是整类排除的套话公告。

    法律意见书、审计报告这类**第三方出具的文件永远排除**——它们是对某件事的
    见证，不是承诺本身，而承诺本身在另一份公告里，那份不会被挡。
    """
    text = str(title or "")
    if not SKIP_TITLE.search(text):
        return False
    # 第三方文件不开口子：《…关于股权激励计划的法律意见书》里没有承诺，
    # 承诺在《股权激励计划（草案）》里，那份没被挡。
    if re.search(r"(法律意见书|审计报告|声明)", text):
        return True
    return not KEEP_ANYWAY.search(text)


def _score(event: dict[str, Any]) -> int:
    title = str(event.get("title") or "")
    return sum(weight for word, weight in PROMISE_HINTS if word in title)


def readable(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """挑出能读正文的公告，按"像不像有承诺"排序。

    只排序、不截断——截断由调用方按预算决定，这样测试能单独验排序。
    """
    out = [event for event in events
           if pdf_url(event.get("url")) and not skipped(event.get("title") or "")]
    # 同分的按日期新在前：新公告里的承诺还没到期，旧的多半已经核过了。
    # 分两趟排（先日期倒序，再按分数稳定排序）——日期是字符串，取不了负号，
    # 塞进同一个 key 里只能同向排，那样"新在前"就变成了"旧在前"。
    out.sort(key=lambda event: str(event.get("event_date") or ""), reverse=True)
    out.sort(key=_score, reverse=True)
    return out


def _extract_text(body: bytes) -> str:
    import logging
    from io import BytesIO

    from pypdf import PdfReader

    # 巨潮的 PDF 有一批缺 EOF 标记，pypdf 会对每一份打一条 ERROR 日志。
    # 内容照样读得出来，而这条日志会把真正的错误淹掉——所以压到 CRITICAL。
    # **不是吞异常**：解析真失败了照样抛，由 fetch_one 记成"取不到"。
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    reader = PdfReader(BytesIO(body))
    parts: list[str] = []
    total = 0
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= MAX_TEXT_CHARS:
            break
    # PDF 抽出来的文字断行很碎（每行一个短句），压掉多余空白，
    # 否则模型看到的是一堆被折断的句子，原文引用就对不上了。
    joined = re.sub(r"[ \t　]+", " ", "\n".join(parts))
    return re.sub(r"\n{3,}", "\n\n", joined).strip()[:MAX_TEXT_CHARS]


def describe_body(body: bytes) -> str:
    """取回来的这坨东西是什么。**用在"不是 PDF"的错误消息里。**

    原来那两句消息是「这不是 PDF 文件」和「返回的不是 PDF，公告可能已撤下」——
    两句都在说"你的链接不对"，而实测最常见的原因根本不是链接：
    **服务器取到了一个几百字节的反爬校验页，而响应头里的 content-type 还写着
    application/pdf。** 使用者拿着同一个链接在本地能读、线上读不了，
    照着那句消息只会去反复检查链接。所以要说出取回来的到底是什么。
    """
    if not body:
        return "什么都没取到（0 字节）"
    head = body[:400].lstrip()
    size = f"{len(body)} 字节"
    if head[:5] == b"%PDF-":
        return f"是 PDF，但只有 {size}"
    text = head.decode("utf-8", "replace")
    if head[:1] == b"<":
        kind = "一段 JavaScript" if "<script" in text.lower() else "一个网页"
        return f"{size}的{kind}"
    if head[:1] in (b"{", b"["):
        return f"{size}的 JSON：{text[:80]}"
    return f"{size}，开头是 {text[:60]!r}"


def _looks_like_challenge(body: bytes) -> bool:
    """这是站点的反爬校验页吗。

    腾讯云 EdgeOne 的做法：返回一小段 JavaScript，让浏览器算两个 cookie 再重载。
    **我们不去解它**（里面的数字每次都变，解它就是在绕过站点的机器人校验）；
    认出来只为了两件事：换一个客户端再试一次，以及把话说清楚。
    """
    if len(body) > 4096 or body[:5] == b"%PDF-":
        return False
    return b"<script" in body[:400].lower()


def fetch_bytes(url: str) -> dict[str, Any]:
    """把一个链接取回来。返回 `{body, how, note}`；**取不到时 body 是空的**。

    ## 为什么会有第二条路

    实测：`https://pdf.dfcfw.com/pdf/...` 这个域名（东方财富，前面挂着腾讯云
    EdgeOne）对 **Python 的 urllib 返回 989 字节的反爬校验页**，而同一台机器上的
    curl 直接就拿到 1.5MB 的 PDF。逐项试过了：换 User-Agent 没用（curl 用我们
    这个 UA 也能过）、加 Accept / Accept-Language 没用、不带任何头也没用 ——
    **区别在 TLS 指纹和 HTTP 版本**（curl 协商 h2，urllib 走 HTTP/1.1）。

    所以：urllib 先试，**取回来的不是 PDF 就换 curl 再试一次**。
    这不是伪装成浏览器 —— UA 保持我们自己的名字（反正已经证明它无关），
    只是换一个原站会正常服务的标准客户端。校验页本身不解。
    """
    body, notes = b"", []
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _UA})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=FETCH_TIMEOUT) as response:
            body = response.read(MAX_PDF_BYTES + 1)
    except Exception as caught:  # noqa: BLE001 —— 网络什么都可能抛
        notes.append(f"直连失败：{type(caught).__name__}")

    if body[:5] == b"%PDF-":
        return {"body": body, "how": "urllib", "note": ""}
    if body:
        notes.append(f"直连取到的{describe_body(body)}")

    second = _fetch_with_curl(url)
    if second["body"][:5] == b"%PDF-":
        why = "站点的反爬校验页" if _looks_like_challenge(body) else "不是 PDF"
        return {"body": second["body"], "how": "curl",
                "note": f"直连取回来的是{why}，换 curl 取到了。"}
    if second["note"]:
        notes.append(second["note"])
    elif second["body"]:
        notes.append(f"换 curl 取到的{describe_body(second['body'])}")
    return {"body": second["body"] or body, "how": "", "note": "；".join(notes)}


def _fetch_with_curl(url: str) -> dict[str, Any]:
    """用 curl 取一次。**参数走列表，不过 shell**（url 是使用者给的）。

    `--proto` 锁死 http/https：这个链接由使用者提供，不加这一条 curl 会乐意去读
    `file://` 和 `gopher://`。
    """
    import shutil
    import subprocess

    exe = shutil.which("curl")
    if not exe:
        return {"body": b"", "note": "这台机器上没有 curl，第二条路走不了"}
    try:
        done = subprocess.run(
            [exe, "-sS", "--location", "--proto", "=http,https",
             "--proto-redir", "=http,https",
             "--max-time", str(FETCH_TIMEOUT), "--max-filesize", str(MAX_PDF_BYTES),
             "-A", _UA, url],
            capture_output=True, timeout=FETCH_TIMEOUT + 5, check=False)
    except Exception as caught:  # noqa: BLE001
        return {"body": b"", "note": f"curl 起不来：{type(caught).__name__}"}
    if done.returncode != 0:
        why = done.stderr.decode("utf-8", "replace").strip()[:120]
        return {"body": b"", "note": f"curl 也取不到（退出码 {done.returncode}）：{why}"}
    return {"body": done.stdout, "note": ""}


def fetch_one(url: str) -> dict[str, Any]:
    """抓一份公告正文。**不抛异常**——失败也是要写进库的结果。"""
    target = pdf_url(url)
    if not target:
        return {"status": "取不到", "body": "", "note": "这条公告没有巨潮的编号，拼不出正文地址"}
    got = fetch_bytes(target)
    body = got["body"]
    if not body:
        return {"status": "取不到", "body": "", "note": got["note"] or "下载失败"}

    if len(body) > MAX_PDF_BYTES:
        return {"status": "取不到", "body": "",
                "note": f"文件超过 {MAX_PDF_BYTES // 1024 // 1024}MB，超出了单份的处理上限"}
    if body[:5] != b"%PDF-":
        # **说出取回来的是什么。** 原来这里写「公告可能已撤下」——
        # 那是一个猜测，而且是最常见原因之外的那个猜测。
        return {"status": "取不到", "body": "",
                "note": f"取回来的不是 PDF：{got['note'] or describe_body(body)}"}

    try:
        text = _extract_text(body)
    except Exception as caught:  # noqa: BLE001
        return {"status": "取不到", "body": "", "note": f"解析失败：{type(caught).__name__}"}

    if not text:
        # 扫描件没有文字层。这不是错误，是这份公告本来就取不到文字。
        return {"status": "取不到", "body": "", "note": "PDF 里没有文字层，多半是扫描件"}
    return {"status": "已取正文", "body": text, "note": "", "pdf_url": target}


def fetch_many(urls: list[str]) -> dict[str, dict[str, Any]]:
    """并发抓一批，返回 {url: 结果}。顺序无关，失败也在结果里。"""
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        results = list(pool.map(fetch_one, urls))
    return dict(zip(urls, results))


# 承诺句里几乎必然出现的词。用来在长公告里定位该读哪一段。
_DENSE = ("不低于", "不超过", "不高于", "承诺", "期限", "个月", "回购", "增持",
          "分红", "%", "亿元", "万元", "不减持")


def excerpt(body: str, limit: int = PROMPT_CHARS) -> str:
    """截给模型看的那一段。**挑承诺最密的一段，不是简单取开头。**

    直接取前 3000 字是一刀静默的截断：一份二十页的公告，承诺条款在第十页的话
    就永远看不到，而表现出来是"这条公告里没有承诺"——跟真的没有一模一样。

    所以按关键词密度扫一遍，取得分最高的那个窗口。开头有天然加成
    （摘要和要点通常在前面），但不是硬规定，正文里更密的那段能赢过它。
    """
    text = str(body or "").strip()
    if len(text) <= limit:
        return text

    step = max(1, limit // 4)
    best_start, best_score = 0, -1
    for start in range(0, len(text) - limit + step, step):
        window = text[start:start + limit]
        score = sum(window.count(word) for word in _DENSE)
        # 开头那一段加两分：公告的要点通常写在前面，同分时优先取它。
        if start == 0:
            score += 2
        if score > best_score:
            best_start, best_score = start, score
    if best_start == 0:
        return text[:limit]
    # **截掉了多少要说出来。** 不说的话，模型看到的是一段没头没尾的正文，
    # 而使用者看到的是"读了这份公告"，两边都不知道中间少了什么。
    return (f"（这份公告共 {len(text)} 字，下面是其中承诺条款最密集的一段，"
            f"从第 {best_start} 字开始）\n{text[best_start:best_start + limit]}")


# ------------------------------------------------------------------ 长文档：先定位，再读

# 一次喂给模型的最大字数。M3 是百万上下文，这个数远没到上限——
# 定这个数不是因为读不下，是因为**没必要**：要找的那一节通常只有几千字，
# 把整份年报塞进去只是让它在几十万字里找一句话，又慢又容易走神。
WINDOW_CHARS = 60_000

# 相邻窗口之间的重叠。**一节内容正好跨在窗口边界上时，两边都读不全。**
# 视觉接口会把长边压到 1568 像素以内，所以长图必须先在本地切片再送。
WINDOW_OVERLAP = 2_000


def find_section(body: str, headings: tuple[str, ...], span: int = 6_000) -> list[dict[str, Any]]:
    """在长文里定位某一节，返回命中的那几段（带位置）。

    ## 为什么先定位而不是通读

    年报实测 16 万～64 万字。M3 能一次读完，但**要找的那一节只有几千字**，
    把整份塞进去是让它在六十万字里找一句话——慢、贵，而且容易读串。

    而这些是**标准化披露**：「主要销售客户和主要供应商情况」这个标题
    在每家的年报里都长一样。用它定位是确定性的，一次模型调用都不用花。

    定位不到时返回空列表，**由调用方决定要不要退回通读**——
    这里不替它做主，因为"找不到"和"没披露"是两件事。
    """
    text = str(body or "")
    if not text:
        return []
    out: list[dict[str, Any]] = []
    for heading in headings:
        start = 0
        while True:
            at = text.find(heading, start)
            if at < 0:
                break
            out.append({"heading": heading, "at": at,
                        "text": text[at:at + span]})
            start = at + len(heading)
    out.sort(key=lambda item: item["at"])
    return out


def windows(body: str, size: int = WINDOW_CHARS,
            overlap: int = WINDOW_OVERLAP) -> list[str]:
    """把长文切成有重叠的窗口，**用于定位不到、只能通读的情况**。

    读一段 → 记住这一段读出了什么 → 接着读下一段，而不是把中间砍掉。
    重叠是必须的：一节内容正好跨在边界上时，不重叠就两边都读不全。
    """
    text = str(body or "")
    if len(text) <= size:
        return [text] if text else []
    step = max(1, size - overlap)
    return [text[at:at + size] for at in range(0, len(text), step) if at < len(text)]
