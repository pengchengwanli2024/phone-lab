"""Versioned references for an explicit send; selection never grants execution."""
import copy
import hashlib
import re
from agent_runtime.policy import canonical
from .context import CONTEXT_SCHEMA, MODULES, validate_context

SCHEMA='commerce-copilot-capabilities-v1'
LABELS=dict(zip(MODULES,('运营台','订单','库存','成本与补货','经营提醒','客服','经营分析','选品与研究','全球情报','内容制作','商品候选','执行记录','经营关联','商品工作区','任务','平台数据','Ozon 经营','技能库','能力与连接')))
IDS_SCHEMA={'type':'array','maxItems':6,'uniqueItems':True,'items':{'type':'string','maxLength':180,'pattern':r'^(skill|plugin|mcp|tool|extension):[A-Za-z0-9_.-]+$'}}


def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def definitions(schema,string):
    return [
        ('commerce_copilot_capabilities','读取本项目已登记模块、技能、工具、插件及MCP条件；不安装或执行',schema({'context':CONTEXT_SCHEMA,'query':{'type':'string','maxLength':100},'offset':{'type':'integer','minimum':0,'maximum':10000},'limit':{'type':'integer','minimum':1,'maximum':30}},['context'])),
        ('commerce_copilot_capability_check','只读核对本轮选择的真实版本与条件；不请求模型或外部工具',schema({'context':CONTEXT_SCHEMA,'capability_ids':IDS_SCHEMA},['context','capability_ids'])),
    ]


class CopilotCapabilities:
    def __init__(self,copilot):self.copilot=copilot;self.service=copilot.service

    @staticmethod
    def ids(value):
        if not isinstance(value,list) or len(value)>6 or any(not isinstance(v,str) or not re.fullmatch(r'(skill|plugin|mcp|tool|extension):[A-Za-z0-9_.-]{1,160}',v) for v in value) or len(set(value))!=len(value):
            raise ValueError('copilot_invalid_capability_selection')
        return sorted(value)

    def _registry(self):
        rows=[dict(id='mcp:commerce',kind='mcp',name='共享电商 MCP',description='使用当前业务范围内的共享只读工具。',status='available',selectable=True,selection_effect='scoped_read_tools',version='1'),
              dict(id='tool:public-web',kind='tool',name='公开网页检索',description='检索公开资料并读取来源正文；来源仍需核对。',status='registered',selectable=True,selection_effect='existing_public_reads',version='1')]
        for item in self.service.media_plugins.catalog()['connections']:
            provider=item['provider'];ready=item.get('status')=='available_to_host'
            rows.append(dict(id='plugin:'+provider,kind='plugin',name={'lovart':'Lovart','heygen':'HeyGen'}.get(provider,provider),description='在已连接的宿主中继续制作；本轮选择只保留插件偏好。',status='host_only' if ready else 'needs_setup',selectable=ready,selection_effect='host_preference_only',version=str(item.get('revision',0))))
        for item in self.service.extensions.invoke('commerce_extension_list',{})['items']:
            doc=item['definition'];transport=doc.get('spec',{}).get('transport')
            kind='mcp' if transport=='mcp_http' else item['kind']
            ready=bool(item['enabled'] and item['test_status']=='passed')
            rows.append(dict(id='extension:'+item['id'],kind=kind,name=item['name'][:160],description='已登记的项目能力；执行沿原能力页面及其范围核对。',status='reference_available' if ready else 'disabled',selectable=ready,selection_effect='registered_method_reference',version=str(item['version'])))
        for item in self.service.skills.entries.values():
            rows.append(dict(id='skill:'+item['id'],kind='skill',name=item['title'][:160],description=item['description'][:400],status='source_registered',selectable=True,selection_effect='pinned_method_reference',version=item['source_sha256']))
        return rows

    def catalog(self,context,query='',offset=0,limit=20):
        validate_context(context)
        if not isinstance(query,str) or len(query)>100 or any(ord(c)<32 for c in query) or type(offset) is not int or not 0<=offset<=10000 or type(limit) is not int or not 1<=limit<=30:raise ValueError('copilot_invalid_capability_query')
        terms=query.casefold().split()
        match=lambda row:all(term in ' '.join(str(v) for v in row.values()).casefold() for term in terms)
        rows=[row for row in self._registry() if match(row)]
        modules=[dict(id=module,label=LABELS[module],description=LABELS[module]+'范围内的问题与资料') for module in MODULES]
        return dict(schema=SCHEMA,modules=[m for m in modules if match(m)],items=rows[offset:offset+limit],total=len(rows),offset=offset,next_offset=offset+limit if offset+limit<len(rows) else None,external_execution_allowed=False)

    def check(self,context,capability_ids):
        context=validate_context(context);ids=self.ids(capability_ids)
        registry={item['id']:item for item in self._registry()};items=[];issues=[]
        method_budget=12000//max(1,sum(ident.startswith('skill:') for ident in ids))
        for ident in ids:
            if ident not in registry:raise ValueError('copilot_unknown_capability')
            row=copy.deepcopy(registry[ident])
            if ident.startswith('skill:'):
                source=self.service.skills.get(ident.removeprefix('skill:'))
                if not source.get('integrity') or not isinstance(source.get('skill_text'),str):
                    row.update(status='source_unavailable',selectable=False)
                else:
                    clipped=source['skill_text'].encode()[:min(6000,method_budget)].decode('utf8',errors='ignore')
                    row.update(method_text=clipped,method_truncated=clipped!=source['skill_text'],instructions_are_untrusted_data=True,source_sha256=source['source_sha256'])
            elif ident=='mcp:commerce':
                from .reads import menu
                row['tools']=[item['tool'] for item in menu(context)]
            elif ident=='tool:public-web':row['tools']=['commerce_web_search','commerce_web_read']
            elif ident.startswith('extension:'):
                source=self.service.extensions.get(ident.removeprefix('extension:'))
                row['definition_sha256']=digest(source['definition'])
                row['instructions_are_untrusted_data']=True
                row['method_steps']=[{'id':step['id'],'uses':{k:v for k,v in step.get('uses',{}).items() if k in ('builtin','extension')}} for step in source['definition']['spec'].get('steps',[])][:20]
            if not row['selectable']:issues.append(dict(id=ident,code=row['status']))
            items.append(row)
        value=dict(schema=SCHEMA,capability_ids=ids,capabilities=items,context_sha256=digest(context),available=not issues,issues=issues,external_execution_allowed=False)
        value['selection_sha256']=digest(value)
        return value

    def freeze(self,context,capability_ids=None,expected_capability_sha256=None):
        if capability_ids is None:
            if expected_capability_sha256 is not None:raise ValueError('copilot_invalid_capability_selection')
            return None
        value=self.check(context,capability_ids)
        if not value['available']:raise ValueError('copilot_capability_unavailable')
        if not isinstance(expected_capability_sha256,str) or value['selection_sha256']!=expected_capability_sha256:raise ValueError('copilot_capability_changed')
        return value

    def invoke(self,name,args):
        from inspect import signature
        method={'commerce_copilot_capabilities':self.catalog,'commerce_copilot_capability_check':self.check}.get(name)
        if method is None:raise ValueError('unknown_tool')
        if not isinstance(args,dict):raise ValueError('copilot_invalid_arguments')
        try:signature(method).bind(**args)
        except TypeError:raise ValueError('copilot_invalid_arguments') from None
        return method(**args)
