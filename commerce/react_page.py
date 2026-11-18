"""One React artifact for the browser and for opaque Harness iframes.

The page always carries its own style, shared kit and executable shell. The three
embedded business documents are optional: the browser fetches them on demand from
/workspace/document/<id>, while a host that only receives an HTML string (the Harness
srcdoc iframe has no usable origin) keeps them inline as the default.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent

DOCUMENTS = ('legacy', 'product', 'intel-map')
_BLOCK = re.compile(
    r'<script id="commerce-embedded-(?P<id>[a-z][a-z0-9-]*)" type="application/octet-stream">(?P<payload>[^<]*)</script>'
)


def payloads():
    """The exact base64 payloads already produced by the build; never re-encoded here."""
    found = {match['id']: match['payload'] for match in _BLOCK.finditer((ROOT / 'web/workbench.html').read_text())}
    if set(found) != set(DOCUMENTS):
        raise RuntimeError('embedded_documents_incomplete')
    return found


def without_documents(html):
    """Keep each block's completion marker so a module still initialises on its own."""
    def replace(match):
        return '<script id="commerce-embedded-%s" type="application/octet-stream" data-commerce-fetch="1"></script>' % match['id']
    return _BLOCK.sub(replace, html)


def page(documents=True):
    from ui.build import generated
    css = generated() + '\n' + (ROOT / 'ui/primitives.css').read_text() + '\n' + (ROOT / 'web/workbench.bundle.css').read_text()
    kit = (ROOT / 'ui/status.js').read_text() + '\n' + (ROOT / 'ui/kit.js').read_text() + '\n' + (ROOT / 'ui/shipping-files.js').read_text()
    html = (ROOT / 'web/workbench.html').read_text().replace('/* INLINE_STYLE */', css).replace('/* INLINE_KIT */', kit).replace('/* INLINE_APP */', (ROOT / 'web/workbench.bundle.js').read_text())
    return html if documents else without_documents(html)
