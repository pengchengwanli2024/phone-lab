"""Synthetic follow-up lifecycle server; no model/collector/device/message worker."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):
    raise SystemExit('An isolated state and port are required')
import server
from service import Commerce
import test_attention as attention_fixture

app = Commerce(server.STATE)
marker = server.STATE / 'followup-fixture.json'
if not marker.exists():
    helper = attention_fixture.Attention(); helper.app = app; helper.counter = 0
    thread = helper.thread(); helper.run_record(thread=thread, questions=['合成原事项待补充'])
    helper.run_record(questions=['合成示例范围事项'], demo=True)
    app.core.invoke('commerce_task_create', {'kind':'report','input':{'title':'合成未执行任务'},'idempotency_key':'followup-fixture-task'})
    # A genuine local task receipt and synthetic model decisions exercise the
    # integrated timeline; no real provider or external channel is invoked.
    from test_agent_runtime import inspect,answer
    model_run=app.agent_runtime.create('检查本机运行状态','conductor','runtime','timeline-fixture',parameters={'demo':True})
    with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer(proposals=[{'operation':'report','reason':'合成时间线任务'}])]):
        app.agent_runtime.run_once()
    result=app.agent_runtime.get(model_run['id'])
    app.agent_runtime.apply(result['id'],'P1',result['result_sha256'])
    app.autonomy.work(time.time())
    marker.write_text(json.dumps({'thread_id':thread['id']}))
server.Handler.secret = 'synthetic-followup-only'
(server.STATE / 'auth.token').write_text(server.Handler.secret)
server.Handler.service = app
original_post = server.Handler.do_POST


def post(handler):
    if handler.path != '/qa/followup-advance':return original_post(handler)
    if handler.headers.get('Authorization') != 'Bearer '+server.Handler.secret:return handler.answer(401, {'error':'unauthorized'})
    # Keep the test endpoint's HTTP/1.1 connection aligned for later API reads.
    try:
        size = int(handler.headers.get('Content-Length', '0'))
        if not 0 <= size <= 4096:raise ValueError()
        if size and json.loads(handler.rfile.read(size)) != {}:raise ValueError()
    except (ValueError, TypeError):return handler.answer(400, {'error':'invalid_test_arguments'})
    return handler.answer(200, {'checks':app.followups.tick(at=time.time()+7200)})


server.Handler.do_POST = post
app.autonomy.start(recover=True)
try:
    server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler).serve_forever()
finally:
    app.autonomy.stop(); app.agent_runtime.stop()
