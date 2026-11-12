"""Client fallback links retain exact object scope and existing authentication."""
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from response_links import with_workspace_link


class ResponseLinks(unittest.TestCase):
    def test_bound_surface_links_to_same_product_without_credentials_or_protocol_mutation(self):
        result={'surface_id':'cost_'+'a'*32,'binding':{'case_id':'existing-case'},'text':'Current saved cost','messages':[{'version':'1.0'}],'fallback':'standard_cost_form'}
        decorated=with_workspace_link('commerce_a2ui_get',result,51234)
        url=decorated['links']['workspace']['url']
        self.assertEqual(parse_qs(urlsplit(url).query),{'tab':['operations'],'case_id':['existing-case']})
        self.assertEqual(urlsplit(url).netloc,'127.0.0.1:51234')
        self.assertTrue(decorated['links']['workspace']['requires_authentication'])
        self.assertEqual(decorated['messages'],result['messages'])
        self.assertEqual(decorated['fallback'],result['fallback'])
        self.assertNotIn('links',result)
        self.assertNotIn('token',url)
        self.assertIn(url,decorated['text'])

    def test_unbound_surface_restores_same_surface_and_other_tools_are_unchanged(self):
        result={'surface_id':'cost_'+'b'*32,'text':'Cost input'}
        decorated=with_workspace_link('commerce_a2ui_create',result,51235)
        self.assertEqual(parse_qs(urlsplit(decorated['links']['workspace']['url']).query)['surface'],[result['surface_id']])
        self.assertIs(with_workspace_link('commerce_task_get',result,51235),result)
        status={'enabled':True}
        self.assertIs(with_workspace_link('commerce_a2ui_status',status,51235),status)


if __name__=='__main__':unittest.main()
