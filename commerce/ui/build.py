"""Bundle UI primitives/tokens into the existing shared resources; --check is read-only."""
import argparse
import json
import hashlib
import shutil
import subprocess
import sys
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
        base += '@media (prefers-color-scheme: dark) {\n:root[data-theme=\"system\"]'+selector+', :root[data-theme=\"system\"] '+selector+', :root:not([data-theme])'+selector+', :root:not([data-theme]) '+selector+' {\n'+dark_profile+'\n}\n}\n'
    return base + END


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    file_helper = (ROOT / 'ui/shipping-files.js').read_text().rstrip()
    host_path = ROOT / 'harness/client.js'
    host_original = host_path.read_text()
    host_start, host_end = '/* COMMERCE_SHIPPING_FILES_HOST_START */', '/* COMMERCE_SHIPPING_FILES_HOST_END */'
    host_block = host_start + '\n' + file_helper + '\n' + host_end
    if host_start in host_original:
        head, tail = host_original.split(host_start, 1)
        _, tail = tail.split(host_end, 1)
        host_expected = head + host_block + tail
    else:
        host_expected = host_block + '\n' + host_original
    subprocess.run([sys.executable, str(ROOT / 'creative_ui_build.py'), *(['--check'] if args.check else [])], check=True)
    subprocess.run([sys.executable, str(ROOT / 'skills_ui_build.py'), *(['--check'] if args.check else [])], check=True)
    subprocess.run([sys.executable, str(ROOT / 'a2ui/build_contract.py'), *(['--check'] if args.check else [])], check=True)
    if not (ROOT / 'workbench/map/node_modules/esbuild').exists():
        raise SystemExit('Install the pinned offline map build dependencies: npm ci --prefix commerce/workbench/map')
    subprocess.run(['node', str(ROOT / 'workbench/map/build.mjs'), *(['--check'] if args.check else [])], check=True)
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
    original_javascript = javascript
    # The operations view participates in the same source-of-truth build.
    ops_start, ops_end = '/* BEGIN GENERATED OPERATIONS MODULE */', '/* END GENERATED OPERATIONS MODULE */'
    if ops_start not in javascript or ops_end not in javascript:
        raise SystemExit('Operations module markers missing; preserve existing business code.')
    before, tail = javascript.split(ops_start, 1)
    _, after = tail.split(ops_end, 1)
    javascript = before + ops_start + '\n' + (ROOT / 'web/ops-ui.js').read_text().rstrip() + '\n' + ops_end + after
    start, end = '/* COMMERCE_UI_KIT_START */', '/* COMMERCE_UI_KIT_END */'
    kit = start + '\n' + (ROOT / 'ui/status.js').read_text().rstrip() + '\n' + (ROOT / 'ui/kit.js').read_text().rstrip() + '\n' + (ROOT / 'web/product-identity.js').read_text().rstrip() + '\n' + (ROOT / 'ui/page-context.js').read_text().rstrip() + '\n' + file_helper + '\n' + end
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
    intel = (ROOT / 'web/intel-map.bundle.js').read_text() + '\n' + (ROOT / 'web/social-ui.js').read_text() + '\n' + (ROOT / 'web/intel-dashboard-ui.js').read_text() + '\n' + (ROOT / 'web/intel-live-ui.js').read_text() + '\n' + (ROOT / 'web/ozon-search-terms-ui.js').read_text() + '\n' + (ROOT / 'web/intel-opportunities-ui.js').read_text() + '\n' + (ROOT / 'web/intel-ui.js').read_text().replace('__INTEL_WORLD_PATH__', (ROOT / 'web/intel-land.txt').read_text())
    if intel_start not in js_expected or intel_end not in js_expected:
        raise SystemExit('Shared information module markers missing; preserve existing business modules.')
    before, tail = js_expected.split(intel_start, 1)
    _, after = tail.split(intel_end, 1)
    js_expected = before + intel_start + '\n' + intel.rstrip() + '\n' + intel_end + after
    intel_css_start, intel_css_end = '/* COMMERCE_INTEL_STYLE_START */', '/* COMMERCE_INTEL_STYLE_END */'
    intel_css = intel_css_start + '\n' + (ROOT / 'web/social-ui.css').read_text().rstrip() + '\n' + (ROOT / 'web/intel-ui.css').read_text().rstrip() + '\n' + (ROOT / 'web/intel-map.bundle.css').read_text().rstrip() + '\n' + intel_css_end
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
    legacy_begin, legacy_end = '/* BEGIN GENERATED LIVE PLAN MODULE */', '/* END GENERATED LIVE PLAN MODULE */'
    if legacy_begin in js_expected:
        before, tail = js_expected.split(legacy_begin, 1)
        _, after = tail.split(legacy_end, 1)
        js_expected = before + after.lstrip('\n')
    for name in ('organization','channels','connections','live-plan','live','platform','pilot','businessforms','business','shipping','workspace','copilot'):
        marker=name.upper().replace('-','_')
        begin, end = '/* COMMERCE_'+marker+'_START */', '/* COMMERCE_'+marker+'_END */'
        source = (ROOT/('web/'+name+'-ui.js')).read_text().rstrip()
        if name == 'business':
            source = (ROOT/'web/order-support-context.js').read_text().rstrip()+'\n'+source
        if name == 'copilot':
            source = (ROOT/'web/copilot-upload.js').read_text()+'\n'+(ROOT/'web/copilot-reading.js').read_text()+'\n'+(ROOT/'web/copilot-events.js').read_text()+'\n'+(ROOT/'web/copilot-evidence.js').read_text().rstrip()+'\n'+(ROOT/'web/copilot-interactions.js').read_text().rstrip()+'\n'+(ROOT/'web/generative-ui.js').read_text().rstrip()+'\n'+(ROOT/'web/copilot-capabilities.js').read_text().rstrip()+'\n'+source
        if name == 'workspace':
            source = (ROOT/'ui/next-actions.js').read_text().rstrip()+'\n'+source
        if name == 'shipping':
            source = (ROOT/'web/shipping-viewer.js').read_text().rstrip()+'\n'+source
        block = begin+'\n'+source+'\n'+end
        if begin in js_expected:
            before, tail = js_expected.split(begin, 1);_, after = tail.split(end, 1);js_expected = before+block+after
        else:
            anchor='/* COMMERCE_EXPOSURE_END */';js_expected=js_expected.replace(anchor,anchor+'\n'+block,1)
        if name in ('organization', 'channels', 'connections', 'live'):
            continue  # These views reuse the existing primitives and layout styles.
        begin, end = '/* COMMERCE_'+name.upper()+'_STYLE_START */', '/* COMMERCE_'+name.upper()+'_STYLE_END */'
        block = begin+'\n'+(ROOT/('web/'+name+'-ui.css')).read_text().rstrip()+'\n'+end
        if name=='copilot':block=block.replace('\n'+end,'\n'+(ROOT/'web/copilot-capabilities.css').read_text().rstrip()+'\n'+end)
        if name=='shipping':block=block.replace('\n'+end,'\n'+(ROOT/'web/shipping-viewer.css').read_text().rstrip()+'\n'+end)
        if begin in expected:
            before, tail = expected.split(begin, 1);_, after = tail.split(end, 1);expected=before+block+after
        else:expected+='\n'+block+'\n'
    for name in ('catalog','media-library','media-provider','media-workflow','creative','extensions','ops'):
        begin,end='/* COMMERCE_'+name.upper()+'_STYLE_START */','/* COMMERCE_'+name.upper()+'_STYLE_END */'
        block=begin+'\n'+(ROOT/('web/'+name+'-ui.css')).read_text().rstrip()+'\n'+end
        if begin in expected:
            before,tail=expected.split(begin,1);_,after=tail.split(end,1);expected=before+block+after
        else:expected+='\n'+block+'\n'
    workspace_style = (ROOT/'ui/workspace.css').read_text().rstrip()
    begin,end='/* COMMERCE_UI_COMPOSITION_START */','/* COMMERCE_UI_COMPOSITION_END */'
    block=begin+'\n'+workspace_style+'\n'+end
    if begin in expected:
        before,tail=expected.split(begin,1);_,after=tail.split(end,1);expected=before+block+after
    else:expected+='\n'+block+'\n'
    product_css = generated()+'\n'+(ROOT/'ui/primitives.css').read_text()+'\n'+(ROOT/'web/copilot-ui.css').read_text()+'\n'+(ROOT/'web/copilot-capabilities.css').read_text()+'\n'+(ROOT/'web/product-workspace-ui.css').read_text()+'\n'+(ROOT/'web/product-evidence-ui.css').read_text()+'\n'+(ROOT/'web/catalog-ui.css').read_text()+'\n'+(ROOT/'web/media-library-ui.css').read_text()+'\n'+(ROOT/'web/media-provider-ui.css').read_text()+'\n'+(ROOT/'web/media-workflow-ui.css').read_text()+'\n'+(ROOT/'web/creative-ui.css').read_text()+'\n'+workspace_style
    product_js = (ROOT/'ui/status.js').read_text()+'\n'+(ROOT/'ui/kit.js').read_text()+'\n'+(ROOT/'web/product-identity.js').read_text()+'\n'+(ROOT/'ui/page-context.js').read_text()+'\n'+(ROOT/'web/copilot-upload.js').read_text()+'\n'+(ROOT/'web/copilot-reading.js').read_text()+'\n'+(ROOT/'web/copilot-events.js').read_text()+'\n'+(ROOT/'web/copilot-evidence.js').read_text()+'\n'+(ROOT/'web/copilot-interactions.js').read_text()+'\n'+(ROOT/'web/generative-ui.js').read_text()+'\n'+(ROOT/'web/copilot-capabilities.js').read_text()+'\n'+(ROOT/'web/copilot-ui.js').read_text()+'\n'+(ROOT/'web/research-context.js').read_text()+'\n'+(ROOT/'web/catalog-presentation.js').read_text()+'\n'+(ROOT/'web/media-library-ui.js').read_text()+'\n'+(ROOT/'web/catalog-ui.js').read_text()+'\n'+(ROOT/'web/media-video-review-ui.js').read_text()+'\n'+(ROOT/'web/media-plugin-execution-ui.js').read_text()+'\n'+(ROOT/'web/media-plugin-ui.js').read_text()+'\n'+(ROOT/'web/media-provider-ui.js').read_text()+'\n'+(ROOT/'web/creative-readiness-ui.js').read_text()+'\n'+(ROOT/'web/media-quality-ui.js').read_text()+'\n'+(ROOT/'web/media-delivery-ui.js').read_text()+'\n'+(ROOT/'web/media-workflow-ui.js').read_text()+'\n'+(ROOT/'creative_ui.js').read_text()+'\n'+(ROOT/'web/product-creative-links.js').read_text()+'\n'+(ROOT/'web/sourcing-ui.js').read_text()+'\n'+(ROOT/'web/product-evidence-ui.js').read_text()+'\n'+(ROOT/'web/product-research-editor.js').read_text()+'\n'+(ROOT/'web/product-workspace-ui.js').read_text()
    product_outputs = {ROOT/'web/product-workspace.bundle.css':product_css,ROOT/'web/product-workspace.bundle.js':product_js}
    if args.check:
        if host_expected != host_original:
            raise SystemExit('Harness shipping file helper is stale; run python3 commerce/ui/build.py')
        if any(not path.exists() or path.read_text()!=body for path,body in product_outputs.items()):
            raise SystemExit('Product workspace resources are stale; run python3 commerce/ui/build.py')
        if expected != content or js_expected != original_javascript:
            raise SystemExit('UI kit/tokens are stale; run python3 commerce/ui/build.py')
        manifest_path=ROOT/'web/workbench.sources.json'
        if (ROOT/'workbench/package.json').exists():
            if not manifest_path.exists():raise SystemExit('React workspace is not built; run npm ci and npm run build in commerce/workbench')
            manifest=json.loads(manifest_path.read_text())
            expected_sources=set(json.loads(subprocess.check_output(['node',str(ROOT/'workbench/source-inputs.mjs')],text=True)))
            if set(manifest.get('sources',{}))!=expected_sources or set(manifest.get('outputs',{}))!={'web/workbench.bundle.js','web/workbench.bundle.css'}:
                raise SystemExit('React workspace source inventory is incomplete; rebuild with commerce/ui/build.py')
            for name,digest in {**manifest['sources'],**manifest['outputs']}.items():
                source=ROOT/name
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
                    raise SystemExit('React workspace resources are stale; run python3 commerce/ui/build.py')
        print('Shared UI kit and tokens match versioned sources.')
    else:
        if path.read_text() != content or js_path.read_text() != original_javascript or host_path.read_text() != host_original:
            raise SystemExit('Concurrent UI edit detected; retry against current files.')
        host_path.write_text(host_expected)
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
