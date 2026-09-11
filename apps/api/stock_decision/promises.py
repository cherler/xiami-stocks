"""管理层承诺兑现台账：公司说过的话，到期之后有没有人回头看。

## 为什么这件事没人做

「未来三年现金分红比例不低于 30%」「拟回购不低于 5 亿元、期限 12 个月」
「2026 年扣非净利润不低于 8 亿元」——这些话说出来的那天是利好，股价会涨，
研报会引用。而到期日**没有任何一个提醒，没有任何一处记录**。

后果是：一家从不兑现承诺的公司，和一家次次说到做到的公司，
在你的档案里长得一模一样。而这恰恰是判断管理层最硬的一个证据来源——
比调研纪要、比投资者关系问答硬得多，因为它是可以被证伪的。

## 跟认错条件是同一个形状

**一句话 + 一个到期日 + 一个到期时能核对的条件。**
这不是巧合：它们都是「在清醒的时候把未来某天要检查的事写下来」。
所以这里复用同一条纪律——到期了要顶到你面前，而不是等你想起来去查。

## 抽取从严：宁可漏一条，不要编一条

一条编出来的承诺会变成你对管理层的成见，而成见不会被复核。所以：

- **必须有原文。** statement 是从公告里抄的那句话，不许改写、不许概括。
- **必须能被证伪。** 「将努力提升股东回报」不是承诺，是修辞，不收。
  能收的是带数字、带比例、带期限的那种。
- **推不出到期日就留空。** 留空的会进「没有明确期限」那一栏等你补，
  而猜一个日期会让台账在错误的那天报"未兑现"。
- **拿不准就不收。** 漏掉一条只是回到现在的状态；编出来一条会误导判断。

## 到期之后，能算的自己算，算不了的问你

净利润、营业收入、分红比例这几类，库里有报表数据，到期直接比对——
**这部分完全不经过模型**，是纯算术。

回购进度、项目达产、增持完成度这些库里没有，到期问你一句，你自己去看后续公告。

**一条都不自动判「未兑现」。** 自动核对只输出"对上了 / 没对上 / 数据不够"，
而「这家管理层靠不靠谱」是判断，判断由人来下。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from . import llm
from .jsonio import Truncated, loads_or_reformat
from .llm import ai_available

# 承诺的类别。分类只是为了让台账能按类型看，不参与任何判断。
CATEGORIES = ("回购", "增持", "分红", "业绩", "锁定减持", "募投项目", "重组对赌", "治理", "其他")

# 能机器核对的指标。**只有这三个**——库里有报表数据、口径明确、算术确定。
# 回购进度、项目达产这些库里没有，硬编一个"自动核对"只会得出错的结论。
CHECKABLE = {
    "净利润": "financial:net_profit",
    "营业收入": "financial:revenue",
    "分红比例": "profile:latest_dividend_payout_ratio",
}

OPERATORS = {">=": "不低于", "<=": "不高于", ">": "高于", "<": "低于", "==": "等于"}

# 到期日过了多久还没人核对，就顶到面前来。给两周：定期报告要等披露。
DUE_GRACE_DAYS = 14

EXTRACT_SYSTEM_PROMPT = """你在从上市公司公告里，把**管理层做出的、可以被证伪的承诺**挑出来。

## 什么算承诺

必须同时满足三条，缺一条就不要收：

1. **有明确的行为或结果**：回购不低于多少钱、增持不低于多少股、
   分红比例不低于百分之多少、净利润不低于多少、几年内不减持、
   某项目何时达产。
2. **有数字或有期限**（至少有一样）。
3. **是承诺，不是预测也不是修辞**。
   - 收：「拟在 12 个月内回购不低于 3 亿元」
   - 收：「控股股东承诺 6 个月内不减持」
   - 收：「未来三年每年现金分红不低于当年净利润的 30%」
   - **不收**：「将努力提升股东回报」（修辞）
   - **不收**：「预计明年营收增长 20%」（预测，不是承诺）
   - **不收**：「本次回购已实施完毕」（这是结果，不是承诺）

