"""这家公司未来有哪些日子在等着 —— 甘特图的原料。

## 为什么是甘特图，而不是又一张列表

台账和日历回答的都是「有哪些」。而承诺和解禁真正要问的是**「还有多久」**，
以及**「它们会不会撞在一起」**：一批解禁跟一条回购承诺同时到期，
是一件跟"分别有这两件事"完全不同的事，而列表说不出这个。

甘特图要求每一根都有**起点和终点**。这一页里真的有区间的只有两种：

- **承诺**：说出口那天 → 承诺的期限。一句承诺本身就是一段时间。
- **解禁**：公告那天 → 解禁那天，那就是锁定期。

## 先量了再画：三条泳道只有两条有数据

使用者要的是「承诺台账 + 解禁 + 募投进度」。量完线上库：

| 要画的      | 库里有没有 |
|-------------|-----------|
| 承诺台账    | 有（management_promises），但**多数没有到期日** |
| 解禁        | 有（company_calendar_events 里 86 条，带股数与市值） |
| **募投进度** | **没有**。没有这张表、日历里没有这个类别、公告也没抽过 |

**募投那条不画，而且要说出来。** 悄悄少一条，看的人会以为这家公司没有募投项目；
写一句"没有数据"，他才知道该去别处找。

## 没有期限的承诺不上这根轴

第一版把它们画成说出口那天的一个点，结果是**九个一模一样的点挤在同一条竖线上**
（同一份年报里抽出来的，公告日当然相同）。使用者：「这个图目前没有意义」。他是对的。

看清楚那 11 条之后，它们其实是两类：

- **有期限的**（5 条）：2 条库里就有到期日；3 条的期限写在原话里但是相对的
  （「期限不超过 1 年」「自股东会审议通过之日起 12 个月内」）→ `term_end()`
  按公告日推出来，**一律标成估算**，画成虚边。偏几周的日期仍然回答得了
  「这条承诺和那批解禁会不会撞上」，而一个点回答不了任何事。
- **没有期限的**（6 条）：「回购资金总额不低于 50 亿」「不低于 70% 用于注销」
  「390 亿闲置资金理财」—— 它们是**金额上限和比例约束，不是一段时间**。
  在台账里有意义，在时间轴上没有位置。

所以它们不上轴，但也不消失：泳道的说明里报数，并说清是哪一类。
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any

# 从原话里读期限：「期限不超过 1 年」「自股东会审议通过之日起 12 个月内」。
#
# **必须先出现「期限 / 之日起 / 有效期」这类词**，否则 `(\d+)年` 会把
# 「考核年度」「2026 年度」这种也吃进去，推出一个 2026 年长的承诺。
_HAS_TERM = re.compile(r"期限|之日起|有效期|存续期")
_MONTHS = re.compile(r"(?<!\d)(\d{1,3})\s*个?月(?!份)")
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*年(?!度|报|末|初|\d)")

# 解禁事件的 detail 长这样：
#     解禁 333.49 万股 · 解禁市值约 41.42 亿元 · 公告于 2025-10-21
# 三段都可能缺，所以三个独立的正则，谁匹配上算谁的。
_SHARES = re.compile(r"解禁\s*([\d.]+)\s*万股")
_VALUE = re.compile(r"解禁市值约\s*([\d.]+)\s*亿元")
_ANNOUNCED = re.compile(r"公告于\s*(\d{4}-\d{2}-\d{2})")

# 库里没有的那些泳道。**列出来而不是省掉** —— 少一条看不出来，
# 而"这家公司没有募投项目"和"我们没有这项数据"是两件完全不同的事。
#
# 募投那条从这里毕业了：它的数据源是「募集资金存放、管理与实际使用情况的专项报告」，
# 在「读文档」里读一次就落库（fundraising_projects）。**这是第一条
# 「读文档的结果喂给另一个功能」的链子。** 一家公司还没读过那份公告时，
# 这条泳道仍然是空的 —— 但那时候要说的是"去读一份"，不是"我们没有这项数据"。
NO_DATA: tuple[tuple[str, str], ...] = ()


def _lockup(detail: str) -> dict[str, Any]:
    """从解禁事件的 detail 里抠出股数、市值和公告日。抠不到的留空，不猜。"""
    shares = _SHARES.search(detail or "")
    value = _VALUE.search(detail or "")
    announced = _ANNOUNCED.search(detail or "")
    return {
        "shares_wan": float(shares.group(1)) if shares else None,
        "value_yi": float(value.group(1)) if value else None,
        "announced_on": announced.group(1) if announced else None,
    }


# 「自公司股东会审议通过本次回购方案之日起 12 个月内」—— 起点是股东会那天。
# 那个日期**库里已经有了**：日历里有 12 条「…股东会决议公告」。
_FROM_MEETING = re.compile(r"股东[大]?会审议通过")


def _add_months(day: date, months: int) -> date:
    """加整月，不是加 30 天。

    「12 个月」按 30 天算是 360 天，一年就差五天；三年差半个月。
    这个偏差**看不出来**（图上就是一根稍短的条），但它会让"这条承诺和那批解禁
    差几天"这种判断错掉，而那正是这张图存在的理由。
    """
    total = day.month - 1 + months
    year, month = day.year + total // 12, total % 12 + 1
    return day.replace(year=year, month=month,
                       day=min(day.day, calendar.monthrange(year, month)[1]))


def term_end(statement: str, promised_on: str,
             meetings: list[str] | None = None) -> tuple[str, bool] | None:
    """原话里写的是相对期限时，推一个到期日。返回 (日期, 是不是估算)。

    ## 起点尽量用真的那一天

    「本次回购的期限为**自公司股东会审议通过本次回购方案之日起 12 个月内**」——
    起点是股东会那天。以前拿公告日凑，偏两个多月；而那个日期**库里就有**：
    日历里的「…股东会决议公告」。`meetings` 传公告日之后最近的那些决议日，
    取第一个当起点 —— 这时候它就不是估算了，是能核对的。

    找不到决议公告才退回公告日，并**标成估算**：偏几周的日期仍然回答得了
    「这条承诺和那批解禁会不会撞上」，而一个点回答不了任何事。
    但它不许假装自己是精确的。
    """
    text = str(statement or "")
    if not promised_on or not _HAS_TERM.search(text):
        return None
    months = _MONTHS.search(text)
    years = _YEARS.search(text)
    if months:
        span_months = int(months.group(1))
    elif years:
        span_months = int(years.group(1)) * 12
    else:
        return None
    if not 0 < span_months <= 120:        # 十年以上多半是把某个数读错了
        return None
    base, guessed = promised_on, True
    if _FROM_MEETING.search(text):
        # 公告之后（含当天）最近的一次股东会决议 —— 那就是期限的起点。
        after = sorted(d for d in (meetings or []) if d >= promised_on)
        if after:
            base, guessed = after[0], False
    return _add_months(date.fromisoformat(base), span_months).isoformat(), guessed


def _promise_bar(row: dict[str, Any], today: str,
                 meetings: list[str] | None = None) -> dict[str, Any] | None:
    """一条承诺。**没有期限的不上轴** —— 见下面那段。"""
    due = row.get("due_date")
    derived = None if due else term_end(row.get("statement", ""),
                                        str(row.get("promised_on") or ""), meetings)
    guessed = bool(derived and derived[1])
    end = due or (derived[0] if derived else None)
    # **没有任何期限的承诺，在时间轴上没有位置。**
    #
    # 格力那 11 条里有 6 条是金额上限或比例约束：「回购资金总额不低于 50 亿」
    # 「不低于 70% 用于注销」「390 亿闲置资金理财」—— 它们在台账里有意义，
    # 但它们不是一段时间。第一版把它们画成说出口那天的一个点，结果是**九个一模一样
    # 的点挤在同一条竖线上**（同一份年报里抽出来的，公告日当然相同），
    # 一眼看不出任何东西。使用者原话：「这个图目前没有意义」。
    #
    # 它们不消失，只是回台账去 —— 泳道的说明里报数并说清是哪一类。
    if not end:
        return None
    settled = str(row.get("status") or "") not in ("待到期", "")
    return {
        "title": str(row.get("statement") or "")[:52],
        "start": row.get("promised_on"),
        "end": end,
        "point": False,
        # 按公告日凑出来的终点画法不一样，而且要说得出是凑的。
        # 找到了股东会决议日的那些**不算估算** —— 那个日期是能核对的。
        "estimated": guessed,
        "state": ("已了结" if settled else
                  "已到期" if end < today else "进行中"),
        "detail": (f"{row.get('subject') or '公司'} · {row.get('category') or '其他'}"
                   f" · {row.get('promised_on')} 说的 · "
                   + (f"到期 {end}" if due else
                      f"原话写的是相对期限，按公告日推到 {end}（估算）" if guessed else
                      f"原话是「自股东会审议通过之日起」，用那次股东会决议的日期算到 {end}")),
        "url": row.get("source_url") or None,
        "kind": "承诺",
    }


def _lockup_bar(row: dict[str, Any], today: str) -> dict[str, Any]:
    """一批解禁。区间是**公告日 → 解禁日**，也就是这批股份还锁着的那段时间。"""
    facts = _lockup(str(row.get("detail") or ""))
    unlock = str(row.get("event_date") or "")
    parts = []
    if facts["shares_wan"] is not None:
        parts.append(f"{facts['shares_wan']:.2f} 万股")
    if facts["value_yi"] is not None:
        parts.append(f"约 {facts['value_yi']:.2f} 亿元")
    return {
        "title": str(row.get("title") or "限售股上市流通"),
        # 公告日抠不到时退回解禁日：那会画成一个点，而不是一段编出来的锁定期。
        "start": facts["announced_on"] or unlock,
        "end": unlock,
        "point": facts["announced_on"] is None,
        "state": "已解禁" if unlock < today else "未解禁",
        "detail": " · ".join(parts) + (f" · 公告于 {facts['announced_on']}"
                                       if facts["announced_on"] else ""),
        "url": row.get("url") or None,
        "kind": "解禁",
        "weight": facts["value_yi"],       # 市值：图上用它决定条的深浅
    }


# 横轴往回看多远。**格力的解禁记录能追到 2007 年**，全画上去横轴就是二十年，
# 未来那两批挤在最右边一条缝里 —— 而这张图问的正是"还有多久"。
# 砍掉的部分要报数：悄悄少画几条，看起来就像这家公司历史上没解禁过几次。
WINDOW_BACK_DAYS = 730


def _in_window(bar: dict[str, Any], floor: str) -> bool:
    """整段都落在窗口左边的不画（终点比窗口起点还早）。"""
    return str(bar.get("end") or bar.get("start") or "") >= floor


def _fund_bar(row: dict[str, Any], today: str) -> dict[str, Any] | None:
    """一个募投项目。区间是**这份报告的期末 → 预定可使用状态日期**。

    没有预定日期的不上轴（跟没有期限的承诺同一条规矩）：一个进度 7.49% 的项目
    不知道什么时候该完成，在时间轴上没有位置 —— 它属于列表。
    """
    due = str(row.get("due_on") or "")
    if not due:
        return None
    # 「2028-10」这种只到月的补成月末那天，图上差几天无所谓，而缺了没法定位。
    end = due if len(due) >= 10 else f"{due}-28" if len(due) == 7 else ""
    if not end:
        return None
    start = str(row.get("created_at") or today)[:10]
    progress = row.get("progress")
    parts = [f"进度 {progress:.1f}%" if isinstance(progress, (int, float)) else ""]
    if isinstance(row.get("committed"), (int, float)):
        parts.append(f"承诺 {row['committed'] / 10000:.1f} 亿")
    if isinstance(row.get("invested"), (int, float)):
        parts.append(f"已投 {row['invested'] / 10000:.1f} 亿")
    pages = row.get("source_pages") or []
    return {
        "title": str(row.get("project") or "")[:52],
        "start": min(start, end), "end": end, "point": False,
        "estimated": False,
        "state": "已了结" if row.get("settled") else ("已到期" if end < today else "进行中"),
        "detail": " · ".join(filter(None, parts))
                  + (f" · {row.get('batch')}" if row.get("batch") else "")
                  + (f" · 出自专项报告第 {'、'.join(str(p) for p in pages)} 页" if pages else ""),
        "url": None, "kind": "募投",
    }


def build(promises: list[dict[str, Any]], lockups: list[dict[str, Any]],
          today: str | None = None, meetings: list[str] | None = None,
          fundraising: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """拼出甘特图。**空的泳道不画，但要说得出为什么空**。"""
    now = today or date.today().isoformat()
    floor = (date.fromisoformat(now) - timedelta(days=WINDOW_BACK_DAYS)).isoformat()
    lanes: list[dict[str, Any]] = []

    dated = [bar for bar in (_promise_bar(row, now, meetings) for row in promises
                             if row.get("promised_on")) if bar]
    # 没有任何期限的那些不上轴 —— 它们是金额上限、比例约束，不是一段时间。
    undated = len([row for row in promises if row.get("promised_on")]) - len(dated)
    promise_bars = [bar for bar in dated if _in_window(bar, floor)]
    dropped_promises = len(dated) - len(promise_bars)
    if promise_bars:
        guessed = sum(1 for bar in promise_bars if bar["estimated"])
        lanes.append({
            "key": "承诺", "label": "管理层承诺", "items": promise_bars,
            # **说清楚有几条没有期限。** 图上它们是点，而一排点看起来像"数据不全"；
            # 数据是全的，是公告里本来就没写死日子。
            "note": " ".join(filter(None, [
                (f"其中 **{guessed} 条**的期限在原话里是相对的，而没找到对应的股东会决议公告，"
                 f"只能按公告日推，画成虚边 —— **日子会偏几周**。" if guessed else ""),
                (f"另有 **{undated} 条没有期限**，没上这根轴：它们是金额上限或比例约束"
                 f"（「回购不低于 50 亿」「不低于 70% 用于注销」这类），在台账里，不是一段时间。"
                 if undated else ""),
                (f"还有 **{dropped_promises} 条**在两年以前就结束了，没画进来。"
                 if dropped_promises else ""),
            ])),
        })

    all_lockups = [_lockup_bar(row, now) for row in lockups if row.get("event_date")]
    lockup_bars = [bar for bar in all_lockups if _in_window(bar, floor)]
    dropped_lockups = len(all_lockups) - len(lockup_bars)
    if lockup_bars:
        future = sum(1 for bar in lockup_bars if bar["state"] == "未解禁")
        lanes.append({
            "key": "解禁", "label": "限售股解禁", "items": lockup_bars,
            "note": " ".join(filter(None, [
                (f"未来还有 {future} 批没解禁。" if future else
                 "**已知的批次全部解禁完了** —— 不代表以后不会有新的，"
                 "只代表现在库里没有未来的解禁公告。"),
                (f"另有 **{dropped_lockups} 批**是两年以前的，没画进来 ——"
                 f"全画上横轴会拉到十几二十年，未来那几批挤成一条缝。"
                 if dropped_lockups else ""),
            ])),
        })

    all_funds = [_fund_bar(row, now) for row in (fundraising or [])]
    fund_bars = [bar for bar in all_funds if bar]
    if fund_bars:
        undated_funds = len(all_funds) - len(fund_bars)
        lanes.append({
            "key": "募投", "label": "募投项目进度", "items": fund_bars,
            "note": " ".join(filter(None, [
                "每一项都来自「募集资金存放、管理与实际使用情况的专项报告」，"
                "**鼠标停上去能看到出自第几页**。",
                (f"另有 **{undated_funds} 项**没写明预定可使用状态日期，没上这根轴 ——"
                 f"不知道什么时候该完成的项目在时间轴上没有位置。" if undated_funds else ""),
            ])),
        })

    dates = [d for bar in promise_bars + lockup_bars + fund_bars
             for d in (bar["start"], bar["end"]) if d]
    return {
        "available": bool(lanes),
        "today": now,
        "start": min(dates) if dates else now,
        "end": max(dates + [now]) if dates else now,
        "lanes": lanes,
        # 画不出来的那些，逐条说明为什么。
        "missing": [{"key": key, "why": why} for key, why in NO_DATA],
        "note": ("还没有可以排进时间线的东西：承诺台账是空的，没有解禁记录，"
                 "也没有读过募集资金专项报告。先在「从公告里找承诺」抽一次、"
                 "同步一次公司日历，或者到「读文档」读一份募集资金专项报告。"
                 if not lanes else ""),
        "boundary": ("每一根都来自公告：承诺是台账里你自己核过的原话，"
                     "解禁来自限售股上市流通公告。**这一页只排日子，不判断影响。**"),
    }
