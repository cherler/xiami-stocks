import asyncio
import importlib.util
import json
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('web_chat',Path(__file__).resolve().parents[2]/'web_chat.py')
web=importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

async def events(rows):
    for row in rows:
        yield json.dumps({'chat_id':'chat','turn_id':'turn',**row})

class WebChatTests(unittest.TestCase):
    def test_streams_reasoning_progress_and_other_turns_are_separate(self):
        rows=[{'event':'reasoning_delta','text':'private reasoning'},
              {'event':'message','kind':'progress','text':'查阅中'},
              {'event':'delta','stream_id':'first','text':'先查一下'},
              {'event':'delta','stream_id':'final','text':'已'},
              {'event':'delta','stream_id':'final','text':'保存'},
              {'event':'message','turn_id':'another','text':'别人的回答'},
              {'event':'stream_end','stream_id':'final'},
              {'event':'turn_end'}]
        self.assertEqual(asyncio.run(web.receive_answer(events(rows),'chat','turn')),{'answer':'已保存'})

    def test_interrupted_partial_answer_never_becomes_success(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(web.receive_answer(events([{'event':'delta','text':'正在保存'},
                {'event':'turn_end','outcome':'failed'}]),'chat','turn'))

    def test_non_streaming_final_and_rewritten_stream(self):
        for rows in ([{'event':'message','text':'回复'},{'event':'turn_end'}],
                     [{'event':'delta','text':'旧回复'},{'event':'stream_end','text':'回复'},{'event':'turn_end'}]):
            self.assertEqual(asyncio.run(web.receive_answer(events(rows),'chat','turn')),{'answer':'回复'})

    def test_binding_accepts_only_unique_approved_route_and_preserves_identity(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); home=root/'.nanobot'; home.mkdir()
            workspace=root/'workspace'; (workspace/'triggers').mkdir(parents=True)
            cfg=home/'stock-assistant-bridge.json'
            cfg.write_text(json.dumps({'secret':'keep', 'workspace':str(workspace),'web_client_id':'keep-client'}))
            (home/'pairing.json').write_text(json.dumps({'approved':{'feishu':['owner']}}))
            (workspace/'triggers/triggers.json').write_text(json.dumps({'triggers':[
                {'enabled':True,'channel':'feishu','chatId':'private'}]}))
            with patch.object(Path,'home',return_value=root), patch.dict(web.os.environ,{'STOCK_ASSISTANT_BRIDGE_CONFIG':str(cfg)}):
                self.assertEqual(web.bind_feishu(),{'bound':True})
                bound=json.loads(cfg.read_text())
                self.assertEqual(bound['secret'],'keep')
                self.assertEqual(bound['web_client_id'],'keep-client')
                self.assertEqual(cfg.stat().st_mode & 0o777,0o600)
                (home/'pairing.json').write_text(json.dumps({'approved':{'feishu':['different']}}))
                self.assertFalse(web.bind_feishu()['bound'])
                self.assertEqual(json.loads(cfg.read_text())['sender_ids'],['owner'])
                (home/'pairing.json').write_text(json.dumps({'approved':{'feishu':['owner','different']}}))
                self.assertFalse(web.bind_feishu()['bound'])
