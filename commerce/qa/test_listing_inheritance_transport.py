"""Real HTTP and Codex/Hermes/Harness stdio calls share inherited store plans."""
import copy,json,unittest
import test_listing_transport as fixtures

class ListingInheritanceTransport(unittest.TestCase):
 call=classmethod(fixtures.ListingTransport.call.__func__)
 mcp=fixtures.ListingTransport.mcp
 rpc=fixtures.ListingTransport.rpc
 setUpClass=classmethod(fixtures.ListingTransport.setUpClass.__func__)
 tearDownClass=classmethod(fixtures.ListingTransport.tearDownClass.__func__)
 def test_three_clients_share_overrides_rebase_and_legacy_save_compatibility(self):
  target=dict(case_id=self.cid,platform='ozon',store_ref='inheritance-mcp-only',market='RU');before=self.call('commerce_task_list',{})['tasks'];prior=None
  for client in ('codex','hermes','harness'):
   with self.subTest(client=client),self.mcp(client)as process:
    tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']};schema=tools['commerce_listing_save']['inputSchema'];self.assertIn('field_overrides',schema['properties']);self.assertIn('expected_base_sha256',schema['properties']);self.assertFalse(tools['commerce_listing_save']['annotations']['readOnlyHint'])
    def call(name,args):
     result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result'];self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
    value=call('commerce_listing_get',target)
    if client=='codex':
     value=call('commerce_listing_save',{**target,'payload':value['payload'],'field_overrides':{'title':'Scoped MCP store title'},'expected_base_sha256':value['base_sha256'],'expected_revision':value['revision'],'expected_source_sha256':value['source_sha256']});self.assertEqual(value['payload']['fields']['title'],'Scoped MCP store title');prior=value
     product=self.call('commerce_workspace_get',{'case_id':self.cid});content=copy.deepcopy(product['forms']['content']['payload']or {'fields':{}});content['fields'].update(title='New MCP base title',description='New inherited MCP description')
     self.call('commerce_workspace_save',{'case_id':self.cid,'form':'content','payload':content,'expected_revision':product['forms']['content']['revision'],'expected_source_sha256':product['source_sha256']})
     failed=self.rpc(process,'tools/call',{'name':'commerce_listing_save','arguments':{**target,'payload':prior['payload'],'field_overrides':prior['field_overrides'],'expected_base_sha256':prior['base_sha256'],'expected_revision':prior['revision'],'expected_source_sha256':prior['source_sha256']}})['result'];self.assertTrue(failed['isError'])
    elif client=='hermes':
     self.assertEqual(value['revision'],1);self.assertTrue(value['stale']);self.assertEqual(value['payload']['fields']['title'],'Scoped MCP store title');self.assertEqual(value['payload']['fields']['description'],'New inherited MCP description')
     value=call('commerce_listing_save',{**target,'payload':value['payload'],'field_overrides':{},'expected_base_sha256':value['base_sha256'],'expected_revision':value['revision'],'expected_source_sha256':value['source_sha256']});self.assertFalse(value['stale']);self.assertEqual(value['payload']['fields']['title'],'New MCP base title');export=call('commerce_listing_export',{**target,'expected_preview_sha256':value['preview_sha256']});self.assertEqual(json.loads(export['content'])['platform_submission'],'not_performed')
    else:
     self.assertEqual(value['revision'],2);payload=copy.deepcopy(value['payload']);payload['fields']['price']='129'
     saved=call('commerce_listing_save',{**target,'payload':payload,'expected_revision':value['revision'],'expected_source_sha256':value['source_sha256']});self.assertEqual(saved['inheritance_mode'],'legacy_explicit');self.assertEqual(saved['payload'],payload);self.assertEqual(saved['field_overrides'],payload['fields'])
  self.assertEqual(self.call('commerce_task_list',{})['tasks'],before)

if __name__=='__main__':unittest.main()
