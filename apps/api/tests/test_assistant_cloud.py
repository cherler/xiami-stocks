import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from stock_decision import access, assistant_cloud as cloud, assistant_cloud_feishu as feishu, assistant_web as web, llm
from stock_decision.database import connection, now_iso
from test_assistant_agent import company
from test_idor import client  # noqa: F401

HEADERS={'Origin':'https://xiamimate.com','X-Stock-Chat':'1'}


@pytest.fixture(autouse=True)
def hosted(monkeypatch):
    monkeypatch.setenv('STOCK_ASSISTANT_WEB_MODE','cloud')
    monkeypatch.setattr(access,'mode',lambda:'multi')
    monkeypatch.setattr(llm,'principal_for_scope',lambda user: llm.Principal(user_id=user,internal_key='test'))
    cloud.heartbeat()


def message(mid='a',text='我的票',company_id=None):
    return web.ChatInput(id=mid*32,text=text,company_id=company_id)


def test_guest_csrf_and_other_company_rejected(client):
    cid=company()
    client.as_user('alice')
    assert client.get('/api/v1/assistant/web/status').json()['mode']=='cloud'
    assert client.post('/api/v1/assistant/web/messages',json=message(company_id=cid).model_dump(),headers=HEADERS).status_code==404
    assert client.post('/api/v1/assistant/web/messages',json=message().model_dump()).status_code==403
    client.as_user(access.GUEST_SCOPE)
    assert client.get('/api/v1/assistant/web/messages').status_code==401
    assert client.get('/api/v1/assistant/web/status').status_code==401


def test_durable_queue_user_and_global_limits(monkeypatch):
    monkeypatch.setenv('STOCK_CLOUD_QUEUE_SIZE','2')
    with cloud.scope('alice'):
        cloud.enqueue(message())
        assert cloud.enqueue(message())=={'id':'a'*32}
        with pytest.raises(HTTPException):
            cloud.enqueue(message('b'))
    with cloud.scope('bob'):
        with pytest.raises(HTTPException):
            cloud.enqueue(message())
        cloud.enqueue(message('b'))
        assert [m['id'] for m in web.history()]==['b'*32]
    with cloud.scope('carol'),pytest.raises(HTTPException) as exc:
        cloud.enqueue(message('c'))
    assert exc.value.status_code==429
    a,b=cloud.claim(),cloud.claim()
    assert {a['user_id'],b['user_id']}=={'alice','bob'}
    assert cloud.claim() is None
    cloud.recover()
    with cloud.scope('alice'):
        assert web.history()[0]['state']=='interrupted'
    assert cloud.claim() is None


def test_worker_history_tools_and_billing_never_cross_users(monkeypatch):
    with cloud.scope('alice'):
        company()
        cloud.enqueue(message(text='帮我记下工业富联：只看现金流'))
    seen=[]
    def call(system,messages,tools,**kw):
        seen.append((access.current_scope(),llm._principal.get().user_id,json.dumps(messages,ensure_ascii=False)))
        if len(seen)==1:
            content=[{'type':'tool_use','id':'tool-1','name':'stock_action','input':{'operation':'remember','stock':'工业富联','text':'只看现金流'}}]
        else:
            content=[{'type':'text','text':'已经记录现金流。'}]
        return {'content':content,'completion':SimpleNamespace(tokens=100)}
    monkeypatch.setattr(llm,'call_tools',call)
    cloud.run(cloud.claim())
    with cloud.scope('alice'):
        assert web.history()[0]['actions'][0]['operation']=='remember'
        assert len(cloud.tool_result('my_stocks',{}, {},''))==1
    with cloud.scope('bob'):
        assert web.history()==[]
        assert cloud.tool_result('my_stocks',{}, {},'')==[]
        cloud.enqueue(message('b',text='我的票'))
    cloud.run(cloud.claim())
    assert seen[-1][0:2]==('bob','bob')
    assert '现金流' not in seen[-1][2]
    assert not llm._strict_billing.get()


