"""Build a runtime-only snapshot; never copy local databases or credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile


SKIP = {'qa', 'tests', 'node_modules', '__pycache__', 'integrations'}
SUFFIXES = {'.py', '.ps1', '.js', '.mjs', '.cjs', '.css', '.html', '.svg', '.wasm', '.woff', '.woff2'}
RESOURCES = {'commerce/requirements.txt', 'commerce/a2ui/requirements.txt',
             'commerce/web/intel-land.txt', 'commerce/engineering/features.json',
             'commerce/agents/roles.json', 'commerce/organization/org.json',
             'commerce/generative/catalog.json', 'commerce/sealeap/catalogue.json',
             'commerce/social_intel/schema.json', 'crawlers/sources.json'}
REQUIRED = {'commerce/server.py', 'commerce/runtime.py', 'commerce/requirements.txt',
            'commerce/web/workbench.bundle.js', 'commerce/web/workbench.bundle.css',
            'commerce/web/workbench.html', 'commerce/ui/tokens.json',
            'scripts/windows/smoke.py', 'scripts/windows/install_wsl.py'}


def selected(relative):
    name = relative.as_posix()
    if any(p.startswith('.') or p in SKIP for p in relative.parts):
        return False
    if relative.suffix in SUFFIXES:
        return True
    if name in RESOURCES:
        return True
    if relative.suffix == '.json' and name.startswith(('commerce/a2ui/', 'commerce/ui/', 'commerce/web/')):
        return True
    return relative.suffix in {'.md', '.txt'} and name.startswith(('commerce/organization/roles/', 'commerce/sealeap/'))


def build(root, output):
    root, output = Path(root).resolve(), Path(output).absolute()
    files = {}
    for prefix in ('commerce', 'crawlers', 'scripts/windows'):
        top = root / prefix
        if top.is_symlink():
            raise ValueError('source_symlink_rejected')
        if not top.exists():
            continue
        for folder, directories, names in os.walk(top, followlinks=False):
            for name in list(directories):
                child = Path(folder) / name
                if name.startswith('.') or name in SKIP:
                    directories.remove(name)
                elif child.is_symlink():
                    raise ValueError('source_symlink_rejected')
            for name in sorted(names):
                path = Path(folder) / name
                relative = path.relative_to(root)
                if not selected(relative):
                    continue
                if path.is_symlink() or not path.is_file():
                    raise ValueError('source_symlink_or_special_file_rejected')
                raw = path.read_bytes()
                files[relative.as_posix()] = (raw, path.stat().st_mode & 0o777)
    if not REQUIRED <= files.keys():
        raise ValueError('runtime_files_missing: ' + ', '.join(sorted(REQUIRED - files.keys())))
    manifest = {'format': 'phone-lab-wsl-v1', 'files': {
        name: {'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'mode': mode}
        for name, (raw, mode) in sorted(files.items())}}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves any previously prepared delivery artifact.
    with output.open('xb') as handle:
        try:
            with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, (raw, mode) in sorted(files.items()):
                    info = zipfile.ZipInfo('phone-lab/' + name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = (stat.S_IFREG | mode) << 16
                    archive.writestr(info, raw)
                archive.writestr('bundle.json', json.dumps(manifest, sort_keys=True, ensure_ascii=False))
            for name, (raw, _) in files.items():
                if (root / name).read_bytes() != raw:
                    raise ValueError('source_changed_during_bundle')
        except BaseException:
            handle.close()
            output.unlink(missing_ok=True)
            raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (args.root / 'commerce/workbench/package.json').exists():
        subprocess.run([sys.executable, str(args.root / 'commerce/ui/build.py'), '--check'], check=True)
    manifest = build(args.root, args.output)
    print(json.dumps({'status': 'bundled', 'files': len(manifest['files']),
                      'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'private_state_included': False}))


if __name__ == '__main__':
    main()
