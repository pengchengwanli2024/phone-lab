"""Bounded MCP metadata discovery from an existing, exact registry definition.

Discovery never calls a tool, changes a registry entry, or grants execution.
The fixed worker shares the extension transport's network policy and keeps
DNS/socket lifetime bounded without accepting executable server commands.
"""
import inspect
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from extension_runtime import transport
from extension_runtime.validation import encoded, endpoint, redact, schema_check, sha

PROBE_TIMEOUT_SECONDS = 20
MAX_PAGES = 8
MAX_TOOLS = 200
MAX_CATALOG_BYTES = 128000
TOOL_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,128}$')
SCHEMA_TYPES = {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}


def definitions(schema, string):
    return [('commerce_extension_tools_discover',
             '对当前已登记 MCP-HTTP 扩展做有界握手和工具目录发现；不调用、测试、启用或授权工具。',
             schema({'extension_id': string, 'expected_definition_sha256': {
                 'type': 'string', 'pattern': '^[a-f0-9]{64}$'}},
                    ['extension_id', 'expected_definition_sha256']))]


def _text(value, maximum, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or not empty and not value.strip()
            or any(ord(char) < 32 and char not in '\n\t' for char in value)):
        raise ValueError('tool_discovery_invalid_metadata')
    return value


def _schema(value, depth=0, root=False):
    """Check bounded JSON Schema structure without fetching refs or compiling it.

    Advanced keywords remain inert metadata; the separate extension subset
    flag says whether the existing registry can accept the schema unchanged.
    """
    if depth > 12:
        raise ValueError('tool_discovery_invalid_schema')
    if type(value) is bool and not root:
        return
    if not isinstance(value, dict) or root and value.get('type') != 'object':
        raise ValueError('tool_discovery_invalid_schema')
    typ = value.get('type')
    types = typ if isinstance(typ, list) else [typ] if typ is not None else []
    if len(types) > 7 or any(not isinstance(item, str) or item not in SCHEMA_TYPES for item in types):
        raise ValueError('tool_discovery_invalid_schema')
    for key in ('properties', '$defs', 'definitions', 'patternProperties'):
        if key in value:
            mapping = value[key]
            if not isinstance(mapping, dict) or len(mapping) > 64:
                raise ValueError('tool_discovery_invalid_schema')
            for name, child in mapping.items():
                _text(name, 160)
                _schema(child, depth + 1)
    if 'required' in value:
        names = value['required']
        if (not isinstance(names, list) or len(names) > 64 or
                any(not isinstance(name, str) for name in names) or len(set(names)) != len(names)):
            raise ValueError('tool_discovery_invalid_schema')
        for name in names:
            _text(name, 160)
    for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
        if key in value:
            children = value[key]
            if not isinstance(children, list) or not 1 <= len(children) <= 32:
                raise ValueError('tool_discovery_invalid_schema')
            for child in children:
                _schema(child, depth + 1)
    for key in ('items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains', 'propertyNames'):
        if key in value:
            _schema(value[key], depth + 1)
    for key in ('minLength', 'maxLength', 'minItems', 'maxItems', 'minProperties', 'maxProperties'):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] <= 128000):
            raise ValueError('tool_discovery_invalid_schema')
    for key in ('minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'):
        if key in value and (type(value[key]) not in (int, float) or not math.isfinite(value[key])):
            raise ValueError('tool_discovery_invalid_schema')
    if 'enum' in value and (not isinstance(value['enum'], list) or not 1 <= len(value['enum']) <= 100):
        raise ValueError('tool_discovery_invalid_schema')
    if '$ref' in value and (not isinstance(value['$ref'], str) or not value['$ref'].startswith('#')):
        raise ValueError('tool_discovery_external_schema_reference')


def _clean(value, secrets, depth=0):
    if depth > 24:
        raise ValueError('tool_discovery_invalid_metadata')
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            cleaned = _clean(key, secrets, depth + 1)
            if cleaned in result:
                raise ValueError('tool_discovery_invalid_metadata')
            result[cleaned] = _clean(child, secrets, depth + 1)
        return result
    if isinstance(value, list):
        return [_clean(item, secrets, depth + 1) for item in value]
    return redact(value, secrets) if isinstance(value, str) else value


