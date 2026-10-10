"""Stock assistant v1: durable, scoped actions behind an authenticated bot adapter.

Natural-language interpretation belongs to nanobot. This module owns identifiers,
records, confirmations and arithmetic. Original user text and message identity come
from the adapter's RequestContext, never from model-supplied tool arguments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import access, assistant, repository as repo
from .database import connection, now_iso


class AgentError(ValueError):
    pass


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["context", "remember", "correct", "undo", "watch", "pause_watch",
                       "resume_watch", "compare", "prepare_fill", "confirm", "cancel", "preferences"]
    stock: str = Field(default="", max_length=80)
    text: str = Field(default="", max_length=100000)
    title: str = Field(default="", max_length=160)
    record_id: str = Field(default="", max_length=64)
    kind: Literal["note", "report", "price", "research"] = "note"
    threshold: float | None = Field(default=None, gt=0, lt=1000000, allow_inf_nan=False)
    direction: Literal["below", "above"] = "below"
    price: float | None = Field(default=None, gt=0, lt=1000000, allow_inf_nan=False)
    shares: float | None = Field(default=None, gt=0, lt=10000000000, allow_inf_nan=False)
    filled_on: str = Field(default="", max_length=10)


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Command
    channel: str = Field(min_length=1, max_length=40)
    chat_id: str = Field(min_length=1, max_length=200)
    sender_id: str = Field(min_length=1, max_length=200)
    session_key: str = Field(min_length=1, max_length=250)
    message_id: str = Field(min_length=1, max_length=250)
    original_text: str = Field(min_length=1, max_length=120000)
    sent_at: int


def bridge_config() -> dict:
    path = Path(os.getenv("STOCK_ASSISTANT_BRIDGE_CONFIG", str(Path.home() / ".nanobot/stock-assistant-bridge.json")))
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def verify_request(raw: bytes, signature: str) -> Envelope:
    config = bridge_config()
    secret = config.get("secret", "")
    if not secret or not hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), signature):
        raise AgentError("助理连接未验证，请重新配置本机连接。")
    envelope = Envelope.model_validate_json(raw)
    if abs(time.time() - envelope.sent_at) > 90:
        raise AgentError("请求已过期，请重试。")
    if (envelope.channel != config.get("channel") or envelope.chat_id != config.get("chat_id")
            or envelope.sender_id not in config.get("sender_ids", [])):
        raise AgentError("这段对话没有绑定到看股助手。")
    if access.current_scope() != access.OWNER_SCOPE:
        raise AgentError("当前连接只供已绑定的私人助理使用。")
    return envelope


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(raw):
    return json.loads(raw or "{}")


def _scope() -> str:
    scope = access.current_scope()
    if not scope or scope == access.GUEST_SCOPE:
        raise AgentError("请在自己的账户内操作。")
    return scope


def _memory(conn, key: str) -> dict:
    row = conn.execute("SELECT value FROM assistant_memory WHERE user_id = ? AND memory_key = ?",
                       (_scope(), key)).fetchone()
    return _load(row["value"]) if row else {}


def _set_memory(conn, key: str, value: dict) -> None:
    conn.execute("""INSERT INTO assistant_memory (user_id, memory_key, value, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, memory_key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (_scope(), key, _json(value), now_iso()))


def _lock(conn) -> None:
    # A scoped write lock also serializes report versions and duplicate confirmations.
    conn.execute("""INSERT INTO assistant_memory (user_id, memory_key, value, updated_at)
        VALUES (?, '_lock', '{}', ?) ON CONFLICT(user_id, memory_key) DO NOTHING""", (_scope(), now_iso()))
    conn.execute("UPDATE assistant_memory SET updated_at = ? WHERE user_id = ? AND memory_key = '_lock'",
                 (now_iso(), _scope()))


def _company(conn, company_id: int) -> dict:
    row = conn.execute("SELECT id, name, symbol FROM companies WHERE id = ? AND user_id = ?",
                       (company_id, _scope())).fetchone()
    if not row:
        raise AgentError("找不到这家公司的个人档案。")
    return dict(row)


