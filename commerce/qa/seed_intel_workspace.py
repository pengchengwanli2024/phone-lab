"""Seed one isolated QA database, using fixed synthetic feeds only."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


def earthquakes(count, start=0, title='Synthetic earthquake near Mexico'):
    return json.dumps({'type':'FeatureCollection','features':[
        {'id':'synthetic-'+str(i),'properties':{'title':title+' '+str(i),'url':'https://example.org/quake/'+str(i),'time':(1700000000+i)*1000},'geometry':{'coordinates':[-99+i*.015,19+i*.01]}}
        for i in range(start,start+count)
    ]}).encode()


def seed(folder):
    app=Commerce(folder)
    def collect(source,data,stamp):
        with patch('intelligence.fetch',return_value=data),patch('intelligence.time.time',return_value=stamp):
            app.intelligence.refresh(source)
    collect('usgs',earthquakes(1,900,'Archived synthetic earthquake in Peru'),1700001000)
    collect('usgs',earthquakes(45),1700001200)
    gdacs=b'''<rss xmlns:g="http://www.gdacs.org" xmlns:geo="http://www.georss.org/georss"><channel>
<item><title>Synthetic flood in Mexico</title><link>https://example.org/flood/mexico</link><guid>synthetic-flood-mex</guid><pubDate>Tue, 14 Nov 2023 22:13:20 GMT</pubDate><g:country>Mexico</g:country><g:iso3>MEX</g:iso3><g:alertlevel>Orange</g:alertlevel><geo:point>19 -99</geo:point></item>
<item><title>Synthetic cyclone in Russia</title><link>https://example.org/cyclone/russia</link><guid>synthetic-cyclone-rus</guid><pubDate>Tue, 14 Nov 2023 22:13:20 GMT</pubDate><g:country>Russia</g:country><g:iso3>RUS</g:iso3><geo:point>60 150</geo:point></item>
</channel></rss>'''
    collect('gdacs',gdacs,1700001200)
    collect('wto',b'<rss><channel><item><title>Synthetic tariff bulletin</title><link>https://example.org/trade</link><guid>synthetic-trade</guid><pubDate>Tue, 14 Nov 2023 22:14:20 GMT</pubDate></item></channel></rss>',1700001200)
    from article_binding import bind,text_hash
    import time
    item=next(row for row in app.intelligence.store.rows('archive') if row['source']=='wto')
    text='Synthetic article body 25 USD. <script>not executable</script>'
    article=bind(dict(text=text,content_sha256=text_hash(text),source_url=item['url'],record_sha256=item['record_sha256'],captured_at='2026-01-01T00:00:00Z',routes=['synthetic-a','synthetic-b']),dict(zh='合成文章 25 USD。',original_sha256=text_hash(text),zh_sha256=text_hash('合成文章 25 USD。')))
    doc=dict(id='a'*32,item_id=item['id'],record_sha256=item['record_sha256'],status='ready',source='wto',url=item['url'],created_at=time.time(),error=None,translation_status='pending_review',article=article)
    with app.core.db() as db:db.execute('INSERT OR REPLACE INTO intel_articles VALUES (?,?,?,?,?)',(doc['id'],'synthetic-article',item['id'],item['record_sha256'],json.dumps(doc)))
    from collection_jobs import save
    from collection_state import evolve
    job=app.collections.request('federal-reserve-press','synthetic-ui-failure')
    job=evolve(evolve(job,'start',time.time(),attempt=1),'finish_error',time.time(),attempt=1,error='collection_source_check_failed')
    with app.core.db() as db:save(db,job);app.collections.alert(db,job)
    return app


if __name__=='__main__':
    seed(sys.argv[1])
