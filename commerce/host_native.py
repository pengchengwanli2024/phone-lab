"""Owned, bounded native host subprocesses; no gateway management or shell."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
from agent_runtime import codex_provider


def environment():
    allowed = {'PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL', 'HERMES_HOME',
               'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY',
               'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}
    result={**{k: v for k, v in os.environ.items() if k in allowed},
            'HERMES_SAFE_MODE': '1', 'HERMES_IGNORE_USER_CONFIG': '1', 'HERMES_IGNORE_RULES': '1'}
    for scheme,proxy in urllib.request.getproxies().items():
        if scheme in ('http','https') and proxy:result.setdefault(scheme.upper()+'_PROXY',proxy)
    result.setdefault('NO_PROXY','127.0.0.1,localhost,::1')
    return result


def hermes_command():
    executable=shutil.which('hermes') or str(Path.home()/'.local/bin/hermes')
    if not Path(executable).is_file():raise ValueError('agent_host_unavailable_use_workbench')
    resolved=subprocess.run([executable,'--print-runtime-command','--module','runpy'],
        capture_output=True,text=True,timeout=15,env=environment())
    try:command=json.loads(resolved.stdout)
    except (TypeError,ValueError):raise ValueError('agent_host_runtime_unavailable') from None
    entry="runpy.run_module('runpy', run_name='__main__', alter_sys=True)"
    if (resolved.returncode or not isinstance(command,list) or len(command)!=4
            or not all(isinstance(v,str) for v in command) or command[1:3]!=['-I','-c'] or not command[3].endswith(entry)):
        raise ValueError('agent_host_runtime_unavailable')
    command[3]=command[3][:-len(entry)]+"runpy.run_path(sys.argv[1], run_name='__main__')"
    return command+[str(Path(__file__).parent/'agent_runtime/hermes_host_worker.py')]


def invoke(lease, cancelled):
    request = lease['request']; route = request['route']
    payload = {'request_id': request['request_id'], 'input': request['payload']}
    if lease['host_id'] == 'codex':
        if route['provider'] != 'codex': raise ValueError('agent_host_route_unavailable')
        return codex_provider.invoke_json(payload, cancelled, route, request['output_schema'],
                                          request['instructions'], with_receipt=True)
    if lease['host_id'] != 'hermes' or route['provider'] != 'codex':
        raise ValueError('agent_host_route_unavailable')
    command=hermes_command()
    with tempfile.TemporaryDirectory(prefix='commerce-hermes-') as directory:
        work = Path(directory)
        with (work / 'request.json').open('wb+') as input_file, (work / 'output.json').open('wb+') as output, (work / 'stderr.log').open('wb+') as errors:
            input_file.write(json.dumps({'request': request}, ensure_ascii=False).encode()); input_file.seek(0)
            if cancelled(): raise codex_provider.Cancelled()
            process = subprocess.Popen(command, stdin=input_file,
                                       stdout=output, stderr=errors, cwd=work, env=environment(), start_new_session=True)
            try:
                end = time.monotonic() + 100
                while process.poll() is None:
                    if cancelled(): raise codex_provider.Cancelled()
                    if time.monotonic() > end: raise ValueError('agent_provider_outcome_unknown')
                    if output.tell() > 1000000 or errors.tell() > 1000000: raise ValueError('agent_host_output_too_large')
                    time.sleep(.1)
                if cancelled(): raise codex_provider.Cancelled()
                # Without a committed native receipt even a nonzero exit can
                # follow provider admission. Never turn it into an automatic retry.
                if process.returncode: raise ValueError('agent_provider_outcome_unknown')
                output.seek(0)
                try: result = json.loads(output.read(50001))
                except (ValueError, UnicodeError): raise ValueError('agent_model_invalid_response') from None
                if not isinstance(result, dict) or set(result) != {'data', 'receipt'}:
                    raise ValueError('agent_model_invalid_response')
                return result
            finally:
                codex_provider.stop(process)
