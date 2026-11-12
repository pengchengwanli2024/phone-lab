"""One inline React artifact for the browser and opaque Harness iframe."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def page():
    from ui.build import generated
    css = generated() + '\n' + (ROOT / 'ui/primitives.css').read_text() + '\n' + (ROOT / 'web/workbench.bundle.css').read_text()
    kit = (ROOT / 'ui/status.js').read_text() + '\n' + (ROOT / 'ui/kit.js').read_text()
    return (ROOT / 'web/workbench.html').read_text().replace('/* INLINE_STYLE */', css).replace('/* INLINE_KIT */', kit).replace('/* INLINE_APP */', (ROOT / 'web/workbench.bundle.js').read_text())
