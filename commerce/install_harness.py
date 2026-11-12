"""Install the tested local bundle, preserving unrelated profile settings."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import sys
from harness_local_bundle import prepare, local_link_lock

ROOT=Path(__file__).resolve().parent
PROFILE=Path(os.environ.get('COMMERCE_HARNESS_PROFILE',str(Path.home()/'.dsh/profiles/desktop'))).expanduser()
STATE=ROOT.parent/'.commerce-state'
BACKUP=STATE/'harness-backup'
manifest=PROFILE/'package.json'
lock=PROFILE/'pnpm-lock.yaml'
snapshot={p:p.read_bytes()for p in [manifest,lock]}
time.sleep(.5)
if any(p.read_bytes()!=b for p,b in snapshot.items()):raise SystemExit('Profile changed during preparation; no changes applied.')
BACKUP.mkdir(exist_ok=True,mode=0o700)
for p,b in snapshot.items():
 target=BACKUP/p.name
 if not target.exists():target.write_bytes(b);target.chmod(0o600)
value=json.loads(snapshot[manifest]);old=json.loads(snapshot[manifest]);name='@local/dsh-commerce'
local_bundle=prepare(ROOT,STATE/'harness-local',sys.executable)
expected='link:'+str(local_bundle)
if name in value.get('dependencies',{})and value['dependencies'][name] not in (expected,'link:'+str(ROOT/'harness')):raise SystemExit('Different commerce bundle already exists; no overwrite.')
value.setdefault('dependencies',{})[name]=expected
bundles=value['dsh']['profile']['bundles']
if name not in bundles:bundles.append(name)
target=PROFILE/'node_modules/@local/dsh-commerce';target.parent.mkdir(exist_ok=True)
if target.is_symlink():
 if target.resolve()==(ROOT/'harness').resolve():target.unlink();target.symlink_to(local_bundle,target_is_directory=True)
 elif target.resolve()!=local_bundle:raise SystemExit('Different local bundle link exists.')
elif target.exists():raise SystemExit('Existing package directory will not be replaced.')
else:target.symlink_to(local_bundle,target_is_directory=True)
if manifest.read_bytes()!=snapshot[manifest]:raise SystemExit('Profile changed before commit; manifest was not replaced.')
fd,temp=tempfile.mkstemp(prefix='.commerce-manifest-',dir=PROFILE)
with os.fdopen(fd,'w')as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
os.chmod(temp,0o600);os.replace(temp,manifest)
lock.write_text(local_link_lock(snapshot[lock].decode(),name,local_bundle))
# Linked local sources need no registry lookup or reinstall of unrelated agents.
done=subprocess.CompletedProcess([],0,'','')
after=json.loads(manifest.read_text());check=json.loads(json.dumps(after));check['dependencies'].pop(name,None);check['dsh']['profile']['bundles']=[b for b in check['dsh']['profile']['bundles']if b!=name]
original=json.loads(json.dumps(old));original.get('dependencies',{}).pop(name,None);original['dsh']['profile']['bundles']=[b for b in original['dsh']['profile']['bundles']if b!=name]
if check!=original:raise SystemExit('Unrelated profile values changed during install; inspect private backup before continuing.')
result={'status':'installed'if done.returncode==0 else'installed_lock_sync_pending','profile':'desktop','package':name,'version':'0.1.0','unrelated_manifest_values_preserved':True,'lock_sync_exit':done.returncode,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'current_desktop_activation':'not_yet_verified'}
if done.returncode:result['diagnostic']=(done.stderr or done.stdout)[-1200:]
(ROOT/'qa/harness-install.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