def test_budget_atomic_and_failure_cannot_refund(monkeypatch):
    monkeypatch.setenv('STOCK_CLOUD_DAILY_TOKENS','150')
    with cloud.scope('alice'):
        day=cloud.reserve_tokens(100)
    with cloud.scope('bob'),pytest.raises(llm.CreditsError):
        cloud.reserve_tokens(100)
    with cloud.scope('alice'):
        cloud.settle_tokens(day,100,25)
    with cloud.scope('bob'):
        cloud.reserve_tokens(100)
    with cloud.scope('alice'),pytest.raises(llm.CreditsError):
        cloud.reserve_tokens(100)


def test_billing_refusal_returns_shared_budget_without_calling_again(monkeypatch):
    def deny(*a,**kw):
        raise llm.CreditsError('余额不足')
    monkeypatch.setattr(llm,'call_tools',deny)
    with cloud.scope('alice'):
        cloud.enqueue(message())
    cloud.run(cloud.claim())
    with cloud.scope('alice'):
        assert web.history()[0]['error']=='余额不足'
        with connection() as conn:
            assert conn.execute("SELECT tokens FROM assistant_cloud_budget WHERE user_id='alice'").fetchone()['tokens']==0


@pytest.mark.parametrize('failure',[401,503,'network'])
def test_cloud_billing_fails_closed(monkeypatch,failure):
    monkeypatch.setattr(llm,'load_env',lambda:{'XM_API_BASE':'https://billing','XM_INTERNAL_KEY':'key','XM_OWNER_USER_ID':'owner'})
    def post(*a,**kw):
        if failure=='network':
            raise OSError('offline')
        return failure,{}
    monkeypatch.setattr(llm,'_post',post)
    p=llm.set_principal(llm.Principal(user_id='alice',internal_key='key'))
    t=llm._strict_billing.set(True)
    try:
        with pytest.raises(llm.CreditsError):
            llm.reserve('stocks','cloud',1000)
    finally:
        llm._strict_billing.reset(t)
        llm.reset_principal(p)


def test_feishu_trusts_verified_creator_only_and_deduplicates():
    with cloud.scope('alice'),connection() as conn:
        conn.execute("INSERT INTO assistant_cloud_accounts(user_id,state,app_id,sender_id,credential,updated_at) VALUES ('alice','authorized','cli_a','ou_alice','secret',?)",(now_iso(),))
    event=SimpleNamespace(message=SimpleNamespace(chat_type='p2p',message_type='text',chat_id='chat-a',message_id='message-a',content=json.dumps({'text':'我的票'})),
                          sender=SimpleNamespace(sender_id=SimpleNamespace(open_id='ou_bob')))
    feishu.accept('alice','cli_a',event)
    assert cloud.claim() is None
    event.sender.sender_id.open_id='ou_alice'
    feishu.accept('alice','wrong_app',event)
    assert cloud.claim() is None
    event.message.chat_type='group'
    feishu.accept('alice','cli_a',event)
    assert cloud.claim() is None
    event.message.chat_type='p2p'
    feishu.accept('alice','cli_a',event)
    feishu.accept('alice','cli_a',event)
    with cloud.scope('alice'):
        assert len(web.history())==1
        assert cloud.status()['feishu_bound']
        assert 'secret' not in json.dumps(cloud.status())
        feishu.disconnect()
    assert cloud.claim() is None


def test_registration_credentials_hidden_and_confirmation_scoped(client):
    with cloud.scope('alice'),connection() as conn:
        conn.execute("INSERT INTO assistant_cloud_accounts(user_id,state,app_id,sender_id,credential,updated_at) VALUES ('alice','awaiting_confirmation','cli_a','ou_a','secret',?)",(now_iso(),))
    client.as_user('bob')
    assert client.post('/api/v1/assistant/cloud/feishu/confirm',headers=HEADERS).status_code==409
    client.as_user('alice')
    response=client.post('/api/v1/assistant/cloud/feishu/confirm',headers=HEADERS)
    assert response.status_code==200
    assert response.json()['feishu']['state']=='authorized'
    assert 'secret' not in response.text and 'ou_a' not in response.text


