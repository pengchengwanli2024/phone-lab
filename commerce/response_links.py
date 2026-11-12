"""Trusted HTTP transport metadata; A2UI messages and domain state stay intact."""
from urllib.parse import urlencode


def with_workspace_link(tool, result, port):
    if not tool.startswith('commerce_a2ui_') or not isinstance(result, dict) or not result.get('surface_id'):
        return result
    binding=result.get('binding') or {}
    case_id=binding.get('case_id')
    query={'tab':'operations', **({'case_id':case_id} if case_id else {'surface':result['surface_id']})}
    url='http://127.0.0.1:'+str(port)+'/workspace?'+urlencode(query)
    label='打开当前商品成本工作台' if case_id else '打开本次成本工作台'
    return {**result, 'links':{'workspace':{'url':url,'requires_authentication':True}},
            'text':str(result.get('text',''))+'\n\n['+label+']('+url+')（需本机授权）'}
