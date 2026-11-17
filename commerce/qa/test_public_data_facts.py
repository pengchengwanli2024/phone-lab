"""Official JSON fact projections preserve units, nulls and explicit time zones."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from public_data_facts import official_facts

URL='https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1'

def event():
    return {'type':'Feature','id':'qa-event','properties':{'place':'62.3 km S of Test Island','mag':2.0,'magType':'ml',
        'time':1794828720000,'status':'automatic','alert':None,'tsunami':0},
        'geometry':{'type':'Point','coordinates':[124.5,1.2,5.0]}}

class OfficialFacts(unittest.TestCase):
    def test_units_and_beijing_conversion_come_from_fields_not_place_distance(self):
        value=official_facts(URL,event());item=value['items'][0]
        self.assertEqual(value['schema'],'usgs-earthquake-v1')
        self.assertEqual(item['magnitude'],2.0);self.assertEqual(item['depth_km'],5.0)
        self.assertEqual(item['occurred_utc'],'2026-11-16 11:32:00 UTC')
        self.assertEqual(item['occurred_beijing'],'2026-11-16 19:32:00 +08:00')
        self.assertFalse(item['utc_to_beijing_date_changed'])
        self.assertEqual(item['review_status'],'automatic')
        self.assertEqual(item['tsunami_flag'],0);self.assertIsNone(item['alert'])
        self.assertIn('62.3',item['place'])

    def test_cross_day_conversion_is_independent_of_host_timezone(self):
        value=event();value['properties']['time']=1794846600000
        item=official_facts(URL,value)['items'][0]
        self.assertEqual(item['occurred_utc'],'2026-11-16 16:30:00 UTC')
        self.assertEqual(item['occurred_beijing'],'2026-11-17 00:30:00 +08:00')
        self.assertTrue(item['utc_to_beijing_date_changed'])

    def test_missing_invalid_and_zero_are_not_conflated(self):
        for bad in [None,True,'2.0',float('inf'),float('nan'),10**500]:
            value=event();value['properties']['mag']=bad;value['properties']['time']=bad
            value['geometry']['coordinates']=[124.5,1.2]
            item=official_facts(URL,value)['items'][0]
            self.assertIsNone(item['magnitude']);self.assertIsNone(item['depth_km']);self.assertIsNone(item['occurred_beijing'])
            self.assertIsNone(item['utc_to_beijing_date_changed'])
        value=event();value['properties']['mag']=0;value['properties']['time']=0
        value['geometry']['coordinates'][2]=-1.5
        item=official_facts(URL,value)['items'][0]
        self.assertEqual(item['magnitude'],0);self.assertEqual(item['depth_km'],-1.5)
        self.assertEqual(item['occurred_beijing'],'1970-01-01 08:00:00 +08:00')
        value['properties']['time']=1e30
        self.assertIsNone(official_facts(URL,value)['items'][0]['occurred_utc'])

    def test_collection_is_bounded_without_claiming_every_record_was_read(self):
        data={'type':'FeatureCollection','features':[event() for _ in range(8)]}
        value=official_facts(URL,data)
        self.assertEqual(len(value['items']),3);self.assertEqual(value['records_returned'],8)
        self.assertTrue(value['truncated'])
        self.assertEqual(official_facts(URL,{'type':'FeatureCollection','features':[]})['items'],[])

    def test_projection_requires_exact_official_host_and_recognized_geojson_shape(self):
        for url in ['https://earthquake.usgs.gov.evil.test/fdsnws/event/1/query',
                    'https://example.com/fdsnws/event/1/query',
                    'http://earthquake.usgs.gov/fdsnws/event/1/query',
                    'https://earthquake.usgs.gov/unrelated']:
            self.assertIsNone(official_facts(url,event()))
        for data in [None,[],{}, {'type':'Feature','properties':None}, {'type':'FeatureCollection','features':'bad'}]:
            self.assertIsNone(official_facts(URL,data))
        self.assertIsNotNone(official_facts('https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/qa.geojson',event()))

    def test_source_data_is_not_mutated_or_promoted_to_independent_verification(self):
        data=event();before=copy.deepcopy(data)
        data['properties']['status']='unknown-script';data['properties']['alert']='invented'
        value=official_facts(URL,data)
        self.assertIsNone(value['items'][0]['review_status']);self.assertIsNone(value['items'][0]['alert'])
        self.assertEqual(before['geometry'],data['geometry'])
        self.assertNotIn('independently_verified',value)

if __name__=='__main__':unittest.main()