def _tool(value, secrets):
    if not isinstance(value, dict) or not TOOL_NAME.fullmatch(str(value.get('name', ''))):
        raise ValueError('tool_discovery_invalid_tool_name')
    encoded(value, 64000)
    name = value['name']
    if not isinstance(name, str):
        raise ValueError('tool_discovery_invalid_tool_name')
    description = _text(value.get('description', ''), 6000, empty=True)
    schema = value.get('inputSchema')
    _schema(schema, root=True)
    annotations = value.get('annotations', {})
    if not isinstance(annotations, dict):
        raise ValueError('tool_discovery_invalid_annotations')
    projected = {}
    for key in ('readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint'):
        if key in annotations:
            if type(annotations[key]) is not bool:
                raise ValueError('tool_discovery_invalid_annotations')
            projected[key] = annotations[key]
    if 'title' in annotations:
        projected['title'] = _text(annotations['title'], 200)
    result = _clean({'name': name, 'description': description, 'inputSchema': schema,
                     'annotations': projected}, secrets)
    if result['name'] != name:
        raise ValueError('tool_discovery_invalid_tool_name')
    try:
        schema_check(result['inputSchema'])
        supported = True
    except ValueError:
        supported = False
    result['extension_schema_supported'] = supported
    return result


def _rpc(value, ident):
    if (not isinstance(value, dict) or value.get('jsonrpc') != '2.0'
            or type(value.get('id')) is not int or value['id'] != ident
            or 'error' in value or not isinstance(value.get('result'), dict)):
        raise ValueError('tool_discovery_invalid_rpc')
    return value['result']


