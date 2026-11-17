"""Isolated UI acceptance over real local ledgers and a labelled synthetic model."""
from pathlib import Path
import base64,json,os,sys,time
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):raise SystemExit('Isolated state and port required')
import server
from test_owner_review import OwnerReviewTests
from agent_runtime import model
from generative.streaming import emit

fixture=OwnerReviewTests();fixture.setUp();app=fixture.app
fields=dict(supplier='合成供应方 A',currency='CNY',purchase_cost=30,lead_time_days=14,moq=20,
    source_ref='synthetic:quotation',valid_until=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
    packaging=dict(length_cm=20,width_cm=10,height_cm=5,weight_kg=.4,units_per_pack=1))
for index,price in enumerate((30,32)):
    fields={**fields,'supplier':'合成供应方 '+str(index+1),'purchase_cost':price}
    app.product_workspace.supply.save(fixture.cid,'synthetic-'+str(index),fields,0,app.product_workspace.sources(fixture.cid)[3],'synthetic-quote-'+str(index))
# Quotations change product evidence. Refresh the original listing's source binding.
plan=app.listings.get(**fixture.target)
app.listings.save(**fixture.target,payload=plan['payload'],expected_revision=plan['revision'],expected_source_sha256=plan['source_sha256'])
png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')
image_patch=patch('catalog_media.fetch',return_value=png);image_patch.start()

def fake_model(payload,cancelled,**kwargs):
    question=payload['question'];observations=payload.get('observations',[])
    business=[o for o in observations if o['tool'] in ('commerce_listing_get','commerce_workspace_get','commerce_workspace_quote_compare')]
    if not business:
        calls=([{'tool':'commerce_listing_get','arguments':fixture.target}] if '上架' in question else
            [{'tool':'commerce_workspace_get','arguments':{'case_id':fixture.cid}},
             {'tool':'commerce_workspace_quote_compare','arguments':{'case_id':fixture.cid,'quantity':10}}])
        decision={'phase':'inspect','calls':calls}
    else:
        listing='上架' in question
        refs={o['tool']:o['id']for o in business}
        ui=([{'component':'ListingReview','reference':refs['commerce_listing_get']}] if listing else
            [{'component':'QuoteComparison','reference':refs['commerce_workspace_quote_compare']},{'component':'DeliveryReview','reference':refs['commerce_workspace_get']},{'component':'CostSummary','reference':refs['commerce_workspace_get']}])
        decision={'phase':'answer','answer':'合成验收：已读取当前资料，请按卡片核对版本。缺失资料继续保留待补充状态。'*8,
            'questions':[],'evidence_refs':[o['id']for o in observations],'proposals':[],'ui':ui}
        limited='限量' in question
        if limited:decision['answer']*=3
        encoded=json.dumps(decision,ensure_ascii=False)
        width=1 if limited else 35
        for start in range(0,len(encoded),width):
            if cancelled():raise model.Cancelled()
            emit(encoded[start:start+width]);time.sleep(.001 if limited else .13)
        if limited:time.sleep(1)
        if '中断' in question:raise ValueError('agent_provider_outcome_unknown')
    return {'decision':decision,'provider':'synthetic-labelled-ui-test','model':'no-network-no-charge'}

model.invoke=fake_model
server.Handler.secret='synthetic-generative-preview';server.Handler.service=app
(server.STATE/'auth.token').write_text(server.Handler.secret)
root=Path(__file__).resolve().parents[1]
context=dict(module='organization',demo=False,platform='ozon',store_id='ozon-live',market='RU',entity={'kind':'case','id':fixture.cid})
page='''<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/generative-resource/style.css"><link rel="stylesheet" href="/generative-resource/copilot-ui.css"><style>body{margin:0;padding:16px;background:var(--ui-bg);color:var(--ui-text)}#host{height:850px;max-width:540px;margin:auto}.copilot-shell{height:850px!important}.copilot-generative-card{min-width:0;overflow-wrap:anywhere}.copilot-generative-card dl div{display:block}#synthetic{max-width:540px;margin:0 auto 12px}</style><p id="synthetic">合成生成式验收 · 隔离数据 / 无模型费用 / 无店铺写入</p><div id="opened" role="status"></div><main id="host"></main><script src="/generative-resource/status.js"></script><script src="/generative-resource/kit.js"></script><script src="/generative-resource/copilot-upload.js"></script><script src="/generative-resource/copilot-reading.js"></script><script src="/generative-resource/copilot-events.js"></script><script src="/generative-resource/copilot-evidence.js"></script><script src="/generative-resource/copilot-interactions.js"></script><script src="/generative-resource/generative-ui.js"></script><script src="/generative-resource/copilot-capabilities.js"></script><script src="/generative-resource/copilot-ui.js"></script><script>
const host=document.getElementById('host');const api=async(tool,args={})=>{const r=await fetch('/v1/invoke',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({tool,arguments:args,client:'browser'})});const data=await r.json();if(!r.ok)throw Error(data.error);return data};
window.qaContext=CONTEXT;window.cp=CommerceCopilot({api,inline:true,compact:true,getContext:()=>window.qaContext,repaint:()=>{host.innerHTML=cp.view();cp.afterPaint()},onOpenCandidate:id=>{document.getElementById('opened').textContent='已导航到准确商品 '+id},toast:()=>{}});cp.open();</script></html>'''.replace('CONTEXT',json.dumps(context,ensure_ascii=False))
original_get=server.Handler.do_GET
def get(handler):
    if handler.path=='/generative-test':return handler.answer(200,page,typ='text/html; charset=utf-8')
    if handler.path.startswith('/generative-resource/'):
        name=handler.path.rsplit('/',1)[-1]
        allowed={'status.js':root/'ui/status.js','kit.js':root/'ui/kit.js',**{n:root/'web'/n for n in ('style.css','copilot-ui.css','copilot-upload.js','copilot-reading.js','copilot-events.js','copilot-evidence.js','copilot-interactions.js','generative-ui.js','copilot-capabilities.js','copilot-ui.js')}}
        if name in allowed:return handler.answer(200,allowed[name].read_text(),typ='text/css' if name.endswith('.css') else 'text/javascript')
    if handler.path=='/harness-open':
        descriptor=server.STATE/'native-host.json'
        if descriptor.is_file():return handler.answer(303,'',headers={'Location':json.loads(descriptor.read_text())['url']})
    return original_get(handler)
server.Handler.do_GET=get
app.agent_runtime.start()
print('Isolated generative fixture ready',flush=True)
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:app.agent_runtime.stop();image_patch.stop();fixture.tearDown()
