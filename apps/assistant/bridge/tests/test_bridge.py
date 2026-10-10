import asyncio
import hashlib
import hmac
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import stock_assistant_bridge as bridge
from nanobot.agent.tools.context import RequestContext, request_context

spec = importlib.util.spec_from_file_location('stock_delivery_test', Path(__file__).resolve().parents[2] / 'delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class BridgeTests(unittest.TestCase):
    def test_model_cannot_supply_real_user_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            path.write_text(json.dumps({'secret':'test', 'api_base':'http://localhost', 'channel':'feishu', 'chat_id':'chat', 'sender_ids':['user']}))
            ctx = RequestContext(channel='feishu', chat_id='chat', sender_id='user', message_id='m1',
                                 session_key='session', original_user_text='先不要确认')
            sent = []
            def capture(api, raw, signature):
                assert hmac.compare_digest(signature, hmac.new(b'test', raw, hashlib.sha256).hexdigest())
                sent.append(json.loads(raw))
                return '{}'
            with patch.object(bridge, 'CONFIG', path), patch.object(bridge, '_post', capture), request_context(ctx):
                asyncio.run(bridge.StockAssistantTool().execute(operation='confirm', record_id='AABBCCDD'))
            self.assertEqual(sent[0]['original_text'], '先不要确认')
            self.assertEqual(sent[0]['sender_id'], 'user')

    def test_unbound_user_and_automation_cannot_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            path.write_text(json.dumps({'secret':'test', 'channel':'feishu', 'chat_id':'chat', 'sender_ids':['owner']}))
            for sender in ('other', 'trigger'):
                with patch.object(bridge, 'CONFIG', path), request_context(RequestContext(
                        channel='feishu', chat_id='chat', sender_id=sender, message_id='m', original_user_text='确认')):
                    result = asyncio.run(bridge.StockAssistantTool().execute(operation='confirm', record_id='A'))
                    self.assertTrue(result.startswith('Error:'))

    def test_delivery_restart_reuses_successful_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'workspace': folder}
            payload = {'key':'owner:1', 'message':'测试仅在假发送器中使用'}
            with patch.object(delivery, '_send', return_value='platform-message') as send:
                one = delivery.process(payload, config)
                two = delivery.process(payload, config)
                self.assertEqual(one['state'], 'sent')
                self.assertEqual(two['message_id'], 'platform-message')
                self.assertEqual(send.call_count, 1)

    def test_delivery_retry_keeps_uuid_and_stops_after_window(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'workspace': folder}
            payload = {'key':'owner:2', 'message':'测试不发送'}
            clock = [1000]
            with patch.object(delivery.time, 'time', lambda: clock[0]), patch.object(delivery, '_send', side_effect=TimeoutError) as send:
                one = delivery.process(payload, config)
                self.assertEqual(one['state'], 'failed')
                clock[0] = 1200
                delivery.process(payload, config)
                self.assertEqual(send.call_args_list[0].args[1], send.call_args_list[1].args[1])
                clock[0] = 5000
                stopped = delivery.process(payload, config)
                self.assertEqual(send.call_count, 2)
                self.assertIn('停止自动重发', stopped['error'])

    def test_official_sdk_request_schema_and_channel_selection(self):
        from lark_oapi.api.im.v1 import CreateMessageRequestBody
        from nanobot.channels.feishu.instances import managed_feishu_instance_specs, runtime_channel_name
        specs = managed_feishu_instance_specs({'enabled':True, 'appId':'test', 'appSecret':'test'})
        self.assertEqual(runtime_channel_name('feishu', specs[0].instance_id), 'feishu')
        self.assertEqual(CreateMessageRequestBody.builder().uuid('1234').build().uuid, '1234')


if __name__ == '__main__':
    unittest.main()
