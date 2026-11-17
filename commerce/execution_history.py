"""Read-only, paginated metadata over the three original execution ledgers.

No runtime getter is used here: some getters attach live detail or advance work.
The cursor fixes each ledger's insertion watermark and a unique ordering key.
"""
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3

from assistant_team import PRIVATE
from extension_runtime.validation import redact

ORIGINS = {'agent': 'agent_runs', 'skills': 'extension_runs',
           'assistant-team': 'assistant_team_discussions'}
ACTIVE = {'queued', 'running', 'cancel_requested', 'cancelling'}
READ_ONLY = {'commerce_execution_history'}


def tools(schema):
    return [('commerce_execution_history', '只读分页检索模型、能力和团队的全部本地执行元信息；保留原状态，不执行或恢复', schema({
        'origin': {'type': 'string', 'enum': ['all', *ORIGINS]},
        'query': {'type': 'string', 'maxLength': 200},
        'status': {'type': 'string', 'maxLength': 64},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
        'cursor': {'type': 'string', 'minLength': 1, 'maxLength': 4096}}))]


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _time(value):
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            value = parsed.timestamp() if parsed.tzinfo else None
        except (ValueError, OverflowError, OSError):
            return None
    return float(value) if type(value) in (int, float) and math.isfinite(value) and abs(value) <= 8640000000000 else None


def _title(value, secrets=()):
    if not isinstance(value, str) or not value.strip():
        return None
    # Reuse both domains' existing public boundaries before limiting the title.
    value = PRIVATE.sub('[redacted]', redact(value, secrets))
    value = re.sub(r'https?://[^/\s]*@', '[redacted]@', value, flags=re.I)
    return ' '.join(value.split()) or None


def _status(value):
    # Original state codes are never merged (completed and succeeded stay apart).
    return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}', value) else None


