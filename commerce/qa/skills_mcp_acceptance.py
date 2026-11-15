"""Fresh stdio MCP checks, including a local-only missing-input generation gate."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime import STATE


def main():
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/'mcp_server.py'),'test'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    serial=0;checks=[]
    def rpc(method,params):
        nonlocal serial
        serial+=1;child.stdin.write(json.dumps(dict(jsonrpc='2.0',id=serial,method=method,params=params))+'\n');child.stdin.flush()
        reply=json.loads(child.stdout.readline());assert reply.get('id')==serial and 'error' not in reply
        return reply['result']
    def call(name,args={}):
        result=rpc('tools/call',dict(name=name,arguments=args));assert not result.get('isError'),name
        return json.loads(next(v['text'] for v in result['content'] if v['type']=='text'))
    try:
        rpc('initialize',{'protocolVersion':'2025-11-25'});table=rpc('tools/list',{})['tools'];tools={v['name']:v for v in table if v['name'].startswith('commerce_skills_')};assert len(tools)==14
        assert tools['commerce_skills_generate']['annotations']['openWorldHint'] is True
        assert tools['commerce_skills_draft_get']['annotations']['readOnlyHint'] is True
        assert tools['commerce_skills_draft_export']['annotations']['readOnlyHint'] is True
        checks.append('fresh actual MCP lists all 14 skill APIs and correct model/read-only annotations')
        status=call('commerce_skills_status');assert status['draft_workflow_entries']==778 and status['offline_adapters']==19
        entry=call('commerce_skills_get',{'skill_id':'sealeap-ebay-category-keywords'})
        case=call('commerce_skills_prepare',dict(skill_id=entry['id'],input=entry['draft_input_template'],synthetic=True,idempotency_key='mcp-workflow-empty-case-v1'))
        item=call('commerce_skills_generate',dict(case_id=case['id'],idempotency_key='mcp-workflow-empty-draft-v1'));assert item['status']=='needs_inputs' and item['result']['model_requested'] is False
        replay=call('commerce_skills_generate',dict(case_id=case['id'],idempotency_key='mcp-workflow-empty-draft-v1'));assert replay['id']==item['id']
        read=call('commerce_skills_draft_get',{'draft_id':item['id']});assert read['source_matches_current']
        call('commerce_skills_draft_cancel',{'draft_id':item['id']});export=call('commerce_skills_draft_export',dict(draft_id=item['id'],format='markdown'));assert '平台操作未执行' in export['content']
        checks.append('actual MCP prepare/generate/get/cancel/export and same-key replay preserve missing evidence without model submission')
        records=Path(os.environ.get('SKILLS_MODEL_SAMPLES',str(STATE.parent/'model-samples-private.json')))
        if records.exists():
            samples=json.loads(records.read_text());record=next((r for r in samples if r['family']=='finance'),samples[-1])
            draft=call('commerce_skills_draft_get',{'draft_id':record['draft_id']});assert draft['result']['sections'] and draft['result']['tools_enabled'] is False
            out=call('commerce_skills_draft_review',dict(draft_id=draft['id'],result_sha256=draft['result_sha256'],decision='reject',note='synthetic MCP review only'));assert out['review']['decision']=='reject'
            if draft['contract'].get('source_requirements'):
                assert {c['requirement_id'] for c in draft['result']['requirement_checks']}=={c['id'] for c in draft['contract']['source_requirements']}
                checks.append('fresh MCP reads exact original input/delivery requirement checks from an actual synthetic model result')
            checks.append('fresh MCP reads actual synthetic model result and records hash-bound caller rejection')
        result=dict(status='passed',synthetic=True,actual_stdio=True,checks=checks,platform_operations_executed=False);(STATE.parent/'mcp-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        child.stdin.close()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=5)
        child.stdout.close();child.stderr.close()


if __name__=='__main__':main()
