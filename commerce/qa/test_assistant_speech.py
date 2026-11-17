"""Answer-bound local speech: synthetic ledger and executable fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import base64
import hashlib
import importlib
import importlib.util
import io
import json
import os
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core


FAKE_TOOL = r'''#!PYTHON
from pathlib import Path
import json, os, stat, subprocess, sys, time, wave
args=sys.argv[1:]
mode=os.environ.get('FAKE_SPEECH_MODE','ready')
if Path(sys.argv[0]).name=='say':
    if args==['-v','?']:
        print('Samantha en_US # public voice')
        if mode!='no_chinese':print('Tingting zh_CN # public voice')
        sys.exit(0)
    source=Path(args[args.index('-f')+1]);output=Path(args[args.index('-o')+1])
    Path(os.environ['FAKE_SPEECH_AUDIT']).write_text(json.dumps({
        'text':source.read_text(), 'input_mode':stat.S_IMODE(source.stat().st_mode),
        'output_mode':stat.S_IMODE(output.stat().st_mode),
        'directory_mode':stat.S_IMODE(source.parent.stat().st_mode),
        'directory':str(source.parent), 'voice':args[args.index('-v')+1]}))
    if mode=='error':
        print('/private/PRIVATE_CREDENTIAL_SENTINEL',file=sys.stderr);sys.exit(1)
    if mode in ('hang','orphan_error'):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
        Path(os.environ['FAKE_SPEECH_CHILD']).write_text(str(child.pid))
        if mode=='orphan_error':sys.exit(1)
        time.sleep(60)
    output.write_bytes(b'FORM-synthetic-aiff')
else:
    target=Path(args[-1])
    if mode=='oversize':target.write_bytes(b'x'*(7*1024*1024));sys.exit(0)
    if mode=='invalid_audio':target.write_bytes(b'not audio');sys.exit(0)
    with wave.open(str(target),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2)
        audio.setframerate(44100 if mode=='wrong_format' else 22050)
        audio.writeframes(b'\0\0'*2205)
'''


class AssistantSpeech(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('assistant_speech')
        self.assertIsNotNone(spec, 'local answer speech module is not implemented')
        self.speech = importlib.import_module('assistant_speech')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = Core(self.root/'ledger.sqlite')
        with self.core.db() as db:
            db.execute('CREATE TABLE copilot_turns(id TEXT PRIMARY KEY,thread_id TEXT,idem TEXT,request TEXT,question TEXT,run_id TEXT UNIQUE,context_sha TEXT,revision INTEGER,created REAL,UNIQUE(thread_id,idem))')
            db.execute('CREATE TABLE agent_runs(id TEXT PRIMARY KEY,idem TEXT UNIQUE,request TEXT,payload TEXT,status TEXT,created REAL,updated REAL,owner TEXT,expires REAL,result TEXT,trace TEXT)')
            db.execute('INSERT INTO copilot_turns VALUES (?,?,?,?,?,?,?,?,?)', ('turn-a','thread-a','synthetic','{}','public question','run-a','context',0,0))
            db.execute('INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('run-a','synthetic','{}','{}','completed',0,0,None,None,json.dumps({'answer':'公开测试回答。','questions':[],'proposals':[]}), '[]'))
        self.reader = self.speech.SpeechReader(SimpleNamespace(core=self.core))
        self.text = '公开测试回答。'
        self.args = {'thread_id':'thread-a','run_id':'run-a', 'expected_text_sha256':hashlib.sha256(self.text.encode()).hexdigest()}
        self.audit = self.root/'audit.json'
        self.child = self.root/'child.pid'
        for tool in ('say','ffmpeg'):
            target=self.root/tool
            target.write_text(FAKE_TOOL.replace('PYTHON',sys.executable,1))
            target.chmod(0o700)
        self.addCleanup(patch.stopall)
        patch.object(self.speech.platform,'system',return_value='Darwin').start()
        patch.object(self.speech.shutil,'which',side_effect=lambda name:str(self.root/name)).start()
        patch.dict(os.environ,{'FAKE_SPEECH_MODE':'ready','FAKE_SPEECH_AUDIT':str(self.audit),'FAKE_SPEECH_CHILD':str(self.child)}).start()

    def render(self, **overrides):
        return self.reader.invoke('commerce_assistant_speech',{**self.args,**overrides})

    def change_result(self, answer=None, status='completed', raw=None):
        with self.core.db() as db:
            db.execute('UPDATE agent_runs SET status=?,result=? WHERE id=?', (status, raw if raw is not None else json.dumps({'answer':answer}), 'run-a'))

    def test_completed_answer_returns_valid_bounded_wav_without_paths_or_playback(self):
        result=self.render()
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['mime_type'],'audio/wav')
        self.assertEqual(result['text_sha256'],self.args['expected_text_sha256'])
        self.assertTrue(result['audio_data_url'].startswith('data:audio/wav;base64,'))
        payload=base64.b64decode(result['audio_data_url'].split(',',1)[1],validate=True)
        with wave.open(io.BytesIO(payload)) as audio:
            self.assertEqual((audio.getnchannels(),audio.getframerate(),audio.getsampwidth()),(1,22050,2))
        self.assertEqual(result['byte_length'],len(payload))
        self.assertEqual(result['audio_sha256'],hashlib.sha256(payload).hexdigest())
        self.assertNotIn(str(self.root),str(result))
        audit=json.loads(self.audit.read_text())
        self.assertEqual(audit['text'],self.text)
        self.assertEqual((audit['input_mode'],audit['output_mode'],audit['directory_mode']),(0o600,0o600,0o700))
        self.assertFalse(Path(audit['directory']).exists())
        with self.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT status FROM agent_runs').fetchone()[0],'completed')

    def test_public_tool_schema_requires_bound_ids_and_rejects_extra_input(self):
        schema=lambda properties=None,required=None:{'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}
        definitions=self.speech.definitions(schema,{'type':'string'})
        self.assertEqual(len(definitions),1)
        self.assertEqual(set(definitions[0][2]['required']),set(self.args))
        for extra in ({'text':'secret'},{'path':'/etc/passwd'},{'command':'say secret'},{'voice':'unreviewed'},{'autoplay':True}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError,'assistant_speech_invalid_arguments'):
                self.render(**extra)
        with self.assertRaisesRegex(ValueError,'unknown_tool'):
            self.reader.invoke('commerce_arbitrary_speech',self.args)
        self.assertFalse(self.audit.exists())

    def test_foreign_thread_never_reads_or_renders_the_answer(self):
        with self.assertRaisesRegex(ValueError,'assistant_speech_run_not_found'):
            self.render(thread_id='thread-other')
        self.assertFalse(self.audit.exists())

    def test_authoritative_research_successor_keeps_thread_ownership_without_copying_a_turn(self):
        with self.core.db() as db:
            db.execute('CREATE TABLE market_research_runs(run_id TEXT PRIMARY KEY, task_id TEXT)')
            db.execute('CREATE TABLE market_research_jobs(task_id TEXT PRIMARY KEY, document TEXT)')
            db.execute('INSERT INTO agent_runs SELECT ?, ?, request,payload,status,created,updated,owner,expires,result,trace FROM agent_runs WHERE id=?', ('run-b','research-resume','run-a'))
            db.execute('INSERT INTO market_research_runs VALUES (?,?)', ('run-b','research-task'))
            db.execute('INSERT INTO market_research_jobs VALUES (?,?)', ('research-task',json.dumps({'thread_id':'thread-a','run_id':'run-b'})))
        self.assertEqual(self.reader._answer('thread-a','run-b',self.args['expected_text_sha256']),self.text)
        with self.assertRaisesRegex(ValueError,'assistant_speech_run_not_found'):
            self.reader._answer('thread-other','run-b',self.args['expected_text_sha256'])
        with self.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_turns').fetchone()[0],1)

    def test_only_completed_runs_can_be_rendered(self):
        for status in ('queued','running','awaiting_input','awaiting_review','failed','unknown','cancelled'):
            self.change_result(self.text,status)
            with self.subTest(status=status), self.assertRaisesRegex(ValueError,'assistant_speech_answer_not_completed'):
                self.render()
        self.assertFalse(self.audit.exists())

    def test_hash_mismatch_and_malformed_arguments_never_invoke_synthesis(self):
        with self.assertRaisesRegex(ValueError,'assistant_speech_answer_changed'):
            self.render(expected_text_sha256='0'*64)
        for key,value in (('thread_id',''),('run_id','x\nprivate'),('run_id',42),('expected_text_sha256','not-a-hash')):
            with self.subTest(key=key,value=value), self.assertRaisesRegex(ValueError,'assistant_speech_invalid_arguments'):
                self.render(**{key:value})
        self.assertFalse(self.audit.exists())

    def test_empty_corrupt_and_oversized_answers_are_rejected(self):
        for raw in ('not json','[]','{"answer":null}','{"answer":""}'):
            self.change_result(raw=raw)
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError,'assistant_speech_answer_unavailable'):
                self.render()
        self.change_result('a'*2001)
        with self.assertRaisesRegex(ValueError,'assistant_speech_answer_too_large'):
            self.render()
        self.assertFalse(self.audit.exists())

    def test_speech_markup_cannot_override_voice_or_rate(self):
        text='公开 [[voice Evil]][[rate 900]] 测试'
        self.change_result(text)
        self.render(expected_text_sha256=hashlib.sha256(text.encode()).hexdigest())
        audit=json.loads(self.audit.read_text())
        self.assertNotIn('[[',audit['text'])
        self.assertEqual(audit['voice'],'Tingting')

    def test_overlapping_speech_markup_is_also_read_literally(self):
        text='公开 [[[voice Evil]]]] 测试'
        self.change_result(text)
        self.render(expected_text_sha256=hashlib.sha256(text.encode()).hexdigest())
        audit=json.loads(self.audit.read_text())
        self.assertNotIn('[[',audit['text'])
        self.assertNotIn(']]',audit['text'])

    def test_unsupported_platform_is_explicit_and_does_not_render(self):
        with patch.object(self.speech.platform,'system',return_value='Linux'):
            result=self.render()
        self.assertEqual((result['status'],result['reason']),('unavailable','unsupported_platform'))
        self.assertTrue(result['setup_required'])
        self.assertFalse(self.audit.exists())

    def test_missing_dependencies_are_explicit_without_paths(self):
        with patch.object(self.speech.shutil,'which',return_value=None):
            result=self.render()
        self.assertEqual((result['status'],result['reason']),('unavailable','local_dependencies_missing'))
        self.assertNotIn('audio_data_url',result)
        self.assertFalse(self.audit.exists())

    def test_missing_suitable_voice_does_not_render_in_an_unrelated_language(self):
        with patch.dict(os.environ,{'FAKE_SPEECH_MODE':'no_chinese'}):
            result=self.render()
        self.assertEqual((result['status'],result['reason']),('unavailable','suitable_voice_unavailable'))
        self.assertFalse(self.audit.exists())

    def test_process_failure_hides_private_error_and_removes_input(self):
        with patch.dict(os.environ,{'FAKE_SPEECH_MODE':'error'}):
            result=self.render()
        self.assertEqual((result['status'],result['reason']),('failed','local_render_failed'))
        self.assertNotIn('PRIVATE_CREDENTIAL_SENTINEL',str(result))
        self.assertNotIn('audio_data_url',result)
        self.assertFalse(Path(json.loads(self.audit.read_text())['directory']).exists())

    def test_invalid_or_oversized_audio_is_not_returned(self):
        for mode,reason in (('oversize','audio_too_large'),('invalid_audio','invalid_audio'),('wrong_format','invalid_audio')):
            with self.subTest(mode=mode), patch.dict(os.environ,{'FAKE_SPEECH_MODE':mode}):
                result=self.render()
                self.assertEqual((result['status'],result['reason']),('failed',reason))
                self.assertNotIn('audio_data_url',result)
                self.assertFalse(Path(json.loads(self.audit.read_text())['directory']).exists())

    def assert_child_stopped(self):
        pid=int(self.child.read_text())
        def cleanup():
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
        self.addCleanup(cleanup)
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            try:os.kill(pid,0)
            except ProcessLookupError:return
            time.sleep(.02)
        self.fail('speech subprocess descendant survived cancellation')

    def test_error_exit_also_stops_surviving_process_group(self):
        with patch.dict(os.environ,{'FAKE_SPEECH_MODE':'orphan_error'}):
            result=self.render()
        self.assertEqual((result['status'],result['reason']),('failed','local_render_failed'))
        self.assert_child_stopped()

    def test_timeout_stops_process_group_and_cleans_temporary_files(self):
        with patch.dict(os.environ,{'FAKE_SPEECH_MODE':'hang'}), patch.object(self.speech,'TIMEOUT_SECONDS',.7):
            result=self.render()
        self.assertEqual((result['status'],result['reason']),('failed','render_timeout'))
        self.assert_child_stopped()
        self.assertFalse(Path(json.loads(self.audit.read_text())['directory']).exists())

    def test_trusted_cancellation_stops_render_and_rejects_overlapping_work(self):
        cancel=threading.Event()
        with patch.dict(os.environ,{'FAKE_SPEECH_MODE':'hang'}), ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.reader.render,**self.args,cancel_event=cancel)
            deadline=time.monotonic()+3
            while not self.child.exists() and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(self.child.exists())
            busy=self.render()
            self.assertEqual((busy['status'],busy['reason']),('failed','render_busy'))
            cancel.set()
            result=pending.result(timeout=3)
        self.assertEqual((result['status'],result['reason']),('cancelled','render_cancelled'))
        self.assert_child_stopped()
        self.assertFalse(Path(json.loads(self.audit.read_text())['directory']).exists())

    def test_pre_cancelled_request_never_starts_local_render(self):
        cancel=threading.Event();cancel.set()
        result=self.reader.render(**self.args,cancel_event=cancel)
        self.assertEqual(result['status'],'cancelled')
        self.assertFalse(self.audit.exists())


if __name__=='__main__':unittest.main()