class ExecutionHistory:
    def __init__(self, service):
        self.core = service.core
        self.extensions = service.extensions
        # Process-local authentication needs no persistent credential or DB write.
        # A service restart expires old cursors; clients can reread page one.
        self._cursor_key = secrets.token_bytes(32)

    def _secrets(self, refs, cache):
        values = []
        for ref in json.loads(refs or '[]'):
            ident, version = ref.get('id'), ref.get('version')
            if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,79}', ident) or type(version) is not int or version < 1:
                raise ValueError('execution_history_source_unavailable')
            if (ident, version) not in cache:
                try:
                    cache[ident, version] = list(self.extensions._secret_headers(ident, version).values())
                except (ValueError, OSError):
                    raise ValueError('execution_history_source_unavailable') from None
            for secret in cache[ident, version]:
                values.append(secret)
                if secret.startswith(('Bearer ', 'Basic ')):
                    values.append(secret.split(' ', 1)[1])
        return values

    def invoke(self, name, args):
        if name != 'commerce_execution_history':
            raise ValueError('unknown_tool')
        if not isinstance(args, dict) or set(args) - {'origin', 'query', 'status', 'limit', 'cursor'}:
            raise ValueError('execution_history_invalid_query')
        return self.listing(**args)

    def _cursor(self, filters, watermarks, last):
        raw = _json({'v': 1, 'filters': filters, 'watermarks': watermarks, 'last': last}).encode()
        encoded = base64.urlsafe_b64encode(raw).decode().rstrip('=')
        return 'eh1.' + encoded + '.' + hmac.new(self._cursor_key, raw, hashlib.sha256).hexdigest()

    def _decode(self, cursor, filters):
        try:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError()
            prefix, encoded, checksum = cursor.split('.')
            if prefix != 'eh1' or not re.fullmatch(r'[A-Za-z0-9_-]+', encoded) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
                raise ValueError()
            raw = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
            if not hmac.compare_digest(hmac.new(self._cursor_key, raw, hashlib.sha256).hexdigest(), checksum):
                raise ValueError()
            value = json.loads(raw)
            if set(value) != {'v', 'filters', 'watermarks', 'last'} or type(value['v']) is not int or value['v'] != 1 or _json(value).encode() != raw:
                raise ValueError()
            if value['filters'] != filters:
                raise ValueError()
            marks, last = value['watermarks'], value['last']
            if not isinstance(marks, dict) or set(marks) != set(ORIGINS) or any(type(n) is not int or n < 0 for n in marks.values()):
                raise ValueError()
            if not isinstance(last, list) or len(last) != 3 or last[0] not in ORIGINS or not isinstance(last[1], str) or not 1 <= len(last[1]) <= 160:
                raise ValueError()
            if last[2] is not None and (type(last[2]) not in (int, float) or _time(last[2]) != last[2]):
                raise ValueError()
            return marks, last
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            raise ValueError('execution_history_invalid_cursor') from None

    @staticmethod
    def _team_status(db, row):
        members, state, mode, plan_length = row[6:10]
        state = _status(state)
        if state in ('blocked', 'unknown', 'failed', 'interrupted', 'awaiting_input', 'awaiting_review'):
            return state
        if members is None:
            return None
        statuses = []
        for member in json.loads(members):
            if not isinstance(member, dict) or not isinstance(member.get('run_id'), str):
                return None
            base = member.get('continuation_run_id', member['run_id'])
            research = db.execute("SELECT CASE WHEN json_valid(j.document) THEN json_extract(j.document,'$.status') END FROM market_research_runs r LEFT JOIN market_research_jobs j ON j.task_id=r.task_id WHERE r.run_id=?", (base,)).fetchone()
            if research:
                status = _status(research[0])
            else:
                run = db.execute('SELECT status FROM agent_runs WHERE id=?', (base,)).fetchone()
                status = _status(run[0]) if run else None
            if status is None:
                return None
            statuses.append(status)
        # Same precedence as TeamDiscussions.get, from stored references only.
        if any(s in ACTIVE for s in statuses):
            status = 'queued' if all(s == 'queued' for s in statuses) else 'running'
        elif 'unknown' in statuses:
            status = 'unknown'
        elif statuses and len(set(statuses)) == 1:
            status = statuses[0]
        else:
            status = 'partial'
        if state == 'cancelled':
            return 'cancelling' if any(s in ACTIVE for s in statuses) else 'unknown' if 'unknown' in statuses else 'cancelled'
        if mode == 'collaborate':
            if state == 'completed':
                return 'completed'
            if (state == 'running' and not any(s in ACTIVE for s in statuses)
                    or plan_length is not None and len(statuses) < plan_length and status == 'completed'):
                return 'running'
        return status

    @staticmethod
    def _rows(db, marks, origin, last):
        # Extract only list metadata. Request/result/model/pins objects never
        # leave SQLite; the frozen capability name is selected as a scalar.
        sql = """WITH history AS (
          SELECT 'agent' origin,id,history_time(created) at,status,
            CASE WHEN json_valid(payload) AND json_type(payload,'$.question')='text' THEN json_extract(payload,'$.question') END title,
            NULL version,NULL members,NULL state,NULL mode,NULL plan_length,NULL redactions
          FROM agent_runs WHERE rowid<=?
          UNION ALL
          SELECT 'skills',r.id,history_time(r.created),r.status,
            COALESCE((SELECT CASE WHEN json_type(p.value,'$.definition.name')='text' THEN json_extract(p.value,'$.definition.name') END
              FROM json_each(CASE WHEN json_valid(r.document) THEN r.document ELSE '{}' END,'$.pins') p WHERE p.key=r.extension_id),
              CASE WHEN json_valid(v.document) AND json_type(v.document,'$.name')='text' THEN json_extract(v.document,'$.name') END),
            CASE WHEN json_valid(r.document) AND json_type(r.document,'$.version')='integer' THEN json_extract(r.document,'$.version') END,
            NULL,NULL,NULL,NULL,
            (SELECT json_group_array(json_object('id',p.key,'version',json_extract(p.value,'$.version')))
              FROM json_each(CASE WHEN json_valid(r.document) THEN r.document ELSE '{}' END,'$.pins') p
              WHERE p.type='object' AND json_extract(p.value,'$.definition.kind')='plugin')
          FROM extension_runs r LEFT JOIN extension_versions v ON v.id=r.extension_id
            AND v.version=CASE WHEN json_valid(r.document) THEN json_extract(r.document,'$.version') END WHERE r.rowid<=?
          UNION ALL
          SELECT 'assistant-team',id,history_time(created),NULL,
            CASE WHEN json_valid(document) AND json_type(document,'$.question')='text' THEN json_extract(document,'$.question') END,NULL,
            CASE WHEN json_valid(document) AND json_type(document,'$.members')='array' THEN json_extract(document,'$.members') END,
            CASE WHEN json_valid(document) THEN json_extract(document,'$.collaboration_state') END,
            CASE WHEN json_valid(document) THEN json_extract(document,'$.mode') END,
            CASE WHEN json_valid(document) AND json_type(document,'$.plan')='array' THEN json_array_length(document,'$.plan') END,NULL
          FROM assistant_team_discussions WHERE rowid<=?
        ) SELECT * FROM history WHERE (?='all' OR origin=?)"""
        args = [marks[key] for key in ORIGINS] + [origin, origin]
        if last:
            source, ident, at = last
            tie = '(origin>? OR (origin=? AND id>?))'
            if at is None:
                sql += ' AND at IS NULL AND ' + tie
                args += [source, source, ident]
            else:
                sql += ' AND (at IS NULL OR at<? OR (at=? AND ' + tie + '))'
                args += [at, at, source, source, ident]
        return db.execute(sql + ' ORDER BY at IS NULL,at DESC,origin COLLATE BINARY,id COLLATE BINARY', args)

    def listing(self, origin='all', query='', status='all', limit=30, cursor=None):
        if origin not in ('all', *ORIGINS) or not isinstance(query, str) or len(query) > 200 or not isinstance(status, str) or len(status) > 64 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('execution_history_invalid_query')
        if any(ord(c) < 32 for c in query + status):
            raise ValueError('execution_history_invalid_query')
        query, status = query.strip().casefold(), status.strip()
        if status not in ('', 'all') and _status(status) is None:
            raise ValueError('execution_history_invalid_query')
        filters = {'origin': origin, 'query': query, 'status': status or 'all', 'limit': limit}
        decoded = self._decode(cursor, filters) if cursor is not None else None
        # A separate read-only connection also protects callers accidentally
        # invoking this projection from inside a write transaction.
        try:
            with closing(sqlite3.connect(Path(self.core.path).resolve().as_uri() + '?mode=ro', uri=True, timeout=20)) as db:
                db.create_function('history_time', 1, _time, deterministic=True)
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                current = {key: db.execute('SELECT COALESCE(MAX(rowid),0) FROM ' + table).fetchone()[0] for key, table in ORIGINS.items()}
                marks, last = decoded if decoded else (current, None)
                if any(marks[key] > current[key] for key in ORIGINS):
                    raise ValueError('execution_history_invalid_cursor')
                if last:
                    anchor = db.execute('SELECT history_time(created) FROM ' + ORIGINS[last[0]] + ' WHERE id=? AND rowid<=?', (last[1], marks[last[0]])).fetchone()
                    if not anchor or anchor[0] != last[2] or origin != 'all' and origin != last[0]:
                        raise ValueError('execution_history_invalid_cursor')
                items, secret_cache = [], {}
                for row in self._rows(db, marks, origin, last):
                    source, ident, at, raw_status, title, version = row[:6]
                    state = self._team_status(db, row) if source == 'assistant-team' else _status(raw_status)
                    if not isinstance(ident, str) or not 1 <= len(ident) <= 160 or any(ord(c) < 32 for c in ident):
                        raise ValueError('execution_history_source_unavailable')
                    title = _title(title, self._secrets(row[10], secret_cache) if source == 'skills' else ())
                    if filters['status'] != 'all' and state != filters['status']:
                        continue
                    if query and query not in ' '.join((source + ':' + ident, title or '', state or '')).casefold():
                        continue
                    items.append({'key': source + ':' + ident, 'id': ident, 'origin': source,
                                  'title': title[:240] if title else None, 'status': state, 'at': at,
                                  'version': version if type(version) is int and version > 0 else None})
                    if len(items) > limit:
                        break
                more = len(items) > limit
                items = items[:limit]
                next_cursor = self._cursor(filters, marks, [items[-1]['origin'], items[-1]['id'], items[-1]['at']]) if more else None
                return {'schema': 'commerce-execution-history-v1', 'read_only': True,
                        'items': items, 'next_cursor': next_cursor, 'filters': filters}
        except sqlite3.Error:
            raise ValueError('execution_history_source_unavailable') from None
