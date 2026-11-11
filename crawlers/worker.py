"""Bounded same-origin extraction using installed desktop crawler engines."""
import argparse
import asyncio
from datetime import timedelta, datetime, timezone
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import sys
import ssl
import tempfile
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs, urlencode
from urllib.request import Request, urlopen

from setup import STATE, environment

ENGINES = ('scrapy', 'crawl4ai', 'crawlee-http', 'crawlee-browser', 'scrapling-http',
           'scrapling-browser', 'firecrawl', 'scrapy+crawl4ai', 'crawl4ai+scrapling',
           'crawlee+scrapling', 'json-http', 'feed-http', 'feed-scrapling', 'feed-native')
FIELDS = ('sku', 'title', 'price', 'currency', 'stock')
WAIT_SELECTORS = {'products': '.product', 'books': '.product_pod', 'quotes': '.quote',
                  'product-schema': 'body'}
KIND_FIELDS = {'products': FIELDS, 'books': FIELDS, 'quotes': ('text', 'author'),
               'news': ('id', 'title', 'url', 'published'),
               'product-schema': (*FIELDS, 'url')}


def identity(row):
    return row.get('sku') or row.get('id') or row.get('text', '')


def browser_executable():
    configured = os.environ.get('CRAWLER_BROWSER_EXECUTABLE')
    if configured:
        return configured
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    if Path(executable).exists():
        return executable
    chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    return str(chrome) if chrome.exists() else None


def remote_proxy(url):
    if urlsplit(url).hostname in ('localhost', '127.0.0.1', '::1'):
        return None
    return os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')


def crawl4ai_browser(url):
    from crawl4ai import BrowserConfig
    # Crawl4AI supports a system Chrome channel; downloaded Chromium is the default.
    return BrowserConfig(headless=True, verbose=False, ignore_https_errors=False,
                         channel=os.environ.get('CRAWLER_BROWSER_CHANNEL', 'chromium'),
                         proxy=remote_proxy(url))


def http_status_hook(crawler, output):
    async def after_goto(page, response=None, **kwargs):
        if response and response.status >= 400:
            output.errors.append(f'http_{response.status}')
            raise RuntimeError('upstream_http_error')
        return page
    crawler.crawler_strategy.set_hook('after_goto', after_goto)


def extract(selector, kind, base_url=''):
    if kind == 'product-schema':
        from structured import products
        return products(selector.css('script[type="application/ld+json"]::text').getall(), base_url), None
    if kind == 'books':
        rows = []
        for node in selector.css('.product_pod'):
            price = (node.css('.price_color::text').get() or '').strip()
            rows.append({'sku': (node.css('h3 a::attr(href)').get() or '').strip(),
                         'title': (node.css('h3 a::attr(title)').get() or '').strip(),
                         'price': price[1:] if price.startswith('£') else price,
                         'currency': 'GBP' if price.startswith('£') else '',
                         'stock': ' '.join(' '.join(node.css('.availability::text').getall()).split())})
        return rows, selector.css('.next a::attr(href)').get()
    if kind == 'products':
        rows = [{key: (node.css(f'.{key}::text').get() or '').strip() for key in FIELDS}
                for node in selector.css('.product')]
        return rows, selector.css('a[rel="next"]::attr(href)').get()
    rows = [{'text': (node.css('.text::text').get() or '').strip(),
             'author': (node.css('.author::text').get() or '').strip()}
            for node in selector.css('.quote')]
    return rows, selector.css('.next a::attr(href)').get()


def selector_for(html, scrapling=False):
    if scrapling:
        from scrapling.parser import Selector
        return Selector(content=html, adaptive=False)
    from parsel import Selector
    return Selector(text=html)