## 三条硬规矩

1. **statement 必须是公告标题或正文里的原话**，照抄，不许改写、不许概括、
   不许把两句话并成一句。抄不到原话的就不要收这一条。
2. **到期日推不出来就留空**。「12 个月内」+ 公告日期可以推；
   「适时」「择机」「未来」推不出来 —— 留空，不要猜。
   **猜一个日期会让台账在错误的那天报「未兑现」。**
3. **拿不准就不收。** 漏掉一条只是回到现在的状态，编出来一条会变成
   使用者对管理层的成见，而成见不会被复核。

## 能被机器核对的那几条，多填三个字段

只有指标是 净利润 / 营业收入 / 分红比例 这三个之一时才填，别的一律留空：
- check_metric：净利润 / 营业收入 / 分红比例
- check_op：>= / <= / > / < / ==
- check_value：数字。**金额一律用元**（「8 亿元」写 800000000），比例用百分数（30% 写 30）
- check_period：要核对哪一期，写 YYYY-12-31 这种报告期；不确定就留空

只输出 JSON：
{"promises": [
  {"subject": "公司", "statement": "拟回购不低于人民币3亿元，回购期限12个月",
   "category": "回购", "promised_on": "2026-03-14", "due_date": "2027-03-13",
   "check_metric": "", "check_op": "", "check_value": null, "check_period": "",
   "source_index": 1}
]}
一条都没有就返回 {"promises": []}。"""

# 重排时告诉模型该长成什么样。跟上面那段示例同形，两处写岔的话重排会照着
# 另一个形状改，改出来是合法 JSON 但字段对不上，然后静静地读出一堆空值。
REFORMAT_SHAPE = ('{"promises": [{"subject": "…", "statement": "公告原话", "category": "回购", '
                  '"promised_on": "2026-03-14", "due_date": "2027-03-13", '
                  '"check_metric": "", "check_op": "", "check_value": null, '
                  '"check_period": "", "source_index": 1}]}')

# 一批最多写多长。**原来是 3000，而一批塞得下 24,000 字正文。**
# 一份回购报告书里能有四五条带数字带期限的承诺，几份撞在同一批里就会撞线；
# 撞线的表现是这一批整个丢掉，而界面上写的是"这家公司没有承诺"。
# 冻结额不跟 max_tokens 挂钩（见 llm.estimate_tokens），调大不会挡住任何人。
MAX_ANSWER_TOKENS = 20000


def build_prompt(events: list[dict[str, Any]]) -> str:
    """**正文有就给正文。** 只给标题的话，这个功能不可能有产出——

    「关于股份回购进展情况的公告」这十四个字里没有承诺，承诺在正文的
    「不低于人民币 50 亿元」「不超过 12 个月」里。见 disclosure.py 开头。
    """
    from .disclosure import excerpt

    parts = ["这家公司的公告：\n"]
    for index, event in enumerate(events, 1):
        parts.append(
            f"\n{index}. [{event.get('category') or '公告'}] {event.get('event_date') or ''}"
            f" {str(event.get('title') or '')[:200]}")
        body = str(event.get("body") or "").strip()
        if body:
            parts.append(f"\n   公告正文：\n{excerpt(body)}\n")
            continue
        detail = str(event.get("summary") or event.get("detail") or "").strip()
        if detail:
            # 没抓到正文时退回摘要。**要说明这是摘要不是原文**——
            # 否则模型会把摘要里的转述当成原话抄进 statement，
            # 而 statement 的全部价值就在于它是原话。
            parts.append(f"\n   摘要（不是原文，据此抽出的承诺不要当原话引用）：{detail[:400]}")
    return "".join(parts)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else ""


# 一次调用最多塞多少字的正文。**超了就分批，不截断。**
#
# 截断是这里最容易犯也最难发现的错：被截掉的那几条公告不会报错、不会留痕，
# 只会表现为"这家公司没有承诺"——跟真的没有承诺长得一模一样。
BATCH_BODY_CHARS = 24_000

# 批次之间互不依赖，并发读。跟切图那边同一个数。
BATCH_CONCURRENCY = 4


def _batches(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按正文长度分批。带正文的公告很占地方，一批塞不下就下一批。"""
    from .disclosure import PROMPT_CHARS

    out: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    used = 0
    for event in events:
        cost = min(len(str(event.get("body") or "")), PROMPT_CHARS)
        if current and used + cost > BATCH_BODY_CHARS:
            out.append(current)
            current, used = [], 0
        current.append(event)
        used += cost
    if current:
        out.append(current)
    return out


