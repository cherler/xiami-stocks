"""A scoped response report assembled from existing research and public prices."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import access, assistant, assistant_agent as agent, repository as repo, response_model as model
from .database import connection, now_iso

REGIMES = {"up": "上升趋势", "hot": "上升但偏热", "down": "下降趋势", "range": "方向未明"}


def build(conn, company_id: int) -> dict | None:
    if access.current_scope() in {None, access.GUEST_SCOPE}:
        return None
    company = conn.execute("SELECT id, name, symbol FROM companies WHERE id=? AND user_id=?",
                           (company_id, agent._scope())).fetchone()
    if not company:
        return None
    company = dict(company)
    # One source revision per date; a second provider must not create duplicate days.
    bars = [dict(r) for r in conn.execute("""SELECT trade_date,close,open_price,high,low FROM (
        SELECT trade_date,close,open_price,high,low,
            ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY refreshed_at DESC,source DESC) AS revision
        FROM price_bars WHERE symbol=?) b WHERE revision=1 ORDER BY trade_date DESC LIMIT 600""",
        (company["symbol"],)).fetchall()]
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.hour < 15 or (now.hour == 15 and now.minute < 5):
        bars = [r for r in bars if r["trade_date"] != now.date().isoformat()]
    prices = model.analyze(bars, today=now.date())
    position = assistant._positions(conn).get(company_id)
    thesis = conn.execute("SELECT id, claim, status, counter_condition FROM theses WHERE company_id=? "
                          "AND is_sample=0 ORDER BY id DESC LIMIT 1", (company_id,)).fetchone()
    card_row = repo._card_row(conn, company_id)
    card = repo._decode_card(card_row) if card_row else {}
    real_theses = {r["id"] for r in conn.execute("SELECT id FROM theses WHERE company_id=? AND is_sample=0", (company_id,)).fetchall()}
    reviews = [r for r in repo._review_queue_rows(conn) if r["company_id"] == company_id and r["thesis_id"] in real_theses]
    reviews = [{"thesis_id": r["thesis_id"], "claim": r["claim"], "reasons": repo._review_reasons(r),
                "counter_hits": r.get("new_counter_hits", 0)} for r in reviews if repo._review_reasons(r)]
    failed = bool(thesis and thesis["status"] in {"broken", "challenged"}) or any(r["counter_hits"] for r in reviews)
    regime = prices.get("regime", "unknown")
    limit = model.positive((card.get("position_plan") or {}).get("total_percent"))
    weight = (position or {}).get("weight_percent")
    over_limit = limit is not None and weight is not None and weight > limit
    if failed:
        code, held, empty = "review", "先复核原判断，暂停加仓", "先查清反证，暂不参与"
    elif not prices["ready"]:
        code, held, empty = "data", "先更新行情，暂不调整", "先更新行情，暂不参与"
    elif over_limit:
        code, held, empty = "position_limit", "仓位已超计划，先处理超额部分", "先核对仓位记录，暂不参与"
    elif regime == "down":
        code, held, empty = "defend", "暂停加仓，核对减仓条件", "先等止跌，不急着抄底"
    elif regime == "hot":
        code, held, empty = "wait_hot", "暂不追加，检查仓位上限", "暂不追涨，等价格降温"
    elif regime == "up":
        code, held, empty = "hold", "按原计划持有，先不追加", "进入观察，先核对估值"
    else:
        code, held, empty = "wait", "先维持计划，不频繁交易", "继续观察，等待方向清楚"
    reasons = []
    if failed:
        reasons.append("已有判断受挑战、已被推翻，或认错条件被触发；先处理这件事。")
    if over_limit:
        reasons.append(f"账本仓位 {weight:g}%，超过你设的计划总仓位 {limit:g}%。")
    if prices["ready"]:
        reasons.append(f"近 20 日涨跌 {prices['return20']:+.1f}%，距近 60 日高点 {prices['drawdown60']:.1f}%。")
        reasons.append({"up": "收盘站上中期均线，上升方向尚在。", "hot": "收盘高于 20 日均线超过 12%，继续追价的余地变小。",
                        "down": "收盘低于中期均线，且均线向下。", "range": "价格与中期方向没有形成一致信号，来回操作缺少依据。"}[regime])
    else:
        reasons.append(prices["note"])
    if not thesis:
        reasons.append("还没有保存投资判断；走势向上也不能替代买入理由。")
    elif reviews and not failed:
        reasons.append("已有研究到了复核时间或出现新资料，先读变化。")
    # User-entered price bands are nominal prices. Do not compare with old adjusted closes.
    quote = assistant.freshest_price(conn, company["symbol"])
    plan_note = card.get("watch_reason") or ""
    bands = card.get("bands") or {}
    band_note = ""
    if bands:
        band_note = "已保存价格计划；执行前核对现价、估值日期和仓位，报告不会改写你的计划。"
    conditions = ["出现新的反证或认错条件触发：先复核，暂停新增。"]
    for key, label in (("stop_buy", "你的停止买入条件"), ("exit_rule", "你的减仓或退出条件")):
        value = (card.get("position_plan") or {}).get(key)
        if value:
            conditions.append(f"{label}：{value}")
    if prices["ready"]:
        conditions.append("收盘重新站稳中期均线、均线转升：再检查估值和参与条件。" if regime in {"down", "range"}
                          else "收盘跌破中期均线且均线转向下：重新检查减仓条件。")
        if regime == "hot":
            conditions.append("价格与 20 日均线的距离缩小后再看，不因继续上涨临时追价。")
    if thesis and thesis["counter_condition"]:
        conditions.insert(0, "你的认错条件：" + thesis["counter_condition"])
    summary = {"code": code,
               "holding": bool(position), "failed": failed, "review_due": bool(reviews), "over_limit": over_limit}
    return {"company": company, "generated_at": now_iso(), "horizon": "未来 20–60 个交易日",
            "action": held if position else empty, "held_action": held, "empty_action": empty,
            "position": position, "position_note": "已读取账本持仓" if position else "账本未记录当前持仓，同时列出两种应对",
            "regime_label": REGIMES.get(regime, "资料待补") if prices["ready"] else "行情待更新",
            "reasons": reasons, "conditions": conditions, "prices": prices, "quote": quote,
            "thesis": dict(thesis) if thesis else None, "plan_note": plan_note, "band_note": band_note,
            "reviews": reviews, "summary": summary, "version": model.VERSION}


def summaries(company_ids: list[int]) -> list[dict]:
    rows = []
    with connection() as conn:
        for company_id in dict.fromkeys(company_ids):
            report = build(conn, company_id)
            if report is not None:
                rows.append({"company_id": company_id, "action": report["action"],
                             "reason": report["reasons"][0], "as_of": report["prices"].get("as_of"),
                             "needs_attention": report["summary"]["code"] in {"review", "position_limit"}})
    return rows


def read(company_id: int, *, remember: bool = True) -> dict | None:
    with connection() as conn:
        report = build(conn, company_id)
        if report is None:
            return None
        key = f"response_report:{company_id}"
        previous = agent._memory(conn, key)
        if previous.get("version") != model.VERSION:
            previous = {}  # New rules get a new baseline, not a fabricated market change.
        if previous.get("summary") != report["summary"] or previous.get("version") != model.VERSION:
            current = {"summary": report["summary"], "action": report["action"], "at": report["generated_at"],
                       "version": model.VERSION, "previous_action": previous.get("action"),
                       "previous_at": previous.get("at")}
            if remember:
                agent._set_memory(conn, key, current)
        else:
            current = previous
        report["previous_action"] = current.get("previous_action")
        report["previous_at"] = current.get("previous_at")
        report["change_note"] = ("应对结论维持不变；研究复核状态发生了变化。"
                                 if current.get("previous_action") == report["action"] else "")
        row = conn.execute("SELECT enabled FROM assistant_subscriptions WHERE user_id=? AND company_id=? "
                           "AND kind='response' AND direction='below'", (agent._scope(), company_id)).fetchone()
        report["watching"] = bool(row and row["enabled"])
        report["watch_running"] = assistant.watch_enabled()
        import os
        report["watch_running"] = report["watch_running"] or os.getenv("STOCK_ASSISTANT_WEB_MODE") == "cloud"
        return report


def watch(company_id: int, enabled: bool) -> dict | None:
    if access.current_scope() in {None, access.GUEST_SCOPE}:
        return None
    with connection() as conn:
        agent._lock(conn)
        report = build(conn, company_id)
        if report is None:
            return None
        old = conn.execute("SELECT id,enabled FROM assistant_subscriptions WHERE user_id=? AND company_id=? AND kind='response'",
                           (agent._scope(), company_id)).fetchone()
        if old and bool(old["enabled"]) == enabled:
            return {"watching": enabled}
        if old:
            agent._cancel_watch_alerts(conn, old["id"])
        conn.execute("""INSERT INTO assistant_subscriptions
            (user_id,company_id,kind,direction,enabled,snapshot,created_at,updated_at)
            VALUES (?,?,'response','below',?,?,?,?)
            ON CONFLICT(user_id,company_id,kind,direction) DO UPDATE SET
            enabled=excluded.enabled,snapshot=excluded.snapshot,updated_at=excluded.updated_at""",
            (agent._scope(), company_id, int(enabled), agent._json(watch_snapshot(report)), now_iso(), now_iso()))
    return {"watching": enabled}


def watch_snapshot(report: dict) -> dict:
    return {"summary": report["summary"], "version": model.VERSION, "action": report["action"]}


def watch_changes(previous: dict, report: dict) -> list[str]:
    current = watch_snapshot(report)
    if not previous or previous.get("version") != model.VERSION or previous.get("summary") == current["summary"]:
        return []
    # No daily-price notifications, no first-run or deployment-change broadcast.
    headline = (f"应对更新：{previous.get('action', '原结论')} → {report['action']}。"
                if previous.get("action") != report["action"] else
                "研究复核状态有变化；当前应对结论不变。")
    reason = (report["reviews"][0]["reasons"][0] if report["reviews"] else report["reasons"][0])
    return [headline,
            f"行情截至 {report['prices'].get('as_of') or '待补'}。" + reason]
