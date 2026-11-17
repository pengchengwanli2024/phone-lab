"""Fit local llama.cpp prompts using its tokenizer, without sending an inference."""
import copy
import ipaddress
import json
from urllib.parse import urlsplit,urlunsplit
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def call(base,path,body,key):
    headers={'Content-Type':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    request=Request(base+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers=headers)
    with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=2)as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('local_tokenizer_response_limit')
    return json.loads(raw)


def excerpt(payload,limit):
    value=copy.deepcopy(payload)
    for observation in value.get('observations',[]):
        data=observation.get('data',{});tool=observation.get('tool')
        if tool=='commerce_web_search':
            data={k:v for k,v in data.items()if k in('status','query','groups','window','retrieved_beijing','independently_verified')}
            for group in data.get('groups',[]):
                group['items']=[{k:v for k,v in row.items()if k in('url','title','summary','publication_status','published_beijing')}for row in group.get('items',[])]
        elif tool=='commerce_web_read':
            data={k:v for k,v in data.items()if k in('status','items','window','retrieved_beijing','independently_verified')}
            data['items']=[{k:v for k,v in row.items()if k in('url','title','text','status','error','publication_status',
                'published_beijing','published_utc','retrieved_beijing','content_status','page_kind','article_candidates','structured_facts','text_truncated')}for row in data.get('items',[])]
        elif tool=='commerce_workspace_get':
            data={k:v for k,v in data.items()if k not in('artifacts','artifact_summary','history','quotes','delivery_package')}
            for stage in data.get('stages',[]):
                for gap in stage.get('gaps',[]):
                    for field in('reason','verify'):
                        if isinstance(gap.get(field),str)and len(gap[field])>limit:
                            gap[field]=gap[field][:limit];gap['model_excerpt_truncated']=True
        observation['data']=data;observation['model_view_of_full_observation']=True
    def trim(node):
        if isinstance(node,dict):
            for key,child in list(node.items()):
                if key in('text','summary','snippet','raw_excerpt')and isinstance(child,str)and len(child)>limit:
                    node[key]=child[:limit];node['model_excerpt_truncated']=True
                    if key=='text':node['text_truncated']=True
                elif key in('items','article_candidates','gaps')and isinstance(child,list):
                    # Keep every region/page and all typed fact records. Only
                    # individual search hits and optional link/gap samples shrink.
                    cap=(2 if 'region'in node else len(child))if key=='items'else 3
                    if len(child)>cap:
                        node[key]=child[:cap];node['model_'+key+'_total']=len(child);node['model_'+key+'_truncated']=True
                    trim(node[key])
                else:trim(child)
        elif isinstance(node,list):
            for row in node:trim(row)
    for observation in value.get('observations',[]):trim(observation.get('data',{}))
    history=value.get('conversation')
    if isinstance(history,list)and len(history)>2:
        value['conversation']=history[-2:];value['model_history_truncated']=True
    for row in value.get('conversation',[]):trim(row)
    value['model_context_note']='来源只在模型输入中作有标记的限量摘录；原读取、来源哈希和回执完整保留。不得推断未展示内容。'
    return value


def prepare(payload,instructions,config,max_tokens,cancelled):
    if cancelled():raise InterruptedError()
    parsed=urlsplit(config.get('base_url',''));host=parsed.hostname
    try:local=host=='localhost'or ipaddress.ip_address(host).is_loopback
    except ValueError:local=False
    if config.get('engine')!='llama_cpp'or not local:return payload,None
    base=urlunsplit((parsed.scheme,parsed.netloc,parsed.path.removesuffix('/v1').rstrip('/'),'',''))
    key=config.get('api_key','')
    needs_compaction=False
    try:
        ctx=call(base,'/props',None,key)['default_generation_settings']['n_ctx']
        if type(ctx)is not int or not 1024<=ctx<=262144:return payload,None
        def count(value):
            if cancelled():raise InterruptedError()
            messages=[{'role':'system','content':instructions},{'role':'user','content':json.dumps(value,ensure_ascii=False)}]
            prompt=call(base,'/apply-template',{'messages':messages},key)['prompt']
            if not isinstance(prompt,str):raise ValueError('invalid_template')
            tokens=call(base,'/tokenize',{'content':prompt,'parse_special':True},key)['tokens']
            if not isinstance(tokens,list):raise ValueError('invalid_tokenizer')
            return len(tokens)
        initial=count(payload);target=ctx-max_tokens-128;selected=payload;tokens=initial
        if tokens>target:
            needs_compaction=True
            for limit in(1200,700,350,160,80):
                selected=excerpt(payload,limit);tokens=count(selected)
                if tokens<=target:break
            else:raise ValueError('agent_model_context_limit')
        return selected,{'context_tokens':ctx,'original_prompt_tokens':initial,'prompt_tokens':tokens,
                         'output_reserved_tokens':max_tokens,'compacted':selected is not payload}
    except InterruptedError:raise
    except (KeyError,TypeError,OSError,ValueError)as error:
        if str(error)=='agent_model_context_limit':raise
        if needs_compaction:raise ValueError('agent_model_context_limit')from None
        # Other compatible servers may omit these optional metadata endpoints.
        # Their existing guarded transport remains authoritative; no retry occurs.
        return payload,None
