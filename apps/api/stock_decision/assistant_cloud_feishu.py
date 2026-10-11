"""Feishu device registration and multiplexed transport, never model identity.

App secrets are encrypted at rest. Identity comes from the device-flow result;
neither the first chat sender nor an LLM can claim another user's account.
"""
import asyncio
import hashlib
import json
import os
import time
import uuid
import urllib.request
from datetime import datetime, timedelta

from fastapi import HTTPException

from . import assistant_cloud as cloud, assistant_agent as agent
from .database import connection, now_iso


def cipher():
    from cryptography.fernet import Fernet
    return Fernet(os.environ['STOCK_CLOUD_ENCRYPTION_KEY'].encode())


def request_connection():
    user = agent._scope()
    if not cloud.ready():
        raise HTTPException(503, '云端助手暂时离线，请稍后连接。')
    with cloud.scope(None), connection() as conn:
        cloud.lock(conn)
        old = conn.execute('SELECT state,updated_at FROM assistant_cloud_accounts WHERE user_id=?',(user,)).fetchone()
        if old and old['state'] in {'requested','registering','awaiting_confirmation','authorized','connected'}:
            return
        if old and old['updated_at'] > (datetime.now()-timedelta(minutes=2)).isoformat():
            raise HTTPException(429, '请稍等两分钟再重新连接。')
        pending=conn.execute("SELECT COUNT(*) AS n FROM assistant_cloud_accounts WHERE state IN ('requested','registering')").fetchone()['n']
        if pending >= 2:
            raise HTTPException(429, '目前有其他用户正在扫码，请稍后再连接；网页聊天可照常使用。')
        count=conn.execute("SELECT COUNT(*) AS n FROM assistant_cloud_accounts WHERE state NOT IN ('failed','disconnected')").fetchone()['n']
        if count >= cloud.limit('CONNECTIONS',128):
            raise HTTPException(429, '飞书连接数量已到服务容量上限，请先使用网页助手。')
        conn.execute("""INSERT INTO assistant_cloud_accounts(user_id,state,request_id,updated_at) VALUES (?,'requested',?,?)
            ON CONFLICT(user_id) DO UPDATE SET state='requested',request_id=excluded.request_id,qr_url='',expires_at='',app_id='',credential='',sender_id='',chat_id='',error='',updated_at=excluded.updated_at""",(user,uuid.uuid4().hex,now_iso()))


def confirm_connection():
    with connection() as conn:
        count=conn.execute("UPDATE assistant_cloud_accounts SET state='authorized',updated_at=? WHERE user_id=? AND state='awaiting_confirmation'",
                           (now_iso(),agent._scope())).rowcount
    if not count:
        raise HTTPException(409,'请先完成扫码，再确认连接。')
    return cloud.status()


def disconnect():
    user=agent._scope()
    with connection() as conn:
        conn.execute("UPDATE assistant_cloud_accounts SET state='disconnected',credential='',sender_id='',chat_id='',qr_url='',updated_at=? WHERE user_id=?",(now_iso(),user))
        conn.execute("""UPDATE assistant_web_messages SET state='interrupted',error='飞书已断开，排队消息已取消。'
            WHERE user_id=? AND id IN (SELECT id FROM assistant_cloud_jobs WHERE user_id=? AND channel='feishu' AND state='queued')""",(user,user))
        conn.execute("UPDATE assistant_cloud_jobs SET state='interrupted',delivery='skipped' WHERE user_id=? AND channel='feishu' AND state='queued'",(user,))
    return cloud.status()


