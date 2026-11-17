"""Verify and install an isolated Linux/WSL release without moving business state."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile


LIMIT = 512 * 1024 * 1024


def unpack(bundle, destination):
    destination = Path(destination).expanduser().absolute()
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        names = [i.filename for i in entries]
        if len(names) != len(set(names)) or sum(i.file_size for i in entries) > LIMIT:
            raise ValueError('archive_duplicate_or_size_limit')
        for entry in entries:
            p = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if (p.is_absolute() or '..' in p.parts or '\\' in entry.filename or ':' in entry.filename
                    or entry.is_dir() or stat.S_ISLNK(mode) or entry.file_size > 64 * 1024 * 1024):
                raise ValueError('unsafe_archive_path_or_type')
        manifest_raw = archive.read('bundle.json')
        manifest = json.loads(manifest_raw)
        if manifest.get('format') != 'phone-lab-wsl-v1' or not isinstance(manifest.get('files'), dict) or not manifest['files']:
            raise ValueError('invalid_bundle_manifest')
        if set(names) != {'bundle.json', *('phone-lab/' + name for name in manifest['files'])}:
            raise ValueError('archive_unmanifested_file')
        contents = {}
        for name, expected in manifest['files'].items():
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] not in ('commerce', 'crawlers', 'scripts')):
                raise ValueError('unsafe_manifest_path')
            raw = archive.read('phone-lab/' + name)
            if len(raw) != expected['size'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                raise ValueError('bundle_hash_mismatch')
            contents[name] = raw
    # Verify the entire archive before making destination directories.
    release = destination / 'releases' / hashlib.sha256(manifest_raw).hexdigest()[:24]
    for ancestor in (destination, *destination.parents):
        if ancestor.is_symlink():
            raise ValueError('destination_symlink_rejected')
    if release.parent.is_symlink() or release.is_symlink():
        raise ValueError('destination_symlink_rejected')
    if release.exists():
        for name, raw in contents.items():
            path = release / name
            if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.read_bytes() != raw:
                raise ValueError('existing_release_modified')
        return release
    release.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=release.parent))
    try:
        for name, raw in contents.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o700 if manifest['files'][name]['mode'] & 0o111 else 0o600)
        (stage / 'bundle.json').write_bytes(manifest_raw)
        if release.exists():
            raise ValueError('release_already_created')
        stage.rename(release)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return release


def run(command, *, env=None):
    subprocess.run([str(x) for x in command], env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--destination', type=Path, default=Path.home() / 'phone-lab-windows')
    parser.add_argument('--port', type=int, default=38731)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux' or sys.version_info < (3, 12):
        raise SystemExit('Requires Linux/WSL with Python 3.12 or newer')
    if not 1024 <= args.port <= 65535:
        raise SystemExit('Invalid local port')
    release = unpack(args.bundle, args.destination)
    if args.prepare_only:
        print(json.dumps({'status': 'prepared', 'release': str(release), 'service_started': False}))
        return
    for program in ('ffmpeg', 'ffprobe'):
        if not shutil.which(program):
            raise SystemExit('Missing ' + program + '; install the documented system prerequisites')
    venv = release / '.venv'
    if not (venv / 'bin/python').exists():
        run([sys.executable, '-m', 'venv', venv])
    python = venv / 'bin/python'
    run([python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', release / 'commerce/requirements.txt'])
    run([python, release / 'scripts/windows/smoke.py', '--root', release])
    destination = args.destination.expanduser().absolute()
    config = {'release': str(release), 'state': str(destination / 'state'), 'port': args.port}
    current = destination / 'current.json'
    if current.exists() and json.loads(current.read_text()) != config:
        raise SystemExit('Existing installation differs; new release staged, activation requires an explicit upgrade')
    if args.activate:
        env = os.environ.copy()
        # Store/model credentials are deliberately configured on this installation.
        for name in list(env):
            if name.startswith(('COMMERCE_', 'OPENAI_', 'ANTHROPIC_', 'OZON_')):
                env.pop(name)
        env.update(COMMERCE_STATE=config['state'], COMMERCE_PORT=str(args.port))
        run([python, release / 'commerce/manage.py', 'start'], env=env)
        current.write_text(json.dumps(config, indent=2))
        current.chmod(0o600)
    print(json.dumps({'status': 'started' if args.activate else 'installed_tested',
                      'origin': 'http://127.0.0.1:' + str(args.port),
                      'service_started': args.activate, 'boot_start_configured': False,
                      'business_state_migrated': False}))


if __name__ == '__main__':
    main()
