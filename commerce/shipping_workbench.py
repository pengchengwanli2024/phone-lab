"""Private, immutable shipment estimates. No labels, bookings or marketplace writes."""
import csv
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from html import escape
import io
import json
import math
import re

from shipping_packing import candidates
from shipping_models import model_catalog, model_payload, normalize_model
from shipping_rates import parse_csv, quote, template as rates_template

ITEM_COLUMNS = ['group_id','recipient_ref','sku','quantity','length_cm','width_cm','height_cm','weight_kg','rotation_allowed','no_stack']
CARTON_COLUMNS = ['id','name','inner_length_cm','inner_width_cm','inner_height_cm','outer_length_cm','outer_width_cm','outer_height_cm','tare_kg','max_weight_kg','packaging_cost']
MODEL_COLUMNS = CARTON_COLUMNS + ['kind','model_id','door_width_cm','door_height_cm','reference_json']
READ_ONLY = frozenset('commerce_shipping_state commerce_shipping_template commerce_shipping_rates_preview commerce_shipping_input_preview commerce_shipping_compare commerce_shipping_plan_get commerce_shipping_export'.split())
COMPARE_MODELS = ('container-20gp','container-40gp','container-40hq')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def text(value, field, maximum=160, optional=False):
    if not isinstance(value,str) or len(value)>maximum or (not optional and not value.strip()) or any(ord(c)<32 for c in value):
        raise ValueError('shipping_invalid_'+field)
    return value.strip()


