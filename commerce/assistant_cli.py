"""Headless commands for the existing, authenticated local assistant teams.

This client never starts a server or worker. A wait only observes the discussion
created by ask; losing the connection or reaching its deadline never resends it.
"""
import argparse
import json
import math
import os
import re
import socket
import stat
import sys
import time
import urllib.error

try:
    import runtime
except (ValueError, OSError):
    # Runtime configuration errors can contain environment values in their
    # exception text. Keep even module-import failures out of terminal traces.
    runtime = None

PACKAGE_BYTES = 65536
EVENT_BYTES = 8192
ACTIVE = {'queued', 'running', 'cancel_requested', 'cancelling'}
WAIT_CODES = {'completed': 0, 'awaiting_input': 2, 'awaiting_review': 2,
              'unknown': 3, 'failed': 3, 'cancelled': 3, 'partial': 3, 'interrupted': 3}
SAFE_ERRORS = {'unexpected_service', 'unauthorized', 'invalid_client', 'idempotency_conflict',
               'team_not_found', 'team_revision_changed', 'team_profile_disabled',
               'team_member_outside_channel', 'team_no_available_model', 'team_discussion_not_found',
               'team_invalid_package', 'team_package_private_data', 'team_package_changed',
               'team_limit_reached', 'team_invalid_text', 'invalid_idempotency_key', 'model_not_ready',
               'team_invalid_arguments', 'team_invalid_routing', 'team_invalid_keywords',
               'team_ambiguous_mention', 'team_unknown_mention', 'team_model_changed',
               'team_preset_not_found', 'team_playbook_not_found', 'team_discussion_changed',
               'team_discussion_requires_review', 'team_discussion_reply_required',
               'team_collaboration_cancelled', 'team_collaboration_dispatch_failed',
               'team_collaboration_awaiting_input', 'team_collaboration_awaiting_review',
               'team_collaboration_unknown', 'team_collaboration_failed', 'team_collaboration_interrupted',
               'team_collaboration_blocked', 'team_trigger_not_found', 'team_trigger_revision_changed',
               'team_trigger_invalid_arguments', 'team_trigger_invalid_definition', 'team_trigger_invalid_name',
               'team_trigger_invalid_question', 'team_trigger_invalid_kind', 'team_trigger_invalid_playbook',
               'team_trigger_invalid_schedule', 'team_trigger_invalid_time', 'team_trigger_invalid_payload',
               'team_trigger_invalid_enabled', 'team_trigger_invalid_event_id', 'team_trigger_limit_reached',
               'team_trigger_channel_not_found', 'team_trigger_source_not_found', 'team_trigger_source_changed',
               'team_trigger_profile_disabled', 'team_trigger_playbook_not_found', 'team_trigger_model_unavailable',
               'team_trigger_event_limit', 'team_trigger_event_conflict', 'team_trigger_disabled',
               'team_trigger_channel_busy', 'team_trigger_not_ready', 'team_trigger_slot_missed',
               'team_trigger_dispatch_rejected', 'team_trigger_dispatch_unknown',
               'team_trigger_source_unknown', 'team_trigger_recovered_unknown'}


class _CLIError(Exception):
    def __init__(self, code, exit_code=3):
        self.code, self.exit_code = code, exit_code


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal diagnostics repeat unrecognized arguments, which may
        # include a credential pasted into the wrong command.
        raise _CLIError('assistant_cli_invalid_arguments', 2)


def _positive_revision(value):
    try:
        result = int(value)
        if result < 1:
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('revision must be positive') from None


def _timeout(value):
    try:
        result = float(value)
        if not math.isfinite(result) or not 1 <= result <= 120:
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('timeout must be 1..120 seconds') from None


def _finite_float(value):
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('expected updated must be finite') from None


