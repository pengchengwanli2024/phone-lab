"""Install or verify only this project's Mac user LaunchAgent; never a bot gateway."""
from pathlib import Path
import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from runtime import ROOT,STATE,PORT,health

LABEL='local.phone-lab.commerce'


def main():
    if sys.platform!='darwin':raise ValueError('mac_launchd_only_use_manage_serve')
    domain=f'gui/{os.getuid()}'
    agent=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    agent.parent.mkdir(exist_ok=True)
    STATE.mkdir(exist_ok=True,mode=0o700)
    value={'Label':LABEL,'ProgramArguments':[sys.executable,str(ROOT/'server.py')],'WorkingDirectory':str(ROOT),'EnvironmentVariables':{'COMMERCE_STATE':str(STATE),'COMMERCE_PORT':str(PORT)},'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':5,'StandardOutPath':str(STATE/'service.log'),'StandardErrorPath':str(STATE/'service.log')}
    existing=agent.exists()
    if existing:
        old=plistlib.loads(agent.read_bytes())
        if old.get('ProgramArguments',[None])[-1]!=str(ROOT/'server.py') or old.get('EnvironmentVariables',{}).get('COMMERCE_STATE')!=str(STATE) or old.get('EnvironmentVariables',{}).get('COMMERCE_PORT')!=str(PORT):
            raise ValueError('existing_supervisor_configuration_conflict')
        value=old  # Preserve an already installed interpreter and other settings.
    else:
        descriptor=STATE/'runtime.json'
        if descriptor.exists():
            pid=json.loads(descriptor.read_text())['pid']
            done=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
            if done.returncode==0:
                if done.stdout.strip()!=str(value['ProgramArguments'][0])+' '+str(ROOT/'server.py'):
                    raise ValueError('unexpected_process_no_restart')
                os.kill(pid,signal.SIGTERM)
                for _ in range(60):
                    try:os.kill(pid,0);time.sleep(.05)
                    except ProcessLookupError:break
        agent.write_bytes(plistlib.dumps(value));agent.chmod(0o600)
    loaded=subprocess.run(['launchctl','print',domain+'/'+LABEL],capture_output=True).returncode==0
    if not loaded:
        done=subprocess.run(['launchctl','bootstrap',domain,str(agent)],capture_output=True)
        if done.returncode:raise ValueError('launchctl_bootstrap_failed')
    for _ in range(100):
        try:
            if health()['status']=='ready':break
        except Exception:time.sleep(.1)
    else:raise ValueError('supervised_health_check_failed')
    print(json.dumps({'status':'running','supervisor':'launchd','existing_configuration_preserved':existing,'run_at_login':True,'keep_alive':True,'sleep_or_power_loss_available':False,'remote_bot_gateway':'not_managed'}))


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit(str(error) if isinstance(error,ValueError) else 'supervisor_install_failed')
