"""Case-bound channel discovery and product previews, never orders or login automation."""
from datetime import datetime, timezone
import json, re, time, uuid
from urllib.parse import urlsplit
from research import canonical, digest
from sourcing_extract import imported, html_product, clean

# These are discovery/import adapters, not claims of platform API credentials.
CHANNELS=[
 ('1688','1688',['1688.com'],'批发','import'),
 ('yiwugo','义乌购',['yiwugo.com'],'批发','public'),
 ('made_in_china','中国制造网',['made-in-china.com'],'工厂/批发','public'),
 ('alibaba','Alibaba 国际站',['alibaba.com'],'工厂/跨境批发','public'),
 ('taobao','淘宝',['taobao.com'],'零售/店铺货源','public'),
 ('tmall','天猫',['tmall.com'],'品牌零售','public'),
 ('jd','京东',['jd.com'],'零售/品牌参照','public'),
 ('pdd','拼多多',['pinduoduo.com','yangkeduo.com'],'零售/多多批发待确认','public'),
 ('chinagoods','义乌小商品城',['chinagoods.com'],'批发','public'),
 ('aicaigou','百度爱采购',['b2b.baidu.com'],'工厂/询盘线索','public'),
 ('hc360','慧聪网',['hc360.com'],'工厂/询盘线索','public'),
 ('gongchang','世界工厂网',['gongchang.com'],'工厂/询盘线索','public'),
 ('suning','苏宁易购',['suning.com'],'零售/品牌参照','public'),
 ('vip','唯品会',['vip.com'],'品牌零售','public'),
 ('dangdang','当当',['dangdang.com'],'零售','public'),
 ('other','其他供货网站',[],'待核供应商','import'),
]
EXTRA_PLATFORMS=[{'id':i,'label':label,'hosts':hosts} for i,label,hosts,_,_ in CHANNELS
                 if i not in {'1688','yiwugo','made_in_china','alibaba','taobao','jd','pdd','other'}]
READ_ONLY={'commerce_product_evidence_sourcing_channels','commerce_product_evidence_sourcing_history'}

def definitions(schema,string):
    case={'case_id':string};common={**case,'platform':string,'idempotency_key':string}
    return [
      ('commerce_product_evidence_sourcing_channels','读取国内进货渠道、可用方式与当前商品实际采集状态；渠道登记不等于平台API已接通',schema(case,['case_id'])),
      ('commerce_product_evidence_sourcing_search','在一个渠道检索公开商品线索，留存同商品回执；搜索摘要不作为已核实报价',schema({**common,'query':{'type':'string','minLength':1,'maxLength':120}},[*common,'query'])),
      ('commerce_product_evidence_sourcing_preview','读取可用公开商品元数据或解析用户正常导出的JSON/HTML；先预览不采购、不登录、不保存正式报价',schema({**common,'url':string,'mode':{'type':'string','enum':['public','import']},'format':{'type':'string','enum':['json','html']},'content':{'type':'string','maxLength':200000}},[*common,'url','mode'])),
      ('commerce_product_evidence_sourcing_history','读取同商品渠道检索/读取/导入回执；不重发网络请求',schema(case,['case_id'])),
    ]