def _parser():
    parser = _Parser(description='Use the existing local assistant-team service; never starts background work.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Check service identity and member/channel/model counts.')
    commands.add_parser('catalog', help='List local members, channels, roles and available models.')
    opened = commands.add_parser('open', help='Open an existing member configuration without asking a model.')
    opened.add_argument('--profile', required=True)
    opened.add_argument('--channel')
    opened.add_argument('--key', required=True)
    ask = commands.add_parser('ask', help='Explicitly enqueue one question using the selected channel routing.')
    ask.add_argument('--channel', required=True)
    ask.add_argument('--revision', required=True, type=_positive_revision)
    ask.add_argument('--question', required=True)
    ask.add_argument('--key', required=True)
    ask.add_argument('--mode', choices=('all', 'auto', 'collaborate'))
    ask.add_argument('--rounds', type=int, choices=(1, 2, 3))
    ask.add_argument('--playbook')
    for name in ('get', 'cancel', 'wait'):
        command = commands.add_parser(name, help={'get':'Read original discussion/run states.',
                                                  'cancel':'Request cancellation of original active runs.',
                                                  'wait':'Poll original runs; timeout never cancels or resends.'}[name])
        command.add_argument('--discussion', required=True)
        if name == 'wait':
            command.add_argument('--timeout', default=30.0, type=_timeout, metavar='SECONDS')
    advanced = commands.add_parser('advance', help='Explicitly resume paused collaboration after the original reply completes.')
    advanced.add_argument('--discussion', required=True)
    advanced.add_argument('--expected-updated', required=True, type=_finite_float)
    exported = commands.add_parser('export', help='Write one selected channel or preset as a new private Markdown file.')
    source = exported.add_mutually_exclusive_group(required=True)
    source.add_argument('--channel')
    source.add_argument('--preset', '--preset-id', dest='preset')
    exported.add_argument('--version', type=int, choices=(1, 2))
    exported.add_argument('--name', required=True)
    exported.add_argument('--output', required=True)
    for name in ('preview', 'import'):
        command = commands.add_parser(name, help='Read a local team package (maximum 64 KiB).')
        command.add_argument('--file', required=True)
        if name == 'import':
            command.add_argument('--expected-sha', required=True, help='sha256 returned by preview; not a raw file hash.')
            command.add_argument('--key', required=True)
    listed = commands.add_parser('trigger-list', help='Read saved local triggers; never dispatches.')
    listed.add_argument('--channel')
    for name in ('get', 'save', 'enable', 'pause', 'run', 'event'):
        command = commands.add_parser('trigger-' + name, help={
            'get': 'Read a saved trigger and its event receipts.',
            'save': 'Save a bounded JSON trigger definition paused; never enables or runs it.',
            'enable': 'Explicitly enable a trigger using its current revision.',
            'pause': 'Explicitly pause a trigger using its current revision.',
            'run': 'Explicitly dispatch an enabled trigger once; never waits or retries.',
            'event': 'Submit a bounded JSON object as event metadata; never waits or retries.'}[name])
        if name in ('save', 'event'):
            command.add_argument('--file', required=True)
        if name != 'save':
            command.add_argument('--trigger', required=True)
        if name != 'get':
            command.add_argument('--revision', required=name != 'save', type=_positive_revision)
        if name == 'run':
            command.add_argument('--key', required=True)
        if name == 'event':
            command.add_argument('--event-id', required=True)
    return parser


def _auth_required():
    # runtime.token() normally creates credentials on first use. A diagnostic or
    # read-only CLI invocation must instead report missing local setup.
    if runtime is None:
        raise _CLIError('assistant_cli_runtime_setup_required')
    try:
        if not stat.S_ISREG((runtime.STATE/'auth.token').stat().st_mode):
            raise _CLIError('assistant_cli_auth_required')
    except OSError:
        raise _CLIError('assistant_cli_auth_required') from None


def _request(suffix, arguments, *, timeout=None):
    _auth_required()
    value = runtime.request('commerce_assistant_team_' + suffix, arguments, client='local', timeout=timeout)
    if not isinstance(value, dict):
        raise _CLIError('assistant_cli_invalid_response')
    return value


def _fields(value, names):
    if not isinstance(value, dict):
        raise _CLIError('assistant_cli_invalid_response')
    return {key: value[key] for key in names if key in value}


def _rows(value, fields):
    if not isinstance(value, list):
        raise _CLIError('assistant_cli_invalid_response')
    return [_fields(row, fields) for row in value]


