"""Protected model setup, sharing the canonical kit and styles."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def page():
    style=(ROOT/'web/style.css').read_text();kit=(ROOT/'ui/kit.js').read_text();script=(ROOT/'web/model-setup.js').read_text()
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>模型与本地服务</title><style>'+style+'\n.model-setup{max-width:1040px;margin:auto;padding:var(--ui-space-6)}.model-setup .model-fields{display:grid;grid-template-columns:1fr 1fr;gap:var(--ui-space-4)}.model-setup .model-wide{grid-column:1/-1}.model-setup .model-actions{display:flex;gap:var(--ui-space-2);flex-wrap:wrap;margin-top:var(--ui-space-4)}.model-setup select,.model-setup input{max-width:100%}.model-setup h1{font-size:24px;margin:0}.model-setup pre{white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:600px){.model-setup{padding:var(--ui-space-3)}.model-setup .model-fields{grid-template-columns:1fr}}</style></head><body data-ui-appearance="shopify"><main id="model-setup-root" class="model-setup">正在读取模型配置…</main><script>'+kit+'\n'+script+'</script></body></html>'
