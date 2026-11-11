"""Deterministic synthetic pages for extraction, rendering and pagination checks."""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
from urllib.parse import parse_qs, urlsplit

PRODUCTS = [
    {'sku': 'SYN-A', 'title': '旅行水杯 Café', 'price': '19.90', 'currency': 'USD', 'stock': '12'},
    {'sku': 'SYN-B', 'title': '灯具 & 支架', 'price': '0.00', 'currency': 'USD', 'stock': '0'},
    {'sku': 'SYN-C', 'title': 'Notebook 日本語', 'price': '1200.50', 'currency': 'USD', 'stock': '7'},
    {'sku': 'SYN-D', 'title': 'Кружка 300 ml', 'price': '8.25', 'currency': 'USD', 'stock': '3'},
    {'sku': 'SYN-E', 'title': 'USB-C Cable', 'price': '4.99', 'currency': 'USD', 'stock': '50'},
    {'sku': 'SYN-F', 'title': '收纳盒 <小号>', 'price': '11.05', 'currency': 'USD', 'stock': '1'},
]
PAGES = [[0, 1, 2], [2, 3, 4], [4, 5]]


def cards(products):
    return ''.join('<article class="product">' + ''.join(
        f'<span class="{key}">{escape(value)}</span>' for key, value in product.items()
    ) + '</article>' for product in products)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        route = urlsplit(self.path)
        try:
            page = int(parse_qs(route.query).get('page', ['1'])[0])
        except ValueError:
            page = 0
        status, content_type = 200, 'text/html; charset=utf-8'
        if route.path == '/slow':
            time.sleep(3)
        if route.path == '/robots.txt':
            content_type, body = 'text/plain', 'User-agent: *\nDisallow: /private/\n'
        elif route.path == '/quote-static':
            body = '<html><div class="quote"><span class="text">Synthetic  quote.</span><small class="author">Fixture author</small></div></html>'
        elif route.path == '/api/quotes':
            content_type = 'application/json'
            body = json.dumps({'has_next': False, 'quotes': [{'text': 'Synthetic quote.', 'author': {'name': 'Fixture author'}}]})
        elif route.path == '/broken':
            status, body = 503, '<h1>Fixture unavailable</h1>'
        elif route.path in ('/static', '/dynamic', '/api/products', '/partial', '/truncated', '/conflict', '/slow') and 1 <= page <= 3:
            products = [dict(PRODUCTS[i]) for i in PAGES[page - 1]]
            if route.path == '/partial':
                products[0]['currency'] = ''
            elif route.path == '/truncated':
                products = products[:1]
            elif route.path == '/conflict':
                products[0]['price'] = '999.99'
            if route.path == '/api/products':
                content_type, body = 'application/json', json.dumps(products, ensure_ascii=False)
            else:
                link = f'<a rel="next" href="{route.path}?page={page+1}">Next</a>' if page < 3 else ''
                content = cards(products) if route.path != '/dynamic' else ''
                script = '' if route.path != '/dynamic' else f'''<script>
setTimeout(async () => {{
  const rows = await (await fetch('/api/products?page={page}')).json();
  const root = document.querySelector('#products');
  for (const row of rows) {{
    const card = document.createElement('article'); card.className = 'product';
    for (const [key, value] of Object.entries(row)) {{
      const field = document.createElement('span'); field.className = key;
      field.textContent = value; card.appendChild(field);
    }}
    root.appendChild(card);
  }}
  root.dataset.loaded = 'true';
}}, 350);
</script>'''
                body = f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>Synthetic catalog</title><body><h1>Synthetic catalog</h1><main id="products">{content}</main>{link}{script}</body></html>'
        else:
            status, body = 404, '<h1>Not found</h1>'
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def server():
    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)
