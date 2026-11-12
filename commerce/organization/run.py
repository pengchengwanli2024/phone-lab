"""Inspect the shared local organization; no scheduler or external write command."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime import ensure,request

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',nargs='?',default='board',choices=['board','gaps','brief','check','import-inventory']);parser.add_argument('target',nargs='?');parser.add_argument('--case',dest='case_id');args=parser.parse_args();ensure()
    selected={'case_id':args.case_id}if args.case_id else{}
    if args.command=='import-inventory':
        result=request('commerce_organization_import_inventory',{},'local');print(json.dumps({'local_cases':len(result['cases']),'external_execution':False}));return
    if args.command=='board':
        result=request('commerce_organization_capture',selected,'local');print(json.dumps({'location':result['location'],'gate_passed':result['board']['passed'],'gate_total':result['board']['total'],'gate_pass_rate':result['board']['gate_pass_rate'],'notice':result['board']['notice']},ensure_ascii=False));return
    board=request('commerce_organization_board',selected,'local')
    if args.command=='gaps':result=[dict(stage=s['id'],role=s['role'],status=s['status'],gaps=s['gaps'])for s in board['stages']if s['status']!='PASS']
    elif args.command=='check':
        result=next((s for s in board['stages']if s['id']==args.target),None)
        if result is None:raise ValueError('invalid_organization_stage')
    else:
        if not board['case']:raise ValueError('import_or_select_work_item_first')
        stage=next((s for s in board['stages']if s['id']==args.target or s['role']==args.target),None)
        if not stage:raise ValueError('invalid_organization_role_or_stage')
        result=request('commerce_organization_brief',{'case_id':board['case']['id'],'stage_id':stage['id']},'local')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
