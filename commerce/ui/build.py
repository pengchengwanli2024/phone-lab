"""Bundle UI primitives/tokens into the existing shared resources; --check is read-only."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START, END = '/* COMMERCE_UI_TOKENS_START */', '/* COMMERCE_UI_TOKENS_END */'


def generated():
    source = json.loads((ROOT / 'ui/tokens.json').read_text())
    rules = '\n'.join('  --ui-' + name + ': ' + value + ';' for name, value in source['tokens'].items())
    dark = '\n'.join('  --ui-' + name + ': ' + value + ';' for name, value in source['dark'].items())
    return (START + '\n:root {\n' + rules + '\n  color-scheme: light;\n}\n'
            + ':root[data-theme="dark"] {\n' + dark + '\n  color-scheme: dark;\n}\n'
            + '@media (prefers-color-scheme: dark) {\n:root:not([data-theme]), :root[data-theme="system"] {\n'
            + dark + '\n  color-scheme: dark;\n}\n}\n' + END)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'web/style.css'
    content = path.read_text()
    block = generated()
    if START in content:
        before, tail = content.split(START, 1)
        _, after = tail.split(END, 1)
        expected = before + block + after
    else:
        expected = block + '\n' + content
    css_start, css_end = '/* COMMERCE_UI_PRIMITIVES_START */', '/* COMMERCE_UI_PRIMITIVES_END */'
    primitives = css_start + '\n' + (ROOT / 'ui/primitives.css').read_text().rstrip() + '\n' + css_end
    if css_start in expected:
        before, tail = expected.split(css_start, 1)
        _, after = tail.split(css_end, 1)
        expected = before + primitives + after
    else:
        expected += '\n' + primitives + '\n'
    js_path = ROOT / 'web/app.js'
    javascript = js_path.read_text()
    start, end = '/* COMMERCE_UI_KIT_START */', '/* COMMERCE_UI_KIT_END */'
    kit = start + '\n' + (ROOT / 'ui/kit.js').read_text().rstrip() + '\n' + end
    version = json.loads((ROOT / 'ui/tokens.json').read_text())['version']
    if "version:'" + version + "'" not in kit:
        raise SystemExit('UI component and token versions differ.')
    if start in javascript:
        before, tail = javascript.split(start, 1)
        _, after = tail.split(end, 1)
        js_expected = before + kit + after
    else:
        js_expected = kit + '\n' + javascript
    intel_start, intel_end = '/* COMMERCE_INTEL_START */', '/* COMMERCE_INTEL_END */'
    intel = (ROOT / 'web/intel-ui.js').read_text().replace('__INTEL_WORLD_PATH__', (ROOT / 'web/intel-land.txt').read_text())
    if intel_start not in js_expected or intel_end not in js_expected:
        raise SystemExit('Shared information module markers missing; preserve existing business modules.')
    before, tail = js_expected.split(intel_start, 1)
    _, after = tail.split(intel_end, 1)
    js_expected = before + intel_start + '\n' + intel.rstrip() + '\n' + intel_end + after
    intel_css_start, intel_css_end = '/* COMMERCE_INTEL_STYLE_START */', '/* COMMERCE_INTEL_STYLE_END */'
    intel_css = intel_css_start + '\n' + (ROOT / 'web/intel-ui.css').read_text().rstrip() + '\n' + intel_css_end
    if intel_css_start in expected:
        before, tail = expected.split(intel_css_start, 1)
        _, after = tail.split(intel_css_end, 1)
        expected = before + intel_css + after
    else:
        expected += '\n' + intel_css + '\n'
    if args.check:
        if expected != content or js_expected != javascript:
            raise SystemExit('UI kit/tokens are stale; run python3 commerce/ui/build.py')
        print('Shared UI kit and tokens match versioned sources.')
    else:
        if path.read_text() != content or js_path.read_text() != javascript:
            raise SystemExit('Concurrent UI edit detected; retry against current files.')
        path.write_text(expected)
        js_path.write_text(js_expected)
        print('Shared UI kit and tokens bundled into existing web resources.')


if __name__ == '__main__':
    main()
