"""Bounded translation-only jobs using the user's existing Hermes model route."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import subprocess
import threading
import uuid
from research import canonical, digest, drift

_slots = threading.BoundedSemaphore(2)
ROOT = Path(__file__).resolve().parent


def stamp(): return datetime.now(timezone.utc).isoformat()


def normalize(data):
    if not isinstance(data, dict) or set(data) != {'language', 'items'} or not isinstance(data['language'], str) or not 1 <= len(data['language']) <= 50:
        raise ValueError('invalid_translation_input')
    items = data['items']
    if not isinstance(items, list) or not 1 <= len(items) <= 30:
        raise ValueError('translation_batch_size')
    seen = set(); total = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {'id', 'text'}:
            raise ValueError('invalid_translation_item')
        ident, text = item['id'], item['text']
        if not isinstance(ident, str) or not 1 <= len(ident) <= 80 or ident in seen or not isinstance(text, str) or not text.strip() or len(text) > 6000:
            raise ValueError('invalid_translation_item')
        seen.add(ident); total += len(text)
    if total > 12000: raise ValueError('translation_text_too_large_split_batch')
    return data


def model_command():
    executable = shutil.which('hermes') or str(Path.home() / '.local/bin/hermes')
    if not Path(executable).is_file(): raise ValueError('translation_hermes_unavailable')
    profile = Path.home() / '.hermes/profiles/commerce-bot'
    if not profile.is_dir(): raise ValueError('translation_profile_unavailable')
    env = os.environ.copy(); env['HERMES_HOME'] = str(profile)
    resolved = subprocess.run([executable, '--print-runtime-command', '--module', 'runpy'],
                              text=True, capture_output=True, timeout=15, env=env)
    try: command = json.loads(resolved.stdout)
    except (ValueError, TypeError): raise ValueError('translation_runtime_unavailable') from None
    entry = "runpy.run_module('runpy', run_name='__main__', alter_sys=True)"
    if resolved.returncode or len(command) != 4 or command[1:3] != ['-I', '-c'] or not command[3].endswith(entry):
        raise ValueError('translation_runtime_unavailable')
    command[3] = command[3][:-len(entry)] + "runpy.run_path(sys.argv[1], run_name='__main__')"
    return command + [str(ROOT / 'translation_worker.py')], env


def run_model(data):
    command, env = model_command()
    # No shell, no arbitrary command/URL arguments, no chat history or agent tools.
    done = subprocess.run(command,
                          input=json.dumps(data, ensure_ascii=False), text=True, capture_output=True,
                          timeout=100, env=env, cwd=ROOT)
    if done.returncode: raise ValueError('translation_provider_failed')
    try: result = json.loads(done.stdout)
    except (ValueError, TypeError): raise ValueError('translation_invalid_response') from None
    return validate_response(data, result)


def validate_response(data, result):
    if not isinstance(result, dict) or not isinstance(result.get('translations'), list): raise ValueError('translation_invalid_response')
    source = {x['id']: x['text'] for x in data['items']}
    values = result['translations']
    if len(values) != len(source): raise ValueError('translation_incomplete_response')
    seen = set(); output = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {'id', 'zh'}: raise ValueError('translation_invalid_response')
        ident, zh = value['id'], value['zh']
        if ident not in source or ident in seen or not isinstance(zh, str) or not zh.strip() or len(zh) > 12000:
            raise ValueError('translation_invalid_response')
        seen.add(ident)
        output.append(dict(id=ident, original_sha256=digest(source[ident]), zh=zh,
                           status='pending_review', warnings=drift(source[ident], zh)))
    return dict(translations=output, provider=str(result.get('provider', 'unknown'))[:100],
                model=str(result.get('model', 'unknown'))[:160], translated_at=stamp(),
                prompt_version='zh-faithful-v1', tools_enabled=False, independently_verified=False)


class TranslationJobs:
    def __init__(self, core):
        self.core = core
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS translations (id TEXT PRIMARY KEY, idem TEXT UNIQUE, input TEXT, status TEXT, result TEXT, created_at TEXT)')
            db.execute("UPDATE translations SET status='failed', result=? WHERE status IN ('queued','running')", (canonical({'error': 'translation_interrupted_no_automatic_retry'}),))

    def start(self, data, key):
        normalize(data)
        if not isinstance(key, str) or not key.strip() or len(key) > 160: raise ValueError('invalid_idempotency_key')
        frozen = canonical(data)
        with self.core.db() as db:
            old = db.execute('SELECT id,input FROM translations WHERE idem=?', (key,)).fetchone()
            if old:
                if old[1] != frozen: raise ValueError('idempotency_conflict')
                return self.get(old[0])
            if not _slots.acquire(blocking=False): raise ValueError('translation_busy_try_later')
            ident = str(uuid.uuid4())
            try: db.execute('INSERT INTO translations VALUES (?,?,?,?,?,?)', (ident, key, frozen, 'queued', None, stamp()))
            except Exception:
                _slots.release(); raise
        thread = threading.Thread(target=self._work, args=(ident, data), daemon=True); thread.start()
        return self.get(ident)

    def _work(self, ident, data):
        try:
            with self.core.db() as db: db.execute("UPDATE translations SET status='running' WHERE id=?", (ident,))
            result = run_model(data); status = 'completed'
        except Exception as error:
            result = {'error': str(error) if isinstance(error, ValueError) else 'translation_failed'}; status = 'failed'
        finally:
            _slots.release()
        with self.core.db() as db: db.execute('UPDATE translations SET status=?,result=? WHERE id=?', (status, canonical(result), ident))

    def get(self, ident):
        with self.core.db() as db: row = db.execute('SELECT id,input,status,result,created_at FROM translations WHERE id=?', (ident,)).fetchone()
        if not row: raise ValueError('translation_not_found')
        return dict(id=row[0], input_sha256=digest(row[1]), status=row[2], result=json.loads(row[3]) if row[3] else None, created_at=row[4])
