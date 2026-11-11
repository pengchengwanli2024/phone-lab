"""One shared commerce domain service for Harness, Codex and Hermes."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
import hashlib
from commerce_core import Core, PLATFORMS
from operations_analysis import unit_economics, restock_plan, input_schema, UNIT_FIELDS, STOCK_FIELDS
from knowledge_ranking import ranked_notes
from research import template as collection_template, validate as collection_check, export as collection_export
from translation import TranslationJobs
from intelligence import Intelligence
from intel_articles import Articles
from collection_jobs import CollectionJobs
from crawler_feed_bridge import REGISTRY as CRAWLER_REGISTRY

LABELS=dict(zip(PLATFORMS,['Ozon','TikTok Shop','Amazon','Mercado Libre','Temu']))
SALES=[39200,34800,28640,18000,8000]
MARKETS=dict(zip(PLATFORMS,['RU','US','US','MX','待选择']))


def now():return datetime.now(timezone.utc).isoformat()


def schema(properties=None,required=None):
    return {'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}


S={'type':'string','minLength':1,'maxLength':160}
FILTERS={'demo':{'type':'boolean'},'platform':{'type':'string','enum':['all',*PLATFORMS]},'store_id':{'type':'string','enum':['all',*(p+'-demo'for p in PLATFORMS)]},'market':{'type':'string','enum':['all','RU','US','MX']}}
INTEL_QUERY={'query':{'type':'string','maxLength':100},'source':{'type':'string','enum':['all','usgs','gdacs','wto','fed','ecb','eia','hmrc','transport']},'category':{'type':'string','enum':['all','earthquake','disaster','trade','macro','energy','logistics']},'country':{'type':'string','maxLength':80},'hours':{'type':'string','enum':['all','24','168']},'scope':{'type':'string','enum':['latest','archive']},'view':{'type':'string','enum':['all','unviewed','bookmarked']}}
TOOLS=[
 ('commerce_crawler_start','启动固定公开源多路采集并导入；串行队列、可取消，无店铺写操作',schema({'source':{'type':'string','enum':['all',*CRAWLER_REGISTRY]},'idempotency_key':S},['source','idempotency_key'])),
 ('commerce_crawler_list','读取采集队列、逐来源进度和已导入结果',schema()),
 ('commerce_crawler_alert_ack','确认已查看本机采集失败告警；保留失败记录，不重试任务',schema({'alert_id':S},['alert_id'])),
 ('commerce_crawler_get','读取指定采集任务',schema({'job_id':S},['job_id'])),
 ('commerce_crawler_cancel','取消剩余采集；已完成的来源快照保留',schema({'job_id':S},['job_id'])),
 ('commerce_crawler_retry','明确重试失败、取消或中断的采集任务，递增尝试次数',schema({'job_id':S},['job_id'])),
 ('commerce_intel_article_start','采集所选记录的发布方正文，双路核对并绑定原记录版本；不下载附件',schema({'item_id':S,'record_sha256':S,'idempotency_key':S},['item_id','record_sha256','idempotency_key'])),
 ('commerce_intel_article_get','读取正文、原文哈希、来源证据和待校对中文；保留原始版本',schema({'article_id':S},['article_id'])),
 ('commerce_intel_article_list','读取所选记录已留存的正文版本',schema({'item_id':S},['item_id'])),
 ('commerce_intel_article_translate','通过已配置 Hermes 翻译所选正文；分段保留来源绑定，机器译文待校对',schema({'article_id':S},['article_id'])),
 ('commerce_intel_sources','查看全球公开信息源的覆盖、采集时间、失败和陈旧状态',schema()),
 ('commerce_intel_search','分页检索当前快照或本机积累；支持收藏和未查看，不是全网历史搜索',schema({**INTEL_QUERY,'limit':{'type':'string','enum':['20','50','100']},'cursor':{'type':'string','maxLength':400},'include_map':{'type':'boolean'}})),
 ('commerce_intel_item_get','读取公开来源记录、采集凭据与本地版本摘要；不标记为已查看',schema({'item_id':S},['item_id'])),
 ('commerce_intel_item_update','收藏或按明确版本标记已查看；不表示事实已核实',schema({'item_id':S,'action':{'type':'string','enum':['viewed','unviewed','bookmark','unbookmark']},'record_sha256':S},['item_id','action'])),
 ('commerce_intel_review_create','按已展示的来源版本创建共享核查任务，同版本重复调用复用任务；不会执行店铺操作',schema({'item_id':S,'record_sha256':S},['item_id','record_sha256'])),
 ('commerce_intel_watch_save','保存共享检索条件，最多12项；不启用自动采集或消息推送',schema({'name':{'type':'string','minLength':1,'maxLength':60},**INTEL_QUERY},['name'])),
 ('commerce_intel_watch_list','读取共享关注主题、匹配和未查看数量；不是推送状态',schema()),
 ('commerce_intel_watch_remove','移除指定的共享检索条件；保留记录和收藏',schema({'watch_id':S},['watch_id'])),
 ('commerce_intel_refresh','更新公开来源：读取固定源并导入本机多路采集快照；失败保留旧数据，90秒限频，不访问店铺',schema({'source':{'type':'string','enum':['all','usgs','gdacs','wto','fed','ecb','eia','hmrc','transport']}})),
 ('commerce_worldmonitor_status','查看 World Monitor 接入准备状态；discover=true 仅发现官方公开工具表，不调用收费数据工具',schema({'discover':{'type':'boolean'}})),
 ('commerce_status','查看共享后台、五平台与连接状态',schema()),
 ('commerce_dashboard','读取经营指标；demo=true 仅返回明确标注的模拟数据',schema(FILTERS)),
 ('commerce_orders_list','查询订单；未授权时真实订单为空',schema({**FILTERS,'query':{'type':'string','maxLength':100},'status':{'type':'string','maxLength':40}})),
 ('commerce_products_list','查询商品与库存；原币与 SKU 保留来源',schema(FILTERS)),
 ('commerce_task_create','创建可跨工具查询的任务；不会自动执行平台写操作',schema({'idempotency_key':S,'kind':{'type':'string','enum':['report','analysis','draft']},'input':{'type':'object'}},['idempotency_key','kind'])),
 ('commerce_task_list','读取所有客户端共用的任务队列',schema()),
 ('commerce_task_get','按任务 ID 查询同一任务',schema({'task_id':S},['task_id'])),
 ('commerce_task_cancel','取消尚未执行的共享任务',schema({'task_id':S},['task_id'])),
 ('commerce_report_create','生成本地运营简报草稿；不发消息、不修改店铺',schema({'demo':{'type':'boolean'},'idempotency_key':S},['idempotency_key'])),
 ('commerce_knowledge_list','列出已配置业务知识目录中的 Markdown 文件',schema()),
 ('commerce_knowledge_read','读取所选目录内的业务 Markdown；禁止路径穿越和软链接',schema({'path':S},['path'])),
 ('commerce_knowledge_search','在所选业务目录内搜索；不扫描整个 Vault',schema({'query':{'type':'string','minLength':1,'maxLength':80}},['query'])),
 ('commerce_summary_save','将简报草稿归档到配置的 Obsidian 业务目录',schema({'report_id':S},['report_id'])),
 ('commerce_reports_list','查看共用的本地运营简报草稿',schema()),
 ('commerce_unit_economics','用明确提供的同币种成本计算单件贡献草稿；缺参数返回 HOLD，不内置平台费率',schema({'input':input_schema(UNIT_FIELDS)},['input'])),
 ('commerce_restock_plan','按明确提供的销量窗口与库存计算补货草稿；不创建采购单或修改库存',schema({'input':input_schema(STOCK_FIELDS)},['input'])),
 ('commerce_collection_template','读取平台采集清单与中英证据模板；不是平台上架规则',schema({'platform':{'type':'string','enum':['research',*PLATFORMS]}},['platform'])),
 ('commerce_collection_check','检查采集缺项、译文校对、数字差异和证据；不证明真实性',schema({'record':{'type':'object'}},['record'])),
 ('commerce_collection_export','生成包含原文、中文、来源与哈希的 JSON/CSV 文件内容；不完整时拒绝正式导出',schema({'record':{'type':'object'},'final':{'type':'boolean'}},['record'])),
 ('commerce_translation_start','使用现有 Hermes 模型翻译所选原文，产生待校对译文；无工具执行',schema({'input':{'type':'object'},'idempotency_key':S},['input','idempotency_key'])),
 ('commerce_translation_get','查询同一翻译任务与模型来源、数字差异；不自动重发',schema({'job_id':S},['job_id'])),
]


class Commerce:
    def __init__(self,state):
        self.state=Path(state).resolve();self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.core=Core(self.state/'commerce.sqlite')
        with self.core.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, idem TEXT UNIQUE, mode TEXT, content TEXT, created_at TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS clients (name TEXT PRIMARY KEY, seen_at TEXT)')
        self.translations=TranslationJobs(self.core)
        self.intelligence=Intelligence(self.core)
        self.collections=CollectionJobs(self.core,self.state,importer=self.intelligence.import_collection)
        self.articles=Articles(self.core,self.state,self.intelligence,self.translations)

    def validate(self,name,args):
        definition=next((x[2]for x in TOOLS if x[0]==name),None)
        if definition is None:raise ValueError('unknown_tool')
        if not isinstance(args,dict) or set(args)-set(definition['properties']) or any(k not in args for k in definition['required']):raise ValueError('invalid_arguments')
        for key,value in args.items():
            rule=definition['properties'][key];typ=rule['type']
            if (typ=='string' and not isinstance(value,str))or(typ=='boolean' and not isinstance(value,bool))or(typ=='object' and not isinstance(value,dict)):raise ValueError('invalid_'+key)
            if typ=='string' and not rule.get('minLength',0)<=len(value)<=rule.get('maxLength',20000):raise ValueError('invalid_'+key)
            if 'enum'in rule and value not in rule['enum']:raise ValueError('invalid_'+key)

    def config(self):
        path=self.state/'config.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def root(self):
        value=self.config().get('knowledge_root')
        if not value:return None
        p=Path(value)
        if not p.is_absolute() or not p.is_dir() or p.is_symlink():raise ValueError('knowledge_root_invalid')
        return p.resolve()

    def safe_note(self,relative):
        root=self.root()
        if root is None:raise ValueError('knowledge_not_configured')
        path=Path(relative)
        if path.is_absolute() or '..'in path.parts or path.suffix!='.md':raise ValueError('invalid_note_path')
        target=root/path
        if any(p.is_symlink() for p in [target,*target.parents] if p!=root.parent) or not target.resolve().is_relative_to(root):raise ValueError('invalid_note_path')
        if not target.is_file() or target.stat().st_size>128000:raise ValueError('note_unavailable')
        return target

    def notes(self):
        root=self.root()
        if root is None:return []
        result=[]
        for folder,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink())
            for f in sorted(files):
                p=Path(folder)/f
                if f.endswith('.md') and not p.is_symlink() and p.stat().st_size<=128000:result.append(str(p.relative_to(root)))
                if len(result)>=200:return result
        return result

    def invoke(self,name,args,client='local'):
        self.validate(name,args)
        if client not in ['codex','hermes','harness','browser','local','test']:raise ValueError('invalid_client')
        with self.core.db() as c:c.execute('INSERT OR REPLACE INTO clients VALUES (?,?)',(client,now()))
        if name=='commerce_intel_item_get':return self.intelligence.store.item(**args)
        if name=='commerce_intel_item_update':return self.intelligence.store.update_item(**args)
        if name=='commerce_intel_review_create':return self.intelligence.store.create_review(**args)
        if name=='commerce_intel_watch_save':return self.intelligence.store.save_watch(**args)
        if name=='commerce_intel_watch_list':return self.intelligence.store.watches()
        if name=='commerce_intel_watch_remove':return self.intelligence.store.remove_watch(**args)
        if name=='commerce_crawler_start':return self.collections.request(args['source'],args['idempotency_key'])
        if name=='commerce_crawler_list':return self.collections.listing()
        if name=='commerce_crawler_alert_ack':return self.collections.acknowledge(args['alert_id'])
        if name=='commerce_crawler_get':return self.collections.get(args['job_id'])
        if name=='commerce_crawler_cancel':return self.collections.cancel(args['job_id'])
        if name=='commerce_crawler_retry':return self.collections.retry(args['job_id'])
        if name=='commerce_intel_article_start':return self.articles.start(**args)
        if name=='commerce_intel_article_get':return self.articles.get(**args)
        if name=='commerce_intel_article_list':return self.articles.for_item(**args)
        if name=='commerce_intel_article_translate':return self.articles.translate(**args)
        if name=='commerce_intel_sources':return self.intelligence.sources()
        if name=='commerce_intel_search':return self.intelligence.search(**args)
        if name=='commerce_intel_refresh':return self.intelligence.refresh(**args)
        if name=='commerce_worldmonitor_status':return self.intelligence.worldmonitor(**args)
        if name=='commerce_status':
            with self.core.db() as c:clients=dict(c.execute('SELECT name,seen_at FROM clients'))
            team=json.loads((Path(__file__).parent/'agents/roles.json').read_text())
            return {'version':'0.1.0','mode':'unconfigured','platforms':[{'id':p,'name':LABELS[p],'status':'not_authorized'}for p in PLATFORMS], 'clients':clients,'knowledge':{'configured':self.root()is not None,'notes':len(self.notes())},'marketplace_writes':False,'agent_team':{'roles':team['roles'],'deployment':team['deployment'],'default_role':team['default_role']}}
        if name=='commerce_task_create':
            role=args.get('input',{}).get('agent_role')
            if role is not None:
                team=json.loads((Path(__file__).parent/'agents/roles.json').read_text())
                if role not in [r['id']for r in team['roles']]:raise ValueError('unknown_agent_role')
        if name.startswith('commerce_task_'):return self.core.invoke(name,args)
        if name=='commerce_unit_economics':return unit_economics(args['input'])
        if name=='commerce_restock_plan':return restock_plan(args['input'])
        if name=='commerce_collection_template':return collection_template(args['platform'])
        if name=='commerce_collection_check':return collection_check(args['record'])
        if name=='commerce_collection_export':return collection_export(args['record'],args.get('final',False))
        if name=='commerce_translation_start':return self.translations.start(args['input'],args['idempotency_key'])
        if name=='commerce_translation_get':return self.translations.get(args['job_id'])
        demo=args.get('demo',False);platform=args.get('platform','all');store=args.get('store_id','all');market=args.get('market','all')
        selected=[i for i,p in enumerate(PLATFORMS)if platform in ['all',p]and store in ['all',p+'-demo']and market in ['all',MARKETS[p]]]
        if name=='commerce_dashboard':
            rows=[{'id':PLATFORMS[i],'name':LABELS[PLATFORMS[i]],'amount':SALES[i]}for i in selected] if demo else []
            amount=sum(x['amount']for x in rows)
            indices=selected
            return {'mode':'demo' if demo else 'live','currency':'USD','timezone':'Asia/Shanghai','rate_note':'模拟汇率与数据，不用于经营决策'if demo else'尚未授权店铺，暂无汇率与经营数据','sales':amount if demo else None,'orders':sum([392,348,286,180,78][i]for i in indices)if demo else None,'pending':sum([8,12,4,5,3][i]for i in indices)if demo else None,'stock_alerts':sum([3,1,1,1,1][i]for i in indices)if demo else None,'platforms':rows,'updated_at':now(),'data_source':'synthetic'if demo else'not_connected'}
        if name=='commerce_orders_list':
            data=[{'id':f'SIM-{1001+i}','platform':p,'store_id':p+'-demo','store':'示例店铺','market':MARKETS[p],'product':['宠物梳理套装','便携咖啡杯','桌面收纳架','旅行收纳套装','硅胶厨房工具'][i],'sku':['PET-021','CUP-014','HOME-008','BAG-006','KIT-031'][i],'amount':[8990,79,129,1490,36][i],'currency':['RUB','USD','USD','MXN','USD'][i],'status':['待发货','物流异常','运输中','待处理','待确认'][i]}for i,p in enumerate(PLATFORMS)if i in selected]if demo else[]
            data=[x for x in data if(not args.get('status')or x['status']==args['status'])and args.get('query','').lower()in json.dumps(x,ensure_ascii=False).lower()]
            return {'mode':'demo'if demo else'live','orders':data,'total':len(data),'data_source':'synthetic'if demo else'not_connected'}
        if name=='commerce_products_list':
            orders=self.invoke('commerce_orders_list',{'demo':demo,'platform':platform,'store_id':store,'market':market},client)['orders']
            return {'mode':'demo'if demo else'live','products':[{'sku':o['sku'],'name':o['product'],'platform':o['platform'],'available':[3,26,52,12,7][PLATFORMS.index(o['platform'])],'threshold':10,'currency':o['currency'],'price':o['amount']}for o in orders]}
        if name=='commerce_report_create':
            key=args['idempotency_key'];mode='demo'if demo else'live'
            if not key.strip():raise ValueError('invalid_idempotency_key')
            with self.core.db() as c:
                c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM reports WHERE idem=?',(key,)).fetchone()
                if row and row[2]!=mode:raise ValueError('idempotency_conflict')
                if not row:
                    report_id=hashlib.sha256(key.encode()).hexdigest()[:20]
                    content=('# 运营简报草稿\n\n数据模式：'+('模拟数据，仅供界面验证。\n\n五平台示例销售额合计 USD 128,640；待处理订单 32，库存预警 7。\n\n建议：核对库存和物流，审阅客服草稿。'if demo else'真实模式，尚未授权店铺，暂无经营数据。\n\n请先完成平台授权与数据核验。')+'\n\n本简报由本地模板生成，未调用 LLM，未执行平台操作。\n')
                    row=(report_id,key,mode,content,now());c.execute('INSERT INTO reports VALUES (?,?,?,?,?)',row)
                return {'id':row[0],'mode':row[2],'content':row[3],'created_at':row[4],'status':'draft','generator':'local_template'}
        if name=='commerce_reports_list':
            with self.core.db() as c:return {'reports':[{'id':r[0],'mode':r[2],'content':r[3],'created_at':r[4],'status':'draft'}for r in c.execute('SELECT * FROM reports ORDER BY rowid DESC LIMIT 30')]}
        if name=='commerce_knowledge_list':return {'configured':self.root()is not None,'notes':self.notes()}
        if name=='commerce_knowledge_read':
            target=self.safe_note(args['path']);return {'path':args['path'],'content':target.read_text(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
        if name=='commerce_knowledge_search':
            q=args['query'].strip().lower()
            if not q:raise ValueError('query_required')
            documents=[]
            for note in self.notes():
                try:content=self.safe_note(note).read_text(encoding='utf-8')
                except UnicodeError:continue
                documents.append({'path':note,'content':content})
            return {'hits':ranked_notes(documents,q),'configured':self.root()is not None}
        if name=='commerce_summary_save':
            root=self.root()
            if root is None:raise ValueError('knowledge_not_configured')
            report_id=args['report_id']
            if not re.fullmatch('[a-f0-9]{20}',report_id):raise ValueError('invalid_report_id')
            with self.core.db() as c:row=c.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone()
            if row is None:raise ValueError('report_not_found')
            name='运营简报-'+report_id+'.md';target=root/name
            if target.is_symlink():raise ValueError('invalid_note_path')
            try:
                with target.open('x',encoding='utf-8') as f:f.write(row[3])
            except FileExistsError:
                if target.read_text()!=row[3]:raise ValueError('note_conflict')
            return {'saved':True,'path':name,'mode':row[2]}
        raise ValueError('unknown_tool')
