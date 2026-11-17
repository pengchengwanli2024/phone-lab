"""Exact product cards over temporary store inventory; no real accounts or I/O."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from research import canonical
from test_live_connections import batch


class CatalogStoreIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.app.ozon_accounts.configure(dict(ozon_client_id='111111',ozon_api_key='synthetic-catalog-account-A',store_label='Test shop A',fulfillment_modes=['OGL']))
        self.stock=self.inventory();self.publish(self.stock)

    def tearDown(self):
        self.app.catalog_sync.stop();self.app.agent_runtime.stop();self.app.autonomy.stop();self.temp.cleanup()

    @staticmethod
    def inventory():
        result=batch('stock');template=result['records'][0];result['records']=[]
        for index in range(8):
            row=deepcopy(template);row['product_id']=str(index+100)
            row['offer_id']='SAME-SKU'if index<2 else'PRODUCT-'+str(index)
            row['stocks']=[dict(row['stocks'][0],type=kind,sku=str(1000+index))for kind in (['fbs','rfbs','fbo']if index==0 else['fbs','rfbs'])]
            result['records'].append(row)
        return result

    def publish(self,stock):
        config=self.app.live.config();self.app.live._publish(config['connection_id'],'stock',stock,config,False)
        self.app.organization.import_inventory()

    def cases(self):return self.app.organization.cases()

    def clone(self,case,**updates):
        ident=uuid.uuid4().hex;scope=deepcopy(case['scope']);scope.update(updates)
        config=self.app.live.config();rowkey=ident
        scope['row_key']=rowkey
        with self.app.core.db()as db:db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',(ident,config['connection_id'],rowkey,canonical(scope),None,'2026-01-01T00:00:00+00:00'))
        return ident

    def candidate(self):
        ident=uuid.uuid4().hex;scope=dict(platform='ozon',market='RU',sku='SAME-SKU',label='Same title',
            origin='research_candidate_not_inventory',research_task_id='synthetic-research',row_key=ident)
        with self.app.core.db()as db:db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',(ident,'',ident,canonical(scope),None,'2026-01-01T00:00:00+00:00'))
        return ident

    def test_seventeen_fulfillment_cases_form_eight_product_cards(self):
        self.assertEqual(len(self.cases()),17)
        cards=self.app.catalog.listing()['items']
        self.assertEqual(len(cards),8,'Distinct stock scope cases must project to one card per store product')
        first=next(r for r in cards if r['product_id']=='100')
        self.assertEqual(len(first['case_ids']),3)
        self.assertEqual({r['inventory_type']for r in first['source_scopes']},{'fbs','rfbs','fbo'})
        self.assertEqual(len(self.cases()),17,'Projection never deletes or merges original cases')

    def test_every_original_case_remains_exactly_addressable(self):
        before={r['id']:r for r in self.cases()}
        for ident,case in before.items():
            detail=self.app.catalog.get(ident)
            self.assertEqual(detail['id'],ident)
            self.assertEqual(detail['case']['scope'],case['scope'])
            self.assertEqual(detail['product_id'],case['scope']['product_id'])
            self.assertIn(ident,detail['case_ids'])
            self.assertEqual(detail['store_identity']['label'],'Test shop A')
            self.assertEqual(detail['store_identity']['connection_id'],self.app.live.config()['connection_id'])

    def test_same_sku_different_product_ids_do_not_merge(self):
        matches=[r for r in self.app.catalog.listing()['items']if r['sku']=='SAME-SKU']
        self.assertEqual(len(matches),2)
        self.assertEqual({r['product_id']for r in matches},{'100','101'})
        self.assertNotEqual(matches[0]['product_key'],matches[1]['product_key'])

    def test_account_switch_excludes_old_cases_and_uses_new_store_identity(self):
        old=self.app.catalog.listing()['items'];old_case=old[0]['id'];old_keys={r['product_key']for r in old}
        self.app.ozon_accounts.configure(dict(ozon_client_id='222222',ozon_api_key='synthetic-catalog-account-B',store_label='Test shop B',fulfillment_modes=['OGL']))
        self.assertEqual(self.app.catalog.listing()['items'],[])
        self.publish(self.stock);new=self.app.catalog.listing()['items']
        self.assertEqual(len(new),8)
        self.assertTrue(all(r['store_identity']['label']=='Test shop B'for r in new))
        self.assertFalse(old_keys&{r['product_key']for r in new})
        self.assertNotEqual(old[0]['store_identity']['account_id'],new[0]['store_identity']['account_id'])
        with self.assertRaisesRegex(ValueError,'case_not_found'):self.app.catalog.get(old_case)

    def test_research_candidates_remain_separate_without_assigned_store(self):
        one=self.candidate();two=self.candidate();cards=self.app.catalog.listing()['items']
        candidates=[r for r in cards if r['kind']=='candidate'];self.assertEqual(len(candidates),2)
        self.assertEqual({r['id']for r in candidates},{one,two})
        for card in candidates:
            identity=card['store_identity'];self.assertEqual(identity['kind'],'research_candidate')
            self.assertIsNone(identity['account_id']);self.assertIsNone(identity['connection_id'])
            self.assertIsNone(identity['label']);self.assertEqual(card['case_ids'],[card['id']])

    def test_matching_other_scope_keeps_all_product_scope_references(self):
        matches=self.app.catalog.listing(query='fbo')['items'];self.assertEqual(len(matches),1)
        self.assertEqual(len(matches[0]['case_ids']),3)
        self.assertEqual(len(matches[0]['inventory_scopes']),3)

    def test_platform_and_market_are_part_of_identity(self):
        case=self.cases()[0];self.clone(case,platform='amazon');self.clone(case,market='KZ')
        cards=self.app.catalog.listing()['items'];self.assertEqual(len(cards),10)
        foreign=next(r for r in cards if r['platform']=='amazon')
        self.assertIsNone(foreign['store_identity']['account_id'])
        self.assertIsNone(foreign['store_identity']['label'])

    def test_sku_fallback_groups_only_when_product_id_missing(self):
        case=self.cases()[0]
        one=self.clone(case,product_id=None,sku='FALLBACK-SKU',inventory_type='fbs')
        two=self.clone(case,product_id=None,sku='FALLBACK-SKU',inventory_type='rfbs')
        card=next(r for r in self.app.catalog.listing()['items']if r['sku']=='FALLBACK-SKU')
        self.assertEqual(set(card['case_ids']),{one,two});self.assertIsNone(card['product_id'])

    def test_missing_identifiers_or_same_names_never_merge(self):
        case=self.cases()[0]
        one=self.clone(case,product_id=None,sku=None,label='Identical')
        two=self.clone(case,product_id=None,sku=None,label='Identical')
        cards=[r for r in self.app.catalog.listing()['items']if r['id']in(one,two)]
        self.assertEqual(len(cards),2)

    def test_current_store_account_metadata_contains_no_credentials(self):
        encoded=json.dumps(self.app.catalog.listing())
        for secret in ('111111','synthetic-catalog-account-A','ozon_api_key','ozon_client_id'):
            self.assertNotIn(secret,encoded)
        safe=self.app.ozon_accounts.listing()
        identities=[r['store_identity']for r in self.app.catalog.listing()['items']]
        self.assertTrue(all(r['account_id']==safe['active_account_id']for r in identities))

    def test_detail_and_card_share_identity_and_scope_metadata(self):
        for card in self.app.catalog.listing()['items']:
            detail=self.app.catalog.get(card['id'])
            for key in ('sku','product_id','product_key','store_identity','case_ids','source_scopes','inventory_scopes'):
                self.assertEqual(detail[key],card[key],key)


if __name__=='__main__':unittest.main()
