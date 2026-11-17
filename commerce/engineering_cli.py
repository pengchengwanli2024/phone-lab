"""Authenticated local entry to the project-owned engineering team."""
import argparse
import json
from pathlib import Path
import sys

from runtime import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'recall', 'retrospect', 'enable', 'disable'): commands.add_parser(name)
    commands.add_parser('features').add_argument('query', nargs='?', default='')
    commands.add_parser('feature').add_argument('feature_id')
    prepare = commands.add_parser('prepare', help='Print a pinned work order without submitting it')
    prepare.add_argument('feature_id');prepare.add_argument('--goal', required=True)
    prepare.add_argument('--key', required=True);prepare.add_argument('--kind', choices=('bugfix', 'feature'), default='bugfix')
    submit = commands.add_parser('submit');submit.add_argument('file', help='Explicit JSON engineering work order, or - for stdin')
    for name in ('get', 'artifact', 'cancel', 'resume'):
        commands.add_parser(name).add_argument('run_id')
    args = parser.parse_args();data = {}
    command = args.command
    if command in ('enable', 'disable'): data = {'enabled': command == 'enable'};command = 'configure'
    elif command == 'features': data = {'query': args.query};command = 'feature_list'
    elif command == 'feature': data = {'feature_id': args.feature_id};command = 'feature_get'
    elif command == 'prepare':
        data = {'feature_id': args.feature_id, 'goal': args.goal, 'idempotency_key': args.key, 'kind': args.kind}
    elif command == 'submit':
        if args.file == '-':
            raw = sys.stdin.read(12001)
        else:
            with Path(args.file).open(encoding='utf-8') as stream:
                raw = stream.read(12001)
        if len(raw) > 12000: parser.error('Work order exceeds 12000 characters')
        data = json.loads(raw);command = 'create'
        if not isinstance(data, dict): parser.error('Work order must be a JSON object')
    elif hasattr(args, 'run_id'): data = {'run_id': args.run_id}
    result = request('commerce_engineering_' + command, data, 'codex')
    if command == 'prepare': result = result['work_order']
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
