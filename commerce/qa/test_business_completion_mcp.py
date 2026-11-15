"""Actual stdio MCP reads/writes share one isolated product workspace."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import test_paos_mcp as transport

ROOT=Path(__file__).resolve().parents[1]


class BusinessMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name)
        cls.token='synthetic-business-completion-only'
        (cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_product_workspace.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                rows=cls.call('commerce_workspace_list',{})['items']
                if rows:cls.cid=rows[0]['id'];break
            except (OSError,ValueError):pass
            time.sleep(.05)
        else:raise AssertionError('isolated workspace MCP fixture unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_three_clients_discover_and_share_the_same_versioned_quote_and_read_conditions(self):
        before=len(self.call('commerce_task_list',{})['tasks']);quote_sha=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_workspace_quotes','commerce_workspace_quote_compare','commerce_workspace_delivery_get','commerce_workspace_delivery_export','commerce_skills_readiness'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_workspace_quote_save']['annotations']['readOnlyHint'])
                def call(name,args):
                    result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result']
                    self.assertFalse(result.get('isError'),str(result))
                    return result['structuredContent']
                if quote_sha is None:
                    source=self.call('commerce_workspace_get',{'case_id':self.cid})['source_sha256']
                    saved=call('commerce_workspace_quote_save',dict(case_id=self.cid,quote_id='shared-mcp-quote',payload={'supplier':'Synthetic MCP supplier'},expected_revision=0,expected_source_sha256=source,idempotency_key='shared-quote'))
                    quote_sha=saved['sha256']
                quotes=call('commerce_workspace_quotes',{'case_id':self.cid})
                self.assertEqual(quotes['items'][0]['sha256'],quote_sha)
                comparison=call('commerce_workspace_quote_compare',{'case_id':self.cid,'quantity':13})
                self.assertEqual(comparison['items'][0]['sha256'],quote_sha)
                self.assertIsNone(comparison['items'][0]['goods_subtotal'])
                self.assertFalse(comparison['external_execution_allowed'])
                review=call('commerce_workspace_delivery_get',{'case_id':self.cid})
                self.assertFalse(review['external_execution_allowed'])
                readiness=call('commerce_skills_readiness',{'skill_id':'sealeap-tiktokshop-unit-economics','input':{}})
                self.assertFalse(readiness['offline_check']['can_request'])
                self.assertFalse(readiness['external_execution']['available'])
                denied=self.rpc(process,'tools/call',{'name':'commerce_workspace_quotes','arguments':{'case_id':'another-case'}})['result']
                self.assertTrue(denied['isError'])
        self.assertEqual(len(self.call('commerce_task_list',{})['tasks']),before)


if __name__=='__main__':unittest.main()
