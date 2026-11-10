"""Keep the local shared backend running while the Mac user session is active."""
from pathlib import Path
import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from runtime import ROOT,STATE,PORT,request

LABEL='local.phone-lab.commerce'
domain=f'gui/{os.getuid()}'
agent=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
agent.parent.mkdir(exist_ok=True)
value={'Label':LABEL,'ProgramArguments':[sys.executable,str(ROOT/'server.py')],'WorkingDirectory':str(ROOT),'EnvironmentVariables':{'COMMERCE_STATE':str(STATE),'COMMERCE_PORT':str(PORT)},'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':5,'StandardOutPath':str(STATE/'service.log'),'StandardErrorPath':str(STATE/'service.log')}
if agent.exists():
    old=plistlib.loads(agent.read_bytes())
    if old.get('ProgramArguments',[None,None])[-1]!=str(ROOT/'server.py'):raise SystemExit('Existing unrelated LaunchAgent is not replaced.')
    raise SystemExit('Commerce LaunchAgent already exists; inspect it instead of replacing a running service.')
STATE.mkdir(exist_ok=True,mode=0o700)
descriptor=STATE/'runtime.json'
if descriptor.exists():
    pid=json.loads(descriptor.read_text())['pid']
    try:
        command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
        if str(ROOT/'server.py')not in command:raise SystemExit('Unexpected process; no restart performed.')
        os.kill(pid,signal.SIGTERM)
        for _ in range(60):
            try:os.kill(pid,0);time.sleep(.05)
            except ProcessLookupError:break
    except subprocess.CalledProcessError:pass
agent.write_bytes(plistlib.dumps(value));agent.chmod(0o600)
done=subprocess.run(['launchctl','bootstrap',domain,str(agent)],capture_output=True,text=True)
if done.returncode:raise SystemExit('launchctl bootstrap failed: '+done.stderr.strip())
for _ in range(100):
    try:
        status=request('commerce_status',{},'test')
        if status['version']=='0.1.0':break
    except Exception:time.sleep(.1)
else:raise SystemExit('Supervised backend health check did not pass.')
result={'status':'running','supervisor':'launchd','label':LABEL,'run_at_login':True,'keep_alive':True,'scope':'current Mac user session','sleep_or_power_loss_available':False,'remote_bot_gateway':'not_started_by_this_installer'}
(ROOT/'qa/runtime-supervision.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