def _profile_rows(values):
    return _rows(values, ('id', 'name', 'role_id', 'model_ids', 'enabled', 'revision', 'sha256'))


def _channel_rows(values):
    return _rows(values, ('id', 'name', 'member_ids', 'revision', 'sha256'))


def _preset(value):
    result = _fields(value, ('id', 'name', 'created', 'source_format'))
    package = value.get('package')
    if package is not None:
        if not isinstance(package, dict):
            raise _CLIError('assistant_cli_invalid_response')
        result['counts'] = {key: len(_rows(package.get(key, []), ())) for key in
                            ('profiles', 'channels', 'playbooks', 'starter_notes', 'skills',
                             'connector_requirements', 'triggers')}
    return result


def _preset_rows(values):
    if not isinstance(values, list):
        raise _CLIError('assistant_cli_invalid_response')
    return [_preset(value) for value in values]


def _catalog(value):
    return {'profiles': _profile_rows(value.get('profiles', [])),
            'channels': _channel_rows(value.get('channels', [])),
            'roles': _rows(value.get('roles', []), ('id', 'name')),
            'models': _rows(value.get('models', []), ('id', 'label', 'selectable')),
            'discussions': _rows(value.get('discussions', []), ('id', 'status', 'created')),
            'presets': _preset_rows(value.get('presets', [])),
            'external_execution_allowed': False}


def _discussion(value):
    result = _fields(value, ('id', 'channel_id', 'question', 'status', 'created', 'completed', 'total',
                             'updated', 'mode', 'max_rounds', 'collaboration_state', 'final_answer'))
    result['members'] = _rows(value.get('members', []),
                              ('profile_id', 'name', 'thread_id', 'run_id', 'original_run_id', 'research_task_id',
                               'status', 'run_status', 'answer', 'questions', 'result_sha256', 'answer_sha256',
                               'index', 'round', 'kind'))
    if 'stopped_reason' in value:
        result['stopped_reason'] = _safe_error(value['stopped_reason'])
    if 'plan' in value:
        result['plan'] = _rows(value['plan'], ('index', 'round', 'profile_id', 'name', 'kind', 'status', 'thread_id', 'run_id'))
    if 'routing_decision' in value:
        result['routing_decision'] = _fields(value['routing_decision'],
            ('selected_member_ids', 'selected_member_names', 'lead_id', 'reason', 'matched_keywords'))
    if 'budget' in value:
        result['budget'] = _fields(value['budget'], ('max_member_requests', 'used_member_requests'))
    return result


def _safe_error(value):
    return value if value is None or isinstance(value, str) and value in SAFE_ERRORS else 'assistant_cli_request_failed'


def _trigger_event(value):
    result = _fields(value, ('id', 'trigger_id', 'trigger_revision', 'event_id', 'kind', 'created',
                             'status', 'discussion_id', 'payload_sha256'))
    if 'error' in value:
        result['error'] = _safe_error(value['error'])
    if value.get('discussion') is not None:
        result['discussion'] = _discussion(value['discussion'])
    return result


def _trigger(value):
    result = _fields(value, ('id', 'name', 'kind', 'channel_id', 'channel_revision', 'question',
                             'dispatch_mode', 'max_rounds', 'playbook_key', 'revision', 'enabled',
                             'created', 'activated_at', 'last_slot', 'last_checked_at', 'last_discussion_id', 'next_at'))
    if 'schedule' in value:
        result['schedule'] = _fields(value['schedule'],
            ('at', 'start_at', 'interval_seconds', 'weekday', 'time', 'timezone', 'discussion_id'))
    if 'error' in value:
        result['error'] = _safe_error(value['error'])
    history = value.get('history', [])
    if not isinstance(history, list):
        raise _CLIError('assistant_cli_invalid_response')
    result['history'] = [_trigger_event(event) for event in history]
    return result


def _trigger_rows(values):
    if not isinstance(values, list):
        raise _CLIError('assistant_cli_invalid_response')
    return [_trigger(value) for value in values]


