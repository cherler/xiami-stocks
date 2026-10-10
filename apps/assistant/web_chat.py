"""Private server-side client of nanobot's existing WebUI transport.

Tokens never reach the stock browser. Run with the nanobot Python environment.
"""
import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def endpoint():
    config = json.loads((Path.home() / '.nanobot/config.json').read_text())
    ws = config.get('channels', {}).get('websocket', {})
    port = int(ws.get('port', 18791))
    base = f'http://127.0.0.1:{port}'
    secret = os.path.expandvars(ws.get('tokenIssueSecret') or ws.get('token') or '')
    return base, secret


def bootstrap():
    base, secret = endpoint()
    req = urllib.request.Request(base + '/webui/bootstrap')
    if secret:
        req.add_header('Authorization', 'Bearer ' + secret)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as response:
        return base, json.load(response)


async def chat(payload):
    from websockets.asyncio.client import connect
    base, boot = await asyncio.to_thread(bootstrap)
    bridge_path = Path(os.getenv('STOCK_ASSISTANT_BRIDGE_CONFIG', str(Path.home()/'.nanobot/stock-assistant-bridge.json')))
    config = json.loads(bridge_path.read_text())
    chat_id = config['web_chat_id']
    uri = base.replace('http:', 'ws:') + boot['ws_path'] + '?' + urllib.parse.urlencode({
        'token': boot['token'], 'client_id': config['web_client_id']})
    async with connect(uri, proxy=None, open_timeout=8, max_size=4*1024*1024) as socket:
        await socket.recv()  # ready
        await socket.send(json.dumps({'type':'attach', 'chat_id':chat_id}))
        while True:
            event = json.loads(await socket.recv())
            if event.get('event') == 'attached' and event.get('chat_id') == chat_id:
                break
        await socket.send(json.dumps({'type':'message', 'webui':True, 'chat_id':chat_id,
                                      'turn_id':payload['id'], 'content':payload['prompt']}))
        return await receive_answer(socket, chat_id, payload['id'])




async def receive_answer(socket, chat_id, turn_id):
    """Fold answer streams only; reasoning and tool activity never become the answer."""
    text, current_stream = '', None
    buffers = {}
    async for raw in socket:
        event = json.loads(raw)
        if event.get('chat_id') != chat_id or event.get('turn_id') not in (None, turn_id):
            continue
        kind = event.get('event')
        if kind == 'error':
            raise RuntimeError('Assistant rejected message')
        if kind == 'message' and event.get('kind') not in ('progress','tool_hint'):
            text = event.get('text', '')
        if kind in ('delta', 'stream_end'):
            current_stream = event.get('stream_id', '')
            if kind == 'delta':
                buffers[current_stream] = buffers.get(current_stream, '') + event.get('text', '')
            elif 'text' in event:
                buffers[current_stream] = event['text']
            text = buffers.get(current_stream, '')
        if kind == 'turn_end':
            if event.get('outcome', 'completed') != 'completed' or not text:
                raise RuntimeError('Assistant turn did not finish')
            return {'answer':text}
    raise RuntimeError('Assistant connection ended')


def bind_feishu():
    """Bind only the uniquely approved private chat; never accept IDs from a browser."""
    import tempfile
    path = Path(os.getenv('STOCK_ASSISTANT_BRIDGE_CONFIG', str(Path.home()/'.nanobot/stock-assistant-bridge.json')))
    config = json.loads(path.read_text())
    try:
        approved = json.loads((Path.home()/'.nanobot/pairing.json').read_text()).get('approved', {}).get('feishu', [])
        triggers = json.loads((Path(config['workspace'])/'triggers/triggers.json').read_text()).get('triggers', [])
    except (OSError, ValueError):
        return {'bound':False, 'message':'请先在连接设置批准飞书配对，并在私聊发送 /trigger 虾米看股到价提醒。'}
    chats = {t.get('chatId') for t in triggers if t.get('enabled') and t.get('channel')=='feishu' and t.get('chatId')}
    if len(approved)!=1 or len(chats)!=1:
        return {'bound':False, 'message':'需要唯一的已批准飞书用户和私聊提醒路由；请先完成配对，移除多余绑定后再检查。'}
    chat_id = next(iter(chats))
    if config.get('sender_ids') and (config['sender_ids'] != approved or config.get('chat_id') != chat_id):
        return {'bound':False, 'message':'现有绑定与这次配对不同。为保留原私聊，请先在本机重新配置助手。'}
    config.update(channel='feishu', chat_id=chat_id, sender_ids=approved)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(config, output, ensure_ascii=False, indent=2)
    os.replace(output.name, path)
    return {'bound':True}

if __name__ == '__main__':
    try:
        data = json.load(sys.stdin)
        if data.get('operation') == 'bind_feishu':
            print(json.dumps(bind_feishu(), ensure_ascii=False))
        elif data.get('operation') == 'status':
            base, _ = bootstrap()
            print(json.dumps({'ready':True, 'settings_url':base}))
        else:
            print(json.dumps(asyncio.run(asyncio.wait_for(chat(data), timeout=210)), ensure_ascii=False))
    except Exception:
        # Never print connection URLs, token values or upstream exception bodies.
        print(json.dumps({'error':'助手连接中断，结果尚未确认。请先查看记录，再决定是否重发。'}, ensure_ascii=False))
        sys.exit(1)
