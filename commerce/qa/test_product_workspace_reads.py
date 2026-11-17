"""Product picker reads stay bounded as cases grow, retaining exact source scope."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from product_workspace import ProductWorkspace


class ProductPickerReads(unittest.TestCase):
    def fixture(self, count=55):
        cases = [{'id':f'case-{i}', 'scope':{'platform':'ozon','market':'RU',
                  'synthetic':i%2 == 0,'sku':f'SKU-{i}'}} for i in range(count)]
        documents = {}
        for case in cases:
            ident=case['id']
            documents[ident]={'fresh':True,'document':{'origin_ref':'private-export:ozon-'+ident,
                'records':[{'key':'title','value':'产品 '+ident}]}}
        calls=[]
        def listing(synthetic):
            calls.append(synthetic)
            return {'sources':[{'id':c['id'],'kind':'facts','scope':{
                'subject_ref':c['id'],'platform':'ozon'}} for c in cases
                if c['scope']['synthetic'] is synthetic], 'drafts':[]}
        workspace=ProductWorkspace.__new__(ProductWorkspace)
        workspace.org=SimpleNamespace(cases=lambda:deepcopy(cases))
        workspace.service=SimpleNamespace(business=SimpleNamespace(listing=listing,
            source=Mock(side_effect=lambda ident:deepcopy(documents[ident]))))
        return workspace,cases,documents,calls

    def test_picker_does_not_rescan_all_business_sources_for_every_product(self):
        workspace,cases,_,calls=self.fixture()
        result=workspace.listing()
        self.assertEqual([r['id'] for r in result['items']],[c['id'] for c in cases])
        self.assertEqual([r['name'] for r in result['items']],['产品 '+c['id'] for c in cases])
        self.assertFalse(result['external_execution_allowed'])
        self.assertLessEqual(len(calls),2,'Read each real/synthetic source list once per request, not once per case')
        self.assertEqual(set(calls),{False,True})

    def test_labels_keep_explicit_names_fallbacks_and_current_product_scope(self):
        workspace,cases,docs,calls=self.fixture(6)
        cases[0]['scope']['label']='明确商品名'
        docs['case-1']['fresh']=False
        docs['case-2']['document']['origin_ref']='private-export:ozon-case-4'
        docs['case-3']['document']['records'][0]['value']=' '
        original=workspace.service.business.listing
        def listing(mode):
            result=original(mode)
            result['sources'].insert(0,{'id':'foreign','kind':'facts','scope':{'subject_ref':'case-4','platform':'amazon'}})
            result['sources'].insert(0,{'id':'wrong-kind','kind':'reviews','scope':{'subject_ref':'case-5','platform':'ozon'}})
            return result
        workspace.service.business.listing=listing
        result=workspace.listing()
        self.assertEqual([r['name']for r in result['items']],['明确商品名','SKU-1','SKU-2','SKU-3','产品 case-4','产品 case-5'])
        self.assertNotIn('case-0',[c.args[0]for c in workspace.service.business.source.call_args_list])
        self.assertLessEqual(len(calls),2)
        # Request-local reuse must not conceal a later source revision.
        docs['case-4']['document']['records'][0]['value']='新商品标题'
        self.assertEqual(workspace.listing()['items'][4]['name'],'新商品标题')

    def test_named_or_empty_picker_does_not_read_unneeded_business_sources(self):
        workspace,cases,_,calls=self.fixture(3)
        for case in cases:case['scope']['label']='指定 '+case['id']
        self.assertEqual(len(workspace.listing()['items']),3)
        self.assertEqual(calls,[])
        workspace.org.cases=lambda:[]
        self.assertEqual(workspace.listing()['items'],[])
        self.assertEqual(calls,[])


class CatalogReads(unittest.TestCase):
    def setUp(self):
        import test_organization as fixtures
        self.fixture=fixtures.OrganizationTests();self.fixture.setUp()
        self.app=self.fixture.app
        with self.app.core.db()as db:
            connection=db.execute('SELECT connection FROM org_cases WHERE id=?',(self.fixture.cid,)).fetchone()[0]
            scope=self.app.organization.case(self.fixture.cid)['scope']
            for i in range(8):
                value={**scope,'sku':'READ-'+str(i),'synthetic':i%2==0}
                db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',
                    ('read-'+str(i),connection,'read-'+str(i),json.dumps(value),None,'2026-01-01T00:00:00+00:00'))

    def tearDown(self):self.fixture.tearDown()

    def test_catalog_matches_individual_current_details_without_repeated_full_source_scans(self):
        before=self.app.catalog.listing()
        with patch.object(self.app.business,'listing',wraps=self.app.business.listing)as scans:
            after=self.app.catalog.listing()
        self.assertEqual(after,before)
        self.assertLessEqual(scans.call_count,2,'One source scan per real/synthetic scope for the whole catalog')
        for item in after['items']:
            detail=self.app.catalog.get(item['id'])
            for key,value in item.items():
                if key in detail:self.assertEqual(value,detail[key],key)
            self.assertEqual(item['supplier_count'],len(detail['suppliers']))
        with self.assertRaisesRegex(ValueError,'invalid_arguments'):
            self.app.invoke('commerce_catalog_get',{'case_id':self.fixture.cid,'_fact_sources':[]})


if __name__=='__main__':unittest.main()
