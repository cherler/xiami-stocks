"""助理的大脑：替你盯、交易前替你拦。**判断全在这里，框架只负责把话递过去。**

2026-09-24 定的方向：虾米看股要从「你伺候它」翻成「它伺候你」——它一直在干活，
只在两种时刻找你：你写下的条件到了；它要改你的记录、需要你点头。

## 为什么判断不交给 nanobot（或任何 agent 框架）

框架是嘴，这里是脑子。「到没到价」「合不合计划」是算术，算术要能测、要每次都一样。
交给模型判，同一个价今天说到了、明天说没到，而且写不出判据。
框架只做两件事：把这里写好的话递给你，把你的话递回来。**换框架时这里一行不用改。**

## 三条规矩

1. **只拿你自己的规则说话。**「到了你写的计划价」「进了你的合理区」，
   不说「建议买」。这条守住 PRODUCT.md 4.2（不给买卖点、不给目标价）。
2. **安静必须是「看过了，没事」，不能是「根本没看」。** 每一轮盯盘都记一笔
   （assistant_watch_runs），送不出去也记（assistant_alerts.delivery = failed）。
   2026-09-24 的实测反例：认错条件比对作业每天报「成功」，其实一条都没比过。
3. **只盯「你的票」。** 观察池 / 候选池、有决策卡的、写过投资逻辑的、手上持有的——
   四个清单取并集。那天量出来这四个清单互相对不上：并集 14 只，其中 8 只只出现在
   一个清单里。其余两百多家是资料库，**永远不产生提醒**。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import difflib
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import bands as bd
from . import decision_loop as loop
from .database import connection, now_iso

MY_GROUPS = ("观察池", "候选池")
# 你亲手搁置或清仓的票，不再替你盯。它们仍然出现在「你的票」里，只是不响。
QUIET_STATES = ("shelved", "exited")
# 会响的档位。「观察区」不响：它的意思是「进了视野，但赔率一般，通常不动手」——
# 为一个通常不动手的区间打扰你，正是这个系统原来让人烦的那种事。
ALERT_LEVELS = ("plan", "fair", "ideal", "extreme")
# 出区的回差：价格要回到门槛之上 1% 才算出去、才重新上膛。
HYSTERESIS = 0.01
RECENT_DAYS = 14
UPCOMING_DAYS = 45
LEVEL_LABELS = {"plan": "计划买入价", **loop.BAND_LABELS}
DEVIATION_LABELS = {"price": "价格", "band": "价格带", "state": "闭环状态",
                    "valuation": "估值", "stale": "价格带过期"}


# ───────────────────────────────────────────────────────────── 小工具

def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN 当成没有


def _p(value: float | None) -> str:
    """价格：最多两位小数，去掉末尾的 0。"""
    if value is None:
        return "—"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _pct(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _short(title: str, limit: int = 22) -> str:
    """公告标题压成一小段。**留头也留尾**：同一个激励计划的三条公告，
    前半截一字不差（「2022年股票期权与限制性股票激励计划…」），区别全在后半截
    （「自主行权」「注销完成」「股份上市」）——只留开头，三条看上去是同一条。"""
    title = re.sub(r"^(关于|[^\s]{2,12}股份有限公司关于)", "", (title or "").strip())
    title = re.sub(r"(的)?(提示性)?公告$", "", title)
    if len(title) <= limit:
        return title
    return title[:8] + "…" + title[-(limit - 8):]


def _plain(text: str) -> str:
    """bands.compare 的话带着 markdown 粗体；推到微信里会原样露出星号。"""
    return text.replace("**", "")


def _decode(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _today() -> date:
    return date.today()


# ───────────────────────────────────────────────────────────── 你的票

def _positions(conn) -> dict[int, dict[str, Any]]:
    """账本推出的当前持仓。**复用 _accumulate_positions，不另算一份**——
    守卫那边另算过一份，结果不认「持仓对账」，填了持仓卡片却推不到「持仓中」。"""
    from .repository import _accumulate_positions, _sw, _trade_records

    trades = _trade_records(conn.execute(
        f"""SELECT t.id, t.company_id, t.side, t.trade_date, t.shares, t.price,
                   t.fee, t.weight_percent, t.cash_amount, t.review_due
            FROM trades t JOIN portfolios p ON p.id = t.portfolio_id
            WHERE 1=1{_sw('p')}""").fetchall())
    held = {}
    for company_id, state in _accumulate_positions(trades).items():
        shares = float(state.get("shares") or 0.0)
        weight = state.get("weight_percent")
        if shares > 1e-9 or (weight is not None and float(weight) > 0):
            held[int(company_id)] = {
                "shares": shares,
                "cost": (state["cost_value"] / shares) if shares > 1e-9 else None,
                "weight_percent": weight,
            }
    return held


def _my_sources(conn) -> tuple[dict[int, set[str]], dict[int, dict[str, Any]]]:
    """{company_id: 来自哪几个清单}，外加持仓明细。"""
    from .repository import _sw

    sources: dict[int, set[str]] = {}

    def add(ids, label):
        for company_id in ids:
            sources.setdefault(int(company_id), set()).add(label)

    placeholders = ", ".join("?" for _ in MY_GROUPS)
    add([row["id"] for row in conn.execute(
        f"SELECT id FROM companies WHERE watch_group IN ({placeholders}){_sw()}",
        MY_GROUPS).fetchall()], "分组")
    add([row["company_id"] for row in conn.execute(
        f"SELECT company_id FROM decision_cards WHERE 1=1{_sw()}").fetchall()], "决策卡")
    add([row["company_id"] for row in conn.execute(
        f"""SELECT DISTINCT t.company_id FROM theses t JOIN companies c ON c.id = t.company_id
            WHERE 1=1{_sw('c')}""").fetchall()], "投资逻辑")
    add([row["company_id"] for row in conn.execute(
        f"SELECT company_id FROM assistant_subscriptions WHERE enabled = 1{_sw()}").fetchall()], "主动跟踪")
    add([row["company_id"] for row in conn.execute(
        f"""SELECT DISTINCT r.company_id FROM research_reports r JOIN companies c ON c.id = r.company_id
            WHERE r.model = '飞书助理 · 个人记录'{_sw('c')}""").fetchall()], "随手记")
    held = _positions(conn)
    add(held, "持仓")
    return sources, held


def freshest_price(conn, symbol: str) -> dict[str, Any]:
    """最新的价：**盘中快照比最后一根日线新，就用快照。**

    决策卡上的价取的是日线收盘（`_latest_close`），那是为了「一天最多触发一次」。
    助理要的是另一件事：你写的价到了，**今天**就该知道，而不是等收盘后再说。
    两边用的是同一个 `loop.band_of`，只是喂进去的价不同。
    """
    bar = conn.execute(
        "SELECT trade_date, close FROM price_bars WHERE symbol = ? ORDER BY trade_date DESC LIMIT 1",
        (symbol,)).fetchone()
    # **refreshed_at 只精确到秒**（now_iso 去掉了微秒）：同一秒写进两条快照时，
    # 光按它排序拿到的是哪条听天由命。用自增 id 兜底，后写的就是新的。
    snap = conn.execute(
        "SELECT price, change_percent, market_timestamp, refreshed_at FROM market_snapshots "
        "WHERE symbol = ? ORDER BY refreshed_at DESC, id DESC LIMIT 1", (symbol,)).fetchone()
    bar_day = str(bar["trade_date"])[:10] if bar and bar["close"] is not None else ""
    snap_at = ""
    if snap and snap["price"] is not None:
        snap_at = str(snap["market_timestamp"] or snap["refreshed_at"] or "")
    if snap_at and snap_at[:10] > bar_day:
        return {"price": float(snap["price"]), "as_of": snap_at[:16].replace("T", " "),
                "source": "盘中", "change_percent": _num(snap["change_percent"])}
    if bar_day:
        return {"price": float(bar["close"]), "as_of": bar_day, "source": "收盘",
                "change_percent": _num(snap["change_percent"]) if snap and snap_at[:10] == bar_day else None}
    return {"price": None, "as_of": "", "source": "", "change_percent": None}


def my_stocks() -> list[dict[str, Any]]:
    """「你的票」一张表：在哪几个清单里、卡片停在哪、现价离你写的价多远。"""
    from .repository import _sw

    with connection() as conn:
        sources, held = _my_sources(conn)
        if not sources:
            return []
        ids = sorted(sources)
        marks = ", ".join("?" for _ in ids)
        companies = {row["id"]: dict(row) for row in conn.execute(
            f"SELECT id, symbol, name, watch_group FROM companies WHERE id IN ({marks}){_sw()}",
            ids).fetchall()}
        cards = {row["company_id"]: dict(row) for row in conn.execute(
            f"SELECT company_id, state, bands, order_plan FROM decision_cards "
            f"WHERE company_id IN ({marks}){_sw()}", ids).fetchall()}
        subscribed = {row['company_id'] for row in conn.execute(
            f"SELECT company_id FROM assistant_subscriptions WHERE enabled = 1{_sw()}").fetchall()}
        rows = []
        for company_id in ids:
            company = companies.get(company_id)
            if not company:
                continue
            card = cards.get(company_id) or {}
            bands = loop.normalise_bands(_decode(card.get("bands")))
            plan_price = _num(_decode(card.get("order_plan")).get("price"))
            quote = freshest_price(conn, company["symbol"])
            price = quote["price"]
            state = card.get("state")
            rows.append({
                "company_id": company_id,
                "symbol": company["symbol"],
                "name": company["name"],
                "group": company["watch_group"],
                "in_lists": sorted(sources[company_id]),
                "state": state,
                "state_label": loop.STATES[state]["label"] if state in loop.STATES else "没有决策卡",
                "watched": company_id in subscribed or (bool(card) and state not in QUIET_STATES and (bool(bands) or plan_price is not None)),
                "price": price,
                "price_as_of": quote["as_of"],
                "change_percent": quote["change_percent"],
                "band": loop.band_of(price, bands),
                "band_label": loop.BAND_LABELS.get(loop.band_of(price, bands) or ""),
                "plan_price": plan_price,
                "to_plan_percent": (round((price / plan_price - 1) * 100, 1)
                                    if price and plan_price else None),
                "holding": held.get(company_id),
            })
    return rows


def resolve(query: str) -> list[dict[str, Any]]:
    """「宁德」→ 宁德时代。**先在你的票里找，找不到再去全部档案里找。**

    同名前缀在全部档案里很常见（294 家里搜「中国」能出一串），
    而你说「平安」时十有八九说的是你拿着的那只。
    """
    from .repository import _sw

    text = unicodedata.normalize("NFKC", query or "").strip()
    if not text:
        return []
    with connection() as conn:
        sources, _ = _my_sources(conn)
        all_rows = [dict(row) for row in conn.execute(
            f"SELECT id, symbol, name FROM companies WHERE 1=1{_sw()} ORDER BY id").fetchall()]
    symbol = re.sub(r"^(SH|SZ|BJ)|\.(SH|SZ|BJ)$", "", text.upper())
    aliases = {"宁德": "宁德时代", "茅台": "贵州茅台", "富联": "工业富联", "海光": "海光信息",
               "格力": "格力电器"}
    expanded = aliases.get(text, text)
    rows = [row for row in all_rows if expanded in row['name'] or row['symbol'] == symbol]
    match = "alias" if expanded != text else "exact"
    if not rows and len(text) >= 3 and not any(ch.isdigit() for ch in text):
        # Suggestions only: never fuzzy-correct a security code or price.
        ranked_names = [(difflib.SequenceMatcher(None, text, row['name']).ratio(), row) for row in all_rows]
        best = max((score for score, _ in ranked_names), default=0)
        rows = [row for score, row in ranked_names if score >= max(0.70, best - 0.08)]
        match = "fuzzy"
    exact = [row for row in rows if row["name"] == expanded or row["symbol"] == symbol]
    pool = exact or rows
    mine = [row for row in pool if row["id"] in sources]
    ranked = mine or pool
    return [{"company_id": row["id"], "symbol": row["symbol"], "name": row["name"],
             "mine": row["id"] in sources, "match": match,
             "input": text} for row in ranked[:8]]


# ───────────────────────────────────────────────────────────── 近况

def _change_over(conn, symbol: str, price: float | None, days: int = 30) -> tuple[float | None, str | None]:
    if not price:
        return None, None
    since = (_today() - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT trade_date, close FROM price_bars WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT 1", (symbol, since)).fetchone()
    if not row or not row["close"]:
        return None, None
    return round((price / float(row["close"]) - 1) * 100, 1), str(row["trade_date"])[:10]


def _recent_announcements(conn, company_id: int, limit: int = 3) -> list[dict[str, Any]]:
    """最近两周的公告。**低相关的（程序性文件）不列**，没分过级的照列——
    宁德那条「绿色债券发行完成」就没分过级，它不重要，但你该知道最近发生了什么。"""
    since = (_today() - timedelta(days=RECENT_DAYS)).isoformat()
    rows = conn.execute(
        """SELECT event_date, title, relevance FROM company_calendar_events
           WHERE company_id = ? AND category = '公告' AND event_date >= ? AND event_date <= ?
             AND (relevance IS NULL OR relevance <> '低')
           ORDER BY CASE relevance WHEN '高' THEN 0 WHEN '中' THEN 1 ELSE 2 END, event_date DESC
           LIMIT ?""",
        (company_id, since, _today().isoformat(), limit)).fetchall()
    return [{"date": str(row["event_date"])[:10], "title": row["title"], "relevance": row["relevance"]}
            for row in rows]


def _upcoming(conn, company_id: int) -> list[dict[str, Any]]:
    """接下来 45 天里等着的日子：解禁、分红。"""
    today = _today()
    rows = conn.execute(
        """SELECT category, event_date, title, detail FROM company_calendar_events
           WHERE company_id = ? AND category IN ('解禁', '分红') AND event_date > ? AND event_date <= ?
           ORDER BY event_date""",
        (company_id, today.isoformat(), (today + timedelta(days=UPCOMING_DAYS)).isoformat())).fetchall()
    out = []
    for row in rows:
        day = str(row["event_date"])[:10]
        out.append({"category": row["category"], "date": day, "title": row["title"],
                    "detail": row["detail"] or "",
                    "days": (date.fromisoformat(day) - today).days})
    return out


def _event_line(event: dict[str, Any]) -> str:
    detail = event["detail"].split(" · 公告于")[0] if event["category"] == "解禁" else event["title"]
    return f"{event['date'][5:]} {event['category']}：{detail}（还有 {event['days']} 天）"


# ───────────────────────────────────────────────────────────── 交易前核验

def pre_trade_check(company_id: int, price: float | None = None) -> dict[str, Any] | None:
    """你说「我想买 X」时，一屏回答：合不合你自己写的计划。

    **每一条都是把你已经写下的东西和今天的事实摆在一起**，没有一条是预测。
    停止买入那几条是自由文本，机器判不了，所以只列出来请你自己对——
    不判比瞎判好（跟纪律指标不判卖出是同一个理由）。
    """
    from .repository import _sw, base_per_share, company_valuation

    with connection() as conn:
        company = conn.execute(
            f"SELECT id, symbol, name FROM companies WHERE id = ?{_sw()}", (company_id,)).fetchone()
        if not company:
            return None
        company = dict(company)
        card_row = conn.execute(
            f"SELECT * FROM decision_cards WHERE company_id = ?{_sw()}", (company_id,)).fetchone()
        quote = freshest_price(conn, company["symbol"])
        if price is None:
            price = quote["price"]
            as_of, source = quote["as_of"], quote["source"]
        else:
            as_of, source = "", "你给的价"
        change30, change30_from = _change_over(conn, company["symbol"], price)
        announcements = _recent_announcements(conn, company_id)
        upcoming = _upcoming(conn, company_id)
        holding = _positions(conn).get(company_id)

    head = f"{company['name']}（{company['symbol']}）"
    if card_row is None:
        text = (f"【交易前核验】{head}\n你还没给它写过计划（没有决策卡），"
                "所以没有可以对照的价格带和计划价。\n"
                "想按计划做，先说一句你为什么关注它、打算什么价买、最多买几成。")
        return {"company_id": company_id, "name": company["name"], "symbol": company["symbol"],
                "has_plan": False, "price": price, "price_as_of": as_of, "items": [],
                "deviations": [], "verdict": "没有计划可对", "text": text}

    card = dict(card_row)
    state = card["state"]
    bands = loop.normalise_bands(_decode(card["bands"]))
    order = _decode(card["order_plan"])
    plan = _decode(card["position_plan"])
    stamps = _decode(card.get("block_stamps"))
    plan_price = _num(order.get("price"))
    band = loop.band_of(price, bands)
    # 估值要自己开库，放在 connection() 外面。
    valuation = company_valuation(company_id)
    per_share = base_per_share(valuation)

    items: list[dict[str, str]] = []
    deviations: list[str] = []

    def item(mark: str, key: str, text: str) -> None:
        items.append({"mark": mark, "key": key, "text": text})
        # **按类别数，不按句子数**：计划价和合理区上沿都比基准值高 15%，
        # 是同一件事说了两遍——数成「2 处对不上」会把事情说得比实际严重。
        if mark == "⚠" and DEVIATION_LABELS.get(key, key) not in deviations:
            deviations.append(DEVIATION_LABELS.get(key, key))

    # 1. 价格对计划价
    if price is None:
        item("⚠", "price", "取不到现价，没法跟你的计划价比。")
    elif plan_price is None:
        item("·", "price", f"现价 {_p(price)}。你没写这一笔打算买什么价。")
    elif price <= plan_price:
        item("✓", "price", f"现价 {_p(price)} ≤ 你写的计划价 {_p(plan_price)}")
    else:
        item("⚠", "price",
             f"现价 {_p(price)} 比你写的计划价 {_p(plan_price)} 高 {_pct((price / plan_price - 1) * 100)}%")

    # 2. 价格带
    if not bands:
        item("⚠", "band", "这只没写价格带，没法说现在算便宜还是贵。")
    elif band in ("fair", "ideal", "extreme"):
        item("✓", "band", f"在你的「{loop.BAND_LABELS[band]}」（≤{_p(bands[band])}）")
    elif band == "watch":
        item("⚠", "band", f"只在「观察区」（≤{_p(bands['watch'])}），还没进你的合理区"
                          + (f"（≤{_p(bands['fair'])}）" if bands.get("fair") else ""))
    elif price is not None:
        item("⚠", "band", f"还没进你的任何一段价格带（最高那段是观察区 ≤{_p(bands.get('watch'))}）")

    # 3. 闭环停在哪
    state_label = loop.STATES[state]["label"] if state in loop.STATES else state
    if state in ("discovered", "researching"):
        item("⚠", "state", f"卡片还在「{state_label}」——按你自己定的规矩，没估值就没有买点。")
    elif state in QUIET_STATES:
        why = card.get("entered_reason") or ""
        item("⚠", "state", f"你把它放进了「{state_label}」" + (f"：{why}" if why else ""))
    elif state == "holding" and not holding:
        # 2026-09-24 实测：清掉持仓准备重填之后，格力和平安的卡还停在「持仓中」。
        # 不点破的话，这一屏会同时说「这一笔是加仓」和「现在没有持仓」。
        item("⚠", "state", "卡片停在「持仓中」，可账本里没有持仓——持仓清掉之后卡片没跟上。")
    elif state == "holding":
        item("·", "state", "已经持有，这一笔是加仓。")
    else:
        item("✓", "state", f"卡片在「{state_label}」")

    # 4. 仓位
    total, first = _num(plan.get("total_percent")), _num(plan.get("first_percent"))
    fraction = str(order.get("fraction") or "").strip()
    position_bits = []
    if holding:
        if holding.get("shares"):
            position_bits.append(f"现在持有 {_p(holding['shares'])} 股"
                                 + (f"（成本 {_p(holding['cost'])}）" if holding.get("cost") else ""))
        elif holding.get("weight_percent") is not None:
            position_bits.append(f"现在占 {_p(float(holding['weight_percent']))}%")
    else:
        position_bits.append("现在没有持仓")
    if fraction:
        position_bits.append(f"这一笔买计划的 {fraction}")
    if first is not None:
        position_bits.append(f"首笔 {_p(first)}%")
    if total is not None:
        position_bits.append(f"总仓位上限 {_p(total)}%")
    item("·", "position", "，".join(position_bits) if position_bits else "没写仓位计划。")

    # 5. 估值对不对得上。**门槛只在 bands.gaps 里定**（页面上那几句也从它取数）。
    #    聊天里合成一行：计划价高 15%、合理区上沿高 15% 是同一件事，拆成三行就是一堵墙，
    #    模型看见一堵墙就想替你「概括」——一概括就会漏条目。
    found = bd.gaps(per_share, bands, plan_price, price)
    if found is None:
        item("·", "valuation", "还没存过估值，没有基准每股价值可以对照。")
    else:
        def said(value: float) -> str:
            return f"高 {_pct(value)}%" if value >= 0 else f"低 {_pct(-value)}%"

        parts = []
        if "plan" in found:
            parts.append(f"计划价 {_p(plan_price)} {said(found['plan'])}")
        if "fair" in found:
            parts.append(f"合理区上沿 {_p(bands['fair'])} {said(found['fair'])}")
        if "price" in found:
            parts.append(f"现价{said(found['price'])}")
        flagged = found.get("plan", 0) > 0 or found.get("fair", 0) > 0
        item("⚠" if flagged else "·", "valuation",
             f"对你算的基准每股价值 {_p(per_share)}：" + "，".join(parts))

    # 6. 这组价格带多旧了（记录要带时间：过去正确的数，放在现在就是错的）
    bands_stamp = stamps.get("bands") or {}
    stale = bd.staleness(bands_stamp.get("base_report_date"), (valuation or {}).get("base_report_date"))
    if stale:
        item("⚠", "stale", _plain(stale))
    elif bands and not bands_stamp.get("set_at"):
        item("·", "stale", "价格带没记是哪天定的（那时还没开始记时间）")

    # 7. 近况
    if change30 is not None:
        item("·", "trend", f"近 30 天 {'+' if change30 >= 0 else ''}{_pct(change30)}%（{change30_from} 以来）")
    if announcements:
        # 合成一行。标题取前 22 个字：公告标题前半句就是事由，后半句多是「的公告」「提示性公告」。
        item("·", "news", "近两周公告：" + "；".join(
            f"{event['date'][5:]} {_short(event['title'])}" for event in announcements))
    for event in upcoming:
        item("📅", "upcoming", _event_line(event))

    # 8. 停止买入：自由文本，机器判不了，列出来请你自己对
    stop_buy = [part.strip() for part in re.split(r"[/／;；\n]", str(plan.get("stop_buy") or "")) if part.strip()]
    if stop_buy:
        item("?", "stop_buy", f"你写的 {len(stop_buy)} 条「停止买入」要你自己对一下："
                              + "、".join(stop_buy))

    why_now = str(order.get("why_now") or card.get("watch_reason") or "").strip()
    if why_now:
        item("💬", "why", f"你当时写的理由：「{why_now}」")

    verdict = ("和你写下的计划对得上" if not deviations
               else f"有 {len(deviations)} 处和你写下的计划对不上（{'、'.join(deviations)}）")
    stamp = f"（{as_of} {source}）" if as_of else (f"（{source}）" if source else "")
    lines = [f"【交易前核验】{head} {_p(price)}{stamp}", f"结论：{verdict}"]
    lines += [f"{entry['mark']} {entry['text']}" for entry in items]
    lines.append("决定和下单都在你。真下了单，告诉我成交价，我帮你记一笔。")
    return {
        "company_id": company_id, "name": company["name"], "symbol": company["symbol"],
        "has_plan": True, "state": state, "state_label": state_label,
        "price": price, "price_as_of": as_of, "price_source": source,
        "plan_price": plan_price, "band": band, "per_share_base": per_share,
        "items": items, "deviations": deviations, "verdict": verdict,
        "text": "\n".join(lines),
    }


# ───────────────────────────────────────────────────────────── 盯盘

def _thresholds(bands: dict[str, float], order: dict[str, Any]) -> dict[str, float]:
    """会响的那几档的门槛价。**哪几档会响只认 ALERT_LEVELS 这一处**——
    第一版这里另写了一份 ("fair", "ideal", "extreme")，常量成了摆设：
    改常量什么都不变，判据还全绿（变异测试抓到的）。"""
    out = {}
    for level in ALERT_LEVELS:
        value = _num(order.get("price")) if level == "plan" else _num(bands.get(level))
        if value is not None and value > 0:
            out[level] = value
    return out


def compose_price_alert(company: dict[str, Any], price: float, quote: dict[str, Any],
                        entered: list[str], thresholds: dict[str, float],
                        order: dict[str, Any], per_share: float | None,
                        upcoming: list[dict[str, Any]]) -> str:
    """一条到价提醒。**全是你自己写过的数和今天的事实**，没有一句建议。"""
    stamp = f"（{quote['as_of']} {quote['source']}）" if quote.get("as_of") else ""
    lines = [f"【虾米看股·到价】{company['name']} {_p(price)}{stamp}"]
    if "plan" in entered:
        fraction = str(order.get("fraction") or "").strip()
        lines.append(f"· 到了你写的计划买入价 {_p(thresholds['plan'])}"
                     + (f"（这一笔买计划的 {fraction}）" if fraction else ""))
    deepest = [level for level in ("extreme", "ideal", "fair") if level in entered]
    if deepest:
        level = deepest[0]
        lines.append(f"· 进了你的「{loop.BAND_LABELS[level]}」（≤{_p(thresholds[level])}）")
    if per_share and per_share > 0:
        gap = (price / per_share - 1) * 100
        if gap > 5:
            lines.append(f"⚠ 这个价比你自己算的基准每股价值 {_p(per_share)} 高 {_pct(gap)}%")
        elif gap < -5:
            lines.append(f"· 比你算的基准每股价值 {_p(per_share)} 低 {_pct(-gap)}%")
    for event in upcoming[:2]:
        lines.append(f"📅 {_event_line(event)}")
    lines.append(f"想动手之前回我「核验 {company['name']}」，我按你的计划逐条对一遍。")
    return "\n".join(lines)


def scan_price_alerts() -> list[dict[str, Any]]:
    """扫一遍你的票：哪一档价位**刚刚**进去了。进去那一刻记一条提醒。

    同一档只在「进去」的那一刻响一次；价格要回到门槛之上 HYSTERESIS 才算出去、
    才重新上膛。你改了计划价或价格带，门槛变了，就当成新的一档。
    """
    from .repository import _stamp, _sw, base_per_share, company_valuation

    pending: list[dict[str, Any]] = []
    with connection() as conn:
        sources, _ = _my_sources(conn)
        if not sources:
            return []
        ids = sorted(sources)
        marks = ", ".join("?" for _ in ids)
        cards = [dict(row) for row in conn.execute(
            f"""SELECT d.company_id, d.state, d.bands, d.order_plan, c.symbol, c.name
                FROM decision_cards d JOIN companies c ON c.id = d.company_id
                WHERE d.company_id IN ({marks}){_sw('d')}""", ids).fetchall()]
        now = now_iso()
        for card in cards:
            if card["state"] in QUIET_STATES:
                continue
            bands = loop.normalise_bands(_decode(card["bands"]))
            order = _decode(card["order_plan"])
            thresholds = _thresholds(bands, order)
            if not thresholds:
                continue
            quote = freshest_price(conn, card["symbol"])
            price = quote["price"]
            # 断网或节假日时，昨天的收盘不能当成今天刚触发。
            if price is None or str(quote.get("as_of") or "")[:10] != _today().isoformat():
                continue
            states = {row["level"]: dict(row) for row in conn.execute(
                f"SELECT level, threshold, inside FROM assistant_watch_state WHERE company_id = ?{_sw()}",
                (card["company_id"],)).fetchall()}
            entered = []
            for level, threshold in thresholds.items():
                before = states.get(level)
                was_inside = bool(before and before["inside"]
                                  and abs(float(before["threshold"]) - threshold) < 1e-9)
                if price <= threshold:
                    inside = True
                    if not was_inside:
                        entered.append(level)
                elif was_inside and price <= threshold * (1 + HYSTERESIS):
                    inside = True  # 还在回差里，不算出去
                else:
                    inside = False
                if before is None:
                    conn.execute(
                        """INSERT INTO assistant_watch_state
                           (user_id, company_id, level, threshold, inside, changed_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (_stamp(), card["company_id"], level, threshold, int(inside), now))
                elif bool(before["inside"]) != inside or abs(float(before["threshold"]) - threshold) >= 1e-9:
                    conn.execute(
                        f"""UPDATE assistant_watch_state SET threshold = ?, inside = ?, changed_at = ?
                            WHERE company_id = ? AND level = ?{_sw()}""",
                        (threshold, int(inside), now, card["company_id"], level))
            if entered:
                pending.append({"card": card, "price": price, "quote": quote, "entered": entered,
                                "thresholds": thresholds, "order": order,
                                "upcoming": _upcoming(conn, card["company_id"])})

    alerts = []
    for entry in pending:
        card = entry["card"]
        # 估值自己开库，放在 connection() 外面。
        per_share = base_per_share(company_valuation(card["company_id"]))
        message = compose_price_alert(card, entry["price"], entry["quote"], entry["entered"],
                                      entry["thresholds"], entry["order"], per_share, entry["upcoming"])
        with connection() as conn:
            cursor = conn.execute(
                """INSERT INTO assistant_alerts
                   (user_id, company_id, kind, levels, price, price_at, message, created_at)
                   VALUES (?, ?, 'price', ?, ?, ?, ?, ?)""",
                (_stamp(), card["company_id"], json.dumps(entry["entered"]), entry["price"],
                 entry["quote"].get("as_of") or "", message, now_iso()))
            alert_id = int(cursor.lastrowid)
        alerts.append({"id": alert_id, "company_id": card["company_id"], "name": card["name"],
                       "levels": entry["entered"], "price": entry["price"], "message": message})
    return alerts