class Result:
    def __init__(self, args):
        self.args = args
        self.rows, self.pages, self.errors = [], [], []
        self.record_evidence = {}
        self.markdown_chars = 0
        self.rendered = 0

    def consume(self, url, html, status=200, scrapling=False):
        if status >= 400:
            self.errors.append(f'http_{status}')
            return None
        rows, link = extract(selector_for(html, scrapling), self.args.kind, url)
        self.add_page(url, rows, html.encode(), status, 'html')
        return self.next(url, link)

    def add_page(self, url, rows, payload, status=200, format='html'):
        payload_hash = hashlib.sha256(payload).hexdigest()
        captured = datetime.now(timezone.utc).isoformat()
        self.pages.append({'url': url, 'status': status, 'records': len(rows),
                           'html_sha256': payload_hash, 'format': format, 'captured_at': captured})
        for index, row in enumerate(rows):
            self.record_evidence.setdefault(identity(row), []).append({
                'source_url': url, 'captured_at': captured,
                'locator': f'{format}:record[{index + 1}]', 'payload_sha256': payload_hash,
                'record_sha256': hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            })
        self.rows.extend(rows)

    def next(self, url, link):
        if not link:
            return None
        target = urljoin(url, link)
        return target if urlsplit(target).netloc == urlsplit(self.args.url).netloc else None

    def finish(self):
        unique = {}
        for row in self.rows:
            key = identity(row) or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            if key in unique and unique[key] != row and 'duplicate_conflict' not in self.errors:
                self.errors.append('duplicate_conflict')
            unique[key] = row
        rows = list(unique.values())
        if not rows and not self.errors:
            self.errors.append('no_records')
        required = KIND_FIELDS[self.args.kind]
        if rows and any(not row.get(key) for row in rows for key in required
                        if not (self.args.kind == 'news' and key == 'published')):
            self.errors.append('incomplete_fields')
        blocked = any(error in ('firecrawl_backend_not_configured', 'browser_not_installed',
                                'WebsiteNotSupportedError') for error in self.errors)
        return {'engine': self.args.engine, 'status': 'blocked' if blocked else 'failed' if self.errors else 'ok',
                'errors': self.errors, 'rows': rows, 'pages': self.pages,
                'record_evidence': self.record_evidence,
                'raw_records': len(self.rows), 'unique_records': len(rows),
                'duplicates_removed': len(self.rows) - len(rows),
                'rendered_pages': None if self.args.engine == 'firecrawl' else self.rendered,
                'markdown_chars': self.markdown_chars}


async def render_crawl4ai(url, kind):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    wait = 'css:' + WAIT_SELECTORS[kind]
    async with AsyncWebCrawler(config=crawl4ai_browser(url),
                               base_directory=str(STATE / 'crawl4ai')) as crawler:
        result = await crawler.arun(url, config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS, wait_for=wait, page_timeout=25000,
            wait_for_timeout=10000, verbose=False))
        if not result.success or (result.status_code or 200) >= 400:
            raise RuntimeError('render_failed')
        return result.html, len(str(result.markdown or ''))


def scrapy_run(args, output):
    import scrapy
    from scrapy.crawler import CrawlerProcess

    class Catalog(scrapy.Spider):
        name = 'desktop_lab'
        custom_settings = {'ROBOTSTXT_OBEY': True, 'LOG_ENABLED': False,
                           'RETRY_ENABLED': False, 'DOWNLOAD_TIMEOUT': 25,
                           'CONCURRENT_REQUESTS': 1, 'TELNETCONSOLE_ENABLED': False,
                           'HTTPPROXY_ENABLED': True}

        async def start(self):
            yield scrapy.Request(args.url, callback=self.parse, errback=self.failed)

        async def parse(self, response):
            html = response.text
            rows, _ = extract(response, args.kind)
            if args.engine == 'scrapy+crawl4ai' and not rows:
                html, chars = await render_crawl4ai(response.url, args.kind)
                output.markdown_chars += chars
                output.rendered += 1
            link = output.consume(response.url, html, response.status)
            if link and len(output.pages) < args.max_pages:
                yield response.follow(link, callback=self.parse, errback=self.failed)

        def failed(self, failure):
            status = getattr(getattr(failure.value, 'response', None), 'status', None)
            output.errors.append(f'http_{status}' if status else 'request_failed')

    process = CrawlerProcess()
    process.crawl(Catalog)
    process.start()


async def crawlee_run(args, output):
    from crawlee import ConcurrencySettings
    from crawlee.crawlers import BeautifulSoupCrawler, PlaywrightCrawler
    browser = args.engine in ('crawlee-browser', 'crawlee+scrapling')
    cls = PlaywrightCrawler if browser else BeautifulSoupCrawler
    options = dict(max_requests_per_crawl=args.max_pages, max_request_retries=0,
                   concurrency_settings=ConcurrencySettings(min_concurrency=1, max_concurrency=1),
                   request_handler_timeout=timedelta(seconds=30), respect_robots_txt_file=True)
    proxy = remote_proxy(args.url)
    if proxy:
        from crawlee.proxy_configuration import ProxyConfiguration
        options['proxy_configuration'] = ProxyConfiguration(proxy_urls=[proxy])
    if browser:
        options['browser_launch_options'] = {'executable_path': args.browser_executable}
    crawler = cls(**options)

    @crawler.router.default_handler
    async def handle(context):
        if browser:
            await context.page.wait_for_selector(WAIT_SELECTORS[args.kind], timeout=10000)
            html = await context.page.content()
            output.rendered += 1
        else:
            html = str(context.soup)
        link = output.consume(context.request.url, html,
                              scrapling=args.engine == 'crawlee+scrapling')
        if link and len(output.pages) < args.max_pages:
            await context.add_requests([link])

    @crawler.failed_request_handler
    async def failed(context, error):
        status = getattr(error, 'status_code', None)
        output.errors.append(f'http_{status}' if status else 'request_failed')

    await crawler.run([args.url])


