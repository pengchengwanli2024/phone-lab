"""Owned subprocess and bounded HTTP transport; never exposes server diagnostics."""
from pathlib import Path
import json,os,re,subprocess,sys,time

class Cancelled(Exception):pass

def _public_read_requested(payload):
    question=payload.get('question','')
    if (not isinstance(question,str) or payload.get('observations')
            or payload.get('evidence_required',True) is False):return False
    if re.search(r'如何|怎么|什么是',question):return False
    clauses=re.split(r'[，,。；;！？!?\n]',question)
    reads=[clause for clause in clauses if re.search(r'检索|搜索|查询|查找|读取',clause)]
    if any(re.search(r'不要|无需|不必|禁止|别',clause)for clause in reads):return False
    return bool(reads and
                re.search(r'USGS|GDACS|公开|网络|互联网|新闻|要闻|政策|https?://',question,re.I))

def _public_body_required(payload):
    if (not _public_read_requested({**payload,'observations':[]})
            or not re.search(r'读取|正文|原文',payload['question'])):return False
    observations=payload.get('observations',[])
    if any(item.get('tool')=='commerce_web_read' for item in observations):return False
    from public_web import result_urls
    return any(item.get('tool')=='commerce_web_search' and result_urls(item.get('data',{}))
               for item in observations)

def _unread_article_targets(payload):
    if (not _public_read_requested({**payload,'observations':[]})
            or not re.search(r'原文|正文',payload.get('question',''))):return []
    pages=[page for observation in payload.get('observations',[])
           if observation.get('tool')=='commerce_web_read'
           for page in observation.get('data',{}).get('items',[])]
    if any(page.get('status')=='ready'and page.get('page_kind')=='article'for page in pages):return []
    attempted={page.get('url')for page in pages}
    return list(dict.fromkeys(link['url']for page in pages if page.get('status')=='ready'
        for link in page.get('article_candidates',[])if isinstance(link.get('url'),str)
        and link['url']not in attempted))[:8]

def invoke_json(payload,cancelled,config,instructions,max_tokens=2200,output_schema=None):
    if cancelled():raise Cancelled()
    from generative.streaming import enabled
    request={'base_url':config['base_url'],'model':config['model'],'api_key':config.get('api_key',''),'json_mode':config.get('json_mode',True),'instructions':instructions,'payload':payload,'max_tokens':max_tokens,'output_schema':output_schema}
    if enabled():request['stream']=True
    encoded=json.dumps(request,ensure_ascii=False)
    if len(encoded.encode())>150000:raise ValueError('agent_model_input_too_large')
    allowed={'PATH','HOME','TMPDIR','LANG','LC_ALL','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR'}
    env={k:v for k,v in os.environ.items() if k in allowed}
    process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        if enabled():
            from generative.process import receive
            return receive(process,encoded,cancelled,Cancelled,timeout=90)
        first=True;end=time.monotonic()+90
        while True:
            if cancelled():raise Cancelled()
            if time.monotonic()>end:raise ValueError('agent_provider_outcome_unknown')
            try:output,_=process.communicate(input=encoded if first else None,timeout=.2);break
            except subprocess.TimeoutExpired:first=False
        if len(output)>50000:raise ValueError('agent_model_response_too_large')
        try:result=json.loads(output)
        except ValueError:raise ValueError('agent_model_invalid_json') from None
        if process.returncode:raise ValueError(result.get('error','agent_provider_failed_no_automatic_retry'))
        return result
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream:stream.close()

