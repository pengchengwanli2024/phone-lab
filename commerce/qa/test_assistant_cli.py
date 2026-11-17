"""Real isolated loopback HTTP and the original team/run ledger; no worker/model."""
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import hashlib
import importlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service import Commerce
from assistant_team import AssistantTeams
import runtime


class AssistantCLI(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('assistant_cli'), 'headless assistant CLI is not implemented')
        self.cli = importlib.import_module('assistant_cli')
        self.temp = tempfile.TemporaryDirectory(prefix='assistant-cli-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root/'state'; self.state.mkdir(mode=0o700)
        self.secret = 'synthetic-cli-auth-only'
        (self.state/'auth.token').write_text(self.secret)
        (self.state/'auth.token').chmod(0o600)
        self.app = Commerce(self.state)
        self.addCleanup(self.app.agent_runtime.stop)
        self.addCleanup(self.app.autonomy.stop)
        self.team = getattr(self.app, 'assistant_team', None) or AssistantTeams(self.app)
        self.app.assistant_team = self.team
        for target, value in ((self.app.models, 'default_snapshot'),):
            guard=patch.object(target,value,return_value={'provider':'hermes','model':'synthetic-local-test'})
            guard.start();self.addCleanup(guard.stop)
        guard=patch('agent_runtime.model.invoke',side_effect=AssertionError('CLI must not execute a model'))
        guard.start();self.addCleanup(guard.stop)
        guard=patch.object(runtime,'ensure',side_effect=AssertionError('CLI must not start a background service'))
        guard.start();self.addCleanup(guard.stop)
        role=self.app.agent_runtime.roles()[0]['id']
        self.profile=self.team.profile_save({'name':'公开测试成员','role_id':role,'instructions':'只说明公开资料。','model_ids':[],'enabled':True})
        self.channel=self.team.channel_save({'name':'公开测试频道','instructions':'只分析。','context':{'module':'overview','demo':True},'member_ids':[self.profile['id']]})
        self.requests=[];self.health_service='commerce-backend';self.delay=0;self.backend_error=None
        test=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,value):
                body=json.dumps(value).encode()
                try:
                    self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
            def authorized(self):
                if self.headers.get('Authorization')!='Bearer '+test.secret:
                    self.reply(401,{'error':'unauthorized'});return False
                return True
            def do_GET(self):
                if not self.authorized():return
                test.requests.append(('health',{}))
                self.reply(200,{'service':test.health_service,'version':'0.1.0','status':'ready','token':'PRIVATE_BACKEND_SENTINEL','environment':{'private':'PRIVATE_BACKEND_SENTINEL'}})
            def do_POST(self):
                if not self.authorized():return
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.requests.append((request['tool'],request['arguments']))
                if request.get('client')!='local':self.reply(400,{'error':'invalid_client'});return
                if test.backend_error is not None:self.reply(400,{'error':test.backend_error});return
                if request['tool']=='commerce_assistant_team_discussion_get' and test.delay:time.sleep(test.delay)
                try:
                    result=test.team.invoke(request['tool'],request['arguments'])
                    result['private_config']={'token':'PRIVATE_BACKEND_SENTINEL','environment':'PRIVATE_BACKEND_SENTINEL'}
                    self.reply(200,result)
                except ValueError as error:self.reply(400,{'error':str(error)})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=False
        self.server_thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.server_thread.start()
        def stop_server():self.server.shutdown();self.server.server_close();self.server_thread.join(2)
        self.addCleanup(stop_server)
        for name,value in (('STATE',self.state),('PORT',self.server.server_address[1])):
            guard=patch.object(runtime,name,value);guard.start();self.addCleanup(guard.stop)

    def call(self,*args):
        out=io.StringIO();err=io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):code=self.cli.main(list(args))
        self.assertEqual(err.getvalue(),'')
        raw=out.getvalue()
        self.assertNotIn(self.secret,raw)
        self.assertNotIn('PRIVATE_BACKEND_SENTINEL',raw)
        return code,json.loads(raw)

    def discussion(self,key='discussion-key'):
        return self.team.discussion_start(self.channel['id'],self.channel['revision'],'公开问题',key)

    def set_status(self,discussion,status):
        with self.app.core.db() as db:
            for member in discussion['members']:
                db.execute('UPDATE agent_runs SET status=?,result=? WHERE id=?',(status,json.dumps({'answer':'公开回答','questions':[],'proposals':[]}),member['run_id']))

    def count(self,table):
        with self.app.core.db() as db:return db.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def test_doctor_validates_identity_and_reports_only_public_counts(self):
        code,result=self.call('doctor')
        self.assertEqual(code,0)
        self.assertEqual(result['health'],{'service':'commerce-backend','version':'0.1.0','status':'ready'})
        self.assertEqual(result['counts'],{'profiles':1,'channels':1,'available_models':1})
        self.assertEqual([name for name,_ in self.requests],['health','commerce_assistant_team_catalog'])
        self.assertEqual(self.count('agent_runs'),0)
        self.health_service='unrelated-service';self.requests.clear()
        code,result=self.call('doctor')
        self.assertEqual(code,3)
        self.assertEqual(result['error'],'unexpected_service')
        self.assertEqual([name for name,_ in self.requests],['health'])

    def test_missing_or_wrong_authentication_never_creates_credentials_or_prints_them(self):
        (self.state/'auth.token').write_text('wrong-synthetic-token')
        code,_=self.call('catalog');self.assertEqual(code,3)
        code,_=self.call('doctor');self.assertEqual(code,3)
        (self.state/'auth.token').unlink()
        code,result=self.call('doctor')
        self.assertEqual(code,3)
        self.assertFalse((self.state/'auth.token').exists())
        self.assertEqual(result['error'],'assistant_cli_auth_required')

    def test_catalog_and_script_entry_use_the_authenticated_runtime_request(self):
        code,result=self.call('catalog')
        self.assertEqual(code,0)
        self.assertEqual(result['profiles'][0]['id'],self.profile['id'])
        self.assertEqual(result['channels'][0]['id'],self.channel['id'])
        process=subprocess.run([sys.executable,str(ROOT/'assistant_cli.py'),'catalog'],capture_output=True,text=True,timeout=5,
            env={**os.environ,'COMMERCE_STATE':str(self.state),'COMMERCE_PORT':str(self.server.server_address[1])})
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)['profiles'][0]['id'],self.profile['id'])
        self.assertNotIn(self.secret,process.stdout+process.stderr)
        self.assertEqual(self.count('agent_runs'),0)

    def test_invalid_private_runtime_environment_has_a_sanitized_entrypoint_error(self):
        process=subprocess.run([sys.executable,str(ROOT/'assistant_cli.py'),'doctor'],capture_output=True,text=True,timeout=5,
            env={**os.environ,'COMMERCE_STATE':str(self.state),'COMMERCE_PORT':'PRIVATE_ENV_SENTINEL'})
        self.assertEqual(process.returncode,3)
        self.assertEqual(process.stderr,'')
        self.assertNotIn('PRIVATE_ENV_SENTINEL',process.stdout)
        self.assertEqual(json.loads(process.stdout)['error'],'assistant_cli_runtime_setup_required')

    def test_open_and_ask_keep_supplied_keys_and_original_ledger_identity(self):
        arguments=('open','--profile',self.profile['id'],'--channel',self.channel['id'],'--key','stable-open')
        code,first=self.call(*arguments);self.assertEqual(code,0)
        _,replay=self.call(*arguments)
        self.assertEqual(first['thread']['id'],replay['thread']['id'])
        self.assertEqual(self.count('agent_runs'),0)
        arguments=('ask','--channel',self.channel['id'],'--revision',str(self.channel['revision']),'--question','公开问题','--key','stable-ask')
        code,first=self.call(*arguments);self.assertEqual(code,0)
        _,replay=self.call(*arguments)
        self.assertEqual(first['id'],replay['id'])
        self.assertEqual(first['members'][0]['run_id'],replay['members'][0]['run_id'])
        self.assertEqual(self.count('agent_runs'),1)
        starts=[args for name,args in self.requests if name=='commerce_assistant_team_discussion_start']
        self.assertEqual([args['idempotency_key'] for args in starts],['stable-ask','stable-ask'])
        self.assertTrue(first['members'][0]['thread_id'])

    def test_stale_revision_cannot_enqueue_another_discussion(self):
        code,result=self.call('ask','--channel',self.channel['id'],'--revision','999','--question','公开问题','--key','stale')
        self.assertEqual(code,3)
        self.assertEqual(result['error'],'team_revision_changed')
        self.assertEqual(self.count('agent_runs'),0)

    def test_get_and_cancel_return_original_member_status_without_new_work(self):
        discussion=self.discussion()
        code,result=self.call('get','--discussion',discussion['id'])
        self.assertEqual((code,result['status']),(0,'queued'))
        code,result=self.call('cancel','--discussion',discussion['id'])
        self.assertEqual((code,result['status']),(0,'cancelled'))
        self.assertEqual(result['members'][0]['run_id'],discussion['members'][0]['run_id'])
        self.assertEqual(self.count('agent_runs'),1)

    def test_wait_distinguishes_terminal_states_instead_of_treating_settled_as_success(self):
        discussion=self.discussion()
        for status,want in (('completed',0),('awaiting_input',2),('awaiting_review',2),('unknown',3),('failed',3),('cancelled',3),('interrupted',3),('settled',3)):
            with self.subTest(status=status):
                self.set_status(discussion,status)
                code,result=self.call('wait','--discussion',discussion['id'],'--timeout','1')
                self.assertEqual(code,want)
                self.assertEqual(result['discussion']['status'],status)
                self.assertEqual(result['discussion']['members'][0]['status'],status)
                self.assertEqual(result['discussion']['members'][0]['run_id'],discussion['members'][0]['run_id'])
        self.assertEqual(self.count('agent_runs'),1)

    def test_wait_preserves_mixed_member_outcomes_as_partial(self):
        second=self.team.profile_save({**{key:self.profile[key] for key in ('role_id','instructions','model_ids','enabled')},'name':'第二公开成员'})
        channel=self.team.channel_save({'name':'双成员频道','instructions':'只分析。','context':{'module':'overview','demo':True},'member_ids':[self.profile['id'],second['id']]})
        discussion=self.team.discussion_start(channel['id'],channel['revision'],'公开问题','mixed')
        with self.app.core.db() as db:
            for member,status in zip(discussion['members'],('completed','failed')):
                db.execute('UPDATE agent_runs SET status=? WHERE id=?',(status,member['run_id']))
        code,result=self.call('wait','--discussion',discussion['id'],'--timeout','1')
        self.assertEqual((code,result['discussion']['status']),(3,'partial'))
        self.assertEqual([member['status'] for member in result['discussion']['members']],['completed','failed'])

    def test_wait_observes_a_later_completion_without_new_dispatch(self):
        discussion=self.discussion();self.requests.clear()
        timer=threading.Timer(.1,self.set_status,args=(discussion,'completed'));timer.start()
        try:code,result=self.call('wait','--discussion',discussion['id'],'--timeout','2')
        finally:timer.cancel();timer.join(2)
        self.assertEqual((code,result['discussion']['status']),(0,'completed'))
        self.assertEqual(result['discussion']['members'][0]['run_id'],discussion['members'][0]['run_id'])
        self.assertGreaterEqual(len(self.requests),2)
        self.assertEqual({name for name,_ in self.requests},{'commerce_assistant_team_discussion_get'})
        self.assertEqual(self.count('agent_runs'),1)

    def test_wait_keeps_polling_cancelling_until_original_runs_are_cancelled(self):
        discussion=self.discussion();self.set_status(discussion,'cancelling');self.requests.clear()
        original_get=self.team.discussion_get
        timer=None
        def cancelling_response(discussion_id):
            nonlocal timer
            value=original_get(discussion_id)
            if value['members'][0]['status']=='cancelling':
                # Exercise the transport's explicit active state as well as
                # today's aggregate "running" representation of these runs.
                value['status']='cancelling'
                if timer is None:
                    timer=threading.Timer(.1,self.set_status,args=(discussion,'cancelled'));timer.start()
            return value
        try:
            with patch.object(self.team,'discussion_get',new=cancelling_response):
                code,result=self.call('wait','--discussion',discussion['id'],'--timeout','2')
        finally:
            if timer is not None:timer.cancel();timer.join(2)
        self.assertEqual((code,result['outcome']),(3,'cancelled'))
        self.assertEqual(result['discussion']['members'][0]['status'],'cancelled')
        self.assertGreaterEqual(len(self.requests),2)
        self.assertEqual({name for name,_ in self.requests},{'commerce_assistant_team_discussion_get'})
        self.assertEqual(self.count('agent_runs'),1)

    def test_get_preserves_original_and_current_research_run_bindings_and_answer_hash(self):
        channel=self.team.channel_save({'name':'公开研究频道','instructions':'只分析。',
            'context':{'module':'research','market':'RU','demo':False},'member_ids':[self.profile['id']]})
        discussion=self.team.discussion_start(channel['id'],channel['revision'],'请调研俄罗斯厨房收纳用品并保存候选商品','research-cli')
        original=discussion['members'][0]['run_id']
        research=self.app.market_research.for_run(original)
        with self.app.core.atomic() as db:
            job=self.app.market_research._load(db,research['task_id'])
            job['status']='failed';self.app.market_research._save(db,job)
            db.execute("UPDATE agent_runs SET status='interrupted' WHERE id=?",(original,))
        current=self.app.market_research.get(research['task_id'])
        resumed=self.app.market_research.resume(current['task_id'],current['revision'],'research-cli-resume')
        with self.app.core.atomic() as db:
            job=self.app.market_research._load(db,research['task_id'])
            job['status']='completed';self.app.market_research._save(db,job)
            db.execute('UPDATE agent_runs SET status=?,result=? WHERE id=?',
                ('completed',json.dumps({'answer':'公开回答','questions':[],'proposals':[]}),resumed['run_id']))
        self.requests.clear()
        code,result=self.call('get','--discussion',discussion['id'])
        self.assertEqual(code,0)
        member=result['members'][0]
        self.assertEqual(member.get('original_run_id'),original)
        self.assertEqual(member.get('run_id'),resumed['run_id'])
        self.assertEqual(member.get('research_task_id'),research['task_id'])
        self.assertEqual(member.get('run_status'),'completed')
        self.assertEqual(member.get('answer_sha256'),hashlib.sha256('公开回答'.encode()).hexdigest())
        self.assertEqual([name for name,_ in self.requests],['commerce_assistant_team_discussion_get'])
        self.assertEqual(self.count('agent_runs'),2)

    def test_wait_timeout_only_polls_existing_discussion_and_never_cancels_or_resends(self):
        discussion=self.discussion();self.requests.clear()
        started=time.monotonic()
        code,result=self.call('wait','--discussion',discussion['id'],'--timeout','1')
        self.assertEqual(code,4)
        self.assertLess(time.monotonic()-started,1.4)
        self.assertEqual(result['outcome'],'timeout')
        self.assertEqual(result['discussion']['status'],'queued')
        self.assertEqual({name for name,_ in self.requests},{'commerce_assistant_team_discussion_get'})
        self.assertEqual(self.count('agent_runs'),1)
        self.assertEqual(self.team.discussion_get(discussion['id'])['status'],'queued')

    def test_slow_http_response_obeys_the_whole_wait_deadline(self):
        discussion=self.discussion();self.requests.clear();self.delay=1.8
        started=time.monotonic()
        code,result=self.call('wait','--discussion',discussion['id'],'--timeout','1')
        self.assertEqual((code,result['outcome']),(4,'timeout'))
        self.assertLess(time.monotonic()-started,1.4)
        self.assertEqual([name for name,_ in self.requests],['commerce_assistant_team_discussion_get'])
        self.assertEqual(self.team.discussion_get(discussion['id'])['status'],'queued')

    def test_export_writes_only_selected_markdown_with_private_permissions(self):
        destination=self.root/'team.md'
        code,result=self.call('export','--channel',self.channel['id'],'--name','公开团队','--output',str(destination))
        self.assertEqual((code,result['status']),(0,'exported'))
        self.assertTrue(destination.read_text().startswith('# 公开团队\n'))
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode),0o600)
        self.assertEqual(self.team.package_preview(destination.read_text())['sha256'],result['package_sha256'])
        self.assertNotIn(str(destination),json.dumps(result))

    def test_export_never_overwrites_existing_files_or_symbolic_links(self):
        existing=self.root/'existing.md';existing.write_text('preserve this')
        link=self.root/'link.md';link.symlink_to(existing)
        dangling=self.root/'dangling.md';dangling.symlink_to(self.root/'missing.md')
        for destination in (existing,link,dangling):
            with self.subTest(destination=destination.name):
                code,result=self.call('export','--channel',self.channel['id'],'--name','公开团队','--output',str(destination))
                self.assertEqual(code,3)
                self.assertEqual(result['error'],'assistant_cli_output_exists')
        self.assertEqual(existing.read_text(),'preserve this')
        self.assertTrue(link.is_symlink());self.assertTrue(dangling.is_symlink())
        self.assertFalse((self.root/'missing.md').exists())

    def test_failed_export_cleans_its_new_file_without_echoing_local_io_errors(self):
        destination=self.root/'failed.md'
        with patch.object(self.cli.os,'fsync',side_effect=OSError('PRIVATE_BACKEND_SENTINEL')):
            code,result=self.call('export','--channel',self.channel['id'],'--name','公开团队','--output',str(destination))
        self.assertEqual((code,result['error']),(3,'assistant_cli_output_write_failed'))
        self.assertFalse(destination.exists())

    def test_import_previews_the_exact_local_content_before_hash_bound_idempotent_import(self):
        source=self.root/'team.md';source.write_text(self.team.package_export(self.channel['id'],'公开团队')['content'])
        code,preview=self.call('preview','--file',str(source));self.assertEqual(code,0)
        self.requests.clear()
        arguments=('import','--file',str(source),'--expected-sha',preview['sha256'],'--key','stable-import')
        code,first=self.call(*arguments);self.assertEqual(code,0)
        _,second=self.call(*arguments)
        self.assertEqual(first,second)
        self.assertFalse(first['profiles'][0]['enabled'])
        self.assertEqual(self.count('assistant_team_profiles'),2)
        self.assertEqual([name for name,_ in self.requests],['commerce_assistant_team_package_preview','commerce_assistant_team_package_import']*2)
        for name,args in self.requests:
            self.assertEqual(args['content'],source.read_text())
            self.assertNotIn('file',args)
            if name.endswith('import'):self.assertEqual(args['idempotency_key'],'stable-import')
        self.assertEqual(self.count('agent_runs'),0)

    def test_changed_hash_and_invalid_local_files_never_reach_import(self):
        source=self.root/'team.md';source.write_text(self.team.package_export(self.channel['id'],'公开团队')['content'])
        code,result=self.call('import','--file',str(source),'--expected-sha','0'*64,'--key','changed')
        self.assertEqual((code,result['error']),(3,'team_package_changed'))
        self.assertNotIn('commerce_assistant_team_package_import',[name for name,_ in self.requests])
        self.requests.clear();source.write_bytes(b'x'*65537)
        code,result=self.call('preview','--file',str(source))
        self.assertEqual((code,result['error']),(3,'assistant_cli_package_too_large'))
        fifo=self.root/'pipe';os.mkfifo(fifo)
        for path in (fifo,self.root):
            code,_=self.call('preview','--file',str(path));self.assertEqual(code,3)
        self.assertEqual(self.requests,[])

    def test_private_backend_errors_and_unknown_cli_arguments_are_never_echoed(self):
        self.backend_error='token=PRIVATE_BACKEND_SENTINEL /Users/private/config'
        code,result=self.call('catalog')
        self.assertEqual((code,result['error']),(3,'assistant_cli_request_failed'))
        code,result=self.call('invoke','--token',self.secret)
        self.assertEqual((code,result['error']),(2,'assistant_cli_invalid_arguments'))


if __name__=='__main__':unittest.main()
