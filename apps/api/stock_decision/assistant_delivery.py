"""Deliver through the bound Feishu app; acknowledge only platform receipts."""
import json
import subprocess
from pathlib import Path

from . import access, assistant
from .assistant_agent import bridge_config
from .database import connection


def available() -> bool:
    config = bridge_config()
    return bool(config.get('nanobot_python') and config.get('workspace'))


def transfer(alert: dict, *, receipt: bool = False) -> tuple[str, str]:
    if not receipt:
        # Re-read the durable outbox: the user may have paused a watch since scanning.
        with connection() as conn:
            row = conn.execute("SELECT message, delivery FROM assistant_alerts WHERE id = ? AND user_id = ?",
                               (alert['id'], access.current_scope() or access.OWNER_SCOPE)).fetchone()
        if row:
            if row['delivery'] == 'skipped':
                return 'skipped', '跟踪已暂停或条件已修改'
            alert = {**alert, 'message': row['message']}
    config = bridge_config()
    if not available():
        return assistant.deliver(alert['message']) if not receipt else ('queued', '')
    payload = {'operation': 'receipt' if receipt else 'enqueue',
               'key': f"{access.current_scope()}:{alert['id']}",
               'trigger_id': assistant._setting('STOCK_ASSISTANT_TRIGGER'),
               'workspace': config['workspace'], 'message': alert['message']}
    helper = Path(__file__).resolve().parents[2] / 'assistant/delivery.py'
    try:
        proc = subprocess.run([config['nanobot_python'], str(helper)], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=15)
        result = json.loads(proc.stdout)
        # Missing receipt files belong to legacy queued alerts; unknown is not unsent.
        if receipt and result['state'] == 'pending':
            return 'queued', ''
        return result['state'], result.get('error', '')
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return 'queued' if receipt else 'failed', '提醒回执暂不可用，稍后重试'


def reconcile() -> None:
    if not available() or access.current_scope() != access.OWNER_SCOPE:
        return
    with connection() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, message FROM assistant_alerts WHERE user_id = ? AND delivery = 'queued' ORDER BY id DESC LIMIT 20",
                                            (access.OWNER_SCOPE,)).fetchall()]
    for row in rows:
        state, error = transfer(row, receipt=True)
        if state != 'queued' or error:
            assistant._record_delivery(row['id'], state, error)