_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")

# 对原文时忽略的字符：空白、中英文标点、百分号。
#
# 同一句话在 PDF 里的排版跟模型抄出来的几乎总有细微差别（「15亿元」vs「15 亿元」、
# 括号全角半角、换行处多一个空格），按字面比会把真正的原话也判成改写。
_IGNORABLE = re.compile(r"[\s，。、；：（）()【】「」《》\"'%％·．,.]")

# 修复拼接时，允许补回来的最长跨度倍数。
#
# 模型常见的改写方式是**把中间一段删掉再接起来**（「同意公司使用自有资金…回购
# 部分股份」＋「回购的资金总额不低于 20 亿元」中间删掉了"用于实施股权激励计划"）。
# 这种情况原文是连续的，可以把中间那段补回来还原成真正的原话。
#
# 但补回来的跨度不能没有上限：两个碎片如果分散在正文两头，中间夹着几千字，
# 那就不是"删了一句连接词"，而是**模型把两件不相干的事拼成了一条承诺**——
# 那种必须当作找不到原文处理，不能靠补全把它洗白。
MAX_STITCH_RATIO = 1.8


def _flat(text: str) -> str:
    return _IGNORABLE.sub("", str(text or ""))


def verbatim_check(statement: str, body: str) -> dict[str, Any]:
    """这句话是不是真的在这份公告里。**纯字符串比对，不经过模型。**

    ## 为什么必须机器来对

    「statement 必须是原话」这条规矩现在只写在提示词里，而实测**37 条里有 7 条
    不是原话**（约 19%）：模型把两句话中间的内容删掉再接起来。

    这件事的后果比听起来严重：statement 的全部价值就在于你能点进公告去核对它。
    对不上一次，整张台账就都不敢信了——**而一张不敢信的台账等于没有台账。**

    返回 {"verdict": 原文/拼接/找不到, "statement": 修正后的原话, "note": ...}

    - **原文**：照抄的，原样收下。
    - **拼接**：碎片都在正文里、位置连得上——把中间删掉的那段补回来，
      还原成真正的原话。这不是纵容，是**把它变成能核对的**。
    - **找不到**：正文里没有这句话。**丢掉。** 提示词本来就写着
      "抄不到原话的就不要收这一条"，现在由代码来执行。
    """
    flat_statement, flat_body = _flat(statement), _flat(body)
    if not flat_statement or not flat_body:
        return {"verdict": "找不到", "statement": statement,
                "note": "这条公告没有正文可对，没法确认是不是原话"}
    if flat_statement in flat_body:
        return {"verdict": "原文", "statement": statement, "note": ""}

    # 拿开头和结尾两段去正文里定位。**两头都要找到**——只找到开头的话，
    # 后半句可能是模型自己接上去的，那正是最该被挡住的一种。
    head, tail = flat_statement[:12], flat_statement[-12:]
    start = flat_body.find(head)
    if start < 0:
        return {"verdict": "找不到", "statement": statement,
                "note": "正文里找不到这句话的开头，这一条不收"}
    end = flat_body.find(tail, start + len(head))
    if end < 0:
        return {"verdict": "找不到", "statement": statement,
                "note": "正文里找不到这句话的结尾，可能是模型自己接上去的，这一条不收"}

    span = end + len(tail) - start
    if span > len(flat_statement) * MAX_STITCH_RATIO:
        return {"verdict": "找不到", "statement": statement,
                "note": f"这句话的头尾在正文里相隔 {span} 字，"
                        f"中间隔得太远——多半是把两件事拼成了一条，这一条不收"}

    # 补回中间删掉的那段。**要在原始正文（带标点）里取**，
    # 不能拿去掉标点的那份——还原出来的"原话"没有标点就不叫原话了。
    original = _restore(body, start, end + len(tail))
    return {"verdict": "拼接", "statement": original,
            "note": "模型把中间一段删掉再接起来了，已按公告原文补回"}


