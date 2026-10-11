"""Run with python -m stock_decision.assistant_cloud_worker (one instance)."""
import asyncio
import fcntl
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from . import assistant, assistant_agent, assistant_cloud as cloud, assistant_cloud_feishu as feishu, pgbackend
from .database import connection, is_postgres, now_iso

log=logging.getLogger(__name__)


def registration_claim():
    with cloud.scope(None),connection() as conn:
        cloud.lock(conn)
        row=conn.execute("SELECT user_id,request_id FROM assistant_cloud_accounts WHERE state='requested' ORDER BY updated_at LIMIT 1").fetchone()
        if row:
            conn.execute("UPDATE assistant_cloud_accounts SET state='registering',updated_at=? WHERE user_id=?",(now_iso(),row['user_id']))
            return row['user_id'],row['request_id']


async def jobs():
    while True:
        try:
            job=await asyncio.to_thread(cloud.claim)
            if job:
                await asyncio.to_thread(cloud.run,job)
            else:
                await asyncio.sleep(1)
        except Exception:
            log.exception('Assistant queue error')
            await asyncio.sleep(5)


async def registrations():
    while True:
        try:
            user=await asyncio.to_thread(registration_claim)
            if user:
                await asyncio.to_thread(feishu.register,*user)
            else:
                await asyncio.sleep(3)
        except Exception:
            log.exception('Assistant registration error')
            await asyncio.sleep(10)


def watches():
    from . import repository
    with cloud.scope(None),connection() as conn:
        users=[r['user_id'] for r in conn.execute('SELECT DISTINCT user_id FROM assistant_cloud_jobs').fetchall()]
        symbols=[r['symbol'] for r in conn.execute("""SELECT DISTINCT c.symbol FROM assistant_subscriptions s
            JOIN companies c ON c.id=s.company_id AND c.user_id=s.user_id WHERE s.enabled=1
            AND s.user_id IN (SELECT user_id FROM assistant_cloud_jobs) LIMIT 500""").fetchall()]
    # Fetch once per symbol, not once per subscriber. Research reads use the cache.
    if symbols and assistant.is_trading_time():
        try:
            with cloud.scope(None):
                repository.store_market_quotes(repository._fetch_market_quotes(symbols))
        except Exception:
            log.warning('Shared watch prices unavailable; keeping dated cache')
    for user in users:
        with cloud.scope(user):
            assistant_agent.scan_subscriptions()
            with connection() as conn:
                alerts=[dict(r) for r in conn.execute("SELECT id,message FROM assistant_alerts WHERE user_id=? AND delivery='pending' ORDER BY id LIMIT 8",(user,)).fetchall()]
                account=conn.execute("SELECT chat_id FROM assistant_cloud_accounts WHERE user_id=? AND state='connected'",(user,)).fetchone()
            for alert in alerts:
                mid=hashlib.sha256(f"alert:{user}:{alert['id']}".encode()).hexdigest()[:32]
                with connection() as conn:
                    # Recheck after scanning: pause/change may have invalidated it.
                    current=conn.execute("SELECT message FROM assistant_alerts WHERE id=? AND user_id=? AND delivery='pending'",(alert['id'],user)).fetchone()
                    if not current:
                        continue
                    body=current['message']
                    conn.execute("""INSERT INTO assistant_web_messages(id,user_id,content,prompt,state,answer,created_at,updated_at)
                        VALUES (?,?,'跟踪提醒','跟踪提醒','done',?,?,?) ON CONFLICT(id) DO NOTHING""",(mid,user,body,now_iso(),now_iso()))
                if account and account['chat_id']:
                    try:
                        if not feishu.send(user,account['chat_id'],body,mid):
                            continue
                    except Exception:
                        continue
                assistant._record_delivery(alert['id'],'sent','网页提醒已保存')


async def periodic(fn, interval):
    while True:
        try:
            await asyncio.to_thread(fn)
        except Exception:
            log.exception('Assistant maintenance failed: %s',fn.__name__)
        await asyncio.sleep(interval)


def cleanup():
    before=(datetime.now()-timedelta(days=90)).isoformat()
    with cloud.scope(None),connection() as conn:
        conn.execute("DELETE FROM assistant_cloud_jobs WHERE created_at<? AND state NOT IN ('queued','running') AND delivery IN ('sent','skipped','failed')",(before,))
        conn.execute("DELETE FROM assistant_web_messages WHERE created_at<? AND state IN ('done','interrupted')",(before,))
        conn.execute('DELETE FROM assistant_cloud_budget WHERE day<?',((datetime.now()-timedelta(days=35)).date().isoformat(),))


async def main():
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=8))
    cloud.recover()
    with cloud.scope(None),connection() as conn:
        conn.execute("UPDATE assistant_cloud_accounts SET state='failed',qr_url='',error='连接过程已中断，请重新扫码。' WHERE state='registering'")
    connections=feishu.Connections()
    async def transport():
        while True:
            try:
                await connections.sync()
            except Exception:
                log.exception('Feishu transport error')
            await asyncio.sleep(10)
    await asyncio.gather(
        *(jobs() for _ in range(min(4,cloud.limit('CONCURRENCY',2)))),
        registrations(),registrations(),transport(),
        periodic(cloud.heartbeat,10),periodic(feishu.deliver_pending,10),
        periodic(watches,180),periodic(cleanup,3600))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    if not cloud.enabled() or not is_postgres() or not pgbackend.rls_status()['effective']:
        raise RuntimeError('Hosted assistant requires cloud mode and effective PostgreSQL RLS')
    feishu.cipher()  # Fail closed on missing/invalid encryption key.
    path=Path(os.getenv('STOCK_CLOUD_LOCK','/srv/xiamimate/stocks-data/assistant-cloud.lock'))
    with path.open('w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        asyncio.run(main())
