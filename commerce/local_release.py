"""Private UI checkpoints and guarded offline rollback; never changes business state."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

FILES=('commerce/web/index.html','commerce/web/app.js','commerce/web/style.css',
       'commerce/ui/kit.js','commerce/ui/primitives.css','commerce/ui/tokens.json','commerce/ui/build.py')
ROOT=Path(__file__).resolve().parents[1]


def digest(raw):return hashlib.sha256(raw).hexdigest()
def safe_file(path):
    path=Path(path)
    if any(p.is_symlink()for p in (path,*path.parents)):raise ValueError('release_symlink_rejected')
    return path
def private_json(path,value):
    safe_file(path)
    with path.open('x',encoding='utf-8')as f:json.dump(value,f,indent=2)
    path.chmod(0o600)
def context(root):
    files={}
    for p in sorted((root/'commerce').rglob('*')):
        relative=p.relative_to(root)
        if any(part in ('qa','__pycache__','integrations')for part in relative.parts):continue
        if p.is_symlink():raise ValueError('release_symlink_rejected')
        if p.is_file()and p.suffix in ('.js','.css','.html','.txt','.json','.py')and relative.as_posix()not in FILES:
            files[relative.as_posix()]=digest(p.read_bytes())
    return files
def current(root):
    result={}
    for name in FILES:
        p=safe_file(root/name)
        if not p.is_file()or p.stat().st_size>8*1024*1024:raise ValueError('release_source_unavailable')
        result[name]={'sha256':digest(p.read_bytes()),'mode':p.stat().st_mode&0o777}
    return result
def release_root(state):
    state=Path(state)
    if state.is_symlink():raise ValueError('release_symlink_rejected')
    p=safe_file(state.resolve()/'ui-releases');p.mkdir(parents=True,exist_ok=True,mode=0o700);p.chmod(0o700);return p
def snapshot(root,state):
    root=Path(root).resolve();base=release_root(state);ident=uuid.uuid4().hex;folder=base/ident;folder.mkdir(mode=0o700)
    initial=current(root);other=context(root)
    for name in FILES:
        raw=safe_file(root/name).read_bytes()
        if digest(raw)!=initial[name]['sha256']:raise ValueError('release_source_changed')
        target=folder/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);target.write_bytes(raw);target.chmod(0o600)
    if current(root)!=initial or context(root)!=other:raise ValueError('release_source_changed')
    private_json(folder/'manifest.json',{'schema':'commerce-ui-release-v1','id':ident,'files':initial,'peer_context':other,'business_state_included':False})
    return {'status':'saved','release_id':ident,'files':len(FILES),'business_state_included':False}
def load(state,ident):
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('release_id_invalid')
    folder=safe_file(release_root(state)/ident);p=safe_file(folder/'manifest.json');value=json.loads(p.read_text())
    if value.get('schema')!='commerce-ui-release-v1'or value.get('id')!=ident or set(value.get('files',{}))!=set(FILES):raise ValueError('release_manifest_invalid')
    for name,record in value['files'].items():
        if not isinstance(record.get('mode'),int)or record['mode']not in (0o600,0o644,0o755,0o700):raise ValueError('release_manifest_invalid')
        if digest(safe_file(folder/name).read_bytes())!=record['sha256']:raise ValueError('release_archive_changed')
    return folder,value
def replace(path,raw,mode):
    fd,name=tempfile.mkstemp(prefix='.commerce-ui-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.chmod(name,mode);os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()
def rollback(root,state,source,expected,apply=False):
    root=Path(root).resolve();folder,desired=load(state,source);_,baseline=load(state,expected)
    if current(root)!=baseline['files']:raise ValueError('release_current_source_changed')
    if context(root)!=baseline['peer_context']or desired['peer_context']!=baseline['peer_context']:raise ValueError('release_peer_context_changed')
    if not apply:return {'status':'ready_to_restore_offline','dry_run':True,'files':len(FILES),'business_state_changed':False}
    originals={name:safe_file(root/name).read_bytes()for name in FILES};written=[]
    try:
        for name in FILES:
            path=safe_file(root/name)
            if digest(path.read_bytes())!=baseline['files'][name]['sha256']:raise ValueError('release_current_source_changed')
            replace(path,safe_file(folder/name).read_bytes(),desired['files'][name]['mode']);written.append(name)
        if current(root)!=desired['files']or context(root)!=desired['peer_context']:raise ValueError('release_postcheck_failed')
    except Exception:
        compensated=True
        for name in reversed(written):
            path=safe_file(root/name)
            if digest(path.read_bytes())!=desired['files'][name]['sha256']:compensated=False;continue
            try:replace(path,originals[name],baseline['files'][name]['mode'])
            except OSError:compensated=False
        raise ValueError('release_restore_failed_originals_retained'if compensated else'release_restore_incomplete_manual_review')from None
    return {'status':'restored','dry_run':False,'files':len(FILES),'business_state_changed':False}
def main():
    from runtime import STATE
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True);sub.add_parser('snapshot')
    restore=sub.add_parser('rollback');restore.add_argument('--source',required=True);restore.add_argument('--expected',required=True);restore.add_argument('--apply',action='store_true');args=parser.parse_args()
    if args.command=='snapshot':result=snapshot(ROOT,STATE)
    else:
        if args.apply:
            path=safe_file(STATE/'server.lock')
            with path.open('a+')as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError('stop_workspace_service_before_ui_rollback')from None
                result=rollback(ROOT,STATE,args.source,args.expected,True)
        else:result=rollback(ROOT,STATE,args.source,args.expected,False)
    print(json.dumps(result))
if __name__=='__main__':
    try:main()
    except Exception as e:
        code=str(e)if isinstance(e,ValueError)and re.fullmatch('[a-z_]+',str(e))else'ui_release_operation_failed'
        print(json.dumps({'status':'failed','code':code}));raise SystemExit(1)
