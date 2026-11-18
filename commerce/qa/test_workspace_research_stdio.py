"""Real MCP stdio -> isolated synthetic HTTP -> atomic research domain."""
from copy import deepcopy
from pathlib import Path
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


class WorkspaceResearchStdioTests(unittest.TestCase):
    def test_public_contract_actual_save_replay_and_conflict_across_clients(self):
        with tempfile.TemporaryDirectory(prefix='workspace-research-stdio-') as directory:
            state = Path(directory)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0));port = probe.getsockname()[1]
            origin = 'http://127.0.0.1:' + str(port)
            env = {**os.environ, 'COMMERCE_STATE': directory, 'COMMERCE_PORT': str(port),
                   'COMMERCE_QA_INTEL': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PYTHONPATH': os.pathsep.join(filter(None, (os.environ.get('PYTHONPATH'), str(ROOT/'commerce')))),
                   'NO_PROXY': '127.0.0.1,localhost',
                   'no_proxy': '127.0.0.1,localhost'}
            fixture = subprocess.Popen([sys.executable, '-B', str(ROOT/'commerce/qa/react_workbench_fixture.py')],
                                       cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            clients = []
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                ready = False
                for _ in range(150):
                    self.assertIsNone(fixture.poll(), 'the isolated fixture unexpectedly exited')
                    try:
                        request = urllib.request.Request(origin+'/v1/health', headers={'Authorization':'Bearer synthetic-workbench-preview'})
                        with opener.open(request, timeout=1) as response:
                            if json.load(response)['status'] == 'ready':ready = True;break
                    except (OSError, ValueError):pass
                    time.sleep(.1)
                self.assertTrue(ready)
                case_id = json.loads((state/'fixture.json').read_text())['case_id']
                entry = os.environ.get('WORKSPACE_RESEARCH_MCP_ENTRY', str(ROOT/'commerce/mcp_server.py'))
                def client(label):
                    process = subprocess.Popen([sys.executable, '-B', entry, label], cwd=ROOT, env=env,
                                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               text=True, bufsize=1)
                    clients.append(process);return process
                sequence = 0
                def rpc(process, method, params=None):
                    nonlocal sequence
                    sequence += 1
                    process.stdin.write(json.dumps(dict(jsonrpc='2.0',id=sequence,method=method,params=params or {}))+'\n');process.stdin.flush()
                    readable, _, _ = select.select([process.stdout], [], [], 20)
                    self.assertTrue(readable, 'actual MCP response timed out')
                    value = json.loads(process.stdout.readline())
                    self.assertEqual(value['id'], sequence);self.assertNotIn('error', value)
                    return value['result']
                def call(process, name, arguments):return rpc(process, 'tools/call', dict(name=name, arguments=arguments))
                codex = client('codex')
                rpc(codex, 'initialize', {'protocolVersion':'2025-11-25','capabilities':{}})
                tools = {row['name']:row for row in rpc(codex, 'tools/list')['tools']}
                save = tools['commerce_workspace_research_save']
                self.assertEqual(save['annotations'], dict(readOnlyHint=False,destructiveHint=False,idempotentHint=True,openWorldHint=False))
                self.assertTrue(tools['commerce_workspace_research_capabilities']['annotations']['readOnlyHint'])
                self.assertEqual(save['inputSchema']['properties']['expected_artifact_id']['minLength'], 0)
                capability = call(codex, 'commerce_workspace_research_capabilities', {})
                self.assertFalse(capability['isError']);self.assertTrue(capability['structuredContent']['atomic_source_and_head'])
                current = call(codex, 'commerce_workspace_get', {'case_id':case_id})['structuredContent']
                record = deepcopy(current['artifacts']['research']['payload']['record'])
                record['raw_excerpt'] += ' Edited through real synthetic MCP.'
                request = dict(case_id=case_id,record=record,expected_source_sha256=current['source_sha256'],
                               expected_artifact_id=current['artifacts']['research']['id'],idempotency_key='stdio-research-1')
                first = call(codex, 'commerce_workspace_research_save', request)
                self.assertFalse(first['isError']);receipt = first['structuredContent']
                readback = call(codex, 'commerce_workspace_get', {'case_id':case_id})['structuredContent']
                self.assertEqual(readback['artifacts']['research']['id'], receipt['artifact_id'])
                self.assertEqual(readback['artifacts']['research']['sha256'], receipt['artifact_sha256'])
                self.assertEqual(readback['source_sha256'], receipt['source_sha256'])
                self.assertEqual(readback['artifacts']['research']['payload']['record'], record)
                hermes = client('hermes');rpc(hermes, 'initialize', {'protocolVersion':'2025-11-25','capabilities':{}})
                replay = call(hermes, 'commerce_workspace_research_save', request)
                self.assertEqual(first, replay, 'cross-client replay must return the exact original successful response')
                conflict = deepcopy(request);conflict['record']['raw_excerpt'] += ' Different payload.'
                denied = call(hermes, 'commerce_workspace_research_save', conflict)
                self.assertTrue(denied['isError']);self.assertEqual(denied['content'][0]['text'], 'workspace_research_idempotency_conflict')
                self.assertFalse(receipt['external_operations_executed'])
            finally:
                for process in clients:
                    if process.poll() is None:
                        process.stdin.close()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                    process.stdout.close();process.stderr.close()
                fixture.terminate()
                try:fixture.wait(timeout=5)
                except subprocess.TimeoutExpired:fixture.kill();fixture.wait(timeout=5)
                fixture.stderr.close()
                # The adapter's normal ensure() uses this already-ready fixture.
                # If it unexpectedly auto-started a replacement, only that
                # private state's matching loopback process may be cleaned up.
                runtime = state/'runtime.json'
                if runtime.exists():
                    value = json.loads(runtime.read_text())
                    if value.get('origin') == origin and value.get('pid') not in (None, fixture.pid, os.getpid()):
                        try:os.kill(value['pid'], signal.SIGTERM)
                        except ProcessLookupError:pass


if __name__ == '__main__':unittest.main()