class Sourcing:
    def __init__(self,dossier):
        self.dossier=dossier;self.service=dossier.service;self.core=dossier.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sourcing_receipts(id TEXT PRIMARY KEY,case_id TEXT NOT NULL,idem TEXT NOT NULL,request_sha TEXT NOT NULL,document TEXT NOT NULL,UNIQUE(case_id,idem))')
    def channel(self,platform):
        row=next((r for r in CHANNELS if r[0]==platform),None)
        if not row:raise ValueError('sourcing_channel_unknown')
        return row
    def validate_url(self,platform,value):
        from product_evidence import url
        value=url(value,platform);host=urlsplit(value).hostname.lower()
        row=self.channel(platform)
        if row[2] and not any(host==h or host.endswith('.'+h) for h in row[2]):raise ValueError('sourcing_channel_url_mismatch')
        return value
    def history(self,case_id):
        self.dossier.case(case_id)
        with self.core.db() as db:rows=db.execute('SELECT document FROM sourcing_receipts WHERE case_id=? ORDER BY rowid DESC LIMIT 30',(case_id,)).fetchall()
        return {'items':[self.verified(json.loads(r[0]),case_id) for r in rows],'external_execution_allowed':False}
    def verified(self,doc,case_id):
        if doc.get('case_id')!=case_id or doc.get('sha256')!=digest(canonical({k:v for k,v in doc.items() if k!='sha256'})):
            raise ValueError('sourcing_receipt_changed')
        return doc
    def channels(self,case_id):
        history=self.history(case_id)['items'];sources=self.dossier.get(case_id)['sources'];items=[]
        for ident,label,hosts,kind,network in CHANNELS:
            last=next((r for r in history if r['platform']==ident),None)
            items.append({'id':ident,'label':label,'hosts':hosts,'kind':kind,'search_supported':network=='public',
                          'public_preview_supported':network=='public','import_supported':True,'authorized_api_connected':False,
                          'status':'export_only' if network=='import' else 'public_attempt_available',
                          'status_note':('当前访问受限，使用正常导出资料；授权接口尚未接入' if ident=='1688' else '支持其他公开供货网站的资料导入；需核对供应商身份') if network=='import' else '可检索公开线索、尝试读取结构化商品页；登录或验证受限时改用资料导入',
                          'source_count':sum(s['platform']==ident and s['kind'] in ('supplier','market') and not s['archived'] for s in sources),'last_attempt':last})
        return {'items':items,'external_execution_allowed':False}
    def old(self,case_id,key,request):
        self.dossier.case(case_id)
        from product_evidence import text
        text(key,160,True)
        with self.core.db() as db:r=db.execute('SELECT request_sha,document FROM sourcing_receipts WHERE case_id=? AND idem=?',(case_id,key)).fetchone()
        if r:
            if r[0]!=digest(canonical(request)):raise ValueError('sourcing_idempotency_conflict')
            return self.verified(json.loads(r[1]),case_id)
    def save(self,case_id,key,request,result):
        doc={'id':'srcp_'+uuid.uuid4().hex,'case_id':case_id,'platform':request['platform'],
             'action':request['action'],'observed_at':datetime.now(timezone.utc).isoformat(),
             'request_url':request.get('url',''),'query':request.get('query',''),**result,'external_execution_allowed':False}
        doc['sha256']=digest(canonical(doc))
        with self.core.atomic() as db:
            old=self.old(case_id,key,request)
            if old:return old
            db.execute('INSERT INTO sourcing_receipts VALUES(?,?,?,?,?)',(doc['id'],case_id,key,digest(canonical(request)),canonical(doc)))
        return doc
    def search(self,case_id,platform,query,idempotency_key):
        from product_evidence import text
        query=text(query,120,True);channel=self.channel(platform)
        req={'action':'search','platform':platform,'query':query};old=self.old(case_id,idempotency_key,req)
        if old:return old
        if channel[4]!='public':return self.save(case_id,idempotency_key,req,{'status':'export_required','items':[],'reason':'当前渠道受限，不通过检索或其他读取方式绕过原访问限制。'})
        result=self.service.public_web.search(query+' site:'+channel[2][0],period='any',limit=6)
        rows=[]
        for group in result.get('groups',[]):
            for r in group.get('items',[]):
                try:link=self.validate_url(platform,r.get('url',''))
                except ValueError:continue
                if not any(i['url']==link for i in rows):rows.append({'url':link,'title':clean(r.get('title'),500),'snippet':clean(r.get('summary'),1200),'evidence_level':'search_lead_not_read'})
        return self.save(case_id,idempotency_key,req,{'status':'search_failed' if result.get('status')=='failed' else 'leads' if rows else 'no_public_leads','items':rows[:6],'reason':'检索摘要不证明现价、库存、同款或可采购性。'})
    def preview(self,case_id,platform,url,mode,idempotency_key,format='json',content=''):
        url=self.validate_url(platform,url);channel=self.channel(platform)
        if mode not in ('public','import'):raise ValueError('sourcing_mode_invalid')
        if not isinstance(content,str) or len(content)>200000:raise ValueError('sourcing_import_size')
        req={'action':'preview','platform':platform,'url':url,'mode':mode,'format':format,'content_sha256':digest(content)}
        old=self.old(case_id,idempotency_key,req)
        if old:return old
        if mode=='public' and channel[4]!='public':return self.save(case_id,idempotency_key,req,{'status':'export_required','draft':None,'reason':'当前渠道访问受限，仅支持正常导出资料；不代替授权接口。'})
        try:
            if mode=='import':product=imported(content,format,url);raw_sha=digest(content);excerpt=''
            else:
                page=self.service.public_web.read([url],url_validator=lambda value:self.validate_url(platform,value))['items'][0]
                if page['status']!='ready':raise ValueError(page.get('error','web_page_unavailable'))
                resolved_url=self.validate_url(platform,page['url'])
                excerpt=page.get('text','')[:1800]
                if re.search(r'captcha|安全验证|访问验证|访问受限|登录|sign.?in|access denied',page.get('title',''),re.I):raise ValueError('sourcing_login_or_challenge')
                product=page.get('product_metadata');raw_sha=page['source_sha256']
                if not product or product.get('multiple_products'):raise ValueError('sourcing_structured_product_missing')
                if product.get('needs_variant_confirmation') and not product['description']:
                    product['description']='页面原文摘录，可能含不同规格或推荐商品：'+excerpt
            observed=datetime.now(timezone.utc).isoformat()
            notes='取得方式：'+('导入资料，非本次原站实时采集；导入者陈述待核对。' if mode=='import' else '公开页面结构化元数据，页面声明未经实物核实。')
            redirected=mode=='public' and resolved_url!=url
            if mode=='public':notes+='\n请求原始地址：'+url+'\n实际读取地址：'+resolved_url
            if redirected:notes+='\n原地址发生跳转；本预览只归属实际读取地址，请另核对是否同款。'
            notes+='\n读取回执/导入内容哈希：'+raw_sha+'\n商品陈述：'+product['description']
            notes+='\n供应方陈述：'+(product['supplier'] or '待核对')+'\n规格/包装原文（未实测）：'+product.get('specifications','')
            notes+='\n原文报价选项（不是正式报价，不自动选最低价）：'+json.dumps(product['offers'],ensure_ascii=False)
            notes+='\n零售/券后/会员/拼团/批发身份、准确款式、含税运、单包重量、有效期与商用权均须另核。'
            draft={'kind':'supplier','platform':platform,'label':product['title'][:1000],'url':resolved_url if mode=='public' else url,'model':product['model'],'variant':product['variant'],
                   'observed_at':observed,'valid_until':'','review_state':'unreviewed','verification_note':'待核原页/选项及实物，不自动批准采购',
                   'rights_status':'reference_only','rights_evidence':'','notes':notes[:5000],'quote_ids':[],
                   'images':[{'url':u,'media_id':'','label':'渠道原始参考图 '+str(n+1),'role':'original'} for n,u in enumerate(product['images'])], 'metrics':{},'archived':False}
            self.dossier.validate_source(case_id,draft)
            return self.save(case_id,idempotency_key,req,{'status':'preview_partial' if redirected or product.get('needs_variant_confirmation') else 'preview_ready','product':product,'draft':draft,'source_sha256':raw_sha,'excerpt':excerpt,'reason':'已取得商品页面资料；缺少准确款式或标价的字段保留待核。预览尚未存入来源，请核对后显式保存。'})
        except ValueError as error:
            return self.save(case_id,idempotency_key,req,{'status':'needs_export','draft':None,'error':str(error),
                             'reason':'公开读取未取得准确商品结构，请正常导出单个商品JSON/含Product元数据的HTML；不重试登录或验证。'})