def test_model_cannot_override_identity_or_confirm_trade():
    with cloud.scope('alice'):
        company()
        job={'id':'a'*32}
        pending=cloud.tool_result('stock_action',{'operation':'prepare_fill','stock':'工业富联','price':30},job,'记录30元买入')
        with pytest.raises(ValueError):
            cloud.tool_result('stock_action',{'operation':'confirm','record_id':pending['record_id']},{'id':'b'*32},'先不确认')
        with pytest.raises(ValueError):
            cloud.tool_result('stock_action',{'operation':'context','user_id':'bob'},job,'看看')


def test_registration_encrypts_and_stale_completion_cannot_replace_new_request(monkeypatch):
    import lark_oapi as lark
    from cryptography.fernet import Fernet
    monkeypatch.setenv('STOCK_CLOUD_ENCRYPTION_KEY',Fernet.generate_key().decode())
    def register(**kwargs):
        kwargs['on_qr_code']({'url':'https://accounts.feishu.cn/example','expire_in':60})
        return {'client_id':'cli_new','client_secret':'private-secret','user_info':{'open_id':'ou_new','tenant_brand':'feishu'}}
    monkeypatch.setattr(lark,'register_app',register)
    with cloud.scope('alice'),connection() as conn:
        conn.execute("INSERT INTO assistant_cloud_accounts(user_id,state,request_id,updated_at) VALUES ('alice','registering','new',?)",(now_iso(),))
    feishu.register('alice','old')
    with cloud.scope('alice'),connection() as conn:
        assert conn.execute("SELECT state FROM assistant_cloud_accounts WHERE user_id='alice'").fetchone()['state']=='registering'
    feishu.register('alice','new')
    with cloud.scope('alice'),connection() as conn:
        row=conn.execute("SELECT * FROM assistant_cloud_accounts WHERE user_id='alice'").fetchone()
        assert row['state']=='awaiting_confirmation'
        assert row['credential']!='private-secret'
        assert feishu.cipher().decrypt(row['credential'].encode())==b'private-secret'
        assert 'ou_new' not in json.dumps(cloud.status())


def test_transport_multiplexes_clients_without_cross_routing(monkeypatch):
    import lark_oapi as lark
    from cryptography.fernet import Fernet
    monkeypatch.setenv('STOCK_CLOUD_ENCRYPTION_KEY',Fernet.generate_key().decode())
    captured=[]
    async def connect(self):
        captured.append((self._app_id,self._get_conn_url()))
        self._conn=object()
    async def disconnect(self):
        self._conn=None
    monkeypatch.setattr(lark.ws.Client,'_get_conn_url',lambda self:'wss://example/'+self._app_id)
    monkeypatch.setattr(lark.ws.Client,'_connect',connect)
    monkeypatch.setattr(lark.ws.Client,'_disconnect',disconnect)
    for user in ('alice','bob'):
        with cloud.scope(user),connection() as conn:
            conn.execute("INSERT INTO assistant_cloud_accounts(user_id,state,app_id,credential,updated_at) VALUES (?,'authorized',?,?,?)",
                         (user,'cli_'+user,feishu.cipher().encrypt(b'secret').decode(),now_iso()))
    async def exercise():
        pool=feishu.Connections()
        await pool.sync()
        assert set(pool.clients)=={'alice','bob'}
        with cloud.scope('alice'):
            feishu.disconnect()
        await pool.sync()
        assert set(pool.clients)=={'bob'}
        with cloud.scope('bob'):
            feishu.disconnect()
        await pool.sync()
        assert not pool.clients
    asyncio.run(exercise())
    assert captured==[('cli_alice','wss://example/cli_alice'),('cli_bob','wss://example/cli_bob')]
