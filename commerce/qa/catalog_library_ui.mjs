// Isolated real HTTP/Chrome acceptance; never uses the running commerce state.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdtemp,mkdir,readdir,rm,access} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {tmpdir,homedir} from 'node:os';
import path from 'node:path';
import net from 'node:net';

const root=path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));
const out=path.resolve(process.env.QA_OUTPUT_DIR||path.join(root,'.local/agent-team/control/catalog-library-browser'));
const prepare=process.argv.includes('--check-prepare'),finderOnly=process.argv.includes('--finder-race-only');
const work=await mkdtemp(path.join(tmpdir(),'phone-lab-catalog-library-'));
assert.ok(!work.startsWith(path.join(root,'.commerce-state')),'A fresh temporary state is mandatory');
await mkdir(out,{recursive:true,mode:0o700});
const socket=net.createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
const origin='http://127.0.0.1:'+port,TOKEN='synthetic-catalog-library-preview',hash=b=>createHash('sha256').update(b).digest('hex');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));

// Reuse the existing 17-scope/8-product seed, original domain APIs and server.
// The only direct SQL creates clearly synthetic case metadata in this temp DB.
const fixture=String.raw`
import base64,hashlib,json,os,socket,struct,sys,threading,uuid,zlib
from pathlib import Path
from datetime import datetime,timezone
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'commerce'),str(root/'commerce/qa')]
assert os.environ.get('COMMERCE_QA_MODE')=='mock_live'
assert os.environ.get('COMMERCE_STATE')==os.environ.get('COMMERCE_STATE_DIR')
assert os.environ.get('COMMERCE_IGNORE_DOTENV')=='1'
import server
from service import Commerce
from research import canonical,template
from test_catalog_store_identity import CatalogStoreIdentityTests
from agent_runtime import model
app=Commerce(server.STATE)
def denied(*args,**kwargs):raise AssertionError('synthetic_fixture_external_execution_disabled')
model.invoke=denied;app.live.sync=denied
def png(w=320,h=240):
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    pixels=b''.join(b'\0'+bytes([8,97,248])*w for _ in range(h))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
image=png();image_sha=hashlib.sha256(image).hexdigest()
def publish(label,client):
    app.ozon_accounts.configure(dict(ozon_client_id=client,ozon_api_key='synthetic-'+client,store_label=label,fulfillment_modes=['OGL']))
    cfg=app.live.config();app.live._publish(cfg['connection_id'],'stock',CatalogStoreIdentityTests.inventory(),cfg,False)
    cases=app.organization.import_inventory()['cases'];assert len(cases)==17
    with app.core.db()as db:
        for c in cases:
            scope=dict(c['scope'],label=label+' Product '+str(c['scope']['product_id']))
            db.execute('UPDATE org_cases SET scope=?,currency=? WHERE id=?',(canonical(scope),'CNY',c['id']))
    cards=app.catalog.listing(kind='inventory')['items'];assert len(cards)==8
    return cards,app.ozon_accounts.listing()
def register(project,kind,name,data=image,source='synthetic:local-media'):
    p=server.STATE/name;p.write_bytes(data)
    meta=dict(display_name=name,source_ref=source,usage_scope='synthetic_only')
    if p.suffix=='.png':meta['media']=app.creative.probe(p)
    return app.creative.register(project,kind,p,meta)
a,accounts=publish('SYN店铺A','801111');account_a=accounts['active_account_id'];connection_a=app.live.config()['connection_id']
detail=next(r for r in a if r['product_id']=='100');cid=detail['id']
attributes=json.dumps([dict(id=100+i,name='SYN属性'+str(i),values=[dict(value='Русский '+str(i))])for i in range(7)],ensure_ascii=False)
description='<ul><li>SYN俄语套装：12张双面卡</li><li>仅合成验收</li></ul><script>window.__catalogXss=true</script><img src="https://example.invalid/must-not-load" onerror="window.__catalogXss=true">'+('长原文测试。'*150)+'SYN原文末尾'
record=template('ozon')['record'];record.update(market='RU',language='ru',source_url='https://example.invalid/synthetic-catalog',captured_at=datetime.now(timezone.utc).isoformat(),raw_excerpt='Synthetic browser acceptance only')
for key,f in record['fields'].items():f.update(original='',zh='',reviewed=False,locator='synthetic:'+key)
for key,value in dict(title='SYN完整商品信息100',description=description,attributes=attributes,dimensions=json.dumps(dict(depth=250,width=280,height=30,dimension_unit='mm')),weight=json.dumps(dict(weight=230,weight_unit='g'))).items():record['fields'][key]['original']=value
app.organization.record(cid,'research',dict(sku='SAME-SKU',row_key=app.organization.case(cid)['scope']['row_key'],record=record),'synthetic-catalog-research')
p=app.catalog.creative(cid,app.catalog.get(cid)['source_sha256'],'synthetic-catalog-media');pid=p['id']
original=register(pid,'product_image','SYN-A-original.png')
generated=[]
for n in range(21):generated.append(register(pid,'generated_image','SYN-A-approved-generated-%02d.png'%n))
document=register(pid,'production_manifest','SYN-A-original-document.json',b'{"synthetic":true,"note":"<script>must remain text</script>"}\n')
e=app.product_evidence.get(cid)
source=dict(kind='supplier',platform='other',label='SYN supplier source',url='https://example.invalid/supplier',model='SYN',variant='synthetic',observed_at=datetime.now(timezone.utc).isoformat(),valid_until='',review_state='unreviewed',verification_note='',rights_status='reference_only',rights_evidence='',notes='Synthetic source only',quote_ids=[],images=[dict(url='https://example.invalid/source-image.png',media_id='',label='SYN supplier original',role='original')],metrics={},archived=False)
saved=app.product_evidence.source_save(cid,'',source,0,e['dossier_sha256'],'synthetic-catalog-source','synthetic fixture')['entry']
up=app.product_evidence.media.upload_begin(cid,saved['id'],saved['sha256'],'SYN-source.png',len(image),image_sha,'https://example.invalid/source-image.png','original','synthetic fixture')
for i,start in enumerate(range(0,len(image),up['chunk_bytes'])):app.product_evidence.media.upload_chunk(cid,up['upload_id'],i,base64.b64encode(image[start:start+up['chunk_bytes']]).decode())
app.product_evidence.media.upload_finish(cid,up['upload_id'])
unknown=app.creative.create(dict(synthetic=False,product=dict(name='SYN unknown store project')),'synthetic-unassigned')
register(unknown['id'],'generated_image','SYN-unknown-generated.png')
b,accounts=publish('SYN店铺B','802222');account_b=accounts['active_account_id'];connection_b=app.live.config()['connection_id']
bcid=next(r for r in b if r['product_id']=='100')['id'];bp=app.catalog.creative(bcid,app.catalog.get(bcid)['source_sha256'],'synthetic-store-b')
register(bp['id'],'product_image','SYN-B-original.png')
assert not ({r['product_key']for r in a}&{r['product_key']for r in b})
app.ozon_accounts.activate(account_a,accounts['revision'],'synthetic-return-a')
candidate_ids=[]
with app.core.db()as db:
    for n in range(2):
        ident=uuid.uuid4().hex;candidate_ids.append(ident);scope=dict(platform='ozon',market='RU',sku='SAME-SKU',label='SYN研究待分配'+str(n),origin='research_candidate_not_inventory',research_task_id='synthetic-catalog-research',row_key=ident)
        db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',(ident,'',ident,canonical(scope),None,datetime.now(timezone.utc).isoformat()))
target_path=app.creative.asset(pid,generated[0]['id'])[0]
manifest=dict(synthetic_fixture=True,case_id=cid,account_a=account_a,account_b=account_b,connection_a=connection_a,connection_b=connection_b,old_a_keys=[r['product_key']for r in a],b_keys=[r['product_key']for r in b],candidate_ids=candidate_ids,project_id=pid,generated_id=generated[0]['id'],image_sha256=image_sha,image_bytes=len(image),attributes_raw=attributes,description_raw=description,tamper_file=str(target_path.relative_to(server.STATE)))
(server.STATE/'catalog-library-fixture.json').write_text(json.dumps(manifest,ensure_ascii=False))
server.Handler.secret='synthetic-catalog-library-preview';(server.STATE/'auth.token').write_text(server.Handler.secret);server.Handler.service=app
calls=[];lock=threading.Lock();invoke=app.invoke
def tracked(tool,args=None,client='local'):
    with lock:
        calls.append(dict(tool=tool,arguments=args or{}));(server.STATE/'catalog-library-calls.json').write_text(json.dumps(calls))
    return invoke(tool,args or{},client)
app.invoke=tracked
original_dns=socket.getaddrinfo
def local_dns(host,*args,**kwargs):
    if host not in ('127.0.0.1','localhost','::1',None):raise OSError('fixture_external_network_disabled')
    return original_dns(host,*args,**kwargs)
socket.getaddrinfo=local_dns
print('Synthetic catalog/library fixture ready',flush=True)
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:app.catalog_sync.stop();app.agent_runtime.stop();app.autonomy.stop()
`;
let python=process.env.COMMERCE_PYTHON;
if(!python){const preferred=path.join(root,'.local/commerce-runtime/venv/bin/python');try{await access(preferred);python=preferred;}catch{python='python3';}}
const child=spawn(python,['-c',fixture,root],{cwd:work,env:{PATH:process.env.PATH,LANG:'en_US.UTF-8',COMMERCE_STATE:work,COMMERCE_STATE_DIR:work,COMMERCE_IGNORE_DOTENV:'1',COMMERCE_PORT:String(port),COMMERCE_QA_MODE:'mock_live'},stdio:['ignore','ignore','pipe']});
const stopped=new Promise(resolve=>child.once('close',resolve));let stderr='';child.stderr.on('data',chunk=>stderr=(stderr+chunk).slice(-10000));
let browser,page;const result={status:'running',synthetic_fixture:true,phase:prepare?'fixture_prepare':finderOnly?'finder_race_probe':'browser',checks:[],errors:[],external:[],unexpectedWrites:[],calls:[]};
const fingerprint=async()=>Object.fromEntries(await Promise.all(['commerce/web/workbench.bundle.js','commerce/web/product-workspace.bundle.js','commerce/web/catalog-ui.js','commerce/web/catalog-presentation.js','commerce/web/media-library-ui.js'].map(async name=>[name,hash(await readFile(path.join(root,name)))])));
result.startHashes=await fingerprint();
async function call(tool,args={}){const r=await fetch(origin+'/v1/invoke',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+TOKEN},body:JSON.stringify({tool,arguments:args,client:'test'})});const value=await r.json();assert.ok(r.ok,value.error||tool);return value;}
async function switchAccount(account_id){const accounts=await call('commerce_ozon_accounts_list');const response=await fetch(origin+'/v1/connections/activate',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+TOKEN,Origin:origin},body:JSON.stringify({account_id,expected_revision:accounts.revision,idempotency_key:'synthetic-qa-switch-'+account_id+'-'+accounts.revision})});assert.equal(response.status,200);return response.json();}
async function finderProbe(context){
 const p=await context.newPage(),probe={natural:[],sameTick:null,source:'modern_web_regression.mjs first() pattern; no shared QA modifications'};
 await p.goto(origin+'/workspace?tab=overview&demo=false');await p.locator('.r-dashboard').waitFor();
 for(const query of ['operations','connections','memory','operations']){
  await p.locator('.r-search').click();const dialog=p.getByRole('dialog');await dialog.getByRole('searchbox').fill(query);
  const first=dialog.locator('.r-finder-list button').first(),label=await first.innerText();await first.click();await dialog.waitFor({state:'hidden'});
  probe.natural.push({query,first_label:label,module:await p.locator('.r-app').getAttribute('data-module')});
 }
 await p.locator('.r-search').click();await p.getByRole('dialog').getByRole('searchbox').waitFor();
 probe.sameTick=await p.evaluate(()=>{const input=document.querySelector('dialog input[type=search]'),before=document.querySelector('.r-finder-list button')?.textContent;const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'operations');input.dispatchEvent(new Event('input',{bubbles:true}));const first=document.querySelector('.r-finder-list button'),immediate=first?.textContent;first?.click();return {before,typed:input.value,immediate_first:immediate,same_task_input_and_click:true};});
 await p.waitForTimeout(100);probe.sameTick.module_after=await p.locator('.r-app').getAttribute('data-module');
 probe.natural_mismatch=probe.natural.some(row=>row.module!==row.query);probe.same_tick_mismatch=probe.sameTick.module_after!=='operations';
 probe.interpretation=probe.natural_mismatch?'The unqualified first() helper selected an unexpected route in this natural run.':probe.same_tick_mismatch?'Natural Playwright sequence did not reproduce a mismatch; the separately labelled same-task probe demonstrates the stale-DOM gap only.':'No mismatch reproduced in either probe; no product defect inferred.';
 await writeFile(path.join(out,'finder-race-private.json'),JSON.stringify(probe,null,2));await p.close();return probe;
}
try{
 let ready=false;for(let i=0;i<160;i++){if(child.exitCode!==null)throw Error('Fixture exited: '+stderr);try{ready=(await fetch(origin+'/v1/health',{headers:{authorization:'Bearer '+TOKEN}})).ok;}catch{}if(ready)break;await pause(100);}assert.ok(ready,'Fixture did not become ready');
 const manifest=JSON.parse(await readFile(path.join(work,'catalog-library-fixture.json'),'utf8'));
 const initial=await call('commerce_catalog_list',{kind:'inventory'});assert.equal(initial.items.length,8);assert.equal(initial.items.reduce((n,row)=>n+row.case_ids.length,0),17);assert.equal(initial.items.filter(row=>row.sku==='SAME-SKU').length,2);
 const all=await call('commerce_catalog_list',{kind:'all'});assert.equal(all.items.filter(row=>row.kind==='candidate').length,2);assert.ok(all.items.filter(row=>row.kind==='candidate').every(row=>row.store_identity.kind==='research_candidate'&&row.store_identity.connection_id===null));
 const library=await call('commerce_media_library_list',{synthetic:false,limit:50,offset:0});assert.ok(library.total>20);assert.equal(library.files_copied,0);assert.equal(library.new_approvals,0);assert.equal(library.store_facets_complete,true);assert.ok(library.stores.some(row=>row.store_ref===manifest.account_b));
 result.checks.push('Real HTTP fixture:17 original inventory cases ->8 product cards; same SKU/different product IDs separate;2 research candidates remain unassigned; local media index has exact store facets and no copies/approvals');
 if(prepare){result.status='prepared';result.ui_verified=false;result.finder_probe='not_executed';}
 else{
  let pw;try{pw=await import(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{for(const folder of await readdir(path.join(homedir(),'.npm/_npx')).catch(()=>[])){try{pw=await import(pathToFileURL(path.join(homedir(),'.npm/_npx',folder,'node_modules/playwright/index.mjs')).href);break;}catch{}}}assert.ok(pw,'Use an existing Playwright installation');
  browser=await pw.chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--use-mock-keychain','--password-store=basic']});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});await context.addCookies([{name:'commerce_session',value:TOKEN,url:origin,httpOnly:true,sameSite:'Strict'}]);
  await context.route('**/*',route=>{const request=route.request(),url=request.url();if(!url.startsWith(origin+'/')&&!/^(data|blob|about):/.test(url)){result.external.push(url);return route.abort();}if(url.endsWith('/v1/invoke')){const r=request.postDataJSON(),tool=r?.tool||'';result.calls.push(tool);if(/(?:save|configure|import|generate|execute|submit|send|approve|create|start|delete|select)$/.test(tool)&&tool!=='commerce_ui_save_preferences'&&!(tool==='commerce_workspace_save'&&r.arguments?.form==='view')){result.unexpectedWrites.push(tool);return route.abort();}}return route.continue();});
  page=await context.newPage();page.on('pageerror',error=>result.errors.push(error.message));page.on('console',message=>{if(message.type()==='error'&&/content security policy|refused to load/i.test(message.text()))result.errors.push(message.text());});page.setDefaultTimeout(18000);
  if(!finderOnly){
   const openCatalog=async cid=>{await page.goto(origin+'/product-workspace?case_id='+cid);await page.locator('[data-pw-action="choose-product"]').waitFor();await page.locator('[data-pw-action="choose-product"]').click();await page.locator('.catalog-browser[aria-busy="false"]').waitFor();};
   await openCatalog(manifest.case_id);assert.equal(await page.locator('[id^="catalog-kind-"]').inputValue(),'inventory');assert.equal(await page.locator('.catalog-product').count(),8);
   assert.equal(await page.locator('.catalog-product').filter({hasText:'SAME-SKU'}).count(),2);assert.ok((await page.locator('.catalog-card-store').allTextContents()).every(label=>label.includes('SYN店铺A')));
   await page.locator('[id^="catalog-kind-"]').selectOption('all');await page.waitForFunction(()=>document.querySelectorAll('.catalog-product').length===10);
   await page.locator('[id^="catalog-store-"]').selectOption('unassigned');assert.equal(await page.locator('.catalog-product').count(),2);assert.match(await page.locator('.catalog-browser').innerText(),/调研候选 · 尚未绑定店铺/);
   await page.locator('[id^="catalog-store-"]').selectOption(manifest.connection_a);assert.equal(await page.locator('.catalog-product').count(),8);
   await page.locator(`[data-catalog-action="open"][data-case="${manifest.case_id}"]`).click();await page.locator('.catalog-detail-header').waitFor();
   const attributeRow=page.locator('.catalog-text').filter({has:page.locator('.catalog-readable-pairs')}).filter({hasText:'SYN属性0'});await attributeRow.first().waitFor();assert.match(await attributeRow.first().innerText(),/Русский 0/);await attributeRow.getByText('其余 2 项属性',{exact:true}).click();assert.match(await attributeRow.innerText(),/SYN属性6/);
   await attributeRow.getByText('查看原始字段',{exact:true}).click();assert.equal(await attributeRow.locator('.catalog-original pre').innerText(),manifest.attributes_raw);
   const descriptionRow=page.locator('tr').filter({has:page.getByText('描述与卖点',{exact:true})});assert.match(await descriptionRow.innerText(),/SYN俄语套装：12张双面卡/);await descriptionRow.getByText('展开完整内容',{exact:true}).click();assert.match(await descriptionRow.innerText(),/SYN原文末尾/);await descriptionRow.getByText('查看原始字段',{exact:true}).click();assert.equal(await descriptionRow.locator('.catalog-original pre').innerText(),manifest.description_raw);assert.equal(await page.evaluate(()=>window.__catalogXss),undefined);
   const cardDownload=page.waitForEvent('download');await page.locator('[data-catalog-action="export-card"]').click();const exported=await cardDownload;const cardFile=path.join(out,'synthetic-information-card.json');await exported.saveAs(cardFile);const card=JSON.parse(await readFile(cardFile));assert.equal(card.case_id,manifest.case_id);assert.equal(card.inventory_scopes.length,3);assert.equal(card.fields.find(f=>f.key==='attributes').original,manifest.attributes_raw);assert.equal(card.external_execution_allowed,false);
   result.checks.push('Actual catalog default inventory, exact store/unassigned filters, readable JSON/HTML, complete/raw field expansion and actual information-card JSON download');
   for(const theme of ['light','dark']){await page.locator('#pw-theme').selectOption(theme);for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`catalog overflow ${theme}/${width}`);await page.screenshot({path:path.join(out,`catalog-${theme}-${width}.png`)});}}
   const originalReaderCalls=()=>result.calls.filter(t=>['commerce_creative_asset_read','commerce_product_evidence_image'].includes(t)).length,readersBeforeLibrary=originalReaderCalls();await page.locator('[data-catalog-action="library"]').click();await page.locator('.media-library[aria-busy="false"]').waitFor();assert.equal(await page.locator('.media-library-preview img').count(),0);assert.equal(originalReaderCalls(),readersBeforeLibrary,'Metadata listing must not read media bytes');
   await page.locator('[data-media-library-action="next"]').click();await page.locator('.media-library[aria-busy="false"]').waitFor();assert.match(await page.locator('.media-library-pagination').innerText(),/21–/);await page.locator('[data-media-library-action="prev"]').click();await page.locator('.media-library[aria-busy="false"]').waitFor();
   await page.locator('[id^="media-library-store-"]').selectOption('unassigned');await page.locator('.media-library[aria-busy="false"]').waitFor();assert.equal(await page.locator('.media-library-item').count(),1);assert.match(await page.locator('.media-library-group').innerText(),/未知店铺/);
   await page.locator('[id^="media-library-store-"]').selectOption(manifest.account_b);await page.locator('.media-library[aria-busy="false"]').waitFor();assert.match(await page.locator('.media-library-item').innerText(),/SYN店铺B/);assert.equal(await page.locator('[data-media-library-action="product"]').count(),0);
   await page.locator('[id^="media-library-store-"]').selectOption(manifest.account_a);await page.locator('.media-library[aria-busy="false"]').waitFor();await page.locator('[id^="media-library-query-"]').fill('SYN-A-approved-generated-00');await page.locator('[data-media-library-action="search"]').click();await page.locator('.media-library[aria-busy="false"]').waitFor();assert.equal(await page.locator('.media-library-item').count(),1);assert.match(await page.locator('.media-library-item').innerText(),/当前用途未审核/);
   await page.locator('[data-media-library-action="preview"]').click();await page.waitForFunction(()=>document.querySelector('.media-library-preview img')?.naturalWidth===320);await page.locator('[data-media-library-action="close"]').click();assert.equal(await page.locator('.media-library-preview').count(),0);assert.match(await page.evaluate(()=>document.activeElement.id),/preview/);
   const mediaDownload=page.waitForEvent('download');await page.locator('[data-media-library-action="download"]').click();const downloaded=await mediaDownload,file=path.join(out,'synthetic-library-image.png');await downloaded.saveAs(file);assert.equal(hash(await readFile(file)),manifest.image_sha256);
   const target=path.join(work,manifest.tamper_file),originalBytes=await readFile(target),tampered=Buffer.from(originalBytes);tampered[tampered.length-5]^=1;await writeFile(target,tampered);await page.locator('[data-media-library-action="preview"]').click();await page.getByText(/读取或SHA核对未通过/).waitFor();assert.equal(await page.locator('.media-library-preview img').count(),0);await writeFile(target,originalBytes);
   await page.locator('[id^="media-library-query-"]').fill('');await page.locator('[id^="media-library-kind-"]').selectOption('document');await page.locator('.media-library[aria-busy="false"]').waitFor();assert.equal(await page.locator('.media-library-item').count(),1);await page.locator('[data-media-library-action="preview"]').click();await page.locator('.media-library-text').waitFor();assert.match(await page.locator('.media-library-text').innerText(),/<script>must remain text<\/script>/);assert.equal(await page.locator('.media-library-preview script').count(),0);await page.locator('[id^="media-library-kind-"]').selectOption('supplier_image');await page.locator('.media-library[aria-busy="false"]').waitFor();assert.equal(await page.locator('.media-library-item').count(),1);await page.locator('[data-media-library-action="preview"]').click();await page.waitForFunction(()=>document.querySelector('.media-library-preview img')?.naturalWidth===320);
   result.checks.push('Actual material pagination, exact inactive/unknown store filters, explicit original readers, image preview/close focus, SHA-verified download and real temporary-file tamper rejection');
   for(const theme of ['light','dark']){await page.locator('#pw-theme').selectOption(theme);for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`library overflow ${theme}/${width}`);await page.screenshot({path:path.join(out,`library-${theme}-${width}.png`)});}}
   await switchAccount(manifest.account_b);const b=await call('commerce_catalog_list',{kind:'inventory'});assert.equal(b.items.length,8);assert.ok(b.items.every(r=>r.store_identity.account_id===manifest.account_b));assert.ok(!b.items.some(r=>manifest.old_a_keys.includes(r.product_key)));await openCatalog(b.items[0].id);assert.equal(await page.locator('.catalog-product').count(),8);assert.ok((await page.locator('.catalog-card-store').allTextContents()).every(label=>label.includes('SYN店铺B')));await switchAccount(manifest.account_a);
   result.checks.push('Real isolated account switch: same-SKU B products keep different product keys; A products never leak into B cards');
  }
  result.finder_probe=await finderProbe(context);assert.deepEqual(result.errors,[]);assert.deepEqual(result.external,[]);assert.deepEqual(result.unexpectedWrites,[]);result.status='passed';result.ui_verified=!finderOnly;
 }
 result.endHashes=await fingerprint();assert.deepEqual(result.endHashes,result.startHashes,'Shared source/build changed during acceptance; rerun against a frozen build');
 await writeFile(path.join(out,prepare?'prepare.json':finderOnly?'finder-run.json':'verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:result.status,phase:result.phase,checks:result.checks.length,ui_verified:result.ui_verified}));
}catch(error){result.status='failed';result.error=String(error);result.stderr=stderr;await page?.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});await writeFile(path.join(out,'failure.json'),JSON.stringify(result,null,2));throw error;}
finally{await browser?.close();child.kill('SIGTERM');await Promise.race([stopped,pause(3000)]);if(child.exitCode===null){child.kill('SIGKILL');await stopped;}await rm(work,{recursive:true,force:true});}
