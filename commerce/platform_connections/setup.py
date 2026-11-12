"""Private configuration page, using the same canonical UI kit and stylesheet."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def page():
 style=(ROOT/'web/style.css').read_text();kit=(ROOT/'ui/kit.js').read_text();script=(ROOT/'web/platform-setup.js').read_text()
 return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport"content="width=device-width,initial-scale=1"><title>平台私有接入</title><style>'+style+'</style></head><body><main id="platform-setup-root"class="platform-setup">正在读取本机接入状态…</main><script>'+kit+'\n'+script+'</script></body></html>'