def _is_timeout(error):
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return isinstance(error, urllib.error.URLError) and isinstance(error.reason, (TimeoutError, socket.timeout))


def _wait(discussion_id, seconds):
    deadline = time.monotonic() + seconds
    latest = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 4, {'outcome': 'timeout', 'discussion_id': discussion_id, 'discussion': latest}
        try:
            latest = _discussion(_request('discussion_get', {'discussion_id': discussion_id}, timeout=max(.001, remaining)))
        except (OSError, urllib.error.URLError) as error:
            if _is_timeout(error):
                return 4, {'outcome': 'timeout', 'discussion_id': discussion_id, 'discussion': latest}
            raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 4, {'outcome': 'timeout', 'discussion_id': discussion_id, 'discussion': latest}
        status = latest.get('status')
        if status not in ACTIVE:
            code = WAIT_CODES.get(status, 3)
            # Keep both the aggregate state and each original run's state. An
            # unfamiliar terminal word such as "settled" is never a success.
            return code, {'outcome': status, 'discussion_id': discussion_id, 'discussion': latest}
        time.sleep(min(.25, remaining))


def _read_package(path, limit=PACKAGE_BYTES):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise _CLIError('assistant_cli_package_not_regular')
        if info.st_size > limit:
            raise _CLIError('assistant_cli_package_too_large')
        with os.fdopen(descriptor, 'rb') as source:
            descriptor = None
            data = source.read(limit + 1)
        if len(data) > limit:
            raise _CLIError('assistant_cli_package_too_large')
        return data.decode('utf-8')
    except UnicodeError:
        raise _CLIError('assistant_cli_package_not_utf8') from None
    except OSError:
        raise _CLIError('assistant_cli_package_unreadable') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_json(path, limit=PACKAGE_BYTES):
    try:
        content = _read_package(path, limit)
    except _CLIError as error:
        raise _CLIError(error.code.replace('_package_', '_json_')) from None

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result

    def constant(value):
        raise ValueError()

    try:
        value = json.loads(content, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)
        if not isinstance(value, dict):
            raise ValueError()
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise ValueError()
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        return value
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise _CLIError('assistant_cli_invalid_json') from None


def _export(value, path):
    content, digest = value.get('content'), value.get('sha256')
    if (not isinstance(content, str) or not content.startswith('# ')
            or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
        raise _CLIError('assistant_cli_invalid_response')
    data = content.encode('utf-8')
    if len(data) > PACKAGE_BYTES:
        raise _CLIError('assistant_cli_package_too_large')
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        raise _CLIError('assistant_cli_output_exists') from None
    except OSError:
        raise _CLIError('assistant_cli_output_unwritable') from None
    created = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        try:
            current = os.lstat(path)
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino) and stat.S_ISREG(current.st_mode):
                os.unlink(path)
        except OSError:
            pass
        raise _CLIError('assistant_cli_output_write_failed') from None
    return {'status': 'exported', 'package_sha256': digest, 'byte_length': len(data), 'file_created': True}


