"""Read-only incremental release dependency report; never stages or publishes.

Reports contain relative source names and hashes only. Source/configuration,
databases, screenshots and provider responses are never copied to the public
checkout. A report is not a privacy, license, install or release acceptance.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OWNED=[
 'commerce/platform_connections/__init__.py','commerce/platform_connections/protocols.py','commerce/platform_connections/setup.py','commerce/platform_connections/diagnostics.py','commerce/manage.py',
 'commerce/pilot_bridge.py','commerce/release_preflight.py','commerce/web/platform-ui.js','commerce/web/platform-ui.css',
 'commerce/README.md','commerce/RUNNING.md','commerce/web/platform-setup.js','commerce/web/pilot-ui.js','commerce/web/pilot-ui.css','commerce/PLATFORMS.md','commerce/PILOTS.md',
 'commerce/service.py','commerce/server.py','commerce/mcp_server.py','commerce/ui/build.py','commerce/web/app.js','commerce/web/style.css',
 'commerce/qa/test_platform_connections.py','commerce/qa/test_platform_integrity.py','commerce/qa/test_platform_diagnostics.py','commerce/qa/test_pilot_bridge.py','commerce/qa/test_release_preflight.py',
 'commerce/qa/fixture_platforms.py','commerce/qa/platform_ui.mjs','commerce/qa/harness_smoke.mjs',
]


def fingerprint(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def local_file(root,module):
 if not module:return None
 parts=module.split('.')
 if any(not p.isidentifier()for p in parts):return None
 for path in (root/'commerce'/Path(*parts).with_suffix('.py'),root/'commerce'/Path(*parts)/'__init__.py'):
  if path.is_file():
   if path.is_symlink()or not path.resolve().is_relative_to((root/'commerce').resolve()):raise ValueError('release_source_symlink_rejected')
   return path
 return None


def dependencies(root,path):
 relative=path.relative_to(root/'commerce');package=list(relative.parts[:-1]);found=set()
 for node in ast.walk(ast.parse(path.read_text())):
  names=[]
  if isinstance(node,ast.Import):names=[n.name for n in node.names]
  elif isinstance(node,ast.ImportFrom):
   prefix=package[:len(package)-node.level+1]if node.level else[]
   if node.module:prefix+=node.module.split('.')
   names=['.'.join(prefix)]if prefix else[]
   names+=['.'.join([*prefix,n.name])for n in node.names if n.name!='*']
  for name in names:
   file=local_file(root,name)
   if file:found.add(file)
 return found


def report(root,base,entries=OWNED):
 root=Path(root).resolve();base=Path(base).resolve();own=[];queue=[];seen=set()
 for name in entries:
  relative=Path(name)
  if relative.is_absolute()or '..'in relative.parts or not relative.parts or relative.parts[0]!='commerce':raise ValueError('release_invalid_source_path')
  path=root/relative
  if path.is_symlink()or not path.resolve().is_relative_to(root/'commerce'):raise ValueError('release_source_symlink_rejected')
  if not path.is_file():raise ValueError('release_source_missing')
  published=base/relative
  own.append({'path':relative.as_posix(),'sha256':fingerprint(path),'public_base_state':'same'if published.is_file()and fingerprint(path)==fingerprint(published)else 'different'if published.is_file()else 'absent'})
  if path.suffix=='.py':queue.append(path)
 while queue:
  path=queue.pop()
  if path in seen:continue
  seen.add(path);queue.extend(dependencies(root,path)-seen)
 missing=sorted(p.relative_to(root).as_posix()for p in seen if not(base/p.relative_to(root)).is_file()and p.relative_to(root).as_posix()not in entries)
 own_changed=[r for r in own if r['public_base_state']!='same']
 return {'schema':'commerce-release-preflight-v1','status':'blocked_missing_runtime_dependencies'if missing else 'needs_privacy_license_and_install_validation',
         'planned_owned_files':own_changed,'transitive_python_files_checked':len(seen),'missing_base_dependencies_outside_owned_scope':missing,
         'public_checkout_written':False,'git_stage_or_commit':False,'network_or_push':False,'private_state_included':False,
         'privacy_scan':'not_performed_by_this_readonly_preflight','license_review':'pending','static_data_and_optional_runtime_dependencies':'pending_separate_validation',
         'clean_install_verified':False,'publish_ready':False,'overall_project':'partial'}


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,default=ROOT/'.local/open-source/phone-lab');parser.add_argument('--output',type=Path,default=ROOT/'.commerce-state/verification/platforms/release-preflight.json');args=parser.parse_args()
 base=args.base.resolve();out=args.output.resolve();private=ROOT/'.commerce-state/verification'
 if not base.is_dir()or not(base/'.git').exists():raise SystemExit('existing_public_git_checkout_required')
 if not out.is_relative_to(private.resolve()):raise SystemExit('private_verification_output_required')
 # No repository content or history is printed. Preserve dirty peer work.
 head=subprocess.run(['git','-C',str(base),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
 dirty=subprocess.run(['git','-C',str(base),'status','--porcelain'],capture_output=True,text=True,check=True).stdout
 value=report(ROOT,base);value.update(public_base_commit=head,public_base_dirty=bool(dirty.strip()))
 out.parent.mkdir(parents=True,exist_ok=True,mode=0o700);out.write_text(json.dumps(value,ensure_ascii=False,indent=2));out.chmod(0o600)
 print(json.dumps({k:value[k]for k in ('status','publish_ready','public_checkout_written','public_base_dirty')}|{'planned_owned_files':len(value['planned_owned_files']),'missing_dependencies':len(value['missing_base_dependencies_outside_owned_scope'])}))


if __name__=='__main__':main()
