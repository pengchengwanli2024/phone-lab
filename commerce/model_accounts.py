"""Reuse account owners. No auth-file reads, token copies or password forms."""
import os
import shutil
import subprocess
import threading
import time
from agent_runtime.codex_provider import KNOWN_BINARIES
from research import canonical,digest

_lock=threading.Lock()
_login=None

def executable():
 return shutil.which('codex')or next((str(p)for p in KNOWN_BINARIES if p.is_file()and os.access(p,os.X_OK)),None)

def profiles(models):
 try:route=models.default_snapshot()
 except ValueError:route={}
 with models.core.db()as db:hosts=models.service.host_execution._routes(db)
 native=next((r for r in hosts if r['host_id']=='dsh'and r['available']and r['provider']=='deepseek-account'),None)
 return [
  {'id':'account-openai','label':'OpenAI · ChatGPT 账号','engine':'builtin','provider':'codex','model':route.get('model',''),'revision':digest(canonical(route)),'enabled':True,'selectable':bool(executable()and route.get('provider')=='codex'),'test_status':'account_owner_checked_on_use','auth_owner':'official_codex_cli'},
  {'id':'account-deepseek','label':'DeepSeek · Harness 账号','engine':'builtin','provider':'host_native','model':native['model']if native else'','revision':native['route_sha256']if native else'unavailable','enabled':True,'selectable':bool(native),'test_status':'host_account_checked_on_use','auth_owner':'harness','host_id':'dsh'}]

def snapshot(models,model_id):
 item=next((p for p in profiles(models)if p['id']==model_id),None)
 if not item or not item['selectable']:raise ValueError('model_not_ready')
 if model_id=='account-openai':return {**models.default_snapshot(),'profile_id':model_id,'profile_revision':item['revision'],'label':item['label']}
 with models.core.db()as db:route=next(r for r in models.service.host_execution._routes(db)if r['host_id']=='dsh'and r['available']and r['provider']=='deepseek-account')
 return {**item,'profile_id':model_id,'profile_revision':item['revision'],'host_id':'dsh','native_provider':route['provider'],'route_sha256':route['route_sha256'],'routing_reason':'explicit_deepseek_account'}

def status(models):
 items=profiles(models);authenticated=False;cli=executable()
 if cli:
  try:
   r=subprocess.run([cli,'login','status'],capture_output=True,text=True,timeout=8)
   authenticated=r.returncode==0
  except (OSError,subprocess.TimeoutExpired):pass
 accounts=[{'id':'openai','label':'OpenAI / ChatGPT','model_id':'account-openai','status':'authenticated'if authenticated else'login_required'if cli else'owner_unavailable','owner':'官方 Codex CLI','login_supported':bool(cli),'instructions':'登录与续期由本机官方 Codex CLI 管理；项目不读取或复制令牌。'},
           {'id':'deepseek','label':'DeepSeek','model_id':'account-deepseek','status':'connected_host_account'if items[1]['selectable']else'host_login_required','owner':'DeepSeek Harness','login_supported':False,'instructions':'在 Harness 左下角账号菜单完成 DeepSeek 登录并选择 DeepSeek 模型，再回此处刷新。账号凭据由 Harness 管理；浏览器通过同一宿主工作进程调用。'}]
 with _lock:pending=bool(_login and _login.poll()is None)
 return {'accounts':accounts,'login_pending':pending,'credentials_copied':False,'automatic_login':False}

def login(models,provider):
 global _login
 if provider!='openai':raise ValueError('model_account_login_in_owner')
 current=status(models)
 if current['accounts'][0]['status']=='authenticated':return current
 cli=executable()
 if not cli:raise ValueError('model_account_owner_unavailable')
 with _lock:
  if not _login or _login.poll()is not None:
   _login=subprocess.Popen([cli,'login'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
   child=_login
   def expire():
    try:child.wait(timeout=600)
    except subprocess.TimeoutExpired:child.terminate()
   threading.Thread(target=expire,daemon=True,name='commerce-account-login').start()
 return {**current,'login_pending':True}