def _restore(body: str, flat_start: int, flat_end: int) -> str:
    """把去标点后的下标映射回原始正文，取出那一段带标点的原话。"""
    mapping: list[int] = []
    for index, char in enumerate(body):
        if not _IGNORABLE.match(char):
            mapping.append(index)
    if not mapping or flat_start >= len(mapping):
        return body[:0]
    begin = mapping[flat_start]
    finish = mapping[min(flat_end, len(mapping)) - 1] + 1
    return body[begin:finish].strip()


def _same_promise(item: dict[str, Any]) -> tuple[str, str, str]:
    """同一条承诺的指纹：**承诺人** + 类别 + 句子里的那串数字。

    **一条回购承诺会在每份进展公告里重述一遍**，实测茅台一轮抽出 15 条里有 5 条
    是同一句「回购不低于 15 亿元且不超过 30 亿元」。逐条确认时它们看着像五件事，
    记进台账就是五条到期日相同、内容相同的记录——**台账被同一句话灌满，
    跟被套话灌满是一个后果：没人再看它。**

    按数字认而不按字面认，是因为同一句话在不同公告里的排版不一样
    （「15亿元」和「15 亿元」、带不带"人民币"），字面比对认不出来。

    ## 承诺人必须进指纹，否则会去重去过头

    锁定减持类公告里，几个股东**各自**作出同一句承诺是常态：

        珠海明骏承诺自本公告之日起 6 个月内不减持公司股份
        京海互联承诺自本公告之日起 6 个月内不减持公司股份

    类别相同、数字都是「6」—— 不带承诺人的话这两条的指纹一模一样，
    于是京海互联那一条被静默丢掉。**而丢掉的是一条真承诺**：
    台账的用处正是"谁说过什么话、后来做到没有"，把承诺人抹掉，
    剩下的那半张台账连问题都问不出来。
    """
    numbers = ",".join(_DIGITS.findall(str(item.get("statement") or "")))
    return (str(item.get("subject") or ""), str(item.get("category") or ""), numbers)


