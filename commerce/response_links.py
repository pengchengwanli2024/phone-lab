"""Trusted HTTP transport metadata; A2UI messages and domain state stay intact."""
from urllib.parse import urlencode


def with_workspace_link(tool, result, port):
    if isinstance(result,dict) and (tool.startswith('commerce_market_research_') or tool in ('commerce_copilot_get','commerce_copilot_send','commerce_task_result')):
        job=result if result.get('schema')=='commerce-market-research-v1' else result.get('research_job')
        if isinstance(job,dict) and job.get('task_id'):
            query=urlencode({'tab':'pilots','research_task_id':job['task_id']})
            url='http://127.0.0.1:'+str(port)+'/workspace?'+query
            text='研究任务 '+job['task_id']+' · '+str(job.get('status','unknown'))+'\n'
            text+='已采集 '+str(job.get('source_count',0))+' 个来源，已保存 '+str(job.get('candidate_count',0))+' 个候选。\n'
            text+=(job.get('report') or {}).get('summary','')
            text+='\n[继续同一研究任务]('+url+')（需本机授权）'
            return {**result,'links':{'workspace':{'url':url,'requires_authentication':True}},'text':text}
    if not tool.startswith('commerce_a2ui_') or not isinstance(result, dict) or not result.get('surface_id'):
        return result
    binding=result.get('binding') or {}
    case_id=binding.get('case_id')
    query={'tab':'operations', **({'case_id':case_id} if case_id else {'surface':result['surface_id']})}
    url='http://127.0.0.1:'+str(port)+'/workspace?'+urlencode(query)
    label='打开当前商品成本工作台' if case_id else '打开本次成本工作台'
    return {**result, 'links':{'workspace':{'url':url,'requires_authentication':True}},
            'text':str(result.get('text',''))+'\n\n['+label+']('+url+')（需本机授权）'}
