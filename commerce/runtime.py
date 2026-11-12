"""Start one detached loopback service; do not couple it to a UI/client lifetime."""
from pathlib import Path
import contextlib
import fcntl
import json
import os
import secrets
import plistlib
import subprocess
import sys
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parent
STATE=Path(os.environ.get('COMMERCE_STATE',str(ROOT.parent/'.commerce-state'))).resolve()
PORT=int(os.environ.get('COMMERCE_PORT','38731'))
if not 1 <= PORT <= 65535:raise ValueError('invalid_commerce_port')


def token():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=STATE/'auth.token'
    if not path.exists():
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w')as f:f.write(secrets.token_urlsafe(36))
        except FileExistsError:pass
    return path.read_text().strip()


def request(tool,args,client='local'):
    data=json.dumps({'tool':tool,'arguments':args,'client':client}).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}/v1/invoke',data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+token()})
    try:
        with urllib.request.urlopen(req,timeout=15)as r:return json.load(r)
    except urllib.error.HTTPError as exc:
        try:code=json.loads(exc.read(4096)).get('error','commerce_request_failed')
        except Exception:code='commerce_request_failed'
        raise ValueError(code)from None


def health():
    req=urllib.request.Request(f'http://127.0.0.1:{PORT}/v1/health',headers={'Authorization':'Bearer '+token()})
    with urllib.request.urlopen(req,timeout=2)as response:
        value=json.load(response)
    if value.get('service')!='commerce-backend' or value.get('version')!='0.1.0':raise ValueError('unexpected_service')
    return value


def supervised():
    """Wait for our matching Mac supervisor instead of racing it at login."""
    if sys.platform != 'darwin':return False
    path=Path.home()/'Library/LaunchAgents/local.phone-lab.commerce.plist'
    try:
        value=plistlib.loads(path.read_bytes())
        env=value.get('EnvironmentVariables',{})
        if (value.get('Label')!='local.phone-lab.commerce'
                or value.get('ProgramArguments',[None])[-1]!=str(ROOT/'server.py')
                or env.get('COMMERCE_STATE')!=str(STATE)
                or env.get('COMMERCE_PORT')!=str(PORT)):
            return False
        return subprocess.run(['launchctl','print',f'gui/{os.getuid()}/local.phone-lab.commerce'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2).returncode==0
    except (OSError,ValueError,plistlib.InvalidFileException,subprocess.TimeoutExpired):return False


def ensure():
    token()
    with (STATE/'start.lock').open('a+')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            if health()['status']=='ready':return
        except Exception:pass
        if not supervised():
            with (STATE/'service.log').open('ab')as log:
                subprocess.Popen([sys.executable,str(ROOT/'server.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=os.environ.copy(),cwd=ROOT)
        for _ in range(80):
            try:
                if health()['status']=='ready':return
            except Exception:time.sleep(.1)
        raise RuntimeError('commerce_service_unavailable')


if __name__=='__main__':
    ensure();print(json.dumps({'origin':f'http://127.0.0.1:{PORT}','status':'ready'}))