async def crawl4ai_run(args, output):
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    async with AsyncWebCrawler(config=crawl4ai_browser(args.url),
                               base_directory=str(STATE / 'crawl4ai')) as crawler:
        http_status_hook(crawler, output)
        url = args.url
        while url and len(output.pages) < args.max_pages:
            result = await crawler.arun(url, config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS, wait_for='css:' + WAIT_SELECTORS[args.kind],
                page_timeout=25000, wait_for_timeout=10000, verbose=False))
            if not result.success:
                if not output.errors:
                    output.errors.append('render_failed')
                break
            output.markdown_chars += len(str(result.markdown or ''))
            output.rendered += 1
            next_url = output.consume(url, result.html, result.status_code or 200,
                                      scrapling=args.engine == 'crawl4ai+scrapling')
            if next_url == url:
                break
            url = next_url


def scrapling_run(args, output):
    from scrapling.fetchers import Fetcher
    url = args.url
    if args.engine == 'scrapling-browser':
        from scrapling.fetchers import StealthySession
        with StealthySession(headless=True, executable_path=args.browser_executable,
                            solve_cloudflare=False, google_search=False,
                            proxy=remote_proxy(args.url)) as session:
            while url and len(output.pages) < args.max_pages:
                page = session.fetch(url, wait_selector=WAIT_SELECTORS[args.kind])
                output.rendered += 1
                url = output.consume(url, page.html_content, page.status, scrapling=True)
    else:
        while url and len(output.pages) < args.max_pages:
            page = Fetcher.get(url, timeout=25, proxy=remote_proxy(url))
            url = output.consume(url, page.html_content, page.status, scrapling=True)


def firecrawl_run(args, output):
    from firecrawl import Firecrawl
    endpoint = os.environ.get('FIRECRAWL_API_URL')
    if not endpoint:
        if os.environ.get('FIRECRAWL_CLOUD_TEST') != '1' or urlsplit(args.url).hostname != 'quotes.toscrape.com':
            output.errors.append('firecrawl_backend_not_configured')
            return
        endpoint = 'https://api.firecrawl.dev'
        # The opt-in sandbox probe must not consume a pre-existing account key.
        os.environ.pop('FIRECRAWL_API_KEY', None)
    app = Firecrawl(api_url=endpoint, api_key=os.environ.get('FIRECRAWL_API_KEY'),
                    timeout=40, max_retries=0, origin='desktop-crawler-lab')
    url = args.url
    while url and len(output.pages) < args.max_pages:
        page = app.scrape(url, formats=['rawHtml', 'markdown'], wait_for=1000,
                          timeout=30000, max_age=0, store_in_cache=False)
        output.markdown_chars += len(page.markdown or '')
        url = output.consume(url, page.raw_html or '', (page.metadata.status_code or 200))


def json_run(args, output):
    """Explicit product-list and Quotes to Scrape API schemas; no inferred fields."""
    url = args.url
    for index in range(args.max_pages):
        with public_request(url) as response:
            data = response.read(4_000_001)
            if len(data) > 4_000_000:
                raise ValueError('response_too_large')
            document = json.loads(data)
            if args.kind == 'quotes':
                rows = [{'text': row.get('text', ''), 'author': (row.get('author') or {}).get('name', '')}
                        for row in document['quotes']]
                more = bool(document.get('has_next'))
            elif args.kind == 'products' and isinstance(document, list):
                rows = [{key: str(row[key]) if row.get(key) is not None else '' for key in FIELDS}
                        for row in document]
                more = bool(rows)
            else:
                raise ValueError('unsupported_json_schema')
            output.add_page(url, rows, data, response.status, 'json')
        if not more:
            break
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        query['page'] = [str(int(query.get('page', ['1'])[0]) + 1)]
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ''))


def parse_feed(data, base_url):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('xml_entities_rejected')
    root = ET.fromstring(data)
    rows = []
    for item in root.iter():
        if item.tag.rsplit('}', 1)[-1] not in ('item', 'entry'):
            continue
        fields = {}
        for child in item:
            name = child.tag.rsplit('}', 1)[-1]
            value = child.attrib.get('href') if name == 'link' else None
            fields.setdefault(name, value or ''.join(child.itertext()).strip())
        link = urljoin(base_url, fields.get('link', '')) if fields.get('link') else ''
        if urlsplit(link).scheme not in ('http', 'https'):
            link = ''
        rows.append({'id': fields.get('guid') or fields.get('id') or link,
                     'title': unescape(fields.get('title', '')),
                     'url': link, 'published': fields.get('pubDate') or fields.get('published')
                     or fields.get('date') or fields.get('updated') or ''})
        if len(rows) >= 20:
            break
    return rows


