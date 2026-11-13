"""Bundle UI primitives/tokens into the existing shared resources; --check is read-only."""
import argparse
import json
import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START, END = '/* COMMERCE_UI_TOKENS_START */', '/* COMMERCE_UI_TOKENS_END */'


def generated():
    source = json.loads((ROOT / 'ui/tokens.json').read_text())
    rules = '\n'.join('  --ui-' + name + ': ' + value + ';' for name, value in source['tokens'].items())
    dark = '\n'.join('  --ui-' + name + ': ' + value + ';' for name, value in source['dark'].items())
    base = (START + '\n:root {\n' + rules + '\n  color-scheme: light;\n}\n'
            + ':root[data-theme="dark"] {\n' + dark + '\n  color-scheme: dark;\n}\n'
            + '@media (prefers-color-scheme: dark) {\n:root:not([data-theme]), :root[data-theme="system"] {\n'
            + dark + '\n  color-scheme: dark;\n}\n}\n')
    for name, appearance in source.get('appearances', {}).items():
        selector = '[data-ui-appearance=\"'+name+'\"]'
        light = '\n'.join('  --ui-'+key+': '+value+';' for key,value in appearance['tokens'].items())
        dark_profile = '\n'.join('  --ui-'+key+': '+value+';' for key,value in appearance['dark'].items())
        base += selector+' {\n'+light+'\n}\n'
        base += ':root[data-theme=\"dark\"]'+selector+', :root[data-theme=\"dark\"] '+selector+' {\n'+dark_profile+'\n}\n'
        base += '@media (prefers-color-scheme: dark) {\n:root[data-theme=\"system\"]'+selector+', :root:not([data-theme])'+selector+' {\n'+dark_profile+'\n}\n}\n'
    return base + END


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
    kit = start + '\n' + (ROOT / 'ui/status.js').read_text().rstrip() + '\n' + (ROOT / 'ui/kit.js').read_text().rstrip() + '\n' + end
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
    intel = (ROOT / 'web/social-ui.js').read_text() + '\n' + (ROOT / 'web/intel-ui.js').read_text().replace('__INTEL_WORLD_PATH__', (ROOT / 'web/intel-land.txt').read_text())
    if intel_start not in js_expected or intel_end not in js_expected:
        raise SystemExit('Shared information module markers missing; preserve existing business modules.')
    before, tail = js_expected.split(intel_start, 1)
    _, after = tail.split(intel_end, 1)
    js_expected = before + intel_start + '\n' + intel.rstrip() + '\n' + intel_end + after
    intel_css_start, intel_css_end = '/* COMMERCE_INTEL_STYLE_START */', '/* COMMERCE_INTEL_STYLE_END */'
    intel_css = intel_css_start + '\n' + (ROOT / 'web/social-ui.css').read_text().rstrip() + '\n' + (ROOT / 'web/intel-ui.css').read_text().rstrip() + '\n' + intel_css_end
    if intel_css_start in expected:
        before, tail = expected.split(intel_css_start, 1)
        _, after = tail.split(intel_css_end, 1)
        expected = before + intel_css + after
    else:
        expected += '\n' + intel_css + '\n'
    agent_start, agent_end = '/* COMMERCE_AGENT_START */', '/* COMMERCE_AGENT_END */'
    agent_block = agent_start + '\n' + (ROOT / 'web/agent-ui.js').read_text().rstrip() + '\n' + agent_end
    if agent_start in js_expected:
        before, tail = js_expected.split(agent_start, 1)
        _, after = tail.split(agent_end, 1)
        js_expected = before + agent_block + after
    else:
        js_expected = js_expected.replace(intel_end, intel_end + '\n' + agent_block, 1)
    css_start, css_end = '/* COMMERCE_AGENT_STYLE_START */', '/* COMMERCE_AGENT_STYLE_END */'
    agent_css = css_start + '\n' + (ROOT / 'web/agent-ui.css').read_text().rstrip() + '\n' + css_end
    if css_start in expected:
        before, tail = expected.split(css_start, 1)
        _, after = tail.split(css_end, 1)
        expected = before + agent_css + after
    else:
        expected += '\n' + agent_css + '\n'
    exposure_start, exposure_end = '/* COMMERCE_EXPOSURE_START */', '/* COMMERCE_EXPOSURE_END */'
    exposure_js = exposure_start + '\n' + (ROOT / 'web/exposure-ui.js').read_text().rstrip() + '\n' + exposure_end
    if exposure_start in js_expected:
        before, tail = js_expected.split(exposure_start, 1)
        _, after = tail.split(exposure_end, 1)
        js_expected = before + exposure_js + after
    else:
        js_expected = js_expected.replace(agent_end, agent_end + '\n' + exposure_js, 1)
    exposure_start, exposure_end = '/* COMMERCE_EXPOSURE_STYLE_START */', '/* COMMERCE_EXPOSURE_STYLE_END */'
    exposure_css = exposure_start + '\n' + (ROOT / 'web/exposure-ui.css').read_text().rstrip() + '\n' + exposure_end
    if exposure_start in expected:
        before, tail = expected.split(exposure_start, 1)
        _, after = tail.split(exposure_end, 1)
        expected = before + exposure_css + after
    else:
        expected += '\n' + exposure_css + '\n'
    # Migrate the old copied organization block to the same single-source build.
    legacy_begin, legacy_end = '/* BEGIN GENERATED ORGANIZATION MODULE */', '/* END GENERATED ORGANIZATION MODULE */'
    if legacy_begin in js_expected:
        before, tail = js_expected.split(legacy_begin, 1)
        _, after = tail.split(legacy_end, 1)
        js_expected = before + after.lstrip('\n')
    for name in ('organization','channels','connections','live','platform','pilot','businessforms','business','workspace','copilot'):
        begin, end = '/* COMMERCE_'+name.upper()+'_START */', '/* COMMERCE_'+name.upper()+'_END */'
        source = (ROOT/('web/'+name+'-ui.js')).read_text().rstrip()
        if name == 'workspace':
            source = (ROOT/'ui/next-actions.js').read_text().rstrip()+'\n'+source
        block = begin+'\n'+source+'\n'+end
        if begin in js_expected:
            before, tail = js_expected.split(begin, 1);_, after = tail.split(end, 1);js_expected = before+block+after
        else:
            anchor='/* COMMERCE_EXPOSURE_END */';js_expected=js_expected.replace(anchor,anchor+'\n'+block,1)
        if name in ('organization', 'channels', 'connections', 'live'):
            continue  # These views reuse the existing primitives and layout styles.
        begin, end = '/* COMMERCE_'+name.upper()+'_STYLE_START */', '/* COMMERCE_'+name.upper()+'_STYLE_END */'
        block = begin+'\n'+(ROOT/('web/'+name+'-ui.css')).read_text().rstrip()+'\n'+end
        if begin in expected:
            before, tail = expected.split(begin, 1);_, after = tail.split(end, 1);expected=before+block+after
        else:expected+='\n'+block+'\n'
    product_css = generated()+'\n'+(ROOT/'ui/primitives.css').read_text()+'\n'+(ROOT/'web/copilot-ui.css').read_text()+'\n'+(ROOT/'web/product-workspace-ui.css').read_text()
    product_js = (ROOT/'ui/status.js').read_text()+'\n'+(ROOT/'ui/kit.js').read_text()+'\n'+(ROOT/'web/copilot-ui.js').read_text()+'\n'+(ROOT/'web/research-context.js').read_text()+'\n'+(ROOT/'web/product-workspace-ui.js').read_text()
    product_outputs = {ROOT/'web/product-workspace.bundle.css':product_css,ROOT/'web/product-workspace.bundle.js':product_js}
    if args.check:
        if any(not path.exists() or path.read_text()!=body for path,body in product_outputs.items()):
            raise SystemExit('Product workspace resources are stale; run python3 commerce/ui/build.py')
        if expected != content or js_expected != javascript:
            raise SystemExit('UI kit/tokens are stale; run python3 commerce/ui/build.py')
        manifest_path=ROOT/'web/workbench.sources.json'
        if (ROOT/'workbench/package.json').exists():
            if not manifest_path.exists():raise SystemExit('React workspace is not built; run npm ci and npm run build in commerce/workbench')
            manifest=json.loads(manifest_path.read_text())
            for name,digest in {**manifest['sources'],**manifest['outputs']}.items():
                source=ROOT/name
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
                    raise SystemExit('React workspace resources are stale; run python3 commerce/ui/build.py')
        print('Shared UI kit and tokens match versioned sources.')
    else:
        if path.read_text() != content or js_path.read_text() != javascript:
            raise SystemExit('Concurrent UI edit detected; retry against current files.')
        for product_path,body in product_outputs.items():product_path.write_text(body)
        path.write_text(expected)
        js_path.write_text(js_expected)
        if (ROOT/'workbench/package.json').exists():
            node=shutil.which('node')
            if not node or not (ROOT/'workbench/node_modules/esbuild').is_dir():
                raise SystemExit('Install workspace build dependencies with npm ci --prefix commerce/workbench, then rebuild.')
            subprocess.run([node,str(ROOT/'workbench/build.mjs')],cwd=ROOT/'workbench',check=True)
        print('Shared UI kit and tokens bundled into existing web resources.')


if __name__ == '__main__':
    main()
