"""Private, authenticated setup for media endpoints and plugin credentials."""
from pathlib import Path
import webbrowser

ROOT=Path(__file__).resolve().parent


def page():
    styles=(ROOT/'web/style.css').read_text()
    kit=(ROOT/'ui/status.js').read_text()+'\n'+(ROOT/'ui/kit.js').read_text()
    script=(ROOT/'web/capability-setup.js').read_text()
    return ('<!doctype html><html lang="zh-CN" data-ui-appearance="shopify"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>模型服务与插件接入</title><style>'+styles+
            '\n.capability-setup{max-width:1120px;margin:auto;padding:var(--ui-space-5)}.capability-setup h1{font-size:26px}'
            '.capability-setup .setup-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--ui-space-4)}'
            '.capability-setup .ui-card{margin-top:var(--ui-space-5);padding:var(--ui-space-4)}.capability-setup textarea{width:100%;resize:vertical;line-height:1.6}'
            '.capability-setup .form-actions{display:flex;gap:var(--ui-space-2);flex-wrap:wrap;margin:var(--ui-space-4) 0}.capability-setup .ui-field{min-width:0;margin-bottom:var(--ui-space-3)}'
            '.capability-setup pre{white-space:pre-wrap;overflow-wrap:anywhere}.capability-setup td{vertical-align:top}.capability-setup .ui-control{max-width:100%}'
            '@media(max-width:680px){.capability-setup{padding:var(--ui-space-3)}.capability-setup .setup-fields{grid-template-columns:1fr}}'
            '</style></head><body><main id="capability-setup-root" class="capability-setup">正在读取接入设置…</main><script>'+kit+'\n'+script+'</script></body></html>')


def open_setup(service):
    from runtime import PORT
    ticket=service.live.new_setup_ticket()
    opened=webbrowser.open(f'http://127.0.0.1:{PORT}/capability-setup?ticket='+ticket)
    return {'opened':bool(opened),'status':'opened_local_private_setup' if opened else 'browser_open_unconfirmed'}