def _target(conn, stock: str, session: str, *, writing: bool = False) -> dict:
    if not stock or stock in {"它", "这只", "那只", "这家公司", "上次那个"}:
        memory = _memory(conn, "session:" + session)
        if not memory.get("company_id"):
            raise AgentError("你说的是哪家公司？")
        if memory.get("at", "") < (datetime.now() - timedelta(hours=24)).isoformat():
            raise AgentError("上次讨论已超过一天，你说的是哪家公司？")
        return _company(conn, int(memory["company_id"]))
    found = assistant.resolve(stock)
    if len(found) != 1:
        names = "、".join(f"{row['name']}（{row['symbol']}）" for row in found)
        raise AgentError(f"你指的是哪一家：{names}？" if names else f"没找到「{stock}」，请给公司名或代码。")
    target = found[0]
    if writing and target.get("match") == "fuzzy":
        raise AgentError(f"你说的是 {target['name']}（{target['symbol']}）吗？确认公司后再保存。")
    company = _company(conn, int(target["company_id"]))
    _set_memory(conn, "session:" + session, {"company_id": company["id"], "at": now_iso()})
    return company


def _action(conn, record_id: str, session: str | None = None) -> dict:
    row = conn.execute("SELECT * FROM assistant_actions WHERE id = ? AND user_id = ?",
                       (record_id, _scope())).fetchone()
    if not row or (session is not None and row["session_key"] != session):
        raise AgentError("找不到这条记录，请先查看当前对话的记录。")
    return dict(row)


