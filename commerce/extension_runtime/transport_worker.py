"""Fixed transport entry point; never accepts source, shell or executable names."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extension_runtime.transport import _invoke

if __name__=='__main__':
    try:
        raw=sys.stdin.read(80001)
        if len(raw)>80000:raise ValueError()
        packet=json.loads(raw)
        result=_invoke(packet['spec'],packet['args'],packet['headers'])
        sys.stdout.write(json.dumps({'result':result},allow_nan=False))
    except Exception:
        sys.stdout.write('{"error":"extension_plugin_transport_failed"}')
        raise SystemExit(1)