def extract(events: list[dict[str, Any]], timeout: int = 120,
            failures: list[str] | None = None) -> list[dict[str, Any]]:
    """从一批公告里抽出承诺。**只抽取，不落库**——每条都要人确认。

    failures 传一个列表进来，读失败的批次会写在里面。**调用方要把它报给使用者**：
    静默丢一批会表现成"这家公司没有承诺"，跟真的没有承诺长得一模一样。
    """
    if not events:
        return []
    if failures is None:
        failures = []
    available, reason = ai_available()
    if not available:
        raise RuntimeError(reason)

    batches = _batches(events)

    def read(batch: list[dict[str, Any]]) -> list[Any]:
        completion = llm.call(EXTRACT_SYSTEM_PROMPT, build_prompt(batch),
                              task="promise-extract", max_tokens=MAX_ANSWER_TOKENS, timeout=timeout)
        # 一批就是一次真调用（实测格力一轮 3 批 35,822 token、8 分）。
        # 最后一段格式坏了就丢掉整批，等于把这一批公告的钱白花 —— 而它表现出来
        # 只是"这几条公告里没有承诺"，跟真的没有承诺长得一模一样。
        payload, _ = loads_or_reformat(completion.text, task="promise-extract",
                                       shape=REFORMAT_SHAPE, timeout=timeout)
        chunk = payload.get("promises") if isinstance(payload, dict) else None
        if not isinstance(chunk, list):
            return []
        # source_index 是**这一批里**的序号，模型看不到别的批次。
        # 直接汇总会让第二批的第 1 条指到第一批的第 1 条公告上——
        # 出处指错比没有出处更糟，所以在这里就把它换成公告本身。
        out: list[Any] = []
        for item in chunk:
            if isinstance(item, dict):
                try:
                    item["_event"] = batch[int(item.get("source_index", 0)) - 1]
                except (ValueError, TypeError, IndexError):
                    item["_event"] = None
                out.append(item)
        return out

    def note_failure(index: int, batch: list[dict[str, Any]], caught: BaseException) -> None:
        """**失败必须留痕。** 静默返回空列表的话，一次限流会表现成
        "这家公司没有承诺"，跟真的没有承诺长得一模一样。

        两种失败要分开说：**没写完**是长度上限掐的，跟"这批公告有没有承诺"
        无关；别的（限流、超时、格式坏到重排也救不回来）另说。混成一句
        「读失败」的话，使用者不知道该重点一次还是该来找我。
        """
        why = ("这一批写到一半被长度上限掐断了" if isinstance(caught, Truncated)
               else f"没读成功（{type(caught).__name__}）")
        failures.append(f"第 {index + 1} 批{why}——"
                        f"这一批里的 {len(batch)} 条公告没被看过，再点一次会重读。")

    raw: list[Any] = []
    if len(batches) == 1:
        # **一批也要走同一条兜底。** 原来这条路是裸调用：一次坏 JSON 直接把
        # 整个任务打成"失败"，而使用者看到的是一句 JSONDecodeError。
        # 现在跟多批一样，如实说"这一批没读成功"，并且照旧把已读几份正文报出来。
        try:
            raw = read(batches[0])
        except Exception as caught:  # noqa: BLE001
            note_failure(0, batches[0], caught)
    else:
        # 读了正文之后一次抽取有五六批，串行要两三分钟。批次之间互不依赖，
        # 并发跑就行。
        #
        # **上下文要显式带进线程，而且每个线程一份。** 数据域和计费主体都在
        # contextvars 里，ThreadPoolExecutor 不会自动复制；不带的话这几次调用
        # 会记到系统身上而不是这个用户身上。
        #
        # 而**一份 Context 不能被多个线程同时进入** —— 复制一份共用会让
        # 除第一个线程外全部抛 "cannot enter context: ... is already entered"。
        # 这个错我在这里犯过一次，当时的表现是"12 批只有 1 批有结果"，
        # 而结果看起来完全正常：少了的那 11 批不报错，只是没有承诺。
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        contexts = [contextvars.copy_context() for _ in batches]

        def guarded(item: tuple[int, list[dict[str, Any]]]) -> list[Any]:
            index, batch = item
            try:
                return contexts[index].run(read, batch)
            except Exception as caught:  # noqa: BLE001 —— 一批失败不该带走其余几批
                note_failure(index, batch, caught)
                return []

        with ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY) as pool:
            for chunk in pool.map(guarded, enumerate(batches)):
                raw.extend(chunk)

    out: list[dict[str, Any]] = []
    dropped_not_verbatim: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or "").strip()
        promised_on = _as_date(item.get("promised_on"))
        # 没有原话、没有说这话的日期，这一条就没法核对也没法追溯 —— 不收。
        if not statement or not promised_on:
            continue
        # 指不到出处的承诺不许进台账。**猜一个出处比没有出处更糟**：
        # 你会点进去发现那条公告根本没说过这句话，然后整张台账都不敢信了。
        event = item.get("_event")
        if not isinstance(event, dict):
            continue

        metric = str(item.get("check_metric") or "").strip()
        operator = str(item.get("check_op") or "").strip()
        value = _as_float(item.get("check_value"))
        checkable = metric in CHECKABLE and operator in OPERATORS and value is not None
        out.append({
            "subject": str(item.get("subject") or "公司").strip()[:40],
            "statement": statement[:500],
            "category": (str(item.get("category") or "其他").strip()
                         if str(item.get("category") or "").strip() in CATEGORIES else "其他"),
            "promised_on": promised_on,
            "due_date": _as_date(item.get("due_date")),
            "check_metric": metric if checkable else "",
            "check_op": operator if checkable else "",
            "check_value": value if checkable else None,
            "check_period": _as_date(item.get("check_period")) if checkable else "",
            "event_id": event.get("id"),
            # 只为下面回原文核对用，核完就 pop 掉，不进返回值。
            "_source_event": event,
            "source_title": str(event.get("title") or "")[:300],
            "source_url": event.get("url"),
        })

    # **回原文核对。纯字符串比对，不经过模型，不花钱。**
    #
    # 「statement 必须是原话」这条规矩原来只写在提示词里，而实测 37 条里有 7 条
    # 不是（约 19%）：模型把两句话中间的内容删掉再接起来。statement 的全部价值
    # 就在于你能点进公告去核对它——对不上一次，整张台账就都不敢信了。
    checked: list[dict[str, Any]] = []
    # **丢掉的要说出来。** 静默丢弃跟"这家公司没有这条承诺"长得一模一样，
    # 而这里丢掉的恰恰是模型编得最像的那几条。
    for item in out:
        event = item.pop("_source_event", None)
        body = str((event or {}).get("body") or "")
        if not body:
            # 没有正文可对的（只读到标题那几条）照原样收，但要标出来：
            # **"没核过"和"核过了"必须能分辨**。
            item["verbatim"] = "没有正文可对"
            checked.append(item)
            continue
        verdict = verbatim_check(item["statement"], body)
        if verdict["verdict"] == "找不到":
            # **丢之前先去别的公告里找一遍。**
            #
            # 实测丢掉的那几条里，有些句子本身是真的、原文也在，只是模型把出处
            # 指到了另一份公告上（同一条回购承诺会在好几份公告里重述）。
            # 直接丢等于因为一个指错的链接扔掉一条真承诺——**改出处比丢掉好**，
            # 前提是新出处能唯一确定：找到两份都含这句话时不猜，照旧丢。
            elsewhere = [other for other in events
                         if other.get("body")
                         and _flat(item["statement"]) in _flat(str(other["body"]))]
            if len(elsewhere) == 1:
                fixed = elsewhere[0]
                item["event_id"] = fixed.get("id")
                item["source_title"] = str(fixed.get("title") or "")[:300]
                item["source_url"] = fixed.get("url")
                item["verbatim"] = "原文"
                item["verbatim_note"] = "模型指错了出处，已按原文所在的公告更正"
                checked.append(item)
                continue
            dropped_not_verbatim.append(f"「{item['statement'][:28]}…」——{verdict['note']}")
            continue
        item["statement"] = verdict["statement"]
        item["verbatim"] = verdict["verdict"]
        if verdict["note"]:
            item["verbatim_note"] = verdict["note"]
        checked.append(item)
    out = checked
    if dropped_not_verbatim:
        failures.append(
            f"有 {len(dropped_not_verbatim)} 条在公告原文里对不上，已丢弃："
            + "；".join(dropped_not_verbatim[:3])
            + ("…" if len(dropped_not_verbatim) > 3 else ""))

    # 去重：同一条承诺被多份进展公告重述时只留一条。
    #
    # **留最早说的那一份**——承诺是在原始公告那天做出的，到期日从那天起算；
    # 留进展公告会让到期日整体往后漂，而漂了的到期日永远不会准时提醒你。
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in sorted(out, key=lambda row: row["promised_on"]):
        key = _same_promise(item)          # (承诺人, 类别, 数字)
        # 数字都抽不出来的（纯文字承诺）不参与去重——它们本来就该逐条看。
        if not key[2]:
            unique[(key[0], key[1], item["statement"])] = item
            continue
        unique.setdefault(key, item)

    # 第二趟：**同一份公告里，被拆成碎片的同一条承诺合起来。**
    #
    # 模型有时抽整句「回购价格不超过 1863.67 元/股，回购金额不低于 15 亿元…」，
    # 有时把它拆成「回购价格不超过 1863.67 元/股」和「回购金额不低于 15 亿元」两条。
    # 数字集合不同，第一趟认不出来。
    #
    # **按数字包含来合并时，只在同一条公告内部**，这是安全线：不同公告里数字碰巧包含
    # （「未来 3 个月、6 个月不减持」被并进某条带 3 和 6 的承诺）就会误伤，
    # 而误伤掉的是真承诺。同一份公告里的碎片则确实是同一件事。
    #
    # **但「一句话整个落在另一句话里面」是跨公告也成立的。** 2026-08-15 线上实测
    # （格力，5 条里有 2 条是同一件事）：
    #
    #   方案公告 4635（04-29）  回购资金总额不低于 50 亿元…回购价格不超过 56.55 元/股
    #   进展公告 4574（08-04）  回购资金总额不低于 50 亿元…56.55 元/股，回购期限…12 个月
    #
    # 数字集合是 {50,100,56.55} 与 {50,100,56.55,12}，第一趟的指纹不同；
    # 第二趟被 event_id 那一条挡住 —— 于是台账里一件事记了两遍。而这个模块的
    # 开头写着「台账被同一句话灌满，跟被套话灌满是一个后果：没人再看它」。
    #
    # 文本包含比数字包含强得多：短的那句**逐字**就是长的那句的一段，
    # 不可能是"数字碰巧撞上"。所以这一种跨公告也合。
    #
    # **留长的那条**（下面按长度倒序，先进 merged 的就是留下的）。乍看跟上面
    # 「留最早说的那一份」相反，其实是同一个目的：长的那句多出来的正是
    # 「回购期限…12 个月」，而到期日就是从这句推出来的 —— 上面那次实测里，
    # 短的那条的 due_date 是空的。**留下短的，这条承诺就永远不会到期。**
    kept = list(unique.values())
    merged: list[dict[str, Any]] = []
    for item in sorted(kept, key=lambda row: -len(row["statement"])):
        numbers = set(_DIGITS.findall(item["statement"]))
        flat = _flat(item["statement"])
        if any(
                # 承诺人也要一致 —— 见 _same_promise：几个股东各自说同一句话
                # 是锁定减持类公告的常态，合掉的话丢的是一条真承诺。
                other["subject"] == item["subject"]
                and other["category"] == item["category"]
                and ((flat and flat in _flat(other["statement"]))
                     or (numbers and other["event_id"] == item["event_id"]
                         and numbers < set(_DIGITS.findall(other["statement"]))))
                for other in merged):
            continue
        merged.append(item)
    return merged