def _probe(packet):
    address = endpoint(packet['endpoint'])
    headers = packet['headers']
    if (not isinstance(headers, dict) or set(headers) - {'Authorization', 'X-Api-Key'}
            or any(not isinstance(value, str) or len(value) > 9000
                   or any(ord(char) < 32 for char in value) for value in headers.values())):
        raise ValueError('tool_discovery_invalid_credentials')
    headers = dict(headers)
    secrets = list(headers.values())
    secrets.extend(value.split(' ', 1)[1] for value in headers.values()
                   if value.startswith(('Bearer ', 'Basic ')))
    end = time.monotonic() + PROBE_TIMEOUT_SECONDS

    def request(payload, notification=False):
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise ValueError('tool_discovery_timeout')
        return transport.request(address, 'POST', payload, headers,
                                 timeout=min(8, remaining), notification=notification)

    initial, response_headers = request({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                   'clientInfo': {'name': 'commerce-tool-discovery', 'version': '1'}}})
    result = _rpc(initial, 1)
    protocol = result.get('protocolVersion')
    if not isinstance(protocol, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', protocol):
        raise ValueError('tool_discovery_invalid_protocol')
    capabilities = result.get('capabilities', {})
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get('tools'), dict):
        raise ValueError('tool_discovery_tools_unavailable')
    headers['MCP-Protocol-Version'] = protocol
    session = next((value for key, value in response_headers.items()
                    if key.lower() == 'mcp-session-id'), None)
    if session is not None:
        if not isinstance(session, str) or not 1 <= len(session) <= 200 or any(
                ord(char) < 33 or ord(char) > 126 for char in session):
            raise ValueError('tool_discovery_invalid_session')
        headers['Mcp-Session-Id'] = session
        secrets.append(session)
    request({'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {}}, notification=True)
    tools = []
    names = set()
    cursors = set()
    cursor = None
    for page in range(1, MAX_PAGES + 1):
        ident = page + 1
        value, _ = request({'jsonrpc': '2.0', 'id': ident, 'method': 'tools/list',
                            'params': {'cursor': cursor} if cursor is not None else {}})
        result = _rpc(value, ident)
        rows = result.get('tools')
        if not isinstance(rows, list) or len(tools) + len(rows) > MAX_TOOLS:
            raise ValueError('tool_discovery_catalog_limit')
        for row in rows:
            tool = _tool(row, secrets)
            if tool['name'] in names:
                raise ValueError('tool_discovery_duplicate_tool')
            names.add(tool['name'])
            tools.append(tool)
        encoded(tools, MAX_CATALOG_BYTES)
        cursor = result.get('nextCursor')
        if cursor is None:
            return {'tools': sorted(tools, key=lambda row: row['name']), 'pages': page,
                    'protocol_version': protocol}
        if (not isinstance(cursor, str) or not 1 <= len(cursor) <= 512
                or any(ord(char) < 32 for char in cursor) or cursor in cursors):
            raise ValueError('tool_discovery_invalid_cursor')
        cursors.add(cursor)
    raise ValueError('tool_discovery_page_limit')


def _worker(packet):
    environment = {key: value for key, value in os.environ.items() if key in
                   {'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}}
    process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--worker'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
    try:
        output, _ = process.communicate(encoded(packet, 16000), timeout=PROBE_TIMEOUT_SECONDS)
        if process.returncode or len(output.encode()) > MAX_CATALOG_BYTES + 2000:
            raise ValueError('tool_discovery_probe_failed')
        value = json.loads(output)
        if not isinstance(value, dict) or not isinstance(value.get('result'), dict):
            raise ValueError('tool_discovery_probe_failed')
        return value['result']
    except subprocess.TimeoutExpired:
        raise ValueError('tool_discovery_timeout') from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('tool_discovery_probe_failed') from None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


class ToolDiscovery:
    def __init__(self, service):
        self.service = service
        self._slots = threading.BoundedSemaphore(2)

    def _snapshot(self, extension_id):
        try:
            with self.service.core.db() as db:
                entry = self.service.extensions._entry(db, extension_id)
                headers = self.service.extensions._secret_headers(extension_id, entry['version'])
            return entry, headers
        except ValueError:
            raise ValueError('tool_discovery_registration_unavailable') from None

    def discover(self, extension_id, expected_definition_sha256):
        if (not isinstance(extension_id, str) or not re.fullmatch(r'ext_[a-f0-9]{20}', extension_id)
                or not isinstance(expected_definition_sha256, str)
                or not re.fullmatch(r'[a-f0-9]{64}', expected_definition_sha256)):
            raise ValueError('tool_discovery_invalid_arguments')
        entry, headers = self._snapshot(extension_id)
        definition_hash = sha(entry['definition'])
        if definition_hash != expected_definition_sha256:
            raise ValueError('tool_discovery_definition_changed')
        if (entry['kind'] != 'plugin'
                or entry['definition']['spec'].get('transport') != 'mcp_http'):
            raise ValueError('tool_discovery_registered_mcp_required')
        credential_hash = sha(headers)
        if not self._slots.acquire(blocking=False):
            raise ValueError('tool_discovery_busy')
        try:
            result = _worker({'endpoint': entry['definition']['spec']['endpoint'], 'headers': headers})
            current, current_headers = self._snapshot(extension_id)
            if (current['version'] != entry['version'] or sha(current['definition']) != definition_hash
                    or sha(current_headers) != credential_hash):
                raise ValueError('tool_discovery_definition_changed')
            return {**result, 'extension_id': extension_id, 'version': current['version'],
                    'definition_sha256': definition_hash,
                    'catalog_sha256': sha({'definition_sha256': definition_hash, 'tools': result['tools']}),
                    'test_status': current['test_status'], 'extension_enabled': current['enabled'],
                    'verification': 'mcp_handshake_and_tools_list_only',
                    'tools_called': False, 'tools_tested': False, 'activation_changed': False,
                    'instructions_are_untrusted_data': True, 'annotations_are_authorization': False,
                    'external_execution_allowed': False,
                    'limits': {'pages': MAX_PAGES, 'tools': MAX_TOOLS,
                               'catalog_bytes': MAX_CATALOG_BYTES, 'seconds': PROBE_TIMEOUT_SECONDS}}
        finally:
            self._slots.release()

    def invoke(self, name, args):
        if name != 'commerce_extension_tools_discover':
            raise ValueError('tool_discovery_unknown_tool')
        if not isinstance(args, dict):
            raise ValueError('tool_discovery_invalid_arguments')
        try:
            inspect.signature(self.discover).bind(**args)
        except TypeError:
            raise ValueError('tool_discovery_invalid_arguments') from None
        return self.discover(**args)


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        raise SystemExit(2)
    try:
        raw = sys.stdin.read(16001)
        if len(raw.encode()) > 16000:
            raise ValueError()
        packet = json.loads(raw)
        if not isinstance(packet, dict) or set(packet) != {'endpoint', 'headers'}:
            raise ValueError()
        sys.stdout.write(encoded({'result': _probe(packet)}, MAX_CATALOG_BYTES + 2000))
    except Exception:
        # Remote bodies, headers, provider errors and keys never leave the worker.
        sys.stdout.write('{"error":"tool_discovery_probe_failed"}')
        raise SystemExit(1)
