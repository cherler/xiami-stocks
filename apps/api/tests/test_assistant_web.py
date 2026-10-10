"""Browser transport identity, durable receipts and isolation; no live model requests."""
import asyncio
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException
from stock_decision import access, assistant_agent as agent, assistant_web as web
from stock_decision.database import connection, now_iso, is_postgres
from test_assistant_agent import company, message
from test_idor import client  # noqa: F401

CFG = {'secret':'test-secret', 'web_enabled':True, 'web_client_id':'client',
       'web_chat_id':'chat', 'nanobot_python':'unused', 'channel':'feishu',
       'chat_id':'private', 'sender_ids':['owner']}
HEADERS = {'Origin':'http://testserver', 'X-Stock-Chat':'1'}


@pytest.fixture(autouse=True)
def fake_config(monkeypatch):
    monkeypatch.setenv('STOCK_ASSISTANT_WEB_MODE', 'local')
    monkeypatch.setattr(agent, 'bridge_config', lambda: dict(CFG))
    monkeypatch.setattr(web, '_status_cache', (0, {}))
    async def helper(_payload, timeout=220):
        return {'ready':True, 'answer':'完成', 'settings_url':'http://127.0.0.1:18791'}
    monkeypatch.setattr(web, 'helper', helper)


def test_routes_deny_other_users_and_cross_origin(client):
    assert client.get('/api/v1/assistant/web/status').status_code == 200
    for origin in (None, 'https://evil.example'):
        headers = {'X-Stock-Chat':'1'}
        if origin:
            headers['Origin'] = origin
        assert client.post('/api/v1/assistant/web/messages', json={'id':'a'*32,'text':'测试'}, headers=headers).status_code==403
        assert client.post('/api/v1/assistant/web/connect-feishu', headers=headers).status_code==403
    for scope in ('other', access.GUEST_SCOPE):
        client.as_user(scope)
        assert client.get('/api/v1/assistant/web/status').status_code==403
        assert client.get('/api/v1/assistant/web/messages').status_code==403
        assert client.post('/api/v1/assistant/web/messages', json={'id':'a'*32,'text':'测试'}, headers=HEADERS).status_code==403


def test_reply_persisted_after_idempotent_submission_and_company_context():
    cid = company()
    async def exercise():
        data = web.ChatInput(id='a'*32,text='只看现金流',company_id=cid)
        first = await web.submit(data)
        assert await web.submit(data) == first
        with pytest.raises(HTTPException) as exc:
            await web.submit(web.ChatInput(id='b'*32,text='另一条'))
        assert exc.value.status_code == 409
        with pytest.raises(HTTPException):
            await web.submit(web.ChatInput(id='a'*32,text='改掉消息'))
        await asyncio.gather(*web._tasks)
        rows = web.history()
        assert len(rows)==1 and rows[0]['answer']=='完成' and rows[0]['state']=='done'
        with connection() as conn:
            row = conn.execute('SELECT prompt,content FROM assistant_web_messages').fetchone()
            assert '工业富联' in row['prompt'] and row['content']=='只看现金流'
    asyncio.run(exercise())


def test_failure_is_not_replayed_and_stale_rows_recover(monkeypatch):
    calls=[]
    async def fail(payload, **kw):
        calls.append(payload)
        raise TimeoutError
    monkeypatch.setattr(web,'helper',fail)
    async def exercise():
        data=web.ChatInput(id='a'*32,text='保存这条')
        await web.submit(data)
        await asyncio.gather(*web._tasks)
        await web.submit(data)
        assert len(calls)==1
    asyncio.run(exercise())
    assert web.history()[0]['state']=='interrupted'
    with connection() as conn:
        conn.execute("UPDATE assistant_web_messages SET state='running',updated_at='2000-01-01T00:00:00'")
    assert web.history()[0]['state']=='interrupted'


def test_foreign_company_cannot_be_attached_and_admin_commands_blocked():
    cid=company()
    token=access.set_scope('other')
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(web.submit(web.ChatInput(id='a'*32,text='这家如何',company_id=cid)))
        assert exc.value.status_code==404
    finally:
        access.reset_scope(token)
    for text in ('/pairing approve abc','!shell command','   '):
        with pytest.raises(HTTPException):
            asyncio.run(web.submit(web.ChatInput(id='b'*32,text=text)))


def signed_web(original='确认', prompt='当前网页公司：工业富联。\n用户原话：确认'):
    mid='c'*32
    with connection() as conn:
        conn.execute('''INSERT INTO assistant_web_messages(id,user_id,content,prompt,state,created_at,updated_at)
            VALUES (?,?,?,?,'running',?,?)''', (mid,access.current_scope(),original,prompt,now_iso(),now_iso()))
    e=message('context', original=prompt, mid=mid)
    e.channel='websocket'; e.sender_id='client'; e.chat_id='chat'
    return e


def verify(e):
    raw=e.model_dump_json().encode()
    return agent.verify_request(raw,hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest())


def test_web_context_restores_real_original_and_rejects_forgery():
    e=signed_web(original='先不要确认')
    assert verify(e).original_text=='先不要确认'
    for field,value in [('sender_id','imposter'),('chat_id','other'),('message_id','missing'),('original_text','确认')]:
        with pytest.raises(agent.AgentError):
            verify(e.model_copy(update={field:value}))
    with connection() as conn:
        conn.execute("UPDATE assistant_web_messages SET state='done'")
    with pytest.raises(agent.AgentError):
        verify(e)


def test_web_receipt_links_actual_report_and_is_isolated():
    cid=company()
    e=signed_web(original='帮我记下先看现金流')
    e.command=agent.Command(operation='remember',stock='工业富联',text='先看现金流')
    result=agent.dispatch(verify(e))
    history=web.history()
    assert history[0]['actions'][0]['record_id']==result['record_id']
    assert history[0]['actions'][0]['company_id']==cid
    token=access.set_scope('other')
    try:
        assert web.history()==[]
        if is_postgres():
            with connection() as conn:
                assert conn.execute('SELECT COUNT(*) AS n FROM assistant_web_messages').fetchone()['n']==0
    finally:
        access.reset_scope(token)


def test_guide_is_public_and_never_reads_private_runtime(client, monkeypatch):
    monkeypatch.setenv('STOCK_ASSISTANT_WEB_MODE', 'guide')
    def forbidden(*args, **kwargs):
        raise AssertionError('Guide must not read private runtime')
    monkeypatch.setattr(agent, 'bridge_config', forbidden)
    monkeypatch.setattr(web, 'helper', forbidden)
    for scope in (access.OWNER_SCOPE, 'other', access.GUEST_SCOPE):
        client.as_user(scope)
        response = client.get('/api/v1/assistant/web/status')
        assert response.status_code == 200
        data = response.json()
        assert data['mode'] == 'guide' and data['settings_url'] is None
        assert not data['ready'] and not data['feishu_bound']
        assert len(data['guide']) == 3
        assert 'private' not in response.text and '18791' not in response.text
        assert client.get('/api/v1/assistant/web/messages').status_code == 409
        assert client.post('/api/v1/assistant/web/messages', json={'id':'a'*32, 'text':'保存'}, headers=HEADERS).status_code == 409
        assert client.post('/api/v1/assistant/web/connect-feishu', headers=HEADERS).status_code == 409