def public_request(url):
    # Use OS-managed roots and intermediate certificate retrieval; never disable TLS verification.
    import truststore
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return urlopen(Request(url, headers={'User-Agent': 'desktop-crawler-lab/0.1'}), timeout=25, context=context)


def feed_run(args, output):
    if args.kind != 'news':
        raise ValueError('feed_requires_news_schema')
    if args.engine == 'feed-native':
        import subprocess
        (STATE / 'cache').mkdir(parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(prefix='feed-', dir=STATE / 'cache')
        os.close(descriptor)
        try:
            native = '/usr/bin/curl' if Path('/usr/bin/curl').exists() else 'curl'
            result = subprocess.run([native, '--fail', '--silent', '--show-error', '--location',
                                     '--proto', '=http,https', '--proto-redir', '=http,https',
                                     '--max-time', '25', '--max-filesize', '4000000',
                                     '--output', filename, '--write-out', '%{http_code}', args.url],
                                    capture_output=True, env=environment(), timeout=30)
            status = int(result.stdout) if result.stdout.isdigit() else 0
            if result.returncode:
                output.errors.append('tls_certificate_error' if result.returncode == 60 else
                                     f'http_{status}' if status >= 400 else 'native_request_failed')
                return
            data = Path(filename).read_bytes()
        finally:
            Path(filename).unlink(missing_ok=True)
    elif args.engine == 'feed-scrapling':
        from scrapling.fetchers import Fetcher
        response = Fetcher.get(args.url, timeout=25, proxy=remote_proxy(args.url))
        if response.status >= 400:
            output.errors.append(f'http_{response.status}')
            return
        data = response.body
        if isinstance(data, str):
            data = data.encode()
        status = response.status
    else:
        with public_request(args.url) as response:
            data, status = response.read(4_000_001), response.status
    if len(data) > 4_000_000:
        raise ValueError('response_too_large')
    output.add_page(args.url, parse_feed(data, args.url), data, status, 'rss_or_atom')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=ENGINES, required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--kind', choices=tuple(KIND_FIELDS), default='products')
    parser.add_argument('--max-pages', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.engine == 'firecrawl' and os.environ.get('FIRECRAWL_FIXTURE_ORIGIN'):
        target = urlsplit(args.url)
        if target.hostname == '127.0.0.1':
            args.url = os.environ['FIRECRAWL_FIXTURE_ORIGIN'].rstrip('/') + target.path
            if target.query:
                args.url += '?' + target.query
    parsed = urlsplit(args.url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        parser.error('Use an HTTP(S) URL without embedded credentials')
    if not 1 <= args.max_pages <= 10:
        parser.error('max-pages must be between 1 and 10')
    os.environ.update(environment())
    # Isolate Crawlee queues between subprocess runs, including repeat benchmarks.
    os.environ['CRAWLEE_STORAGE_DIR'] = str(STATE / 'storage' / str(os.getpid()))
    uses_browser = args.engine in ('crawl4ai', 'crawlee-browser', 'scrapling-browser',
                                   'scrapy+crawl4ai', 'crawl4ai+scrapling', 'crawlee+scrapling')
    args.browser_executable = browser_executable() if uses_browser else None
    if args.browser_executable and '/Google Chrome.app/' in args.browser_executable:
        os.environ['CRAWLER_BROWSER_CHANNEL'] = 'chrome'
    started = time.perf_counter()
    output = Result(args)
    try:
        if args.engine.startswith('scrapy'):
            scrapy_run(args, output)
        elif args.engine.startswith('crawl4ai'):
            asyncio.run(crawl4ai_run(args, output))
        elif args.engine.startswith('crawlee'):
            asyncio.run(crawlee_run(args, output))
        elif args.engine.startswith('scrapling'):
            scrapling_run(args, output)
        elif args.engine == 'json-http':
            json_run(args, output)
        elif args.engine.startswith('feed-'):
            feed_run(args, output)
        else:
            firecrawl_run(args, output)
    except Exception as error:
        # No raw exception strings: URLs, paths or provider credentials can appear there.
        code = getattr(error, 'code', None)
        output.errors.append('browser_not_installed' if "Executable doesn't exist" in str(error)
                             else 'tls_certificate_error' if code == 60 or 'CERTIFICATE_VERIFY_FAILED' in str(error)
                             else f'http_{code}' if isinstance(code, int) and 400 <= code < 600 else type(error).__name__)
    result = output.finish()
    result['captured_at'] = datetime.now(timezone.utc).isoformat()
    result['elapsed_seconds'] = round(time.perf_counter() - started, 3)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    args.output.chmod(0o600)
    print(json.dumps({key: result[key] for key in ('engine', 'status', 'unique_records', 'errors')}))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
