"""Import a reviewed private package through the running shared HTTP interface."""
import argparse
import base64
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime import request
from social_intel.admission import prepare
from social_intel import package as contract

def upload(source,expected_heads=None):
    source=Path(source);bundle=json.loads(source.read_text());approved=prepare(bundle,source.parent)
    key='social-import:'+approved['fingerprint']
    staged=request('commerce_social_stage',{'bundle':bundle,'idempotency_key':key})
    progress={r['evidence_id']:int(r['offset']) for r in staged['evidence']}
    for asset in bundle['assets']:
        path=contract.asset_path(source.parent,asset['path']);offset=progress[asset['evidence_id']]
        if offset>path.stat().st_size:raise ValueError('social_remote_offset_conflict')
        with path.open('rb') as f:
            f.seek(offset)
            while chunk:=f.read(90000):
                result=request('commerce_social_upload',{'stage_id':staged['stage_id'],'evidence_id':asset['evidence_id'],'offset':str(offset),'content_base64':base64.b64encode(chunk).decode()})
                offset=int(result['offset'])
    return request('commerce_social_commit',{'stage_id':staged['stage_id'],'idempotency_key':key,'expected_heads':expected_heads or {}})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--expected-heads',type=Path);args=parser.parse_args()
    result=upload(args.source,json.loads(args.expected_heads.read_text()) if args.expected_heads else None)
    print(json.dumps({k:result[k] for k in ('status','records','selected','fingerprint')}))
