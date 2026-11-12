"""Reviewed function-only bridges to pinned upstream offline algorithms.

No upstream CLI, network function, persistent database writer or report writer
is invoked. The parent supplies registered files with verified package hashes.
This is a fixed dispatch bridge, not an operating-system sandbox.
"""
import ast
from datetime import date
import json
import math
from pathlib import Path
import sys
import types

OPERATIONS={
 'walmart_boxes':('check_box_manifest.py',{'json','sys','collections','pathlib'}),
 'ca_budget':('budget_mix_check.py',{'__future__','argparse','json','math','pathlib','typing'}),
 'apollo_ads':('ad_economics.py',{'argparse','json','math','pathlib'}),
 'discounts':('discount_plan.py',{'argparse','json','math','pathlib'}),
 'titles':('check_titles.py',{'argparse','csv','json','re','pathlib'}),
 'snapshots':('snapshots.py',{'argparse','html','json','math','os','re','sqlite3','datetime','pathlib'}),
 'prime_insights':('filter_insights.py',{'__future__','argparse','csv','json','collections','pathlib','typing'}),
 'mpstats_audit':('validate_data.py',{'argparse','datetime','json','math','pathlib','re','zoneinfo'})}


def tree_for(operation,text):
    if operation not in OPERATIONS:raise ValueError('sealeap_unknown_offline_operation')
    tree=ast.parse(text);nodes=[]
    for node in tree.body:
        # check(document, ...) does not use the sibling module's JSON reader.
        # Strip that single import, so its network-capable sibling is never loaded.
        if operation=='mpstats_audit' and isinstance(node,ast.ImportFrom) and node.module=='mpstats_read':
            if [(a.name,a.asname) for a in node.names]!=[('parse_json',None)]:raise ValueError('sealeap_unreviewed_sibling_import')
            continue
        if isinstance(node,ast.If):
            if ast.unparse(node.test) not in ["__name__ == '__main__'", "'__main__' == __name__"]:raise ValueError('sealeap_unreviewed_module_statement')
            continue
        if not isinstance(node,(ast.Import,ast.ImportFrom,ast.FunctionDef,ast.Assign,ast.AnnAssign,ast.Expr)):raise ValueError('sealeap_unreviewed_module_statement')
        if isinstance(node,ast.Expr) and not (isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)):raise ValueError('sealeap_unreviewed_module_statement')
        nodes.append(node)
    tree.body=nodes;imports=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):imports.update(a.name.split('.')[0] for a in node.names)
        if isinstance(node,ast.ImportFrom):imports.add((node.module or '').split('.')[0])
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'exec','eval','compile','__import__'}:raise ValueError('sealeap_dynamic_upstream_code')
    if imports-OPERATIONS[operation][1]:raise ValueError('sealeap_unreviewed_offline_import')
    return tree


def load(operation,path):
    if path.name!=OPERATIONS[operation][0]:raise ValueError('sealeap_wrong_offline_script')
    tree=tree_for(operation,path.read_text());module=types.ModuleType('reviewed_sealeap_offline');module.__file__=str(path)
    exec(compile(tree,str(path),'exec'),module.__dict__)
    return module


