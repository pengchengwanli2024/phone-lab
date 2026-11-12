"""Keep machine-specific Harness launch paths in private runtime storage."""
from pathlib import Path
import json


def prepare(root, destination, python):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    package = json.loads((root / 'harness/package.json').read_text())
    (destination / 'package.json').write_text(json.dumps(package, indent=2) + '\n')
    for name in ('client.js',):
        link = destination / name
        target = root / 'harness' / name
        if link.is_symlink():
            if link.resolve() != target:
                raise ValueError('different_local_bundle_link')
        elif link.exists():
            raise ValueError('existing_local_bundle_file')
        else:
            link.symlink_to(target)
    # Keep package resolution anchored in this private bundle. A symlinked main
    # may cause the host to resolve its patch against the shared template.
    entry = destination / 'index.js'
    if entry.is_symlink():
        if entry.resolve() != root / 'harness/index.js':
            raise ValueError('different_local_bundle_link')
        entry.unlink()
    entry.write_text('export {name, inject, apply} from ' + json.dumps((root / 'harness/index.js').as_uri()) + ';\n')
    patch = (root / 'harness/cordis.patch.yml').read_text()
    patch = patch.replace('"<PYTHON_EXECUTABLE>"', json.dumps(str(python)))
    patch = patch.replace('"<COMMERCE_MCP_SERVER_PATH>"', json.dumps(str(root / 'mcp_server.py')))
    target = destination / 'cordis.patch.yml'
    target.write_text(patch)
    target.chmod(0o600)
    return destination


def local_link_lock(lock_text, package, target):
    """Change only this linked import; never resolve unrelated installed packages."""
    lines = lock_text.splitlines(keepends=True)
    header = '    dependencies:\n'
    start = lines.index(header, lines.index('  .:\n')) + 1
    end = start
    while end < len(lines) and (lines[end].startswith('      ') or not lines[end].strip()):
        end += 1
    key = "      '" + package + "':\n"
    if key in lines[start:end]:
        at = lines.index(key, start, end)
        stop = at + 1
        while stop < end and lines[stop].startswith('        '):
            stop += 1
        del lines[at:stop]
        start = at
    value = 'link:' + str(target)
    block = key + '        specifier: ' + json.dumps(value) + '\n        version: ' + json.dumps(value) + '\n'
    lines.insert(start, block)
    return ''.join(lines)
