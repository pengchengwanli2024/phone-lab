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
        intel=await server.session.call_tool('commerce_intel_sources',{})
        assert not intel.is_error
        assert len(json.loads(intel.content[0].text)['sources'])==6
        preference=await server.session.call_tool('commerce_ui_get_preferences',{})
        assert not preference.is_error
        assert json.loads(preference.content[0].text)['theme']in ['system','light','dark']
        topics=await server.session.call_tool('commerce_intel_watch_list',{})
        assert not topics.is_error
        assert json.loads(topics.content[0].text)['notification_enabled']is False
        archive=await server.session.call_tool('commerce_intel_search',{'scope':'archive','limit':'20'})
        assert not archive.is_error
        rows=json.loads(archive.content[0].text)['items'];assert rows
        record=await server.session.call_tool('commerce_intel_item_get',{'item_id':rows[0]['id']})
        assert not record.is_error
        assert len(json.loads(record.content[0].text)['record_sha256'])==64
        output={'status':'passed','client':'installed Hermes MCP client','tools':len(server._tools),'tool_calls':['commerce_status','commerce_knowledge_read','commerce_intel_sources','commerce_intel_search','commerce_intel_item_get','commerce_intel_watch_list','commerce_ui_get_preferences'],'knowledge_scope':'dedicated business directory','model_turn_sent':False}
        Path(__file__).with_name('hermes-result.json').write_text(json.dumps(output,indent=2));print(json.dumps(output))
    finally:await server.shutdown()

asyncio.run(main())