async def register(user, request_id):
    import lark_oapi as lark
    with cloud.scope(user):
        def qr(info):
            with connection() as conn:
                conn.execute("UPDATE assistant_cloud_accounts SET qr_url=?,expires_at=?,updated_at=? WHERE user_id=? AND state='registering' AND request_id=?",
                    (info['url'],(datetime.now()+timedelta(seconds=min(180,info['expire_in']))).isoformat(),now_iso(),user,request_id))
        async def exchange():
            task=asyncio.create_task(lark.aregister_app(on_qr_code=qr,source='xiami-stocks',create_only=True,
                app_preset={'name':'虾米看股助手','desc':'查股票、记想法、盯变化、核对计划'},
                addons={'preset':False,'scopes':{'tenant':['im:message:send_as_bot','im:message.p2p_msg:readonly']},
                        'events':{'items':{'tenant':['im.message.receive_v1']}}}))
            try:
                while True:
                    done,_=await asyncio.wait({task},timeout=2)
                    if done:
                        return await task
                    with connection() as conn:
                        row=conn.execute("SELECT state,request_id FROM assistant_cloud_accounts WHERE user_id=?",(user,)).fetchone()
                    if not row or row['state']!='registering' or row['request_id']!=request_id:
                        raise ValueError('Registration cancelled')
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task,return_exceptions=True)
        try:
            result=await asyncio.wait_for(exchange(),180)
            sender=(result.get('user_info') or {}).get('open_id')
            brand=(result.get('user_info') or {}).get('tenant_brand')
            if not sender or brand not in {None,'feishu'}:
                raise ValueError('No verified Feishu creator identity')
            encrypted=cipher().encrypt(result['client_secret'].encode()).decode()
            with connection() as conn:
                conn.execute("""UPDATE assistant_cloud_accounts SET state='awaiting_confirmation',app_id=?,credential=?,sender_id=?,qr_url='',updated_at=?
                    WHERE user_id=? AND state='registering' AND request_id=?""",(result['client_id'],encrypted,sender,now_iso(),user,request_id))
        except Exception:
            with connection() as conn:
                conn.execute("UPDATE assistant_cloud_accounts SET state='failed',qr_url='',error='扫码未完成或飞书未返回可验证的身份，请重试。',updated_at=? WHERE user_id=? AND state='registering' AND request_id=?",(now_iso(),user,request_id))


def accept(user, expected_app, event):
    """Trusted SDK event only. Text and sender identity have separate origins."""
    from .assistant_web import ChatInput
    message=event.message
    if message.chat_type != 'p2p' or message.message_type != 'text':
        return
    with cloud.scope(user):
        with connection() as conn:
            account=conn.execute("SELECT * FROM assistant_cloud_accounts WHERE user_id=? AND state IN ('authorized','connected')",(user,)).fetchone()
            if (not account or account['app_id'] != expected_app or
                    event.sender.sender_id.open_id != account['sender_id']):
                return
            conn.execute("UPDATE assistant_cloud_accounts SET chat_id=?,state='connected',error='',updated_at=? WHERE user_id=?",(message.chat_id,now_iso(),user))
        try:
            original=json.loads(message.content).get('text','')
            mid=hashlib.sha256((user+'|'+expected_app+'|'+message.message_id).encode()).hexdigest()[:32]
            cloud.enqueue(ChatInput(id=mid,text=original),channel='feishu',chat_id=message.chat_id)
        except (HTTPException,ValueError) as exc:
            # Do not let an over-quota user generate unlimited outgoing API work.
            detail=exc.detail if isinstance(exc,HTTPException) else '请发送不超过 12000 字的文字问题。'
            return {'chat_id':message.chat_id,'message':detail,'id':message.message_id}


