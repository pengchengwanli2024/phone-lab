"""Bounded synthetic fidelity screening using only the existing translation route.

Automatic flags are not a semantic-quality score. No profile edits, fallback
providers, retries, local-model loading or production data are used.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import uuid
from translation import run_model, normalize

ROOT=Path(__file__).resolve().parent
def sha(value):return hashlib.sha256(value.encode()).hexdigest()

def screen(case, zh):
    flags=[]
    if not isinstance(zh,str)or not zh.strip():return ['empty_translation']
    for token in case['tokens']:
        if token not in zh:flags.append('literal_token_changed:'+token)
    if case.get('negative_zh')and not re.search(case['negative_zh'],zh):flags.append('negative_meaning_needs_review')
    return flags

def evaluate(state, *, runner=run_model, corpus=None):
    cases=json.loads((ROOT/'qa/translation-fidelity-cases.json').read_text())if corpus is None else corpus
    if not isinstance(cases,list)or not 1<=len(cases)<=12:raise ValueError('invalid_fidelity_corpus')
    folder=Path(state).resolve()/'translation-evaluation'
    if folder.is_symlink():raise ValueError('unsafe_evaluation_directory')
    folder.mkdir(exist_ok=True,parents=True,mode=0o700);folder=folder/uuid.uuid4().hex;folder.mkdir(mode=0o700)
    batches=[];rows=[];blocked=False
    for language in dict.fromkeys(c['language']for c in cases):
        selected=[c for c in cases if c['language']==language]
        data=normalize({'language':language,'items':[{'id':c['id'],'text':c['text']}for c in selected]})
        if blocked:
            batches.append({'language':language,'status':'not_run_after_provider_failure'});continue
        try:
            result=runner(data);lookup={v['id']:v for v in result['translations']}
            if set(lookup)!={c['id']for c in selected}:raise ValueError('translation_incomplete_response')
            for case in selected:
                value=lookup[case['id']]
                if value.get('original_sha256')!=sha(case['text'])or value.get('zh_sha256')!=sha(value['zh']):raise ValueError('translation_evidence_mismatch')
                rows.append(dict(id=case['id'],language=language,original=case['text'],zh=value['zh'],original_sha256=value['original_sha256'],zh_sha256=value['zh_sha256'],model=result.get('model'),provider=result.get('provider'),flags=screen(case,value['zh']),pipeline_warnings=value.get('warnings',[]),review_status='pending_human_semantic_review'))
            batches.append(dict(language=language,status='completed',model=result.get('model'),provider=result.get('provider'),prompt_version=result.get('prompt_version')))
            print(json.dumps({'language':language,'status':'completed','synthetic_items':len(selected)}),flush=True)
        except Exception as error:
            blocked=True
            known={'translation_provider_failed','translation_hermes_unavailable','translation_profile_unavailable','translation_runtime_unavailable','translation_incomplete_response','translation_evidence_mismatch'}
            batches.append(dict(language=language,status='unknown'if isinstance(error,subprocess.TimeoutExpired)else'blocked',code=str(error)if isinstance(error,ValueError)and str(error)in known else'provider_result_unavailable'))
            print(json.dumps({'language':language,'status':batches[-1]['status']}),flush=True)
    report=dict(schema='synthetic-translation-fidelity-v1',status='partial'if blocked else'screened',synthetic=True,requested_items=len(cases),completed_items=len(rows),flagged_items=sum(bool(r['flags'])for r in rows),human_semantic_acceptance=False,model_profiles_changed=False,local_models_loaded=False,automatic_retries=0,corpus_sha256=sha(json.dumps(cases,ensure_ascii=False,sort_keys=True)),batches=batches,rows=rows,limitation='数字/字面标记与否定表达筛查，不代表完整翻译准确率；所有结果待人工语义复核。')
    path=folder/'report.json';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w')as f:json.dump(report,f,ensure_ascii=False,indent=2)
    fd=os.open(folder/'bilingual.csv',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8-sig',newline='')as f:
        writer=csv.writer(f);writer.writerow(['样本','原文语言','原文','中文译文','校对状态','自动筛查标记','原文SHA256','译文SHA256','模型','提供方'])
        for r in rows:writer.writerow([r['id'],r['language'],r['original'],r['zh'],r['review_status'],'; '.join(r['flags']),r['original_sha256'],r['zh_sha256'],r['model'],r['provider']])
    return dict(report=path,details=report)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-existing',action='store_true');args=parser.parse_args()
    if not args.run_existing:raise SystemExit('Use --run-existing to explicitly test the existing configured route with synthetic text.')
    result=evaluate(Path(os.environ.get('COMMERCE_STATE',str(ROOT.parent/'.commerce-state'))))
    print(json.dumps({'status':result['details']['status'],'completed_items':result['details']['completed_items'],'flagged_items':result['details']['flagged_items'],'private_report':str(result['report']),'human_semantic_acceptance':False}))
