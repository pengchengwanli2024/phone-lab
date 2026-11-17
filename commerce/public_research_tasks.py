"""Explicit local archive of a completed public analysis, bound to original reads."""
import hashlib
import re
import copy
from research import canonical


def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def requested(question):
    if re.search(r'如何|怎么|什么是|解释|方法是什么',question):return False
    positive=False
    for clause in re.split(r'[，,。；;！？!?\n]',question):
        negative=re.search(r'不要|不必|无需|禁止|别',clause)
        archive=re.search(r'保存|归档|存档|(?:创建|建立|新建).{0,8}任务',clause)
        # A prohibition against store writes is not a prohibition against an
        # explicitly requested local report in another clause. Archive denials
        # still win, including contradictory positive/negative instructions.
        if negative and archive:return False
        if not negative and re.search(r'(?:保存|归档|存档).{0,14}(?:分析|结果|报告|简报|任务)|(?:创建|建立|新建).{0,8}(?:研究|情报|分析|简报|报告).{0,6}任务',clause):positive=True
    return positive


def public_sources(result):
    return [o for o in result.get('observations',[])if o['tool']in ('commerce_web_search','commerce_web_read')]


def retained_answer(service,payload):
    question=payload['question']
    if not(payload.get('parent_id')and requested(question)and re.search(r'上面|上述|刚才|前面|这份|这个|那份',question))or re.search(r'查询|检索|搜索|重新|更新|再查|改写|修改|翻译|补充',question):return None
    parent=service.agent_runtime.get(payload['parent_id'])
    result=parent.get('result')or{}
    if parent['status']not in ('completed','awaiting_input')or not public_sources(result):return None
    return {'answer':'本轮保存上一轮分析及其原始来源，执行状态和结果见下方任务回执。','questions':[],'proposals':[],
            'generator':'retained_public_analysis','provider':'local','model':'原分析归档','independently_verified':False,'review_status':'pending_review',
            'evidence_refs':list(result['evidence_refs']),'observations':copy.deepcopy(result['observations']),
            'archive_of_run_id':parent['id']}


def proposal(service,run_id,payload,result):
    sources=public_sources(result)
    available=any(i for o in sources for g in o['data'].get('groups',[])for i in g.get('items',[]))or any(
        i.get('status')=='ready'for o in sources for i in o['data'].get('items',[]))
    if not requested(payload['question'])or result.get('questions')or not sources or not available:return None
    with service.core.db()as db:
        row=db.execute('SELECT thread_id FROM copilot_turns WHERE run_id=?',(run_id,)).fetchone()
    source_run_id=result.get('archive_of_run_id')or run_id
    source_answer=service.agent_runtime.get(source_run_id)['result']['answer']if source_run_id!=run_id else result['answer']
    return {'id':'P_archive','operation':'report','reason':'保存本轮公开研究简报','kind':'report',
            'input':{'title':'公开研究 · '+payload['question'][:90],'mode':'public_research','demo':False,
                     'source_run_id':source_run_id,'source_thread_id':row[0]if row else'',
                     'answer_sha256':sha(source_answer),'sources_sha256':sha(sources)},
            'requires_human_review':False,'authorization':'explicit_user_local_archive'}


def validate(data):
    if(not isinstance(data.get('source_run_id'),str)or not re.fullmatch('[a-f0-9]{32}',data['source_run_id'])or
       any(not isinstance(data.get(k),str)or not re.fullmatch('[a-f0-9]{64}',data[k])for k in ('answer_sha256','sources_sha256'))):
        raise ValueError('public_research_source_required')


def render(service,data):
    validate(data);run=service.agent_runtime.get(data['source_run_id']);result=run['result']or{};sources=public_sources(result)
    if sha(result.get('answer'))!=data['answer_sha256']or sha(sources)!=data['sources_sha256']:
        raise ValueError('public_research_source_changed')
    if any(sha(o['data'])!=o['sha256']for o in sources):raise ValueError('public_research_source_changed')
    links=[]
    for observation in sources:
        rows=[i for group in observation['data'].get('groups',[])for i in group['items']]+observation['data'].get('items',[])
        for row in rows:
            link=row.get('url')
            if not link:continue
            old=next((r for r in links if r['url']==link),None)
            projected={k:row[k]for k in ('publisher','published_at','published_beijing','publication_status','content_status')if row.get(k)is not None}
            if old:
                if row.get('status')=='ready'and row.get('content_status')in ('page_text','json_data'):old.update(projected)
            else:links.append({'title':row.get('title')or link,'url':link,**projected})
    pending=result.get('questions',[])
    return {'generator':'saved_public_analysis','analysis':result['answer'],'source_questions':pending,'sources':sources,'source_links':links,
            'source_run_id':run['id'],'source_result_sha256':run['result_sha256'],'independently_verified':False,
            'content':result['answer']+('\n\n原分析待补充\n'+'\n'.join(pending)if pending else'')+'\n\n来源\n'+'\n'.join(r['title']+'\n'+r['url']for r in links)}
