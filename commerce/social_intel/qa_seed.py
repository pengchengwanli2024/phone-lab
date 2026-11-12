"""Seed isolated UI acceptance from a selected local private package."""
import base64
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce

def seed(state,source):
    source=Path(source);bundle=json.loads(source.read_text());service=Commerce(state)
    stage=service.invoke('commerce_social_stage',{'bundle':bundle,'idempotency_key':'ui-acceptance-seed'},'test')
    for a in bundle['assets']:
        data=(source.parent/a['path']).read_bytes()
        for offset in range(0,len(data),90000):service.invoke('commerce_social_upload',{'stage_id':stage['stage_id'],'evidence_id':a['evidence_id'],'offset':str(offset),'content_base64':base64.b64encode(data[offset:offset+90000]).decode()},'test')
    return service.invoke('commerce_social_commit',{'stage_id':stage['stage_id'],'idempotency_key':'ui-acceptance-seed','expected_heads':{}},'test')

if __name__=='__main__':print(json.dumps(seed(sys.argv[1],sys.argv[2])))
