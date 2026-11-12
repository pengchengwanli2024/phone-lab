"""Same compiled product surface for the authenticated browser and Harness iframe."""
from pathlib import Path


def page():
    root = Path(__file__).resolve().parent / 'web'
    return (root / 'product-workspace.html').read_text().replace('/* INLINE_STYLE */', (root / 'product-workspace.bundle.css').read_text()).replace('/* INLINE_APP */', (root / 'product-workspace.bundle.js').read_text()).replace('__COMMERCE_BOOTSTRAP__', '{"embedded":false}')
