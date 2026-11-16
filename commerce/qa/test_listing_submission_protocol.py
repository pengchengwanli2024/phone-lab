"""Single-item import requests retain actual units, explicit tax and original attributes."""
import copy,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
from listing_submission_protocol import publication_issues,materialize,project_before

PAYLOAD=dict(fields=dict(sku='SYN-PUBLISH',title='Synthetic product',description='Synthetic description',category_id='10',price='100.00',currency='CNY',quantity=1,image_refs=['https://example.com/synthetic.png']),ozon=dict(type_id=20,attributes=[dict(id=8229,values=[dict(dictionary_value_id=20,value='Synthetic type')],source_ref='synthetic:type'),dict(id=4191,values=[dict(dictionary_value_id=0,value='Synthetic description')],source_ref='synthetic:description')],publication=dict(depth=100,width=80,height=50,dimension_unit='mm',weight=200,weight_unit='g',vat='0.22',source_ref='synthetic:package',vat_source_ref='synthetic:tax',description_attribute_id=4191)))
SCHEMA=[dict(id=8229,dictionary_id=1,complex_id=0,type='String'),dict(id=4191,dictionary_id=0,complex_id=0,type='String')]
class SubmissionProtocol(unittest.TestCase):
 def test_missing_and_zero_values_are_not_defaulted_or_converted(self):
  p=copy.deepcopy(PAYLOAD);p['ozon'].pop('publication');self.assertIn('publication',publication_issues(p,SCHEMA));self.assertEqual(p['fields']['quantity'],1)
  for k in ('depth','width','height','weight'):
   p=copy.deepcopy(PAYLOAD);p['ozon']['publication'][k]=0;self.assertIn(k,publication_issues(p,SCHEMA))
 def test_body_uses_declared_units_exact_values_and_no_inventory_write(self):
  body=materialize(PAYLOAD,SCHEMA,dict(kind='new',attributes=[]));item=body['items'][0]
  self.assertEqual(item['depth'],100);self.assertEqual(item['vat'],'0.22');self.assertEqual(item['currency_code'],'CNY')
  self.assertNotIn('quantity',item);self.assertNotIn('source_ref',str(body));self.assertEqual(item['offer_id'],'SYN-PUBLISH')
 def test_description_type_and_image_bounds_are_required(self):
  for key,value,issue in [('description_attribute_id',0,'description_attribute'),('vat','','vat'),('vat_source_ref','','vat_source_ref')]:
   p=copy.deepcopy(PAYLOAD);p['ozon']['publication'][key]=value;self.assertIn(issue,publication_issues(p,SCHEMA))
  p=copy.deepcopy(PAYLOAD);p['fields']['image_refs']*=11;self.assertIn('images',publication_issues(p,SCHEMA))
  p=copy.deepcopy(PAYLOAD);p['ozon']['attributes'][0]['values'][0]['dictionary_value_id']=21;self.assertIn('type_attribute',publication_issues(p,SCHEMA))
 def test_existing_attributes_are_preserved_and_category_or_special_media_refused(self):
  before=dict(kind='existing',product_id='9',sku='SYN-PUBLISH',category_id=10,type_id=20,attributes=[dict(id=999,complex_id=0,values=[dict(dictionary_value_id=0,value='Original optional attribute')])],barcode='SYN-BAR',special_media=False)
  item=materialize(PAYLOAD,SCHEMA,before)['items'][0];self.assertTrue(any(r['id']==999 for r in item['attributes']));self.assertEqual(item['barcode'],'SYN-BAR')
  for change in ({'category_id':11},{'type_id':21},{'special_media':True}):
   with self.assertRaises(ValueError):materialize(PAYLOAD,SCHEMA,{**before,**change})
 def test_remote_identity_is_exact_and_complex_attributes_never_dropped(self):
  raw=dict(items=[dict(id=9,offer_id='SYN-PUBLISH',name='Original',price='90',currency_code='CNY',images=[],images360=[],color_image='')])
  attrs=dict(result=[dict(id=9,offer_id='SYN-PUBLISH',description_category_id=10,type_id=20,barcode='SYN-BAR',attributes=[dict(attribute_id=999,complex_id=0,values=[dict(dictionary_value_id=0,value='Original')])],complex_attributes=[])])
  self.assertEqual(project_before(raw,attrs,'SYN-PUBLISH','9')['attributes'][0]['id'],999)
  attrs['result'][0]['complex_attributes']=[dict(attributes=[])]
  with self.assertRaisesRegex(ValueError,'complex'):project_before(raw,attrs,'SYN-PUBLISH','9')
  with self.assertRaises(ValueError):project_before(raw,attrs,'SYN-PUBLISH','8')