def run(operation,module,data):
    if not isinstance(data,dict):raise ValueError('sealeap_input_object_required')
    if operation=='walmart_boxes':
        result=module.validate(data);return dict(result,status='READY_FOR_REVIEW' if result['ok'] else 'HOLD')
    if operation=='ca_budget':
        product,stage=data.get('product'),data.get('stage')
        if product not in module.BASELINES or stage not in module.BASELINES[product]:raise ValueError('sealeap_budget_product_stage_required')
        allocation=data.get('allocation');errors=[]
        if not isinstance(allocation,dict) or not allocation:raise ValueError('sealeap_explicit_allocation_required')
        for value in allocation.values():
            if type(value) not in [int,float] or not math.isfinite(value) or value<0:raise ValueError('sealeap_invalid_budget_percentage')
        total=sum(allocation.values());baseline=module.BASELINES[product][stage]
        if not math.isclose(total,100,abs_tol=.01):errors.append('allocation_total_must_be_100')
        return dict(status='HOLD' if errors else 'DRAFT',product=product,stage=stage,total_pct=total,errors=errors,
            comparison={k:dict(course_baseline_pct=baseline.get(k),proposed_pct=allocation.get(k)) for k in sorted(set(baseline)|set(allocation))},
            boundary='Historical course comparison only; not a current account budget recommendation or launch approval.')
    if operation=='apollo_ads':return module.calculate(data)
    if operation=='discounts':return module.plan(data)
    if operation=='titles':
        rows=data.get('rows');policy=data.get('policy')
        if not isinstance(rows,list) or not 1<=len(rows)<=500 or not isinstance(policy,dict):raise ValueError('sealeap_title_rows_policy_required')
        for row in rows:
            if not isinstance(row,dict) or any(not isinstance(row.get(k),str) for k in ['sku','marketplace','product_type','title','highlight']):raise ValueError('sealeap_title_fields_required')
        results=[dict(row,**module.check(row,policy)) for row in rows]
        counts={s:sum(row['check_status']==s for row in results) for s in ['PASS','FAIL','HOLD']}
        return dict(status='HOLD' if counts['HOLD'] or counts['FAIL'] else 'DRAFT',counts=counts,rows=results,policy_authenticity='caller_declared_not_independently_verified',submitted=False)
    if operation=='snapshots':
        records=data.get('records')
        if not isinstance(records,list) or not 1<=len(records)<=500:raise ValueError('sealeap_snapshot_records_required')
        rows=[module.normalized(row) for row in records];rows.sort(key=lambda row:row['captured_at']);last={};changes=[];seen={}
        for row in rows:
            key=tuple(row[k] for k in ['own_asin','marketplace','asin','source','data_mode']);identity=key+(row['captured_at'],)
            frozen=json.dumps(row,sort_keys=True,ensure_ascii=False,allow_nan=False)
            if identity in seen:
                if seen[identity]!=frozen:raise ValueError('sealeap_snapshot_identity_conflict')
                continue
            seen[identity]=frozen
            if key in last:changes.append(dict(asin=row['asin'],captured_at=row['captured_at'],changes=module.changes(last[key],row)))
            last[key]=row
        return dict(status='DRAFT',snapshots=len(seen),comparisons=changes,persistent_monitor_started=False,source_authenticity='caller_declared_not_independently_verified')
    if operation=='prime_insights':
        filters={k:data.get(k) for k in ['marketplace','metric','ad_product','contains']}
        if any(value is not None and (not isinstance(value,str) or len(value)>200) for value in filters.values()):raise ValueError('sealeap_invalid_insight_filter')
        selected=module.select(module.load_rows(),**filters)
        return dict(status='REFERENCE_ONLY' if selected else 'HOLD',historical_reference_period='2025',records=[dict(csv_line=line,**row) for line,row in selected],current_policy_or_performance_verified=False)
    if operation=='mpstats_audit':
        if not isinstance(data.get('document'),dict):raise ValueError('sealeap_mpstats_document_required')
        as_of=date.fromisoformat(data['as_of']);age=data.get('max_age_days',7)
        if type(age) is not int or not 0<=age<=365:raise ValueError('sealeap_invalid_freshness_days')
        return dict(module.check(data['document'],as_of,age),assessed_as_of=as_of.isoformat(),api_contacted=False)
    raise ValueError('sealeap_unknown_offline_operation')


if __name__=='__main__':
    try:
        operation,path,input_file=sys.argv[1:];result=run(operation,load(operation,Path(path)),json.loads(Path(input_file).read_text()))
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));raise SystemExit(2 if result.get('status') in ['HOLD','INVALID','FAIL'] else 0)
    except (ValueError,TypeError,KeyError,OSError,OverflowError) as error:
        print(json.dumps({'status':'INVALID','error_type':type(error).__name__,'error':str(error)[:500] if isinstance(error,ValueError) else 'Input fields do not match this offline contract.'}));raise SystemExit(1)
