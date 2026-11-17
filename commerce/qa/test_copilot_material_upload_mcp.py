"""Actual three-client MCP/HTTP chunk receipts, isolated local bytes only."""
import base64,hashlib,unittest
import test_paos_mcp as transport
from test_copilot_transport import CopilotTransport

class UploadMCP(unittest.TestCase):
    setUpClass=classmethod(CopilotTransport.setUpClass.__func__)
    tearDownClass=classmethod(CopilotTransport.tearDownClass.__func__)
    start_server=classmethod(CopilotTransport.start_server.__func__)
    stop_server=classmethod(CopilotTransport.stop_server.__func__)
    http=classmethod(CopilotTransport.http.__func__)
    call=classmethod(CopilotTransport.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc
    def test_original_upload_is_shared_between_codex_hermes_and_harness(self):
        thread=self.call('commerce_copilot_open',dict(context={'module':'overview','demo':True},idempotency_key='mcp-synthetic-material'))
        bound=dict(thread_id=thread['id'],context_sha256=thread['context_sha256']);content=('合成跨客户端本机附件。\n'*6000).encode();upload=None;item=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client)as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('capabilities','preflight'):self.assertTrue(tools['commerce_copilot_material_'+name]['annotations']['readOnlyHint'])
                for name in ('upload_begin','upload_chunk','upload_finish','upload_cancel'):
                    self.assertFalse(tools['commerce_copilot_material_'+name]['annotations']['readOnlyHint']);self.assertFalse(tools['commerce_copilot_material_'+name]['annotations']['openWorldHint'])
                def call(op,args):
                    result=self.rpc(process,'tools/call',{'name':'commerce_copilot_material_'+op,'arguments':args})['result'];self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
                if client=='codex':
                    upload=call('upload_begin',dict(**bound,filename='synthetic-reference.txt',mime_type='text/plain',size_bytes=len(content),content_sha256=hashlib.sha256(content).hexdigest(),idempotency_key='mcp-shared-upload'))
                elif client=='hermes':
                    for i,start in enumerate(range(0,len(content),upload['chunk_bytes'])):call('upload_chunk',dict(**bound,upload_id=upload['id'],index=i,content_base64=base64.b64encode(content[start:start+upload['chunk_bytes']]).decode()))
                else:
                    item=call('upload_finish',dict(**bound,upload_id=upload['id']));self.assertEqual(call('get',dict(thread_id=thread['id'],material_id=item['id']))['sha256'],hashlib.sha256(content).hexdigest());self.assertFalse(item['visual_understanding'])
        self.assertEqual(len(self.call('commerce_copilot_material_list',{'thread_id':thread['id']})['items']),1)
        self.assertEqual(self.call('commerce_copilot_get',{'thread_id':thread['id']})['total_turns'],0)
        self.assertEqual(self.call('commerce_task_list')['tasks'],[])

if __name__=='__main__':unittest.main()
