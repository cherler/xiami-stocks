"""Owner-scoped browser chat; the API owns identity, original text and receipts."""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import access, assistant_agent as agent, assistant_cloud as cloud
from .database import connection, now_iso

_tasks: set[asyncio.Task] = set()
_status_cache: tuple[float, dict] = (0, {})


class ChatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    text: str = Field(min_length=1, max_length=12000)
    company_id: int | None = Field(default=None, gt=0)


def guide_only():
    return os.getenv("STOCK_ASSISTANT_WEB_MODE", "local").strip().lower() == "guide"


def guard(request: Request, *, write=False):
    if cloud.enabled():
        if access.mode() == 'open' or access.current_scope() in {None, access.GUEST_SCOPE}:
            raise HTTPException(401, '请先登录，再使用云端助手。')
        if write:
            expected = os.getenv('STOCK_CLOUD_ORIGIN', 'https://xiamimate.com')
            if request.headers.get('origin') != expected or request.headers.get('x-stock-chat') != '1':
                raise HTTPException(403, '请从虾米看股的助手入口操作。')
        return
    if guide_only():
        raise HTTPException(409, "线上提供接入指引，请在自己的本地虾米看股使用助手。")
    if access.current_scope() != access.OWNER_SCOPE or not access.is_owner():
        raise HTTPException(403, '这台私人助手只供它的主人使用。请在自己的本地虾米看股连接助手。')
    # Open local mode must not allow arbitrary remote pages to use the owner's assistant.
    if access.mode() == 'open':
        if request.client is None or request.client.host not in {'127.0.0.1','::1','testclient'}:
            raise HTTPException(403, '请从本机网页使用私人助手。')
        if request.url.hostname not in {'127.0.0.1','localhost','::1','testserver'}:
            raise HTTPException(403, '请从本机地址使用私人助手。')
    if write:
        origin = request.headers.get('origin')
        allowed = {str(request.base_url).rstrip('/'), 'http://127.0.0.1:5217', 'http://localhost:5217',
                   'http://127.0.0.1:3000', 'http://localhost:3000'}
        if origin not in allowed or request.headers.get('x-stock-chat') != '1':
            raise HTTPException(403, '请从虾米看股的助手入口发送。')


def configured():
    cfg = agent.bridge_config()
    return bool(cfg.get('web_enabled') and cfg.get('web_client_id') and cfg.get('web_chat_id') and cfg.get('nanobot_python'))


async def helper(payload: dict, timeout=220):
    cfg = agent.bridge_config()
    script = Path(__file__).resolve().parents[2] / 'assistant/web_chat.py'
    proc = await asyncio.create_subprocess_exec(cfg['nanobot_python'], str(script),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), timeout)
        result = json.loads(out)
        if proc.returncode or result.get('error'):
            raise RuntimeError('Assistant unavailable')
        return result
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def status():
    global _status_cache
    if cloud.enabled():
        return await asyncio.to_thread(cloud.status)
    if guide_only():
        return {'mode':'guide', 'ready':False, 'configured':False, 'feishu_bound':False,
                'settings_url':None, 'message':'在自己的电脑运行助手，连接自己的飞书。',
                'guide':[
                    {'title':'在电脑上安装', 'done':False, 'text':'按安装说明运行虾米看股与助手，配置自己的模型服务。'},
                    {'title':'先在本地网页聊一句', 'done':False, 'text':'打开本地虾米看股，点“问助手”，确认可以正常回复。'},
                    {'title':'连接自己的飞书', 'done':False, 'text':'在本地助手的接入帮助中打开连接设置，扫码连接飞书应用、批准私聊配对，再完成提醒绑定。'},
                ]}
    cfg = agent.bridge_config()
    enabled = configured()
    ready = False
    settings_url = 'http://127.0.0.1:18791'
    if enabled:
        if time.monotonic() - _status_cache[0] > 20:
            try:
                response = await helper({'operation':'status'}, timeout=9)
            except Exception:
                response = {'ready':False}
            _status_cache = (time.monotonic(), response)
        ready = bool(_status_cache[1].get('ready'))
        settings_url = _status_cache[1].get('settings_url') or settings_url
    bound = bool(cfg.get('channel') and cfg.get('chat_id') and cfg.get('sender_ids'))
    return {'mode':'local', 'ready':ready, 'configured':enabled, 'feishu_bound':bound,
            'settings_url':settings_url,
            'message': '可以直接问，也可以让我记下想法。' if ready else
                ('助手暂未连接。请启动本机助手，再点重新检查。' if enabled else '本机尚未接入助手。先完成一次安装，再回来聊天。'),
            'guide': [
                {'title':'启动本机助手', 'done':ready, 'text':'助手和虾米看股都需要保持运行；电脑休眠后会暂停。'},
                {'title':'连接飞书应用', 'done':bound, 'text':'打开连接设置，在飞书通道选择连接，按提示扫码创建或绑定应用。'},
                {'title':'配对你的私聊', 'done':bound, 'text':'在飞书给机器人发消息，把配对码填入连接设置批准。再在私聊发送 /trigger 虾米看股到价提醒，最后点下方“完成飞书绑定”。'},
            ]}


