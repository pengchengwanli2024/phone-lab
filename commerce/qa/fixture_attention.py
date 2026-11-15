"""Private synthetic browser fixture. No workers, model calls, phones or messages."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
if not os.environ.get('COMMERCE_STATE') or not os.environ.get('COMMERCE_PORT'):
    raise SystemExit('Isolated state and port are required')
import server
from service import Commerce
from test_attention import Attention

app = Commerce(server.STATE)
fixture = Attention()
fixture.app, fixture.counter = app, 0
thread = fixture.thread()
pending = fixture.run_record(thread=thread, questions=['合成待补充：请明确本轮预算'], proposals=[fixture.proposal()])
old = fixture.run_record(status='unknown')
for _ in range(32):
    fixture.run_record(questions=['合成分页待补充'])
fixture.run_record(questions=['DEMO_ONLY_ATTENTION'], demo=True)
research_thread = fixture.thread()
research = app.copilot.send(research_thread['id'], '请调研俄罗斯厨房收纳用品并保存候选', research_thread['context_sha256'], 'attention-research')['research_job']
with app.core.db() as db:
    job = json.loads(db.execute('SELECT document FROM market_research_jobs WHERE task_id=?', (research['task_id'],)).fetchone()[0])
    job['status'] = 'unknown'
    app.market_research._save(db, job)
    db.execute("UPDATE agent_runs SET status='unknown' WHERE id=?", (job['run_id'],))

server.Handler.secret = 'synthetic-attention-browser-only'
(server.STATE / 'auth.token').write_text(server.Handler.secret)
server.Handler.service = app
(server.STATE / 'fixture.json').write_text(json.dumps({'thread_id': thread['id'], 'pending_run': pending['id'],
    'old_run': old['id'], 'research_task': research['task_id']}))
original = app.invoke


def invoke(name, arguments, client='local'):
    if name == 'commerce_attention_list' and (server.STATE / 'fail-attention').exists():
        raise ValueError('attention_source_unavailable')
    return original(name, arguments, client)


app.invoke = invoke
try:
    server.CommerceHTTPServer(('127.0.0.1', server.PORT), server.Handler).serve_forever()
finally:
    app.agent_runtime.stop()