def _execute(args):
    if args.command == 'doctor':
        _auth_required()
        health = runtime.health()
        catalog = _catalog(_request('catalog', {}))
        result = {'health': _fields(health, ('service', 'version', 'status')),
                  'counts': {'profiles': len(catalog['profiles']), 'channels': len(catalog['channels']),
                             'available_models': sum(model.get('selectable') is True for model in catalog['models'])}}
        return (0 if health.get('status') == 'ready' else 3), result
    if args.command == 'catalog':
        return 0, _catalog(_request('catalog', {}))
    if args.command == 'open':
        payload = {'profile_id': args.profile, 'idempotency_key': args.key}
        if args.channel is not None:
            payload['channel_id'] = args.channel
        value = _request('thread_open', payload)
        thread = _fields(value.get('thread'), ('id', 'revision', 'context_sha256', 'total_turns'))
        if value['thread'].get('latest_run') is not None:
            thread['latest_run'] = _fields(value['thread']['latest_run'], ('id', 'status', 'result_sha256'))
        return 0, {'thread': thread, 'route': _fields(value.get('route'), ('selected_model_id', 'reason'))}
    if args.command == 'ask':
        payload = {'channel_id': args.channel, 'expected_revision': args.revision,
                   'question': args.question, 'idempotency_key': args.key}
        for key, value in (('mode', args.mode), ('max_rounds', args.rounds), ('playbook_key', args.playbook)):
            if value is not None:
                payload[key] = value
        return 0, _discussion(_request('discussion_start', payload))
    if args.command in ('get', 'cancel'):
        return 0, _discussion(_request('discussion_' + args.command, {'discussion_id': args.discussion}))
    if args.command == 'wait':
        return _wait(args.discussion, args.timeout)
    if args.command == 'advance':
        return 0, _discussion(_request('discussion_advance', {
            'discussion_id': args.discussion, 'expected_updated': args.expected_updated}))
    if args.command == 'export':
        payload = {'name': args.name}
        payload['channel_id' if args.channel is not None else 'preset_id'] = args.channel if args.channel is not None else args.preset
        if args.version is not None:
            payload['version'] = args.version
        return 0, _export(_request('package_export', payload), args.output)
    if args.command in ('preview', 'import'):
        content = _read_package(args.file)
        if args.command == 'import' and not re.fullmatch('[a-f0-9]{64}', args.expected_sha):
            raise _CLIError('assistant_cli_invalid_arguments', 2)
        preview = _request('package_preview', {'content': content})
        if args.command == 'preview':
            return 0, _fields(preview, ('sha256', 'package', 'counts', 'warnings', 'source_format', 'execution_started'))
        if preview.get('sha256') != args.expected_sha:
            raise _CLIError('team_package_changed')
        value = _request('package_import', {'content': content, 'expected_sha256': args.expected_sha, 'idempotency_key': args.key})
        result = {**_fields(value, ('status', 'package_sha256', 'execution_started')),
                  'profiles': _profile_rows(value.get('profiles', [])), 'channels': _channel_rows(value.get('channels', []))}
        if 'preset' in value:
            result['preset'] = _preset(value['preset'])
        if 'triggers' in value:
            result['triggers'] = _trigger_rows(value['triggers'])
        return 0, result
    if args.command == 'trigger-list':
        payload = {'channel_id': args.channel} if args.channel is not None else {}
        return 0, {'triggers': _trigger_rows(_request('trigger_list', payload).get('triggers', []))}
    if args.command == 'trigger-get':
        return 0, _trigger(_request('trigger_get', {'trigger_id': args.trigger}))
    if args.command == 'trigger-save':
        payload = {'trigger': _read_json(args.file)}
        if args.revision is not None:
            payload['expected_revision'] = args.revision
        return 0, _trigger(_request('trigger_save', payload))
    if args.command in ('trigger-enable', 'trigger-pause'):
        return 0, _trigger(_request('trigger_enable', {'trigger_id': args.trigger,
            'expected_revision': args.revision, 'enabled': args.command == 'trigger-enable'}))
    if args.command in ('trigger-run', 'trigger-event'):
        payload = {'trigger_id': args.trigger, 'expected_revision': args.revision}
        if args.command == 'trigger-run':
            payload['idempotency_key'] = args.key
        else:
            payload.update(event_id=args.event_id, payload=_read_json(args.file, EVENT_BYTES))
        return 0, _trigger_event(_request(args.command.replace('-', '_'), payload))
    raise _CLIError('assistant_cli_invalid_arguments', 2)


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        code, result = _execute(args)
    except _CLIError as error:
        code, result = error.exit_code, {'error': error.code}
    except ValueError as error:
        name = str(error)
        code, result = 3, {'error': name if name in SAFE_ERRORS else 'assistant_cli_request_failed'}
    except urllib.error.HTTPError as error:
        code, result = 3, {'error': 'unauthorized' if error.code == 401 else 'assistant_cli_request_failed'}
        error.close()
    except (OSError, urllib.error.URLError):
        code, result = 3, {'error': 'assistant_cli_service_unavailable'}
    except KeyboardInterrupt:
        code, result = 130, {'error': 'assistant_cli_interrupted'}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