def _report(conn, company: dict, title: str, text: str, original: str, kind: str) -> tuple[int, str]:
    body = text.strip()
    if not body:
        raise AgentError("还没有需要保存的内容。")
    if original.strip() != body:
        body += "\n\n---\n用户原话（保留以便纠错）：\n" + original.strip()
    version = int(conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM research_reports WHERE company_id = ?",
                               (company["id"],)).fetchone()["v"])
    title = title.strip() or f"{company['name']} · {'导入研究' if kind == 'report' else '随手记'}"
    report_id = int(conn.execute("""INSERT INTO research_reports
        (company_id, version, title, body, model, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
        (company["id"], version, title, body, "飞书助理 · 个人记录", now_iso())).lastrowid)
    return report_id, hashlib.sha256(body.encode()).hexdigest()


def _snapshot(conn, company: dict) -> dict:
    fields = "report_date, revenue, net_profit, operating_cash_flow, receivables, inventory, currency, source"
    periods = [dict(r) for r in conn.execute(f"SELECT {fields} FROM financial_periods WHERE symbol = ? ORDER BY report_date DESC, source LIMIT 8",
                                           (company["symbol"],)).fetchall()]
    events = [dict(r) for r in conn.execute("""SELECT id, event_date, title, url FROM company_calendar_events
        WHERE company_id = ? AND category = '公告' AND (relevance IS NULL OR relevance <> '低')
        ORDER BY event_date DESC, id DESC LIMIT 30""", (company["id"],)).fetchall()]
    return {"financials": periods, "announcements": events}


def _comparison(old: dict, new: dict) -> dict:
    before = {(p["report_date"], p["source"]): p for p in old.get("financials", [])}
    changed = [p for p in new.get("financials", []) if before.get((p["report_date"], p["source"])) != p]
    seen = {p["id"]: p for p in old.get("announcements", [])}
    announcements = [p for p in new.get("announcements", []) if seen.get(p["id"]) != p]
    return {"financials": changed, "announcements": announcements}


def _context(conn, session: str, company: dict | None) -> dict:
    actions = [dict(r) for r in conn.execute("""SELECT id, operation, company_id, state, result, created_at
        FROM assistant_actions WHERE user_id = ? AND session_key = ? AND operation <> 'context'
        ORDER BY created_at DESC, id DESC LIMIT 12""", (_scope(), session)).fetchall()]
    for item in actions:
        item["result"] = _load(item["result"])
    result = {"company": company, "preferences": _memory(conn, "preferences"), "recent_actions": actions}
    if company:
        result["records"] = [dict(r) for r in conn.execute("""SELECT id, title, body, created_at FROM research_reports
            WHERE company_id = ? ORDER BY version DESC LIMIT 3""", (company["id"],)).fetchall()]
        for report in result["records"]:
            report["body"] = report["body"][:6000]
        result["theses"] = [dict(r) for r in conn.execute("SELECT claim, counter_condition, updated_at FROM theses WHERE company_id = ?",
                                                          (company["id"],)).fetchall()]
        result["subscriptions"] = [dict(r) for r in conn.execute("""SELECT id, kind, direction, threshold, reason, enabled
            FROM assistant_subscriptions WHERE user_id = ? AND company_id = ?""", (_scope(), company["id"])).fetchall()]
    return result


def dispatch(envelope: Envelope) -> dict:
    """Caller must verify the signed envelope first. All writes commit atomically."""
    c = envelope.command
    session = envelope.session_key
    with connection() as conn:
        _lock(conn)
        company = None
        if c.operation in {"remember", "watch", "prepare_fill", "compare"} or (c.operation == "context" and c.stock):
            company = _target(conn, c.stock, session, writing=c.operation in {"remember", "watch", "prepare_fill"})
        elif c.operation == "context":
            memory = _memory(conn, "session:" + session)
            if memory.get("company_id"):
                company = _company(conn, memory["company_id"])
        if c.operation == "context":
            return _context(conn, session, company)
        if c.operation == "compare":
            new = _snapshot(conn, company)
            previous = _memory(conn, f"comparison:{company['id']}")
            changes = _comparison(previous.get("snapshot", {}), new) if previous else None
            _set_memory(conn, f"comparison:{company['id']}", {"at": now_iso(), "snapshot": new})
            return {**_context(conn, session, company), "baseline_at": previous.get("at"),
                    "changes": changes, "current": new,
                    "note": "按库内资料对比；首次建立基线不代表没有变化。财报按报告期、币种与来源分别列出，不能把累计数当单季。"}
        # One semantic action per company/kind/message. A retry with changed payload
        # cannot silently create another record for the same user message.
        slot = [envelope.channel, envelope.chat_id, envelope.sender_id, envelope.message_id, c.operation,
                company["id"] if company else c.record_id, c.kind, c.direction]
        request_key = hashlib.sha256(_json(slot).encode()).hexdigest()
        previous = conn.execute("SELECT * FROM assistant_actions WHERE user_id = ? AND request_key = ?",
                                (_scope(), request_key)).fetchone()
        if previous:
            if previous["state"] in {"undone", "superseded", "cancelled", "expired"}:
                label = {"undone": "已撤销", "superseded": "已有修订版", "cancelled": "已取消", "expired": "已过期"}[previous["state"]]
                return {"record_id": previous["id"], "state": previous["state"], "replayed": True,
                        "message": f"这条原操作{label}，没有重新执行。"}
            return {**_load(previous["result"]), "replayed": True, "state": previous["state"]}
        action_id = secrets.token_hex(4).upper()
        conn.execute("""INSERT INTO assistant_actions
            (id, user_id, session_key, request_key, operation, company_id, payload, original_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (action_id, _scope(), session, request_key, c.operation, company["id"] if company else None,
             _json({**c.model_dump(), "_message_id": envelope.message_id}), envelope.original_text, now_iso(), now_iso()))
        result = _execute(conn, envelope, company, action_id)
        result.setdefault("record_id", action_id)
        result.setdefault("state", "done")
        conn.execute("UPDATE assistant_actions SET state = ?, result = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                     (result["state"], _json(result), now_iso(), action_id, _scope()))
        return result


def _execute(conn, e: Envelope, company: dict | None, action_id: str) -> dict:
    c, original = e.command, e.original_text.strip()
    if c.operation == "preferences":
        if not c.text.strip():
            return _memory(conn, "preferences")
        old = _memory(conn, "preferences")
        _set_memory(conn, "preferences", {"text": c.text.strip(), "original": original, "at": now_iso()})
        return {"message": "偏好已更新。", "previous": old}
    if c.operation in {"remember", "correct"}:
        if c.operation == "correct":
            old = _action(conn, c.record_id)
            if old["operation"] not in {"remember", "correct"} or old["state"] != "done":
                raise AgentError("这条记录不能修订，请先查看当前版本。")
            company = (_target(conn, c.stock, e.session_key, writing=True) if c.stock
                       else _company(conn, old["company_id"]))
            conn.execute("UPDATE assistant_actions SET state = 'superseded', updated_at = ? WHERE id = ? AND user_id = ?",
                         (now_iso(), old["id"], _scope()))
            conn.execute("UPDATE assistant_actions SET company_id = ? WHERE id = ?", (company["id"], action_id))
        report_id, digest = _report(conn, company, c.title, c.text, original, c.kind)
        return {"message": "已保存到公司研究记录。" + ("旧版保留，新版已追加。" if c.operation == "correct" else ""),
                "report_id": report_id, "body_hash": digest, "company": company,
                "url": f"/companies/{company['id']}", "previous_id": c.record_id if c.operation == "correct" else None}
    if c.operation == "undo":
        old = _action(conn, c.record_id)
        if old["state"] == "undone":
            return {"message": "这条记录已经撤销。"}
        if old["state"] != "done" or old["operation"] not in {"remember", "correct", "confirm", "preferences"}:
            raise AgentError("这条记录不能直接撤销；跟踪条件请暂停，待确认动作请取消。")
        result = _load(old["result"])
        if old["operation"] in {"remember", "correct"}:
            report = conn.execute("SELECT body FROM research_reports WHERE id = ? AND company_id = ?",
                                  (result["report_id"], old["company_id"])).fetchone()
            if report and hashlib.sha256(report["body"].encode()).hexdigest() != result["body_hash"]:
                raise AgentError("网页上的记录已经修改，请先核对新版，不能撤掉后来的修改。")
            conn.execute("DELETE FROM research_reports WHERE id = ? AND company_id = ?", (result["report_id"], old["company_id"]))
            if result.get("previous_id"):
                conn.execute("UPDATE assistant_actions SET state = 'done' WHERE id = ? AND user_id = ? AND state = 'superseded'",
                             (result["previous_id"], _scope()))
        elif old["operation"] == "confirm":
            if not result.get("fill_id"):
                raise AgentError("这条不是成交登记。")
            conn.execute("DELETE FROM decision_fills WHERE id = ? AND user_id = ?", (result["fill_id"], _scope()))
        else:
            current = _memory(conn, "preferences")
            if current.get("text") != _load(old["payload"]).get("text", "").strip():
                raise AgentError("偏好已有新版本，请直接说明新的偏好。")
            _set_memory(conn, "preferences", result["previous"])
        conn.execute("UPDATE assistant_actions SET state = 'undone', updated_at = ? WHERE id = ? AND user_id = ?",
                     (now_iso(), old["id"], _scope()))
        return {"message": "已撤销，操作历史保留。"}
    if c.operation == "watch":
        if c.kind not in {"price", "research"}:
            raise AgentError("请选择到价跟踪或研究变化跟踪。")
        if c.kind == "price":
            if c.threshold is None:
                raise AgentError("到什么价格提醒你？")
            numbers = [float(n) for n in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", original.replace(",", ""))]
            if c.threshold not in numbers:
                raise AgentError("请明确写一次提醒价格，我不会替你补零或改小数点。")
            quote = assistant.freshest_price(conn, company["symbol"])
            if quote["price"] and not 0.2 <= c.threshold / quote["price"] <= 5:
                raise AgentError(f"提醒价 {c.threshold:g} 与库内价格 {quote['price']:g} 差距很大，请核对公司、币种和数值。")
        direction = c.direction if c.kind == "price" else "below"
        snapshot = _snapshot(conn, company) if c.kind == "research" else {}
        before = conn.execute("SELECT * FROM assistant_subscriptions WHERE user_id = ? AND company_id = ? AND kind = ? AND direction = ?",
                              (_scope(), company["id"], c.kind, direction)).fetchone()
        unchanged = bool(before and before["threshold"] == c.threshold and before["enabled"])
        if unchanged:
            snapshot = _load(before["snapshot"])
        conn.execute("""INSERT INTO assistant_subscriptions
            (user_id, company_id, kind, threshold, direction, reason, snapshot, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id, company_id, kind, direction)
            DO UPDATE SET threshold = excluded.threshold, reason = excluded.reason, enabled = 1,
                snapshot = excluded.snapshot, updated_at = excluded.updated_at""",
            (_scope(), company["id"], c.kind, c.threshold, direction, c.text.strip() or original[:1000],
             _json(snapshot), now_iso(), now_iso()))
        if before and not unchanged:
            _cancel_watch_alerts(conn, before["id"])
        if not unchanged:
            conn.execute("UPDATE assistant_subscriptions SET inside = 0 WHERE user_id = ? AND company_id = ? AND kind = ? AND direction = ?",
                         (_scope(), company["id"], c.kind, direction))
        row = conn.execute("SELECT id FROM assistant_subscriptions WHERE user_id = ? AND company_id = ? AND kind = ? AND direction = ?",
                           (_scope(), company["id"], c.kind, direction)).fetchone()
        return {"message": "跟踪条件已保存。" + ("自动检查已开启。" if assistant.watch_enabled() else "自动检查尚未开启。"),
                "subscription_id": row["id"], "company": company, "kind": c.kind,
                "threshold": c.threshold, "direction": direction,
                "previous": dict(before) if before else None}
    if c.operation in {"pause_watch", "resume_watch"}:
        if not c.record_id.isdigit():
            raise AgentError("请先查看跟踪条件，指定要暂停或恢复的那一条。")
        count = conn.execute("UPDATE assistant_subscriptions SET enabled = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                             (int(c.operation == "resume_watch"), now_iso(), int(c.record_id), _scope())).rowcount
        if not count:
            raise AgentError("找不到这条跟踪条件。")
        if c.operation == "pause_watch":
            _cancel_watch_alerts(conn, int(c.record_id))
        return {"message": "已暂停。" if c.operation == "pause_watch" else "已恢复；下一轮检查时生效。"}
    if c.operation == "prepare_fill":
        if c.price is None:
            raise AgentError("实际成交价是多少？")
        day = c.filled_on or date.today().isoformat()
        try:
            if date.fromisoformat(day) > date.today():
                raise ValueError()
        except ValueError:
            raise AgentError("请填写实际成交日期，不能是未来日期。")
        # A correction replaces all still-pending drafts in this conversation.
        conn.execute("UPDATE assistant_actions SET state = 'cancelled', updated_at = ? WHERE user_id = ? AND session_key = ? AND state = 'pending'",
                     (now_iso(), _scope(), e.session_key))
        card = conn.execute("SELECT * FROM decision_cards WHERE company_id = ? AND user_id = ?", (company["id"], _scope())).fetchone()
        plan = {k: card[k] for k in ("id", "state", "order_plan", "updated_at")} if card else None
        return {"state": "pending", "company": company, "price": c.price, "shares": c.shares,
                "filled_on": day, "plan_snapshot": plan, "record_id": action_id,
                "message": f"待登记：{company['name']}，{day}，成交价 {c.price:g}，"
                    + (f"{c.shares:g} 股。" if c.shares else "股数未提供。")
                    + f"仅记录成交，不改持仓。回复「确认」即可保存，也可改口或取消。（编号 {action_id}）"}
    if c.operation in {"confirm", "cancel"}:
        old = _action(conn, c.record_id, e.session_key)
        if c.operation == "cancel":
            if old["state"] != "pending":
                return {"message": "这条已不在等待确认；已完成的记录请撤销。"}
            conn.execute("UPDATE assistant_actions SET state = 'cancelled', updated_at = ? WHERE id = ? AND user_id = ?",
                         (now_iso(), old["id"], _scope()))
            return {"message": "已取消，未登记成交。"}
        # This original text is signed by the adapter, unavailable as a model parameter.
        valid_text = re.fullmatch(r"确认(?:\s*" + re.escape(old["id"]) + r")?[。！!\s]*", original, re.I)
        if not valid_text or _load(old["payload"]).get("_message_id") == e.message_id:
            raise AgentError(f"请由你本人回复「确认 {old['id']}」，助手不能代为确认。")
        if old["state"] != "pending":
            raise AgentError("这条提议已完成或取消，不会重复登记。")
        if old["created_at"] < (datetime.now() - timedelta(minutes=15)).isoformat():
            conn.execute("UPDATE assistant_actions SET state = 'expired' WHERE id = ?", (old["id"],))
            return {"message": "提议已过期，请重新给出成交信息。", "state": "expired"}
        view = _load(old["result"])
        company = _company(conn, old["company_id"])
        card = conn.execute("SELECT * FROM decision_cards WHERE company_id = ? AND user_id = ?", (company["id"], _scope())).fetchone()
        plan = {k: card[k] for k in ("id", "state", "order_plan", "updated_at")} if card else None
        if plan != view["plan_snapshot"]:
            raise AgentError("计划在确认前已被修改，请重新核对成交草稿。")
        if not card:
            # Same defaults as ensure_decision_card, within this transaction.
            conn.execute("""INSERT INTO decision_cards (user_id, company_id, state, entered_at, created_at, updated_at)
                VALUES (?, ?, 'researching', ?, ?, ?)""", (_scope(), company["id"], now_iso(), now_iso(), now_iso()))
            card = conn.execute("SELECT * FROM decision_cards WHERE company_id = ? AND user_id = ?", (company["id"], _scope())).fetchone()
        order = _load(card["order_plan"])
        fill_id = int(conn.execute("""INSERT INTO decision_fills
            (user_id, card_id, company_id, filled_on, price, shares, planned_price, planned_fraction, state_then, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_scope(), card["id"], company["id"], view["filled_on"], view["price"], view["shares"],
             order.get("price"), str(order.get("fraction") or ""), card["state"],
             _load(old["payload"])["text"][:300], now_iso())).lastrowid)
        conn.execute("UPDATE assistant_actions SET state = 'done', updated_at = ? WHERE id = ?", (now_iso(), old["id"]))
        return {"message": "成交已登记，可撤销；持仓未改变。", "fill_id": fill_id, "company": company}
    raise AgentError("暂不支持这个操作。")


def _watch_message(company: dict, parts: list[dict]) -> str:
    lines = list(dict.fromkeys(line for part in parts for line in part["lines"]))
    return (f"【虾米看股·跟踪】{company['name']}（{company['symbol']}）\n" + "\n".join(lines)
            + "\n回复公司名和“对比”，可以结合原判断查看变化。")


def _cancel_watch_alerts(conn, subscription_id: int) -> None:
    """Remove unsent parts without discarding other watches in the same message."""
    rows = conn.execute("""SELECT id, company_id, levels FROM assistant_alerts
        WHERE user_id = ? AND kind = 'subscription' AND delivery IN ('pending', 'failed')""",
        (_scope(),)).fetchall()
    for row in rows:
        parts = json.loads(row["levels"] or "[]")
        kept = [part for part in parts if part["subscription_id"] != subscription_id]
        if len(kept) == len(parts):
            continue
        if kept:
            conn.execute("UPDATE assistant_alerts SET levels = ?, message = ? WHERE id = ? AND user_id = ?",
                         (_json(kept), _watch_message(_company(conn, row["company_id"]), kept), row["id"], _scope()))
        else:
            conn.execute("UPDATE assistant_alerts SET delivery = 'skipped', delivery_error = ? WHERE id = ? AND user_id = ?",
                         ("跟踪已暂停或条件已修改", row["id"], _scope()))


def scan_subscriptions() -> list[dict]:
    """One durable scan. Trigger state and outbox entry commit together."""
    alerts = []
    with connection() as conn:
        _lock(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM assistant_subscriptions WHERE enabled = 1 AND user_id = ?",
                                            (_scope(),)).fetchall()]
        grouped: dict[int, list[dict]] = {}
        for row in rows:
            company = _company(conn, row["company_id"])
            lines = []
            if row["kind"] == "price":
                quote = assistant.freshest_price(conn, company["symbol"])
                price, threshold = quote["price"], row["threshold"]
                if price is None or quote["as_of"][:10] != date.today().isoformat():
                    continue
                entered = price <= threshold if row["direction"] == "below" else price >= threshold
                holding = price <= threshold * 1.01 if row["direction"] == "below" else price >= threshold * 0.99
                inside = entered or (bool(row["inside"]) and holding)
                if entered and not row["inside"]:
                    lines.append(f"现价 {price:g}（{quote['as_of']}），已{'低于或等于' if row['direction'] == 'below' else '高于或等于'}你设的 {threshold:g}。")
                conn.execute("UPDATE assistant_subscriptions SET inside = ? WHERE id = ? AND user_id = ?",
                             (int(inside), row["id"], _scope()))
            else:
                current = _snapshot(conn, company)
                changes = _comparison(_load(row["snapshot"]), current)
                for period in changes["financials"][:2]:
                    lines.append(f"财报数据有更新：{period['report_date']}，来源 {period['source']}。")
                for event in changes["announcements"][:3]:
                    lines.append(f"{event['event_date']}：{event['title']}" + (f"\n{event['url']}" if event.get('url') else ""))
                conn.execute("UPDATE assistant_subscriptions SET snapshot = ? WHERE id = ? AND user_id = ?",
                             (_json(current), row["id"], _scope()))
            if lines:
                if row["reason"]:
                    lines.append("你当时关注：" + row["reason"][:220])
                grouped.setdefault(company["id"], []).append({"subscription_id": row["id"], "lines": lines})
        for company_id, parts in grouped.items():
            company = _company(conn, company_id)
            message = _watch_message(company, parts)
            alert_id = int(conn.execute("""INSERT INTO assistant_alerts
                (user_id, company_id, kind, levels, message, created_at) VALUES (?, ?, 'subscription', ?, ?, ?)""",
                (_scope(), company_id, _json(parts), message, now_iso())).lastrowid)
            alerts.append({"id": alert_id, "company_id": company_id, "name": company["name"],
                           "levels": [], "price": None, "message": message})
    return alerts
