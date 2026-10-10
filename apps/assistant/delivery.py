"""Deliver computed alerts directly with Feishu's receipt and stable dedup UUID.

This helper runs in nanobot's environment to reuse its official Feishu SDK and
existing app configuration. Alert text never needs a model call. No credentials
or recipient identifiers are printed. A receipt means platform acceptance, not read.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def _send(message: str, key: str, config: dict) -> str:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    from nanobot.channels.feishu.instances import managed_feishu_instance_specs, runtime_channel_name

    raw = json.loads((Path.home() / '.nanobot/config.json').read_text())
    specs = managed_feishu_instance_specs(raw.get('channels', {}).get('feishu', {}))
    selected = [spec for spec in specs if runtime_channel_name('feishu', spec.instance_id) == config['channel']]
    if len(selected) != 1:
        raise RuntimeError('Feishu app configuration is not unique')
    app = selected[0].config
    domain = lark.LARK_DOMAIN if app.get('domain') == 'lark' else lark.FEISHU_DOMAIN
    client = (lark.Client.builder().app_id(os.path.expandvars(app['appId']))
              .app_secret(os.path.expandvars(app['appSecret'])).domain(domain).log_level(lark.LogLevel.ERROR).build())
    chat = config['chat_id']
    request = (CreateMessageRequest.builder().receive_id_type('chat_id' if chat.startswith('oc_') else 'open_id')
               .request_body(CreateMessageRequestBody.builder().receive_id(chat).msg_type('text')
                   .content(json.dumps({'text': message}, ensure_ascii=False)).uuid(key).build()).build())
    response = client.im.v1.message.create(request)
    if not response.success() or not response.data or not response.data.message_id:
        raise RuntimeError('Feishu did not acknowledge message')
    return response.data.message_id


def process(payload: dict, config: dict) -> dict:
    key = hashlib.sha256(payload['key'].encode()).hexdigest()[:32]
    root = Path(config['workspace']) / 'stock-deliveries'
    root.mkdir(mode=0o700, exist_ok=True)
    with (root / f'{key}.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / f'{key}.json'
        record = json.loads(path.read_text()) if path.exists() else {'state': 'pending', 'attempts': 0}
        if record['state'] == 'sent' or payload.get('operation') == 'receipt':
            return record
        if record.get('first_attempt_at') and time.time() - record['first_attempt_at'] > 3500:
            return {**record, 'state': 'failed', 'error': '上次投递结果未确定且已超过安全重试窗口，请人工核对，停止自动重发。'}
        if record['attempts'] >= 6:
            return {**record, 'state': 'failed', 'error': '提醒重试6次仍未成功，请检查飞书连接。'}
        if record.get('next_attempt_at', 0) > time.time():
            return record
        # Persist intent before network I/O. Retrying uses the same platform UUID.
        record.setdefault('first_attempt_at', time.time())
        record.update(state='failed', attempts=record['attempts'] + 1, error='正在等待飞书回执',
                      next_attempt_at=time.time() + min(600, 15 * 2 ** record['attempts']))
        _save(path, record)
        try:
            message_id = _send(payload['message'], key, config)
            record.update(state='sent', message_id=message_id, error='', delivered_at=time.time())
        except Exception:
            record.update(state='failed', error='飞书未返回成功回执，稍后重试。')
        _save(path, record)
        return record


def _save(path: Path, record: dict) -> None:
    temp = path.with_suffix('.tmp')
    with temp.open('w') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(record))
        output.flush()
        os.fsync(output.fileno())
    temp.replace(path)


if __name__ == '__main__':
    try:
        data = json.load(sys.stdin)
        config_path = Path(os.getenv('STOCK_ASSISTANT_BRIDGE_CONFIG', str(Path.home() / '.nanobot/stock-assistant-bridge.json')))
        config = json.loads(config_path.read_text())
        result = process(data, config)
        print(json.dumps({'state': result['state'], 'error': result.get('error', '')}, ensure_ascii=False))
    except Exception:
        print(json.dumps({'state': 'failed', 'error': '提醒连接不可用，请检查本机配置。'}))
        sys.exit(1)