def invoke(payload,cancelled,config):
    from agent_runtime.model_worker import SYSTEM,LOCAL_STRUCTURED_SYSTEM
    if config.get('engine') in ('llama_cpp','vllm') and config.get('json_mode',True):
        from agent_runtime.codex_provider import schema
        from .decision_contract import object_schema,arguments_schema,required_read,restrict_proposals,decode,requested_period
        public_analysis=_public_read_requested({**payload,'observations':[]})
        from public_web import explicit_urls
        direct_urls=explicit_urls(payload.get('question',''))[:3]if public_analysis and re.search(r'读取|正文|原文',payload.get('question',''))else[]
        attempted=any(item.get('tool')=='commerce_web_read'for item in payload.get('observations',[]))
        article_targets=_unread_article_targets(payload)
        # The host renders typed observations and receipts; local inference only
        # chooses a bounded read or writes an answer, without a second UI task.
        spec=schema(payload.get('observations',[]),generative=False)
        payload={key:value for key,value in payload.items()if key!='ui_catalog'}
        inspect,answer=spec['properties']['decision']['anyOf']
        inspect['properties']['calls'].update(minItems=1,maxItems=2)
        answer['properties']['answer']={**answer['properties']['answer'],'minLength':1,'maxLength':5000}
        answer['properties']['questions'].update(maxItems=3)
        # Match the parent question contract before constrained generation.
        answer['properties']['questions']['items']={'type':'string','minLength':1,'maxLength':400}
        answer['properties']['proposals'].update(maxItems=0 if public_analysis else 3)
        if not payload.get('observations') and payload.get('evidence_required',True):answer['properties']['questions']['minItems']=1
        restrict_proposals(answer,payload,public_analysis)
        from .grounded_answers import answer_text
        grounded=answer_text(payload)
        if grounded:
            answer['properties']['answer']={'type':'string','enum':[grounded]}
            if not any(o.get('data',{}).get('status')=='HOLD'and o.get('tool')in('commerce_unit_economics','commerce_restock_plan')for o in payload.get('observations',[])):
                answer['properties']['questions']['maxItems']=0
        menu=payload.get('tools',[])
        if menu:
            direct_required=bool(direct_urls and not attempted)
            body_required=(direct_required or bool(article_targets) or _public_body_required(payload)) and any(call['tool']=='commerce_web_read' for call in menu)
            fixed_read=required_read(payload,public_analysis)
            variants=[]
            for call in menu:
                if body_required and call['tool']!='commerce_web_read':continue
                if fixed_read and call['tool']!=fixed_read:continue
                arguments=arguments_schema(call,payload)
                if arguments is None:continue
                if direct_required and call['tool']=='commerce_web_read':
                    arguments={'type':'object','enum':[{'urls':direct_urls,'period':requested_period(payload)or'any'}]}
                elif article_targets and call['tool']=='commerce_web_read':
                    arguments['properties']['urls']['items']['enum']=article_targets
                shape=object_schema({'tool':{'type':'string','enum':[call['tool']]},'arguments':arguments})
                variants.append(shape)
            if variants:inspect['properties']['calls']['items']={'anyOf':variants}
            else:spec['properties']['decision']['anyOf']=[answer]
            if body_required or fixed_read:inspect['properties']['calls']['maxItems']=1
            # An explicit public-read request already authorizes a scoped read.
            # Small models otherwise repeatedly promise to search without issuing
            # a call, even after the user has supplied the requested time range.
            if variants and (_public_read_requested(payload)or body_required or fixed_read):spec['properties']['decision']['anyOf']=[inspect]
            if direct_urls and attempted and not body_required:spec['properties']['decision']['anyOf']=[answer]
            if grounded and not body_required and not fixed_read:spec['properties']['decision']['anyOf']=[answer]
        else:spec['properties']['decision']['anyOf']=[answer]
        instructions=LOCAL_STRUCTURED_SYSTEM+'''
For an explicit public-search/read request, issue the allowed read rather than
asking permission. Use the stated date/window; for an unspecified latest-news
window use 7d and state it. Ask only when an essential query subject is missing.
Use Chinese status labels: search_summary_only means 仅搜索摘要, unconfirmed means
发布时间待核对, and independently_verified:false means 未独立核实. A failed body
read does not verify a search summary. Do not claim that a report is saved:
the application displays the real local-task receipt after your answer.
Inspect calls use a typed arguments object, not an encoded arguments_json string.
When calculator input or a selected work item is supplied, read it first instead
of asking whether the user wants the result. Explain actual calculator output;
for HOLD ask only for fields listed in missing, never ask the user what is missing.
如果来源提供 structured_facts，逐项使用这些已换算字段；震级、深度（千米）、
发生时间（UTC）、发生时间（北京时间 +08:00）、资料读取时间（北京时间 +08:00）
分别标明，不再从地点距离或原始时间戳猜测。automatic 表示自动处理、可能修订，
UTC转北京时间是否跨日，只按 utc_to_beijing_date_changed 回答：true 为日期变化，
false 为日期不变，null 为未知。这与查询窗口是否超过24小时无关。
reviewed 表示来源已审阅，两者都不是独立核实。HTTP 404 只表示本次地址未返回
记录，不能据此断言事件不存在、没有新闻或没有风险。读取失败时不编造数值或时间。
'''
        from .context_window import prepare
        if grounded and spec['properties']['decision']['anyOf']==[answer]:
            # Exact source-bound prose already lives in the answer grammar. The
            # final local turn needs references/proposals, not the same raw pages
            # twice. Full observations and hashes remain in the parent ledger.
            payload={**payload,'tools':[],'observations':[
                {key:o[key]for key in('id','tool','sha256')if key in o}
                for o in payload.get('observations',[])],
                'model_context_note':'答复正文已由本轮完整工具结果约束；只选择该正文及允许的任务草案，原观察完整保留。'}
        try:model_payload,input_budget=prepare(payload,instructions,config,2200,cancelled)
        except InterruptedError:raise Cancelled()from None
        result=invoke_json(model_payload,cancelled,config,instructions,output_schema=spec)
        decoded=decode(result['decision'])
        if grounded and decoded.get('phase')=='answer'and decoded.get('answer')!=grounded:
            raise ValueError('agent_model_invalid_response')
        return {**result,'decision':decoded,**({'input_budget':input_budget}if input_budget else{})}
    return invoke_json(payload,cancelled,config,SYSTEM)
