"""Actual three-client stdio/HTTP owner-review contract in an isolated fixture."""
import json,os,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
import test_paos_mcp as transport

ROOT=Path(__file__).resolve().parents[1]
class OwnerReviewMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name);cls.token='synthetic-workbench-preview'
        (cls.state/'auth.token').write_text(cls.token)
        with socket.socket()as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port),'COMMERCE_QA_OWNER_REVIEW':'1'}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/react_workbench_fixture.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(120):
            try:
                cls.target=dict(case_id='b619'*8,platform='ozon',store_ref='ozon-live',market='RU');cls.call('commerce_owner_review_get',cls.target);break
            except (OSError,ValueError):time.sleep(.05)
        else:raise AssertionError('owner-review fixture unavailable')
    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()
    def test_three_clients_share_scoped_local_draft_and_readonly_annotations(self):
        before=self.call('commerce_task_list',{})['tasks'];sha=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client)as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_owner_review_get','commerce_owner_review_image'):self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_owner_review_image']['annotations']['openWorldHint'])
                self.assertFalse(tools['commerce_owner_review_record']['annotations']['readOnlyHint']);self.assertFalse(tools['commerce_owner_review_record']['annotations']['openWorldHint'])
                def call(name,args):
                    result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result'];self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
                view=call('commerce_owner_review_get',self.target)
                if sha is None:
                    view=call('commerce_owner_review_record',dict(**self.target,expected_binding_sha256=view['binding_sha256'],expected_review_sha256='',checks=view['checks'],decision='save',reviewer='Synthetic owner draft',confirmed=False,idempotency_key='mcp-owner-draft'));sha=view['review_sha256']
                self.assertEqual(view['review_sha256'],sha);self.assertFalse(view['current']);self.assertFalse(view['independent_certification']);self.assertFalse(view['external_execution_allowed'])
                image=call('commerce_owner_review_image',dict(**self.target,expected_binding_sha256=view['binding_sha256'],index=0));self.assertEqual(image['mime'],'image/png')
                denied=self.rpc(process,'tools/call',{'name':'commerce_owner_review_get','arguments':{**self.target,'case_id':'another-case'}})['result'];self.assertTrue(denied['isError'])
        self.assertEqual(self.call('commerce_task_list',{})['tasks'],before)
