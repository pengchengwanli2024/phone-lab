"""Create machine-local integration definitions without touching client settings."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parent
entry=str(ROOT/'mcp_server.py')
python=sys.executable
patch='''- insert:
    - id: commerce-workspace
      name: '@local/dsh-commerce'
    - id: mcp-commerce
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: commerce
        transport: stdio
        command: PYTHON
        args: [ENTRY, "harness"]
        toolCallTimeoutMs: 20000
        failOnStartupError: false
'''.replace('PYTHON',json.dumps(python)).replace('ENTRY',json.dumps(entry))
(ROOT/'harness/cordis.patch.yml').write_text(patch)
out=ROOT/'integrations';out.mkdir(exist_ok=True)
(out/'codex.toml').write_text('[mcp_servers.commerce]\ncommand = '+json.dumps(python)+'\nargs = ['+json.dumps(entry)+', "codex"]\nstartup_timeout_sec = 20\ntool_timeout_sec = 20\n')
(out/'hermes.json').write_text(json.dumps({'mcp_servers':{'commerce':{'command':python,'args':[entry,'hermes'],'connect_timeout':20}}},indent=2))
(out/'mcp.json').write_text(json.dumps({'mcpServers':{'commerce':{'command':python,'args':[entry,'local']}}},indent=2))
print('Local connector definitions prepared; client settings not changed.')
