"""Prepare/start the official pinned Firecrawl source in private local state."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

from setup import ROOT, STATE, environment

RELEASE = 'v2.11.162'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'start', 'stop', 'status'))
    parser.add_argument('--source-build', action='store_true', help='Build the pinned source instead of official image digests')
    parser.add_argument('--public-proxy', action='store_true', help='Route external sandbox requests through the existing host proxy')
    args = parser.parse_args()
    (STATE / 'logs').mkdir(parents=True, exist_ok=True)
    source = STATE / 'firecrawl'
    env = environment()
    log_path = STATE / 'logs' / 'firecrawl-deployment.log'
    with log_path.open('a') as log:
        if not source.exists():
            result = subprocess.run(['git', 'clone', '--depth', '1', '--branch', RELEASE,
                                     'https://github.com/firecrawl/firecrawl.git', str(source)],
                                    cwd=ROOT, env=env, stdout=log, stderr=log)
            if result.returncode:
                print('{"status":"blocked","reason":"source_download_failed"}')
                return 1
        # Do not overwrite an existing private database password.
        private_env = source / '.env'
        if not private_env.exists():
            private_env.write_text('USE_DB_AUTHENTICATION=false\nPOSTGRES_USER=postgres\n'
                                   'POSTGRES_DB=postgres\nPOSTGRES_PASSWORD=' + secrets.token_hex(32) + '\n')
            private_env.chmod(0o600)
        import yaml
        config = yaml.safe_load((source / 'docker-compose.yaml').read_text())
        # Keep the PostgreSQL backend; FoundationDB is optional in this release.
        config['services'].pop('foundationdb', None)
        config['services'].pop('foundationdb-init', None)
        config['services']['api']['ports'] = ['127.0.0.1:13002:3002']
        config['services']['api']['volumes'] = []
        config['services']['api']['environment']['HARNESS_STARTUP_TIMEOUT_MS'] = '120000'
        config['services']['api']['environment']['CRAWL_CONCURRENT_REQUESTS'] = '2'
        config['services']['api']['environment']['NUM_WORKERS_PER_QUEUE'] = '1'
        config['services']['api']['environment']['ALLOW_LOCAL_WEBHOOKS'] = 'true'
        config['services']['playwright-service']['environment']['ALLOW_LOCAL_WEBHOOKS'] = 'true'
        # The official image's pnpm entrypoint lazily downloads its package manager.
        # Execute the already-built server directly, using its package.json start script.
        config['services']['playwright-service']['command'] = ['node', 'dist/api.js']
        config['services']['fixture'] = {
            'image': 'python:3.12-slim', 'working_dir': '/fixture',
            'volumes': [str(ROOT / 'crawlers/fixture.py') + ':/fixture/fixture.py:ro'],
            'command': ['python', '-c', 'from http.server import ThreadingHTTPServer; '
                        'from fixture import Handler; '
                        'ThreadingHTTPServer(("0.0.0.0",8877),Handler).serve_forever()'],
            'networks': {'backend': {'aliases': ['fixture.test']}},
            'read_only': True, 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'],
        }
        # Local host proxy addresses need Docker's host gateway during image builds.
        build_proxy = {}
        for key in ('HTTP_PROXY', 'HTTPS_PROXY'):
            value = env.get(key)
            if value:
                parsed = urlsplit(value)
                if parsed.hostname in ('127.0.0.1', 'localhost') and not parsed.username:
                    value = urlunsplit((parsed.scheme, f'host.docker.internal:{parsed.port}',
                                       parsed.path, '', ''))
                build_proxy[key] = value
        if args.public_proxy:
            proxy = build_proxy.get('HTTPS_PROXY')
            if not proxy:
                print('{"status":"blocked","reason":"existing_proxy_not_configured"}')
                return 1
            config['services']['api']['environment']['PROXY_SERVER'] = proxy
            config['services']['playwright-service']['environment']['PROXY_SERVER'] = proxy
        for service in config['services'].values():
            if isinstance(service.get('build'), str):
                service['build'] = {'context': service['build'], 'args': build_proxy}
        if not args.source_build:
            images = json.loads((ROOT / 'crawlers/firecrawl-images.json').read_text())
            for name, image in images.items():
                config['services'][name].pop('build', None)
                config['services'][name]['image'] = image
        compose = source / 'compose.lab.yaml'
        compose.write_text(yaml.safe_dump(config, sort_keys=False))
        compose.chmod(0o600)
        if args.action == 'prepare':
            print(json.dumps({'status': 'prepared', 'release': RELEASE, 'bind': 'loopback_only'}))
            return 0
        docker = subprocess.run(['docker', 'info'], stdout=log, stderr=log, timeout=15)
        if docker.returncode:
            print('{"status":"blocked","reason":"docker_daemon_unavailable"}')
            return 1
        command = ['docker', 'compose', '-p', 'phone-lab-firecrawl', '-f', str(compose)]
        if args.action == 'start':
            command += ['up', '--build', '-d']
        elif args.action == 'stop':
            command += ['down']
        else:
            command += ['ps', '--all']
        result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=log)
        print(json.dumps({'status': 'command_completed' if result.returncode == 0 else 'blocked',
                          'action': args.action, 'exit_code': result.returncode,
                          'note': 'A successful start still requires a functional scrape test.'}))
        return result.returncode


if __name__ == '__main__':
    sys.exit(main())
