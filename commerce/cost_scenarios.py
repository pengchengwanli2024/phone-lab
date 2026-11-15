"""Immutable cost alternatives over original saved inputs and artifact storage."""
import json
from research import canonical, digest
from operations_analysis import unit_economics

def definitions(schema,string):
    return [
        ('commerce_cost_scenarios_get','比较同一商品已保存的成本情景；显示依据过期，不选用或更新当前测算',schema({'case_id':string},['case_id'])),
        ('commerce_cost_scenarios_save','从已保存且来源当前的成本参数固定一个情景；不修改报价、当前成本或店铺',schema({'case_id':string,'label':{'type':'string','maxLength':80},'expected_source_sha256':string,'expected_revision':{'type':'integer','minimum':1},'idempotency_key':string},['case_id','label','expected_source_sha256','expected_revision','idempotency_key'])),
    ]

class CostScenarios:
    def __init__(self,service):self.service=service;self.workspace=service.product_workspace;self.core=service.core
    def get(self,case_id):
        case,_,_,source=self.workspace.sources(case_id)
        from supply_quotes import selection_issues
        quote_stale=bool(selection_issues(self.workspace.org,case,self.workspace.org.artifact(case_id,'supply')))
        items=[]
        with self.core.db()as db:
            for ident,raw,sha,created in db.execute("SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind='cost_scenario'ORDER BY created DESC,id DESC LIMIT 20",(case_id,)):
                if digest(raw)!=sha:raise ValueError('cost_scenario_integrity')
                d=json.loads(raw)
                items.append(dict(id=ident,sha256=sha,created_at=created,**d,stale=d['source_sha256']!=source or quote_stale))
        return dict(case_id=case_id,items=items,source_sha256=source,currency=case['currency'],external_execution_allowed=False)
    def save(self,case_id,label,expected_source_sha256,expected_revision,idempotency_key):
        if type(label)is not str or not 1<=len(label.strip())<=80:raise ValueError('cost_scenario_label_required')
        with self.core.atomic():
            case=self.workspace.guard(case_id,expected_source_sha256)
            from supply_quotes import selection_issues
            if selection_issues(self.workspace.org,case,self.workspace.org.artifact(case_id,'supply')):raise ValueError('workspace_quote_not_ready')
            saved=self.workspace.checkpoint(case_id,'cost',expected_source_sha256)
            if saved['revision']!=expected_revision:raise ValueError('form_draft_conflict')
            if saved['stale']or not saved['payload']:raise ValueError('workspace_cost_checkpoint_required')
            inputs=saved['payload']['input'];result=unit_economics(inputs)
            if result['status']!='CALCULATED':raise ValueError('cost_scenario_parameters_required')
            if not case['currency']or case['currency']!=inputs.get('currency'):raise ValueError('workspace_currency_required')
            payload=dict(label=label.strip(),input=inputs,result=result,source_sha256=expected_source_sha256,cost_revision=expected_revision)
            self.workspace.org._store(case_id,'cost_scenario',payload,idempotency_key)
        return self.get(case_id)
    def invoke(self,name,args):return (self.get if name.endswith('_get')else self.save)(**args)