# ───────────────────────────────────────────────────────────── 送出去

def _setting(key: str) -> str:
    """环境变量优先，其次仓根的 .env（跟 llm.load_env 同一个文件）。"""
    from .llm import _ENV_FILE

    value = os.environ.get(key, "")
    if value:
        return value.strip()
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


def _nanobot_binary() -> str | None:
    configured = _setting("STOCK_ASSISTANT_NANOBOT")
    if configured:
        return configured
    found = shutil.which("nanobot")
    if found:
        return found
    # uvicorn 从 launchd / 别的 shell 起的时候 PATH 里常常没有 ~/.local/bin。
    fallback = Path.home() / ".local" / "bin" / "nanobot"
    return str(fallback) if fallback.exists() else None


def deliver(message: str) -> tuple[str, str]:
    """把一句话交给 nanobot，由它送到飞书。返回 (状态, 出错原因)。

    queued 只表示进入 nanobot 队列，不代表飞书送达；skipped 未发送，failed 入队失败。
    **skipped 也要落库**：没配 trigger 的时候提醒只躺在库里，页面和心跳要说得出来。
    """
    trigger = _setting("STOCK_ASSISTANT_TRIGGER")
    if not trigger:
        return "skipped", "没配 STOCK_ASSISTANT_TRIGGER：提醒记在库里，没往外发"
    binary = _nanobot_binary()
    if not binary:
        return "failed", "找不到 nanobot 命令（可以用 STOCK_ASSISTANT_NANOBOT 指定路径）"
    # trigger 也会加载 nanobot 配置并展开密钥占位；API 进程不一定从网关脚本启动。
    env = os.environ.copy()
    for key in ("MINIMAX_API_KEY", "TAVILY_API_KEY"):
        value = _setting(key)
        if value:
            env[key] = value
    try:
        result = subprocess.run([binary, "trigger", trigger], input=message, text=True,
                                capture_output=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "failed", f"调用 nanobot 失败：{exc}"[:300]
    if result.returncode != 0:
        return "failed", (result.stderr or result.stdout or f"退出码 {result.returncode}").strip()[:300]
    return "queued", ""


def _record_delivery(alert_id: int, status: str, error: str) -> None:
    from .repository import _sw

    with connection() as conn:
        conn.execute(
            f"""UPDATE assistant_alerts SET delivery = ?, delivery_error = ?, delivered_at = ?
                WHERE id = ?{_sw()}""",
            (status, error, now_iso() if status == "sent" else None, alert_id))


def watch_once(*, fetch: bool = True, send: bool = True) -> dict[str, Any]:
    """盯一轮：刷你的票的行情 → 看哪一档刚进去 → 送出去。每一轮都留记录。"""
    from .repository import _fetch_market_quotes, _stamp, _sw, store_market_quotes

    started = now_iso()
    with connection() as conn:
        run_id = int(conn.execute(
            "INSERT INTO assistant_watch_runs (user_id, started_at) VALUES (?, ?)",
            (_stamp(), started)).lastrowid)
        sources, _ = _my_sources(conn)
        ids = sorted(sources)
        symbols = []
        if ids:
            marks = ", ".join("?" for _ in ids)
            symbols = [row["symbol"] for row in conn.execute(
                f"SELECT symbol FROM companies WHERE id IN ({marks}){_sw()}", ids).fetchall()]

    notes: list[str] = []
    status = "ok"
    priced = 0
    if fetch and symbols:
        try:
            priced = store_market_quotes(_fetch_market_quotes(symbols))
        except Exception as exc:  # 行情源抖一下不该让这一轮什么都不做：用库里最后的价接着看
            status = "partial"
            notes.append(f"行情没刷到（{str(exc)[:120]}），用的是库里最后的价")
    try:
        from .assistant_agent import scan_subscriptions
        alerts = scan_price_alerts() + scan_subscriptions()
    except Exception as exc:
        alerts = []
        status = "failed"
        notes.append(f"扫描出错：{exc}")

    # 飞书那头是**站主一个人**的对话。别的数据域的提醒只记不发——
    # 不然别人的计划价会出现在站主的聊天记录里。
    from . import access

    owner_scope = _setting("STOCK_ASSISTANT_SCOPE") or access.OWNER_SCOPE
    sendable = send and (access.current_scope() or access.OWNER_SCOPE) == owner_scope
    if sendable:
        with connection() as conn:
            retries = [dict(row) for row in conn.execute(
                f"SELECT id, company_id, message FROM assistant_alerts WHERE delivery IN ('failed', 'pending'){_sw()} "
                "AND created_at >= ? ORDER BY id LIMIT 20", ((date.today() - timedelta(days=1)).isoformat(),)).fetchall()]
        seen_ids = {alert['id'] for alert in alerts}
        alerts.extend(row for row in retries if row['id'] not in seen_ids)
    sent = queued = failed = skipped = 0
    for alert in alerts:
        if sendable:
            from . import assistant_delivery
            outcome, error = assistant_delivery.transfer(alert)
        else:
            outcome, error = "skipped", ("这一轮只看不发" if not send else "不是助理主人的数据域，只记不发")
        _record_delivery(alert["id"], outcome, error)
        alert["delivery"], alert["delivery_error"] = outcome, error
        sent += outcome == "sent"
        queued += outcome == "queued"
        failed += outcome == "failed"
        skipped += outcome == "skipped"
    if failed:
        status = "partial" if status == "ok" else status
        notes.append(f"{failed} 条没送出去")
    detail = (f"盯了 {len(ids)} 只，刷到 {priced} 个价，新提醒 {len(alerts)} 条"
              + (f"（已入队 {queued}、送出 {sent}、没发 {skipped}、失败 {failed}）" if alerts else "")
              + ("；" + "；".join(notes) if notes else ""))
    with connection() as conn:
        conn.execute(
            f"""UPDATE assistant_watch_runs SET finished_at = ?, watched = ?, priced = ?, alerts = ?,
                   status = ?, detail = ? WHERE id = ?{_sw()}""",
            (now_iso(), len(ids), priced, len(alerts), status, detail, run_id))
    return {"run_id": run_id, "watched": len(ids), "priced": priced, "alerts": alerts,
            "status": status, "detail": detail}


def status(limit: int = 10) -> dict[str, Any]:
    """助理最近在干什么：最近几轮盯盘、最近几条提醒送没送到。"""
    from .repository import _sw

    with connection() as conn:
        runs = [dict(row) for row in conn.execute(
            f"SELECT * FROM assistant_watch_runs WHERE 1=1{_sw()} ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
        alerts = [dict(row) for row in conn.execute(
            f"""SELECT a.id, a.company_id, c.name, a.kind, a.levels, a.price, a.price_at, a.message,
                       a.created_at, a.delivery, a.delivery_error, a.delivered_at
                FROM assistant_alerts a LEFT JOIN companies c ON c.id = a.company_id
                WHERE 1=1{_sw('a')} ORDER BY a.id DESC LIMIT ?""", (limit,)).fetchall()]
    for alert in alerts:
        alert["levels"] = json.loads(alert.get("levels") or "[]")
    return {"configured": bool(_setting("STOCK_ASSISTANT_TRIGGER")),
            "watch_enabled": watch_enabled(), "trading_time": is_trading_time(),
            "runs": runs, "alerts": alerts}


# ───────────────────────────────────────────────────────────── 什么时候盯

def is_trading_time(moment: datetime | None = None) -> bool:
    """A 股交易时段（本机时区按北京时间算）。周末不盯；节假日靠行情时点兜底——
    节假日刷到的价还是上一个交易日的，进没进区间跟昨天一样，不会重复响。"""
    moment = moment or datetime.now()
    if moment.weekday() >= 5:
        return False
    minutes = moment.hour * 60 + moment.minute
    return (9 * 60 + 25 <= minutes <= 11 * 60 + 35) or (12 * 60 + 55 <= minutes <= 15 * 60 + 5)


WATCH_INTERVAL_SECONDS = 180


def watch_enabled() -> bool:
    return _setting("STOCK_ASSISTANT_WATCH").lower() in {"1", "true", "yes", "on"}


async def watch_loop(stop_event) -> None:
    """跟调度器分开跑：调度器同一时间只跑一个作业，一个四分钟的「公司简况」
    就能把到价提醒拖过五分钟。这里只刷你那十几只的价，半秒的事。"""
    import asyncio
    import logging

    from . import access

    logger = logging.getLogger(__name__)

    def one_round() -> None:
        token = access.set_scope(_setting("STOCK_ASSISTANT_SCOPE") or access.OWNER_SCOPE)
        try:
            from .assistant_delivery import reconcile
            reconcile()
            result = watch_once(fetch=is_trading_time())
            if result["alerts"] or result["status"] != "ok":
                logger.info("助理盯盘：%s", result["detail"])
        finally:
            access.reset_scope(token)

    while not stop_event.is_set():
        # Research updates and delivery receipts also matter after market hours.
        try:
            await asyncio.to_thread(one_round)
        except Exception:
            logger.exception("助理盯盘这一轮出错")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=WATCH_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
