"""Fixed public retail origins; no cookies, login, challenge bypass or redirects."""
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import time
from urllib.parse import urlencode, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[2]
HOSTS = {'www.maxidom.ru': ('/catalog/', '/search/'),
         'www.sima-land.ru': ('/search/', '/organajzery-dlya-kuhni/'),
         'www.ozon.ru': ('/search/', '/category/')}
MAX_BYTES = 2_500_000


def allowed(url, resolve=True):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc not in HOSTS or p.username or p.password
            or p.fragment or len(url) > 1800 or not p.path.startswith(HOSTS[p.netloc])):
        raise ValueError('market_research_url_rejected')
    if resolve:
        for entry in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(entry[4][0]).is_global:
                raise ValueError('market_research_address_rejected')
    return url


def urls(query):
    # The planner supplies search text, never a network location or executable.
    return ['https://www.maxidom.ru/search/catalog/?' + urlencode({'q': query}),
            'https://www.sima-land.ru/search/?' + urlencode({'q': query}),
            'https://www.ozon.ru/search/?' + urlencode({'text': query})]


class Page(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.stack, self.parts, self.products, self.scripts = url, [], [], [], []
        self.current, self.title, self.product_depth = None, '', 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'article' and 'schema.org/Product' in a.get('itemtype', ''):
            self.current = {'title': '', 'url': '', 'price': '', 'currency': '', 'text': ''}
            self.product_depth = len(self.stack) + 1
        prop = a.get('itemprop', '')
        if self.current:
            if prop == 'url' and a.get('href'):
                link = urljoin(self.url, a['href'])
                if urlsplit(link).netloc == urlsplit(self.url).netloc: self.current['url'] = link
            if prop == 'priceCurrency': self.current['currency'] = a.get('content', '')[:10]
            if prop == 'price' and a.get('content'): self.current['price'] = a['content'][:40]
        if tag not in ('meta', 'img', 'br', 'hr', 'input', 'link', 'source', 'wbr', 'area', 'embed'):
            self.stack.append((tag, prop, a.get('type', '')))

    def handle_endtag(self, tag):
        if self.current and tag == 'article':
            self.current['text'] = ' '.join(self.current['text'].split())[:2000]
            if self.current['title'].strip() and self.current['url']:
                self.current['title'] = ' '.join(self.current['title'].split())[:240]
                self.products.append(self.current)
            self.current = None
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if any(t[0] in ('script', 'style', 'noscript', 'svg') for t in self.stack): return
        value = ' '.join(data.split())
        if not value: return
        if any(t[0] == 'title' for t in self.stack): self.title += value
        self.parts.append(value)
        if self.current:
            self.current['text'] += value + ' '
            if any(t[1] == 'name' for t in self.stack): self.current['title'] += value + ' '
            if any(t[1] == 'price' for t in self.stack): self.current['price'] += value


def extract(raw, url):
    if len(raw) > MAX_BYTES: raise ValueError('market_research_payload_too_large')
    try: html = raw.decode('utf-8')
    except UnicodeDecodeError: html = raw.decode('cp1251', errors='replace')
    page = Page(url); page.feed(html)
    if any(s in page.title.lower() for s in ('captcha', 'access denied', 'just a moment', 'доступ ограничен')) or any(
            s in html.lower() for s in ('cf-chl-', 'verify you are human', 'checking your browser')):
        raise ValueError('market_research_challenge_no_bypass')
    products, seen = [], set()
    for item in page.products:
        if item['url'] in seen: continue
        seen.add(item['url']); products.append(item)
        if len(products) >= 40: break
    text = '\n'.join(item['text'] for item in products) if products else '\n'.join(page.parts)
    if not products and len(text) < 40: raise ValueError('market_research_body_unavailable')
    return {'title': page.title[:300], 'text': text[:24000], 'products': products,
            'sha256': hashlib.sha256(raw).hexdigest(), 'url': url}


def capture(url, directory, cancelled):
    allowed(url, resolve=False)
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    result_path = directory / (key + '.json')
    python = Path(os.environ.get('COMMERCE_CRAWLER_PYTHON', str(ROOT / '.local/crawlers/venv/bin/python')))
    if not python.is_file(): raise ValueError('market_research_crawler_setup_required')
    inherited = runpy.run_path(str(ROOT / 'crawlers/setup.py'))['environment']()
    keys = {'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}
    env = {k: v for k, v in inherited.items() if k in keys}
    process = subprocess.Popen([str(python), str(ROOT / 'crawlers/market.py'), '--url', url,
                                '--output', str(result_path)], env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline = time.monotonic() + 38
        while process.poll() is None:
            if cancelled(): raise ValueError('market_research_cancelled')
            if time.monotonic() > deadline: raise ValueError('market_research_source_timeout')
            time.sleep(.1)
        if not result_path.is_file(): raise ValueError('market_research_capture_failed')
        result = json.loads(result_path.read_text())
        if process.returncode or result.get('error'): raise ValueError(result.get('error', 'market_research_capture_failed'))
        return result
    finally:
        if process.poll() is None:
            from collection_jobs import terminate
            terminate(process)
