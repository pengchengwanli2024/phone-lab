"""Build a pinned, per-skill coverage index. Source snapshots remain private."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from sealeap_adapter_specs import FUNCTION_ADAPTERS, example_input
from sealeap_offline import tree_for
from sealeap_contracts import contract_for
from sealeap_methodology import method_for
from sealeap_input_sources import resolve as resolve_input_sources

ROOT=Path(__file__).resolve().parent
SOURCES={
    'ecommerce':('sealeap-ecommerce-skills','914f920b368fd73f867e3d03af7e48b9ab1e18ed'),
    'amazon':('sealeap-amazon-skills','1283764556e61cbe56c600bbe504b8731b2254cb')}
# Only reviewed, offline JSON-in/JSON-out scripts are exposed to execution.
ADAPTERS={
 'sealeap-tiktokshop-unit-economics':('unit_economics.py',False,'example-scenario.json'),
 'sealeap-mercadolibre-unit-economics':('unit_economics.py',False,'scenario.example.json'),
 'sealeap-wayfair-wholesale-economics':('wholesale_contribution.py',False,'example-scenario.json'),
 'sealeap-wayfair-order-multibox':('check_cartons.py',False,'example-cartons.json'),
 'sealeap-amazon-acos-diagnostics':('acos_diagnose.py',True,'acos-input.example.json'),
 'sealeap-amazon-listing-optimizer':('audit_listing.py',False,'listing-input.example.json'),
 'sealeap-amazon-product-targeting':('targeting_plan_check.py',True,'targeting-plan.example.json'),
 'sealeap-hermes-product-research':('unit_economics.py',False,'unit-economics.example.json'),
 'sealeap-amazon-creator-commission-planning':('commission_plan.py',False,'input.example.json'),
 'sealeap-amazon-fba-reimbursement-audit':('reconcile_reimbursements.py',False,'input.example.json'),
 'sealeap-amazon-sqp-period-reconciliation':('reconcile_sqp.py',False,'input.example.json')}


def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def audit_script(text):
    allowed={'__future__','argparse','json','math','pathlib','typing','sys','decimal','datetime','re','collections'}
    tree=ast.parse(text);imports=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):imports.update(a.name.split('.')[0] for a in node.names)
        if isinstance(node,ast.ImportFrom):imports.add((node.module or '').split('.')[0])
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'exec','eval','compile','__import__'}:
            raise ValueError('sealeap_dynamic_execution_not_allowed')
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'write_text','write_bytes','unlink','mkdir','rmdir','rename','replace'}:
            # String.replace is normal calculation/text normalization; only actual
            # filesystem write methods are disallowed here.
            if node.func.attr!='replace':raise ValueError('sealeap_script_write_not_allowed')
    if imports-allowed:raise ValueError('sealeap_script_import_not_reviewed')
    return sorted(imports)


def frontmatter(text,key):
    front=text.split('---',2)[1] if text.startswith('---') else ''
    match=re.search(r'^'+key+r':\s*(.*?)(?=\n[A-Za-z_][\w-]*:|\Z)',front,re.M|re.S)
    return re.sub(r'\s+',' ',match.group(1).strip().strip('"\'').lstrip('>|- ')) if match else ''


def build(source_root, output):
    records=[];repos=[];all_modes=[]
    for repo,(slug,commit) in SOURCES.items():
        root=(source_root/repo).resolve()
        actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
        if actual!=commit:raise ValueError('sealeap_source_revision_changed_review_before_updating')
        if subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=root).returncode:raise ValueError('sealeap_tracked_source_changed')
        license_text=(root/'LICENSE').read_text()
        if 'MIT License' not in license_text:raise ValueError('sealeap_license_not_verified')
        athena={};migrations={}
        if repo=='amazon':
            folder=root/'amazon-skills/app/athena'
            athena={r['name']:r for r in json.loads((folder/'catalog.json').read_text())['skills']}
            migrations={r['legacy_name']:r for r in json.loads((folder/'migration.json').read_text())['mappings']}
        count=0
        for skill in sorted(root.rglob('SKILL.md')):
            if '.git' in skill.parts:continue
            text=skill.read_text();name=frontmatter(text,'name')
            if not re.fullmatch(r'sealeap-[a-z0-9-]+',name) or name!=skill.parent.name:raise ValueError('sealeap_name_mismatch')
            files=[]
            for p in sorted(skill.parent.rglob('*')):
                if p.is_symlink():raise ValueError('sealeap_source_symlink')
                if not p.is_file() or '__pycache__' in p.parts:continue
                if not p.resolve().is_relative_to(root):raise ValueError('sealeap_source_escape')
                raw=p.read_bytes()
                if len(raw)>2*1024*1024:raise ValueError('sealeap_source_file_limit')
                if p.suffix in {'.md','.json','.yaml','.yml','.py','.csv','.txt'} or p.name in {'LICENSE','NOTICE'}:
                    raw.decode('utf-8') # Read every included text/reference/script, not just filenames.
                    files.append({'path':str(p.relative_to(skill.parent)),'sha256':sha(raw),'bytes':len(raw)})
            sections=[dict(heading=m.group(1).strip(),text=m.group(2).strip()) for m in re.finditer(r'^##\s+([^\n]+)\n(.*?)(?=^##\s|\Z)',text,re.M|re.S)]
            platform=skill.relative_to(root).parts[1] if repo=='ecommerce' else 'amazon'
            group=skill.relative_to(root).parts[1]
            if name in athena:
                platform=next((label for token,label in [('amazon','amazon'),('tiktok','tiktokshop'),('temu','temu'),('shopee','shopee'),('1688','1688')] if '-'+token+'-' in name),'cross_platform')
            modes=[]
            for mode in athena.get(name,{}).get('subcapabilities',[]):
                mapping=migrations[mode['name']];reference=str(Path(mapping['reference']).relative_to(name))
                if reference not in {f['path'] for f in files}:raise ValueError('sealeap_mode_reference_missing')
                item={k:mode.get(k) for k in ['name','title','description','category','mode','route','capabilities','limitation']}
                item.update(parent_skill_id=name,reference=reference,execution='external_requirements_not_verified')
                modes.append(item);all_modes.append(item)
            title=next((line[2:].strip() for line in text.splitlines() if line.startswith('# ')),name)
            adapter=None;example=None;review=None;inline_example=None
            if name in ADAPTERS:
                script,flag,ex=ADAPTERS[name];path=skill.parent/'scripts'/script
                review=audit_script(path.read_text());script_sha=sha(path.read_bytes())
                adapter={'script_sha256':script_sha,'script':'scripts/'+script,'input_flag':flag,'version':'offline-json-v1','extra_args':['--fail-on','hold'] if name=='sealeap-amazon-listing-optimizer' else []}
                adapter['id']=sha(canonical(adapter).encode())
                matches=[f['path'] for f in files if Path(f['path']).name==ex]
                example=matches[0] if matches else None
                if example is None:raise ValueError('sealeap_adapter_example_missing')
                json.loads((skill.parent/example).read_text())
            if name in FUNCTION_ADAPTERS:
                script,operation,scope=FUNCTION_ADAPTERS[name];path=skill.parent/'scripts'/script
                tree_for(operation,path.read_text())
                adapter=dict(script_sha256=sha(path.read_bytes()),script='scripts/'+script,runner=operation,scope=scope,version='function-json-v1',worker_sha256=sha((ROOT/'sealeap_offline.py').read_bytes()))
                adapter['id']=sha(canonical(adapter).encode());inline_example=example_input(operation,skill.parent)
            combined=(name+' '+title+' '+frontmatter(text,'description')).lower()
            area='advertising' if re.search(r'广告|投放|acos|ppc|campaign|ads|attribution',combined) else 'inventory' if re.search(r'库存|履约|补货|fba|fulfillment|stock|carton',combined) else 'creative' if re.search(r'视频|图片|文案|listing|创意|ugc|content|image',combined) else 'research' if re.search(r'选品|竞品|research|keyword|关键词|niche',combined) else 'operations'
            external=[label for needle,label in [('mpstats','MPstats'),('mcp','MCP工具资格'),('api','平台API或导出'),('账户','账户与数据权限'),('费用','当期费用口径')] if needle in text.lower()]
            digest=sha(canonical(files).encode())
            records.append(dict(id=name,repo=repo,platform=platform,group=group,title=title,description=frontmatter(text,'description'),area=area,
                commit=commit,path=str(skill.relative_to(root)),source_url=f'https://github.com/xjli360/{slug}/blob/{commit}/{skill.relative_to(root)}',
                source_sha256=digest,skill_sha256=sha(skill.read_bytes()),files=files,sections=sections,adapter=adapter,example=example,
                reviewed_imports=review,example_input_inline=inline_example,external_prerequisites=external,workbench_entry='能力库',subcapabilities=modes,source_review='structural_full_text_read_not_semantic_mastery',
                business_gaps=['full_skill_task_acceptance_required','current_policy_and_account_scope_not_verified'] if adapter else ['specialized_executor_not_connected','actual_task_data_and_output_acceptance_required']))
            count+=1
        repos.append(dict(id=repo,url='https://github.com/xjli360/'+slug,commit=commit,skills=count,license='MIT'))
    if len({r['id'] for r in records})!=len(records):raise ValueError('sealeap_duplicate_skill_id')
    for entry in records:
        folder=source_root/entry['repo']/Path(entry['path']).parent
        entry['input_sources']=resolve_input_sources(entry,lambda path:(folder/path).read_text())
        entry['source_method']=method_for(entry)
        entry['draft_contract']=contract_for(entry)
        if entry['draft_contract']:
            entry['business_gaps']=['actual_task_evidence_and_human_review_required','whole_skill_business_acceptance_pending']
            if entry['draft_contract']['family']=='operation_plan':entry['business_gaps'].append('authorized_account_execution_not_connected')
    result=dict(schema='sealeap-coverage-v1',sources=repos,skills=records,subcapabilities=all_modes,limits=['Structural full-text review is not semantic mastery or live execution validation.'])
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with (output.parent/'METHOD_COVERAGE.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['skill_id','source_sha256','method_sha256','input_candidates','mode_input_candidates','mode_selection_required','input_resolution','deliverable_candidates','procedure_candidates','boundary_candidates','extraction_gaps','semantic_review']);writer.writeheader()
        for entry in records:
            method=entry['source_method']
            writer.writerow(dict(skill_id=entry['id'],source_sha256=entry['source_sha256'],method_sha256=method['sha256'],input_candidates=len(method['inputs']),mode_input_candidates=sum(len(m['inputs']) for m in method['mode_methods'].values()),mode_selection_required=method['mode_selection_required'],input_resolution=method['input_resolution'],deliverable_candidates=len(method['deliverables']),procedure_candidates=len(method['procedures']),boundary_candidates=len(method['boundaries']),extraction_gaps=';'.join(method['extraction_gaps']),semantic_review='pending'))
    with (output.parent/'INPUT_RESOLUTION.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['skill_id','source_sha256','resolution','common_inputs','mode_count','mode_inputs','mode_selection_required','source_paths','semantic_acceptance']);writer.writeheader()
        for entry in records:
            resolved=entry['input_sources'];method=entry['source_method']
            if not resolved['common'] and not resolved['modes']:continue
            all_inputs=method['inputs']+[row for m in method['mode_methods'].values() for row in m['inputs']]
            writer.writerow(dict(skill_id=entry['id'],source_sha256=entry['source_sha256'],resolution=method['input_resolution'],common_inputs=len(method['inputs']),mode_count=len(method['mode_methods']),mode_inputs=sum(len(m['inputs']) for m in method['mode_methods'].values()),mode_selection_required=method['mode_selection_required'],source_paths=';'.join(sorted({r['source']['path'] for r in all_inputs})),semantic_acceptance='pending'))
    with (output.parent/'SUBCAPABILITIES.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['name','parent_skill_id','title','category','mode','route','required_tool_contracts','reference','execution']);writer.writeheader()
        for item in all_modes:
            writer.writerow({k:(canonical(item.get('capabilities') or []) if k=='required_tool_contracts' else item.get(k,'')) for k in writer.fieldnames})
    with (output.parent/'WORKFLOW_COVERAGE.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['skill_id','title','family','contract_sha256','source_sha256','required_scope','deliverable_sections','route','acceptance']);writer.writeheader()
        for entry in records:
            contract=entry['draft_contract']
            if contract:writer.writerow(dict(skill_id=entry['id'],title=entry['title'],family=contract['family'],contract_sha256=contract['sha256'],source_sha256=entry['source_sha256'],required_scope=';'.join(contract['required_scope']),deliverable_sections=';'.join(contract['sections']),route='bounded_model_draft_or_operation_preparation',acceptance='source_contract_and_model_output_require_domain_review;no_platform_execution'))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,default=ROOT.parent/'.local/sealeap-sources');p.add_argument('--output',type=Path,default=ROOT/'sealeap/catalogue.json');a=p.parse_args()
    result=build(a.source_root,a.output);print(json.dumps({'skills':len(result['skills']),'sources':result['sources'],'offline_adapters':sum(bool(s['adapter']) for s in result['skills'])},ensure_ascii=False))