def api(path, body, token=''):
    request=urllib.request.Request('https://open.feishu.cn/open-apis/'+path,
        data=json.dumps(body).encode(),headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    with urllib.request.urlopen(request,timeout=10) as response:
        value=json.loads(response.read(1_000_000))
    if value.get('code',0):
        raise RuntimeError('Feishu request rejected')
    return value


def send(user, chat_id, text, key):
    with cloud.scope(user), connection() as conn:
        row=conn.execute("SELECT app_id,credential,chat_id FROM assistant_cloud_accounts WHERE user_id=? AND state='connected'",(user,)).fetchone()
    if not row or row['chat_id'] != chat_id:
        return False
    token=api('auth/v3/tenant_access_token/internal',{'app_id':row['app_id'],'app_secret':cipher().decrypt(row['credential'].encode()).decode()})['tenant_access_token']
    result=api('im/v1/messages?receive_id_type=chat_id',{'receive_id':chat_id,'msg_type':'text',
        'content':json.dumps({'text':text[:14000]},ensure_ascii=False),'uuid':hashlib.sha256(key.encode()).hexdigest()[:40]},token)
    return bool((result.get('data') or {}).get('message_id'))


class Connections:
    """One SDK WebSocket loop, many lightweight transports, zero per-user LLMs.

    SDK 1.7.3 pins the async bridge below: its public start() owns an event loop
    and cannot multiplex clients in an already-running worker. No global loop
    is changed after initialization. Revisit this adapter when upgrading SDK.
    """
    def __init__(self):
        self.clients={}
        self.errors={}

    async def sync(self):
        import lark_oapi as lark
        import lark_oapi.ws.client as transport
        from types import SimpleNamespace
        import requests
        # SDK endpoint discovery has no timeout by default. Keep its bounded
        # HTTP adapter local to this SDK module, not a process-wide requests patch.
        transport.requests=SimpleNamespace(post=lambda *a,**kw: requests.post(*a,timeout=10,**kw))
        transport.loop=asyncio.get_running_loop()
        class MultiplexClient(lark.ws.Client):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                self.background=set()
                self.retired=False

            async def _receive_message_loop(self):
                task=asyncio.current_task()
                self.background.add(task)
                try:
                    await super()._receive_message_loop()
                finally:
                    self.background.discard(task)

            async def _handle_message(self,msg):
                task=asyncio.current_task()
                self.background.add(task)
                try:
                    await super()._handle_message(msg)
                finally:
                    self.background.discard(task)

            async def retire(self):
                self.retired=True
                self._auto_reconnect=False
                pending=[*self.background,self._cache._cron]
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending,return_exceptions=True)
                await self._disconnect()

            async def _connect(self):
                if self.retired:
                    raise RuntimeError('Transport retired')
                if self._conn is not None:
                    return
                url=await asyncio.to_thread(super()._get_conn_url)
                self._get_conn_url=lambda:url
                await super()._connect()
        with cloud.scope(None),connection() as conn:
            rows=[dict(r) for r in conn.execute("SELECT user_id,app_id,credential FROM assistant_cloud_accounts WHERE state IN ('authorized','connected') LIMIT ?",(cloud.limit('CONNECTIONS',128),)).fetchall()]
        wanted={r['user_id']:r for r in rows}
        self.errors={key:value for key,value in self.errors.items() if key.removeprefix('notice:') in wanted}
        for user,(client,ping,app) in list(self.clients.items()):
            if user not in wanted or wanted[user]['app_id'] != app:
                ping.cancel()
                await client.retire()
                del self.clients[user]
        for user,row in wanted.items():
            if user in self.clients or self.errors.get(user,0)>time.monotonic():
                continue
            def receive(data, user=user, app=row['app_id']):
                # SDK callback never receives a model-provided user ID.
                notice=accept(user,app,data.event)
                if notice and self.errors.get('notice:'+user,0)<time.monotonic():
                    self.errors['notice:'+user]=time.monotonic()+60
                    asyncio.create_task(asyncio.to_thread(send,user,notice['chat_id'],notice['message'],notice['id']+':notice'))
            handler=lark.EventDispatcherHandler.builder('','').register_p2_im_message_receive_v1(receive).build()
            client=MultiplexClient(row['app_id'],cipher().decrypt(row['credential'].encode()).decode(),
                                  event_handler=handler,log_level=lark.LogLevel.ERROR)
            try:
                await asyncio.wait_for(client._connect(),15)
                ping=asyncio.create_task(client._ping_loop())
                self.clients[user]=(client,ping,row['app_id'])
                with cloud.scope(user),connection() as conn:
                    conn.execute("UPDATE assistant_cloud_accounts SET error='' WHERE user_id=?",(user,))
            except Exception:
                await client.retire()
                self.errors[user]=time.monotonic()+60
                with cloud.scope(user),connection() as conn:
                    conn.execute("UPDATE assistant_cloud_accounts SET error='飞书连接暂未就绪，正在重连。' WHERE user_id=?",(user,))


def deliver_pending():
    with cloud.scope(None),connection() as conn:
        rows=[dict(r) for r in conn.execute("""SELECT j.id,j.user_id,j.chat_id,m.answer,m.error FROM assistant_cloud_jobs j
            JOIN assistant_web_messages m ON m.id=j.id AND m.user_id=j.user_id
            WHERE j.channel='feishu' AND j.state IN ('done','interrupted') AND j.delivery='pending'
            ORDER BY j.created_at LIMIT 8""").fetchall()]
    for row in rows:
        with cloud.scope(row['user_id']),connection() as conn:
            conn.execute('UPDATE assistant_cloud_jobs SET delivery_attempts=delivery_attempts+1 WHERE id=? AND user_id=?',(row['id'],row['user_id']))
        try:
            ok=send(row['user_id'],row['chat_id'],row['answer'] or row['error'],row['id'])
        except Exception:
            with cloud.scope(row['user_id']),connection() as conn:
                conn.execute("UPDATE assistant_cloud_jobs SET delivery='failed' WHERE id=? AND user_id=? AND delivery_attempts>=5",(row['id'],row['user_id']))
            continue
        with cloud.scope(row['user_id']),connection() as conn:
            conn.execute('UPDATE assistant_cloud_jobs SET delivery=? WHERE id=? AND user_id=?',('sent' if ok else 'skipped',row['id'],row['user_id']))