def history():
    with connection() as conn:
        rows = [dict(r) for r in conn.execute('''SELECT id, content, company_id, company_name,
            state, answer, error, created_at, updated_at FROM assistant_web_messages
            WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 60''', (access.current_scope(),)).fetchall()]
        actions = _action_map(conn, rows)
        for row in rows:
            if not cloud.enabled() and row['state'] == 'running' and row['updated_at'] < (datetime.now()-timedelta(minutes=5)).isoformat():
                conn.execute("UPDATE assistant_web_messages SET state='interrupted', error=? WHERE id=? AND user_id=?",
                    ('连接已中断，操作结果可能已保存，请先核对记录。', row['id'],access.current_scope()))
                row.update(state='interrupted', error='连接已中断，操作结果可能已保存，请先核对记录。')
            row['actions'] = actions[row['id']]
    return list(reversed(rows))


def _action_map(conn, messages):
    result = {m['id']: [] for m in messages}
    if not messages:
        return result
    # One query per history refresh, regardless of how many messages are visible.
    rows = conn.execute("""SELECT operation, company_id, state, payload, result FROM assistant_actions
        WHERE user_id=? AND created_at>=? ORDER BY created_at""",
        (access.current_scope(), min(m['created_at'] for m in messages))).fetchall()
    for row in rows:
        message_id = json.loads(row['payload']).get('_message_id')
        if message_id not in result or row['state'] != 'done' or row['operation'] in {'context', 'compare'}:
            continue
        saved = json.loads(row['result'])
        result[message_id].append({'operation':row['operation'], 'company_id':row['company_id'],
            'record_id':saved.get('record_id'), 'url':saved.get('url')})
    return result


async def submit(data: ChatInput):
    if cloud.enabled():
        return await asyncio.to_thread(cloud.enqueue, data)
    if not configured():
        raise HTTPException(503, '本机尚未接入助手，请先完成连接。')
    text = data.text.strip()
    if not text or text.startswith(('/', '!')):
        raise HTTPException(422, '请直接描述你的问题或需要记录的内容。连接设置请使用下方入口。')
    with connection() as conn:
        agent._lock(conn)
        old = conn.execute('SELECT content,company_id FROM assistant_web_messages WHERE id=? AND user_id=?',
                           (data.id,access.current_scope())).fetchone()
        if old:
            if old['content'] != text or old['company_id'] != data.company_id:
                raise HTTPException(409, '这条消息的内容已改变，请重新发送。')
            return {'id':data.id}
        running = conn.execute("SELECT id FROM assistant_web_messages WHERE user_id=? AND state='running'", (access.current_scope(),)).fetchone()
        if running:
            raise HTTPException(409, '上一条还在处理，等它完成后再发。')
        name = ''
        prompt = text
        if data.company_id:
            try:
                company = agent._company(conn, data.company_id)
            except agent.AgentError as exc:
                raise HTTPException(404, str(exc)) from exc
            name = company['name']
            prompt = f"当前网页公司：{name}（{company['symbol']}）。仅作为问题背景，具体公司以用户明确表述为准。\n用户原话：{text}"
        conn.execute('''INSERT INTO assistant_web_messages
            (id,user_id,content,prompt,company_id,company_name,state,created_at,updated_at)
            VALUES (?,?,?,?,?,?,'running',?,?)''',
            (data.id,access.current_scope(),text,prompt,data.company_id,name,now_iso(),now_iso()))
    task = asyncio.create_task(_run(data.id, prompt))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {'id':data.id}


async def _run(message_id, prompt):
    try:
        result = await helper({'id':message_id,'prompt':prompt})
        state, answer, error = 'done', result['answer'], ''
    except (Exception, asyncio.CancelledError):
        state, answer, error = 'interrupted', '', '助手连接中断，结果尚未确认。请先查看公司记录，再决定是否重发。'
    with connection() as conn:
        conn.execute('UPDATE assistant_web_messages SET state=?,answer=?,error=?,updated_at=? WHERE id=? AND user_id=?',
                     (state,answer,error,now_iso(),message_id,access.current_scope()))


async def connect_feishu():
    global _status_cache
    if cloud.enabled():
        from .assistant_cloud_feishu import request_connection
        await asyncio.to_thread(request_connection)
        return await status()
    if not configured():
        raise HTTPException(503, '请先安装并启动本机助手。')
    try:
        result = await helper({'operation':'bind_feishu'}, timeout=10)
    except Exception as exc:
        raise HTTPException(503, '暂时无法检查配对，请检查本机助手。') from exc
    if not result.get('bound'):
        raise HTTPException(409, result.get('message', '请先完成飞书配对。'))
    _status_cache = (0, {})
    return await status()
