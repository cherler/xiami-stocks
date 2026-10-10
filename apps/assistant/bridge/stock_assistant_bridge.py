"""Tiny nanobot tool plugin: sign real request identity, not model-supplied identity.

Uses nanobot's public external-tool entry point and RequestContext. No upstream
patches, model credentials, shell access, or arbitrary file-reading tool.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context

CONFIG = Path(os.getenv("STOCK_ASSISTANT_BRIDGE_CONFIG", str(Path.home() / ".nanobot/stock-assistant-bridge.json")))


class StockAssistantTool(Tool):
    name = "stock_assistant"
    description = (
        "虾米看股个人助理：context 读取当前公司、原判断、记录、偏好和跟踪条件；"
        "remember 保存想法或报告；correct 追加修订(record_id=记录号)；undo 撤销记录；"
        "watch 建立跟踪(kind=price/research，价格需threshold和direction)，pause_watch/resume_watch(record_id=跟踪号)；"
        "compare 对比上次查阅后的财报公告；preferences 读写偏好；"
        "prepare_fill 提交成交草稿；confirm 在本人回复确认后登记；cancel 取消草稿。"
        "用户随便说话，由你理解并组合能力；模糊价格、数量不能猜。"
        "新话题和代词先context，写完看真实回执再回答。"
    )
    parameters = {
        "type": "object", "required": ["operation"], "additionalProperties": False,
        "properties": {
            "operation": {"type": "string", "enum": ["context", "remember", "correct", "undo", "watch",
                "pause_watch", "resume_watch", "compare", "prepare_fill", "confirm", "cancel", "preferences"]},
            "stock": {"type": "string", "description": "公司名或代码。明确代词可留空读取当前会话公司；新公司必须明确。"},
            "text": {"type": "string", "description": "保存的正文、修订后完整正文、跟踪理由或偏好；保留用户原意。"},
            "title": {"type": "string"},
            "record_id": {"type": "string", "description": "工具回执里的记录号或跟踪号，不得编造"},
            "kind": {"type": "string", "enum": ["note", "report", "price", "research"]},
            "threshold": {"type": "number", "description": "用户明确给出的提醒价，不能补零或改小数点"},
            "direction": {"type": "string", "enum": ["below", "above"]},
            "price": {"type": "number"}, "shares": {"type": "number"},
            "filled_on": {"type": "string", "description": "成交日期 YYYY-MM-DD"},
        },
    }

    async def execute(self, **kwargs):
        ctx = current_request_context()
        if not ctx or not ctx.original_user_text or not ctx.sender_id or not ctx.message_id:
            return "Error: 当前不是有身份和消息编号的用户对话，不能保存或确认；请在已绑定的飞书私聊里操作。"
        try:
            config = json.loads(CONFIG.read_text())
            if (ctx.channel != config["channel"] or ctx.chat_id != config["chat_id"]
                    or ctx.sender_id not in config["sender_ids"]):
                return "Error: 这段对话没有绑定到虾米看股。"
            envelope = {
                "command": kwargs, "channel": ctx.channel, "chat_id": ctx.chat_id,
                "sender_id": ctx.sender_id, "session_key": ctx.session_key or f"{ctx.channel}:{ctx.chat_id}",
                "message_id": ctx.message_id, "original_text": ctx.original_user_text,
                "sent_at": int(time.time()),
            }
            raw = json.dumps(envelope, ensure_ascii=False).encode()
            signature = hmac.new(config["secret"].encode(), raw, hashlib.sha256).hexdigest()
            return await asyncio.to_thread(_post, config["api_base"], raw, signature)
        except (OSError, KeyError, ValueError):
            return "Error: 私人助理连接尚未配置完成，请运行项目的助手安装器。"


def _post(api_base: str, raw: bytes, signature: str) -> str:
    request = urllib.request.Request(api_base.rstrip("/") + "/api/v1/assistant/command", data=raw,
        headers={"Content-Type": "application/json", "X-Stock-Signature": signature}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return response.read().decode()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "操作失败")
        except ValueError:
            detail = "操作失败"
        return "Error: " + str(detail)
    except (OSError, TimeoutError):
        return "Error: 暂时连不上虾米看股，未确认保存成功；重试不会重复保存。"