def csv_safe(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value


def csv_text(columns, rows):
    output=io.StringIO(newline='');writer=csv.writer(output)
    writer.writerow(columns)
    writer.writerows([[csv_safe(v) for v in row] for row in rows])
    return '\ufeff'+output.getvalue()


def csv_number(raw, field, row):
    try:value=Decimal(raw)
    except InvalidOperation:raise ValueError(f'shipping_csv_row_{row}_invalid_{field}') from None
    if not value.is_finite() or not 0<=value<=1000000 or value.as_tuple().exponent < -9:
        raise ValueError(f'shipping_csv_row_{row}_invalid_{field}')
    if field=='quantity':
        if value!=value.to_integral_value() or not 1<=value<=500:raise ValueError(f'shipping_csv_row_{row}_invalid_quantity')
        return int(value)
    return float(value)


class ShippingWorkbench:
    def __init__(self, core):
        self.core=core
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS shipping_rate_books(id TEXT PRIMARY KEY,document TEXT NOT NULL,created_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS shipping_plans(id TEXT PRIMARY KEY,document TEXT NOT NULL,created_at TEXT NOT NULL)')

    def state(self):
        with self.core.db() as db:
            books=[json.loads(r[0]) for r in db.execute('SELECT document FROM shipping_rate_books ORDER BY rowid DESC LIMIT 50')]
            plans=[json.loads(r[0]) for r in db.execute('SELECT document FROM shipping_plans ORDER BY rowid DESC LIMIT 20')]
        return {'model_catalog':model_catalog(),
                'rate_books':[{k:b[k] for k in ('id','sha256','source_ref','synthetic','created_at')} | {'rate_count':len(b['rates'])} for b in books],
                'plans':[{k:p[k] for k in ('id','sha256','created_at','mode','input_units','synthetic')} for p in plans]}

    def preview_rates(self, content, source_ref, synthetic=False):
        text(source_ref,'source_ref',500)
        if type(synthetic) is not bool:raise ValueError('shipping_invalid_synthetic')
        if not isinstance(content,str) or len(content.encode())>500000:raise ValueError('shipping_rate_file_limit')
        rates=parse_csv(content)
        sha=digest({'content':content,'source_ref':source_ref,'synthetic':synthetic})
        return {'sha256':sha,'rates':rates,'source_ref':source_ref,'synthetic':synthetic,'rate_count':len(rates)}

    def import_rates(self, content, source_ref, expected_sha256, synthetic=False):
        actual=digest({'content':content,'source_ref':source_ref,'synthetic':synthetic})
        if actual!=expected_sha256:raise ValueError('shipping_preview_changed')
        book=self.preview_rates(content,source_ref,synthetic)
        book.update(id='rates_'+actual[:24],created_at=datetime.now(timezone.utc).isoformat())
        with self.core.db() as db:
            db.execute('INSERT OR IGNORE INTO shipping_rate_books VALUES (?,?,?)',(book['id'],encoded(book),book['created_at']))
        return self.rate_book(book['id'])

    def rate_book(self, ident):
        text(ident,'rate_book_id')
        with self.core.db() as db:row=db.execute('SELECT document FROM shipping_rate_books WHERE id=?',(ident,)).fetchone()
        if row is None:raise ValueError('shipping_rate_book_not_found')
        return json.loads(row[0])

    @staticmethod
    def template(kind):
        if kind=='rates':content=rates_template()
        elif kind=='items':content=csv_text(ITEM_COLUMNS,[['BATCH-OR-ORDER-1','RECIPIENT-REF','DEMO-A',12,20,10,10,.4,'true','false'],['BATCH-OR-ORDER-1','RECIPIENT-REF','DEMO-B',8,10,10,10,.2,'true','false']])
        elif kind=='cartons':content=csv_text(CARTON_COLUMNS,[['DEMO-M','演示中箱',40,30,40,42,32,42,.9,20,6],['DEMO-S','演示小箱',40,30,20,42,32,22,.7,20,5]])
        elif kind=='models':
            rows=[]
            for row in model_catalog()['models']:
                if row['id'] not in ('carton-m','container-20gp'):continue
                rows.append([row['id'],row['name'],*row['inner_cm'],*row['outer_cm'],row['tare_kg'],row['max_weight_kg'],row['packaging_cost'],row['kind'],row['model_id'],*row.get('door_cm',['','']),encoded(row['reference'])])
            content=csv_text(MODEL_COLUMNS,rows)
        else:raise ValueError('shipping_invalid_template_kind')
        return {'filename':'shipping-'+kind+'-synthetic-template.csv','mime_type':'text/csv;charset=utf-8','content':content,'synthetic':True}

    @staticmethod
    def preview_input(kind, content):
        if kind not in ('items','cartons'):raise ValueError('shipping_invalid_input_kind')
        if not isinstance(content,str) or len(content.encode())>200000:raise ValueError('shipping_input_file_limit')
        columns=ITEM_COLUMNS if kind=='items' else CARTON_COLUMNS
        try:rows=list(csv.reader(io.StringIO(content.removeprefix('\ufeff')),strict=True))
        except csv.Error:raise ValueError('shipping_invalid_csv') from None
        if not rows or rows[0] not in ([columns] if kind=='items' else [CARTON_COLUMNS,MODEL_COLUMNS]) or not 1<=len(rows)-1<=(100 if kind=='items' else 12):raise ValueError('shipping_invalid_csv_columns_or_rows')
        columns=rows[0]
        result=[]
        for index,cells in enumerate(rows[1:],2):
            if len(cells)!=len(columns):raise ValueError(f'shipping_csv_row_{index}_column_count')
            row=dict(zip(columns,[x.strip() for x in cells]))
            if kind=='items':
                for key in ('rotation_allowed','no_stack'):
                    if row[key] not in ('true','false'):raise ValueError(f'shipping_csv_row_{index}_boolean')
                    row[key]=row[key]=='true'
                for key in ('quantity','length_cm','width_cm','height_cm','weight_kg'):
                    row[key]=csv_number(row[key],key,index)
                result.append(row)
            else:
                entry=({k:row[k] for k in ('id','name','packaging_cost')} |
                       {k:csv_number(row[k],k,index) for k in ('tare_kg','max_weight_kg')} |
                       {side+'_cm':[csv_number(row[side+'_'+axis+'_cm'],side+'_'+axis+'_cm',index) for axis in ('length','width','height')] for side in ('inner','outer')})
                for key in ('kind','model_id'):
                    if row.get(key):entry[key]=row[key]
                if row.get('door_width_cm') or row.get('door_height_cm'):
                    if not row.get('door_width_cm') or not row.get('door_height_cm'):raise ValueError(f'shipping_csv_row_{index}_invalid_door_cm')
                    entry['door_cm']=[csv_number(row[key],key,index) for key in ('door_width_cm','door_height_cm')]
                if row.get('reference_json'):
                    try:entry['reference']=json.loads(row['reference_json'])
                    except (ValueError,TypeError):raise ValueError(f'shipping_csv_row_{index}_invalid_reference_json') from None
                try:result.append(normalize_model(entry))
                except ValueError as exc:raise ValueError(f'shipping_csv_row_{index}_{exc}') from None
        # Full geometric validation is performed again when creating a plan.
        return {'kind':kind,'rows':result,'row_count':len(result),'sha256':digest(content)}

    @staticmethod
    def _plan_input(data, *, allow_empty_cartons=False):
        required={'mode','origin','destination','ship_date','packaging_currency','items','cartons'}
        if type(data) is not dict or not required<=set(data) or set(data)-required-{'rate_book_id','synthetic'}:raise ValueError('shipping_invalid_input')
        if len(encoded(data))>200000:raise ValueError('shipping_input_limit')
        if data['mode'] not in ('warehouse','buyer'):raise ValueError('shipping_invalid_mode')
        for k in ('origin','destination'):text(data[k],k,100)
        if not re.fullmatch('[A-Z]{3}',str(data['packaging_currency'])):raise ValueError('shipping_invalid_currency')
        if not isinstance(data['ship_date'],str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',data['ship_date']):raise ValueError('shipping_invalid_ship_date')
        date.fromisoformat(data['ship_date'])
        if type(data.get('synthetic',False)) is not bool:raise ValueError('shipping_invalid_synthetic')
        if not isinstance(data['items'],list) or not 1<=len(data['items'])<=100:raise ValueError('shipping_item_limit')
        if (type(data['cartons']) is not list or not (0 if allow_empty_cartons else 1)<=len(data['cartons'])<=12
                or any(type(row) is not dict for row in data['cartons'])):
            raise ValueError('packing_invalid_cartons')
        groups={};identities=set();sku_specs={};total=0
        for row in data['items']:
            if type(row) is not dict or set(row)-set(ITEM_COLUMNS) or not set(ITEM_COLUMNS[:-2])<=set(row):raise ValueError('shipping_invalid_item')
            group=text(row['group_id'],'group_id',128);recipient=text(row['recipient_ref'],'recipient_ref',128,optional=data['mode']=='warehouse')
            sku=text(row['sku'],'sku',128)
            if (group,sku) in identities:raise ValueError('shipping_duplicate_group_sku')
            identities.add((group,sku))
            spec=encoded({k:row.get(k,True if k=='rotation_allowed' else False) for k in ('length_cm','width_cm','height_cm','weight_kg','rotation_allowed','no_stack')})
            if sku in sku_specs and sku_specs[sku]!=spec:raise ValueError('shipping_sku_spec_conflict')
            sku_specs[sku]=spec
            quantity=row['quantity']
            try:q=Decimal(str(quantity))
            except Exception:raise ValueError('shipping_invalid_quantity') from None
            if isinstance(quantity,bool) or not q.is_finite() or q!=q.to_integral_value() or not 1<=q<=500:raise ValueError('shipping_invalid_quantity')
            for field in ('length_cm','width_cm','height_cm','weight_kg'):
                value=row[field]
                if (type(value) not in (int,float) or not 0<=value<=1000000 or not math.isfinite(value)
                        or (field!='weight_kg' and value==0)):
                    raise ValueError('packing_invalid_'+field)
            for field in ('rotation_allowed','no_stack'):
                if field in row and type(row[field]) is not bool:raise ValueError('packing_invalid_'+field)
            total+=int(q)
            entry=groups.setdefault(group,{'recipient_ref':recipient,'items':[]})
            if entry['recipient_ref']!=recipient:raise ValueError('shipping_recipient_conflict')
            entry['items'].append({k:v for k,v in row.items() if k not in ('group_id','recipient_ref')} | {'quantity':int(q),'sku':sku})
        if total>500 or len(groups)>20:raise ValueError('shipping_unit_or_group_limit')
        return groups,total

    def create_plan(self, data):
        return self.compute_plan(data,persist=True)

    def compute_plan(self, data, *, persist=False):
        """Use the same solver for a read-only preview or an immutable saved plan."""
        groups,total=self._plan_input(data)
        book=self.rate_book(data['rate_book_id']) if data.get('rate_book_id') else None
        variants={'space':[],'cost':[]};comparisons=[]
        for group,entry in groups.items():
            plans=candidates(entry['items'],data['cartons'])
            for plan in plans:
                quotes=[]
                if book and plan['complete']:
                    for rate in book['rates']:
                        result=quote(plan['boxes'],rate,mode=data['mode'],origin=data['origin'],destination=data['destination'],ship_date=data['ship_date'],packaging_currency=data['packaging_currency'])
                        if result['status']=='QUOTED':quotes.append(result)
                plan['quote']=min(quotes,key=lambda q:Decimal(q['total_cost'])) if quotes else None
            space=min(plans,key=lambda p:(not p['complete'],-p['placed_units'],p['total_outer_volume_cm3'],p['box_count']))
            quoted=[p for p in plans if p['complete'] and p['quote']]
            cost=min(quoted,key=lambda p:(Decimal(p['quote']['total_cost']),p['total_outer_volume_cm3'],p['box_count'])) if quoted else None
            for kind,choice in (('space',space),('cost',cost)):
                if choice is not None:variants[kind].append({**choice,'group_id':group,'recipient_ref':entry['recipient_ref']})
            comparisons.append({'group_id':group,'candidate_count':len(plans),'quoted_candidates':len(quoted)})
        def combine(parts):
            if len(parts)!=len(groups):return None
            all_quoted=all(p['quote'] for p in parts)
            def amount(key):return format(sum((Decimal(p['quote'][key]) for p in parts),Decimal(0)),'.2f') if all_quoted else None
            packaging=[b['packaging_cost'] for p in parts for b in p['boxes']]
            packaging_total=(format(sum((Decimal(cost).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) for cost in packaging),Decimal(0)),'.2f')
                             if all(cost!='' for cost in packaging) else None)
            if not persist and not all(p['complete'] for p in parts):packaging_total=None
            return {'groups':parts,'complete':all(p['complete'] for p in parts),'box_count':sum(p['box_count'] for p in parts),
                    'placed_units':sum(p['placed_units'] for p in parts),'total_outer_volume_cm3':sum(p['total_outer_volume_cm3'] for p in parts),
                    'gross_weight_kg':sum(b['gross_weight_kg'] for p in parts for b in p['boxes']),
                    'shipping_cost':amount('shipping_cost'),'packaging_cost':packaging_total,
                    'total_cost':amount('total_cost'),'currency':data['packaging_currency']}
        result={'mode':data['mode'],'input':data,'input_sha256':digest(data),'input_units':total,'comparisons':comparisons,
                'variants':{kind:combine(parts) for kind,parts in variants.items()},'rate_book_sha256':book['sha256'] if book else None,
                'source_ref':book['source_ref'] if book else None,'synthetic':data.get('synthetic',False) or bool(book and book['synthetic']),
                'review_required':True,'shipment_submitted':False,'optimality_proven':False,
                'notice':'有界启发式候选比较；商品直接装入所选箱型或柜型，省空间按外部总体积排序。总费用须具备完整费率和包装费；空白费用未知。参考尺寸须复测；柜门仅校验商品按放置朝向的宽高，不验证装载路径、倾斜、柜底承重或加固。',
                'created_at':datetime.now(timezone.utc).isoformat()}
        if not persist:result['persisted']=False
        result['sha256']=digest(result);result['id']=('shipping_' if persist else 'shipping_preview_')+result['sha256'][:24]
        if persist:
            with self.core.db() as db:db.execute('INSERT INTO shipping_plans VALUES (?,?,?)',(result['id'],encoded(result),result['created_at']))
        return result

    def compare(self, data):
        """Compare the same goods in three isolated container models without saving."""
        self._plan_input(data,allow_empty_cartons=True)
        book=self.rate_book(data['rate_book_id']) if data.get('rate_book_id') else None
        columns=[]
        for ident in COMPARE_MODELS:
            model=None
            try:
                matches=[row for row in data['cartons'] if row.get('model_id',row.get('id'))==ident]
                if len(matches)>1:raise ValueError('shipping_duplicate_model_'+ident)
                model=normalize_model({**matches[0],'model_id':ident}) if matches else model_payload(ident)
                plan=self.compute_plan(deepcopy(data) | {'cartons':[deepcopy(model)]})
                selected='cost' if plan['variants']['cost'] is not None else 'space'
                variant=plan['variants'][selected]
                boxes=[box for group in variant['groups'] for box in group['boxes']]
                def volume(dimensions):return math.prod(Decimal(str(value)) for value in dimensions)
                cargo=sum((volume(item['orientation_cm']) for box in boxes for item in box['items']),Decimal(0))
                capacity=sum((volume(box['inner_cm']) for box in boxes),Decimal(0))
                summary={key:variant[key] for key in ('box_count','placed_units','complete','currency')}
                summary.update(unplaced_units=plan['input_units']-variant['placed_units'],
                               cargo_volume_cm3=float(cargo),capacity_volume_cm3=float(capacity),
                               volume_utilization_pct=float(cargo/capacity*100) if capacity else None)
                summary.update({key:variant[key] if variant['complete'] else None
                                for key in ('shipping_cost','packaging_cost','total_cost')})
                columns.append({'model_id':ident,'model':model,'status':'ready','plan':plan,
                                'summary':summary,'selected_variant':selected})
            except ValueError as exc:
                summary={key:None for key in ('box_count','placed_units','unplaced_units','volume_utilization_pct',
                                             'shipping_cost','packaging_cost','total_cost','cargo_volume_cm3','capacity_volume_cm3')}
                summary.update(currency=data['packaging_currency'],complete=False)
                columns.append({'model_id':ident,'model':model,'status':'error','plan':None,
                                'summary':summary,'selected_variant':None,'error':str(exc)})
        return {'input_sha256':digest(data),'models':columns,'persisted':False,
                'notice':'同一批商品分别直接装入20GP、40GP、40HQ；仅为只读预览，未保存草稿、报价或提交发货。利用率按已装商品体积除以已用柜内体积加权；未装完时费用不可用，空白费用未知。参考值须复测。',
                'synthetic':data.get('synthetic',False) or bool(book and book['synthetic'])}

    def get_plan(self, ident):
        text(ident,'plan_id')
        with self.core.db() as db:row=db.execute('SELECT document FROM shipping_plans WHERE id=?',(ident,)).fetchone()
        if row is None:raise ValueError('shipping_plan_not_found')
        return json.loads(row[0])

    def export(self, ident, variant, format_, expected_sha256):
        plan=self.get_plan(ident)
        if plan['sha256']!=expected_sha256:raise ValueError('shipping_plan_changed')
        if variant not in ('space','cost') or not plan['variants'][variant]:raise ValueError('shipping_variant_unavailable')
        chosen=plan['variants'][variant]
        if format_ not in ('csv','json','html'):raise ValueError('shipping_invalid_export_format')
        columns=['plan_id','plan_sha256','mode','variant','synthetic','complete','group_id','recipient_ref','box_index','carton_id','sku','quantity','x_cm','y_cm','z_cm','length_cm','width_cm','height_cm','item_weight_kg','gross_weight_kg','outer_length_cm','outer_width_cm','outer_height_cm','rate_id','currency','group_total_cost','excluded_fees']
        columns+=['model_kind','model_id','door_width_cm','door_height_cm','model_reference_json','model_max_weight_kg','model_packaging_cost']
        rows=[]
        for group in chosen['groups']:
            tariff=group.get('quote') or {}
            for i,box in enumerate(group['boxes'],1):
                for item in box['items']:
                    door=box.get('door_cm',['',''])
                    rows.append([plan['id'],plan['sha256'],plan['mode'],variant,plan['synthetic'],chosen['complete'],group['group_id'],group['recipient_ref'],i,box['carton_id'],item['sku'],1,*item['position_cm'],*item['orientation_cm'],item['weight_kg'],box['gross_weight_kg'],*box['outer_cm'],tariff.get('rate_id',''),chosen['currency'],tariff.get('total_cost','待报价'),tariff.get('excluded_fees','待提供物流报价'),box.get('kind','carton'),box.get('model_id',''),*[float(v) if v!='' else '' for v in door],encoded(box['reference']) if 'reference' in box else '',box.get('max_weight_kg',''),box['packaging_cost']])
        if format_=='csv':body=csv_text(columns,rows);mime='text/csv;charset=utf-8'
        elif format_=='json':body=json.dumps({'plan':plan,'selected_variant':variant},ensure_ascii=False,indent=2);mime='application/json'
        else:
            heading='装箱草稿 · '+('省空间' if variant=='space' else '候选总费用最低')
            body='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>装箱单</title><style>body{font:14px sans-serif;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #aaa;padding:6px;text-align:left}section{break-inside:avoid;margin:24px 0}@media print{button{display:none}}</style><h1>'+heading+'</h1><p>'+escape(plan['notice'])+'</p><p>'+escape(plan['id'])+' / '+escape(plan['sha256'])+'</p><p>'+('合成演示 · ' if plan['synthetic'] else '')+('已装入全部商品' if chosen['complete'] else '部分商品未装入，禁止按完整装箱单执行')+'</p>'
            for group in chosen['groups']:
                for i,box in enumerate(group['boxes'],1):
                    counts={}
                    for item in box['items']:counts[item['sku']]=counts.get(item['sku'],0)+1
                    body+='<section><h2>'+escape(group['group_id'])+' / 第 '+str(i)+' 箱</h2><p>箱型 '+escape(box['carton_name'])+' · 外径 '+escape(' × '.join(map(str,box['outer_cm'])))+' cm · 毛重 '+escape(str(box['gross_weight_kg']))+' kg</p><table><tr><th>SKU</th><th>件数</th></tr>'+''.join('<tr><td>'+escape(sku)+'</td><td>'+str(qty)+'</td></tr>' for sku,qty in counts.items())+'</table></section>'
            body+='</html>';mime='text/html;charset=utf-8'
        return {'filename':ident+'-'+variant+'.'+format_,'content':body,'mime_type':mime,'plan_sha256':plan['sha256'],'content_sha256':hashlib.sha256(body.encode()).hexdigest()}

    def invoke(self,name,args):
        if name=='commerce_shipping_state':return self.state()
        if name=='commerce_shipping_template':return self.template(args['kind'])
        if name=='commerce_shipping_rates_preview':return self.preview_rates(args['content'],args['source_ref'],args.get('synthetic',False))
        if name=='commerce_shipping_rates_import':return self.import_rates(args['content'],args['source_ref'],args['expected_sha256'],args.get('synthetic',False))
        if name=='commerce_shipping_input_preview':return self.preview_input(args['kind'],args['content'])
        if name=='commerce_shipping_compare':return self.compare(args['input'])
        if name=='commerce_shipping_plan_create':return self.create_plan(args['input'])
        if name=='commerce_shipping_plan_get':return self.get_plan(args['plan_id'])
        if name=='commerce_shipping_export':return self.export(args['plan_id'],args['variant'],args['format'],args['expected_sha256'])
        raise ValueError('shipping_unknown_tool')


def definitions(schema):
    s={'type':'string','minLength':1,'maxLength':160}
    sha={'type':'string','pattern':'^[a-f0-9]{64}$'}
    intake={'content':{'type':'string','minLength':1,'maxLength':500000},'source_ref':{'type':'string','minLength':1,'maxLength':500},'synthetic':{'type':'boolean','default':False}}
    return [
        ('commerce_shipping_state','读取本机物流报价表版本与装箱草稿；不代表已发货',schema()),
        ('commerce_shipping_template','下载明确标注示例的报价、商品或箱型/柜型CSV模板；models含来源与柜门字段，cartons保留旧格式',schema({'kind':{'enum':['rates','items','cartons','models'],'type':'string'}},['kind'])),
        ('commerce_shipping_rates_preview','只读校验物流报价CSV；未知费用不得填零',schema(intake,['content','source_ref'])),
        ('commerce_shipping_rates_import','按预览哈希确认保存本机不可变物流报价表；不调用承运商',schema({**intake,'expected_sha256':sha},['content','source_ref','expected_sha256'])),
        ('commerce_shipping_input_preview','只读解析商品或箱型CSV；计算时再次验证尺寸与约束',schema({'kind':{'enum':['items','cartons'],'type':'string'},'content':{'type':'string','minLength':1,'maxLength':200000}},['kind','content'])),
        ('commerce_shipping_compare','只读并排比较同一批商品独立装入20GP、40GP、40HQ；保留当前实箱修改、分组、柜门和费用约束，不保存草稿或报价',schema({'input':{'type':'object'}},['input'])),
        ('commerce_shipping_plan_create','保存两模式、多SKU混装候选与运费试算；不是全局最优或发货回执',schema({'input':{'type':'object'}},['input'])),
        ('commerce_shipping_plan_get','读取不可变装箱草稿和关联报价版本',schema({'plan_id':s},['plan_id'])),
        ('commerce_shipping_export','导出哈希绑定的CSV/JSON/可打印HTML装箱草稿；不生成面单或发货',schema({'plan_id':s,'variant':{'type':'string','enum':['space','cost']},'format':{'type':'string','enum':['csv','json','html']},'expected_sha256':sha},['plan_id','variant','format','expected_sha256']))]
