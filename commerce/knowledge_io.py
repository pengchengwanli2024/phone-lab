"""Bound reads on a scoped path so an OS access prompt cannot stall the API.

Path containment/size/link checks belong to Commerce.safe_note. This child
receives only that already approved path; no shell, model or network access.
"""
import subprocess
import sys


def read_note(path):
    script="import sys,os;f=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW);b=os.read(f,128001);os.close(f);assert len(b)<=128000;sys.stdout.buffer.write(b)"
    try:
        result=subprocess.run([sys.executable,'-I','-c',script,str(path)],capture_output=True,timeout=3,check=True)
        return result.stdout
    except subprocess.TimeoutExpired:
        raise ValueError('knowledge_access_timeout_check_os_permission') from None
    except Exception:
        raise ValueError('knowledge_read_unavailable') from None
