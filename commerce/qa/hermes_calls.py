"""Run through Hermes' own bootstrap and installed MCP client, no model turn."""
import asyncio
import json
from pathlib import Path
from hermes_cli.mcp_config import _get_mcp_servers
from tools.mcp_tool_discovery import _connect_server

async def main():
    config=_get_mcp_servers()['commerce']
    server=await asyncio.wait_for(_connect_server('commerce',config),timeout=25)
    try:
        result=await server.session.call_tool('commerce_status',{})
        if result.is_error:raise RuntimeError('Hermes commerce_status failed')
        status=json.loads(result.content[0].text)
        assert status['version']=='0.1.0'
        note=await server.session.call_tool('commerce_knowledge_read',{'path':'00-接入说明.md'})
        assert not note.is_error
        note=json.loads(note.content[0].text)
        assert '跨境电商工作台'in note['content']
        output={'status':'passed','client':'installed Hermes MCP client','tools':len(server._tools),'tool_calls':['commerce_status','commerce_knowledge_read'],'knowledge_scope':'dedicated business directory','model_turn_sent':False}
        Path(__file__).with_name('hermes-result.json').write_text(json.dumps(output,indent=2));print(json.dumps(output))
    finally:await server.shutdown()

asyncio.run(main())