# ------------------------------------------------------------------ 到期核对（纯算术）

def _is_annual(period: Any) -> bool:
    """这一期是不是年报。

    两种写法都要认：财报表里是 ISO 日期（`2025-12-31`），
    而档案里的分红期次是中文（`2025年报` / `2026中报` / `2025三季报`）——
    两处的数据源不同，只认一种的话另一种会被整类判成"没有年报"。
    """
    text = str(period or "")
    return text.endswith("12-31") or "年报" in text


def auto_check(promise: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """能算的自己算。**这一段完全不经过模型。**

    facts 形如 {"net_profit": {"2026-12-31": 812000000.0}, ...}
    返回 {"verdict": 对上了/没对上/数据不够/不能自动核, "actual": …, "note": …}
    """
    metric = promise.get("check_metric") or ""
    operator = promise.get("check_op") or ""
    target = promise.get("check_value")
    if metric not in CHECKABLE or operator not in OPERATORS or target is None:
        return {"verdict": "不能自动核", "actual": None,
                "note": "这条承诺没有可以直接比对的量化指标——回购进度、项目达产这些"
                        "库里没有数据，要你自己看后续公告。"}

    field = CHECKABLE[metric].split(":", 1)[1]
    series = facts.get(field) or {}
    period = promise.get("check_period") or ""
    actual = series.get(period) if period else None
    if actual is None and not period:
        # 没指定报告期时**只认年报**，并且说出来用的是哪一期。
        #
        # 原来这里取的是 `max(series)` —— 库里最新的那一期。而库里最新的
        # 那一期通常不是年报：2026-08-15 线上格力的 financial_periods 最新是
        # **2026-03-31（一季报）**，档案里的分红比例最新是 **2025 三季报**。
        #
        # 于是一条「2026 年净利润不低于 8 亿元」的承诺，会拿一季度的累计净利润
        # 去跟全年目标比，然后在台账上写「没对上」。**那不是算术错，是拿错了期**，
        # 而使用者读到的是"这家公司食言了"。
        #
        # 这个模块自己的规矩是「猜一个日期会让台账在错误的那天报未兑现」，
        # 同一句话原样适用于报告期：拿不准就说数据不够，不要凑一个数出来判。
        annual = {key: value for key, value in series.items() if _is_annual(key)}
        if annual:
            period = max(annual)
            actual = annual[period]
        elif series:
            latest = max(series)
            return {"verdict": "数据不够", "actual": None,
                    "note": f"这条承诺没写明要核对哪一期，而库里最新的一期是 {latest}，"
                            f"不是年报。季报是累计口径，拿它去对一条年度承诺会得出"
                            f"错的结论。等年报同步进来再看，或者给这条承诺补一个报告期。"}
    if actual is None:
        return {"verdict": "数据不够", "actual": None,
                "note": f"库里没有 {period or '对应报告期'} 的{metric}。"
                        f"先到公司档案里同步一次财务再看。"}

    ok = {">=": actual >= target, "<=": actual <= target, ">": actual > target,
          "<": actual < target, "==": abs(actual - target) < 1e-6}[operator]
    return {
        "verdict": "对上了" if ok else "没对上",
        "actual": actual,
        "period": period,
        "note": (f"{period} 的{metric}是 {_pretty(actual, metric)}，"
                 f"承诺是{OPERATORS[operator]} {_pretty(target, metric)}。"
                 f"**这是算术，不是判断**——为什么会这样、算不算食言，要你自己看。"),
    }


def _pretty(value: float, metric: str) -> str:
    if metric == "分红比例":
        return f"{value:g}%"
    return f"{value / 1e8:.2f} 亿元" if abs(value) >= 1e8 else f"{value:,.0f} 元"


def summarize(rows: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """把台账数一遍。**只计数，不评价管理层。**"""
    today = today or date.today()
    total = len(rows)
    if total == 0:
        return {"total": 0, "due": 0, "kept": 0, "broken": 0, "undated": 0, "pending": 0,
                "headline": "还没有记录任何承诺。",
                "note": "到公司档案里点一次「从公告里找承诺」，"
                        "系统会把管理层说过的、可以被证伪的话挑出来给你确认。",
                "boundary": _BOUNDARY}

    kept = sum(1 for r in rows if r["status"] == "已兑现")
    broken = sum(1 for r in rows if r["status"] == "未兑现")
    undated = sum(1 for r in rows if not r.get("due_date"))
    due = sum(1 for r in rows
              if r["status"] == "待到期" and r.get("due_date")
              and r["due_date"] <= (today - timedelta(days=DUE_GRACE_DAYS)).isoformat())
    pending = sum(1 for r in rows if r["status"] == "待到期") - due

    parts = [f"记着 {total} 条承诺"]
    if kept or broken:
        parts.append(f"已核对 {kept + broken} 条（兑现 {kept}、未兑现 {broken}）")
    if due:
        parts.append(f"**{due} 条已经到期还没核对**")
    if undated:
        parts.append(f"{undated} 条没有明确期限")

    return {
        "total": total, "due": due, "kept": kept, "broken": broken,
        "undated": undated, "pending": max(0, pending),
        "headline": "，".join(parts) + "。",
        "note": (f"到期后给 {DUE_GRACE_DAYS} 天再提醒——定期报告要等披露，"
                 f"到期当天就催是不合理的。" if due else ""),
        "boundary": _BOUNDARY,
    }


# 页面底部那一句。**只留"它会不会骗我"，删掉"它为什么这么设计"**——
# 设计理由写在代码注释里给改代码的人看，不该占使用者的屏幕。
_BOUNDARY = (
    "每条都留着公告原话与出处；到期只说「对上了 / 没对上 / 数据不够」，"
    "**一条都不会被自动判成「未兑现」**——那是判断，由你来下。"
)
